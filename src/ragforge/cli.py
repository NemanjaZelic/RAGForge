"""Local corpus discovery, diagnostics and draft schema commands."""

import json
import platform
import sqlite3
from contextlib import closing
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer

from ragforge import __version__
from ragforge.artifacts.manifest import BundleManifest
from ragforge.core.chunk import Chunk, ChunkConfig, chunk_document
from ragforge.core.contracts import RetrievalResponse, RetrieveRequest
from ragforge.core.parse import load_document
from ragforge.core.scan import ScanError, ScanLimits, scan_corpus
from ragforge.types import ContractModel

app = typer.Typer(
    name="ragforge",
    help="Portable document retrieval. Corpus scan, contracts and diagnostics.",
    no_args_is_help=True,
    invoke_without_command=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)


class SchemaName(StrEnum):
    manifest = "manifest"
    retrieve_request = "retrieve-request"
    retrieval_response = "retrieval-response"


def schema_document(name: SchemaName) -> dict[str, Any]:
    models: dict[SchemaName, type[ContractModel]] = {
        SchemaName.manifest: BundleManifest,
        SchemaName.retrieve_request: RetrieveRequest,
        SchemaName.retrieval_response: RetrievalResponse,
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
def doctor() -> None:
    """Check Python and SQLite FTS5 locally; output JSON without using the network."""
    available = False
    try:
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.execute("CREATE VIRTUAL TABLE probe USING fts5(text)")
            connection.execute("INSERT INTO probe(text) VALUES (?)", ("local retrieval",))
            available = (
                connection.execute(
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
                "stage": "phase-1",
                "python": platform.python_version(),
                "sqlite": sqlite3.sqlite_version,
                "fts5": available,
                "retrieval_implemented": False,
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
    typer.echo(report.model_dump_json())


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
) -> None:
    """Preview normalized chunks and citations as JSON; does not build an index."""
    try:
        config = ChunkConfig(chunk_size_chars=chunk_size_chars, overlap_chars=overlap_chars)
        limits = ScanLimits(max_file_bytes, max_total_bytes, max_entries)
        report = scan_corpus(root, collection, limits)
        documents = []
        chunks: list[Chunk] = []
        output_chars = 0
        for record in report.documents:
            parsed = load_document(root, collection, record, limits)
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
