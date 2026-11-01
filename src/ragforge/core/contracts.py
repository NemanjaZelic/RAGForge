"""Version 1 draft retrieval contract shared by all future adapters."""

from typing import Annotated, Literal, Protocol, Self

from pydantic import Field, field_validator, model_validator

from ragforge.types import ContractModel, Identifier, RelativePath, SearchMethod, Sha256

PositiveInt = Annotated[int, Field(ge=1)]


class SourceLocation(ContractModel):
    path: RelativePath
    page: PositiveInt | None = None
    line_start: PositiveInt | None = None
    line_end: PositiveInt | None = None
    section: str | None = None

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
    query: Annotated[str, Field(min_length=1, max_length=8192)]
    collection_id: Identifier | None = None
    top_k: Annotated[int, Field(ge=1, le=50)] = 5
    max_output_chars: Annotated[int, Field(ge=1, le=100000)] = 16000
    filters: RetrievalFilters | None = None
    # None resolves to the bundle default; unsupported methods must raise.
    search_method: SearchMethod | None = None

    @field_validator("query")
    @classmethod
    def nonblank_query(cls, value: str) -> str:
        if not value.strip():
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


class RetrievalResponse(ContractModel):
    contract_version: Literal["1"]
    results: Annotated[list[RetrievedChunk], Field(max_length=50)]

    @model_validator(mode="after")
    def bounded_unique_results(self) -> Self:
        if sum(len(result.text) for result in self.results) > 100000:
            raise ValueError("total result text exceeds 100000 characters")
        keys = [(r.collection_id, r.chunk_id) for r in self.results]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate result chunk")
        return self


class FetchContextRequest(ContractModel):
    collection_id: Identifier
    chunk_id: Sha256
    neighbors: Annotated[int, Field(ge=0, le=5)] = 1
    max_output_chars: Annotated[int, Field(ge=1, le=100000)] = 16000


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
