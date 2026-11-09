"""Optional bounded-memory ANN shards in one verifiable, memory-mapped container."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import mmap
import os
import struct
from bisect import bisect_left
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import Field

from ragforge.core.limits import MAX_DENSE_ROWS
from ragforge.core.sqlite import SQLiteEngine
from ragforge.jobs.build import atomic_json
from ragforge.types import ContractModel, Sha256

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

BACKEND = "usearch-sharded-cosine"
BACKEND_VERSION = "1"
LIBRARY_VERSION: Literal["2.26.6"] = "2.26.6"
MAGIC = b"RFGANN1\n"
HEADER_BYTES = 65536
SHARD_ROWS = 25000


def index_type() -> Any:
    try:
        from usearch.index import Index
    except ImportError as error:
        raise ValueError("ANN search/build requires ragforge[scale]") from error
    if importlib.metadata.version("usearch") != LIBRARY_VERSION:
        raise ValueError("ANN runtime library version is unsupported")
    return Index


class Shard(ContractModel):
    first_row: Annotated[int, Field(ge=1)]
    rows: Annotated[int, Field(ge=1, le=25000)]
    offset: Annotated[int, Field(ge=HEADER_BYTES)]
    size_bytes: Annotated[int, Field(ge=1)]
    sha256: Sha256


class AnnHeader(ContractModel):
    format_version: Literal["1"] = "1"
    library_version: Literal["2.26.6"] = LIBRARY_VERSION
    dimensions: Annotated[int, Field(ge=1, le=65536)]
    rows: Annotated[int, Field(ge=1, le=MAX_DENSE_ROWS)]
    dtype: Literal["f16"] = "f16"
    metric: Literal["cosine"] = "cosine"
    shards: Annotated[list[Shard], Field(min_length=1, max_length=512)]


def read_header(path: Path, *, rows: int, dimensions: int) -> AnnHeader:
    """Pure Python verification keeps BM25 independent of NumPy/USearch imports."""
    with path.open("rb") as stream:
        if stream.read(8) != MAGIC:
            raise ValueError("unsupported ANN container signature")
        size = stream.read(4)
        if len(size) != 4:
            raise ValueError("truncated ANN header")
        length = struct.unpack("<I", size)[0]
        if not 1 <= length <= HEADER_BYTES - 12:
            raise ValueError("invalid ANN header length")
        header = AnnHeader.model_validate_json(stream.read(length))
    if (header.rows, header.dimensions) != (rows, dimensions):
        raise ValueError("ANN header does not match SQLite/model")
    expected_row, expected_offset = 1, HEADER_BYTES
    for shard in header.shards:
        if shard.first_row != expected_row or shard.offset != expected_offset:
            raise ValueError("ANN shards are not a contiguous row/byte inventory")
        expected_row += shard.rows
        expected_offset += shard.size_bytes
    if expected_row != rows + 1 or expected_offset != path.stat().st_size:
        raise ValueError("ANN row count or container size mismatch")
    return header


def write_ann(
    database: Path,
    vectors_path: Path,
    destination: Path,
    dimensions: int,
    *,
    checkpoint: Path | None = None,
    identity: str = "",
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    import numpy as np

    Index = index_type()

    with SQLiteEngine(database)._connect() as connection:
        count, first, last = connection.execute(
            "SELECT count(*),min(rowid),max(rowid) FROM chunks"
        ).fetchone()
    if first != 1 or last != count or not 1 <= count <= MAX_DENSE_ROWS:
        raise ValueError("ANN requires contiguous SQLite row IDs within capacity")
    vectors = np.load(vectors_path, mmap_mode="r", allow_pickle=False, max_header_size=4096)
    if vectors.dtype != np.dtype("<f4") or vectors.shape != (count, dimensions):
        raise ValueError("ANN source vector shape/dtype mismatch")
    shards: list[Shard] = []
    offset, start = HEADER_BYTES, 0
    if checkpoint is not None and checkpoint.exists():
        if checkpoint.stat().st_size > HEADER_BYTES:
            raise ValueError("oversized ANN checkpoint")
        state = json.loads(checkpoint.read_text(encoding="utf-8"))
        if (
            state.get("identity") != identity
            or state.get("rows") != count
            or state.get("dimensions") != dimensions
        ):
            raise ValueError("ANN checkpoint identity/shape mismatch")
        shards = [Shard.model_validate(row) for row in state["shards"]]
        with destination.open("rb") as previous:
            for shard in shards:
                if shard.first_row != start + 1 or shard.offset != offset:
                    raise ValueError("invalid ANN checkpoint shard sequence")
                previous.seek(offset)
                if hashlib.sha256(previous.read(shard.size_bytes)).hexdigest() != shard.sha256:
                    raise ValueError("committed ANN shard checksum mismatch")
                start += shard.rows
                offset += shard.size_bytes
    with destination.open("r+b" if destination.exists() and checkpoint else "w+b") as stream:
        stream.truncate(offset)  # Discard only the uncommitted suffix of this owned build file.
        stream.seek(offset)
        for begin in range(start, count, SHARD_ROWS):
            stop = min(begin + SHARD_ROWS, count)
            block = np.asarray(vectors[begin:stop], dtype=np.float32)
            if not np.isfinite(block).all():
                raise ValueError("nonfinite ANN input vectors")
            index = Index(
                ndim=dimensions,
                metric="cos",
                dtype="f16",
                connectivity=16,
                expansion_add=128,
                expansion_search=64,
            )
            index.add(np.arange(begin + 1, stop + 1, dtype=np.uint64), block, threads=1)
            payload = index.save()
            if not isinstance(payload, (bytes, bytearray)):
                raise ValueError("ANN serialization did not return bytes")
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            shards.append(
                Shard(
                    first_row=begin + 1,
                    rows=stop - begin,
                    offset=offset,
                    size_bytes=len(payload),
                    sha256=hashlib.sha256(payload).hexdigest(),
                )
            )
            offset += len(payload)
            if checkpoint is not None:
                atomic_json(
                    checkpoint,
                    {
                        "identity": identity,
                        "rows": count,
                        "dimensions": dimensions,
                        "shards": [s.model_dump() for s in shards],
                    },
                )
            if progress:
                progress({"phase": "ann", "completed_chunks": stop, "total_chunks": count})
        header = AnnHeader(dimensions=dimensions, rows=count, shards=shards)
        encoded = header.model_dump_json().encode()
        if len(encoded) > HEADER_BYTES - 12:
            raise ValueError("ANN container header capacity exceeded")
        stream.seek(0)
        stream.write(MAGIC + struct.pack("<I", len(encoded)) + encoded)
        stream.write(b"\0" * (HEADER_BYTES - 12 - len(encoded)))
        stream.flush()
        os.fsync(stream.fileno())
    del vectors
    read_header(destination, rows=count, dimensions=dimensions)


class AnnStore:
    """Approximate global search; exact float16-vector scoring within document filters."""

    def __init__(
        self, path: Path, database: SQLiteEngine, dimensions: int, *, workers: int = 1
    ) -> None:
        if type(workers) is not int or not 1 <= workers <= 32:
            raise ValueError("ANN workers must be between 1 and 32")
        self.workers = min(workers, 8)
        Index = index_type()

        self.database = database
        with database._connect() as connection:
            count, first, last = connection.execute(
                "SELECT count(*),min(rowid),max(rowid) FROM chunks"
            ).fetchone()
        if first != 1 or last != count:
            raise ValueError("ANN SQLite row IDs are not contiguous")
        self.header = read_header(path, rows=count, dimensions=dimensions)
        self.file = path.open("rb")
        self.mapping = mmap.mmap(self.file.fileno(), 0, access=mmap.ACCESS_READ)
        self.buffers: list[memoryview] = []
        self.indexes: list[Any] = []
        self.ends: list[int] = []
        for shard in self.header.shards:
            buffer = memoryview(self.mapping)[shard.offset : shard.offset + shard.size_bytes]
            if hashlib.sha256(buffer).hexdigest() != shard.sha256:
                raise ValueError("ANN shard checksum mismatch")
            index = Index.restore(buffer, view=True, expansion_search=64)
            if index is None or len(index) != shard.rows or index.ndim != dimensions:
                raise ValueError("ANN graph metadata mismatch")
            self.buffers.append(buffer)
            self.indexes.append(index)
            self.ends.append(shard.first_row + shard.rows - 1)

    def _candidate_scores(
        self, shard_index: int, keys: list[int], vector: NDArray[np.float32]
    ) -> list[tuple[int, float]]:
        import numpy as np

        if not keys:
            return []
        if len(set(keys)) != len(keys) or any(
            not self.header.shards[shard_index].first_row <= key <= self.ends[shard_index]
            for key in keys
        ):
            raise ValueError("ANN graph returned duplicate or out-of-shard keys")
        stored = self.indexes[shard_index].get(np.asarray(keys, dtype=np.uint64), dtype="f32")
        if stored is None or any(row is None for row in stored):
            raise ValueError("ANN candidate vector is missing")
        values = np.asarray(stored, dtype=np.float32)
        norms = np.linalg.norm(values, axis=1)
        if not np.isfinite(values).all() or not (norms > 0).all():
            raise ValueError("invalid ANN candidate vectors")
        # Preserve each original shard's matrix shape and floating-point operation.
        scores = (values @ vector) / norms
        return [(key, float(scores[i])) for i, key in enumerate(keys)]

    def rank(
        self,
        vector: NDArray[np.float32],
        limit: int,
        document_ids: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        import numpy as np

        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("ANN candidate limit must be between 1 and 200")
        if vector.shape != (self.header.dimensions,) or not np.isfinite(vector).all():
            raise ValueError("invalid ANN query vector")
        best: list[tuple[str, float]] = []
        with self.database._connect() as connection:

            def resolve(candidates: list[tuple[int, float]]) -> None:
                nonlocal best
                if not candidates:
                    return
                keys = [key for key, _ in candidates]
                rows = connection.execute(
                    "SELECT rowid,chunk_id FROM chunks WHERE rowid IN ("
                    + ",".join("?" for _ in keys)
                    + ")",
                    keys,
                ).fetchall()
                mapping = {int(row["rowid"]): str(row["chunk_id"]) for row in rows}
                if len(mapping) != len(keys):
                    raise ValueError("ANN key does not map to a unique SQLite chunk")
                selected = [(mapping[key], score) for key, score in candidates]
                best = sorted(best + selected, key=lambda item: (-item[1], item[0]))[:limit]

            if document_ids is None:

                def search(shard: int) -> list[tuple[int, float]]:
                    graph = self.indexes[shard]
                    matches = graph.search(vector, count=min(limit, len(graph)), threads=1)
                    return self._candidate_scores(shard, [int(key) for key in matches.keys], vector)

                # Every shard still performs the original search and exact scoring.
                # Only SQL identity reads for strictly losing scores are eliminated.
                # The constructor verifies contiguous row IDs, and shard key ranges
                # are validated above, so losing keys cannot conceal missing rows.
                candidates = []
                if self.workers == 1 or len(self.indexes) <= 1:
                    for shard in range(len(self.indexes)):
                        candidates.extend(search(shard))
                else:
                    pool = ThreadPoolExecutor(max_workers=self.workers)
                    try:
                        for batch in pool.map(search, range(len(self.indexes))):
                            candidates.extend(batch)
                    finally:
                        pool.shutdown(wait=True, cancel_futures=True)
                if candidates:
                    cutoff = sorted((score for _, score in candidates), reverse=True)[
                        min(limit, len(candidates)) - 1
                    ]
                    # All boundary ties must survive until chunk-ID tie breaking.
                    candidates = [item for item in candidates if item[1] >= cutoff]
                    for start in range(0, len(candidates), 512):
                        resolve(candidates[start : start + 512])
            else:
                # Grants filter SQL before reading vectors; broad/narrow filters
                # retain the original exhaustive stored-vector scoring semantics.
                cursor = connection.execute(
                    "SELECT rowid FROM chunks WHERE document_id IN ("
                    + ",".join("?" for _ in document_ids)
                    + ") ORDER BY rowid",
                    document_ids,
                )
                while rows := cursor.fetchmany(512):
                    groups: dict[int, list[int]] = {}
                    for row in rows:
                        key = int(row["rowid"])
                        groups.setdefault(bisect_left(self.ends, key), []).append(key)
                    for shard, keys in groups.items():
                        resolve(self._candidate_scores(shard, keys, vector))
        return best
