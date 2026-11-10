"""Bounded lexical question facets; only input query words are reused.

Experimental candidate planning. Facets supplement the original query and do
not assert facts or interpret retrieved document instructions.
"""

from __future__ import annotations

import re
from contextlib import ExitStack
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ragforge.core.contracts import RetrievalResponse, RetrieveRequest
    from ragforge.core.engine import BundleEngine
    from ragforge.core.lexical_plan import Ranker

_MODALS = {
    "MUST",
    "SHOULD",
    "SHALL",
    "REQUIRED",
    "MAY",
    "OPTIONAL",
    "NOT",
    "CAN",
    "WHAT",
    "WHICH",
    "HOW",
}
_START = r"what|which|who|where|when|why|how|must|may|can|could|should|does|do|is|are"


def _names(text: str) -> list[str]:
    return [
        word
        for word in re.findall(r"\b[A-Za-z][A-Za-z0-9/-]*\b", text)
        if word not in _MODALS
        and (sum(c.isupper() for c in word) >= 2 or any(c.isdigit() for c in word))
    ]


def question_facets(query: str) -> list[str]:
    """Return at most three supplemental questions, with bounded fallback.

    Never remove the original query from the retrieval plan. Missing names in a
    coordinated question inherit at most one explicit name from its first part.
    This is a syntactic heuristic, not a language model or answer lookup.
    """
    if len(query) > 2048 or len(query.split()) > 128:
        return []
    text = query.strip().rstrip("?.!")
    parts = re.split(r"\s*,?\s+and\s+(?=(?:" + _START + r")\b)", text, flags=re.I)
    proposed: list[str] = []
    if len(parts) > 1:
        names = _names(parts[0])
        scope = names[:1]
        for part in parts[:3]:
            if (
                not (set(_names(part)) - set(names))
                and scope
                and not set(scope) & set(_names(part))
            ):
                part = scope[0] + ": " + part
            proposed.append(part)
    else:
        comparison = re.fullmatch(
            r"(How\s+(?:does|do|should|can|would)\s+)(.+?)\s+(?:differ\s+from|versus|vs\.?)\s+(.+)",
            text,
            re.I,
        )
        if comparison:
            proposed = [comparison[1] + comparison[2], comparison[1] + comparison[3]]
        else:
            shared = re.fullmatch(
                r"(How\s+(?:do|does|should|can|would)\s+)(.+?)\s+and\s+(.+?)\s+((?:be\s+)?(?:differ|interpret\w*|restrict\w*|address\w*|work\w*|relate\w*|be\s+interpreted)\b.*)",
                text,
                re.I,
            )
            if shared:
                left, right = shared[2], shared[3]
                # A coordinated adjective/name can share the right-hand noun.
                tail = right.split(maxsplit=1)
                if (
                    len(left.split()) <= 2
                    and len(tail) == 2
                    and tail[0].casefold() not in {"a", "an", "the"}
                ):
                    left += " " + tail[1]
                proposed = [shared[1] + left + " " + shared[4], shared[1] + right + " " + shared[4]]
            else:
                between = re.fullmatch(r"(.+?)\s+between\s+(.+?)\s+and\s+(.+)", text, re.I)
                if between:
                    proposed = [between[1] + " " + between[2], between[1] + " " + between[3]]
    result = []
    for part in proposed:
        part = part.strip(" ,;:") + "?"
        if part.casefold().rstrip("?") == text.casefold() or len(part) > 2048:
            continue
        if part not in result:
            result.append(part)
    return result[:3]


def referenced_documents(
    query: str, documents: list[tuple[str, str]], allowed: list[str] | None = None
) -> list[str]:
    """Resolve explicitly written file stems/letter-number IDs, at most four.

    Caller supplies the already verified source inventory. A mention of a
    document is only a supplemental retrieval branch, never authority to bypass
    document grants or to assert that the document contains an answer.
    """
    if len(query) > 2048:
        return []
    identifiers = {
        re.sub(r"[^a-z0-9]", "", m.casefold())
        for m in re.findall(r"\b[A-Za-z]{2,16}[ -]?\d{1,8}\b", query)
    }
    literal = query.casefold()
    result = []
    for document_id, path in documents:
        if allowed is not None and document_id not in allowed:
            continue
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        stem = name.rsplit(".", 1)[0]
        identifier = re.sub(r"[^a-z0-9]", "", stem.casefold())
        exact_name = name.casefold() in literal and re.search(
            r"(?<![\w.-])" + re.escape(name.casefold()) + r"(?![\w-]|\.[\w.-])", literal
        )
        if (identifier in identifiers or exact_name) and document_id not in result:
            result.append(document_id)
        if len(result) == 4:
            break
    return result


def _ordered(values: list[tuple[str, float]]) -> list[tuple[str, float]]:
    return sorted(values, key=lambda pair: (-pair[1], pair[0]))


def maximum_branch_rank(branches: list[list[tuple[str, float]]]) -> list[tuple[str, float]]:
    """Retain strong evidence for any question facet; scores are not confidence."""
    scores: dict[str, float] = {}
    for branch in branches:
        for rank, (key, _) in enumerate(branch, 1):
            scores[key] = max(scores.get(key, 0.0), 1.0 / (60 + rank))
    return _ordered(list(scores.items()))


def planned_response(engine: BundleEngine, request: RetrieveRequest) -> RetrievalResponse:
    with ExitStack() as stack:
        return _planned_response(engine, request, stack)


def _planned_response(
    engine: BundleEngine, request: RetrieveRequest, stack: ExitStack
) -> RetrievalResponse:
    """Versioned bounded recipe, at most 400 total reranker pairs.

    Original BM25/dense candidates and their original-query reranker scores are
    preserved. Verified aliases add candidates only. Every branch receives the
    caller's document scope before search and again before passage inference.
    The shared response builder applies the final character/document limits.
    """
    from ragforge.core.contracts import RetrievalFilters
    from ragforge.core.dense import reciprocal_rank_fusion

    config = engine.manifest.retrieval_configuration
    if config is None or config.query_planning not in {"facets-v1", "facets-v2", "facets-v3"}:
        raise ValueError("query planning requires its configured local reranker")
    make_facets = question_facets
    find_references = referenced_documents
    if config.query_planning == "facets-v2":
        from ragforge.core.planning_v2 import question_facets as make_facets_v2
        from ragforge.core.planning_v2 import referenced_documents as find_references_v2

        make_facets = make_facets_v2
        find_references = find_references_v2
    if config.query_planning == "facets-v3":
        from ragforge.core.planning_v3 import question_facets as make_facets_v3

        make_facets = make_facets_v3
        from ragforge.core.planning_v2 import referenced_documents as find_references_v2

        find_references = find_references_v2
    allowed = request.filters.document_ids if request.filters is not None else None
    hint = engine._ranking_query(request.query, allowed)
    inventory = [(d.document_id, d.source_path) for d in engine.collection.documents]
    references_found = find_references(request.query, inventory, allowed)
    facets = make_facets(request.query)
    lexical: Ranker = engine.sqlite.rank_bm25
    if config.query_language == "en" and engine.threads > 1:
        from ragforge.core.lexical_plan import prefetch_lexical

        lexical_requests = [(request, 100)]
        if hint != request.query:
            lexical_requests.append((request.model_copy(update={"query": hint}), 100))
        for document_id in references_found:
            scoped = request.model_copy(
                update={"filters": RetrievalFilters(document_ids=[document_id])}
            )
            lexical_requests.append((scoped, 8))
        for facet in facets:
            lexical_requests.append((request.model_copy(update={"query": facet}), 32))
        lexical = stack.enter_context(
            prefetch_lexical(lexical, lexical_requests, workers=engine.threads)
        )
    documents: dict[str, str] = {}
    pairs = 0

    def score(query: str, ranks: list[tuple[str, float]]) -> list[tuple[str, float]]:
        nonlocal pairs
        pairs += len(ranks)
        if pairs > 400:
            raise ValueError("query plan exceeds aggregate reranker budget")
        ordered, owners = engine._score_candidates(ranks, request, query)
        documents.update(owners)
        return ordered

    dense = engine._rank_dense(request, 100)
    base_lexical = lexical(request, 100)
    base = score(request.query, reciprocal_rank_fusion(base_lexical, dense, 200))
    base_ids = {key for key, _ in base}
    aliases: list[tuple[str, float]] = []
    if hint != request.query:
        aliases = [
            item
            for item in lexical(request.model_copy(update={"query": hint}), 100)
            if item[0] not in base_ids
        ][:50]
    aliases = score(request.query, aliases)
    main = _ordered(base + aliases)
    references = []
    for document_id in references_found:
        scoped = request.model_copy(
            update={"filters": RetrievalFilters(document_ids=[document_id])}
        )
        references.append(score(request.query, lexical(scoped, 8)))
    branches = []
    if facets:
        limit = min(64, (400 - pairs) // len(facets))
        assert engine._embedder is not None and engine._dense is not None
        vectors = engine._embedder.encode(facets, query=True)
        for facet, vector in zip(facets, vectors, strict=True):
            local = request.model_copy(update={"query": facet})
            facet_lexical = lexical(local, 32)
            dense = engine._dense.rank(vector, 64, allowed)
            if engine._parents is not None:
                dense = engine._parents.map_ranks(dense, 32, allowed)
            else:
                dense = dense[:32]
            candidates = reciprocal_rank_fusion(facet_lexical, dense, limit)
            branches.append(score(facet, candidates))
    ranks = maximum_branch_rank([main, *references, *branches])
    return engine._selected_response(ranks, documents, request, "hybrid")
