import hashlib
import json
from pathlib import Path

import pytest

from ragforge.artifacts.builder import build_bundle
from ragforge.artifacts.diagnostics import ingestion_diagnostics
from ragforge.core.contracts import RetrievalResponse, RetrievedChunk, SourceLocation
from ragforge.core.engine import BundleEngine
from ragforge.core.identity import document_id
from ragforge.evaluation.models import EvaluationCase, Evidence, EvidenceGroup
from ragforge.evaluation.runner import evaluate_bundle, read_cases
from ragforge.evaluation.scoring import score_response
from ragforge.jobs.ingest import ingest_corpus


def target(path: str, body: str, start: int = 0, end: int | None = None):
    end = len(body) if end is None else end
    return Evidence(
        source_path=path,
        source_sha256=hashlib.sha256(body.encode()).hexdigest(),
        canonicalizer="collapse-whitespace-v1",
        char_start=start,
        char_end=end,
        span_sha256=hashlib.sha256(body[start:end].encode()).hexdigest(),
    )


def case(groups, **kwargs):
    return EvaluationCase(
        case_id="case:1",
        corpus_id="original",
        collection_id="docs",
        family_id="family",
        split="dev",
        query="alpha beta",
        answerability="answerable",
        evidence_groups=[EvidenceGroup(any_of=group) for group in groups],
        review_status="ai_draft",
        **kwargs,
    )


def chunk(path: str, text: str, page: int | None = None):
    return RetrievedChunk(
        collection_id="docs",
        document_id=document_id("docs", path),
        chunk_id=hashlib.sha256((path + text + str(page)).encode()).hexdigest(),
        text=text,
        source=SourceLocation(path=path, page=page),
        rank_score=1.0,
        retrieval_method="bm25",
    )


def test_document_hit_cannot_replace_required_multi_document_evidence():
    a, b = target("a.txt", "alpha evidence"), target("b.txt", "beta evidence")
    query = case([[a], [b]])

    def source(t):
        return {"a.txt": "alpha evidence", "b.txt": "beta evidence"}[t.source_path]

    one = score_response(
        query,
        RetrievalResponse(contract_version="1", results=[chunk("a.txt", "alpha evidence")]),
        source,
    )
    assert one["mrr_at_10"] == 1 and one["document_recall_at_5"] == 0.5
    assert one["evidence_group_coverage"] == 0.5 and not one["all_required_groups_covered"]
    both = score_response(
        query,
        RetrievalResponse(
            contract_version="1",
            results=[chunk("a.txt", "alpha evidence"), chunk("b.txt", "beta evidence")],
        ),
        source,
    )
    assert both["all_required_groups_covered"] and both["document_recall_at_5"] == 1


def test_repeated_text_and_wrong_page_do_not_receive_favorable_evidence_locations():
    evidence = target("a.pdf", "same same", 0, 4).model_copy(update={"page": 1})
    query = case([[evidence]])
    repeated = score_response(
        query,
        RetrievalResponse(contract_version="1", results=[chunk("a.pdf", "same", 1)]),
        lambda t: "same same",
    )
    assert (
        repeated["ambiguous_reference_chunks"] == 1 and not repeated["all_required_groups_covered"]
    )
    wrong_page = score_response(
        query,
        RetrievalResponse(contract_version="1", results=[chunk("a.pdf", "same", 2)]),
        lambda t: "same same",
    )
    assert wrong_page["evidence_group_coverage"] == 0
    with pytest.raises(ValueError, match="hash mismatch"):
        score_response(
            query, RetrievalResponse(contract_version="1", results=[]), lambda t: "changed text"
        )


def test_native_context_negative_is_not_a_global_negative():
    query = EvaluationCase(
        case_id="negative",
        corpus_id="native",
        collection_id="docs",
        family_id="family",
        split="dev",
        query="question",
        answerability="unanswerable",
        negative_scope="provided-context",
        review_status="native_mapping_pending",
    )
    result = score_response(
        query, RetrievalResponse(contract_version="1", results=[]), lambda t: ""
    )
    assert result["negative_scoring"] == "excluded_wrong_scope"
    with pytest.raises(ValueError, match="strict scoring"):
        EvaluationCase.model_validate({**query.model_dump(), "strict_scoring_eligible": True})


def test_actual_bundle_evaluation_draft_gate_and_resume_without_requery(
    tmp_path: Path, monkeypatch
):
    source = tmp_path / "source"
    source.mkdir()
    a, b = "alpha evidence", "beta evidence"
    (source / "a.txt").write_text(a)
    (source / "b.txt").write_text(b)
    bundle = tmp_path / "bundle"
    build_bundle(source, bundle, collection_id="docs", profile="minimal")
    positive = case([[target("a.txt", a)], [target("b.txt", b)]])
    negative = EvaluationCase(
        case_id="negative",
        corpus_id="original",
        collection_id="docs",
        family_id="negative",
        split="dev",
        query="absent_z42",
        answerability="unanswerable",
        negative_scope="collection",
        review_status="ai_draft",
    )
    cases = tmp_path / "cases.jsonl"
    cases.write_text(positive.model_dump_json() + "\n" + negative.model_dump_json() + "\n")
    output = tmp_path / "results"
    with pytest.raises(ValueError, match="allow-draft"):
        evaluate_bundle(bundle, cases, source, output)
    report = evaluate_bundle(bundle, cases, source, output, allow_draft=True)
    assert report["quality_gate"] == "not_approved_draft_labels" and not report["strict_scoring"]
    assert report["methods"]["bm25"]["document_recall_at_5"] == 1
    assert report["methods"]["bm25"]["all_required_groups_covered"] == 1
    assert report["methods"]["bm25"]["collection_negatives_with_results"] == 0
    assert report["source_coverage"]["indexed_documents"] == 2

    def forbidden(*args, **kwargs):
        raise AssertionError("resumed completed evaluation must not query again")

    with monkeypatch.context() as patched:
        patched.setattr(BundleEngine, "retrieve", forbidden)
        resumed = evaluate_bundle(bundle, cases, source, output, allow_draft=True, resume=True)
    assert resumed["methods"] == report["methods"]
    changed = positive.model_copy(update={"query": "changed query"})
    cases.write_text(changed.model_dump_json() + "\n" + negative.model_dump_json() + "\n")
    with pytest.raises(ValueError, match="recipe changed"):
        evaluate_bundle(bundle, cases, source, output, allow_draft=True, resume=True)


def test_label_drift_and_split_leakage_are_rejected(tmp_path: Path):
    item = case([[target("a.txt", "alpha")]])
    path = tmp_path / "cases.jsonl"
    other = item.model_copy(update={"case_id": "second", "split": "test"})
    path.write_text(item.model_dump_json() + "\n" + other.model_dump_json() + "\n")
    with pytest.raises(ValueError, match="leakage"):
        read_cases(path)
    with pytest.raises(ValueError, match="strict scoring"):
        EvaluationCase.model_validate({**item.model_dump(), "strict_scoring_eligible": True})


def test_failed_documents_remain_visible_in_opted_in_artifact_inventory(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_bytes(b"\xffunreadable")
    (source / "b.txt").write_text("valid evidence")
    job, bundle = tmp_path / "ingest", tmp_path / "bundle"
    ingest_corpus(source, job, collection_id="docs", continue_on_error=True)
    build_bundle(
        source,
        bundle,
        collection_id="docs",
        profile="minimal",
        ingest_job=job,
        allow_failed_documents=True,
        allow_incomplete=True,
    )
    engine = BundleEngine(bundle)
    assert len(engine.collection.documents) == 2
    diagnostics = ingestion_diagnostics(engine.sqlite)
    assert diagnostics["source_documents"] == 2 and diagnostics["indexed_documents"] == 1
    assert diagnostics["failed_documents_retained"] == 1
    assert not diagnostics["all_sources_have_searchable_text"]
    with engine.sqlite._connect() as connection:
        warnings = json.loads(
            connection.execute(
                "SELECT warnings_json FROM documents WHERE source_path='a.txt'"
            ).fetchone()[0]
        )
    assert warnings[0].startswith("SOURCE NOT INDEXED")
