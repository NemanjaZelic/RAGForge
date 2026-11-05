"""Small dense hits map only to actual, same-source parent context."""

import json
import sqlite3
from pathlib import Path

import pytest

from ragforge.core.chunk import ChunkConfig
from ragforge.core.contracts import RetrieveRequest
from ragforge.core.parents import ParentMapper
from ragforge.core.parse import load_document
from ragforge.core.scan import scan_corpus
from ragforge.core.sqlite import SQLiteEngine, create_index


def indexes(tmp_path: Path):
    root = tmp_path / "sources"
    root.mkdir()
    body = " ".join(f"Sentence {i} explains protocol requirement and evidence." for i in range(30))
    (root / "current.txt").write_text(body)
    (root / "unrelated.txt").write_text("An unrelated document with different information.")
    docs = [load_document(root, "docs", r) for r in scan_corpus(root, "docs").documents]
    child = tmp_path / "children.sqlite"
    parent = tmp_path / "parents.sqlite"
    create_index(child, "docs", "Docs", docs, ChunkConfig(chunk_size_chars=140, overlap_chars=30))
    create_index(parent, "docs", "Docs", docs, ChunkConfig(chunk_size_chars=500, overlap_chars=100))
    return SQLiteEngine(child), SQLiteEngine(parent)


def test_child_hits_return_real_parent_chunks_and_preserve_scope(tmp_path):
    child, parent = indexes(tmp_path)
    mapper = ParentMapper(child, parent)
    ranks = child.rank_bm25(RetrieveRequest(query="Sentence 10 requirement"), 10)
    mapped = mapper.map_ranks(ranks, 10)
    assert mapped
    with parent._connect() as c:
        for key, score in mapped:
            row = c.execute(
                "SELECT text,document_id FROM chunks WHERE chunk_id=?", (key,)
            ).fetchone()
            assert len(row["text"]) > 140
            assert "protocol requirement" in row["text"]
            assert score in [v for _, v in ranks]
    with pytest.raises(ValueError, match="outside document scope"):
        mapper.map_ranks(ranks, allowed_documents=["f" * 64])
    with pytest.raises(ValueError, match="missing"):
        mapper.map_ranks([("f" * 64, 1.0)])
    assert mapped == mapper.map_ranks(ranks, 10)


def test_mapping_rejects_different_source_versions(tmp_path):
    child, parent = indexes(tmp_path)
    with sqlite3.connect(parent.database) as c:
        c.execute("UPDATE documents SET content_sha256=?", ("f" * 64,))
    with pytest.raises(ValueError, match="inventories differ"):
        ParentMapper(child, parent)


def test_source_inventory_alone_cannot_substitute_for_actual_text_and_page(tmp_path):
    child, parent = indexes(tmp_path)
    ranks = child.rank_bm25(RetrieveRequest(query="Sentence"), 5)
    with sqlite3.connect(parent.database) as c:
        c.execute("UPDATE chunks SET text='No matching protocol evidence exists in this text.'")
    assert not ParentMapper(child, parent).map_ranks(ranks)
    with sqlite3.connect(parent.database) as c:
        c.execute("UPDATE chunks SET text=(SELECT text FROM chunk_fts WHERE rowid=chunks.rowid)")
        for key, raw in c.execute("SELECT chunk_id,source_json FROM chunks").fetchall():
            source = json.loads(raw)
            source["page"] = 2
            c.execute("UPDATE chunks SET source_json=? WHERE chunk_id=?", (json.dumps(source), key))
    assert not ParentMapper(child, parent).map_ranks(ranks)


def test_large_paginated_document_maps_each_page_without_loading_other_pages(tmp_path):
    child, parent = indexes(tmp_path)
    ranks = child.rank_bm25(RetrieveRequest(query="Sentence requirement"), 2)
    assert len(ranks) == 2
    with sqlite3.connect(child.database) as db:
        for page, (key, _) in enumerate(ranks, 1):
            raw = db.execute("SELECT source_json FROM chunks WHERE chunk_id=?", (key,)).fetchone()[
                0
            ]
            source = json.loads(raw)
            source["page"] = page
            db.execute(
                "UPDATE chunks SET source_json=? WHERE chunk_id=?", (json.dumps(source), key)
            )
        doc = db.execute(
            "SELECT document_id FROM chunks WHERE chunk_id=?", (ranks[0][0],)
        ).fetchone()[0]
    with sqlite3.connect(parent.database) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT * FROM chunks WHERE document_id=? ORDER BY ordinal", (doc,)
        ).fetchall()
        for row in rows:
            source = json.loads(row["source_json"])
            source["page"] = 1
            db.execute(
                "UPDATE chunks SET source_json=? WHERE chunk_id=?",
                (json.dumps(source), row["chunk_id"]),
            )
            source["page"] = 2
            db.execute(
                "INSERT INTO chunks(collection_id,document_id,chunk_id,ordinal,text,source_json) "
                "VALUES(?,?,?,?,?,?)",
                (
                    row["collection_id"],
                    doc,
                    f"{row['ordinal'] + 10000:064x}",
                    row["ordinal"] + 10000,
                    row["text"],
                    json.dumps(source),
                ),
            )
        source = json.loads(rows[0]["source_json"])
        source["page"] = 3
        db.executemany(
            "INSERT INTO chunks(collection_id,document_id,chunk_id,ordinal,text,source_json) "
            "VALUES(?,?,?,?,?,?)",
            (
                (
                    rows[0]["collection_id"],
                    doc,
                    f"{i + 20000:064x}",
                    i + 20000,
                    "Unrelated page context. ".ljust(500, "x"),
                    json.dumps(source),
                )
                for i in range(4100)
            ),
        )
        assert (
            db.execute(
                "SELECT sum(length(text)) FROM chunks WHERE document_id=?", (doc,)
            ).fetchone()[0]
            > 2_000_000
        )
    mapper = ParentMapper(child, parent)
    mapped = mapper.map_ranks(ranks, 10, [doc])
    assert mapped == mapper.map_ranks(ranks, 10, [doc])
    assert mapper._cache_chars < 10_000
    with parent._connect() as db:
        pages = set()
        for key, score in mapped:
            row = db.execute(
                "SELECT document_id,source_json FROM chunks WHERE chunk_id=?", (key,)
            ).fetchone()
            assert row["document_id"] == doc
            page = json.loads(row["source_json"])["page"]
            pages.add(page)
            assert score == ranks[page - 1][1]
        assert pages == {1, 2}
    # The original cap still rejects a pathological matching page, without
    # poisoning the cached valid pages or silently truncating the matching tail.
    with sqlite3.connect(child.database) as db:
        source = json.loads(
            db.execute(
                "SELECT source_json FROM chunks WHERE chunk_id=?", (ranks[0][0],)
            ).fetchone()[0]
        )
        source["page"] = 3
        db.execute(
            "UPDATE chunks SET source_json=? WHERE chunk_id=?", (json.dumps(source), ranks[0][0])
        )
    with pytest.raises(ValueError, match="parent document context budget exceeded"):
        mapper.map_ranks(ranks[:1], 10, [doc])
    assert mapper.map_ranks(ranks[1:], 10, [doc])
