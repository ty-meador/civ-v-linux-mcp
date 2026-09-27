"""A turn that will not end must say something true about why.

Live t189 (Shoshone vs the Inca): end_turn answered
  "CONTROL_ENDTURN was sent but the turn did not end: a unit or decision still blocks it"
with blocking NO_ENDTURN_BLOCKING_TYPE and an empty todo -- three statements that together say
nothing, and no way to tell them apart from a unit that genuinely needs orders. The engine had the
answer the whole time: UI.CanEndTurn() was false, meaning the stock HUD's own End Turn button was
greyed out and CONTROL_ENDTURN was being discarded on arrival.
"""
import unittest

import test_mcp_safety as support
from harness.game import Game


WORLD = """
UI={CanEndTurn=function() return CAN_END end,
    IsCityScreenUp=function() return false end,
    GetInterfaceMode=function() return 1 end}
Game.IsProcessingMessages=function() return false end
Players={[0]={
  HasReadyUnit=function() return READY end,
  HasBusyUnit=function() return false end,
  GetEndTurnBlockingType=function() return -1 end,
  IsTurnActive=function() return true end,
}}
"""


class EndTurnDiagnosisLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)

    def diagnose(self, can_end, ready=False):
        self.run_lua(f"CAN_END={'true' if can_end else 'false'}; READY={'true' if ready else 'false'}")
        self.run_lua(WORLD)
        self.run_lua("""
        D = H.end_turn_diagnosis(0)
        OUT = tostring(D.can_end_turn) .. '|' .. tostring(D.has_ready_unit) .. '|'
              .. tostring(D.blocking) .. '|' .. tostring(D.note ~= nil)
        """)
        return self.lua_out()

    def lua_out(self):
        # the runtime is loaded in a bare Lua state; read the string back through an error message,
        # which is how run_lua reports to Python.
        captured = {}
        try:
            self.run_lua("error(OUT, 0)")
        except AssertionError as e:      # run_lua calls self.fail()
            captured["v"] = str(e)
        return captured.get("v", "")

    def test_a_disabled_end_turn_button_is_named_as_such(self):
        out = self.diagnose(can_end=False)
        self.assertTrue(out.startswith("false|false|-1|true"),
                        f"expected can_end_turn false with a note, got {out!r}")

    def test_a_normal_refusal_carries_no_misleading_note(self):
        out = self.diagnose(can_end=True, ready=True)
        self.assertTrue(out.startswith("true|true|-1|false"),
                        f"a ready unit is an ordinary blocker, not the disabled-button case: {out!r}")


class EndTurnMessageTest(unittest.TestCase):
    """game.py must prefer the engine's answer over its own guess."""

    class FakeGame(Game):
        def __init__(self, diag):
            self.seat = 0
            self._diag = diag

        def q(self, lua, *a, **kw):
            return self._diag if "end_turn_diagnosis" in lua else {}

        def turn_state(self):
            return {"turn": 189, "my_turn": True, "active_player": 0, "hotseat": False,
                    "blocking_name": "NO_ENDTURN_BLOCKING_TYPE", "todo": {"units": []},
                    "blocking_hint": None}

        def discussion_pending(self):
            return False

        def dismiss_pending_popups(self, ts=None):
            return False

        def _end_turn_send(self, autosave_lua):
            return {"ok": True, "turn_complete_sent": False}

    def _fail_message(self, diag):
        g = self.FakeGame(diag)
        r = Game.end_turn(g, autosave=False)
        self.assertFalse(r["ok"])
        return r

    def test_the_disabled_button_is_reported_instead_of_a_guess(self):
        r = self._fail_message({"can_end_turn": False, "has_ready_unit": False,
                                "note": "the engine's own End Turn is disabled (UI.CanEndTurn() is false), so ..."})
        self.assertIn("UI.CanEndTurn() is false", r["err"])
        self.assertNotIn("a unit or decision still blocks it", r["err"])
        self.assertEqual(r["engine"]["can_end_turn"], False)

    def test_without_an_engine_note_the_old_wording_still_stands(self):
        r = self._fail_message({"can_end_turn": True, "has_ready_unit": True})
        self.assertIn("a unit or decision still blocks it", r["err"])
        self.assertEqual(r["engine"]["has_ready_unit"], True)


class HotseatEndIsConfirmedTest(unittest.TestCase):
    """Live 2026-09-27 (Mongolia, seat 1, t93): end_turn returned the moment CONTROL_ENDTURN was sent, and
    finish_turn's first poll read the not-yet-processed end as turn 93 still ours. The tool answered
    ended=true, turn 93, my_turn true while the game was on seat 0's turn 94: the caller would have acted on
    a turn that was over. Hotseat confirms the end the way single player does."""

    class FakeGame(Game):
        _END_TURN_CONFIRM_POLLS = 4
        _END_TURN_CONFIRM_SLEEP = 0.0

        def __init__(self, stale_reads, then):
            self.seat = 1
            self.reads = 0
            self.stale_reads = stale_reads
            self.then = then

        def q(self, lua, *a, **kw):
            return {"can_end_turn": True} if "end_turn_diagnosis" in lua else {}

        def turn_state(self):
            self.reads += 1
            stale = {"turn": 93, "my_turn": True, "active_player": 1, "hotseat": True, "processing": False,
                     "hand_off_pending": False, "blocking_name": "NO_ENDTURN_BLOCKING_TYPE", "todo": {"units": []}}
            # the first read is end_turn's own precondition read; the engine processes the end `stale_reads`
            # reads later
            if self.reads <= 1 + self.stale_reads:
                return stale
            return {**stale, **self.then}

        def dismiss_pending_popups(self, ts=None):
            return False

        def _claim_turn(self, ts, what, force=False):
            return None

        def _end_turn_send(self, autosave_lua):
            return {"ok": True, "turn_complete_sent": False}

    def test_the_other_seat_taking_the_screen_confirms_the_end(self):
        g = self.FakeGame(stale_reads=2, then={"turn": 94, "active_player": 0, "my_turn": False})
        r = Game.end_turn(g, autosave=False)
        self.assertTrue(r["ok"] and r.get("confirmed"))
        self.assertEqual(g.reads, 4, "polled past the two stale reads, then stopped")

    def test_the_ai_round_starting_confirms_the_end(self):
        g = self.FakeGame(stale_reads=1, then={"processing": True})
        self.assertTrue(Game.end_turn(g, autosave=False)["ok"])

    def test_an_end_that_never_takes_is_refused_in_hotseat_too(self):
        g = self.FakeGame(stale_reads=99, then={})
        r = Game.end_turn(g, autosave=False)
        self.assertFalse(r["ok"])
        self.assertIn("did not end", r["err"])
        self.assertEqual(g.reads, 1 + 4 + 1, "the precondition read, every confirm poll, the diagnosis read")


if __name__ == "__main__":
    unittest.main()


class StaleBlockerResendTest(unittest.TestCase):
    """Live 2026-09-27 (Mongolia, t139): set_production then end_turn in one batch; the engine still named
    PRODUCTION (it re-reads the blocker on its next update) and discarded CONTROL_ENDTURN, so the turn was
    refused with an empty todo. One settle and one re-send end it; a real blocker still gets one send."""

    class FakeGame(Game):
        _END_TURN_CONFIRM_POLLS = 2
        _END_TURN_CONFIRM_SLEEP = 0.0
        _END_TURN_STALE_SETTLE = 0.0

        def __init__(self, todo, ends_on_send):
            self.seat = 1
            self.sends = 0
            self.todo = todo
            self.ends_on_send = ends_on_send

        def q(self, lua, *a, **kw):
            return {"can_end_turn": True, "note": "engine: still blocked"} if "end_turn_diagnosis" in lua else {}

        def turn_state(self):
            if self.sends >= self.ends_on_send:
                return {"turn": 140, "active_player": 0, "my_turn": False, "hotseat": True}
            return {"turn": 139, "my_turn": True, "active_player": 1, "hotseat": True, "processing": False,
                    "hand_off_pending": False, "blocking_name": "ENDTURN_BLOCKING_PRODUCTION", "todo": self.todo}

        def dismiss_pending_popups(self, ts=None):
            return False

        def _claim_turn(self, ts, what, force=False):
            return None

        def _end_turn_send(self, autosave_lua):
            self.sends += 1
            return {"ok": True, "turn_complete_sent": False}

    def test_a_stale_production_blocker_gets_one_resend_and_the_turn_ends(self):
        g = self.FakeGame(todo={"cities": [], "units": []}, ends_on_send=2)
        r = Game.end_turn(g, autosave=False)
        self.assertTrue(r["ok"] and r.get("confirmed"), r)
        self.assertEqual(g.sends, 2)
        self.assertIn("re-evaluated", r["resent"])

    def test_a_real_production_blocker_is_refused_after_one_send(self):
        g = self.FakeGame(todo={"cities": [{"id": 16385}], "units": []}, ends_on_send=99)
        r = Game.end_turn(g, autosave=False)
        self.assertFalse(r["ok"])
        self.assertEqual(g.sends, 1)
        self.assertEqual(r["blocking"], "ENDTURN_BLOCKING_PRODUCTION")

    def test_an_announcement_that_arrives_after_the_sweep_is_swept_and_the_end_resent(self):
        # live t153 (Mongolia): the Great Work splash came up a moment after the artist's order; end_turn's own
        # sweep had run before it, and CONTROL_ENDTURN was discarded against it
        g = self.FakeGame(todo={"cities": [], "units": []}, ends_on_send=2)
        g.swept = 0
        base_state = g.turn_state

        def turn_state():
            ts = base_state()
            if g.sends == 1 and g.swept == 0:
                ts = {**ts, "blocking_name": "ENDTURN_BLOCKING_UNITS", "todo": {"units": [], "cities": []},
                      "pending_popups": [{"name": "BUTTONPOPUP_GREAT_WORK_COMPLETED_ACTIVE_PLAYER"}]}
            return ts
        g.turn_state = turn_state

        def dismiss(ts=None):
            g.swept += 1
            return True
        g.dismiss_pending_popups = dismiss
        r = Game.end_turn(g, autosave=False)
        self.assertTrue(r["ok"] and r.get("confirmed"), r)
        self.assertEqual((g.sends, g.swept), (2, 1))

    def test_a_stale_blocker_that_never_clears_is_still_refused(self):
        g = self.FakeGame(todo={"cities": [], "units": []}, ends_on_send=99)
        r = Game.end_turn(g, autosave=False)
        self.assertFalse(r["ok"])
        self.assertEqual(g.sends, 2)
