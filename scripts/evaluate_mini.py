"""Document-label BM25 development baseline; not a release quality claim."""

import argparse
import hashlib
import json
import platform
import sqlite3
import statistics
import time
from pathlib import Path

from ragforge import __version__
from ragforge.core.chunk import CHUNKER_VERSION, ChunkConfig
from ragforge.core.contracts import RetrieveRequest
from ragforge.core.parse import load_document
from ragforge.core.scan import scan_corpus
from ragforge.core.sqlite import SQLiteEngine, create_index


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    scan = scan_corpus(args.corpus, "mini")
    documents = [load_document(args.corpus, "mini", r) for r in scan.documents]
    config = ChunkConfig()
    started = time.perf_counter()
    summary = create_index(args.database, "mini", "Development mini corpus", documents, config)
    build_seconds = time.perf_counter() - started
    engine = SQLiteEngine(args.database)
    queries = [json.loads(line) for line in args.queries.read_text(encoding="utf-8").splitlines()]
    recalls, reciprocal_ranks, latencies, results = [], [], [], []
    for row in queries:
        request = RetrieveRequest(
            query=row["query"],
            collection_id=row["collection_id"],
            top_k=10,
            max_output_chars=100000,
            search_method="bm25",
        )
        started = time.perf_counter()
        response = engine.retrieve(request)
        latency = time.perf_counter() - started
        latencies.append(latency)
        expected = set(row["relevant_document_ids"])
        recall = reciprocal = None
        if row["kind"] == "relevant":
            assert expected
            found = {hit.document_id for hit in response.results[:5]}
            recall = len(found & expected) / len(expected)
            reciprocal = next(
                (
                    1 / rank
                    for rank, hit in enumerate(response.results, 1)
                    if hit.document_id in expected
                ),
                0,
            )
            recalls.append(recall)
            reciprocal_ranks.append(reciprocal)
        results.append(
            {
                "query_id": row["query_id"],
                "kind": row["kind"],
                "query": row["query"],
                "recall_at_5": recall,
                "reciprocal_rank_at_10": reciprocal,
                "latency_seconds": latency,
                "results": [
                    {
                        "chunk_id": hit.chunk_id,
                        "document_id": hit.document_id,
                        "rank_score": hit.rank_score,
                        "source": hit.source.model_dump(),
                    }
                    for hit in response.results
                ],
            }
        )
    configuration = {
        "chunker_version": CHUNKER_VERSION,
        **config.model_dump(),
        "parser_versions": sorted({doc.parser_version for doc in documents}),
        "search_method": "bm25",
        "tokenizer": "unicode61 remove_diacritics 2",
        "query_mode": "literal Unicode alphanumeric terms OR",
        "top_k": 10,
        "max_output_chars": 100000,
    }
    report = {
        "kind": "development-mini-bm25",
        "producer_version": __version__,
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "platform": platform.platform(),
        "corpus_sha256": digest([r.model_dump() for r in scan.documents]),
        "queries_sha256": hashlib.sha256(args.queries.read_bytes()).hexdigest(),
        "configuration": configuration,
        "configuration_sha256": digest(configuration),
        "summary": summary.model_dump(),
        "positive_queries": len(recalls),
        "negative_queries": sum(row["kind"] == "unanswerable" for row in queries),
        "recall_at_5": statistics.mean(recalls),
        "mrr_at_10": statistics.mean(reciprocal_ranks),
        "negative_queries_with_results": sum(
            row["kind"] == "unanswerable" and bool(row["results"]) for row in results
        ),
        "build_seconds": build_seconds,
        "latency_p50_seconds": statistics.median(latencies),
        "latency_p95_seconds": sorted(latencies)[int(0.95 * (len(latencies) - 1))],
        "results": results,
        "limitations": [
            "20 development questions on 6 tiny documents; not a representative benchmark.",
            "Positive labels identify documents, not exact evidence spans.",
            "Recall uses relevant document IDs within first 5 chunks; MRR uses first 10 chunks.",
            "Unanswerable questions are reported separately; no abstention threshold exists.",
            "Warm local timings include opening a read-only SQLite connection per query.",
            "Standalone index; bundle E2E and dense/hybrid comparison are pending.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "positive_queries",
                    "negative_queries",
                    "recall_at_5",
                    "mrr_at_10",
                    "negative_queries_with_results",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
