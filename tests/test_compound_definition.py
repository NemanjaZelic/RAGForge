"""Compound definitions use real source prose without increasing the search budget."""

import textwrap

import pytest
from reportlab.pdfgen.canvas import Canvas

from ragforge.artifacts.builder import build_bundle
from ragforge.artifacts.source_context import build_source_context
from ragforge.core import source_context
from ragforge.core.contracts import RetrievalFilters, RetrieveRequest
from ragforge.core.definitions import catalogue_connection
from ragforge.core.engine import BundleEngine
from ragforge.core.source_context import SourceContext, information_key, parenthetical_subject


@pytest.mark.parametrize(
    "query,expected",
    [
        ("What is a multi-zone buffer?", "multi-zone buffer"),
        ("What are asynchronous jobs?", "asynchronous jobs"),
        ("What is DNS?", None),
        ("What is not synchronized?", None),
        ("What is no longer registered?", None),
        ("What is never activated?", None),
        ("What is neither active nor idle?", None),
        ("What is only locally configured?", None),
        ("What is a buffer except overflow?", None),
        ("What is a buffer unless offline?", None),
        ("What is a buffer in release 17?", None),
        ("What is a queue used for?", None),
        ("What is the purpose of a queue?", None),
        ("What is a buffer and how does it work?", None),
        ('What is "multi-zone buffer"?', None),
        ("What is a buffer; DROP TABLE chunks?", None),
        ("What is " + "x" * 130 + " buffer?", None),
    ],
)
def test_compound_subject_is_bounded_and_keeps_scope(query, expected):
    assert parenthetical_subject(query) == expected


@pytest.fixture(params=[False, True])
def compound_bundle(tmp_path, request):
    source = tmp_path / "source"
    source.mkdir()
    duplicate = "Existing evidence stays available. " + (
        "Repeating the original paragraph keeps every established source fact. " * 4
    )
    for version in [100, 101, 102]:
        canvas = Canvas(str(source / f"ts01v{version}p.pdf"))
        for i, line in enumerate(textwrap.wrap(duplicate, 80)):
            canvas.drawString(40, 800 - i * 15, line)
        canvas.save()
    for n in range(80):
        (source / f"decoy-{n:03d}.txt").write_text(
            "multi-zone buffer configuration parameter. " * 12 + f" Test row {n}.",
            encoding="utf-8",
        )
    alias = "( multi-zone\n\tbuffer )" if request.param else "(multi-zone buffer)"
    definition = (
        "Replication across independent failure zones "
        + alias
        + " keeps the ordered records available after a zone failure."
    )
    (source / "definition.txt").write_text(definition, encoding="utf-8")
    bundle = tmp_path / "bundle"
    manifest = build_bundle(source, bundle, collection_id="docs", profile="minimal")
    catalogue = tmp_path / "catalogue.sqlite"
    build_source_context(bundle, catalogue)
    engine = BundleEngine(bundle)
    raw = engine.retrieve(RetrieveRequest(query="Existing evidence", top_k=3))
    assert len(raw.results) == 3 and len({information_key(c, False) for c in raw.results}) == 1
    record = next(f for f in manifest.files if f.path == manifest.collections[0].database_path)
    context = SourceContext(catalogue, engine.sqlite, record.sha256, "docs")
    return bundle, catalogue, engine, context, raw, definition


def focused(context, request):
    with catalogue_connection(context.path, context.index_sha256, context.collection_id) as bank:
        with context.index._connect() as db:
            statements = []
            db.set_trace_callback(
                lambda sql: statements.append(sql) if "chunk_fts MATCH" in sql else None
            )
            chunks = context._focused(
                request.query,
                db,
                bank,
                "bm25",
                request.filters.document_ids if request.filters else None,
            )
            return chunks, statements


def test_parenthetical_definition_beats_repetitive_tables_and_preserves_evidence(
    compound_bundle, monkeypatch
):
    bundle, catalogue, _, context, raw, definition = compound_bundle
    request = RetrieveRequest(query="What is a multi-zone buffer?", top_k=3)
    with monkeypatch.context() as control:
        control.setattr(source_context, "parenthetical_subject", lambda query: None)
        old, old_statements = focused(context, request)
        assert not any(c.source.path == "definition.txt" for c in old)
    new, new_statements = focused(context, request)
    assert any(c.source.path == "definition.txt" and c.text == definition for c in new)
    assert len(new_statements) == len(old_statements) == 2
    assert "instr(lower(" in new_statements[-1]
    engine = BundleEngine(bundle, source_context=catalogue)
    monkeypatch.setattr(engine, "_retrieve", lambda query: raw)
    response = engine.retrieve(request)
    assert any(c.source.path == "definition.txt" for c in response.results)
    assert {information_key(c, False) for c in raw.results} <= {
        information_key(c, False) for c in response.results
    }
    assert len(response.results) <= 3
    assert sum(len(c.text) for c in response.evidence_chunks()) <= request.max_output_chars


def test_missing_authorized_alias_restores_old_fallback_within_three_queries(
    compound_bundle, monkeypatch
):
    _, _, engine, context, raw, _ = compound_bundle
    allowed = [c.document_id for c in raw.results]
    with engine.sqlite._connect() as db:
        allowed.append(
            db.execute(
                "SELECT document_id FROM documents WHERE source_path=?", ("decoy-000.txt",)
            ).fetchone()[0]
        )
    request = RetrieveRequest(
        query="What is multi-zone buffer?", filters=RetrievalFilters(document_ids=allowed)
    )
    with monkeypatch.context() as control:
        control.setattr(source_context, "parenthetical_subject", lambda query: None)
        old, old_statements = focused(context, request)
    new, new_statements = focused(context, request)
    assert new == old and new
    assert all(c.document_id in allowed and c.source.path != "definition.txt" for c in new)
    assert len(old_statements) == 2 and len(new_statements) == 3


def test_saturated_three_branch_plan_is_unchanged(compound_bundle, monkeypatch):
    _, _, _, context, _, _ = compound_bundle
    request = RetrieveRequest(query="What is multi-zone buffer replication behavior?")
    with monkeypatch.context() as control:
        control.setattr(source_context, "parenthetical_subject", lambda query: None)
        old, old_statements = focused(context, request)
    new, new_statements = focused(context, request)
    assert new == old and new_statements == old_statements
    assert len(new_statements) <= 3
