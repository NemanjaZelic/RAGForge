"""Embedded exact cosine index. NumPy is imported only for dense work."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ragforge.core.embedding import ONNXEmbedder
from ragforge.core.limits import MAX_DENSE_ROWS
from ragforge.core.sqlite import SQLiteEngine

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

BACKEND = "numpy-exact-cosine"
BACKEND_VERSION = "1"
CANDIDATES = 50
RRF_K = 60


def write_dense(
    database: Path,
    destination: Path,
    embedder: ONNXEmbedder,
    *,
    row_order: Literal["chunk_id", "rowid"] = "chunk_id",
    checkpoint: Path | None = None,
    identity: str = "",
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> int:
    import numpy as np

    engine = SQLiteEngine(database)
    with engine._connect() as connection:
        count = int(connection.execute("SELECT count(*) FROM chunks").fetchone()[0])
        if not 1 <= count <= MAX_DENSE_ROWS:
            raise ValueError("dense index row count exceeds supported capacity")
        from ragforge.jobs.build import atomic_json

        start = 0
        expected = {
            "identity": identity,
            "count": count,
            "dimensions": embedder.spec.dimensions,
            "row_order": row_order,
            "embedding_pipeline": "length-buckets-512-batch32-v2",
        }
        if checkpoint is not None and checkpoint.exists():
            if checkpoint.stat().st_size > 4096:
                raise ValueError("oversized dense checkpoint")
            state = json.loads(checkpoint.read_text(encoding="utf-8"))
            if any(state.get(key) != value for key, value in expected.items()):
                raise ValueError("dense checkpoint identity/shape mismatch")
            start = state["next_row"]
            if type(start) is not int or not 0 <= start <= count:
                raise ValueError("invalid dense checkpoint row")
        matrix = np.lib.format.open_memmap(
            destination,
            mode="r+" if destination.exists() and checkpoint is not None else "w+",
            dtype="<f4",
            shape=(count, embedder.spec.dimensions),
        )
        if matrix.dtype != np.dtype("<f4") or matrix.shape != (count, embedder.spec.dimensions):
            raise ValueError("resumed dense matrix shape/dtype mismatch")
        try:
            for offset in range(0, start, 4096):
                block = matrix[offset : min(offset + 4096, start)]
                if not np.isfinite(block).all() or not np.allclose(
                    np.linalg.norm(block, axis=1), 1, atol=0.001
                ):
                    raise ValueError("committed dense prefix is corrupt")
            cursor = connection.execute(
                "SELECT text FROM chunks ORDER BY " + row_order + " LIMIT -1 OFFSET ?", (start,)
            )
            committed = start
            while rows := cursor.fetchmany(512):
                texts = [str(row["text"]) for row in rows]
                lengths = embedder.token_lengths(texts)
                order = sorted(range(len(rows)), key=lambda index: lengths[index])
                for begin in range(0, len(order), 32):
                    positions = order[begin : begin + 32]
                    vectors = embedder.encode([texts[index] for index in positions])
                    matrix[start + np.asarray(positions)] = vectors
                start += len(rows)
                if start - committed >= 4096 or start == count:
                    matrix.flush()
                    with destination.open("r+b") as data:
                        os.fsync(data.fileno())
                    if checkpoint is not None:
                        atomic_json(checkpoint, {**expected, "next_row": start})
                    committed = start
                    if progress:
                        progress(
                            {"phase": "dense", "completed_chunks": start, "total_chunks": count}
                        )
            matrix.flush()
        finally:
            del matrix
    return count


class DenseStore:
    def __init__(self, path: Path, database: SQLiteEngine, dimensions: int) -> None:
        import numpy as np

        self.database = database
        with database._connect() as connection:
            self.count = int(connection.execute("SELECT count(*) FROM chunks").fetchone()[0])
        matrix = np.load(path, mmap_mode="r", allow_pickle=False, max_header_size=4096)
        if matrix.dtype != np.dtype("<f4") or matrix.shape != (self.count, dimensions):
            raise ValueError("dense shape/dtype does not match SQLite/model")
        if not 1 <= self.count <= MAX_DENSE_ROWS:
            raise ValueError("dense row count is outside supported bounds")
        self.block_rows = min(4096, max(1, (16 * 1024**2) // (dimensions * 4)))
        for start in range(0, self.count, self.block_rows):
            block = matrix[start : start + self.block_rows]
            if not np.isfinite(block).all() or not np.allclose(
                np.linalg.norm(block, axis=1), 1, atol=0.001
            ):
                raise ValueError("dense vectors must be finite and unit normalized")
        self.matrix: NDArray[np.float32] = matrix

    def rank(
        self, vector: NDArray[np.float32], limit: int, document_ids: list[str] | None = None
    ) -> list[tuple[str, float]]:
        import numpy as np

        allowed = set(document_ids) if document_ids is not None else None
        best: list[tuple[str, float]] = []
        with self.database._connect() as connection:
            cursor = connection.execute("SELECT chunk_id,document_id FROM chunks ORDER BY chunk_id")
            for start in range(0, self.count, self.block_rows):
                rows = cursor.fetchmany(self.block_rows)
                stop = start + len(rows)
                scores = self.matrix[start:stop] @ vector
                if not np.isfinite(scores).all():
                    raise ValueError("nonfinite dense similarity")
                candidates = [
                    (str(row["chunk_id"]), float(scores[index]))
                    for index, row in enumerate(rows)
                    if allowed is None or row["document_id"] in allowed
                ]
                candidates.sort(key=lambda item: (-item[1], item[0]))
                best = sorted(best + candidates[:limit], key=lambda item: (-item[1], item[0]))[
                    :limit
                ]
        return best


def reciprocal_rank_fusion(
    lexical: list[tuple[str, float]], semantic: list[tuple[str, float]], limit: int
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for branch in (lexical, semantic):
        for rank, (chunk_id, _) in enumerate(branch, 1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]
