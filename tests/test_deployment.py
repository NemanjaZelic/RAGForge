"""Actual bundle/version smoke tests with atomic operator-controlled rollback."""

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from typer.testing import CliRunner

from ragforge.artifacts.builder import build_bundle
from ragforge.cli import app
from ragforge.core.contracts import RetrieveRequest
from ragforge.core.engine import BundleEngine
from ragforge.shared.client import SharedClient
from ragforge.shared.policy import SharedPolicy
from ragforge.shared.registry import activate, create_deployment, read_deployment, rollback


@pytest.fixture
def versions(tmp_path, tiny_model):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        private.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "issuer_url": "https://identity.example.invalid",
                "resource_url": "http://127.0.0.1:8765/mcp",
                "verification_keys": [{"key_id": "test-key", "public_key_pem": public}],
                "principals": [{"subject": "alice", "collection_id": "docs"}],
            }
        ),
        encoding="utf-8",
    )
    bundles = []
    for version in (1, 2):
        source = tmp_path / f"source-v{version}"
        source.mkdir()
        (source / "a.txt").write_text(f"alpha evidence version {version}", encoding="utf-8")
        bundle = tmp_path / f"bundle-v{version}"
        build_bundle(
            source, bundle, collection_id="docs", model_directory=tiny_model, dense_backend="ann"
        )
        bundles.append(bundle)
    return bundles, policy


def test_prepare_activate_rollback_reuses_real_immutable_bundles_and_hides_probe(
    tmp_path, versions, monkeypatch
):
    bundles, policy = versions
    root = tmp_path / "deployment with spaces"
    state = create_deployment(bundles[0], root, policy, "alpha")
    assert state.active.smoke_methods == ["bm25", "dense", "hybrid"]
    initial = state.active.build_id
    assert not state.previous
    files = "\n".join(p.read_text(encoding="utf-8") for p in root.glob("*.json"))
    assert "alpha" not in files
    assert "BEGIN PRIVATE KEY" not in files
    launcher = json.loads((root / "serve.json").read_text(encoding="utf-8"))
    assert launcher["started"] is False and "--deployment" in launcher["command"]
    monkeypatch.setenv("RAGFORGE_ACCESS_TOKEN", "synthetic-never-saved")
    client = SharedClient.configured(None, root / "connection.json")
    assert client.endpoint == "http://127.0.0.1:8765"
    assert "synthetic-never-saved" not in files
    updated = activate(root, bundles[1], "alpha")
    assert updated.active.build_id != initial
    assert updated.previous[0].build_id == initial
    selected = BundleEngine(Path(read_deployment(root).active.path))
    assert selected.retrieve(RetrieveRequest(query="alpha")).results[0].text.endswith("2")
    restored = rollback(root, "alpha")
    assert restored.active.build_id == initial
    assert (
        BundleEngine(Path(restored.active.path))
        .retrieve(RetrieveRequest(query="alpha"))
        .results[0]
        .text.endswith("1")
    )
    assert restored.previous[0].build_id == updated.active.build_id
    assert activate(root, bundles[0], "alpha") == restored  # Idempotent activation.


def test_failed_candidate_or_corrupt_previous_version_preserves_active_pointer(tmp_path, versions):
    bundles, policy = versions
    root = tmp_path / "deployment"
    create_deployment(bundles[0], root, policy, "alpha")
    before = (root / "deployment.json").read_bytes()
    with pytest.raises(ValueError, match="smoke test"):
        activate(root, bundles[1], "nevermatchesinventory")
    assert (root / "deployment.json").read_bytes() == before
    activate(root, bundles[1], "alpha")
    before = (root / "deployment.json").read_bytes()
    previous_index = bundles[0] / "collections/docs/index.sqlite"
    previous_index.write_bytes(b"corrupted previous data")
    with pytest.raises(ValueError):
        rollback(root, "alpha")
    assert (root / "deployment.json").read_bytes() == before


def test_cli_prepares_without_starting_and_refuses_tampered_active_build(
    tmp_path, versions, monkeypatch
):
    bundles, policy = versions
    root = tmp_path / "deployment"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "deploy",
            str(bundles[0]),
            "--output",
            str(root),
            "--auth-file",
            str(policy),
            "--smoke-query",
            "alpha",
        ],
    )
    assert result.exit_code == 0, result.output
    status = json.loads(result.output)
    assert status["server_started"] is False and status["remote_resources_created"] is False
    result = runner.invoke(
        app, ["activate", str(bundles[1]), "--deployment", str(root), "--smoke-query", "alpha"]
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["rollback", "--deployment", str(root), "--smoke-query", "alpha"])
    assert result.exit_code == 0, result.output
    body = json.loads((root / "deployment.json").read_text(encoding="utf-8"))
    body["active"]["build_id"] = "0" * 64
    (root / "deployment.json").write_text(json.dumps(body), encoding="utf-8")
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: pytest.fail("must not bind a listener"))
    result = runner.invoke(app, ["serve", "--transport", "http", "--deployment", str(root)])
    assert result.exit_code == 2 and "build ID" in result.output
    assert runner.invoke(app, ["serve", "--deployment", str(root)]).exit_code == 2


def test_invalid_policy_error_never_echoes_accidentally_supplied_token(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text('{"access_token":"PRIVATE_POLICY_SECRET"}', encoding="utf-8")
    with pytest.raises(ValueError) as error:
        SharedPolicy.read(path)
    assert "PRIVATE_POLICY_SECRET" not in str(error.value)
