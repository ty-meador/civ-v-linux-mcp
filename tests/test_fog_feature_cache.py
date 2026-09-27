"""Remembered terrain features under fog (GitLab #19).

The stock map keeps drawing the forest a fogged tile had when last seen. The engine has no
GetRevealedFeatureType and GetFeatureType is live, so the harness remembers what it saw while the
plot was visible: seeded from every plot visible when a team first asks, kept by every visible
describe_plot, carried across runtime reloads, and never the live read under fog.
"""
import unittest

import test_mcp_safety as support

WORLD = r"""
local function no() return false end
FEATURE = { ['5,5'] = 1, ['6,5'] = -1, ['7,5'] = 1 }   -- 1 = forest, -1 = bare
VISIBLE = { ['5,5'] = true, ['6,5'] = true, ['7,5'] = false }
LIVE_READS = 0
local plots = {}
local function plot(x, y)
  local key = x .. ',' .. y
  local p = { IsRevealed = function() return true end, IsVisible = function() return VISIBLE[key] end,
    GetX = function() return x end, GetY = function() return y end,
    GetTerrainType = function() return 0 end, IsHills = no, IsMountain = no, IsRiver = no, IsLake = no,
    GetResourceType = function() return -1 end,
    GetRevealedImprovementType = function() return -1 end, GetRevealedRouteType = function() return -1 end,
    GetRevealedOwner = function() return -1 end,
    GetImprovementType = function() return -1 end, GetRouteType = function() return -1 end, GetOwner = function() return -1 end,
    IsImprovementPillaged = no, IsRoutePillaged = no, IsCity = no, GetNumUnits = function() return 0 end,
    GetFeatureType = function()
      if not VISIBLE[key] then LIVE_READS = LIVE_READS + 1; error('live feature read under fog at ' .. key) end
      return FEATURE[key]
    end,
  }
  plots[#plots + 1] = p
  return p
end
local by = { ['5,5'] = plot(5, 5), ['6,5'] = plot(6, 5), ['7,5'] = plot(7, 5) }
Map = { GetNumPlots = function() return #plots end, GetPlotByIndex = function(i) return plots[i + 1] end,
        GetPlot = function(x, y) return by[x .. ',' .. y] end }
GameInfo = { Terrains = { [0] = { Type = 'TERRAIN_GRASS' } }, Features = { [1] = { Type = 'FEATURE_FOREST' } },
             Improvements = {}, Routes = {} }
Teams = { [7] = {} }
PLOT = function(x, y) return by[x .. ',' .. y] end
"""


class FogFeatureCacheTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_a_forest_seen_then_fogged_is_remembered_and_chopping_it_stays_hidden(self):
        self.run_lua("""
        local e = H.describe_plot(PLOT(5, 5), 7)
        assert(e.vis == true and e.feature == 'FOREST' and e.remembered == nil)
        VISIBLE['5,5'] = false
        FEATURE['5,5'] = -1          -- chopped while we could not see it
        e = H.describe_plot(PLOT(5, 5), 7)
        assert(e.vis == false and e.feature == 'FOREST' and e.remembered == true, H.json(e))
        assert(LIVE_READS == 0, 'live feature read under fog')
        """)

    def test_the_cache_is_seeded_from_what_was_visible_at_first_use(self):
        self.run_lua("""
        -- 6,5 was visible and bare at first use; 7,5 never visible: no entry
        VISIBLE['5,5'] = false; VISIBLE['6,5'] = false
        local first = H.describe_plot(PLOT(7, 5), 7)     -- first use seeds; 7,5 itself is fogged
        assert(first.feature == nil and first.remembered == nil, 'never seen: nothing to remember')
        FEATURE['6,5'] = 1                                  -- a forest grew under fog
        local e = H.describe_plot(PLOT(6, 5), 7)
        assert(e.feature == nil and e.remembered == nil, 'seen bare, stays bare')
        assert(LIVE_READS == 0)
        """)

    def test_the_cache_is_per_team_and_survives_a_reload(self):
        self.run_lua("""
        H.describe_plot(PLOT(5, 5), 7)
        VISIBLE['5,5'] = false
        assert(H.describe_plot(PLOT(5, 5), 7).feature == 'FOREST')
        -- team 8 never saw it (its seed happens with 5,5 already fogged)
        assert(H.describe_plot(PLOT(5, 5), 8).feature == nil)
        local keep = H.seen_features
        assert(keep[7] and keep[8], 'one cache per team')
        """)
        # a reload carries seen_features like events
        self.run_lua("""
        local before = H.seen_features
        H.version = -1
        """)
        self.lua_reload()
        self.run_lua("""
        VISIBLE['5,5'] = false
        assert(H.describe_plot(PLOT(5, 5), 7).feature == 'FOREST', 'forgotten on reload')
        assert(LIVE_READS == 0)
        """)

    def lua_reload(self):
        """Run the runtime source again on the same state, as ensure_runtime does after a bump."""
        support.LuaRuntimeTests.load_runtime(self)


if __name__ == "__main__":
    unittest.main()
