"""CI smoke of a generated MCP configuration using public synthetic demo docs."""

import argparse
import asyncio
import json
import tomllib
from pathlib import Path

from mcp import Client, StdioServerParameters


async def check(config: Path) -> None:
    data = json.loads(config.read_text(encoding="utf-8"))
    name, server = next(iter(data["mcpServers"].items()))
    codex = tomllib.loads((config.parent / "codex.toml").read_text(encoding="utf-8"))
    profile = codex["mcp_servers"][name]
    if {key: profile[key] for key in ("command", "args", "env")} != server:
        raise RuntimeError("Codex and Claude-compatible profiles select different servers")
    skill = config.parent / "skills" / name / "SKILL.md"
    if not skill.is_file() or not (skill.parent / "agents/openai.yaml").is_file():
        raise RuntimeError("generated agent skill is incomplete")
    if not (config.parent / "INSTALL.md").is_file():
        raise RuntimeError("missing skill/client installation instructions")
    async with Client(StdioServerParameters(**server), read_timeout_seconds=120) as client:
        result = await client.call_tool("search_docs", {"query": "How are access tokens sent?"})
        if result.is_error or not result.structured_content:
            raise RuntimeError("generated MCP search failed")
        results = result.structured_content["results"]
        if not results or not any(r["source"]["path"] == "authentication.md" for r in results):
            raise RuntimeError("generated MCP search missed the expected synthetic demo source")
        selected = next(r for r in results if r["source"]["path"] == "authentication.md")
        context = await client.call_tool(
            "fetch_context",
            {
                "collection_id": selected["collection_id"],
                "chunk_id": selected["chunk_id"],
                "neighbors": 1,
            },
        )
        if context.is_error or not context.structured_content:
            raise RuntimeError("generated MCP context read failed")
        if not all(
            r["document_id"] == selected["document_id"]
            for r in context.structured_content["results"]
        ):
            raise RuntimeError("context escaped the selected source")
        print(
            "Skill + both client profiles: actual model search, context read and citation passed."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    asyncio.run(asyncio.wait_for(check(args.config), timeout=180))
