"""Embedded exact cosine index. NumPy is imported only for dense work."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

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


def write_dense(database: Path, destination: Path, embedder: ONNXEmbedder) -> int:
    import numpy as np

    engine = SQLiteEngine(database)
    with engine._connect() as connection:
        count = int(connection.execute("SELECT count(*) FROM chunks").fetchone()[0])
        if not 1 <= count <= MAX_DENSE_ROWS:
            raise ValueError("dense index row count exceeds supported capacity")
        matrix = np.lib.format.open_memmap(
            destination, mode="w+", dtype="<f4", shape=(count, embedder.spec.dimensions)
        )
        try:
            cursor = connection.execute("SELECT text FROM chunks ORDER BY chunk_id")
            start = 0
            while rows := cursor.fetchmany(32):
                vectors = embedder.encode([row["text"] for row in rows])
                matrix[start : start + len(rows)] = vectors
                start += len(rows)
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
