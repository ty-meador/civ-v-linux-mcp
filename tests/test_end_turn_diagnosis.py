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
        # runtime.lua is loaded in a bare Lua state; read the string back through an error message,
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

        def dismiss_pending_popups(self):
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


if __name__ == "__main__":
    unittest.main()
