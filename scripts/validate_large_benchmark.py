"""Offline audit of prepared large benchmark cases, without executing retrieval."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def read_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def validate(root: Path) -> dict[str, Any]:
    summary = json.loads((root / "prepared-qa/summary.json").read_text(encoding="utf-8"))
    cases = []
    for split in ("dev", "tuning", "test"):
        rows = read_rows(root / "prepared-qa" / (split + ".jsonl"))
        if any(r["split"] != split for r in rows):
            raise ValueError("Wrong split file")
        cases.extend(rows)
    if len(cases) != 4763 or len({r["case_id"] for r in cases}) != len(cases):
        raise ValueError("Incomplete or duplicate native benchmark questions")
    if Counter(r["track"] for r in cases) != {
        "native_context_qa": 4485,
        "native_tabular_qa_draft": 278,
    }:
        raise ValueError("External benchmark track counts changed")
    contexts = {r["context_id"]: r["text"] for r in read_rows(root / "prepared-qa/contexts.jsonl")}
    family_splits: dict[str, set[str]] = defaultdict(set)
    context_splits: dict[str, set[str]] = defaultdict(set)
    quarantined = []
    for case in cases:
        if case["product_execution"] != "not_run":
            raise ValueError("Preparation cannot claim product execution")
        if case["full_corpus_retrieval_eligible"]:
            raise ValueError("Unmapped native paragraph QA cannot be promoted to full-corpus gold")
        if case["answerability_scope"] != "provided_context_only":
            raise ValueError("Native unanswerability scope changed")
        context = contexts[case["context_id"]]
        family_splits[case["source_family"]].add(case["split"])
        context_splits[case["context_id"]].add(case["split"])
        if case["native_annotation_check"] == "quarantined_span_mismatch":
            quarantined.append(case["case_id"])
        elif case["track"] == "native_context_qa" and not case["native_is_impossible"]:
            if not case["answers"]:
                raise ValueError("Answerable question without labels")
            for answer in case["answers"]:
                if context[answer["answer_start"] : answer["answer_end"]] != answer["text"]:
                    raise ValueError("Native answer span mismatch was not quarantined")
    if any(len(s) != 1 for s in family_splits.values()):
        raise ValueError("Source-family leakage between splits")
    if any(len(s) != 1 for s in context_splits.values()):
        raise ValueError("Duplicate-context leakage between splits")
    if sorted(quarantined) != sorted(summary["quarantined_extractive_cases"]):
        raise ValueError("Quarantine summary mismatch")
    version_cases = read_rows(root / "prepared-qa/version-scoped.jsonl")
    originals = {r["case_id"]: r for r in cases}
    if len(version_cases) != 42:
        raise ValueError("Expected 42 explicit-version draft cases")
    for row in version_cases:
        original = originals[row["upstream_case_id"]]
        if row["split"] != original["split"] or row["split_group"] != original["split_group"]:
            raise ValueError("Version-prefixed case leaked outside its source group")
        if row["strict_scoring_eligible"] or not row["candidate_evidence"]:
            raise ValueError("Version case lacks evidence or has been silently promoted")
    tspec = json.loads(
        (root / "metadata/tspec-markdown-inventory.json").read_text(encoding="utf-8")
    )
    if len(tspec["files"]) != 15420 or sum(r["size"] for r in tspec["files"]) != 4727725277:
        raise ValueError("Pinned full TSpec inventory changed")
    acquisition_path = root / "3gpp-etsi/acquisition-summary.json"
    acquired = (
        json.loads(acquisition_path.read_text()).get("state")
        == "bytes_acquired_text_not_yet_verified"
        if acquisition_path.exists()
        else False
    )
    return {
        "cases": len(cases),
        "version_scope_draft_cases": len(version_cases),
        "quarantined_cases": len(quarantined),
        "source_families": len(family_splits),
        "tspec_cataloged_markdown_files": len(tspec["files"]),
        "tspec_cataloged_markdown_bytes": tspec["markdown_size_bytes"],
        "large_corpus_downloaded": acquired,
        "full_corpus_retrieval_ready": False,
        "product_execution": "not_run",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.root), indent=2))


if __name__ == "__main__":
    main()
