"""Shared bounded source reads for discovery and parsing."""

import hashlib
import os
import stat
from pathlib import Path


class SourceError(ValueError):
    """Unsafe, unreadable, changed or oversized source."""


def is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def stamp(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns


def checked_stat(path: Path, root: Path) -> os.stat_result:
    info = path.lstat()
    if is_link(info):
        raise SourceError("symlinks and reparse points are forbidden")
    if not path.resolve(strict=True).is_relative_to(root):
        raise SourceError("source escapes corpus root")
    return info


def read_file(
    path: Path, root: Path, max_file_bytes: int, remaining: int, *, capture: bool = False
) -> tuple[str, int, bytes]:
    before = checked_stat(path, root)
    if not stat.S_ISREG(before.st_mode):
        raise SourceError("source must be a regular file")
    if before.st_size > max_file_bytes:
        raise SourceError("max_file_bytes exceeded")
    if before.st_size > remaining:
        raise SourceError("max_total_bytes exceeded")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    blocks = []
    with os.fdopen(os.open(path, flags), "rb") as stream:
        if stamp(os.fstat(stream.fileno())) != stamp(before):
            raise SourceError("source changed while opening")
        digest, size = hashlib.sha256(), 0
        while block := stream.read(64 * 1024):
            size += len(block)
            if size > max_file_bytes or size > remaining:
                raise SourceError("source grew beyond scan byte limits")
            digest.update(block)
            if capture:
                blocks.append(block)
        after = os.fstat(stream.fileno())
    if size != before.st_size or stamp(before) != stamp(after):
        raise SourceError("source changed while hashing")
    if stamp(checked_stat(path, root)) != stamp(after):
        raise SourceError("source replaced while hashing")
    return digest.hexdigest(), size, b"".join(blocks)
