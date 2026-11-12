import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
import yaml

from ragforge.artifacts.builder import build_bundle
from ragforge.artifacts.verification import verify_bundle
from ragforge.quickstart import main
from ragforge.shared.client import ConnectionProfile
from ragforge.shared.policy import JWTVerifier, SharedPolicy
from ragforge.shared.public_docker import create_deployment, renew_clients, start_deployment

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def source_bundle(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "manual.txt").write_text("authentication alpha evidence", encoding="utf-8")
    bundle = tmp_path / "bundle"
    build_bundle(source, bundle, collection_id="docs", profile="minimal")
    monkeypatch.setattr(
        "ragforge.shared.public_docker.getpass.getpass", lambda _: "test-password-long"
    )
    return bundle


def test_publish_command_creates_portable_verified_deployment_without_private_build_context(
    tmp_path, source_bundle, capsys
):
    output = tmp_path / "deploy"
    assert (
        main(
            [
                "--project",
                str(ROOT),
                "publish",
                "--bundle",
                str(source_bundle),
                "--domain",
                "rag.example.com",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    policy = SharedPolicy.read(output / "secrets/shared-policy.json")
    token = (output / "clients/ai-client-1.jwt").read_text()
    assert JWTVerifier(policy).verify(token).subject == "ai-client-1"
    assert token not in capsys.readouterr().out
    profile = ConnectionProfile.read(output / "clients/connection.json")
    assert str(profile.endpoint).rstrip("/") == "https://rag.example.com"
    assert verify_bundle(output / "bundle").build_id == verify_bundle(source_bundle).build_id
    assert not (output / "runtime/secrets").exists()
    assert not (output / "runtime/.git").exists()
    assert not (output / "runtime/.venv").exists()
    if os.name == "posix":
        assert output.stat().st_mode & 0o777 == 0o700
        assert (output / "secrets/signing-key.pem").stat().st_mode & 0o777 == 0o600
        assert (output / "clients/ai-client-1.jwt").stat().st_mode & 0o777 == 0o600
        assert (output / "secrets/shared-policy.json").stat().st_mode & 0o004
        assert (output / "bundle").stat().st_mode & 0o005
        assert (output / "bundle/manifest.json").stat().st_mode & 0o004
    assert "!runtime/**" in (output / ".dockerignore").read_text()
    compose = json.loads((output / "compose.json").read_text())
    gateway, backend = compose["services"]["gateway"], compose["services"]["ragforge"]
    assert gateway["ports"] == ["80:80", "443:443"]
    assert backend["network_mode"] == "service:gateway"
    assert "ports" not in backend and "expose" not in backend
    assert "127.0.0.1" in backend["command"]
    assert all("signing-key" not in item and "clients" not in item for item in backend["volumes"])
    caddy = (output / "Caddyfile").read_text()
    assert caddy.startswith("rag.example.com {")
    assert "reverse_proxy 127.0.0.1:8765" in caddy and "tls " not in caddy
    for public in (output / "static").iterdir():
        assert token.encode() not in public.read_bytes()
    with zipfile.ZipFile(output / "static/ragforge-skill.zip") as archive:
        skill = archive.read("ragforge-docs/SKILL.md").decode()
        metadata = yaml.safe_load(skill.split("---")[1])
        assert metadata["name"] == "ragforge-docs" and metadata["description"]
        assert "search_docs" in skill and "fetch_context" in skill
    before = (output / "secrets/signing-key.pem").read_bytes()
    renewed = renew_clients(output)
    assert JWTVerifier(policy).verify((renewed / "ai-client-1.jwt").read_text())
    assert (output / "secrets/signing-key.pem").read_bytes() == before


@pytest.mark.parametrize(
    "domain", ["https://example.com", "x.com;evil", "localhost", "127.0.0.1", "x..com", "x.com:443"]
)
def test_invalid_domains_never_create_deployment(tmp_path, source_bundle, domain):
    output = tmp_path / "deploy"
    with pytest.raises(ValueError):
        create_deployment(ROOT, source_bundle, output, domain=domain)
    assert not output.exists()


def test_existing_output_and_invalid_password_are_not_overwritten(
    tmp_path, source_bundle, monkeypatch
):
    output = tmp_path / "deploy"
    monkeypatch.setattr("ragforge.shared.public_docker.getpass.getpass", lambda _: "short")
    with pytest.raises(ValueError, match="password"):
        create_deployment(ROOT, source_bundle, output, domain="rag.example.com")
    assert not output.exists()
    output.mkdir()
    (output / "keep.txt").write_text("keep")
    with pytest.raises(ValueError, match="new deployment"):
        create_deployment(ROOT, source_bundle, output, domain="rag.example.com")
    assert (output / "keep.txt").read_text() == "keep"


def test_explicit_start_uses_docker_argv_and_preserves_package_on_failure(tmp_path, monkeypatch):
    (tmp_path / "compose.json").write_text("{}")
    calls = []

    def failed(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr("ragforge.shared.public_docker.subprocess.run", failed)
    with pytest.raises(ValueError, match="startup failed"):
        start_deployment(tmp_path)
    assert calls[0] == [
        "docker",
        "compose",
        "-f",
        str(tmp_path / "compose.json"),
        "up",
        "-d",
        "--build",
    ]
    assert (tmp_path / "compose.json").exists()


@pytest.mark.skipif(
    os.environ.get("RAGFORGE_TEST_DOCKER") != "1" or not shutil.which("docker"),
    reason="explicit Docker integration environment required",
)
def test_actual_docker_proxy_and_backend(tmp_path, source_bundle):
    output = create_deployment(ROOT, source_bundle, tmp_path / "deploy", domain="ragforge.test")
    # Test the production proxy topology with Caddy's private CA; public ACME needs real DNS.
    caddy = (
        (output / "Caddyfile")
        .read_text()
        .replace("ragforge.test {", "ragforge.test {\n  tls internal")
    )
    (output / "Caddyfile").write_text(caddy)
    command = ["docker", "compose", "-f", str(output / "compose.json")]
    try:
        subprocess.run([*command, "config", "--quiet"], check=True)
        subprocess.run([*command, "up", "-d", "--build"], check=True, timeout=900)
        import time

        certificate = output / "root.crt"
        for _ in range(90):
            result = subprocess.run(
                [
                    *command,
                    "exec",
                    "-T",
                    "gateway",
                    "cat",
                    "/data/caddy/pki/authorities/local/root.crt",
                ],
                capture_output=True,
            )
            if result.returncode == 0:
                certificate.write_bytes(result.stdout)
                break
            time.sleep(1)
        assert certificate.exists()
        token = (output / "clients/ai-client-1.jwt").read_text()
        request = [
            "curl",
            "--silent",
            "--show-error",
            "--fail",
            "--noproxy",
            "*",
            "--resolve",
            "ragforge.test:443:127.0.0.1",
            "--cacert",
            str(certificate),
        ]
        for _ in range(90):
            result = subprocess.run(
                [
                    *request,
                    "https://ragforge.test/collections",
                    "-H",
                    "Authorization: Bearer " + token,
                ],
                capture_output=True,
            )
            if result.returncode == 0:
                break
            time.sleep(1)
        assert result.returncode == 0, result.stderr.decode()
        assert json.loads(result.stdout)["collections"][0]["collection_id"] == "docs"
        response = subprocess.run(
            [
                *request,
                "https://ragforge.test/retrieve",
                "-H",
                "Authorization: Bearer " + token,
                "-H",
                "Content-Type: application/json",
                "--data",
                '{"query":"authentication"}',
            ],
            capture_output=True,
            check=True,
        )
        assert json.loads(response.stdout)["results"][0]["source"]["path"] == "manual.txt"
        page = subprocess.run(
            [*request, "https://ragforge.test/connect"], capture_output=True, check=True
        )
        assert "Poveži AI" in page.stdout.decode()
    finally:
        subprocess.run([*command, "logs", "--tail=100"], check=False)
        subprocess.run([*command, "down", "--volumes"], check=False)
