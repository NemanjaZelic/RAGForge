"""Independent SQL searches retain exact rankings and request scope."""

from threading import Barrier, Lock

import pytest

from ragforge.core.contracts import RetrievalFilters, RetrieveRequest
from ragforge.core.lexical_plan import prefetch_lexical


def test_independent_searches_overlap_and_keep_exact_prefixes_and_scope():
    gate = Barrier(2, timeout=5)
    calls = []
    lock = Lock()
    first = RetrieveRequest(
        query="literal ALPHA", filters=RetrievalFilters(document_ids=["a" * 64])
    )
    other = first.model_copy(update={"filters": RetrievalFilters(document_ids=["b" * 64])})

    def rank(request, limit):
        with lock:
            calls.append((request, limit))
        gate.wait()
        return [(f"{i:064x}", float(100 - i)) for i in range(limit)]

    with prefetch_lexical(rank, [(first, 32), (other, 8), (first, 100)], workers=2) as prepared:
        assert prepared(first, 32) == [(f"{i:064x}", float(100 - i)) for i in range(32)]
        assert prepared(other, 8) == [(f"{i:064x}", float(100 - i)) for i in range(8)]
        assert len(calls) == 2
        prepared(first, 32).clear()
        assert len(prepared(first, 32)) == 32
        with pytest.raises(ValueError, match="outside"):
            prepared(first.model_copy(update={"query": "unplanned"}), 5)
        with pytest.raises(ValueError, match="outside"):
            prepared(first, 101)
