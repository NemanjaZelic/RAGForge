"""Large external data checks are opt-in; these never import the product."""

import json
import os
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXTERNAL = ROOT / "data/benchmarks/scale-v1"
RUN_EXTERNAL = os.environ.get("RAGFORGE_TEST_EXTERNAL_DATA") == "1"


@pytest.mark.skipif(
    not RUN_EXTERNAL,
    reason="External benchmark data check is opt-in: RAGFORGE_TEST_EXTERNAL_DATA=1; no downloads",
)
def test_large_native_benchmark_has_no_label_or_split_drift() -> None:
    if not EXTERNAL.exists():
        pytest.fail("External benchmark input is missing; prepare it separately")
    validator = runpy.run_path(str(ROOT / "scripts/validate_large_benchmark.py"))
    report = validator["validate"](EXTERNAL)
    assert report["cases"] == 4763
    assert report["tspec_cataloged_markdown_files"] == 15420
    assert report["full_corpus_retrieval_ready"] is False


def test_benchmark_policy_does_not_accept_smoke_as_scale_evidence() -> None:
    policy = json.loads(
        (ROOT / "tests/fixtures/benchmarks/scale-v1/policy.json").read_text(encoding="utf-8")
    )
    assert policy["smoke_dataset_is_release_quality_evidence"] is False
    assert (
        policy["production_dataset_policy"] == "complete_frozen_collection_no_cherry_picked_guides"
    )
    assert policy["native_context_negative_is_global_negative"] is False
    assert policy["required_tracks"] == [
        "ingestion",
        "retrieval_evidence",
        "version_scope",
        "resources",
    ]
    assert policy["product_execution"] == "not_run"


def test_large_source_snapshot_covers_complete_catalogs() -> None:
    import hashlib

    path = ROOT / "tests/fixtures/benchmarks/scale-v1/corpus-snapshots.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    corpora = {row["corpus_id"]: row for row in manifest["corpora"]}
    assert {key: row["file_count"] for key, row in corpora.items()} == {
        "3gpp-etsi": 4723,
        "kernel-6.18": 3857,
        "ietf-rfcs": 9854,
    }
    assert manifest["input_file_count"] == 18434
    for corpus in corpora.values():
        rows = corpus["files"]
        assert len({r["path"] for r in rows}) == len(rows) == corpus["file_count"]
        assert sum(r["size_bytes"] for r in rows) == corpus["input_size_bytes"]
        canonical = json.dumps(
            [{k: row[k] for k in ("path", "size_bytes", "sha256")} for row in rows],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        assert hashlib.sha256(canonical).hexdigest() == corpus["snapshot_id"]
        assert corpus["retrieval_run"] is False


def test_supplementary_cases_have_complete_evidence_metadata() -> None:
    validator = runpy.run_path(str(ROOT / "scripts/validate_large_drafts.py"))
    report = validator["validate"](ROOT / "tests/fixtures/benchmarks/scale-v1")
    assert report["draft_cases"] == 240
    assert report["multi_document_cases"] == 40
    assert report["source_documents"] == 100
    assert report["strict_scoring_eligible"] == 0


def test_storage_policy_limits_all_test_assets_together() -> None:
    policy = json.loads(
        (ROOT / "tests/fixtures/benchmarks/scale-v1/policy.json").read_text(encoding="utf-8")
    )
    assert policy["storage_budget_bytes"] == 65_000_000_000
    assert policy["current_storage_bytes"] < policy["acquisition_budget_bytes"]
    assert {"indexes", "benchmark_models", "build_staging"} <= set(policy["storage_budget_scope"])
