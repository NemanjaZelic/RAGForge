"""Local corpus discovery, diagnostics and draft schema commands."""

import json
import platform
import sqlite3
from contextlib import closing
from dataclasses import asdict
from enum import StrEnum
from importlib.util import find_spec
from pathlib import Path
from typing import Annotated, Any

import typer

from ragforge import __version__
from ragforge.artifacts.builder import build_bundle
from ragforge.artifacts.manifest import BundleManifest
from ragforge.artifacts.verification import verify_bundle
from ragforge.core.chunk import Chunk, ChunkConfig, chunk_document
from ragforge.core.contracts import (
    FetchContextRequest,
    RetrievalEngine,
    RetrievalResponse,
    RetrieveRequest,
)
from ragforge.core.engine import BundleEngine
from ragforge.core.parse import load_document
from ragforge.core.pdf import PdfOptions
from ragforge.core.scan import ScanError, ScanLimits, scan_corpus
from ragforge.core.sqlite import SQLiteEngine, create_index
from ragforge.shared.client import ConnectionProfile
from ragforge.shared.policy import SharedPolicy
from ragforge.types import ContractModel

app = typer.Typer(
    name="ragforge",
    help="Local hybrid retrieval, portable bundles and read-only MCP.",
    no_args_is_help=True,
    invoke_without_command=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)


class SchemaName(StrEnum):
    manifest = "manifest"
    retrieve_request = "retrieve-request"
    retrieval_response = "retrieval-response"
    shared_policy = "shared-policy"
    shared_connection = "shared-connection"


def schema_document(name: SchemaName) -> dict[str, Any]:
    models: dict[SchemaName, type[ContractModel]] = {
        SchemaName.manifest: BundleManifest,
        SchemaName.retrieve_request: RetrieveRequest,
        SchemaName.retrieval_response: RetrievalResponse,
        SchemaName.shared_policy: SharedPolicy,
        SchemaName.shared_connection: ConnectionProfile,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **models[name].model_json_schema(),
    }


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", help="Show the development version."),
) -> None:
    if version:
        typer.echo(__version__)
        raise typer.Exit()


@app.command()
def doctor(
    endpoint: Annotated[str | None, typer.Option(help="Explicit shared origin to probe.")] = None,
    connection: Annotated[
        Path | None, typer.Option(help="Explicit shared connection profile.")
    ] = None,
    token_env: str = typer.Option("RAGFORGE_ACCESS_TOKEN"),
    ca_file: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Check the local engine, or explicitly probe an authenticated shared endpoint."""
    if endpoint is not None or connection is not None:
        from ragforge.shared.client import SharedClient

        try:
            client = SharedClient.configured(
                endpoint, connection, token_env=token_env, ca_file=ca_file
            )
            report = {
                "mode": "shared",
                "health": client.health(),
                "collections": [row.model_dump(mode="json") for row in client.list_collections()],
            }
            typer.echo(json.dumps(report, ensure_ascii=True))
        except (ValueError, OSError) as error:
            typer.echo(json.dumps({"error": str(error)}, ensure_ascii=True), err=True)
            raise typer.Exit(code=2) from error
        return
    if ca_file is not None:
        typer.echo(json.dumps({"error": "a shared CA requires an explicit endpoint"}), err=True)
        raise typer.Exit(code=2)
    available = False
    try:
        with closing(sqlite3.connect(":memory:")) as probe_db:
            probe_db.execute("CREATE VIRTUAL TABLE probe USING fts5(text)")
            probe_db.execute("INSERT INTO probe(text) VALUES (?)", ("local retrieval",))
            available = (
                probe_db.execute(
                    "SELECT count(*) FROM probe WHERE probe MATCH ?", ("retrieval",)
                ).fetchone()[0]
                == 1
            )
    except sqlite3.Error:
        available = False
    typer.echo(
        json.dumps(
            {
                "version": __version__,
                "stage": "phase-3-shared-http",
                "python": platform.python_version(),
                "sqlite": sqlite3.sqlite_version,
                "fts5": available,
                "retrieval_implemented": True,
                "retrieval_methods": ["bm25", "dense", "hybrid"],
                "balanced_dependencies_available": all(
                    find_spec(name) is not None for name in ("numpy", "onnxruntime", "tokenizers")
                ),
                "bundle_implemented": True,
                "mcp_stdio_implemented": True,
                "shared_http_implemented": True,
                "shared_dependencies_available": all(
                    find_spec(name) is not None
                    for name in ("mcp", "uvicorn", "jwt", "cryptography")
                ),
                "mcp_dependency_available": find_spec("mcp") is not None,
            },
            sort_keys=True,
        )
    )
    if not available:
        raise typer.Exit(code=1)


@app.command()
def schema(name: SchemaName) -> None:
    """Print a draft JSON Schema (not a bundle checksum or authenticity check)."""
    typer.echo(json.dumps(schema_document(name), indent=2, sort_keys=True))


@app.command()
def scan(
    root: Annotated[
        Path, typer.Argument(help="Corpus directory; files are hashed, never executed.")
    ],
    collection: str = typer.Option("default", "--collection", help="Portable collection slug."),
    max_file_bytes: int = typer.Option(32 * 1024 * 1024, min=1),
    max_total_bytes: int = typer.Option(512 * 1024 * 1024, min=1),
    max_entries: int = typer.Option(100000, min=1),
) -> None:
    """Inventory MD/TXT/HTML/PDF locally as JSON; this does not parse or index them."""
    try:
        report = scan_corpus(
            root, collection, ScanLimits(max_file_bytes, max_total_bytes, max_entries)
        )
    except (ScanError, ValueError) as error:
        typer.echo(json.dumps({"error": str(error)}, ensure_ascii=True), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(json.dumps(report.model_dump(mode="json"), ensure_ascii=True))


@app.command()
def chunk(
    root: Annotated[Path, typer.Argument(help="Corpus directory to parse and chunk.")],
    collection: str = typer.Option("default", "--collection"),
    chunk_size_chars: int = typer.Option(1000, min=1, max=100000),
    overlap_chars: int = typer.Option(100, min=0),
    max_file_bytes: int = typer.Option(32 * 1024 * 1024, min=1),
    max_total_bytes: int = typer.Option(512 * 1024 * 1024, min=1),
    max_entries: int = typer.Option(100000, min=1),
    max_chunks: int = typer.Option(10000, min=1),
    max_output_chars: int = typer.Option(100000, min=1),
    pdf_max_pages: int = typer.Option(500, min=1, max=10000),
    pdf_max_stream_bytes: int = typer.Option(8 * 1024 * 1024, min=1),
    pdf_max_text_chars: int = typer.Option(2000000, min=1),
    allow_partial_pdf: bool = typer.Option(
        False, help="Report page errors and keep other PDF pages."
    ),
) -> None:
    """Preview normalized chunks and citations as JSON; does not build an index."""
    try:
        pdf_options = PdfOptions(
            max_pages=pdf_max_pages,
            max_stream_bytes=pdf_max_stream_bytes,
            max_text_chars=pdf_max_text_chars,
            allow_partial=allow_partial_pdf,
        )
        config = ChunkConfig(chunk_size_chars=chunk_size_chars, overlap_chars=overlap_chars)
        limits = ScanLimits(max_file_bytes, max_total_bytes, max_entries)
        report = scan_corpus(root, collection, limits)
        documents = []
        chunks: list[Chunk] = []
        output_chars = 0
        for record in report.documents:
            parsed = load_document(root, collection, record, limits, pdf_options=pdf_options)
            if parsed.blocks and len(chunks) >= max_chunks:
                raise ValueError("max_chunks exceeded")
            if parsed.blocks and output_chars >= max_output_chars:
                raise ValueError("max_output_chars exceeded")
            parts = (
                chunk_document(
                    parsed,
                    config,
                    max_chunks=max_chunks - len(chunks),
                    max_output_chars=max_output_chars - output_chars,
                )
                if parsed.blocks
                else []
            )
            output_chars += sum(len(part.text) for part in parts)
            if output_chars > max_output_chars:
                raise ValueError("max_output_chars exceeded")
            documents.append(
                {
                    "source_path": record.source_path,
                    "document_id": record.document_id,
                    "content_sha256": record.content_sha256,
                    "warnings": parsed.warnings,
                    "chunk_count": len(parts),
                    "pages": [asdict(page) for page in parsed.page_reports],
                    "incomplete": any(page.status != "extracted" for page in parsed.page_reports),
                }
            )
            chunks.extend(parts)
        result = {
            "collection_id": collection,
            "documents": documents,
            "ignored_paths": report.ignored_paths,
            "chunks": [part.model_dump() for part in chunks],
        }
    except ValueError as error:
        typer.echo(json.dumps({"error": str(error)}, ensure_ascii=True), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(json.dumps(result, ensure_ascii=True))


@app.command()
def index(
    root: Annotated[Path, typer.Argument(help="Corpus directory.")],
    database: Annotated[Path, typer.Argument(help="New standalone development SQLite file.")],
    collection: str = typer.Option("default", "--collection"),
    title: str = typer.Option("Documents"),
    chunk_size_chars: int = typer.Option(1000, min=1, max=100000),
    overlap_chars: int = typer.Option(100, min=0),
    max_file_bytes: int = typer.Option(32 * 1024 * 1024, min=1),
    max_total_bytes: int = typer.Option(512 * 1024 * 1024, min=1),
    max_entries: int = typer.Option(100000, min=1),
    max_chunks: int = typer.Option(100000, min=1),
    max_index_text_chars: int = typer.Option(100000000, min=1),
    allow_partial_pdf: bool = typer.Option(False),
    allow_incomplete: bool = typer.Option(
        False, help="Explicitly index PDFs with unextracted pages."
    ),
) -> None:
    """Create a real BM25 development index; not the planned balanced bundle."""
    try:
        limits = ScanLimits(max_file_bytes, max_total_bytes, max_entries)
        report = scan_corpus(root, collection, limits)
        pdf_options = PdfOptions(allow_partial=allow_partial_pdf)
        documents = (
            load_document(root, collection, record, limits, pdf_options=pdf_options)
            for record in report.documents
        )
        summary = create_index(
            database,
            collection,
            title,
            documents,
            ChunkConfig(chunk_size_chars=chunk_size_chars, overlap_chars=overlap_chars),
            allow_incomplete=allow_incomplete,
            max_chunks=max_chunks,
            max_output_chars=max_index_text_chars,
        )
    except (ValueError, OSError, sqlite3.Error) as error:
        typer.echo(json.dumps({"error": str(error)}, ensure_ascii=True), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(json.dumps(summary.model_dump(mode="json"), ensure_ascii=True))


@app.command()
def search(
    database: Annotated[Path, typer.Argument(help="Standalone development SQLite index.")],
    query: Annotated[str, typer.Argument(help="Plain literal query; no FTS operators.")],
    collection: str | None = typer.Option(None, "--collection"),
    top_k: int = typer.Option(5, min=1, max=50),
    max_output_chars: int = typer.Option(16000, min=1, max=100000),
    search_method: str = typer.Option("bm25", help="Only bm25 is implemented for this index."),
) -> None:
    """Return real lexical search results with source citations as JSON."""
    try:
        request = RetrieveRequest.model_validate(
            {
                "query": query,
                "collection_id": collection,
                "top_k": top_k,
                "max_output_chars": max_output_chars,
                "search_method": search_method,
            }
        )
        result = SQLiteEngine(database).retrieve(request)
    except (ValueError, OSError) as error:
        typer.echo(json.dumps({"error": str(error)}, ensure_ascii=True), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(json.dumps(result.model_dump(mode="json"), ensure_ascii=True))


@app.command()
def context(
    target: Annotated[str, typer.Argument(help="Local bundle/index, or chunk ID in shared mode.")],
    chunk_id: Annotated[str | None, typer.Argument(help="Local exact chunk ID.")] = None,
    collection: str | None = typer.Option(None, "--collection"),
    neighbors: int = typer.Option(1, min=0, max=5),
    max_output_chars: int = typer.Option(16000, min=1, max=100000),
    mode: str = typer.Option("local", help="local or shared."),
    endpoint: Annotated[str | None, typer.Option()] = None,
    connection: Annotated[
        Path | None, typer.Option(help="Explicit shared connection profile.")
    ] = None,
    token_env: str = typer.Option("RAGFORGE_ACCESS_TOKEN"),
    ca_file: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Fetch an exact chunk and bounded neighbors within the same document."""
    try:
        engine: RetrievalEngine
        if mode == "shared":
            from ragforge.shared.client import SharedClient

            if (endpoint is None and connection is None) or chunk_id is not None:
                raise ValueError(
                    "shared context requires one chunk ID and an endpoint or connection profile"
                )
            engine = SharedClient.configured(
                endpoint, connection, token_env=token_env, ca_file=ca_file
            )
            chunk_id = target
        elif mode == "local":
            if (
                chunk_id is None
                or endpoint is not None
                or connection is not None
                or ca_file is not None
            ):
                raise ValueError("local context requires bundle/index and chunk ID")
            database = Path(target)
            engine = BundleEngine(database) if database.is_dir() else SQLiteEngine(database)
        else:
            raise ValueError("choose local or shared runtime mode")
        selected = collection or engine.list_collections()[0].collection_id
        result = engine.fetch_context(
            FetchContextRequest(
                collection_id=selected,
                chunk_id=chunk_id,
                neighbors=neighbors,
                max_output_chars=max_output_chars,
            )
        )
    except (ValueError, OSError) as error:
        typer.echo(json.dumps({"error": str(error)}, ensure_ascii=True), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(json.dumps(result.model_dump(mode="json"), ensure_ascii=True))


class BuildProfile(StrEnum):
    balanced = "balanced"
    minimal = "minimal"


@app.command()
def build(
    root: Annotated[Path, typer.Argument(help="Local MD/TXT/HTML/PDF corpus.")],
    output: Annotated[Path, typer.Option("--output", help="New bundle version directory.")],
    profile: Annotated[BuildProfile, typer.Option()] = BuildProfile.balanced,
    model: Annotated[
        Path | None, typer.Option(help="Prepared local query model directory.")
    ] = None,
    reranker: Annotated[
        Path | None, typer.Option(help="Prepared local ONNX reranker; no download.")
    ] = None,
    rerank_candidates: int = typer.Option(100, min=50, max=200),
    max_chunks_per_document: Annotated[int | None, typer.Option(min=1, max=50)] = None,
    token_aware: bool = typer.Option(False, help="Split using the pinned embedding token budget."),
    chunk_strategy: str = typer.Option("blocks", help="blocks or section-aware sections."),
    collection: str = typer.Option("default", "--collection"),
    title: str = typer.Option("Documents"),
    chunk_size_chars: int = typer.Option(1000, min=1, max=100000),
    overlap_chars: int = typer.Option(100, min=0),
    compute: str = typer.Option("local", help="Only local compute is implemented."),
    offline: bool = typer.Option(
        False, "--offline", help="Explicit assertion; build is always offline."
    ),
    allow_incomplete: bool = typer.Option(False),
    allow_failed_documents: bool = typer.Option(
        False, help="Retain failed sources visibly with zero chunks."
    ),
    allow_partial_pdf: bool = typer.Option(False),
    pdf_max_pages: int = typer.Option(500, min=1, max=10000),
    max_file_bytes: int = typer.Option(32 * 1024 * 1024, min=1),
    max_total_bytes: int = typer.Option(512 * 1024 * 1024, min=1),
    max_entries: int = typer.Option(100000, min=1),
    threads: int = typer.Option(4, min=1, max=32),
    ingest_job: Annotated[
        Path | None, typer.Option(help="Verified source-bound parsing journal.")
    ] = None,
    work_directory: Annotated[
        Path | None, typer.Option("--job", help="Persistent build checkpoint directory.")
    ] = None,
    resume: bool = typer.Option(False),
    storage_root: Annotated[
        Path | None, typer.Option(help="Aggregate benchmark storage root.")
    ] = None,
    dense_backend: str = typer.Option("exact", help="exact or explicit sharded ann backend."),
    max_index_chunks: int = typer.Option(100000, min=1, max=8000000),
    max_index_text_chars: int = typer.Option(100000000, min=1),
) -> None:
    """Build and verify a portable data bundle; never downloads or deploys."""
    from ragforge.jobs.budget import StorageBudget

    def progress(event: dict[str, Any]) -> None:
        if event["phase"] != "index" or event["completed_documents"] % 100 == 0:
            typer.echo(json.dumps(event, ensure_ascii=True), err=True)

    try:
        if chunk_strategy not in {"blocks", "sections"}:
            raise ValueError("unknown chunk strategy")
        if dense_backend not in {"exact", "ann"}:
            raise ValueError("unknown dense backend")
        if compute != "local":
            raise ValueError("only local build compute is implemented")
        manifest = build_bundle(
            root,
            output,
            collection_id=collection,
            title=title,
            profile="balanced" if profile == BuildProfile.balanced else "minimal",
            model_directory=model,
            reranker_directory=reranker,
            rerank_candidates=rerank_candidates,
            max_chunks_per_document=max_chunks_per_document,
            chunk_config=ChunkConfig(
                strategy="sections" if chunk_strategy == "sections" else "blocks",
                chunk_size_chars=chunk_size_chars,
                overlap_chars=overlap_chars,
            ),
            token_aware=token_aware,
            allow_incomplete=allow_incomplete,
            allow_failed_documents=allow_failed_documents,
            pdf_options=PdfOptions(max_pages=pdf_max_pages, allow_partial=allow_partial_pdf)
            if ingest_job is None
            else None,
            scan_limits=ScanLimits(max_file_bytes, max_total_bytes, max_entries)
            if ingest_job is None
            else None,
            ingest_job=ingest_job,
            max_index_chunks=max_index_chunks,
            max_index_text_chars=max_index_text_chars,
            dense_backend="ann" if dense_backend == "ann" else "exact",
            work_directory=work_directory,
            resume=resume,
            storage=StorageBudget(storage_root) if storage_root is not None else None,
            progress=progress if work_directory is not None else None,
            threads=threads,
        )
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as error:
        typer.echo(json.dumps({"error": str(error)}, ensure_ascii=True), err=True)
        raise typer.Exit(code=2) from error
    from ragforge.artifacts.diagnostics import ingestion_diagnostics

    typer.echo(
        json.dumps(
            {
                "source_coverage": ingestion_diagnostics(
                    SQLiteEngine(output / manifest.collections[0].database_path)
                ),
                "build_id": manifest.build_id,
                "profile": manifest.profile,
                "collection_id": collection,
                "files": len(manifest.files),
                "offline": True,
            }
        )
    )


@app.command()
def recontextualize(
    dense_base: Path,
    context_base: Path,
    output: Annotated[Path, typer.Option(help="New verified context-mapped bundle.")],
    storage_root: Annotated[Path | None, typer.Option()] = None,
    document_titles: Annotated[
        Path | None, typer.Option(help="Source-verified title metadata JSON.")
    ] = None,
    query_aliases: Annotated[
        Path | None, typer.Option(help="Source-verified acronym JSON.")
    ] = None,
    plan_queries: bool = typer.Option(
        False, "--plan-queries", help="Optional bounded facets-v1 hybrid candidate planning."
    ),
    complete_sections: bool = typer.Option(
        False, "--complete-sections", help="Optional bounded section-start-v1 context completion."
    ),
) -> None:
    """Reuse small-chunk dense vectors with larger source-identical context chunks."""
    from ragforge.artifacts.recontextualize import recontextualize_bundle
    from ragforge.jobs.budget import StorageBudget

    try:
        result = recontextualize_bundle(
            dense_base,
            context_base,
            output,
            storage=StorageBudget(storage_root) if storage_root else None,
            document_titles=document_titles,
            query_aliases=query_aliases,
            query_planning="facets-v1" if plan_queries else None,
            section_context="section-start-v1" if complete_sections else None,
        )
    except (ValueError, OSError, RuntimeError) as error:
        typer.echo(json.dumps({"error": str(error)}, ensure_ascii=True), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(json.dumps({"build_id": result.build_id, "reused_dense_vectors": True}))


@app.command()
def enhance(
    artifact: Path,
    output: Annotated[Path, typer.Option(help="New verified bundle version.")],
    reranker: Annotated[Path, typer.Option(help="Prepared local reranker model.")],
    candidates: int = typer.Option(100, min=50, max=200),
    max_chunks_per_document: Annotated[int | None, typer.Option(min=1, max=50)] = None,
    storage_root: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Add a local reranker in a new version, reusing index bytes without re-embedding."""
    from ragforge.artifacts.enhance import enhance_bundle
    from ragforge.jobs.budget import StorageBudget

    try:
        result = enhance_bundle(
            artifact,
            output,
            reranker,
            candidates=candidates,
            max_chunks_per_document=max_chunks_per_document,
            storage=StorageBudget(storage_root) if storage_root else None,
        )
    except (ValueError, OSError, RuntimeError) as error:
        typer.echo(json.dumps({"error": str(error)}, ensure_ascii=True), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(json.dumps({"build_id": result.build_id, "reused_index_bytes": True}))


@app.command()
def use(
    artifact: Annotated[
        Path | None, typer.Argument(help="Local bundle; omit for shared mode.")
    ] = None,
    query: str = typer.Option(..., "--query"),
    mode: str = typer.Option("local", help="local or explicit authenticated shared endpoint."),
    search_method: str | None = typer.Option(
        None, help="bm25, dense or hybrid; bundle default if omitted."
    ),
    collection: str | None = typer.Option(None, "--collection"),
    top_k: int = typer.Option(5, min=1, max=50),
    max_output_chars: int = typer.Option(16000, min=1, max=100000),
    threads: int = typer.Option(4, min=1, max=32),
    rerank: Annotated[bool | None, typer.Option("--rerank/--no-rerank")] = None,
    endpoint: Annotated[str | None, typer.Option()] = None,
    connection: Annotated[
        Path | None, typer.Option(help="Explicit shared connection profile.")
    ] = None,
    token_env: str = typer.Option("RAGFORGE_ACCESS_TOKEN"),
    ca_file: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Query the same local engine; balanced defaults to hybrid, minimal to BM25."""
    try:
        if mode not in {"local", "shared"}:
            raise ValueError("choose local or shared runtime mode")
        request = RetrieveRequest.model_validate(
            {
                "query": query,
                "collection_id": collection,
                "top_k": top_k,
                "max_output_chars": max_output_chars,
                "search_method": search_method,
                "rerank": rerank,
            }
        )
        if mode == "shared":
            from ragforge.shared.client import SharedClient

            if artifact is not None or (endpoint is None and connection is None):
                raise ValueError(
                    "shared mode requires an endpoint/connection and no local artifact argument"
                )
            result = SharedClient.configured(
                endpoint, connection, token_env=token_env, ca_file=ca_file
            ).retrieve(request)
        else:
            if (
                artifact is None
                or endpoint is not None
                or connection is not None
                or ca_file is not None
            ):
                raise ValueError("local mode requires a bundle and no shared endpoint/CA options")
            result = BundleEngine(artifact, threads=threads).retrieve(request)
    except (ValueError, OSError, RuntimeError) as error:
        typer.echo(json.dumps({"error": str(error)}, ensure_ascii=True), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(json.dumps(result.model_dump(mode="json"), ensure_ascii=True))


@app.command()
def verify(artifact: Path) -> None:
    """Verify paths, versions, complete inventory and checksums before runtime."""
    try:
        manifest = verify_bundle(artifact)
    except (ValueError, OSError) as error:
        typer.echo(json.dumps({"error": str(error)}, ensure_ascii=True), err=True)
        raise typer.Exit(code=2) from error
    from ragforge.artifacts.diagnostics import ingestion_diagnostics

    typer.echo(
        json.dumps(
            {
                "valid": True,
                "build_id": manifest.build_id,
                "profile": manifest.profile,
                "source_coverage": ingestion_diagnostics(
                    SQLiteEngine(artifact / manifest.collections[0].database_path)
                ),
            }
        )
    )


@app.command()
def serve(
    artifact: Annotated[Path | None, typer.Argument(help="Bundle; omit with --deployment.")] = None,
    deployment: Annotated[
        Path | None, typer.Option(help="Prepared shared deployment directory.")
    ] = None,
    threads: int = typer.Option(4, min=1, max=32),
    transport: str = typer.Option("stdio", help="stdio or authenticated shared http."),
    auth_file: Annotated[
        Path | None, typer.Option(help="Explicit shared JWT/access policy.")
    ] = None,
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8765, min=1, max=65535),
    tls_cert: Annotated[Path | None, typer.Option()] = None,
    tls_key: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Run read-only stdio MCP or explicit authenticated REST/MCP HTTP."""
    if transport == "http":
        try:
            from ragforge.shared.http import run_shared
        except ImportError as error:
            typer.echo(json.dumps({"error": "HTTP support requires ragforge[shared]."}), err=True)
            raise typer.Exit(code=2) from error
        try:
            expected_build_id = None
            if deployment is not None:
                from ragforge.shared.registry import read_deployment

                if artifact is not None:
                    raise ValueError("choose a bundle argument or --deployment, not both")
                state = read_deployment(deployment)
                artifact, expected_build_id = Path(state.active.path), state.active.build_id
                auth_file = auth_file or Path(state.auth_policy)
            if artifact is None or auth_file is None:
                raise ValueError("HTTP requires a bundle/deployment and explicit auth policy")
            run_shared(
                artifact,
                auth_file,
                host=host,
                port=port,
                threads=threads,
                tls_cert=tls_cert,
                tls_key=tls_key,
                expected_build_id=expected_build_id,
            )
        except (ValueError, OSError, RuntimeError, sqlite3.Error) as error:
            typer.echo(json.dumps({"error": str(error)}, ensure_ascii=True), err=True)
            raise typer.Exit(code=2) from error
        return
    if (
        transport != "stdio"
        or deployment is not None
        or auth_file is not None
        or tls_cert is not None
        or tls_key is not None
        or host != "127.0.0.1"
        or port != 8765
    ):
        typer.echo(json.dumps({"error": "choose stdio or explicit authenticated http"}), err=True)
        raise typer.Exit(code=2)
    if artifact is None:
        typer.echo(json.dumps({"error": "stdio requires a verified bundle argument"}), err=True)
        raise typer.Exit(code=2)
    try:
        from ragforge.adapters.mcp import create_server
    except ImportError as error:
        typer.echo(json.dumps({"error": "MCP support requires the ragforge[mcp] extra."}), err=True)
        raise typer.Exit(code=2) from error
    try:
        create_server(artifact, threads=threads).run(transport="stdio")
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as error:
        typer.echo(json.dumps({"error": str(error)}, ensure_ascii=True), err=True)
        raise typer.Exit(code=2) from error


@app.command()
def integrate(
    artifact: Annotated[Path, typer.Argument(help="Verified local bundle directory.")],
    output: Annotated[Path, typer.Option("--output", help="New agent files directory.")],
    description: Annotated[str | None, typer.Option(help="User-authored skill purpose.")] = None,
) -> None:
    """Generate a skill and separate MCP config without editing host settings."""
    from ragforge.adapters.integration import create_integration

    try:
        result = create_integration(artifact, output, description=description)
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as error:
        typer.echo(json.dumps({"error": str(error)}, ensure_ascii=True), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(json.dumps(result, ensure_ascii=True))


@app.command()
def ingest(
    root: Annotated[Path, typer.Argument(help="Complete source corpus; no sampling.")],
    job: Annotated[Path, typer.Option("--job", help="New or explicitly resumed parsing journal.")],
    collection: str = typer.Option("default", "--collection"),
    resume: bool = typer.Option(False),
    retry_failed: bool = typer.Option(False),
    continue_on_error: bool = typer.Option(False),
    allow_permitted_pdf: bool = typer.Option(
        False, help="Allow empty-password PDFs only when user extraction permission is set."
    ),
    text_fallback: str = typer.Option("none", help="none or explicitly selected latin-1 fallback."),
    escape_controls: bool = typer.Option(False, help="Represent legacy control bytes visibly."),
    pdf_backend: str = typer.Option("pypdf", help="pypdf or optional pdfium; always isolated."),
    pdf_max_pages: int = typer.Option(500, min=1, max=10000),
    pdf_max_text_chars: int = typer.Option(2000000, min=1),
    pdf_max_document_stream_bytes: int = typer.Option(64 * 1024**2, min=1),
    allow_partial_pdf: bool = typer.Option(False),
    max_file_bytes: int = typer.Option(32 * 1024**2, min=1),
    max_total_bytes: int = typer.Option(512 * 1024**2, min=1),
    max_entries: int = typer.Option(100000, min=1),
    worker_memory_mib: int = typer.Option(512, min=128, max=4096),
    document_timeout_seconds: int = typer.Option(300, min=1, max=86400),
    storage_root: Annotated[
        Path | None, typer.Option(help="Aggregate benchmark storage root.")
    ] = None,
    storage_budget_bytes: int = typer.Option(65_000_000_000, min=1),
    reserve_free_bytes: int = typer.Option(15_000_000_000, min=0),
) -> None:
    """Parse every source with OS-bounded workers; checkpoint each outcome for resume."""
    from ragforge.core.parse import TextOptions
    from ragforge.jobs.budget import StorageBudget
    from ragforge.jobs.ingest import ingest_corpus

    def progress(event: dict[str, Any]) -> None:
        if event["attempted"] % 25 == 0 or event["status"] == "error":
            typer.echo(json.dumps(event, ensure_ascii=True), err=True)

    try:
        if text_fallback not in {"none", "latin-1"}:
            raise ValueError("unknown text fallback encoding")
        if pdf_backend not in {"pypdf", "pdfium"}:
            raise ValueError("unknown PDF backend")
        storage = (
            StorageBudget(
                storage_root,
                limit_bytes=storage_budget_bytes,
                reserve_free_bytes=reserve_free_bytes,
            )
            if storage_root is not None
            else None
        )
        result = ingest_corpus(
            root,
            job,
            collection_id=collection,
            limits=ScanLimits(max_file_bytes, max_total_bytes, max_entries),
            pdf_options=PdfOptions(
                max_pages=pdf_max_pages,
                max_text_chars=pdf_max_text_chars,
                max_document_stream_bytes=pdf_max_document_stream_bytes,
                allow_partial=allow_partial_pdf,
            ),
            pdf_backend="pdfium" if pdf_backend == "pdfium" else "pypdf",
            allow_permitted_pdf=allow_permitted_pdf,
            text_options=TextOptions(
                fallback_encoding="latin-1" if text_fallback == "latin-1" else "none",
                control_characters="escape" if escape_controls else "reject",
            ),
            resume=resume,
            retry_failed=retry_failed,
            continue_on_error=continue_on_error,
            worker_memory_mib=worker_memory_mib,
            document_timeout_seconds=document_timeout_seconds,
            storage=storage,
            progress=progress,
        )
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as error:
        typer.echo(json.dumps({"error": str(error)}, ensure_ascii=True), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(json.dumps(result, ensure_ascii=True))
    if result["status_counts"].get("error", 0):
        raise typer.Exit(code=2)


@app.command("job-status")
def inspect_job(job: Path) -> None:
    """Inspect completed, partial, failed and pending document counts without parsing."""
    from ragforge.jobs.build import build_status
    from ragforge.jobs.ingest import job_status

    try:
        result = build_status(job) if (job / "build.json").exists() else job_status(job)
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as error:
        typer.echo(json.dumps({"error": str(error)}, ensure_ascii=True), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(json.dumps(result, ensure_ascii=True))


@app.command()
def evaluate(
    artifact: Annotated[Path, typer.Argument(help="Verified full collection bundle.")],
    cases: Annotated[Path, typer.Option(help="Frozen source-evidence cases as JSONL.")],
    source_root: Annotated[Path, typer.Option(help="Frozen original source directory.")],
    output: Annotated[Path, typer.Option(help="New result/checkpoint directory.")],
    split: str = typer.Option("dev"),
    track: str | None = typer.Option(None),
    methods: Annotated[list[str] | None, typer.Option("--method")] = None,
    top_k: int = typer.Option(10, min=10, max=50),
    max_output_chars: int = typer.Option(16000, min=1, max=100000),
    answer_evidence: Annotated[
        Path | None,
        typer.Option(help="Question-bound accepted answer facts and alternative citations."),
    ] = None,
    threads: int = typer.Option(4, min=1, max=32),
    allow_draft: bool = typer.Option(False),
    rerank: Annotated[bool | None, typer.Option("--rerank/--no-rerank")] = None,
    resume: bool = typer.Option(False),
    pdf_reference_cache: Annotated[
        Path | None, typer.Option(help="Frozen PDF reference page JSONs.")
    ] = None,
) -> None:
    """Measure actual retrieval and source-span coverage; drafts cannot approve release."""
    from pydantic import TypeAdapter

    from ragforge.evaluation.runner import evaluate_bundle
    from ragforge.types import SearchMethod

    try:
        if split not in {"dev", "tuning", "test"}:
            raise ValueError("unknown evaluation split")
        selected = TypeAdapter(list[SearchMethod]).validate_python(methods) if methods else None
        report = evaluate_bundle(
            artifact,
            cases,
            source_root,
            output,
            split="dev" if split == "dev" else ("tuning" if split == "tuning" else "test"),
            methods=selected,
            track=track,
            top_k=top_k,
            max_output_chars=max_output_chars,
            allow_draft=allow_draft,
            answer_evidence_file=answer_evidence,
            rerank=rerank,
            threads=threads,
            resume=resume,
            pdf_reference_cache=pdf_reference_cache,
            progress=lambda event: typer.echo(json.dumps(event, ensure_ascii=True), err=True),
        )
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as error:
        typer.echo(json.dumps({"error": str(error)}, ensure_ascii=True), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(json.dumps(report, ensure_ascii=True))
    if any(row["errors"] for row in report["methods"].values()):
        raise typer.Exit(code=2)


@app.command()
def deploy(
    artifact: Annotated[Path, typer.Argument(help="Existing immutable bundle.")],
    output: Annotated[Path, typer.Option(help="New local deployment control directory.")],
    auth_file: Annotated[Path, typer.Option(help="Operator-supplied shared policy.")],
    smoke_query: Annotated[str, typer.Option(help="Required source query; never persisted.")],
    mode: str = typer.Option("shared"),
    expected_document_id: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Prepare shared version/connection files; never starts a server or provisions a host."""
    from ragforge.shared.registry import create_deployment, state_summary

    try:
        if mode != "shared":
            raise ValueError("only explicit shared deployment preparation is implemented")
        state = create_deployment(
            artifact, output, auth_file, smoke_query, expected_document_id=expected_document_id
        )
    except (ValueError, OSError, RuntimeError, sqlite3.Error, ImportError) as error:
        typer.echo(json.dumps({"error": str(error)}, ensure_ascii=True), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(json.dumps(state_summary(state), ensure_ascii=True))


@app.command("activate")
def activate_version(
    artifact: Annotated[Path, typer.Argument(help="New immutable bundle version.")],
    deployment: Annotated[Path, typer.Option(help="Existing shared deployment directory.")],
    smoke_query: Annotated[str, typer.Option(help="Required source query; never persisted.")],
    expected_document_id: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Verify and smoke-test a new version before atomic pointer activation; then restart."""
    from ragforge.shared.registry import activate, state_summary

    try:
        state = activate(
            deployment, artifact, smoke_query, expected_document_id=expected_document_id
        )
    except (ValueError, OSError, RuntimeError, sqlite3.Error, ImportError) as error:
        typer.echo(json.dumps({"error": str(error)}, ensure_ascii=True), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(json.dumps(state_summary(state), ensure_ascii=True))


@app.command()
def rollback(
    deployment: Annotated[Path, typer.Option(help="Existing shared deployment directory.")],
    smoke_query: Annotated[str, typer.Option(help="Required source query; never persisted.")],
    expected_document_id: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Reverify/smoke-test and restore the previous version pointer; then restart."""
    from ragforge.shared.registry import rollback as restore
    from ragforge.shared.registry import state_summary

    try:
        state = restore(deployment, smoke_query, expected_document_id=expected_document_id)
    except (ValueError, OSError, RuntimeError, sqlite3.Error, ImportError) as error:
        typer.echo(json.dumps({"error": str(error)}, ensure_ascii=True), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(json.dumps(state_summary(state), ensure_ascii=True))
