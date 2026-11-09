"""Corpus-only acronym candidates bound to actual indexed source quotes."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter
from collections.abc import Iterator
from contextlib import closing, contextmanager
from itertools import islice
from pathlib import Path

from ragforge.core.source import is_link
from ragforge.core.sqlite import RetrievalError, SQLiteEngine
from ragforge.jobs.budget import StorageBudget

FORMAT = "source-definitions-v1"
APPLICATION_ID = 0x52464431
MAX_BYTES = 256 * 1024**2
MAX_PROOFS = 180000
MAX_MEANINGS = 180000
MAX_SHORT_FORMS = 16384
PARENTHETICAL = re.compile(r"\(([A-Za-z][A-Za-z0-9/-]{1,15})\)")
LINE_PAIR = re.compile(
    r"(?m)^[ \t]{0,4}([A-Za-z][A-Za-z0-9/-]{1,15})[ \t]+"
    r"([A-Za-z][A-Za-z0-9 ,/\x27-]{2,130})[ \t]*$"
)
EXCLUDED = {
    "NOTE",
    "AND",
    "THE",
    "FOR",
    "MUST",
    "SHALL",
    "TRUE",
    "FALSE",
    "NULL",
    "VOID",
    "SEE",
    "TABLE",
    "FIGURE",
}
SCHEMA = """
PRAGMA journal_mode=DELETE;
PRAGMA synchronous=FULL;
PRAGMA application_id=1380336689;
PRAGMA user_version=1;
CREATE TABLE meanings(short TEXT,meaning TEXT,long_form TEXT,occurrences INTEGER NOT NULL,
    PRIMARY KEY(short,meaning));
CREATE TABLE definitions(short TEXT,meaning TEXT,chunk_id TEXT,document_id TEXT,family TEXT,
    source_json TEXT,quote TEXT,PRIMARY KEY(short,meaning,chunk_id));
CREATE TABLE progress(id INTEGER PRIMARY KEY,last_rowid INTEGER);
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
"""
EXPECTED_TABLES = {
    match[1]: " ".join(match[0].rstrip(";").split()).casefold()
    for match in re.finditer(r"CREATE TABLE (\w+)\(.*?\);", SCHEMA, re.S)
}


def meaning_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def source_family(path: str) -> str:
    return (
        re.sub(r"v\d+p\.pdf$", "", Path(path).name.casefold())
        if path.casefold().endswith(".pdf")
        else path
    )


def _valid_short(value: str) -> bool:
    return value not in EXCLUDED and (
        sum(c.isupper() for c in value) >= 2 or any(c.isdigit() for c in value)
    )


def _align(short: str, long: str) -> tuple[int, str] | None:
    letters = "".join(c.casefold() for c in short if c.isalnum())
    at = len(long) - 1
    for index in range(len(letters) - 1, -1, -1):
        char = letters[index]
        while at >= 0 and (
            long[at].casefold() != char or (index == 0 and at > 0 and long[at - 1].isalnum())
        ):
            at -= 1
        if at < 0:
            return None
        if index:
            at -= 1
    value = long[at:].strip()
    if (
        not 3 <= len(value) <= 140
        or any(c in value for c in ":;!?=<>[]()")
        or len(value.split()) > min(len(letters) + 5, len(letters) * 2)
        or meaning_key(value) == letters
    ):
        return None
    return at, value


def extract_definitions(text: str) -> Iterator[tuple[str, str, str]]:
    """Extract bounded literal candidates, never certify the meaning as an answer."""
    for match in islice(PARENTHETICAL.finditer(text), 64):
        short = match[1]
        if not _valid_short(short):
            continue
        begin = max(0, match.start() - 200)
        result = _align(short, text[begin : match.start()].rstrip())
        if result:
            start, long = result
            yield short, long, text[begin + start : match.end()]
    for match in islice(LINE_PAIR.finditer(text), 64):
        short, long = match[1], match[2].strip()
        if not _valid_short(short):
            continue
        result = _align(short, long)
        if result and result[0] == 0:
            yield short, long, match[0].strip()


def _metadata(index_sha256: str, collection_id: str) -> dict[str, str]:
    if not re.fullmatch(r"[0-9a-f]{64}", index_sha256):
        raise ValueError("invalid source-index checksum")
    return {"format": FORMAT, "index_sha256": index_sha256, "collection_id": collection_id}


@contextmanager
def _catalogue_connection(
    path: Path, index_sha256: str, collection_id: str
) -> Iterator[sqlite3.Connection]:
    if is_link(path.lstat()) or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise RetrievalError("unsafe or oversized source-definition catalogue")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 2_000_000)
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        if (
            db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
            or db.execute("PRAGMA user_version").fetchone()[0] != 1
        ):
            raise RetrievalError("unsupported source-definition catalogue format")
        names = set()
        for row in db.execute("SELECT type,name,sql FROM sqlite_master"):
            if (
                row["type"] == "index"
                and row["name"]
                in {
                    "sqlite_autoindex_meanings_1",
                    "sqlite_autoindex_definitions_1",
                    "sqlite_autoindex_metadata_1",
                }
                and row["sql"] is None
            ):
                continue
            if row["type"] != "table" or row["name"] not in {
                "meanings",
                "definitions",
                "progress",
                "metadata",
            }:
                raise RetrievalError("unexpected catalogue schema component")
            if " ".join(str(row["sql"]).split()).casefold() != EXPECTED_TABLES[row["name"]]:
                raise RetrievalError("unexpected catalogue table schema")
            names.add(row["name"])
        if names != {"meanings", "definitions", "progress", "metadata"}:
            raise RetrievalError("incomplete catalogue schema")
        if dict(db.execute("SELECT key,value FROM metadata")) != _metadata(
            index_sha256, collection_id
        ):
            raise RetrievalError("source-definition catalogue belongs to another index")
        yield db


@contextmanager
def catalogue_connection(
    path: Path, index_sha256: str, collection_id: str
) -> Iterator[sqlite3.Connection]:
    try:
        with _catalogue_connection(path, index_sha256, collection_id) as db:
            yield db
    except sqlite3.Error as error:
        raise RetrievalError("cannot use source-definition catalogue") from error


def verify_catalogue(
    path: Path, index: SQLiteEngine, index_sha256: str, collection_id: str
) -> None:
    """Verify every retained relation against its actual physical source chunk."""
    with catalogue_connection(path, index_sha256, collection_id) as db, index._connect() as source:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RetrievalError("source-definition catalogue quick_check failed")
        if db.execute("SELECT count(*) FROM definitions").fetchone()[0] > MAX_PROOFS:
            raise RetrievalError("source-definition proof budget exceeded")
        if db.execute("SELECT count(*) FROM meanings").fetchone()[0] > MAX_MEANINGS:
            raise RetrievalError("source-definition meaning budget exceeded")
        if (
            db.execute("SELECT count(DISTINCT short) FROM definitions").fetchone()[0]
            > MAX_SHORT_FORMS
        ):
            raise RetrievalError("source-definition short-form budget exceeded")
        for row in db.execute("SELECT * FROM meanings"):
            if (
                not isinstance(row["long_form"], str)
                or not 3 <= len(row["long_form"]) <= 140
                or meaning_key(row["long_form"]) != row["meaning"]
                or not isinstance(row["occurrences"], int)
                or row["occurrences"] < 1
            ):
                raise RetrievalError("invalid source-definition meaning")
        for proof in db.execute("SELECT * FROM definitions"):
            row = source.execute(
                "SELECT * FROM chunks WHERE collection_id=? AND chunk_id=?",
                (collection_id, proof["chunk_id"]),
            ).fetchone()
            if (
                row is None
                or row["document_id"] != proof["document_id"]
                or json.loads(row["source_json"]) != json.loads(proof["source_json"])
                or source_family(json.loads(row["source_json"])["path"]) != proof["family"]
                or (proof["short"], proof["meaning"], proof["quote"])
                not in {
                    (s.casefold(), meaning_key(long), quote)
                    for s, long, quote in extract_definitions(row["text"])
                }
                or db.execute(
                    "SELECT 1 FROM meanings WHERE short=? AND meaning=?",
                    (proof["short"], proof["meaning"]),
                ).fetchone()
                is None
            ):
                raise RetrievalError("source-definition proof differs from indexed source")


def build_catalogue(
    index: SQLiteEngine,
    output: Path,
    index_sha256: str,
    collection_id: str,
    *,
    storage: StorageBudget | None = None,
) -> dict[str, int | bool]:
    """Scan only the immutable corpus. No queries, answers or model inference are inputs."""
    expected_metadata = _metadata(index_sha256, collection_id)
    output = output.absolute()
    if storage:
        if not output.resolve().is_relative_to(storage.root):
            raise ValueError("catalogue must remain inside storage budget")
        storage.check(MAX_BYTES + 16 * 1024**2, refresh=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    owned = output.lstat()
    processed = retained = 0
    stored: Counter[tuple[str, str]] = Counter()
    families: set[tuple[str, str, str]] = set()
    meanings: set[tuple[str, str]] = set()
    shorts: set[str] = set()
    updates: dict[tuple[str, str], tuple[str, int]] = {}
    previous_size = 0
    try:
        with closing(sqlite3.connect(output)) as db, index._connect() as source:
            index._collection(source, collection_id)
            db.executescript(SCHEMA)

            def checkpoint(rowid: int) -> None:
                nonlocal previous_size
                with db:
                    db.executemany(
                        "INSERT INTO meanings VALUES(?,?,?,?) ON CONFLICT(short,meaning) "
                        "DO UPDATE SET occurrences=occurrences+excluded.occurrences",
                        [(s, k, value, count) for (s, k), (value, count) in updates.items()],
                    )
                    db.execute("INSERT OR REPLACE INTO progress VALUES(1,?)", (rowid,))
                updates.clear()
                size = output.stat().st_size
                if size > MAX_BYTES:
                    raise ValueError("source-definition catalogue byte budget exceeded")
                if storage:
                    storage.account(max(0, size - previous_size))
                    storage.check(16 * 1024**2)
                previous_size = size

            last = 0
            for row in source.execute(
                "SELECT rowid,chunk_id,document_id,text,source_json FROM chunks "
                "WHERE collection_id=? ORDER BY rowid",
                (collection_id,),
            ):
                found = set()
                for short, long, quote in extract_definitions(row["text"]):
                    short = short.casefold()
                    meaning = meaning_key(long)
                    key = (short, meaning)
                    if not meaning or key in found:
                        continue
                    found.add(key)
                    meanings.add(key)
                    shorts.add(short)
                    if len(meanings) > MAX_MEANINGS or len(shorts) > MAX_SHORT_FORMS:
                        raise ValueError("source-definition vocabulary budget exceeded")
                    first, count = updates.get(key, (long, 0))
                    updates[key] = (first, count + 1)
                    if stored[key] >= 4 or retained >= MAX_PROOFS:
                        continue
                    family = source_family(json.loads(row["source_json"])["path"])
                    if (short, meaning, family) in families:
                        continue
                    db.execute(
                        "INSERT INTO definitions VALUES(?,?,?,?,?,?,?)",
                        (
                            short,
                            meaning,
                            row["chunk_id"],
                            row["document_id"],
                            family,
                            row["source_json"],
                            quote,
                        ),
                    )
                    stored[key] += 1
                    retained += 1
                    families.add((short, meaning, family))
                processed += 1
                last = row["rowid"]
                if processed % 10000 == 0:
                    checkpoint(last)
            checkpoint(last)
            with db:
                db.executemany("INSERT INTO metadata VALUES(?,?)", expected_metadata.items())
        return {
            "source_chunks_scanned": processed,
            "retained_source_proofs": retained,
            "distinct_short_forms": len(shorts),
            "distinct_meanings": len(meanings),
            "retained_cap_reached": retained >= MAX_PROOFS,
            "neural_inference_calls": 0,
            "benchmark_inputs_read": 0,
        }
    except BaseException:
        current = output.lstat() if output.exists() else None
        if current and (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino):
            output.unlink()
        raise
