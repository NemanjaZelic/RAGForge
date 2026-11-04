"""Bounded section definitions from existing source chunks; no additional inference."""

import json
import sqlite3
from collections import Counter

from ragforge.core.contracts import RetrievalResponse, RetrieveRequest
from ragforge.core.sqlite import RetrievalError, SQLiteEngine

MAX_DOCUMENT_CHUNKS = 20000
MAX_METADATA_CHARS = 2000000
PROTECTED_HITS = 20
MAX_GROUPS = 8
MAX_SECTION_CHUNKS = 4


def complete_sections(
    sqlite: SQLiteEngine,
    request: RetrieveRequest,
    response: RetrievalResponse,
    *,
    max_chunks_per_document: int | None = None,
) -> RetrievalResponse:
    """Exchange weak same-document hits for short section starts and successors.

    Preserve the first twenty hits and each section's sole representative.
    At most eight exchanges; output count, character budget and per-document
    counts never increase. Scores describe final context order, not confidence.
    """
    original = response.results
    if len(original) <= PROTECTED_HITS or max_chunks_per_document == 1:
        return response
    allowed = set(request.filters.document_ids) if request.filters else None
    if any(
        (allowed is not None and c.document_id not in allowed)
        or request.collection_id not in (None, c.collection_id)
        for c in original
    ):
        raise RetrievalError("section context outside request scope")
    groups: dict[tuple[str, str], tuple[bool, int, int]] = {}
    additions = []
    metadata: dict[str, list[sqlite3.Row]] = {}
    with sqlite._connect() as db:
        collection = sqlite._collection(db, request.collection_id)
        for rank, chunk in enumerate(original):
            section = chunk.source.section
            if not section:
                continue
            anchor = db.execute(
                "SELECT ordinal FROM chunks WHERE collection_id=? AND document_id=? AND chunk_id=?",
                (collection, chunk.document_id, chunk.chunk_id),
            ).fetchone()
            if anchor is None:
                raise RetrievalError("section context anchor is missing")
            root = " > " not in section
            if root and anchor["ordinal"] > 2:
                continue
            key = (chunk.document_id, section)
            _, count, first_rank = groups.get(key, (root, 0, rank))
            groups[key] = (root, count + 1, first_rank)
        selected = sorted(
            groups.items(), key=lambda item: (not item[1][0], -item[1][1], item[1][2])
        )
        for (document, section), _ in selected[:MAX_GROUPS]:
            if document not in metadata:
                rows: list[sqlite3.Row] = []
                metadata_chars = 0
                for row in db.execute(
                    "SELECT ordinal,source_json FROM chunks "
                    "WHERE collection_id=? AND document_id=? "
                    "ORDER BY ordinal LIMIT ?",
                    (collection, document, MAX_DOCUMENT_CHUNKS + 1),
                ):
                    metadata_chars += len(row["source_json"])
                    if len(rows) == MAX_DOCUMENT_CHUNKS or metadata_chars > MAX_METADATA_CHARS:
                        rows = []
                        break
                    rows.append(row)
                metadata[document] = rows
            rows = metadata[document]
            matching = [
                row for row in rows if json.loads(row["source_json"]).get("section") == section
            ]
            if not matching or len(matching) > MAX_SECTION_CHUNKS:
                continue
            for offset in range(2):
                item = db.execute(
                    "SELECT * FROM chunks WHERE collection_id=? AND document_id=? AND ordinal=?",
                    (collection, document, matching[0]["ordinal"] + offset),
                ).fetchone()
                if item is not None:
                    additions.append(sqlite._chunk(item, 0, original[0].retrieval_method))
    result = list(original)
    seen = {c.chunk_id for c in result}
    total = sum(len(c.text) for c in result)
    added: set[str] = set()
    swaps = 0
    for chunk in additions:
        if chunk.chunk_id in seen:
            continue
        counts = Counter(c.document_id for c in result)
        sections = Counter((c.document_id, c.source.section) for c in result)
        donor = next(
            (
                i
                for i in range(len(result) - 1, PROTECTED_HITS - 1, -1)
                if result[i].document_id == chunk.document_id
                and result[i].chunk_id not in added
                and counts[chunk.document_id] >= 3
                and sections[(chunk.document_id, result[i].source.section)] >= 2
                and total - len(result[i].text) + len(chunk.text) <= request.max_output_chars
            ),
            None,
        )
        if donor is None:
            continue
        total += len(chunk.text) - len(result[donor].text)
        seen.remove(result[donor].chunk_id)
        result[donor] = chunk
        seen.add(chunk.chunk_id)
        added.add(chunk.chunk_id)
        swaps += 1
        if swaps == MAX_GROUPS:
            break
    if not swaps:
        return response
    return RetrievalResponse(
        contract_version="1",
        results=[c.model_copy(update={"rank_score": 1 / (61 + i)}) for i, c in enumerate(result)],
    )
