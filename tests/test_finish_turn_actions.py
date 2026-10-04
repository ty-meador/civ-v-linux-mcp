"""finish_turn(actions=[...]): a turn's closing orders and its end in one call.

Through the MCP memory transport with a fake game, as test_do_batch: the orders run as `do` would (first
refusal stops them, action_id replays), the turn ends only when every one was ok, and the reply carries
`batch` either way -- with the new turn on success, with the current status and ended=false on a refusal.
"""
import os
import unittest
from unittest import mock

import anyio

from harness import mcp_server as m
from tests.test_do_batch import FakeGame, session


class FinishGame(FakeGame):
    def finish_turn(self, autosave=True, timeout=600, on_wait=None, skip_quiet_turns=0, wake_on=None, force=False):
        self.calls.append(("finish_turn",))
        return {"ok": True, "ended": True, "turn": 8, "status": {**self.turn_state(), "turn": 8},
                "digest": {"events": [], "notifications": []}, "turns_skipped": 0}


class FinishTurnActionsTests(unittest.TestCase):
    def setUp(self):
        self.fake = FinishGame()
        self.patches = [mock.patch.object(m, "game", lambda: self.fake),
                        mock.patch.dict(os.environ, {"CIV5_TUNERD_SOCK": "/tmp/civ5-test-fta.sock"}),
                        mock.patch.dict(m._RECENT, {}, clear=True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_the_orders_run_and_then_the_turn_ends(self):
        (out,) = anyio.run(session, [("finish_turn", {"actions": [
            {"tool": "unit_mission", "args": {"unit_id": 7, "mission": "MISSION_FORTIFY"}},
            {"tool": "set_production", "args": {"city_id": 1, "item": "UNIT_ARCHER"}},
        ]})])
        self.assertTrue(out["ok"])
        self.assertTrue(out["ended"])
        self.assertEqual(out["turn"], 8)
        self.assertEqual(out["batch"]["done"], 2)
        self.assertEqual([r["tool"] for r in out["batch"]["results"]], ["unit_mission", "set_production"])
        self.assertEqual([c[0] for c in self.fake.calls], ["unit_mission", "set_production", "finish_turn"])

    def test_a_refused_order_leaves_the_turn_open(self):
        (out,) = anyio.run(session, [("finish_turn", {"actions": [
            {"tool": "unit_mission", "args": {"unit_id": 13, "mission": "MISSION_SKIP"}},
            {"tool": "move_unit", "args": {"unit_id": 8, "x": 3, "y": 4}},
        ]})])
        self.assertFalse(out["ok"])
        self.assertFalse(out["ended"])
        self.assertEqual(out["turn"], 7, "the turn handed back is the one still open")
        self.assertEqual(out["batch"]["results"][0]["result"]["err"], "no such unit")
        self.assertEqual(out["batch"]["skipped"], [{"index": 1, "tool": "move_unit"}])
        self.assertIn("status", out)
        self.assertIn("gate", out)
        self.assertIn("not ended", out["hint"])
        self.assertNotIn(("finish_turn",), self.fake.calls)

    def test_no_actions_is_the_plain_boundary(self):
        (out,) = anyio.run(session, [("finish_turn", {})])
        self.assertTrue(out["ended"])
        self.assertNotIn("batch", out)
        self.assertEqual(self.fake.calls, [("finish_turn",)])

    def test_the_wait_tools_cannot_hide_inside_the_actions(self):
        (out,) = anyio.run(session, [("finish_turn", {"actions": [{"tool": "end_turn", "args": {}}]})])
        self.assertFalse(out["ended"])
        self.assertIn("cannot run inside a batch", out["batch"]["results"][0]["result"]["err"])
        self.assertEqual(self.fake.calls, [])

    def test_an_order_with_an_action_id_replays_on_the_retry(self):
        order = {"tool": "unit_mission", "args": {"unit_id": 7, "mission": "MISSION_FORTIFY"}, "action_id": "t7-fortify-7"}
        first, second = anyio.run(session, [("finish_turn", {"actions": [order]}), ("finish_turn", {"actions": [order]})])
        self.assertTrue(first["ended"] and second["ended"])
        self.assertTrue(second["batch"]["results"][0]["result"].get("replayed"))
        self.assertEqual([c for c in self.fake.calls if c[0] == "unit_mission"], [("unit_mission", 7, "MISSION_FORTIFY")],
                         "the unit was fortified once")


if __name__ == "__main__":
    unittest.main()
