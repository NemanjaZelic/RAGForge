"""Bounded section definitions from existing source chunks; no additional inference."""

import json
import sqlite3
from collections import Counter
from typing import Literal

from ragforge.core.contracts import RetrievalResponse, RetrieveRequest
from ragforge.core.sqlite import RetrievalError, SQLiteEngine

MAX_DOCUMENT_CHUNKS = 20000
MAX_METADATA_CHARS = 2000000
PROTECTED_HITS = 20
MAX_GROUPS = 8
MAX_SECTION_CHUNKS = 4
MAX_GROUP_PROBES = 32


def complete_sections(
    sqlite: SQLiteEngine,
    request: RetrieveRequest,
    response: RetrievalResponse,
    *,
    max_chunks_per_document: int | None = None,
    policy: Literal["section-start-v1", "section-start-v2", "section-gaps-v3"] = "section-start-v1",
) -> RetrievalResponse:
    """Exchange weak same-document hits for short section starts and successors.

    Preserve the first twenty hits and each section's sole representative.
    At most eight exchanges preserve output and character limits. Version two
    may use one cross-document exchange to complete a short section missing only
    its first chunk; per-document caps still apply. Version one is unchanged.
    Scores describe final context order, not confidence.
    """
    if policy == "section-gaps-v3":
        from ragforge.core.section_gaps import complete_section_gaps

        base = complete_sections(
            sqlite,
            request,
            response,
            max_chunks_per_document=max_chunks_per_document,
            policy="section-start-v2",
        )
        return complete_section_gaps(
            sqlite, request, base, max_chunks_per_document=max_chunks_per_document
        )
    if policy not in {"section-start-v1", "section-start-v2"}:
        raise ValueError("unsupported section completion policy")
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
    boundary_completions: set[str] = set()
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
        document_frequency = Counter(c.document_id for c in original)
        selected = sorted(
            groups.items(),
            key=lambda item: (
                -document_frequency[item[0][0]] if policy == "section-start-v2" else 0,
                not item[1][0],
                -item[1][1],
                item[1][2],
            ),
        )
        eligible_groups = 0
        for (document, section), _ in selected[
            : MAX_GROUP_PROBES if policy == "section-start-v2" else MAX_GROUPS
        ]:
            if document not in metadata:
                if len(metadata) == MAX_GROUPS:
                    continue
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
            section_hits = sum(
                c.document_id == document and c.source.section == section for c in original
            )
            boundary_completion = (
                policy == "section-start-v2"
                and 2 <= len(matching) <= 4
                and section_hits == len(matching) - 1
            )
            eligible_groups += 1
            for offset in range(2):
                item = db.execute(
                    "SELECT * FROM chunks WHERE collection_id=? AND document_id=? AND ordinal=?",
                    (collection, document, matching[0]["ordinal"] + offset),
                ).fetchone()
                if item is not None:
                    chunk = sqlite._chunk(item, 0, original[0].retrieval_method)
                    additions.append(chunk)
                    if (
                        offset == 0
                        and boundary_completion
                        and chunk.chunk_id not in {c.chunk_id for c in original}
                    ):
                        boundary_completions.add(chunk.chunk_id)
            if eligible_groups == MAX_GROUPS:
                break
    result = list(original)
    seen = {c.chunk_id for c in result}
    total = sum(len(c.text) for c in result)
    added: set[str] = set()
    swaps = 0
    cross_document_swaps = 0
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
        cross_document = False
        if (
            donor is None
            and chunk.chunk_id in boundary_completions
            and cross_document_swaps == 0
            and (
                max_chunks_per_document is None
                or counts[chunk.document_id] < max_chunks_per_document
            )
        ):
            donor = next(
                (
                    i
                    for i in range(len(result) - 1, PROTECTED_HITS - 1, -1)
                    if result[i].document_id != chunk.document_id
                    and result[i].chunk_id not in added
                    and counts[result[i].document_id] >= 3
                    and sections[(result[i].document_id, result[i].source.section)] >= 2
                    and total - len(result[i].text) + len(chunk.text) <= request.max_output_chars
                ),
                None,
            )
            cross_document = donor is not None
        if donor is None:
            continue
        cross_document_swaps += int(cross_document)
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
