"""Local staging builder. Build never downloads models or deploys services."""

import ctypes
import importlib.metadata
import os
import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Literal

from ragforge import __version__
from ragforge.artifacts.manifest import (
    BuildConfiguration,
    BundleManifest,
    CollectionManifest,
    DenseIndex,
    DocumentRecord,
    FileRecord,
    QueryModel,
    RerankerModel,
    RetrievalConfiguration,
    RuntimeRequirements,
)
from ragforge.artifacts.verification import build_identity, bundle_files, verify_bundle
from ragforge.core.chunk import ChunkConfig, chunker_version
from ragforge.core.embedding import ONNXEmbedder, file_hash, model_spec
from ragforge.core.limits import MAX_DENSE_ROWS
from ragforge.core.parse import load_document
from ragforge.core.pdf import PdfOptions
from ragforge.core.scan import ScanLimits, scan_corpus
from ragforge.core.source import is_link
from ragforge.core.sqlite import SQLiteEngine, create_index
from ragforge.jobs.budget import StorageBudget
from ragforge.jobs.build import BuildWorkspace
from ragforge.jobs.ingest import job_lock


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
    reranker_directory: Path | None = None,
    rerank_candidates: int = 100,
    max_chunks_per_document: int | None = None,
    chunk_config: ChunkConfig | None = None,
    scan_limits: ScanLimits | None = None,
    allow_incomplete: bool = False,
    allow_failed_documents: bool = False,
    threads: int = 4,
    pdf_options: PdfOptions | None = None,
    ingest_job: Path | None = None,
    max_index_chunks: int = 100000,
    max_index_text_chars: int = 100000000,
    dense_backend: Literal["exact", "ann"] = "exact",
    work_directory: Path | None = None,
    resume: bool = False,
    storage: StorageBudget | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> BundleManifest:
    """Hold exclusive job/cache ownership for every mutable build operation."""
    with ExitStack() as locks:
        if resume and work_directory is None:
            raise ValueError("resumable builds require --job")
        if ingest_job is not None:
            locks.enter_context(job_lock(ingest_job))
        if work_directory is not None:
            work_directory = work_directory.absolute()
            if (
                work_directory.resolve().is_relative_to(source.resolve())
                or source.resolve().is_relative_to(work_directory.resolve())
                or work_directory.resolve().is_relative_to(output.resolve())
                or output.resolve().is_relative_to(work_directory.resolve())
                or (ingest_job and work_directory.resolve() == ingest_job.resolve())
            ):
                raise ValueError("build job must be separate from source, cache and output")
            if work_directory.exists():
                if not resume or is_link(work_directory.lstat()):
                    raise ValueError("existing build job requires explicit --resume")
            else:
                if resume:
                    raise ValueError("cannot resume a missing build job")
                work_directory.mkdir(parents=True)
            if storage and not work_directory.resolve().is_relative_to(storage.root):
                raise ValueError("build job must remain inside the storage budget root")
            locks.enter_context(job_lock(work_directory))
        return _build_bundle(
            source,
            output,
            collection_id=collection_id,
            title=title,
            profile=profile,
            model_directory=model_directory,
            reranker_directory=reranker_directory,
            rerank_candidates=rerank_candidates,
            max_chunks_per_document=max_chunks_per_document,
            chunk_config=chunk_config,
            scan_limits=scan_limits,
            allow_incomplete=allow_incomplete,
            allow_failed_documents=allow_failed_documents,
            threads=threads,
            pdf_options=pdf_options,
            ingest_job=ingest_job,
            max_index_chunks=max_index_chunks,
            max_index_text_chars=max_index_text_chars,
            dense_backend=dense_backend,
            work_directory=work_directory,
            resume=resume,
            storage=storage,
            progress=progress,
        )


def _build_bundle(
    source: Path,
    output: Path,
    *,
    collection_id: str = "default",
    title: str = "Documents",
    profile: Literal["minimal", "balanced"] = "balanced",
    model_directory: Path | None = None,
    reranker_directory: Path | None = None,
    rerank_candidates: int = 100,
    max_chunks_per_document: int | None = None,
    chunk_config: ChunkConfig | None = None,
    scan_limits: ScanLimits | None = None,
    allow_incomplete: bool = False,
    allow_failed_documents: bool = False,
    threads: int = 4,
    pdf_options: PdfOptions | None = None,
    ingest_job: Path | None = None,
    max_index_chunks: int = 100000,
    max_index_text_chars: int = 100000000,
    dense_backend: Literal["exact", "ann"] = "exact",
    work_directory: Path | None = None,
    resume: bool = False,
    storage: StorageBudget | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> BundleManifest:
    if allow_failed_documents and (ingest_job is None or not allow_incomplete):
        raise ValueError("failed-document retention requires an ingestion job and allow_incomplete")
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
    if type(rerank_candidates) is not int or not 50 <= rerank_candidates <= 200:
        raise ValueError("rerank candidates must be between 50 and 200")
    if max_chunks_per_document is not None and (
        type(max_chunks_per_document) is not int or not 1 <= max_chunks_per_document <= 50
    ):
        raise ValueError("max chunks per document must be between 1 and 50")
    if max_chunks_per_document is not None and reranker_directory is None:
        raise ValueError("document diversity requires an explicit reranker")
    reranker_descriptor = None
    if reranker_directory is not None:
        from ragforge.core.rerank import reranker_spec

        reranker_descriptor = reranker_spec(reranker_directory)

    limits = scan_limits or ScanLimits()
    if dense_backend not in {"exact", "ann"} or (profile == "minimal" and dense_backend != "exact"):
        raise ValueError("invalid dense backend for bundle profile")
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
    if os.path.lexists(output) and not (resume and work_directory is not None):
        raise FileExistsError("bundle output already exists; choose a new version directory")
    report = scan_corpus(source, collection_id, limits)
    if not report.documents:
        raise ValueError("corpus contains no supported documents")
    output.parent.mkdir(parents=True, exist_ok=True)
    parent = output.parent.resolve(strict=True)
    output = parent / output.name
    workspace = None
    if storage:
        if not output.resolve().is_relative_to(storage.root):
            raise ValueError("bundle output must remain inside aggregate storage root")
        storage.check(64 * 1024**2)
    if work_directory is not None:
        recipe = {
            "source_snapshot": report.model_dump(mode="json"),
            "profile": profile,
            "title": title,
            "chunk_config": config.model_dump(),
            "pdf_options": pdf_options.model_dump() if pdf_options else None,
            "allow_incomplete": allow_incomplete,
            "allow_failed_documents": allow_failed_documents,
            "model": model_spec(model_directory).model_dump(mode="json")
            if model_directory
            else None,
            "ingestion_cache_sha256": file_hash(ingest_job / "parsed.sqlite")
            if ingest_job
            else None,
            "dense_backend": dense_backend,
            "embedding_pipeline": "length-buckets-512-batch32-v2",
            "threads": threads,
            "max_index_chunks": max_index_chunks,
            "max_index_text_chars": max_index_text_chars,
        }
        if reranker_descriptor is not None:
            recipe["retrieval_configuration"] = {
                "reranker": reranker_descriptor.model_dump(mode="json"),
                "candidates": rerank_candidates,
                "max_chunks_per_document": max_chunks_per_document,
            }
        workspace = BuildWorkspace(work_directory, output, recipe, resume=resume)
        stage = workspace.stage
        if workspace.published:
            recovered = verify_bundle(output)
            if recovered.build_id != workspace.state["build_id"]:
                raise ValueError("published output does not match the build checkpoint")
            workspace.after_publish()
            return recovered
    else:
        stage = Path(tempfile.mkdtemp(prefix=".ragforge-stage-", dir=parent)).resolve()
    try:
        collection_path = stage / "collections" / collection_id
        collection_path.mkdir(parents=True, exist_ok=True)
        database = collection_path / "index.sqlite"
        if ingest_job is not None:
            from ragforge.jobs.ingest import cached_documents

            documents = cached_documents(ingest_job, report, allow_failed=allow_failed_documents)
        else:
            documents = (
                load_document(source, collection_id, record, limits, pdf_options=pdf_options)
                for record in report.documents
            )
        last_index_bytes = database.stat().st_size if database.exists() else 0

        def index_progress(event: dict[str, Any]) -> None:
            nonlocal last_index_bytes
            if storage:
                size = database.stat().st_size
                storage.account(size - last_index_bytes)
                last_index_bytes = size
                storage.check(64 * 1024**2)
            if progress:
                progress(event)

        if workspace is None or not workspace.reusable("index", database):
            if database.exists():
                if workspace is None or is_link(database.lstat()):
                    raise ValueError("refusing to replace an unowned partial index")
                # Only this recipe's uncommitted private stage files are reset.
                for partial in (database, database.with_name(database.name + "-journal")):
                    if partial.exists():
                        if (
                            is_link(partial.lstat())
                            or partial.resolve().parent != collection_path.resolve()
                        ):
                            raise ValueError("unsafe partial index cleanup target")
                        partial.unlink()
            summary = create_index(
                database,
                collection_id,
                title,
                documents,
                config,
                allow_incomplete=allow_incomplete,
                max_chunks=max_index_chunks,
                max_output_chars=max_index_text_chars,
                progress=index_progress,
            )
            chunk_count = summary.chunk_count
            if workspace:
                workspace.completed("index", database)
        else:
            chunk_count = SQLiteEngine(database).list_collections()[0].chunk_count
        if not chunk_count:
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
            model_root.mkdir(parents=True, exist_ok=True)
            model_paths = [str(record.path) for record in spec.files] + ["model.json"]
            model_bytes = sum((model_directory / path).stat().st_size for path in model_paths)
            if storage:
                storage.check(model_bytes + chunk_count * spec.dimensions * 4 + 4096)
            for relative in model_paths:
                destination = model_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                previous_size = destination.stat().st_size if destination.exists() else 0
                shutil.copyfile(model_directory / relative, destination)
                if storage:
                    storage.account(destination.stat().st_size - previous_size)
            dense_path = collection_path / "dense.index"
            if workspace is None or not workspace.reusable("dense", dense_path):
                vectors_path = (
                    (workspace.job / "embeddings.npy" if workspace else stage / ".embeddings.npy")
                    if dense_backend == "ann"
                    else dense_path
                )
                if workspace is None or not workspace.reusable("vectors", vectors_path):
                    embedder = ONNXEmbedder(model_root, threads=threads)
                    write_dense(
                        database,
                        vectors_path,
                        embedder,
                        row_order="rowid" if dense_backend == "ann" else "chunk_id",
                        checkpoint=workspace.job / "dense-progress.json" if workspace else None,
                        identity=workspace.fingerprint if workspace else "",
                        progress=progress,
                    )
                    del embedder
                    if workspace:
                        workspace.completed("vectors", vectors_path)
                if dense_backend == "ann":
                    from ragforge.core.ann import write_ann

                    if storage:
                        storage.check(
                            chunk_count * (spec.dimensions * 2 + 512) + 65536, refresh=True
                        )
                    write_ann(
                        database,
                        vectors_path,
                        dense_path,
                        spec.dimensions,
                        checkpoint=workspace.job / "ann-progress.json" if workspace else None,
                        identity=workspace.fingerprint if workspace else "",
                        progress=progress,
                    )
                    if workspace is None:
                        vectors_path.unlink()
                if workspace:
                    workspace.completed("dense", dense_path)
            if dense_backend == "ann":
                from ragforge.core.ann import BACKEND as ANN_BACKEND
                from ragforge.core.ann import BACKEND_VERSION as ANN_VERSION

                backend_name, backend_version = ANN_BACKEND, ANN_VERSION
            else:
                backend_name, backend_version = BACKEND, BACKEND_VERSION
            dense = DenseIndex(
                path=f"collections/{collection_id}/dense.index",
                backend=backend_name,
                backend_version=backend_version,
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
        retrieval_configuration = None
        if reranker_descriptor is not None:
            assert reranker_directory is not None
            reranker_root = stage / "models/reranker"
            reranker_root.mkdir(parents=True, exist_ok=True)
            reranker_paths = [str(r.path) for r in reranker_descriptor.files] + ["reranker.json"]
            if storage:
                storage.check(sum((reranker_directory / p).stat().st_size for p in reranker_paths))
            for relative in reranker_paths:
                destination_r = reranker_root / relative
                destination_r.parent.mkdir(parents=True, exist_ok=True)
                old_size = destination_r.stat().st_size if destination_r.exists() else 0
                shutil.copyfile(reranker_directory / relative, destination_r)
                if storage:
                    storage.account(destination_r.stat().st_size - old_size)
            retrieval_configuration = RetrievalConfiguration(
                candidates_per_method=rerank_candidates,
                max_chunks_per_document=max_chunks_per_document,
                reranker=RerankerModel(
                    model_id=reranker_descriptor.model_id,
                    revision=reranker_descriptor.revision,
                    license=reranker_descriptor.license,
                    files=["models/reranker/" + p for p in sorted(reranker_paths)],
                ),
            )
            licenses.append(reranker_descriptor.license + ": reranker; see models/reranker/LICENSE")
        descriptor = stage / "manifest.json"
        if descriptor.exists():
            if workspace is None or is_link(descriptor.lstat()):
                raise ValueError("unexpected staged manifest")
            descriptor.unlink()  # Recompute a previous, unpublished owned manifest.
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
            retrieval_configuration=retrieval_configuration,
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
                chunker_version=chunker_version(config),
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
        if storage:
            storage.check(refresh=True)
        if workspace:
            workspace.before_publish(manifest.build_id)
        publish_new(stage, output)
        if workspace:
            workspace.after_publish()
        return manifest
    finally:
        # Delete only this call's private staging directory inside the checked parent.
        if workspace is None and stage.exists():
            if (
                stage.resolve().parent != parent
                or is_link(stage.lstat())
                or not stage.name.startswith(".ragforge-stage-")
            ):
                raise ValueError("refusing cleanup outside owned staging directory")
            shutil.rmtree(stage)
