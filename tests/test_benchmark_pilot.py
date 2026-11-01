"""RF-006B fixture invariants. No product imports, downloads or retrieval."""

import copy
import json
import runpy
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "tests" / "fixtures" / "benchmarks" / "pilot-v1"
validator = runpy.run_path(str(ROOT / "scripts" / "validate_benchmark_set.py"))


def test_pilot_labels_and_source_inventory_are_consistent() -> None:
    report = validator["validate"](DATASET)
    assert report["queries"] == 90
    assert report["answerable"] == 72
    assert report["unanswerable"] == 18
    assert report["strict_scoring_eligible"] == 0
    assert report["product_execution"] == "not_run"
    assert report["sources_verified"] is False


@pytest.mark.parametrize("mutation", ["duplicate", "snapshot", "evidence", "promoted_draft"])
def test_corrupt_labels_are_rejected(tmp_path: Path, mutation: str) -> None:
    dataset = tmp_path / "pilot"
    shutil.copytree(DATASET, dataset)
    path = dataset / "gold" / "dev.jsonl"
    rows = validator["read_jsonl"](path)
    positive = next(r for r in rows if r["answerability"] == "answerable")
    if mutation == "duplicate":
        rows[1]["query_id"] = rows[0]["query_id"]
    elif mutation == "snapshot":
        positive["snapshot_id"] = "0" * 64
    elif mutation == "evidence":
        positive["required_evidence_groups"][0]["any_of"] = ["missing-evidence"]
    else:
        positive["review"]["strict_scoring_eligible"] = True
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    with pytest.raises(ValueError):
        validator["validate"](dataset)


def test_paraphrases_cannot_move_to_another_split(tmp_path: Path) -> None:
    dataset = tmp_path / "pilot"
    shutil.copytree(DATASET, dataset)
    dev_path = dataset / "gold" / "dev.jsonl"
    test_path = dataset / "gold" / "test.jsonl"
    dev = validator["read_jsonl"](dev_path)
    test = validator["read_jsonl"](test_path)
    a = next(i for i, row in enumerate(dev) if row["answerability"] == "answerable")
    b = next(
        i
        for i, row in enumerate(test)
        if row["corpus_id"] == dev[a]["corpus_id"] and row["answerability"] == "answerable"
    )
    dev[a], test[b] = copy.deepcopy(test[b]), copy.deepcopy(dev[a])
    dev[a]["split"] = "dev"
    test[b]["split"] = "test"
    for path, rows in ((dev_path, dev), (test_path, test)):
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    with pytest.raises(ValueError, match="leakage"):
        validator["validate"](dataset)


def test_source_inventory_cannot_change_silently(tmp_path: Path) -> None:
    dataset = tmp_path / "pilot"
    shutil.copytree(DATASET, dataset)
    path = dataset / "dataset.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["corpora"][0]["files"][0]["sha256"] = "0" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="snapshot inventory"):
        validator["validate"](dataset)


def test_control_inputs_are_distinct_diagnostics() -> None:
    controls = DATASET / "controls"
    assert (controls / "empty/input/empty.txt").read_bytes() == b""
    assert (controls / "duplicates/input/first.md").read_bytes() == (
        controls / "duplicates/input/second.md"
    ).read_bytes()
    with pytest.raises(UnicodeDecodeError):
        (controls / "malformed/input/bad.txt").read_text(encoding="utf-8")
    text = (controls / "unicode/input/sr.txt").read_text(encoding="utf-8")
    assert "č, ć, š, ž i đ" in text
    assert "Ћирилица" in text
    assert (controls / "long-code/input/long.md").stat().st_size > 16000


def test_control_fixture_changes_require_inventory_update(tmp_path: Path) -> None:
    dataset = tmp_path / "pilot"
    shutil.copytree(DATASET, dataset)
    (dataset / "controls/duplicates/input/first.md").write_bytes(b"changed")
    with pytest.raises(ValueError, match="control fixture drift"):
        validator["validate"](dataset)


def test_unexecuted_scenario_cannot_claim_success(tmp_path: Path) -> None:
    dataset = tmp_path / "pilot"
    shutil.copytree(DATASET, dataset)
    path = dataset / "scenarios.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["scenarios"][0]["status"] = "passed"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="unexecuted scenario claimed success"):
        validator["validate"](dataset)
