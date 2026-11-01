"""Minimal-profile manifest. Schema validity is not bundle integrity verification."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from ragforge.core.identity import document_id
from ragforge.types import ContractModel, Identifier, RelativePath, Sha256


class FileRecord(ContractModel):
    path: RelativePath
    sha256: Sha256
    size_bytes: Annotated[int, Field(ge=0)]


class DocumentRecord(ContractModel):
    document_id: Sha256
    source_path: RelativePath
    content_sha256: Sha256


class CollectionManifest(ContractModel):
    collection_id: Identifier
    title: Annotated[str, Field(min_length=1, max_length=256)]
    database_path: RelativePath
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
    profile: Literal["minimal"]
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
        return self
