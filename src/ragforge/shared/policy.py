"""Offline JWT verification and explicit source access around the unchanged bundle engine."""

import threading
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, ConfigDict, Field, model_validator

from ragforge.core.contracts import (
    CollectionDescription,
    FetchContextRequest,
    RetrievalFilters,
    RetrievalResponse,
    RetrieveRequest,
)
from ragforge.core.engine import BundleEngine
from ragforge.core.source import is_link
from ragforge.types import ContractModel, Identifier, Sha256

READ_SCOPE = "retrieval:read"


class VerificationKey(ContractModel):
    key_id: Annotated[str, Field(min_length=1, max_length=128)]
    public_key_pem: Annotated[str, Field(min_length=1, max_length=16384)]


class Principal(ContractModel):
    subject: Annotated[str, Field(min_length=1, max_length=256)]
    collection_id: Identifier
    document_ids: Annotated[list[Sha256], Field(min_length=1, max_length=100)] | None = None

    @model_validator(mode="after")
    def unique_documents(self) -> Self:
        if self.document_ids and len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError("duplicate document grant")
        return self


class SharedPolicy(ContractModel):
    model_config = ConfigDict(url_preserve_empty_path=True)

    schema_version: Literal["1"] = "1"
    issuer_url: AnyHttpUrl
    resource_url: AnyHttpUrl
    verification_keys: Annotated[list[VerificationKey], Field(min_length=1, max_length=10)]
    principals: Annotated[list[Principal], Field(min_length=1, max_length=1000)]
    max_token_lifetime_seconds: Annotated[int, Field(ge=60, le=86400)] = 3600

    @model_validator(mode="after")
    def valid_authorities(self) -> Self:
        issuer, resource = urlsplit(str(self.issuer_url)), urlsplit(str(self.resource_url))
        for url in (issuer, resource):
            if url.username or url.password or url.query or url.fragment:
                raise ValueError("auth authorities must not contain credentials/query/fragment")
            if url.scheme != "https" and url.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("non-loopback auth authorities require HTTPS")
        if resource.path != "/mcp":
            raise ValueError("shared resource URL must end with /mcp")
        if len({k.key_id for k in self.verification_keys}) != len(self.verification_keys):
            raise ValueError("duplicate verification key ID")
        if len({p.subject for p in self.principals}) != len(self.principals):
            raise ValueError("duplicate principal subject")
        return self

    @classmethod
    def read(cls, path: Path) -> "SharedPolicy":
        if is_link(path.lstat()) or path.stat().st_size > 8 * 1024**2:
            raise ValueError("unsafe/oversized shared policy")
        return cls.model_validate_json(path.read_bytes())


class JWTVerifier:
    """RS256 only, pinned local public keys, exact issuer/audience, expiry and subject."""

    def __init__(self, policy: SharedPolicy) -> None:
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
        from cryptography.hazmat.primitives.serialization import load_pem_public_key

        self.policy = policy
        self.principals = {p.subject: p for p in policy.principals}
        self.keys: dict[str, RSAPublicKey] = {}
        for key in policy.verification_keys:
            loaded = load_pem_public_key(key.public_key_pem.encode("ascii"))
            if not isinstance(loaded, RSAPublicKey) or loaded.key_size < 2048:
                raise ValueError(
                    "shared verification requires RSA public keys of at least 2048 bits"
                )
            self.keys[key.key_id] = loaded

    def verify(self, token: str) -> Any:
        import jwt
        from mcp.server.auth.provider import AccessToken

        if not 1 <= len(token) <= 16384:
            return None
        try:
            header = jwt.get_unverified_header(token)
            if (
                header.get("alg") != "RS256"
                or header.get("kid") not in self.keys
                or header.get("crit")
                or header.get("b64") is False
                or any(key in header for key in ("jku", "x5u", "jwk"))
            ):
                return None
            claims = jwt.decode(
                token,
                self.keys[header["kid"]],
                algorithms=["RS256"],
                issuer=str(self.policy.issuer_url),
                audience=str(self.policy.resource_url),
                options={"require": ["exp", "iat", "iss", "aud", "sub"], "strict_aud": True},
            )
            if (
                type(claims["iat"]) is not int
                or type(claims["exp"]) is not int
                or not 0 < claims["exp"] - claims["iat"] <= self.policy.max_token_lifetime_seconds
                or not isinstance(claims["sub"], str)
                or claims["sub"] not in self.principals
                or not isinstance(claims.get("scope", ""), str)
            ):
                return None
            return AccessToken(
                token=token,
                client_id=claims["sub"],
                subject=claims["sub"],
                scopes=claims.get("scope", "").split(),
                expires_at=claims["exp"],
                resource=str(self.policy.resource_url),
                claims={"iss": claims["iss"]},
            )
        except (jwt.PyJWTError, TypeError, ValueError, KeyError):
            return None

    async def verify_token(self, token: str) -> Any:
        return self.verify(token)


class ScopedEngine:
    """Per-request principal from the SDK auth context; CPU/model work is serialized."""

    def __init__(self, engine: BundleEngine, policy: SharedPolicy) -> None:
        self.engine, self.policy = engine, policy
        self.principals = {p.subject: p for p in policy.principals}
        self.lock = threading.RLock()
        inventory = {d.document_id for d in engine.collection.documents}
        for principal in policy.principals:
            if principal.collection_id != engine.collection.collection_id:
                raise ValueError("principal grant targets another collection")
            if principal.document_ids and not set(principal.document_ids) <= inventory:
                raise ValueError("principal grant contains unknown source IDs")

    def principal(self) -> Principal:
        from mcp.server.auth.middleware.auth_context import get_access_token

        token = get_access_token()
        if (
            token is None
            or READ_SCOPE not in token.scopes
            or not isinstance(token.subject, str)
            or token.subject not in self.principals
        ):
            raise PermissionError("retrieval access denied")
        return self.principals[token.subject]

    def retrieve(self, request: RetrieveRequest) -> RetrievalResponse:
        principal = self.principal()
        if request.collection_id not in (None, principal.collection_id):
            raise PermissionError("retrieval access denied")
        if principal.document_ids is not None:
            allowed = set(principal.document_ids)
            if request.filters and not set(request.filters.document_ids) <= allowed:
                raise PermissionError("retrieval access denied")
            request = request.model_copy(
                update={
                    "filters": request.filters
                    or RetrievalFilters(document_ids=principal.document_ids)
                }
            )
        with self.lock:
            return self.engine.retrieve(request)

    def fetch_context(self, request: FetchContextRequest) -> RetrievalResponse:
        principal = self.principal()
        if request.collection_id != principal.collection_id:
            raise PermissionError("retrieval access denied")
        with self.lock:
            if principal.document_ids is not None:
                with self.engine.sqlite._connect() as connection:
                    row = connection.execute(
                        "SELECT document_id FROM chunks WHERE chunk_id=?", (request.chunk_id,)
                    ).fetchone()
                if row is None or row[0] not in principal.document_ids:
                    raise PermissionError("retrieval access denied")
            return self.engine.fetch_context(request)

    def list_collections(self) -> list[CollectionDescription]:
        principal = self.principal()
        with self.lock:
            description = self.engine.list_collections()[0]
            if principal.document_ids is not None:
                with self.engine.sqlite._connect() as connection:
                    count = connection.execute(
                        "SELECT count(*) FROM chunks WHERE document_id IN ("
                        + ",".join("?" for _ in principal.document_ids)
                        + ")",
                        principal.document_ids,
                    ).fetchone()[0]
                description = description.model_copy(
                    update={"document_count": len(principal.document_ids), "chunk_count": count}
                )
            return [description]
