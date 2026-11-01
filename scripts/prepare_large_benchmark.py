"""Prepare external telecom benchmark cases; no RAGForge imports or evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


def sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def source_family(source: str) -> str:
    match = re.search(r"3GPP-Specs#(\d{5}(?:-\d+)*)-([0-9a-z]{3})(?:#\d+)?$", source)
    if match:
        return "3gpp:" + match[1]
    # Page suffixes in native titles are not treated as original PDF page numbers.
    return "web:" + source.split("#", 1)[0]


def partition(family: str) -> str:
    bucket = int(sha(("ragforge-scale-v1|" + family).encode())[:8], 16) % 10
    return "dev" if bucket < 6 else "tuning" if bucket < 8 else "test"


def prepare(root: Path) -> dict[str, Any]:
    native_root = root / "external-qa/telequad/raw"
    audit = json.loads((root / "metadata/telequad-audit.json").read_text(encoding="utf-8"))
    for row in audit["files"]:
        body = (native_root / row["path"]).read_bytes()
        if sha(body) != row["sha256"]:
            raise ValueError("External QA source hash changed: " + row["path"])
    extractive = json.loads(
        (native_root / "extractive/v4/TeleQuAD-v4-full.json").read_text(encoding="utf-8")
    )
    tabular = json.loads(
        (native_root / "tabular/v1/TeleQuAD-v1-full-Tabular.json").read_text(encoding="utf-8")
    )
    cases = []
    contexts: dict[str, dict[str, Any]] = {}
    alignment_path = root / "metadata/telequad-source-alignment.json"
    alignment = (
        {r["case_id"]: r for r in json.loads(alignment_path.read_text())["records"]}
        if alignment_path.exists()
        else {}
    )
    snapshot_path = (
        Path(__file__).resolve().parents[1]
        / "tests/fixtures/benchmarks/scale-v1/corpus-snapshots.json"
    )
    source_aliases: dict[str, list[str]] = {}
    if snapshot_path.exists():
        for corpus in json.loads(snapshot_path.read_text())["corpora"]:
            if corpus["corpus_id"] == "3gpp-etsi":
                for source in corpus["files"]:
                    source_aliases.setdefault(source["sha256"], []).append(source["document_id"])
    for doc in extractive["data"]:
        source = doc["source"]
        family = source_family(source)
        for paragraph in doc["paragraphs"]:
            text = paragraph["context"]
            context_id = sha(text.encode())
            contexts[context_id] = {"context_id": context_id, "text": text}
            for query in paragraph["qas"]:
                positive = not query["is_impossible"]
                valid = not positive or all(
                    0 <= a["answer_start"] < a["answer_end"] <= len(text)
                    and text[a["answer_start"] : a["answer_end"]] == a["text"]
                    for a in query["answers"]
                )
                if positive and not query["answers"]:
                    valid = False
                cases.append(
                    {
                        "case_id": "telequad-extractive:" + query["id"],
                        "track": "native_context_qa",
                        "question": query["question"],
                        "source": source,
                        "source_family": family,
                        "split": partition(family),
                        "context_id": context_id,
                        "answers": query["answers"],
                        "native_is_impossible": query["is_impossible"],
                        "answerability_scope": "provided_context_only",
                        "native_annotation_check": (
                            "not_applicable_context_negative"
                            if not positive
                            else "exact"
                            if valid
                            else "quarantined_span_mismatch"
                        ),
                        "full_corpus_retrieval_eligible": False,
                        "full_source_mapping": "pending_exact_version_and_source_span_verification",
                        "product_execution": "not_run",
                    }
                )
                if candidates := alignment.get("telequad-extractive:" + query["id"]):
                    cases[-1]["source_alignment"] = candidates
                    cases[-1]["full_source_mapping"] = candidates["status"]
    for doc in tabular["data"]:
        for query in doc["questions"]:
            text = query["context"]
            context_id = sha(text.encode())
            contexts[context_id] = {"context_id": context_id, "text": text}
            family = "3gpp:" + query["document_name"].split("-", 1)[0]
            cases.append(
                {
                    "case_id": "telequad-tabular:" + query["id"],
                    "track": "native_tabular_qa_draft",
                    "question": query["question"],
                    "expected_answer": query["answer"],
                    "source": query["document_name"],
                    "source_family": family,
                    "split": partition(family),
                    "context_id": context_id,
                    "section_number": query["section_number"],
                    "table_name": query["table_name"],
                    "native_page_start": query["start_page"],
                    "native_page_end": query["end_page"],
                    "page_semantics": "native_DOC_or_DOCX_pagination_not_verified_ETSI_PDF_pages",
                    "native_annotation_check": "upstream_draft_not_independently_validated",
                    "answerability_scope": "provided_context_only",
                    "full_corpus_retrieval_eligible": False,
                    "full_source_mapping": "pending_exact_version_and_source_span_verification",
                    "product_execution": "not_run",
                }
            )
    if len({row["case_id"] for row in cases}) != len(cases):
        raise ValueError("Duplicate native query identity")
    # Exact duplicate contexts must not leak between source-family splits.
    families_by_context: dict[str, set[str]] = {}
    for row in cases:
        families_by_context.setdefault(row["context_id"], set()).add(row["source_family"])
    parent = {row["source_family"]: row["source_family"] for row in cases}

    def find(family: str) -> str:
        while parent[family] != family:
            family = parent[family]
        return family

    for families in families_by_context.values():
        ordered = sorted(families)
        for family in ordered[1:]:
            parent[find(family)] = find(ordered[0])
    for row in cases:
        row["split_group"] = find(row["source_family"])
        row["split"] = partition(row["split_group"])
    version_cases = []
    per_spec: Counter[str] = Counter()
    for row in sorted(cases, key=lambda r: r["case_id"]):
        source = row.get("source_alignment", {})
        code = source.get("spec_code")
        if not code or not source.get("candidate_evidence") or per_spec[code] >= 3:
            continue
        if row["native_annotation_check"] != "exact":
            continue
        per_spec[code] += 1
        kind = "TR" if code in {"21915", "25996"} else "TS"
        document_id = sha(
            json.dumps(
                ["ragforge-document-v1", "3gpp-etsi", source["source_path"]],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        )
        version_cases.append(
            {
                "case_id": row["case_id"].replace(
                    "telequad-extractive:", "telequad-version-scope:"
                ),
                "upstream_case_id": row["case_id"],
                "track": "version_scope_draft",
                "question": f"According to 3GPP {kind} {code[:2]}.{code[2:]} "
                f"version {source['version']}, {row['question']}",
                "collection_id": "3gpp-etsi",
                "expected_document_id": document_id,
                "acceptable_document_ids": sorted(
                    source_aliases.get(source["source_sha256"], [document_id])
                ),
                "source_path": source["source_path"],
                "source_sha256": source["source_sha256"],
                "source_version": source["version"],
                "candidate_evidence": source["candidate_evidence"],
                "expected_answers": row["answers"],
                "split": row["split"],
                "split_group": row["split_group"],
                "source_family": row["source_family"],
                "review": "adapted_from_native_QA_pending_independent_review",
                "strict_scoring_eligible": False,
                "product_execution": "not_run",
            }
        )
    out = root / "prepared-qa"
    out.mkdir(parents=True, exist_ok=True)
    for split in ("dev", "tuning", "test"):
        (out / (split + ".jsonl")).write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in cases if r["split"] == split),
            encoding="utf-8",
        )
    (out / "contexts.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in contexts.values()),
        encoding="utf-8",
    )
    (out / "version-scoped.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in version_cases), encoding="utf-8"
    )
    summary = {
        "native_revision": audit["revision"],
        "cases": len(cases),
        "tracks": dict(Counter(r["track"] for r in cases)),
        "splits": dict(Counter(r["split"] for r in cases)),
        "source_families": len(parent),
        "contexts": len(contexts),
        "version_scope_cases": len(version_cases),
        "cases_with_exact_source_candidates": sum(
            bool(r.get("source_alignment", {}).get("candidate_evidence")) for r in cases
        ),
        "quarantined_extractive_cases": [
            r["case_id"]
            for r in cases
            if r["native_annotation_check"] == "quarantined_span_mismatch"
        ],
        "full_corpus_retrieval_eligible": 0,
        "status": "external_native_QA_prepared_full_corpus_mapping_pending",
        "product_execution": "not_run",
        "distribution": (
            "local derivative of unchanged native data; do not redistribute without rights review"
        ),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.root), indent=2))


if __name__ == "__main__":
    main()
