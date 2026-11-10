"""Portable URL provenance with no network operations."""

from __future__ import annotations

import posixpath
import re
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from pydantic import Field, field_validator, model_validator

from ragforge.core.source import is_link
from ragforge.types import ContractModel, RelativePath, Sha256

if TYPE_CHECKING:
    from ragforge.artifacts.manifest import CollectionManifest


def normalize_url(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 4096
        or any(ord(c) <= 32 or ord(c) == 127 for c in value)
        or "\\" in value
    ):
        raise ValueError("URL must be an HTTP(S) address without whitespace or controls")
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("only absolute HTTP(S) URLs are supported")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL credentials are not supported")
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    if not re.fullmatch(r"[a-z0-9.:-]+", host):
        raise ValueError("invalid URL host")
    port = parsed.port
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("invalid URL port")
    authority = ("[" + host + "]") if ":" in host else host
    if port is not None and port != (443 if parsed.scheme.lower() == "https" else 80):
        authority += ":" + str(port)
    path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = quote(parsed.query, safe="%/:?@!$&'()*+,;=-._~[]")
    return urlunsplit((parsed.scheme.lower(), authority, path, query, ""))


def url_origin(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, "", "", ""))


def decoded_path(url: str) -> str:
    raw = unquote(urlsplit(url).path)
    if "\\" in raw:
        raise ValueError("encoded backslashes are unsupported in document URLs")
    return posixpath.normpath("/" + raw.lstrip("/"))


class WebSource(ContractModel):
    source_path: RelativePath
    url: Annotated[str, Field(max_length=4096)]
    content_sha256: Sha256
    raw_sha256: Sha256
    media_type: Annotated[str, Field(min_length=1, max_length=128)]

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        if normalize_url(value) != value:
            raise ValueError("source URL must be normalized")
        return value


class WebSources(ContractModel):
    format_version: Literal["1"] = "1"
    seed_url: Annotated[str, Field(max_length=4096)]
    fetched_at: Annotated[str, Field(min_length=1, max_length=64)]
    max_pages: Annotated[int, Field(ge=1, le=1000)]
    max_depth: Annotated[int, Field(ge=0, le=10)]
    complete: bool
    issues: Annotated[list[str], Field(max_length=10000)] = []
    sources: Annotated[list[WebSource], Field(min_length=1, max_length=1000)]

    @model_validator(mode="after")
    def unique_sources(self) -> WebSources:
        normalize_url(self.seed_url)
        if len({s.source_path.casefold() for s in self.sources}) != len(self.sources):
            raise ValueError("duplicate web source path")
        if len({s.url for s in self.sources}) != len(self.sources):
            raise ValueError("duplicate final source URL")
        return self


def read_web_sources(path: Path) -> WebSources:
    if is_link(path.lstat()) or path.stat().st_size > 16 * 1024**2:
        raise ValueError("invalid or oversized web source catalogue")
    return WebSources.model_validate_json(path.read_text(encoding="utf-8"))


def verify_web_sources(catalogue: WebSources, collection: CollectionManifest) -> None:
    expected = {d.source_path: d.content_sha256 for d in collection.documents}
    actual = {s.source_path: s.content_sha256 for s in catalogue.sources}
    if actual != expected:
        raise ValueError("web URL provenance does not match the exact document inventory")
