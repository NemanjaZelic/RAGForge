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
