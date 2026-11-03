"""Context mapping is a real portable engine mode, never a different QA lookup."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from ragforge.artifacts.builder import build_bundle
from ragforge.artifacts.recontextualize import recontextualize_bundle
from ragforge.artifacts.verification import build_identity, verify_bundle
from ragforge.core.chunk import ChunkConfig
from ragforge.core.contracts import RetrievalFilters, RetrieveRequest
from ragforge.core.embedding import file_hash
from ragforge.core.engine import BundleEngine


@pytest.mark.parametrize("backend", ["exact", "ann"])
def test_mapped_bundle_reuses_dense_bytes_and_returns_scoped_parent_text_offline(
    tmp_path: Path, tiny_model: Path, tiny_reranker: Path, offline_cli, backend: str
):
    source = tmp_path / "sources"
    source.mkdir()
    text = "\n".join(
        f"Protocol sentence {i}: rollback token transaction is required." for i in range(24)
    )
    (source / "guide.txt").write_text(text)
    (source / "other.txt").write_text("An unrelated secret access token is private.")
    child = tmp_path / "child"
    parent = tmp_path / "parent"
    before = build_bundle(
        source,
        child,
        collection_id="docs",
        model_directory=tiny_model,
        dense_backend=backend,
        chunk_config=ChunkConfig(chunk_size_chars=140, overlap_chars=30),
    )
    base = build_bundle(
        source,
        parent,
        collection_id="docs",
        profile="minimal",
        reranker_directory=tiny_reranker,
        chunk_config=ChunkConfig(chunk_size_chars=500, overlap_chars=100),
    )
    child_manifest = (child / "manifest.json").read_bytes()
    parent_manifest = (parent / "manifest.json").read_bytes()
    output = tmp_path / "mapped"
    result = recontextualize_bundle(child, parent, output)
    assert result.profile == "balanced" and result.default_search_method == "hybrid"
    dense = result.collections[0].dense_index
    assert dense.source_chunks.build_id == before.build_id
    assert file_hash(output / dense.path) == file_hash(child / dense.path)
    assert file_hash(output / result.collections[0].database_path) == file_hash(
        parent / base.collections[0].database_path
    )
    assert (child / "manifest.json").read_bytes() == child_manifest
    assert (parent / "manifest.json").read_bytes() == parent_manifest
    relocated = tmp_path / "relocated"
    shutil.copytree(output, relocated)
    engine = BundleEngine(relocated, threads=1)
    engine.retrieve(RetrieveRequest(query="rollback", search_method="bm25"))
    assert engine._embedder is None and engine._dense is None and engine._parents is None
    allowed = next(
        d.document_id for d in result.collections[0].documents if d.source_path == "guide.txt"
    )
    for method in ["dense", "hybrid"]:
        for rerank in [False, True]:
            response = engine.retrieve(
                RetrieveRequest(
                    query="rollback token",
                    search_method=method,
                    rerank=rerank,
                    filters=RetrievalFilters(document_ids=[allowed]),
                    top_k=5,
                    max_output_chars=16000,
                )
            )
            assert response.results
            assert all(c.document_id == allowed for c in response.results)
            assert any(len(c.text) > 140 for c in response.results)
            with engine.sqlite._connect() as c:
                for value in response.results:
                    row = c.execute(
                        "SELECT text,source_json FROM chunks WHERE chunk_id=?", (value.chunk_id,)
                    ).fetchone()
                    assert row["text"] == value.text
                    assert json.loads(row["source_json"]) == value.source.model_dump(mode="json")
    used = offline_cli(
        ["use", str(relocated), "--query", "rollback token", "--search-method", "hybrid"]
    )
    assert used.returncode == 0, used.stderr
    assert json.loads(used.stdout)["results"]
    with pytest.raises(FileExistsError):
        recontextualize_bundle(child, parent, output)
    with pytest.raises(ValueError, match="separate"):
        recontextualize_bundle(child, parent, child / "nested")
    # Inventory changes remain detectable even when all source identities match.
    path = relocated / dense.source_chunks.database_path
    with path.open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        verify_bundle(relocated)


def test_old_balanced_identity_omits_absent_mapping_metadata(tmp_path, tiny_model):
    output = tmp_path / "old"
    manifest = build_bundle(
        Path(__file__).resolve().parents[1] / "examples/mini-docs",
        output,
        model_directory=tiny_model,
    )
    data = manifest.model_dump(mode="json", exclude={"build_id", "retrieval_configuration"})
    del data["collections"][0]["dense_index"]["source_chunks"]
    expected = hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    assert manifest.build_id == expected == build_identity(manifest)
    saved = json.loads((output / "manifest.json").read_text())
    del saved["collections"][0]["dense_index"]["source_chunks"]
    (output / "manifest.json").write_text(json.dumps(saved))
    assert verify_bundle(output).build_id == expected


def test_mapping_requires_identical_versions_and_genuinely_larger_windows(tmp_path, tiny_model):
    source = tmp_path / "sources"
    source.mkdir()
    (source / "guide.txt").write_text("The original protocol requires rollback tokens.")
    child, same = tmp_path / "child", tmp_path / "same"
    config = ChunkConfig(chunk_size_chars=140, overlap_chars=30)
    build_bundle(
        source, child, collection_id="docs", model_directory=tiny_model, chunk_config=config
    )
    build_bundle(source, same, collection_id="docs", profile="minimal", chunk_config=config)
    output = tmp_path / "rejected"
    with pytest.raises(ValueError, match="larger context"):
        recontextualize_bundle(child, same, output)
    (source / "guide.txt").write_text(
        "A new protocol version changes the mandatory token behavior."
    )
    changed = tmp_path / "changed"
    build_bundle(source, changed, collection_id="docs", profile="minimal")
    with pytest.raises(ValueError, match="source inventories"):
        recontextualize_bundle(child, changed, output)
    assert not output.exists()
