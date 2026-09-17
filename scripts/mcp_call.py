"""Call one real stdio MCP tool; no gameplay decisions or turn automation.

Usage: .venv/bin/python scripts/mcp_call.py --seat 0 overview '{}'
       .venv/bin/python scripts/mcp_call.py --list
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seat", default="0")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("tool", nargs="?")
    parser.add_argument("arguments", nargs="?", default="{}")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "harness.mcp_server"],
        cwd=str(root), env={**os.environ, "CIV5_SEAT": args.seat},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            if args.list:
                result = await session.list_tools()
                print(json.dumps([t.name for t in result.tools]))
            else:
                result = await session.call_tool(args.tool, json.loads(args.arguments))
                for content in result.content:
                    if content.type == "text":
                        print(content.text)
                if getattr(result, "is_error", getattr(result, "isError", False)):
                    raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
