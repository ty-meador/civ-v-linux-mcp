"""The city-state "Gift Improvement" button, and the hexes it highlights.

Stock (citystatediplopopup.lua + ingame.lua): the button is allies-only and greyed when
`CanMajorGiftTileImprovement` is false, so the interface mode never opens and *no* hex is
highlighted. When it does open, `HighlightImprovableCityStatePlots` lights up every plot within
MINOR_CIV_RESOURCE_SEARCH_RADIUS of the city-state's capital where
`CanMajorGiftTileImprovementAtPlot` is true, and clicking one calls
`Game.DoMinorGiftTileImprovement(from, to, x, y)`.

The two things worth pinning: a greyed button must not leak the target list a human cannot see,
and the write must refuse a plot the highlighter would not have lit rather than sending gold at it.
"""
import unittest

import test_mcp_safety as support

WORLD = """
gold = 500
allied = true
cost = 200
gifted = {}
GameDefines = { MINOR_CIV_RESOURCE_SEARCH_RADIUS = 1 }
GameInfo = { Terrains = {[0]={Type='TERRAIN_GRASS'}},
             Improvements = {[1]={Type='IMPROVEMENT_PLANTATION'}},
             Resources = {[2]={Type='RESOURCE_SILK'}}, Routes = {} }

local function no() return false end
-- Revealed but fogged: describe_plot's cheap path, and the one a human can still name.
local function fogged(x, y, resource)
  return { GetX=function() return x end, GetY=function() return y end,
    IsRevealed=function() return true end, IsVisible=no,
    GetTerrainType=function() return 0 end, IsHills=no, IsMountain=no, IsRiver=no,
    GetResourceType=function() return resource or -1 end,
    GetRevealedImprovementType=function() return -1 end,
    GetRevealedRouteType=function() return -1 end,
    GetRevealedOwner=function() return -1 end,
    GetImprovementType=function() return improvement_now or -1 end }
end
local silk = fogged(10, 10, 2)          -- legal target next to the capital
local hidden = { GetX=function() return 11 end, GetY=function() return 10 end,
                 IsRevealed=no,
                 GetImprovementType=function() return -1 end,
                 -- everything else on an unrevealed plot stays unread
                 GetTerrainType=function() error('unrevealed plot read') end }
local barren = fogged(9, 10)            -- in range, but the engine says no
local grid = { ['10,10']=silk, ['11,10']=hidden, ['9,10']=barren, ['10,9']=barren }
legal = { ['10,10']=true, ['11,10']=true }

Map = {
  PlotXYWithRangeCheck = function(cx, cy, dx, dy, r)
    if math.abs(dx) > r or math.abs(dy) > r then return nil end
    return grid[(cx+dx) .. ',' .. (cy+dy)]
  end,
  GetPlot = function(x, y) return grid[x .. ',' .. y] end,
}

local capital = { GetName=function() return 'Lhasa' end,
                  GetX=function() return 10 end, GetY=function() return 9 end }
local minor = {
  IsMinorCiv=function() return true end, IsAlive=function() return true end,
  GetTeam=function() return 5 end, GetName=function() return 'Lhasa' end,
  IsAllies=function() return allied end,
  GetCapitalCity=function() return capital end,
  GetMinorCivFriendshipWithMajor=function() return 62 end,
  GetGiftTileImprovementCost=function() return cost end,
  CanMajorGiftTileImprovement=function() return allied and gold >= cost end,
  CanMajorGiftTileImprovementAtPlot=function(_, from, x, y)
    assert(from == 0, 'the gift is attributed to our seat')
    return legal[x .. ',' .. y] == true
  end,
}
Players = { [0] = { GetTeam=function() return 0 end, GetGold=function() return gold end }, [5] = minor }
Teams = { [0] = { IsHasMet=function() return true end, IsAtWar=no } }
Game.DoMinorGiftTileImprovement = function(from, to, x, y)
  gifted[#gifted+1] = { from, to, x, y }
  gold = gold - cost
  improvement_now = 1
end
"""


class GiftTileImprovementTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_a_greyed_button_lists_no_targets(self):
        """Not an ally: a human sees a red button and zero highlighted hexes."""
        self.run_lua("""
        allied = false
        local r = H.gift_tile_improvement_options(5, 0)
        assert(r.ok and r.can == false, 'button must read as unavailable')
        assert(r.plots == nil, 'a greyed button highlights nothing; do not list targets')
        assert(r.why_not:find('ally'), 'say it is allies-only: ' .. tostring(r.why_not))
        assert(r.cost == 200 and r.gold == 500)
        """)

    def test_too_poor_says_the_price_and_the_treasury(self):
        self.run_lua("""
        gold = 30
        local r = H.gift_tile_improvement_options(5, 0)
        assert(r.can == false and r.plots == nil)
        assert(r.why_not:find('200') and r.why_not:find('30'), r.why_not)
        """)

    def test_greyed_with_every_resource_tile_improved_says_so(self):
        """Live t241: Sidon, ally, 232 gold against 200, button grey -- its Wine plantation and
        Bison camp were already improved. The human looks at the tiles; so does the harness."""
        self.run_lua("""
        Players[5].CanMajorGiftTileImprovement = function() return false end
        local silk = Map.GetPlot(10, 10)
        silk.GetRevealedOwner = function() return 5 end
        silk.GetRevealedImprovementType = function() return 1 end
        local r = H.gift_tile_improvement_options(5, 0)
        assert(r.ok and r.can == false and r.plots == nil, 'still a greyed button: no target list')
        assert(r.why_not:find('no tile left to improve'), r.why_not)
        assert(r.why_not:find('silk plantation at %(10,10%)'), r.why_not)
        assert(#r.resource_tiles == 1 and r.resource_tiles[1].improvement == 'PLANTATION')
        assert(r.search_radius == 1)
        local w = H.gift_tile_improvement(5, 10, 10, 0)
        assert(w.ok == false and #gifted == 0 and w.err:find('no tile left'), w.err)
        """)

    def test_greyed_with_an_unimproved_resource_lists_it_without_guessing(self):
        """The engine's plot rule beyond 'already improved' is not ported; name the tiles, not a cause."""
        self.run_lua("""
        Players[5].CanMajorGiftTileImprovement = function() return false end
        Map.GetPlot(10, 10).GetRevealedOwner = function() return 5 end
        local r = H.gift_tile_improvement_options(5, 0)
        assert(r.can == false and r.plots == nil)
        assert(r.why_not:find('would let us improve') and r.why_not:find('silk unimproved at %(10,10%)'), r.why_not)
        """)

    def test_greyed_with_no_visible_resource_tile(self):
        self.run_lua("""
        Players[5].CanMajorGiftTileImprovement = function() return false end
        local r = H.gift_tile_improvement_options(5, 0)
        assert(r.can == false and r.plots == nil)
        assert(r.why_not:find('none of its revealed tiles within 1 hexes'), r.why_not)
        assert(#r.resource_tiles == 0)
        """)

    def test_options_are_the_highlighted_hexes_only(self):
        self.run_lua("""
        local r = H.gift_tile_improvement_options(5, 0)
        assert(r.can == true and r.cost == 200 and r.search_radius == 1)
        assert(r.capital.name == 'Lhasa' and r.capital.x == 10 and r.capital.y == 9)
        assert(#r.plots == 2, 'only the two legal plots, got ' .. #r.plots)
        local by = {}
        for _, e in ipairs(r.plots) do by[e.x .. ',' .. e.y] = e end
        assert(by['10,10'].resource == 'SILK', 'a revealed target names what is on it')
        assert(by['11,10'].revealed == false and by['11,10'].t == nil,
               'an unrevealed target is a bare highlight, not a terrain read')
        """)

    def test_a_plot_the_highlighter_would_not_light_is_refused(self):
        self.run_lua("""
        local r = H.gift_tile_improvement(5, 9, 10, 0)
        assert(r.ok == false and #gifted == 0, 'no gold may be sent at an illegal plot')
        assert(r.err:find('9,10') and r.err:find('2 plots'), r.err)
        assert(r.options.can == true, 'the refusal carries the real options')
        """)

    def test_a_greyed_button_refuses_the_write(self):
        self.run_lua("""
        allied = false
        local r = H.gift_tile_improvement(5, 10, 10, 0)
        assert(r.ok == false and #gifted == 0)
        assert(r.err:find('ally'), r.err)
        """)

    def test_the_gift_reports_what_it_bought(self):
        self.run_lua("""
        local r = H.gift_tile_improvement(5, 10, 10, 0)
        assert(r.ok, r.err)
        assert(#gifted == 1, 'exactly one engine call')
        local c = gifted[1]
        assert(c[1] == 0 and c[2] == 5 and c[3] == 10 and c[4] == 10,
               'stock argument order is (fromPlayer, toPlayer, x, y)')
        assert(r.before.gold == 500 and r.after.gold == 300 and r.gold_spent == 200)
        assert(r.after.improvement == 'PLANTATION', 'say which improvement appeared')
        assert(r.plot.resource == 'SILK' and r.name == 'Lhasa')
        """)

    def test_an_inactive_seat_does_not_gift(self):
        self.run_lua("""
        Game.GetActivePlayer = function() return 3 end
        local r = H.gift_tile_improvement(5, 10, 10, 0)
        assert(r.ok == false and #gifted == 0 and r.err:find('not active'), r.err)
        """)

    def test_the_city_state_screen_reuses_the_same_status(self):
        """city_state_actions' button row and the options tool must not drift apart."""
        self.run_lua("""
        gold = 30
        local st = H.gift_tile_improvement_status(5, 0)
        assert(st.can == false and st.cost == 200 and st.why_not:find('200'))
        assert(st.plots == nil, 'the status row is the button, not the target list')
        """)


if __name__ == "__main__":
    unittest.main()
