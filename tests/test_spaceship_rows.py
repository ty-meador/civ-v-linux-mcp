"""A spaceship part is a decision row (GitLab #93) and the purchase reply flags the capital tile's civilian (GitLab #80)."""
import unittest

from harness.briefing import decisions
from harness.game import Game

CITIES = [{"id": 8192, "name": "Assur", "x": 16, "y": 27, "capital": True}, {"id": 16385, "name": "Nineveh", "x": 20, "y": 28, "capital": False}]


class SpaceshipDecisionTests(unittest.TestCase):
    def test_a_part_in_the_capital_gets_the_mission_and_one_elsewhere_the_walk(self):
        ts = {"todo": {"units": [{"id": 1441812, "type": "SS_BOOSTER", "x": 16, "y": 27, "moves": 2},
                                 {"id": 1441900, "type": "SS_ENGINE", "x": 20, "y": 28, "moves": 2},
                                 {"id": 7, "type": "WORKER", "x": 1, "y": 1, "moves": 2}], "cities": []},
              "blocking_name": "ENDTURN_BLOCKING_UNITS", "blocking_hint": "x", "pending_popups": []}
        rows = decisions(ts, CITIES)
        self.assertEqual([r["kind"] for r in rows], ["spaceship_part", "spaceship_part", "unit_orders"])
        booster, engine = rows[0], rows[1]
        self.assertTrue(booster["at_capital"])
        self.assertEqual(booster["actions"], [{"tool": "order", "args": {"to": "unit", "action": "mission", "id": 1441812, "args": {"mission": "MISSION_SPACESHIP"}}}])
        self.assertFalse(engine["at_capital"])
        self.assertEqual(engine["actions"][0]["args"]["args"], {"x": 16, "y": 27})
        self.assertEqual(engine["actions"][1]["args"]["args"], {"mission": "MISSION_SPACESHIP"})
        self.assertIn("Assur", engine["note"])

    def test_a_part_with_no_moves_says_next_turn(self):
        ts = {"todo": {"units": [{"id": 1, "type": "SS_COCKPIT", "x": 16, "y": 27, "moves": 0}], "cities": []},
              "blocking_name": "x", "blocking_hint": "x", "pending_popups": []}
        row = decisions(ts, CITIES)[0]
        self.assertIn("next turn", row["note"])


class CapitalTileNoteTests(unittest.TestCase):
    def _game(self, units_on_tile):
        g = Game.__new__(Game)
        g.seat = 0
        g._pid = lambda pid=None: 0
        g.h = Game.h.__get__(g)
        g.cities = lambda pid=None: CITIES
        g.q = lambda call, timeout=None: {"ok": True, "visible": True, "units": units_on_tile} if call.fn == "plot_units" else {"ok": True}
        return g

    def test_the_worker_on_the_capital_tile_is_named_with_its_move(self):
        g = self._game([{"id": 65540, "owner": 0, "type": "WORKER"}, {"id": 1441812, "owner": 0, "type": "SS_BOOSTER"}])
        out = {"ok": True, "unit": {"id": 1441812, "type": "SS_BOOSTER"}}
        g._capital_tile_note(out, None)
        self.assertEqual(out["capital_tile"]["held_by"]["id"], 65540)
        self.assertIn("move it off first", out["capital_tile"]["note"])
        self.assertEqual(out["capital_tile"]["actions"][0]["args"]["id"], 65540)

    def test_a_free_tile_adds_nothing(self):
        g = self._game([{"id": 1441812, "owner": 0, "type": "SS_BOOSTER"}, {"id": 5, "owner": 0, "type": "MUSKETMAN"}])
        out = {"ok": True, "unit": {"id": 1441812}}
        g._capital_tile_note(out, None)
        self.assertNotIn("capital_tile", out)


if __name__ == "__main__":
    unittest.main()
