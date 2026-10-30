"""A melee attack the engine drops is reported as a refused attack, not as an occupied plot.

Live t200 (Mongolia): an Infantry in Karakorum (28,24), two moves, at war, was ordered onto the Russian Infantry
across the river at (29,24). tactical_view called it `attack`; the engine did nothing; move_unit answered
"unit did not move: (29,24) is occupied by another civ's unit (INFANTRY); pick an adjacent free plot" -- the
hint for a *move*, and wrong advice for an attack, which is exactly a move onto an occupied plot. The pre-read
(H.attack_before) already knows the order was an attack, so the refusal now says so and lists the engine's
attack gates this harness can read. The engine's own probe is out of reach: Unit:CanMoveInto is nil in this
build and Unit:CanMoveOrAttackInto reads false for every neighbour (probed live, England t139).
"""
import itertools
import unittest
from unittest import mock

from tests.test_after_reads import _game

DEFENDER = {"owner": "Russia", "unit": "INFANTRY", "x": 29, "y": 24, "hp": 100, "max_hp": 100}


def _refused(facts, attack=True, foreign_on_plot=True):
    g = _game([("H.attack_before", {"attack": True, "def_player": 3, "def_unit": 55, "def_hp": 100, "my_hp": 100,
                                    "defender": DEFENDER} if attack else {"attack": False}),
               ("H.move_unit", {"ok": True, "x": 28, "y": 24, "moves": 2}),
               ("H.unit_pos", {"ok": True, "x": 28, "y": 24, "moves": 2, "activity": 0}),
               ("H.drop_pending_move", True),
               ("H.melee_refusal_facts", facts)])
    g.units = lambda pid=None: [{"id": 9, "type": "INFANTRY", "x": 28, "y": 24, "strength": 70, "domain": "LAND"}]
    g.plots_around = lambda x, y, r: {"plots": [{"x": 29, "y": 24, "units":
                                                 [{"owner": 3, "id": 55, "type": "INFANTRY", "hp": 100}] if foreign_on_plot else []}]}
    return g


class RefusedAttackTests(unittest.TestCase):
    def setUp(self):
        self.sleep = mock.patch("harness.game_parts.units.time.sleep")
        self.sleep.start()
        self.clock = mock.patch("harness.game_parts.units.time.monotonic", side_effect=itertools.count(0, 0.6))
        self.clock.start()

    def tearDown(self):
        self.sleep.stop()
        self.clock.stop()

    def test_the_t200_shape_names_the_attack_and_its_setting(self):
        g = _refused({"moves": 120, "from_city": True, "out_of_attacks": False, "cannot_attack": False,
                      "embarked": False, "amphibious": False, "adjacent": True, "river": True})
        r = g.move_unit(9, 29, 24)
        self.assertFalse(r["ok"])
        self.assertIn("the engine refused the melee attack on Russia INFANTRY at (29,24) from inside a city across a river", r["err"])
        self.assertIn("not identified", r["err"])
        self.assertIn("state(what='unit', id, view='tactical')", r["err"])
        self.assertNotIn("occupied", r["err"])
        self.assertNotIn("free plot", r["err"])
        self.assertEqual(r["refused_attack"]["defender"], DEFENDER)
        self.assertTrue(r["refused_attack"]["river"] and r["refused_attack"]["from_city"])
        self.assertNotIn("adjacent", r["refused_attack"])

    def test_a_fogged_destination_says_the_fog_may_hide_the_blocker(self):
        """Live Assyria t132-t143: four "no path" refusals in a row, each a fogged plot holding a unit the banner
        does not show; the refusal says so without reading what stands there."""
        g = _refused({"moves": 120, "from_city": False, "out_of_attacks": False, "cannot_attack": False,
                      "embarked": False, "amphibious": False, "adjacent": True, "river": False},
                     attack=False, foreign_on_plot=False)
        orig = g.q
        g.q = lambda body: False if "H.plot_visible(" in body else orig(body)
        r = g.move_unit(9, 29, 24)
        self.assertFalse(r["ok"])
        self.assertIn("the destination is fogged, so a unit you cannot see may hold it", r["err"])
        self.assertTrue(r["fogged_destination"])
        g2 = _refused({"moves": 120, "from_city": False, "out_of_attacks": False, "cannot_attack": False,
                       "embarked": False, "amphibious": False, "adjacent": True, "river": False},
                      attack=False, foreign_on_plot=False)
        r2 = g2.move_unit(9, 29, 24)
        self.assertNotIn("fogged", r2["err"])
        self.assertNotIn("fogged_destination", r2)

    def test_my_own_unit_on_a_visible_destination_is_named(self):
        """GitLab #113 (Maya t106): the plot held my own Caravan and the refusal blamed the fog."""
        g = _refused({"moves": 120, "from_city": False, "out_of_attacks": False, "cannot_attack": False,
                      "embarked": False, "amphibious": False, "adjacent": True, "river": False},
                     attack=False, foreign_on_plot=False)
        orig = g.q
        g.q = lambda body: ({"ok": True, "visible": True, "units": [{"id": 44, "owner": 0, "type": "CARAVAN", "hp": 100}]}
                            if "H.plot_units(" in body else orig(body))
        r = g.move_unit(9, 29, 24)
        self.assertFalse(r["ok"])
        self.assertIn("already holds your CARAVAN (44)", r["err"])
        self.assertEqual(r["blocking_unit"]["id"], 44)
        self.assertNotIn("fogged", r["err"])

    def test_a_closed_gate_is_named(self):
        g = _refused({"moves": 60, "from_city": False, "out_of_attacks": True, "adjacent": True, "river": False})
        r = g.move_unit(9, 29, 24)
        self.assertEqual(r["err"], "the engine refused the melee attack on Russia INFANTRY at (29,24): the unit has already attacked this turn")

    def test_the_domain_sentence_wins(self):
        g = _refused({"moves": 60, "from_city": False, "domain": "a land unit cannot attack a unit at sea; a ship or a ranged unit can",
                      "adjacent": True, "river": False})
        r = g.move_unit(9, 29, 24)
        self.assertTrue(r["err"].endswith(": a land unit cannot attack a unit at sea; a ship or a ranged unit can"), r["err"])

    def test_a_far_target_says_the_walk_failed(self):
        g = _refused({"moves": 60, "from_city": False, "adjacent": False})
        r = g.move_unit(9, 29, 24)
        self.assertIn("is not adjacent: the unit walks toward it first", r["err"])

    def test_a_plain_move_keeps_the_occupancy_hint(self):
        g = _refused({}, attack=False)
        r = g.move_unit(9, 29, 24)
        self.assertFalse(r["ok"])
        self.assertIn("occupied by another civ's unit (INFANTRY); pick an adjacent free plot", r["err"])
        self.assertNotIn("refused_attack", r)

    def test_a_failed_fact_read_still_says_refused_attack(self):
        g = _refused({"moves": 60, "adjacent": True})
        from harness.client import TunerdError

        def boom(body):
            if "H.melee_refusal_facts" in body:
                raise TunerdError("gone")
            return orig(body)
        orig, g.q = g.q, boom
        r = g.move_unit(9, 29, 24)
        self.assertTrue(r["err"].startswith("the engine refused the melee attack on Russia INFANTRY at (29,24);"), r["err"])
        self.assertEqual(r["refused_attack"], {"defender": DEFENDER})


if __name__ == "__main__":
    unittest.main()
