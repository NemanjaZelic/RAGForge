"""Validate supplementary source-grounded draft queries without running retrieval."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path


class MainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.depth = 0
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = dict(attrs)
        if tag == "div":
            if self.depth:
                self.depth += 1
            elif data.get("role") == "main" and "body" in (data.get("class") or "").split():
                self.depth = 1
        if not self.depth:
            return
        if tag in {"head", "script", "style", "template"}:
            self.skip += 1
        if not self.skip and tag in {
            "p",
            "div",
            "li",
            "tr",
            "h1",
            "h2",
            "h3",
            "h4",
            "pre",
            "br",
            "section",
        }:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"head", "script", "style", "template"}:
            self.skip = max(0, self.skip - 1)
        if tag == "div" and self.depth:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth and not self.skip:
            self.parts.append(data)


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def validate(dataset: Path, source_root: Path | None = None) -> dict[str, object]:
    cases = []
    for corpus in ("ietf-rfcs", "kernel-6.18"):
        for split in ("dev", "tuning", "test"):
            path = dataset / "drafts" / corpus / (split + ".jsonl")
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            if any(r["split"] != split or r["corpus_id"] != corpus for r in rows):
                raise ValueError("Draft stored in wrong corpus/split")
            cases.extend(rows)
    if len(cases) != 240 or len({r["query_id"] for r in cases}) != 240:
        raise ValueError("Expected 240 unique supplementary draft cases")
    counts = Counter(r["corpus_id"] for r in cases)
    if counts != {"ietf-rfcs": 120, "kernel-6.18": 120}:
        raise ValueError("Unexpected draft corpus counts")
    scopes: dict[tuple[str, str], set[str]] = defaultdict(set)
    text_cache: dict[tuple[str, str], str] = {}
    for row in cases:
        if row["review"]["status"] != "ai_draft" or row["review"]["strict_scoring_eligible"]:
            raise ValueError("Draft labels cannot be silently promoted")
        if row["corpus_id"] == "kernel-6.18" and row["split"] != "test":
            raise ValueError("Kernel collection is reserved as a whole-corpus holdout")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", row["collection_id"]):
            raise ValueError("Invalid collection ID")
        documents = set()
        for evidence in row["evidence"]:
            path = evidence["source_path"]
            key = row["corpus_id"], path
            scopes[key].add(row["split"])
            document_id = digest(
                json.dumps(
                    ["ragforge-document-v1", row["collection_id"], path],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
            )
            documents.add(document_id)
            if source_root is not None:
                if key not in text_cache:
                    raw = (source_root / key[0] / "input" / path).read_bytes()
                    if digest(raw) != evidence["source_sha256"]:
                        raise ValueError("Draft source hash mismatch")
                    text = raw.decode("utf-8")
                    if path.endswith(".html"):
                        parser = MainText()
                        parser.feed(text)
                        text = "".join(parser.parts)
                    text_cache[key] = re.sub(r"\s+", " ", text)
                text = text_cache[key]
                loc = evidence["locator"]
                if not 0 <= loc["char_start"] < loc["char_end"] <= len(text):
                    raise ValueError("Draft evidence range out of bounds")
                if (
                    digest(text[loc["char_start"] : loc["char_end"]].encode())
                    != evidence["span_sha256"]
                ):
                    raise ValueError("Draft evidence span hash mismatch")
        if set(row["relevant_document_ids"]) != documents:
            raise ValueError("Draft document IDs do not match source evidence")
        if row.get("task_type") == "multi_document":
            if len(documents) != 2 or len(row["expected_facts"]) != 2:
                raise ValueError("Incomplete multi-document evidence groups")
    if any(len(splits) != 1 for splits in scopes.values()):
        raise ValueError("Evidence-source leakage across splits")
    return {
        "draft_cases": len(cases),
        "multi_document_cases": sum(r.get("task_type") == "multi_document" for r in cases),
        "source_documents": len(scopes),
        "source_spans_verified": source_root is not None,
        "strict_scoring_eligible": 0,
        "product_execution": "not_run",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "tests/fixtures/benchmarks/scale-v1",
    )
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.dataset, args.source_root), indent=2))


if __name__ == "__main__":
    main()
