"""Literal content terms for the explicit English GPU hybrid profile.

Only its lexical branch changes. Original query, dense input, scoring query and
source/version scope stay with the caller. This is a candidate-selection policy,
not an equivalent BM25 score optimization; source-quality checks are required.
"""

import re

from ragforge.core.contracts import RetrieveRequest
from ragforge.core.lexical_plan import Ranker, Ranks
from ragforge.core.sqlite import plain_query

# Preserve negation, conditions and normative language (not/without/if/must/shall/
# should/may/can), technical uppercase names and all quoted/code/argument forms.
_GRAMMAR = frozenset(
    "a an the what which who where when why how is are was were be been being "
    "do does did to of for in by at with from it its this that these those according".split()
)
_PREFACE = re.compile(
    r"^\s*according\s+to\s+.{1,180}?,\s*"
    r"(?=(?:what|which|who|where|when|why|how|is|are|does|do|can|should)\b)",
    re.I,
)


def english_content_query(query: str) -> str:
    """Use only input words; keep literals intact and the original term limit."""
    plain_query(query)
    if (
        len(query) > 2048
        or any(c in query for c in "\"'`“”‘’«»()[]{}=\\")
        or "/" in query
        or "--" in query
    ):
        return query
    body = _PREFACE.sub("", query, count=1)
    words = re.findall(r"[^\W_]+", body)
    terms = [
        word
        for word in words
        if word.casefold() not in _GRAMMAR or (len(word) > 1 and word.isupper())
    ]
    return " ".join(terms) if len(terms) >= 2 else query


def content_lexical(rank: Ranker) -> Ranker:
    def search(request: RetrieveRequest, limit: int) -> Ranks:
        query = english_content_query(request.query)
        lexical = request.model_copy(update={"query": query}) if query != request.query else request
        return rank(lexical, limit)

    return search
