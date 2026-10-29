"""Quiet turns stay quiet through the harness's own screens and my own orders (GitLab #99); a gold-per-turn drop
names its cause (GitLab #78)."""
import unittest

from harness.briefing import compare, snapshot
from harness.game import Game


class QuietWakeTests(unittest.TestCase):
    def _game(self):
        g = Game.__new__(Game)
        g.seat = 0
        g._alert_wake_reasons = lambda ts: []
        g._expiring_new = lambda k, v, ts: v
        return g

    def test_ruins_city_state_greetings_own_founding_and_own_strikes_do_not_wake(self):
        g = self._game()
        ts = {"todo": {}, "blocking_name": "NO_ENDTURN_BLOCKING_TYPE", "pending_popups": []}
        digest = {"events": [
            {"kind": "popup_shown", "data": {"name": "BUTTONPOPUP_GOODY_HUT_REWARD", "reward": "GOODY_GOLD"}},
            {"kind": "popup_shown", "data": {"name": "BUTTONPOPUP_CITY_STATE_GREETING", "city_state": "Sidon"}},
            {"kind": "city_created", "data": {"player": 0, "name": "Tikal", "x": 1, "y": 1}},
            {"kind": "alert", "data": {"text": "Tikal bombarded an enemy Brute! (36 damage)"}},
            {"kind": "alert", "data": {"text": "Your Atlatlist bombarded an enemy Warrior! (20 damage)"}},
            {"kind": "alert", "data": {"text": "The enemy has been spotted near Palenque!", "hostiles_as_in": 41}},
        ], "notifications": []}
        self.assertEqual(g._wake_reasons(ts, digest), [])
        loud = {"events": [
            {"kind": "city_created", "data": {"player": 3, "name": "Mombasa"}},
            {"kind": "alert", "data": {"text": "The enemy has been spotted near Palenque!", "hostiles": [{"unit": "BRUTE"}]}},
            {"kind": "popup_shown", "data": {"name": "BUTTONPOPUP_WONDER_COMPLETED"}},
        ], "notifications": []}
        self.assertEqual(g._wake_reasons(ts, loud), ["event:city_created", "alert:The enemy has been spotted near Palenque!", "event:popup_shown"])
        self.assertEqual(g._wake_reasons(ts, digest, ("ruins",))[:0], [])   # the API still takes wake words
        self.assertIn("event:popup_shown", g._wake_reasons(ts, digest, ("goody",)))


class GptCauseTests(unittest.TestCase):
    def test_a_drop_over_a_quarter_names_the_expense_that_grew(self):
        prev = snapshot(239, {"gold": 2334, "gold_per_turn": 38, "expenses": {"unit_maintenance": 180, "building_maintenance": 90}}, [], [], 1)
        now = snapshot(243, {"gold": 2400, "gold_per_turn": 16, "expenses": {"unit_maintenance": 231, "building_maintenance": 90}}, [], [], 2)
        d = compare(prev, now)["empire"]["gold_per_turn"]
        self.assertEqual((d["was"], d["now"]), (38, 16))
        self.assertIn("unit_maintenance rose 180 -> 231", d["cause"])
        small = snapshot(244, {"gold": 2400, "gold_per_turn": 34, "expenses": {"unit_maintenance": 185, "building_maintenance": 90}}, [], [], 3)
        self.assertNotIn("cause", compare(prev, small)["empire"]["gold_per_turn"])


if __name__ == "__main__":
    unittest.main()
