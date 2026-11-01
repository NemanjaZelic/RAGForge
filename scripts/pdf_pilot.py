"""Measure the local PDF adapter against an explicitly downloaded source."""

import argparse
import hashlib
import json
import platform
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from ragforge.core.parse import load_document
from ragforge.core.pdf import PdfOptions
from ragforge.core.scan import scan_corpus


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--license-url", required=True)
    args = parser.parse_args()
    source = args.input.resolve()
    record = next(
        r for r in scan_corpus(source.parent, "pdf-pilot").documents if r.source_path == source.name
    )
    options = PdfOptions()
    started = time.perf_counter()
    document = load_document(source.parent, "pdf-pilot", record, pdf_options=options)
    elapsed = time.perf_counter() - started
    report = {
        "kind": "pdf-parser-smoke-pilot",
        "source_url": args.source_url,
        "source_license_url": args.license_url,
        "source_rights": "Source copyright/license URL apply; PDF/text not redistributed.",
        "source_sha256": record.content_sha256,
        "source_size_bytes": record.size_bytes,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "parser_version": document.parser_version,
        "options": options.model_dump(),
        "wall_seconds": elapsed,
        "page_count": len(document.page_reports),
        "statuses": dict(Counter(r.status for r in document.page_reports)),
        "text_chars": sum(len(b.text) for b in document.blocks),
        "warnings": document.warnings,
        "page_hits": {
            phrase: [b.page for b in document.blocks if phrase in b.text]
            for phrase in ("HTTP Semantics", "404 Not Found")
        },
        "extracted_text_sha256": hashlib.sha256(
            json.dumps(
                [(b.page, b.text) for b in document.blocks],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
        "pages": [asdict(r) for r in document.page_reports],
        "limitations": [
            "Smoke/pipeline check only; not a representative retrieval benchmark.",
            "No source PDF or extracted document text redistributed.",
            "Elapsed time is local observation, not a hardware-independent promise.",
            "Physical pages checked; no semantic table/reading-order guarantee.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "page_count",
                    "statuses",
                    "text_chars",
                    "wall_seconds",
                    "source_sha256",
                    "page_hits",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
