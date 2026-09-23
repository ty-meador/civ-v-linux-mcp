"""The city screen's corner meters, and the red price of a tile you cannot afford.

cities() is the banner: integer yields and a growth word from FoodDifference(true). Opening the
city shows something else (cityview.lua): food stored against the growth threshold, hammers
stored against what the item costs, culture stored against the next border, and fractional gold
and science. A settler eats the food surplus, so that label says stagnant while the banner may
not. A tile priced in red is still a price -- CanBuyPlotAt(x, y, true) ignores gold.
"""
import unittest

import test_mcp_safety as support

WORLD = r"""
YieldTypes = { YIELD_GOLD = 0, YIELD_SCIENCE = 1 }
GameOptionTypes = { GAMEOPTION_NO_SCIENCE = 1, GAMEOPTION_NO_RELIGION = 2 }
local other = {
  GetID = function() return 8 end, GetName = function() return 'Te-Moak' end,
  IsWorkingPlot = function() return true end,
}
local function plot(x, y, extra)
  local p = { GetX = function() return x end, GetY = function() return y end,
    IsVisible = function() return true end, GetOwner = function() return 0 end,
    IsWater = function() return false end, IsVisibleEnemyUnit = function() return false end }
  if extra then for k, v in pairs(extra) do p[k] = v end end
  return p
end
local plots = {
  [0] = plot(10, 20),
  [1] = plot(11, 20),  -- priced, not affordable
  [2] = plot(12, 20),  -- affordable
  [3] = plot(10, 21, { IsWater = function() return true end }),
  [4] = plot(10, 19, { IsVisibleEnemyUnit = function() return true end }),
  [5] = plot(11, 21, { GetWorkingCity = function() return other end }),
}
local city = {
  GetID = function() return 7 end, GetName = function() return 'Moson Kahni' end,
  GetX = function() return 10 end, GetY = function() return 20 end, GetPopulation = function() return 8 end,
  GetOwner = function() return 0 end,
  IsCapital = function() return true end, IsPuppet = function() return false end,
  IsOccupied = function() return false end, IsRazing = function() return false end,
  GetProductionNameKey = function() return 'TXT_KEY_BUILDING_LIBRARY' end,
  GetProductionTurnsLeft = function() return 4 end, IsProductionProcess = function() return false end,
  FoodDifference = function(_, include) return include and 3 or 2 end,
  FoodDifferenceTimes100 = function() return 250 end,
  IsFoodProduction = function() return false end,
  GetFood = function() return 17 end, GrowthThreshold = function() return 30 end,
  GetFoodTurnsLeft = function() return 6 end,
  GetProductionTimes100 = function() return 4550 end, GetProductionNeeded = function() return 120 end,
  GetCurrentProductionDifferenceTimes100 = function() return 1875 end,
  GetProductionModifier = function() return 25 end,
  GetJONSCultureStored = function() return 13 end, GetJONSCultureThreshold = function() return 40 end,
  GetJONSCulturePerTurn = function() return 7 end,
  GetYieldRateTimes100 = function(_, yield)
    if yield == YieldTypes.YIELD_GOLD then return 1250 end
    if yield == YieldTypes.YIELD_SCIENCE then return 800 end
    return 0
  end,
  GetFaithPerTurn = function() return 4 end, GetBaseTourism = function() return 2 end,
  IsEmpireVeryUnhappy = function() return false end,
  GetNumCityPlots = function() return 6 end,
  GetCityIndexPlot = function(_, i) return plots[i] end,
  IsWorkingPlot = function() return false end, IsForcedWorkingPlot = function() return false end,
  CanWork = function() return true end,
  CanBuyPlotAt = function(_, x, y, ignore_gold)
    if x == 11 and y == 20 then return ignore_gold and true or false end
    if x == 12 and y == 20 then return true end
    return false
  end,
  GetBuyPlotCost = function(_, x, y)
    if x == 11 then return 80 end
    if x == 12 then return 65 end
    return 0
  end,
  IsPlotBlockaded = function(_, p) return p:GetX() == 10 and p:GetY() == 21 end,
  GetOrderQueueLength = function() return 0 end,
  GetResourceDemanded = function() return -1 end,
}
Players = { [0] = {
  GetTeam = function() return 0 end, GetCityByID = function(_, id) return id == 7 and city or nil end,
  IsEmpireVeryUnhappy = function() return false end,
} }
H.L = function(s) return s end
H._city = city
"""


class CityScreenMeterTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_meters_match_the_city_view_and_a_red_price_is_still_a_price(self):
        self.run_lua("""
        local r = H.city_screen(7, 0)
        assert(r.ok, r.err)
        local m = r.meters
        assert(m.food.stored == 17 and m.food.needed == 30 and m.food.per_turn == 2.5)
        assert(m.food.state == 'growing' and m.food.turns == 6)
        assert(m.production.stored == 45.5 and m.production.needed == 120 and m.production.per_turn == 18.75)
        assert(m.production.modifier == 25)
        assert(m.culture.stored == 13 and m.culture.needed == 40 and m.culture.per_turn == 7)
        assert(m.culture.turns == 4)  -- ceil((40-13)/7) = 4
        assert(m.gold == 12.5 and m.science == 8 and m.faith == 4 and m.tourism == 2)
        assert(m.empire_very_unhappy == nil)
        -- banner growth stays on FoodDifference(true), which this city reports as 3
        assert(r.food_surplus == 3 and r.growth == 'growing' and r.growth_turns == 6)
        local unaffordable, affordable
        for _, e in ipairs(r.plots) do
          if e.x == 11 and e.y == 20 then unaffordable = e end
          if e.x == 12 and e.y == 20 then affordable = e end
        end
        assert(unaffordable.buy_gold == 80 and unaffordable.can_afford == false and unaffordable.buyable == nil)
        assert(affordable.buy_gold == 65 and affordable.buyable == true and affordable.can_afford == nil)
        """)

    def test_tile_icons_name_the_reason_the_city_screen_does(self):
        self.run_lua("""
        local r = H.city_screen(7, 0)
        local by = {}
        for _, e in ipairs(r.plots) do by[e.x .. ',' .. e.y] = e end
        assert(by['10,21'].blockaded == true and by['10,21'].enemy_unit == nil)
        assert(by['10,19'].enemy_unit == true and by['10,19'].blockaded == nil)
        assert(by['11,21'].worked_by == 'Te-Moak')
        assert(by['10,20'].worked_by == nil and by['10,20'].blockaded == nil)
        """)

    def test_a_settler_is_stagnant_and_a_process_has_no_cost(self):
        self.run_lua("""
        local c = H._city
        c.IsFoodProduction = function() return true end
        c.IsProductionProcess = function() return true end
        c.GetJONSCulturePerTurn = function() return 0 end
        c.GetProductionModifier = function() return 0 end
        c.IsEmpireVeryUnhappy = function() return true end
        Players[0].IsEmpireVeryUnhappy = function() return true end
        local r = H.city_screen(7, 0)
        assert(r.meters.food.state == 'stagnant' and r.meters.food.turns == nil)
        assert(r.meters.food.per_turn == 2.5)  -- the number is still on screen
        assert(r.meters.production.needed == nil and r.meters.production.modifier == nil)
        assert(r.meters.culture.turns == nil and r.meters.culture.per_turn == 0)
        assert(r.meters.empire_very_unhappy == true)
        -- the banner did not change its mind just because a settler is being built
        assert(r.growth == 'growing')
        """)

    def test_starving_hides_the_turn_count_and_options_hide_yields(self):
        self.run_lua("""
        local c = H._city
        c.FoodDifferenceTimes100 = function() return -150 end
        c.FoodDifference = function() return -1 end
        Game.IsOption = function(opt) return opt == GameOptionTypes.GAMEOPTION_NO_SCIENCE
            or opt == GameOptionTypes.GAMEOPTION_NO_RELIGION end
        local r = H.city_screen(7, 0)
        assert(r.meters.food.state == 'starving' and r.meters.food.turns == nil and r.meters.food.per_turn == -1.5)
        assert(r.meters.science == nil and r.meters.faith == nil and r.meters.gold == 12.5 and r.meters.tourism == 2)
        assert(r.growth == 'starving' and r.growth_turns == nil)
        """)

    def test_culture_turns_never_drop_below_one(self):
        self.run_lua("""
        H._city.GetJONSCultureStored = function() return 40 end
        local r = H.city_screen(7, 0)
        assert(r.meters.culture.turns == 1)
        """)


if __name__ == "__main__":
    unittest.main()
