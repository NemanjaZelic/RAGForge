"""Map small retrieval chunks to source-matched larger context chunks."""

import json
import math
import sqlite3
from collections import OrderedDict
from collections.abc import Iterator
from itertools import zip_longest

from ragforge.core.sqlite import SQLiteEngine

MAX_PAGE_RANGES = 20000
MAX_RANGE_DOCUMENTS = 16


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
        self._bounds: OrderedDict[str, dict[int | None, tuple[int, int]] | None] = OrderedDict()
        self._bounds_entries = 0
        with children._connect() as child, parents._connect() as parent:
            sql = (
                "SELECT document_id,collection_id,source_path,content_sha256 "
                "FROM documents ORDER BY document_id"
            )
            for left, right in zip_longest(child.execute(sql), parent.execute(sql)):
                if left is None or right is None or tuple(left) != tuple(right):
                    raise ValueError("parent/child source inventories differ")

    def _page_rows(
        self, parent: sqlite3.Connection, document: str, page: int | None
    ) -> Iterator[sqlite3.Row]:
        sql = (
            "SELECT chunk_id,text,source_json FROM chunks "
            "WHERE document_id=? AND json_extract(source_json, '$.page') IS ? "
            "ORDER BY ordinal"
        )
        if page is None:
            # Text/HTML documents cannot benefit from a PDF page range catalogue.
            return iter(parent.execute(sql, (document, page)))
        if document not in self._bounds:
            page_bounds: dict[int | None, tuple[int, int]] = {}
            complete = True
            for row in parent.execute(
                "SELECT json_extract(source_json, '$.page') AS page,"
                "min(ordinal) AS first,max(ordinal) AS last FROM chunks "
                "WHERE document_id=? GROUP BY json_extract(source_json, '$.page') LIMIT ?",
                (document, MAX_PAGE_RANGES + 1),
            ):
                if row["page"] is not None and type(row["page"]) is not int:
                    raise ValueError("invalid parent page metadata")
                if len(page_bounds) == MAX_PAGE_RANGES:
                    complete = False
                    break
                page_bounds[row["page"]] = (row["first"], row["last"])
            bounds = page_bounds if complete else None
            count = len(bounds) if bounds is not None else 0
            while self._bounds and (
                len(self._bounds) >= MAX_RANGE_DOCUMENTS
                or self._bounds_entries + count > MAX_PAGE_RANGES
            ):
                _, removed = self._bounds.popitem(last=False)
                self._bounds_entries -= len(removed) if removed is not None else 0
            self._bounds[document] = bounds
            self._bounds_entries += count
        self._bounds.move_to_end(document)
        bounds = self._bounds[document]
        if bounds is None:
            return iter(parent.execute(sql, (document, page)))
        if page not in bounds:
            return iter(())
        first, last = bounds[page]
        # Keep the page predicate: ordinals for a page need not be contiguous.
        return iter(
            parent.execute(
                "SELECT chunk_id,text,source_json FROM chunks WHERE document_id=? "
                "AND ordinal BETWEEN ? AND ? AND json_extract(source_json, '$.page') IS ? "
                "ORDER BY ordinal",
                (document, first, last, page),
            )
        )

    def map_ranks(
        self,
        ranks: list[tuple[str, float]],
        limit: int = 200,
        allowed_documents: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        if not 1 <= limit <= 200 or len(ranks) > 200 or any(not math.isfinite(v) for _, v in ranks):
            raise ValueError("parent mapping candidate limit exceeded")
        if not ranks:
            return []
        mapped: dict[str, float] = {}
        with self.children._connect() as child, self.parents._connect() as parent:
            keys = [key for key, _ in ranks]
            sql = (
                "SELECT chunk_id,document_id,json_extract(source_json,'$.page') AS page "
                "FROM chunks WHERE chunk_id IN (" + ",".join("?" for _ in keys) + ")"
            )
            params = list(keys)
            if allowed_documents is not None:
                sql += " AND document_id IN (" + ",".join("?" for _ in allowed_documents) + ")"
                params += allowed_documents
            lookup = {}
            for row in child.execute(sql, params):
                if (
                    not isinstance(row["document_id"], str)
                    or len(row["document_id"]) != 64
                    or (row["page"] is not None and type(row["page"]) is not int)
                ):
                    raise ValueError("invalid child identity/page metadata")
                lookup[row["chunk_id"]] = row
            groups: dict[str, dict[int | None, list[tuple[str, float]]]] = {}
            for key, score in ranks:
                row = lookup.get(key)
                if row is None:
                    raise ValueError("child candidate missing or outside document scope")
                groups.setdefault(row["document_id"], {}).setdefault(row["page"], []).append(
                    (key, score)
                )
            # Process a physical page once per request. The final max-score merge
            # and deterministic ordering do not depend on anchor processing order.
            for document, pages in groups.items():
                for page, anchors in pages.items():
                    cache_key = (document, page)
                    locations = None
                    for key, score in anchors:
                        row = child.execute(
                            "SELECT text,source_json FROM chunks "
                            "WHERE chunk_id=? AND document_id=?",
                            (key, document),
                        ).fetchone()
                        if row is None:
                            raise ValueError("child candidate missing")
                        source = json.loads(row["source_json"])
                        body = normalized(row["text"])
                        if len(body) < 20:
                            continue
                        if source["page"] != page:
                            raise ValueError("child page changed during mapping")
                        if locations is None:
                            if cache_key not in self._cache:
                                values: list[tuple[dict[str, object], str]] = []
                                chars = 0
                                for parent_row in self._page_rows(parent, document, page):
                                    chars += len(parent_row["text"])
                                    if len(values) >= 20000 or chars > 2_000_000:
                                        raise ValueError("parent document context budget exceeded")
                                    values.append(
                                        (dict(parent_row), normalized(parent_row["text"]))
                                    )
                                while self._cache and (
                                    len(self._cache) >= 8 or self._cache_chars + chars > 8_000_000
                                ):
                                    _, removed = self._cache.popitem(last=False)
                                    self._cache_chars -= sum(
                                        len(str(v[0]["text"])) for v in removed
                                    )
                                self._cache[cache_key] = values
                                self._cache_chars += chars
                            self._cache.move_to_end(cache_key)
                            locations = [
                                (candidate, text, json.loads(str(candidate["source_json"])))
                                for candidate, text in self._cache[cache_key]
                            ]
                        width = min(64, len(body))
                        probes = [body[:width], body[-width:]]
                        start = max(0, (len(body) - width) // 2)
                        probes.append(body[start : start + width])
                        matches = []
                        for candidate, text, location in locations:
                            if location["page"] != source["page"]:
                                continue
                            if (
                                source["line_start"] is not None
                                and location["line_start"] is not None
                            ):
                                if (
                                    location["line_end"] < source["line_start"]
                                    or location["line_start"] > source["line_end"]
                                ):
                                    continue
                            overlap = sum(probe in text for probe in probes)
                            if overlap:
                                matches.append((overlap, str(candidate["chunk_id"])))
                        for _, parent_id in sorted(matches, key=lambda pair: (-pair[0], pair[1]))[
                            :3
                        ]:
                            mapped[parent_id] = max(score, mapped.get(parent_id, float("-inf")))
        return sorted(mapped.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]
