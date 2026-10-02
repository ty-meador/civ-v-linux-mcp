"""GitLab #23: ENDTURN_BLOCKING_UNITS with an empty todo is a stale reading, not a unit.

The engine does not re-evaluate GetEndTurnBlockingType while a popup is up (UI.IsPopupUp()). When
the last ready unit's order also raises an announcement -- a city-state met on the way, a natural
wonder found -- the blocker stays UNITS with HasReadyUnit() false and nothing in todo.units, for as
long as the popup lasts. Reproduced live t215 (Persia, Infantry 32771 walking toward Melbourne past
a natural wonder): blocking UNITS, has_ready false, todo empty, popup_up true; the old refusal read
"every unit in todo.units still has moves" over an empty list, and finish_turn gave up on it.

turn_status now says so (blocking_stale, the true hint), _end_turn_send treats the popup as the
blocker, and the sweep processes a popup the engine waits on that nothing draws.
"""
import unittest

import test_mcp_safety as support
from harness.game import Game


WORLD = """
EndTurnBlockingTypes = {NO_ENDTURN_BLOCKING_TYPE=-1, ENDTURN_BLOCKING_UNITS=5, ENDTURN_BLOCKING_POLICY=1}
UI = {IsPopupUp=function() return POPUP_UP end}
P = {HasReadyUnit=function() return READY end}
"""


class StaleUnitsBlockerLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_units_blocker_with_no_ready_unit_and_empty_todo_is_stale(self):
        self.run_lua("""
        POPUP_UP = true; READY = false
        local hint = H.stale_units_blocker(P, 5, {units={}})
        assert(type(hint) == "string", "expected the stale hint")
        assert(hint:find("stale", 1, true), hint)
        assert(hint:find("UI.IsPopupUp() is true", 1, true), hint)
        assert(not hint:find("every unit in todo.units", 1, true), hint)
        """)

    def test_the_hint_does_not_claim_a_popup_it_cannot_see(self):
        self.run_lua("""
        POPUP_UP = false; READY = false
        local hint = H.stale_units_blocker(P, 5, {units={}})
        assert(hint and not hint:find("IsPopupUp() is true", 1, true), tostring(hint))
        """)

    def test_a_unit_in_todo_is_a_real_blocker(self):
        self.run_lua("""
        POPUP_UP = true; READY = false
        assert(H.stale_units_blocker(P, 5, {units={{id=1}}}) == nil, "a stalled unit listed in todo blocks for real")
        READY = true
        assert(H.stale_units_blocker(P, 5, {units={}}) == nil, "HasReadyUnit true is a real blocker")
        """)

    def test_other_blockers_and_no_blocker_are_never_stale(self):
        self.run_lua("""
        POPUP_UP = true; READY = false
        assert(H.stale_units_blocker(P, -1, {units={}}) == nil)
        assert(H.stale_units_blocker(P, 1, {units={}}) == nil)
        assert(H.stale_units_blocker(P, 5, nil) == nil, "no todo (not my turn) is not a stale reading")
        """)


class StaleBlockerLuaTests(unittest.TestCase):
    """v254: the same frozen reading for PRODUCTION and RESEARCH (live t153, Mongolia: the Great Work splash
    froze ENDTURN_BLOCKING_PRODUCTION on a notification set_production had already expired; todo.cities was
    empty and end_turn refused before its popup sweep)."""
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)
        self.run_lua("EndTurnBlockingTypes.ENDTURN_BLOCKING_PRODUCTION = 2; EndTurnBlockingTypes.ENDTURN_BLOCKING_RESEARCH = 3")

    def test_production_with_no_empty_city_is_stale_and_names_the_popup(self):
        self.run_lua("""
        POPUP_UP = true; READY = false
        local hint = H.stale_blocker(P, 2, {units={}, cities={}, research_unset=false})
        assert(type(hint) == "string" and hint:find("ENDTURN_BLOCKING_PRODUCTION is a stale reading", 1, true), tostring(hint))
        assert(hint:find("todo.cities is empty", 1, true) and hint:find("UI.IsPopupUp() is true", 1, true), hint)
        POPUP_UP = false
        hint = H.stale_blocker(P, 2, {units={}, cities={}, research_unset=false})
        assert(hint and not hint:find("IsPopupUp() is true", 1, true), tostring(hint))
        """)

    def test_a_city_in_todo_or_research_unset_is_a_real_blocker(self):
        self.run_lua("""
        POPUP_UP = true; READY = false
        assert(H.stale_blocker(P, 2, {units={}, cities={{id=8192}}, research_unset=false}) == nil, "an empty city blocks for real")
        assert(H.stale_blocker(P, 3, {units={}, cities={}, research_unset=true}) == nil, "research unset blocks for real")
        local hint = H.stale_blocker(P, 3, {units={}, cities={}, research_unset=false})
        assert(hint and hint:find("ENDTURN_BLOCKING_RESEARCH is a stale reading", 1, true), tostring(hint))
        """)

    def test_units_policy_and_no_blocker_keep_their_old_answers(self):
        self.run_lua("""
        POPUP_UP = true; READY = false
        local hint = H.stale_blocker(P, 5, {units={}, cities={}})
        assert(hint and hint:find("ENDTURN_BLOCKING_UNITS is a stale", 1, true), tostring(hint))
        assert(H.stale_blocker(P, 5, {units={{id=1}}, cities={}}) == nil)
        assert(H.stale_blocker(P, 1, {units={}, cities={}, research_unset=false}) == nil, "a policy to pick is never stale")
        assert(H.stale_blocker(P, -1, {units={}, cities={}}) == nil)
        assert(H.stale_blocker(P, 2, nil) == nil, "no todo (not my turn) is not a stale reading")
        """)


class OrphanedPopupTests(unittest.TestCase):
    """The sweep closes visible screens; a popup the engine waits on with no screen drawn gets its
    Processed event instead -- and only then."""

    class FakeGame(Game):
        def __init__(self, pending, popup_up=True, visible=False, leader=False, ctx_present=True):
            self.seat = 0
            self._pending = pending
            self._popup_up = popup_up
            self._visible = visible
            self._leader = leader
            self._ctx_present = ctx_present
            self.processed = []
            self.cleared = []
            self.c = self

        # Game surface
        def turn_state(self, pid=None):
            return {"pending_popups": self._pending}

        def q(self, lua, *a, **kw):
            if "UI.IsPopupUp" in lua:
                return self._popup_up
            if "H.popups[" in lua:
                self.cleared.append(lua)
                return True
            if "PopupProcessed" in lua:
                self.processed.append(("InGame", lua))
                return True
            return None

        def _screens(self):
            # v214: one H.modal_flags read answers the leader flags and every screen's up/down
            return {"leader_greeting_pending": self._leader, "discussion_pending": False,
                    "screens": {"CityStateGreetingPopup": self._visible} if self._ctx_present else {}}

        def states(self):
            return {1: "CityStateGreetingPopup", 2: "TextPopup"} if self._ctx_present else {2: "TextPopup"}

        # tuner client surface (self.c)
        def query(self, state, lua, **kw):
            return self._visible if "IsHidden" in lua else None

        def exec(self, state, lua, **kw):
            self.processed.append((state, lua))
            return []

    GREETING = [{"type": 61, "name": "BUTTONPOPUP_CITY_STATE_GREETING", "data1": 22}]

    def test_a_hidden_popup_the_engine_waits_on_is_processed_in_its_own_context(self):
        g = self.FakeGame(self.GREETING)
        out = Game._process_orphaned_popups(g, {"CityStateGreetingPopup": "OnCloseButtonClicked"})
        self.assertEqual(len(out), 1)
        self.assertIn("orphaned", out[0])
        self.assertEqual(g.processed[0][0], "CityStateGreetingPopup")
        self.assertIn("SerialEventGameMessagePopupProcessed.CallImmediate(61, 0)", g.processed[0][1])
        self.assertIn("DequeuePopup", g.processed[0][1])
        self.assertEqual(len(g.cleared), 1)

    def test_a_visible_screen_is_the_sweeps_job_not_this(self):
        g = self.FakeGame(self.GREETING, visible=True)
        self.assertEqual(Game._process_orphaned_popups(g, {"CityStateGreetingPopup": "OnCloseButtonClicked"}), [])
        self.assertEqual(g.processed, [])

    def test_nothing_happens_when_the_engine_is_not_waiting(self):
        g = self.FakeGame(self.GREETING, popup_up=False)
        self.assertEqual(Game._process_orphaned_popups(g, {}), [])
        self.assertEqual(g.processed, [])

    def test_a_leader_screen_means_the_popup_is_merely_queued(self):
        g = self.FakeGame(self.GREETING, leader=True)
        self.assertEqual(Game._process_orphaned_popups(g, {}), [])

    def test_a_decision_popup_is_never_processed_blind(self):
        g = self.FakeGame([{"type": 7, "name": "BUTTONPOPUP_DECLAREWARMOVE"}])
        self.assertEqual(Game._process_orphaned_popups(g, {}), [])
        self.assertEqual(g.processed, [])

    def test_without_the_context_state_the_event_goes_through_ingame(self):
        g = self.FakeGame(self.GREETING, ctx_present=False)
        out = Game._process_orphaned_popups(g, {})
        self.assertEqual(len(out), 1)
        self.assertEqual(g.processed[0][0], "InGame")
        self.assertNotIn("DequeuePopup", g.processed[0][1])


if __name__ == "__main__":
    unittest.main()
