"""Offline, frozen-runtime raw/reranked comparison. Detailed evidence stays local."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def checksum(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while part := stream.read(1024**2):
            value.update(part)
    return value.hexdigest()


def child(task):
    import sitecustomize

    from ragforge.evaluation.runner import evaluate_bundle

    assert sitecustomize.RAGFORGE_QUALITY_OFFLINE
    result = evaluate_bundle(
        Path(task["artifact"]),
        Path(task["cases"]),
        Path(task["source"]),
        Path(task["output"]),
        split=task["split"],
        methods=task["methods"],
        answer_evidence_file=Path(task["answers"]),
        rerank=task["rerank"],
        threads=2,
        allow_draft=True,
        top_k=10,
        max_output_chars=16000,
        resume=Path(task["output"]).exists(),
        progress=lambda event: print(json.dumps(event), flush=True),
    )
    if any(row["errors"] for row in result["methods"].values()):
        raise RuntimeError("quality comparison recorded retrieval errors")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--answer-evidence", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--method", action="append", choices=["bm25", "dense", "hybrid"])
    parser.add_argument("--split", choices=["dev", "tuning"], default="dev")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--child", type=Path)
    args = parser.parse_args()
    if args.child:
        child(json.loads(args.child.read_text(encoding="utf-8")))
        return
    from ragforge.core.source import is_link
    from ragforge.jobs.build import atomic_json
    from ragforge.jobs.ingest import job_lock

    required = [args.artifact, args.cases, args.answer_evidence, args.source_root, args.output]
    if any(value is None for value in required):
        raise ValueError("all input/output paths required")
    output = args.output.absolute()
    if output.exists() and not args.resume:
        raise FileExistsError("comparison output must be new")
    if not output.exists() and args.resume:
        raise ValueError("cannot resume missing comparison")
    output.mkdir(parents=True, exist_ok=True)
    if is_link(output.lstat()):
        raise ValueError("comparison output must not be a link")
    root = Path(__file__).resolve().parents[1]
    with job_lock(output):
        recipe = {
            "artifact_build_id": json.loads((args.artifact / "manifest.json").read_text())[
                "build_id"
            ],
            "cases_sha256": checksum(args.cases),
            "answer_evidence_sha256": checksum(args.answer_evidence),
            "split": args.split,
            "methods": args.method or ["bm25"],
            "top_k": 10,
            "max_output_chars": 16000,
            "threads": 2,
            "dependencies": {
                name: importlib.metadata.version(name)
                for name in ["pydantic", "numpy", "onnxruntime", "tokenizers", "usearch"]
            },
        }
        recipe_file = output / "recipe.json"
        runtime = output / "runtime"
        driver = output / "driver.py"
        if args.resume:
            previous = json.loads(recipe_file.read_text(encoding="utf-8"))
            if any(previous[k] != v for k, v in recipe.items()):
                raise ValueError("comparison recipe changed")
            for name, digest in previous["runtime_sha256"].items():
                if checksum(output / name) != digest:
                    raise ValueError("frozen quality runtime changed")
            recipe = previous
        else:
            runtime.mkdir()
            shutil.copytree(
                root / "src/ragforge",
                runtime / "ragforge",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            shutil.copyfile(__file__, driver)
            guard = output / "offline-guard"
            guard.mkdir()
            (guard / "sitecustomize.py").write_text(
                "import socket\nRAGFORGE_QUALITY_OFFLINE=True\n"
                "def denied(*a,**k):raise RuntimeError('network forbidden in quality comparison')\n"
                "class Blocked(socket.socket):\n def __init__(self,*a,**k):denied()\n"
                "socket.socket=Blocked\nsocket.create_connection=denied\n"
                "socket.getaddrinfo=denied\nsocket.gethostbyname=denied\n",
                encoding="utf-8",
            )
            recipe["runtime_sha256"] = {
                p.relative_to(output).as_posix(): checksum(p)
                for p in sorted([*runtime.rglob("*.py"), driver, guard / "sitecustomize.py"])
            }
            atomic_json(recipe_file, recipe)
        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join([str(output / "offline-guard"), str(runtime)]),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "TOKENIZERS_PARALLELISM": "false",
        }
        state = {"state": "running", "steps": {}}
        safe = {
            "scope": "development diagnostic; draft labels; no generated answer accuracy",
            "recipe": recipe,
            "stages": {},
            "quality_gate": "not_approved_draft_labels",
        }
        for mode in ["raw", "reranked"]:
            destination = output / mode
            task = {
                "artifact": str(args.artifact.absolute()),
                "cases": str(args.cases.absolute()),
                "answers": str(args.answer_evidence.absolute()),
                "source": str(args.source_root.absolute()),
                "output": str(destination),
                "rerank": mode == "reranked",
                "split": args.split,
                "methods": recipe["methods"],
            }
            task_file = output / (mode + "-task.json")
            atomic_json(task_file, task)
            state["current_step"] = mode
            state["steps"][mode] = "running"
            atomic_json(output / "status.json", state)
            with (output / (mode + ".log")).open("ab") as log:
                result = subprocess.run(
                    [sys.executable, str(driver), "--child", str(task_file)],
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            if result.returncode:
                state["state"] = "failed"
                state["steps"][mode] = "failed"
                atomic_json(output / "status.json", state)
                raise RuntimeError("quality stage failed; inspect local " + mode + ".log")
            summary = json.loads((destination / "summary.json").read_text(encoding="utf-8"))
            safe["stages"][mode] = {
                key: summary[key] for key in ["selected_cases", "methods", "source_coverage"]
            }
            safe["stages"][mode]["summary_sha256"] = checksum(destination / "summary.json")
            state["steps"][mode] = "complete"
            atomic_json(output / "status.json", state)
            atomic_json(output / "safe-summary.json", safe)
            print(
                json.dumps({"stage": mode, "state": "complete", "methods": summary["methods"]}),
                flush=True,
            )
        state["state"] = "complete"
        atomic_json(output / "status.json", state)


if __name__ == "__main__":
    main()
