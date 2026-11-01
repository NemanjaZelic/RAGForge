"""Text-layer PDF adapter. No OCR, attachments, actions or external decoders."""

import hashlib
import io
import json
from dataclasses import dataclass
from typing import Annotated, Literal

import pypdf
from pydantic import Field
from pypdf.errors import PyPdfError

from ragforge.types import ContractModel

PDF_PARSER_VERSION = f"pdf-pypdf-{pypdf.__version__}-plain-v1"


class PdfOptions(ContractModel):
    max_pages: Annotated[int, Field(ge=1, le=10000)] = 500
    max_stream_bytes: Annotated[int, Field(ge=1)] = 8 * 1024 * 1024
    max_document_stream_bytes: Annotated[int, Field(ge=1)] = 64 * 1024 * 1024
    max_page_text_chars: Annotated[int, Field(ge=1)] = 200000
    max_text_chars: Annotated[int, Field(ge=1)] = 2000000
    max_stream_operations: Annotated[int, Field(ge=1)] = 500000
    allow_partial: bool = False


@dataclass(frozen=True)
class PdfPageReport:
    page: int
    status: Literal["extracted", "no_text", "error"]
    text_chars: int
    message: str | None = None


@dataclass(frozen=True)
class PdfText:
    pages: tuple[tuple[int, str], ...]
    reports: tuple[PdfPageReport, ...]
    warnings: tuple[str, ...]
    parser_version: str


class PdfError(ValueError):
    pass


class PdfBudgetError(PdfError):
    """Document-wide work/output budget: never continue past it."""


def extract_pdf(raw: bytes, options: PdfOptions | None = None) -> PdfText:
    options = options or PdfOptions()
    if not raw.startswith(b"%PDF-"):
        raise PdfError("invalid PDF header")
    pages: list[tuple[int, str]] = []
    reports: list[PdfPageReport] = []
    warnings: list[str] = []
    text_chars = stream_bytes = 0
    try:
        with pypdf.apply_configuration(
            maximum_declared_stream_length=options.max_stream_bytes,
            array_based_stream_maximum_output_length=options.max_stream_bytes,
            zlib_maximum_output_length=options.max_stream_bytes,
            lzw_maximum_output_length=options.max_stream_bytes,
            run_length_maximum_output_length=options.max_stream_bytes,
            brotli_maximum_output_length=options.max_stream_bytes,
            stream_decoding_work_maximum_length=options.max_stream_bytes * 4,
            stream_parsing_work_maximum_count=options.max_stream_operations,
            stream_filters_maximum_length=8,
            page_tree_maximum_entries=options.max_pages * 4,
            page_tree_maximum_page_entries=options.max_pages * 100,
            page_tree_maximum_depth=32,
            xform_maximum_invocations_per_extraction=100,
            jbig2dec_binary=None,
        ):
            reader = pypdf.PdfReader(
                io.BytesIO(raw), strict=True, xref_stream_maximum_entries=100000
            )
            try:
                if reader.is_encrypted:
                    raise PdfError(
                        "encrypted PDFs are not supported; provide a decrypted local copy"
                    )
                count = len(reader.pages)
                if count > options.max_pages:
                    raise PdfError("max_pages exceeded; PDF was not silently truncated")
                if not count:
                    raise PdfError("PDF contains no pages")
                for number, page in enumerate(reader.pages, 1):
                    try:
                        contents = page.get_contents()
                        size = len(contents.get_data()) if contents is not None else 0
                        stream_bytes += size
                        if stream_bytes > options.max_document_stream_bytes:
                            raise PdfBudgetError("max_document_stream_bytes exceeded")
                        if size > options.max_stream_bytes:
                            raise PdfError("max_stream_bytes exceeded")
                        text = page.extract_text(extraction_mode="plain")
                        text = text.replace("\r\n", "\n").replace("\r", "\n")
                        if len(text) > options.max_page_text_chars:
                            raise PdfError("max_page_text_chars exceeded")
                        if text_chars + len(text) > options.max_text_chars:
                            raise PdfBudgetError("max_text_chars exceeded")
                        if "\ufffd" in text or "\x00" in text:
                            raise PdfError("unreliable PDF text decoding")
                        if text.strip():
                            pages.append((number, text))
                            text_chars += len(text)
                            reports.append(PdfPageReport(number, "extracted", len(text)))
                        else:
                            message = (
                                "no extractable text; page may be scanned or blank; OCR is disabled"
                            )
                            reports.append(PdfPageReport(number, "no_text", 0, message))
                            warnings.append(f"PDF page {number}: {message}")
                    except PdfBudgetError:
                        raise
                    except (
                        PdfError,
                        PyPdfError,
                        ValueError,
                        RecursionError,
                        NotImplementedError,
                    ) as error:
                        if not options.allow_partial:
                            raise PdfError(
                                f"PDF page {number}: {error}; no partial result returned"
                            ) from error
                        reports.append(PdfPageReport(number, "error", 0, str(error)))
                        warnings.append(f"PDF page {number}: extraction failed: {error}")
            finally:
                reader.close()
    except (PyPdfError, RecursionError, NotImplementedError) as error:
        raise PdfError(f"cannot parse PDF: {error}") from error
    # Include options and outcome in pipeline identity: partial pages never alias
    # complete output at the same ordinal.
    identity = {"options": options.model_dump(), "pages": [(r.page, r.status) for r in reports]}
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return PdfText(tuple(pages), tuple(reports), tuple(warnings), PDF_PARSER_VERSION + "-" + digest)
