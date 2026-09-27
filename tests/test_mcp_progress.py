"""Progress notifications reach a real MCP client while wait_for_my_turn / finish_turn are waiting.

The whole chain is exercised in-process over the SDK's memory transport: the client asks for progress
(a progressToken on the call), the tool runs in the SDK's worker thread, the reporter hops back onto the
event loop, and the notification arrives at the client's progress callback. No game: mcp_server.game()
is replaced by a fake whose wait calls on_wait a few times.
"""
import json
import os
import unittest
from unittest import mock

import anyio
from mcp import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from harness import mcp_server as m


class FakeGame:
    seat = 0

    def __init__(self):
        self.waits = []

    def has_state(self, name):
        return True

    def turn_state(self, pid=None):
        return {"turn": 7, "active_player": 0, "my_turn": True, "processing": False, "paused": False,
                "blocking_name": "NO_ENDTURN_BLOCKING_TYPE", "todo": {}, "pending_popups": []}

    def wait_for_my_turn(self, timeout=90, poll=1.0, on_wait=None):
        self.waits.append(timeout)
        ts = {"turn": 7, "active_player": 3}
        for elapsed in (0.0, 5.5, 11.0, 16.5):
            if on_wait:
                on_wait(elapsed, ts)
        return self.turn_state()

    def finish_turn(self, autosave=True, timeout=600, on_wait=None, skip_quiet_turns=0, wake_on=None, force=False):
        if on_wait:
            on_wait(0.0, {"turn": 7, "active_player": 3})
            on_wait(0.0, {"skipping_quiet_turn": 8})
        return {"ok": True, "turn": 9, "turns_skipped": 1, "woke_because": ["turn_started"], "digest": {}, "status": {}}

    def notebook(self):
        class NB:
            def latest(self, limit=8):
                return [{"id": 1, "turn": 3, "tag": "plan", "text": "hold the pass"}]
        return NB()


async def call_with_progress(tool, args):
    got = []

    async def cb(progress, total, message):
        got.append((progress, message))

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        async with anyio.create_task_group() as tg:
            srv = m.mcp._lowlevel_server

            async def run_server():
                await srv.run(server_streams[0], server_streams[1], srv.create_initialization_options())

            tg.start_soon(run_server)
            async with ClientSession(client_streams[0], client_streams[1]) as s:
                await s.initialize()
                res = await s.call_tool(tool, args, progress_callback=cb)
                out = json.loads(res.content[0].text)
            tg.cancel_scope.cancel()
    return out, got


class McpProgressTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeGame()
        self.patch = mock.patch.object(m, "game", lambda: self.fake)
        self.patch.start()
        self.env = mock.patch.dict(os.environ, {"CIV5_TUNERD_SOCK": "/tmp/civ5-test-progress.sock"})
        self.env.start()

    def tearDown(self):
        self.patch.stop()
        self.env.stop()

    def test_wait_for_my_turn_streams_progress_to_the_client(self):
        out, got = anyio.run(call_with_progress, "wait_for_my_turn", {"timeout_seconds": 300})
        self.assertTrue(out["my_turn"])
        self.assertEqual(self.fake.waits, [300])
        self.assertEqual([p for p, _ in got], [1.0, 2.0, 3.0, 4.0], got)
        self.assertIn("waiting for my turn (seat 0): 6s", got[1][1])

    def test_finish_turn_streams_progress_and_carries_notes(self):
        out, got = anyio.run(call_with_progress, "finish_turn", {"skip_quiet_turns": 1})
        self.assertEqual(out["turn"], 9)
        self.assertEqual(out["notes"][0]["text"], "hold the pass")
        self.assertEqual(len(got), 2)
        self.assertIn("turn 8 was quiet", got[1][1])

    def test_ctx_is_not_a_tool_argument(self):
        for name in ("wait_for_my_turn", "finish_turn"):
            props = m.mcp._tool_manager.get_tool(name).parameters["properties"]
            self.assertNotIn("ctx", props)


if __name__ == "__main__":
    unittest.main()
