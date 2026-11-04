"""One-shot supervisor for the project's existing frozen local benchmark runs."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from ragforge.jobs.build import atomic_json
from ragforge.jobs.ingest import job_lock

ROOT = Path(__file__).resolve().parents[1]


def checked_file(root: Path, relative: str) -> Path:
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("frozen runtime file must stay inside its run directory")
    return path


def verify_frozen(run: Path, config: dict, key: str) -> None:
    records = config.get(key)
    if not isinstance(records, dict) or not records:
        raise ValueError("missing frozen runtime inventory")
    for relative, digest in records.items():
        if hashlib.sha256(checked_file(run, relative).read_bytes()).hexdigest() != digest:
            raise ValueError("frozen benchmark runtime changed")


def make_plan(root: Path, jobs: str, publish_private: bool) -> list[dict]:
    root = root.resolve(strict=True)
    python = root / ".venv/Scripts/python.exe"
    if not python.is_file():
        raise ValueError("project Windows virtual environment is missing")
    data = (root / "data/benchmarks/scale-v1/runs").resolve(strict=True)
    if not data.is_relative_to(root):
        raise ValueError("benchmark directory must stay inside the project")
    plans = []
    if jobs in {"scale", "both"}:
        run = (data / "execution-v1").resolve(strict=True)
        if not run.is_relative_to(data):
            raise ValueError("benchmark run must stay inside the project")
        recipe = json.loads((run / "recipe.json").read_text(encoding="utf-8"))
        verify_frozen(run, recipe, "runtime_sha256")
        command = [str(python), str(root / "scripts/run_scale_benchmark.py")]
        for name in ["root", "model", "cases", "pdf_cache", "budget_root"]:
            path = Path(recipe[name]).resolve(strict=True)
            if not path.is_relative_to(root):
                raise ValueError("local benchmark input must stay inside the project")
            command.extend(["--" + name.replace("_", "-"), str(path)])
        command.extend(["--output", str(run), "--resume"])
        command.extend(["--reserve-free-bytes", str(recipe.get("reserve_free_bytes", 15000000000))])
        plans.append({"name": "scale", "run": str(run), "command": command})
        if publish_private:
            plans[-1]["publisher"] = [
                str(python),
                str(root / "scripts/save_benchmark_report.py"),
                str(run),
                "--watch",
                "--branch",
                "results/scale-v1",
            ]
    if jobs in {"rfc-rebuild", "both"}:
        run = (data / "quality-v1/full-rfc-rebuild-v1").resolve(strict=True)
        if not run.is_relative_to(data):
            raise ValueError("benchmark run must stay inside the project")
        config = run / "configuration.json"
        recipe = json.loads(config.read_text(encoding="utf-8"))
        verify_frozen(run, recipe, "frozen_sha256")
        plans.append(
            {
                "name": "rfc-rebuild",
                "run": str(run),
                "command": [
                    str(python),
                    str(root / "scripts/queue_quality_followup.py"),
                    "--child",
                    str(config),
                ],
                "publication": "unchanged frozen configuration",
            }
        )
    if not plans:
        raise ValueError("unknown local benchmark selection")
    return plans


def supervise(root: Path, plans: list[dict]) -> None:
    from keep_benchmark_awake import WindowsRequest

    state = root / ".cache/background-benchmarks-v1"
    state.mkdir(parents=True, exist_ok=True)
    if not state.resolve().is_relative_to(root.resolve()):
        raise ValueError("background state must stay inside the project")
    with job_lock(state):
        processes = []
        publishers = []
        logs = []
        request = WindowsRequest(os.getpid())
        try:
            for plan in plans:
                log = (state / (plan["name"] + ".log")).open("ab")
                logs.append(log)
                options = {
                    "cwd": root,
                    "stdin": subprocess.DEVNULL,
                    "stdout": log,
                    "stderr": subprocess.STDOUT,
                    "close_fds": True,
                    "creationflags": subprocess.CREATE_NO_WINDOW,
                }
                processes.append((plan["name"], subprocess.Popen(plan["command"], **options)))
                if "publisher" in plan:
                    publishers.append(subprocess.Popen(plan["publisher"], **options))
            request.acquire()
            while True:
                running = any(process.poll() is None for _, process in processes)
                atomic_json(
                    state / "status.json",
                    {
                        "state": "running"
                        if running
                        else ("failed" if any(p.poll() != 0 for _, p in processes) else "complete"),
                        "unix_time": time.time(),
                        "jobs": [
                            {"name": name, "pid": process.pid, "exit_code": process.poll()}
                            for name, process in processes
                        ],
                        "scope": "one-shot local processes; original frozen recipes and budgets",
                    },
                )
                if not running:
                    break
                time.sleep(20)
            failures = [name for name, process in processes if process.returncode != 0]
            for publisher in publishers:
                try:
                    publisher.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    publisher.terminate()
                    publisher.wait(timeout=10)
            if failures:
                raise RuntimeError("Benchmark failed; inspect local logs: " + ", ".join(failures))
        finally:
            request.restore()
            for process in [p for _, p in processes] + publishers:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=30)
            for log in logs:
                log.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", choices=["scale", "rfc-rebuild", "both"], default="both")
    parser.add_argument("--publish-private", action="store_true")
    parser.add_argument(
        "--check", action="store_true", help="Validate and print the plan; start nothing."
    )
    args = parser.parse_args()
    plans = make_plan(ROOT, args.jobs, args.publish_private)
    if args.check:
        print(json.dumps({"jobs": plans, "starts_processes": False}))
        return
    if sys.platform != "win32":
        raise ValueError("use the foreground benchmark commands on this platform")
    supervise(ROOT, plans)


if __name__ == "__main__":
    main()
