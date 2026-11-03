"""Provisioning is explicit, bounded and never destroys pre-existing files."""

import importlib.util
import io
from pathlib import Path

import pytest


def module():
    path = Path(__file__).resolve().parents[1] / "scripts/prepare_models.py"
    spec = importlib.util.spec_from_file_location("model_provisioning", path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_download_budget_removes_only_its_own_incomplete_file(tmp_path, monkeypatch):
    value = module()
    monkeypatch.setattr(value.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"x" * 2000))
    output = tmp_path / "new.onnx"
    with pytest.raises(ValueError, match="size limit"):
        value.download("https://model.invalid/pinned.onnx", output, max_bytes=1000)
    assert not output.exists()
    output.write_bytes(b"existing user file")
    with pytest.raises(FileExistsError):
        value.download("https://model.invalid/pinned.onnx", output, max_bytes=1000)
    assert output.read_bytes() == b"existing user file"


def test_download_explicit_allowance_is_bounded_and_success_is_exact(tmp_path, monkeypatch):
    value = module()
    monkeypatch.setattr(
        value.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"verified local bytes")
    )
    output = tmp_path / "new.onnx"
    for bad in [0, 384 * 1024**2 + 1, True]:
        with pytest.raises(ValueError, match="byte limit"):
            value.download("https://model.invalid/pinned.onnx", output, max_bytes=bad)
    value.download("https://model.invalid/pinned.onnx", output, max_bytes=384 * 1024**2)
    assert output.read_bytes() == b"verified local bytes"
