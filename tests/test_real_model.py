"""Actual pretrained-model integration; model provisioning is an explicit CI step."""

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not os.environ.get("RAGFORGE_MODEL_DIR"), reason="explicit local real model required"
)
@pytest.mark.parametrize("dense_backend", ["exact", "ann"])
def test_pretrained_model_offline_build_query_and_relocation(
    tmp_path: Path,
    offline_cli: Callable[[list[str]], subprocess.CompletedProcess[str]],
    dense_backend: str,
) -> None:
    root = Path(__file__).resolve().parents[1]
    model = Path(os.environ["RAGFORGE_MODEL_DIR"]).resolve(strict=True)
    bundle = tmp_path / "bundle"
    built = offline_cli(
        [
            "build",
            str(root / "examples/mini-docs"),
            "--output",
            str(bundle),
            "--collection",
            "mini",
            "--model",
            str(model),
            "--offline",
            "--dense-backend",
            dense_backend,
        ]
    )
    assert built.returncode == 0, built.stderr
    copied = tmp_path / "different location"
    shutil.copytree(bundle, copied)
    ids = {}
    for method in ("bm25", "dense", "hybrid"):
        result = offline_cli(
            [
                "use",
                str(copied),
                "--query",
                "How are access tokens sent to the service?",
                "--search-method",
                method,
                "--top-k",
                "3",
            ]
        )
        assert result.returncode == 0, result.stderr
        chunks = json.loads(result.stdout)["results"]
        assert chunks[0]["source"]["path"] == "authentication.md"
        assert all(chunk["retrieval_method"] == method for chunk in chunks)
        ids[method] = chunks[0]["document_id"]
    assert len(set(ids.values())) == 1


@pytest.mark.skipif(
    not os.environ.get("RAGFORGE_MODEL_DIR"), reason="explicit local real model required"
)
@pytest.mark.parametrize("dense_backend", ["exact", "ann"])
def test_pretrained_mcp_stdio_offline(tmp_path: Path, offline_cli, dense_backend: str) -> None:
    import asyncio

    from mcp_helpers import offline_client

    root = Path(__file__).resolve().parents[1]
    model = Path(os.environ["RAGFORGE_MODEL_DIR"]).resolve(strict=True)
    bundle = tmp_path / "mcp-bundle"
    built = offline_cli(
        [
            "build",
            str(root / "examples/mini-docs"),
            "--output",
            str(bundle),
            "--collection",
            "mini",
            "--model",
            str(model),
            "--offline",
            "--dense-backend",
            dense_backend,
        ]
    )
    assert built.returncode == 0, built.stderr
    copied = tmp_path / "relocated MCP bundle"
    shutil.copytree(bundle, copied)

    async def exercise():
        async with offline_client(copied, tmp_path / "mcp-guard") as client:
            for method in (None, "bm25", "dense", "hybrid"):
                arguments = {"query": "How are access tokens sent to the service?", "top_k": 3}
                if method is not None:
                    arguments["search_method"] = method
                result = await client.call_tool("search_docs", arguments)
                assert not result.is_error
                first = result.structured_content["results"][0]
                assert first["source"]["path"] == "authentication.md"
                assert first["retrieval_method"] == (method or "hybrid")
                context = await client.call_tool(
                    "fetch_context",
                    {
                        "collection_id": first["collection_id"],
                        "chunk_id": first["chunk_id"],
                    },
                )
                assert not context.is_error
                assert all(
                    r["document_id"] == first["document_id"]
                    for r in context.structured_content["results"]
                )

    asyncio.run(asyncio.wait_for(exercise(), timeout=60))
