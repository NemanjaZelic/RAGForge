"""Run the complete frozen scale benchmark offline with resumable real-engine steps.

Detailed QA and outputs stay under ignored data. This tool never deploys or tunes
on scores. Run status/report JSON is updated after each completed stage.
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def checksum(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024**2):
            result.update(block)
    return result.hexdigest()


def child(task):
    # Only this frozen offline child imports the product engine.
    import sitecustomize

    from ragforge.core.resources import process_memory
    from ragforge.jobs.build import atomic_json

    if not getattr(sitecustomize, "RAGFORGE_BENCHMARK_OFFLINE", False):
        raise RuntimeError("offline guard was not loaded")
    started = time.monotonic()
    if task["kind"] == "build":
        from ragforge.artifacts.builder import build_bundle
        from ragforge.artifacts.diagnostics import ingestion_diagnostics
        from ragforge.core.chunk import ChunkConfig
        from ragforge.core.sqlite import SQLiteEngine
        from ragforge.jobs.budget import StorageBudget

        job = Path(task["job"])
        manifest = build_bundle(
            Path(task["source"]),
            Path(task["artifact"]),
            collection_id=task["collection"],
            title=task["corpus"],
            model_directory=Path(task["model"]),
            ingest_job=Path(task["ingest_job"]),
            work_directory=job,
            resume=job.exists(),
            dense_backend="ann",
            threads=4,
            chunk_config=ChunkConfig(chunk_size_chars=350, overlap_chars=50),
            max_index_chunks=8_000_000,
            max_index_text_chars=4_000_000_000,
            allow_incomplete=True,
            allow_failed_documents=task["corpus"] == "3gpp-etsi",
            storage=StorageBudget(
                Path(task["budget_root"]),
                limit_bytes=60_000_000_000,
                reserve_free_bytes=task["reserve_free_bytes"],
            ),
            progress=lambda event: print(json.dumps(event), flush=True),
        )
        report = {
            "build_id": manifest.build_id,
            "source_coverage": ingestion_diagnostics(
                SQLiteEngine(Path(task["artifact"]) / manifest.collections[0].database_path)
            ),
        }
    elif task["kind"] == "evaluate":
        from ragforge.evaluation.runner import evaluate_bundle

        destination = Path(task["evaluation_output"])
        report = evaluate_bundle(
            Path(task["artifact"]),
            Path(task["cases"]),
            Path(task["source"]),
            destination,
            split=task["split"],
            track=task["track"],
            methods=["bm25", "dense", "hybrid"],
            top_k=10,
            max_output_chars=16000,
            allow_draft=True,
            pdf_reference_cache=Path(task["pdf_cache"]) if task["pdf_cache"] else None,
            resume=destination.exists(),
            progress=lambda event: print(json.dumps(event), flush=True),
        )
        if any(row["errors"] for row in report["methods"].values()):
            raise RuntimeError("evaluation recorded query errors; inspect local diagnostics")
    else:
        raise ValueError("unknown benchmark task")
    report.update(wall_seconds=time.monotonic() - started, process_memory=process_memory())
    atomic_json(Path(task["report"]), report)


def steps(root, output, model, cases, pdf_cache, budget_root):
    tasks = []
    for corpus, collection in (
        ("kernel-6.18", "kernel-6-18"),
        ("ietf-rfcs", "ietf-rfcs"),
        ("3gpp-etsi", "3gpp-etsi"),
    ):
        work = output / corpus
        common = {
            "corpus": corpus,
            "collection": collection,
            "source": str(root / corpus / "input"),
            "model": str(model),
            "ingest_job": str(root / "runs/ingest-v1" / corpus),
            "job": str(work / "build-job"),
            "artifact": str(work / "bundle"),
            "budget_root": str(budget_root),
            "cases": str(cases / (corpus + ".jsonl")),
            "pdf_cache": str(pdf_cache) if corpus == "3gpp-etsi" else None,
        }
        tasks.append(
            {
                **common,
                "kind": "build",
                "name": corpus + "-build",
                "report": str(work / "build-summary.json"),
            }
        )
        tracks = (
            ["native_source_alignment_diagnostic", "explicit_version_draft"]
            if (corpus == "3gpp-etsi")
            else ["supplementary_evidence_draft"]
        )
        for track in tracks:
            for split in ("dev", "tuning", "test"):
                destination = work / "evaluations" / track / split
                tasks.append(
                    {
                        **common,
                        "kind": "evaluate",
                        "track": track,
                        "split": split,
                        "name": corpus + "-" + track + "-" + split,
                        "evaluation_output": str(destination),
                        "report": str(destination / "measurement.json"),
                    }
                )
    return tasks


def aggregate(output, tasks, state):
    """Only numerical/provenance summaries; never export native QA or per-case records."""
    from ragforge.jobs.build import atomic_json

    completed = []
    for task in tasks:
        if state["steps"].get(task["name"], {}).get("state") != "complete":
            continue
        report = json.loads(Path(task["report"]).read_text(encoding="utf-8"))
        completed.append(
            {
                "corpus": task["corpus"],
                "kind": task["kind"],
                "track": task.get("track"),
                "split": task.get("split"),
                "measurement": report,
            }
        )
    groups = {}
    metrics = (
        "document_recall_at_5",
        "mrr_at_10",
        "evidence_group_coverage",
        "all_required_groups_covered",
    )
    for row in completed:
        if row["kind"] != "evaluate":
            continue
        for method, scores in row["measurement"]["methods"].items():
            key = (row["track"], row["split"], method)
            groups.setdefault(key, []).append(scores)
    macro = []
    for (track, split, method), rows in sorted(groups.items()):
        values = {
            metric: sum(r[metric] for r in rows) / len(rows)
            for metric in metrics
            if all(r[metric] is not None for r in rows)
        }
        macro.append(
            {
                "track": track,
                "split": split,
                "method": method,
                "completed_corpora": len(rows),
                "metrics": values,
            }
        )
    atomic_json(
        output / "aggregate-summary.json",
        {
            "state": state["state"],
            "quality_gate": "not_approved_draft_labels",
            "recipe_sha256": checksum(output / "recipe.json"),
            "total_steps": len(tasks),
            "completed_steps": len(completed),
            "measurements": completed,
            "corpus_macro_by_track_and_split": macro,
            "macro_scope": "equal corpus weight within each track/split; incomplete while running",
            "wall_scope": "successful invocation; previous interrupted attempts excluded",
            "negative_scope": "native context negatives are not global negatives",
        },
    )


def execute(
    root,
    output,
    model,
    cases,
    pdf_cache,
    budget_root,
    *,
    resume=False,
    reserve_free_bytes=15_000_000_000,
):
    from ragforge.jobs.build import atomic_json
    from ragforge.jobs.ingest import job_lock

    project = Path(__file__).resolve().parents[1]
    if not output.resolve().is_relative_to(root.resolve() / "runs"):
        raise ValueError("benchmark output must remain in the ignored corpus runs directory")
    if output.exists() and not resume:
        raise FileExistsError("output exists; resume explicitly or choose a new run")
    if resume and not output.exists():
        raise ValueError("cannot resume missing run")
    output.mkdir(parents=True, exist_ok=True)
    with job_lock(output):
        control = output / "recipe.json"
        if control.exists():
            recipe = json.loads(control.read_text(encoding="utf-8"))
            actual = {
                "root": str(root),
                "model": str(model),
                "cases": str(cases),
                "pdf_cache": str(pdf_cache),
                "budget_root": str(budget_root),
                "reserve_free_bytes": reserve_free_bytes,
            }
            if any(
                recipe.get(k, 15_000_000_000 if k == "reserve_free_bytes" else None) != v
                for k, v in actual.items()
            ):
                raise ValueError("resume paths differ from the frozen recipe")
            if any(
                importlib.metadata.version(name) != version
                for name, version in recipe["dependencies"].items()
            ):
                raise ValueError("installed benchmark dependencies changed")
            for relative, digest in recipe["runtime_sha256"].items():
                if checksum(output / relative) != digest:
                    raise ValueError("frozen runtime was modified")
            if any(
                checksum(cases / name) != digest for name, digest in recipe["cases_sha256"].items()
            ):
                raise ValueError("frozen evaluation bank was modified")
        else:
            if resume:
                raise ValueError("run has no committed recipe")
            package = project / "src/ragforge"
            runtime = output / "runtime/ragforge"
            shutil.copytree(package, runtime, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            shutil.copyfile(Path(__file__), output / "driver.py")
            guard = output / "offline-guard"
            guard.mkdir()
            (guard / "sitecustomize.py").write_text(
                "import socket\nRAGFORGE_BENCHMARK_OFFLINE=True\n"
                'def denied(*a,**k):raise RuntimeError("benchmark network disabled")\n'
                "class NoNetwork(socket.socket):\n"
                "    def __init__(self,*a,**k):denied()\n"
                "socket.socket=NoNetwork\nsocket.create_connection=denied\n"
                "socket.getaddrinfo=denied\nsocket.gethostbyname=denied\n",
                encoding="utf-8",
            )
            recipe = {
                "root": str(root),
                "model": str(model),
                "cases": str(cases),
                "pdf_cache": str(pdf_cache),
                "budget_root": str(budget_root),
                "reserve_free_bytes": reserve_free_bytes,
                "source_commit": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=project, text=True
                ).strip(),
                "lock_sha256": checksum(project / "uv.lock"),
                "dependencies": {
                    name: importlib.metadata.version(name)
                    for name in (
                        "ragforge",
                        "pydantic",
                        "numpy",
                        "onnxruntime",
                        "tokenizers",
                        "usearch",
                    )
                },
                "cases_sha256": {
                    name: checksum(cases / name)
                    for name in ("kernel-6.18.jsonl", "ietf-rfcs.jsonl", "3gpp-etsi.jsonl")
                },
                "fixed_parameters": {
                    "chunk_chars": 350,
                    "overlap_chars": 50,
                    "dense_backend": "usearch-sharded-cosine",
                    "threads": 4,
                    "top_k": 10,
                    "max_output_chars": 16000,
                    "candidate_pool": 50,
                    "rrf_k": 60,
                },
                "runtime_sha256": {
                    str(p.relative_to(output)).replace("\\", "/"): checksum(p)
                    for p in [
                        *runtime.rglob("*.py"),
                        output / "driver.py",
                        guard / "sitecustomize.py",
                    ]
                },
            }
            atomic_json(control, recipe)
        temp = output / "tmp"
        temp.mkdir(exist_ok=True)
        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join((str(output / "offline-guard"), str(output / "runtime"))),
            "PYTHONNOUSERSITE": "1",
            "TEMP": str(temp),
            "TMP": str(temp),
            "SQLITE_TMPDIR": str(temp),
            "TOKENIZERS_PARALLELISM": "false",
        }
        state = {"state": "running", "recipe_sha256": checksum(control), "steps": {}}
        if (output / "status.json").exists():
            state = json.loads((output / "status.json").read_text(encoding="utf-8"))
        state["state"] = "running"
        tasks = steps(root, output, model, cases, pdf_cache, budget_root)
        for task in tasks:
            task["reserve_free_bytes"] = reserve_free_bytes
        for task in tasks:
            name = task["name"]
            previous = state["steps"].get(name, {})
            if previous.get("state") == "complete":
                if checksum(Path(task["report"])) != previous["report_sha256"]:
                    raise ValueError("completed measurement checksum mismatch")
                continue
            Path(task["report"]).parent.mkdir(parents=True, exist_ok=True)
            task_file = output / (name + "-task.json")
            atomic_json(task_file, task)
            state["current_step"] = name
            state["steps"][name] = {"state": "running"}
            atomic_json(output / "status.json", state)
            print(json.dumps({"starting": name}), flush=True)
            with (output / (name + ".log")).open("ab") as log:
                process = subprocess.Popen(
                    [sys.executable, str(output / "driver.py"), "--child", str(task_file)],
                    cwd=project,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                state["child_pid"] = process.pid
                atomic_json(output / "status.json", state)
                code = process.wait()
            if code:
                state["state"] = "failed_resumable"
                state["steps"][name] = {"state": "failed", "exit_code": code}
                atomic_json(output / "status.json", state)
                aggregate(output, tasks, state)
                raise RuntimeError("benchmark step failed; inspect " + name + ".log")
            state["steps"][name] = {
                "state": "complete",
                "report_sha256": checksum(Path(task["report"])),
            }
            atomic_json(output / "status.json", state)
            aggregate(output, tasks, state)
        state.update(state="complete_diagnostic_draft_labels", current_step=None, child_pid=None)
        atomic_json(output / "status.json", state)
        aggregate(output, tasks, state)
        print(json.dumps({"state": state["state"], "steps": len(state["steps"])}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--pdf-cache", type=Path)
    parser.add_argument("--budget-root", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--reserve-free-bytes", type=int, default=15_000_000_000)
    parser.add_argument("--child", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        child(json.loads(args.child.read_text(encoding="utf-8")))
    else:
        if any(
            getattr(args, name) is None
            for name in ("root", "output", "model", "cases", "pdf_cache", "budget_root")
        ):
            parser.error("root/output/model/cases/pdf-cache/budget-root are required")
        execute(
            *(
                getattr(args, name).absolute()
                for name in ("root", "output", "model", "cases", "pdf_cache", "budget_root")
            ),
            resume=args.resume,
            reserve_free_bytes=args.reserve_free_bytes,
        )


if __name__ == "__main__":
    main()
