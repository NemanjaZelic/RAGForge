"""Global ANN cutoff must preserve ties, every shard and source grants."""

import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from ragforge.core.ann import AnnStore
from ragforge.core.chunk import ChunkConfig
from ragforge.core.parse import load_document
from ragforge.core.scan import scan_corpus
from ragforge.core.sqlite import SQLiteEngine, create_index


@pytest.fixture
def ranked_index(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    for name in ["first", "second"]:
        (source / f"{name}.txt").write_text(
            "\n\n".join(f"Protocol item {i:04d} requires a transaction token." for i in range(350))
        )
    docs = [load_document(source, "docs", r) for r in scan_corpus(source, "docs").documents]
    path = tmp_path / "index.sqlite"
    create_index(path, "docs", "Docs", docs, ChunkConfig(chunk_size_chars=64, overlap_chars=0))
    index = SQLiteEngine(path)
    with index._connect() as db:
        rows = db.execute("SELECT rowid,chunk_id,document_id FROM chunks ORDER BY rowid").fetchall()
    assert len(rows) > 512
    return index, rows


def store_for(index, rows, *, all_ties, workers=4, allowed=None):
    keys = [r["rowid"] for r in rows]
    parts = [keys[i : i + 200] for i in range(0, len(keys), 200)]
    barrier = threading.Barrier(min(workers, len(parts)), timeout=10)
    seen = {"shards": set(), "vectors": set()}
    lock = threading.Lock()

    class Graph:
        def __init__(self, number, keys):
            self.number, self.keys = number, keys

        def __len__(self):
            return len(self.keys)

        def search(self, vector, count, threads):
            assert count == min(200, len(self.keys)) and threads == 1
            with lock:
                seen["shards"].add(self.number)
            if workers > 1 and self.number < barrier.parties:
                barrier.wait()
            return SimpleNamespace(keys=self.keys[:count])

        def get(self, ids, dtype):
            values = [int(i) for i in ids]
            assert set(values) <= set(self.keys)
            if allowed is not None:
                assert set(values) <= allowed  # A forbidden vector must never be read.
            with lock:
                seen["vectors"].update(values)
            vector = [1.0, 0.0] if all_ties or self.number == 0 else [0.0, 1.0]
            return np.tile(np.asarray(vector, dtype=np.float32), (len(values), 1))

    store = object.__new__(AnnStore)
    store.database, store.workers = index, workers
    store.indexes = [Graph(i, keys) for i, keys in enumerate(parts)]
    store.ends = [keys[-1] for keys in parts]
    store.header = SimpleNamespace(
        dimensions=2, shards=[SimpleNamespace(first_row=keys[0]) for keys in parts]
    )
    return store, seen


def test_global_boundary_ties_survive_beyond_one_sql_batch(ranked_index):
    index, rows = ranked_index
    store, seen = store_for(index, rows, all_ties=True)
    actual = store.rank(np.asarray([1, 0], dtype=np.float32), 200)
    assert actual == sorted((r["chunk_id"], 1.0) for r in rows)[:200]
    assert seen["shards"] == set(range(len(store.indexes)))
    assert seen["vectors"] == {r["rowid"] for r in rows}


def test_strict_losers_do_not_change_global_top_k(ranked_index):
    index, rows = ranked_index
    store, seen = store_for(index, rows, all_ties=False)
    actual = store.rank(np.asarray([1, 0], dtype=np.float32), 200)
    assert actual == sorted((r["chunk_id"], 1.0) for r in rows[:200])
    assert len(seen["shards"]) == len(store.indexes)  # Search recall was not reduced.


def test_filtered_scoring_reads_only_authorized_vectors(ranked_index):
    index, rows = ranked_index
    document = rows[-1]["document_id"]
    allowed = {r["rowid"] for r in rows if r["document_id"] == document}
    store, seen = store_for(index, rows, all_ties=True, allowed=allowed)
    actual = store.rank(np.asarray([1, 0], dtype=np.float32), 200, [document])
    assert actual == sorted((r["chunk_id"], 1.0) for r in rows if r["rowid"] in allowed)[:200]
    assert not seen["shards"]  # Filtered mode keeps exhaustive scoring, not graph search.
    assert seen["vectors"] == allowed


@pytest.mark.parametrize("limit", [0, 201, True])
def test_unbounded_or_invalid_ann_limit_is_rejected(ranked_index, limit):
    store, _ = store_for(*ranked_index, all_ties=True)
    with pytest.raises(ValueError, match="limit"):
        store.rank(np.asarray([1, 0], dtype=np.float32), limit)
