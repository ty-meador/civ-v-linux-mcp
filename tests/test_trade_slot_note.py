"""overview.trade_note (harness/game_parts/reads.py): trade_routes_used counts running routes, so a free slot may
already have an idle caravan waiting for a route; the note says whether to route or to build."""
import unittest

from harness.game import Game


def summary_with(available, used, idle):
    g = Game.__new__(Game)
    g.seat = 0
    g.q = lambda code, **kw: {"trade_routes_available": available, "trade_routes_used": used,
                              "idle_trade_units": [{"unit_id": 1 + i} for i in range(idle)]}
    return g.summary()


class TradeNoteTests(unittest.TestCase):
    def test_no_idle_unit_means_build(self):
        r = summary_with(5, 4, 0)
        self.assertEqual(r["free_trade_route_slots"], 1)
        self.assertIn("build or buy", r["trade_note"])

    def test_idle_units_covering_every_slot_mean_route_not_build(self):
        r = summary_with(4, 2, 2)
        self.assertEqual(r["free_trade_route_slots"], 2)
        self.assertIn("do not build another", r["trade_note"])
        self.assertIn("establish_trade_route", r["trade_note"])

    def test_some_idle_units_mean_route_first_then_build_the_rest(self):
        r = summary_with(6, 2, 1)
        self.assertIn("route them first", r["trade_note"])
        self.assertIn("for the other 3", r["trade_note"])

    def test_no_free_slot_means_no_note(self):
        r = summary_with(4, 4, 0)
        self.assertNotIn("free_trade_route_slots", r)
        self.assertNotIn("trade_note", r)
