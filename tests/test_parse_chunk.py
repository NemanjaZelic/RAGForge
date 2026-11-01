import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from ragforge.cli import app
from ragforge.core.chunk import ChunkConfig, chunk_document, pipeline_hash
from ragforge.core.parse import ParseError, load_document, parse_document
from ragforge.core.scan import ScanLimits, scan_corpus


def document(tmp_path: Path, raw: bytes, name: str = "doc.md"):
    (tmp_path / name).write_bytes(raw)
    record = scan_corpus(tmp_path, "mini").documents[0]
    return parse_document("mini", record, raw)


def test_utf8_bom_newlines_and_actual_source_lines(tmp_path: Path) -> None:
    doc = document(tmp_path, b"\xef\xbb\xbf# Header\r\n\r\nHello\rWorld\n")
    assert doc.blocks[0].text == "# Header\n\nHello\nWorld\n"
    assert (doc.blocks[0].line_start, doc.blocks[0].line_end) == (1, 4)
    chunks = chunk_document(doc, ChunkConfig(chunk_size_chars=15, overlap_chars=3))
    for chunk in chunks:
        assert chunk.text == doc.blocks[0].text[chunk.char_start : chunk.char_end]
        start = 1 + doc.blocks[0].text[: chunk.char_start].count("\n")
        end = 1 + doc.blocks[0].text[: chunk.char_end - 1].count("\n")
        assert (chunk.source.line_start, chunk.source.line_end) == (start, end)
    assert (
        doc.record.content_sha256
        == hashlib.sha256(b"\xef\xbb\xbf# Header\r\n\r\nHello\rWorld\n").hexdigest()
    )


def test_markdown_sections_setext_and_fenced_code_are_preserved(tmp_path: Path) -> None:
    raw = (
        b"# Guide\nintro\n\n## API\nUse this.\n\n"
        b"```python\n# This is code, not a heading\nx = 1\n```\n"
        b"tail\nNext\n----\nother\n"
    )
    doc = document(tmp_path, raw)
    code = next(block for block in doc.blocks if block.kind == "code")
    assert code.text == "```python\n# This is code, not a heading\nx = 1\n```\n"
    assert code.section == "Guide > API"
    assert (code.line_start, code.line_end) == (7, 10)
    assert doc.blocks[-1].section == "Guide > Next"
    chunks = chunk_document(doc)
    assert next(chunk for chunk in chunks if chunk.kind == "code").text == code.text


def test_unclosed_fence_is_data_and_reports_warning(tmp_path: Path) -> None:
    doc = document(tmp_path, b"~~~js\n# not a heading\ncode")
    assert doc.blocks[0].kind == "code"
    assert doc.blocks[0].line_end == 3
    assert doc.warnings == ("unclosed code fence at line 1",)


def test_html_text_has_no_fabricated_line_numbers_and_never_keeps_scripts(tmp_path: Path) -> None:
    doc = document(
        tmp_path,
        b"""<!doctype html><html><head><title>omit title</title>
<style>omit style</style></head><body><h1>API &amp; tools</h1>
<p>Hello <b>world</b> &lt;safe&gt;.</p><script src="https://invalid.test/x">omit script</script>
<template><p>omit nested</p></template><!-- omit comment -->
<pre>  x = 1
  y = 2</pre><h2>Next</h2><p>more</p></body></html>""",
        "doc.html",
    )
    text = "\n".join(block.text for block in doc.blocks)
    assert "Hello world <safe>." in text
    assert "omit" not in text
    assert doc.blocks[-1].section == "API & tools > Next"
    assert next(block for block in doc.blocks if block.kind == "code").text == "  x = 1\n  y = 2"
    for chunk in chunk_document(doc):
        assert chunk.source.line_start is None
        assert chunk.source.line_end is None
        assert chunk.source.page is None


def test_malformed_html_suppression_is_reported(tmp_path: Path) -> None:
    doc = document(tmp_path, b"<p>kept</p><script>hidden trailing", "doc.html")
    assert [block.text for block in doc.blocks] == ["kept"]
    assert "unclosed excluded HTML" in doc.warnings[0]


@pytest.mark.parametrize("raw", [b"\xff\xfea\x00", b"a\xff", b"a\x00b", b"\x01"])
def test_invalid_encoding_and_controls_are_not_replaced(tmp_path: Path, raw: bytes) -> None:
    with pytest.raises(ParseError, match="UTF-8|control"):
        document(tmp_path, raw, "doc.txt")


@pytest.mark.parametrize("raw", [b"", b" \n\t"])
def test_empty_documents_are_explicit_and_have_no_chunks(tmp_path: Path, raw: bytes) -> None:
    doc = document(tmp_path, raw)
    assert doc.warnings == ("no extractable text",)
    assert not chunk_document(doc)


@pytest.mark.parametrize("size,overlap", [(1, 0), (20, 0), (20, 5), (20, 19), (100, 10)])
def test_chunks_cover_nonblank_text_with_exact_provenance_and_bounds(
    tmp_path: Path, size: int, overlap: int
) -> None:
    doc = document(tmp_path, ("ћирилица café\n\nword " * 12).encode(), "doc.txt")
    config = ChunkConfig(chunk_size_chars=size, overlap_chars=overlap)
    chunks = chunk_document(doc, config)
    assert chunks == chunk_document(doc, config)
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
    covered: set[int] = set()
    text = doc.blocks[0].text
    for ordinal, chunk in enumerate(chunks):
        assert chunk.ordinal == ordinal
        assert len(chunk.text) <= size
        assert chunk.text == text[chunk.char_start : chunk.char_end]
        assert chunk.source.line_start == 1 + text[: chunk.char_start].count("\n")
        assert chunk.source.line_end == 1 + text[: chunk.char_end - 1].count("\n")
        covered.update(range(chunk.char_start, chunk.char_end))
    assert all(index in covered for index, char in enumerate(text) if not char.isspace())


def test_pipeline_and_content_changes_invalidate_chunk_ids(tmp_path: Path) -> None:
    doc = document(tmp_path, b"same text\r\n", "doc.txt")
    config = ChunkConfig()
    first = chunk_document(doc)[0].chunk_id
    assert chunk_document(doc, ChunkConfig(overlap_chars=50))[0].chunk_id != first
    assert chunk_document(replace(doc, parser_version="text-v2"))[0].chunk_id != first
    updated = document(tmp_path, b"same text\n", "doc.txt")
    assert updated.blocks == doc.blocks
    assert chunk_document(updated)[0].chunk_id != first
    payload = [
        "ragforge-chunk-v1",
        doc.record.document_id,
        doc.record.content_sha256,
        pipeline_hash(doc, config),
        0,
    ]
    expected = hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
    assert first == expected


def test_chunk_limit_and_config_errors_are_explicit(tmp_path: Path) -> None:
    doc = document(tmp_path, b"abcdefghij", "doc.txt")
    with pytest.raises(ValueError, match="max_chunks"):
        chunk_document(doc, ChunkConfig(chunk_size_chars=1, overlap_chars=0), max_chunks=2)
    with pytest.raises(ValidationError):
        ChunkConfig(chunk_size_chars=10, overlap_chars=10)
    with pytest.raises(ValidationError):
        ChunkConfig(chunk_size_chars=100001)
    with pytest.raises(ValueError, match="max_chunks"):
        chunk_document(doc, max_chunks=True)


def test_loader_checks_same_bytes_and_limits_again(tmp_path: Path) -> None:
    raw = b"# title\noriginal"
    (tmp_path / "doc.md").write_bytes(raw)
    record = scan_corpus(tmp_path, "mini").documents[0]
    assert load_document(tmp_path, "mini", record).blocks[0].text == raw.decode()
    with pytest.raises(ParseError, match="max_file_bytes"):
        load_document(tmp_path, "mini", record, ScanLimits(max_file_bytes=1))
    (tmp_path / "doc.md").write_bytes(b"# title\nmodified")
    with pytest.raises(ParseError, match="since scan"):
        load_document(tmp_path, "mini", record)
    with pytest.raises(ParseError, match="identity"):
        load_document(tmp_path, "other", record)
    with pytest.raises(ParseError, match="bytes do not match"):
        parse_document("mini", record, b"forged content")


def test_line_separators_other_than_lf_do_not_invent_physical_lines(tmp_path: Path) -> None:
    doc = document(tmp_path, "a\u2028b\fc\nd\n".encode(), "doc.txt")
    assert doc.blocks[0].line_end == 2
    assert chunk_document(doc)[0].source.line_end == 2


def test_pdf_is_explicitly_unsupported_until_adapter_exists(tmp_path: Path) -> None:
    with pytest.raises(ParseError, match="RF-007"):
        document(tmp_path, b"%PDF fixture not parsed", "doc.pdf")


def test_chunk_cli_is_json_and_failures_have_no_partial_stdout(tmp_path: Path) -> None:
    (tmp_path / "doc.md").write_text("# Evidence\nreliable text\n", encoding="utf-8")
    runner = CliRunner()
    good = runner.invoke(app, ["chunk", str(tmp_path), "--collection", "mini"])
    assert good.exit_code == 0, good.output
    report = json.loads(good.stdout)
    assert report["chunks"][0]["source"]["line_start"] == 1
    assert report["documents"][0]["chunk_count"] == 1
    small = runner.invoke(app, ["chunk", str(tmp_path), "--max-output-chars", "1"])
    assert small.exit_code == 2
    assert small.stdout == ""
    assert "max_output_chars" in json.loads(small.stderr)["error"]
    (tmp_path / "bad.pdf").write_bytes(b"%PDF")
    bad = runner.invoke(app, ["chunk", str(tmp_path)])
    assert bad.exit_code == 2
    assert bad.stdout == ""
    assert "RF-007" in json.loads(bad.stderr)["error"]


def test_overlap_output_budget_is_enforced_before_accumulating_chunks(tmp_path: Path) -> None:
    doc = document(tmp_path, b"x" * 1000, "doc.txt")
    config = ChunkConfig(chunk_size_chars=100, overlap_chars=99)
    with pytest.raises(ValueError, match="max_output_chars"):
        chunk_document(doc, config, max_output_chars=150)


def test_empty_document_after_exact_chunk_budget_is_still_reported(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("evidence")
    (tmp_path / "b.txt").write_bytes(b"")
    result = CliRunner().invoke(app, ["chunk", str(tmp_path), "--max-chunks", "1"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["documents"][1]["warnings"] == ["no extractable text"]
