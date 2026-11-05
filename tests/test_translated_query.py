"""Caller translations share one bounded, scoped offline retrieval operation."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ragforge.artifacts.builder import build_bundle
from ragforge.core.chunk import ChunkConfig
from ragforge.core.contracts import RetrievalFilters, RetrievalResponse, RetrieveRequest
from ragforge.core.engine import BundleEngine
from ragforge.core.translated import scoped_facets, translated_response


@pytest.mark.parametrize("translation", ["", "  ", "x" * 8193, 12, False, ["text"]])
def test_translation_is_a_bounded_nonblank_query(translation):
    with pytest.raises(ValidationError):
        RetrieveRequest(query="original", query_translation=translation)


def test_technical_subjects_are_inherited_without_inventing_or_replacing_subjects():
    assert scoped_facets("How does route_table log updates and which scans are redundant?") == [
        "How does route_table log updates?",
        "route_table: which scans are redundant?",
    ]
    assert scoped_facets("How does alpha_fn work and how does beta_fn differ?") == [
        "How does alpha_fn work?",
        "how does beta_fn differ?",
    ]
    assert scoped_facets('How does route_table use "and how" and which scans repeat?') == [
        'How does route_table use "and how"?',
        "route_table: which scans repeat?",
    ]


def test_all_query_and_reference_branches_share_the_400_pair_limit_and_grants():
    requests = []
    scored = []
    allowed = [f"{i:064x}" for i in range(1, 5)]

    def lexical(request, limit):
        requests.append(request)
        assert request.filters.document_ids and set(request.filters.document_ids) <= set(allowed)
        assert request.query_translation is None
        return [(f"lex-{request.query}-{i}", -float(i)) for i in range(limit)]

    def dense(request, limit):
        requests.append(request)
        assert request.filters.document_ids == allowed
        assert request.query_translation is None
        return [(f"dense-{request.query}-{i}", -float(i)) for i in range(limit)]

    def score(ranks, request, query):
        scored.extend(ranks)
        assert len(scored) <= 400 and request.filters.document_ids == allowed
        return ranks, {key: allowed[0] for key, _ in ranks}

    engine = SimpleNamespace(
        sqlite=SimpleNamespace(rank_bm25=lexical),
        _rank_dense=dense,
        _ranking_query=lambda query, scope: query + " alias",
        _score_candidates=score,
        collection=SimpleNamespace(
            documents=[
                SimpleNamespace(document_id=d, source_path=f"spec{i}.txt")
                for i, d in enumerate(allowed, 1)
            ]
        ),
        _selected_response=lambda *args: RetrievalResponse(contract_version="1", results=[]),
    )
    translated_response(
        engine,
        RetrieveRequest(
            query="Šta rade SPEC 1 SPEC 2 SPEC 3 SPEC 4?",
            query_translation=(
                "What does ALPHA do and what does BETA do "
                "and how does GAMMA work and how does DELTA end?"
            ),
            filters=RetrievalFilters(document_ids=allowed),
        ),
    )
    assert len(scored) == 400
    assert any(r.query.startswith("Šta") for r in requests)
    assert any(r.query.startswith("What") for r in requests)


@pytest.mark.parametrize("backend", ["exact", "ann"])
def test_real_offline_translation_path_keeps_scope_limits_and_bundle_bytes(
    tmp_path: Path, tiny_model, tiny_reranker, offline_cli, monkeypatch, backend
):
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "public.md").write_text(
        "# Public route\nThe public route returns rollback information. " * 12
    )
    (sources / "private.md").write_text(
        "# Private route\nSECRET_PRIVATE_DATA authorized rollback token. " * 12
    )
    bundle = tmp_path / "bundle"
    manifest = build_bundle(
        sources,
        bundle,
        collection_id="docs",
        model_directory=tiny_model,
        reranker_directory=tiny_reranker,
        dense_backend=backend,
        chunk_config=ChunkConfig(chunk_size_chars=140, overlap_chars=20),
    )
    before = (bundle / "manifest.json").read_bytes()
    public = next(
        d.document_id for d in manifest.collections[0].documents if d.source_path == "public.md"
    )
    engine = BundleEngine(bundle, threads=1)
    seen = []
    actual = engine._score_candidates

    def capture(ranks, request, ranking_query=None):
        seen.append((ranking_query, len(ranks)))
        assert sum(n for _, n in seen) <= 400
        values = actual(ranks, request, ranking_query)
        assert all(owner == public for owner in values[1].values())
        return values

    monkeypatch.setattr(engine, "_score_candidates", capture)
    request = RetrieveRequest(
        query="Šta javna ruta vraća?",
        query_translation="What rollback information does public.md return?",
        search_method="hybrid",
        top_k=3,
        max_output_chars=700,
        filters=RetrievalFilters(document_ids=[public]),
    )
    response = engine.retrieve(request)
    assert response.results
    assert all(
        c.document_id == public and "SECRET_PRIVATE_DATA" not in c.text for c in response.results
    )
    assert len(response.results) <= 3 and sum(len(c.text) for c in response.results) <= 700
    assert seen[0][0] == request.query and seen[1][0] == request.query_translation
    used = offline_cli(
        [
            "use",
            str(bundle),
            "--query",
            request.query,
            "--query-translation",
            request.query_translation,
            "--search-method",
            "hybrid",
            "--top-k",
            "3",
            "--max-output-chars",
            "700",
        ]
    )
    assert used.returncode == 0, used.stderr
    assert json.loads(used.stdout)["results"]
    assert (bundle / "manifest.json").read_bytes() == before
    for update in [{"search_method": "bm25"}, {"search_method": "dense"}, {"rerank": False}]:
        with pytest.raises(ValueError, match="query translation requires"):
            engine.retrieve(request.model_copy(update=update))
