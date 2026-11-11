import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ragforge.cli import app
from ragforge.core.scan import ScanError, ScanLimits, scan_corpus


def test_mixed_scan_is_sorted_repeatable_and_content_independent(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    for name in ["z.PDF", "nested/ćirilica.md", "b.html", "a.txt", "empty.htm"]:
        (tmp_path / name).write_bytes(b"" if name == "empty.htm" else b"same contents")
    (tmp_path / "ignored.exe").write_bytes(b"not executed")
    first = scan_corpus(tmp_path, "mini")
    assert first == scan_corpus(tmp_path, "mini")
    assert [d.source_path for d in first.documents] == [
        "a.txt",
        "b.html",
        "empty.htm",
        "nested/ćirilica.md",
        "z.PDF",
    ]
    assert first.ignored_paths == ["ignored.exe"]
    assert len({d.document_id for d in first.documents}) == 5
    assert first.total_bytes == 4 * len(b"same contents")
    assert first.documents[2].content_sha256 == hashlib.sha256(b"").hexdigest()
    (tmp_path / "a.txt").write_bytes(b"updated")
    changed = scan_corpus(tmp_path, "mini").documents[0]
    assert changed.document_id == first.documents[0].document_id
    assert changed.content_sha256 != first.documents[0].content_sha256
    assert scan_corpus(tmp_path, "other").documents[0].document_id != changed.document_id


@pytest.mark.parametrize("limit", ["file", "total", "entries"])
def test_limits_fail_entire_scan(tmp_path: Path, limit: str) -> None:
    (tmp_path / "a.txt").write_bytes(b"1234")
    (tmp_path / "b.txt").write_bytes(b"1234")
    limits = {
        "file": ScanLimits(max_file_bytes=3),
        "total": ScanLimits(max_total_bytes=7),
        "entries": ScanLimits(max_entries=1),
    }
    with pytest.raises(ScanError, match=f"max_{limit if limit != 'total' else 'total'}"):
        scan_corpus(tmp_path, "mini", limits[limit])


def test_empty_corpus_and_exact_byte_limit(tmp_path: Path) -> None:
    assert scan_corpus(tmp_path, "mini").documents == []
    (tmp_path / "a.txt").write_bytes(b"1234")
    assert scan_corpus(tmp_path, "mini", ScanLimits(4, 4, 1)).total_bytes == 4


@pytest.mark.parametrize("value", [0, -1, True])
def test_bad_limits_rejected(value: int) -> None:
    with pytest.raises(ValueError):
        ScanLimits(max_entries=value)


def test_case_distinct_sources_are_never_silently_merged(tmp_path: Path) -> None:
    (tmp_path / "A.md").write_text("first")
    (tmp_path / "a.MD").write_text("second")
    if len(list(tmp_path.iterdir())) == 1:
        pytest.skip("case-insensitive filesystem cannot create the collision")
    report = scan_corpus(tmp_path, "mini")
    assert [d.source_path for d in report.documents] == ["A.md", "a.MD"]
    assert len({d.document_id for d in report.documents}) == 2
    assert len({d.content_sha256 for d in report.documents}) == 2
    assert scan_corpus(tmp_path, "mini") == report


def test_non_nfc_source_is_not_silently_renamed(tmp_path: Path) -> None:
    path = tmp_path / "cafe\u0301.md"
    path.write_text("content")
    if list(tmp_path.iterdir())[0].name != path.name:
        pytest.skip("filesystem normalizes names")
    with pytest.raises(ScanError, match="nonportable"):
        scan_corpus(tmp_path, "mini")


@pytest.mark.parametrize("directory", [False, True])
def test_links_cannot_import_external_sources(tmp_path: Path, directory: bool) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    outside = tmp_path / ("outside" if directory else "outside.txt")
    if directory:
        outside.mkdir()
    else:
        outside.write_text("secret")
    link = corpus / ("link" if directory else "link.txt")
    try:
        link.symlink_to(outside, target_is_directory=directory)
    except OSError:
        pytest.skip("creating symlinks requires local privileges")
    with pytest.raises(ScanError, match="reparse|symlink"):
        scan_corpus(corpus, "mini")


@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
def test_windows_junction_cannot_import_external_directory(tmp_path: Path) -> None:
    corpus, outside = tmp_path / "corpus", tmp_path / "outside"
    corpus.mkdir()
    outside.mkdir()
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(corpus / "junction"), str(outside)],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    with pytest.raises(ScanError, match="reparse"):
        scan_corpus(corpus, "mini")


def test_scan_does_not_hide_missing_sources(tmp_path: Path) -> None:
    with pytest.raises(ScanError, match="cannot complete"):
        scan_corpus(tmp_path / "missing", "mini")


def test_read_failure_does_not_produce_partial_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.txt").write_text("good")
    (tmp_path / "b.txt").write_text("unreadable")
    original = os.open

    def fail(path: Path, flags: int) -> int:
        if path.name == "b.txt":
            raise PermissionError("fixture denied")
        return original(path, flags)

    monkeypatch.setattr(os, "open", fail)
    with pytest.raises(ScanError, match="fixture denied"):
        scan_corpus(tmp_path, "mini")


def test_file_replacement_during_scan_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.txt").write_text("original")
    original = os.open

    def replace(path: Path, flags: int) -> int:
        replacement = tmp_path / "replacement"
        replacement.write_text("changed")
        replacement.replace(path)
        return original(path, flags)

    monkeypatch.setattr(os, "open", replace)
    with pytest.raises(ScanError, match="changed while opening"):
        scan_corpus(tmp_path, "mini")


def test_cli_scan_outputs_json_and_nonzero_error_without_partial_stdout(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("evidence")
    runner = CliRunner()
    good = runner.invoke(app, ["scan", str(tmp_path), "--collection", "mini"])
    assert good.exit_code == 0, good.output
    assert json.loads(good.stdout)["documents"][0]["source_path"] == "a.md"
    bad = runner.invoke(app, ["scan", str(tmp_path), "--max-file-bytes", "1"])
    assert bad.exit_code == 2
    assert bad.stdout == ""
    assert "max_file_bytes" in json.loads(bad.stderr)["error"]
