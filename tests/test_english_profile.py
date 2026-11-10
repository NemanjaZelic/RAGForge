"""Explicit English-documentation setup, portable tuning and real MCP behavior."""

import asyncio
import hashlib
import importlib
import json
import shutil
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from ragforge.adapters.integration import create_integration
from ragforge.artifacts.builder import build_bundle
from ragforge.artifacts.verification import verify_bundle
from ragforge.core.contracts import RetrieveRequest
from ragforge.core.engine import BundleEngine
from ragforge.core.rerank import reranker_spec
from ragforge.quickstart import ModelPaths, model_paths, ready_documentation

CORPUS = Path(__file__).resolve().parents[1] / "examples/mini-docs"


def test_portable_english_configuration_and_actual_mcp(tmp_path, tiny_model, tiny_reranker):
    before = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in tiny_reranker.iterdir()
        if p.is_file()
    }
    original_batch = reranker_spec(tiny_reranker).batch_size
    bundle = tmp_path / "English bundle"
    manifest = build_bundle(
        CORPUS,
        bundle,
        model_directory=tiny_model,
        reranker_directory=tiny_reranker,
        rerank_batch_size=1,
        query_planning="facets-v3",
        section_context="section-gaps-v3",
        query_language="en",
        threads=1,
    )
    verify_bundle(bundle)
    assert reranker_spec(bundle / "models/reranker").batch_size == 1
    assert reranker_spec(tiny_reranker).batch_size == original_batch
    assert before == {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in tiny_reranker.iterdir()
        if p.is_file()
    }
    assert manifest.retrieval_configuration.query_language == "en"
    engine = BundleEngine(bundle, threads=1, rerank_cache_batches=0)
    query = "How are access tokens sent?"
    request = RetrieveRequest(query=query, top_k=50, max_output_chars=48000)
    expected = engine.retrieve(request)
    assert (
        engine.retrieve(
            request.model_copy(update={"query": "Како се шаљу токени?", "query_translation": query})
        )
        == expected
    )
    with pytest.raises(ValueError, match="hybrid"):
        engine.retrieve(
            request.model_copy(update={"query_translation": query, "search_method": "bm25"})
        )
    with pytest.raises(ValueError, match="hybrid"):
        engine.retrieve(request.model_copy(update={"query_translation": query, "rerank": False}))
    output = tmp_path / "agent"
    result = create_integration(bundle, output, threads=1, rerank_workers=1, warm_up=True)
    skill = output / result["skill"]
    text = skill.read_text(encoding="utf-8")
    assert "faithful English question" in text and "without `query_translation`" in text
    metadata = json.loads((skill.parent / "references/collection.json").read_text(encoding="utf-8"))
    assert metadata["recommended_query_language"] == "en"
    assert metadata["recommended_search_request"]["top_k"] == 50
    server = next(
        iter(json.loads((output / "mcp.json").read_text(encoding="utf-8"))["mcpServers"].values())
    )

    async def exercise():
        async with Client(StdioServerParameters(**server), read_timeout_seconds=40) as client:
            actual = await client.call_tool(
                "search_docs", request.model_dump(mode="json", exclude_none=True)
            )
            assert not actual.is_error
            assert actual.structured_content == expected.model_dump(mode="json")

    asyncio.run(asyncio.wait_for(exercise(), timeout=50))


def test_quickstart_english_build_and_legacy_state(tmp_path, tiny_model, tiny_reranker):
    project = tmp_path / "project"
    project.mkdir()
    state = project / ".cache/quickstart"
    state.mkdir(parents=True)
    ranker = tmp_path / "english"
    shutil.copytree(tiny_reranker, ranker)
    descriptor = ranker / "reranker.json"
    spec = json.loads(descriptor.read_text(encoding="utf-8"))
    spec["model_id"] = "cross-encoder/ms-marco-MiniLM-L6-v2"
    descriptor.write_text(json.dumps(spec), encoding="utf-8")
    record = ModelPaths(query_model=str(tiny_model), reranker=str(ranker), document_language="en")
    (state / "models.json").write_text(record.model_dump_json(), encoding="utf-8")
    bundle = ready_documentation(project, CORPUS, threads=1)
    engine = BundleEngine(bundle, threads=1)
    assert engine.manifest.retrieval_configuration.query_language == "en"
    assert engine.manifest.retrieval_configuration.section_context == "section-gaps-v3"
    assert engine._get_reranker().spec.batch_size == 1
    assert reranker_spec(ranker).batch_size == spec["batch_size"]
    (state / "models.json").write_text(
        json.dumps({"query_model": str(tiny_model), "reranker": str(tiny_reranker)}),
        encoding="utf-8",
    )
    assert model_paths(project).document_language == "multilingual"
    legacy = ready_documentation(project, CORPUS, threads=1)
    data = json.loads((legacy / "manifest.json").read_text(encoding="utf-8"))
    assert "query_language" not in data["retrieval_configuration"]
    assert (
        reranker_spec(legacy / "models/reranker").batch_size
        == reranker_spec(tiny_reranker).batch_size
    )


def test_setup_english_selection_and_failed_switch_are_atomic(
    tmp_path, tiny_model, tiny_reranker, monkeypatch
):
    monkeypatch.syspath_prepend(str(CORPUS.parents[1] / "scripts"))
    setup = importlib.import_module("setup_models")
    calls = []

    def prepared(destination, **kwargs):
        calls.append((destination, kwargs))
        if "reranker" in destination.name and len(calls) > 2:
            raise ValueError("missing English model")
        return destination.absolute()

    monkeypatch.setattr(setup, "prepare", prepared)
    paths = setup.setup_models(tmp_path, tmp_path / "models", offline=True, document_language="en")
    assert paths.document_language == "en"
    assert calls[1][0].name == "ms-marco-minilm-reranker"
    assert calls[1][1]["script_args"] == ["--model", "minilm-l6"]
    assert calls[1][1]["expected_id"] == setup.ENGLISH_MODEL
    assert calls[1][1]["offline"] is True
    state = tmp_path / ".cache/quickstart/models.json"
    before = state.read_bytes()
    with pytest.raises(ValueError, match="missing"):
        setup.setup_models(tmp_path, tmp_path / "models", offline=True, document_language="en")
    assert state.read_bytes() == before


@pytest.mark.parametrize(
    "kwargs",
    [
        {"rerank_batch_size": 0},
        {"rerank_batch_size": True},
        {"query_language": "sr"},
        {"section_context": "unknown"},
    ],
)
def test_invalid_portable_tuning_never_publishes(tmp_path, tiny_model, tiny_reranker, kwargs):
    output = tmp_path / "output"
    with pytest.raises(ValueError):
        build_bundle(
            CORPUS, output, model_directory=tiny_model, reranker_directory=tiny_reranker, **kwargs
        )
    assert not output.exists()
