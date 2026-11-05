"""Opt-in multilingual question facets, reusing only words from the query.

No translation, language detection, document lookup or model calls. Language
patterns supplement the original request, whose candidates and grants remain.
"""

import re

from ragforge.core.planning_v2 import question_facets as previous_facets

# Explicit interrogative clauses only: conjunctions inside a noun phrase do not
# establish separate questions. Unrecognized languages keep the original query.
_START = (
    r"what|which|who|where|when|why|how|must|may|can|could|should|does|do|is|are|"
    r"šta|što|sta|sto|kako|koji|koja|koje|zašto|zasto|kada|gde|gdje|da\s+li|"
    r"шта|што|како|који|која|које|зашто|када|где|гдје|да\s+ли|"
    r"wie|was|welche[rnms]?|wo|wann|warum|kann|soll|"
    r"comment|pourquoi|quand|où|quels?|quelles?|"
    r"c[oó]mo|qu[eé]|cu[aá]ndo|d[oó]nde|por\s+qu[eé]|cu[aá]les?|"
    r"como|qual|quais|quando|onde|por\s+que|"
    r"как|что|почему|когда|где|какой|какая|какие"
)
_BOUNDARY = re.compile(
    r"(?:\s*,?\s+(?:and|or|i|a|ili|и|а|или|und|oder|et|ou|y|o|e)\s+|[?؟？;]\s+)"
    r"(?=(?:" + _START + r")\b)",
    re.IGNORECASE,
)


def _mask_protected(text: str) -> str | None:
    """Mask quoted/code/parenthesized text without changing character offsets."""
    chars = list(text)
    closing = {"(": ")", "[": "]", "{": "}"}
    quotes = {'"': '"', "'": "'", "`": "`", "“": "”", "‘": "’", "«": "»"}
    stack: list[str] = []
    quote: str | None = None
    escaped = False
    for index, char in enumerate(text):
        if quote is not None:
            chars[index] = "¤"
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in quotes and not (
            char in {"'", "‘"} and index > 0 and text[index - 1].isalnum()
        ):
            quote = quotes[char]
            chars[index] = "¤"
        elif char in closing:
            stack.append(closing[char])
            chars[index] = "¤"
        elif char in closing.values():
            if not stack or stack.pop() != char:
                return None
            chars[index] = "¤"
        elif stack:
            chars[index] = "¤"
    return None if stack or quote is not None else "".join(chars)


def question_facets(query: str) -> list[str]:
    if len(query) > 2048 or len(query.split()) > 128:
        return []
    text = query.strip().rstrip("?.!؟？")
    masked = _mask_protected(text)
    if masked is None:
        return []
    if masked == text:
        previous = previous_facets(query)
        if previous:
            return previous
    boundaries = list(_BOUNDARY.finditer(masked))
    if not boundaries:
        return []
    parts = []
    start = 0
    for boundary in boundaries:
        parts.append(text[start : boundary.start()])
        start = boundary.end()
    parts.append(text[start:])
    result: list[str] = []
    for part in parts:
        part = part.strip(" ,;:?")
        if not part or len(part) > 2048:
            continue
        facet = part + "?"
        if all(facet.casefold() != previous.casefold() for previous in result):
            result.append(facet)
    return result[:3] if len(result) > 1 else []
