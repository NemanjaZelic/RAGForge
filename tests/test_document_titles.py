"""Document topics come from source text and cannot invent retrieval evidence."""

import json

import pytest

from ragforge.artifacts.builder import build_bundle
from ragforge.artifacts.recontextualize import recontextualize_bundle
from ragforge.artifacts.titles import apply_document_titles
from ragforge.artifacts.verification import build_identity, verify_bundle
from ragforge.core.chunk import ChunkConfig
from ragforge.core.contracts import RetrieveRequest
from ragforge.core.engine import BundleEngine
from ragforge.core.rerank import ONNXReranker
from ragforge.core.sqlite import SQLiteEngine


def test_title_metadata_is_source_bound_and_reaches_the_shared_reranker(
    tmp_path, tiny_model, tiny_reranker, monkeypatch
):
    source = tmp_path / "sources"
    source.mkdir()
    body = "# Protocol Handbook\n\n" + "Rollback tokens are required for every transaction. " * 15
    (source / "guide.md").write_text(body)
    child, parent, output = tmp_path / "child", tmp_path / "parent", tmp_path / "mapped"
    build_bundle(
        source,
        child,
        collection_id="docs",
        model_directory=tiny_model,
        chunk_config=ChunkConfig(chunk_size_chars=140, overlap_chars=20),
    )
    base = build_bundle(
        source, parent, collection_id="docs", profile="minimal", reranker_directory=tiny_reranker
    )
    document = base.collections[0].documents[0]
    rows = [
        {
            "source_path": document.source_path,
            "source_sha256": document.content_sha256,
            "title": "Protocol Handbook",
        }
    ]
    metadata = tmp_path / "titles.json"
    metadata.write_text(json.dumps(rows))
    manifest = recontextualize_bundle(child, parent, output, document_titles=metadata)
    assert manifest.collections[0].documents[0].title == "Protocol Handbook"
    assert verify_bundle(output).build_id == manifest.build_id
    seen = []
    original = ONNXReranker.score

    def score(self, query, passages):
        seen.extend(passages)
        return original(self, query, passages)

    monkeypatch.setattr(ONNXReranker, "score", score)
    engine = BundleEngine(output)
    response = engine.retrieve(RetrieveRequest(query="rollback tokens", search_method="hybrid"))
    assert response.results and seen
    assert all("guide.md\nProtocol Handbook\n" in text for text in seen)
    with engine.sqlite._connect() as connection:
        for chunk in response.results:
            assert (
                chunk.text
                == connection.execute(
                    "SELECT text FROM chunks WHERE chunk_id=?", (chunk.chunk_id,)
                ).fetchone()[0]
            )
    # Even a recomputed manifest checksum cannot approve invented topic metadata.
    manifest.collections[0].documents[0].title = "Invented unrelated service"
    manifest.build_id = build_identity(manifest)
    (output / "manifest.json").write_text(manifest.model_dump_json())
    with pytest.raises(ValueError, match="title differs"):
        verify_bundle(output)
    engine = SQLiteEngine(parent / base.collections[0].database_path)
    for bad in ["source_sha256", "title"]:
        changed = [dict(rows[0])]
        changed[0][bad] = (
            "f" * 64 if bad == "source_sha256" else "An invented title absent from source"
        )
        metadata.write_text(json.dumps(changed))
        with pytest.raises(ValueError, match="source|title"):
            apply_document_titles(base, engine, metadata)
    metadata.write_text(json.dumps(rows + rows))
    with pytest.raises(ValueError, match="duplicate"):
        apply_document_titles(base, engine, metadata)
