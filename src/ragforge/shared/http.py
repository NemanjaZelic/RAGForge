"""Authenticated REST and stateless MCP HTTP over exactly one shared BundleEngine."""

import os
import sqlite3
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import TypeVar
from urllib.parse import urlsplit

# Disable inherited telemetry before importing the MCP/ASGI stack.
os.environ["OTEL_SDK_DISABLED"] = "true"

import anyio
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import RequestBodyLimitMiddleware, TransportSecuritySettings
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ragforge import __version__
from ragforge.adapters.mcp import create_server
from ragforge.core.contracts import FetchContextRequest, RetrievalResponse, RetrieveRequest
from ragforge.core.engine import BundleEngine
from ragforge.shared.policy import READ_SCOPE, JWTVerifier, ScopedEngine, SharedPolicy
from ragforge.types import ContractModel

MAX_BODY_BYTES = 65536
R = TypeVar("R", bound=ContractModel)


class HTTPBoundary:
    def __init__(self, app: ASGIApp, policy: SharedPolicy) -> None:
        self.app = RequestBodyLimitMiddleware(app, max_body_size=MAX_BODY_BYTES)
        resource = urlsplit(str(policy.resource_url))
        self.host = resource.netloc
        self.origin = resource.scheme + "://" + resource.netloc

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        hosts = [v.decode("latin-1") for k, v in scope["headers"] if k.lower() == b"host"]
        origins = [v.decode("latin-1") for k, v in scope["headers"] if k.lower() == b"origin"]
        if hosts != [self.host]:
            await JSONResponse({"error": "invalid_host"}, status_code=421)(scope, receive, send)
            return
        if origins and origins != [self.origin]:
            await JSONResponse({"error": "invalid_origin"}, status_code=403)(scope, receive, send)
            return
        body_complete, response_started = False, False
        deadline = time.monotonic() + 10

        async def bounded_receive() -> Message:
            nonlocal body_complete
            if body_complete:
                return await receive()
            with anyio.fail_after(max(0, deadline - time.monotonic())):
                message = await receive()
            if message["type"] == "http.request" and not message.get("more_body", False):
                body_complete = True
            return message

        async def private_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                    ],
                }
            await send(message)

        try:
            await self.app(scope, bounded_receive, private_send)
        except TimeoutError:
            if response_started:
                raise
            await JSONResponse({"error": "request_body_timeout"}, status_code=408)(
                scope, receive, private_send
            )


def create_shared_app(artifact: Path, policy: SharedPolicy, *, threads: int = 4) -> ASGIApp:
    engine = BundleEngine(artifact, threads=threads)
    scoped = ScopedEngine(engine, policy)
    verifier = JWTVerifier(policy)
    server = create_server(
        artifact,
        engine=scoped,
        token_verifier=verifier,
        auth=AuthSettings(
            issuer_url=policy.issuer_url,
            resource_server_url=policy.resource_url,
            required_scopes=[READ_SCOPE],
            validate_token_resource=True,
        ),
    )

    def rejected(code: int) -> JSONResponse:
        headers = {"WWW-Authenticate": 'Bearer error="invalid_token"'} if code == 401 else None
        return JSONResponse(
            {"error": "authentication_required" if code == 401 else "access_denied"},
            status_code=code,
            headers=headers,
        )

    async def perform(
        request: Request, model: type[R], operation: Callable[[R], RetrievalResponse]
    ) -> Response:
        if get_access_token() is None:
            return rejected(401)
        try:
            scoped.principal()
            if (
                request.headers.get("content-type", "").split(";", 1)[0].lower()
                != "application/json"
            ):
                return JSONResponse({"error": "expected_json"}, status_code=415)
            parsed = model.model_validate_json(await request.body())
            response = await anyio.to_thread.run_sync(partial(operation, parsed))
            return JSONResponse(response.model_dump(mode="json"))
        except PermissionError:
            return rejected(403)
        except ValidationError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        except (ValueError, OSError, RuntimeError, sqlite3.Error):
            return JSONResponse({"error": "retrieval_failed"}, status_code=400)

    async def retrieve(request: Request) -> Response:
        return await perform(request, RetrieveRequest, scoped.retrieve)

    async def context(request: Request) -> Response:
        return await perform(request, FetchContextRequest, scoped.fetch_context)

    async def collections(request: Request) -> Response:
        if get_access_token() is None:
            return rejected(401)
        try:
            rows = await anyio.to_thread.run_sync(scoped.list_collections)
            return JSONResponse({"collections": [row.model_dump(mode="json") for row in rows]})
        except PermissionError:
            return rejected(403)

    async def health(request: Request) -> Response:
        if get_access_token() is None:
            return rejected(401)
        try:
            scoped.principal()
            return JSONResponse({"status": "ready", "build_id": engine.manifest.build_id})
        except PermissionError:
            return rejected(403)

    async def metadata(request: Request) -> Response:
        if get_access_token() is None:
            return rejected(401)
        try:
            scoped.principal()
            return JSONResponse(
                {
                    "contract_version": "1",
                    "runtime_version": __version__,
                    "build_id": engine.manifest.build_id,
                    "profile": engine.manifest.profile,
                    "capabilities": engine.manifest.capabilities,
                    "resource": str(policy.resource_url),
                }
            )
        except PermissionError:
            return rejected(403)

    server.custom_route("/retrieve", methods=["POST"])(retrieve)
    server.custom_route("/context", methods=["POST"])(context)
    server.custom_route("/collections", methods=["GET"])(collections)
    server.custom_route("/health", methods=["GET"])(health)
    server.custom_route("/metadata", methods=["GET"])(metadata)

    authority = urlsplit(str(policy.resource_url))
    security = TransportSecuritySettings(
        allowed_hosts=[authority.netloc],
        allowed_origins=[authority.scheme + "://" + authority.netloc],
    )
    app = server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        max_request_body_size=MAX_BODY_BYTES,
        transport_security=security,
    )
    return HTTPBoundary(app, policy)


def run_shared(
    artifact: Path,
    policy_file: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    threads: int = 4,
    tls_cert: Path | None = None,
    tls_key: Path | None = None,
) -> None:
    import ipaddress
    import ssl

    import uvicorn

    loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    if bool(tls_cert) != bool(tls_key):
        raise ValueError("TLS requires both certificate and private key")
    if not loopback and tls_cert is None:
        raise ValueError("non-loopback shared listeners require explicit TLS certificate/key")
    policy = SharedPolicy.read(policy_file)
    if tls_cert is not None and policy.resource_url.scheme != "https":
        raise ValueError("TLS listener requires an HTTPS resource URL")
    application = create_shared_app(artifact, policy, threads=threads)
    uvicorn.run(
        application,
        host=host,
        port=port,
        access_log=False,
        log_level="warning",
        proxy_headers=False,
        limit_concurrency=16,
        timeout_keep_alive=5,
        timeout_graceful_shutdown=15,
        ssl_version=ssl.PROTOCOL_TLS_SERVER,
        ssl_certfile=str(tls_cert) if tls_cert else None,
        ssl_keyfile=str(tls_key) if tls_key else None,
    )
