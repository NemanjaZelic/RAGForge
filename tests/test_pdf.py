import hashlib
import io
import json
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject
from typer.testing import CliRunner

from ragforge.cli import app
from ragforge.core.chunk import chunk_document
from ragforge.core.identity import document_id
from ragforge.core.parse import parse_document
from ragforge.core.pdf import PdfError, PdfOptions, extract_pdf
from ragforge.core.scan import ScannedDocument

FIXTURES = Path(__file__).parent / "fixtures" / "pdf"


def parsed(name: str, options: PdfOptions | None = None):
    raw = (FIXTURES / name).read_bytes()
    record = ScannedDocument(
        document_id=document_id("mini", name),
        source_path=name,
        content_sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
        format="pdf",
    )
    return parse_document("mini", record, raw, pdf_options=options)


def test_text_pdf_has_physical_page_citations_and_no_invented_lines() -> None:
    document = parsed("structured.pdf")
    assert [r.status for r in document.page_reports] == ["extracted", "extracted"]
    assert "retry_limit" in document.blocks[0].text
    assert "transaction.rollback()" in document.blocks[0].text
    assert "Local mode needs no server." in document.blocks[1].text
    assert "Shared mode needs authentication." in document.blocks[1].text
    chunks = chunk_document(document)
    assert [c.source.page for c in chunks] == [1, 2]
    assert all(c.source.line_start is None and c.source.line_end is None for c in chunks)
    assert "Printed label i" in chunks[0].text
    assert chunk_document(parsed("structured.pdf")) == chunks


def test_image_only_and_mixed_pages_are_explicit_without_ocr() -> None:
    image = parsed("image-only.pdf")
    assert not image.blocks
    assert image.page_reports[0].status == "no_text"
    assert any("OCR is disabled" in warning for warning in image.warnings)
    mixed = parsed("mixed.pdf")
    assert [r.status for r in mixed.page_reports] == ["extracted", "extracted", "no_text"]
    assert [c.source.page for c in chunk_document(mixed)] == [1, 2]


def test_page_limit_rejects_instead_of_silently_truncating() -> None:
    with pytest.raises(PdfError, match="max_pages"):
        extract_pdf((FIXTURES / "structured.pdf").read_bytes(), PdfOptions(max_pages=1))


def test_partial_requires_opt_in_and_changes_pipeline_identity() -> None:
    raw = (FIXTURES / "structured.pdf").read_bytes()
    with pytest.raises(PdfError, match="page 1.*max_page_text_chars"):
        extract_pdf(raw, PdfOptions(max_page_text_chars=250))
    partial = parsed("structured.pdf", PdfOptions(max_page_text_chars=250, allow_partial=True))
    assert [r.status for r in partial.page_reports] == ["error", "extracted"]
    chunk = chunk_document(partial)[0]
    assert chunk.source.page == 2
    assert chunk.chunk_id != chunk_document(parsed("structured.pdf"))[1].chunk_id


@pytest.mark.parametrize("partial", [False, True])
def test_document_text_budget_is_always_fatal(partial: bool) -> None:
    with pytest.raises(PdfError, match="max_text_chars"):
        extract_pdf(
            (FIXTURES / "structured.pdf").read_bytes(),
            PdfOptions(max_text_chars=10, allow_partial=partial),
        )


def test_compressed_stream_limit_applies_before_text_extraction() -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    stream = DecodedStreamObject()
    stream.set_data(b" " * 100000)
    page[NameObject("/Contents")] = stream.flate_encode()
    output = io.BytesIO()
    writer.write(output)
    assert len(output.getvalue()) < 2000
    with pytest.raises(PdfError):
        extract_pdf(output.getvalue(), PdfOptions(max_stream_bytes=2000))


def test_encrypted_and_invalid_pdf_are_not_silent_empty_successes() -> None:
    writer = PdfWriter()
    writer.add_page(PdfReader(FIXTURES / "structured.pdf").pages[0])
    writer.encrypt("fixture-password")
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(PdfError, match="encrypted"):
        extract_pdf(output.getvalue())
    with pytest.raises(PdfError, match="PDF"):
        extract_pdf(b"%PDF-1.7\nbroken")


def test_configuration_is_restored_after_failure() -> None:
    import pypdf

    before = pypdf.get_configuration()
    with pytest.raises(PdfError):
        extract_pdf((FIXTURES / "structured.pdf").read_bytes(), PdfOptions(max_pages=1))
    assert pypdf.get_configuration() is before


def test_cli_pdf_preview_reports_page_status_and_limits() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["chunk", str(FIXTURES)])
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert any(doc["incomplete"] for doc in report["documents"])
    assert any(chunk["source"]["page"] == 2 for chunk in report["chunks"])
    failed = runner.invoke(app, ["chunk", str(FIXTURES), "--pdf-max-pages", "1"])
    assert failed.exit_code == 2
    assert failed.stdout == ""
    assert "max_pages" in json.loads(failed.stderr)["error"]
