"""`do` runs many orders in one call and stops at the first refusal; `action_id` makes any retried call a replay.

Exercised through a real MCP client over the SDK's memory transport with mcp_server.game() replaced by a fake.
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
        self.calls = []

    def has_state(self, name):
        return True

    def turn_state(self, pid=None):
        return {"turn": 7, "active_player": 0, "my_turn": True, "processing": False, "paused": False,
                "blocking_name": "NO_ENDTURN_BLOCKING_TYPE", "todo": {}, "pending_popups": []}

    def discussion_pending(self):
        return False

    def unit_mission(self, unit_id, mission, x=-1, y=-1, build=None):
        self.calls.append(("unit_mission", unit_id, mission))
        if unit_id == 13:
            return {"ok": False, "err": "no such unit"}
        return {"ok": True, "unit": unit_id, "mission": mission}

    def move_unit(self, unit_id, x, y):
        self.calls.append(("move_unit", unit_id, x, y))
        return {"ok": True, "unit": unit_id, "x": x, "y": y}

    def set_production(self, city_id, order, item, append=False):
        self.calls.append(("set_production", city_id, item))
        return {"ok": True}


async def session(calls):
    outs = []
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        async with anyio.create_task_group() as tg:
            srv = m.mcp._lowlevel_server

            async def run_server():
                await srv.run(server_streams[0], server_streams[1], srv.create_initialization_options())

            tg.start_soon(run_server)
            async with ClientSession(client_streams[0], client_streams[1]) as s:
                await s.initialize()
                for name, args in calls:
                    res = await s.call_tool(name, args)
                    outs.append(json.loads(res.content[0].text) if not getattr(res, "is_error", getattr(res, "isError", False)) else {"is_error": True, "text": res.content[0].text})
            tg.cancel_scope.cancel()
    return outs


class DoBatchTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeGame()
        self.patches = [mock.patch.object(m, "game", lambda: self.fake),
                        mock.patch.dict(os.environ, {"CIV5_TUNERD_SOCK": "/tmp/civ5-test-do.sock"}),
                        mock.patch.dict(m._RECENT, {}, clear=True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_orders_run_in_order_and_each_result_comes_back(self):
        (out,) = anyio.run(session, [("do", {"actions": [
            {"tool": "unit_mission", "args": {"unit_id": 7, "mission": "MISSION_FORTIFY"}},
            {"tool": "move_unit", "args": {"unit_id": 8, "x": 3, "y": 4}},
            {"tool": "set_production", "args": {"city_id": 1, "item": "UNIT_ARCHER"}},
        ]})])
        self.assertTrue(out["ok"])
        self.assertEqual(out["done"], 3)
        self.assertEqual([r["tool"] for r in out["results"]], ["unit_mission", "move_unit", "set_production"])
        self.assertEqual(out["results"][1]["result"]["x"], 3)
        self.assertEqual(self.fake.calls[0], ("unit_mission", 7, "MISSION_FORTIFY"))
        self.assertNotIn("skipped", out)

    def test_first_refusal_stops_the_batch_and_lists_the_rest(self):
        (out,) = anyio.run(session, [("do", {"actions": [
            {"tool": "unit_mission", "args": {"unit_id": 7, "mission": "MISSION_SKIP"}},
            {"tool": "unit_mission", "args": {"unit_id": 13, "mission": "MISSION_SKIP"}},
            {"tool": "move_unit", "args": {"unit_id": 8, "x": 3, "y": 4}},
        ]})])
        self.assertFalse(out["ok"])
        self.assertEqual(out["done"], 2)
        self.assertEqual(out["results"][1]["result"]["err"], "no such unit")
        self.assertEqual(out["skipped"], [{"index": 2, "tool": "move_unit"}])
        self.assertEqual(len(self.fake.calls), 2)

    def test_stop_on_refusal_false_runs_everything(self):
        (out,) = anyio.run(session, [("do", {"stop_on_refusal": False, "actions": [
            {"tool": "unit_mission", "args": {"unit_id": 13, "mission": "MISSION_SKIP"}},
            {"tool": "move_unit", "args": {"unit_id": 8, "x": 3, "y": 4}},
        ]})])
        self.assertFalse(out["ok"], "ok is false whenever any order was refused")
        self.assertEqual(out["done"], 2)
        self.assertEqual(len(self.fake.calls), 2)

    def test_bad_arguments_and_forbidden_tools_are_refusals_not_crashes(self):
        (out,) = anyio.run(session, [("do", {"actions": [
            {"tool": "move_unit", "args": {"unit_id": 8, "x": "three"}},
        ]})])
        self.assertFalse(out["ok"])
        self.assertIn("accepts", out["results"][0]["result"])
        (out,) = anyio.run(session, [("do", {"actions": [{"tool": "finish_turn", "args": {}}]})])
        self.assertIn("cannot run inside a batch", out["results"][0]["result"]["err"])
        (out,) = anyio.run(session, [("do", {"actions": [{"tool": "no_such", "args": {}}]})])
        self.assertFalse(out["results"][0]["result"]["ok"])
        (out,) = anyio.run(session, [("do", {"actions": []})])
        self.assertFalse(out["ok"])

    def test_aliases_apply_inside_a_batch(self):
        # x/y for move_unit is fine; `unit` -> `unit_id` is the alias rule.
        (out,) = anyio.run(session, [("do", {"actions": [{"tool": "move_unit", "args": {"unit": 8, "x": 1, "y": 2}}]})])
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.fake.calls, [("move_unit", 8, 1, 2)])


class ActionIdTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeGame()
        self.patches = [mock.patch.object(m, "game", lambda: self.fake),
                        mock.patch.dict(os.environ, {"CIV5_TUNERD_SOCK": "/tmp/civ5-test-do.sock"}),
                        mock.patch.dict(m._RECENT, {}, clear=True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_a_retried_call_with_the_same_action_id_replays_instead_of_repeating(self):
        first, second, other = anyio.run(session, [
            ("move_unit", {"unit_id": 8, "x": 3, "y": 4, "action_id": "t7-move-8"}),
            ("move_unit", {"unit_id": 8, "x": 3, "y": 4, "action_id": "t7-move-8"}),
            ("move_unit", {"unit_id": 8, "x": 5, "y": 6, "action_id": "t7-move-8-again"}),
        ])
        self.assertTrue(first["ok"] and "replayed" not in first)
        self.assertTrue(second["replayed"])
        self.assertEqual(second["x"], 3)
        self.assertNotIn("replayed", other)
        self.assertEqual(len(self.fake.calls), 2, "the replayed call never reached the game")

    def test_action_id_is_scoped_per_tool_and_never_reaches_validation(self):
        a, b = anyio.run(session, [
            ("unit_mission", {"unit_id": 7, "mission": "MISSION_SKIP", "action_id": "same"}),
            ("move_unit", {"unit_id": 7, "x": 1, "y": 1, "action_id": "same"}),
        ])
        self.assertNotIn("replayed", b)
        self.assertNotIn("is_error", a)
        self.assertEqual(len(self.fake.calls), 2)

    def test_action_id_inside_a_batch(self):
        first, again = anyio.run(session, [
            ("do", {"actions": [{"tool": "move_unit", "args": {"unit_id": 8, "x": 3, "y": 4}, "action_id": "m8"},
                                {"tool": "unit_mission", "args": {"unit_id": 13, "mission": "MISSION_SKIP"}, "action_id": "s13"}]}),
            ("do", {"actions": [{"tool": "move_unit", "args": {"unit_id": 8, "x": 3, "y": 4}, "action_id": "m8"},
                                {"tool": "unit_mission", "args": {"unit_id": 13, "mission": "MISSION_SKIP"}, "action_id": "s13"}]}),
        ])
        self.assertTrue(again["results"][0]["result"]["replayed"])
        self.assertTrue(again["results"][1]["result"]["replayed"])
        self.assertEqual(len(self.fake.calls), 2)

    def test_action_id_inside_an_orders_args_is_taken_not_refused(self):
        # Codex (t54, t55) put the id inside args; set_research and move_unit refused the extra field and
        # the rest of each batch was skipped.
        first, again = anyio.run(session, [
            ("do", {"actions": [{"tool": "move_unit", "args": {"unit_id": 8, "x": 3, "y": 4, "action_id": "m8"}}]}),
            ("do", {"actions": [{"tool": "move_unit", "args": {"unit_id": 8, "x": 3, "y": 4, "action_id": "m8"}}]}),
        ])
        self.assertTrue(first["ok"], first)
        self.assertTrue(first["results"][0]["result"]["ok"])
        self.assertTrue(again["results"][0]["result"]["replayed"])
        self.assertEqual(self.fake.calls, [("move_unit", 8, 3, 4)])

    def test_cache_is_bounded(self):
        for i in range(m.RECENT_MAX + 5):
            m._remember_result("t", f"id{i}", "{}")
        self.assertEqual(len(m._RECENT), m.RECENT_MAX)
        self.assertIsNone(m._replayed("t", "id0"))
        self.assertIsNotNone(m._replayed("t", f"id{m.RECENT_MAX + 4}"))


if __name__ == "__main__":
    unittest.main()
