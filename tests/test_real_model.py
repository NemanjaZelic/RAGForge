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
def test_pretrained_model_offline_build_query_and_relocation(
    tmp_path: Path, offline_cli: Callable[[list[str]], subprocess.CompletedProcess[str]]
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
