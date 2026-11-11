"""Resolve an explicit title from indexed headings before ranking the question.

This is a user-declared document scope, not a guess from question similarity.
Unresolved or ambiguous titles leave the original request unchanged.
"""

import json
import re

from ragforge.core.contracts import RetrievalFilters, RetrieveRequest
from ragforge.core.sqlite import SQLiteEngine

_MARKER = re.compile(r"^(?:Paper|Document) title:", re.I | re.M)
_SCOPED_QUERY = re.compile(r"(.+?)\r?\n(?:Paper|Document) title: *([^\r\n]+) *", re.S | re.I)
_MAX_TITLE_HITS = 65


def resolve_title_scope(sqlite: SQLiteEngine, request: RetrieveRequest) -> RetrieveRequest:
    """Narrow to one source-confirmed title inside the caller's existing grant.

    Query the existing FTS index for a literal title phrase, then check the
    first indexed heading of each candidate document. Body mentions and nested
    headings cannot establish a document title. No labels or source files are
    consulted. Hitting the candidate cap or finding multiple matching titles
    keeps the original request; no fuzzy or first-hit selection is performed.
    """
    match = _SCOPED_QUERY.fullmatch(request.query)
    if match is None:
        return request
    body, title = match[1].strip(), match[2].strip()
    terms = re.findall(r"[^\W_]+", title)
    if not body or _MARKER.search(body) or not 2 <= len(terms) <= 48 or len(title) > 512:
        return request
    normalized_title = " ".join(title.split()).casefold()
    translation = request.query_translation
    if translation is not None:
        translated = _SCOPED_QUERY.fullmatch(translation)
        if (
            translated is None
            or not translated[1].strip()
            or _MARKER.search(translated[1])
            or " ".join(translated[2].split()).casefold() != normalized_title
        ):
            return request
        translation = translated[1].strip()
    expression = '"' + " ".join(terms) + '"'
    hits = sqlite._rank_expression(request, _MAX_TITLE_HITS, expression)
    if len(hits) >= _MAX_TITLE_HITS:
        return request
    documents = set()
    checked = set()
    with sqlite._connect() as connection:
        for key, _ in hits:
            row = connection.execute(
                "SELECT document_id FROM chunks WHERE chunk_id=?", (key,)
            ).fetchone()
            if row is None:
                raise ValueError("title candidate is missing from the verified index")
            owner = str(row[0])
            if owner in checked:
                continue
            checked.add(owner)
            lead = connection.execute(
                "SELECT source_json FROM chunks WHERE document_id=? ORDER BY ordinal LIMIT 1",
                (owner,),
            ).fetchone()
            heading = json.loads(lead[0]).get("section") or ""
            if " ".join(heading.split()).casefold() == normalized_title:
                documents.add(owner)
    if len(documents) != 1:
        return request
    return request.model_copy(
        update={
            "query": body,
            "query_translation": translation,
            "filters": RetrievalFilters(document_ids=sorted(documents)),
        }
    )
