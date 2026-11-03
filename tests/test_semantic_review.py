"""Semantic judgments require actual returned proof and a full denominator."""

import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_answer_evidence import annotation
from test_evaluation import case, chunk, target

from ragforge.artifacts.builder import build_bundle
from ragforge.evaluation.review import (
    FactReview,
    ReviewObservation,
    ReviewProof,
    SemanticReview,
    summarize_reviews,
    validate_review,
)
from ragforge.evaluation.runner import evaluate_bundle


def observation(case_id="case:1"):
    return ReviewObservation(
        case_id=case_id,
        query_sha256="a" * 64,
        artifact_build_id="b" * 64,
        run_recipe_sha256="c" * 64,
        facts=["The service requires TCP on port 853."],
        chunks=[
            chunk(
                "another-current-source.txt", "Clients must connect using TCP port 853 by default."
            )
        ],
    )


def review(obs):
    return SemanticReview(
        case_id=obs.case_id,
        observation_sha256=obs.fingerprint(),
        reviewer="development reviewer",
        reviewer_kind="ai",
        facts=[
            FactReview(
                fact_index=0,
                verdict="supported",
                scope_matches_question=True,
                reason="Equivalent source explicitly supplies transport and default port.",
                proofs=[ReviewProof(chunk_id=obs.chunks[0].chunk_id, quote=obs.chunks[0].text)],
            )
        ],
    )


def test_equivalent_information_is_reviewable_without_exact_reference_quote():
    obs = observation()
    assert obs.facts[0] not in obs.chunks[0].text
    assert validate_review(obs, review(obs))
    result = summarize_reviews([obs], [review(obs)])
    assert result["supported_fraction_of_total"] == 1
    assert result["ai_reviewed_cases"] == 1
    assert result["human_reviewed_cases"] == 0
    assert result["automatic_quality_approval"] is False


def test_partial_reviews_cannot_report_a_small_reviewed_subset_as_full_accuracy():
    observations = [observation(f"case:{i}") for i in range(80)]
    result = summarize_reviews(observations, [review(observations[0])])
    assert result["pending_cases"] == 79
    assert result["supported_fraction_of_total"] == 1 / 80
    with pytest.raises(ValueError, match="duplicate"):
        summarize_reviews(observations, [review(observations[0])] * 2)


@pytest.mark.parametrize("change", ["query_sha256", "artifact_build_id", "run_recipe_sha256"])
def test_changed_observation_invalidates_review(change):
    obs = observation()
    with pytest.raises(ValueError, match="observation"):
        validate_review(obs.model_copy(update={change: "d" * 64}), review(obs))


@pytest.mark.parametrize("quote", ["          ", "TCP port 443 by default."])
def test_review_rejects_empty_or_invented_proof(quote):
    obs = observation()
    value = review(obs)
    value.facts[0].proofs[0].quote = quote
    with pytest.raises(ValueError, match="exact quote"):
        validate_review(obs, value)


def test_fact_scope_and_every_fact_are_required():
    obs = observation()
    value = review(obs)
    with pytest.raises(ValidationError, match="matching scope"):
        FactReview(
            fact_index=0,
            verdict="supported",
            scope_matches_question=False,
            proofs=value.facts[0].proofs,
            reason="This is an obsolete different protocol version.",
        )
    obs.facts.append("The service additionally requires mutual authentication.")
    value.observation_sha256 = obs.fingerprint()
    with pytest.raises(ValueError, match="every required fact"):
        validate_review(obs, value)
    value.facts.append(
        FactReview(
            fact_index=1,
            verdict="insufficient",
            scope_matches_question=True,
            reason="Returned passages do not establish mutual authentication.",
        )
    )
    assert not validate_review(obs, value)
    assert summarize_reviews([obs], [value])["supported_fraction_of_total"] == 0


def test_review_export_requires_complete_real_run_and_rejects_changed_sources(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/review_retrieval.py"
    spec = importlib.util.spec_from_file_location("review_export", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / "sources"
    source.mkdir()
    text = "Alpha is required for every protocol request."
    (source / "a.txt").write_text(text)
    query = case([[target("a.txt", text)]])
    bank = tmp_path / "cases.jsonl"
    bank.write_text(query.model_dump_json() + "\n")
    labels = annotation(query, [[target("a.txt", text)]])
    answers = tmp_path / "answers.jsonl"
    answers.write_text(labels.model_dump_json() + "\n")
    bundle = tmp_path / "bundle"
    build_bundle(source, bundle, collection_id="docs", profile="minimal")
    run = tmp_path / "evaluation"
    evaluate_bundle(bundle, bank, source, run, allow_draft=True, answer_evidence_file=answers)
    args = SimpleNamespace(
        artifact=bundle,
        run=run,
        cases=bank,
        answers=answers,
        source_root=source,
        method="bm25",
        output=tmp_path / "packets",
    )
    module.export(args)
    obs = ReviewObservation.model_validate_json((args.output / "observations.jsonl").read_text())
    assert obs.query_sha256 == hashlib.sha256(query.query.encode()).hexdigest()
    assert obs.chunks[0].text == text
    args.method = "dense"
    args.output = tmp_path / "incomplete"
    with pytest.raises(ValueError, match="every case"):
        module.export(args)
    assert not args.output.exists()
    args.method = "bm25"
    (source / "a.txt").write_text("Changed source")
    with pytest.raises(ValueError, match="source bytes"):
        module.export(args)
