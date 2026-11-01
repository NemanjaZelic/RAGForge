"""Implementation pilot on existing development fixtures, not the external test set."""

import argparse
import importlib.metadata
import json
import platform
import sqlite3
import statistics
import time
from pathlib import Path

from ragforge.artifacts.builder import build_bundle
from ragforge.artifacts.verification import verify_bundle
from ragforge.core.contracts import RetrieveRequest
from ragforge.core.embedding import file_hash, model_spec
from ragforge.core.engine import BundleEngine


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    queries = [
        json.loads(line)
        for line in (root / "examples/eval.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    observations = []
    for candidate in ("e5-small", "minilm"):
        directory = args.models / candidate
        spec = model_spec(directory)
        destination = args.work / (candidate + "-bundle")
        started = time.perf_counter()
        manifest = (
            build_bundle(
                root / "examples/mini-docs",
                destination,
                collection_id="mini",
                model_directory=directory,
            )
            if not destination.exists()
            else verify_bundle(destination)
        )
        build_seconds = time.perf_counter() - started
        methods = {}
        for method in ("bm25", "dense", "hybrid"):
            started = time.perf_counter()
            engine = BundleEngine(destination)
            init_seconds = time.perf_counter() - started
            recalls, rr, latencies, rows = [], [], [], []
            for row in queries:
                started = time.perf_counter()
                result = engine.retrieve(
                    RetrieveRequest(
                        query=row["query"],
                        search_method=method,
                        top_k=10,
                        max_output_chars=100000,
                    )
                )
                latencies.append(time.perf_counter() - started)
                expected = set(row["relevant_document_ids"])
                if expected:
                    recalls.append(
                        len(expected & {r.document_id for r in result.results[:5]}) / len(expected)
                    )
                    rr.append(
                        next(
                            (
                                1 / index
                                for index, part in enumerate(result.results, 1)
                                if part.document_id in expected
                            ),
                            0,
                        )
                    )
                rows.append(
                    {
                        "query_id": row["query_id"],
                        "kind": row["kind"],
                        "returned": len(result.results),
                        "first_source": result.results[0].source.path if result.results else None,
                        "ranked_document_ids": [r.document_id for r in result.results],
                    }
                )
            methods[method] = {
                "recall_at_5": statistics.mean(recalls),
                "mrr_at_10": statistics.mean(rr),
                "negative_with_results": sum(
                    r["kind"] == "unanswerable" and r["returned"] > 0 for r in rows
                ),
                "constructor_seconds": init_seconds,
                "first_query_seconds": latencies[0],
                "warm_p50_seconds": statistics.median(latencies[1:]),
                "queries": rows,
            }
        observations.append(
            {
                "candidate": candidate,
                "model_id": spec.model_id,
                "revision": spec.revision,
                "license": spec.license,
                "dimensions": spec.dimensions,
                "model_package_bytes": sum(r.size_bytes for r in spec.files),
                "graph_sha256": next(r.sha256 for r in spec.files if r.path == "model.onnx"),
                "bundle_build_id": manifest.build_id,
                "build_or_reuse_seconds": build_seconds,
                "methods": methods,
            }
        )
    report = {
        "kind": "cpu-model-implementation-pilot",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "threads": 4,
        "sqlite": sqlite3.sqlite_version,
        "versions": {
            name: importlib.metadata.version(name)
            for name in (
                "numpy",
                "onnxruntime",
                "tokenizers",
            )
        },
        "queries_sha256": file_hash(root / "examples/eval.jsonl"),
        "candidates": observations,
        "selected_initial_model": "intfloat/multilingual-e5-small",
        "selection_reason": [
            "Initial multilingual profile including Serbian use; MiniLM card targets English.",
            "Both candidates were loaded and measured on the same existing development fixtures.",
            "CPU/size tradeoff is provisional; external test sets are separate.",
        ],
        "limits": [
            "20 development questions with document-level labels, not held-out relevance evidence.",
            "No abstention threshold; negative results are listed rather than scored as successes.",
            "Local CPU timings only; no global optimum or semantic quality guarantee.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            [
                {
                    "candidate": r["candidate"],
                    "bytes": r["model_package_bytes"],
                    "methods": {
                        method: {key: value for key, value in data.items() if key != "queries"}
                        for method, data in r["methods"].items()
                    },
                }
                for r in observations
            ]
        )
    )


if __name__ == "__main__":
    main()
