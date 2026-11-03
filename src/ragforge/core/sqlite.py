"""Standalone development SQLite/FTS5 index; bundle verification comes in RF-004."""

import json
import os
import re
import sqlite3
import stat
import unicodedata
from collections.abc import Callable, Iterable, Iterator
from contextlib import closing, contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from ragforge.core.chunk import ChunkConfig, iter_chunks
from ragforge.core.contracts import (
    CollectionDescription,
    FetchContextRequest,
    RetrievalResponse,
    RetrievedChunk,
    RetrieveRequest,
    SourceLocation,
)
from ragforge.core.identity import document_id
from ragforge.core.parse import ParsedDocument
from ragforge.types import ContractModel, SearchMethod

APPLICATION_ID = 0x52464731
SCHEMA_VERSION = 1
# Bound rowid probes; broad grants keep the FTS-first plan.
FILTER_ROW_PROBE_LIMIT = 4096
SCHEMA = """
PRAGMA foreign_keys=ON;
PRAGMA journal_mode=DELETE;
PRAGMA synchronous=FULL;
PRAGMA application_id=1380337457;
PRAGMA user_version=1;
CREATE TABLE collections(collection_id TEXT PRIMARY KEY, title TEXT NOT NULL);
CREATE TABLE documents(
    document_id TEXT PRIMARY KEY, collection_id TEXT NOT NULL REFERENCES collections,
    source_path TEXT NOT NULL UNIQUE, content_sha256 TEXT NOT NULL,
    parser_version TEXT NOT NULL, warnings_json TEXT NOT NULL, pages_json TEXT NOT NULL
);
CREATE TABLE chunks(
    rowid INTEGER PRIMARY KEY, collection_id TEXT NOT NULL REFERENCES collections,
    document_id TEXT NOT NULL REFERENCES documents, chunk_id TEXT NOT NULL UNIQUE,
    ordinal INTEGER NOT NULL, text TEXT NOT NULL, source_json TEXT NOT NULL,
    UNIQUE(document_id, ordinal)
);
CREATE VIRTUAL TABLE chunk_fts USING fts5(
    text, content='chunks', content_rowid='rowid', tokenize='unicode61 remove_diacritics 2'
);
"""


class RetrievalError(ValueError):
    pass


class IndexSummary(ContractModel):
    collection_id: str
    document_count: Annotated[int, Field(ge=0)]
    chunk_count: Annotated[int, Field(ge=0)]
    incomplete_document_count: Annotated[int, Field(ge=0)]


def create_index(
    path: Path,
    collection_id: str,
    title: str,
    documents: Iterable[ParsedDocument],
    config: ChunkConfig | None = None,
    *,
    allow_incomplete: bool = False,
    token_counter: Callable[[str], int] | None = None,
    max_chunks: int = 100000,
    max_output_chars: int = 100000000,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> IndexSummary:
    """Create a new owned database. Existing files are never overwritten.

    A failed new index is removed; this is not an atomic portable bundle build.
    Sources must have passed load_document's byte/provenance verification.
    """
    CollectionDescription(collection_id=collection_id, title=title, document_count=0, chunk_count=0)
    if type(max_chunks) is not int or max_chunks < 1:
        raise RetrievalError("max_chunks must be a positive integer")
    if type(max_output_chars) is not int or max_output_chars < 1:
        raise RetrievalError("max_output_chars must be a positive integer")
    config = config or ChunkConfig()
    path = path.absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    owned = path.lstat()
    document_count = chunk_count = incomplete_count = text_chars = 0
    try:
        with closing(sqlite3.connect(path)) as connection:
            connection.executescript(SCHEMA)
            with connection:
                connection.execute("INSERT INTO collections VALUES (?, ?)", (collection_id, title))
                for document in documents:
                    if document.collection_id != collection_id:
                        raise RetrievalError("document belongs to another collection")
                    if document.record.document_id != document_id(
                        collection_id, document.record.source_path
                    ):
                        raise RetrievalError("invalid document identity")
                    incomplete = (
                        any(r.status != "extracted" for r in document.page_reports)
                        or document.parser_version == "parse-failed-v1"
                    )
                    if incomplete and not allow_incomplete:
                        raise RetrievalError(
                            "failed source requires explicit allow_incomplete"
                            if document.parser_version == "parse-failed-v1"
                            else "incomplete PDF requires explicit allow_incomplete"
                        )
                    if document.blocks and (
                        chunk_count >= max_chunks or text_chars >= max_output_chars
                    ):
                        raise RetrievalError("index chunk/text budget exceeded")
                    parts = (
                        iter_chunks(
                            document,
                            config,
                            token_counter=token_counter,
                            max_chunks=max_chunks - chunk_count,
                            max_output_chars=max_output_chars - text_chars,
                        )
                        if document.blocks
                        else iter(())
                    )
                    connection.execute(
                        "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            document.record.document_id,
                            collection_id,
                            document.record.source_path,
                            document.record.content_sha256,
                            document.parser_version,
                            json.dumps(document.warnings),
                            json.dumps([asdict(r) for r in document.page_reports]),
                        ),
                    )
                    for part in parts:
                        cursor = connection.execute(
                            "INSERT INTO chunks(collection_id,document_id,chunk_id,"
                            "ordinal,text,source_json) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                collection_id,
                                part.document_id,
                                part.chunk_id,
                                part.ordinal,
                                part.text,
                                part.source.model_dump_json(),
                            ),
                        )
                        connection.execute(
                            "INSERT INTO chunk_fts(rowid,text) VALUES (?,?)",
                            (cursor.lastrowid, part.text),
                        )
                        text_chars += len(part.text)
                        chunk_count += 1
                    document_count += 1
                    incomplete_count += int(incomplete)
                    if progress:
                        progress(
                            {
                                "phase": "index",
                                "completed_documents": document_count,
                                "chunks": chunk_count,
                                "text_chars": text_chars,
                            }
                        )
                connection.execute("INSERT INTO chunk_fts(chunk_fts) VALUES('optimize')")
        return IndexSummary(
            collection_id=collection_id,
            document_count=document_count,
            chunk_count=chunk_count,
            incomplete_document_count=incomplete_count,
        )
    except BaseException:
        # Remove only the regular file created by this call, after closing SQLite.
        current = path.lstat()
        if stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == (
            owned.st_dev,
            owned.st_ino,
        ):
            path.unlink()
        raise


def plain_query(query: str) -> str | None:
    """Literal Unicode alphanumeric terms with OR; never expose raw FTS syntax."""
    terms = list(dict.fromkeys(re.findall(r"[^\W_]+", unicodedata.normalize("NFC", query))))
    if len(terms) > 64:
        raise RetrievalError("query exceeds 64 literal terms")
    return " OR ".join('"' + term + '"' for term in terms) or None


class SQLiteEngine:
    """One read-only local lexical engine, shared by all future adapters."""

    def __init__(self, database: Path) -> None:
        self.database = database.absolute()
        with self._connect():
            pass

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        try:
            if not stat.S_ISREG(self.database.lstat().st_mode):
                raise RetrievalError("index must be a regular file, not a symlink")
            with closing(
                sqlite3.connect(self.database.resolve().as_uri() + "?mode=ro", uri=True)
            ) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only=ON")
                connection.execute("PRAGMA trusted_schema=OFF")
                connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 2000000)
                if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                    raise RetrievalError("not a RAGForge development index")
                if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                    raise RetrievalError("unsupported SQLite index schema version")
                if connection.execute("SELECT count(*) FROM collections").fetchone()[0] != 1:
                    raise RetrievalError("index must contain exactly one collection")
                yield connection
        except (OSError, sqlite3.Error) as error:
            raise RetrievalError(f"cannot use SQLite index: {error}") from error

    @staticmethod
    def _collection(connection: sqlite3.Connection, requested: str | None) -> str:
        collection: str = connection.execute("SELECT collection_id FROM collections").fetchone()[0]
        if requested is not None and requested != collection:
            raise RetrievalError("unknown collection")
        return collection

    @staticmethod
    def _chunk(row: sqlite3.Row, score: float, method: SearchMethod = "bm25") -> RetrievedChunk:
        return RetrievedChunk(
            collection_id=row["collection_id"],
            document_id=row["document_id"],
            chunk_id=row["chunk_id"],
            text=row["text"],
            source=SourceLocation.model_validate_json(row["source_json"]),
            rank_score=score,
            retrieval_method=method,
        )

    def list_collections(self) -> list[CollectionDescription]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT collection_id,title,(SELECT count(*) FROM documents) AS document_count,"
                "(SELECT count(*) FROM chunks) AS chunk_count FROM collections"
            ).fetchone()
            return [CollectionDescription.model_validate(dict(row))]

    def rank_bm25(self, request: RetrieveRequest, limit: int) -> list[tuple[str, float]]:
        return self._rank_expression(request, limit, plain_query(request.query))

    def rank_focused_bm25(self, request: RetrieveRequest, limit: int) -> list[tuple[str, float]]:
        """Experimental literal branch requiring explicit, uncommon technical names.

        No reference labels, acronym dictionary or generated query terms are used.
        The ordinary BM25 baseline remains unchanged.
        """
        if not 1 <= limit <= 200:
            raise RetrievalError("candidate limit must be between 1 and 200")
        plain_query(request.query)  # Apply the same literal-term limit.
        terms = list(
            dict.fromkeys(re.findall(r"[^\W_]+", unicodedata.normalize("NFC", request.query)))
        )
        anchors = []
        with self._connect() as connection:
            self._collection(connection, request.collection_id)
            total = connection.execute("SELECT count(*) FROM chunks").fetchone()[0]
            for term in terms:
                if sum(char.isupper() for char in term) < 2:
                    continue
                count = connection.execute(
                    "SELECT count(*) FROM chunk_fts WHERE chunk_fts MATCH ?", ('"' + term + '"',)
                ).fetchone()[0]
                if 0 < count <= total * 0.05:
                    anchors.append(term)
            if not anchors or len(anchors) > 3:
                return []
        stop = set(
            (
                "a an the what which how does do is are can must should may be to of for "
                "in on at by with and or both from under use using"
            ).split()
        )
        body = [term for term in terms if term not in anchors and term.lower() not in stop]
        expression = " AND ".join('"' + term + '"' for term in anchors)
        if body:
            expression += " AND (" + " OR ".join('"' + term + '"' for term in body) + ")"
        return self._rank_expression(request, limit, expression)

    def _rank_expression(
        self, request: RetrieveRequest, limit: int, query: str | None
    ) -> list[tuple[str, float]]:
        if not 1 <= limit <= 200:
            raise RetrievalError("candidate limit must be between 1 and 200")
        with self._connect() as connection:
            collection = self._collection(connection, request.collection_id)
            if query is None:
                return []
            if request.filters is None:
                # FTS5's rank cursor can stop before materializing every matching
                # row. Consume the complete boundary tie to retain chunk_id order.
                best: list[tuple[str, float]] = []
                cursor = connection.execute(
                    "SELECT rowid,rank FROM chunk_fts WHERE chunk_fts MATCH ? "
                    "AND rank MATCH 'bm25()' ORDER BY rank",
                    (query,),
                )
                for match in cursor:
                    score = -float(match["rank"])
                    if len(best) == limit and score < best[-1][1]:
                        break
                    row = connection.execute(
                        "SELECT chunk_id,collection_id FROM chunks WHERE rowid=?", (match["rowid"],)
                    ).fetchone()
                    if row is None or row["collection_id"] != collection:
                        continue
                    best = sorted(
                        best + [(str(row["chunk_id"]), score)], key=lambda item: (-item[1], item[0])
                    )[:limit]
                return best
            ids = request.filters.document_ids
            placeholders = ",".join("?" for _ in ids)
            scope = "c.collection_id=? AND c.document_id IN (" + placeholders + ")"
            # Counting is bounded and uses the (document_id, ordinal) index.
            # A narrow grant can otherwise scan millions of global FTS hits.
            scoped_rows = connection.execute(
                "SELECT count(*) FROM (SELECT 1 FROM chunks c WHERE " + scope + " LIMIT ?)",
                [collection, *ids, FILTER_ROW_PROBE_LIMIT + 1],
            ).fetchone()[0]
            if scoped_rows <= FILTER_ROW_PROBE_LIMIT:
                # CROSS JOIN fixes the loop order: probe MATCH at each allowed
                # rowid. bm25 still uses the complete corpus statistics.
                sql = (
                    "SELECT c.chunk_id,-bm25(chunk_fts) AS score "
                    "FROM chunks c CROSS JOIN chunk_fts WHERE "
                    + scope
                    + " AND chunk_fts.rowid=c.rowid AND chunk_fts MATCH ?"
                )
                params: list[str | int] = [collection, *ids, query]
            else:
                sql = (
                    "SELECT c.chunk_id,-bm25(chunk_fts) AS score FROM chunk_fts "
                    "JOIN chunks c ON c.rowid=chunk_fts.rowid WHERE chunk_fts MATCH ? AND " + scope
                )
                params = [query, collection, *ids]
            sql += " ORDER BY score DESC,c.chunk_id ASC LIMIT ?"
            params.append(limit)
            return [
                (str(row["chunk_id"]), float(row["score"]))
                for row in connection.execute(sql, params)
            ]

    def ranked_response(
        self, ranks: list[tuple[str, float]], request: RetrieveRequest, method: SearchMethod
    ) -> RetrievalResponse:
        with self._connect() as connection:
            collection = self._collection(connection, request.collection_id)
            results: list[RetrievedChunk] = []
            remaining = request.max_output_chars
            for chunk_id, score in ranks:
                row = connection.execute(
                    "SELECT * FROM chunks WHERE collection_id=? AND chunk_id=?",
                    (collection, chunk_id),
                ).fetchone()
                if row is None:
                    raise RetrievalError("ranked chunk is missing from collection")
                if len(row["text"]) > remaining:
                    if not results:
                        raise RetrievalError(
                            "max_output_chars is too small for the highest ranked chunk"
                        )
                    break
                results.append(self._chunk(row, score, method))
                remaining -= len(row["text"])
            return RetrievalResponse(contract_version="1", results=results)

    def retrieve(self, request: RetrieveRequest) -> RetrievalResponse:
        if request.search_method not in (None, "bm25"):
            raise RetrievalError(
                "standalone SQLite index supports only bm25; no dense/hybrid fallback"
            )
        return self.ranked_response(self.rank_bm25(request, request.top_k), request, "bm25")

    def fetch_context(self, request: FetchContextRequest) -> RetrievalResponse:
        with self._connect() as connection:
            collection = self._collection(connection, request.collection_id)
            anchor = connection.execute(
                "SELECT * FROM chunks WHERE collection_id=? AND chunk_id=?",
                (collection, request.chunk_id),
            ).fetchone()
            if anchor is None:
                raise RetrievalError("unknown chunk in collection")
            if len(anchor["text"]) > request.max_output_chars:
                raise RetrievalError("max_output_chars is too small for the anchor chunk")
            rows = connection.execute(
                "SELECT * FROM chunks WHERE collection_id=? AND document_id=? "
                "AND ordinal BETWEEN ? AND ? ORDER BY abs(ordinal-?),chunk_id",
                (
                    collection,
                    anchor["document_id"],
                    anchor["ordinal"] - request.neighbors,
                    anchor["ordinal"] + request.neighbors,
                    anchor["ordinal"],
                ),
            ).fetchall()
            selected: list[RetrievedChunk] = []
            remaining = request.max_output_chars
            for row in rows:
                if len(row["text"]) <= remaining:
                    selected.append(self._chunk(row, 0.0))
                    remaining -= len(row["text"])
            # Context is unranked: zero scores, stable contract tie order.
            return RetrievalResponse(
                contract_version="1", results=sorted(selected, key=lambda chunk: chunk.chunk_id)
            )
