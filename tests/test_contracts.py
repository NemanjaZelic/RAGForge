import hashlib
from typing import Any

import pytest
from pydantic import ValidationError

from ragforge.artifacts.manifest import BundleManifest
from ragforge.core.contracts import (
    FetchContextRequest,
    RetrievalResponse,
    RetrievedChunk,
    RetrieveRequest,
    SourceLocation,
)
from ragforge.core.identity import document_id

DIGEST = "a" * 64


def manifest_data() -> dict[str, Any]:
    return {
        "artifact_schema_version": "1",
        "build_id": DIGEST,
        "producer_version": "0.1.0.dev0",
        "profile": "minimal",
        "index_backend": "sqlite-fts5",
        "index_schema_version": 1,
        "sqlite_build_version": "3.49.1",
        "collections": [
            {
                "collection_id": "mini",
                "title": "Test collection",
                "database_path": "collections/mini/index.sqlite",
                "documents": [
                    {
                        "document_id": document_id("mini", "example.md"),
                        "source_path": "example.md",
                        "content_sha256": DIGEST,
                    }
                ],
            }
        ],
        "files": [
            {
                "path": "collections/mini/index.sqlite",
                "sha256": DIGEST,
                "size_bytes": 100,
            }
        ],
        "build_configuration": {
            "parser_version": "draft-1",
            "chunker_version": "draft-1",
            "chunk_size_chars": 1000,
            "overlap_chars": 100,
        },
        "runtime": {"python_min": "3.11", "requires_fts5": True, "adapters": ["cli"]},
        "licenses": ["test-fixture-only"],
    }


def test_manifest_round_trip() -> None:
    manifest = BundleManifest.model_validate(manifest_data())
    assert BundleManifest.model_validate_json(manifest.model_dump_json()) == manifest


@pytest.mark.parametrize(
    "change",
    [
        {"artifact_schema_version": "999"},
        {"profile": "balanced"},
        {"secret_token": "must-not-be-accepted"},
    ],
)
def test_manifest_rejects_unsupported_contract(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BundleManifest.model_validate({**manifest_data(), **change})


def test_manifest_requires_database_in_inventory() -> None:
    data = manifest_data()
    data["files"][0]["path"] = "unrelated.sqlite"
    with pytest.raises(ValidationError, match="inventoried path"):
        BundleManifest.model_validate(data)


def test_manifest_checks_document_identity_and_chunk_config() -> None:
    data = manifest_data()
    data["collections"][0]["documents"][0]["document_id"] = "b" * 64
    with pytest.raises(ValidationError, match="document_id"):
        BundleManifest.model_validate(data)
    data = manifest_data()
    data["build_configuration"]["overlap_chars"] = 1000
    with pytest.raises(ValidationError, match="overlap"):
        BundleManifest.model_validate(data)


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "../secret",
        "docs/../secret",
        "docs//file.md",
        "D:/secret",
        "docs\\file.md",
        "docs/./a",
        "CON.txt",
        "docs/a.",
        "docs/a ",
        "docs/a\x00.md",
        "cafe\u0301.md",
    ],
)
def test_source_rejects_nonportable_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        SourceLocation(path=path)


def test_known_line_ranges_and_unicode_source() -> None:
    source = SourceLocation(path="izvori/ćirilica.md", line_start=2, line_end=9)
    assert source.line_end == 9
    for values in ({"line_start": 2}, {"line_start": 10, "line_end": 2}, {"page": 0}):
        with pytest.raises(ValidationError):
            SourceLocation(path="doc.md", **values)


@pytest.mark.parametrize(
    "values",
    [
        {"query": ""},
        {"query": " \t\n"},
        {"query": "a" * 8193},
        {"query": "x", "top_k": 0},
        {"query": "x", "top_k": 51},
        {"query": "x", "top_k": True},
        {"query": "x", "max_output_chars": 100001},
        {"query": "x", "filters": {"sql": "anything"}},
    ],
)
def test_retrieve_request_limits(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RetrieveRequest.model_validate(values)


def test_context_request_bounds_and_exact_scope() -> None:
    with pytest.raises(ValidationError):
        FetchContextRequest(collection_id="mini", chunk_id=DIGEST, neighbors=6)
    with pytest.raises(ValidationError):
        FetchContextRequest.model_validate({"chunk_id": DIGEST})


def test_response_is_not_confidence_and_has_global_bounds() -> None:
    chunk = RetrievedChunk(
        collection_id="mini",
        document_id=DIGEST,
        chunk_id=DIGEST,
        text="evidence",
        source=SourceLocation(path="doc.md"),
        rank_score=-2.0,
        retrieval_method="bm25",
    )
    assert RetrievalResponse(contract_version="1", results=[chunk]).results[0].rank_score == -2.0
    with pytest.raises(ValidationError, match="duplicate"):
        RetrievalResponse(contract_version="1", results=[chunk, chunk])
    too_large = chunk.model_copy(update={"text": "x" * 100000})
    other = chunk.model_copy(update={"chunk_id": "b" * 64})
    with pytest.raises(ValidationError, match="total"):
        RetrievalResponse(contract_version="1", results=[too_large, other])


def test_document_identity_is_content_independent_and_collection_scoped() -> None:
    expected = hashlib.sha256(b'["ragforge-document-v1","mini","example.md"]').hexdigest()
    assert document_id("mini", "example.md") == expected
    assert document_id("mini", "renamed.md") != expected
    assert document_id("other", "example.md") != expected


def test_manifest_preserves_case_distinct_source_identity() -> None:
    data = manifest_data()
    collection = data["collections"][0]
    collection["documents"] = [
        {
            "document_id": document_id("mini", path),
            "source_path": path,
            "content_sha256": DIGEST,
        }
        for path in ["readme.txt", "Readme.txt", "Docs/a.txt", "docs/a.txt"]
    ]
    manifest = BundleManifest.model_validate(data)
    documents = manifest.collections[0].documents
    assert len({d.document_id for d in documents}) == 4
    assert [d.source_path for d in documents] == [
        "readme.txt",
        "Readme.txt",
        "Docs/a.txt",
        "docs/a.txt",
    ]
    collection["documents"].append(collection["documents"][0].copy())
    with pytest.raises(ValidationError, match="duplicate source path"):
        BundleManifest.model_validate(data)
