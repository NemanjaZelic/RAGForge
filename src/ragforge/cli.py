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
from ragforge.core.contracts import RetrievalResponse, RetrieveRequest
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
