"""Planning adds retrieval branches without query replacement or grant bypass."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ragforge.artifacts.builder import build_bundle
from ragforge.artifacts.recontextualize import recontextualize_bundle
from ragforge.artifacts.verification import build_identity, verify_bundle
from ragforge.core.aliases import Acronym, AliasBank, AliasProof
from ragforge.core.chunk import ChunkConfig
from ragforge.core.contracts import RetrievalFilters, RetrievalResponse, RetrieveRequest
from ragforge.core.engine import BundleEngine
from ragforge.core.planning import (
    maximum_branch_rank,
    planned_response,
    question_facets,
    referenced_documents,
)


def test_facets_keep_explicit_names_and_inherit_only_shared_scope():
    assert question_facets("What does ALPHA require and what does BETA provide?") == [
        "What does ALPHA require?",
        "what does BETA provide?",
    ]
    assert question_facets("Which port carries ALPHA over BETA and must a BETA client retry?") == [
        "Which port carries ALPHA over BETA?",
        "ALPHA: must a BETA client retry?",
    ]
    comparison = question_facets("How do Secure and Hidden cookie attributes restrict access?")
    assert comparison == [
        "How do Secure cookie attributes restrict access?",
        "How do Hidden cookie attributes restrict access?",
    ]
    query = (
        "What does ALPHA do and what does BETA do and how does GAMMA work and why is DELTA used?"
    )
    assert len(question_facets(query)) == 3
    assert question_facets("single ordinary question") == []
    assert question_facets("What " + "long " * 129 + "and what else?") == []
    assert question_facets("x" * 2049) == []


def test_explicit_identifiers_respect_boundaries_ambiguity_cap_and_grants():
    docs = [("a", "spec42.txt"), ("b", "private/spec421.txt"), ("c", "guide.md")]
    assert referenced_documents("Read SPEC 42", docs) == ["a"]
    assert referenced_documents("Read SPEC 421", docs, ["a"]) == []
    assert referenced_documents("Use guide.md.", docs) == ["c"]
    assert referenced_documents("Use xguide.md", docs) == []
    assert len(referenced_documents("SPEC 42", [(str(i), "spec42.txt") for i in range(10)])) == 4


def test_branch_fusion_counts_best_rank_once_with_stable_ties():
    result = maximum_branch_rank([[("a", -9.0), ("b", 8.0)], [("b", -100.0), ("c", 5.0)]])
    assert result == [("a", 1 / 61), ("b", 1 / 61), ("c", 1 / 62)]


@pytest.mark.parametrize("backend", ["exact", "ann"])
def test_portable_planning_scopes_every_passage_and_keeps_reranker_queries_original(
    tmp_path: Path, tiny_model, tiny_reranker, monkeypatch, offline_cli, backend: str
):
    sources = tmp_path / "sources"
    sources.mkdir()
    for i in range(3):
        (sources / f"spec{42 + i}.txt").write_text(
            "Alpha Beta Protocol (ABP) provides rollback tokens. SOURCE_PRIVATE.\n"
            + "The server processes protocol messages and requires a transaction. " * 12
        )
    (sources / "public.txt").write_text(
        "ABP public server information and transaction rollback. " * 12
    )
    child, parent, output = tmp_path / "child", tmp_path / "parent", tmp_path / "planned"
    build_bundle(
        sources,
        child,
        collection_id="docs",
        model_directory=tiny_model,
        dense_backend=backend,
        chunk_config=ChunkConfig(chunk_size_chars=140, overlap_chars=20),
    )
    base = build_bundle(
        sources,
        parent,
        collection_id="docs",
        profile="minimal",
        reranker_directory=tiny_reranker,
        chunk_config=ChunkConfig(chunk_size_chars=500, overlap_chars=100),
    )
    aliases = tmp_path / "aliases.json"
    aliases.write_text(
        AliasBank(
            catalogue_sha256="a" * 64,
            definitions=[
                Acronym(
                    short="ABP",
                    long_form="alpha beta protocol",
                    proofs=[
                        AliasProof(
                            source_path=d.source_path,
                            source_sha256=d.content_sha256,
                            quote="Alpha Beta Protocol (ABP)",
                        )
                        for d in base.collections[0].documents
                        if d.source_path != "public.txt"
                    ],
                )
            ],
        ).model_dump_json()
    )
    manifest = recontextualize_bundle(
        child,
        parent,
        output,
        query_aliases=aliases,
        query_planning="facets-v1",
        section_context="section-start-v1",
    )
    assert verify_bundle(output).retrieval_configuration.query_planning == "facets-v1"
    assert manifest.retrieval_configuration.section_context == "section-start-v1"
    original = (parent / "manifest.json").read_bytes()
    engine = BundleEngine(output, threads=1)
    raw_request = RetrieveRequest(query="ABP server", search_method="bm25")
    assert engine.retrieve(raw_request) == engine.sqlite.retrieve(raw_request)
    assert engine._reranker is None and engine._embedder is None
    public = next(
        d.document_id for d in manifest.collections[0].documents if d.source_path == "public.txt"
    )
    from ragforge.core.rerank import ONNXReranker

    scorer = ONNXReranker(output / "models/reranker", threads=1)
    engine._reranker = scorer
    calls = []
    actual_score = scorer.score

    def score(query, passages):
        calls.append((query, list(passages)))
        return actual_score(query, passages)

    monkeypatch.setattr(scorer, "score", score)
    query = "What ABP server is in SPEC 42 and what does GAMMA require?"
    request = RetrieveRequest(
        query=query,
        search_method="hybrid",
        top_k=10,
        max_output_chars=2000,
        filters=RetrievalFilters(document_ids=[public]),
    )
    response = engine.retrieve(request)
    assert response.results and all(c.document_id == public for c in response.results)
    assert sum(len(c.text) for c in response.results) <= 2000
    assert all(
        "SOURCE_PRIVATE" not in p and "alpha beta protocol" not in p.casefold()
        for _, passages in calls
        for p in passages
    )
    assert all("alpha beta protocol" not in q.casefold() for q, _ in calls)
    assert calls[0][0] == query
    calls.clear()
    engine.retrieve(request.model_copy(update={"filters": None}))
    assert calls and calls[0][0] == query
    assert all(q == query or q in question_facets(query) for q, _ in calls)
    assert sum(len(passages) for _, passages in calls) <= 400
    assert (parent / "manifest.json").read_bytes() == original
    used = offline_cli(["use", str(output), "--query", "ABP server", "--search-method", "hybrid"])
    assert used.returncode == 0, used.stderr
    assert json.loads(used.stdout)["results"]
    with pytest.raises(ValidationError, match="100 candidates"):
        manifest.retrieval_configuration.model_copy(update={"candidates_per_method": 200})
        type(manifest.retrieval_configuration).model_validate(
            {**manifest.retrieval_configuration.model_dump(), "candidates_per_method": 200}
        )
    data = base.model_dump(mode="json", exclude={"build_id"})
    data["retrieval_configuration"].pop("query_aliases", None)
    data["retrieval_configuration"].pop("query_planning", None)
    data["retrieval_configuration"].pop("section_context", None)
    for doc in data["collections"][0]["documents"]:
        doc.pop("title", None)
    expected = hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    assert base.build_id == build_identity(base) == expected


def test_plan_bounds_all_branches_before_reranker_inference():
    requests = []

    def rank(request, limit):
        prefix = request.query + str(request.filters)
        return [(prefix + str(i), float(-i)) for i in range(limit)]

    class Model:
        def encode(self, queries, query=True):
            return list(range(len(queries)))

    class Dense:
        def rank(self, vector, limit, allowed):
            return [(f"dense{vector}-{i}", -float(i)) for i in range(limit)]

    engine = SimpleNamespace(
        manifest=SimpleNamespace(
            retrieval_configuration=SimpleNamespace(query_planning="facets-v1")
        ),
        collection=SimpleNamespace(
            documents=[
                SimpleNamespace(document_id=f"{i:064x}", source_path=f"spec{i}.txt")
                for i in range(1, 5)
            ]
        ),
        sqlite=SimpleNamespace(rank_bm25=rank),
        _rank_dense=lambda request, limit: [(f"base{i}", -float(i)) for i in range(limit)],
        _ranking_query=lambda query, allowed: query + " supplemental",
        _embedder=Model(),
        _dense=Dense(),
        _parents=None,
        _selected_response=lambda *args: RetrievalResponse(contract_version="1", results=[]),
    )

    def score(ranks, request, query):
        requests.extend(ranks)
        assert len(requests) <= 400
        return ranks, {key: "document" for key, _ in ranks}

    engine._score_candidates = score
    planned_response(
        engine,
        RetrieveRequest(
            query=(
                "What does ALPHA do in SPEC 1 SPEC 2 SPEC 3 SPEC 4 "
                "and what does BETA do and how does GAMMA work?"
            )
        ),
    )
    assert len(requests) == 399
