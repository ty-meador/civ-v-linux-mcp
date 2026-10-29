"""A refused build names the engine's rule when it is a feature-removal tech (GitLab #130).

Siam t30 (Grok): a Worker on jungle cocoa with Calendar known was refused BUILD_PLANTATION with the bare legal list
and the plot never appeared among the build plots. CIV5Builds.xml's BuildFeatures: a plantation on Jungle removes the
jungle as part of the build and needs Bronze Working (Forest: Mining, Marsh: Masonry).
"""
import unittest

import test_mcp_safety as support

WORLD = """
GameDefines = { MOVE_DENOMINATOR = 60 }
GameInfo = GameInfo or {}
GameInfo.Features = { [2] = { Type = 'FEATURE_JUNGLE' } }
GameInfo.Resources = { [7] = { Type = 'RESOURCE_COCOA' } }
GameInfoTypes = { TECH_BRONZE_WORKING = 12, TECH_CALENDAR = 9 }
local builds = { { ID = 3, Type = 'BUILD_PLANTATION', ImprovementType = 'IMPROVEMENT_PLANTATION' },
                 { ID = 4, Type = 'BUILD_FARM', ImprovementType = 'IMPROVEMENT_FARM' },
                 { ID = 5, Type = 'BUILD_REMOVE_JUNGLE' } }
GameInfo.Builds = function() local i = 0; return function() i = i + 1; return builds[i] end end
local bf = { { BuildType = 'BUILD_PLANTATION', FeatureType = 'FEATURE_JUNGLE', PrereqTech = 'TECH_BRONZE_WORKING', Remove = true },
             { BuildType = 'BUILD_PLANTATION', FeatureType = 'FEATURE_FOREST', PrereqTech = 'TECH_MINING', Remove = true } }
GameInfo.BuildFeatures = function(filter)
  local i = 0
  return function()
    while true do
      i = i + 1
      local r = bf[i]
      if not r then return nil end
      if not filter or r.BuildType == filter.BuildType then return r end
    end
  end
end
local irt = { { ImprovementType = 'IMPROVEMENT_PLANTATION', ResourceType = 'RESOURCE_COCOA' } }
GameInfo.Improvement_ResourceTypes = function(filter)
  local i = 0
  return function()
    while true do
      i = i + 1
      local r = irt[i]
      if not r then return nil end
      if r.ImprovementType == filter.ImprovementType and r.ResourceType == filter.ResourceType then return r end
    end
  end
end
HAS = { [9] = true }
Teams = { [0] = { IsHasTech = function(_, id) return HAS[id] == true end } }
PLOT = { GetFeatureType = function() return 2 end, GetResourceType = function() return 7 end }
UNIT = { CanBuild = function(_, pl, id) return id == 4 end, GetPlot = function() return PLOT end }
Players = { [0] = { GetUnitByID = function() return UNIT end, GetTeam = function() return 0 end } }
"""


class FeatureTechGapTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_the_plantation_on_jungle_names_bronze_working(self):
        self.run_lua("""
        local b = H.blocked_builds(UNIT, PLOT, 0)
        assert(#b == 1 and b[1].build == 'BUILD_PLANTATION' and b[1].needs_tech == 'TECH_BRONZE_WORKING' and b[1].feature == 'JUNGLE', H.json(b))
        assert(b[1].reason:find('removes the JUNGLE as part of the build', 1, true), b[1].reason)
        local why = H.build_refusal_why(32769, 'BUILD_PLANTATION', 0)
        assert(why and why:find('TECH_BRONZE_WORKING', 1, true) and why:find('research it', 1, true), tostring(why))
        assert(H.build_refusal_why(32769, 'BUILD_FARM', 0) == nil, 'a farm has no feature rule here')
        HAS[12] = true
        assert(#H.blocked_builds(UNIT, PLOT, 0) == 0, 'with Bronze Working the engine, not a tech, decides')
        assert(H.build_refusal_why(32769, 'BUILD_PLANTATION', 0) == nil)
        """)

    def test_no_resource_or_no_feature_names_nothing(self):
        self.run_lua("""
        PLOT.GetResourceType = function() return -1 end
        assert(#H.blocked_builds(UNIT, PLOT, 0) == 0, 'no resource: the plot calls for no build')
        PLOT.GetResourceType = function() return 7 end
        PLOT.GetFeatureType = function() return -1 end
        assert(#H.blocked_builds(UNIT, PLOT, 0) == 0, 'no feature: no removal rule')
        assert(H.build_refusal_why(32769, 'BUILD_PLANTATION', 0) == nil)
        """)


if __name__ == "__main__":
    unittest.main()
