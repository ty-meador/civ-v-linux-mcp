"""The 'auto' seat must survive a server that starts before the game does.

Live 2026-09-21: the MCP server came up while Civ V was still loading, so `detect_seat` raised,
the seat silently stayed at its hotseat default of 1, and every tool in a solo game where we are
player 0 answered `{"ok": false, "err": "this seat is not active", "active_player": 0}` for the
rest of the session -- unrecoverable in practice, because restarting the MCP server is exactly
what loses the tools. Detection is therefore retried until it succeeds.
"""
import unittest

from harness.client import TunerdError


class _FakeGame:
    """Stands in for Game: raises from mode() until the game is 'up', then reports a seat."""

    def __init__(self, mode="single", up_after=0, seat_when_up=0):
        self.seat = None
        self._mode = None
        self._real_mode = mode
        self._up_after = up_after
        self._seat_when_up = seat_when_up
        self.probes = 0
        self.detects = 0

    def mode(self):
        self.probes += 1
        if self.probes <= self._up_after:
            raise TunerdError("no game running")
        self._mode = self._real_mode
        return self._real_mode

    def detect_seat(self):
        self.detects += 1
        self.seat = self._seat_when_up
        return self.seat


class ResolveSeatTest(unittest.TestCase):
    def setUp(self):
        from harness import mcp_server
        self.mcp = mcp_server

    def test_detects_the_seat_once_the_game_is_up(self):
        g = _FakeGame(seat_when_up=0)
        self.assertTrue(self.mcp._resolve_seat(g))
        self.assertEqual(g.seat, 0)

    def test_an_unreachable_game_is_not_an_answer(self):
        g = _FakeGame(up_after=1)
        self.assertFalse(self.mcp._resolve_seat(g), "no game means 'ask again', not 'seat is 1'")
        self.assertEqual(g.detects, 0)

    def test_a_failed_probe_does_not_pin_the_cached_mode(self):
        """Game.mode() memoises; a probe that raised must leave nothing cached behind it."""
        g = _FakeGame(up_after=1)
        self.mcp._resolve_seat(g)
        self.assertIsNone(g._mode)

        self.assertTrue(self.mcp._resolve_seat(g))
        self.assertEqual(g.seat, 0)

    def test_hotseat_keeps_the_documented_default(self):
        """Hotseat runs every seat in one instance, so the engine cannot say which one is ours."""
        g = _FakeGame(mode="hotseat")
        g.seat = 1
        self.assertTrue(self.mcp._resolve_seat(g))
        self.assertEqual(g.seat, 1)
        self.assertEqual(g.detects, 0, "hotseat must not ask the engine")

    def test_game_retries_detection_on_later_calls(self):
        g = _FakeGame(seat_when_up=0)      # the startup probe already failed; the game is up now
        original_game, original_flag = self.mcp._game, self.mcp._seat_unresolved
        self.addCleanup(lambda: (setattr(self.mcp, "_game", original_game),
                                 setattr(self.mcp, "_seat_unresolved", original_flag)))
        g.seat = 1
        self.mcp._game = g
        self.mcp._seat_unresolved = True

        self.assertIs(self.mcp.game(), g)
        self.assertEqual(g.seat, 0, "the seat is corrected on the first call after the game loads")
        self.assertFalse(self.mcp._seat_unresolved)

        self.mcp.game()
        self.assertEqual(g.detects, 1, "a resolved seat is never re-detected")


if __name__ == "__main__":
    unittest.main()
