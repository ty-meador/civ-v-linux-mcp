"""turn_status and unit_mission must agree about which units block the turn.

A multi-turn move pushed from Lua does not resume at the next turn start: the unit sits in
ACTIVITY_MISSION with moves still in hand and the engine will not spend them. todo() calls that
"stalled_mission" and lists the unit as blocking; the MISSION_SKIP guard called the same state
"already on a multi-turn move and does not block end_turn" and refused.

Live t186 (Shoshone vs the Inca): Great General 335877 at (49,20), 0.33 moves, listed in
turn_status.todo.units with stalled_mission=true under blocking_name ENDTURN_BLOCKING_UNITS, while
unit_mission(MISSION_SKIP) refused it as not blocking. Both cannot be true, and the pair deadlocks
the turn. A human at that screen presses Space.
"""
import unittest

import test_mcp_safety as support


WORLD = """
ActivityTypes={ACTIVITY_MISSION=6,ACTIVITY_AWAKE=1}

-- A unit knob-set: activity, moves and build state are what the two callers disagreed about.
function make_unit(o)
  return {
    GetActivityType=function() return o.activity or 1 end,
    MovesLeft=function() return o.moves or 0 end,
    GetBuildType=function() return o.build or -1 end,
  }
end
"""


class StalledMissionTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_a_queued_move_with_moves_left_is_stalled(self):
        self.run_lua("""
        assert(H.is_stalled_mission(make_unit{activity=6, moves=60}) == true)
        """)

    def test_a_unit_that_spent_its_moves_walking_is_not_stalled(self):
        """It really is mid-path and really does not block the turn -- the case the guard exists for
        (live t306: a Caravel's standing order died to a reflex MISSION_SKIP)."""
        self.run_lua("""
        assert(H.is_stalled_mission(make_unit{activity=6, moves=0}) == false)
        """)

    def test_a_worker_mid_build_idles_at_full_moves_but_is_not_stalled(self):
        self.run_lua("""
        assert(H.is_stalled_mission(make_unit{activity=6, moves=120, build=7}) == false)
        """)

    def test_an_awake_unit_is_not_stalled(self):
        self.run_lua("""
        assert(H.is_stalled_mission(make_unit{activity=1, moves=120}) == false)
        assert(H.is_stalled_mission(nil) == false)
        assert(H.is_stalled_mission({}) == false)
        """)

    def test_todo_and_the_skip_guard_ask_the_same_question(self):
        """They used to carry separate copies of the rule -- todo() with the literal activity 6 plus
        moves and build checks, the guard with ActivityTypes.ACTIVITY_MISSION and neither -- which is
        how they drifted apart. Neither may test the activity itself again."""
        source = open("harness/lua/runtime.lua").read()
        todo = source[source.index("function H.todo("):]
        todo = todo[:todo.index("\nend\n")]
        guard = source[source.index('if mission == "MISSION_SKIP" then'):]
        guard = guard[:guard.index("H.pending_moves[unit_id] = nil", guard.index("return { ok = false"))]

        for name, body in (("todo", todo), ("the MISSION_SKIP guard", guard)):
            self.assertIn("H.is_stalled_mission(", body, f"{name} should ask the shared predicate")
        self.assertNotIn("GetActivityType", todo, "todo re-implements the stalled test instead of asking")


if __name__ == "__main__":
    unittest.main()
