"""Explicit shared client. No redirects, environment proxies or implicit token discovery."""

import ipaddress
import os
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, ValidationError

from ragforge.core.contracts import (
    CollectionDescription,
    FetchContextRequest,
    RetrievalResponse,
    RetrieveRequest,
)
from ragforge.types import ContractModel, Sha256


class CollectionsResponse(ContractModel):
    collections: list[CollectionDescription]


class HealthResponse(ContractModel):
    status: Literal["ready"]
    build_id: Sha256


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


class SharedClient:
    def __init__(
        self,
        endpoint: str,
        token: str,
        *,
        ca_file: Path | None = None,
        timeout_seconds: float = 120,
    ) -> None:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError(
                "shared endpoint must be an HTTP(S) origin without credentials or path"
            )
        try:
            loopback = (
                parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname).is_loopback
            )
        except ValueError:
            loopback = False
        if parsed.scheme == "http" and not loopback:
            raise ValueError("non-loopback shared endpoints require HTTPS")
        if not 1 <= len(token) <= 16384 or any(not 33 <= ord(c) <= 126 for c in token):
            raise ValueError("shared client requires a nonblank bearer token without whitespace")
        if not 0 < timeout_seconds <= 300:
            raise ValueError("shared timeout must be greater than zero and at most 300 seconds")
        self.endpoint, self.token, self.timeout = (
            str(AnyHttpUrl(endpoint)).rstrip("/"),
            token,
            timeout_seconds,
        )
        context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            NoRedirect(),
            urllib.request.HTTPSHandler(context=context),
        )

    @classmethod
    def from_environment(
        cls, endpoint: str, token_env: str = "RAGFORGE_ACCESS_TOKEN", *, ca_file: Path | None = None
    ) -> Self:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", token_env):
            raise ValueError("invalid token environment variable name")
        return cls(endpoint, os.environ.get(token_env, ""), ca_file=ca_file)

    def _request(self, path: str, data: bytes | None = None) -> bytes:
        request = urllib.request.Request(
            self.endpoint + path,
            data=data,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                if (
                    response.status != 200
                    or response.headers.get_content_type() != "application/json"
                ):
                    raise ValueError("unexpected shared response status or content type")
                raw = response.read(2 * 1024**2 + 1)
            if not isinstance(raw, bytes):
                raise ValueError("invalid shared response body")
            if len(raw) > 2 * 1024**2:
                raise ValueError("shared response exceeds 2 MiB")
            return raw
        except urllib.error.HTTPError as error:
            raise ValueError(f"shared request rejected (HTTP {error.code})") from None
        except urllib.error.URLError:
            raise ValueError("shared connection failed; check endpoint and TLS trust") from None

    def retrieve(self, request: RetrieveRequest) -> RetrievalResponse:
        try:
            result = RetrievalResponse.model_validate_json(
                self._request("/retrieve", request.model_dump_json().encode())
            )
        except ValidationError:
            raise ValueError("shared server returned an invalid retrieval contract") from None
        if (
            len(result.results) > request.top_k
            or sum(len(r.text) for r in result.results) > request.max_output_chars
            or request.collection_id is not None
            and any(r.collection_id != request.collection_id for r in result.results)
            or request.filters is not None
            and any(r.document_id not in request.filters.document_ids for r in result.results)
        ):
            raise ValueError("shared response escaped the requested scope or budget")
        return result

    def fetch_context(self, request: FetchContextRequest) -> RetrievalResponse:
        try:
            result = RetrievalResponse.model_validate_json(
                self._request("/context", request.model_dump_json().encode())
            )
        except ValidationError:
            raise ValueError("shared server returned an invalid context contract") from None
        if (
            sum(len(r.text) for r in result.results) > request.max_output_chars
            or any(r.collection_id != request.collection_id for r in result.results)
            or len(result.results) > 2 * request.neighbors + 1
            or len({r.document_id for r in result.results}) > 1
            or not any(r.chunk_id == request.chunk_id for r in result.results)
        ):
            raise ValueError("shared context escaped the requested scope or budget")
        return result

    def list_collections(self) -> list[CollectionDescription]:
        try:
            return CollectionsResponse.model_validate_json(
                self._request("/collections")
            ).collections
        except ValidationError:
            raise ValueError("shared server returned an invalid collection contract") from None

    def health(self) -> dict[str, object]:
        try:
            return HealthResponse.model_validate_json(self._request("/health")).model_dump()
        except ValidationError:
            raise ValueError(
                "shared server is not ready or returned an invalid health contract"
            ) from None
