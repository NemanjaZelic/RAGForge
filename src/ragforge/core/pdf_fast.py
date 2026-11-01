"""Optional PDFium text backend; production ingestion runs it in a bounded worker.

No page rendering, forms, JavaScript, attachments, actions or external decoders.
PDFium has no pypdf decoded-stream/work counter; worker memory/time budgets apply.
"""

import hashlib
import importlib.metadata
import json
from contextlib import closing
from threading import Lock

from ragforge.core.pdf import PdfBudgetError, PdfError, PdfOptions, PdfPageReport, PdfText

_LOCK = Lock()  # PDFium is process-global and must never run concurrently in threads.


def extract_pdfium(
    raw: bytes, options: PdfOptions | None = None, *, allow_permitted: bool = False
) -> PdfText:
    options = options or PdfOptions()
    if not raw.startswith(b"%PDF-"):
        raise PdfError("invalid PDF header")
    try:
        import pypdfium2 as pdfium  # type: ignore[import-untyped]
    except ImportError as error:
        raise PdfError("PDFium ingestion requires ragforge[pdf-fast]") from error
    pages: list[tuple[int, str]] = []
    reports: list[PdfPageReport] = []
    warnings: list[str] = []
    total = 0
    permitted_encryption = False
    with _LOCK:
        try:
            with pdfium.PdfDocument(raw) as document:
                if pdfium.raw.FPDF_GetSecurityHandlerRevision(document) != -1:
                    if not allow_permitted:
                        raise PdfError("encrypted PDFs are not supported")
                    # No password is supplied. Even owner-unlocked documents must
                    # retain the user's extraction right (PDF permission bit 5).
                    if not pdfium.raw.FPDF_GetDocUserPermissions(document) & 16:
                        raise PdfError("PDF user permissions do not permit text extraction")
                    permitted_encryption = True
                    warnings.append(
                        "empty-password PDF opened with explicit text extraction permission"
                    )
                count = len(document)
                if not 1 <= count <= options.max_pages:
                    raise PdfBudgetError("PDF page count exceeds configured bounds")
                for index in range(count):
                    number = index + 1
                    try:
                        with (
                            closing(document[index]) as page,
                            closing(page.get_textpage()) as textpage,
                        ):
                            if textpage.count_chars() > options.max_page_text_chars:
                                raise PdfError("max_page_text_chars exceeded")
                            text = textpage.get_text_bounded(errors="strict")
                        text = text.replace("\r\n", "\n").replace("\r", "\n")
                        if len(text) > options.max_page_text_chars:
                            raise PdfError("max_page_text_chars exceeded")
                        if total + len(text) > options.max_text_chars:
                            raise PdfBudgetError("max_text_chars exceeded")
                        if "\ufffd" in text or "\x00" in text:
                            raise PdfError("unreliable PDF text decoding")
                        if text.strip():
                            pages.append((number, text))
                            total += len(text)
                            reports.append(PdfPageReport(number, "extracted", len(text)))
                        else:
                            message = (
                                "no extractable text; page may be blank/scanned; OCR is disabled"
                            )
                            reports.append(PdfPageReport(number, "no_text", 0, message))
                            warnings.append(f"PDF page {number}: {message}")
                    except PdfBudgetError:
                        raise
                    except (ValueError, RuntimeError, UnicodeError) as error:
                        if not options.allow_partial:
                            raise PdfError(f"PDF page {number}: extraction failed") from error
                        reports.append(PdfPageReport(number, "error", 0, str(error)[:1000]))
                        warnings.append(f"PDF page {number}: extraction failed")
        except PdfError:
            raise
        except (ValueError, RuntimeError) as error:
            raise PdfError(f"cannot parse PDF with PDFium: {error}") from error
    identity: dict[str, object] = {
        "options": options.model_dump(),
        "pages": [(r.page, r.status) for r in reports],
    }
    if permitted_encryption:
        identity["permitted_empty_password_encryption"] = True
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    version = importlib.metadata.version("pypdfium2")
    return PdfText(
        tuple(pages), tuple(reports), tuple(warnings), f"pdf-pdfium-{version}-v1-{digest}"
    )
