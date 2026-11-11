import asyncio
import datetime
import ipaddress
import json
import socket
import ssl
import threading
import time

import httpx2
import pytest
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from ragforge.artifacts.builder import build_bundle
from ragforge.quickstart import main
from ragforge.shared.policy import JWTVerifier, SharedPolicy


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    docs = tmp_path / "documents"
    docs.mkdir()
    (docs / "guide.txt").write_text("alpha authentication evidence", encoding="utf-8")
    bundle = tmp_path / "bundle"
    manifest = build_bundle(docs, bundle, profile="minimal", collection_id="docs")
    state = tmp_path / ".cache/quickstart"
    state.mkdir(parents=True)
    (state / "active.json").write_text(
        json.dumps(
            {
                "bundle": str(bundle),
                "build_id": manifest.build_id,
            }
        )
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    certificate = secrets / "server.pem"
    certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (secrets / "server-key.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    monkeypatch.setattr(
        "ragforge.shared.quickstart.getpass.getpass", lambda _: "test-password-long"
    )
    return tmp_path, certificate


def test_two_original_commands_serve_real_authenticated_tls_rest_and_mcp(
    prepared, monkeypatch, capsys
):
    project, certificate = prepared
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    origin = f"https://127.0.0.1:{port}"
    prefix = ["--project", str(project)]
    assert (
        main(
            [
                *prefix,
                "server-setup",
                "--url",
                origin + "/mcp",
                "--client",
                "ai-one",
                "--client",
                "ai-two",
            ]
        )
        == 0
    )
    root = project / "secrets/server"
    clients = next(root.glob("clients-*"))
    token = (clients / "ai-one.jwt").read_text()
    assert token not in capsys.readouterr().out
    assert "BEGIN ENCRYPTED PRIVATE KEY" in (root / "signing-key.pem").read_text()
    assert "signing-key" not in (clients / "CONNECT.md").read_text()

    def run(app, **options):
        assert options["host"] == "0.0.0.0" and options["port"] == port
        server = uvicorn.Server(uvicorn.Config(app, **options))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert server.started
            trust = ssl.create_default_context(cafile=str(certificate))
            headers = {"Authorization": "Bearer " + token}
            with httpx2.Client(verify=trust, trust_env=False) as client:
                assert client.get(origin + "/health").status_code == 401
                result = client.post(
                    origin + "/retrieve", headers=headers, json={"query": "authentication"}
                )
                assert result.status_code == 200
                assert result.json()["results"][0]["source"]["path"] == "guide.txt"

            async def mcp_call():
                async with httpx2.AsyncClient(
                    verify=trust, trust_env=False, headers=headers
                ) as http:
                    async with Client(
                        streamable_http_client(origin + "/mcp", http_client=http)
                    ) as ai:
                        result = await ai.call_tool("search_docs", {"query": "authentication"})
                        assert not result.is_error
                        assert (
                            result.structured_content["results"][0]["source"]["path"] == "guide.txt"
                        )

            asyncio.run(mcp_call())
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive()

    monkeypatch.setattr(uvicorn, "run", run)
    assert main([*prefix, "server"]) == 0
    private_before = (root / "signing-key.pem").read_bytes()
    assert main([*prefix, "server-setup"]) == 0
    assert len(list(root.glob("clients-*"))) == 2
    assert (root / "signing-key.pem").read_bytes() == private_before
    policy = SharedPolicy.read(root / "shared-policy.json")
    assert JWTVerifier(policy).verify(token).subject == "ai-one"


@pytest.mark.parametrize("client", ["../escape", "duplicate", "password"])
def test_invalid_setup_leaves_no_partial_server(prepared, monkeypatch, client):
    project, _ = prepared
    args = ["--project", str(project), "server-setup", "--url", "https://example.com:8765/mcp"]
    if client == "password":
        monkeypatch.setattr("ragforge.shared.quickstart.getpass.getpass", lambda _: "short")
    else:
        args.extend(["--client", client])
        if client == "duplicate":
            args.extend(["--client", client])
    assert main(args) == 2
    assert not (project / "secrets/server").exists()
    assert not list((project / "secrets").glob(".server-*"))


def test_bad_certificate_and_missing_configuration_do_not_start_server(prepared, monkeypatch):
    project, certificate = prepared
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: pytest.fail("unexpected listener"))
    prefix = ["--project", str(project)]
    assert main([*prefix, "server"]) == 2
    certificate.write_text("not a certificate")
    assert main([*prefix, "server-setup", "--url", "https://example.com/mcp"]) == 2
    assert not (project / "secrets/server").exists()


def test_wrong_password_or_changed_url_cannot_replace_access(prepared, monkeypatch):
    project, _ = prepared
    prefix = ["--project", str(project)]
    assert main([*prefix, "server-setup", "--url", "https://example.com/mcp"]) == 0
    root = project / "secrets/server"
    original = (root / "shared-policy.json").read_bytes()
    assert main([*prefix, "server-setup", "--url", "https://other.example/mcp"]) == 2
    monkeypatch.setattr("ragforge.shared.quickstart.getpass.getpass", lambda _: "wrong password")
    assert main([*prefix, "server-setup"]) == 2
    assert (root / "shared-policy.json").read_bytes() == original
    assert len(list(root.glob("clients-*"))) == 1
