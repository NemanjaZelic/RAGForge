"""Explicit warm-up loads the default runtime before serving, without user queries."""

from pathlib import Path

import pytest

from ragforge.artifacts.builder import build_bundle
from ragforge.core.contracts import RetrieveRequest
from ragforge.core.engine import BundleEngine

CORPUS = Path(__file__).resolve().parents[1] / "examples/mini-docs"


@pytest.mark.parametrize("backend", ["exact", "ann"])
def test_warm_up_preserves_first_actual_response(tmp_path, tiny_model, tiny_reranker, backend):
    bundle = tmp_path / "bundle"
    build_bundle(
        CORPUS,
        bundle,
        collection_id="docs",
        model_directory=tiny_model,
        reranker_directory=tiny_reranker,
        dense_backend=backend,
    )
    request = RetrieveRequest(query="rollback transaction token", top_k=10)
    reference = BundleEngine(bundle, threads=2, rerank_cache_batches=0).retrieve(request)
    prepared = BundleEngine(bundle, threads=2, rerank_cache_batches=16)
    assert prepared._embedder is prepared._dense is prepared._reranker is None
    assert prepared.warm_up() == {"query_model": True, "dense_index": True, "reranker": True}
    assert prepared._embedder is not None and prepared._dense is not None
    assert prepared._reranker is not None
    assert prepared.retrieve(request) == reference
    assert prepared.retrieve(request) == reference


def test_minimal_warm_up_remains_model_free(tmp_path, monkeypatch):
    from test_bundle import deny_ml

    bundle = tmp_path / "bundle"
    build_bundle(CORPUS, bundle, profile="minimal")
    deny_ml(monkeypatch)
    engine = BundleEngine(bundle)
    assert engine.warm_up() == {"query_model": False, "dense_index": False, "reranker": False}
    assert engine._embedder is engine._dense is engine._reranker is None
    assert engine.retrieve(RetrieveRequest(query="rollback")).results


@pytest.mark.parametrize("transport", ["stdio", "http"])
def test_cli_forwards_startup_resource_options(tmp_path, monkeypatch, transport):
    from typer.testing import CliRunner

    import ragforge.adapters.mcp as mcp
    import ragforge.shared.http as http
    from ragforge.cli import app

    calls = []

    class Server:
        def run(self, **kwargs):
            assert kwargs == {"transport": "stdio"}

    def capture(*args, **kwargs):
        calls.append(kwargs)
        return Server()

    monkeypatch.setattr(mcp, "create_server", capture)
    monkeypatch.setattr(http, "run_shared", capture)
    args = [
        "serve",
        str(tmp_path),
        "--threads",
        "8",
        "--rerank-workers",
        "8",
        "--rerank-cache-batches",
        "0",
        "--warm-up",
    ]
    if transport == "http":
        args += ["--transport", "http", "--auth-file", str(tmp_path / "auth.json")]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0]["warm_up"] is True
    assert calls[0]["threads"] == calls[0]["rerank_workers"] == 8
    assert calls[0]["rerank_cache_batches"] == 0


def test_stdio_warm_up_actual_offline_response(tmp_path, tiny_model, tiny_reranker):
    import asyncio

    from mcp_helpers import offline_client

    bundle = tmp_path / "bundle"
    build_bundle(CORPUS, bundle, model_directory=tiny_model, reranker_directory=tiny_reranker)
    request = RetrieveRequest(query="rollback token", top_k=2)
    expected = BundleEngine(bundle, rerank_cache_batches=0).retrieve(request)

    async def exercise():
        async with offline_client(bundle, tmp_path / "guard", warm_up=True) as client:
            result = await client.call_tool("search_docs", request.model_dump(mode="json"))
            assert not result.is_error
            assert result.structured_content == expected.model_dump(mode="json")

    asyncio.run(exercise())


def test_mcp_prepares_actual_engine_before_binding(
    tmp_path, tiny_model, tiny_reranker, monkeypatch
):
    import ragforge.adapters.mcp as adapter

    bundle = tmp_path / "bundle"
    build_bundle(CORPUS, bundle, model_directory=tiny_model, reranker_directory=tiny_reranker)
    engines = []
    original = BundleEngine.warm_up

    def warm(self):
        flags = original(self)
        engines.append(self)
        return flags

    monkeypatch.setattr(BundleEngine, "warm_up", warm)
    adapter.create_server(bundle, warm_up=True, rerank_cache_batches=0)
    assert len(engines) == 1
    assert engines[0]._dense is not None and engines[0]._reranker is not None
    assert engines[0]._reranker.cache_info()["capacity"] == 0
