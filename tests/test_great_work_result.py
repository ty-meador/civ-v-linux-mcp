"""Creating a great work must say what was created and where it went.

A Great Person is a once-in-many-turns resource, and MISSION_CREATE_GREAT_WORK answered with a bare
`{"ok": true, "consumed": true}`. Live t215: a Great Writer turned into "Martin Fierro" in Te-Moak's
Amphitheater and the reply said none of it -- the seat had to call `culture_works` and diff the
slots to learn where its Great Person went. The game itself shows a popup naming the work.
"""
import unittest
from unittest.mock import patch

from harness.game import Game


WORK = {"work_id": 15, "city": "Te-Moak", "city_id": 16385, "building": "BUILDING_AMPHITHEATER",
        "slot_type": "GREAT_WORK_SLOT_LITERATURE", "slot": 0, "name": "Martin Fierro",
        "tooltip": "Martin Fierro\nJose Hernandez (Great Writer)\n+2 Culture, +2 Tourism"}
OLD = {"8": {"work_id": 8, "city": "Moson Kahni", "name": "Beads"}}


class GreatWorkResultTest(unittest.TestCase):
    def _run(self, index_reads):
        """index_reads: successive H.great_work_index answers (before, then each poll)."""
        g = Game.__new__(Game)
        g.seat = 0
        reads = list(index_reads)

        def q(body):
            if "great_work_index" in body:
                return reads.pop(0) if len(reads) > 1 else reads[0]
            raise AssertionError("unexpected query: " + body)

        g.q = q
        g._order = lambda body: {"ok": True, "consumed": True}
        with patch("harness.game.time.sleep"):
            return g.unit_mission(688135, "MISSION_CREATE_GREAT_WORK")

    def test_the_new_work_and_its_slot_come_back_with_the_mission(self):
        out = self._run([OLD, {**OLD, "15": WORK}])
        self.assertTrue(out["ok"])
        self.assertEqual(out["great_work"]["name"], "Martin Fierro")
        self.assertEqual(out["great_work"]["city"], "Te-Moak")
        self.assertEqual(out["great_work"]["building"], "BUILDING_AMPHITHEATER")
        self.assertIn("Great Writer", out["great_work"]["tooltip"])

    def test_works_already_held_are_not_mistaken_for_the_new_one(self):
        out = self._run([{**OLD, "15": WORK}, {**OLD, "15": WORK, "22": {**WORK, "work_id": 22, "name": "Ulysses"}}])
        self.assertEqual(out["great_work"]["name"], "Ulysses")

    def test_a_slot_that_never_fills_says_so_instead_of_claiming_success(self):
        out = self._run([OLD, OLD])
        self.assertNotIn("great_work", out)
        self.assertIn("no new great work", out["note"])
        self.assertIn("culture_works", out["note"])

    def test_the_first_work_of_the_game_is_found_from_an_empty_index(self):
        out = self._run([{}, {"15": WORK}])
        self.assertEqual(out["great_work"]["work_id"], 15)


if __name__ == "__main__":
    unittest.main()
