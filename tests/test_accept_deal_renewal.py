"""accept_deal on a renewal: the offer's rows carry the OLD deal's final turn (the engine clones the expiring
deal onto the scratch table), so `accepted_items` said final_turn t161 / turns_left 0 for a deal just signed to
run to t186 (live t161 Venice, China's open-borders renewal; current_deals had the right row). Once the deal
count has risen, the new deal is read off current_deals and its end replaces the stale one."""
from __future__ import annotations

import unittest
from unittest import mock

from harness.client import TunerdError
from harness.game import Game


def _game(current_deals):
    g = Game.__new__(Game)
    g.seat = 0
    g._runtime_ok = True
    g._trade_state = "DiploTrade"
    g.states = lambda: ["InGame", "DiploTrade"]
    g._trade_up = lambda states=None: True
    g.incoming_deal = lambda pid=None: {
        "ok": True, "from": 3, "to": 0, "n": 2,
        "items": [{"type": "OPEN_BORDERS", "from_us": True, "duration": 25, "final_turn": 161, "turns_left": 0},
                  {"type": "OPEN_BORDERS", "from_us": False, "from": 3, "duration": 25, "final_turn": 161, "turns_left": 0}]}
    snaps = iter([{"deals": 3, "gold": 100}, {"deals": 4, "gold": 100}])
    g._deal_snapshot = lambda items, pid: next(snaps)
    g._settle_leader_remark = lambda: {"remark": "Very well."}
    g.leader_greeting_pending = lambda: False
    g.c = mock.Mock()
    g.current_deals = current_deals
    return g


class AcceptDealRenewalTests(unittest.TestCase):
    def setUp(self):
        self.sleep = mock.patch("harness.game.time.sleep").start()
        self.addCleanup(mock.patch.stopall)

    def test_the_new_deal_replaces_the_stale_end_on_the_accepted_rows(self):
        cur = {"ok": True, "deals": [
            {"other": 3, "civ": "China", "start_turn": 136, "duration": 25, "ends_on": 161, "turns_left": 0, "items": []},
            {"other": 3, "civ": "China", "start_turn": 161, "duration": 25, "ends_on": 186, "turns_left": 25, "items": []},
            {"other": 5, "civ": "Russia", "start_turn": 150, "duration": 30, "ends_on": 180, "turns_left": 19, "items": []},
        ]}
        out = _game(lambda pid=None: cur).accept_deal()
        self.assertTrue(out["ok"])
        self.assertEqual(out["new_deal"], {"other": 3, "civ": "China", "start_turn": 161, "duration": 25,
                                           "ends_on": 186, "turns_left": 25})
        for it in out["accepted_items"]:
            self.assertEqual((it["final_turn"], it["turns_left"], it["final_turn_offered"]), (186, 25, 161))
        self.assertTrue(out["renewal"])
        self.assertIn("runs to turn 186", out["note"])
        self.assertEqual(out["effects"], {"deals": {"before": 3, "after": 4}})

    def test_a_fresh_deal_whose_rows_already_say_the_right_end_is_left_alone(self):
        cur = {"ok": True, "deals": [
            {"other": 3, "civ": "China", "start_turn": 161, "duration": 25, "ends_on": 161, "turns_left": 0, "items": []},
        ]}
        # ends_on equals the rows' final_turn: nothing stale, no renewal flag, new_deal still named
        out = _game(lambda pid=None: cur).accept_deal()
        self.assertEqual(out["new_deal"]["ends_on"], 161)
        self.assertNotIn("renewal", out)
        self.assertNotIn("note", out)
        self.assertNotIn("final_turn_offered", out["accepted_items"][0])

    def test_current_deals_refusing_or_failing_leaves_the_rows_as_offered(self):
        for cur in ({"ok": False, "err": "trade table is occupied; answer incoming_deal first", "deals": []},
                    {"ok": True, "deals": [{"other": 5, "ends_on": 180, "turns_left": 19}]}):
            out = _game(lambda pid=None, cur=cur: cur).accept_deal()
            self.assertNotIn("new_deal", out)
            self.assertEqual(out["accepted_items"][0]["final_turn"], 161)

        def boom(pid=None):
            raise TunerdError("gone")
        out = _game(boom).accept_deal()
        self.assertNotIn("new_deal", out)
        self.assertTrue(out["ok"])

    def test_an_unchanged_deal_count_never_reads_current_deals(self):
        g = _game(lambda pid=None: self.fail("current_deals must not be read when no deal was added"))
        snaps = iter([{"deals": 3}] * 50)
        g._deal_snapshot = lambda items, pid: next(snaps)
        with mock.patch("harness.game.time.monotonic", side_effect=[0, 0.1, 5.0, 5.1]):
            out = g.accept_deal()
        self.assertIn("deal count unchanged", out["note"])
        self.assertNotIn("new_deal", out)


if __name__ == "__main__":
    unittest.main()
