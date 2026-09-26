"""The hovers behind the city screen's numbers (GitLab #14, #16, #17).

infotooltipinclude.lua builds a yield's tooltip from the city's base-rate sources, the food usage
line, the engine's modifier string and the total; the culture and faith tooltips have their own
source lists. cityview.lua prints a specialist's per-yield numbers beside its slot and shows a
built building's help on hover. city_screen now carries all three next to the meters.
"""
import unittest

import test_mcp_safety as support
from test_city_screen_meters import WORLD

HOVERS = r"""
YieldTypes.YIELD_FOOD = 2; YieldTypes.YIELD_PRODUCTION = 3; YieldTypes.YIELD_CULTURE = 4; YieldTypes.YIELD_FAITH = 5
GameOptionTypes.GAMEOPTION_NO_POLICIES = 3
GameDefines = { PUPPET_CULTURE_MODIFIER = -25, PUPPET_FAITH_MODIFIER = -25 }
local Y = YieldTypes
local city = H._city
local src = {  -- [yield] = {terrain, buildings, specialists, misc, religion}
  [Y.YIELD_FOOD] = { 9, 2, 0, 0, 1 },
  [Y.YIELD_PRODUCTION] = { 6, 4, 0, 1, 0 },
  [Y.YIELD_GOLD] = { 3, 5, 2, 0, 0 },
  [Y.YIELD_SCIENCE] = { 0, 3, 3, 8, 0 },
  [Y.YIELD_CULTURE] = { 1, 0, 0, 0, 0 },
  [Y.YIELD_FAITH] = { 2, 0, 0, 0, 0 },
}
city.GetBaseYieldRateFromTerrain = function(_, y) return src[y][1] end
city.GetBaseYieldRateFromBuildings = function(_, y) return src[y][2] end
city.GetBaseYieldRateFromSpecialists = function(_, y) return src[y][3] end
city.GetBaseYieldRateFromMisc = function(_, y) return src[y][4] end
city.GetBaseYieldRateFromReligion = function(_, y) return src[y][5] end
city.GetBaseYieldRate = function(_, y) local s = src[y]; return s[1] + s[2] + s[3] + s[4] + s[5] end
city.GetYieldPerPopTimes100 = function(_, y) return y == Y.YIELD_SCIENCE and 50 or 0 end  -- 8 pop -> +4
city.GetYieldRate = function(_, y, no_trade)
  if y == Y.YIELD_FOOD then return no_trade and 12 or 14 end  -- 2 food from trade routes
  return 0
end
city.FoodConsumption = function(_, real, extra) assert(real == true and extra == 0); return 16 end
city.GetYieldModifierTooltip = function(_, y)
  -- the engine mixes [ICON_BULLET] and a bare [BULLET] (live t266, the trade-route gold line)
  if y == Y.YIELD_PRODUCTION then return "[NEWLINE][ICON_BULLET]+25% from [COLOR_POSITIVE_TEXT]Workshop[ENDCOLOR][NEWLINE][BULLET]+10% from Policies" end
  return ""
end
city.GetJONSCulturePerTurnFromBuildings = function() return 4 end
city.GetJONSCulturePerTurnFromPolicies = function() return 1 end
city.GetJONSCulturePerTurnFromSpecialists = function() return 0 end
city.GetJONSCulturePerTurnFromGreatWorks = function() return 2 end
city.GetJONSCulturePerTurnFromReligion = function() return 0 end
city.GetJONSCulturePerTurnFromLeagues = function() return 0 end
city.GetJONSCulturePerTurnFromTraits = function() return 0 end
city.GetCultureRateModifier = function() return 0 end
city.GetNumWorldWonders = function() return 1 end
city.GetFaithPerTurnFromBuildings = function() return 2 end
city.GetFaithPerTurnFromTraits = function() return 0 end
city.GetFaithPerTurnFromPolicies = function() return 0 end
city.GetFaithPerTurnFromReligion = function() return 0 end
city.GetTourismTooltip = function() return "+2 [ICON_TOURISM] from Great Works[NEWLINE]----------------[NEWLINE]+0% modifiers" end
city.GetSpecialistYield = function(_, sid, y)
  if sid == 1 and y == Y.YIELD_SCIENCE then return 3 end
  if sid == 1 and y == Y.YIELD_GOLD then return 1 end
  return 0
end
city.GetCultureFromSpecialist = function(_, sid) return sid == 1 and 1 or 0 end
city.GetSpecialistCount = function(_, sid) return sid == 1 and 2 or 0 end
city.GetSpecialistGreatPersonProgress = function() return 30 end
city.GetSpecialistUpgradeThreshold = function() return 100 end
city.GetGreatPeopleRateModifier = function() return 0 end
city.IsHasBuilding = function(_, id) return id == 11 end
city.GetNumRealBuilding = function(_, id) return id == 11 and 1 or 0 end
city.GetNumFreeBuilding = function() return 0 end
city.IsBuildingSellable = function() return false end
city.GetNumSpecialistsInBuilding = function(_, id) return id == 11 and 2 or 0 end
city.GetNumSpecialistsAllowedByBuilding = function(_, id) return id == 11 and 2 or 0 end
local p = Players[0]
p.GetCultureCityModifier = function() return 10 end
p.GetCultureWonderMultiplier = function() return 33 end
p.GetGreatPeopleRateModifier = function() return 0 end
p.GetGreatScientistRateModifier = function() return 50 end
p.GetGoldenAgeTurns = function() return 0 end
local function rows(list) return function() local i = 0; return function() i = i + 1; return list[i] end end end
local yields = { { ID = Y.YIELD_FOOD, Type = 'YIELD_FOOD' }, { ID = Y.YIELD_PRODUCTION, Type = 'YIELD_PRODUCTION' },
                 { ID = Y.YIELD_GOLD, Type = 'YIELD_GOLD' }, { ID = Y.YIELD_SCIENCE, Type = 'YIELD_SCIENCE' } }
local scientist = { ID = 1, Type = 'SPECIALIST_SCIENTIST', GreatPeopleUnitClass = 'UNITCLASS_SCIENTIST', GreatPeopleRateChange = 3 }
local university = { ID = 11, Type = 'BUILDING_UNIVERSITY', SpecialistType = 'SPECIALIST_SCIENTIST',
                     Help = 'TXT_KEY_BUILDING_UNIVERSITY_HELP', GreatPeopleRateChange = 0 }
GameInfo = GameInfo or {}
GameInfo.Yields = rows(yields)
GameInfo.Specialists = setmetatable({ SPECIALIST_SCIENTIST = scientist, [1] = scientist }, { __call = rows({ scientist }) })
GameInfo.Buildings = setmetatable({ [11] = university, BUILDING_UNIVERSITY = university }, { __call = rows({ university }) })
GameInfo.UnitClasses = { UNITCLASS_SCIENTIST = { ID = 5, Type = 'UNITCLASS_SCIENTIST' } }
Locale = { ConvertTextKey = function(k)
  if k == 'TXT_KEY_BUILDING_UNIVERSITY_HELP' then return '+33% [ICON_RESEARCH] Science in this City.[NEWLINE]+2 [ICON_RESEARCH] from Jungle tiles.' end
  return k
end }
"""


class CityScreenHoverTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD + HOVERS)

    def test_yield_hovers_list_the_tooltip_sources_and_totals(self):
        self.run_lua("""
        local r = H.city_screen(7, 0)
        assert(r.ok, r.err)
        local b = r.meters.breakdown
        -- food: sources, trade routes, usage line, base after eating, total = FoodDifferenceTimes100/100
        assert(b.food.terrain == 9 and b.food.buildings == 2 and b.food.religion == 1 and b.food.specialists == nil)
        assert(b.food.trade_routes == 2 and b.food.eaten == 16 and b.food.gross == 14)
        assert(b.food.base == 14 - 16, 'base is the surplus after eating, as the stock base line reads')
        assert(b.food.total == 2.5)
        -- production: misc stays misc, modifiers are the engine string as clean lines
        assert(b.production.misc == 1 and b.production.population == nil)
        assert(#b.production.modifiers == 2, 'two modifier lines')
        assert(b.production.modifiers[1] == '+25% from Workshop', b.production.modifiers[1])
        assert(b.production.modifiers[2] == '+10% from Policies')
        -- GetProductionTooltip: bare base rate, and the production-specific total the meter shows
        assert(b.production.base == 11 and b.production.total == 18.75, tostring(b.production.total))
        -- gold: no modifiers key when the engine string is empty
        assert(b.gold.terrain == 3 and b.gold.buildings == 5 and b.gold.specialists == 2 and b.gold.modifiers == nil)
        assert(b.gold.total == 12.5)
        -- science: misc is the population line, and the per-pop extra is its own line and part of base
        assert(b.science.population == 8 and b.science.misc == nil)
        assert(b.science.per_population == 4 and b.science.base == 14 + 4)
        assert(b.science.total == 8)
        """)

    def test_culture_and_faith_hovers_follow_their_own_source_lists(self):
        self.run_lua("""
        local b = H.city_screen(7, 0).meters.breakdown
        assert(b.culture.buildings == 4 and b.culture.policies == 1 and b.culture.great_works == 2)
        assert(b.culture.specialists == nil and b.culture.religion == nil, 'zero sources are omitted')
        assert(b.culture.terrain == 1 and b.culture.total == 7)
        assert(b.culture.player_modifier_pct == 10 and b.culture.city_modifier_pct == nil)
        assert(b.culture.wonder_bonus_pct == 33, 'wonder bonus only with a world wonder')
        assert(b.culture.puppet_modifier_pct == nil)
        assert(b.faith.buildings == 2 and b.faith.terrain == 2 and b.faith.total == 4)
        assert(b.faith.puppet_modifier_pct == nil)
        assert(#b.tourism == 2 and b.tourism[1] == '+2 from Great Works', b.tourism[1])
        """)

    def test_a_puppet_shows_the_puppet_modifier_and_no_wonder_bonus_without_wonders(self):
        self.run_lua("""
        H._city.IsPuppet = function() return true end
        H._city.GetNumWorldWonders = function() return 0 end
        local b = H.city_screen(7, 0).meters.breakdown
        assert(b.culture.puppet_modifier_pct == -25 and b.faith.puppet_modifier_pct == -25)
        assert(b.culture.wonder_bonus_pct == nil)
        """)

    def test_hovers_are_absent_under_the_matching_game_options(self):
        self.run_lua("""
        Game = Game or {}
        Game.IsOption = function(o) return o == GameOptionTypes.GAMEOPTION_NO_SCIENCE or o == GameOptionTypes.GAMEOPTION_NO_RELIGION end
        local b = H.city_screen(7, 0).meters.breakdown
        assert(b.science == nil and b.faith == nil and b.food ~= nil and b.culture ~= nil)
        """)

    def test_specialist_rows_and_slots_carry_the_slot_yields(self):
        self.run_lua("""
        local r = H.city_screen(7, 0)
        assert(#r.specialists == 1, 'one specialist type in the city')
        local s = r.specialists[1]
        assert(s.specialist == 'SPECIALIST_SCIENTIST' and s.count == 2)
        assert(s.yields.SCIENCE == 3 and s.yields.GOLD == 1 and s.yields.CULTURE == 1 and s.yields.GREAT_PEOPLE == 3)
        assert(s.yields.FOOD == nil, 'zero yields are not printed')
        local u
        for _, b in ipairs(r.buildings) do if b.building == 'BUILDING_UNIVERSITY' then u = b end end
        assert(u and u.specialist_assigned == 2 and u.specialist_slots == 2)
        assert(u.specialist_yields.SCIENCE == 3 and u.specialist_yields.GREAT_PEOPLE == 3)
        """)

    def test_built_buildings_do_not_repeat_their_help_text(self):
        """v216: the building blurb is static and lives once in reference("buildings"); the city screen
        row keeps the enum and name (GitLab #17 wanted the words reachable, not repeated per city)."""
        self.run_lua("""
        local r = H.city_screen(7, 0)
        local u
        for _, b in ipairs(r.buildings) do if b.building == 'BUILDING_UNIVERSITY' then u = b end end
        assert(u and u.name == 'UNIVERSITY' and u.help == nil, tostring(u and u.help))
        """)

    def test_a_city_without_the_hover_api_still_answers(self):
        """An older engine (or a mocked one) without the breakdown methods keeps the meters intact."""
        self.run_lua("""
        for _, k in ipairs({ 'GetBaseYieldRateFromTerrain', 'GetYieldModifierTooltip', 'GetJONSCulturePerTurnFromBuildings',
                             'GetFaithPerTurnFromBuildings', 'GetTourismTooltip', 'GetSpecialistYield' }) do
          H._city[k] = nil
        end
        local r = H.city_screen(7, 0)
        assert(r.ok and r.meters.gold == 12.5 and r.meters.food.stored == 17)
        assert(r.meters.breakdown.food.total == 2.5 and r.meters.breakdown.food.terrain == nil)
        assert(r.meters.breakdown.tourism == nil)
        """)


if __name__ == "__main__":
    unittest.main()
