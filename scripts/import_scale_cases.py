"""Create local-only evaluator inputs from frozen drafts; never promote annotation status."""

import argparse
import json
from collections import Counter
from pathlib import Path

from ragforge.evaluation.models import EvaluationCase, Evidence, EvidenceGroup

ROOT = Path(__file__).resolve().parents[1]


def rows(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def aligned_targets(path, checksum, candidates):
    return [
        Evidence(
            source_path=path,
            source_sha256=checksum,
            page=target["page"],
            canonicalizer=target["canonicalizer"],
            char_start=target["canonical_char_start"],
            char_end=target["canonical_char_end"],
            span_sha256=target["span_sha256"],
        )
        for target in candidates
    ]


def prepare(root: Path, output: Path):
    # Native questions/adaptations stay local under the ignored data root.
    if output.exists():
        raise FileExistsError("case import output already exists; select a new version")
    output.mkdir(parents=True)
    collections = {"3gpp-etsi": [], "ietf-rfcs": [], "kernel-6.18": []}
    excluded = Counter()
    for split in ("dev", "tuning", "test"):
        for original in rows(root / "prepared-qa" / (split + ".jsonl")):
            if original["track"] != "native_context_qa":
                excluded["native_tabular_mapping_pending"] += 1
                continue
            if original["native_is_impossible"]:
                excluded["native_negative_not_global_ground_truth"] += 1
                continue
            if original["native_annotation_check"] == "quarantined_span_mismatch":
                excluded["quarantined_native_span"] += 1
                continue
            alignment = original.get("source_alignment") or {}
            candidates = alignment.get("candidate_evidence") or []
            if not candidates:
                excluded["native_full_source_alignment_missing"] += 1
                continue
            targets = aligned_targets(
                alignment["source_path"], alignment["source_sha256"], candidates
            )
            collections["3gpp-etsi"].append(
                EvaluationCase(
                    case_id=original["case_id"],
                    corpus_id="3gpp-etsi",
                    collection_id="3gpp-etsi",
                    track="native_source_alignment_diagnostic",
                    family_id=original["split_group"],
                    split=original["split"],
                    query=original["question"],
                    answerability="answerable",
                    evidence_groups=[EvidenceGroup(any_of=targets)],
                    review_status="native_mapping_pending",
                )
            )
    for original in rows(root / "prepared-qa/version-scoped.jsonl"):
        targets = aligned_targets(
            original["source_path"], original["source_sha256"], original["candidate_evidence"]
        )
        collections["3gpp-etsi"].append(
            EvaluationCase(
                case_id=original["case_id"],
                corpus_id="3gpp-etsi",
                collection_id="3gpp-etsi",
                track="explicit_version_draft",
                family_id=original["split_group"],
                split=original["split"],
                query=original["question"],
                answerability="answerable",
                evidence_groups=[EvidenceGroup(any_of=targets)],
                review_status="ai_draft",
            )
        )
    fixture = ROOT / "tests/fixtures/benchmarks/scale-v1/drafts"
    for corpus in ("ietf-rfcs", "kernel-6.18"):
        for split in ("dev", "tuning", "test"):
            for original in rows(fixture / corpus / (split + ".jsonl")):
                groups = [
                    EvidenceGroup(
                        any_of=[
                            Evidence(
                                source_path=e["source_path"],
                                source_sha256=e["source_sha256"],
                                canonicalizer=e["locator"]["canonicalizer"],
                                char_start=e["locator"]["char_start"],
                                char_end=e["locator"]["char_end"],
                                span_sha256=e["span_sha256"],
                            )
                        ]
                    )
                    for e in original["evidence"]
                ]
                collections[corpus].append(
                    EvaluationCase(
                        case_id=original["query_id"],
                        corpus_id=corpus,
                        collection_id=original["collection_id"],
                        track="supplementary_evidence_draft",
                        family_id=original["split_group"],
                        split=original["split"],
                        query=original["query"],
                        answerability="answerable",
                        evidence_groups=groups,
                        review_status="ai_draft",
                    )
                )
    for corpus, cases in collections.items():
        (output / (corpus + ".jsonl")).write_text(
            "".join(case.model_dump_json() + "\n" for case in cases), encoding="utf-8"
        )
    report = {
        "state": "prepared_not_executed",
        "strict_scoring_eligible": 0,
        "review": "original annotations and mapping review states remain unchanged",
        "distribution": "local-only derivative; do not redistribute native question adaptations",
        "counts": {
            corpus: dict(Counter(c.track for c in cases)) for corpus, cases in collections.items()
        },
        "excluded_with_reasons": dict(excluded),
    }
    (output / "import-summary.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.root, args.output), indent=2))


if __name__ == "__main__":
    main()
