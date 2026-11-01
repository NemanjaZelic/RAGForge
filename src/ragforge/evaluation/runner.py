"""Resumable actual-engine evaluation, with source binding and explicit draft status."""

import hashlib
import json
import sqlite3
import statistics
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any, Literal

from ragforge.artifacts.diagnostics import ingestion_diagnostics
from ragforge.core.contracts import RetrieveRequest
from ragforge.core.engine import BundleEngine
from ragforge.core.identity import document_id
from ragforge.core.resources import process_memory
from ragforge.core.source import is_link
from ragforge.evaluation.models import EvaluationCase
from ragforge.evaluation.scoring import score_response
from ragforge.evaluation.sources import EvidenceSources
from ragforge.jobs.build import atomic_json
from ragforge.jobs.ingest import job_lock
from ragforge.types import SearchMethod

SCORER_VERSION = "source-span-coverage-v1"


def read_cases(path: Path) -> list[EvaluationCase]:
    if path.stat().st_size > 128 * 1024**2:
        raise ValueError("evaluation case file exceeds 128 MiB")
    rows = [
        EvaluationCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    ids: set[str] = set()
    families: dict[str, str] = {}
    for row in rows:
        if row.case_id in ids:
            raise ValueError("duplicate evaluation case ID")
        ids.add(row.case_id)
        previous = families.setdefault(row.family_id, row.split)
        if previous != row.split:
            raise ValueError("source-family leakage between evaluation splits")
    return rows


def mean(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if key in row]
    return statistics.fmean(values) if values else None


def summarize(records: list[dict[str, Any]], *, strict: bool) -> dict[str, Any]:
    methods: dict[str, Any] = {}
    for method in sorted({str(row["method"]) for row in records}):
        rows = [row for row in records if row["method"] == method]
        valid = [row for row in rows if "error" not in row]
        seconds = sorted(float(row["seconds"]) for row in valid)
        negatives = [row for row in valid if row.get("negative_scoring") == "collection"]
        methods[method] = {
            "attempted": len(rows),
            "errors": len(rows) - len(valid),
            "positive_cases": sum("mrr_at_10" in row for row in valid),
            "document_recall_at_5": mean(valid, "document_recall_at_5"),
            "mrr_at_10": mean(valid, "mrr_at_10"),
            "evidence_group_coverage": mean(valid, "evidence_group_coverage"),
            "all_required_groups_covered": mean(valid, "all_required_groups_covered"),
            "collection_negative_cases": len(negatives),
            "collection_negatives_with_results": sum(
                not row["predicted_empty"] for row in negatives
            ),
            "context_negatives_not_global_scored": sum(
                row.get("negative_scoring") == "excluded_wrong_scope" for row in valid
            ),
            "seconds_p50": statistics.median(seconds) if seconds else None,
            "seconds_p95": seconds[min(len(seconds) - 1, int(0.95 * len(seconds)))]
            if seconds
            else None,
            "first_query_seconds": next((r["seconds"] for r in rows if "error" not in r), None),
            "unmapped_reference_chunks": sum(
                row.get("unmapped_reference_chunks", 0) for row in valid
            ),
            "ambiguous_reference_chunks": sum(
                row.get("ambiguous_reference_chunks", 0) for row in valid
            ),
        }
    return {
        "quality_gate": "reviewed_measurement_no_automatic_quality_threshold"
        if strict
        else "not_approved_draft_labels",
        "strict_scoring": strict,
        "scorer_version": SCORER_VERSION,
        "methods": methods,
        "process_memory": process_memory(),
        "latency_scope": (
            "query wall time; first query includes lazy setup; OS caches not cleared"
        ),
    }


def evaluate_bundle(
    artifact: Path,
    cases_file: Path,
    source_root: Path,
    output: Path,
    *,
    split: Literal["dev", "tuning", "test"] = "dev",
    track: str | None = None,
    methods: list[SearchMethod] | None = None,
    top_k: int = 10,
    max_output_chars: int = 16000,
    allow_draft: bool = False,
    pdf_reference_cache: Path | None = None,
    resume: bool = False,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    cases = [
        case
        for case in read_cases(cases_file)
        if case.split == split and (track is None or case.track == track)
    ]
    if not cases:
        raise ValueError("selected evaluation split is empty")
    strict = all(case.strict_scoring_eligible for case in cases)
    if not strict and not allow_draft:
        raise ValueError(
            "unreviewed labels require explicit --allow-draft; no strict score is approved"
        )
    request_probe = RetrieveRequest(
        query="validate", top_k=top_k, max_output_chars=max_output_chars
    )
    if top_k < 10:
        raise ValueError("MRR@10 evaluation requires top_k >= 10")
    if output.exists() and is_link(output.lstat()):
        raise ValueError("evaluation output must not be a link")
    if output.exists() and not resume:
        raise FileExistsError(
            "evaluation output exists; choose a new directory or explicitly resume"
        )
    if resume and not output.exists():
        raise ValueError("cannot resume missing evaluation output")
    output.mkdir(parents=True, exist_ok=True)
    with job_lock(output):
        opened = time.monotonic()
        engine = BundleEngine(artifact)
        constructor_seconds = time.monotonic() - opened
        selected = methods or list(engine.manifest.capabilities)
        if len(set(selected)) != len(selected) or not set(selected) <= set(
            engine.manifest.capabilities
        ):
            raise ValueError("unsupported or duplicate evaluation methods")
        inventory = {str(doc.source_path): doc for doc in engine.collection.documents}
        provider = EvidenceSources(source_root, pdf_reference_cache=pdf_reference_cache)
        for case in cases:
            if case.collection_id != engine.collection.collection_id:
                raise ValueError("evaluation cases belong to another collection")
            for group in case.evidence_groups:
                for target in group.any_of:
                    doc = inventory.get(target.source_path)
                    if (
                        doc is None
                        or doc.content_sha256 != target.source_sha256
                        or doc.document_id != document_id(case.collection_id, target.source_path)
                    ):
                        raise ValueError("evidence inventory does not match evaluated bundle")
                    provider.text(
                        target
                    )  # Validate frozen evidence before executing any retrieval.
        recipe = {
            "artifact_build_id": engine.manifest.build_id,
            "cases_sha256": hashlib.sha256(cases_file.read_bytes()).hexdigest(),
            "split": split,
            "track": track,
            "methods": selected,
            "top_k": request_probe.top_k,
            "max_output_chars": request_probe.max_output_chars,
            "allow_draft": allow_draft,
            "scorer_version": SCORER_VERSION,
            "minimum_evidence_coverage": 0.8,
        }
        metadata = output / "run.json"
        if metadata.exists():
            if is_link(metadata.lstat()) or metadata.stat().st_size > 1024**2:
                raise ValueError("unsafe evaluation run metadata")
            if not resume or json.loads(metadata.read_text(encoding="utf-8")) != recipe:
                raise ValueError("evaluation recipe changed; use a new output directory")
        else:
            atomic_json(metadata, recipe)
        database = output / "evaluation.sqlite"
        if database.exists() and is_link(database.lstat()):
            raise ValueError("evaluation database must not be a link")
        with closing(sqlite3.connect(database)) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS results(case_id TEXT,method TEXT,json TEXT NOT NULL,"
                "PRIMARY KEY(case_id,method))"
            )
            for method in selected:
                for number, case in enumerate(cases, 1):
                    if connection.execute(
                        "SELECT 1 FROM results WHERE case_id=? AND method=?", (case.case_id, method)
                    ).fetchone():
                        continue
                    started = time.monotonic()
                    try:
                        request = RetrieveRequest(
                            query=case.query,
                            collection_id=case.collection_id,
                            top_k=top_k,
                            max_output_chars=max_output_chars,
                            search_method=method,
                        )
                        response = engine.retrieve(request)
                        elapsed = time.monotonic() - started
                        record = score_response(
                            case, response, provider.text, evidence_cutoff=top_k
                        )
                        record.update(seconds=elapsed, method=method)
                        record["ranked_sources"] = [
                            {
                                "document_id": r.document_id,
                                "chunk_id": r.chunk_id,
                                "source": r.source.model_dump(mode="json"),
                            }
                            for r in response.results
                        ]
                    except (ValueError, OSError, RuntimeError) as error:
                        record = {
                            "case_id": case.case_id,
                            "method": method,
                            "seconds": time.monotonic() - started,
                            "error": type(error).__name__ + ": " + str(error)[:1000],
                        }
                    with connection:
                        connection.execute(
                            "INSERT INTO results VALUES(?,?,?)",
                            (case.case_id, method, json.dumps(record, ensure_ascii=True)),
                        )
                    if progress and (number % 25 == 0 or "error" in record):
                        progress(
                            {"method": method, "completed_cases": number, "total_cases": len(cases)}
                        )
            records = [
                json.loads(row[0])
                for row in connection.execute("SELECT json FROM results ORDER BY method,rowid")
            ]
        report = summarize(records, strict=strict)
        report["source_coverage"] = ingestion_diagnostics(engine.sqlite)
        report.update(
            recipe=recipe,
            collection_id=engine.collection.collection_id,
            selected_cases=len(cases),
            bundle_constructor_seconds=constructor_seconds,
        )
        atomic_json(output / "summary.json", report)
        return report
