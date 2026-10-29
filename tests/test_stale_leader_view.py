"""GitLab #137: a leader left on screen at an exit to the main menu keeps the next loaded game's End Turn disabled.

Live Maya t200 (2026-10-29): finish met Dido's friendship request during the AI turns; session(main_menu) with
that screen up, then load of the same save, left UI.CanEndTurn() false with NO_ENDTURN_BLOCKING_TYPE, no popup
and no leader in any Lua context, so every CONTROL_ENDTURN was discarded. UI.RequestLeaveLeader() (the leader
screen's back button) clears it at once. Two paths: exit_to_main_menu leaves an open leader view first, and
end_turn_send clears a stale one when nothing on screen explains the disabled button.
"""
import unittest

import test_mcp_safety as support


WORLD = """
CAN_END = false; BLOCKING = -1; LEADER = false; POPUPS = {}
LEFT = 0; EXITED = 0; CONTROLS = {}
GameInfoTypes = {CONTROL_ENDTURN = 7}
UI = {CanEndTurn = function() return CAN_END end,
      RequestLeaveLeader = function() LEFT = LEFT + 1; CAN_END = true end,
      QuickSave = function() end,
      IsCityScreenUp = function() return false end,
      GetInterfaceMode = function() return 1 end}
Game.IsPaused = function() return false end
Game.IsProcessingMessages = function() return false end
Game.IsNetworkMultiPlayer = function() return false end
Game.DoControl = function(c) CONTROLS[#CONTROLS + 1] = c end
Events.ExitToMainMenu = function() EXITED = EXITED + 1 end
Players = {[0] = {
  IsTurnActive = function() return true end,
  HasReadyUnit = function() return false end,
  HasBusyUnit = function() return false end,
  GetEndTurnBlockingType = function() return BLOCKING end,
  GetCurrentResearch = function() return 3 end,
}}
H.modal_flags = function() return {leader_greeting_pending = LEADER, discussion_pending = false} end
H.pending_popups = function() return POPUPS end
H.todo = function() return {units = {}, cities = {}, promotions = {}} end
H.stale_blocker = function() return nil end
RECORDED = nil
H.record = function(kind, data) RECORDED = kind end
"""


class StaleLeaderViewLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_end_turn_send_clears_the_stale_view_and_says_so(self):
        self.run_lua("""
        local r = H.end_turn_send(false, 0)
        assert(r.ok == true, tostring(r.err))
        assert(r.stale_leader_view_cleared == true, "the reply says the stale view was cleared")
        assert(LEFT == 1, "UI.RequestLeaveLeader() once, got " .. LEFT)
        assert(#CONTROLS == 1 and CONTROLS[1] == 7, "CONTROL_ENDTURN still sent")
        assert(RECORDED == "stale_leader_view_cleared", "the digest carries what was done: " .. tostring(RECORDED))
        """)

    def test_an_enabled_end_turn_is_left_alone(self):
        self.run_lua("""
        CAN_END = true
        local r = H.end_turn_send(false, 0)
        assert(r.ok == true and r.stale_leader_view_cleared == nil, "no flag when nothing was cleared")
        assert(LEFT == 0, "RequestLeaveLeader not called")
        assert(RECORDED == nil, "nothing recorded when nothing was cleared")
        """)

    def test_a_leader_really_on_screen_is_not_walked_out_on(self):
        self.run_lua("""
        LEADER = true
        local c = H.clear_stale_leader_view(0)
        assert(c.cleared == false and c.why == "a leader is on screen", c.why)
        assert(LEFT == 0)
        """)

    def test_a_named_blocker_or_a_popup_is_the_real_reason(self):
        self.run_lua("""
        BLOCKING = 5
        assert(H.clear_stale_leader_view(0).why == "the engine names a blocker")
        BLOCKING = -1; POPUPS = {{type = "X"}}
        assert(H.clear_stale_leader_view(0).why == "a popup is up")
        assert(LEFT == 0)
        """)

    def test_exit_to_main_menu_leaves_an_open_leader_view_first(self):
        self.run_lua("""
        LEADER = true
        local r = H.exit_to_main_menu(0)
        assert(r.ok == true and r.left_leader_view == true, "the reply says the view was left")
        assert(LEFT == 1 and EXITED == 1)
        LEADER = false; LEFT = 0
        r = H.exit_to_main_menu(0)
        assert(r.left_leader_view == nil and LEFT == 0 and EXITED == 2, "no leader: nothing to leave")
        """)

    def test_the_diagnosis_carries_the_leader_view_and_names_the_tried_case(self):
        self.run_lua("""
        local d = H.end_turn_diagnosis(0)
        assert(d.leader_view_up == false)
        assert(d.note and d.note:find("GitLab #137", 1, true), tostring(d.note))
        LEADER = true
        d = H.end_turn_diagnosis(0)
        assert(d.leader_view_up == true and not d.note:find("#137", 1, true), "a leader on screen is the explanation itself")
        """)


if __name__ == "__main__":
    unittest.main()
