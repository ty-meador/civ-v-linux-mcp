"""The production chooser's button says a name, not an enum, and they do not always match.

BNW renamed several items without renaming their types: BUILDING_THEATRE is "Zoo" on screen, and
UNIT_SHOSHONE_PATHFINDER is just "Pathfinder". `cities()` reports the localized name, so a city
building BUILDING_THEATRE read as "Zoo" and that string appeared nowhere in its own available list
(live t222: set_production was asked for BUILDING_THEATRE and answered `production: "Zoo"`).
"""
import unittest

import test_mcp_safety as support

WORLD = """
YieldTypes = { YIELD_GOLD = 2, YIELD_FAITH = 5 }
Locale = { ConvertTextKey = function(k)
  local names = { TXT_KEY_BUILDING_THEATRE = 'Zoo', TXT_KEY_BUILDING_THEATRE_HELP = 'Happiness.',
                  TXT_KEY_UNIT_SHOSHONE_PATHFINDER = 'Pathfinder',
                  TXT_KEY_BUILDING_FORGE = 'Forge' }
  return names[k] or k
end }
GameInfo = {
  Units = function()
    local rows, i = { { ID = 1, Type = 'UNIT_SHOSHONE_PATHFINDER',
                        Description = 'TXT_KEY_UNIT_SHOSHONE_PATHFINDER' } }, 0
    return function() i = i + 1; return rows[i] end
  end,
  Buildings = function()
    local rows, i = { { ID = 2, Type = 'BUILDING_THEATRE', Description = 'TXT_KEY_BUILDING_THEATRE',
                        Help = 'TXT_KEY_BUILDING_THEATRE_HELP' },
                      { ID = 3, Type = 'BUILDING_FORGE', Description = 'TXT_KEY_BUILDING_FORGE' } }, 0
    return function() i = i + 1; return rows[i] end
  end,
}
local city = {
  IsPuppet = function() return false end,
  IsProductionAutomated = function() return false end,
  CanTrain = function() return true end,
  CanConstruct = function(_, id) return id ~= 3 end,      -- Forge already built
  GetUnitProductionTurnsLeft = function() return 3 end,
  GetBuildingProductionTurnsLeft = function() return 11 end,
  GetUnitPurchaseCost = function() return 220 end,
  GetBuildingPurchaseCost = function() return 740 end,
  IsCanPurchase = function() return true end,
}
Players = { [0] = { GetCityByID = function() return city end } }
"""


class ProductionNameTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_a_renamed_item_carries_the_name_on_the_button(self):
        self.run_lua("""
        local r = H.available_production(1, 0)
        assert(r.ok)
        local by = {}
        for _, e in ipairs(r.items) do by[e.item] = e end
        assert(by['BUILDING_THEATRE'].name == 'Zoo',
               'the enum is Theatre, the button and cities() both say Zoo')
        assert(by['UNIT_SHOSHONE_PATHFINDER'].name == 'Pathfinder')
        assert(by['BUILDING_THEATRE'].help == 'Happiness.', 'help still comes through')
        """)

    def test_an_unlocalized_row_does_not_invent_a_name(self):
        """ConvertTextKey echoes back whatever it cannot resolve; that is not a name."""
        self.run_lua("""
        GameInfo.Buildings = function()
          local rows, i = { { ID = 2, Type = 'BUILDING_MYSTERY', Description = 'BUILDING_MYSTERY' } }, 0
          return function() i = i + 1; return rows[i] end
        end
        local r = H.available_production(1, 0)
        for _, e in ipairs(r.items) do
          if e.item == 'BUILDING_MYSTERY' then assert(e.name == nil, tostring(e.name)) end
        end
        """)


if __name__ == "__main__":
    unittest.main()
