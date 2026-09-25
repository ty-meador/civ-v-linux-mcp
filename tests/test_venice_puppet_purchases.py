"""Venice may buy in its puppets; nobody may choose a puppet's production (GitLab #15).

Stock `ingame/popups/productionpopup.lua` returns early for a puppet -- unless the active player
`MayNotAnnex()` and the popup was opened in purchase mode ("You're super-special Venice and are able
to update the window"). So Venice's human sees a purchase list for each puppet while the production
picker stays closed. Before v201 `H.available_production` answered the blanket puppet refusal for
every player, hiding a legal screen from Venice; `purchase_cost` already knew the exception.

Runs the shipped Lua in lupa with a fake city, once as an ordinary player and once as Venice.
"""
import unittest

import test_mcp_safety as support

WORLD = """
YieldTypes = { YIELD_GOLD = 2, YIELD_FAITH = 5 }
Locale = { ConvertTextKey = function(k) return k end }
GameInfo = {
  Units = function()
    local rows, i = { { ID = 1, Type = 'UNIT_MUSKETMAN', Description = 'Musketman' },
                      { ID = 2, Type = 'UNIT_MISSIONARY', Description = 'Missionary' } }, 0
    return function() i = i + 1; return rows[i] end
  end,
  Buildings = function()
    local rows, i = { { ID = 3, Type = 'BUILDING_MARKET', Description = 'Market' },
                      { ID = 4, Type = 'BUILDING_NATIONAL_COLLEGE', Description = 'National College' } }, 0
    return function() i = i + 1; return rows[i] end
  end,
  Projects = function()
    local rows, i = { { ID = 5, Type = 'PROJECT_MANHATTAN', Description = 'Manhattan' } }, 0
    return function() i = i + 1; return rows[i] end
  end,
  Processes = function()
    local rows, i = { { ID = 6, Type = 'PROCESS_WEALTH', Description = 'Wealth' } }, 0
    return function() i = i + 1; return rows[i] end
  end,
}
VENICE = false
city = {
  IsPuppet = function() return true end,
  IsProductionAutomated = function() return true end,
  GetProductionNameKey = function() return 'TXT_KEY_BUILDING_GRANARY' end,
  CanTrain = function(_, id) return id == 1 end,
  CanConstruct = function(_, id) return id == 3 or id == 4 end,
  CanCreate = function() return true end,
  CanMaintain = function() return true end,
  GetUnitProductionTurnsLeft = function() return 3 end,
  GetBuildingProductionTurnsLeft = function() return 11 end,
  GetProjectProductionTurnsLeft = function() return 40 end,
  GetUnitPurchaseCost = function(_, id) return 300 end,
  GetBuildingPurchaseCost = function(_, id) if id == 4 then return -1 end return 740 end,
  GetUnitFaithPurchaseCost = function(_, id) if id == 2 then return 200 end return -1 end,
  GetBuildingFaithPurchaseCost = function() return -1 end,
  IsCanPurchase = function(_, test_cost, test_train, uid, bid, pid, yield)
    if yield == 5 then return uid == 2 end             -- faith: only the Missionary
    if bid == 4 then return false end                  -- national wonder: never for gold
    return true
  end,
}
Players = { [0] = { GetCityByID = function() return city end,
                    MayNotAnnex = function() return VENICE end } }
H.league_projects = function() return {} end
"""


class VenicePuppetPurchaseTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_an_ordinary_players_puppet_is_still_refused(self):
        self.run_lua("""
        local r = H.available_production(1, 0)
        assert(r.ok == false, 'a puppet has no production picker')
        assert(r.puppet == true)
        assert(r.err:find('annex'), r.err)
        assert(r.items == nil, 'no list at all: an offer the seat cannot take')
        """)

    def test_venice_gets_the_purchase_list_and_only_that(self):
        self.run_lua("""
        VENICE = true
        local r = H.available_production(1, 0)
        assert(r.ok == true, 'purchase mode opens for Venice')
        assert(r.puppet == true and r.purchase_only == true)
        assert(r.producing == 'TXT_KEY_BUILDING_GRANARY', 'what the puppet AI chose is still visible')
        local by = {}
        for _, e in ipairs(r.items) do by[e.item] = e end
        assert(by['UNIT_MUSKETMAN'] and by['UNIT_MUSKETMAN'].gold == 300 and by['UNIT_MUSKETMAN'].can_buy == true)
        assert(by['BUILDING_MARKET'] and by['BUILDING_MARKET'].gold == 740)
        assert(by['UNIT_MISSIONARY'] and by['UNIT_MISSIONARY'].faith == 200 and by['UNIT_MISSIONARY'].faith_only == true)
        assert(by['BUILDING_NATIONAL_COLLEGE'] == nil, 'no price at all: not on the purchase screen')
        assert(by['PROJECT_MANHATTAN'] == nil and by['PROCESS_WEALTH'] == nil,
               'projects and processes belong to the production picker')
        for _, e in ipairs(r.items) do
          assert(e.turns == nil, 'the AI schedule is not an offer: ' .. e.item)
        end
        """)

    def test_a_non_puppet_venice_city_is_unchanged(self):
        self.run_lua("""
        VENICE = true
        city.IsPuppet = function() return false end
        local r = H.available_production(1, 0)
        assert(r.ok == true and r.purchase_only == nil and r.puppet == nil)
        local by = {}
        for _, e in ipairs(r.items) do by[e.item] = e end
        assert(by['PROJECT_MANHATTAN'] and by['PROCESS_WEALTH'], 'the capital keeps its full picker')
        """)


if __name__ == "__main__":
    unittest.main()
