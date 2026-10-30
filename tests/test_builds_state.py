"""A plot build's state is read from one place: the panel's turn count, the dig from the plot (GitLab #165, #140),
and a unit that completed is not a drop (#141).

#165 (Grok, hotseat seat 1 t28): starting a camp answered turns_left 3 while the worker row said build_turns_left
4 the same second; the row is the stock unit panel's "(4)" and counts down, so the order was one short.
#140 (Maya t218-t235): an Archaeologist's dig keeps the unit's GetBuildType at -1 while the plot carries the
build; build_check called the dig refused, completed (the Trading Post under it had vanished) and, when the
dig consumed the unit, the order failed as unit_gone.
#141 (Maya t232): a Caravan completed with no route slot left reads CanTrain false the same turn, and the
queue watch called it dropped.
"""
import unittest

import test_mcp_safety as support
from harness import orders as O

WORLD = """
GameInfoTypes = { MISSION_BUILD = 5 }
MissionTypes = GameInfoTypes
GameInfo = { Builds = { [9] = { Type = 'BUILD_FARM', ID = 9 }, [12] = { Type = 'BUILD_ARCHAEOLOGY_DIG', ID = 12 } },
             Improvements = { [3] = { Type = 'IMPROVEMENT_TRADING_POST' } },
             Units = { [1] = { Type = 'UNIT_ARCHAEOLOGIST', Class = 'UNITCLASS_ARCHAEOLOGIST' }, [2] = { Type = 'UNIT_WORKER', Class = 'UNITCLASS_WORKER' } },
             Resources = { [5] = { Type = 'RESOURCE_ARTIFACTS' }, [6] = { Type = 'RESOURCE_WHEAT' } } }
setmetatable(GameInfo.Builds, { __call = function(t) local i = 0; local keys = { 9, 12 }
  return function() i = i + 1; local k = keys[i]; return k and t[k] or nil end end })
progress = {}          -- build id -> progress on the plot
turns_left = {}        -- build id -> the engine's raw GetBuildTurnsLeft
improvement = -1
function plot(x, y)
  return { GetX = function() return x end, GetY = function() return y end,
           GetBuildProgress = function(_, b) return progress[b] or 0 end,
           GetBuildTurnsLeft = function(_, b, pid) return turns_left[b] or 4001 end,
           GetImprovementType = function() return improvement end,
           IsImprovementPillaged = function() return false end,
           GetRouteType = function() return -1 end, IsRoutePillaged = function() return false end,
           GetFeatureType = function() return -1 end, GetOwner = function() return 0 end,
           IsRevealed = function() return true end, IsVisible = function() return true end,
           GetResourceType = function() return resource_at[x .. ',' .. y] or -1 end }
end
resource_at = {}
unit_buildtype, unit_mission, unit_type = -1, -1, 1
unit = { GetBuildType = function() return unit_buildtype end, GetMissionType = function() return unit_mission end,
         GetPlot = function() return plot(5, 5) end, GetX = function() return 5 end, GetY = function() return 5 end,
         MovesLeft = function() return 0 end, GetUnitType = function() return unit_type end }
Players = { [0] = { GetUnitByID = function() return unit end, GetTeam = function() return 0 end } }
Teams = { [0] = { GetLeaderID = function() return 0 end } }
Map = { GetPlot = function(x, y) return plot(x, y) end, GetNumPlots = function() return 4 end,
        GetPlotByIndex = function(i) return plot(i, 5) end,
        PlotDistance = function(x1, y1, x2, y2) return math.max(math.abs(x1 - x2), math.abs(y1 - y2)) end }
GameDefines = { MOVE_DENOMINATOR = 60 }
"""


class BuildStateLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_the_turn_count_is_the_unit_panels_everywhere(self):
        self.run_lua("""
        turns_left[9] = 3
        assert(H.build_turns_left(plot(5, 5), 9, 0) == 4, 'GetBuildTurnsLeft + 1, as unitpanel.lua prints it')
        assert(H.build_turns_left(plot(5, 5), 12, 0) == nil, '4000+ is the engine\\'s never')
        unit_buildtype = 9
        local b = H.unit_build(unit, 0)
        assert(b.build == 'BUILD_FARM' and b.turns_left == 4 and b.from_plot == nil, H.json(b))
        local c = H.build_check(1, 5, 5, { imp = -1, pillaged = false, route = -1, route_pillaged = false, feature = -1 }, 0)
        assert(c.started == true and c.turns_left == 4, H.json(c))
        """)

    def test_a_dig_is_read_from_the_plot_and_is_not_completed_by_the_improvement_it_cleared(self):
        self.run_lua("""
        -- the dig started: the unit's build type stays -1, its mission is MISSION_BUILD, the plot carries the build
        unit_buildtype, unit_mission = -1, 5
        progress[12], turns_left[12] = 100, 3
        improvement = -1   -- the Trading Post that stood there is gone
        local b = H.unit_build(unit, 0)
        assert(b and b.build == 'BUILD_ARCHAEOLOGY_DIG' and b.turns_left == 4 and b.from_plot == true, H.json(b))
        local before = { imp = 3, pillaged = false, route = -1, route_pillaged = false, feature = -1 }
        local c = H.build_check(1, 5, 5, before, 0)
        assert(c.started == true and c.completed == false, H.json(c))
        assert(c.build == 'BUILD_ARCHAEOLOGY_DIG' and c.turns_left == 4 and c.from_plot == true, H.json(c))
        assert(c.replaced_improvement == 'TRADING_POST', H.json(c))
        -- a unit standing on someone else's running build is not building it
        unit_mission = -1
        assert(H.unit_build(unit, 0) == nil, 'no mission, no build')
        -- a plain Worker whose farm is done: the plot changed and nothing runs on it
        progress[12] = 0
        improvement = 3
        c = H.build_check(1, 5, 5, { imp = -1, pillaged = false, route = -1, route_pillaged = false, feature = -1 }, 0)
        assert(c.started == false and c.completed == true, H.json(c))
        """)

    def test_an_archaeologist_sees_its_dig_sites_nearest_first(self):
        self.run_lua("""
        resource_at['0,5'], resource_at['3,5'], resource_at['1,5'] = 5, 5, 6
        H.owner_label = function(owner) return 'me' end
        local r = H.dig_sites(unit, 0)
        assert(r and r.sites_total == 2 and #r.sites == 2, H.json(r))
        assert(r.sites[1].x == 3 and r.sites[1].distance == 2 and r.sites[2].x == 0 and r.sites[2].distance == 5, H.json(r))
        assert(r.sites[1].owner == 'me' and r.sites[1].resource == 'RESOURCE_ARTIFACTS', H.json(r))
        assert(r.hint:find('BUILD_ARCHAEOLOGY_DIG', 1, true))
        unit_type = 2
        assert(H.dig_sites(unit, 0) == nil, 'a Worker has no dig sites')
        """)

    def test_the_todo_names_a_completed_dig_waiting_on_its_choice(self):
        self.run_lua("""
        Game.GetActivePlayer = function() return 0 end
        local p = Players[0]
        p.IsTurnActive = function() return true end
        p.GetCurrentResearch = function() return 3 end
        p.Units = function() return function() return nil end end
        p.Cities = function() return function() return nil end end
        p.GetNextDigCompletePlot = function() return plot(7, 8) end
        local t = H.todo(0)
        assert(t.dig_choice and t.dig_choice.x == 7 and t.dig_choice.y == 8, H.json(t))
        assert(t.dig_choice.hint:find('question()', 1, true))
        p.GetNextDigCompletePlot = function() return nil end
        assert(H.todo(0).dig_choice == nil, 'no completed dig, no row')
        """)


QUEUE_WORLD = """
GameInfo = GameInfo or {}
GameInfo.Buildings = {}
GameInfo.Units = { UNIT_CARAVAN = { ID = 7 } }
GameInfo.Projects = {}
Teams = { [0] = { GetProjectCount = function() return 0 end } }
RECORDED = {}
H.record = function(kind, data, audience) RECORDED[#RECORDED + 1] = { kind = kind, data = data, audience = audience } end
QUEUES = {}
H.queue_items = function(city) return QUEUES[city:GetID()] or {} end
UNITS = {}
Game.GetGameTurn = function() return 232 end
Map = { PlotDistance = function(x1, y1, x2, y2) return math.max(math.abs(x1 - x2), math.abs(y1 - y2)) end }
function city(id, name)
  return { GetID = function() return id end, GetName = function() return name end, GetTeam = function() return 0 end,
           GetOwner = function() return 0 end, GetX = function() return 10 end, GetY = function() return 10 end,
           IsHasBuilding = function() return false end, CanConstruct = function() return true end,
           CanTrain = function() return false end, CanCreate = function() return true end }
end
function unit(utype, created, x, y)
  return { GetUnitType = function() return utype end, GetGameTurnCreated = function() return created end,
           GetX = function() return x end, GetY = function() return y end }
end
CITIES = {}
Players = { [0] = { Cities = function() local i = 0; return function() i = i + 1; return CITIES[i] end end,
                    Units = function() local i = 0; return function() i = i + 1; return UNITS[i] end end } }
"""


class QueueWatchCompletionTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(QUEUE_WORLD)

    def test_a_caravan_that_completed_with_no_route_slot_left_is_not_a_drop(self):
        self.run_lua("""
        CITIES = { city(1, 'Uxmal') }
        QUEUES = { [1] = { 'UNIT_CARAVAN', 'BUILDING_FACTORY' } }
        H.queue_snapshot(0)
        QUEUES = { [1] = { 'BUILDING_FACTORY' } }
        UNITS = { unit(7, 232, 10, 10) }       -- the Caravan stands in Uxmal, born this turn
        H.queue_compare(0)
        assert(#RECORDED == 0, H.json(RECORDED))
        """)

    def test_a_unit_gone_from_the_queue_with_no_new_unit_is_still_a_drop(self):
        self.run_lua("""
        CITIES = { city(1, 'Uxmal') }
        QUEUES = { [1] = { 'UNIT_CARAVAN' } }
        H.queue_snapshot(0)
        QUEUES = { [1] = {} }
        UNITS = { unit(7, 230, 10, 10) }       -- an older Caravan: not this turn's
        H.queue_compare(0)
        assert(#RECORDED == 1 and RECORDED[1].data.item == 'UNIT_CARAVAN', H.json(RECORDED))
        """)


class ConsumedByItsBuildTests(unittest.TestCase):
    def _order(self, state):
        return {"id": 10, "unit": {"id": 44, "type": "ARCHAEOLOGIST"}, "step": 0, "state": state,
                "steps": [{"kind": "build", "build": "BUILD_ARCHAEOLOGY_DIG", "x": 38, "y": 57}]}

    def test_a_dig_whose_archaeologist_is_gone_completes(self):
        facts = {"units": {"44": {"missing": True}},
                 "builds": {"44:BUILD_ARCHAEOLOGY_DIG": {"known": True, "consumes_unit": True, "done": False}}}
        d = O.decide(self._order("building"), facts, 235)
        self.assertEqual(d["do"], "complete")
        self.assertIn("consumed building it", d["note"])

    def test_a_worker_killed_mid_farm_still_fails(self):
        facts = {"units": {"44": {"missing": True}}, "builds": {"44:BUILD_ARCHAEOLOGY_DIG": {"known": True, "done": False}}}
        d = O.decide(self._order("building"), facts, 235)
        self.assertEqual((d["do"], d["kind"]), ("fail", "unit_gone"))
        d = O.decide(self._order("moving"), {**facts, "builds": {"44:BUILD_ARCHAEOLOGY_DIG": {"consumes_unit": True}}}, 235)
        self.assertEqual(d["do"], "fail", "gone before it was ever seen building: not completed")


if __name__ == "__main__":
    unittest.main()


class DigChoiceSurfaceTests(unittest.TestCase):
    def test_the_briefing_lists_a_completed_dig_as_a_decision(self):
        from harness import briefing as B
        ts = {"turn": 221, "blocking_name": "ENDTURN_BLOCKING_PRODUCTION",
              "todo": {"units": [], "cities": [], "promotions": [], "dig_choice": {"x": 34, "y": 58, "hint": "question()"}}}
        rows = [r for r in B.decisions(ts, []) if r["kind"] == "dig_choice"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["detail"]["x"], 34)
        self.assertEqual([a["tool"] for a in rows[0]["actions"]], ["question", "answer"])
        ts["blocking_name"] = "ENDTURN_BLOCKING_CHOOSE_ARCHAEOLOGY"
        kinds = [r["kind"] for r in B.decisions(ts, [])]
        self.assertEqual(kinds.count("dig_choice"), 1, "the engine's blocker names the same decision, not a second row")
        self.assertNotIn("blocker", kinds)

    def test_the_dig_answer_names_the_great_work_it_made(self):
        from unittest.mock import patch
        from harness.game import Game
        g = Game.__new__(Game)
        g.seat = 0
        g._pid = lambda pid=None: 0
        g.h = Game.h.__get__(g)
        works = [{}, {"1": {"work_id": 1, "name": "Baetylus of Palenque", "city": "Tikal", "city_id": 9, "building": "BUILDING_MUSEUM", "slot": 0}}]
        pending = [True, True, False]

        def q(call, timeout=None):
            if call.fn == "archaeology_options":
                return {"ok": True, "pending": pending.pop(0), "x": 34, "y": 58, "unit_id": 5, "name": "Baetylus of Palenque",
                        "artifact": "ARTIFACT_ANCIENT_RUIN", "era": "ERA_ANCIENT", "options": [{"choice": 1}, {"choice": 2}]}
            if call.fn == "great_work_index":
                return works.pop(0)
            if call.fn == "choose_archaeology":
                return {"ok": True, "choice": 2, "x": 34, "y": 58}
            return True
        g.q = q
        g._visible_in_state = lambda *a, **k: False
        with patch("harness.game.time.sleep", lambda s: None):
            r = g.choose_archaeology(2, 34, 58)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["great_work"]["city"], "Tikal")
        self.assertEqual(r["great_work"]["building"], "BUILDING_MUSEUM")
        self.assertIn("Tikal's BUILDING_MUSEUM", r["outcome"])
        self.assertEqual(r["find"]["name"], "Baetylus of Palenque")
