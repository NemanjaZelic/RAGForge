"""Opt-in real GPU regression, never an implicit model download or GPU CI claim."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not os.environ.get("RAGFORGE_GPU_RERANKER_DIR"),
    reason="explicit local model and supported Intel GPU required",
)
def test_real_gpu_no_network_no_analytics():
    model = Path(os.environ["RAGFORGE_GPU_RERANKER_DIR"]).resolve(strict=True)
    code = """
import socket, sys
class Blocked(socket.socket):
    def __init__(self, *args, **kwargs):
        raise AssertionError("network is forbidden during local GPU retrieval")
def denied(*args, **kwargs):
    raise AssertionError("DNS/network is forbidden during local GPU retrieval")
socket.socket = Blocked
socket.create_connection = socket.getaddrinfo = socket.gethostbyname = denied
from pathlib import Path
import numpy as np
from ragforge.core.rerank import ONNXReranker
model = ONNXReranker(Path(sys.argv[1]), threads=8, workers=8, cache_batches=0)
assert model.spec.runtime == "openvino-gpu-f16"
assert model.workers == 2
scores = model.score("warmup", ["warmup document source"] * 9)
assert len(scores) == 9 and np.isfinite(scores).all()
assert model.cache_info()["hits"] == 0
assert all(d.startswith("GPU") for d in model.session.execution_devices)
from openvino.tools.ovc import telemetry_utils
assert telemetry_utils.tm.__name__ == "openvino.tools.ovc.telemetry_stub"
assert "openvino_telemetry" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(model)], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr
