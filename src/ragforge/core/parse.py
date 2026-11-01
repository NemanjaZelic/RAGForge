"""Offline text normalization and source provenance. Documents are always data."""

import hashlib
import re
import stat
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal

from ragforge.core.identity import document_id
from ragforge.core.pdf import PdfError, PdfOptions, PdfPageReport, extract_pdf
from ragforge.core.scan import FORMATS, ScanLimits, ScannedDocument
from ragforge.core.source import SourceError, checked_stat, is_link, read_file
from ragforge.types import ContractModel

PARSER_VERSION = "text-v1"
HTML_PARSER_VERSION = "html-main-v2"


class TextOptions(ContractModel):
    """Explicit legacy policies; UTF-8 and control rejection remain the default."""

    fallback_encoding: Literal["none", "latin-1"] = "none"
    control_characters: Literal["reject", "escape"] = "reject"


class ParseError(ValueError):
    """No silent fallback for unsupported, invalid or changed sources."""


@dataclass(frozen=True)
class TextBlock:
    text: str
    section: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    page: int | None = None
    kind: Literal["text", "code"] = "text"


@dataclass(frozen=True)
class ParsedDocument:
    collection_id: str
    record: ScannedDocument
    blocks: tuple[TextBlock, ...]
    warnings: tuple[str, ...] = ()
    parser_version: str = PARSER_VERSION
    page_reports: tuple[PdfPageReport, ...] = ()


def load_document(
    root: Path,
    collection_id: str,
    record: ScannedDocument,
    limits: ScanLimits | None = None,
    *,
    pdf_options: PdfOptions | None = None,
    pdf_backend: Literal["pypdf", "pdfium"] = "pypdf",
    text_options: TextOptions | None = None,
) -> ParsedDocument:
    limits = limits or ScanLimits()
    # Validate identity/path again even if a caller bypassed model construction.
    if record.document_id != document_id(collection_id, record.source_path):
        raise ParseError("document identity does not match collection and path")
    try:
        if is_link(root.lstat()):
            raise ParseError("corpus root must not be a link or reparse point")
        root = root.resolve(strict=True)
        if not root.is_dir():
            raise ParseError("corpus root must be a directory")
        path = root
        for part in record.source_path.split("/")[:-1]:
            path /= part
            if not stat.S_ISDIR(checked_stat(path, root).st_mode):
                raise ParseError("source parent must be a directory")
        path = root / record.source_path
        digest, size, raw = read_file(
            path, root, limits.max_file_bytes, limits.max_total_bytes, capture=True
        )
        if digest != record.content_sha256 or size != record.size_bytes:
            raise ParseError("source changed since scan")
    except (OSError, SourceError) as error:
        raise ParseError(f"{record.source_path!r}: {error}") from error
    return parse_document(
        collection_id,
        record,
        raw,
        pdf_options=pdf_options,
        pdf_backend=pdf_backend,
        text_options=text_options,
    )


def _section(headings: dict[int, str]) -> str | None:
    return " > ".join(headings[level] for level in sorted(headings) if headings[level]) or None


def _heading(headings: dict[int, str], level: int, title: str) -> str | None:
    for key in list(headings):
        if key >= level:
            del headings[key]
    headings[level] = title
    return _section(headings)


def _markdown(text: str) -> tuple[list[TextBlock], list[str]]:
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    blocks: list[TextBlock] = []
    warnings: list[str] = []
    headings: dict[int, str] = {}
    pending: list[str] = []
    pending_start = 1

    def flush() -> None:
        value = "".join(pending)
        if value.strip():
            blocks.append(
                TextBlock(
                    value,
                    _section(headings),
                    pending_start,
                    pending_start + len(pending) - 1,
                )
            )
        pending.clear()

    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\n")
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            flush()
            marker = fence.group(1)
            end = i + 1
            closed = False
            while end < len(lines):
                closing = lines[end].rstrip("\n")
                if re.fullmatch(
                    r" {0,3}" + re.escape(marker[0]) + r"{" + str(len(marker)) + r",}[ \t]*",
                    closing,
                ):
                    end += 1
                    closed = True
                    break
                end += 1
            blocks.append(
                TextBlock("".join(lines[i:end]), _section(headings), i + 1, end, kind="code")
            )
            if not closed:
                warnings.append(f"unclosed code fence at line {i + 1}")
            i = end
            continue
        atx = re.match(r"^ {0,3}(#{1,6})(?:[ \t]+(.*)|[ \t]*)$", line)
        setext = (
            re.fullmatch(r" {0,3}(=+|-+)[ \t]*", lines[i + 1].rstrip("\n"))
            if i + 1 < len(lines) and line.strip()
            else None
        )
        if atx or setext:
            flush()
            if atx:
                title = re.sub(r"[ \t]+#+[ \t]*$", "", atx.group(2) or "").strip()
                level, count = len(atx.group(1)), 1
            else:
                assert setext is not None
                title, level, count = line.strip(), 1 if setext.group(1)[0] == "=" else 2, 2
            _heading(headings, level, title)
            pending_start = i + 1
            pending.extend(lines[i : i + count])
            i += count
            continue
        if not pending:
            pending_start = i + 1
        pending.append(lines[i])
        i += 1
    flush()
    return blocks, warnings


class _HTMLText(HTMLParser):
    OMIT = {"head", "script", "style", "template", "noscript"}
    VOID = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
    BOUNDARY = {
        "address",
        "article",
        "aside",
        "blockquote",
        "dd",
        "div",
        "dl",
        "dt",
        "footer",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "section",
        "table",
        "tr",
        "ul",
        "br",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[TextBlock] = []
        self.parts: list[str] = []
        self.omitted: list[str] = []
        self.headings: dict[int, str] = {}
        self.heading_level: int | None = None
        self.pre = False

    def flush(self) -> None:
        text = "".join(self.parts)
        self.parts.clear()
        text = text if self.pre else re.sub(r"\s+", " ", text).strip()
        if not text.strip():
            self.heading_level = None
            return
        if self.heading_level is not None:
            _heading(self.headings, self.heading_level, text)
        self.blocks.append(
            TextBlock(text, _section(self.headings), kind="code" if self.pre else "text")
        )
        self.heading_level = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.omitted or tag in self.OMIT:
            if tag not in self.VOID:
                self.omitted.append(tag)
            return
        if re.fullmatch(r"h[1-6]", tag):
            self.flush()
            self.heading_level = int(tag[1])
        elif tag == "pre":
            self.flush()
            self.pre = True
        elif tag in self.BOUNDARY and not self.pre:
            self.flush()
        elif tag in {"td", "th"} and not self.pre:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if self.omitted:
            if tag in self.omitted:
                index = len(self.omitted) - 1 - self.omitted[::-1].index(tag)
                del self.omitted[index:]
            return
        if tag == "pre":
            self.flush()
            self.pre = False
        elif re.fullmatch(r"h[1-6]", tag) or (tag in self.BOUNDARY and not self.pre):
            self.flush()

    def handle_data(self, data: str) -> None:
        if not self.omitted:
            self.parts.append(data)


class _MainHTMLText(_HTMLText):
    """Prefer an authored main landmark; generic HTML retains the existing fallback."""

    def __init__(self) -> None:
        super().__init__()
        self.found = False
        self.scope: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not self.found:
            if tag != "main" and not (tag == "div" and dict(attrs).get("role") == "main"):
                return
            self.found = True
        elif not self.scope:
            return
        if tag not in self.VOID:
            self.scope.append(tag)
        super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if not self.scope:
            return
        super().handle_endtag(tag)
        if tag in self.scope:
            last = len(self.scope) - 1 - self.scope[::-1].index(tag)
            del self.scope[last:]

    def handle_data(self, data: str) -> None:
        if self.scope:
            super().handle_data(data)


def parse_document(
    collection_id: str,
    record: ScannedDocument,
    raw: bytes,
    *,
    pdf_options: PdfOptions | None = None,
    pdf_backend: Literal["pypdf", "pdfium"] = "pypdf",
    text_options: TextOptions | None = None,
) -> ParsedDocument:
    if record.document_id != document_id(collection_id, record.source_path):
        raise ParseError("document identity does not match collection and path")
    if len(raw) != record.size_bytes or hashlib.sha256(raw).hexdigest() != record.content_sha256:
        raise ParseError("source bytes do not match scan")
    if FORMATS.get(Path(record.source_path).suffix.lower()) != record.format:
        raise ParseError("source format does not match extension")
    if record.format == "pdf":
        try:
            if pdf_backend == "pdfium":
                from ragforge.core.pdf_fast import extract_pdfium

                extracted = extract_pdfium(raw, pdf_options)
            else:
                extracted = extract_pdf(raw, pdf_options)
        except PdfError as error:
            raise ParseError(str(error)) from error
        pdf_blocks = tuple(TextBlock(text, page=number) for number, text in extracted.pages)
        pdf_warnings = extracted.warnings + (() if pdf_blocks else ("no extractable text",))
        return ParsedDocument(
            collection_id,
            record,
            pdf_blocks,
            pdf_warnings,
            parser_version=extracted.parser_version,
            page_reports=extracted.reports,
        )
    text_options = text_options or TextOptions()
    warnings: list[str] = []
    suffix = ""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        if text_options.fallback_encoding != "latin-1":
            raise ParseError(
                "source must be UTF-8 (optional BOM); invalid bytes are not replaced"
            ) from error
        text = raw.decode("latin-1")
        warnings.append("decoded using explicitly selected latin-1 fallback")
        suffix += ";encoding-latin-1"
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if any(ord(char) < 32 and char not in "\n\t\f" for char in text):
        if text_options.control_characters != "escape":
            raise ParseError("source contains unsupported control characters")
        text = "".join(
            f"\\x{ord(char):02x}" if ord(char) < 32 and char not in "\n\t\f" else char
            for char in text
        )
        warnings.append("control characters escaped under explicit legacy text policy")
        suffix += ";controls-escaped-v1"
    if record.format == "markdown":
        blocks, markdown_warnings = _markdown(text)
        warnings.extend(markdown_warnings)
    elif record.format == "html":
        scoped = _MainHTMLText()
        scoped.feed(text)
        scoped.close()
        parser: _HTMLText = scoped if scoped.found else _HTMLText()
        if not scoped.found:
            parser.feed(text)
        parser.close()
        parser.flush()
        blocks = parser.blocks
        if parser.omitted:
            warnings.append("unclosed excluded HTML element; trailing content was suppressed")
    else:
        blocks = (
            [TextBlock(text, line_start=1, line_end=text.count("\n") + (not text.endswith("\n")))]
            if text.strip()
            else []
        )
    if not blocks:
        warnings.append("no extractable text")
    return ParsedDocument(
        collection_id,
        record,
        tuple(blocks),
        tuple(warnings),
        parser_version=(HTML_PARSER_VERSION if record.format == "html" else PARSER_VERSION)
        + suffix,
    )
