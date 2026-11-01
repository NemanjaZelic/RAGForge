"""Local staging builder. Build never downloads models or deploys services."""

import ctypes
import importlib.metadata
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Literal

from ragforge import __version__
from ragforge.artifacts.manifest import (
    BuildConfiguration,
    BundleManifest,
    CollectionManifest,
    DenseIndex,
    DocumentRecord,
    FileRecord,
    QueryModel,
    RuntimeRequirements,
)
from ragforge.artifacts.verification import build_identity, bundle_files, verify_bundle
from ragforge.core.chunk import CHUNKER_VERSION, ChunkConfig
from ragforge.core.embedding import ONNXEmbedder, file_hash, model_spec
from ragforge.core.limits import MAX_DENSE_ROWS
from ragforge.core.parse import load_document
from ragforge.core.pdf import PdfOptions
from ragforge.core.scan import ScanLimits, scan_corpus
from ragforge.core.source import is_link
from ragforge.core.sqlite import SQLiteEngine, create_index


def publish_new(stage: Path, output: Path) -> None:
    """Atomic no-replace publish, including an empty directory created by a peer."""
    if stage.resolve().parent != output.parent.resolve():
        raise ValueError("publication must stay within the staging parent")
    if sys.platform == "win32":
        os.rename(stage, output)
    elif sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            raise OSError("atomic no-replace publication requires Linux renameat2")
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(stage), -100, os.fsencode(output), 1) != 0:
            number = ctypes.get_errno()
            raise OSError(number, os.strerror(number), str(output))
    else:
        raise OSError("bundle publishing currently supports Windows and Linux")


def build_bundle(
    source: Path,
    output: Path,
    *,
    collection_id: str = "default",
    title: str = "Documents",
    profile: Literal["minimal", "balanced"] = "balanced",
    model_directory: Path | None = None,
    chunk_config: ChunkConfig | None = None,
    scan_limits: ScanLimits | None = None,
    allow_incomplete: bool = False,
    threads: int = 4,
    pdf_options: PdfOptions | None = None,
    ingest_job: Path | None = None,
    max_index_chunks: int = 100000,
    max_index_text_chars: int = 100000000,
) -> BundleManifest:
    if ingest_job is not None:
        from ragforge.jobs.ingest import read_configuration

        cached = read_configuration(ingest_job)
        if cached.collection_id != collection_id:
            raise ValueError("ingestion cache belongs to another collection")
        if pdf_options is not None and pdf_options != cached.pdf_options:
            raise ValueError("PDF configuration must match the ingestion job")
        if scan_limits is not None and scan_limits != ScanLimits(**cached.scan_limits):
            raise ValueError("scan configuration must match the ingestion job")
        pdf_options = cached.pdf_options
        scan_limits = ScanLimits(**cached.scan_limits)
    if not 1 <= max_index_chunks <= MAX_DENSE_ROWS or max_index_text_chars < 1:
        raise ValueError("invalid index chunk/text capacity")
    config = chunk_config or ChunkConfig()
    limits = scan_limits or ScanLimits()
    if profile not in ("minimal", "balanced"):
        raise ValueError("unsupported build profile")
    if profile == "balanced" and model_directory is None:
        raise ValueError("balanced build requires an explicitly prepared local --model directory")
    if profile == "minimal" and model_directory is not None:
        raise ValueError("minimal build does not package a model")
    if not 1 <= config.chunk_size_chars <= 100000:
        raise ValueError("unsupported chunk size")
    if is_link(source.lstat()):
        raise ValueError("corpus root must not be a link")
    source = source.resolve(strict=True)
    output = output.absolute()
    if output.resolve().is_relative_to(source):
        raise ValueError("bundle output must be outside corpus root")
    if os.path.lexists(output):
        raise FileExistsError("bundle output already exists; choose a new version directory")
    report = scan_corpus(source, collection_id, limits)
    if not report.documents:
        raise ValueError("corpus contains no supported documents")
    output.parent.mkdir(parents=True, exist_ok=True)
    parent = output.parent.resolve(strict=True)
    output = parent / output.name
    stage = Path(tempfile.mkdtemp(prefix=".ragforge-stage-", dir=parent)).resolve()
    try:
        collection_path = stage / "collections" / collection_id
        collection_path.mkdir(parents=True)
        database = collection_path / "index.sqlite"
        if ingest_job is not None:
            from ragforge.jobs.ingest import cached_documents

            documents = cached_documents(ingest_job, report)
        else:
            documents = (
                load_document(source, collection_id, record, limits, pdf_options=pdf_options)
                for record in report.documents
            )
        summary = create_index(
            database,
            collection_id,
            title,
            documents,
            config,
            allow_incomplete=allow_incomplete,
            max_chunks=max_index_chunks,
            max_output_chars=max_index_text_chars,
        )
        if not summary.chunk_count:
            raise ValueError("corpus contains no searchable text chunks")
        dense = None
        query_model = None
        capabilities: list[Literal["bm25", "dense", "hybrid"]] = ["bm25"]
        licenses = ["NOASSERTION: RAGForge project and user-supplied corpus"]
        if profile == "balanced":
            from ragforge.core.dense import BACKEND, BACKEND_VERSION, write_dense

            assert model_directory is not None
            spec = model_spec(model_directory)
            model_root = stage / "models/query"
            model_root.mkdir(parents=True)
            model_paths = [str(record.path) for record in spec.files] + ["model.json"]
            for relative in model_paths:
                destination = model_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(model_directory / relative, destination)
            embedder = ONNXEmbedder(model_root, threads=threads)
            write_dense(database, collection_path / "dense.index", embedder)
            del embedder
            dense = DenseIndex(
                path=f"collections/{collection_id}/dense.index",
                backend=BACKEND,
                backend_version=BACKEND_VERSION,
                dimensions=spec.dimensions,
                metric="cosine",
            )
            query_model = QueryModel(
                model_id=spec.model_id,
                revision=spec.revision,
                dimensions=spec.dimensions,
                runtime="onnxruntime-cpu",
                runtime_version=importlib.metadata.version("onnxruntime"),
                files=["models/query/" + path for path in sorted(model_paths)],
                license=spec.license,
            )
            capabilities = ["bm25", "dense", "hybrid"]
            licenses.append(spec.license + ": local query model; see models/query/LICENSE")
        records = [
            FileRecord(path=relative, sha256=file_hash(path), size_bytes=path.stat().st_size)
            for relative, path in sorted(bundle_files(stage).items())
        ]
        engine = SQLiteEngine(database)
        with engine._connect() as connection:
            versions = [
                str(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT parser_version FROM documents ORDER BY parser_version"
                )
            ]
        manifest = BundleManifest(
            artifact_schema_version="1",
            build_id="0" * 64,
            producer_version=__version__,
            profile=profile,
            capabilities=capabilities,
            default_search_method="hybrid" if profile == "balanced" else "bm25",
            query_model=query_model,
            index_backend="sqlite-fts5",
            index_schema_version=1,
            sqlite_build_version=sqlite3.sqlite_version,
            collections=[
                CollectionManifest(
                    collection_id=collection_id,
                    title=title,
                    database_path=f"collections/{collection_id}/index.sqlite",
                    dense_index=dense,
                    documents=[
                        DocumentRecord(
                            document_id=record.document_id,
                            source_path=record.source_path,
                            content_sha256=record.content_sha256,
                        )
                        for record in report.documents
                    ],
                )
            ],
            files=records,
            licenses=licenses,
            build_configuration=BuildConfiguration(
                pdf_options=(pdf_options or PdfOptions())
                if any(r.format == "pdf" for r in report.documents)
                else None,
                parser_version=";".join(versions),
                chunker_version=CHUNKER_VERSION,
                chunk_size_chars=config.chunk_size_chars,
                overlap_chars=config.overlap_chars,
            ),
            runtime=RuntimeRequirements(python_min="3.11", requires_fts5=True, adapters=["cli"]),
        )
        manifest.build_id = build_identity(manifest)
        (stage / "manifest.json").write_text(
            manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        verify_bundle(stage)
        publish_new(stage, output)
        return manifest
    finally:
        # Delete only this call's private staging directory inside the checked parent.
        if stage.exists():
            if (
                stage.resolve().parent != parent
                or is_link(stage.lstat())
                or not stage.name.startswith(".ragforge-stage-")
            ):
                raise ValueError("refusing cleanup outside owned staging directory")
            shutil.rmtree(stage)
