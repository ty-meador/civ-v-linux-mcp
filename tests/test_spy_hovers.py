"""The espionage screen's two hovers a spy row hides (GitLab #9, #10).

espionageoverview.lua greys the coup button for one of four reasons, in a fixed order, and prints
Player:GetCoupChanceOfSuccess on the enabled button and its confirm. The potential meter on a
foreign city row has three tooltip states; the building/wonder/policy modifiers and the catch-spies
lines are only built in the first of them.
"""
import unittest

import test_mcp_safety as support

WORLD = r"""
local cs_city = { GetOwner = function() return 24 end, GetName = function() return 'Wittenberg' end, GetID = function() return 8192 end }
local capital = { GetOwner = function() return 5 end, GetName = function() return 'Marrakech' end, GetID = function() return 8192 end,
  IsHasBuilding = function(_, id) return id == 1 end,
  GetBuildingEspionageModifier = function(_, id) return id == 1 and -25 or 0 end,
  GetBuildingGlobalEspionageModifier = function(_, id) return id == 2 and -15 or 0 end,
}
local buildings_read = 0
local guarded = setmetatable({}, { __index = function(_, k)
  if k == 'IsHasBuilding' or k == 'GetBuildingEspionageModifier' or k == 'GetBuildingGlobalEspionageModifier' then
    buildings_read = buildings_read + 1
    error('foreign city buildings read outside the potential state')
  end
  return capital[k]
end })
H._guarded = guarded
H._buildings_read = function() return buildings_read end
local plots = {
  ['10,10'] = { GetPlotCity = function() return cs_city end },
  ['20,20'] = { GetPlotCity = function() return capital end },
  ['30,30'] = { GetPlotCity = function() return guarded end },
}
Map = { GetPlot = function(x, y) return plots[x .. ',' .. y] end }
local function rows(list) return function() local i = 0; return function() i = i + 1; return list[i] end end end
GameInfo = {
  Buildings = rows({ { ID = 1, Type = 'BUILDING_CONSTABLE', BuildingClass = 'BUILDINGCLASS_CONSTABLE', Description = 'Constabulary' },
                     { ID = 2, Type = 'BUILDING_GREAT_FIREWALL', BuildingClass = 'BUILDINGCLASS_GREAT_FIREWALL', Description = 'Great Firewall' } }),
  BuildingClasses = { BUILDINGCLASS_CONSTABLE = { ID = 1 }, BUILDINGCLASS_GREAT_FIREWALL = { ID = 2 } },
  Policies = rows({ { ID = 0, Type = 'POLICY_A', Description = 'Policy A' }, { ID = 1, Type = 'POLICY_B', Description = 'Policy B' } }),
}
Locale = { ConvertTextKey = function(k) return k end }
SPY = {}          -- the row GetEspionageSpies returns; tests reshape it
CAN_COUP = false
ALLY = 4
EST = false
STATUS = {}
CHANCE = 42
Players = {
  [0] = {
    GetEspionageSpies = function() return { SPY } end,
    GetEspionageCityStatus = function() return STATUS end,
    CanSpyStageCoup = function() return CAN_COUP end,
    HasSpyEstablishedSurveillance = function() return EST end,
    GetCoupChanceOfSuccess = function(_, city) assert(city == cs_city); return CHANCE end,
    GetAvailableSpyRelocationCities = function() return {} end,
    IsMinorCiv = function() return false end,
  },
  [4] = { IsMinorCiv = function() return false end, GetCivilizationShortDescriptionKey = function() return 'Ethiopia' end },
  [5] = { IsMinorCiv = function() return false end, GetName = function() return 'Ahmad' end,
          GetBuildingClassCount = function(_, id) return id == 2 and 1 or 0 end,
          HasPolicy = function(_, id) return id == 1 end, IsPolicyBlocked = function() return false end,
          GetPolicyEspionageModifier = function(_, id) return id == 1 and -10 or 0 end,
          GetPolicyEspionageCatchSpiesModifier = function(_, id) return id == 1 and 25 or 0 end },
  [24] = { IsMinorCiv = function() return true end, GetAlly = function() return ALLY end },
}
local function spy(x, y, state, est)
  return { AgentID = 1, Name = 'Cameahwait', Rank = 'Agent', State = state or 'TXT_KEY_SPY_STATE_SURVEILLANCE',
           CityX = x, CityY = y, TurnsLeft = 0, PercentComplete = 0, EstablishedSurveillance = est or false }
end
H._spy = spy
"""


class CoupButtonTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_enabled_button_carries_the_percent_and_the_ally(self):
        self.run_lua("""
        SPY = H._spy(10, 10); CAN_COUP = true; EST = true; ALLY = 4
        local r = H.spies(0)[1]
        assert(r.can_stage_coup == true and r.coup_chance == 42, tostring(r.coup_chance))
        assert(r.coup_ally == 4 and r.coup_ally_name == 'Ethiopia' and r.coup_why_not == nil)
        assert(r.city_potential == nil, 'a city-state row has no potential meter')
        """)

    def test_grey_reasons_follow_the_stock_order(self):
        self.run_lua("""
        SPY = H._spy(10, 10); CAN_COUP = false
        EST = false; ALLY = 4
        assert(H.spies(0)[1].coup_why_not == 'surveillance_pending')
        EST = true; ALLY = -1
        local r = H.spies(0)[1]
        assert(r.coup_why_not == 'no_ally' and r.coup_ally == nil and r.coup_chance == nil)
        EST = true; ALLY = 0
        assert(H.spies(0)[1].coup_why_not == 'we_are_ally')
        SPY = H._spy(10, 10, 'TXT_KEY_SPY_STATE_DEAD'); CAN_COUP = true; EST = true; ALLY = 4
        r = H.spies(0)[1]
        assert(r.coup_why_not == 'spy_dead' and r.can_stage_coup == false and r.coup_chance == nil)
        """)

    def test_stage_coup_refuses_with_the_reason_and_reports_the_chance(self):
        self.run_lua("""
        SPY = H._spy(10, 10); CAN_COUP = false; EST = false; ALLY = 4
        local sent = 0
        Network = { SendStageCoup = function(pid, agent) sent = sent + 1; assert(pid == 0 and agent == 1) end }
        local r = H.stage_coup(1, 0)
        assert(r.ok == false and r.why_not == 'surveillance_pending' and r.coup_ally == 'Ethiopia' and sent == 0)
        CAN_COUP = true; EST = true
        Players[0].GetNumNotifications = function() return 7 end
        r = H.stage_coup(1, 0)
        assert(r.ok == true and r.chance == 42 and r.city == 'Wittenberg' and r.against == 'Ethiopia', H.json(r))
        assert(r.held_before == 7 and r.city_owner == 24 and sent == 1)
        assert(H.stage_coup(9, 0).ok == false)
        """)


class PotentialHoverTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_established_surveillance_with_positive_potential_prints_everything(self):
        self.run_lua("""
        SPY = H._spy(20, 20, 'TXT_KEY_SPY_STATE_GATHERING_INTEL', true)
        STATUS = { { PlayerID = 5, CityID = 8192, BasePotential = 6588, Potential = 9882 } }
        local r = H.spies(0)[1]
        local cp = r.city_potential
        assert(cp.state == 'potential' and cp.potential == 9882 and cp.base_potential == 6588, H.json(cp))
        assert(#cp.modifiers.buildings == 1 and cp.modifiers.buildings[1].name == 'Constabulary' and cp.modifiers.buildings[1].pct == -25)
        assert(#cp.modifiers.wonders == 1 and cp.modifiers.wonders[1].building == 'BUILDING_GREAT_FIREWALL' and cp.modifiers.wonders[1].pct == -15)
        assert(#cp.modifiers.policies == 1 and cp.modifiers.policies[1].policy == 'POLICY_B' and cp.modifiers.policies[1].pct == -10)
        assert(#cp.catch_spies == 1 and cp.catch_spies[1].pct == 25 and cp.catch_spies[1].who == 'Ahmad')
        assert(r.coup_why_not == nil and r.coup_chance == nil, 'no coup fields on a major civ row')
        """)

    def test_nonpositive_potential_and_no_surveillance_never_read_foreign_buildings(self):
        self.run_lua("""
        SPY = H._spy(30, 30, 'TXT_KEY_SPY_STATE_SURVEILLANCE', true)
        STATUS = { { PlayerID = 5, CityID = 8192, BasePotential = 5554, Potential = -1 } }
        local cp = H.spies(0)[1].city_potential
        assert(cp.state == 'cannot_steal' and cp.base_potential == 5554 and cp.potential == nil and cp.modifiers == nil, H.json(cp))
        SPY = H._spy(30, 30, 'TXT_KEY_SPY_STATE_TRAVELLING', false)
        STATUS = { { PlayerID = 5, CityID = 8192, BasePotential = 5554, Potential = 9000 } }
        cp = H.spies(0)[1].city_potential
        assert(cp.state == 'once_known' and cp.base_potential == 5554 and cp.modifiers == nil, H.json(cp))
        STATUS = { { PlayerID = 5, CityID = 8192, BasePotential = 0, Potential = 0 } }
        assert(H.spies(0)[1].city_potential.state == 'unknown')
        STATUS = {}
        assert(H.spies(0)[1].city_potential.state == 'unknown')
        assert(H._buildings_read() == 0, 'foreign buildings were read outside the potential state')
        """)

    def test_own_city_rows_in_the_relocation_list_carry_modifiers(self):
        self.run_lua("""
        Players[0].GetAvailableSpyRelocationCities = function() return { { PlayerID = 0, CityID = 7, Name = 'Moson Kahni', Population = 12 },
                                                                          { PlayerID = 5, CityID = 8192, Name = 'Marrakech', Population = 20 } } end
        Players[0].GetCityByID = function(_, id) return id == 7 and H._guarded or nil end
        Players[0].GetBuildingClassCount = function() return 0 end
        Players[0].HasPolicy = function(_, id) return id == 0 end
        Players[0].IsPolicyBlocked = function() return false end
        Players[0].GetPolicyEspionageModifier = function() return 0 end
        Players[0].GetPolicyEspionageCatchSpiesModifier = function(_, id) return id == 0 and 20 or 0 end
        STATUS = { { PlayerID = 0, CityID = 7, BasePotential = 4666, Potential = 4666 },
                   { PlayerID = 5, CityID = 8192, BasePotential = 6588, Potential = 9882 } }
        Players[5].GetCityByID = function() error('foreign city read from the relocation list') end
        local rows = H.available_spy_cities(1, 0)
        assert(rows[1].potential == 4666 and rows[1].catch_spies[1].who == 'you' and rows[1].catch_spies[1].pct == 20, H.json(rows[1]))
        assert(rows[2].potential == 6588 and rows[2].modifiers == nil and rows[2].catch_spies == nil)
        """)


if __name__ == "__main__":
    unittest.main()
