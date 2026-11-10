"""Version 1 draft retrieval contract shared by all future adapters."""

from typing import Annotated, Literal, Protocol, Self

from pydantic import Field, field_validator, model_validator

from ragforge.types import ContractModel, Identifier, RelativePath, SearchMethod, Sha256

PositiveInt = Annotated[int, Field(ge=1)]
QueryText = Annotated[str, Field(min_length=1, max_length=8192, strict=True)]
TopK = Annotated[int, Field(ge=1, le=50, strict=True)]
OutputChars = Annotated[int, Field(ge=1, le=100000, strict=True)]
Neighbors = Annotated[int, Field(ge=0, le=5, strict=True)]


class SourceLocation(ContractModel):
    path: RelativePath
    page: PositiveInt | None = None
    line_start: PositiveInt | None = None
    line_end: PositiveInt | None = None
    section: str | None = None
    url: Annotated[str, Field(max_length=4096, pattern=r"^https?://")] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @field_validator("url")
    @classmethod
    def source_url(cls, value: str | None) -> str | None:
        if value is not None:
            from ragforge.core.web_sources import normalize_url

            return normalize_url(value)
        return value

    @model_validator(mode="after")
    def ordered_lines(self) -> Self:
        if (self.line_start is None) != (self.line_end is None):
            raise ValueError("line_start and line_end must both be known or both be null")
        if self.line_start is not None and self.line_end is not None:
            if self.line_end < self.line_start:
                raise ValueError("line_end must not precede line_start")
        return self


class RetrievalFilters(ContractModel):
    document_ids: Annotated[list[Sha256], Field(min_length=1, max_length=100)]


class RetrieveRequest(ContractModel):
    query: QueryText
    # Caller-provided faithful translation; the runtime never calls a translation service.
    query_translation: QueryText | None = None
    collection_id: Identifier | None = None
    top_k: TopK = 5
    max_output_chars: OutputChars = 16000
    filters: RetrievalFilters | None = None
    # None resolves to the bundle default; unsupported methods must raise.
    search_method: SearchMethod | None = None
    rerank: Annotated[bool | None, Field(strict=True)] = None

    @field_validator("query", "query_translation")
    @classmethod
    def nonblank_query(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("query must not be blank")
        return value


class RetrievedChunk(ContractModel):
    collection_id: Identifier
    document_id: Sha256
    chunk_id: Sha256
    text: Annotated[str, Field(min_length=1, max_length=100000)]
    source: SourceLocation
    rank_score: float
    retrieval_method: SearchMethod
    # An attached context excerpt is an exact substring of this indexed chunk.
    # Offsets count Python Unicode characters, not bytes or model tokens.
    text_offset: Annotated[int | None, Field(ge=0, le=100000, strict=True)] = Field(
        default=None, exclude_if=lambda value: value is None
    )


class RetrievalResponse(ContractModel):
    contract_version: Literal["1"]
    results: Annotated[list[RetrievedChunk], Field(max_length=50)]
    context: Annotated[list[RetrievedChunk], Field(max_length=32)] = Field(
        default_factory=list,
        exclude_if=lambda value: not value,
    )

    def evidence_chunks(self, cutoff: int | None = None) -> list[RetrievedChunk]:
        primary = self.results if cutoff is None else self.results[:cutoff]
        # Ranked cutoffs stay ranked cutoffs. A full-response evidence check also
        # includes the explicitly returned, unranked context within the same budget.
        return (
            [*primary, *self.context] if cutoff is None or cutoff >= len(self.results) else primary
        )

    @model_validator(mode="after")
    def bounded_unique_results(self) -> Self:
        if sum(len(result.text) for result in self.evidence_chunks()) > 100000:
            raise ValueError("total result text exceeds 100000 characters")
        for extra in self.context:
            anchors = [
                r
                for r in self.results
                if (
                    r.collection_id == extra.collection_id
                    and r.document_id == extra.document_id
                    and r.source.path == extra.source.path
                    and r.source.page == extra.source.page
                    and r.source.section == extra.source.section
                )
            ]
            if not anchors:
                raise ValueError("context must match a same-page or same-section source result")
        keys = [(r.collection_id, r.chunk_id) for r in self.evidence_chunks()]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate result chunk")
        return self


class FetchContextRequest(ContractModel):
    collection_id: Identifier
    chunk_id: Sha256
    neighbors: Neighbors = 1
    max_output_chars: OutputChars = 16000


class CollectionDescription(ContractModel):
    collection_id: Identifier
    title: Annotated[str, Field(min_length=1, max_length=256)]
    document_count: Annotated[int, Field(ge=0)]
    chunk_count: Annotated[int, Field(ge=0)]


class RetrievalEngine(Protocol):
    """Implementations must enforce request-specific bounds and collection scope.

    Results use higher-is-better scores and deterministic chunk_id tie breaking.
    The response model enforces global bounds; the engine enforces request limits.
    """

    def retrieve(self, request: RetrieveRequest) -> RetrievalResponse: ...

    def fetch_context(self, request: FetchContextRequest) -> RetrievalResponse: ...

    def list_collections(self) -> list[CollectionDescription]: ...
