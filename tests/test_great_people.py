"""A Great Person's withheld missions are explained, a gift names its recipient, a concert tour says what it did.

GitLab #142 (Maya t207-t234). The unit panel listed the missions the engine allowed and nothing about the ones it
withheld: a Great Writer with every writing slot full showed the treatise alone (the slots were found through
screen/culture_works), a Great Musician at home showed no concert tour (the rule -- another major civ's plot --
was found by walking onto Venice's land). On that land the Musician's COMMAND_GIFT row mapped to gift_unit,
which gifts to city-states alone. The tour's reply was a bare {ok, consumed}: no tourism, no receiving civ.

Lua: `missing` rows from available_unit_actions (great_people.lua), the gift row's owner, the tour preview.
Python: the complete gift order, the tour's `effect`, the up-front refusal from home soil.
"""
import unittest
from unittest.mock import patch

import test_mcp_safety as support

from harness import affordances as A
from harness.game import Game

# A Great Writer (unit type 1), a Great Musician (2) and a Warrior (3). Player 0 holds two cities; the Amphitheater
# in each carries one writing slot and both are filled. Plot owners: (5,5) mine, (6,5) Venice (major, player 1),
# (7,5) Zurich (city-state, player 2), (8,5) unowned.
WORLD = """
Locale = { ConvertTextKey = function(k) return (k:gsub('^TXT_KEY_', '')) end }
GameDefines = { MOVE_DENOMINATOR = 60 }
GameInfo = {
  Units = {
    -- the Units row has no GreatWorkType at runtime (live t237); GetGreatWorkSlotType on the unit says it
    [1] = { Type = 'UNIT_WRITER', BaseCultureTurnsToCount = 8 },
    [2] = { Type = 'UNIT_MUSICIAN', OneShotTourism = 10, OneShotTourismPercentOthers = 20 },
    [3] = { Type = 'UNIT_WARRIOR' },
  },
  GreatWorkSlots = { [3] = { ID = 3, Type = 'GREAT_WORK_SLOT_LITERATURE' }, [4] = { ID = 4, Type = 'GREAT_WORK_SLOT_MUSIC' } },
  BuildingClasses = { BUILDINGCLASS_AMPHITHEATER = { ID = 10, MaxGlobalInstances = -1, MaxPlayerInstances = -1 },
                      BUILDINGCLASS_GREAT_LIBRARY = { ID = 11, MaxGlobalInstances = 1, MaxPlayerInstances = -1 },
                      BUILDINGCLASS_OPERA_HOUSE = { ID = 12, MaxGlobalInstances = -1, MaxPlayerInstances = -1 } },
}
local buildings = {
  { ID = 1, Type = 'BUILDING_AMPHITHEATER', BuildingClass = 'BUILDINGCLASS_AMPHITHEATER', Description = 'TXT_KEY_Amphitheater',
    GreatWorkSlotType = 'GREAT_WORK_SLOT_LITERATURE', GreatWorkCount = 1, Cost = 100 },
  { ID = 2, Type = 'BUILDING_GREAT_LIBRARY', BuildingClass = 'BUILDINGCLASS_GREAT_LIBRARY', Description = 'TXT_KEY_Great Library',
    GreatWorkSlotType = 'GREAT_WORK_SLOT_LITERATURE', GreatWorkCount = 2, Cost = 185 },
  { ID = 3, Type = 'BUILDING_OPERA_HOUSE', BuildingClass = 'BUILDINGCLASS_OPERA_HOUSE', Description = 'TXT_KEY_Opera House',
    GreatWorkSlotType = 'GREAT_WORK_SLOT_MUSIC', GreatWorkCount = 1, Cost = 300 },
}
GameInfo.Buildings = setmetatable({}, { __call = function()
  local i = 0
  return function() i = i + 1; return buildings[i] end
end })
local function city(name, x, y, works)
  return { GetName = function() return name end, GetX = function() return x end, GetY = function() return y end,
           IsHasBuilding = function(_, id) return id == 1 end,
           GetBuildingGreatWork = function(_, cls, i) return works[i] or -1 end }
end
cities = { city('Palenque', 5, 5, { [0] = 7 }), city('Tikal', 9, 9, { [0] = 8 }) }
owners = { [5] = 0, [6] = 1, [7] = 2, [8] = -1 }
plots = {}
local function plot(x, y)
  local key = x .. ',' .. y
  if not plots[key] then
    plots[key] = { GetX = function() return x end, GetY = function() return y end,
                   GetOwner = function() return owners[x] or -1 end, IsRevealed = function() return true end }
  end
  return plots[key]
end
Map = { GetPlotXY = function(x, y, dx, dy) if y + dy ~= 5 then return nil end; return plot(x + dx, 5) end,
        PlotDistance = function(x1, y1, x2, y2) return math.abs(x1 - x2) end }
Teams = { [0] = { IsAtWar = function() return false end } }
local function civ(name, minor)
  return { IsAlive = function() return true end, IsMinorCiv = function() return minor end,
           GetCivilizationShortDescription = function() return 'TXT_KEY_' .. name end, GetTeam = function() return 1 end }
end
Players = { [1] = civ('Venice', false), [2] = civ('Zurich', true) }
Players[0] = {
  GetTeam = function() return 0 end, GetUnitByID = function(_, id) return units[id] end,
  Cities = function() local i = 0; return function() i = i + 1; return cities[i] end end,
  GetCityOfClosestGreatWorkSlot = function() return cities[1] end,
}
function make_unit(utype, x, legal)
  return {
    GetUnitType = function() return utype end, GetX = function() return x end, GetY = function() return 5 end,
    GetPlot = function() return plot(x, 5) end, MovesLeft = function() return moves or 120 end,
    IsCombatUnit = function() return false end,
    CanStartMission = function(_, mid) return legal[mid] == true end,
    CanDoCommand = function(_, cmd) return cmd == 9 end,
    GetGreatWorkSlotType = function() return utype == 1 and 3 or utype == 2 and 4 or -1 end,
    GetBlastTourism = function() return 300 end,
  }
end
GameInfoActions = {
  [0] = { Type = 'MISSION_CREATE_GREAT_WORK', MissionType = 50, CommandType = -1, AutomateType = -1, MissionData = -1,
          DisabledHelp = 'TXT_KEY_MISSION_CREATE_GREAT_WORK_DISABLED_HELP' },
  [1] = { Type = 'MISSION_GIVE_POLICIES', MissionType = 51, CommandType = -1, AutomateType = -1, MissionData = -1 },
  [2] = { Type = 'MISSION_ONE_SHOT_TOURISM', MissionType = 52, CommandType = -1, AutomateType = -1, MissionData = -1,
          DisabledHelp = 'TXT_KEY_MISSION_ONE_SHOT_TOURISM_DISABLED_HELP' },
  [3] = { Type = 'COMMAND_GIFT', MissionType = -1, CommandType = 9, AutomateType = -1, MissionData = -1 },
  [4] = { Type = 'MISSION_FORTIFY', MissionType = 7, CommandType = -1, AutomateType = -1, MissionData = -1 },
}
units = {
  [11] = make_unit(1, 5, { [51] = true }),         -- Writer at home: treatise offered, Great Work withheld
  [12] = make_unit(2, 5, {}),                      -- Musician at home: nothing offered
  [13] = make_unit(3, 7, { [7] = true }),          -- Warrior on Zurich's plot
  [14] = make_unit(2, 6, { [52] = true }),         -- Musician on Venice's plot
}
"""


class GreatPeopleLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_a_full_slot_census_explains_the_withheld_great_work(self):
        self.run_lua("""
        local r = H.available_unit_actions(11, 0)
        assert(r.ok and #r.actions == 1 and r.actions[1].type == 'MISSION_GIVE_POLICIES', H.json(r))
        assert(r.missing and #r.missing == 1, H.json(r.missing))
        local m = r.missing[1]
        assert(m.mission == 'MISSION_CREATE_GREAT_WORK', m.mission)
        assert(m.slots.total == 2 and m.slots.filled == 2 and m.slots.free == 0, H.json(m.slots))
        assert(m.why:find('no free literature Great Work slot in the empire (2/2 filled)', 1, true), m.why)
        assert(m.why:find('build one of: Amphitheater', 1, true), m.why)
        assert(not m.why:find('Great Library', 1, true), 'a wonder is not what to build: ' .. m.why)
        assert(m.slots.buildings[1] == 'Amphitheater' and #m.slots.buildings == 1, H.json(m.slots.buildings))
        """)

    def test_a_free_slot_points_at_the_nearest_city_instead(self):
        self.run_lua("""
        cities[2] = { GetName = function() return 'Tikal' end, GetX = function() return 9 end, GetY = function() return 9 end,
                      IsHasBuilding = function(_, id) return id == 1 end, GetBuildingGreatWork = function() return -1 end }
        local r = H.available_unit_actions(11, 0)
        local m = r.missing[1]
        assert(m.slots.free == 1, H.json(m.slots))
        assert(m.why == 'stand in or next to one of your cities', m.why)
        assert(m.nearest and m.nearest.city == 'Palenque', H.json(m.nearest))
        """)

    def test_the_concert_tour_names_the_soil_rule_and_the_nearest_plot(self):
        self.run_lua("""
        local r = H.available_unit_actions(12, 0)
        assert(#r.actions == 0 and #r.missing == 2, H.json(r))
        local tour
        for _, m in ipairs(r.missing) do if m.mission == 'MISSION_ONE_SHOT_TOURISM' then tour = m end end
        assert(tour, H.json(r.missing))
        assert(tour.why:find('another major civ', 1, true) and tour.why:find('here: yours', 1, true), tour.why)
        assert(tour.nearest.x == 6 and tour.nearest.name == 'Venice' and tour.nearest.distance == 1, H.json(tour.nearest))
        for _, m in ipairs(r.missing) do
          if m.mission == 'MISSION_CREATE_GREAT_WORK' then
            assert(m.why:find('no free music Great Work slot', 1, true) and m.why:find('(0/0 filled)', 1, true), m.why)
            assert(m.why:find('Opera House', 1, true), m.why)
          end
        end
        """)

    def test_zero_moves_is_the_reason_before_any_other(self):
        self.run_lua("""
        moves = 0
        local r = H.available_unit_actions(14, 0)
        assert(#r.actions == 0 and #r.missing == 2, H.json(r))
        for _, m in ipairs(r.missing) do assert(m.why:find('no moves left', 1, true), m.why) end
        moves = nil
        """)

    def test_a_unit_with_no_great_person_mission_has_no_missing_rows(self):
        self.run_lua("""
        local r = H.available_unit_actions(13, 0)
        assert(r.missing == nil, H.json(r))
        """)

    def test_the_gift_row_is_listed_on_a_city_states_plot_only_and_names_it(self):
        self.run_lua("""
        local r = H.available_unit_actions(13, 0)
        local gift
        for _, a in ipairs(r.actions) do if a.type == 'COMMAND_GIFT' then gift = a end end
        assert(gift, 'Zurich owns the plot: the gift row is listed: ' .. H.json(r.actions))
        assert(gift.minor_id == 2 and gift.owner.name == 'Zurich' and gift.owner.minor == true, H.json(gift))
        r = H.available_unit_actions(14, 0)
        for _, a in ipairs(r.actions) do assert(a.type ~= 'COMMAND_GIFT', "Venice is a major civ: no gift row") end
        assert(#r.actions == 1 and r.actions[1].type == 'MISSION_ONE_SHOT_TOURISM', H.json(r.actions))
        assert(r.actions[1].yield.tourism == 300, H.json(r.actions[1]))
        """)

    def test_the_tour_preview_names_the_receiving_civ_or_says_why_not_here(self):
        self.run_lua("""
        local r = H.concert_tour_preview(14, 0)
        assert(r.ok and r.tourism == 300 and r.others_percent == 20, H.json(r))
        assert(r.to.id == 1 and r.to.civ == 'Venice', H.json(r))
        r = H.concert_tour_preview(12, 0)
        assert(r.ok and r.legal_here == false and r.here == 'yours', H.json(r))
        units[12].GetPlot = function() return { GetOwner = function() return 2 end } end
        r = H.concert_tour_preview(12, 0)
        assert(r.legal_here == false and r.here == "Zurich's (city-state)", H.json(r))
        """)


class GiftRowTests(unittest.TestCase):
    def test_a_gift_row_with_the_owner_is_a_complete_order(self):
        rows = A.action_rows(9, {"type": "COMMAND_GIFT", "kind": "command", "minor_id": 2, "owner": {"id": 2, "name": "Zurich"}})
        self.assertEqual(rows, [A.act("gift_unit", unit_id=9, minor_id=2)])

    def test_a_gift_row_without_an_owner_still_asks_for_the_city_state(self):
        self.assertEqual(A.action_rows(9, {"type": "COMMAND_GIFT", "kind": "command"}),
                         [A.pick("gift_unit", ["minor_id"], unit_id=9)])


class ConcertTourReplyTests(unittest.TestCase):
    def _game(self, preview, after):
        g = Game.__new__(Game)
        g.seat = 0
        g.calls = []

        def q(body):
            g.calls.append(body)
            if "concert_tour_preview" in body:
                return preview
            if "unit_pos" in body:
                return after
            raise AssertionError("unexpected query: " + body)

        g.q = q
        g._order = lambda body: {"ok": True}
        return g

    def test_the_tour_reply_carries_tourism_and_the_receiving_civ(self):
        g = self._game({"ok": True, "tourism": 67, "others_percent": 20, "to": {"id": 4, "civ": "Venice"}},
                       {"ok": False, "err": "no such unit"})
        with patch("harness.game.time.sleep"):
            r = g.unit_mission(942113, "MISSION_ONE_SHOT_TOURISM")
        self.assertTrue(r["ok"] and r["consumed"], r)
        self.assertEqual(r["effect"], {"tourism": 67, "others_percent": 20, "to_civ": "Venice", "to_id": 4})
        self.assertIn("67 tourism to Venice", g._spent_by_order[942113])

    def test_a_tour_from_home_soil_is_refused_before_the_push(self):
        g = self._game({"ok": True, "tourism": 67, "legal_here": False, "here": "yours"}, None)
        pushed = []
        g._order = lambda body: pushed.append(body)
        r = g.unit_mission(942113, "MISSION_ONE_SHOT_TOURISM")
        self.assertFalse(r["ok"])
        self.assertIn("another major civ", r["err"])
        self.assertIn("yours land", r["err"])
        self.assertIn("missing", r["err"])
        self.assertEqual(pushed, [])

    def test_a_failed_preview_leaves_the_mission_as_before(self):
        g = Game.__new__(Game)
        g.seat = 0
        g.q = lambda body: {"ok": False, "err": "no such unit"}
        g._order = lambda body: {"ok": True}
        with patch("harness.game.time.sleep"):
            r = g.unit_mission(942113, "MISSION_ONE_SHOT_TOURISM")
        self.assertTrue(r["ok"] and r["consumed"], r)
        self.assertNotIn("effect", r)


if __name__ == "__main__":
    unittest.main()
