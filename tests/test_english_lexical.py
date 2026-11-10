"""English content terms must keep scope, literals and original validation."""

import pytest

from ragforge.core.contracts import RetrievalFilters, RetrieveRequest
from ragforge.core.english_lexical import content_lexical, english_content_query
from ragforge.core.sqlite import RetrievalError


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("What is the purpose of ZQP messages?", "purpose ZQP messages"),
        (
            "According to EXAMPLE 12 version 3.2, How are trace records stored?",
            "trace records stored",
        ),
        ("What should UE do if it is not ready?", "should UE if not ready"),
        ("How must SQL OR IN behave without NULL?", "must SQL OR IN behave without NULL"),
        ("What is DNS?", "What is DNS?"),
        ("What is the?", "What is the?"),
    ],
)
def test_content_terms_keep_normative_words_and_technical_names(query, expected):
    assert english_content_query(query) == expected


@pytest.mark.parametrize(
    "query",
    [
        'What does "IN" mean?',
        "What does `--from` do?",
        "What is f(x)?",
        "How is config[on] used?",
        "What does x=on mean?",
        "Where is /the/in/file?",
        "What does --in do?",
        "How doesn't retry work?",
        "What is “according to” for?",
    ],
)
def test_quoted_code_argument_and_path_queries_are_unchanged(query):
    assert english_content_query(query) == query


def test_original_term_limit_is_checked_before_reformulation():
    query = "What is the " + " ".join(f"term{i}" for i in range(62))
    with pytest.raises(RetrievalError, match="64 literal terms"):
        english_content_query(query)


def test_only_lexical_query_changes_and_caller_scope_is_not_mutated():
    request = RetrieveRequest(
        query="What is the purpose of ZQP messages?",
        collection_id="docs",
        top_k=7,
        max_output_chars=2000,
        filters=RetrievalFilters(document_ids=["a" * 64]),
    )
    snapshot = request.model_dump_json()
    seen = []

    def rank(local, limit):
        seen.append(local)
        assert local.query == "purpose ZQP messages"
        assert local.model_dump(exclude={"query"}) == request.model_dump(exclude={"query"})
        assert limit == 100
        return [("b" * 64, 1.25)]

    assert content_lexical(rank)(request, 100) == [("b" * 64, 1.25)]
    assert seen[0] is not request and request.model_dump_json() == snapshot


def test_compound_gpu_plans_preserve_all_literal_lexical_branches(monkeypatch):
    from types import SimpleNamespace

    from ragforge.core import english_lexical
    from ragforge.core.contracts import RetrievalResponse
    from ragforge.core.planning import planned_response
    from ragforge.core.planning_v3 import question_facets

    query = "How do ALPHA transport and BETA forwarding address different concerns?"
    facets = question_facets(query)
    assert facets
    seen = []

    def forbidden(rank):
        raise AssertionError("compound lexical branch was reformulated")

    monkeypatch.setattr(english_lexical, "content_lexical", forbidden)

    def rank(request, limit):
        seen.append(request.query)
        return [(request.query, 1.0)]

    def score(ranks, request, scoring_query):
        return ranks, {key: "owner" for key, _ in ranks}

    engine = SimpleNamespace(
        manifest=SimpleNamespace(
            retrieval_configuration=SimpleNamespace(
                query_planning="facets-v3",
                query_language="en",
                reranker=SimpleNamespace(runtime="openvino-gpu-f16"),
            )
        ),
        collection=SimpleNamespace(documents=[]),
        threads=2,
        sqlite=SimpleNamespace(rank_bm25=rank),
        _ranking_query=lambda q, allowed: q,
        _rank_dense=lambda request, limit: [("dense", 1.0)],
        _score_candidates=score,
        _embedder=SimpleNamespace(encode=lambda queries, query: list(range(len(queries)))),
        _dense=SimpleNamespace(rank=lambda vector, limit, allowed: []),
        _parents=None,
        _selected_response=lambda *args: RetrievalResponse(contract_version="1", results=[]),
    )
    planned_response(engine, RetrieveRequest(query=query))
    assert set(seen) == {query, *facets}
