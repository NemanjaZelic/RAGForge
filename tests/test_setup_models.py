"""Explicit provisioning reuses checksummed packages and recovers from failed download."""

import importlib
import shutil
import subprocess
from pathlib import Path

import pytest

from ragforge.core.embedding import model_spec

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    return importlib.import_module("setup_models")


def arguments(setup, tiny_model):
    spec = model_spec(tiny_model)
    return {
        "script": SCRIPTS / "prepare_models.py",
        "script_args": ["e5-small"],
        "expected_id": spec.model_id,
        "expected_revision": spec.revision,
        "validate": model_spec,
        "offline": False,
    }


def test_repeated_setup_reuses_verified_model_without_network(setup, tiny_model, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("must not download an existing valid model")

    monkeypatch.setattr(setup.subprocess, "run", forbidden)
    assert setup.prepare(tiny_model, **arguments(setup, tiny_model)) == tiny_model
    assert (
        setup.prepare(tiny_model, **{**arguments(setup, tiny_model), "offline": True}) == tiny_model
    )


def test_failed_download_can_retry_without_partial_destination_or_data_loss(
    setup,
    tiny_model,
    tmp_path,
    monkeypatch,
):
    destination = tmp_path / "models with spaces" / "query"
    destination.parent.mkdir()
    sentinel = destination.parent / "unrelated.txt"
    sentinel.write_text("preserve")
    args = arguments(setup, tiny_model)

    def fail(command, **kwargs):
        partial = Path(command[-1])
        partial.mkdir()
        (partial / "partial.onnx").write_bytes(b"incomplete")
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(setup.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        setup.prepare(destination, **args)
    assert not destination.exists() and not list(destination.parent.glob(".ragforge-setup-*"))
    assert sentinel.read_text() == "preserve"

    def success(command, **kwargs):
        shutil.copytree(tiny_model, Path(command[-1]))

    monkeypatch.setattr(setup.subprocess, "run", success)
    assert setup.prepare(destination, **args) == destination
    assert model_spec(destination) == model_spec(tiny_model)
    assert not list(destination.parent.glob(".ragforge-setup-*"))


def test_setup_refuses_wrong_existing_package_and_offline_download(
    setup,
    tiny_model,
    tmp_path,
    monkeypatch,
):
    before = (tiny_model / "model.json").read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected download")

    monkeypatch.setattr(setup.subprocess, "run", forbidden)
    args = arguments(setup, tiny_model)
    with pytest.raises(ValueError, match="Unexpected model"):
        setup.prepare(tiny_model, **{**args, "expected_revision": "0" * 40})
    assert (tiny_model / "model.json").read_bytes() == before
    with pytest.raises(ValueError, match="without -Offline"):
        setup.prepare(tmp_path / "missing-model", **{**args, "offline": True})
    assert not (tmp_path / "missing-model").exists()


def test_setup_activates_both_models_only_after_success(
    setup,
    tiny_model,
    tiny_reranker,
    tmp_path,
    monkeypatch,
):
    import json

    from ragforge.core.rerank import reranker_spec
    from ragforge.quickstart import model_paths

    query_spec = model_spec(tiny_model)
    rank_spec = reranker_spec(tiny_reranker)
    candidate = {
        **setup.CANDIDATES["e5-small"],
        "id": query_spec.model_id,
        "revision": query_spec.revision,
    }
    monkeypatch.setattr(setup, "CANDIDATES", {"e5-small": candidate})
    monkeypatch.setattr(setup, "MMARCO_MODEL", rank_spec.model_id)
    monkeypatch.setattr(setup, "MMARCO_REVISION", rank_spec.revision)

    def forbidden(*args, **kwargs):
        raise AssertionError("all models are already present")

    monkeypatch.setattr(setup.subprocess, "run", forbidden)
    models = tmp_path / "models"
    shutil.copytree(tiny_model, models / "e5-small")
    shutil.copytree(tiny_reranker, models / "mmarco-minilm-reranker")
    paths = setup.setup_models(tmp_path, models, offline=True)
    assert model_paths(tmp_path) == paths
    state = tmp_path / ".cache/quickstart/models.json"
    before = state.read_bytes()
    assert json.loads(before)["reranker"] == str(models / "mmarco-minilm-reranker")
    (models / "mmarco-minilm-reranker/reranker.json").write_text("{}")
    with pytest.raises(ValueError):
        setup.setup_models(tmp_path, models, offline=True)
    assert state.read_bytes() == before
