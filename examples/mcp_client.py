"""Run a real stdio evidence workflow; no LLM or fabricated answer generation."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

from ragforge.core.contracts import RetrievalResponse, RetrieveRequest


def citation(source: dict[str, object]) -> str:
    location = str(source["path"])
    if source.get("page") is not None:
        return f"{location} (page {source['page']})"
    if source.get("line_start") is not None:
        return f"{location}:{source['line_start']}-{source['line_end']}"
    return location


async def evidence(
    artifact: Path,
    query: str,
    *,
    top_k: int = 3,
    max_output_chars: int = 16000,
    threads: int = 4,
    timeout_seconds: int = 600,
) -> dict[str, object]:
    request = RetrieveRequest(query=query, top_k=top_k, max_output_chars=max_output_chars)
    if type(threads) is not int or not 1 <= threads <= 32:
        raise ValueError("threads must be an integer between 1 and 32")
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 3600:
        raise ValueError("timeout_seconds must be an integer between 1 and 3600")
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "ragforge",
            "serve",
            str(artifact.resolve(strict=True)),
            "--threads",
            str(threads),
        ],
        env={"PYTHONIOENCODING": "utf-8", "OTEL_SDK_DISABLED": "true"},
    )
    async with Client(parameters, read_timeout_seconds=timeout_seconds) as client:
        tools = await client.list_tools()
        collections = await client.call_tool("list_collections", {})
        if collections.is_error:
            raise RuntimeError("MCP collection listing failed")
        search = await client.call_tool(
            "search_docs", request.model_dump(mode="json", exclude_none=True)
        )
        if search.is_error:
            raise RuntimeError("MCP search failed")
        response = RetrievalResponse.model_validate(search.structured_content)
        contexts: list[dict[str, object]] = []
        if response.results:
            first = response.results[0]
            expanded = await client.call_tool(
                "fetch_context",
                {
                    "collection_id": first.collection_id,
                    "chunk_id": first.chunk_id,
                    "neighbors": 1,
                    "max_output_chars": max_output_chars,
                },
            )
            if expanded.is_error:
                raise RuntimeError("MCP context failed")
            context = RetrievalResponse.model_validate(expanded.structured_content)
            contexts = [
                {
                    "citation": citation(r.source.model_dump()),
                    "text": r.text,
                    "chunk_id": r.chunk_id,
                }
                for r in context.results
            ]
        return {
            "workflow": "deterministic MCP client; not an LLM evaluation",
            "protocol_version": client.session.protocol_version,
            "tools": [tool.name for tool in tools.tools],
            "collections": collections.structured_content,
            "query": query,
            "request_limits": {
                "top_k": top_k,
                "max_output_chars": max_output_chars,
                "threads": threads,
                "timeout_seconds": timeout_seconds,
            },
            "evidence": [
                {
                    "citation": citation(r.source.model_dump()),
                    "text": r.text,
                    "chunk_id": r.chunk_id,
                    "retrieval_method": r.retrieval_method,
                }
                for r in response.results
            ],
            "context": contexts,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("query")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--max-output-chars", type=int, default=16000)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    args = parser.parse_args()
    result = asyncio.run(
        evidence(
            args.artifact,
            args.query,
            top_k=args.top_k,
            max_output_chars=args.max_output_chars,
            threads=args.threads,
            timeout_seconds=args.timeout_seconds,
        )
    )
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
