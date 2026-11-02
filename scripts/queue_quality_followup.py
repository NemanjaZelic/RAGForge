"""Queue a frozen local quality comparison after a full baseline bundle is published.

No cloud, document upload or parameter tuning. Optional publication invokes only
our whitelisted/private numerical maintenance tool in a separate process.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024**2):
            digest.update(block)
    return digest.hexdigest()


def write(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def prepare(config_file):
    import sitecustomize

    from ragforge.artifacts.enhance import enhance_bundle
    from ragforge.artifacts.verification import verify_bundle
    from ragforge.core.rerank import reranker_spec
    from ragforge.jobs.budget import StorageBudget

    if not getattr(sitecustomize, "RAGFORGE_QUEUE_OFFLINE", False):
        raise RuntimeError("offline preparation guard missing")
    c = json.loads(config_file.read_text(encoding="utf-8"))
    base = verify_bundle(Path(c["baseline"]))
    model = Path(c["reranker"])
    if sha(model / "reranker.json") != c["reranker_descriptor_sha256"]:
        raise ValueError("queued reranker changed")
    spec = reranker_spec(model)
    output = config_file.parent / ("rebuilt-bundle" if c.get("rebuild") else "enhanced-bundle")
    if c.get("rebuild"):
        from ragforge.artifacts.builder import build_bundle
        from ragforge.core.chunk import ChunkConfig

        model = Path(c["model"])
        if sha(model / "model.json") != c["model_descriptor_sha256"]:
            raise ValueError("queued embedding model changed")
        cache = Path(c["ingest_job"]) if c.get("ingest_job") else None
        if cache and sha(cache / "parsed.sqlite") != c["ingest_cache_sha256"]:
            raise ValueError("queued parsing snapshot changed")
        job = config_file.parent / "build-job"
        result = build_bundle(
            Path(c["source"]),
            output,
            collection_id=base.collections[0].collection_id,
            title=base.collections[0].title,
            model_directory=model,
            reranker_directory=Path(c["reranker"]),
            rerank_candidates=100,
            chunk_config=ChunkConfig(strategy="sections", chunk_size_chars=1000, overlap_chars=150),
            token_aware=True,
            ingest_job=cache,
            work_directory=job,
            resume=job.exists(),
            allow_incomplete=True,
            threads=2,
            dense_backend="ann",
            max_index_chunks=8_000_000,
            max_index_text_chars=4_000_000_000,
            storage=StorageBudget(
                Path(c["budget_root"]),
                limit_bytes=60_000_000_000,
                reserve_free_bytes=c.get("reserve_free_bytes", 15_000_000_000),
            ),
            progress=lambda event: print(json.dumps(event), flush=True),
        )
        if result.collections[0].documents != base.collections[0].documents:
            raise ValueError("quality rebuild source inventory differs from frozen baseline")
        return
    result = (
        verify_bundle(output)
        if output.exists()
        else enhance_bundle(
            Path(c["baseline"]),
            output,
            model,
            candidates=100,
            storage=StorageBudget(
                Path(c["budget_root"]),
                limit_bytes=60_000_000_000,
                reserve_free_bytes=c.get("reserve_free_bytes", 15_000_000_000),
            ),
        )
    )
    inventory = {str(r.path): r for r in result.files}
    if base.collections != result.collections or any(
        inventory.get(str(r.path)) != r for r in base.files
    ):
        raise ValueError("queued enhanced bundle does not retain the complete base index")
    config = result.retrieval_configuration
    if (
        config is None
        or config.candidates_per_method != 100
        or (config.reranker.model_id, config.reranker.revision) != (spec.model_id, spec.revision)
    ):
        raise ValueError("queued enhanced bundle configuration changed")


def execute(config_file):
    c = json.loads(config_file.read_text(encoding="utf-8"))
    out = config_file.parent
    for name, digest in c["frozen_sha256"].items():
        if sha(out / name) != digest:
            raise ValueError("frozen follow-up source changed")
    for name in ["cases", "answers"]:
        if sha(Path(c[name])) != c[name + "_sha256"]:
            raise ValueError("follow-up input changed")
    artifact = Path(c["baseline"])
    deadline = c["deadline_unix"]
    state = {"state": "waiting_for_baseline_bundle"}
    write(out / "status.json", state)
    while not (artifact / "manifest.json").exists():
        baseline = json.loads(Path(c["baseline_status"]).read_text(encoding="utf-8"))
        if baseline["state"] not in {"running", "complete_diagnostic_draft_labels"}:
            raise RuntimeError(
                "baseline stopped before artifact publication; repair and resume explicitly"
            )
        if time.time() > deadline:
            raise RuntimeError("follow-up wait budget expired")
        time.sleep(c["poll_seconds"])
    if c.get("after_status"):
        state["state"] = "waiting_for_prior_quality_comparison"
        write(out / "status.json", state)
        while True:
            prerequisite = json.loads(Path(c["after_status"]).read_text(encoding="utf-8"))["state"]
            if prerequisite == "complete_diagnostic_draft_labels":
                break
            if prerequisite.startswith("failed") or time.time() > deadline:
                raise RuntimeError("prior quality comparison failed or wait budget expired")
            time.sleep(c["poll_seconds"])
    # Retrieval/model access runs with a socket/DNS guard; publishing never shares this process.
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(out / "offline-guard"), str(out / "worktree/src")]),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }
    enhanced = out / ("rebuilt-bundle" if c.get("rebuild") else "enhanced-bundle")
    state["state"] = "preparing_verified_quality_bundle"
    write(out / "status.json", state)
    with (out / "prepare.log").open("ab") as log:
        subprocess.run(
            [
                sys.executable,
                str(out / "worktree/scripts/queue_quality_followup.py"),
                "--prepare",
                str(config_file),
            ],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
        )
    comparison = out / "comparison"
    command = [
        sys.executable,
        str(out / "worktree/scripts/run_quality_comparison.py"),
        "--artifact",
        str(enhanced),
        "--cases",
        c["cases"],
        "--answer-evidence",
        c["answers"],
        "--source-root",
        c["source"],
        "--output",
        str(comparison),
    ]
    for method in ["bm25", "dense", "hybrid"]:
        command.extend(["--method", method])
    if comparison.exists():
        command.append("--resume")
    state["state"] = "running_quality_comparison"
    write(out / "status.json", state)
    with (out / "comparison.log").open("ab") as log:
        process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        watcher = None
        while process.poll() is None:
            if c["publish_private"] and watcher is None and (comparison / "status.json").exists():
                watchlog = (out / "publisher.log").open("ab")
                # Publisher runs outside the offline guard, with the real Git worktree.
                watcher = subprocess.Popen(
                    [
                        sys.executable,
                        c["publisher"],
                        str(comparison),
                        "--quality",
                        "--watch",
                        "--branch",
                        c.get("results_branch", "results/quality-full-rfc-v1"),
                    ],
                    env={**os.environ, "PYTHONPATH": ""},
                    stdout=watchlog,
                    stderr=subprocess.STDOUT,
                )
                watchlog.close()
            time.sleep(c["poll_seconds"])
        if process.returncode:
            raise RuntimeError("queued comparison failed; inspect local logs")
        if watcher is not None:
            watcher.wait(timeout=240)
        if c["publish_private"] and (watcher is None or watcher.returncode):
            subprocess.run(
                [
                    sys.executable,
                    c["publisher"],
                    str(comparison),
                    "--quality",
                    "--branch",
                    c.get("results_branch", "results/quality-full-rfc-v1"),
                ],
                env={**os.environ, "PYTHONPATH": ""},
                check=True,
            )
    state["state"] = "complete_diagnostic_draft_labels"
    write(out / "status.json", state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--baseline-status", type=Path)
    parser.add_argument("--reranker", type=Path)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--model", type=Path)
    parser.add_argument("--ingest-job", type=Path)
    parser.add_argument("--results-branch", default="results/quality-full-rfc-v1")
    parser.add_argument("--after-status", type=Path)
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--answers", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--budget-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--wait-hours", type=float, default=24)
    parser.add_argument("--publish-private", action="store_true")
    parser.add_argument("--child", type=Path)
    parser.add_argument("--prepare", type=Path)
    parser.add_argument("--poll-seconds", type=float, default=30)
    parser.add_argument("--reserve-free-bytes", type=int, default=15_000_000_000)
    args = parser.parse_args()
    if args.prepare:
        prepare(args.prepare)
        return
    if args.child:
        try:
            execute(args.child)
        except Exception:
            write(args.child.parent / "status.json", {"state": "failed_resumable"})
            raise
        return
    required = [
        args.baseline,
        args.baseline_status,
        args.reranker,
        args.cases,
        args.answers,
        args.source,
        args.budget_root,
        args.output,
    ]
    if any(value is None for value in required):
        parser.error("all input/output paths are required")
    if (
        not 0 < args.wait_hours <= 168
        or not 0.1 <= args.poll_seconds <= 60
        or args.reserve_free_bytes < 0
    ):
        parser.error("invalid wait/poll budget")
    if args.rebuild and args.model is None:
        parser.error("a rebuilt quality bundle requires --model")
    out = args.output.absolute()
    if not out.resolve().is_relative_to(args.budget_root.resolve()) or any(
        out.resolve().is_relative_to(p.resolve()) or p.resolve().is_relative_to(out.resolve())
        for p in [args.baseline, args.source, args.reranker]
    ):
        parser.error("follow-up output must be separate from inputs and inside budget root")
    out.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    worktree = out / "worktree"
    shutil.copytree(
        root / "src", worktree / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    (worktree / "scripts").mkdir()
    for name in ["queue_quality_followup.py", "run_quality_comparison.py"]:
        shutil.copyfile(root / "scripts" / name, worktree / "scripts" / name)
    guard = out / "offline-guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(
        "import socket\nRAGFORGE_QUEUE_OFFLINE=True\n"
        "def denied(*a,**k):raise RuntimeError('network forbidden in quality preparation')\n"
        "class Blocked(socket.socket):\n def __init__(self,*a,**k):denied()\n"
        "socket.socket=Blocked\nsocket.create_connection=denied\n"
        "socket.getaddrinfo=denied\nsocket.gethostbyname=denied\n",
        encoding="utf-8",
    )
    c = {
        name: str(getattr(args, name).absolute())
        for name in [
            "baseline",
            "baseline_status",
            "reranker",
            "cases",
            "answers",
            "source",
            "budget_root",
        ]
    }
    c.update(
        deadline_unix=time.time() + args.wait_hours * 3600,
        publish_private=args.publish_private,
        poll_seconds=args.poll_seconds,
        rebuild=args.rebuild,
        after_status=str(args.after_status.absolute()) if args.after_status else None,
        results_branch=args.results_branch,
        reserve_free_bytes=args.reserve_free_bytes,
        publisher=str(root / "scripts/save_benchmark_report.py"),
    )
    if args.rebuild:
        c["model"] = str(args.model.absolute())
        c["model_descriptor_sha256"] = sha(args.model / "model.json")
        c["ingest_job"] = str(args.ingest_job.absolute()) if args.ingest_job else None
        c["ingest_cache_sha256"] = (
            sha(args.ingest_job / "parsed.sqlite") if args.ingest_job else None
        )
    c["reranker_descriptor_sha256"] = sha(args.reranker / "reranker.json")
    c["cases_sha256"] = sha(args.cases)
    c["answers_sha256"] = sha(args.answers)
    c["frozen_sha256"] = {
        p.relative_to(out).as_posix(): sha(p)
        for p in sorted([*worktree.rglob("*.py"), guard / "sitecustomize.py"])
    }
    config = out / "configuration.json"
    write(config, c)
    subprocess.run(
        [
            sys.executable,
            str(worktree / "scripts/queue_quality_followup.py"),
            "--child",
            str(config),
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
