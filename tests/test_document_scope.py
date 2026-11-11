"""Explicit title scope is source-confirmed, bounded and grant-preserving."""

from pathlib import Path

import pytest

from ragforge.artifacts.builder import build_bundle
from ragforge.core.chunk import ChunkConfig
from ragforge.core.contracts import RetrievalFilters, RetrieveRequest
from ragforge.core.document_scope import resolve_title_scope
from ragforge.core.engine import BundleEngine


def make_engine(tmp_path: Path, titles: list[str]) -> BundleEngine:
    source = tmp_path / "source"
    source.mkdir()
    for i, title in enumerate(titles):
        (source / f"{i}.md").write_text(
            f"# {title}\n\n## Evaluation\n\nDataset amber has {i + 7} samples.\n\n"
            "## Amber Protocol\n\nA body mention does not make it this document title.\n",
            encoding="utf-8",
        )
    bundle = tmp_path / "bundle"
    build_bundle(
        source,
        bundle,
        collection_id="docs",
        profile="minimal",
        chunk_config=ChunkConfig(chunk_size_chars=200, overlap_chars=30),
    )
    return BundleEngine(bundle)


def test_shared_engine_uses_question_only_and_source_confirmed_owner(tmp_path, monkeypatch):
    engine = make_engine(tmp_path, ["Amber Protocol", "Other Handbook"])
    request = RetrieveRequest(
        query="Which dataset is used?\nDocument title: Amber Protocol", top_k=50
    )
    captured = []
    original = engine._retrieve

    def retrieve(scoped):
        captured.append(scoped)
        return original(scoped)

    monkeypatch.setattr(engine, "_retrieve", retrieve)
    response = engine.retrieve(request)
    target = next(d.document_id for d in engine.collection.documents if d.source_path == "0.md")
    assert captured[0].query == "Which dataset is used?"
    assert captured[0].filters.document_ids == [target]
    assert request.filters is None and request.query.endswith("Amber Protocol")
    assert response.results and all(c.document_id == target for c in response.evidence_chunks())
    with engine.sqlite._connect() as db:
        for c in response.evidence_chunks():
            assert (
                c.text
                == db.execute("SELECT text FROM chunks WHERE chunk_id=?", (c.chunk_id,)).fetchone()[
                    0
                ]
            )


def test_existing_grant_precedes_resolution_and_duplicate_titles_are_ambiguous(tmp_path):
    engine = make_engine(tmp_path, ["Amber Protocol", "Amber Protocol", "Other Handbook"])
    ids = {d.source_path: d.document_id for d in engine.collection.documents}
    query = "Which dataset?\nPaper title: Amber Protocol"
    original = RetrieveRequest(query=query)
    assert resolve_title_scope(engine.sqlite, original) is original
    granted = RetrieveRequest(query=query, filters=RetrievalFilters(document_ids=[ids["1.md"]]))
    scoped = resolve_title_scope(engine.sqlite, granted)
    assert scoped.query == "Which dataset?" and scoped.filters.document_ids == [ids["1.md"]]
    outside = RetrieveRequest(query=query, filters=RetrievalFilters(document_ids=[ids["2.md"]]))
    assert resolve_title_scope(engine.sqlite, outside) is outside
    assert all(c.document_id == ids["2.md"] for c in engine.retrieve(outside).evidence_chunks())


@pytest.mark.parametrize("title", ["Unknown Handbook", "Amber", "x " * 49, "a" * 510 + " bb"])
def test_unknown_and_oversized_titles_keep_original_request(tmp_path, title):
    engine = make_engine(tmp_path, ["Amber Protocol"])
    request = RetrieveRequest(query="Which dataset?\nPaper title: " + title)
    assert resolve_title_scope(engine.sqlite, request) is request


@pytest.mark.parametrize(
    "query",
    [
        "Which dataset is used?",
        "Paper title: Amber Protocol",
        "Question\nplain second line",
        "Question\nPaper title: Amber Protocol\nDocument title: Other Handbook",
    ],
)
def test_ordinary_and_ambiguous_syntax_do_not_query_the_database(tmp_path, monkeypatch, query):
    def forbidden(*args):
        raise AssertionError("No title lookup expected")

    sqlite = make_engine(tmp_path, ["Amber Protocol"]).sqlite
    monkeypatch.setattr(sqlite, "_rank_expression", forbidden)
    monkeypatch.setattr(sqlite, "_connect", forbidden)
    request = RetrieveRequest(query=query)
    assert resolve_title_scope(sqlite, request) is request


@pytest.mark.parametrize("title", ["O'Brien OR Alpha", "Подешавање приступа"])
def test_literal_operators_punctuation_and_unicode_titles(tmp_path, title):
    engine = make_engine(tmp_path, [title, "Other Handbook"])
    request = RetrieveRequest(query="Which dataset?\nPaper title: " + title)
    scoped = resolve_title_scope(engine.sqlite, request)
    assert scoped.query == "Which dataset?"
    assert len(scoped.filters.document_ids) == 1


def test_candidate_cap_falls_back_instead_of_selecting_an_unchecked_title(tmp_path, monkeypatch):
    engine = make_engine(tmp_path, ["Amber Protocol"])
    monkeypatch.setattr(
        engine.sqlite, "_rank_expression", lambda *args: [(str(i), 1.0) for i in range(65)]
    )
    request = RetrieveRequest(query="Which dataset?\nPaper title: Amber Protocol")
    assert resolve_title_scope(engine.sqlite, request) is request


def test_nested_heading_cannot_impersonate_the_document_title(tmp_path):
    engine = make_engine(tmp_path, ["Other Handbook"])
    request = RetrieveRequest(query="Which dataset?\nPaper title: Amber Protocol")
    assert resolve_title_scope(engine.sqlite, request) is request


def test_matching_title_scope_strips_both_original_and_translation(tmp_path):
    engine = make_engine(tmp_path, ["Amber Protocol"])
    request = RetrieveRequest(
        query="Који скуп података?\nPaper title: Amber Protocol",
        query_translation="Which dataset?\nDocument title: Amber Protocol",
    )
    scoped = resolve_title_scope(engine.sqlite, request)
    assert scoped.query == "Који скуп података?"
    assert scoped.query_translation == "Which dataset?"
    assert len(scoped.filters.document_ids) == 1


@pytest.mark.parametrize(
    "translation",
    [
        "Which dataset?",
        "Which dataset?\nPaper title: Other Handbook",
        "Question\nPaper title: Amber Protocol\nPaper title: Amber Protocol",
    ],
)
def test_translation_must_declare_the_same_unique_scope(tmp_path, translation):
    engine = make_engine(tmp_path, ["Amber Protocol"])
    request = RetrieveRequest(
        query="Који скуп?\nPaper title: Amber Protocol", query_translation=translation
    )
    assert resolve_title_scope(engine.sqlite, request) is request
