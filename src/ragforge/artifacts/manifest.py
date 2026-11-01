"""Minimal and balanced draft manifests. Schema validity is not bundle integrity verification."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from ragforge.core.identity import document_id
from ragforge.types import ContractModel, Identifier, RelativePath, SearchMethod, Sha256


class FileRecord(ContractModel):
    path: RelativePath
    sha256: Sha256
    size_bytes: Annotated[int, Field(ge=0)]


class DocumentRecord(ContractModel):
    document_id: Sha256
    source_path: RelativePath
    content_sha256: Sha256


class DenseIndex(ContractModel):
    path: RelativePath
    backend: Annotated[str, Field(min_length=1)]
    backend_version: Annotated[str, Field(min_length=1)]
    dimensions: Annotated[int, Field(ge=1, le=65536)]
    metric: Literal["cosine", "dot", "l2"]


class QueryModel(ContractModel):
    model_id: Annotated[str, Field(min_length=1)]
    revision: Annotated[str, Field(min_length=1)]
    runtime: Annotated[str, Field(min_length=1)]
    runtime_version: Annotated[str, Field(min_length=1)]
    dimensions: Annotated[int, Field(ge=1, le=65536)]
    files: Annotated[list[RelativePath], Field(min_length=1)]
    license: Annotated[str, Field(min_length=1)]


class CollectionManifest(ContractModel):
    collection_id: Identifier
    title: Annotated[str, Field(min_length=1, max_length=256)]
    database_path: RelativePath
    dense_index: DenseIndex | None = None
    documents: Annotated[list[DocumentRecord], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_document_identity(self) -> Self:
        paths = [doc.source_path for doc in self.documents]
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate source path in collection")
        for doc in self.documents:
            if doc.document_id != document_id(self.collection_id, doc.source_path):
                raise ValueError("document_id does not match collection and source path")
        return self


class BuildConfiguration(ContractModel):
    parser_version: Annotated[str, Field(min_length=1)]
    chunker_version: Annotated[str, Field(min_length=1)]
    chunk_size_chars: Annotated[int, Field(ge=1)]
    overlap_chars: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def overlap_is_smaller(self) -> Self:
        if self.overlap_chars >= self.chunk_size_chars:
            raise ValueError("overlap must be smaller than chunk size")
        return self


class RuntimeRequirements(ContractModel):
    python_min: Literal["3.11"]
    requires_fts5: Literal[True]
    adapters: Annotated[list[Literal["cli"]], Field(min_length=1, max_length=1)]


class BundleManifest(ContractModel):
    artifact_schema_version: Literal["1"]
    build_id: Sha256
    producer_version: Annotated[str, Field(min_length=1)]
    profile: Literal["minimal", "balanced"]
    capabilities: Annotated[list[SearchMethod], Field(min_length=1, max_length=3)] = ["bm25"]
    default_search_method: SearchMethod = "bm25"
    query_model: QueryModel | None = None
    index_backend: Literal["sqlite-fts5"]
    index_schema_version: Literal[1]
    sqlite_build_version: Annotated[str, Field(min_length=1)]
    collections: Annotated[list[CollectionManifest], Field(min_length=1, max_length=1)]
    files: Annotated[list[FileRecord], Field(min_length=1)]
    build_configuration: BuildConfiguration
    runtime: RuntimeRequirements
    licenses: Annotated[list[str], Field(min_length=1)]

    @model_validator(mode="after")
    def database_is_in_inventory(self) -> Self:
        paths = [record.path for record in self.files]
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate file inventory path")
        if any(path == "manifest.json" for path in paths):
            raise ValueError("manifest must not include its own checksum")
        collection = self.collections[0]
        expected = f"collections/{collection.collection_id}/index.sqlite"
        if collection.database_path != expected or expected not in paths:
            raise ValueError("collection database must have its canonical inventoried path")
        # Prevent case-insensitive aliases in a portable inventory.
        if len({path.casefold() for path in paths}) != len(paths):
            raise ValueError("case collision in file inventory")
        if any(path.split("/")[0].casefold() == "manifest.json" for path in paths):
            raise ValueError("manifest path is reserved")
        for path in paths:
            if any(other.startswith(path + "/") for other in paths):
                raise ValueError("inventory file cannot also be a directory")
        capabilities = set(self.capabilities)
        if len(capabilities) != len(self.capabilities):
            raise ValueError("duplicate search capability")
        if self.profile == "minimal":
            if capabilities != {"bm25"} or self.default_search_method != "bm25":
                raise ValueError("minimal profile requires only bm25")
            if self.query_model is not None or collection.dense_index is not None:
                raise ValueError("minimal profile cannot contain dense configuration")
        else:
            if capabilities != {"bm25", "dense", "hybrid"}:
                raise ValueError("balanced profile requires bm25, dense and hybrid capabilities")
            if self.default_search_method != "hybrid":
                raise ValueError("balanced profile requires hybrid as default")
            model, dense = self.query_model, collection.dense_index
            if model is None or dense is None:
                raise ValueError("balanced profile requires local query model and dense index")
            if dense.dimensions != model.dimensions:
                raise ValueError("model and dense index dimensions must match")
            if dense.path != f"collections/{collection.collection_id}/dense.index":
                raise ValueError("dense index must have its canonical path")
            if dense.path not in paths:
                raise ValueError("dense index must be inventoried")
            if len(set(model.files)) != len(model.files):
                raise ValueError("duplicate query model file")
            if any(not path.startswith("models/query/") for path in model.files):
                raise ValueError("query model files must be under models/query/")
            if any(path not in paths for path in model.files):
                raise ValueError("query model files must be inventoried")
        return self
