"""Measure warmed stdio MCP round trips; startup is reported separately.

Examples:
  python scripts/measure_query_latency.py kb/my-bundle --query "How does retry work?"
  Add --output .cache/latency.json to save the report.
No corpus benchmark is started. Models must already be present in the bundle.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("bundle", type=Path)
    command.add_argument("--query", action="append", default=[])
    command.add_argument("--query-translation")
    command.add_argument("--repeats", type=int, choices=range(1, 4), default=1)
    command.add_argument(
        "--threads", type=int, choices=range(1, 33), default=min(8, os.cpu_count() or 1)
    )
    command.add_argument("--output", type=Path)
    command.add_argument("--_server", action="store_true", help=argparse.SUPPRESS)
    return command


async def measure(arguments: argparse.Namespace) -> dict[str, object]:
    from mcp import Client, StdioServerParameters

    from ragforge.core.contracts import RetrieveRequest

    requests = [
        RetrieveRequest(
            query=q, query_translation=arguments.query_translation, top_k=50, max_output_chars=48000
        )
        for q in arguments.query
    ]
    server = StdioServerParameters(
        command=sys.executable,
        args=[
            str(Path(__file__).resolve()),
            str(arguments.bundle.resolve(strict=True)),
            "--_server",
            "--threads",
            str(arguments.threads),
        ],
        env={
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "HF_HUB_OFFLINE": "1",
            "OTEL_SDK_DISABLED": "true",
        },
    )
    rows = []
    started = time.perf_counter()
    async with Client(server, read_timeout_seconds=600) as client:
        startup = time.perf_counter() - started
        for number, request in enumerate(requests, 1):
            expected = None
            for repeat in range(arguments.repeats):
                start = time.perf_counter()
                call = await client.call_tool("search_docs", request.model_dump(mode="json"))
                elapsed = time.perf_counter() - start
                if call.is_error or not call.structured_content:
                    raise RuntimeError("MCP search failed; no latency success is recorded")
                result = call.structured_content
                digest = hashlib.sha256(
                    json.dumps(
                        result, sort_keys=True, ensure_ascii=True, separators=(",", ":")
                    ).encode()
                ).hexdigest()
                if expected is not None and digest != expected:
                    raise RuntimeError(
                        "complete response changed between repeated uncached requests"
                    )
                expected = digest
                rows.append(
                    {
                        "question": number,
                        "repeat": repeat + 1,
                        "mcp_roundtrip_seconds": elapsed,
                        "under_10_seconds": elapsed < 10,
                        "returned_chunks": len(result["results"]),
                        "attached_context_chunks": len(result.get("context", [])),
                        "total_evidence_characters": sum(
                            len(c["text"]) for c in [*result["results"], *result.get("context", [])]
                        ),
                        "response_sha256": digest,
                    }
                )
    return {
        "startup_and_warmup_seconds": startup,
        "neural_cache_enabled": False,
        "threads": arguments.threads,
        "rerank_workers": min(8, arguments.threads),
        "target_seconds": 10,
        "includes": "MCP request, retrieval, context, response serialization and transport",
        "excludes": "startup/warmup, document acquisition/build, agent answer generation",
        "scope": (
            "At most five caller-selected questions; not a quality benchmark "
            "or a whole-bank latency guarantee"
        ),
        "measurements": rows,
    }


def main() -> int:
    command = parser()
    arguments = command.parse_args()
    if arguments._server:
        from ragforge.adapters.mcp import create_server

        create_server(
            arguments.bundle,
            threads=arguments.threads,
            rerank_workers=min(8, arguments.threads),
            rerank_cache_batches=0,
            warm_up=True,
        ).run(transport="stdio")
        return 0
    if not 1 <= len(arguments.query) <= 5:
        command.error(
            "provide 1..5 --query values; this command never runs a full corpus benchmark"
        )
    if arguments.query_translation is not None and len(arguments.query) != 1:
        command.error("--query-translation requires exactly one --query")
    if arguments.output is not None:
        if arguments.output.exists():
            command.error("output already exists; choose a new report path")
        if arguments.output.resolve().is_relative_to(arguments.bundle.resolve(strict=True)):
            command.error("keep timing reports outside the immutable bundle")
    report = asyncio.run(measure(arguments))
    content = json.dumps(report, indent=2) + "\n"
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        # Refuse accidental replacement of an existing source or previous report.
        with arguments.output.open("x", encoding="utf-8") as stream:
            stream.write(content)
    print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
