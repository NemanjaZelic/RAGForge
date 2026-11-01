"""Validate benchmark data offline, without importing or running RAGForge."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def relative_path(value: str) -> str:
    path = PurePosixPath(value)
    require(bool(value) and not path.is_absolute(), "invalid relative source path")
    require("\\" not in value and ":" not in value, "nonportable source path")
    require(all(p not in {"", ".", ".."} for p in value.split("/")), "unsafe source path")
    return value


def document_id(collection: str, path: str) -> str:
    body = json.dumps(
        ["ragforge-document-v1", collection, path], ensure_ascii=False, separators=(",", ":")
    ).encode()
    return digest(body)


def validate(dataset: Path, source_root: Path | None = None) -> dict[str, Any]:
    manifest = json.loads((dataset / "dataset.json").read_text(encoding="utf-8"))
    corpora = {c["corpus_id"]: c for c in manifest["corpora"]}
    require(len(corpora) == 3 == len(manifest["corpora"]), "expected three unique corpora")
    require(
        manifest["product_execution"] == "not_run", "preparation must not claim product results"
    )
    require(manifest["status"] == "ai_draft_pending_independent_review", "unexpected review status")
    files = {}
    for c, corpus in corpora.items():
        require(
            len({r["path"] for r in corpus["files"]}) == len(corpus["files"]), "duplicate source"
        )
        file_rows = sorted(corpus["files"], key=lambda r: r["path"])
        identity = [{k: r[k] for k in ("path", "sha256", "size_bytes")} for r in file_rows]
        require(
            digest(canonical(identity)) == corpus["snapshot_id"], "snapshot inventory hash mismatch"
        )
        require(
            sum(r["size_bytes"] for r in file_rows) == corpus["input_size_bytes"],
            "byte count mismatch",
        )
        require(len(file_rows) == corpus["file_count"], "file count mismatch")
        require(bool(corpus["license_url"]) and bool(corpus["rights"]), "missing source rights")
        for row in file_rows:
            path = relative_path(row["path"])
            require(document_id(c, path) == row["document_id"], "source document identity mismatch")
            require(len(row["sha256"]) == 64 and row["size_bytes"] > 0, "invalid source inventory")
            files[c, path] = row
    evidence_rows = read_jsonl(dataset / "evidence.jsonl")
    evidence = {e["evidence_id"]: e for e in evidence_rows}
    require(len(evidence) == len(evidence_rows), "duplicate evidence ID")
    for e in evidence_rows:
        key = e["corpus_id"], e["source_path"]
        require(key in files, "evidence source missing")
        require(e["snapshot_id"] == corpora[key[0]]["snapshot_id"], "evidence snapshot mismatch")
        require(e["document_id"] == files[key]["document_id"], "evidence document mismatch")
        require(e["relevance_grade"] in {1, 2}, "invalid relevance grade")
        loc = e["locator"]
        kind = loc["kind"]
        require(kind in {"lines", "html_section", "pdf_page_chars"}, "unknown evidence locator")
        if kind == "lines":
            require(1 <= loc["line_start"] <= loc["line_end"], "invalid source lines")
        elif kind == "html_section":
            require(0 <= loc["byte_start"] < loc["byte_end"], "invalid HTML byte span")
            require(bool(loc["element_id"]), "missing HTML section ID")
        else:
            require(1 <= loc["page"] <= 194, "invalid physical PDF page")
            require(0 <= loc["char_start"] < loc["char_end"], "invalid PDF text span")
            require(loc["extractor"] == "pypdf==6.21.4/plain", "unpinned PDF extraction")

    queries = []
    for split in ("dev", "tuning", "test"):
        split_rows = read_jsonl(dataset / "gold" / (split + ".jsonl"))
        require(all(r["split"] == split for r in split_rows), "query stored in wrong split")
        queries.extend(split_rows)
    require(len(queries) == 90, "expected 90 pilot queries")
    require(len({r["query_id"] for r in queries}) == 90, "duplicate query ID")
    used: set[str] = set()
    topic_splits: dict[str, set[str]] = defaultdict(set)
    evidence_splits: dict[str, set[str]] = defaultdict(set)
    counts: Counter[tuple[str, str, str]] = Counter()
    for row in queries:
        c = row["corpus_id"]
        require(c in corpora and row["collection_id"] == c, "invalid query corpus")
        require(row["snapshot_id"] == corpora[c]["snapshot_id"], "query snapshot mismatch")
        require(0 < len(row["query"].strip()) <= 8192, "invalid query text")
        require(row["language"] in {"en", "sr-Latn", "sr-Cyrl"}, "invalid query language")
        review = row["review"]
        require(review["status"] == "ai_draft", "unreviewed data must remain draft")
        require(not review["strict_scoring_eligible"], "draft must not pass strict scoring")
        require(
            review["independent_reviewer"] is None,
            "no independent reviewer has reviewed this draft",
        )
        topic_splits[row["topic_group"]].add(row["split"])
        answerable = row["answerability"] == "answerable"
        require(
            answerable or row["answerability"] == "unanswerable_in_snapshot",
            "invalid answerability",
        )
        counts[c, row["split"], row["answerability"]] += 1
        groups = row["required_evidence_groups"]
        require(bool(groups) == answerable, "answerability/evidence mismatch")
        require(bool(row["expected_facts"]) == answerable, "answerability/facts mismatch")
        require(len({g["group_id"] for g in groups}) == len(groups), "duplicate required group ID")
        expected_documents = set()
        for group in groups:
            require(bool(group["any_of"]), "empty evidence alternative group")
            for id in group["any_of"]:
                require(id in evidence, "unknown evidence reference")
                e = evidence[id]
                require(e["corpus_id"] == c, "cross-corpus evidence reference")
                expected_documents.add(e["document_id"])
                evidence_splits[id].add(row["split"])
                used.add(id)
        require(
            set(row["relevant_document_ids"]) == expected_documents,
            "document labels differ from evidence",
        )
        if not answerable:
            absence = row["absence_check"]
            require(
                set(absence["scope"]) == {r["path"] for r in corpora[c]["files"]},
                "incomplete absence scope",
            )
            require(
                bool(absence["terms"]) and bool(absence["rationale"]), "missing absence rationale"
            )
            require(absence["independent_check"] == "pending", "absence not independently verified")
    require(all(len(s) == 1 for s in topic_splits.values()), "topic leakage across splits")
    require(all(len(s) == 1 for s in evidence_splits.values()), "evidence leakage across splits")
    require(used == set(evidence), "unreferenced evidence")
    for c in corpora:
        for split in ("dev", "tuning", "test"):
            require(
                counts[c, split, "answerable"] == 8, "expected eight positives per corpus/split"
            )
            require(
                counts[c, split, "unanswerable_in_snapshot"] == 2,
                "expected two negatives per corpus/split",
            )
    actual_counts = {
        "corpora": len(corpora),
        "queries": len(queries),
        "answerable": 72,
        "unanswerable": 18,
        "queries_per_corpus": 30,
    }
    require(manifest["counts"] == actual_counts, "manifest query counts mismatch")

    selection = json.loads((dataset / "selection.json").read_text(encoding="utf-8"))
    require(selection["seed"] == manifest["seed"], "selection seed mismatch")
    require(selection["before_retrieval_results"] is True, "selection must precede retrieval")
    controls = json.loads((dataset / "controls" / "cases.json").read_text(encoding="utf-8"))
    require(
        controls["quality_benchmark_queries"] == 0, "controls must not inflate real-corpus counts"
    )
    require(controls["product_execution"] == "not_run", "controls must not claim execution")
    for row in controls["files"]:
        raw = (dataset / "controls" / relative_path(row["path"])).read_bytes()
        require(
            len(raw) == row["size_bytes"] and digest(raw) == row["sha256"], "control fixture drift"
        )
    scenarios = json.loads((dataset / "scenarios.json").read_text(encoding="utf-8"))
    require(scenarios["product_execution"] == "not_run", "scenarios must not claim execution")
    ids = [s["scenario_id"] for s in scenarios["scenarios"]]
    require(len(set(ids)) == len(ids), "duplicate product scenario ID")
    require(
        all(s["status"] == "not_run" for s in scenarios["scenarios"]),
        "unexecuted scenario claimed success",
    )

    # Verify frozen bytes/spans only when the separately acquired sources are supplied.
    if source_root is not None:
        pdf_pages: dict[tuple[str, str], list[str]] = {}
        for (c, path), row in files.items():
            root = source_root / c
            for folder in ("raw", "input"):
                body = (root / folder / path).read_bytes()
                require(digest(body) == row["sha256"], f"source hash mismatch: {c}/{folder}/{path}")
                require(len(body) == row["size_bytes"], "source size mismatch")
            actual = {
                p.relative_to(root / "input").as_posix()
                for p in (root / "input").rglob("*")
                if p.is_file()
            }
            require(
                actual == {r["path"] for r in corpora[c]["files"]}, "unexpected/missing input file"
            )
        for e in evidence_rows:
            key = e["corpus_id"], e["source_path"]
            path = source_root / key[0] / "input" / key[1]
            loc = e["locator"]
            if loc["kind"] == "pdf_page_chars":
                # Optional preparation dependency, never used for metadata-only CI validation.
                import pypdf

                require(
                    pypdf.__version__ == "6.21.4", "PDF source verification requires pinned pypdf"
                )
                if key not in pdf_pages:
                    pdf_pages[key] = [
                        p.extract_text(extraction_mode="plain") for p in pypdf.PdfReader(path).pages
                    ]
                text = pdf_pages[key][loc["page"] - 1]
                require(loc["char_end"] <= len(text), "PDF character range beyond page")
                span = text[loc["char_start"] : loc["char_end"]].encode()
            else:
                raw = path.read_bytes()
                if loc["kind"] == "lines":
                    lines = raw.splitlines(keepends=True)
                    require(loc["line_end"] <= len(lines), "source line beyond file")
                    span = b"".join(lines[loc["line_start"] - 1 : loc["line_end"]])
                else:
                    require(loc["byte_end"] <= len(raw), "HTML span beyond file")
                    span = raw[loc["byte_start"] : loc["byte_end"]]
                    require(
                        span.startswith(('<section id="' + loc["element_id"] + '"').encode()),
                        "HTML anchor mismatch",
                    )
            require(digest(span) == e["span_sha256"], "evidence span hash mismatch")
    return {
        **actual_counts,
        "evidence_spans": len(evidence),
        "sources_verified": source_root is not None,
        "strict_scoring_eligible": 0,
        "product_execution": "not_run",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "tests/fixtures/benchmarks/pilot-v1",
    )
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.dataset, args.source_root), indent=2))


if __name__ == "__main__":
    main()
