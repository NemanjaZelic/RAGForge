"""Independent source representations used by frozen evidence labels."""

import hashlib
import json
import re
import unicodedata
from collections import OrderedDict
from html.parser import HTMLParser
from pathlib import Path

from ragforge.core.embedding import file_hash
from ragforge.core.source import checked_stat, is_link
from ragforge.evaluation.models import Canonicalizer, Evidence


def canonicalize(text: str, method: Canonicalizer) -> str:
    if method == "NFKC-casefold-alnum-v1":
        return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())
    return re.sub(r"\s+", " ", text)


class SphinxMain(HTMLParser):
    """Label oracle matching the preparation spec; independent of product chunking."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.depth = 0
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "div":
            if self.depth:
                self.depth += 1
            elif values.get("role") == "main" and "body" in (values.get("class") or "").split():
                self.depth = 1
        if not self.depth:
            return
        if tag in {"head", "script", "style", "template"}:
            self.skip += 1
        if not self.skip and tag in {
            "p",
            "div",
            "li",
            "tr",
            "h1",
            "h2",
            "h3",
            "h4",
            "pre",
            "br",
            "section",
        }:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"head", "script", "style", "template"}:
            self.skip = max(0, self.skip - 1)
        if tag == "div" and self.depth:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth and not self.skip:
            self.parts.append(data)


class HTMLBodyText(HTMLParser):
    """Independent visible-body evidence oracle; never executes or fetches HTML."""

    SEPARATORS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
    OMIT = {"head", "script", "style", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.in_body = False
        self.omitted: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "body" and not self.omitted:
            self.in_body = True
        if not self.in_body:
            return
        if tag in self.OMIT:
            self.omitted.append(tag)
        elif not self.omitted and tag in self.SEPARATORS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.omitted:
            if tag in self.omitted:
                index = len(self.omitted) - 1 - self.omitted[::-1].index(tag)
                del self.omitted[index:]
            return
        if tag == "body":
            self.in_body = False
        elif self.in_body and tag in self.SEPARATORS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.in_body and not self.omitted:
            self.parts.append(data)


class EvidenceSources:
    def __init__(self, root: Path, *, pdf_reference_cache: Path | None = None) -> None:
        if is_link(root.lstat()):
            raise ValueError("evidence root must not be a link")
        self.root = root.resolve(strict=True)
        self.pdf_cache = pdf_reference_cache.resolve(strict=True) if pdf_reference_cache else None
        self.verified: set[tuple[str, str]] = set()
        self.page_cache: OrderedDict[str, list[str]] = OrderedDict()
        self.text_cache: OrderedDict[str, str] = OrderedDict()
        self.text_cache_chars = 0

    def path(self, target: Evidence) -> Path:
        path = self.root
        for part in target.source_path.split("/"):
            path /= part
            checked_stat(path, self.root)
        key = (target.source_path, target.source_sha256)
        if key not in self.verified:
            if path.stat().st_size > 64 * 1024**2 or file_hash(path) != target.source_sha256:
                raise ValueError("evidence source bytes differ from frozen labels")
            self.verified.add(key)
        return path

    def pdf_pages(self, checksum: str) -> list[str]:
        if checksum in self.page_cache:
            self.page_cache.move_to_end(checksum)
            return self.page_cache[checksum]
        if self.pdf_cache is None:
            raise ValueError("PDF evidence requires the frozen reference extraction cache")
        path = self.pdf_cache / (checksum + ".json")
        if is_link(path.lstat()) or path.stat().st_size > 256 * 1024**2:
            raise ValueError("unsafe/oversized PDF reference cache")
        pages = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(pages, list)
            or len(pages) > 10000
            or any(not isinstance(s, str) for s in pages)
        ):
            raise ValueError("invalid PDF reference page inventory")
        self.page_cache[checksum] = pages
        if len(self.page_cache) > 2:
            self.page_cache.popitem(last=False)
        return pages

    def text(self, target: Evidence) -> str:
        # Multiple facts can refer to the same large source. Cache its canonical
        # representation once, while validating every individual span on each call.
        key = target.model_dump_json(
            include={"source_path", "source_sha256", "canonicalizer", "page"}
        )
        if key in self.text_cache:
            self.text_cache.move_to_end(key)
            value = self.text_cache[key]
        else:
            value = self._text(target.model_dump_json())
            if len(value) <= 8_000_000:
                while self.text_cache and (
                    len(self.text_cache) >= 32 or self.text_cache_chars + len(value) > 8_000_000
                ):
                    _, removed = self.text_cache.popitem(last=False)
                    self.text_cache_chars -= len(removed)
                self.text_cache[key] = value
                self.text_cache_chars += len(value)
        if (
            target.char_end > len(value)
            or hashlib.sha256(value[target.char_start : target.char_end].encode()).hexdigest()
            != target.span_sha256
        ):
            raise ValueError("evidence span hash does not match its frozen source representation")
        return value

    def _text(self, serialized: str) -> str:
        target = Evidence.model_validate_json(serialized)
        path = self.path(target)
        if target.page is not None:
            pages = self.pdf_pages(target.source_sha256)
            if not 1 <= target.page <= len(pages):
                raise ValueError("evidence page exceeds frozen source extraction")
            text = pages[target.page - 1]
        else:
            text = path.read_text(encoding="utf-8")
            if target.canonicalizer == "sphinx-main-html-data-collapse-whitespace-v1":
                parser = SphinxMain()
                parser.feed(text)
                text = "".join(parser.parts)
            elif target.canonicalizer == "html-body-text-collapse-whitespace-v1":
                body = HTMLBodyText()
                body.feed(text)
                text = "".join(body.parts)
        return canonicalize(text, target.canonicalizer)
