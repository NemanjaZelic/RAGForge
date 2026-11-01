"""Three authored page probes on one pinned PDF, not a held-out benchmark."""

import argparse
import hashlib
import json
import sqlite3
import time
from pathlib import Path

from ragforge.core.contracts import RetrieveRequest
from ragforge.core.sqlite import SQLiteEngine

PROBES = [("404 Not Found", 138), ("idempotent", 73), ("Retry-After", 89)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("parser_report", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = json.loads(args.parser_report.read_text(encoding="utf-8"))
    with sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        records = connection.execute("SELECT content_sha256 FROM documents").fetchall()
    if records != [(source["source_sha256"],)]:
        raise ValueError("index must contain exactly the pinned PDF source")
    engine = SQLiteEngine(args.database)
    results = []
    for query, expected_page in PROBES:
        started = time.perf_counter()
        hits = engine.retrieve(RetrieveRequest(query=query, top_k=10))
        elapsed = time.perf_counter() - started
        results.append(
            {
                "query": query,
                "expected_physical_page": expected_page,
                "expected_page_in_first_5": expected_page
                in [r.source.page for r in hits.results[:5]],
                "latency_seconds": elapsed,
                "hits": [
                    {
                        "chunk_id": hit.chunk_id,
                        "source": hit.source.model_dump(),
                        "rank_score": hit.rank_score,
                    }
                    for hit in hits.results
                ],
            }
        )
    report = {
        "kind": "real-pdf-bm25-smoke",
        "source_url": source["source_url"],
        "source_sha256": source["source_sha256"],
        "source_license_url": source["source_license_url"],
        "source_page_count": source["page_count"],
        "parser_version": source["parser_version"],
        "index_sha256": hashlib.sha256(args.database.read_bytes()).hexdigest(),
        "sqlite": sqlite3.sqlite_version,
        "method": "bm25",
        "top_k": 10,
        "all_expected_pages_in_first_5": all(r["expected_page_in_first_5"] for r in results),
        "results": results,
        "limitations": [
            "Three authored exact-term probes on one RFC; not a held-out quality set.",
            "Page labels checked against the source PDF independently of chunk boundaries.",
            "Only BM25; dense/hybrid and multi-corpus evaluation remain RF-006 work.",
            "No source PDF or extracted source text redistributed.",
        ],
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "passed_probes": sum(r["expected_page_in_first_5"] for r in results),
                "total_probes": len(results),
            }
        )
    )


if __name__ == "__main__":
    main()
