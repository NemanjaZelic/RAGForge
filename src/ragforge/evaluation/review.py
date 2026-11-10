"""Traceable semantic reviews; literal-span diagnostics remain independent.

A review is a judgment, not a model confidence or automatic ground truth.
Proof quotes are mechanically bound to actual returned text and request identity.
"""

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from ragforge.core.contracts import RetrievedChunk
from ragforge.evaluation.sources import canonicalize
from ragforge.types import ContractModel, Sha256


class ReviewObservation(ContractModel):
    case_id: str
    query_sha256: Sha256
    artifact_build_id: Sha256
    run_recipe_sha256: Sha256
    facts: Annotated[list[str], Field(min_length=1, max_length=100)]
    chunks: Annotated[list[RetrievedChunk], Field(max_length=82)]

    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json")
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()


class ReviewProof(ContractModel):
    chunk_id: Sha256
    quote: Annotated[str, Field(min_length=10, max_length=5000)]


class FactReview(ContractModel):
    fact_index: Annotated[int, Field(ge=0, le=99)]
    verdict: Literal["supported", "insufficient", "contradicted"]
    proofs: Annotated[list[ReviewProof], Field(max_length=20)] = []
    scope_matches_question: bool
    reason: Annotated[str, Field(min_length=10, max_length=4000)]

    @model_validator(mode="after")
    def supported_needs_proof(self) -> Self:
        if self.verdict == "supported" and (not self.proofs or not self.scope_matches_question):
            raise ValueError("supported facts require cited evidence and matching scope")
        return self


class SemanticReview(ContractModel):
    review_version: Literal["semantic-evidence-review-v1"] = "semantic-evidence-review-v1"
    case_id: str
    observation_sha256: Sha256
    reviewer: Annotated[str, Field(min_length=1, max_length=256)]
    reviewer_kind: Literal["ai", "human", "mechanical"]
    facts: Annotated[list[FactReview], Field(min_length=1, max_length=100)]


def validate_review(observation: ReviewObservation, review: SemanticReview) -> bool:
    if (
        review.case_id != observation.case_id
        or review.observation_sha256 != observation.fingerprint()
    ):
        raise ValueError("semantic review does not match the actual retrieval observation")
    indexes = [fact.fact_index for fact in review.facts]
    if sorted(indexes) != list(range(len(observation.facts))):
        raise ValueError("semantic review must assess every required fact exactly once")
    chunks = {chunk.chunk_id: chunk for chunk in observation.chunks}
    if len(chunks) != len(observation.chunks):
        raise ValueError("observation contains duplicate returned chunks")
    for fact in review.facts:
        for proof in fact.proofs:
            chunk = chunks.get(proof.chunk_id)
            quote = canonicalize(proof.quote, "collapse-whitespace-v1").strip()
            if (
                not quote
                or chunk is None
                or quote not in canonicalize(chunk.text, "collapse-whitespace-v1")
            ):
                raise ValueError("review proof is not an exact quote from a returned chunk")
    return all(fact.verdict == "supported" for fact in review.facts)


def summarize_reviews(
    observations: list[ReviewObservation], reviews: list[SemanticReview]
) -> dict[str, object]:
    cases = {row.case_id: row for row in observations}
    if len(cases) != len(observations) or not cases:
        raise ValueError("empty or duplicate review observations")
    seen: set[str] = set()
    supported = ai = human = mechanical = 0
    for review in reviews:
        if review.case_id not in cases or review.case_id in seen:
            raise ValueError("unknown or duplicate semantic review")
        seen.add(review.case_id)
        supported += validate_review(cases[review.case_id], review)
        ai += review.reviewer_kind == "ai"
        human += review.reviewer_kind == "human"
        mechanical += review.reviewer_kind == "mechanical"
    return {
        "scope": "source-quoted semantic retrieval support judgment; not generated-answer accuracy",
        "quality_gate": "semantic_reviews_require_independent_validation",
        "total_cases": len(cases),
        "reviewed_cases": len(seen),
        "pending_cases": len(cases) - len(seen),
        "supported_reviewed_cases": supported,
        "not_supported_reviewed_cases": len(seen) - supported,
        "supported_fraction_of_total": supported / len(cases),
        "ai_reviewed_cases": ai,
        "human_reviewed_cases": human,
        "mechanically_supported_cases": mechanical,
        "target_good": 0.95,
        "target_excellent": 0.99,
        "automatic_quality_approval": False,
    }
