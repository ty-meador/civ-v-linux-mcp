"""The Happiness screen's rows, not only the top-bar totals.

happinessinfo.lua expands each luxury, each city's building / local / connection happiness and
unhappiness, and the hover that says why a city or a citizen is not the usual three or one.
The totals on the tooltip stay as they were.
"""
import unittest

import test_mcp_safety as support


WORLD = r"""
local function iter(rows)
  local i = 0
  return function() i = i + 1; return rows[i] end
end

Locale = { ConvertTextKey = function(k, ...)
  local names = {
    TXT_KEY_RESOURCE_SILK = "Silk",
    TXT_KEY_RESOURCE_COTTON = "Cotton",
    TXT_KEY_RESOURCE_SPICES = "Spices",
    TXT_KEY_NORMALLY = "(Normally)",
    TXT_KEY_NUMBER_OF_CITIES_TT = "Every non-occupied city produces 3 unhappiness",
    TXT_KEY_NUMBER_OF_CITIES_TT_NORMALLY = "Every non-occupied city produces 3 unhappiness (Normally).",
    TXT_KEY_NUMBER_OF_CITIES_HANDICAP_TT = "Difficulty: {1}% less",
    TXT_KEY_UNHAPPINESS_MOD_MAP = "Map: {1}% less",
    TXT_KEY_UNHAPPINESS_MOD_CAPITAL = "Capital citizens: {1}% of usual",
    TXT_KEY_UNHAPPINESS_MOD_SPECIALIST = "Specialists produce half the usual unhappiness",
    TXT_KEY_POP_UNHAPPINESS_TT = "Every citizen produces 1 unhappiness",
    TXT_KEY_NUMBER_OF_OCCUPIED_CITIES_TT = "Every occupied city produces 5 unhappiness",
    TXT_KEY_OCCUPIED_POP_UNHAPPINESS_TT = "Every occupied citizen produces 1.34 unhappiness",
    TXT_KEY_TP_EMPIRE_UNHAPPY = "Cities grow at 1/4 speed.",
    TXT_KEY_TP_EMPIRE_VERY_UNHAPPY = "Rebel units may appear.",
    TXT_KEY_TP_EMPIRE_SUPER_UNHAPPY = "[COLOR_NEGATIVE_TEXT]Cities may flip.[ENDCOLOR]",
  }
  local s = names[k] or k
  local n = select("#", ...)
  if n >= 1 then s = s:gsub("{1}", tostring(select(1, ...))) end
  return s
end }

GameInfo = {
  Resources = function() return iter({
    { ID = 1, Type = "RESOURCE_SILK", Description = "TXT_KEY_RESOURCE_SILK" },
    { ID = 2, Type = "RESOURCE_COTTON", Description = "TXT_KEY_RESOURCE_COTTON" },
    { ID = 3, Type = "RESOURCE_SPICES", Description = "TXT_KEY_RESOURCE_SPICES" },
  }) end,
  HandicapInfos = { [0] = { NumCitiesUnhappinessMod = 80, PopulationUnhappinessMod = 100 } },
}
Game.GetWorldNumCitiesUnhappinessPercent = function() return 75 end

local function city(id, name, fields)
  local c = { GetID = function() return id end, GetName = function() return name end,
    GetPopulation = function() return fields.pop or 1 end,
    GetHappiness = function() return fields.buildings or 0 end,
    GetLocalHappiness = function() return fields.local_happiness or 0 end,
    IsCapital = function() return fields.capital or false end,
    IsOccupied = function() return fields.occupied or false end,
    IsNoOccupiedUnhappiness = function() return false end }
  return c
end
local moson = city(1, "Moson Kahni", { pop = 10, buildings = 2, capital = true })
local cusco = city(2, "Cusco", { pop = 6, local_happiness = 1, occupied = true })
local quiet = city(3, "Pohokwi", { pop = 1 })
local cities = { moson, cusco, quiet }

local function zero() return 0 end
local p = {
  GetExcessHappiness = function() return 4 end,
  GetHappiness = function() return 20 end,
  GetHappinessFromPolicies = function() return 1 end,
  GetHappinessFromResources = function() return 8 end,
  GetHappinessFromResourceVariety = zero,
  GetHappinessFromBuildings = function() return 2 end,
  GetHappinessFromCities = function() return 1 end,
  GetHappinessFromGarrisonedUnits = zero,
  GetHappinessFromTradeRoutes = function() return 1 end,
  GetHappinessFromReligion = zero,
  GetHappinessFromNaturalWonders = zero,
  GetHappinessFromMinorCivs = zero,
  GetExtraHappinessPerCity = zero,
  GetNumCities = function() return 3 end,
  GetHappinessFromLeagues = function() return 2 end,
  GetExtraHappinessPerLuxury = function() return 1 end,
  GetHappinessFromLuxury = function(_, id) return (id == 1 or id == 2) and 4 or 0 end,
  GetHappinessPerTradeRoute = function() return 100 end,
  IsCapitalConnectedToCity = function(_, c) return c:GetID() == 2 end,
  GetUnhappinessFromCityForUI = function(_, c)
    if c:GetID() == 1 then return 300 end
    if c:GetID() == 2 then return 500 end
    return 0
  end,
  Cities = function()
    local i = 0
    return function() i = i + 1; return cities[i] end
  end,
  GetUnhappinessFromCityCount = function() return 300 end,
  GetUnhappinessFromCapturedCityCount = function() return 500 end,
  GetUnhappinessFromPuppetCityPopulation = function() return 300 end,
  GetUnhappinessFromCitySpecialists = function() return 200 end,
  GetUnhappinessFromCityPopulation = function() return 1000 end,
  GetUnhappinessFromOccupiedCities = function() return 400 end,
  GetUnhappinessFromUnits = zero,
  GetUnhappinessFromPublicOpinion = zero,
  GetUnhappiness = function() return 20 end,
  GetTotalPopulation = function() return 17 end,
  GetHandicapType = function() return 0 end,
  GetCityCountUnhappinessMod = zero,
  GetTraitCityUnhappinessMod = zero,
  GetUnhappinessMod = zero,
  GetTraitPopUnhappinessMod = zero,
  GetCapitalUnhappinessMod = function() return 50 end,
  IsHalfSpecialistUnhappiness = function() return true end,
  GetOccupiedPopulationUnhappinessMod = zero,
  IsEmpireUnhappy = function() return false end,
  IsEmpireVeryUnhappy = function() return false end,
  IsEmpireSuperUnhappy = function() return false end,
}
Players = { [0] = p }

local b = H.happiness_breakdown(0)
assert(b.total == 4, "excess happiness")
assert(b.happiness.luxuries == 8 and b.happiness.buildings == 2 and b.happiness.league == 2)
assert(b.happiness.difficulty == 5, b.happiness.difficulty)
assert(b.happiness.extra_per_luxury == 1)
assert(b.happiness.other_luxury == nil)
assert(#b.happiness.by_luxury == 2, "a luxury with no happiness is not a row")
assert(b.happiness.by_luxury[1].resource == "SILK" and b.happiness.by_luxury[1].name == "Silk")
assert(b.happiness.by_luxury[1].happiness == 4)
assert(b.happiness.by_luxury[2].resource == "COTTON")
assert(b.unhappiness.population == 5, "tooltip still splits specialists and puppets out of population")
assert(b.unhappiness.number_of_cities == 3 and b.unhappiness.captured_cities == 5)
assert(b.unhappiness.citizens == 11 and b.unhappiness.occupied_citizens == 6)
assert(b.unhappy == nil)

assert(#b.cities == 2, "a city that is a dash on every stack is omitted")
local cap, occ = b.cities[1], b.cities[2]
assert(cap.name == "Moson Kahni" and cap.buildings == 2 and cap.unhappiness == 3)
assert(cap.connection == nil and cap.occupied == nil and cap.local_happiness == nil)
assert(occ.name == "Cusco" and occ.occupied == true and occ.local_happiness == 1)
assert(occ.connection == 1 and occ.unhappiness == 5 and occ.buildings == nil)

local tips = b.unhappiness.tooltips
assert(tips.city_count:find("Normally", 1, true) and tips.city_count:find("Difficulty: 20%% less"))
assert(tips.city_count:find("Map: 25%% less"))
assert(not tips.population:find("Map:", 1, true), tips.population)
assert(tips.population:find("Capital citizens: 50%% of usual"))
assert(tips.population:find("Specialists produce half"))
assert(tips.population:find("(Normally).", 1, true))
assert(tips.occupied_cities:find("Difficulty: 20%% less"))
assert(tips.occupied_population:find("1.34"))
assert(tips.occupied_population:find("Specialists produce half"))
assert(not tips.occupied_population:find("Difficulty:", 1, true))

p.IsEmpireUnhappy = function() return true end
local unhappy = H.happiness_breakdown(0)
assert(unhappy.unhappy == "unhappy")
assert(unhappy.penalties[1] == "Cities grow at 1/4 speed.")
p.IsEmpireVeryUnhappy = function() return true end
p.IsEmpireSuperUnhappy = function() return true end
local revolt = H.happiness_breakdown(0)
assert(revolt.unhappy == "super_unhappy")
assert(revolt.penalties[1] == "Cities may flip.")
assert(revolt.penalties[2] == "Rebel units may appear.")
"""


class HappinessScreenTests(support.LuaRuntimeTests):
    def test_happiness_screen_rows_match_the_expandable_stacks(self):
        self.run_lua(WORLD)
