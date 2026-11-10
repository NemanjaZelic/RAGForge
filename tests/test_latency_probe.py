"""Real stdio measurement distinguishes model startup from query round trips."""

import json
import os
import subprocess
import sys
from pathlib import Path

from ragforge.artifacts.builder import build_bundle


def test_latency_probe_runs_bounded_uncached_mcp_and_keeps_source_text_private(
    tmp_path, tiny_model, tiny_reranker
):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "private.txt").write_text("PRIVATE_EVIDENCE_SENTINEL Retry requires a rollback token.")
    bundle = tmp_path / "bundle"
    build_bundle(docs, bundle, model_directory=tiny_model, reranker_directory=tiny_reranker)
    script = Path(__file__).resolve().parents[1] / "scripts/measure_query_latency.py"
    output = tmp_path / "timing.json"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            str(bundle),
            "--query",
            "rollback token",
            "--repeats",
            "2",
            "--threads",
            "2",
            "--output",
            str(output),
        ],
        env={**os.environ, "HF_HUB_OFFLINE": "1"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["startup_and_warmup_seconds"] > 0 and not data["neural_cache_enabled"]
    assert len(data["measurements"]) == 2
    assert len({r["response_sha256"] for r in data["measurements"]}) == 1
    assert all(
        r["mcp_roundtrip_seconds"] > 0 and r["returned_chunks"] > 0 for r in data["measurements"]
    )
    assert "PRIVATE_EVIDENCE_SENTINEL" not in result.stdout + output.read_text()
    assert "rollback token" not in result.stdout + output.read_text()
