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


class _FakeClient:
    """Stands in for Civ5.exec: answers the human scan and the active-player read."""

    def __init__(self, humans, active):
        self.humans = humans
        self.active = active
        self.calls = []

    def exec(self, state, code):
        self.calls.append(code)
        if "IsHuman" in code:
            return ["" , ",".join(str(i) for i in self.humans)]
        return [str(self.active)]


class _SeatGame:
    """The real Game.detect_seat / human_seats over a fake tuner client."""

    def __init__(self, mode, humans, active):
        from harness.game import Game
        self.mode = lambda: mode
        self.seat = 1
        self.c = _FakeClient(humans, active)
        self.detect_seat = Game.detect_seat.__get__(self)
        self.human_seats = Game.human_seats.__get__(self)


class DetectSeatTest(unittest.TestCase):
    def test_solo_seat_is_the_human_not_whichever_ai_is_thinking(self):
        """Live 2026-09-21: detection ran while Pacal (1) moved; we are Pocatello (0)."""
        g = _SeatGame("single", humans=[0], active=1)
        self.assertEqual(g.detect_seat(), 0)
        self.assertNotIn("GetActivePlayer", " ".join(g.c.calls))

    def test_solo_falls_back_to_the_active_player_when_the_scan_says_nothing(self):
        g = _SeatGame("single", humans=[], active=3)
        self.assertEqual(g.detect_seat(), 3)

    def test_network_games_keep_using_the_active_player(self):
        """LAN: the active player IS this instance's player, and several seats are human."""
        g = _SeatGame("lan", humans=[0, 1], active=1)
        self.assertEqual(g.detect_seat(), 1)


class RecheckSeatTest(unittest.TestCase):
    def setUp(self):
        from harness import mcp_server
        self.mcp = mcp_server
        original = mcp_server._seat_rechecked
        self.addCleanup(lambda: setattr(mcp_server, "_seat_rechecked", original))
        mcp_server._seat_rechecked = False

    def test_a_wrong_seat_is_corrected_instead_of_refusing_forever(self):
        g = _FakeGame(seat_when_up=0)
        g.seat = 1
        states = [{"active_player": 0}, {"active_player": 0}]
        g.turn_state = lambda: states.pop(0)
        ts = self.mcp._recheck_seat(g, {"active_player": 0})
        self.assertEqual(g.seat, 0)
        self.assertEqual(ts["active_player"], 0, "the state is re-read once the seat moves")

    def test_an_ai_holding_the_turn_costs_only_one_probe_ever(self):
        g = _FakeGame(seat_when_up=0)
        g.seat = 0
        g.turn_state = lambda: self.fail("no re-read when the seat did not change")
        for _ in range(3):
            self.mcp._recheck_seat(g, {"active_player": 4})
        self.assertLessEqual(g.detects, 1, "re-detection happens at most once per server")

    def test_an_explicit_seat_is_never_second_guessed(self):
        import os
        g = _FakeGame(seat_when_up=0)
        g.seat = 2
        os.environ["CIV5_SEAT"] = "2"
        self.addCleanup(lambda: os.environ.pop("CIV5_SEAT", None))
        self.mcp._recheck_seat(g, {"active_player": 0})
        self.assertEqual(g.seat, 2)
        self.assertEqual(g.detects, 0)


if __name__ == "__main__":
    unittest.main()
