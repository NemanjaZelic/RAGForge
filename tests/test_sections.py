"""Short-section completion preserves scope, strong hits and resource bounds."""

import json
import sqlite3
from pathlib import Path

import pytest

from ragforge.core.contracts import RetrievalFilters, RetrievalResponse, RetrieveRequest
from ragforge.core.sections import complete_sections
from ragforge.core.sqlite import SCHEMA, RetrievalError, SQLiteEngine


@pytest.fixture
def section_index(tmp_path: Path):
    path = tmp_path / "index.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO collections VALUES ('docs','Docs')")
        for doc, name in [("a" * 64, "guide.html"), ("b" * 64, "private.html")]:
            db.execute(
                "INSERT INTO documents VALUES (?,?,?,?,?,?,?)",
                (doc, "docs", name, "f" * 64, "test", "[]", "[]"),
            )
            for ordinal in range(53):
                section = (
                    "Guide"
                    if ordinal == 0
                    else "Guide > Definition"
                    if ordinal == 1
                    else "Guide > Detail"
                )
                text = (
                    "Source definition: tabs occupy eight columns."
                    if ordinal == 1
                    else f"Existing source passage {ordinal}."
                )
                if doc == "b" * 64:
                    text = "PRIVATE " + text
                source = json.dumps({"path": name, "section": section})
                key = f"{ordinal + (100 if doc[0] == 'b' else 0):064x}"
                db.execute(
                    "INSERT INTO chunks(collection_id,document_id,chunk_id,"
                    "ordinal,text,source_json) "
                    "VALUES (?,?,?,?,?,?)",
                    ("docs", doc, key, ordinal, text, source),
                )
    engine = SQLiteEngine(path)
    request = RetrieveRequest(
        query="definition",
        top_k=50,
        max_output_chars=48000,
        filters=RetrievalFilters(document_ids=["a" * 64]),
    )
    ranks = [(f"{i:064x}", 100 - i) for i in [0, *range(2, 51)]]
    response = engine.ranked_response(ranks, request, "hybrid")
    return engine, request, response


def test_complete_short_definition_with_original_ids_text_citations_and_no_private_body(
    section_index,
):
    engine, request, original = section_index
    result = complete_sections(engine, request, original)
    assert result.results[:20] == [
        c.model_copy(update={"rank_score": 1 / (61 + i)})
        for i, c in enumerate(original.results[:20])
    ]
    assert len(result.results) == len(original.results) == 50
    assert any("eight columns" in c.text for c in result.results)
    assert all(c.document_id == "a" * 64 and "PRIVATE" not in c.text for c in result.results)
    assert len({c.chunk_id for c in result.results}) == 50
    with engine._connect() as db:
        for chunk in result.results:
            row = db.execute("SELECT * FROM chunks WHERE chunk_id=?", (chunk.chunk_id,)).fetchone()
            assert engine._chunk(row, chunk.rank_score, "hybrid") == chunk
    assert complete_sections(engine, request, original) == result


def test_full_character_budget_cannot_replace_with_larger_definition(section_index):
    engine, request, original = section_index
    request = request.model_copy(
        update={"max_output_chars": sum(len(c.text) for c in original.results)}
    )
    assert complete_sections(engine, request, original) is original


def test_small_context_and_one_per_document_cap_keep_baseline(section_index):
    engine, request, original = section_index
    assert complete_sections(engine, request, original, max_chunks_per_document=1) is original
    small = RetrievalResponse(contract_version="1", results=original.results[:20])
    assert complete_sections(engine, request.model_copy(update={"top_k": 20}), small) is small


def test_scope_rejected_before_section_database_reads(section_index, monkeypatch):
    engine, request, original = section_index

    def forbidden():
        raise AssertionError("unauthorized metadata access")

    monkeypatch.setattr(engine, "_connect", forbidden)
    for scoped in [
        request.model_copy(update={"filters": RetrievalFilters(document_ids=["b" * 64])}),
        request.model_copy(update={"collection_id": "private"}),
    ]:
        with pytest.raises(RetrievalError, match="outside request scope"):
            complete_sections(engine, scoped, original)


def test_plain_sources_and_oversized_metadata_keep_original(section_index, monkeypatch):
    engine, request, original = section_index
    plain = original.model_copy(
        update={
            "results": [
                c.model_copy(update={"source": c.source.model_copy(update={"section": None})})
                for c in original.results
            ]
        }
    )
    assert complete_sections(engine, request, plain) is plain
    monkeypatch.setattr("ragforge.core.sections.MAX_DOCUMENT_CHUNKS", 20)
    assert complete_sections(engine, request, original) is original


def test_one_representative_per_section_is_preserved(section_index):
    engine, request, original = section_index
    # Every lower-ranked chunk is the only representative of its section.
    protected = original.model_copy(
        update={
            "results": [
                c
                if i < 20
                else c.model_copy(
                    update={"source": c.source.model_copy(update={"section": f"Unique {i}"})}
                )
                for i, c in enumerate(original.results)
            ]
        }
    )
    assert complete_sections(engine, request, protected) is protected


def test_metadata_character_budget_falls_back_without_section_body_reads(
    section_index, monkeypatch
):
    engine, request, original = section_index
    monkeypatch.setattr("ragforge.core.sections.MAX_METADATA_CHARS", 10)
    assert complete_sections(engine, request, original) is original


def boundary_context(section_index, *, long_definition=False):
    engine, request, _ = section_index
    import json
    import sqlite3

    with sqlite3.connect(engine.database) as db:
        for ordinal in range(3):
            source = json.dumps({"path": "guide.html", "section": "Guide > Boundary"})
            text = "Original first definition " + (
                "details " * 500 if long_definition else "with source context."
            )
            db.execute(
                "UPDATE chunks SET source_json=? WHERE document_id=? AND ordinal=?",
                (source, "a" * 64, ordinal),
            )
            if ordinal == 0:
                db.execute(
                    "UPDATE chunks SET text=? WHERE document_id=? AND ordinal=0", (text, "a" * 64)
                )
    scoped = request.model_copy(
        update={"filters": RetrievalFilters(document_ids=["a" * 64, "b" * 64])}
    )
    ranks = [(f"{i:064x}", 1000 - i) for i in [1, 2, *range(100, 148)]]
    return engine, scoped, engine.ranked_response(ranks, scoped, "hybrid")


def test_v2_completes_the_sole_missing_first_chunk_without_displacing_strong_hits(section_index):
    engine, request, original = boundary_context(section_index)
    assert complete_sections(engine, request, original) is original
    result = complete_sections(
        engine, request, original, policy="section-start-v2", max_chunks_per_document=3
    )
    assert [c.chunk_id for c in result.results[:20]] == [c.chunk_id for c in original.results[:20]]
    assert len(result.results) == 50
    assert sum(c.document_id == "a" * 64 for c in result.results) == 3
    assert any(c.chunk_id == "0" * 64 for c in result.results)
    assert all(c.document_id in request.filters.document_ids for c in result.results)
    assert sum(len(c.text) for c in result.evidence_chunks()) <= request.max_output_chars


def test_v2_cross_document_completion_respects_document_cap(section_index):
    engine, request, original = boundary_context(section_index)
    assert (
        complete_sections(
            engine, request, original, policy="section-start-v2", max_chunks_per_document=2
        )
        is original
    )


def test_v2_cannot_exceed_request_character_budget(section_index):
    engine, request, original = boundary_context(section_index, long_definition=True)
    request = request.model_copy(
        update={"max_output_chars": sum(len(c.text) for c in original.results)}
    )
    assert complete_sections(engine, request, original, policy="section-start-v2") is original


def gap_context(section_index):
    engine, request, _ = section_index
    ranks = [(f"{i:064x}", 100 - i) for i in [0, *range(2, 21), *range(22, 52)]]
    return engine, request, engine.ranked_response(ranks, request, "hybrid")


def test_gap_completion_keeps_bracketing_anchors_and_exact_source_chunks(section_index):
    from ragforge.core.section_gaps import complete_section_gaps

    engine, request, original = gap_context(section_index)
    result = complete_section_gaps(engine, request, original)
    assert len(result.results) == 50 and len({c.chunk_id for c in result.results}) == 50
    assert any(c.chunk_id == f"{21:064x}" for c in result.context)
    assert all(any(c.chunk_id == f"{i:064x}" for c in result.results) for i in [20, 22])
    assert [(c.chunk_id, c.text) for c in result.results[:20]] == [
        (c.chunk_id, c.text) for c in original.results[:20]
    ]
    assert sum(len(c.text) for c in result.evidence_chunks()) <= request.max_output_chars
    with engine._connect() as db:
        for c in result.evidence_chunks():
            row = db.execute("SELECT * FROM chunks WHERE chunk_id=?", (c.chunk_id,)).fetchone()
            assert c == engine._chunk(row, c.rank_score, c.retrieval_method)


def test_gap_completion_refuses_scope_before_any_database_access(section_index, monkeypatch):
    from ragforge.core.section_gaps import complete_section_gaps

    engine, request, original = gap_context(section_index)
    monkeypatch.setattr(engine, "_connect", lambda: pytest.fail("must validate scope first"))
    with pytest.raises(RetrievalError, match="outside request scope"):
        complete_section_gaps(
            engine, request.model_copy(update={"collection_id": "wrong"}), original
        )


def test_gap_completion_respects_character_budget_and_page_boundaries(section_index):
    from ragforge.core.section_gaps import complete_section_gaps

    engine, request, original = gap_context(section_index)
    with sqlite3.connect(engine.database) as db:
        db.execute("UPDATE chunks SET text=? WHERE chunk_id=?", ("large " * 1000, f"{21:064x}"))
    limited = request.model_copy(
        update={"max_output_chars": sum(len(c.text) for c in original.results)}
    )
    assert complete_section_gaps(engine, limited, original) is original
    with sqlite3.connect(engine.database) as db:
        source = json.dumps({"path": "guide.html", "section": "Guide > Detail", "page": 2})
        db.execute("UPDATE chunks SET source_json=? WHERE chunk_id=?", (source, f"{22:064x}"))
    ranks = [(c.chunk_id, c.rank_score) for c in original.results]
    response = engine.ranked_response(ranks, request, "hybrid")
    assert complete_section_gaps(engine, request, response) is response


def test_gap_context_preserves_every_section_representative(section_index):
    from ragforge.core.section_gaps import complete_section_gaps

    engine, request, original = gap_context(section_index)
    with sqlite3.connect(engine.database) as db:
        for ordinal in range(23, 53):
            source = json.dumps({"path": "guide.html", "section": f"Guide > Unique {ordinal}"})
            db.execute(
                "UPDATE chunks SET source_json=? WHERE chunk_id=?", (source, f"{ordinal:064x}")
            )
    original = engine.ranked_response(
        [(c.chunk_id, c.rank_score) for c in original.results], request, "hybrid"
    )
    result = complete_section_gaps(engine, request, original)
    assert result.results == original.results
    assert any(c.chunk_id == f"{21:064x}" for c in result.context)


def test_single_hit_can_return_its_complete_short_section_without_losing_sources(section_index):
    from ragforge.core.section_gaps import complete_section_gaps

    engine, request, _ = section_index
    with sqlite3.connect(engine.database) as db:
        for ordinal in range(20, 25):
            source = json.dumps({"path": "guide.html", "section": "Guide > Specific definition"})
            db.execute(
                "UPDATE chunks SET source_json=? WHERE chunk_id=?", (source, f"{ordinal:064x}")
            )
    selected = [i for i in range(53) if i not in {1, 20, 21, 23, 24}]
    original = engine.ranked_response([(f"{i:064x}", 100 - i) for i in selected], request, "hybrid")
    assert sum(c.source.section == "Guide > Specific definition" for c in original.results) == 1
    result = complete_section_gaps(engine, request, original)
    assert result.results == original.results
    assert {c.chunk_id for c in result.context} == {f"{i:064x}" for i in [20, 21, 23, 24]}
    assert sum(len(c.text) for c in result.evidence_chunks()) <= request.max_output_chars


def test_short_pdf_page_is_completed_even_without_a_section_heading(section_index):
    from ragforge.core.section_gaps import complete_section_gaps

    engine, request, _ = section_index
    with sqlite3.connect(engine.database) as db:
        for ordinal in range(20, 25):
            source = json.dumps({"path": "guide.html", "page": 3})
            db.execute(
                "UPDATE chunks SET source_json=? WHERE chunk_id=?", (source, f"{ordinal:064x}")
            )
    selected = [i for i in range(53) if i not in {1, 20, 21, 23, 24}]
    original = engine.ranked_response([(f"{i:064x}", 100 - i) for i in selected], request, "hybrid")
    result = complete_section_gaps(engine, request, original)
    assert result.results == original.results
    assert {c.chunk_id for c in result.context if c.source.page == 3} == {
        f"{i:064x}" for i in [20, 21, 23, 24]
    }
    assert all(c.source.page == 3 for c in result.context)


def test_unheaded_text_adds_neighbors_without_removing_primary_evidence(section_index):
    from ragforge.core.section_gaps import complete_section_gaps

    engine, request, _ = section_index
    with sqlite3.connect(engine.database) as db:
        db.execute("UPDATE chunks SET source_json=?", (json.dumps({"path": "guide.html"}),))
    request = request.model_copy(update={"max_output_chars": 16000})
    original = engine.ranked_response(
        [(f"{i:064x}", 100 - i) for i in range(0, 53, 2)], request, "hybrid"
    )
    result = complete_section_gaps(engine, request, original)
    assert result.context
    assert sum(len(c.text) for c in result.evidence_chunks()) <= request.max_output_chars
    assert all(c.rank_score == 0 for c in result.context)
    assert result.results == original.results
    assert {c.chunk_id for c in result.results}.isdisjoint(c.chunk_id for c in result.context)


def test_unheaded_neighbor_excerpt_is_verbatim_and_preserves_all_primary_hits(section_index):
    from ragforge.core.section_gaps import complete_section_gaps

    engine, request, _ = section_index
    with sqlite3.connect(engine.database) as db:
        db.execute("UPDATE chunks SET source_json=?", (json.dumps({"path": "guide.html"}),))
        db.execute(
            "UPDATE chunks SET text=? WHERE chunk_id=?",
            ("Beginning. " + "verbatim source " * 150 + "Nearest boundary.", f"{1:064x}"),
        )
    original = engine.ranked_response(
        [(f"{i:064x}", 100 - i) for i in range(0, 53, 2)], request, "hybrid"
    )
    request = request.model_copy(
        update={"max_output_chars": sum(len(c.text) for c in original.results) + 200}
    )
    result = complete_section_gaps(engine, request, original)
    assert result.results == original.results
    assert len(result.context) == 1
    extra = result.context[0]
    assert len(extra.text) == 200 and extra.text.startswith("Beginning.")
    assert extra.text_offset is not None
    with engine._connect() as db:
        stored = db.execute(
            "SELECT text FROM chunks WHERE chunk_id=?", (extra.chunk_id,)
        ).fetchone()[0]
    assert extra.text == stored[extra.text_offset : extra.text_offset + len(extra.text)]
    assert sum(len(c.text) for c in result.evidence_chunks()) == request.max_output_chars


def test_previous_neighbor_excerpt_uses_its_tail(section_index):
    from ragforge.core.section_gaps import complete_section_gaps

    engine, request, _ = section_index
    with sqlite3.connect(engine.database) as db:
        db.execute("UPDATE chunks SET source_json=?", (json.dumps({"path": "guide.html"}),))
        db.execute(
            "UPDATE chunks SET text=? WHERE chunk_id=?",
            ("source " * 300 + "Closest preceding boundary.", f"{1:064x}"),
        )
    selected = [2, *range(4, 53, 2), 0]
    original = engine.ranked_response([(f"{i:064x}", 100 - i) for i in selected], request, "hybrid")
    request = request.model_copy(
        update={"max_output_chars": sum(len(c.text) for c in original.results) + 200}
    )
    result = complete_section_gaps(engine, request, original)
    assert result.results == original.results
    assert result.context[0].text.endswith("Closest preceding boundary.")
    assert result.context[0].text_offset > 0


def test_verified_page_bounds_do_not_change_full_context(section_index):
    from ragforge.core.section_gaps import complete_section_gaps

    engine, request, _ = section_index
    with sqlite3.connect(engine.database) as db:
        for ordinal in [20, 22, 24]:
            db.execute(
                "UPDATE chunks SET source_json=? WHERE chunk_id=?",
                (json.dumps({"path": "guide.html", "page": 3}), f"{ordinal:064x}"),
            )
    selected = [i for i in range(53) if i not in {1, 20, 24}]
    original = engine.ranked_response([(f"{i:064x}", 100 - i) for i in selected], request, "hybrid")
    full = complete_section_gaps(engine, request, original)
    bounded = complete_section_gaps(
        engine,
        request,
        original,
        page_bounds=lambda document, page: (20, 24) if page == 3 else None,
    )
    assert bounded == full
    assert {c.chunk_id for c in bounded.context if c.source.page == 3} == {
        f"{i:064x}" for i in [20, 24]
    }
