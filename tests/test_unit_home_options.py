"""The Change Home City / Change Port choosers (trade unit, Great Admiral).

`unit_mission` could already push MISSION_CHANGE_TRADE_UNIT_HOME_CITY, but nothing said which cities
the engine would accept -- stock gets that list from the popup
(Player:GetPotentialTradeUnitNewHomeCity / GetPotentialAdmiralNewPort), and the popup only opens on a
unit standing in one of my cities.
"""
import unittest

import test_mcp_safety as support

WORLD = """
MissionTypes = { MISSION_CHANGE_TRADE_UNIT_HOME_CITY = 40, MISSION_CHANGE_ADMIRAL_PORT = 41 }
GameInfo = { Units = {
  [3] = { Type = 'UNIT_CARAVAN', Class = 'UNITCLASS_CARAVAN' },
  [9] = { Type = 'UNIT_GREAT_ADMIRAL', Class = 'UNITCLASS_GREAT_ADMIRAL' },
  [7] = { Type = 'UNIT_WARRIOR', Class = 'UNITCLASS_WARRIOR' },
} }
candidates = { { X = 50, Y = 24 }, { X = 42, Y = 23 } }
can_start = true

local function city(name, x, y, owner)
  return { GetName = function() return name end, GetX = function() return x end,
           GetY = function() return y end, GetOwner = function() return owner or 0 end }
end
local cities = { ['49,19'] = city('Moson Kahni', 49, 19), ['50,24'] = city('Te-Moak', 50, 24),
                 ['42,23'] = city('Cusco', 42, 23), ['30,30'] = city('Harar', 30, 30, 4) }
Map = { GetPlot = function(x, y)
  local c = cities[x .. ',' .. y]
  return { GetPlotCity = function() return c end, IsCity = function() return c ~= nil end }
end }

function make(unit_type, x, y)
  return { GetUnitType = function() return unit_type end,
           GetX = function() return x end, GetY = function() return y end,
           GetPlot = function() return Map.GetPlot(x, y) end,
           IsTrade = function() return unit_type == 3 end,
           CanStartMission = function() return can_start end }
end
unit = make(3, 49, 19)
asked_with = nil
Players = { [0] = {
  GetUnitByID = function() return unit end,
  GetPotentialTradeUnitNewHomeCity = function(_, u) asked_with = u; return candidates end,
  GetPotentialAdmiralNewPort = function(_, u) asked_with = u; return candidates end,
} }
"""


class UnitHomeOptionTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_a_trade_unit_in_a_city_gets_the_engine_list(self):
        self.run_lua("""
        local r = H.unit_home_options(1, 0)
        assert(r.ok and r.kind == 'trade' and r.can == true)
        assert(r.mission == 'MISSION_CHANGE_TRADE_UNIT_HOME_CITY')
        assert(r.current_home.name == 'Moson Kahni', 'the popup names the city it is standing in')
        assert(#r.cities == 2 and r.cities[1].name == 'Te-Moak' and r.cities[2].name == 'Cusco')
        assert(asked_with == unit, 'the engine is asked about this unit, not the player in general')
        assert(r.how_to_apply:find('unit_mission'), r.how_to_apply)
        """)

    def test_outside_a_city_there_is_no_chooser(self):
        self.run_lua("""
        unit = make(3, 45, 16)
        local r = H.unit_home_options(1, 0)
        assert(r.ok == false and r.can == false and #r.cities == 0)
        assert(r.err:find('45,16') and r.err:find('inside one of my cities'), r.err)
        """)

    def test_a_foreign_city_is_not_a_home(self):
        self.run_lua("""
        unit = make(3, 30, 30)       -- standing in Harar, owned by player 4
        local r = H.unit_home_options(1, 0)
        assert(r.ok == false and r.err:find('inside one of my cities'), r.err)
        """)

    def test_a_great_admiral_uses_its_own_getter_and_mission(self):
        self.run_lua("""
        unit = make(9, 49, 19)
        local r = H.unit_home_options(1, 0)
        assert(r.kind == 'admiral' and r.mission == 'MISSION_CHANGE_ADMIRAL_PORT', r.mission)
        assert(#r.cities == 2)
        """)

    def test_any_other_unit_is_told_plainly(self):
        self.run_lua("""
        unit = make(7, 49, 19)
        local r = H.unit_home_options(1, 0)
        assert(r.ok == false and r.err:find('Great Admiral'), r.err)
        assert(H.unit_home_options(2, 0) ~= nil)
        """)

    def test_an_empty_engine_list_is_not_silence(self):
        self.run_lua("""
        candidates = {}
        local r = H.unit_home_options(1, 0)
        assert(r.ok and #r.cities == 0 and r.note:find('no other city'), tostring(r.note))
        """)


if __name__ == "__main__":
    unittest.main()
