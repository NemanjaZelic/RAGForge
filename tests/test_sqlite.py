import hashlib
import json
import shutil
import sqlite3
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ragforge.cli import app
from ragforge.core.chunk import ChunkConfig
from ragforge.core.contracts import (
    FetchContextRequest,
    RetrievalEngine,
    RetrievalFilters,
    RetrieveRequest,
)
from ragforge.core.parse import load_document
from ragforge.core.scan import scan_corpus
from ragforge.core.sqlite import RetrievalError, SQLiteEngine, create_index

ROOT = Path(__file__).resolve().parents[1]


def mini_index(tmp_path: Path) -> Path:
    corpus = ROOT / "examples/mini-docs"
    report = scan_corpus(corpus, "mini")
    path = tmp_path / "index.sqlite"
    summary = create_index(
        path, "mini", "Mini", (load_document(corpus, "mini", r) for r in report.documents)
    )
    assert summary.document_count == 6
    assert summary.chunk_count == 21
    return path


def test_real_retrieval_is_repeatable_ranked_and_read_only(tmp_path: Path) -> None:
    path = mini_index(tmp_path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    engine: RetrievalEngine = SQLiteEngine(path)
    query = RetrieveRequest(query="rollback", collection_id="mini", top_k=10)
    first = engine.retrieve(query)
    assert first == engine.retrieve(query)
    assert first.results[0].source.path == "transactions.md"
    assert "rollback" in first.results[0].text.lower()
    assert all(r.retrieval_method == "bm25" for r in first.results)
    assert [(r.rank_score, r.chunk_id) for r in first.results] == sorted(
        [(r.rank_score, r.chunk_id) for r in first.results], key=lambda pair: (-pair[0], pair[1])
    )
    assert all(r.source.line_start is not None for r in first.results)
    assert engine.list_collections()[0].chunk_count == 21
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert not Path(str(path) + "-wal").exists()
    assert not Path(str(path) + "-shm").exists()


@pytest.mark.parametrize(
    "query",
    [
        "O'Reilly",
        'x" OR 1=1 --',
        "NEAR(x y)",
        "NOT AND OR",
        "ћирилица",
        "документација",
        "čćžšđ",
        "***",
        "https://host/x?a=b",
        "rollback); DROP TABLE chunks;--",
    ],
)
def test_ordinary_query_never_executes_fts_or_sql_operators(tmp_path: Path, query: str) -> None:
    path = mini_index(tmp_path)
    engine = SQLiteEngine(path)
    engine.retrieve(RetrieveRequest(query=query))
    assert engine.list_collections()[0].document_count == 6


def test_filters_collection_and_output_budgets_are_enforced(tmp_path: Path) -> None:
    engine = SQLiteEngine(mini_index(tmp_path))
    response = engine.retrieve(RetrieveRequest(query="token rollback", top_k=10))
    wanted = response.results[0].document_id
    filtered = engine.retrieve(
        RetrieveRequest(query="token rollback", filters=RetrievalFilters(document_ids=[wanted]))
    )
    assert filtered.results
    assert all(r.document_id == wanted for r in filtered.results)
    with pytest.raises(RetrievalError, match="unknown collection"):
        engine.retrieve(RetrieveRequest(query="rollback", collection_id="other"))
    with pytest.raises(RetrievalError, match="max_output_chars"):
        engine.retrieve(RetrieveRequest(query="rollback", max_output_chars=1))
    with pytest.raises(RetrievalError, match="only bm25"):
        engine.retrieve(RetrieveRequest(query="rollback", search_method="hybrid"))
    with pytest.raises(RetrievalError, match="64 literal"):
        engine.retrieve(RetrieveRequest(query=" ".join(f"word{i}" for i in range(65))))
    assert not engine.retrieve(RetrieveRequest(query="***")).results


def test_context_stays_in_exact_document_and_always_includes_anchor(tmp_path: Path) -> None:
    engine = SQLiteEngine(mini_index(tmp_path))
    anchor = engine.retrieve(RetrieveRequest(query="savepoint")).results[0]
    context = engine.fetch_context(
        FetchContextRequest(collection_id="mini", chunk_id=anchor.chunk_id, neighbors=5)
    )
    assert anchor.chunk_id in {r.chunk_id for r in context.results}
    assert all(r.document_id == anchor.document_id for r in context.results)
    assert [r.chunk_id for r in context.results] == sorted(r.chunk_id for r in context.results)
    assert all(r.rank_score == 0 for r in context.results)
    with pytest.raises(RetrievalError, match="unknown chunk"):
        engine.fetch_context(FetchContextRequest(collection_id="mini", chunk_id="a" * 64))
    with pytest.raises(RetrievalError, match="max_output_chars"):
        engine.fetch_context(
            FetchContextRequest(collection_id="mini", chunk_id=anchor.chunk_id, max_output_chars=1)
        )


def test_empty_and_missing_indexes_have_explicit_behavior(tmp_path: Path) -> None:
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(RetrievalError):
        SQLiteEngine(missing)
    assert not missing.exists()
    empty = tmp_path / "empty.sqlite"
    create_index(empty, "mini", "Empty", [])
    engine = SQLiteEngine(empty)
    assert engine.list_collections()[0].document_count == 0
    assert not engine.retrieve(RetrieveRequest(query="anything")).results
    with sqlite3.connect(empty) as connection:
        connection.execute("PRAGMA user_version=999")
    with pytest.raises(RetrievalError, match="schema version"):
        SQLiteEngine(empty)


def test_failed_new_index_is_removed_and_existing_index_preserved(tmp_path: Path) -> None:
    path = mini_index(tmp_path)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        create_index(path, "mini", "Do not overwrite", [])
    assert path.read_bytes() == before
    failed = tmp_path / "failed.sqlite"

    def broken():
        raise ValueError("fixture parser failed")
        yield

    with pytest.raises(ValueError, match="fixture parser failed"):
        create_index(failed, "mini", "Failed", broken())
    assert not failed.exists()


def test_pdf_retrieval_retains_physical_page_and_incomplete_requires_choice(tmp_path: Path) -> None:
    corpus = ROOT / "tests/fixtures/pdf"
    report = scan_corpus(corpus, "pdf")
    structured = next(r for r in report.documents if r.source_path == "structured.pdf")
    document = load_document(corpus, "pdf", structured)
    database = tmp_path / "pdf.sqlite"
    create_index(database, "pdf", "PDF", [document])
    found = SQLiteEngine(database).retrieve(RetrieveRequest(query="authentication"))
    assert found.results[0].source.page == 2
    assert found.results[0].source.line_start is None
    mixed = load_document(
        corpus, "pdf", next(r for r in report.documents if r.source_path == "mixed.pdf")
    )
    with pytest.raises(RetrievalError, match="incomplete PDF"):
        create_index(tmp_path / "mixed.sqlite", "pdf", "Mixed", [mixed])
    assert not (tmp_path / "mixed.sqlite").exists()
    summary = create_index(
        tmp_path / "mixed.sqlite", "pdf", "Mixed", [mixed], allow_incomplete=True
    )
    assert summary.incomplete_document_count == 1


def test_large_overlap_index_budget_fails_cleanly(tmp_path: Path) -> None:
    corpus = ROOT / "examples/mini-docs"
    report = scan_corpus(corpus, "mini")
    doc = load_document(corpus, "mini", report.documents[0])
    failed = tmp_path / "budget.sqlite"
    with pytest.raises(ValueError, match="max_output_chars"):
        create_index(
            failed,
            "mini",
            "Budget",
            [doc],
            ChunkConfig(chunk_size_chars=100, overlap_chars=99),
            max_output_chars=150,
        )
    assert not failed.exists()


def test_cli_index_search_context_are_real_and_json(tmp_path: Path) -> None:
    runner = CliRunner()
    database = tmp_path / "cli.sqlite"
    indexed = runner.invoke(
        app, ["index", str(ROOT / "examples/mini-docs"), str(database), "--collection", "mini"]
    )
    assert indexed.exit_code == 0, indexed.output
    assert json.loads(indexed.stdout)["chunk_count"] == 21
    searched = runner.invoke(app, ["search", str(database), "rollback"])
    assert searched.exit_code == 0, searched.output
    result = json.loads(searched.stdout)["results"][0]
    assert result["source"]["path"] == "transactions.md"
    context = runner.invoke(
        app, ["context", str(database), result["chunk_id"], "--collection", "mini"]
    )
    assert context.exit_code == 0, context.output
    assert json.loads(context.stdout)["results"]
    rejected = runner.invoke(app, ["search", str(database), "rollback", "--search-method", "dense"])
    assert rejected.exit_code == 2
    assert rejected.stdout == ""
    assert "only bm25" in json.loads(rejected.stderr)["error"]


def test_offline_cli_builds_and_queries_mixed_md_pdf_on_relocated_path(
    tmp_path: Path, offline_cli: Callable[[list[str]], subprocess.CompletedProcess[str]]
) -> None:
    corpus = tmp_path / "mixed corpus"
    corpus.mkdir()
    (corpus / "srpski.md").write_text("# Подаци\nЋирилица и čuvanje података.\n", encoding="utf-8")
    shutil.copyfile(ROOT / "tests/fixtures/pdf/structured.pdf", corpus / "reference.pdf")
    database = tmp_path / "with spaces" / "original.sqlite"
    built = offline_cli(["index", str(corpus), str(database), "--collection", "mixed"])
    assert built.returncode == 0, built.stderr
    assert json.loads(built.stdout)["document_count"] == 2
    copied = tmp_path / "relocated.sqlite"
    shutil.copyfile(database, copied)
    found = offline_cli(["search", str(copied), "authentication", "--collection", "mixed"])
    assert found.returncode == 0, found.stderr
    hit = json.loads(found.stdout)["results"][0]
    assert hit["source"]["path"] == "reference.pdf"
    assert hit["source"]["page"] == 2
    context = offline_cli(["context", str(copied), hit["chunk_id"], "--collection", "mixed"])
    assert context.returncode == 0, context.stderr
    assert hit["chunk_id"] in {r["chunk_id"] for r in json.loads(context.stdout)["results"]}
    unicode = offline_cli(["search", str(copied), "ћирилица čuvanje"])
    assert unicode.returncode == 0, unicode.stderr
    assert json.loads(unicode.stdout)["results"][0]["source"]["path"] == "srpski.md"
