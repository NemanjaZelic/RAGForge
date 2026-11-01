"""Resume-safe parsing journal, source-bound cached documents, and worker lifecycle."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import closing, contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, TypeAdapter

from ragforge.core.parse import HTML_PARSER_VERSION, PARSER_VERSION, ParsedDocument, TextOptions
from ragforge.core.pdf import PDF_PARSER_VERSION, PdfOptions
from ragforge.core.scan import ScanLimits, ScannedDocument, ScanReport, scan_corpus
from ragforge.core.source import is_link
from ragforge.jobs.budget import StorageBudget
from ragforge.types import ContractModel, Identifier

ADAPTER = TypeAdapter(ParsedDocument)
MAX_PAYLOAD_BYTES = 256 * 1024**2
SCHEMA = """
CREATE TABLE configuration(id INTEGER PRIMARY KEY CHECK(id=1), json TEXT NOT NULL);
CREATE TABLE parsed(
    document_id TEXT PRIMARY KEY, source_path TEXT NOT NULL, source_sha256 TEXT NOT NULL,
    status TEXT NOT NULL, payload BLOB, payload_sha256 TEXT, error TEXT,
    elapsed_seconds REAL NOT NULL, text_chars INTEGER NOT NULL,
    pages INTEGER NOT NULL, lost_pages INTEGER NOT NULL
);
"""


class IngestConfiguration(ContractModel):
    schema_version: Literal["1"] = "1"
    collection_id: Identifier
    snapshot_sha256: str
    document_count: Annotated[int, Field(ge=1)]
    scan_limits: dict[str, int]
    pdf_options: PdfOptions
    text_options: TextOptions = Field(default_factory=TextOptions)
    pdf_backend: Literal["pypdf", "pdfium"]
    parser_version: str
    worker_memory_mib: Annotated[int, Field(ge=128, le=4096)] = 512
    document_timeout_seconds: Annotated[int, Field(ge=1, le=86400)] = 300


def configuration(
    report: ScanReport,
    limits: ScanLimits,
    options: PdfOptions,
    backend: Literal["pypdf", "pdfium"],
    memory: int,
    timeout: int,
    text_options: TextOptions | None = None,
) -> IngestConfiguration:
    snapshot = hashlib.sha256(report.model_dump_json().encode()).hexdigest()
    version = (
        PDF_PARSER_VERSION
        if backend == "pypdf"
        else ("pdf-pdfium-" + importlib.metadata.version("pypdfium2"))
    )
    return IngestConfiguration(
        collection_id=report.collection_id,
        snapshot_sha256=snapshot,
        document_count=len(report.documents),
        scan_limits=asdict(limits),
        pdf_options=options,
        text_options=text_options or TextOptions(),
        pdf_backend=backend,
        parser_version=PARSER_VERSION + ";" + HTML_PARSER_VERSION + ";" + version,
        worker_memory_mib=memory,
        document_timeout_seconds=timeout,
    )


@contextmanager
def job_lock(job: Path) -> Iterator[None]:
    # The OS releases this lock after a crash; the persistent inode is not a stale lock.
    path = job / "writer.lock"
    if path.exists() and is_link(path.lstat()):
        raise ValueError("job lock must not be a link")
    with path.open("a+b") as stream:
        if path.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if sys.platform == "win32":
            import msvcrt

            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise ValueError("ingestion job already has a writer") from error
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise ValueError("ingestion job already has a writer") from error
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class ParseWorker:
    def __init__(self, job: Path, config: IngestConfiguration) -> None:
        self.config = config
        self.error_log = (job / "worker.log").open("ab")
        self.process: subprocess.Popen[str] | None = None
        self.reader = ThreadPoolExecutor(max_workers=1)
        self.tasks = 0

    def stop(self) -> None:
        process, self.process = self.process, None
        if process is not None:
            if process.poll() is None:
                if sys.platform == "win32":
                    # The Windows venv redirector may own a child interpreter.
                    # Terminate only this private worker tree, including that child.
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        timeout=10,
                        check=False,
                    )
                else:
                    process.kill()
            process.wait(timeout=10)
            if process.stdin:
                process.stdin.close()
            if process.stdout:
                process.stdout.close()

    def close(self) -> None:
        self.stop()
        self.reader.shutdown(wait=True, cancel_futures=True)
        self.error_log.close()

    def parse(self, root: Path, record: ScannedDocument) -> ParsedDocument:
        if self.process is None or self.tasks >= 25:
            self.stop()
            self.process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "ragforge.jobs.worker",
                    "--memory-mib",
                    str(self.config.worker_memory_mib),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self.error_log,
                text=True,
                encoding="utf-8",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            self.tasks = 0
        process = self.process
        assert process.stdin is not None and process.stdout is not None
        task = {
            "root": str(root),
            "record": record.model_dump(mode="json"),
            "collection_id": self.config.collection_id,
            "scan_limits": self.config.scan_limits,
            "pdf_options": self.config.pdf_options.model_dump(mode="json"),
            "text_options": self.config.text_options.model_dump(mode="json"),
            "pdf_backend": self.config.pdf_backend,
        }
        try:
            process.stdin.write(json.dumps(task, ensure_ascii=True) + "\n")
            process.stdin.flush()
            result = self.reader.submit(process.stdout.readline, MAX_PAYLOAD_BYTES + 1)
            line = result.result(timeout=self.config.document_timeout_seconds)
            if not line or len(line) > MAX_PAYLOAD_BYTES or not line.endswith("\n"):
                raise ValueError("parsing worker exited or exceeded payload budget")
            response = json.loads(line)
            if "error" in response:
                raise ValueError(response["error"])
            document = ADAPTER.validate_python(response["document"])
            if document.record != record or document.collection_id != self.config.collection_id:
                raise ValueError("worker returned mismatched source identity")
            self.tasks += 1
            return document
        except TimeoutError as error:
            self.stop()
            raise ValueError("document wall-time budget exceeded; worker terminated") from error
        except (OSError, ValueError):
            self.stop()
            raise


def read_configuration(job: Path) -> IngestConfiguration:
    database = job / "parsed.sqlite"
    if is_link(job.lstat()) or is_link(database.lstat()):
        raise ValueError("ingestion job and database must not be links")
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA query_only=ON")
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1024**2)
        row = connection.execute("SELECT json FROM configuration WHERE id=1").fetchone()
        if row is None:
            raise ValueError("missing ingestion configuration")
        return IngestConfiguration.model_validate_json(row[0])


def ingest_corpus(
    source: Path,
    job: Path,
    *,
    collection_id: str,
    limits: ScanLimits | None = None,
    pdf_options: PdfOptions | None = None,
    text_options: TextOptions | None = None,
    pdf_backend: Literal["pypdf", "pdfium"] = "pypdf",
    resume: bool = False,
    retry_failed: bool = False,
    continue_on_error: bool = False,
    worker_memory_mib: int = 512,
    document_timeout_seconds: int = 300,
    storage: StorageBudget | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    limits, options = limits or ScanLimits(), pdf_options or PdfOptions()
    source = source.resolve(strict=True)
    job = job.absolute()
    if job.resolve().is_relative_to(source) or source.is_relative_to(job.resolve()):
        raise ValueError("ingestion job and source directories must be separate")
    if storage and not job.resolve().is_relative_to(storage.root):
        raise ValueError("job must remain inside its aggregate storage root")
    if job.exists():
        if not resume or is_link(job.lstat()):
            raise ValueError("existing job requires explicit --resume and a real directory")
    else:
        if resume:
            raise ValueError("cannot resume a missing ingestion job")
        job.mkdir(parents=True)
    with job_lock(job):
        report = scan_corpus(source, collection_id, limits)
        if not report.documents:
            raise ValueError("corpus contains no supported documents")
        config = configuration(
            report,
            limits,
            options,
            pdf_backend,
            worker_memory_mib,
            document_timeout_seconds,
            text_options,
        )
        database = job / "parsed.sqlite"
        if database.exists():
            previous = read_configuration(job)
            operational = {"worker_memory_mib", "document_timeout_seconds", "text_options"}
            safe_policy_upgrade = previous.text_options.fallback_encoding in {
                "none",
                config.text_options.fallback_encoding,
            } and previous.text_options.control_characters in {
                "reject",
                config.text_options.control_characters,
            }
            if (
                previous.model_dump(exclude=operational) != config.model_dump(exclude=operational)
                or not safe_policy_upgrade
            ):
                raise ValueError(
                    "source snapshot or ingestion configuration changed; use a new job"
                )
            if previous != config:
                # These upgrades only affect previously rejected inputs; successful
                # UTF-8/control-free parses are byte-for-byte identical under both.
                with closing(sqlite3.connect(database)) as connection, connection:
                    connection.execute(
                        "UPDATE configuration SET json=? WHERE id=1", (config.model_dump_json(),)
                    )

        else:
            with closing(sqlite3.connect(database)) as connection:
                connection.executescript(SCHEMA)
                with connection:
                    connection.execute(
                        "INSERT INTO configuration VALUES(1,?)", (config.model_dump_json(),)
                    )
        worker = ParseWorker(job, config)
        started = time.monotonic()
        try:
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("PRAGMA trusted_schema=OFF")
                for index, record in enumerate(report.documents):
                    existing = connection.execute(
                        "SELECT status FROM parsed WHERE document_id=?", (record.document_id,)
                    ).fetchone()
                    if existing and (existing[0] != "error" or not retry_failed):
                        continue
                    if storage:
                        storage.check(2 * MAX_PAYLOAD_BYTES)
                    before = database.stat().st_size
                    start = time.monotonic()
                    payload = error = checksum = None
                    chars = pages = lost = 0
                    status = "error"
                    try:
                        document = worker.parse(source, record)
                        payload = ADAPTER.dump_json(document)
                        if len(payload) > MAX_PAYLOAD_BYTES:
                            raise ValueError("parsed document exceeds cache payload budget")
                        checksum = hashlib.sha256(payload).hexdigest()
                        chars = sum(len(block.text) for block in document.blocks)
                        pages = len(document.page_reports)
                        lost = sum(r.status != "extracted" for r in document.page_reports)
                        status = "partial" if lost else ("complete" if chars else "no_text")
                    except (OSError, ValueError) as exception:
                        payload = None
                        error = str(exception)[:2000]
                    with connection:
                        connection.execute(
                            "INSERT OR REPLACE INTO parsed VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                record.document_id,
                                record.source_path,
                                record.content_sha256,
                                status,
                                payload,
                                checksum,
                                error,
                                time.monotonic() - start,
                                chars,
                                pages,
                                lost,
                            ),
                        )
                    if storage:
                        storage.account(database.stat().st_size - before)
                    event = {
                        "attempted": index + 1,
                        "total": len(report.documents),
                        "source_path": record.source_path,
                        "status": status,
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                    }
                    if error:
                        event["error"] = error
                    if progress:
                        progress(event)
                    if status == "error" and not continue_on_error:
                        raise ValueError(
                            "document failed; inspect job-status and explicitly retry/resume"
                        )
        finally:
            worker.close()
        return job_status(job)


def job_status(job: Path) -> dict[str, Any]:
    config = read_configuration(job)
    with closing(
        sqlite3.connect((job / "parsed.sqlite").resolve().as_uri() + "?mode=ro", uri=True)
    ) as c:
        statuses = dict(c.execute("SELECT status,count(*) FROM parsed GROUP BY status"))
        totals = c.execute(
            "SELECT count(*),coalesce(sum(text_chars),0),coalesce(sum(pages),0),"
            "coalesce(sum(lost_pages),0),coalesce(sum(elapsed_seconds),0) FROM parsed"
        ).fetchone()
        failures = [
            dict(zip(("source_path", "error"), row, strict=True))
            for row in c.execute(
                "SELECT source_path,error FROM parsed WHERE status='error' ORDER BY source_path"
            )
        ]
    return {
        "job": str(job.absolute()),
        "collection_id": config.collection_id,
        "snapshot_sha256": config.snapshot_sha256,
        "attempted_documents": totals[0],
        "expected_documents": config.document_count,
        "pending_documents": config.document_count - totals[0],
        "status_counts": statuses,
        "text_chars": totals[1],
        "pages": totals[2],
        "lost_pages": totals[3],
        "document_seconds": round(totals[4], 3),
        "failures": failures,
        "strict_ready": totals[0] == config.document_count
        and statuses.get("error", 0) == 0
        and statuses.get("partial", 0) == 0
        and statuses.get("no_text", 0) == 0,
    }


def cached_documents(job: Path, report: ScanReport) -> Iterator[ParsedDocument]:
    config = read_configuration(job)
    if config.snapshot_sha256 != hashlib.sha256(report.model_dump_json().encode()).hexdigest():
        raise ValueError("cached source snapshot does not match current scan")
    with closing(
        sqlite3.connect((job / "parsed.sqlite").resolve().as_uri() + "?mode=ro", uri=True)
    ) as c:
        c.execute("PRAGMA trusted_schema=OFF")
        c.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_PAYLOAD_BYTES + 16384)
        for record in report.documents:
            row = c.execute(
                "SELECT status,payload,payload_sha256 FROM parsed WHERE document_id=?",
                (record.document_id,),
            ).fetchone()
            if row is None or row[0] == "error" or row[1] is None:
                raise ValueError("cache has pending/failed document; full-source build refused")
            if hashlib.sha256(row[1]).hexdigest() != row[2]:
                raise ValueError("parsed cache payload checksum mismatch")
            document = ADAPTER.validate_json(row[1])
            if document.record != record or document.collection_id != report.collection_id:
                raise ValueError("parsed cache identity does not match current source")
            yield document
