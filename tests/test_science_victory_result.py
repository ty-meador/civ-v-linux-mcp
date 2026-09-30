"""The last spaceship part must say the game is won, not where the unit stands.

Live t502 (solo China, S7 `Wu Zetian_0502 science-victory-eve`): MISSION_SPACESHIP on the third Booster in
Beijing completed the ship and the engine went straight to GAMESTATE_OVER. Its delayed removal of the part
unit never ran, so the read-back found the Booster standing in the capital with its 2 moves, the reply carried
no `consumed`, and `spaceship_status` counted the part as `built_not_delivered: 1` beside `in_ship: 3`.
"""
import unittest
from unittest.mock import patch

from harness.game import Game

PARTS = [
    {"part": "UNIT_SS_COCKPIT", "needed": 1, "in_ship": 1, "built_not_delivered": 0},
    {"part": "UNIT_SS_STASIS_CHAMBER", "needed": 1, "in_ship": 1, "built_not_delivered": 0},
    {"part": "UNIT_SS_ENGINE", "needed": 1, "in_ship": 1, "built_not_delivered": 0},
    {"part": "UNIT_SS_BOOSTER", "needed": 3, "in_ship": 3, "built_not_delivered": 1},
]


def _game(parts, over, unit_after):
    g = Game.__new__(Game)
    g.seat = 0

    def q(body):
        if "H.spaceship_status" in body:
            return {"apollo_done": True, "parts": [dict(p) for p in parts], "rivals": []}
        if "GAMESTATE_OVER" in body:
            return {"over": over}
        if "H.unit_pos" in body:
            return dict(unit_after)
        raise AssertionError("unexpected query: " + body)

    g.q = q
    g._order = lambda body: {"ok": True}
    return g


class SpaceshipStatusTest(unittest.TestCase):
    def test_a_full_ship_reads_complete_and_explains_the_lingering_part(self):
        out = _game(PARTS, True, {"ok": True}).spaceship_status()
        self.assertTrue(out["complete"])
        self.assertTrue(out["game_over"])
        self.assertIn("built_not_delivered", out["note"])
        self.assertEqual(out["parts"][3]["built_not_delivered"], 1, "the engine's own count is not rewritten")

    def test_a_ship_with_a_part_missing_is_not_complete(self):
        parts = [dict(p) for p in PARTS]
        parts[3]["in_ship"] = 2
        out = _game(parts, False, {"ok": True}).spaceship_status()
        self.assertNotIn("complete", out)
        self.assertNotIn("game_over", out)
        self.assertNotIn("note", out)

    def test_a_full_ship_in_a_running_game_carries_no_note(self):
        parts = [dict(p) for p in PARTS]
        parts[3]["built_not_delivered"] = 0
        out = _game(parts, False, {"ok": True}).spaceship_status()
        self.assertTrue(out["complete"])
        self.assertFalse(out["game_over"])
        self.assertNotIn("note", out)


class LastPartMissionTest(unittest.TestCase):
    def _run(self, parts, over):
        g = _game(parts, over, {"ok": True, "x": 24, "y": 23, "moves": 2, "activity": 6, "activity_name": "MISSION"})
        with patch("harness.game.time.sleep"):
            return g.unit_mission(1433615, "MISSION_SPACESHIP")

    def test_the_last_part_reports_the_victory_and_the_unit_as_spent(self):
        r = self._run(PARTS, True)
        self.assertTrue(r["ok"])
        self.assertTrue(r["consumed"])
        self.assertTrue(r["ship_complete"])
        self.assertTrue(r["game_over"])
        self.assertEqual(r["victory"], "science")
        self.assertEqual(r["spaceship"]["UNIT_SS_BOOSTER"], "3/3")
        for k in ("x", "y", "moves", "activity", "activity_name"):
            self.assertNotIn(k, r, f"{k}: the stale read-back of a part the engine never removed")
        self.assertIn("exit_to_main_menu", r["note"])

    def test_an_earlier_part_keeps_the_plain_read_back(self):
        parts = [dict(p) for p in PARTS]
        parts[3]["in_ship"] = 2
        parts[3]["built_not_delivered"] = 0
        g = _game(parts, False, {"ok": False, "err": "no such unit"})
        with patch("harness.game.time.sleep"):
            r = g.unit_mission(1425422, "MISSION_SPACESHIP")
        self.assertTrue(r["consumed"])
        self.assertNotIn("ship_complete", r)
        self.assertNotIn("victory", r)
        self.assertEqual(r["spaceship"]["UNIT_SS_BOOSTER"], "2/3")


if __name__ == "__main__":
    unittest.main()
