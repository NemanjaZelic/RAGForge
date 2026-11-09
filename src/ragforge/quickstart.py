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
) -> Path:
    project = project.resolve(strict=True)
    documents = (documents if documents is not None else project / "documents").absolute()
    models = model_paths(project)
    query_model = query_model if query_model is not None else Path(models.query_model)
    reranker = reranker if reranker is not None else Path(models.reranker)
    if not query_model.exists() or not reranker.exists():
        raise ValueError(f"Prepared models are missing. Run {SETUP} first; build never downloads.")
    model_spec(query_model)
    reranker_spec(reranker)
    if not documents.is_dir():
        raise ValueError("Document folder does not exist. Put files in documents or pass a folder.")
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
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
                print(f"MCP config: {Path(result['output']) / 'mcp.json'}")
                print(f"Agent skill: {Path(result['output']) / result['skill']}")
                print(
                    "Import this MCP config into your agent. "
                    "Existing agent settings were not changed."
                )
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
                for rank, item in enumerate(response.results, 1):
                    source = item.source
                    location = source.path
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
