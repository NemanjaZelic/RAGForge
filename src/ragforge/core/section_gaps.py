"""Return bounded, verbatim source context around the selected evidence."""

import json
import re
from collections import Counter, defaultdict
from collections.abc import Callable

from ragforge.core.contracts import RetrievalResponse, RetrieveRequest
from ragforge.core.sqlite import RetrievalError, SQLiteEngine

MAX_GAP_CHUNKS = 8
MAX_GAP_ADDITIONS = 32
MAX_WHOLE_SECTION_CHUNKS = 16
MAX_SECTION_PROBES = 32
PROTECTED_HITS = 20


def complete_section_gaps(
    sqlite: SQLiteEngine,
    request: RetrieveRequest,
    response: RetrievalResponse,
    *,
    max_chunks_per_document: int | None = None,
    page_bounds: Callable[[str, int], tuple[int, int] | None] | None = None,
) -> RetrievalResponse:
    original = response.results
    if len(original) <= PROTECTED_HITS:
        return response
    allowed = set(request.filters.document_ids) if request.filters else None
    if any(
        (allowed is not None and c.document_id not in allowed)
        or request.collection_id not in (None, c.collection_id)
        for c in response.evidence_chunks()
    ):
        raise RetrievalError("section gap context outside request scope")
    if (
        len(response.context) >= MAX_GAP_ADDITIONS
        or sum(len(c.text) for c in response.evidence_chunks()) >= request.max_output_chars
    ):
        return response
    groups = defaultdict(list)
    candidates = []
    neighbors_to_add = []
    neighborhood_tails: dict[str, bool] = {}
    original_ids = {c.chunk_id for c in original}
    with sqlite._connect() as db:
        collection = sqlite._collection(db, request.collection_id)
        for rank, chunk in enumerate(original):
            row = db.execute(
                "SELECT ordinal FROM chunks WHERE collection_id=? AND document_id=? AND chunk_id=?",
                (collection, chunk.document_id, chunk.chunk_id),
            ).fetchone()
            if row is None:
                raise RetrievalError("section gap anchor is missing")
            groups[(chunk.document_id, chunk.source.section, chunk.source.page)].append(
                (row["ordinal"], rank)
            )
            if chunk.source.section is None and chunk.source.page is None:
                neighbors = db.execute(
                    "SELECT * FROM chunks WHERE collection_id=? AND document_id=? "
                    "AND ordinal IN (?, ?) ORDER BY ordinal",
                    (collection, chunk.document_id, row["ordinal"] - 1, row["ordinal"] + 1),
                ).fetchall()
                for neighbor in neighbors:
                    location = json.loads(neighbor["source_json"])
                    if (
                        neighbor["chunk_id"] not in original_ids
                        and location.get("section") is None
                        and location.get("page") is None
                    ):
                        neighbors_to_add.append(
                            sqlite._chunk(neighbor, 0, original[0].retrieval_method)
                        )
                        # Keep the boundary nearest the hit if only an excerpt
                        # fits. Full primary evidence is never removed to fit it.
                        neighborhood_tails.setdefault(
                            neighbor["chunk_id"], neighbor["ordinal"] < row["ordinal"]
                        )
        query_words = set(re.findall(r"[^\W_]+", request.query.casefold()))
        query_words -= {
            "the",
            "and",
            "for",
            "from",
            "with",
            "what",
            "which",
            "how",
            "does",
            "can",
            "are",
            "this",
            "that",
            "when",
            "where",
            "use",
            "is",
            "of",
            "to",
        }

        def priority(
            item: tuple[tuple[str, str | None, int | None], list[tuple[int, int]]],
        ) -> tuple[int, int, int, str, str]:
            (document, section, _), hits = item
            rank = min(r for _, r in hits)
            header_words = set(
                re.findall(
                    r"[^\W_]+",
                    (
                        (section or "")
                        + " "
                        + original[rank].source.path
                        + " "
                        + str(item[0][2] or "")
                    ).casefold(),
                )
            )
            return (-len(query_words & header_words), -len(hits), rank, document, section or "")

        # Existing headed/page context keeps precedence and its entire budget.
        # Plain-text neighbors are additive, never a reason to displace it.
        headed = [(key, hits) for key, hits in groups.items() if key[1] or key[2] is not None]
        ordered = sorted(headed, key=priority)
        for (document, section, page), hits in ordered[:MAX_SECTION_PROBES]:
            hits.sort()
            for (left, _), (right, _) in zip(hits, hits[1:], strict=False):
                if not 1 < right - left <= MAX_GAP_CHUNKS + 1:
                    continue
                rows = db.execute(
                    "SELECT * FROM chunks WHERE collection_id=? AND document_id=? "
                    "AND ordinal>? AND ordinal<? ORDER BY ordinal",
                    (collection, document, left, right),
                ).fetchall()
                if len(rows) != right - left - 1:
                    continue
                if any(
                    json.loads(row["source_json"]).get("section") != section
                    or json.loads(row["source_json"]).get("page") != page
                    for row in rows
                ):
                    continue
                for row in rows:
                    if row["chunk_id"] not in original_ids:
                        candidates.append(sqlite._chunk(row, 0, original[0].retrieval_method))
            whole_sql = (
                "SELECT * FROM chunks WHERE collection_id=? AND document_id=? "
                "AND json_extract(source_json, '$.section') IS ? "
                "AND json_extract(source_json, '$.page') IS ?"
            )
            whole_params: list[str | int | None] = [collection, document, section, page]
            if page is not None and page_bounds is not None:
                bounds = page_bounds(document, page)
                if bounds is not None:
                    whole_sql += " AND ordinal BETWEEN ? AND ?"
                    whole_params.extend(bounds)
            whole_sql += " ORDER BY ordinal LIMIT ?"
            whole_params.append(MAX_WHOLE_SECTION_CHUNKS + 1)
            whole = db.execute(whole_sql, whole_params).fetchall()
            if 1 <= len(whole) <= MAX_WHOLE_SECTION_CHUNKS:
                for row in whole:
                    if row["chunk_id"] not in original_ids:
                        candidates.append(sqlite._chunk(row, 0, original[0].retrieval_method))
    candidates.extend(neighbors_to_add)
    attached = list(response.context)
    seen = {c.chunk_id for c in response.evidence_chunks()}
    remaining = request.max_output_chars - sum(len(c.text) for c in response.evidence_chunks())
    counts = Counter(c.document_id for c in response.evidence_chunks())
    for chunk in candidates:
        if chunk.chunk_id in seen:
            continue
        if len(chunk.text) > remaining:
            if chunk.chunk_id not in neighborhood_tails or remaining < 128:
                continue
            offset = len(chunk.text) - remaining if neighborhood_tails[chunk.chunk_id] else 0
            chunk = chunk.model_copy(
                update={"text": chunk.text[offset : offset + remaining], "text_offset": offset}
            )
        if (
            max_chunks_per_document is not None
            and counts[chunk.document_id] >= max_chunks_per_document
        ):
            continue
        if len(attached) == MAX_GAP_ADDITIONS:
            break
        attached.append(chunk)
        seen.add(chunk.chunk_id)
        counts[chunk.document_id] += 1
        remaining -= len(chunk.text)
    if len(attached) == len(response.context):
        return response
    # Additional indexed chunks are explicitly unranked context and share
    # the caller's text budget. Every selected primary score stays unchanged.
    return RetrievalResponse(contract_version="1", results=original, context=attached)
