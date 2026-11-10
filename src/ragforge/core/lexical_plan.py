"""Request-local prefetch of independent, unchanged lexical searches."""

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from ragforge.core.contracts import RetrieveRequest

Ranks = list[tuple[str, float]]
Ranker = Callable[[RetrieveRequest, int], Ranks]


@contextmanager
def prefetch_lexical(
    rank: Ranker, requests: list[tuple[RetrieveRequest, int]], *, workers: int
) -> Iterator[Ranker]:
    # No persistent query cache. A larger limit includes the exact deterministic
    # prefix of a smaller one for the same query, scope and filters.
    plans: dict[str, tuple[RetrieveRequest, int]] = {}
    for request, limit in requests:
        key = request.model_dump_json()
        if key not in plans or plans[key][1] < limit:
            plans[key] = (request, limit)
    ordered = list(plans.items())

    def search(item: tuple[str, tuple[RetrieveRequest, int]]) -> tuple[str, Ranks]:
        key, (request, limit) = item
        return key, rank(request, limit)

    with ThreadPoolExecutor(max_workers=max(1, min(4, workers))) as pool:
        results = {key: pool.submit(search, item) for item in ordered for key in [item[0]]}

        def prepared(request: RetrieveRequest, limit: int) -> Ranks:
            key = request.model_dump_json()
            if key not in plans or limit > plans[key][1]:
                raise ValueError("lexical request outside its prepared plan")
            return results[key].result()[1][:limit]

        try:
            yield prepared
        finally:
            for future in results.values():
                future.cancel()
