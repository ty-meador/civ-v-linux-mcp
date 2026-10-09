"""Call several real stdio MCP tools over ONE server session; no gameplay decisions.

`scripts/mcp_call.py` spawns a whole MCP server per call, which is fine for one probe and
painful for a turn's worth of them. This keeps a single session open and runs a script of
calls against it, printing one JSON line per call, so a turn can be played (or a screen
audited) end to end through the real MCP surface rather than through harness.Game.

Usage:
    .venv/bin/python scripts/mcp_session.py --seat 0 overview '{}' units '{}'
    .venv/bin/python scripts/mcp_session.py --seat 0 --script calls.txt   # "tool {json}" per line
    echo 'cities {}' | .venv/bin/python scripts/mcp_session.py --seat 0 --script -

A call whose result is an error stops the run unless --keep-going, so a script does not
carry on issuing orders after the state it was reasoning about turned out to be wrong.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def parse_script(text: str) -> list[tuple[str, dict]]:
    calls = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, _, args = line.partition(" ")
        calls.append((name, json.loads(args) if args.strip() else {}))
    return calls


def parse_pairs(items: list[str]) -> list[tuple[str, dict]]:
    """`tool '{json}' tool '{json}' ...`; the argument object may be omitted for no-arg tools."""
    calls, i = [], 0
    while i < len(items):
        name = items[i]
        if i + 1 < len(items) and items[i + 1].lstrip().startswith("{"):
            calls.append((name, json.loads(items[i + 1])))
            i += 2
        else:
            calls.append((name, {}))
            i += 1
    return calls


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seat", default="0")
    ap.add_argument("--script", help="file with one 'tool {json}' per line, or - for stdin")
    ap.add_argument("--keep-going", action="store_true", help="do not stop at the first failing call")
    ap.add_argument("calls", nargs="*", help="tool '{json}' tool '{json}' ...")
    a = ap.parse_args()

    calls = parse_pairs(a.calls)
    if a.script:
        text = sys.stdin.read() if a.script == "-" else Path(a.script).read_text()
        calls += parse_script(text)
    if not calls:
        ap.error("nothing to call")

    root = Path(__file__).resolve().parent.parent
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "harness.mcp_server"],
        cwd=str(root), env={**os.environ, "CIV5_SEAT": a.seat},
    )
    failed = 0
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for name, args in calls:
                try:
                    result = await session.call_tool(name, args)
                except Exception as e:  # report, do not crash the run
                    print(json.dumps({"tool": name, "error": f"{type(e).__name__}: {e}"}))
                    failed += 1
                    if not a.keep_going:
                        break
                    continue
                for content in result.content:
                    if content.type == "text":
                        print(f"== {name} {json.dumps(args, separators=(',', ':'))}\n{content.text}")
                if getattr(result, "is_error", getattr(result, "isError", False)):
                    failed += 1
                    if not a.keep_going:
                        break
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
