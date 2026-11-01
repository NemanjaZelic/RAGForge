import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ragforge.artifacts.builder import build_bundle
from ragforge.cli import app
from ragforge.core.chunk import chunk_document, iter_chunks
from ragforge.core.contracts import RetrieveRequest
from ragforge.core.engine import BundleEngine
from ragforge.core.pdf import PdfOptions
from ragforge.core.scan import ScanLimits, scan_corpus
from ragforge.jobs.budget import StorageBudget
from ragforge.jobs.ingest import (
    ParseWorker,
    cached_documents,
    configuration,
    ingest_corpus,
    job_lock,
    job_status,
)

PDF = Path(__file__).parent / "fixtures/pdf/structured.pdf"


def test_worker_cache_build_and_streamed_chunks_match_direct_engine(tmp_path: Path):
    root = tmp_path / "source"
    root.mkdir()
    shutil.copyfile(PDF, root / "manual.pdf")
    (root / "readme.txt").write_text("transaction rollback and retry policy", encoding="utf-8")
    job = tmp_path / "ingest"
    result = ingest_corpus(root, job, collection_id="docs")
    assert result["attempted_documents"] == 2 and result["strict_ready"]
    assert result["pending_documents"] == 0
    documents = list(cached_documents(job, scan_corpus(root, "docs")))
    assert all(list(iter_chunks(d)) == chunk_document(d) for d in documents)
    first = build_bundle(root, tmp_path / "direct", collection_id="docs", profile="minimal")
    second = build_bundle(
        root,
        tmp_path / "cached",
        collection_id="docs",
        profile="minimal",
        ingest_job=job,
    )
    assert first.build_id == second.build_id
    assert BundleEngine(tmp_path / "direct").retrieve(RetrieveRequest(query="rollback")) == (
        BundleEngine(tmp_path / "cached").retrieve(RetrieveRequest(query="rollback"))
    )


def test_interrupted_job_resumes_and_rejects_changed_sources(tmp_path: Path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "a.txt").write_text("first source")
    (root / "b.txt").write_text("second source")
    job = tmp_path / "job"

    def interrupt(event):
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        ingest_corpus(root, job, collection_id="docs", progress=interrupt)
    result = job_status(job)
    assert result["attempted_documents"] == result["pending_documents"] == 1
    assert not result["strict_ready"]
    assert ingest_corpus(root, job, collection_id="docs", resume=True)["strict_ready"]
    with pytest.raises(ValueError, match="existing job"):
        ingest_corpus(root, job, collection_id="docs")
    (root / "b.txt").write_text("modified source")
    with pytest.raises(ValueError, match="changed"):
        ingest_corpus(root, job, collection_id="docs", resume=True)
    with pytest.raises(ValueError, match="snapshot"):
        list(cached_documents(job, scan_corpus(root, "docs")))


def test_failures_are_counted_and_never_disappear_from_full_build(tmp_path: Path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "a.txt").write_bytes(b"\xffbad UTF-8")
    (root / "b.txt").write_text("valid document")
    job = tmp_path / "job"
    result = ingest_corpus(root, job, collection_id="docs", continue_on_error=True)
    assert result["status_counts"] == {"complete": 1, "error": 1}
    assert not result["strict_ready"] and result["pending_documents"] == 0
    assert result["failures"][0]["source_path"] == "a.txt"
    with pytest.raises(ValueError, match="failed document"):
        build_bundle(
            root, tmp_path / "bundle", collection_id="docs", profile="minimal", ingest_job=job
        )
    assert not (tmp_path / "bundle").exists()
    assert not list(tmp_path.glob(".ragforge-stage-*"))


def test_pdfium_worker_preserves_physical_pages_and_reports_image_only(tmp_path: Path):
    root = tmp_path / "source"
    root.mkdir()
    shutil.copyfile(PDF, root / "manual.pdf")
    shutil.copyfile(PDF.parent / "image-only.pdf", root / "image.pdf")
    job = tmp_path / "job"
    result = ingest_corpus(root, job, collection_id="docs", pdf_backend="pdfium")
    assert result["status_counts"] == {"complete": 1, "partial": 1}
    assert result["pages"] == 3 and result["lost_pages"] == 1 and not result["strict_ready"]
    documents = list(cached_documents(job, scan_corpus(root, "docs")))
    manual = next(d for d in documents if d.record.source_path == "manual.pdf")
    assert [b.page for b in manual.blocks] == [1, 2]
    assert all(b.line_start is None for b in manual.blocks)
    assert "retry_limit" in manual.blocks[0].text
    assert manual.parser_version.startswith("pdf-pdfium-5.14.0-")
    with pytest.raises(ValueError, match="allow_incomplete"):
        build_bundle(
            root, tmp_path / "strict", collection_id="docs", profile="minimal", ingest_job=job
        )
    bundle = tmp_path / "partial"
    build_bundle(
        root,
        bundle,
        collection_id="docs",
        profile="minimal",
        ingest_job=job,
        allow_incomplete=True,
    )
    found = BundleEngine(bundle).retrieve(RetrieveRequest(query="retry_limit"))
    assert found.results[0].source.page == 1


def test_job_writer_lock_and_storage_budget_fail_closed(tmp_path: Path):
    with job_lock(tmp_path):
        with pytest.raises(ValueError, match="writer"):
            with job_lock(tmp_path):
                pass
    with job_lock(tmp_path):
        pass
    budget = StorageBudget(tmp_path, limit_bytes=100, reserve_free_bytes=0)
    assert budget.check(99) == 1
    with pytest.raises(ValueError, match="storage budget"):
        budget.check(100)
    (tmp_path / "other-process.bin").write_bytes(b"x" * 100)
    with pytest.raises(ValueError, match="storage budget"):
        budget.check(refresh=True)


def test_worker_deadline_terminates_actual_process(tmp_path: Path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    (root / "a.txt").write_text("source")
    report = scan_corpus(root, "docs")
    cfg = configuration(report, ScanLimits(), PdfOptions(), "pypdf", 512, 1)
    worker = ParseWorker(tmp_path, cfg)
    original = subprocess.Popen

    def sleeping_process(*args, **kwargs):
        return original([sys.executable, "-c", "import time;time.sleep(3600)"], **kwargs)

    monkeypatch.setattr(subprocess, "Popen", sleeping_process)
    try:
        with pytest.raises(ValueError, match="wall-time budget"):
            worker.parse(root, report.documents[0])
        assert worker.process is None
    finally:
        worker.close()


def test_actual_os_worker_memory_limit():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from ragforge.jobs.worker import limit_memory; limit_memory(128)\n"
            "try:\n x=bytearray(256*1024**2)\nexcept MemoryError:\n print('limited')",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "limited"


def test_cli_ingest_offline_and_job_status(tmp_path: Path, offline_cli):
    source = tmp_path / "source"
    source.mkdir()
    shutil.copyfile(PDF, source / "manual.pdf")
    job = tmp_path / "job"
    result = offline_cli(
        [
            "ingest",
            str(source),
            "--job",
            str(job),
            "--collection",
            "docs",
            "--pdf-backend",
            "pdfium",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["strict_ready"]
    status = CliRunner().invoke(app, ["job-status", str(job)])
    assert status.exit_code == 0 and json.loads(status.stdout)["attempted_documents"] == 1


def test_html_main_landmark_excludes_surrounding_navigation(tmp_path: Path):
    from ragforge.core.parse import load_document

    source = tmp_path / "source"
    source.mkdir()
    (source / "manual.html").write_text(
        '<nav>unrelated navigation</nav><div role="main"><h1>Manual</h1>'
        "<p>actual evidence</p><script>hidden instructions</script></div>"
        "<footer>unrelated footer</footer>",
        encoding="utf-8",
    )
    record = scan_corpus(source, "docs").documents[0]
    document = load_document(source, "docs", record)
    assert document.parser_version == "html-main-v2"
    assert [b.text for b in document.blocks] == ["Manual", "actual evidence"]
    assert all(b.line_start is None for b in document.blocks)


def test_explicit_legacy_policy_can_retry_only_failed_inputs(tmp_path: Path):
    import sqlite3

    from ragforge.core.parse import TextOptions

    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("unchanged UTF-8 evidence", encoding="utf-8")
    (source / "b.txt").write_bytes(b"caf\xe9\x08legacy")
    job = tmp_path / "job"
    first = ingest_corpus(source, job, collection_id="docs", continue_on_error=True)
    assert first["status_counts"] == {"complete": 1, "error": 1}
    with sqlite3.connect(job / "parsed.sqlite") as connection:
        before = connection.execute(
            "SELECT payload_sha256,elapsed_seconds FROM parsed WHERE source_path='a.txt'"
        ).fetchone()
    second = ingest_corpus(
        source,
        job,
        collection_id="docs",
        resume=True,
        retry_failed=True,
        text_options=TextOptions(fallback_encoding="latin-1", control_characters="escape"),
    )
    assert second["strict_ready"] and second["status_counts"] == {"complete": 2}
    with sqlite3.connect(job / "parsed.sqlite") as connection:
        assert (
            connection.execute(
                "SELECT payload_sha256,elapsed_seconds FROM parsed WHERE source_path='a.txt'"
            ).fetchone()
            == before
        )
    document = next(
        d
        for d in cached_documents(job, scan_corpus(source, "docs"))
        if d.record.source_path == "b.txt"
    )
    assert document.blocks[0].text == "café\\x08legacy"
    assert "encoding-latin-1;controls-escaped-v1" in document.parser_version
    assert len(document.warnings) == 2
    with pytest.raises(ValueError, match="configuration changed"):
        ingest_corpus(source, job, collection_id="docs", resume=True)
