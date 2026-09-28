"""overview.trade_note (harness/game_parts/reads.py): trade_routes_used counts trade units alive (idle or routed),
trade_units_queued the ones in any city's queue, and the engine trains none beyond the slots; the note says what
to route and what to build."""
import unittest

from harness.game import Game


def summary_with(available, used, idle, queued=None):
    g = Game.__new__(Game)
    g.seat = 0
    row = {"trade_routes_available": available, "trade_routes_used": used,
           "idle_trade_units": [{"unit_id": 1 + i} for i in range(idle)]}
    if queued is not None:
        row["trade_units_queued"] = queued
    g.q = lambda code, **kw: row
    return g.summary()


class TradeNoteTests(unittest.TestCase):
    def test_no_idle_unit_means_build(self):
        r = summary_with(5, 4, 0)
        self.assertEqual(r["free_trade_route_slots"], 1)
        self.assertIn("build or buy", r["trade_note"])

    def test_idle_units_hold_slots_so_they_are_routed_and_the_free_ones_still_built(self):
        # used counts the idle caravans already: two idle of four used leaves two slots with no unit at all
        r = summary_with(4, 2, 2)
        self.assertEqual(r["free_trade_route_slots"], 2)
        self.assertIn("2 idle caravan(s)", r["trade_note"])
        self.assertIn("establish_trade_route", r["trade_note"])
        self.assertIn("2 slot(s) have no trade unit yet", r["trade_note"])

    def test_idle_units_with_no_free_slot_are_still_a_note(self):
        r = summary_with(4, 4, 1)
        self.assertNotIn("free_trade_route_slots", r)
        self.assertIn("1 idle caravan(s)", r["trade_note"])
        self.assertNotIn("build", r["trade_note"])

    def test_queued_trade_units_take_slots_before_they_exist(self):
        # live t139: Venice read "4 of 8" and the engine refused a fifth caravan; the queue is the hidden half
        r = summary_with(8, 4, 0, queued=4)
        self.assertNotIn("free_trade_route_slots", r)
        self.assertIn("4 trade unit(s) in production", r["trade_note"])
        r = summary_with(8, 4, 0, queued=1)
        self.assertEqual(r["free_trade_route_slots"], 3)
        self.assertIn("(1 already in production)", r["trade_note"])

    def test_no_free_slot_means_no_note(self):
        r = summary_with(4, 4, 0)
        self.assertNotIn("free_trade_route_slots", r)
        self.assertNotIn("trade_note", r)
