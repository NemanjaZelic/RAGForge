"""Small local workflow over the existing builder, engine and agent generator.

Model downloading belongs exclusively to the separate explicit setup script.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from ragforge.adapters.integration import create_integration
from ragforge.artifacts.builder import build_bundle
from ragforge.artifacts.manifest import BundleManifest
from ragforge.core.chunk import ChunkConfig
from ragforge.core.contracts import RetrieveRequest
from ragforge.core.embedding import model_spec
from ragforge.core.engine import BundleEngine
from ragforge.core.rerank import reranker_spec
from ragforge.core.source import is_link
from ragforge.jobs.build import atomic_json
from ragforge.types import ContractModel, Sha256

LAUNCHER = ".\\ragforge.cmd" if sys.platform == "win32" else "bash ragforge.sh"
SETUP = "setup.cmd" if sys.platform == "win32" else "bash setup.sh"


class ModelPaths(ContractModel):
    query_model: str
    reranker: str
    document_language: Literal["multilingual", "en"] = "multilingual"
    accelerator: Literal["cpu", "intel-gpu"] = "cpu"


class ActiveBundle(ContractModel):
    bundle: str
    build_id: Sha256


def state_directory(project: Path) -> Path:
    path = project / ".cache/quickstart"
    path.mkdir(parents=True, exist_ok=True)
    if is_link(path.lstat()):
        raise ValueError("quickstart state directory must not be a link")
    return path


def read_state(path: Path) -> str:
    if is_link(path.lstat()) or path.stat().st_size > 65536:
        raise ValueError("invalid quickstart state file")
    return path.read_text(encoding="utf-8")


def model_paths(project: Path) -> ModelPaths:
    path = project / ".cache/quickstart/models.json"
    if path.exists():
        return ModelPaths.model_validate_json(read_state(path))
    return ModelPaths(
        query_model=str(project / "models/e5-small"),
        reranker=str(project / "models/mmarco-minilm-reranker"),
    )


def active_bundle(project: Path) -> Path:
    path = project / ".cache/quickstart/active.json"
    if not path.exists():
        raise ValueError(f"No ready documentation. Run {LAUNCHER} build first, or use --bundle.")
    record = ActiveBundle.model_validate_json(read_state(path))
    bundle = Path(record.bundle)
    descriptor = bundle / "manifest.json"
    if is_link(descriptor.lstat()) or descriptor.stat().st_size > 32 * 1024**2:
        raise ValueError("invalid active bundle descriptor")
    manifest = BundleManifest.model_validate_json(descriptor.read_text(encoding="utf-8"))
    if manifest.build_id != record.build_id:
        raise ValueError("active bundle identity changed; rebuild or select --bundle explicitly")
    # Full inventory/hash validation follows in the engine/integration, only once.
    return bundle


def ready_documentation(
    project: Path,
    documents: Path | None = None,
    *,
    output: Path | None = None,
    query_model: Path | None = None,
    reranker: Path | None = None,
    threads: int = 4,
    url: str | None = None,
    site_max_pages: int = 100,
    site_max_depth: int = 2,
    allow_partial_site: bool = False,
) -> Path:
    project = project.resolve(strict=True)
    if url is not None and documents is not None:
        raise ValueError("Choose a document folder or --url, not both.")
    models = model_paths(project)
    query_model = query_model if query_model is not None else Path(models.query_model)
    reranker = reranker if reranker is not None else Path(models.reranker)
    if not query_model.exists() or not reranker.exists():
        raise ValueError(
            f"Prepared models are missing. Run {SETUP} first; build never downloads models."
        )
    model_spec(query_model)
    ranker = reranker_spec(reranker)
    english = models.document_language == "en"
    if english and ranker.model_id != "cross-encoder/ms-marco-MiniLM-L6-v2":
        raise ValueError(
            "English documentation setup requires its prepared English reranker; "
            "rerun setup --document-language en."
        )
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
    provenance = None
    if url is not None:
        from ragforge.importing.website import SiteOptions, import_site

        print("Importing static website documentation...", file=sys.stderr, flush=True)
        snapshot = import_site(
            url,
            project / "data/web" / stamp,
            options=SiteOptions(max_pages=site_max_pages, max_depth=site_max_depth),
            progress=lambda event: print(
                f"Imported {event['pages']} pages; {event['queued']} URLs queued.",
                file=sys.stderr,
                flush=True,
            ),
        )
        documents, provenance = snapshot.documents, snapshot.provenance
        print(f"Saved website snapshot: {snapshot.directory}", file=sys.stderr, flush=True)
    else:
        documents = (documents if documents is not None else project / "documents").absolute()
        # Explicit reuse of a saved snapshot remains entirely offline.
        sibling = documents.parent / "web-sources.json"
        if documents.name == "pages" and sibling.is_file():
            provenance = sibling
    if not documents.is_dir():
        raise ValueError("Document folder does not exist. Put files in documents or pass a folder.")
    if provenance is not None:
        from ragforge.core.web_sources import read_web_sources

        catalogue = read_web_sources(provenance)
        if not catalogue.complete and not allow_partial_site:
            raise ValueError(
                "Website import is incomplete; previous active bundle is unchanged. "
                "Review import-report.json, increase limits or explicitly use --allow-partial-site."
            )
    destination = (
        output if output is not None else project / "kb" / ("documents-" + stamp)
    ).absolute()
    if documents.resolve().is_relative_to(destination.resolve()):
        raise ValueError("the output directory cannot contain the source documents")
    print("Building and verifying local documentation...", file=sys.stderr, flush=True)
    manifest = build_bundle(
        documents,
        destination,
        collection_id="documents",
        web_sources=provenance,
        rerank_batch_size=(8 if ranker.runtime == "openvino-gpu-f16" else 1) if english else None,
        query_planning="facets-v3" if english else None,
        section_context="section-gaps-v3" if english else None,
        query_language="en" if english else None,
        model_directory=query_model,
        reranker_directory=reranker,
        chunk_config=ChunkConfig(strategy="sections"),
        token_aware=True,
        dense_backend="ann",
        threads=threads,
    )
    # The existing builder atomically publishes only a fully verified new bundle.
    # A failure never switches the previous active version or overwrites its data.
    pointer = ActiveBundle(bundle=str(destination), build_id=manifest.build_id)
    atomic_json(state_directory(project) / "active.json", pointer.model_dump(mode="json"))
    return destination


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        description="RAGForge: setup, build documentation, connect an agent."
    )
    command.add_argument("--project", type=Path, default=Path.cwd(), help=argparse.SUPPRESS)
    commands = command.add_subparsers(dest="action", required=True)
    build = commands.add_parser(
        "build", help="Turn the documents folder into a verified searchable bundle."
    )
    build.add_argument("documents", nargs="?", type=Path)
    build.add_argument(
        "--url", help="Import a public static documentation website before building."
    )
    build.add_argument(
        "--site-max-pages", type=int, choices=range(1, 1001), default=100, metavar="1..1000"
    )
    build.add_argument(
        "--site-max-depth", type=int, choices=range(0, 11), default=2, metavar="0..10"
    )
    build.add_argument(
        "--allow-partial-site",
        action="store_true",
        help="Explicitly accept an incomplete website snapshot after reviewing it.",
    )
    build.add_argument("--output", type=Path)
    build.add_argument("--model", type=Path, help="Override the already prepared query model.")
    build.add_argument("--reranker", type=Path, help="Override the already prepared reranker.")
    default_threads = min(8, os.cpu_count() or 1)
    for name in ("agent", "ask", "serve"):
        sub = commands.add_parser(
            name,
            help={
                "agent": "Generate ready MCP config and skill for the latest completed bundle.",
                "ask": "Search local documentation and print evidence with citations.",
                "serve": "Start the persistent MCP server for an agent.",
            }[name],
        )
        sub.add_argument(
            "--bundle", type=Path, help="Use an existing bundle instead of the latest build."
        )
        sub.add_argument("--threads", type=int, choices=range(1, 33), default=default_threads)
        if name == "agent":
            sub.add_argument("--output", type=Path)
        if name == "ask":
            sub.add_argument("query")
            sub.add_argument(
                "--query-translation", help="Faithful query in the documentation language."
            )
    build.add_argument("--threads", type=int, choices=range(1, 33), default=default_threads)
    return command


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        project = arguments.project.resolve(strict=True)
        if arguments.action == "build":
            bundle = ready_documentation(
                project,
                arguments.documents,
                url=arguments.url,
                site_max_pages=arguments.site_max_pages,
                site_max_depth=arguments.site_max_depth,
                allow_partial_site=arguments.allow_partial_site,
                output=arguments.output,
                query_model=arguments.model,
                reranker=arguments.reranker,
                threads=arguments.threads,
            )
            print(
                f'Ready: {bundle}\nSearch: {LAUNCHER} ask "Your question"\nAgent: {LAUNCHER} agent'
            )
        else:
            bundle = arguments.bundle if arguments.bundle is not None else active_bundle(project)
            if arguments.action == "agent":
                stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
                output = (
                    arguments.output if arguments.output is not None else project / "agent" / stamp
                )
                result = create_integration(
                    bundle,
                    output,
                    threads=arguments.threads,
                    rerank_workers=min(8, arguments.threads),
                    warm_up=True,
                )
                print(f"Agent skill: {Path(result['output']) / result['skill']}")
                print(f"Claude / generic MCP: {Path(result['output']) / 'mcp.json'}")
                print(f"Codex MCP: {Path(result['output']) / result['codex_config']}")
                print(f"Connect the agent: {Path(result['output']) / result['instructions']}")
                print("Install the skill and its MCP connection using the generated guide.")
            elif arguments.action == "serve":
                from ragforge.adapters.mcp import create_server

                create_server(
                    bundle,
                    threads=arguments.threads,
                    rerank_workers=min(8, arguments.threads),
                    warm_up=True,
                ).run(transport="stdio")
            else:
                engine = BundleEngine(
                    bundle, threads=arguments.threads, rerank_workers=min(8, arguments.threads)
                )
                response = engine.retrieve(
                    RetrieveRequest(
                        query=arguments.query,
                        query_translation=arguments.query_translation,
                        top_k=50,
                        max_output_chars=48000,
                    )
                )
                if not response.results:
                    print("No matching source evidence found.")
                for rank, item in enumerate(response.evidence_chunks(), 1):
                    source = item.source
                    location = source.url or source.path
                    if source.page is not None:
                        location += f" (page {source.page})"
                    elif source.line_start is not None:
                        location += f" (lines {source.line_start}-{source.line_end})"
                    print(f"\n[{rank}] {location}\n{item.text}")
        return 0
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
