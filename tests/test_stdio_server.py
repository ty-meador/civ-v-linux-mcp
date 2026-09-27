"""The server as a client really runs it: `python -m harness.mcp_server` over stdio, no game.

The in-process suite imports harness.mcp_server once; a stdio client runs it as __main__, and after the
tool-module split that copy served no tools at all (live 2026-09-27: "Unknown tool: turn_status") while every
in-process test passed. This lists the tools and calls the two that need no game through the real transport.
"""
import asyncio
import json
import os
import sys
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent


async def _over_stdio():
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "harness.mcp_server"], cwd=str(ROOT),
        env={**os.environ, "CIV5_SEAT": "1", "CIV5_TUNERD_SOCK": "/nonexistent/civ5-test.sock"})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = (await session.list_tools()).tools
            guide = await session.call_tool("how_to_play", {"topic": "first_turn"})
            status = await session.call_tool("turn_status", {})
            return init, tools, guide, status


class StdioServerTests(unittest.TestCase):
    def test_a_stdio_client_sees_every_tool_and_can_call_one(self):
        init, tools, guide, status = asyncio.run(_over_stdio())
        names = {t.name for t in tools}
        self.assertGreater(len(names), 140, sorted(names)[:5])
        for name in ("turn_status", "finish_turn", "how_to_play", "do", "set_research", "load_latest"):
            self.assertIn(name, names)
        self.assertIn("finish_turn", init.instructions or "")
        self.assertLess(len(init.instructions or ""), 2000)
        text = "".join(c.text for c in guide.content if c.type == "text")
        self.assertIn("## Minimal first turn", text)
        # a tool that needs the game answers with a readable refusal, not a transport error
        text = "".join(c.text for c in status.content if c.type == "text")
        self.assertFalse(json.loads(text)["ok"])
        self.assertIn("err", json.loads(text))
