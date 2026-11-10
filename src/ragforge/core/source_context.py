"""Bounded source context after retrieval; no extra neural inference or answer lookup."""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from ragforge.core.contracts import RetrievalResponse, RetrievedChunk, RetrieveRequest
from ragforge.core.definitions import catalogue_connection, source_family, verify_catalogue
from ragforge.core.sqlite import RetrievalError, SQLiteEngine
from ragforge.types import SearchMethod

STOP = set(
    "what which who how why when where does do is are was were will would should shall can could "
    "may must the a an of to for in on by from at with without and or be been being as if than "
    "then that this these those it its they their any all each one many much have has had there "
    "into over out up use used using called stand stands mean means meant done include includes "
    "included contain contains contained show shows shown provide provided provides perform "
    "performs performed purpose role example examples some another second first affected "
    "supported support supports".split()
)
VERSION = re.compile(r"\b(?:rel(?:ease)?[ -]*\d+|version|v\d+|\d+\.\d+\.\d+)\b", re.I)
DEFINITION = re.compile(
    r"\s*(?:what\s+(?:is|are)(?:\s+(?:the|a|an))?\s+"
    r"([A-Za-z][A-Za-z0-9/-]{1,15})(?:\s+short\s+for)?|"
    r"what\s+(?:does|do)\s+([A-Za-z][A-Za-z0-9/-]{1,15})\s+"
    r"(?:(?:stand|stands)\s+for|mean|means))"
    r"(?:\s+in\s+[A-Za-z0-9 /-]{1,60})?\s*[?.!]?\s*",
    re.I,
)


USAGE = re.compile(
    r"\s*(?:what\s+(?:is|are)(?:\s+(?:the|a|an))?\s+"
    r"([A-Za-z][A-Za-z0-9/-]{1,15})\s+(?:used\s+for|for)|"
    r"what\s+(?:does|do)\s+([A-Za-z][A-Za-z0-9/-]{1,15})\s+do|"
    r"what\s+(?:is|are)\s+the\s+(?:purpose|role|function|use|uses)\s+of\s+"
    r"(?:the\s+)?([A-Za-z][A-Za-z0-9/-]{1,15}))\s*[?.!]?\s*",
    re.I,
)


def definition_short(query: str) -> str | None:
    cleaned = re.sub(r"[\"\u201c\u201d']", "", query)
    match = DEFINITION.fullmatch(cleaned) or USAGE.fullmatch(cleaned)
    if match is None:
        return None
    value = next(value for value in match.groups() if value is not None)
    return (
        value.casefold()
        if (sum(c.isupper() for c in value) >= 2 or any(c.isdigit() for c in value))
        else None
    )


def one_edit(a: str, b: str) -> bool:
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b, strict=True)) == 1
    if len(a) > len(b):
        a, b = b, a
    at = 0
    while at < len(a) and a[at] == b[at]:
        at += 1
    return a[at:] == b[at + 1 :]


def information_key(chunk: RetrievedChunk, versioned: bool) -> tuple[str | None, ...]:
    text = " ".join(chunk.text.split())
    return (
        (
            chunk.document_id if versioned else source_family(chunk.source.path),
            chunk.source.section,
            text,
        )
        if len(text) >= 200
        else (chunk.chunk_id,)
    )


def _fts_word(word: str) -> str:
    value = word.casefold()
    if not word.isalpha() or word.isupper():
        return '"' + value.replace('"', '""') + '"'
    if word.isalpha() and not word.isupper():
        if len(value) > 5 and value.endswith("ies"):
            value = value[:-3] + "y"
        elif len(value) > 6 and value.endswith("ation"):
            value = value[:-5]
        elif len(value) > 6 and value.endswith("tion"):
            value = value[:-4]
        elif len(value) > 5 and value.endswith("ing"):
            value = value[:-3]
            if len(value) > 3 and value[-1] == value[-2]:
                value = value[:-1]
        elif len(value) > 4 and value.endswith("ed"):
            value = value[:-2]
            if len(value) > 3 and value[-1] == value[-2]:
                value = value[:-1]
        elif len(value) > 4 and value.endswith("s") and not value.endswith("ss"):
            value = value[:-1]
    if value.startswith("transmi"):
        value = "transmi"
    prefix = word.isalpha() and not word.isupper() and len(value) >= 4
    return '"' + value.replace('"', '""') + '"' + ("*" if prefix else "")


class SourceContext:
    """Source-proven candidate selection. Text definitions remain untrusted data."""

    def __init__(
        self,
        path: Path,
        index: SQLiteEngine,
        index_sha256: str,
        collection_id: str,
        *,
        verify: bool = True,
    ) -> None:
        if verify:
            verify_catalogue(path, index, index_sha256, collection_id)
        self.path = path
        self.index = index
        self.index_sha256 = index_sha256
        self.collection_id = collection_id

    def _entries(
        self, db: sqlite3.Connection, shorts: list[str], allowed: list[str] | None
    ) -> list[sqlite3.Row]:
        if not shorts:
            return []
        placeholders = ",".join("?" for _ in shorts)
        sql = (
            "SELECT d.*,m.long_form,m.occurrences FROM definitions d "
            "JOIN meanings m USING(short,meaning) WHERE d.short IN (" + placeholders + ")"
        )
        params = list(shorts)
        if allowed is not None:
            sql += " AND d.document_id IN (" + ",".join("?" for _ in allowed) + ")"
            params += allowed
        rows = db.execute(sql, params).fetchall()
        counts = Counter((r["short"], r["meaning"]) for r in rows)
        return sorted(
            rows,
            key=lambda r: (
                -int(r["occurrences"]) if allowed is None else -counts[r["short"], r["meaning"]],
                str(r["short"]),
                str(r["meaning"]),
                str(r["chunk_id"]),
            ),
        )

    def _actual(
        self, row: sqlite3.Row, db: sqlite3.Connection, allowed: list[str] | None
    ) -> sqlite3.Row:
        sql = "SELECT * FROM chunks WHERE collection_id=? AND chunk_id=?"
        params = [self.collection_id, str(row["chunk_id"])]
        if allowed is not None:
            sql += " AND document_id IN (" + ",".join("?" for _ in allowed) + ")"
            params += allowed
        actual: sqlite3.Row | None = db.execute(sql, params).fetchone()
        if (
            actual is None
            or actual["document_id"] != row["document_id"]
            or str(row["quote"]) not in actual["text"]
            or json.loads(actual["source_json"]) != json.loads(row["source_json"])
        ):
            raise RetrievalError("source-context candidate differs from allowed indexed source")
        return actual

    def _definitions(
        self,
        query: str,
        source: sqlite3.Connection,
        bank: sqlite3.Connection,
        method: SearchMethod,
        allowed: list[str] | None,
    ) -> list[RetrievedChunk]:
        short = definition_short(query)
        if short is None:
            return []
        # Most requests name an exact, authorized form. Avoid enumerating the
        # whole catalogue unless plural/typo matching is actually necessary.
        entries = self._entries(bank, [short], allowed)
        if entries:
            return self._definition_chunks(entries, source, method, allowed)
        sql = "SELECT DISTINCT short FROM definitions"
        params: list[str] = []
        if allowed is not None:
            sql += " WHERE document_id IN (" + ",".join("?" for _ in allowed) + ")"
            params += allowed
        shorts = [str(r[0]) for r in bank.execute(sql, params)]
        matches = [short] if short in shorts else []
        if not matches and short.endswith("s") and short[:-1] in shorts:
            matches = [short[:-1]]
        if not matches:
            typo = short[:-1] if short.endswith("s") else short
            matches = [s for s in shorts if one_edit(typo, s)]
        entries = self._entries(bank, matches, allowed)
        return self._definition_chunks(entries, source, method, allowed)

    def _definition_chunks(
        self,
        entries: list[sqlite3.Row],
        source: sqlite3.Connection,
        method: SearchMethod,
        allowed: list[str] | None,
    ) -> list[RetrievedChunk]:
        actual = {r["chunk_id"]: self._actual(r, source, allowed) for r in entries}
        scoped_counts = Counter((r["short"], r["meaning"]) for r in entries)
        entries.sort(
            key=lambda r: (
                -int(r["occurrences"])
                if allowed is None
                else -scoped_counts[r["short"], r["meaning"]],
                str(r["short"]),
                str(r["meaning"]),
                len(actual[r["chunk_id"]]["text"]),
                str(r["chunk_id"]),
            )
        )
        result = []
        seen_meanings = set()
        seen_chunks = set()
        for row in entries:
            key = (row["short"], row["meaning"])
            if key in seen_meanings or row["chunk_id"] in seen_chunks:
                continue
            result.append(self.index._chunk(actual[row["chunk_id"]], 0.0, method))
            seen_meanings.add(key)
            seen_chunks.add(row["chunk_id"])
            if len(result) == 16:
                break
        return result

    def _focused(
        self,
        query: str,
        source: sqlite3.Connection,
        bank: sqlite3.Connection,
        method: SearchMethod,
        allowed: list[str] | None,
    ) -> list[RetrievedChunk]:
        if definition_short(query) is not None:
            return []
        normalized = re.sub(r"\b((?:3G[_ -])?MSC)([ABC])\b", r"\1-\2", query, flags=re.I)
        words = re.findall(r"[A-Za-z0-9][A-Za-z0-9_/-]*", normalized)
        terms = list(dict.fromkeys(w for w in words if w.casefold() not in STOP and len(w) > 1))[:8]
        if len(terms) < 2:
            return []
        queries = [" AND ".join(_fts_word(w) for w in terms)]
        phrases = []
        for width in [3, 2]:
            for start in range(len(words) - width + 1):
                seq = words[start : start + width]
                if (
                    all(w.casefold() not in STOP and len(w) > 1 for w in seq)
                    and sum(len(w) for w in seq) >= 14
                ):
                    phrases.append('"' + " ".join(w.casefold() for w in seq) + '"')
        if phrases:
            queries.append(" OR ".join(dict.fromkeys(phrases[:3])))
        names = [w for w in terms if sum(c.isupper() for c in w) >= 2 and len(w) <= 5]
        if len(names) == 1:
            name = names[0]
            other = [w for w in terms if w != name][:2]
            entries = self._entries(bank, [name.casefold()], allowed)
            long_forms = list(dict.fromkeys(str(r["long_form"]) for r in entries))[:2]
            expanded = []
            for long_form in long_forms:
                long = " ".join(re.findall(r"[A-Za-z0-9]+", long_form))
                if long:
                    expanded.append(
                        '("'
                        + long.casefold()
                        + '" AND '
                        + " AND ".join(_fts_word(w) for w in other)
                        + ")"
                    )
            if expanded:
                queries.append(" OR ".join(expanded))
        purpose_question = bool(
            re.match(r"\s*what\s+(?:is|are)\s+the\s+(?:purpose|role|function)\s+of\b", query, re.I)
        )
        if purpose_question and len(terms) > 3 and len(names) == 1:
            focused_terms = [w for w in terms if w != names[0]][:3] + names
            queries = queries[:2] + [" AND ".join(_fts_word(w) for w in focused_terms)]
        elif len(queries) < 3 and len(terms) > 3:
            queries.append(" AND ".join(_fts_word(w) for w in terms[:3]))
        branches = []
        definition_question = bool(
            re.match(r"\s*(what\s+(is|are)|how\s+(many|much))\b", query, re.I)
        )
        for statement in list(dict.fromkeys(queries))[:3]:
            sql = (
                "SELECT c.*,bm25(chunk_fts) AS relevance FROM chunk_fts "
                "JOIN chunks c ON c.rowid=chunk_fts.rowid WHERE chunk_fts MATCH ? "
                "AND c.collection_id=?"
            )
            params = [statement, self.collection_id]
            if allowed is not None:
                sql += " AND c.document_id IN (" + ",".join("?" for _ in allowed) + ")"
                params += allowed
            sql += " ORDER BY relevance,c.chunk_id LIMIT 64"
            rows = source.execute(sql, params).fetchall()
            if definition_question:
                rows = sorted(
                    rows,
                    key=lambda r: (
                        not bool(
                            re.search(
                                r"\b(?:allows?|enables?|used\s+to|in\s+order\s+to|so\s+that)\b",
                                r["text"],
                                re.I,
                            )
                        )
                        if purpose_question
                        else not bool(
                            re.search(
                                r"\b(?:is|are)\s+(?:defined|a|an)\b|\bconsists?\b|\bcomprises?\b",
                                r["text"],
                                re.I,
                            )
                        ),
                        r["relevance"],
                        r["chunk_id"],
                    ),
                )
            branches.append(rows)
        result = []
        seen = set()
        families = set()
        for rank in range(64):
            for branch in branches:
                if rank >= len(branch):
                    continue
                row = branch[rank]
                family = source_family(json.loads(row["source_json"])["path"])
                if row["chunk_id"] in seen or family in families:
                    continue
                result.append(self.index._chunk(row, 0.0, method))
                seen.add(row["chunk_id"])
                families.add(family)
                if len(result) == 6:
                    return result
        return result

    def supplement(
        self,
        request: RetrieveRequest,
        response: RetrievalResponse,
        *,
        max_chunks_per_document: int | None = None,
    ) -> RetrievalResponse:
        """Replace only duplicate information copies, keeping request/grant limits."""
        allowed = request.filters.document_ids if request.filters else None
        if request.collection_id not in (None, self.collection_id) or any(
            c.collection_id != self.collection_id
            or (allowed is not None and c.document_id not in allowed)
            for c in response.results
        ):
            raise RetrievalError("source context outside request scope")
        if (
            len(response.results) > request.top_k
            or sum(len(c.text) for c in response.results) > request.max_output_chars
        ):
            raise RetrievalError("source context input exceeds request budget")
        query = request.query_translation or request.query
        versioned = bool(VERSION.search(query) or VERSION.search(request.query))
        result = list(response.results)
        original_keys = {information_key(c, versioned) for c in result}
        seen = set()
        donors = []
        anchors = []
        for i, chunk in enumerate(result):
            key = information_key(chunk, versioned)
            if key in seen:
                donors.append(i)
            else:
                seen.add(key)
                anchors.append(chunk)
        if not donors:
            return response
        pending = list(reversed(donors))
        total = sum(len(c.text) for c in result)
        added = 0

        def add(chunk: RetrievedChunk) -> bool:
            nonlocal total, added
            if (
                not pending
                or added == 16
                or chunk.chunk_id in {c.chunk_id for c in result}
                or information_key(chunk, versioned) in seen
            ):
                return False
            choices = [
                i
                for i in pending
                if (
                    total - len(result[i].text) + len(chunk.text) <= request.max_output_chars
                    and (
                        max_chunks_per_document is None
                        or sum(r.document_id == chunk.document_id for r in result)
                        - (result[i].document_id == chunk.document_id)
                        < max_chunks_per_document
                    )
                )
            ]
            if not choices:
                return False
            donor = choices[0]
            before = result[donor]
            result[donor] = chunk.model_copy(update={"rank_score": before.rank_score})
            total += len(chunk.text) - len(before.text)
            pending.remove(donor)
            seen.add(information_key(chunk, versioned))
            added += 1
            return True

        with (
            catalogue_connection(self.path, self.index_sha256, self.collection_id) as bank,
            self.index._connect() as source,
        ):
            self.index._collection(source, self.collection_id)
            method = result[0].retrieval_method
            for chunk in self._definitions(query, source, bank, method, allowed):
                add(chunk)
            if pending and added < 16:
                for chunk in self._focused(query, source, bank, method, allowed):
                    add(chunk)
            anchor_rows = []
            for chunk in anchors[:16] if pending and added < 16 else []:
                row = source.execute(
                    "SELECT document_id,ordinal FROM chunks WHERE collection_id=? AND chunk_id=?",
                    (self.collection_id, chunk.chunk_id),
                ).fetchone()
                if row is None or row["document_id"] != chunk.document_id:
                    raise RetrievalError("source context anchor differs from indexed source")
                anchor_rows.append((chunk, row))
            for offset in [1, -1]:
                for chunk, row in anchor_rows:
                    if not pending or added == 16:
                        break
                    neighbor = source.execute(
                        "SELECT * FROM chunks WHERE collection_id=? "
                        "AND document_id=? AND ordinal=?",
                        (self.collection_id, row["document_id"], row["ordinal"] + offset),
                    ).fetchone()
                    if neighbor is not None:
                        add(self.index._chunk(neighbor, 0.0, chunk.retrieval_method))
        if not original_keys <= {information_key(c, versioned) for c in result}:
            raise RetrievalError("source context lost original unique information")
        if added:
            # These values encode final context order, never new reranker logits/confidence.
            return RetrievalResponse(
                contract_version="1",
                results=[
                    c.model_copy(update={"rank_score": 1 / (61 + i)}) for i, c in enumerate(result)
                ],
            )
        return response
