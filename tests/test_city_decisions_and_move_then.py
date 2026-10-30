"""City decisions are todo rows (GitLab #101) and "go there and hold" is one order (GitLab #105).

Maya t24-t100: a starving city and a city that could fire were notification text only; t54-t64: every move that
arrived with moves left needed a second fortify row, and a fortify at 0 moves was a one-turn HOLD the engine forgot.
"""
import unittest

import test_mcp_safety as support
from harness.briefing import decisions
from harness.game import Game


class CityTodoLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)

    def test_a_starving_city_and_a_city_that_can_fire_are_todo_rows(self):
        self.run_lua("""
        local function city(id, name, food, can_fire)
          return { GetID = function() return id end, GetName = function() return name end,
                   GetProductionNameKey = function() return 'TXT_KEY_X' end,
                   FoodDifference = function() return food end,
                   CanRangeStrikeNow = function() return can_fire end }
        end
        local cities = { city(8192, 'Palenque', -3, false), city(16385, 'Tikal', 2, true), city(24578, 'Uxmal', 1, false) }
        Game.GetActivePlayer = function() return 0 end
        Players = { [0] = { IsTurnActive = function() return true end, GetCurrentResearch = function() return 4 end,
                            Units = function() return function() return nil end end,
                            Cities = function() local i = 0; return function() i = i + 1; return cities[i] end end,
                            GetTeam = function() return 0 end, GetEndTurnBlockingType = function() return -1 end } }
        H.incoming_deal = function() return nil end
        H.religion_choice = function() return nil end
        H.production_is_automated = function() return false end
        H.steal_tech_options = function() return { n = 0 } end
        H.available_city_strikes = function(cid) if cid == 16385 then return { ok = true, can = true, targets = { { x = 1, y = 1 }, { x = 2, y = 2 } } } end return { ok = true, can = false, targets = {} } end
        local t = H.todo(0)
        assert(#t.starving == 1 and t.starving[1].name == 'Palenque' and t.starving[1].food_surplus == -3, H.json(t.starving))
        assert(t.starving[1].hint:find("action='governor'", 1, true), t.starving[1].hint)
        assert(#t.city_strikes == 1 and t.city_strikes[1].name == 'Tikal' and t.city_strikes[1].targets == 2, H.json(t.city_strikes))
        assert(#t.cities == 0, 'production is set everywhere')
        """)


class CityDecisionRowsTests(unittest.TestCase):
    def test_the_rows_carry_the_reads_and_the_orders(self):
        ts = {"todo": {"units": [], "cities": [], "starving": [{"id": 8192, "name": "Palenque", "food_surplus": -3}],
                       "city_strikes": [{"id": 16385, "name": "Tikal", "targets": 1}]},
              "blocking_name": "ENDTURN_BLOCKING_CITY_RANGE_ATTACK", "blocking_hint": "x", "pending_popups": []}
        rows = decisions(ts, [])
        kinds = [r["kind"] for r in rows]
        self.assertEqual(kinds, ["starving", "city_strike"], "the blocker the strike row covers is not repeated")
        starving = rows[0]
        self.assertEqual([a["tool"] for a in starving["actions"]], ["state", "order", "order"])
        self.assertEqual(starving["actions"][1]["args"]["args"], {"focus": "food"})
        self.assertEqual(starving["actions"][2]["choose"], ["x", "y"])
        strike = rows[1]
        self.assertEqual((strike["actions"][0]["args"]["view"], strike["actions"][1]["args"]["action"]), ("strikes", "strike"))


class HoldAfterMoveLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua("""
        GameDefines = { MOVE_DENOMINATOR = 60 }
        ORDERS = {}
        H.unit_mission = function(id, mission, x, y, build, pid)
          ORDERS[#ORDERS + 1] = mission
          if mission == 'MISSION_FORTIFY' and CANNOT_FORTIFY then return { ok = false, err = 'action is not currently legal' } end
          return { ok = true }
        end
        CANNOT_FORTIFY = false
        local function mk(id, x, y)
          return { GetID = function() return id end, GetX = function() return x end, GetY = function() return y end,
                   MovesLeft = function() return 120 end, MaxMoves = function() return 120 end,
                   IsDelayedDeath = function() return false end, IsCombatUnit = function() return true end,
                   GetBuildType = function() return -1 end }
        end
        UNITS = { [1] = mk(1, 5, 5), [2] = mk(2, 7, 7) }
        Players = { [0] = { GetUnitByID = function(_, id) return UNITS[id] end } }
        H.pending_moves = {}
        """)

    def test_the_hold_lands_when_the_standing_move_arrives(self):
        self.run_lua("""
        H.pending_moves[H.pm_key(1, 0)] = { x = 5, y = 5, pid = 0, unit_id = 1, then_mission = 'fortify' }
        local out = H.resume_moves(0)
        assert(#out == 1 and out[1].arrived == true and out[1].held == 'MISSION_FORTIFY' and out[1].hold_ok == true, H.json(out))
        assert(ORDERS[1] == 'MISSION_FORTIFY' and H.pending_moves[H.pm_key(1, 0)] == nil, H.json(ORDERS))
        """)

    def test_a_unit_that_cannot_fortify_sleeps_instead(self):
        self.run_lua("""
        CANNOT_FORTIFY = true
        local r = H.hold_unit(UNITS[2], 'hold', 0)
        assert(r.ok == true and r.mission == 'MISSION_SLEEP' and r.swapped_from == 'MISSION_FORTIFY', H.json(r))
        assert(ORDERS[1] == 'MISSION_FORTIFY' and ORDERS[2] == 'MISSION_SLEEP', H.json(ORDERS))
        """)

    def test_set_pending_then_records_a_hold_for_a_unit_already_there(self):
        self.run_lua("""
        local r = H.set_pending_then(2, 'sleep', 0)
        assert(r.ok and r.x == 7 and r.y == 7 and r.then_mission == 'sleep', H.json(r))
        local pm = H.pending_moves[H.pm_key(2, 0)]
        assert(pm and pm.x == 7 and pm.then_mission == 'sleep', 'a record at the unit plot: the next turn start gives the hold')
        local out = H.resume_moves(0)
        assert(#out == 1 and out[1].held == 'MISSION_SLEEP', H.json(out))
        """)


class MoveThenTests(unittest.TestCase):
    def _game(self, move_result):
        g = Game.__new__(Game)
        g.seat = 0
        g._pid = lambda pid=None: 0
        g.h = Game.h.__get__(g)
        calls = []
        g._with_attack_result = lambda uid, x, y, act, pid=None: dict(move_result)
        g.unit_mission = lambda uid, mission, x=-1, y=-1, data2=0, build=None, pid=None: calls.append(mission) or {"ok": True}
        g.q = lambda call, timeout=None: calls.append(call.fn) or {"ok": True, "then_mission": call.args[1]}
        return g, calls

    def test_arrived_with_moves_left_holds_now(self):
        g, calls = self._game({"ok": True, "x": 5, "y": 5, "moves": 1, "arrived": True})
        r = g.move_unit(7, 5, 5, then="fortify")
        self.assertEqual(r["then"], {"mission": "MISSION_FORTIFY", "ok": True, "when": "now"})
        self.assertEqual(calls, ["MISSION_FORTIFY"])

    def test_a_queued_move_records_the_hold_for_the_arrival(self):
        g, calls = self._game({"ok": True, "x": 4, "y": 5, "moves": 0, "queued": True, "arrived": False})
        r = g.move_unit(7, 9, 9, then="hold")
        self.assertTrue(r["then"]["ok"])
        self.assertIn("on arrival", r["then"]["when"])
        self.assertEqual(calls, ["set_pending_then"])

    def test_arrived_with_no_moves_waits_for_the_turn_start(self):
        g, calls = self._game({"ok": True, "x": 5, "y": 5, "moves": 0, "arrived": True})
        r = g.move_unit(7, 5, 5, then="sleep")
        self.assertIn("next turn start", r["then"]["when"])
        self.assertEqual(calls, ["set_pending_then"])

    def test_a_bad_then_and_a_plain_move(self):
        g, calls = self._game({"ok": True, "x": 5, "y": 5, "moves": 1, "arrived": True})
        self.assertIn("then must be one of", g.move_unit(7, 5, 5, then="dance")["err"])
        self.assertNotIn("then", g.move_unit(7, 5, 5))
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
