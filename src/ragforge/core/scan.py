"""Deterministic, bounded discovery and hashing. No parsing or document execution."""

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from ragforge.core.identity import document_id
from ragforge.core.source import (
    SourceError,
    read_file,
)
from ragforge.core.source import (
    checked_stat as _checked_stat,
)
from ragforge.core.source import (
    is_link as _is_link,
)
from ragforge.types import ContractModel, Identifier, RelativePath, Sha256

FORMATS = {".md": "markdown", ".txt": "text", ".html": "html", ".htm": "html", ".pdf": "pdf"}
_path_adapter: TypeAdapter[str] = TypeAdapter(RelativePath)
_collection_adapter: TypeAdapter[str] = TypeAdapter(Identifier)


ScanError = SourceError


@dataclass(frozen=True)
class ScanLimits:
    max_file_bytes: int = 32 * 1024 * 1024
    max_total_bytes: int = 512 * 1024 * 1024
    max_entries: int = 100_000

    def __post_init__(self) -> None:
        for value in (self.max_file_bytes, self.max_total_bytes, self.max_entries):
            if type(value) is not int or value < 1:
                raise ValueError("scan limits must be positive integers")


class ScannedDocument(ContractModel):
    document_id: Sha256
    source_path: RelativePath
    content_sha256: Sha256
    size_bytes: Annotated[int, Field(ge=0)]
    format: Literal["markdown", "text", "html", "pdf"]


class ScanReport(ContractModel):
    collection_id: Identifier
    documents: list[ScannedDocument]
    ignored_paths: list[RelativePath]
    total_bytes: Annotated[int, Field(ge=0)]


def _hash_file(path: Path, root: Path, remaining: int, limits: ScanLimits) -> tuple[str, int]:
    digest, size, _ = read_file(path, root, limits.max_file_bytes, remaining)
    return digest, size


def scan_corpus(root: Path, collection_id: str, limits: ScanLimits | None = None) -> ScanReport:
    """Reject links, nonportable paths and all read/limit errors.

    NFC paths are required, never silently rewritten. Source paths preserve case;
    distinct filesystem entries remain distinct documents. Empty documents are inventoried.
    Unsupported
    regular files are reported, not hashed. PDF discovery does not verify text.
    Callers must use a stable corpus; this is not an OS filesystem sandbox or an
    atomic snapshot against concurrent directory mutation by another process.
    """
    limits = limits or ScanLimits()
    collection = _collection_adapter.validate_python(collection_id)
    try:
        if _is_link(root.lstat()):
            raise ScanError("corpus root must not be a link or reparse point")
        root = root.resolve(strict=True)
        if not root.is_dir():
            raise ScanError("corpus root must be a directory")
        pending = [root]
        seen: set[str] = set()
        sources: list[tuple[str, Path]] = []
        ignored: list[str] = []
        entries_count = 0
        while pending:
            directory = pending.pop()
            if not stat.S_ISDIR(_checked_stat(directory, root).st_mode):
                raise ScanError("source directory changed")
            with os.scandir(directory) as entries:
                for entry in entries:
                    entries_count += 1
                    if entries_count > limits.max_entries:
                        raise ScanError("max_entries exceeded")
                    path = directory / entry.name
                    relative = path.relative_to(root).as_posix()
                    try:
                        relative = _path_adapter.validate_python(relative)
                    except ValueError as error:
                        raise ScanError(f"nonportable source path: {relative!r}") from error
                    if relative in seen:
                        raise ScanError(f"duplicate source path: {relative!r}")
                    seen.add(relative)
                    info = _checked_stat(path, root)
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(path)
                    elif not stat.S_ISREG(info.st_mode):
                        raise ScanError(f"non-regular source: {relative!r}")
                    elif path.suffix.lower() in FORMATS:
                        sources.append((relative, path))
                    else:
                        ignored.append(relative)
        documents = []
        total = 0
        for relative, path in sorted(sources):
            try:
                digest, size = _hash_file(path, root, limits.max_total_bytes - total, limits)
            except (OSError, ScanError) as error:
                raise ScanError(f"{relative!r}: {error}") from error
            documents.append(
                ScannedDocument.model_validate(
                    {
                        "document_id": document_id(collection, relative),
                        "source_path": relative,
                        "content_sha256": digest,
                        "size_bytes": size,
                        "format": FORMATS[path.suffix.lower()],
                    }
                )
            )
            total += size
        return ScanReport(
            collection_id=collection,
            documents=documents,
            ignored_paths=sorted(ignored),
            total_bytes=total,
        )
    except OSError as error:
        raise ScanError(f"cannot complete corpus scan: {error}") from error
