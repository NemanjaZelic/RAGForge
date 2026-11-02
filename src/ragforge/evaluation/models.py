"""Explicit evidence locations, annotation scope, and immutable scoring inputs."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from ragforge.core.contracts import QueryText
from ragforge.core.identity import document_id
from ragforge.types import ContractModel, Identifier, RelativePath, Sha256

Canonicalizer = Literal[
    "collapse-whitespace-v1",
    "sphinx-main-html-data-collapse-whitespace-v1",
    "NFKC-casefold-alnum-v1",
]


class Evidence(ContractModel):
    source_path: RelativePath
    source_sha256: Sha256
    canonicalizer: Canonicalizer
    char_start: Annotated[int, Field(ge=0)]
    char_end: Annotated[int, Field(ge=1)]
    span_sha256: Sha256
    page: Annotated[int, Field(ge=1)] | None = None

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.char_end <= self.char_start:
            raise ValueError("evidence span must be nonempty and ordered")
        return self


class EvidenceGroup(ContractModel):
    any_of: Annotated[list[Evidence], Field(min_length=1, max_length=1000)]


class EvaluationCase(ContractModel):
    case_id: Annotated[str, Field(min_length=1, max_length=256)]
    corpus_id: Annotated[str, Field(min_length=1, max_length=128)]
    track: Annotated[str, Field(min_length=1, max_length=128)] = "retrieval"
    collection_id: Identifier
    family_id: Annotated[str, Field(min_length=1, max_length=256)]
    split: Literal["dev", "tuning", "test"]
    query: QueryText
    answerability: Literal["answerable", "unanswerable"]
    negative_scope: Literal["none", "collection", "provided-context", "unknown"] = "none"
    evidence_groups: Annotated[list[EvidenceGroup], Field(max_length=100)] = []
    review_status: Literal["ai_draft", "native_mapping_pending", "reviewed"]
    independent_reviewer: str | None = None
    strict_scoring_eligible: bool = False

    @model_validator(mode="after")
    def consistent_labels(self) -> Self:
        if self.answerability == "answerable" and not self.evidence_groups:
            raise ValueError("answerable cases require source evidence")
        if self.answerability == "unanswerable" and self.evidence_groups:
            raise ValueError("negative cases must not claim answer evidence")
        if self.strict_scoring_eligible and (
            self.review_status != "reviewed"
            or not (self.independent_reviewer or "").strip()
            or (self.answerability == "unanswerable" and self.negative_scope != "collection")
        ):
            raise ValueError(
                "strict scoring requires independent review and correct negative scope"
            )
        return self

    def relevant_document_ids(self) -> set[str]:
        return {
            document_id(self.collection_id, target.source_path)
            for group in self.evidence_groups
            for target in group.any_of
        }


class AnswerEvidence(ContractModel):
    """Versioned answer-bearing quotes; any source listed for a fact is acceptable.

    Annotations bind to a question hash. Version/time constraints belong in the
    explicit source choices and scope note; a matching keyword is never sufficient.
    """

    annotation_version: Literal["answer-evidence-v1"] = "answer-evidence-v1"
    case_id: Annotated[str, Field(min_length=1, max_length=256)]
    query_sha256: Sha256
    collection_id: Identifier
    facts: Annotated[list[EvidenceGroup], Field(min_length=1, max_length=100)]
    scope_note: Annotated[str, Field(min_length=1, max_length=4000)]
    review_status: Literal["ai_draft", "reviewed"] = "ai_draft"
    independent_reviewer: str | None = None
    strict_scoring_eligible: bool = False

    @model_validator(mode="after")
    def reviewed(self) -> Self:
        if self.strict_scoring_eligible and (
            self.review_status != "reviewed" or not (self.independent_reviewer or "").strip()
        ):
            raise ValueError("answer evidence requires independent review for strict scoring")
        return self
