"""Save numerical benchmark progress on a private results branch, without touching checkout.

Network access is confined to this explicit maintenance tool. The frozen build
and retrieval workers never import it. No native questions or case records upload.
"""

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = "docs/benchmarks/scale-runtime-v1.json"
CORPORA = {"kernel-6.18", "ietf-rfcs", "3gpp-etsi"}
TRACKS = {
    "supplementary_evidence_draft",
    "native_source_alignment_diagnostic",
    "explicit_version_draft",
}
METRICS = {
    "attempted",
    "errors",
    "positive_cases",
    "document_recall_at_5",
    "mrr_at_10",
    "evidence_group_coverage",
    "all_required_groups_covered",
    "collection_negative_cases",
    "collection_negatives_with_results",
    "context_negatives_not_global_scored",
    "seconds_p50",
    "seconds_p95",
    "first_query_seconds",
    "unmapped_reference_chunks",
    "ambiguous_reference_chunks",
}


def numbers(values, allowed=None):
    return {
        key: value
        for key, value in values.items()
        if (allowed is None or key in allowed)
        and (value is None or type(value) in {bool, int, float} and math.isfinite(value))
    }


def digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("invalid measurement digest")
    return value


def sanitize(run):
    recipe = json.loads((run / "recipe.json").read_text(encoding="utf-8"))
    status = json.loads((run / "status.json").read_text(encoding="utf-8"))
    if status["state"] not in {"running", "failed_resumable", "complete_diagnostic_draft_labels"}:
        raise ValueError("unknown benchmark state")
    if hashlib.sha256((run / "recipe.json").read_bytes()).hexdigest() != status["recipe_sha256"]:
        raise ValueError("benchmark recipe checksum mismatch")
    source = recipe["source_commit"]
    if not re.fullmatch(r"[0-9a-f]{40}", source):
        raise ValueError("invalid source commit")
    result = {
        "state": status["state"],
        "quality_gate": "not_approved_draft_labels",
        "source_commit": source,
        "recipe_sha256": digest(status["recipe_sha256"]),
        "completed_steps": sum(s["state"] == "complete" for s in status["steps"].values()),
        "total_steps": status.get("total_steps", 15),
        "measurements": [],
        "timing_scope": "successful invocation; interrupted attempts excluded",
        "latency_scope": "wall time, first call includes lazy setup; OS caches not cleared",
    }
    if type(result["total_steps"]) is not int or not 1 <= result["total_steps"] <= 100:
        raise ValueError("invalid scheduled stage count")
    if "schedule_sha256" in status:
        result["schedule_sha256"] = digest(status["schedule_sha256"])
    result["embedding_progress"] = {}
    result["progress_granularity_rows"] = 65536
    for corpus in sorted(CORPORA):
        checkpoint = run / corpus / "build-job/dense-progress.json"
        if not checkpoint.exists():
            continue
        progress = json.loads(checkpoint.read_text(encoding="utf-8"))
        done, total = progress["next_row"], progress["count"]
        if type(done) is not int or type(total) is not int or not 0 <= done <= total <= 8_000_000:
            raise ValueError("invalid checkpointed embedding row count")
        result["embedding_progress"][corpus] = {
            "completed_rows_lower_bound": done if done == total else done // 65536 * 65536,
            "total_rows": total,
        }
    path = run / "aggregate-summary.json"
    if not path.exists():
        return result
    aggregate = json.loads(path.read_text(encoding="utf-8"))
    if digest(aggregate["recipe_sha256"]) != result["recipe_sha256"]:
        raise ValueError("aggregate does not belong to this benchmark recipe")
    if (
        aggregate["completed_steps"] != result["completed_steps"]
        or aggregate["state"] != status["state"]
    ):
        raise RuntimeError("benchmark status and aggregate update are not yet synchronized")
    for original in aggregate["measurements"]:
        corpus, track, split = original["corpus"], original["track"], original["split"]
        kind = original["kind"]
        if corpus not in CORPORA or kind not in {"build", "evaluate"}:
            raise ValueError("unknown measurement scope")
        if kind == "evaluate" and (track not in TRACKS or split not in {"dev", "tuning", "test"}):
            raise ValueError("unknown evaluation track/split")
        report = original["measurement"]
        row = {
            "corpus": corpus,
            "kind": kind,
            "source_coverage": numbers(
                report["source_coverage"],
                {
                    "source_documents",
                    "indexed_documents",
                    "failed_documents_retained",
                    "other_zero_chunk_documents",
                    "reported_pdf_pages",
                    "pdf_no_text_pages",
                    "pdf_error_pages",
                    "documents_with_warnings",
                    "all_sources_have_searchable_text",
                },
            ),
            "process_memory": numbers(
                report["process_memory"],
                {
                    "rss_bytes",
                    "peak_rss_bytes",
                    "private_committed_bytes",
                    "peak_private_committed_bytes",
                },
            ),
        }
        row.update(numbers(report, {"wall_seconds", "bundle_constructor_seconds"}))
        if kind == "build":
            row["build_id"] = digest(report["build_id"])
        else:
            row.update(
                track=track,
                split=split,
                selected_cases=numbers(report, {"selected_cases"}).get("selected_cases"),
                build_id=digest(report["recipe"]["artifact_build_id"]),
                methods={
                    method: numbers(report["methods"][method], METRICS)
                    for method in ("bm25", "dense", "hybrid")
                },
            )
        result["measurements"].append(row)
    return result


def sanitize_quality(run):
    recipe = json.loads((run / "recipe.json").read_text(encoding="utf-8"))
    status = json.loads((run / "status.json").read_text(encoding="utf-8"))
    if status["state"] not in {"running", "failed", "complete"}:
        raise ValueError("unknown quality comparison state")
    if recipe["split"] not in {"dev", "tuning"} or not set(recipe["methods"]) <= {
        "bm25",
        "dense",
        "hybrid",
    }:
        raise ValueError("unknown quality comparison scope")
    if recipe["top_k"] != 10 or recipe["max_output_chars"] != 16000:
        raise ValueError("unexpected quality comparison output budget")
    result = {
        "state": status["state"],
        "quality_gate": "not_approved_draft_labels",
        "scope": "retrieval support diagnostic; not generated-answer accuracy",
        "completed_steps": sum(v == "complete" for v in status["steps"].values()),
        "total_steps": 2,
        "split": recipe["split"],
        "artifact_build_id": digest(recipe["artifact_build_id"]),
        "cases_sha256": digest(recipe["cases_sha256"]),
        "answer_evidence_sha256": digest(recipe["answer_evidence_sha256"]),
        "recipe_sha256": hashlib.sha256((run / "recipe.json").read_bytes()).hexdigest(),
        "runtime_inventory_sha256": hashlib.sha256(
            json.dumps(recipe["runtime_sha256"], sort_keys=True).encode()
        ).hexdigest(),
        "top_k": 10,
        "max_output_chars": 16000,
        "stages": {},
        "target_good": 0.95,
        "target_excellent": 0.99,
    }
    for mode in ("raw", "reranked"):
        if status["steps"].get(mode) != "complete":
            continue
        summary = json.loads((run / mode / "summary.json").read_text(encoding="utf-8"))
        measured = summary["recipe"]
        if any(
            measured[key] != recipe[key]
            for key in [
                "artifact_build_id",
                "cases_sha256",
                "answer_evidence_sha256",
                "split",
                "top_k",
                "max_output_chars",
                "methods",
            ]
        ) or measured["rerank"] != (mode == "reranked"):
            raise ValueError("quality summary does not match the frozen comparison")
        result["stages"][mode] = {
            "selected_cases": numbers(summary, {"selected_cases"})["selected_cases"],
            "methods": {
                method: numbers(
                    summary["methods"][method],
                    METRICS
                    | {
                        "answer_evidence_annotated_cases",
                        "answer_evidence_support_at_k",
                        "answer_fact_coverage",
                    },
                )
                for method in recipe["methods"]
            },
            "source_coverage": numbers(
                summary["source_coverage"],
                {
                    "source_documents",
                    "indexed_documents",
                    "failed_documents_retained",
                    "other_zero_chunk_documents",
                    "reported_pdf_pages",
                    "pdf_no_text_pages",
                    "pdf_error_pages",
                    "documents_with_warnings",
                    "all_sources_have_searchable_text",
                },
            ),
        }
    return result


def git(project, *args, data=None, env=None):
    result = subprocess.run(
        ["git", *args],
        cwd=project,
        input=data,
        capture_output=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never", **(env or {})},
        timeout=90,
    )
    if result.returncode:
        raise RuntimeError("benchmark git operation failed: " + args[0])
    return result.stdout.decode().strip()


def save_commit(project, branch, report, *, report_path=None):
    report_path = report_path or REPORT_PATH
    if not re.fullmatch(r"results/[a-z0-9][a-z0-9-]{0,63}", branch):
        raise ValueError("benchmark results branch must use results/lowercase-name")
    ref = "refs/heads/" + branch
    existing = subprocess.run(
        ["git", "show-ref", "--verify", "--hash", ref],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=30,
    )
    parent = (
        existing.stdout.strip() if existing.returncode == 0 else git(project, "rev-parse", "HEAD")
    )
    payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    blob = git(project, "hash-object", "-w", "--stdin", data=payload)
    old = subprocess.run(
        ["git", "rev-parse", parent + ":" + report_path],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if old.returncode == 0 and old.stdout.strip() == blob:
        return parent
    cache = project / ".cache"
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="benchmark-git-", dir=cache) as temporary:
        env = {"GIT_INDEX_FILE": str(Path(temporary) / "index")}
        git(project, "read-tree", parent, env=env)
        git(project, "update-index", "--add", "--cacheinfo", "100644", blob, report_path, env=env)
        tree = git(project, "write-tree", env=env)
        message = (
            f"Record scale diagnostic progress ({report['completed_steps']}/"
            f"{report['total_steps']} stages)\n"
        )
        commit = git(project, "commit-tree", tree, "-p", parent, data=message.encode())
        expected = parent if existing.returncode == 0 else "0" * 40
        git(project, "update-ref", ref, commit, expected)
        return commit


def publish(project, branch):
    # This tool is explicitly online, unlike the product/evaluator.
    import github_sync

    if git(project, "remote", "get-url", "origin") != (
        "https://github.com/NemanjaZelic/RAGForge.git"
    ):
        raise ValueError("unexpected benchmark repository remote")
    repository = github_sync.api(github_sync.credential(), "/repos/NemanjaZelic/RAGForge")
    if repository.get("private") is not True or repository.get("visibility") != "private":
        raise RuntimeError("refusing benchmark upload because repository is not private")
    git(project, "push", "origin", branch)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--branch", default="results/scale-v1")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument(
        "--quality", action="store_true", help="Whitelisted answer-fact comparison reports."
    )
    args = parser.parse_args()
    failures = 0
    previous = None
    while True:
        try:
            report = sanitize_quality(args.run) if args.quality else sanitize(args.run)
            commit = save_commit(
                ROOT,
                args.branch,
                report,
                report_path="docs/benchmarks/quality-runtime-v1.json" if args.quality else None,
            )
            if commit != previous:
                publish(ROOT, args.branch)
                previous = commit
                print(
                    json.dumps(
                        {
                            "saved_commit": commit,
                            "state": report["state"],
                            "completed_steps": report["completed_steps"],
                        }
                    ),
                    flush=True,
                )
            failures = 0
            if not args.watch or report["state"] != "running":
                return
        except (ValueError, OSError, RuntimeError, subprocess.SubprocessError):
            failures += 1
            print(json.dumps({"save_failed": True, "attempt": failures}), flush=True)
            if failures >= 3 or not args.watch:
                raise
        time.sleep(60)


if __name__ == "__main__":
    main()
