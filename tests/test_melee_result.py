"""A melee reply's `attack` block reads the blow, not the preview (GitLab #156).

Hotseat seat 1 (Grok, 2026-10-29), Warrior 16385 onto a barbarian Brute at (19, 29), turns 10 and 11: the
alert said "Your Warrior (30 damage) attacked an enemy Brute (26 damage)!", my_hp 100 -> 70, def_hp 74 --
and `defender.hp` stayed 100, the pre-read's row copied as it was. The preview (31 dealt / 28 taken) missed
the blow by a few points both turns: the stock panel previews without the engine's random roll.
"""
import unittest

from harness.game import Game
from harness.game_parts import combat_result as CR
from tests.test_air_strike_result import FakeGame

PRE = {"attack": True, "def_player": 63, "def_unit": 9, "def_hp": 100, "my_hp": 100, "seq": 0,
       "defender": {"unit": "BRUTE", "owner": "Barbarians", "x": 19, "y": 29, "hp": 100, "max_hp": 100}}


class MeleeResultTest(unittest.TestCase):
    def test_defender_row_reads_the_health_after_the_blow(self):
        a = CR.attack_block(PRE, {"my_hp": 70, "def_hp": 74})
        self.assertEqual(a["defender"]["hp"], 74, "the row's hp is the health after the blow, as def_hp is")
        self.assertEqual(a["defender_hp_before"], 100)
        self.assertEqual(a["def_hp"], 74)
        self.assertEqual((a["damage_dealt"], a["damage_taken"]), (26, 30), "the alert's own two numbers")
        self.assertIn("roll", a["roll_note"])
        self.assertEqual(PRE["defender"]["hp"], 100, "the pre-read is not written to")

    def test_a_kill_reads_as_zero_hp_and_the_whole_health_dealt(self):
        a = CR.attack_block(PRE, {"my_hp": 89, "defender_killed": True})
        self.assertEqual(a["defender"]["hp"], 0)
        self.assertTrue(a["defender"]["killed"])
        self.assertEqual(a["damage_dealt"], 100)
        self.assertEqual(a["damage_taken"], 11)

    def test_a_capture_is_neither_a_kill_nor_damage(self):
        a = CR.attack_block(PRE, {"my_hp": 100, "defender_killed": True})
        CR.mark_captured(a, 4242)
        self.assertNotIn("defender_killed", a)
        self.assertNotIn("damage_dealt", a)
        self.assertEqual(a["captured_unit_id"], 4242)
        self.assertTrue(a["defender"]["captured"])
        self.assertNotIn("killed", a["defender"])
        self.assertNotIn("roll_note", a, "no blow, no roll")

    def test_an_unchanged_board_carries_no_numbers_and_no_note(self):
        a = CR.attack_block(PRE, {"my_hp": 100, "def_hp": 100})
        self.assertTrue(CR.nothing_happened(a))
        self.assertEqual((a["damage_dealt"], a["damage_taken"]), (0, 0))
        self.assertNotIn("roll_note", a)
        self.assertFalse(CR.no_combat_block(a)["happened"])

    def test_the_order_path_hands_the_block_back(self):
        class Melee(FakeGame):
            def q(self, lua, *a, **kw):
                if "H.attack_after" in lua:
                    self.calls.append(lua)
                    return {"my_hp": 70, "def_hp": 74}
                return super().q(lua, *a, **kw)

        g = Melee(defender=True)
        r = Game.unit_mission(g, unit_id=16385, mission="MISSION_MOVE_TO", x=42, y=22)
        self.assertTrue(r["ok"])
        self.assertEqual(r["attack"]["defender"]["hp"], 74)
        self.assertEqual(r["attack"]["damage_dealt"], 26)


if __name__ == "__main__":
    unittest.main()
