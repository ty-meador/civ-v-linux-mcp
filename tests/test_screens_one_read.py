"""Runtime v214: every popup / leader screen's up-or-down comes from one InGame query (H.modal_flags),
carried in turn_state's own answer, instead of one tuner round-trip per Lua context.

Profiled live before the change (S1 t270, 2026-09-25, `scripts/play_loop.py --profile`): a turn took 97 s
and 278 round-trips of ~0.35 s; turn_state was 8 trips (3.1 s), the popup sweep about 20, and the wait
loop repeated both every poll, so 250 of the 278 trips were screen reads. After: turn_state 1 trip,
sweep-with-nothing-up 1 trip, an idle wait poll 2 trips.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from harness.game import Game

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FLAGS = {"leader_greeting_pending": False, "city_state_greeting_pending": False,
         "great_person_reward_pending": False, "tech_popup_pending": False, "discussion_pending": False}


def _game():
    g = Game.__new__(Game)
    g.seat = 0
    g._runtime_ok = True
    g._pid = lambda pid=None: 0
    return g


class TurnStateCarriesTheFlags(unittest.TestCase):
    def test_a_v214_answer_needs_no_second_query(self):
        g = _game()
        calls = []

        def q(code, timeout=None):
            calls.append(code)
            return {"turn": 271, "active_player": 0, "pending_popups": [], **FLAGS, "trade_state": "SimpleDiploTrade",
                    "discussion_pending": True}
        g.q = q
        ts = g.turn_state()
        self.assertEqual(len(calls), 1)
        self.assertTrue(ts["discussion_pending"])
        self.assertEqual(ts["trade_state"], "SimpleDiploTrade", "the gate names accept_deal / refuse_deal by it")
        self.assertEqual(g._trade_state, "SimpleDiploTrade")
        self.assertIn("leader_screen_note", ts)

    def test_an_older_answer_gets_the_flags_from_one_more_query(self):
        g = _game()
        calls = []

        def q(code, timeout=None):
            calls.append(code)
            if "modal_flags" in code:
                return {**FLAGS, "tech_popup_pending": True, "screens": {"TechPopup": True}}
            return {"turn": 271, "active_player": 0, "pending_popups": []}
        g.q = q
        ts = g.turn_state()
        self.assertEqual(len(calls), 2)
        self.assertTrue(ts["tech_popup_pending"])
        for k in FLAGS:
            self.assertIn(k, ts)

    def test_the_single_flag_readers_are_one_query_each(self):
        g = _game()
        calls = []
        g.q = lambda code, timeout=None: calls.append(code) or {**FLAGS, "leader_greeting_pending": True,
                                                                "leader_head_root_up": True, "screens": {}}
        self.assertTrue(g.leader_greeting_pending())
        self.assertFalse(g.discussion_pending())
        self.assertFalse(g.tech_popup_pending())
        self.assertFalse(g._trade_up())
        self.assertEqual(len(calls), 4)
        self.assertTrue(all("modal_flags" in c for c in calls))


class TheSweepReusesWhatItHolds(unittest.TestCase):
    def _sweep_game(self, screens, pending=()):
        g = _game()
        calls = {"q": [], "exec": [], "query": []}

        def q(code, timeout=None):
            calls["q"].append(code)
            if "modal_flags" in code:
                return {**FLAGS, "screens": dict(screens)}
            if "H.turn_state" in code:
                return {"active_player": 0, "pending_popups": list(pending), "popup_up": bool(screens), **FLAGS}
            if "GetCurrentResearch" in code:
                return 5
            return True
        g.q = q
        g.c = type("C", (), {
            "exec": staticmethod(lambda state, lua, check=True: calls["exec"].append((state, lua)) or []),
            "query": staticmethod(lambda state, lua, timeout=None: calls["query"].append((state, lua)) or True),
            "states": staticmethod(lambda: {1: "InGame", 2: "TextPopup"}),
        })()
        return g, calls

    def test_nothing_up_is_one_query_when_the_caller_passes_its_turn_state(self):
        g, calls = self._sweep_game({"TextPopup": False, "LeagueSplash": False})
        ts = {"active_player": 0, "pending_popups": [], **FLAGS}
        self.assertEqual(g.dismiss_pending_popups(ts), [])
        self.assertEqual(len(calls["q"]), 1)
        self.assertIn("modal_flags", calls["q"][0])
        self.assertEqual(calls["query"], [], "no per-context visibility probes any more")

    def test_nothing_up_without_a_turn_state_reads_one(self):
        g, calls = self._sweep_game({"TextPopup": False})
        self.assertEqual(g.dismiss_pending_popups(), [])
        self.assertEqual(len(calls["q"]), 2)

    def test_a_screen_that_is_up_is_closed_in_its_own_state(self):
        g, calls = self._sweep_game({"TextPopup": True})
        ts = {"active_player": 0, "pending_popups": [], **FLAGS}
        out = g.dismiss_pending_popups(ts)
        self.assertIn("TextPopup", out)
        self.assertEqual(calls["exec"][0], ("TextPopup", "OnCloseButtonClicked()"))
        self.assertEqual(calls["query"][0][0], "TextPopup", "the close is still confirmed in that context")

    def test_another_seat_is_left_alone_without_any_read(self):
        g, calls = self._sweep_game({"TextPopup": True})
        self.assertEqual(g.dismiss_pending_popups({"active_player": 1, "pending_popups": []}), [])
        self.assertEqual(calls["q"], [])


class EndTurnAndTheWaitUseTheCarriedFlags(unittest.TestCase):
    def test_end_turn_refuses_on_the_flag_in_its_one_read(self):
        g = _game()
        sends = []
        g.turn_state = lambda pid=None: {"turn": 271, "active_player": 0, "hotseat": False, **FLAGS, "discussion_pending": True}
        g.discussion_pending = lambda: (_ for _ in ()).throw(AssertionError("a second read"))
        g._end_turn_send = lambda lua: sends.append(lua) or {"ok": True}
        r = g.end_turn()
        self.assertEqual(r, {"ok": False, "err": "diplomatic decision pending"})
        self.assertEqual(sends, [])

    def test_an_idle_wait_poll_is_two_queries(self):
        g = _game()
        calls = []
        polls = {"n": 0}

        def q(code, timeout=None):
            calls.append(code)
            if "modal_flags" in code:
                return {**FLAGS, "screens": {}}
            if "H.turn_state" in code:
                polls["n"] += 1
                done = polls["n"] >= 4
                return {"turn": 271, "active_player": 0, "my_turn": True, "processing": not done, "hotseat": False,
                        "pending_popups": [], "todo": {"units": []}, **FLAGS}
            return []
        g.q = q
        g.c = type("C", (), {"ping": staticmethod(lambda: {"connected": True})})()
        g.expiring_city_states = list
        g._unit_rows = lambda pid=None: []
        ts = g.wait_for_my_turn(timeout=5, poll=0.01)
        self.assertTrue(ts["my_turn"])
        idle = [c for c in calls if "H.turn_state" in c or "modal_flags" in c]
        # 3 idle polls x (turn_state + sweep) + the final poll's turn_state + sweep + resume_moves' read,
        # + one turn_state for the look at a leader arriving right after the turn starts (_late_discussion)
        self.assertLessEqual(len(idle), 2 * 4 + 1)


class LoopProfilerTests(unittest.TestCase):
    def test_trips_are_attributed_to_the_phase_and_the_game_method(self):
        spec = importlib.util.spec_from_file_location("play_loop", ROOT / "scripts" / "play_loop.py")
        play_loop = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(play_loop)
        g = _game()
        g.c = type("C", (), {"call": staticmethod(lambda **req: {"ok": True, "result": []})})()
        g.q = lambda code, timeout=None: g.c.call(op="query", state="InGame", lua=code)
        prof = play_loop.Profile(g)
        with prof.in_phase("ensure_production"):
            g.units()
            g.units()
        keys = list(prof.calls)
        self.assertEqual(keys, [("ensure_production", "units")])
        self.assertEqual(prof.calls[keys[0]][0], 2)
        self.assertEqual(prof.phases["ensure_production"][0], 1)
        lines = []
        play_loop.log = lambda msg: lines.append(msg)
        prof.report("turn 1")
        self.assertTrue(any("phase ensure_production" in l and "2 trips" in l for l in lines), lines)
        self.assertTrue(any(l.strip().startswith("units") and "2 trips" in l for l in lines), lines)
        self.assertEqual(prof.calls, {}, "a report starts the next turn's count")


if __name__ == "__main__":
    unittest.main()
