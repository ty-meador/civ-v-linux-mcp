"""todo_actions: legal actions for many units in one read.

Step 4 of the loop asked `available_unit_actions` once per unit. On the late S1 map (38 units) that was 38
tuner round-trips a turn, most of the ~15 minutes `scripts/play_loop.py` spent on one turn. One query now
answers for every unit that still needs an order (plus the promotion-ready ones), or for the ids given.
"""
import json
import os
import unittest
from unittest import mock

import anyio

import test_mcp_safety as support
from test_set_seat import session
from harness import mcp_server as m
from harness.game import Game


WORLD = """
GameDefines={MOVE_DENOMINATOR=60}
Locale={ConvertTextKey=function(key) return ({TXT_KEY_FORTIFY_HELP='Fortify: +50% defence'})[key] or key end}
GameInfo={Units={[3]={Type='UNIT_WARRIOR'}, [5]={Type='UNIT_WORKER'}}}
GameInfoActions={
  [0]={Type='MISSION_FORTIFY', MissionType=7, CommandType=-1, AutomateType=-1, MissionData=-1, Help='TXT_KEY_FORTIFY_HELP'},
  [1]={Type='MISSION_SKIP', MissionType=8, CommandType=-1, AutomateType=-1, MissionData=-1},
}
local function mk(id, utype, ready, promo, x)
  return {
    GetID=function() return id end, GetUnitType=function() return utype end,
    GetX=function() return x end, GetY=function() return 1 end,
    MovesLeft=function() return ready and 120 or 0 end,
    IsReadyToMove=function() return ready end, IsAutomated=function() return false end,
    IsDelayedDeath=function() return false end, IsPromotionReady=function() return promo end,
    IsCombatUnit=function() return false end,
    CanStartMission=function(self, mid) return mid==7 or (ready and mid==8) end,
  }
end
UNITS={ [11]=mk(11, 3, true, false, 1), [22]=mk(22, 5, false, true, 2), [33]=mk(33, 3, false, false, 3) }
ACTIVE=0
Game.GetActivePlayer=function() return ACTIVE end
Players={[0]={
  GetUnitByID=function(_, id) return UNITS[id] end,
  Units=function() local ids={11,22,33}; local i=0; return function() i=i+1; return UNITS[ids[i]] end end,
  IsTurnActive=function() return true end, GetCurrentResearch=function() return 4 end,
  Cities=function() return function() return nil end end,
  GetTeam=function() return 0 end,
}}
"""


class TodoActionsLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_default_covers_todo_units_and_promotion_ready_ones_without_help(self):
        self.run_lua("""
        local r = H.todo_actions(0, nil, false)
        assert(r.ok == true and r.source == 'todo' and r.n == 2, tostring(r.n))
        -- 11 is ready to move (todo.units); 22 is not ready but has a promotion waiting; 33 is neither.
        assert(r.units[1].id == 11 and r.units[1].type == 'WARRIOR' and r.units[1].promotion_ready == nil)
        assert(r.units[2].id == 22 and r.units[2].type == 'WORKER' and r.units[2].promotion_ready == true)
        assert(#r.units[1].actions == 2 and r.units[1].actions[1].type == 'MISSION_FORTIFY')
        for _, u in ipairs(r.units) do for _, a in ipairs(u.actions) do assert(a.help == nil, 'help kept') end end
        assert(r.units[1].moves == 2 and r.units[1].x == 1)
        """)

    def test_full_keeps_only_the_computed_button_line(self):
        """v216: the standing sentence under a button is static and lives in reference("actions"); even
        `full` does not repeat it. Only the per-unit computed lines (upgrade price, scrap gold) remain."""
        self.run_lua("""
        local r = H.todo_actions(0, nil, true)
        assert(r.units[1].actions[1].type == 'MISSION_FORTIFY' and r.units[1].actions[1].help == nil,
               tostring(r.units[1].actions[1].help))
        local ref = H.reference('actions')
        assert(ref.ok and #ref.rows == 1 and ref.rows[1].type == 'MISSION_FORTIFY', tostring(#ref.rows))
        assert(ref.rows[1].help == 'Fortify: +50% defence' and ref.rows[1].kind == 'mission', tostring(ref.rows[1].help))
        """)

    def test_explicit_ids_keep_their_order_and_name_a_missing_unit(self):
        self.run_lua("""
        local r = H.todo_actions(0, {33, 99, 11}, false)
        assert(r.ok == true and r.source == 'ids' and r.n == 3)
        assert(r.units[1].id == 33 and r.units[1].ok == true and #r.units[1].actions == 1)
        assert(r.units[2].id == 99 and r.units[2].ok == false and r.units[2].err == 'no such unit')
        assert(r.units[3].id == 11 and r.units[3].ok == true)
        """)

    def test_inactive_seat_is_refused_unless_ids_are_given(self):
        self.run_lua("""
        ACTIVE=1
        local r = H.todo_actions(0, nil, false)
        assert(r.ok == false and r.err:find('unit_ids'), tostring(r.err))
        local r2 = H.todo_actions(0, {11}, false)
        assert(r2.ok == true and r2.n == 1)
        """)


class TodoActionsQueryTests(unittest.TestCase):
    def test_game_formats_ids_as_a_lua_list_and_nil_when_empty(self):
        g = Game.__new__(Game)
        g.seat = 0
        seen = []
        g.q = lambda code, timeout=None: seen.append((code, timeout)) or {"ok": True}
        g.todo_actions()
        g.todo_actions([5, 7], full=True)
        self.assertEqual(seen[0][0], "return H.todo_actions(0, nil, false)")
        self.assertEqual(seen[1][0], "return H.todo_actions(0, {5,7}, true)")
        self.assertGreaterEqual(seen[0][1], 120, "a whole turn's units in one query needs a long timeout")


class FakeGame:
    seat = 0

    def has_state(self, name):
        return True

    def mode(self):
        return "single"

    def turn_state(self, pid=None):
        return {"turn": 270, "active_player": 0, "my_turn": True, "processing": False, "paused": False,
                "hotseat": False, "mode": "single", "blocking_name": "ENDTURN_BLOCKING_UNITS", "todo": {},
                "pending_popups": []}

    def discussion_pending(self):
        return False

    def todo_actions(self, unit_ids=None, full=False):
        self.args = (unit_ids, full)
        return {"ok": True, "source": "ids" if unit_ids else "todo", "n": 1, "units": [{"id": 11, "ok": True}]}


class TodoActionsToolTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeGame()
        self.patches = [mock.patch.object(m, "game", lambda: self.fake),
                        mock.patch.dict(os.environ, {"CIV5_TUNERD_SOCK": "/tmp/civ5-test-todo.sock", "CIV5_SEAT": "0"}),
                        mock.patch.object(m, "_seat_rechecked", True),
                        mock.patch.dict(m._RECENT, {}, clear=True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_tool_passes_ids_and_full_through_and_runs_inside_do(self):
        out, batch = anyio.run(session, [("todo_actions", {"unit_ids": [11], "full": True}),
                                         ("do", {"actions": [{"tool": "todo_actions", "args": {}}]})])
        self.assertTrue(out["ok"])
        self.assertEqual(out["units"][0]["id"], 11)
        self.assertEqual(batch["results"][0]["result"]["source"], "todo")
        self.assertNotIn("todo_actions", m.BATCH_EXCLUDED)

    def test_empty_list_means_the_todo_list(self):
        (out,) = anyio.run(session, [("todo_actions", {"unit_ids": []})])
        self.assertEqual(self.fake.args, (None, False))
        self.assertEqual(out["source"], "todo")
