"""Trade Route Overview religion columns, and the gold/science hover on each row.

The overview prints a religion icon and "+N" in the left and right columns, and every cell's hover
is BuildTradeRouteToolTipString (base gold, both cities' gold, then only the nonzero bonuses, then
science from the tech gap). A zero pressure cell is blank, and a route with no international gold
has no hover at all.
"""
import unittest

import test_mcp_safety as support


class TradeRouteOverviewTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)

    def test_religion_columns_and_the_hover_omit_what_the_screen_blanks(self):
        self.run_lua(r"""
        local TEXTS = {
          TXT_KEY_RELIGION_TENGRIISM = "Tengriism",
          TXT_KEY_RELIGION_BUDDHISM = "Buddhism",
          TXT_KEY_RESOURCE_SILK = "Silk",
          TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_YOUR_REVENUE = "YOUR REVENUE",
          TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_THEIR_REVENUE = "THEIR REVENUE",
          TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_BASE = "Gold base: {1_Num}",
          TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_GPT_YOURS = "{1_CityName} Gold per turn: {2_Num}",
          TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_POLICIES = "Bonus from Social Policies: {1_Num}",
          TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_BUILDING = "Gold bonus from buildings in {1_CityName}: {2_Num}",
          TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_RESOURCE_HEADER = "Different resources",
          TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_RESOURCE_DIFFERENT = "{1_ResourceIcon} {2_ResourceName:textkey}: {3_Num}",
          TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_RIVER_MODIFIER = "Next to River: +{1_Num}%",
          TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_TOTAL = "Total: {1_Num} [ICON_GOLD] Gold",
          TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_TRADEE_TOTAL = "{1_CivName} Total: {2_Num} [ICON_GOLD] Gold",
          TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_YOUR_SCIENCE_GAIN = "YOUR SCIENCE GAIN",
          TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_THEIR_SCIENCE_GAIN = "THEIR SCIENCE GAIN",
          TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_YOUR_SCIENCE_EXPLAINED = "{1_CivName} has discovered {2_Num} technologies that you do not know. You are receiving {3_Num} [ICON_RESEARCH] Science on this route due to your Cultural Influence over them.",
          TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_THEIR_SCIENCE_EXPLAINED = "You have discovered {1_Num} technologies that {2_CivName} does not know. They are receiving {3_Num} [ICON_RESEARCH] Science on this route due to their Cultural Influence over you.",
          TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_YOUR_SCIENCE_TOTAL = "Total: {1_Num} [ICON_RESEARCH] Science",
          TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_THEIR_SCIENCE_TOTAL = "{1_CivName} Total: {2_Num} [ICON_RESEARCH] Science",
          TXT_KEY_CITY_MOSON = "Moson Kahni",
          TXT_KEY_CITY_ADWA = "Adwa",
        }
        Locale = { ConvertTextKey = function(key, ...)
          local s = TEXTS[key] or key
          local args = {...}
          local i = 0
          s = s:gsub("{%d+_[^}]*}", function()
            i = i + 1
            local v = args[i]
            if TEXTS[v] then return TEXTS[v] end
            return tostring(v)
          end)
          return s
        end }
        DomainTypes = { DOMAIN_LAND = 2, DOMAIN_SEA = 0 }
        ResourceUsageTypes = { RESOURCEUSAGE_LUXURY = 1, RESOURCEUSAGE_STRATEGIC = 2 }
        Game.GetResourceUsageType = function() return 1 end
        Game.IsNetworkMultiPlayer = function() return false end
        GameInfo = {
          Religions = {
            [12] = { Type = "RELIGION_TENGRIISM", Description = "TXT_KEY_RELIGION_TENGRIISM" },
            [10] = { Type = "RELIGION_BUDDHISM", Description = "TXT_KEY_RELIGION_BUDDHISM" },
          },
          Resources = function()
            local i, rows = 0, { { ID = 3, IconString = "[ICON_RES_SILK]", Description = "TXT_KEY_RESOURCE_SILK" } }
            return function() i = i + 1; return rows[i] end
          end,
        }
        local function methods(extra)
          return function(_, ...)
            return extra
          end
        end
        local function city(key, owner, silk)
          return {
            GetNameKey = function() return key end,
            GetOwner = function() return owner end,
            IsHasResourceLocal = function(_, id) return id == 3 and silk or false end,
          }
        end
        local origin = city("TXT_KEY_CITY_MOSON", 0, true)
        local target = city("TXT_KEY_CITY_ADWA", 4, false)
        local function trade_player(name)
          return {
            GetTeam = function() return 0 end,
            GetName = function() return name end,
            GetNickName = function() return "" end,
            GetCivilizationAdjectiveKey = function() return "Ethiopian" end,
            GetInternationalTradeRouteTotal = function(_, _, _, _, mine) return mine == false and 100 or 300 end,
            GetInternationalTradeRouteBaseBonus = function(_, _, _, mine) return mine == false and 0 or 100 end,
            GetInternationalTradeRouteGPTBonus = function(_, _, _, mine) return mine and 200 or 50 end,
            GetInternationalTradeRoutePolicyBonus = function() return 0 end,
            GetInternationalTradeRouteYourBuildingBonus = function() return 0 end,
            GetInternationalTradeRouteTheirBuildingBonus = function(_, _, _, _, mine) return mine and 100 or 0 end,
            GetInternationalTradeRouteResourceTraitModifier = function() return 0 end,
            GetInternationalTradeRouteExclusiveBonus = function() return 0 end,
            GetInternationalTradeRouteOtherTraitBonus = function() return 0 end,
            GetInternationalTradeRouteRiverModifier = function() return 0 end,
            GetInternationalTradeRouteDomainModifier = function() return 0 end,
            GetInternationalTradeRouteScience = function(_, _, _, _, mine) return mine and 100 or 200 end,
            GetNumTechDifference = function() return 3 end,
            GetInfluenceTradeRouteScienceBonus = function() return 1 end,
          }
        end
        Players = { [0] = trade_player("Pocatello"), [4] = trade_player("Haile Selassie") }
        Teams = { [0] = { IsHasMet = function() return true end } }
        local route = {
          FromCityName = "Moson Kahni", ToCityName = "Adwa", FromID = 0, ToID = 4, Domain = 2,
          TurnsLeft = 6, FromGPT = 1273, FromScience = 100, ToGPT = 300, ToScience = 100,
          ToFood = 0, ToProduction = 0, FromReligion = 12, FromPressure = 6, ToReligion = 10, ToPressure = 9,
          FromCity = origin, ToCity = target,
        }
        local blank = {
          FromCityName = "Addis Ababa", ToCityName = "Agaidika", FromID = 4, ToID = 0, Domain = 2,
          TurnsLeft = -22, FromGPT = 702, FromScience = 100, ToGPT = 200, ToScience = 100,
          ToFood = 0, ToProduction = 0, FromReligion = -1, FromPressure = 0, ToReligion = -1, ToPressure = 0,
        }
        Players[0].GetTradeRoutes = function() return { route } end
        Players[0].GetTradeRoutesToYou = function() return { blank } end
        local r = H.trade_routes(0)
        local row = r.outgoing[1]
        assert(row.from_religion == "Tengriism" and row.from_pressure == 6, row.from_religion)
        assert(row.to_religion == "Buddhism" and row.to_pressure == 9, row.to_religion)
        assert(row.details:find("YOUR REVENUE", 1, true), row.details)
        assert(row.details:find("Gold base: 1", 1, true), row.details)
        assert(row.details:find("Moson Kahni Gold per turn: 2", 1, true), row.details)
        assert(row.details:find("Adwa Gold per turn: 0.5", 1, true), row.details)
        assert(row.details:find("Gold bonus from buildings in Adwa: 1", 1, true), row.details)
        assert(row.details:find("Different resources", 1, true) and row.details:find("Silk: 0.5", 1, true), row.details)
        assert(not row.details:find("Social Policies", 1, true), "a zero policy line is not on the hover")
        assert(not row.details:find("Next to River", 1, true), "a zero river line is not on the hover")
        assert(row.details:find("Total: 3", 1, true), row.details)
        assert(row.details:find("Haile Selassie Total: 1", 1, true), row.details)
        assert(row.details:find("YOUR SCIENCE GAIN", 1, true), row.details)
        assert(row.details:find("Haile Selassie has discovered 3 technologies", 1, true), row.details)
        assert(row.details:find("THEIR SCIENCE GAIN", 1, true), row.details)
        local quiet = r.incoming[1]
        assert(quiet.from_religion == nil and quiet.to_pressure == nil, "blank religion cells stay off")
        assert(quiet.turns_left == nil, "a negative TurnsLeft is the panel's empty cell")
        assert(quiet.details == nil, "no city objects, so no hover was invented")
        """)

    def test_chooser_uses_pressure_amount_and_skips_a_route_with_no_gold(self):
        self.run_lua(r"""
        Locale = { ConvertTextKey = function(k) return k end }
        YieldTypes = { YIELD_GOLD = 0, YIELD_SCIENCE = 1, YIELD_FOOD = 2, YIELD_PRODUCTION = 3,
                       YIELD_CULTURE = 4, YIELD_FAITH = 5 }
        DomainTypes = { DOMAIN_LAND = 2, DOMAIN_SEA = 0 }
        GameInfo = { Religions = { [12] = { Type = "RELIGION_TENGRIISM", Description = "TXT_KEY_RELIGION_TENGRIISM" } },
                     Units = {} }
        local origin = { GetNameKey = function() return "Moson" end, GetOwner = function() return 0 end,
                         IsHasResourceLocal = function() return false end }
        local target = { GetName = function() return "Harar" end, GetOwner = function() return 4 end,
                         GetNameKey = function() return "Harar" end, IsHasResourceLocal = function() return false end }
        local plot = { GetPlotCity = function() return origin end }
        local unit = { GetID = function() return 7 end, IsTrade = function() return true end,
                       GetPlot = function() return plot end, GetDomainType = function() return 2 end }
        Players = {
          [0] = { GetUnitByID = function() return unit end,
                  GetPotentialInternationalTradeRouteDestinations = function()
                    return { { X = 1, Y = 2, TradeConnectionType = 0,
                               Yields = { { Mine = 0, Theirs = 0 }, { Mine = 0, Theirs = 0 } },
                               FromReligion = 12, FromPressureAmount = 4, ToReligion = 0, ToPressureAmount = 0 } }
                  end,
                  GetName = function() return "Pocatello" end, GetNickName = function() return "" end,
                  GetInternationalTradeRouteTotal = function() return 0 end },
          [4] = { GetCivilizationDescription = function() return "Ethiopia" end,
                  GetName = function() return "Haile" end },
        }
        Map = { GetPlot = function() return { GetPlotCity = function() return target end } end }
        local r = H.available_trade_routes(7, 0)
        assert(#r == 1, "still a list")
        assert(r[1].from_religion == "TENGRIISM" and r[1].from_pressure == 4, tostring(r[1].from_religion))
        assert(r[1].to_religion == nil and r[1].details == nil, "no gold, so the hover stays off")
        """)


if __name__ == "__main__":
    unittest.main()
