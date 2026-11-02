"""Fact support is source-flexible, question-bound and separate from document recall."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from test_evaluation import case, chunk, target

from ragforge.artifacts.builder import build_bundle
from ragforge.core.contracts import RetrievalResponse
from ragforge.core.engine import BundleEngine
from ragforge.evaluation.models import AnswerEvidence, EvidenceGroup
from ragforge.evaluation.runner import evaluate_bundle
from ragforge.evaluation.scoring import score_answer_evidence, score_response


def annotation(query, facts):
    return AnswerEvidence(
        case_id=query.case_id,
        collection_id=query.collection_id,
        query_sha256=hashlib.sha256(query.query.encode()).hexdigest(),
        facts=[EvidenceGroup(any_of=group) for group in facts],
        scope_note="Both named documents are accepted for the same version and proposition.",
    )


def test_correct_alternative_source_counts_without_relaxing_fact_content():
    text = "The current protocol MUST NOT send credentials in the URL."
    a, b = target("original.txt", text), target("alternative.txt", text)
    query = case([[a]])
    labels = annotation(query, [[a, b]])
    response = RetrievalResponse(contract_version="1", results=[chunk("alternative.txt", text)])
    assert score_response(query, response, lambda t: text)["document_recall_at_5"] == 0
    assert score_answer_evidence(labels, query, response, lambda t: text)[
        "answer_evidence_support_at_k"
    ]
    # A similar sentence in a different, unapproved version is not automatically accepted.
    wrong = RetrievalResponse(contract_version="1", results=[chunk("old-version.txt", text)])
    assert not score_answer_evidence(labels, query, wrong, lambda t: text)[
        "answer_evidence_support_at_k"
    ]
    # Matching a keyword or losing a negation is insufficient.
    partial = RetrievalResponse(
        contract_version="1", results=[chunk("alternative.txt", "send credentials in the URL.")]
    )
    assert not score_answer_evidence(labels, query, partial, lambda t: text)[
        "answer_evidence_support_at_k"
    ]
    with pytest.raises(ValueError, match="question"):
        score_answer_evidence(
            labels, query.model_copy(update={"query": "different"}), response, lambda t: text
        )


def test_every_required_fact_must_be_complete():
    a, b = (
        "The first protocol uses TCP port 853.",
        "The second protocol requires both GET and POST.",
    )
    query = case([[target("a.txt", a)], [target("b.txt", b)]])
    labels = annotation(query, [[target("a.txt", a)], [target("b.txt", b)]])

    def source(t):
        return {"a.txt": a, "b.txt": b}[t.source_path]

    response = RetrievalResponse(contract_version="1", results=[chunk("a.txt", a)])
    score = score_answer_evidence(labels, query, response, source)
    assert score["answer_fact_coverage"] == 0.5
    assert not score["answer_evidence_support_at_k"]
    response = RetrievalResponse(
        contract_version="1", results=[chunk("a.txt", a), chunk("b.txt", b)]
    )
    assert score_answer_evidence(labels, query, response, source)["answer_evidence_support_at_k"]


def test_fact_annotations_are_preflighted_and_bound_to_resumed_evaluation(
    tmp_path: Path, monkeypatch
):
    root = tmp_path / "source"
    root.mkdir()
    body = "Alpha is the mandatory protocol for this service."
    (root / "a.txt").write_text(body)
    (root / "b.txt").write_text(body)
    query = case([[target("a.txt", body)]])
    bank = tmp_path / "cases.jsonl"
    bank.write_text(query.model_dump_json() + "\n")
    labels = annotation(query, [[target("a.txt", body), target("b.txt", body)]])
    answers = tmp_path / "answers.jsonl"
    answers.write_text(labels.model_dump_json() + "\n")
    bundle = tmp_path / "bundle"
    build_bundle(root, bundle, collection_id="docs", profile="minimal")
    output = tmp_path / "results"
    report = evaluate_bundle(
        bundle, bank, root, output, allow_draft=True, answer_evidence_file=answers
    )
    assert report["methods"]["bm25"]["answer_evidence_support_at_k"] == 1
    assert report["methods"]["bm25"]["answer_evidence_annotated_cases"] == 1
    assert report["quality_gate"] == "not_approved_draft_labels"

    def forbidden(*args, **kwargs):
        raise AssertionError("must not requery completed work")

    with monkeypatch.context() as patched:
        patched.setattr(BundleEngine, "retrieve", forbidden)
        same = evaluate_bundle(
            bundle, bank, root, output, allow_draft=True, answer_evidence_file=answers, resume=True
        )
        assert same["methods"] == report["methods"]
        answers.write_text(
            labels.model_copy(update={"scope_note": "Changed annotation policy"}).model_dump_json()
            + "\n"
        )
        with pytest.raises(ValueError, match="recipe changed"):
            evaluate_bundle(
                bundle,
                bank,
                root,
                output,
                allow_draft=True,
                answer_evidence_file=answers,
                resume=True,
            )
    answers.write_text(
        labels.model_copy(update={"query_sha256": "f" * 64}).model_dump_json() + "\n"
    )
    with pytest.raises(ValueError, match="question"):
        evaluate_bundle(
            bundle, bank, root, tmp_path / "bad", allow_draft=True, answer_evidence_file=answers
        )


def test_prepare_verbatim_alternatives_keeps_independent_review_pending(tmp_path: Path):
    script = Path(__file__).resolve().parents[1] / "scripts/prepare_answer_evidence.py"
    spec = importlib.util.spec_from_file_location("prepare_answer_evidence", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "source"
    root.mkdir()
    body = "Alpha is required for all requests under protocol version one."
    for name in ["a.txt", "b.txt"]:
        (root / name).write_text(body)
    query = case([[target("a.txt", body)]])
    bank = tmp_path / "cases.jsonl"
    bank.write_text(query.model_dump_json() + "\n")
    seeds = tmp_path / "seeds.json"
    seeds.write_text(
        json.dumps(
            {
                "cases_sha256": hashlib.sha256(bank.read_bytes()).hexdigest(),
                "facts": {"alpha": {"source_path": "a.txt", "quote": body}},
                "cases": {
                    query.case_id: {
                        "fact_keys": ["alpha"],
                        "scope_note": "Version one only; alternatives require review.",
                    }
                },
            }
        )
    )
    output = tmp_path / "labels.jsonl"
    audit = module.prepare(bank, seeds, root, output, split="dev", expand_verbatim=True)
    labels = AnswerEvidence.model_validate_json(output.read_text().strip())
    assert len(labels.facts[0].any_of) == 2
    assert audit["strict_scoring_eligible"] == 0
    assert not labels.strict_scoring_eligible and labels.review_status == "ai_draft"


def test_frozen_quality_comparison_runs_offline_and_rejects_runtime_tampering(
    tmp_path: Path, tiny_reranker: Path
):
    import subprocess
    import sys

    root = tmp_path / "source"
    root.mkdir()
    body = "Alpha is mandatory for all requests under protocol version one."
    (root / "a.txt").write_text(body)
    query = case([[target("a.txt", body)]])
    bank = tmp_path / "cases.jsonl"
    bank.write_text(query.model_dump_json() + "\n")
    facts = tmp_path / "answers.jsonl"
    facts.write_text(annotation(query, [[target("a.txt", body)]]).model_dump_json() + "\n")
    artifact = tmp_path / "bundle"
    build_bundle(
        root, artifact, collection_id="docs", profile="minimal", reranker_directory=tiny_reranker
    )
    output = tmp_path / "comparison"
    project = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        str(project / "scripts/run_quality_comparison.py"),
        "--artifact",
        str(artifact),
        "--cases",
        str(bank),
        "--answer-evidence",
        str(facts),
        "--source-root",
        str(root),
        "--output",
        str(output),
    ]
    run = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    safe = json.loads((output / "safe-summary.json").read_text())
    assert set(safe["stages"]) == {"raw", "reranked"}
    assert "Alpha is mandatory" not in (output / "safe-summary.json").read_text()
    assert safe["stages"]["reranked"]["methods"]["bm25"]["answer_evidence_support_at_k"] == 1
    frozen = output / "runtime/ragforge/core/engine.py"
    frozen.write_text(frozen.read_text() + "\n# tampered\n")
    resumed = subprocess.run(command + ["--resume"], capture_output=True, text=True, timeout=60)
    assert resumed.returncode != 0 and "frozen quality runtime changed" in resumed.stderr


def test_queued_followup_uses_frozen_offline_engine(
    tmp_path: Path, tiny_model: Path, tiny_reranker: Path
):
    import subprocess
    import sys

    root = tmp_path / "source"
    root.mkdir()
    body = "Alpha is mandatory for all requests under protocol version one."
    (root / "a.txt").write_text(body)
    query = case([[target("a.txt", body)]])
    bank = tmp_path / "cases.jsonl"
    bank.write_text(query.model_dump_json() + "\n")
    answers = tmp_path / "answers.jsonl"
    answers.write_text(annotation(query, [[target("a.txt", body)]]).model_dump_json() + "\n")
    artifact = tmp_path / "base"
    build_bundle(root, artifact, collection_id="docs", model_directory=tiny_model)
    state = tmp_path / "baseline-status.json"
    state.write_text(json.dumps({"state": "running"}))
    output = tmp_path / "followup"
    script = Path(__file__).resolve().parents[1] / "scripts/queue_quality_followup.py"
    command = [
        sys.executable,
        str(script),
        "--baseline",
        str(artifact),
        "--baseline-status",
        str(state),
        "--reranker",
        str(tiny_reranker),
        "--cases",
        str(bank),
        "--answers",
        str(answers),
        "--source",
        str(root),
        "--budget-root",
        str(tmp_path),
        "--output",
        str(output),
        "--poll-seconds",
        "0.1",
        "--reserve-free-bytes",
        "0",
    ]
    run = subprocess.run(command, capture_output=True, text=True, timeout=90)
    preparation_log = output / "prepare.log"
    assert run.returncode == 0, run.stderr + (
        preparation_log.read_text() if preparation_log.exists() else ""
    )
    assert (
        json.loads((output / "status.json").read_text())["state"]
        == "complete_diagnostic_draft_labels"
    )
    summary = json.loads((output / "comparison/safe-summary.json").read_text())
    assert set(summary["stages"]["reranked"]["methods"]) == {"bm25", "dense", "hybrid"}
    assert json.loads((output / "configuration.json").read_text())["publish_private"] is False


def test_source_cache_revalidates_each_fact_span(tmp_path: Path):
    from ragforge.evaluation.sources import EvidenceSources

    body = "Alpha is required. Beta is forbidden."
    (tmp_path / "a.txt").write_text(body)
    provider = EvidenceSources(tmp_path)
    first = target("a.txt", body, 0, 18)
    second = target("a.txt", body, 19, len(body))
    assert provider.text(first) == body
    assert provider.text(second) == body
    assert len(provider.text_cache) == 1
    with pytest.raises(ValueError, match="span hash"):
        provider.text(second.model_copy(update={"span_sha256": "0" * 64}))
