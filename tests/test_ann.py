import builtins
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from ragforge.artifacts.builder import build_bundle
from ragforge.artifacts.verification import verify_bundle
from ragforge.core import ann
from ragforge.core.ann import read_header
from ragforge.core.contracts import RetrievalFilters, RetrieveRequest
from ragforge.core.engine import BundleEngine

CORPUS = Path(__file__).resolve().parents[1] / "examples/mini-docs"


def test_sharded_mapped_ann_scope_citations_and_bm25_without_optional_imports(
    tmp_path: Path,
    tiny_model: Path,
    monkeypatch,
):
    monkeypatch.setattr(ann, "SHARD_ROWS", 4)
    output = tmp_path / "bundle"
    manifest = build_bundle(
        CORPUS,
        output,
        collection_id="mini",
        model_directory=tiny_model,
        dense_backend="ann",
    )
    assert manifest.collections[0].dense_index.backend == ann.BACKEND
    assert verify_bundle(output) == manifest
    assert not (output / ".embeddings.npy").exists()
    copied = tmp_path / "moved bundle"
    shutil.copytree(output, copied)
    engine = BundleEngine(copied)
    for method in ("dense", "hybrid"):
        result = engine.retrieve(RetrieveRequest(query="rollback", search_method=method))
        assert result.results and all(r.retrieval_method == method for r in result.results)
        assert all(r.source.path.endswith((".md", ".txt", ".html")) for r in result.results)
        document = result.results[0].document_id
        filtered = engine.retrieve(
            RetrieveRequest(
                query="rollback",
                search_method=method,
                filters=RetrievalFilters(document_ids=[document]),
            )
        )
        assert filtered.results and all(r.document_id == document for r in filtered.results)
        assert not engine.retrieve(
            RetrieveRequest(
                query="rollback",
                search_method=method,
                filters=RetrievalFilters(document_ids=["f" * 64]),
            )
        ).results
    original = builtins.__import__

    def forbid(name, *args, **kwargs):
        if name.split(".")[0] in {"numpy", "onnxruntime", "tokenizers", "usearch", "numkong"}:
            raise AssertionError("ML import forbidden: " + name)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", forbid)
    lexical = BundleEngine(copied).retrieve(RetrieveRequest(query="rollback", search_method="bm25"))
    assert lexical.results


def test_filtered_ann_scoring_matches_exhaustive_stored_cosine(tmp_path: Path, tiny_model: Path):
    output = tmp_path / "bundle"
    build_bundle(
        CORPUS, output, collection_id="mini", model_directory=tiny_model, dense_backend="ann"
    )
    engine = BundleEngine(output)
    result = engine.retrieve(RetrieveRequest(query="token", search_method="dense"))
    document = result.results[0].document_id
    filtered = engine.retrieve(
        RetrieveRequest(
            query="token",
            search_method="dense",
            top_k=50,
            filters=RetrievalFilters(document_ids=[document]),
        )
    )
    store = engine._dense
    query = engine._embedder.encode(["token"], query=True)[0]
    expected = []
    with engine.sqlite._connect() as connection:
        for row in connection.execute(
            "SELECT rowid,chunk_id FROM chunks WHERE document_id=?", (document,)
        ):
            vector = store.indexes[0].get(int(row["rowid"]), dtype="f32")
            score = float(vector @ query / np.linalg.norm(vector))
            expected.append((row["chunk_id"], score))
    expected.sort(key=lambda item: (-item[1], item[0]))
    assert [r.chunk_id for r in filtered.results] == [key for key, _ in expected]
    assert np.allclose(
        [r.rank_score for r in filtered.results], [s for _, s in expected], atol=1e-6
    )


def test_ann_checkpoint_resumes_completed_shards(tmp_path: Path, tiny_model: Path, monkeypatch):
    monkeypatch.setattr(ann, "SHARD_ROWS", 4)
    output, job = tmp_path / "bundle", tmp_path / "job"

    def interrupt(event):
        if event["phase"] == "ann":
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        build_bundle(
            CORPUS,
            output,
            collection_id="mini",
            model_directory=tiny_model,
            dense_backend="ann",
            work_directory=job,
            progress=interrupt,
        )
    state = json.loads((job / "ann-progress.json").read_text())
    assert len(state["shards"]) == 1
    checksum = state["shards"][0]["sha256"]
    build_bundle(
        CORPUS,
        output,
        collection_id="mini",
        model_directory=tiny_model,
        dense_backend="ann",
        work_directory=job,
        resume=True,
    )
    engine = BundleEngine(output)
    assert engine.retrieve(RetrieveRequest(query="rollback")).results
    header = read_header(
        output / "collections/mini/dense.index",
        rows=engine.list_collections()[0].chunk_count,
        dimensions=engine.manifest.query_model.dimensions,
    )
    assert header.shards[0].sha256 == checksum
    assert len(header.shards) > 1


def test_ann_header_cannot_escape_container_or_change_scope(tmp_path: Path, tiny_model: Path):
    output = tmp_path / "bundle"
    build_bundle(
        CORPUS, output, collection_id="mini", model_directory=tiny_model, dense_backend="ann"
    )
    path = output / "collections/mini/dense.index"
    header = read_header(
        path, rows=BundleEngine(output).list_collections()[0].chunk_count, dimensions=4
    )
    with pytest.raises(ValueError, match="does not match"):
        read_header(path, rows=header.rows + 1, dimensions=4)
    with path.open("ab") as stream:
        stream.write(b"unexpected suffix")
    with pytest.raises(ValueError, match="size mismatch"):
        read_header(path, rows=header.rows, dimensions=4)
