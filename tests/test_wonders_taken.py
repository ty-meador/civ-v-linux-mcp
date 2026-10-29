"""Which world wonders are still open is readable (GitLab #115)."""
import unittest

import test_mcp_safety as support


class WondersTakenLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua("""
        Locale = { ConvertTextKey = function(k) return k end }
        GameDefines = { MAX_MAJOR_CIVS = 3 }
        local buildings = { { ID = 1, Type = 'BUILDING_LEANING_TOWER', BuildingClass = 'BUILDINGCLASS_LEANING_TOWER', Description = 'Leaning Tower' },
                            { ID = 2, Type = 'BUILDING_PYRAMID', BuildingClass = 'BUILDINGCLASS_PYRAMID', Description = 'Pyramids' },
                            { ID = 3, Type = 'BUILDING_LIBRARY', BuildingClass = 'BUILDINGCLASS_LIBRARY', Description = 'Library' } }
        GameInfo = GameInfo or {}
        GameInfo.Buildings = setmetatable({ [1] = buildings[1], [2] = buildings[2], [3] = buildings[3] },
          { __call = function() local i = 0; return function() i = i + 1; return buildings[i] end end })
        GameInfo.BuildingClasses = { BUILDINGCLASS_LEANING_TOWER = { ID = 10, MaxGlobalInstances = 1 },
                                     BUILDINGCLASS_PYRAMID = { ID = 11, MaxGlobalInstances = 1 },
                                     BUILDINGCLASS_LIBRARY = { ID = 12, MaxGlobalInstances = -1 } }
        CREATED = { [10] = 1, [11] = 1, [12] = 5 }
        Game.GetBuildingClassCreatedCount = function(cid) return CREATED[cid] or 0 end
        local function civ(i, name, has)
          return { IsAlive = function() return true end, GetTeam = function() return i end,
                   GetCivilizationShortDescription = function() return name end,
                   CountNumBuildings = function(_, b) return has[b] and 1 or 0 end,
                   Cities = function() return function() return nil end end }
        end
        Players = { [0] = civ(0, 'Maya', { [2] = true }), [1] = civ(1, 'Korea', { [1] = true }), [2] = civ(2, 'Unmet', {}) }
        Teams = { [0] = { IsHasMet = function(_, t) return t ~= 1 end } }
        """)

    def test_a_wonder_of_an_unmet_civ_is_listed_as_built_elsewhere(self):
        self.run_lua("""
        local r = H.wonder_overview(0)
        local by = {}
        for _, w in ipairs(r.wonders) do by[w.building] = w end
        assert(by.BUILDING_PYRAMID and by.BUILDING_PYRAMID.civ == 'Maya' and by.BUILDING_PYRAMID.built_elsewhere == nil, H.json(r))
        assert(by.BUILDING_LEANING_TOWER and by.BUILDING_LEANING_TOWER.built_elsewhere == true and by.BUILDING_LEANING_TOWER.civ == 'unknown', H.json(r))
        assert(by.BUILDING_LIBRARY == nil, 'a plain building is never a wonder row')
        assert(r.scope:find('unmet builder', 1, true))
        """)


if __name__ == "__main__":
    unittest.main()
