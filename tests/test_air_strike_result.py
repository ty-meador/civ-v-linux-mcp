"""An air strike must report the strike, like every other attack does.

Air units attack by being sent onto the target plot: the mission is MISSION_MOVE_TO, not
MISSION_RANGE_ATTACK. unit_mission only attached combat results to RANGE_ATTACK / NUKE /
PARADROP, so a bomber that killed something answered `{"ok":true,"x":50,"y":24,"moves":0}`
-- indistinguishable from a bomber that flew nowhere. Live t182 (Shoshone vs the Inca): a
Bomber killed an Inca Composite Bowman outright and took 11 damage, and the tool said
nothing about either.
"""
import unittest

from harness.game import Game


class FakeGame(Game):
    """A Game with the tuner replaced by a scripted Lua responder."""

    def __init__(self, defender=None, air=None):
        self.seat = 0
        self.calls: list[str] = []
        self._defender = defender
        self._air = air
        self.pushed: list[tuple] = []

    # -- the three seams unit_mission / move_unit use ----------------------
    def q(self, lua, *a, **kw):
        self.calls.append(lua)
        if "H.attack_before" in lua:
            if self._defender is None:
                return {"attack": False}
            return {"attack": True, "def_player": 2, "def_unit": 777, "def_hp": 100, "my_hp": 100,
                    "air": self._air,
                    "defender": {"unit": "COMPOSITE_BOWMAN", "owner": "The Inca", "x": 42, "y": 22,
                                 "hp": 100, "max_hp": 100}}
        if "H.attack_after" in lua:
            return {"defender_killed": True, "my_hp": 89}
        if "H.captured_at" in lua:
            return None
        if "H.unit_pos" in lua:
            return {"ok": True, "x": 50, "y": 24, "moves": 0}
        return {"ok": True}

    def _order(self, lua, *a, **kw):
        self.calls.append(lua)
        return {"ok": True, "x": 50, "y": 24, "moves": 0}


class AirStrikeResultTest(unittest.TestCase):
    def _mission(self, g, **kw):
        return Game.unit_mission(g, **kw)

    def test_air_strike_reports_both_sides(self):
        g = FakeGame(defender=True)
        r = self._mission(g, unit_id=466967, mission="MISSION_MOVE_TO", x=42, y=22)

        self.assertTrue(r["ok"])
        atk = r["attack"]
        self.assertEqual(atk["defender"]["unit"], "COMPOSITE_BOWMAN")
        self.assertEqual(atk["defender_hp_before"], 100)
        self.assertTrue(atk["defender_killed"], "a kill must be reported, not inferred from a later digest")
        self.assertEqual(atk["my_hp_before"], 100)
        self.assertEqual(atk["my_hp"], 89, "the strike's own damage taken is part of what the pilot sees")

    def test_ordinary_move_pays_nothing_and_reports_no_attack(self):
        g = FakeGame(defender=None)
        r = self._mission(g, unit_id=466967, mission="MISSION_MOVE_TO", x=42, y=22)

        self.assertTrue(r["ok"])
        self.assertNotIn("attack", r)
        self.assertFalse([c for c in g.calls if "H.attack_after" in c],
                         "no enemy on the plot means no post-attack reads")

    def test_an_out_of_range_air_strike_is_refused_not_accepted(self):
        """The engine answers an illegal strike by doing nothing, so the old code returned ok
        with both sides' hp unchanged -- indistinguishable from a strike that missed. Live t184:
        a Fighter at (49,19) sent at Cusco (42,23), nine plots away against a range of eight."""
        g = FakeGame(defender=True, air={"air": True, "can_strike": False, "range": 8})
        r = self._mission(g, unit_id=458773, mission="MISSION_MOVE_TO", x=42, y=23)

        self.assertFalse(r["ok"])
        self.assertIn("cannot strike that plot", r["err"])
        self.assertIn("range is 8", r["err"])
        self.assertEqual(r["range"], 8)
        self.assertFalse([c for c in g.calls if "H.move_unit" in c or "H.unit_mission" in c],
                         "an order the engine will ignore must not be sent at all")

    def test_an_in_range_air_strike_still_goes_through(self):
        g = FakeGame(defender=True, air={"air": True, "can_strike": True, "range": 8})
        r = self._mission(g, unit_id=466967, mission="MISSION_MOVE_TO", x=42, y=22)

        self.assertTrue(r["ok"])
        self.assertTrue(r["attack"]["defender_killed"])

    def test_a_ground_unit_is_never_refused_for_range(self):
        """A melee move at a distant enemy is a legal multi-turn order; only air units strike
        or do nothing."""
        g = FakeGame(defender=True, air=None)
        r = self._mission(g, unit_id=507929, mission="MISSION_MOVE_TO", x=42, y=22)

        self.assertTrue(r["ok"])

    def test_a_non_move_mission_is_untouched(self):
        g = FakeGame(defender=True)
        r = self._mission(g, unit_id=466967, mission="MISSION_FORTIFY")

        self.assertTrue(r["ok"])
        self.assertNotIn("attack", r)
        self.assertFalse([c for c in g.calls if "H.attack_before" in c],
                         "MISSION_FORTIFY is not shaped like an attack")


if __name__ == "__main__":
    unittest.main()
