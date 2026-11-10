"""Rank and evidence coverage metrics; never infer facts from answer-model memory."""

import hashlib
from collections.abc import Callable
from typing import Any

from ragforge.core.contracts import RetrievalResponse, RetrievedChunk
from ragforge.core.identity import document_id
from ragforge.evaluation.models import AnswerEvidence, EvaluationCase, Evidence, EvidenceGroup
from ragforge.evaluation.sources import canonicalize


def covered_length(intervals: list[tuple[int, int]]) -> int:
    length = 0
    right = -1
    for start, stop in sorted(intervals):
        length += max(0, stop - max(start, right))
        right = max(right, stop)
    return length


def score_evidence_pool(
    collection_id: str,
    evidence_groups: list[EvidenceGroup],
    results: list[RetrievedChunk],
    source: Callable[[Evidence], str],
) -> dict[str, Any]:
    """Evidence coverage over a diagnostic pool; never label it returned-answer accuracy."""
    if not evidence_groups or len(results) > 5000:
        raise ValueError("invalid diagnostic evidence pool size")
    if any(result.collection_id != collection_id for result in results):
        raise ValueError("retrieval escaped the evaluated collection")
    groups: list[float] = []
    mapped = ambiguous = unmapped = 0
    for group in evidence_groups:
        alternatives = []
        for target in group.any_of:
            original = source(target)
            if (
                target.char_end > len(original)
                or hashlib.sha256(
                    original[target.char_start : target.char_end].encode()
                ).hexdigest()
                != target.span_sha256
            ):
                raise ValueError("scoring evidence source/span hash mismatch")
            intervals: list[tuple[int, int]] = []
            for result in results:
                if (
                    result.document_id != document_id(collection_id, target.source_path)
                    or result.source.path != target.source_path
                    or result.source.page != target.page
                ):
                    continue
                snippet = canonicalize(result.text, target.canonicalizer).strip()
                start = original.find(snippet) if snippet else -1
                if start < 0:
                    unmapped += 1
                    continue
                if original.find(snippet, start + 1) >= 0:
                    ambiguous += 1  # Do not choose a favorable repeated occurrence.
                    continue
                mapped += 1
                stop = start + len(snippet)
                left, right = max(start, target.char_start), min(stop, target.char_end)
                if left < right:
                    intervals.append((left, right))
            alternatives.append(covered_length(intervals) / (target.char_end - target.char_start))
        groups.append(max(alternatives))
    return {
        "group_coverages": groups,
        "mapped_reference_chunks": mapped,
        "ambiguous_reference_chunks": ambiguous,
        "unmapped_reference_chunks": unmapped,
    }


def score_response(
    case: EvaluationCase,
    response: RetrievalResponse,
    source: Callable[[Evidence], str],
    *,
    evidence_cutoff: int = 10,
    minimum_coverage: float = 0.8,
) -> dict[str, Any]:
    if not 1 <= evidence_cutoff <= 50 or not 0 < minimum_coverage <= 1:
        raise ValueError("invalid evidence scoring bounds")
    if any(result.collection_id != case.collection_id for result in response.evidence_chunks()):
        raise ValueError("retrieval escaped the evaluated collection")
    record: dict[str, Any] = {
        "case_id": case.case_id,
        "track": case.track,
        "returned": len(response.results),
    }
    if case.answerability == "unanswerable":
        if case.negative_scope != "collection":
            record.update(
                negative_scoring="excluded_wrong_scope", predicted_empty=not response.results
            )
        else:
            record.update(negative_scoring="collection", predicted_empty=not response.results)
        return record
    relevant = case.relevant_document_ids()
    ranked = [r.document_id for r in response.results]
    first = next((i for i, key in enumerate(ranked[:10], 1) if key in relevant), None)
    coverage = score_evidence_pool(
        case.collection_id, case.evidence_groups, response.evidence_chunks(evidence_cutoff), source
    )
    groups = coverage["group_coverages"]
    record.update(
        document_recall_at_5=len(set(ranked[:5]) & relevant) / len(relevant),
        mrr_at_10=1 / first if first is not None else 0,
        evidence_group_coverage=sum(groups) / len(groups),
        all_required_groups_covered=all(value >= minimum_coverage for value in groups),
        group_coverages=groups,
        mapped_reference_chunks=coverage["mapped_reference_chunks"],
        ambiguous_reference_chunks=coverage["ambiguous_reference_chunks"],
        unmapped_reference_chunks=coverage["unmapped_reference_chunks"],
    )
    return record


def score_answer_evidence(
    annotation: AnswerEvidence,
    case: EvaluationCase,
    response: RetrievalResponse,
    source: Callable[[Evidence], str],
    *,
    evidence_cutoff: int = 10,
) -> dict[str, Any]:
    """Credit complete, source-verified facts from any explicitly accepted citation.

    This measures retrieved support, not the truthfulness of a generated answer.
    Partial quotations do not count as complete facts (e.g. dropping a negation).
    """
    if (
        annotation.case_id != case.case_id
        or annotation.collection_id != case.collection_id
        or annotation.query_sha256 != hashlib.sha256(case.query.encode()).hexdigest()
        or case.answerability != "answerable"
    ):
        raise ValueError("answer evidence does not match the evaluated question")
    fact_case = case.model_copy(update={"evidence_groups": annotation.facts})
    scored = score_response(
        fact_case, response, source, evidence_cutoff=evidence_cutoff, minimum_coverage=1.0
    )
    return {
        "answer_evidence_support_at_k": scored["all_required_groups_covered"],
        "answer_fact_coverage": scored["evidence_group_coverage"],
        "answer_fact_coverages": scored["group_coverages"],
        "answer_facts": len(annotation.facts),
        "answer_ambiguous_chunks": scored["ambiguous_reference_chunks"],
        "answer_evidence_independently_reviewed": annotation.strict_scoring_eligible,
    }
