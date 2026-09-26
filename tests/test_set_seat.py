"""set_seat and the seat in every answer: the way out of "this seat is not active".

Live 2026-09-25: a hotseat save loaded under --seat auto left the server on its default seat 1 while seat 0
sat on the hand-off screen. Every tool refused with only active_player=0, wait_for_my_turn ran its full
timeout, and nothing said which seat the server thought it was playing. Now the refusal and the timeout name
the seat and the fix, turn_status carries `seat`, and set_seat changes it without a server restart (which is
what loses the tools for the session).

Exercised through a real MCP client over the SDK's memory transport with mcp_server.game() replaced by a fake.
"""
import json
import os
import unittest
from unittest import mock

import anyio
from mcp import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from harness import mcp_server as m


class FakeGame:
    def __init__(self, mode="hotseat", humans=(0, 1), active=0, seat=1):
        self.seat = seat
        self._mode = mode
        self._real_mode = mode
        self.humans = list(humans)
        self.active = active
        self.detects = 0
        self.turn = 227

    def has_state(self, name):
        return True

    def mode(self):
        if self._mode is None:
            self._mode = self._real_mode
        return self._mode

    def human_seats(self):
        return list(self.humans)

    def detect_seat(self):
        self.detects += 1
        self.seat = self.humans[0]
        return self.seat

    def turn_state(self, pid=None):
        pid = self.seat if pid is None else pid
        return {"turn": self.turn, "active_player": self.active, "my_turn": self.active == pid, "processing": False,
                "paused": False, "hotseat": self._real_mode == "hotseat", "mode": self._real_mode,
                "blocking_name": "NO_ENDTURN_BLOCKING_TYPE", "todo": {}, "pending_popups": []}

    def expiring_city_states(self):
        return []

    def discussion_pending(self):
        return False

    def wait_for_my_turn(self, timeout=90, on_wait=None):
        if self.active != self.seat:
            raise TimeoutError("timed out waiting for our turn")
        return self.turn_state()

    def overview_dict(self):
        return {"id": self.seat}


async def session(calls):
    outs = []
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        async with anyio.create_task_group() as tg:
            srv = m.mcp._lowlevel_server

            async def run_server():
                await srv.run(server_streams[0], server_streams[1], srv.create_initialization_options())
            tg.start_soon(run_server)
            async with ClientSession(client_streams[0], client_streams[1]) as s:
                await s.initialize()
                for name, args in calls:
                    res = await s.call_tool(name, args)
                    outs.append(json.loads(res.content[0].text))
            tg.cancel_scope.cancel()
    return outs


class SetSeatTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeGame()
        self.patches = [mock.patch.object(m, "game", lambda: self.fake),
                        mock.patch.dict(os.environ, {"CIV5_TUNERD_SOCK": "/tmp/civ5-test-seat.sock", "CIV5_SEAT": "auto"}),
                        mock.patch.object(m, "_seat_rechecked", True),
                        mock.patch.dict(m._RECENT, {}, clear=True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_refusal_names_the_seat_and_the_fix(self):
        (out,) = anyio.run(session, [("units", {})])
        self.assertFalse(out["ok"])
        self.assertEqual(out["err"], "this seat is not active")
        self.assertEqual((out["seat"], out["active_player"]), (1, 0))
        self.assertIn("set_seat", out["hint"])

    def test_turn_status_carries_the_seat_and_a_hotseat_note(self):
        (out,) = anyio.run(session, [("turn_status", {})])
        self.assertEqual(out["seat"], 1)
        self.assertIn("set_seat", out["seat_note"])

    def test_wait_timeout_says_who_holds_the_turn(self):
        (out,) = anyio.run(session, [("wait_for_my_turn", {"timeout_seconds": 1})])
        self.assertFalse(out["ok"])
        self.assertTrue(out["timed_out"])
        self.assertEqual((out["seat"], out["active_player"]), (1, 0))
        self.assertIn("set_seat(0)", out["hint"])

    def test_a_pinned_server_refuses_the_other_players_seat(self):
        """Two agents in one hotseat game: each server is started with its own --seat, and the other human
        seat is the other player's (taking it on its turn would read their map). Only --seat auto may move."""
        with mock.patch.dict(os.environ, {"CIV5_SEAT": "1"}):
            out, same = anyio.run(session, [("set_seat", {"player_id": 0}), ("set_seat", {"player_id": 1})])
        self.assertFalse(out["ok"])
        self.assertIn("plays only that seat", out["err"])
        self.assertIn("seat 0 is another player's", out["err"])
        self.assertEqual(self.fake.seat, 1)
        self.assertTrue(same["ok"])

    def test_set_seat_switches_and_the_tools_work_again(self):
        before, out, after = anyio.run(session, [("units", {}), ("set_seat", {"player_id": 0}), ("turn_status", {})])
        self.assertFalse(before["ok"])
        self.assertTrue(out["ok"])
        self.assertEqual((out["seat"], out["seat_before"], out["human_seats"]), (0, 1, [0, 1]))
        self.assertTrue(out["my_turn"])
        self.assertIsNone(out["hint"])
        self.assertEqual(self.fake.seat, 0)
        self.assertEqual(after["seat"], 0)
        self.assertNotIn("seat_note", after)
        self.assertFalse(m._seat_rechecked, "a chosen seat gets its free re-detection back")

    def test_only_a_human_seat_can_be_chosen(self):
        (out,) = anyio.run(session, [("set_seat", {"player_id": 5})])
        self.assertFalse(out["ok"])
        self.assertEqual(out["human_seats"], [0, 1])
        self.assertEqual(self.fake.seat, 1, "an AI seat must never become ours")

    def test_no_argument_takes_the_seat_on_screen_in_hotseat(self):
        (out,) = anyio.run(session, [("set_seat", {})])
        self.assertTrue(out["ok"])
        self.assertEqual(out["seat"], 0)
        self.assertEqual(self.fake.detects, 0, "hotseat never asks the engine to detect")

    def test_no_argument_refuses_an_ai_on_screen_in_hotseat(self):
        self.fake.active = 7
        (out,) = anyio.run(session, [("set_seat", {})])
        self.assertFalse(out["ok"])
        self.assertEqual(self.fake.seat, 1)

    def test_no_argument_redetects_in_a_solo_game(self):
        self.fake = FakeGame(mode="single", humans=(0,), active=0, seat=1)
        self.patches[0].stop()
        self.patches[0] = mock.patch.object(m, "game", lambda: self.fake)
        self.patches[0].start()
        (out,) = anyio.run(session, [("set_seat", {})])
        self.assertTrue(out["ok"])
        self.assertEqual((out["seat"], self.fake.detects), (0, 1))

    def test_set_seat_never_runs_inside_a_batch(self):
        (out,) = anyio.run(session, [("do", {"actions": [{"tool": "set_seat", "args": {"player_id": 0}}]})])
        self.assertFalse(out["ok"])
        self.assertEqual(self.fake.seat, 1)


class MenuGame(FakeGame):
    """A game that can be left and loaded: the screen flips to MainMenu on leave, InGame on load."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.screen = "InGame"
        self.saves = 0
        self.loaded = []

    def has_state(self, name):
        return self.screen == name

    def front_end_screen(self):
        return self.screen

    def quick_save(self):
        self.saves += 1
        return {"ok": True}

    def leave_to_main_menu(self):
        self.screen = "MainMenu"
        self._mode = None

    def load_save(self, filename, timeout=600):
        self.loaded.append(filename)
        self.screen = "InGame"
        self._mode = None
        return {"ok": True, "turn": 270}

    def load_latest(self, timeout=600):
        return self.load_save("<latest>")


class ExitAndLoadTests(unittest.TestCase):
    def setUp(self):
        self.fake = MenuGame(mode="single", humans=(0,), active=0, seat=0)
        self.patches = [mock.patch.object(m, "game", lambda: self.fake),
                        mock.patch.dict(os.environ, {"CIV5_TUNERD_SOCK": "/tmp/civ5-test-seat.sock", "CIV5_SEAT": "auto"}),
                        mock.patch.object(m, "_seat_rechecked", True),
                        mock.patch.object(m, "_seat_unresolved", False),
                        mock.patch.dict(m._RECENT, {}, clear=True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_exit_saves_a_solo_turn_and_reaches_the_menu(self):
        (out,) = anyio.run(session, [("exit_to_main_menu", {})])
        self.assertTrue(out["ok"])
        self.assertEqual((out["screen"], out["saved"], self.fake.saves), ("MainMenu", True, 1))
        self.assertIn("load_save", out["hint"])

    def test_exit_without_saving_and_when_not_my_turn(self):
        self.fake.active = 3
        (out,) = anyio.run(session, [("exit_to_main_menu", {"save": True})])
        self.assertTrue(out["ok"])
        self.assertEqual((out["saved"], self.fake.saves), (False, 0), "not our turn: nothing to save")
        self.fake.screen, self.fake.active = "InGame", 0
        (out,) = anyio.run(session, [("exit_to_main_menu", {"save": False})])
        self.assertEqual((out["saved"], self.fake.saves), (False, 0))

    def test_exit_from_the_menu_is_a_no_op(self):
        self.fake.screen = "MainMenu"
        (out,) = anyio.run(session, [("exit_to_main_menu", {})])
        self.assertTrue(out["ok"])
        self.assertTrue(out["already"])

    def test_exit_never_runs_inside_a_batch(self):
        (out,) = anyio.run(session, [("do", {"actions": [{"tool": "exit_to_main_menu", "args": {}}]})])
        self.assertFalse(out["ok"])
        self.assertEqual(self.fake.screen, "InGame")

    def test_a_load_detects_the_seat_afresh_and_names_it(self):
        self.fake.screen, self.fake.seat = "MainMenu", 1     # a stale seat from the previous game
        (out,) = anyio.run(session, [("load_save", {"filename": "Pocatello_0270 pre-keepalive"})])
        self.assertTrue(out["ok"])
        self.assertEqual(self.fake.loaded, ["Pocatello_0270 pre-keepalive"])
        self.assertEqual((out["seat"], self.fake.detects), (0, 1), "the solo game's one human seat")
        self.assertFalse(m._seat_rechecked, "the new game gets its free re-detection back")

    def test_load_latest_names_the_seat_too(self):
        self.fake.screen = "MainMenu"
        (out,) = anyio.run(session, [("load_latest", {})])
        self.assertTrue(out["ok"])
        self.assertEqual(out["seat"], 0)

    def test_a_hotseat_load_keeps_the_default_seat(self):
        self.fake = MenuGame(mode="hotseat", humans=(0, 1), active=0, seat=1)
        self.fake.screen = "MainMenu"
        self.patches[0].stop()
        self.patches[0] = mock.patch.object(m, "game", lambda: self.fake)
        self.patches[0].start()
        (out,) = anyio.run(session, [("load_save", {"filename": "Alpha-Bravo_0227 peace"})])
        self.assertEqual((out["seat"], self.fake.detects), (1, 0))


if __name__ == "__main__":
    unittest.main()
