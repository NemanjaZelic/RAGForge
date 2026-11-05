"""Map small retrieval chunks to source-matched larger context chunks."""

import json
import math
from collections import OrderedDict
from itertools import zip_longest

from ragforge.core.sqlite import SQLiteEngine


def normalized(text: str) -> str:
    return " ".join(text.split())


class ParentMapper:
    """Both indexes must already be verified, immutable bundle assets.

    A source inventory match alone is insufficient: every mapped chunk also
    shares actual text, document identity, page and available line provenance.
    No reference answers or external source files participate in mapping.
    """

    def __init__(self, children: SQLiteEngine, parents: SQLiteEngine) -> None:
        self.children = children
        self.parents = parents
        self._cache: OrderedDict[tuple[str, int | None], list[tuple[dict[str, object], str]]] = (
            OrderedDict()
        )
        self._cache_chars = 0
        with children._connect() as child, parents._connect() as parent:
            sql = (
                "SELECT document_id,collection_id,source_path,content_sha256 "
                "FROM documents ORDER BY document_id"
            )
            for left, right in zip_longest(child.execute(sql), parent.execute(sql)):
                if left is None or right is None or tuple(left) != tuple(right):
                    raise ValueError("parent/child source inventories differ")

    def map_ranks(
        self,
        ranks: list[tuple[str, float]],
        limit: int = 200,
        allowed_documents: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        if not 1 <= limit <= 200 or len(ranks) > 200 or any(not math.isfinite(v) for _, v in ranks):
            raise ValueError("parent mapping candidate limit exceeded")
        mapped: dict[str, float] = {}
        with self.children._connect() as child, self.parents._connect() as parent:
            for key, score in ranks:
                row = child.execute("SELECT * FROM chunks WHERE chunk_id=?", (key,)).fetchone()
                if row is None:
                    raise ValueError("child candidate missing")
                doc = str(row["document_id"])
                if allowed_documents is not None and doc not in allowed_documents:
                    raise ValueError("child candidate outside document scope")
                source = json.loads(row["source_json"])
                body = normalized(row["text"])
                if len(body) < 20:
                    continue
                cache_key = (doc, source["page"])
                if cache_key not in self._cache:
                    # Page provenance already excludes other PDF pages from mapping.
                    # Apply it before the bounded read, retaining the full matching
                    # page rather than charging unrelated pages against its budget.
                    values: list[tuple[dict[str, object], str]] = []
                    chars = 0
                    for candidate in parent.execute(
                        "SELECT chunk_id,text,source_json FROM chunks "
                        "WHERE document_id=? AND json_extract(source_json, '$.page') IS ? "
                        "ORDER BY ordinal",
                        cache_key,
                    ):
                        chars += len(candidate["text"])
                        if len(values) >= 20000 or chars > 2_000_000:
                            raise ValueError("parent document context budget exceeded")
                        values.append((dict(candidate), normalized(candidate["text"])))
                    while self._cache and (
                        len(self._cache) >= 8 or self._cache_chars + chars > 8_000_000
                    ):
                        _, removed = self._cache.popitem(last=False)
                        self._cache_chars -= sum(len(str(v[0]["text"])) for v in removed)
                    self._cache[cache_key] = values
                    self._cache_chars += chars
                self._cache.move_to_end(cache_key)
                width = min(64, len(body))
                probes = [body[:width], body[-width:]]
                start = max(0, (len(body) - width) // 2)
                probes.append(body[start : start + width])
                matches = []
                for candidate, text in self._cache[cache_key]:
                    location = json.loads(str(candidate["source_json"]))
                    if location["page"] != source["page"]:
                        continue
                    if source["line_start"] is not None and location["line_start"] is not None:
                        if (
                            location["line_end"] < source["line_start"]
                            or location["line_start"] > source["line_end"]
                        ):
                            continue
                    overlap = sum(probe in text for probe in probes)
                    if overlap:
                        matches.append((overlap, str(candidate["chunk_id"])))
                # A boundary-straddling child may belong to two or three windows.
                for _, parent_id in sorted(matches, key=lambda pair: (-pair[0], pair[1]))[:3]:
                    mapped[parent_id] = max(score, mapped.get(parent_id, float("-inf")))
        return sorted(mapped.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]
