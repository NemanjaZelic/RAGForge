"""Offline candidate/context ceilings. These oracle diagnostics are not answer accuracy.

Gold annotations are used only after actual ranking. No queries/quotes are exported
in the aggregate. Per-case ranks remain in the local checkpoint database.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import statistics
from pathlib import Path


def sha(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while part := stream.read(1024**2):
            value.update(part)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    import gc
    import socket

    import numpy as np

    def denied(*a, **k):
        raise RuntimeError("network forbidden in candidate audit")

    class Blocked(socket.socket):
        def __init__(self, *a, **k):
            denied()

    socket.socket = Blocked
    socket.create_connection = denied
    socket.getaddrinfo = denied
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    from ragforge.core.ann import AnnStore
    from ragforge.core.contracts import RetrieveRequest
    from ragforge.core.embedding import ONNXEmbedder
    from ragforge.core.engine import BundleEngine
    from ragforge.evaluation.models import AnswerEvidence
    from ragforge.evaluation.runner import read_cases
    from ragforge.evaluation.scoring import score_evidence_pool
    from ragforge.evaluation.sources import EvidenceSources
    from ragforge.jobs.build import atomic_json
    from ragforge.jobs.ingest import job_lock

    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    with job_lock(out):
        engine = BundleEngine(args.artifact, threads=2)
        cases = [c for c in read_cases(args.cases) if c.split == "dev"]
        annotations = {
            a.case_id: a
            for a in [
                AnswerEvidence.model_validate_json(line)
                for line in args.answers.read_text(encoding="utf-8").splitlines()
            ]
        }
        sources = EvidenceSources(args.source_root)
        recipe = {
            "artifact_build_id": engine.manifest.build_id,
            "cases_sha256": sha(args.cases),
            "answers_sha256": sha(args.answers),
            "ranking_width": 200,
            "split": "dev",
            "script_sha256": sha(Path(__file__)),
            "scorer_sha256": sha(
                Path(__file__).resolve().parents[1] / "src/ragforge/evaluation/scoring.py"
            ),
        }
        saved = out / "recipe.json"
        if saved.exists() and json.loads(saved.read_text(encoding="utf-8")) != recipe:
            raise ValueError("audit recipe changed")
        atomic_json(saved, recipe)
        vector_file = out / "queries.npy"
        if not vector_file.exists():
            model = ONNXEmbedder(args.artifact / "models/query", threads=2)
            vectors = np.stack([model.encode([case.query], query=True)[0] for case in cases])
            del model
            gc.collect()
            with vector_file.open("xb") as stream:
                np.save(stream, vectors, allow_pickle=False)
            atomic_json(
                out / "queries.json",
                {"sha256": sha(vector_file), "cases_sha256": recipe["cases_sha256"]},
            )
        else:
            meta = json.loads((out / "queries.json").read_text())
            if meta != {"sha256": sha(vector_file), "cases_sha256": recipe["cases_sha256"]}:
                raise ValueError("query vector checkpoint changed")
            vectors = np.load(vector_file, allow_pickle=False)
        dimensions = engine.manifest.query_model.dimensions
        if vectors.shape != (len(cases), dimensions) or not np.isfinite(vectors).all():
            raise ValueError("invalid query vectors")
        print(
            json.dumps({"queries_precomputed": len(cases), "embedding_session_released": True}),
            flush=True,
        )
        dense = engine.collection.dense_index
        from ragforge.core.ann import BACKEND

        if dense is None or dense.backend != BACKEND:
            raise ValueError("audit requires the complete ANN bundle")
        store = AnnStore(args.artifact / dense.path, engine.sqlite, dimensions)
        db = sqlite3.connect(out / "audit.sqlite")
        db.executescript(
            "CREATE TABLE IF NOT EXISTS ranks(case_id TEXT,method TEXT,json TEXT,"
            "PRIMARY KEY(case_id,method));"
            "CREATE TABLE IF NOT EXISTS diagnostics(case_id TEXT PRIMARY KEY,json TEXT);"
        )
        for i, case in enumerate(cases, 1):
            if db.execute("SELECT 1 FROM diagnostics WHERE case_id=?", (case.case_id,)).fetchone():
                continue
            annotation = annotations[case.case_id]
            if annotation.query_sha256 != hashlib.sha256(case.query.encode()).hexdigest():
                raise ValueError("fact question mismatch")
            methods = {}
            for method in ["bm25", "dense"]:
                cached = db.execute(
                    "SELECT json FROM ranks WHERE case_id=? AND method=?", (case.case_id, method)
                ).fetchone()
                if cached:
                    ranks = json.loads(cached[0])
                else:
                    if method == "bm25":
                        ranks = engine.sqlite.rank_bm25(RetrieveRequest(query=case.query), 200)
                    else:
                        ranks = store.rank(vectors[i - 1], 200)
                    with db:
                        db.execute(
                            "INSERT INTO ranks VALUES(?,?,?)",
                            (case.case_id, method, json.dumps(ranks)),
                        )
                methods[method] = ranks
            methods["union"] = list(dict(methods["bm25"] + methods["dense"]).items())
            record = {}
            with engine.sqlite._connect() as c:
                for method, ranks in methods.items():
                    anchors = [
                        c.execute("SELECT * FROM chunks WHERE chunk_id=?", (key,)).fetchone()
                        for key, _ in ranks
                    ]
                    for neighbors in [0, 1, 3, 5]:
                        rows = {row["chunk_id"]: row for row in anchors}
                        if neighbors:
                            for row in anchors:
                                for neighbor in c.execute(
                                    "SELECT * FROM chunks WHERE document_id=? "
                                    "AND ordinal BETWEEN ? AND ?",
                                    (
                                        row["document_id"],
                                        row["ordinal"] - neighbors,
                                        row["ordinal"] + neighbors,
                                    ),
                                ):
                                    rows[neighbor["chunk_id"]] = neighbor
                        chunks = [engine.sqlite._chunk(row, 0, "bm25") for row in rows.values()]
                        scored = score_evidence_pool(
                            case.collection_id, annotation.facts, chunks, sources.text
                        )
                        covers = scored["group_coverages"]
                        paths = {chunk.source.path for chunk in chunks}
                        record[method + "-n" + str(neighbors)] = {
                            "all_facts_available": all(v >= 1 for v in covers),
                            "fact_coverage": statistics.mean(covers),
                            "all_fact_source_groups_available": all(
                                any(t.source_path in paths for t in g.any_of)
                                for g in annotation.facts
                            ),
                            "chunks": len(chunks),
                            "text_chars": sum(len(v.text) for v in chunks),
                        }
            with db:
                db.execute(
                    "INSERT INTO diagnostics VALUES(?,?)", (case.case_id, json.dumps(record))
                )
            all_rows = [json.loads(row[0]) for row in db.execute("SELECT json FROM diagnostics")]
            aggregate = {
                key: {
                    name: statistics.mean(float(row[key][name]) for row in all_rows)
                    for name in [
                        "all_facts_available",
                        "fact_coverage",
                        "all_fact_source_groups_available",
                        "chunks",
                        "text_chars",
                    ]
                }
                for key in record
            }
            report = {
                "scope": (
                    "oracle candidate/context availability only; output budgets are NOT "
                    "enforced; not quality or answer accuracy"
                ),
                "quality_gate": "not_approved_draft_labels",
                "completed": len(all_rows),
                "total": len(cases),
                "recipe": recipe,
                "measurements": aggregate,
            }
            atomic_json(out / "summary.json", report)
            if i % 10 == 0:
                print(json.dumps({"completed": i, "total": len(cases)}), flush=True)
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
