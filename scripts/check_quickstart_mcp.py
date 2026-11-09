"""CI smoke of a generated MCP configuration using public synthetic demo docs."""

import argparse
import asyncio
import json
from pathlib import Path

from mcp import Client, StdioServerParameters


async def check(config: Path) -> None:
    data = json.loads(config.read_text(encoding="utf-8"))
    server = next(iter(data["mcpServers"].values()))
    async with Client(StdioServerParameters(**server), read_timeout_seconds=120) as client:
        result = await client.call_tool("search_docs", {"query": "How are access tokens sent?"})
        if result.is_error or not result.structured_content:
            raise RuntimeError("generated MCP search failed")
        results = result.structured_content["results"]
        if not results or not any(r["source"]["path"] == "authentication.md" for r in results):
            raise RuntimeError("generated MCP search missed the expected synthetic demo source")
        print("Generated MCP configuration: actual model search and citation passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    asyncio.run(asyncio.wait_for(check(args.config), timeout=180))
