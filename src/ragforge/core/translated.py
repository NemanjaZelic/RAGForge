"""Bounded original-plus-source-language retrieval; translation is caller supplied.

The translated query is a query, never source evidence or trusted instructions.
No language model, network client or question/answer table is embedded here.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ragforge.core.contracts import RetrievalResponse, RetrieveRequest
from ragforge.core.dense import reciprocal_rank_fusion
from ragforge.core.planning import maximum_branch_rank
from ragforge.core.planning_v2 import referenced_documents
from ragforge.core.planning_v3 import question_facets

if TYPE_CHECKING:
    from ragforge.core.engine import BundleEngine


# Explicit technical subjects can be inherited only from the first clause, and
# only when a later clause does not name a distinct technical subject itself.
_TECHNICAL = re.compile(
    r"(?<!\w)(?:[A-Za-z]\w*_\w+|[A-Za-z]\w*\d\w*|"
    r"[A-Z][a-z]+[A-Z]\w*|[A-Za-z][\w-]*\.(?:md|txt|html|pdf|mk))(?!\w)"
)


def scoped_facets(query: str) -> list[str]:
    facets = question_facets(query)
    if not facets:
        return []
    subjects = list(dict.fromkeys(_TECHNICAL.findall(facets[0])))
    if not subjects or len(subjects) > 3 or sum(map(len, subjects)) > 96:
        return facets
    result: list[str] = []
    for facet in facets:
        named = set(_TECHNICAL.findall(facet))
        missing = [name for name in subjects if name not in named]
        if named - set(subjects) or not missing:
            result.append(facet)
        else:
            result.append(" ".join(missing) + ": " + facet)
    return result


def translated_response(engine: BundleEngine, request: RetrieveRequest) -> RetrievalResponse:
    """At most 400 reranker pairs across both queries, references and facets.

    Original query receives 80 candidates; the source-language query receives
    120. Remaining pairs cover up to four explicit references and up to three
    translated question facets. Source-language branches define the main order;
    original-query fallback has rank weight 0.85. None are confidence values.
    """
    translation = request.query_translation
    if translation is None:
        raise ValueError("source-language planning requires query_translation")
    allowed = request.filters.document_ids if request.filters else None
    pairs = 0
    owners: dict[str, str] = {}

    def score(query: str, ranks: list[tuple[str, float]]) -> list[tuple[str, float]]:
        nonlocal pairs
        pairs += len(ranks)
        if pairs > 400:
            raise ValueError("translated query plan exceeds aggregate reranker budget")
        ordered, documents = engine._score_candidates(ranks, request, query)
        owners.update(documents)
        return ordered

    def candidates(query: str, limit: int) -> list[tuple[str, float]]:
        local = request.model_copy(update={"query": query, "query_translation": None})
        lexical = engine.sqlite.rank_bm25(local, 100)
        hint = engine._ranking_query(query, allowed)
        if hint != query:
            aliases = engine.sqlite.rank_bm25(local.model_copy(update={"query": hint}), 100)
            lexical = reciprocal_rank_fusion(lexical, aliases, 100)
        dense = engine._rank_dense(local, 100)
        return reciprocal_rank_fusion(lexical, dense, limit)

    original = score(request.query, candidates(request.query, 80))
    translated = score(translation, candidates(translation, 120))
    branches = [translated]
    from ragforge.core.contracts import RetrievalFilters

    inventory = [(d.document_id, d.source_path) for d in engine.collection.documents]
    for document in referenced_documents(request.query, inventory, allowed):
        scoped = request.model_copy(
            update={
                "query": translation,
                "query_translation": None,
                "filters": RetrievalFilters(document_ids=[document]),
            }
        )
        branches.append(score(translation, engine.sqlite.rank_bm25(scoped, 8)))
    facets = scoped_facets(translation)
    if facets:
        limit = min(64, (400 - pairs) // len(facets))
        for facet in facets:
            branches.append(score(facet, candidates(facet, limit)))
    main = dict(maximum_branch_rank(branches))
    for rank, (chunk, _) in enumerate(original, 1):
        main[chunk] = max(main.get(chunk, 0.0), 0.85 / (60 + rank))
    ranks = sorted(main.items(), key=lambda pair: (-pair[1], pair[0]))
    return engine._selected_response(ranks, owners, request, "hybrid")
