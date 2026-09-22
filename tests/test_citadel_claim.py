"""A finished build says what it changed -- including the borders a Citadel moved.

`build_check` watched improvement/route/feature and answered `completed: true`. For a Citadel that
is the least interesting half: it annexes every adjacent tile (the only reason to build one) and
expends the Great General doing it, and neither showed up anywhere. Taking a tile off another civ is
also a diplomatic incident the stock tooltip warns about, so the civ it came from is named.
"""
import unittest

import test_mcp_safety as support

WORLD = """
GameInfo = { Improvements = { [4] = { Type = 'IMPROVEMENT_CITADEL' } },
             Builds = { [9] = { Type = 'BUILD_CITADEL' } } }
owner_now = {}
local function plot(x, y)
  return { GetX = function() return x end, GetY = function() return y end,
           GetOwner = function() return owner_now[x .. ',' .. y] or -1 end,
           GetImprovementType = function() return improvement end,
           IsImprovementPillaged = function() return false end,
           GetRouteType = function() return -1 end,
           IsRoutePillaged = function() return false end,
           GetFeatureType = function() return -1 end }
end
improvement = -1
Map = {
  GetPlot = function(x, y) return plot(x, y) end,
  PlotXYWithRangeCheck = function(cx, cy, dx, dy, r)
    if math.abs(dx) > r or math.abs(dy) > r then return nil end
    return plot(cx + dx, cy + dy)
  end,
}
unit_gone = false
Players = { [0] = { GetTeam = function() return 0 end,
                    GetUnitByID = function()
                      if unit_gone then return nil end
                      return { GetBuildType = function() return -1 end,
                               MovesLeft = function() return 0 end }
                    end },
            [4] = { IsBarbarian = function() return false end, GetTeam = function() return 4 end,
                    GetCivilizationShortDescription = function() return 'Ethiopia' end } }
Teams = { [0] = { IsHasMet = function() return true end } }
Game.GetActivePlayer = function() return 0 end
"""


class CitadelClaimTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_the_snapshot_covers_the_plot_and_its_neighbours(self):
        self.run_lua("""
        owner_now = { ['5,5'] = 0, ['5,6'] = 4 }
        local before = H.plot_owners_around(Map.GetPlot(5, 5), 1)
        local n = 0
        for _ in pairs(before) do n = n + 1 end
        assert(n == 9, 'a radius-1 box, got ' .. n)
        assert(before['5,5'] == 0 and before['5,6'] == 4 and before['4,4'] == -1)
        """)

    def test_a_citadel_reports_the_tiles_it_claimed_and_who_lost_them(self):
        self.run_lua("""
        owner_now = { ['5,5'] = 0, ['5,6'] = 4, ['6,5'] = -1, ['4,5'] = 0 }
        local before = { imp = -1, pillaged = false, route = -1, route_pillaged = false, feature = -1,
                         owners = H.plot_owners_around(Map.GetPlot(5, 5), 1) }
        -- the build lands: improvement appears, borders move, the Great General is gone
        improvement, unit_gone = 4, true
        owner_now['5,6'], owner_now['6,5'] = 0, 0
        local c = H.build_check(1, 5, 5, before, 0)
        assert(c.completed == true and c.improvement == 'CITADEL', tostring(c.improvement))
        assert(c.unit_consumed == true, 'the Great Person was expended')
        assert(#c.claimed_plots == 2, 'two tiles changed hands, got ' .. #c.claimed_plots)
        local by = {}
        for _, r in ipairs(c.claimed_plots) do by[r.x .. ',' .. r.y] = r end
        assert(by['5,6'].taken_from == 4 and by['5,6'].taken_from_name == 'Ethiopia')
        assert(by['6,5'].taken_from == nil, 'unowned land is claimed, not taken from anyone')
        assert(by['4,5'] == nil, 'a tile we already owned is not a claim')
        """)

    def test_an_ordinary_build_reports_no_claims(self):
        self.run_lua("""
        owner_now = { ['5,5'] = 0 }
        local before = { imp = -1, pillaged = false, route = -1, route_pillaged = false, feature = -1,
                         owners = H.plot_owners_around(Map.GetPlot(5, 5), 1) }
        improvement = 4
        local c = H.build_check(1, 5, 5, before, 0)
        assert(c.completed == true and c.claimed_plots == nil and c.unit_consumed == nil,
               'a worker finishing a farm keeps its unit and moves no borders')
        """)

    def test_the_snapshot_never_breaks_a_build_on_a_thin_map(self):
        """It runs on the way into every MISSION_BUILD; a missing getter costs the diff, nothing more."""
        self.run_lua("""
        Map = {}
        assert(next(H.plot_owners_around(Map.GetPlot and Map.GetPlot(1, 1) or nil, 1)) == nil)
        Map = { GetPlot = function() error('boom') end }
        local ok = pcall(function() return H.plot_owners_around({ GetX = function() return 1 end,
                                                                  GetY = function() return 1 end }, 1) end)
        assert(ok, 'a throwing map getter must not propagate')
        """)


if __name__ == "__main__":
    unittest.main()
