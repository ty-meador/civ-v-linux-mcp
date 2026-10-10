"""finish_turn on a turn nothing of ours opened (live t147, England, 2026-10-09): Spain's renewal came at the end
of t146, accept_deal answered it, the AI round finished during the answer, and the next finish_turn met t147 cold
-- it tried to end it, and only research-unset refused. Now such a turn is handed back unended."""
from __future__ import annotations

import json
import unittest
from unittest import mock

from harness.game import Game
from tests.test_finish_turn import QUIET, ScriptedGame, status


def unseen_status(turn):
    return status(turn)


class UnseenGame(ScriptedGame):
    """A ScriptedGame whose first status is my turn with its turn_start undelivered."""

    def __init__(self, *a, probe=True, **kw):
        super().__init__(*a, **kw)
        self.probe = probe
        self.arrivals = 0

    def q(self, code, timeout=None):
        assert "turn_start" in code
        return self.probe

    def arrive_if_due(self, ts=None):
        self.arrivals += 1
        self._arrived_at = (self.first_status["turn"], self.seat)
        return {"orders": {"open": 0, "rows": []}}


class UnseenTurnTests(unittest.TestCase):
    def test_an_unseen_turn_is_handed_back_unended(self):
        g = UnseenGame([(status(2), QUIET)], first_status=status(1))
        r = g.finish_turn()
        self.assertTrue(r["ok"])
        self.assertFalse(r["ended"])
        self.assertTrue(r["unseen_turn"])
        self.assertEqual(r["turn"], 1)
        self.assertEqual(r["woke_because"], ["turn_unseen"])
        self.assertNotIn("end", g.log)
        self.assertEqual(g.arrivals, 1)
        self.assertEqual(r["status"]["orders"], {"open": 0, "rows": []})
        self.assertIn("not ended", r["hint"])

    def test_what_the_turn_needs_rides_in_woke_because(self):
        first = status(1, todo={"units": [{"id": 7}], "promotions": [], "cities": [], "research_unset": True})
        g = UnseenGame([(status(2), QUIET)], first_status=first)
        r = g.finish_turn()
        self.assertFalse(r["ended"])
        self.assertEqual(r["woke_because"][0], "turn_unseen")
        self.assertIn("todo.units", r["woke_because"])
        self.assertIn("todo.research_unset", r["woke_because"])

    def test_a_quiet_unseen_turn_passes_when_quiet_turns_may(self):
        g = UnseenGame([(status(2), QUIET)], first_status=status(1))
        r = g.finish_turn(skip_quiet_turns=1)
        self.assertTrue(r["ended"])
        self.assertEqual(r["turn"], 2)
        self.assertEqual(r["turns_skipped"], 1)
        self.assertEqual(g.log[:2], ["digest", "end"])   # opened (its digest taken), then ended as a quiet turn

    def test_a_turn_already_opened_ends_as_before(self):
        g = UnseenGame([(status(2), QUIET)], first_status=status(1))
        g._arrived_at = (1, 0)   # a wait or an order of ours met this turn
        r = g.finish_turn()
        self.assertTrue(r["ended"])
        self.assertEqual(g.log[0], "end")
        self.assertEqual(g.arrivals, 0)

    def test_without_an_undelivered_turn_start_it_ends(self):
        g = UnseenGame([(status(2), QUIET)], first_status=status(1), probe=False)
        r = g.finish_turn()
        self.assertTrue(r["ended"])
        self.assertEqual(g.log[0], "end")

    def test_a_fake_without_a_tuner_reads_seen(self):
        g = ScriptedGame([(status(2), QUIET)], first_status=status(1))   # no q at all
        self.assertFalse(Game.unseen_turn(g, status(1)))
        r = g.finish_turn()
        self.assertTrue(r["ended"])

    def test_not_my_turn_is_never_unseen(self):
        g = UnseenGame([(status(2), QUIET)], first_status=status(1, my_turn=False))
        self.assertFalse(g.unseen_turn(status(1, my_turn=False)))


class ToolTests(unittest.TestCase):
    """finish_turn(actions=...) on an unseen turn runs none of them."""

    def test_the_batch_is_skipped_and_the_turn_handed_back(self):
        from harness import mcp_server as core
        from harness.mcp_tools import turn as tool
        g = UnseenGame([(status(2), QUIET)], first_status=status(1))
        with mock.patch.object(core, "game", return_value=g):
            out = json.loads(tool.finish_turn.__wrapped__(actions=[{"tool": "unit_mission", "args": {"unit_id": 7, "mission": "MISSION_SKIP"}}]))
        self.assertTrue(out["ok"])
        self.assertFalse(out["ended"])
        self.assertTrue(out["unseen_turn"])
        self.assertFalse(out["batch"]["ok"])
        self.assertEqual(out["batch"]["done"], 0)
        self.assertEqual(len(out["batch"]["skipped"]), 1)
        self.assertNotIn("end", g.log)


if __name__ == "__main__":
    unittest.main()
