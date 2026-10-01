"""overview.trade_note (harness/game_parts/reads.py): trade_routes_used counts trade units alive (idle or routed),
trade_units_queued the ones in any city's queue, and the engine trains none beyond the slots; the note says what
to route and what to build."""
import unittest

from harness.game import Game


def summary_with(available, used, idle, queued=None, trainable=None, refused=None):
    g = Game.__new__(Game)
    g.seat = 0
    row = {"trade_routes_available": available, "trade_routes_used": used,
           "idle_trade_units": [{"unit_id": 1 + i} for i in range(idle)]}
    if queued is not None:
        row["trade_units_queued"] = queued
    if trainable is not None:
        row["trade_units_trainable"] = trainable
        row["trade_units_refused"] = refused or {}
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

    # Runtime v253: the engine's second gate. Live t152 Venice read "4 of 8" with nothing queued and CanTrain false
    # for both kinds in every city ("no available land/sea trade routes"): the old note said build or buy.
    def test_both_kinds_refused_is_a_blocked_note_not_a_build_order(self):
        land = "You cannot construct this trade unit because there are no available land trade routes."
        sea = "You cannot construct this trade unit because there are no available sea trade routes."
        r = summary_with(8, 4, 0, trainable={"caravan": False, "cargo_ship": False},
                         refused={"caravan": land, "cargo_ship": sea})
        self.assertEqual(r["free_trade_route_slots"], 4)
        self.assertNotIn("build or buy a", r["trade_note"])
        self.assertIn("nothing to build or buy", r["trade_note"])
        self.assertIn("Caravan: " + land, r["trade_units_blocked"])
        self.assertIn("Cargo Ship: " + sea, r["trade_units_blocked"])

    def test_one_kind_refused_names_the_other(self):
        sea = "You cannot construct this trade unit because there are no available sea trade routes."
        r = summary_with(8, 4, 0, trainable={"caravan": True, "cargo_ship": False}, refused={"cargo_ship": sea})
        self.assertIn("build or buy a Caravan for each", r["trade_note"])
        self.assertIn("(not a Cargo Ship: " + sea + ")", r["trade_note"])
        self.assertNotIn("trade_units_blocked", r)

    def test_both_trainable_or_an_old_runtime_keeps_the_plain_note(self):
        r = summary_with(8, 4, 0, trainable={"caravan": True, "cargo_ship": True})
        self.assertIn("build or buy a Caravan / Cargo Ship for each", r["trade_note"])
        r = summary_with(8, 4, 0)
        self.assertIn("build or buy a Caravan / Cargo Ship for each", r["trade_note"])

    def test_briefing_opportunity_carries_the_block(self):
        from harness import briefing
        r = summary_with(8, 4, 0, trainable={"caravan": False, "cargo_ship": False},
                         refused={"caravan": "no land routes", "cargo_ship": "no sea routes"})
        rows = [o for o in briefing.opportunities(r, {}) if o["kind"] == "free_trade_route_slots"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["count"], 4)
        self.assertIn("Caravan: no land routes", rows[0]["blocked"])
        r = summary_with(8, 4, 0)
        rows = [o for o in briefing.opportunities(r, {}) if o["kind"] == "free_trade_route_slots"]
        self.assertNotIn("blocked", rows[0])
