"""game_key follows the seat and the loaded game.

Live t173 (2026-10-02, Venice/Mongolia hotseat): the session server started on seat 1 (Mongolia) and was moved
to seat 0 with set_seat. `game_key` was cached once per process from the first seat's leader and capital, so
Venice's `recall` answered an empty notebook under `L19-C20-...-Karakorum-t1-s0-seat0` while her 35 notes sat
under `L38-C43-...-Venice-t0-s0-seat0`. The key is now cached per seat and dropped when a game is loaded.
"""
import os
import tempfile
import unittest
from unittest import mock

from harness.game import Game
from harness.game_parts.notebook import game_keys
from harness.notes import Notebook


class SeatKeyedGame(Game):
    """q() answers the game_key read with the seat's own leader and capital and counts the reads."""

    def __init__(self, seat=1):
        self.seat = seat
        self.reads = []

    def q(self, code, *a, **k):
        seat = int(code.split("H.game_key_facts(", 1)[1].split(")", 1)[0])
        self.reads.append(seat)
        caps = {0: ("38", "43", "Venice", 0), 1: ("19", "20", "Karakorum", 1)}
        leader, civ, cap, founded = caps[seat]
        return {"leader": leader, "civ": civ, "map": "Assets_Maps_continents", "cap": cap, "founded": founded,
                "name": "", "start": 0}


class GameKeyFollowsTheSeat(unittest.TestCase):
    def test_the_key_is_built_from_the_current_seat(self):
        g = SeatKeyedGame(seat=1)
        self.assertEqual(g.game_key(), "L19-C20-Assets_Maps_continents-Karakorum-t1-s0")
        g.seat = 0   # what set_seat does
        self.assertEqual(g.game_key(), "L38-C43-Assets_Maps_continents-Venice-t0-s0")
        self.assertEqual(g.notebook().key, "L38-C43-Assets_Maps_continents-Venice-t0-s0-seat0")

    def test_each_seat_is_read_once(self):
        g = SeatKeyedGame(seat=1)
        g.game_key(); g.game_key()
        g.seat = 0
        g.game_key(); g.game_key()
        g.seat = 1
        g.game_key()
        self.assertEqual(g.reads, [1, 0], "one read per seat, then the cache")

    def test_a_loaded_game_rebuilds_the_key(self):
        g = SeatKeyedGame(seat=1)
        g.game_key()
        g._game_keys = {}   # what wait_ingame does after a load (and the exit to the main menu)
        g.game_key()
        self.assertEqual(g.reads, [1, 1])

    def test_the_legacy_form_is_the_map_with_its_path_prefix(self):
        """Before runtime v285 the map part was `Assets_Maps_<script>` (the inline snippet's pattern lost its
        backslash); the runtime file's key says `<script>`. Both forms come from the same facts."""
        facts = {"leader": "36", "civ": "36", "map": "pangaea", "cap": "Assur", "founded": 0, "name": "", "start": 0}
        keys = game_keys(facts)
        self.assertEqual((keys["key"], keys["legacy"]), ("L36-C36-pangaea-Assur-t0-s0", "L36-C36-Assets_Maps_pangaea-Assur-t0-s0"))
        self.assertIsNone(game_keys({**facts, "map": "Assets_Maps_pangaea"})["legacy"], "already the old form")
        self.assertIsNone(game_keys({**facts, "map": ""})["legacy"])
        g = SeatKeyedGame(seat=0)
        self.assertEqual(g.legacy_game_key(), None, "the fake's map is already the old form")
        g._game_key = "test-game"
        self.assertIsNone(g.legacy_game_key())

    def test_notebook_adopts_the_file_written_under_the_legacy_key(self):
        class NewKeyGame(SeatKeyedGame):
            def q(self, code, *a, **k):
                return {**super().q(code), "map": "continents"}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"CIV5_NOTES_DIR": tmp}):
            Notebook("L38-C43-Assets_Maps_continents-Venice-t0-s0", 0).remember("Venice's plan", turn=10)
            g = NewKeyGame(seat=0)
            nb = g.notebook()
            self.assertEqual(nb.key, "L38-C43-continents-Venice-t0-s0-seat0")
            self.assertEqual([n["text"] for n in nb.recall()["notes"]], ["Venice's plan"])
            self.assertEqual(sorted(p for p in os.listdir(tmp)), ["L38-C43-continents-Venice-t0-s0-seat0.json"])

    def test_a_random_map_game_names_no_script(self):
        """GitLab #119: a game set up with map type Random hides the script from its players; the key said it."""
        facts = {"leader": "36", "civ": "36", "map": "random", "cap": "Sukhothai", "founded": 0, "name": "", "start": 0}
        keys = game_keys(facts)
        self.assertEqual(keys["key"], "L36-C36-random-Sukhothai-t0-s0")
        self.assertIsNone(keys["legacy"])
        self.assertEqual(keys["pattern"], "L36-C36-*-Sukhothai-t0-s0")
        self.assertNotIn("pattern", game_keys({**facts, "map": "pangaea"}))

    def test_notebook_of_a_random_map_game_is_adopted_from_its_script_key(self):
        class RandomGame(SeatKeyedGame):
            def q(self, code, *a, **k):
                return {**super().q(code), "map": "random"}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"CIV5_NOTES_DIR": tmp}):
            Notebook("L38-C43-Fractal-Venice-t0-s0", 0).remember("the plan", turn=10)
            Notebook("L38-C43-Fractal-Venice-t0-s0", 1).remember("another seat", turn=10)
            Notebook("L19-C20-Fractal-Karakorum-t1-s0", 0).remember("another game", turn=10)
            g = RandomGame(seat=0)
            nb = g.notebook()
            self.assertEqual(nb.key, "L38-C43-random-Venice-t0-s0-seat0")
            self.assertEqual([n["text"] for n in nb.recall()["notes"]], ["the plan"])
            self.assertEqual(sorted(os.listdir(tmp)), ["L19-C20-Fractal-Karakorum-t1-s0-seat0.json",
                                                       "L38-C43-Fractal-Venice-t0-s0-seat1.json",
                                                       "L38-C43-random-Venice-t0-s0-seat0.json"])
            nb.remember("new", turn=11)
            self.assertFalse(Notebook("L38-C43-random-Venice-t0-s0", 0).adopt_matching("L38-C43-*-Venice-t0-s0-seat0"),
                             "a key with a file adopts nothing")

    def test_the_key_before_the_capital_is_read_again_until_it_is_founded(self):
        """GitLab #159 (Codex seat 0, t0): the plan remembered before the Settler founded Palenque sat under the
        key with no capital; the key gained `Palenque-t0` a call later and the recovered server read an empty
        notebook. The key is not cached while the seat has no capital, so the writer moves at the founding."""
        class UnsettledGame(SeatKeyedGame):
            def __init__(self):
                super().__init__(seat=0)
                self.cap = ""

            def q(self, code, *a, **k):
                base = super().q(code)
                return {**base, "leader": "31", "civ": "33", "map": "continents", "cap": self.cap, "founded": 0 if self.cap else -1}
        facts = {"leader": "31", "civ": "33", "map": "continents", "cap": "", "founded": -1, "name": "", "start": 0}
        keys = game_keys(facts)
        self.assertEqual((keys["key"], keys["settled"]), ("L31-C33-continents-t-1-s0", False))
        self.assertNotIn("before_capital", keys)
        keys = game_keys({**facts, "cap": "Palenque", "founded": 0})
        self.assertEqual((keys["key"], keys["settled"], keys["before_capital"]),
                         ("L31-C33-continents-Palenque-t0-s0", True, "L31-C33-continents-t-1-s0"))
        g = UnsettledGame()
        self.assertEqual(g.game_key(), "L31-C33-continents-t-1-s0")
        g.game_key()
        self.assertEqual(g.reads, [0, 0], "read again while there is no capital")
        g.cap = "Palenque"
        self.assertEqual(g.game_key(), "L31-C33-continents-Palenque-t0-s0")
        g.game_key()
        self.assertEqual(g.reads, [0, 0, 0], "cached once the capital names the key")

    def test_notebook_adopts_the_file_written_before_the_capital(self):
        class SettledGame(SeatKeyedGame):
            def q(self, code, *a, **k):
                return {**super().q(code), "map": "continents", "cap": "Palenque", "founded": 0, "leader": "31", "civ": "33"}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"CIV5_NOTES_DIR": tmp}):
            Notebook("L31-C33-continents-t-1-s0", 0).remember("Seat 0 Maya. Found capital in place", turn=0)
            Notebook("L31-C33-continents-t-1-s0", 1).remember("the other seat's plan", turn=0)
            g = SettledGame(seat=0)
            nb = g.notebook()
            self.assertEqual(nb.key, "L31-C33-continents-Palenque-t0-s0-seat0")
            self.assertEqual([n["text"] for n in nb.recall()["notes"]], ["Seat 0 Maya. Found capital in place"])
            self.assertEqual(sorted(os.listdir(tmp)), ["L31-C33-continents-Palenque-t0-s0-seat0.json",
                                                       "L31-C33-continents-t-1-s0-seat1.json"])

    def test_a_fixed_key_wins(self):
        g = SeatKeyedGame(seat=1)
        g._game_key = "test-game"
        self.assertEqual(g.game_key(), "test-game")
        self.assertEqual(g.reads, [])


if __name__ == "__main__":
    unittest.main()
