"""Bind manually selected answer facts to sources, with optional verbatim alternatives.

This is annotation preparation, never retrieval. Inputs and outputs containing
questions/quotes stay local. Expanded alternatives remain AI drafts pending review;
exact copying alone does not establish semantic or version appropriateness.
"""

import argparse
import hashlib
import json
from pathlib import Path

from ragforge.core.scan import ScanLimits, scan_corpus
from ragforge.evaluation.models import AnswerEvidence, Evidence, EvidenceGroup
from ragforge.evaluation.runner import read_cases
from ragforge.evaluation.sources import canonicalize


def sha(data):
    return hashlib.sha256(data).hexdigest()


def prepare(cases_file, seeds_file, source_root, output, *, split, expand_verbatim=False):
    seeds = json.loads(seeds_file.read_text(encoding="utf-8"))
    if seeds["cases_sha256"] != sha(cases_file.read_bytes()):
        raise ValueError("seed question bank checksum mismatch")
    if output.exists():
        raise FileExistsError("annotation output must be new")
    cases = [
        c for c in read_cases(cases_file) if c.split == split and c.answerability == "answerable"
    ]
    if set(seeds["cases"]) != {c.case_id for c in cases}:
        raise ValueError("seed annotations must cover exactly the selected positive cases")
    if not cases:
        raise ValueError("selected positive cases are empty")
    inventory = scan_corpus(
        source_root, cases[0].collection_id, ScanLimits(64 * 1024**2, 6 * 1024**3, 100000)
    )
    fact_targets = {key: [] for key in seeds["facts"]}
    primary_found = set()
    for record in inventory.documents:
        if record.format not in {"text", "markdown"}:
            continue  # This helper authors plain-text facts; other formats use explicit Evidence.
        path = source_root / record.source_path
        raw = path.read_bytes()
        if sha(raw) != record.content_sha256:
            raise ValueError("source changed during annotation preparation")
        try:
            text = canonicalize(raw.decode("utf-8"), "collapse-whitespace-v1")
        except UnicodeDecodeError:
            continue
        for key, fact in seeds["facts"].items():
            is_primary = record.source_path == fact["source_path"]
            if not is_primary and not expand_verbatim:
                continue
            quote = canonicalize(fact["quote"], "collapse-whitespace-v1").strip()
            if len(quote) < 30:
                raise ValueError(
                    "fact quotes need sufficient scope; isolated keywords are forbidden"
                )
            start = text.find(quote)
            if start < 0:
                continue
            if is_primary:
                primary_found.add(key)
            while start >= 0:
                if len(fact_targets[key]) >= 1000:
                    raise ValueError("too many alternatives; narrow the fact scope")
                fact_targets[key].append(
                    Evidence(
                        source_path=record.source_path,
                        source_sha256=record.content_sha256,
                        canonicalizer="collapse-whitespace-v1",
                        char_start=start,
                        char_end=start + len(quote),
                        span_sha256=sha(quote.encode()),
                    )
                )
                start = text.find(quote, start + 1)
    if primary_found != set(seeds["facts"]):
        raise ValueError(
            "primary source quote missing: " + str(sorted(set(seeds["facts"]) - primary_found))
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        for case in cases:
            definition = seeds["cases"][case.case_id]
            annotation = AnswerEvidence(
                case_id=case.case_id,
                query_sha256=sha(case.query.encode()),
                collection_id=case.collection_id,
                scope_note=definition["scope_note"],
                facts=[EvidenceGroup(any_of=fact_targets[key]) for key in definition["fact_keys"]],
            )
            stream.write(annotation.model_dump_json() + "\n")
    audit = {
        "state": "draft_annotations_require_independent_review",
        "split": split,
        "cases": len(cases),
        "unique_facts": len(fact_targets),
        "accepted_source_spans": sum(len(v) for v in fact_targets.values()),
        "strict_scoring_eligible": 0,
        "expanded_verbatim": expand_verbatim,
        "cases_sha256": sha(cases_file.read_bytes()),
        "seeds_sha256": sha(seeds_file.read_bytes()),
        "annotations_sha256": sha(output.read_bytes()),
        "policy": (
            "manually chosen scoped facts; exact verbatim candidates across plain-text "
            "sources; no retrieval-output input"
        ),
    }
    output.with_suffix(".audit.json").write_text(
        json.dumps(audit, indent=2) + "\n", encoding="utf-8"
    )
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--seeds", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=["dev", "tuning", "test"], required=True)
    parser.add_argument("--expand-verbatim", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            prepare(
                args.cases,
                args.seeds,
                args.source_root,
                args.output,
                split=args.split,
                expand_verbatim=args.expand_verbatim,
            )
        )
    )


if __name__ == "__main__":
    main()
