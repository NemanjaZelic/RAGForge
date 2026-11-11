"""Exercise the complete simple workflow, publication failures and real MCP output."""

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from ragforge.artifacts.builder import build_bundle
from ragforge.core.chunk import ChunkConfig
from ragforge.core.contracts import RetrieveRequest
from ragforge.core.engine import BundleEngine
from ragforge.quickstart import active_bundle, main, ready_documentation

CORPUS = Path(__file__).resolve().parents[1] / "examples/mini-docs"


def test_simple_build_matches_manual_pipeline_and_preserves_versions(
    tmp_path, tiny_model, tiny_reranker
):
    project = tmp_path / "project with spaces"
    project.mkdir()
    docs = project / "documents"
    shutil.copytree(CORPUS, docs)
    first = ready_documentation(project, query_model=tiny_model, reranker=tiny_reranker, threads=2)
    assert active_bundle(project) == first
    manual = tmp_path / "manual"
    build_bundle(
        docs,
        manual,
        collection_id="documents",
        model_directory=tiny_model,
        reranker_directory=tiny_reranker,
        chunk_config=ChunkConfig(strategy="sections"),
        token_aware=True,
        dense_backend="ann",
        threads=2,
    )
    request = RetrieveRequest(query="rollback token", top_k=50, max_output_chars=48000)
    assert BundleEngine(first).retrieve(request) == BundleEngine(manual).retrieve(request)
    original_manifest = (first / "manifest.json").read_bytes()
    second = ready_documentation(project, query_model=tiny_model, reranker=tiny_reranker, threads=2)
    assert second != first and active_bundle(project) == second
    assert (first / "manifest.json").read_bytes() == original_manifest
    pointer = (project / ".cache/quickstart/active.json").read_bytes()
    bad = tmp_path / "unreadable docs"
    bad.mkdir()
    (bad / "broken.txt").write_bytes(b"\xff\xfe")
    with pytest.raises(ValueError):
        ready_documentation(project, bad, query_model=tiny_model, reranker=tiny_reranker, threads=2)
    assert (project / ".cache/quickstart/active.json").read_bytes() == pointer
    assert active_bundle(project) == second


def test_missing_models_or_missing_active_state_give_actionable_errors(tmp_path, capsys):
    assert main(["--project", str(tmp_path), "build"]) == 2
    assert ("setup.cmd" if sys.platform == "win32" else "setup.sh") in capsys.readouterr().err
    assert main(["--project", str(tmp_path), "ask", "rollback"]) == 2
    assert "build first" in capsys.readouterr().err
    assert not (tmp_path / "kb").exists()


def test_simple_active_identity_drift_is_rejected(tmp_path):
    bundle = tmp_path / "bundle"
    build_bundle(CORPUS, bundle, profile="minimal")
    state = tmp_path / ".cache/quickstart"
    state.mkdir(parents=True)
    (state / "active.json").write_text(json.dumps({"bundle": str(bundle), "build_id": "0" * 64}))
    with pytest.raises(ValueError, match="identity changed"):
        active_bundle(tmp_path)


def test_offline_cli_workflow_and_actual_generated_warmed_mcp(
    tmp_path,
    tiny_model,
    tiny_reranker,
    offline_cli,
):
    # Reuse the strict subprocess socket/DNS guard; this command must never download.
    offline_cli(["--help"])
    project = tmp_path / "fresh project with spaces"
    project.mkdir()
    docs = project / "documents"
    shutil.copytree(CORPUS, docs)
    env = {**os.environ, "PYTHONPATH": str(tmp_path), "PYTHONIOENCODING": "utf-8"}

    def run(*args):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sitecustomize; assert sitecustomize.RAGFORGE_OFFLINE_GUARD; "
                "from ragforge.quickstart import main; raise SystemExit(main())",
                "--project",
                str(project),
                *map(str, args),
            ],
            env=env,
            cwd=tmp_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=40,
        )
        assert result.returncode == 0, result.stderr
        return result

    build = run("build", "--model", tiny_model, "--reranker", tiny_reranker, "--threads", 2)
    assert "Ready:" in build.stdout
    answer = run("ask", "rollback token", "--threads", 2)
    assert "[1]" in answer.stdout and "(lines " in answer.stdout
    integration = project / "integration with spaces"
    run("agent", "--output", integration, "--threads", 2)
    config = json.loads((integration / "mcp.json").read_text())
    server = next(iter(config["mcpServers"].values()))
    assert "--warm-up" in server["args"]
    assert server["args"][-5:] == ["--threads", "2", "--rerank-workers", "2", "--warm-up"]
    expected = BundleEngine(active_bundle(project)).retrieve(
        RetrieveRequest(query="rollback token")
    )

    async def exercise():
        async with Client(
            StdioServerParameters(**server, cwd=str(tmp_path)), read_timeout_seconds=40
        ) as client:
            result = await client.call_tool("search_docs", {"query": "rollback token"})
            assert not result.is_error
            assert result.structured_content == expected.model_dump(mode="json")

    asyncio.run(asyncio.wait_for(exercise(), timeout=50))
    assert not (project / ".mcp.json").exists()  # Does not alter host settings.


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native CMD launcher")
def test_native_windows_launcher_forwards_spaces_and_returns_citations(
    tmp_path, tiny_model, tiny_reranker
):
    bundle = tmp_path / "bundle with spaces"
    build_bundle(CORPUS, bundle, model_directory=tiny_model, reranker_directory=tiny_reranker)
    launcher = Path(__file__).resolve().parents[1] / "ragforge.cmd"
    result = subprocess.run(
        [str(launcher), "ask", "rollback transaction", "--bundle", str(bundle), "--threads", "2"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=40,
    )
    assert result.returncode == 0, result.stderr
    assert "[1]" in result.stdout and "(lines " in result.stdout


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux native Bash launcher")
def test_native_linux_launcher_forwards_spaces_and_returns_citations(
    tmp_path, tiny_model, tiny_reranker
):
    bundle = tmp_path / "bundle with spaces"
    build_bundle(CORPUS, bundle, model_directory=tiny_model, reranker_directory=tiny_reranker)
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["bash", "-n", str(root / "setup.sh")], check=True)
    subprocess.run(["bash", "-n", str(root / "ragforge.sh")], check=True)
    result = subprocess.run(
        [
            "bash",
            str(root / "ragforge.sh"),
            "ask",
            "rollback transaction",
            "--bundle",
            str(bundle),
            "--threads",
            "2",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=40,
    )
    assert result.returncode == 0, result.stderr
    assert "[1]" in result.stdout and "(lines " in result.stdout


@pytest.mark.parametrize("extension", ["txt", "md", "html"])
def test_original_build_command_escapes_controls_without_extra_steps(
    tmp_path, tiny_model, tiny_reranker, capsys, extension
):
    from ragforge.artifacts.verification import verify_bundle

    project = tmp_path / "simple project"
    documents = project / "documents"
    documents.mkdir(parents=True)
    raw = b"authentication\x00 token\x1b documentation\ntransaction rollback\x07\n"
    source = documents / ("manual." + extension)
    source.write_bytes(raw)
    state = project / ".cache/quickstart"
    state.mkdir(parents=True)
    # Same prepared-model state that setup writes; no build flags or manual ingest.
    (state / "models.json").write_text(
        json.dumps({"query_model": str(tiny_model), "reranker": str(tiny_reranker)}),
        encoding="utf-8",
    )
    assert main(["--project", str(project), "build"]) == 0
    assert "Control characters were represented as visible text" in capsys.readouterr().err
    bundle = active_bundle(project)
    manifest = verify_bundle(bundle)
    assert "controls-escaped-v1" in manifest.build_configuration.parser_version
    engine = BundleEngine(bundle)
    results = engine.retrieve(RetrieveRequest(query="authentication", search_method="bm25"))
    assert results.results[0].source.path == source.name
    assert "authentication\\x00 token\\x1b" in results.results[0].text
    if extension != "html":
        assert results.results[0].source.line_start == 1
    assert source.read_bytes() == raw
    # The existing agent command consumes the newly remembered bundle directly.
    assert main(["--project", str(project), "agent"]) == 0


def test_original_build_handles_mixed_source_encodings_without_extra_flags(
    tmp_path, tiny_model, tiny_reranker, capsys
):
    import hashlib

    from ragforge.artifacts.verification import verify_bundle

    docs = tmp_path / "documents"
    docs.mkdir()
    sources = {
        "unicode.txt": "authentication café\n".encode("utf-16"),
        "legacy.md": "transaction – résumé\n".encode("cp1252"),
        "declared.html": '<meta charset="windows-1250"><p>rollback čćžšđ</p>'.encode("cp1250"),
    }
    for name, raw in sources.items():
        (docs / name).write_bytes(raw)
    state = tmp_path / ".cache/quickstart"
    state.mkdir(parents=True)
    (state / "models.json").write_text(
        json.dumps({"query_model": str(tiny_model), "reranker": str(tiny_reranker)}),
        encoding="utf-8",
    )
    assert main(["--project", str(tmp_path), "build"]) == 0
    notice = capsys.readouterr().err
    assert "encoding was handled automatically" in notice
    assert "fallback; check accented characters" in notice
    bundle = active_bundle(tmp_path)
    manifest = verify_bundle(bundle)
    for record in manifest.collections[0].documents:
        assert record.content_sha256 == hashlib.sha256(sources[record.source_path]).hexdigest()
        assert (docs / record.source_path).read_bytes() == sources[record.source_path]
    engine = BundleEngine(bundle)
    for query, expected in [
        ("authentication", "café"),
        ("transaction", "résumé"),
        ("rollback", "čćžšđ"),
    ]:
        result = engine.retrieve(RetrieveRequest(query=query, search_method="bm25"))
        assert expected in result.results[0].text
    assert main(["--project", str(tmp_path), "agent"]) == 0
