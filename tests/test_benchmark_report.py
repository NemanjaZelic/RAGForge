import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path


def module():
    path = Path(__file__).resolve().parents[1] / "scripts/save_benchmark_report.py"
    spec = importlib.util.spec_from_file_location("benchmark_report", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def command(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def test_result_commit_keeps_checkout_and_user_index_unchanged(tmp_path):
    report = module()
    command(tmp_path, "init")
    command(tmp_path, "config", "user.name", "Synthetic test")
    command(tmp_path, "config", "user.email", "synthetic@example.invalid")
    (tmp_path / "base.txt").write_text("base", encoding="utf-8")
    command(tmp_path, "add", "base.txt")
    command(tmp_path, "commit", "-m", "base")
    head = command(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "base.txt").write_text("user edits", encoding="utf-8")
    (tmp_path / "user.txt").write_text("user staged work", encoding="utf-8")
    command(tmp_path, "add", "user.txt")
    before = command(tmp_path, "status", "--porcelain")
    first = report.save_commit(
        tmp_path, "results/synthetic", {"completed_steps": 0, "total_steps": 15}
    )
    assert command(tmp_path, "rev-parse", "HEAD") == head
    assert command(tmp_path, "status", "--porcelain") == before
    assert command(tmp_path, "diff-tree", "--no-commit-id", "--name-only", "-r", first) == (
        report.REPORT_PATH
    )
    assert (
        report.save_commit(tmp_path, "results/synthetic", {"completed_steps": 0, "total_steps": 15})
        == first
    )
    second = report.save_commit(
        tmp_path, "results/synthetic", {"completed_steps": 1, "total_steps": 15}
    )
    assert command(tmp_path, "rev-parse", second + "^") == first
    assert command(tmp_path, "status", "--porcelain") == before
    assert not (tmp_path / report.REPORT_PATH).exists()


def test_sanitizer_cannot_export_native_questions_or_unexpected_text(tmp_path):
    report = module()
    recipe = {"source_commit": "a" * 40}
    (tmp_path / "recipe.json").write_text(json.dumps(recipe), encoding="utf-8")
    fingerprint = hashlib.sha256((tmp_path / "recipe.json").read_bytes()).hexdigest()
    status = {"state": "running", "recipe_sha256": fingerprint, "steps": {}}
    (tmp_path / "status.json").write_text(json.dumps(status), encoding="utf-8")
    methods = {
        name: {
            "attempted": 1,
            "mrr_at_10": 0.5,
            "query": "PRIVATE QUESTION",
            "first_query_seconds": "PRIVATE QUESTION",
        }
        for name in ("bm25", "dense", "hybrid")
    }
    aggregate = {
        "recipe_sha256": fingerprint,
        "completed_steps": 0,
        "state": "running",
        "measurements": [
            {
                "corpus": "3gpp-etsi",
                "kind": "evaluate",
                "track": "explicit_version_draft",
                "split": "dev",
                "measurement": {
                    "wall_seconds": "PRIVATE QUESTION",
                    "selected_cases": "PRIVATE QUESTION",
                    "query": "PRIVATE QUESTION",
                    "source_coverage": {"source_documents": 4723, "query": "PRIVATE QUESTION"},
                    "process_memory": {"rss_bytes": 1024, "query": "PRIVATE QUESTION"},
                    "recipe": {"artifact_build_id": "c" * 64},
                    "methods": methods,
                },
            }
        ],
    }
    (tmp_path / "aggregate-summary.json").write_text(json.dumps(aggregate), encoding="utf-8")
    sanitized = report.sanitize(tmp_path)
    assert "PRIVATE QUESTION" not in json.dumps(sanitized)
    row = sanitized["measurements"][0]
    assert row["methods"]["hybrid"]["mrr_at_10"] == 0.5
    assert row["source_coverage"] == {"source_documents": 4723}


def test_progress_backup_uses_only_bounded_checkpoint_counts(tmp_path):
    report = module()
    recipe = {"source_commit": "a" * 40}
    (tmp_path / "recipe.json").write_text(json.dumps(recipe), encoding="utf-8")
    fingerprint = hashlib.sha256((tmp_path / "recipe.json").read_bytes()).hexdigest()
    (tmp_path / "status.json").write_text(
        json.dumps({"state": "running", "steps": {}, "recipe_sha256": fingerprint}),
        encoding="utf-8",
    )
    job = tmp_path / "kernel-6.18/build-job"
    job.mkdir(parents=True)
    (job / "dense-progress.json").write_text(
        json.dumps({"next_row": 70000, "count": 573041, "private_question": "MUST NOT EXPORT"}),
        encoding="utf-8",
    )
    sanitized = report.sanitize(tmp_path)
    assert sanitized["embedding_progress"]["kernel-6.18"]["completed_rows_lower_bound"] == 65536
    assert "MUST NOT EXPORT" not in json.dumps(sanitized)
