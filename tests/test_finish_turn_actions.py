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


BLOCKED = {"ok": False, "err": "turn has unresolved decisions: every unit in todo.units still has moves: move_unit / "
                               "unit_mission (MISSION_SKIP, MISSION_SLEEP, MISSION_FORTIFY, MISSION_BUILD...) each of them",
           "blocking": "ENDTURN_BLOCKING_UNITS",
           "todo": {"units": [{"id": 40963, "type": "WARRIOR", "x": 21, "y": 48, "moves": 1},
                              {"id": 16385, "type": "ARCHER", "x": 13, "y": 41, "moves": 1}],
                    "promotions": [], "cities": [], "research_unset": False}}


class BlockedGame(FakeGame):
    """The engine refuses the end: units moved one plot still have movement (Codex, 5 of 52 ends on 2026-10-03)."""

    def finish_turn(self, autosave=True, timeout=600, on_wait=None, skip_quiet_turns=0, wake_on=None, force=False):
        self.calls.append(("finish_turn",))
        return {"ok": False, "ended": False, "turn": 7, "end_turn": dict(BLOCKED), "status": self.turn_state(),
                "turns_skipped": 0}

    def end_turn(self, autosave=True, force=False):
        self.calls.append(("end_turn",))
        return dict(BLOCKED)


class LeftoverMovesTests(unittest.TestCase):
    def setUp(self):
        self.fake = BlockedGame()
        self.patches = [mock.patch.object(m, "game", lambda: self.fake),
                        mock.patch.dict(os.environ, {"CIV5_TUNERD_SOCK": "/tmp/civ5-test-fta.sock"}),
                        mock.patch.dict(m._RECENT, {}, clear=True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_the_refusal_hands_back_the_skip_orders_ready_for_the_next_call(self):
        (out,) = anyio.run(session, [("finish_turn", {"actions": [
            {"tool": "move_unit", "args": {"unit_id": 40963, "x": 22, "y": 48}}]})])
        self.assertFalse(out["ok"] or out["ended"])
        self.assertEqual(out["batch"]["done"], 1, "the order ran; the engine then refused the end")
        self.assertEqual(out["end_turn"]["skip_actions"], [
            {"tool": "unit_mission", "args": {"unit_id": 40963, "mission": "MISSION_SKIP"}},
            {"tool": "unit_mission", "args": {"unit_id": 16385, "mission": "MISSION_SKIP"}}])
        self.assertIn("movement left", out["end_turn"]["hint"])
        self.assertIn("finish_turn(actions=skip_actions)", out["end_turn"]["hint"])
        # and they are accepted as the next call's actions as they are
        (again,) = anyio.run(session, [("finish_turn", {"actions": out["end_turn"]["skip_actions"]})])
        self.assertEqual([c for c in self.fake.calls if c[0] == "unit_mission"],
                         [("unit_mission", 40963, "MISSION_SKIP"), ("unit_mission", 16385, "MISSION_SKIP")])
        self.assertEqual(again["batch"]["done"], 2)

    def test_end_turn_carries_the_same_keys_at_top_level(self):
        (out,) = anyio.run(session, [("end_turn", {})])
        self.assertFalse(out["ok"])
        self.assertEqual([a["args"]["unit_id"] for a in out["skip_actions"]], [40963, 16385])
        self.assertIn("MISSION_SKIP", out["skip_actions"][0]["args"]["mission"])

    def test_a_refusal_without_units_gets_no_skip_orders(self):
        self.fake.end_turn = lambda autosave=True, force=False: {"ok": False, "err": "popup needs attention",
                                                                 "pending_popups": [{"type": "x"}]}
        (out,) = anyio.run(session, [("end_turn", {})])
        self.assertNotIn("skip_actions", out)
        self.assertNotIn("hint", out)


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
