"""Actual loopback REST/MCP clients, JWT verification and source access boundaries."""

import asyncio
import datetime
import ipaddress
import json
import os
import socket
import ssl
import subprocess
import sys
import threading
import time
from contextlib import contextmanager

import httpx2
import jwt
import pytest
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from ragforge.artifacts.builder import build_bundle
from ragforge.core.contracts import RetrieveRequest
from ragforge.core.engine import BundleEngine
from ragforge.shared.client import SharedClient
from ragforge.shared.http import create_shared_app, run_shared
from ragforge.shared.policy import JWTVerifier, SharedPolicy


@pytest.fixture
def identity():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        private.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private, public


def policy_for(identity, url, collection="docs", principals=None):
    return SharedPolicy.model_validate_json(
        json.dumps(
            {
                "issuer_url": "https://identity.example.invalid",
                "resource_url": url + "/mcp",
                "verification_keys": [{"key_id": "key-1", "public_key_pem": identity[1]}],
                "principals": principals or [{"subject": "all", "collection_id": collection}],
            }
        )
    )


def token_for(identity, policy, subject="all", **overrides):
    now = int(time.time())
    claims = {
        "sub": subject,
        "iss": str(policy.issuer_url),
        "aud": str(policy.resource_url),
        "iat": now,
        "exp": now + 300,
        "scope": "retrieval:read",
        **overrides,
    }
    return jwt.encode(claims, identity[0], algorithm="RS256", headers={"kid": "key-1"})


@contextmanager
def listener(bundle, identity, principals=None, **tls):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    url = ("https" if tls else "http") + f"://127.0.0.1:{port}"
    policy = policy_for(identity, url, principals=principals)
    app = create_shared_app(bundle, policy)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            access_log=False,
            log_level="warning",
            proxy_headers=False,
            lifespan="on",
            timeout_graceful_shutdown=2,
            **tls,
        )
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        yield url, policy
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        sock.close()
        assert not thread.is_alive()


def test_jwt_verifier_fails_closed_without_discovery_requests(identity, monkeypatch):
    policy = policy_for(identity, "http://127.0.0.1:8765")
    assert str(policy.issuer_url) == "https://identity.example.invalid"  # No added slash.
    verifier = JWTVerifier(policy)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: pytest.fail("no auth discovery"))
    assert verifier.verify(token_for(identity, policy)).subject == "all"
    now = int(time.time())
    for changed in (
        {"aud": "https://different.example/mcp"},
        {"iss": "https://different.example"},
        {"sub": "unknown"},
        {"iat": now - 100, "exp": now - 1},
        {"nbf": now + 100},
        {"iat": now + 100},
        {"exp": now + 4000},
        {"exp": True},
        {"scope": ["retrieval:read"]},
    ):
        assert verifier.verify(token_for(identity, policy, **changed)) is None
    for header in (
        {"jku": "https://attacker.example/keys"},
        {"crit": ["unknown"]},
        {"jwk": {"kty": "oct"}},
    ):
        body = {
            "sub": "all",
            "iss": str(policy.issuer_url),
            "aud": str(policy.resource_url),
            "iat": now,
            "exp": now + 300,
        }
        assert (
            verifier.verify(
                jwt.encode(body, identity[0], algorithm="RS256", headers={"kid": "key-1", **header})
            )
            is None
        )
    assert verifier.verify("not.a.token") is None
    assert verifier.verify("x" * 16385) is None
    claims = {
        "sub": "all",
        "aud": str(policy.resource_url),
        "iss": str(policy.issuer_url),
        "exp": now + 300,
        "iat": now,
    }
    assert (
        verifier.verify(
            jwt.encode(claims, "attacker" * 8, algorithm="HS256", headers={"kid": "key-1"})
        )
        is None
    )
    assert (
        verifier.verify(
            jwt.encode(claims, identity[0], algorithm="RS256", headers={"kid": "unknown"})
        )
        is None
    )
    assert verifier.verify(jwt.encode(claims, None, algorithm="none")) is None


@pytest.mark.parametrize("backend", ["minimal", "exact", "ann"])
def test_rest_mcp_parity_and_parallel_principal_isolation(tmp_path, tiny_model, identity, backend):
    source = tmp_path / "source"
    source.mkdir()
    (source / "allowed.txt").write_text("alpha public rollback durability", encoding="utf-8")
    sentinel = "PRIVATE_SHARED_SENTINEL"
    (source / "secret.txt").write_text("alpha " + sentinel, encoding="utf-8")
    bundle = tmp_path / "bundle"
    build_bundle(
        source,
        bundle,
        collection_id="docs",
        profile=("minimal" if backend == "minimal" else "balanced"),
        model_directory=None if backend == "minimal" else tiny_model,
        dense_backend="ann" if backend == "ann" else "exact",
    )
    engine = BundleEngine(bundle)
    allowed = next(
        d.document_id for d in engine.collection.documents if d.source_path == "allowed.txt"
    )
    forbidden = engine.retrieve(RetrieveRequest(query=sentinel, search_method="bm25")).results[0]
    principals = [
        {"subject": "all", "collection_id": "docs"},
        {"subject": "restricted", "collection_id": "docs", "document_ids": [allowed]},
    ]
    with listener(bundle, identity, principals) as (url, policy):

        async def exercise():
            full_token, limited_token = (
                token_for(identity, policy, sub) for sub in ("all", "restricted")
            )
            async with httpx2.AsyncClient(trust_env=False) as http:
                for path in ("/health", "/collections", "/metadata"):
                    assert (await http.get(url + path)).status_code == 401
                assert (
                    await http.get(url + "/health", headers={"Authorization": "Bearer bad"})
                ).status_code == 401
                assert (
                    await http.get(url + "/health", headers={"Origin": "https://attacker.example"})
                ).status_code == 403
                assert (
                    await http.get(url + "/health", headers={"Host": "attacker.example"})
                ).status_code == 421
                metadata = await http.get(url + "/.well-known/oauth-protected-resource/mcp")
                assert metadata.status_code == 200
                assert metadata.json()["resource"] == str(policy.resource_url)
                headers = {"Authorization": "Bearer " + full_token}
                assert (await http.get(url + "/health", headers=headers)).json()[
                    "status"
                ] == "ready"
                for method in engine.manifest.capabilities:
                    request = {"query": "alpha", "top_k": 2, "search_method": method}
                    response = await http.post(url + "/retrieve", headers=headers, json=request)
                    assert response.status_code == 200
                    assert response.json() == engine.retrieve(
                        RetrieveRequest(**request)
                    ).model_dump(mode="json")
                shared = SharedClient(url, full_token)
                assert (
                    shared.retrieve(
                        RetrieveRequest(query="alpha", search_method="bm25")
                    ).model_dump()
                    == engine.retrieve(
                        RetrieveRequest(query="alpha", search_method="bm25")
                    ).model_dump()
                )
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "ragforge",
                        "use",
                        "--mode",
                        "shared",
                        "--endpoint",
                        url,
                        "--query",
                        "alpha",
                        "--search-method",
                        "bm25",
                    ],
                    env={**os.environ, "RAGFORGE_ACCESS_TOKEN": full_token},
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                assert completed.returncode == 0, completed.stderr
                assert json.loads(completed.stdout) == engine.retrieve(
                    RetrieveRequest(query="alpha", search_method="bm25")
                ).model_dump(mode="json")
                selected = engine.retrieve(
                    RetrieveRequest(query="alpha", search_method="bm25")
                ).results[0]
                from ragforge.core.contracts import FetchContextRequest

                context_args = FetchContextRequest(collection_id="docs", chunk_id=selected.chunk_id)
                assert shared.fetch_context(context_args) == engine.fetch_context(context_args)
                for arguments, expected in (
                    (
                        ["context", selected.chunk_id, "--mode", "shared", "--endpoint", url],
                        engine.fetch_context(context_args).model_dump(mode="json"),
                    ),
                    (["doctor", "--endpoint", url], None),
                ):
                    completed = subprocess.run(
                        [sys.executable, "-m", "ragforge", *arguments],
                        env={**os.environ, "RAGFORGE_ACCESS_TOKEN": full_token},
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    assert completed.returncode == 0, completed.stderr
                    observed = json.loads(completed.stdout)
                    if expected is not None:
                        assert observed == expected
                    else:
                        assert (
                            observed["mode"] == "shared" and observed["health"]["status"] == "ready"
                        )
                restricted = {"Authorization": "Bearer " + limited_token}
                listing = (await http.get(url + "/collections", headers=restricted)).json()
                assert listing["collections"][0]["document_count"] == 1
                response = await http.post(
                    url + "/retrieve",
                    headers=restricted,
                    json={"query": "alpha", "search_method": "bm25"},
                )
                assert {r["document_id"] for r in response.json()["results"]} == {allowed}
                bad = await http.post(
                    url + "/retrieve",
                    headers=restricted,
                    json={"query": "alpha", "filters": {"document_ids": [forbidden.document_id]}},
                )
                assert bad.status_code == 403 and sentinel not in bad.text
                bad = await http.post(
                    url + "/context",
                    headers=restricted,
                    json={"collection_id": "docs", "chunk_id": forbidden.chunk_id},
                )
                assert bad.status_code == 403 and sentinel not in bad.text
                oversized = await http.post(
                    url + "/retrieve", headers=headers, content=b"x" * 65537
                )
                assert oversized.status_code == 413
                wrong_type = await http.post(
                    url + "/retrieve", headers=headers, json={"query": "alpha", "top_k": True}
                )
                assert wrong_type.status_code == 400 and "alpha" not in wrong_type.text
                no_scope = await http.get(
                    url + "/health",
                    headers={
                        "Authorization": "Bearer " + token_for(identity, policy, scope="other")
                    },
                )
                assert no_scope.status_code == 403

            async def mcp_client(subject):
                async with httpx2.AsyncClient(
                    trust_env=False,
                    headers={"Authorization": "Bearer " + token_for(identity, policy, subject)},
                ) as http:
                    async with Client(
                        streamable_http_client(url + "/mcp", http_client=http)
                    ) as client:
                        assert {t.name for t in (await client.list_tools()).tools} == {
                            "search_docs",
                            "fetch_context",
                            "list_collections",
                        }
                        for method in engine.manifest.capabilities:
                            result = await client.call_tool(
                                "search_docs",
                                {"query": "alpha", "search_method": method, "top_k": 2},
                            )
                            assert not result.is_error
                            rows = result.structured_content["results"]
                            if subject == "restricted":
                                assert {r["document_id"] for r in rows} == {allowed}
                                assert (
                                    await client.call_tool(
                                        "fetch_context",
                                        {"collection_id": "docs", "chunk_id": forbidden.chunk_id},
                                    )
                                ).is_error
                            else:
                                assert len(rows) == 2

            await asyncio.gather(mcp_client("restricted"), mcp_client("all"))

        asyncio.run(asyncio.wait_for(exercise(), timeout=60))


def test_nonloopback_listener_requires_tls_before_opening_policy(tmp_path):
    with pytest.raises(ValueError, match="non-loopback.*TLS"):
        run_shared(tmp_path / "bundle", tmp_path / "missing-policy", host="0.0.0.0")
    with pytest.raises(ValueError, match="both certificate"):
        run_shared(tmp_path / "bundle", tmp_path / "missing-policy", tls_cert=tmp_path / "cert")


def test_real_tls_listener_and_client_verify_certificate(tmp_path, identity):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("TLS alpha evidence", encoding="utf-8")
    bundle = tmp_path / "bundle"
    build_bundle(source, bundle, profile="minimal", collection_id="docs")
    tls_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(tls_private.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(tls_private, hashes.SHA256())
    )
    certificate, key = tmp_path / "certificate.pem", tmp_path / "key.pem"
    certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key.write_bytes(
        tls_private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    with listener(bundle, identity, ssl_certfile=str(certificate), ssl_keyfile=str(key)) as (
        url,
        policy,
    ):
        token = token_for(identity, policy)
        client = SharedClient(url, token, ca_file=certificate)
        assert client.health()["status"] == "ready"
        assert (
            client.retrieve(RetrieveRequest(query="alpha")).results[0].text == "TLS alpha evidence"
        )
        with pytest.raises(ValueError, match="TLS trust"):
            SharedClient(url, token).health()

        async def exercise():
            trust = ssl.create_default_context(cafile=str(certificate))
            async with httpx2.AsyncClient(
                trust_env=False, verify=trust, headers={"Authorization": "Bearer " + token}
            ) as http:
                async with Client(streamable_http_client(url + "/mcp", http_client=http)) as mcp:
                    assert not (await mcp.call_tool("search_docs", {"query": "alpha"})).is_error

        asyncio.run(asyncio.wait_for(exercise(), timeout=30))


def test_policy_conversion_uses_only_supplied_public_jwks_and_never_overwrites(tmp_path, identity):
    import importlib.util
    from pathlib import Path

    from jwt.algorithms import RSAAlgorithm

    location = Path(__file__).resolve().parents[1] / "scripts/prepare_shared_policy.py"
    spec = importlib.util.spec_from_file_location("prepare_shared_policy", location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    jwk = json.loads(RSAAlgorithm.to_jwk(identity[0].public_key()))
    jwk.update(kid="key-1", alg="RS256", use="sig")
    source, output = tmp_path / "jwks.json", tmp_path / "policy.json"
    source.write_text(json.dumps({"keys": [jwk]}), encoding="utf-8")
    before = source.read_bytes()
    result = module.prepare(
        source,
        output,
        issuer="https://identity.example.invalid",
        resource="http://127.0.0.1:8765/mcp",
        collection="docs",
        subjects=["all"],
    )
    assert result["network_used"] is False and result["tokens_created"] is False
    policy = SharedPolicy.read(output)
    assert JWTVerifier(policy).verify(token_for(identity, policy)).subject == "all"
    assert source.read_bytes() == before
    with pytest.raises(FileExistsError):
        module.prepare(
            source,
            output,
            issuer="https://identity.example.invalid",
            resource="http://127.0.0.1:8765/mcp",
            collection="docs",
            subjects=["all"],
        )
    private = json.loads(RSAAlgorithm.to_jwk(identity[0]))
    private.update(kid="key-1")
    source.write_text(json.dumps({"keys": [private]}), encoding="utf-8")
    forbidden_output = tmp_path / "forbidden.json"
    with pytest.raises(ValueError, match="public RSA"):
        module.prepare(
            source,
            forbidden_output,
            issuer="https://identity.example.invalid",
            resource="http://127.0.0.1:8765/mcp",
            collection="docs",
            subjects=["all"],
        )
    assert not forbidden_output.exists()
