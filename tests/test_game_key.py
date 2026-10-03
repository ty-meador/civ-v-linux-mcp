"""game_key follows the seat and the loaded game.

Live t173 (2026-10-02, Venice/Mongolia hotseat): the session server started on seat 1 (Mongolia) and was moved
to seat 0 with set_seat. `game_key` was cached once per process from the first seat's leader and capital, so
Venice's `recall` answered an empty notebook under `L19-C20-...-Karakorum-t1-s0-seat0` while her 35 notes sat
under `L38-C43-...-Venice-t0-s0-seat0`. The key is now cached per seat and dropped when a game is loaded.
"""
import unittest

from harness.game import Game


class SeatKeyedGame(Game):
    """q() answers the game_key read with the seat's own leader and capital and counts the reads."""

    def __init__(self, seat=1):
        self.seat = seat
        self.reads = []

    def q(self, code, *a, **k):
        seat = int(code.split("Players[", 1)[1].split("]", 1)[0])
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

    def test_a_fixed_key_wins(self):
        g = SeatKeyedGame(seat=1)
        g._game_key = "test-game"
        self.assertEqual(g.game_key(), "test-game")
        self.assertEqual(g.reads, [])


if __name__ == "__main__":
    unittest.main()
