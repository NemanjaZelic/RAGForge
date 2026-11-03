"""Offline development experiment: small dense hits, larger cited contexts."""

import argparse
import hashlib
import json
import os
import socket
import sqlite3
import statistics
import time
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["children", "parents", "audit", "cases", "answers", "sources", "output"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()

    def denied(*a, **k):
        raise RuntimeError("network forbidden in parent retrieval experiment")

    class Blocked(socket.socket):
        def __init__(self, *a, **k):
            denied()

    socket.socket = Blocked
    socket.create_connection = denied
    socket.getaddrinfo = denied
    os.environ["HF_HUB_OFFLINE"] = "1"
    from ragforge.core.contracts import RetrieveRequest
    from ragforge.core.dense import reciprocal_rank_fusion
    from ragforge.core.engine import BundleEngine
    from ragforge.core.parents import ParentMapper
    from ragforge.core.rerank import ONNXReranker
    from ragforge.evaluation.models import AnswerEvidence
    from ragforge.evaluation.runner import read_cases
    from ragforge.evaluation.scoring import score_answer_evidence
    from ragforge.evaluation.sources import EvidenceSources
    from ragforge.jobs.build import atomic_json
    from ragforge.jobs.ingest import job_lock

    args.output.mkdir(parents=True, exist_ok=True)
    with job_lock(args.output):
        child = BundleEngine(args.children, threads=2)
        parent = BundleEngine(args.parents, threads=2)
        mapper = ParentMapper(child.sqlite, parent.sqlite)
        recipe = {
            "child_build_id": child.manifest.build_id,
            "artifact_build_id": parent.manifest.build_id,
            "cases_sha256": digest(args.cases),
            "answer_evidence_sha256": digest(args.answers),
            "audit_sha256": digest(args.audit),
            "script_sha256": digest(Path(__file__)),
            "mapper_sha256": digest(
                Path(__file__).resolve().parents[1] / "src/ragforge/core/parents.py"
            ),
            "split": "dev",
            "top_k": 10,
            "max_output_chars": 16000,
            "dense_child_candidates": 200,
            "dense_parent_candidates": 100,
            "bm25_parent_candidates": 100,
            "reranker_candidates_max": 200,
        }
        saved = args.output / "run.json"
        if saved.exists() and json.loads(saved.read_text()) != recipe:
            raise ValueError("experiment recipe changed")
        atomic_json(saved, recipe)
        audit = sqlite3.connect(args.audit.resolve().as_uri() + "?mode=ro", uri=True)
        db = sqlite3.connect(args.output / "evaluation.sqlite")
        db.execute(
            "CREATE TABLE IF NOT EXISTS results(case_id TEXT PRIMARY KEY,method TEXT,json TEXT)"
        )
        reranker = ONNXReranker(args.parents / "models/reranker", threads=2)
        labels = {
            a.case_id: a
            for a in [
                AnswerEvidence.model_validate_json(line)
                for line in args.answers.read_text(encoding="utf-8").splitlines()
            ]
        }
        sources = EvidenceSources(args.sources)
        cases = [c for c in read_cases(args.cases) if c.split == "dev"]
        for i, case in enumerate(cases, 1):
            if db.execute("SELECT 1 FROM results WHERE case_id=?", (case.case_id,)).fetchone():
                continue
            started = time.monotonic()
            request = RetrieveRequest(
                query=case.query,
                collection_id=case.collection_id,
                top_k=10,
                max_output_chars=16000,
                search_method="hybrid",
            )
            dense = json.loads(
                audit.execute(
                    "SELECT json FROM ranks WHERE case_id=? AND method='dense'", (case.case_id,)
                ).fetchone()[0]
            )
            dense = mapper.map_ranks(dense, 100)
            lexical = parent.sqlite.rank_bm25(request, 100)
            candidates = reciprocal_rank_fusion(lexical, dense, 200)
            with parent.sqlite._connect() as connection:
                texts = []
                for key, _ in candidates:
                    row = connection.execute(
                        "SELECT text,source_json FROM chunks WHERE chunk_id=?", (key,)
                    ).fetchone()
                    source = json.loads(row["source_json"])
                    texts.append(
                        source["path"] + "\n" + (source.get("section") or "") + "\n" + row["text"]
                    )
            scores = reranker.score(case.query, texts)
            ranks = sorted(
                zip([k for k, _ in candidates], scores, strict=True),
                key=lambda pair: (-pair[1], pair[0]),
            )
            response = parent.sqlite.ranked_response(ranks[:10], request, "hybrid")
            scored = score_answer_evidence(labels[case.case_id], case, response, sources.text)
            scored.update(
                case_id=case.case_id,
                elapsed=time.monotonic() - started,
                ranked_sources=[
                    {"chunk_id": c.chunk_id, "source": c.source.model_dump(mode="json")}
                    for c in response.results
                ],
                mapped_dense_candidates=len(dense),
                candidates=len(candidates),
            )
            with db:
                db.execute(
                    "INSERT INTO results VALUES(?,?,?)",
                    (case.case_id, "hybrid", json.dumps(scored)),
                )
            rows = [json.loads(r[0]) for r in db.execute("SELECT json FROM results")]
            atomic_json(
                args.output / "summary.json",
                {
                    "scope": (
                        "actual returned complete literal fact support; "
                        "semantic alternatives require review"
                    ),
                    "quality_gate": "not_approved_draft_labels",
                    "completed": len(rows),
                    "total": len(cases),
                    "complete_literal_fact_support": statistics.mean(
                        r["answer_evidence_support_at_k"] for r in rows
                    ),
                    "mean_elapsed": statistics.mean(r["elapsed"] for r in rows),
                    "recipe": recipe,
                },
            )
            print(
                json.dumps({"completed": i, "total": len(cases), "elapsed": scored["elapsed"]}),
                flush=True,
            )


if __name__ == "__main__":
    main()
