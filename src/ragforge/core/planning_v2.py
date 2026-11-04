"""Version two query-only facets and explicit technical source-stem references."""

import re

from ragforge.core.planning import (
    _MODALS,
)
from ragforge.core.planning import (
    question_facets as legacy_question_facets,
)
from ragforge.core.planning import (
    referenced_documents as legacy_referenced_documents,
)


def question_facets(query: str) -> list[str]:
    old = legacy_question_facets(query)
    if old or len(query) > 2048 or len(query.split()) > 128:
        return old
    text = query.strip().rstrip("?.!")
    for pattern in [
        r"(?:Combine|Compare)\s+(.+?)\s+with\s+(.+)",
        r"(?:Distinguish|What\s+distinguishes)\s+(.+?)\s+from\s+(.+)",
    ]:
        match = re.fullmatch(pattern, text, re.I)
        if match:
            return [part.strip(" ,;:") + "?" for part in match.groups()]
    return []


def referenced_documents(
    query: str, documents: list[tuple[str, str]], allowed: list[str] | None = None
) -> list[str]:
    if len(query) > 2048 or len(query.split()) > 128:
        return []
    result = legacy_referenced_documents(query, documents, allowed)
    scope = set(allowed) if allowed is not None else None
    inventory = [(doc, path) for doc, path in documents if scope is None or doc in scope]
    # Only visibly technical query tokens can name an extension-free source.
    names = {
        re.sub(r"[^a-z0-9]", "", word.casefold())
        for word in re.findall(r"\b[A-Za-z][A-Za-z0-9_/-]*\b", query)
        if word.upper() not in _MODALS
        and (
            (sum(c.isupper() for c in word) >= 2 and any(c.islower() for c in word)) or "_" in word
        )
    }
    for doc, path in sorted(
        inventory, key=lambda item: (item[1].count("/"), len(item[1]), item[1])
    ):
        stem = path.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if re.sub(r"[^a-z0-9]", "", stem.casefold()) in names and doc not in result:
            result.append(doc)
        if len(result) == 4:
            break
    return result[:4]
