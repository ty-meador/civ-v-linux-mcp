"""Stage 4 of "A seat bound to its channel" (docs/ROADMAP.md): the escape hatches connect like any client.

A server whose tunerd connection is bound to a seat plays that seat and no other: a different --seat (what
scripts/mcp_call.py and scripts/mcp_session.py pass as CIV5_SEAT) is refused on every tool instead of
overridden in silence, set_seat moves nowhere else and re-detection lands on the binding without asking the
engine, the raw `lua` tool (--allow-lua) sends no text to InGame, and the harness client without a token --
the one path `harness.cli`, mcp_call.py and mcp_session.py share -- is unbound at a daemon with a table.
"""
import json
import os
import tempfile
import unittest
from unittest import mock

from harness import mcp_server as m
from harness.client import Civ5, TunerdError
from harness.game import Game
from harness.mcp_tools import reference, turn
from harness.tunerd import SeatTable
from test_seat_call import _RecordingClient
from test_set_seat import FakeGame
from test_tunerd_seats import _Daemon

TOKEN0 = "0" * 24


class BoundServerSeatTests(unittest.TestCase):
    """mcp_server.game() against the real daemon (scratch socket, stub bridge) with a one-seat table."""

    def setUp(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        self.path = os.path.join(d.name, "t.sock")
        self.daemon = _Daemon(self.path, SeatTable([{"seat": 0, "token": TOKEN0}]))
        self.daemon.start(); self.addCleanup(self.daemon.stop)
        for p in (mock.patch.object(m, "_game", None), mock.patch.object(m, "_seat_unresolved", False),
                  mock.patch.object(m, "_seat_rechecked", True), mock.patch.dict(m._RECENT, {}, clear=True)):
            p.start(); self.addCleanup(p.stop)

    def env(self, seat):
        return mock.patch.dict(os.environ, {"CIV5_TUNERD_SOCK": self.path, "CIV5_TUNERD_TOKEN": TOKEN0, "CIV5_SEAT": seat})

    def test_a_pinned_seat_that_is_not_the_binding_is_refused_not_overridden(self):
        with self.env("1"):
            with self.assertRaises(TunerdError) as cm:
                m.game()
            self.assertIn("bound to seat 0", str(cm.exception))
            self.assertIn("--seat 1", str(cm.exception))
            self.assertIsNone(m._game)
            # through a guarded tool the same refusal is a readable reply, and it comes back on every call
            for _ in range(2):
                out = json.loads(turn.set_seat(0))
                self.assertFalse(out["ok"]); self.assertIn("bound to seat 0", out["err"])
            self.assertEqual(self.daemon.bridge.seen, [])   # nothing of the game was read as the wrong seat

    def test_auto_takes_the_binding_without_detection(self):
        with self.env("auto"):
            g = m.game()
            self.assertEqual((g.seat, g.bound_seat), (0, 0))
            self.assertFalse(m._seat_unresolved)
            self.assertFalse(m._may_change_seat())   # a bound server never advertises set_seat
            self.assertEqual(self.daemon.bridge.seen, [])   # no detection trip

    def test_the_binding_itself_is_accepted(self):
        with self.env("0"):
            self.assertEqual(m.game().seat, 0)
            self.assertFalse(m._may_change_seat())

    def test_the_harness_client_without_a_token_is_unbound(self):
        """harness.cli, mcp_call.py and mcp_session.py all connect through Civ5: with no token in the sandbox
        there is nothing to bypass -- the daemon refuses the game's Lua ops and says what to send."""
        c = Civ5(self.path, token=None)
        self.addCleanup(c.close)
        self.assertIsNone(c.seat)
        with self.assertRaises(TunerdError) as cm:
            c.call_fn("turn_state", [], seat=0)
        self.assertIn("hello", str(cm.exception))
        with self.assertRaises(TunerdError):
            c.query("InGame", "return 1")
        self.assertEqual(self.daemon.bridge.seen, [])


class SetSeatOnBoundConnectionTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeGame(mode="hotseat", humans=(0, 1), active=1, seat=1)
        self.fake.bound_seat = 0
        for p in (mock.patch.object(m, "game", lambda: self.fake), mock.patch.object(m, "_game", None),
                  mock.patch.dict(os.environ, {"CIV5_TUNERD_SOCK": "/tmp/civ5-test-bound.sock", "CIV5_SEAT": "auto"}),
                  mock.patch.object(m, "_seat_rechecked", True), mock.patch.dict(m._RECENT, {}, clear=True)):
            p.start(); self.addCleanup(p.stop)

    def test_the_other_human_seat_is_refused_even_under_auto(self):
        out = json.loads(turn.set_seat(1))
        self.assertFalse(out["ok"])
        self.assertIn("bound to seat 0", out["err"]); self.assertIn("seat 1 is another player's", out["err"])
        self.assertEqual(out["bound"], 0)
        self.assertEqual(self.fake.seat, 0)   # and the server sits on its binding, not on the stale guess

    def test_redetection_lands_on_the_binding_without_asking_the_engine(self):
        out = json.loads(turn.set_seat())
        self.assertTrue(out["ok"]); self.assertEqual(out["seat"], 0); self.assertEqual(out["seat_before"], 1)
        self.assertEqual(self.fake.detects, 0)

    def test_the_binding_is_accepted(self):
        out = json.loads(turn.set_seat(0))
        self.assertTrue(out["ok"]); self.assertEqual(self.fake.seat, 0)


class BoundGameTests(unittest.TestCase):
    def game(self, seat=0):
        g = Game.__new__(Game)
        g.seat, g.c, g._runtime_ok, g._mode = 1, _RecordingClient(seat), True, None
        return g

    def test_detect_seat_returns_the_binding_and_asks_nothing(self):
        g = self.game(0)
        self.assertEqual(g.detect_seat(), 0)
        self.assertEqual(g.seat, 0)
        self.assertEqual(g.c.requests, [])

    def test_the_raw_lua_tool_sends_nothing_on_a_bound_connection(self):
        g = self.game(0)
        with mock.patch.object(reference, "lua_allowed", lambda: True), mock.patch.object(m, "game", lambda: g):
            out = json.loads(reference.lua.__wrapped__("return 1"))   # the tool's own body, past the turn gate
        self.assertFalse(out["ok"]); self.assertIn("bound to seat 0", out["err"])
        self.assertEqual(g.c.requests, [])


if __name__ == "__main__":
    unittest.main()
