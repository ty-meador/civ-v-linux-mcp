"""What the Assyria game's turns 31-63 (2026-10-10, late) showed in the Python half: a ranged attack pushed with no
moves left (the engine accepts it and does nothing), an end-turn refusal over a unit whose order the engine had
dropped, and the unseen-turn reply's todo note for a unit under a paused order."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from harness.game import Game
from tests.test_finish_turn import QUIET, status
from tests.test_unseen_turn import UnseenGame


class RangeAttackPrecheckTests(unittest.TestCase):
    PROBE = {"x": 18, "y": 31, "moves": 0, "range": 2, "plot": True, "distance": 1, "out_of_attacks": False,
             "needs_setup": False, "ignores_los": False, "los": True, "visible": True, "enemy": True}

    def reason(self, hard_only, **over):
        f = {**self.PROBE, **over}
        ns = SimpleNamespace(q=lambda code: f, _pid=lambda p: 0, seat=0)
        ns.h = Game.h.__get__(ns)
        return Game._range_attack_reason(ns, 90119, 19, 31, 0, hard_only=hard_only)

    def test_no_moves_is_named_as_a_hard_fact(self):
        # live Assyria t38: the Archer crossed a river onto (19,30), MISSION_RANGE_ATTACK answered ok, damage 0
        why = self.reason(True)
        self.assertIn("no moves left", why)
        self.assertIn("river", why)
        self.assertIn("fires next turn", why)
        self.assertIn("already attacked", self.reason(True, moves=2, out_of_attacks=True))
        self.assertIn("set up", self.reason(True, moves=2, needs_setup=True))
        self.assertIn("range is 2", self.reason(True, moves=2, distance=3))

    def test_the_soft_tests_stay_the_engines(self):
        self.assertIsNone(self.reason(True, moves=2, los=False), "line of fire is the engine's call before the push")
        self.assertIn("line of fire", self.reason(False, moves=2, los=False), "and named after its refusal")
        self.assertIsNone(self.reason(True, moves=2, enemy=False))
        self.assertIn("no enemy", self.reason(False, moves=2, enemy=False))

    def test_unit_mission_refuses_before_the_push(self):
        g = Game.__new__(Game)
        g.seat = 0
        g._pid = lambda p=None: 0
        g.q = lambda code: {}
        g._range_attack_reason = lambda *a, **k: "the unit has no moves left this turn"
        pushed = []
        g._order = lambda lua: pushed.append(lua) or {"ok": True}
        r = g._unit_mission(90119, "MISSION_RANGE_ATTACK", 19, 31)
        self.assertEqual(r, {"ok": False, "err": "action is not currently legal", "reason": "the unit has no moves left this turn"})
        self.assertEqual(pushed, [], "nothing was sent to the game")


class RerunOrdersOnRefusalTests(unittest.TestCase):
    """Live Assyria t41: the Worker's mine at (17,29) was dropped by the engine mid-turn (a Spearman two plots away),
    the order still read "building" and finish_turn refused with the idle Worker in todo."""

    def game(self, active, rows):
        calls = []

        def run_orders(trigger):
            calls.append(trigger)
            return rows

        ns = SimpleNamespace(notebook=lambda: SimpleNamespace(orders=lambda s: active), run_orders=run_orders, calls=calls)
        return ns

    def test_orders_holding_a_blocking_unit_run_again(self):
        rows = [{"id": 1, "unit": {"id": 65540}, "status": "active", "did": ["build MINE at (17,29): issued"]},
                {"id": 2, "unit": {"id": 9}, "status": "active", "did": ["move to (3,3): issued"]},
                {"id": 3, "unit": {"id": 11}, "status": "active"}]
        g = self.game([{"id": 1, "unit": {"id": 65540}}], rows)
        ts = status(41, todo={"units": [{"id": 65540, "type": "WORKER", "moves": 2}], "cities": [], "promotions": [], "research_unset": False})
        out = Game._rerun_orders_for_blocking(g, ts)
        self.assertEqual(out, [rows[0]], "only the blocking unit's row, and only one that issued something")
        self.assertEqual(g.calls, ["turn_end"])

    def test_nothing_runs_without_a_blocking_unit_under_an_order(self):
        g = self.game([{"id": 1, "unit": {"id": 8}}], [{"id": 1, "unit": {"id": 8}, "did": ["x"]}])
        ts = status(41, todo={"units": [{"id": 65540}], "cities": [], "promotions": [], "research_unset": False})
        self.assertIsNone(Game._rerun_orders_for_blocking(g, ts))
        self.assertEqual(g.calls, [], "no run when no blocking unit is under an order")
        self.assertIsNone(Game._rerun_orders_for_blocking(g, status(41)))
        rows = [{"id": 1, "unit": {"id": 65540}, "status": "active"}]
        g = self.game([{"id": 1, "unit": {"id": 65540}}], rows)
        ts = status(41, todo={"units": [{"id": 65540}], "cities": [], "promotions": [], "research_unset": False})
        self.assertIsNone(Game._rerun_orders_for_blocking(g, ts), "a run that issued nothing is not reported")


class UnseenTurnHeldUnitNoteTests(unittest.TestCase):
    def test_the_unseen_reply_notes_a_unit_under_a_paused_order(self):
        """Live Assyria t52: the finish_turn reply that handed t52 back unended still said "queued move did not resume;
        re-issue move_unit" for the Settler whose order had paused, while turn_status a moment later said resume_order."""
        row = {"id": 8, "unit": {"id": 114697}, "status": "paused",
               "pause": {"kind": "hostile", "reason": "a hostile BARBARIAN_SPEARMAN is in sight 2 plot(s) away"}}

        class G(UnseenGame):
            def arrive_if_due(self, ts=None):
                self.arrivals += 1
                self._arrived_at = (self.first_status["turn"], self.seat)
                return {"orders": {"open": 1, "rows": [row], "paused": 1}}

        todo = {"units": [{"id": 114697, "type": "SETTLER", "x": 15, "y": 27, "moves": 2, "stalled_mission": True,
                           "note": "queued move did not resume; re-issue move_unit"}],
                "cities": [], "promotions": [], "research_unset": False}
        g = G([(status(53), QUIET)], first_status=status(52, todo=todo, blocking="ENDTURN_BLOCKING_UNITS"))
        r = g.finish_turn()
        self.assertTrue(r["unseen_turn"])
        u = r["status"]["todo"]["units"][0]
        self.assertEqual(u["order"], {"id": 8, "status": "paused", "reason": row["pause"]["reason"]})
        self.assertIn("resume_order carries on", u["note"])
        self.assertNotIn("re-issue move_unit", u["note"])


if __name__ == "__main__":
    unittest.main()
