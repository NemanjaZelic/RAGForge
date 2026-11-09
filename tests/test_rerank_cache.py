"""A quantized score cache keys the complete tensor batch, never a single passage."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from ragforge.core.rerank import ONNXReranker


class Recording:
    def __init__(self, session):
        self.session = session
        self.calls = 0
        self.lock = threading.Lock()

    def run(self, outputs, values):
        with self.lock:
            self.calls += 1
        time.sleep(0.01)
        return self.session.run(outputs, values)


def test_identical_inflight_batches_share_one_inference(tiny_reranker):
    model = ONNXReranker(tiny_reranker, threads=4, workers=4, cache_batches=4)
    model.spec = model.spec.model_copy(update={"batch_size": 2})
    recording = Recording(model.session)
    model.session = recording
    passages = ["transaction token"] * 16
    expected = ONNXReranker(tiny_reranker, threads=1, cache_batches=0).score("rollback", passages)
    assert model.score("rollback", passages) == expected
    assert recording.calls == 1
    assert model.cache_info() == {"capacity": 4, "entries": 1, "hits": 7, "misses": 1}
    assert model.score("rollback", passages) == expected
    assert recording.calls == 1
    assert not model._inflight


def test_complete_batch_identity_masks_shapes_and_query_are_part_of_key(tiny_reranker):
    model = ONNXReranker(tiny_reranker, threads=1, cache_batches=8)
    model.spec = model.spec.model_copy(update={"batch_size": 2})

    class BatchDependent:
        calls = 0

        def run(self, outputs, values):
            self.calls += 1
            ids = values["input_ids"].sum(axis=1).astype(np.float32)
            masks = values["attention_mask"].sum(axis=1)
            return [(ids + ids.sum() + masks).astype(np.float32)[:, None]]

    session = BatchDependent()
    model.session = session
    first = model.score("token", ["transaction", "token"])
    changed = model.score("token", ["transaction", "token " * 12])
    assert first[0] != changed[0]  # The same passage can score differently beside another one.
    assert session.calls == 2
    model.score("rollback", ["transaction", "token"])
    assert session.calls == 3
    values = {
        "input_ids": np.asarray([[1, 2], [3, 4]], dtype=np.int64),
        "attention_mask": np.ones((2, 2), dtype=np.int64),
    }
    original = model._infer_batch(values)
    changed_mask = model._infer_batch(
        {**values, "attention_mask": np.zeros((2, 2), dtype=np.int64)}
    )
    assert original != changed_mask
    reshaped = model._infer_batch({name: value.reshape(1, 4) for name, value in values.items()})
    assert len(reshaped) == 1 and len(original) == 2
    assert session.calls == 6


def test_cache_is_bounded_lru_and_never_stores_source_text(tiny_reranker):
    model = ONNXReranker(tiny_reranker, threads=1, cache_batches=2)
    for query in ["token", "rollback", "token", "transaction", "rollback"]:
        model.score(query, ["transaction token"])
    info = model.cache_info()
    assert info["entries"] == 2 and info["hits"] == 1 and info["misses"] == 4
    assert all(isinstance(key, bytes) and len(key) == 32 for key in model._batch_cache)
    assert all(
        isinstance(value, tuple) and all(isinstance(v, float) for v in value)
        for value in model._batch_cache.values()
    )


def test_failed_inference_is_not_cached_and_replacing_session_invalidates_results(tiny_reranker):
    model = ONNXReranker(tiny_reranker, threads=1, cache_batches=4)
    actual = model.session
    expected = model.score("rollback", ["transaction token"])

    class Once:
        calls = 0

        def run(self, outputs, values):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary inference failure")
            return [np.full((len(values["input_ids"]), 1), 99.25, dtype=np.float32)]

    changed = Once()
    model.session = changed
    with pytest.raises(RuntimeError, match="temporary"):
        model.score("rollback", ["transaction token"])
    assert not model._batch_cache and not model._inflight
    assert model.tokenizer.truncation is None
    assert model.score("rollback", ["transaction token"]) == [99.25]
    assert changed.calls == 2
    model.session = actual
    assert model.score("rollback", ["transaction token"]) == expected
    assert model.cache_info()["misses"] == 4


def test_concurrent_public_calls_do_not_race_tokenizer_state(tiny_reranker):
    reference = ONNXReranker(tiny_reranker, threads=1, cache_batches=0)
    jobs = [
        ("rollback", ["transaction " * 600, "token"]),
        ("token", ["rollback", "transaction token"]),
    ]
    expected = [reference.score(q, p) for q, p in jobs]
    model = ONNXReranker(tiny_reranker, threads=4, cache_batches=8)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(model.score, q, p) for q, p in jobs]
        assert [f.result() for f in futures] == expected
    assert model.tokenizer.truncation is None


@pytest.mark.parametrize("capacity", [-1, 4097, True])
def test_invalid_cache_capacity_is_rejected(tiny_reranker, capacity):
    with pytest.raises(ValueError, match="cache batches"):
        ONNXReranker(tiny_reranker, cache_batches=capacity)
