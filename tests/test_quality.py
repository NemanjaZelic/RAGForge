"""Offline reranker packaging, source integrity and scope regressions."""

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from ragforge.artifacts.builder import build_bundle
from ragforge.artifacts.verification import build_identity, verify_bundle
from ragforge.core.chunk import ChunkConfig, chunk_document, pipeline_hash
from ragforge.core.contracts import RetrievalFilters, RetrieveRequest
from ragforge.core.engine import BundleEngine
from ragforge.core.parse import TextBlock, parse_document
from ragforge.core.rerank import ONNXReranker, reranker_spec
from ragforge.core.scan import scan_corpus

ROOT = Path(__file__).resolve().parents[1]


def test_section_chunks_merge_prose_but_preserve_boundaries(tmp_path: Path) -> None:
    raw = (
        b"<main><h1>Guide</h1><p>First paragraph.</p><p>Second paragraph.</p>"
        b"<pre>code</pre><p>Tail.</p><h2>Other</h2><p>End.</p></main>"
    )
    (tmp_path / "guide.html").write_bytes(raw)
    record = scan_corpus(tmp_path, "mini").documents[0]
    doc = parse_document("mini", record, raw)
    original = chunk_document(doc)
    merged = chunk_document(doc, ChunkConfig(strategy="sections"))
    assert len(merged) < len(original)
    assert "First paragraph.\nSecond paragraph." in merged[0].text
    assert all(c.source.line_start is None for c in merged)
    assert next(c for c in merged if c.kind == "code").text == "code"
    assert merged[-1].source.section == "Guide > Other"
    assert pipeline_hash(doc, ChunkConfig()) != pipeline_hash(doc, ChunkConfig(strategy="sections"))
    pages = replace(doc, blocks=(TextBlock("page one", page=1), TextBlock("page two", page=2)))
    assert [c.source.page for c in chunk_document(pages, ChunkConfig(strategy="sections"))] == [
        1,
        2,
    ]
    lines = replace(
        doc,
        blocks=(
            TextBlock("a\n", line_start=1, line_end=1),
            TextBlock("b\n", line_start=2, line_end=2),
            TextBlock("gap", line_start=4, line_end=4),
        ),
    )
    chunks = chunk_document(lines, ChunkConfig(strategy="sections"))
    assert chunks[0].text == "a\nb\n"
    assert (chunks[0].source.line_start, chunks[0].source.line_end) == (1, 2)
    assert len(chunks) == 2


def test_legacy_pipeline_and_bundle_identity_are_preserved(tmp_path: Path) -> None:
    bundle = tmp_path / "old-style"
    m = build_bundle(ROOT / "examples/mini-docs", bundle, profile="minimal")
    data = m.model_dump(mode="json", exclude={"build_id", "retrieval_configuration"})
    for d in data["collections"][0]["documents"]:
        d.pop("title", None)
    data.pop("source_context", None)
    expected = hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    assert m.build_id == expected == build_identity(m)
    legacy = json.loads((bundle / "manifest.json").read_text())
    del legacy["retrieval_configuration"]
    for d in legacy["collections"][0]["documents"]:
        d.pop("title", None)
    (bundle / "manifest.json").write_text(json.dumps(legacy), encoding="utf-8")
    assert verify_bundle(bundle).build_id == expected


def test_reranker_offline_relocated_cli_scope_and_raw_bm25(
    tmp_path: Path, tiny_reranker: Path, offline_cli
) -> None:
    output = tmp_path / "bundle"
    m = build_bundle(
        ROOT / "examples/mini-docs",
        output,
        collection_id="mini",
        profile="minimal",
        reranker_directory=tiny_reranker,
        max_chunks_per_document=1,
    )
    assert m.retrieval_configuration is not None
    relocated = tmp_path / "relocated"
    shutil.copytree(output, relocated)
    raw = offline_cli(["use", str(relocated), "--query", "rollback", "--no-rerank"])
    assert raw.returncode == 0, raw.stderr
    reranked = offline_cli(["use", str(relocated), "--query", "rollback", "--rerank"])
    assert reranked.returncode == 0, reranked.stderr
    response = json.loads(reranked.stdout)
    assert len(response["results"]) <= 5
    engine = BundleEngine(relocated)
    engine.retrieve(RetrieveRequest(query="rollback"))
    assert engine._reranker is None  # BM25 remains a model-free baseline by default.
    allowed = m.collections[0].documents[0].document_id
    for method in ["bm25"]:
        result = engine.retrieve(
            RetrieveRequest(
                query="rollback token",
                search_method=method,
                rerank=True,
                filters=RetrievalFilters(document_ids=[allowed]),
                max_output_chars=16000,
            )
        )
        assert all(r.document_id == allowed for r in result.results)
    assert engine._reranker is not None
    for r in response["results"]:
        with engine.sqlite._connect() as c:
            original = c.execute(
                "SELECT text,source_json FROM chunks WHERE chunk_id=?", (r["chunk_id"],)
            ).fetchone()
            assert original["text"] == r["text"]
            assert json.loads(original["source_json"]) == r["source"]


def test_reranker_bounds_and_corruption(tiny_reranker: Path) -> None:
    scorer = ONNXReranker(tiny_reranker, threads=1)
    assert len(scorer.score("rollback", ["transaction " * 1000, "token"])) == 2
    with pytest.raises(ValueError, match="query leaves"):
        scorer.score("token " * 600, ["token"])
    with pytest.raises(ValueError):
        scorer.score("rollback", [])
    path = tiny_reranker / "model.onnx"
    path.write_bytes(path.read_bytes() + b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        reranker_spec(tiny_reranker)


def test_missing_reranker_does_not_silently_fall_back(tmp_path: Path) -> None:
    output = tmp_path / "plain"
    build_bundle(ROOT / "examples/mini-docs", output, profile="minimal")
    with pytest.raises(ValueError, match="requires a bundle"):
        BundleEngine(output).retrieve(RetrieveRequest(query="rollback", rerank=True))


@pytest.mark.parametrize("backend", ["exact", "ann"])
def test_balanced_reranking_keeps_raw_bm25_and_filters_all_candidates(
    tmp_path: Path, tiny_model: Path, tiny_reranker: Path, backend: str
) -> None:
    output = tmp_path / "quality-balanced"
    manifest = build_bundle(
        ROOT / "examples/mini-docs",
        output,
        collection_id="mini",
        model_directory=tiny_model,
        reranker_directory=tiny_reranker,
        dense_backend=backend,
        max_chunks_per_document=1,
    )
    engine = BundleEngine(output)
    engine.retrieve(RetrieveRequest(query="rollback", search_method="bm25"))
    assert engine._reranker is None and engine._embedder is None
    allowed = manifest.collections[0].documents[0].document_id
    for method in ("dense", "hybrid"):
        result = engine.retrieve(
            RetrieveRequest(
                query="rollback token",
                search_method=method,
                filters=RetrievalFilters(document_ids=[allowed]),
            )
        )
        assert result.results and all(r.document_id == allowed for r in result.results)
    assert engine._reranker is not None
    fresh = BundleEngine(output)
    fresh.retrieve(RetrieveRequest(query="rollback", search_method="hybrid", rerank=False))
    assert fresh._reranker is None


@pytest.mark.parametrize("backend", ["exact", "ann"])
def test_enhance_preserves_index_bytes_and_original_bundle(
    tmp_path: Path, tiny_model: Path, tiny_reranker: Path, backend: str
) -> None:
    from ragforge.artifacts.enhance import enhance_bundle
    from ragforge.core.embedding import file_hash

    original = tmp_path / "original"
    before = build_bundle(
        ROOT / "examples/mini-docs", original, model_directory=tiny_model, dense_backend=backend
    )
    manifest_bytes = (original / "manifest.json").read_bytes()
    output = tmp_path / "enhanced"
    after = enhance_bundle(original, output, tiny_reranker, candidates=200)
    assert before.build_id != after.build_id
    assert before.collections == after.collections
    for record in before.files:
        assert file_hash(output / record.path) == record.sha256
    assert (original / "manifest.json").read_bytes() == manifest_bytes
    assert verify_bundle(original).build_id == before.build_id
    assert BundleEngine(output).retrieve(RetrieveRequest(query="rollback")).results
    with pytest.raises(FileExistsError):
        enhance_bundle(original, output, tiny_reranker)
    with pytest.raises(ValueError, match="separate"):
        enhance_bundle(original, original / "nested", tiny_reranker)


def test_token_aware_chunks_preserve_source_and_fit_the_actual_model(
    tmp_path: Path, tiny_model: Path
) -> None:
    from ragforge.core.embedding import ChunkTokenizer, ONNXEmbedder
    from ragforge.evaluation.scoring import covered_length

    descriptor = tiny_model / "model.json"
    data = json.loads(descriptor.read_text())
    data["max_tokens"] = 16
    descriptor.write_text(json.dumps(data), encoding="utf-8")
    source = tmp_path / "source"
    source.mkdir()
    text = "rollback token transaction authentication\n" * 20
    (source / "guide.txt").write_bytes(text.encode())
    record = scan_corpus(source, "mini").documents[0]
    doc = parse_document("mini", record, text.encode())
    counter = ChunkTokenizer(tiny_model)
    config = ChunkConfig(chunk_size_chars=1000, overlap_chars=10, token_budget=counter.budget)
    chunks = chunk_document(doc, config, token_counter=counter)
    assert len(chunks) > 1 and all(counter(c.text) <= 16 for c in chunks)
    assert covered_length([(c.char_start, c.char_end) for c in chunks]) == len(text)
    for c in chunks:
        assert c.text == text[c.char_start : c.char_end]
        assert c.source.line_start == 1 + text[: c.char_start].count("\n")
    assert ONNXEmbedder(tiny_model).encode([c.text for c in chunks[:8]]).shape[0] == min(
        8, len(chunks)
    )
    with pytest.raises(ValueError, match="token limit"):
        build_bundle(
            source, tmp_path / "oversized", collection_id="mini", model_directory=tiny_model
        )
    output = tmp_path / "fitted"
    manifest = build_bundle(
        source,
        output,
        collection_id="mini",
        model_directory=tiny_model,
        token_aware=True,
        chunk_config=ChunkConfig(strategy="sections"),
    )
    assert manifest.build_configuration.chunker_version.startswith("section-token-chars-v3:")
    assert BundleEngine(output).retrieve(RetrieveRequest(query="rollback")).results
    with pytest.raises(ValueError, match="both a pinned budget"):
        chunk_document(doc, config)
    with pytest.raises(ValueError, match="balanced"):
        build_bundle(source, tmp_path / "wrong-profile", profile="minimal", token_aware=True)


def test_reranker_spec_controls_bounded_memory_batching(tiny_reranker):
    from types import SimpleNamespace

    path = tiny_reranker / "reranker.json"
    data = json.loads(path.read_text())
    data["batch_size"] = 1
    path.write_text(json.dumps(data))
    # Disable exact reuse so every actual inference batch remains observable.
    scorer = ONNXReranker(tiny_reranker, threads=1, cache_batches=0)
    original = scorer.session.run
    sizes = []

    def run(names, inputs):
        sizes.append(len(inputs["input_ids"]))
        return original(names, inputs)

    scorer.session = SimpleNamespace(run=run)
    assert len(scorer.score("rollback", ["transaction evidence"] * 9)) == 9
    assert sizes == [1] * 9
