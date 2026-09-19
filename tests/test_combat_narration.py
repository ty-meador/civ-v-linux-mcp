"""turn_digest combat provenance: `Game._narrate_combat` (pure Python; the Lua side fills attacker/defender)."""
import unittest

from harness.game import Game


def narrate(events):
    return Game._narrate_combat(None, events)


class CombatNarrationTests(unittest.TestCase):
    def test_barbarian_attack_names_both_sides(self):
        ev = {"kind": "combat", "data": {
            "att_player": 63, "att_unit": 122881, "att_dmg": 12, "def_player": 0, "def_unit": 8193, "def_dmg": 38,
            "attacker": {"owner": "Barbarians", "unit": "WARRIOR", "x": 13, "y": 8, "hp": 88},
            "defender": {"owner": "you", "unit": "SCOUT", "x": 12, "y": 8, "hp": 62}}}
        s = narrate([ev])[0]["data"]["summary"]
        self.assertIn("Barbarians WARRIOR (13,8) attacked your SCOUT (12,8)", s)
        self.assertIn("defender -38 hp, 62 left", s)

    def test_unseen_attacker_is_not_described(self):
        ev = {"kind": "combat", "data": {"att_player": 3, "att_dmg": 0, "def_player": 0, "def_unit": 5, "def_dmg": 20,
                                         "attacker": {"owner": "Unknown", "ranged": True},
                                         "defender": {"owner": "you", "unit": "WORKER", "x": 1, "y": 2, "hp": 80}}}
        s = narrate([ev])[0]["data"]["summary"]
        self.assertIn("Unknown unit (not visible) shot your WORKER", s)

    def test_hp_fallback_dropped_when_combat_explains_it(self):
        combat = {"kind": "combat", "data": {"def_unit": 5, "def_dmg": 20, "att_dmg": 0,
                                             "attacker": {"owner": "Barbarians"}, "defender": {"owner": "you", "killed": True}}}
        hurt = {"kind": "unit_lost", "data": {"unit_id": 5, "unit": "WORKER", "x": 1, "y": 2, "hp_before": 100}}
        other = {"kind": "unit_hurt", "data": {"unit_id": 9, "unit": "SCOUT", "x": 4, "y": 4, "hp_before": 100, "hp": 70}}
        out = narrate([combat, hurt, other])
        self.assertEqual([e["kind"] for e in out], ["combat", "unit_hurt"])
        self.assertIn("lost 30 hp", out[1]["data"]["summary"])
        self.assertIn("killed", out[0]["data"]["summary"])


if __name__ == "__main__":
    unittest.main()
