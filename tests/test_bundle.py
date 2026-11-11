import builtins
import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ragforge.artifacts import builder
from ragforge.artifacts.builder import build_bundle
from ragforge.artifacts.manifest import BundleManifest
from ragforge.artifacts.verification import build_identity, verify_bundle
from ragforge.cli import app
from ragforge.core.contracts import FetchContextRequest, RetrievalFilters, RetrieveRequest
from ragforge.core.engine import BundleEngine

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "examples/mini-docs"


def deny_ml(monkeypatch: pytest.MonkeyPatch) -> None:
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in {"numpy", "onnxruntime", "onnx", "tokenizers", "huggingface_hub"}:
            raise AssertionError(f"optional inference import forbidden: {name}")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)


def restamp(root: Path) -> None:
    path = root / "manifest.json"
    manifest = BundleManifest.model_validate_json(path.read_text(encoding="utf-8"))
    for record in manifest.files:
        data = (root / record.path).read_bytes()
        record.sha256 = hashlib.sha256(data).hexdigest()
        record.size_bytes = len(data)
    manifest.build_id = build_identity(manifest)
    path.write_text(manifest.model_dump_json(), encoding="utf-8")


def test_minimal_build_verify_query_needs_no_ml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deny_ml(monkeypatch)
    output = tmp_path / "minimal"
    manifest = build_bundle(CORPUS, output, collection_id="mini", profile="minimal")
    assert manifest.profile == "minimal" and len(manifest.files) == 1
    assert verify_bundle(output) == manifest
    result = BundleEngine(output).retrieve(RetrieveRequest(query="rollback"))
    assert result.results[0].source.path == "transactions.md"
    assert result.results[0].retrieval_method == "bm25"


def test_balanced_bm25_does_not_import_or_load_model(
    tmp_path: Path, tiny_model: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "balanced"
    build_bundle(CORPUS, output, collection_id="mini", model_directory=tiny_model)
    deny_ml(monkeypatch)
    engine = BundleEngine(output)
    result = engine.retrieve(RetrieveRequest(query="rollback", search_method="bm25"))
    assert result.results
    assert engine._embedder is None and engine._dense is None


def test_balanced_default_hybrid_and_scope(tmp_path: Path, tiny_model: Path) -> None:
    output = tmp_path / "balanced"
    manifest = build_bundle(CORPUS, output, collection_id="mini", model_directory=tiny_model)
    assert manifest.capabilities == ["bm25", "dense", "hybrid"]
    engine = BundleEngine(output)
    for method in ("bm25", "dense", "hybrid", None):
        result = engine.retrieve(RetrieveRequest(query="rollback", search_method=method))
        assert result.results and all(
            r.retrieval_method == (method or "hybrid") for r in result.results
        )
        scores = [(r.rank_score, r.chunk_id) for r in result.results]
        assert scores == sorted(scores, key=lambda item: (-item[0], item[1]))
    selected = (
        engine.retrieve(RetrieveRequest(query="token", search_method="dense"))
        .results[0]
        .document_id
    )
    for method in ("dense", "hybrid"):
        found = engine.retrieve(
            RetrieveRequest(
                query="token",
                search_method=method,
                filters=RetrievalFilters(document_ids=[selected]),
            )
        )
        assert all(r.document_id == selected for r in found.results)
        assert not engine.retrieve(
            RetrieveRequest(
                query="token",
                search_method=method,
                filters=RetrievalFilters(document_ids=["f" * 64]),
            )
        ).results
    with pytest.raises(ValueError, match="unknown collection"):
        engine.retrieve(RetrieveRequest(query="token", collection_id="other"))
    with pytest.raises(ValueError, match="max_output_chars"):
        engine.retrieve(RetrieveRequest(query="token", max_output_chars=1))


@pytest.mark.parametrize(
    "fault", ["corrupt", "missing", "extra", "version", "hash", "traversal", "empty_dir"]
)
def test_integrity_rejects_bad_bundle_before_reading_runtime_data(
    tmp_path: Path, fault: str
) -> None:
    root = tmp_path / "bundle"
    manifest = build_bundle(CORPUS, root, profile="minimal")
    database = root / manifest.collections[0].database_path
    if fault == "corrupt":
        with database.open("ab") as stream:
            stream.write(b"corruption")
    elif fault == "missing":
        database.unlink()
    elif fault == "extra":
        (root / "unexpected.txt").write_text("unexpected")
    elif fault == "empty_dir":
        (root / "unexpected").mkdir()
    else:
        path = root / "manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        if fault == "version":
            data["artifact_schema_version"] = "999"
        elif fault == "hash":
            data["files"][0]["sha256"] = "f" * 64
        else:
            data["files"][0]["path"] = "../escape.sqlite"
        path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        verify_bundle(root)


def test_unknown_dense_version_and_bad_shape_rejected_without_ml(
    tmp_path: Path, tiny_model: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import numpy as np

    root = tmp_path / "bundle"
    manifest = build_bundle(CORPUS, root, model_directory=tiny_model)
    dense = manifest.collections[0].dense_index
    assert dense is not None
    with (root / dense.path).open("wb") as stream:
        np.save(stream, np.zeros((1, 4), dtype=np.float32))
    restamp(root)
    deny_ml(monkeypatch)
    with pytest.raises(ValueError, match="dense header"):
        verify_bundle(root)


def test_missing_model_has_no_hybrid_fallback(tmp_path: Path, tiny_model: Path) -> None:
    root = tmp_path / "bundle"
    build_bundle(CORPUS, root, model_directory=tiny_model)
    (root / "models/query/model.onnx").unlink()
    with pytest.raises(ValueError, match="missing"):
        BundleEngine(root)


def test_builder_keeps_existing_and_cleans_only_owned_staging(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    (output / "keep.txt").write_text("keep")
    with pytest.raises(FileExistsError):
        build_bundle(CORPUS, output, profile="minimal")
    assert (output / "keep.txt").read_text() == "keep"
    with pytest.raises((OSError, ValueError)):
        build_bundle(CORPUS, tmp_path / "failed", model_directory=tmp_path / "missing")
    assert not (tmp_path / "failed").exists()
    assert not list(tmp_path.glob(".ragforge-stage-*"))
    with pytest.raises(ValueError, match="outside corpus"):
        build_bundle(CORPUS, CORPUS / "never-created", profile="minimal")


def test_publication_does_not_replace_even_a_racing_empty_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "raced"
    publish = builder.publish_new
    observed = []

    def race(stage, target):
        target.mkdir()
        observed.append(target.stat().st_ino)
        publish(stage, target)

    monkeypatch.setattr(builder, "publish_new", race)
    with pytest.raises(FileExistsError):
        build_bundle(CORPUS, output, profile="minimal")
    assert output.is_dir() and not list(output.iterdir())
    assert output.stat().st_ino == observed[0]
    assert not list(tmp_path.glob(".ragforge-stage-*"))


def test_copied_bundle_has_same_ids_and_exact_context(tmp_path: Path, tiny_model: Path) -> None:
    root = tmp_path / "source"
    build_bundle(CORPUS, root, collection_id="mini", model_directory=tiny_model)
    request = RetrieveRequest(query="rollback")
    first = BundleEngine(root).retrieve(request)
    copy = tmp_path / "another location"
    shutil.copytree(root, copy)
    second = BundleEngine(copy).retrieve(request)
    assert first == second
    anchor = second.results[0]
    context = BundleEngine(copy).fetch_context(
        FetchContextRequest(
            collection_id="mini",
            chunk_id=anchor.chunk_id,
            neighbors=5,
        )
    )
    assert anchor.chunk_id in {part.chunk_id for part in context.results}
    assert all(part.document_id == anchor.document_id for part in context.results)


def test_cli_defaults_offline_and_rejects_unsupported_modes(tmp_path: Path) -> None:
    runner = CliRunner()
    root = tmp_path / "bundle"
    built = runner.invoke(
        app,
        [
            "build",
            str(CORPUS),
            "--output",
            str(root),
            "--profile",
            "minimal",
            "--offline",
        ],
    )
    assert built.exit_code == 0, built.output
    assert json.loads(built.stdout)["offline"] is True
    found = runner.invoke(app, ["use", str(root), "--mode", "local", "--query", "rollback"])
    assert found.exit_code == 0, found.output
    hit = json.loads(found.stdout)["results"][0]
    context = runner.invoke(app, ["context", str(root), hit["chunk_id"]])
    assert context.exit_code == 0, context.output
    invalid = runner.invoke(app, ["use", str(root), "--mode", "shared", "--query", "rollback"])
    assert invalid.exit_code == 2 and invalid.stdout == ""
    minimal_dense = runner.invoke(
        app,
        [
            "use",
            str(root),
            "--query",
            "rollback",
            "--search-method",
            "dense",
        ],
    )
    assert minimal_dense.exit_code == 2


def test_socket_blocked_cli_build_use_and_relocation(
    tmp_path: Path,
    tiny_model: Path,
    offline_cli: Callable[[list[str]], subprocess.CompletedProcess[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "bundle"
    built = offline_cli(
        [
            "build",
            str(CORPUS),
            "--output",
            str(root),
            "--collection",
            "mini",
            "--model",
            str(tiny_model),
            "--offline",
        ]
    )
    assert built.returncode == 0, built.stderr
    copied = tmp_path / "copied"
    shutil.copytree(root, copied)
    for method in ("bm25", "dense", "hybrid"):
        found = offline_cli(["use", str(copied), "--query", "rollback", "--search-method", method])
        assert found.returncode == 0, found.stderr
        assert json.loads(found.stdout)["results"]
    monkeypatch.setenv("RAGFORGE_FORBID_ML_IMPORTS", "1")
    lexical = offline_cli(["use", str(copied), "--query", "rollback", "--search-method", "bm25"])
    assert lexical.returncode == 0, lexical.stderr


@pytest.mark.parametrize("fault", ["database_inventory", "backend_version", "model_identity"])
def test_semantic_mismatches_rejected_even_with_recomputed_file_checksums(
    tmp_path: Path, tiny_model: Path, fault: str
) -> None:
    import sqlite3

    root = tmp_path / "bundle"
    manifest = build_bundle(CORPUS, root, model_directory=tiny_model)
    if fault == "database_inventory":
        with sqlite3.connect(root / manifest.collections[0].database_path) as connection:
            connection.execute("UPDATE documents SET content_sha256=?", ("0" * 64,))
    elif fault == "model_identity":
        descriptor = root / "models/query/model.json"
        value = json.loads(descriptor.read_text(encoding="utf-8"))
        value["revision"] = "b" * 40
        descriptor.write_text(json.dumps(value), encoding="utf-8")
    else:
        dense = manifest.collections[0].dense_index
        assert dense is not None
        dense.backend_version = "999"
        (root / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    restamp(root)
    with pytest.raises(ValueError, match="inventory|version|identity"):
        verify_bundle(root)


def test_object_array_dense_file_is_rejected_without_unpickling(
    tmp_path: Path, tiny_model: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import numpy as np

    root = tmp_path / "bundle"
    manifest = build_bundle(CORPUS, root, model_directory=tiny_model)
    dense = manifest.collections[0].dense_index
    assert dense is not None
    with (root / dense.path).open("wb") as stream:
        np.save(stream, np.full((21, 4), None, dtype=object))
    restamp(root)
    deny_ml(monkeypatch)
    with pytest.raises(ValueError, match="dense header"):
        verify_bundle(root)


def test_nonfinite_dense_vectors_are_not_used_as_results(tmp_path: Path, tiny_model: Path) -> None:
    import numpy as np

    root = tmp_path / "bundle"
    manifest = build_bundle(CORPUS, root, model_directory=tiny_model)
    dense = manifest.collections[0].dense_index
    assert dense is not None
    with (root / dense.path).open("wb") as stream:
        np.save(stream, np.full((21, 4), np.nan, dtype="<f4"))
    restamp(root)
    with pytest.raises(ValueError, match="finite"):
        BundleEngine(root).retrieve(RetrieveRequest(query="rollback", search_method="dense"))


def test_default_balanced_requires_explicit_model_and_empty_corpus_fails(tmp_path: Path) -> None:
    runner = CliRunner()
    target = tmp_path / "default"
    result = runner.invoke(app, ["build", str(CORPUS), "--output", str(target)])
    assert result.exit_code == 2 and not target.exists()
    assert "prepared local" in json.loads(result.stderr)["error"]
    corpus = tmp_path / "empty-corpus"
    corpus.mkdir()
    (corpus / "empty.txt").write_bytes(b"")
    with pytest.raises(ValueError, match="no searchable text"):
        build_bundle(corpus, tmp_path / "empty-bundle", profile="minimal")
    assert not list(tmp_path.glob(".ragforge-stage-*"))


def test_balanced_pdf_bundle_keeps_physical_pages_and_parser_options(
    tmp_path: Path, tiny_model: Path
) -> None:
    source = tmp_path / "pdf-corpus"
    source.mkdir()
    shutil.copyfile(ROOT / "tests/fixtures/pdf/structured.pdf", source / "evidence.pdf")
    output = tmp_path / "pdf-bundle"
    manifest = build_bundle(source, output, model_directory=tiny_model)
    assert manifest.build_configuration.pdf_options is not None
    assert manifest.build_configuration.pdf_options.max_pages == 500
    result = BundleEngine(output).retrieve(RetrieveRequest(query="authentication"))
    assert {r.source.page for r in result.results} == {1, 2}
    assert all(r.source.line_start is None for r in result.results)


@pytest.mark.parametrize("nested", [False, True])
def test_case_distinct_sources_build_verify_and_retrieve(tmp_path: Path, nested: bool) -> None:
    source = tmp_path / "source"
    source.mkdir()
    paths = ["Readme.txt", "readme.txt"] if not nested else ["Docs/a.txt", "docs/a.txt"]
    for path, text in zip(
        paths, ["alpha transaction rollback", "beta authentication token"], strict=True
    ):
        file = source / path
        file.parent.mkdir(exist_ok=True)
        file.write_text(text, encoding="utf-8")
    if (source / paths[0]).samefile(source / paths[1]):
        pytest.skip("case-insensitive filesystem cannot create distinct source entries")
    output = tmp_path / "bundle"
    manifest = build_bundle(source, output, collection_id="mini", profile="minimal")
    assert len(manifest.collections[0].documents) == 2
    assert verify_bundle(output) == manifest
    engine = BundleEngine(output)
    for path, query in zip(paths, ["rollback", "authentication"], strict=True):
        result = engine.retrieve(RetrieveRequest(query=query))
        assert result.results[0].source.path == path
        assert result.results[0].document_id == next(
            d.document_id for d in manifest.collections[0].documents if d.source_path == path
        )
    second = build_bundle(source, tmp_path / "repeat", collection_id="mini", profile="minimal")
    assert second.build_id == manifest.build_id
