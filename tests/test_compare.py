"""Compact comparisons (#34): a few caller-chosen candidates side by side from one read.

Lua half: H.compare_production / compare_research / compare_improvements / compare_trade_routes on a mocked Venice
(seat 0, which may not annex) and Mongolia (seat 1). Covered: refusals name the rule found (Venice's no-founding
trait, a missing tech, a building needed in the city, a missing resource, already built) and say so when none is
found; a price appears only where the buy button exists; the estimate formula; conditional rows counted over the
city's tiles; a Venice puppet is purchase-only and anyone else's puppet is refused; locked techs carry their
missing ancestors and beakers; an unworked tile's gain is not an empire gain; fogged plots are not read; a bonus
resource is never "connected"; trade hazards count fog and never say safe.
Python half: harness/compare.py validation, limits with `omitted` arguments, sorting, sources and assumptions.
"""
import json
import unittest

import test_mcp_safety as support
from harness import compare as C
from harness.game import Game


WORLD = r"""
local function forbidden(name) return function() error('live ' .. name .. ' read under fog') end end
Locale = { ConvertTextKey = function(k) return k end }
YieldTypes = { YIELD_FOOD = 0, YIELD_PRODUCTION = 1, YIELD_GOLD = 2, YIELD_SCIENCE = 3, YIELD_CULTURE = 4, YIELD_FAITH = 5 }
ResourceUsageTypes = { RESOURCEUSAGE_BONUS = 0, RESOURCEUSAGE_STRATEGIC = 1, RESOURCEUSAGE_LUXURY = 2 }
GameInfoTypes = {}

-- a GameInfo table: indexed by ID and Type, callable like the game's database cursor
function info(rows)
  local t = {}
  for i, r in ipairs(rows) do
    if r.Type then
      r.ID = r.ID or (i - 1)
      t[r.ID] = r; t[r.Type] = r
      GameInfoTypes[r.Type] = r.ID
    end
  end
  return setmetatable(t, { __call = function()
    local i = 0
    return function() i = i + 1; return rows[i] end
  end })
end

GameInfo = {
  Civilizations = info({ { Type = 'CIVILIZATION_VENICE' }, { Type = 'CIVILIZATION_MONGOL' } }),
  UnitClasses = info({ { Type = 'UNITCLASS_SETTLER', DefaultUnit = 'UNIT_SETTLER' },
                       { Type = 'UNITCLASS_WORKER', DefaultUnit = 'UNIT_WORKER' },
                       { Type = 'UNITCLASS_TRIREME', DefaultUnit = 'UNIT_TRIREME' },
                       { Type = 'UNITCLASS_HORSEMAN', DefaultUnit = 'UNIT_HORSEMAN' },
                       { Type = 'UNITCLASS_CARAVAN', DefaultUnit = 'UNIT_CARAVAN' } }),
  Units = info({
    { Type = 'UNIT_SETTLER', Class = 'UNITCLASS_SETTLER', Found = true, Moves = 2, Domain = 'DOMAIN_LAND', Description = 'Settler' },
    { Type = 'UNIT_WORKER', Class = 'UNITCLASS_WORKER', Moves = 2, Domain = 'DOMAIN_LAND', Description = 'Worker', Help = 'Builds improvements.' },
    { Type = 'UNIT_TRIREME', Class = 'UNITCLASS_TRIREME', Moves = 4, Combat = 10, Domain = 'DOMAIN_SEA', PrereqTech = 'TECH_SAILING', Description = 'Trireme' },
    { Type = 'UNIT_HORSEMAN', Class = 'UNITCLASS_HORSEMAN', Moves = 4, Combat = 12, Domain = 'DOMAIN_LAND', Description = 'Horseman' },
    { Type = 'UNIT_CARAVAN', Class = 'UNITCLASS_CARAVAN', Moves = 2, Domain = 'DOMAIN_LAND', Trade = true, Description = 'Caravan' },
  }),
  Unit_ResourceQuantityRequirements = info({ { UnitType = 'UNIT_HORSEMAN', ResourceType = 'RESOURCE_HORSE', Cost = 1 } }),
  BuildingClasses = info({ { Type = 'BUILDINGCLASS_MONUMENT', DefaultBuilding = 'BUILDING_MONUMENT' },
                           { Type = 'BUILDINGCLASS_LIBRARY', DefaultBuilding = 'BUILDING_LIBRARY' },
                           { Type = 'BUILDINGCLASS_UNIVERSITY', DefaultBuilding = 'BUILDING_UNIVERSITY' },
                           { Type = 'BUILDINGCLASS_LIGHTHOUSE', DefaultBuilding = 'BUILDING_LIGHTHOUSE' },
                           { Type = 'BUILDINGCLASS_GRANARY', DefaultBuilding = 'BUILDING_GRANARY' },
                           { Type = 'BUILDINGCLASS_MYSTERY', DefaultBuilding = 'BUILDING_MYSTERY' } }),
  Buildings = info({
    { Type = 'BUILDING_MONUMENT', BuildingClass = 'BUILDINGCLASS_MONUMENT', GoldMaintenance = 1, Description = 'Monument' },
    { Type = 'BUILDING_LIBRARY', BuildingClass = 'BUILDINGCLASS_LIBRARY', GoldMaintenance = 1, PrereqTech = 'TECH_WRITING', Description = 'Library' },
    { Type = 'BUILDING_UNIVERSITY', BuildingClass = 'BUILDINGCLASS_UNIVERSITY', GoldMaintenance = 3, Description = 'University' },
    { Type = 'BUILDING_LIGHTHOUSE', BuildingClass = 'BUILDINGCLASS_LIGHTHOUSE', GoldMaintenance = 1, Water = true, Description = 'Lighthouse' },
    { Type = 'BUILDING_GRANARY', BuildingClass = 'BUILDINGCLASS_GRANARY', GoldMaintenance = 1, Description = 'Granary', Help = 'Food.' },
    { Type = 'BUILDING_MYSTERY', BuildingClass = 'BUILDINGCLASS_MYSTERY', Description = 'Mystery' },
  }),
  Building_YieldChanges = info({ { BuildingType = 'BUILDING_MONUMENT', YieldType = 'YIELD_CULTURE', Yield = 2 },
                                 { BuildingType = 'BUILDING_GRANARY', YieldType = 'YIELD_FOOD', Yield = 2 } }),
  Building_YieldChangesPerPop = info({ { BuildingType = 'BUILDING_LIBRARY', YieldType = 'YIELD_SCIENCE', Yield = 50 } }),
  Building_YieldModifiers = info({ { BuildingType = 'BUILDING_UNIVERSITY', YieldType = 'YIELD_SCIENCE', Yield = 50 } }),
  Building_ResourceYieldChanges = info({ { BuildingType = 'BUILDING_GRANARY', ResourceType = 'RESOURCE_WHEAT', YieldType = 'YIELD_FOOD', Yield = 1 },
                                         { BuildingType = 'BUILDING_GRANARY', ResourceType = 'RESOURCE_BANANA', YieldType = 'YIELD_FOOD', Yield = 1 },
                                         { BuildingType = 'BUILDING_LIGHTHOUSE', ResourceType = 'RESOURCE_FISH', YieldType = 'YIELD_FOOD', Yield = 1 } }),
  Building_SeaPlotYieldChanges = info({ { BuildingType = 'BUILDING_LIGHTHOUSE', YieldType = 'YIELD_FOOD', Yield = 1 } }),
  Building_ClassesNeededInCity = info({ { BuildingType = 'BUILDING_UNIVERSITY', BuildingClassType = 'BUILDINGCLASS_LIBRARY' } }),
  Technologies = info({ { Type = 'TECH_POTTERY', Era = 'ERA_ANCIENT', Description = 'Pottery' },
                        { Type = 'TECH_WRITING', Era = 'ERA_ANCIENT', Description = 'Writing' },
                        { Type = 'TECH_SAILING', Era = 'ERA_ANCIENT', Description = 'Sailing' },
                        { Type = 'TECH_PHILOSOPHY', Era = 'ERA_CLASSICAL', Description = 'Philosophy' },
                        { Type = 'TECH_THEOLOGY', Era = 'ERA_MEDIEVAL', Description = 'Theology' },
                        { Type = 'TECH_FUTURE', Era = 'ERA_FUTURE', Description = 'Secret' } }),
  Technology_PrereqTechs = info({ { TechType = 'TECH_WRITING', PrereqTech = 'TECH_POTTERY' },
                                  { TechType = 'TECH_PHILOSOPHY', PrereqTech = 'TECH_WRITING' },
                                  { TechType = 'TECH_THEOLOGY', PrereqTech = 'TECH_PHILOSOPHY' },
                                  { TechType = 'TECH_THEOLOGY', PrereqTech = 'TECH_WRITING' } }),
  Resources = info({ { Type = 'RESOURCE_FISH', ResourceClassType = 'RESOURCECLASS_BONUS' },
                     { Type = 'RESOURCE_WHEAT', ResourceClassType = 'RESOURCECLASS_BONUS' },
                     { Type = 'RESOURCE_GOLD', ResourceClassType = 'RESOURCECLASS_LUXURY', Happiness = 4 },
                     { Type = 'RESOURCE_HORSE', ResourceClassType = 'RESOURCECLASS_RUSH' },
                     { Type = 'RESOURCE_BANANA', ResourceClassType = 'RESOURCECLASS_BONUS' } }),
  Terrains = info({ { Type = 'TERRAIN_GRASS' }, { Type = 'TERRAIN_COAST' }, { Type = 'TERRAIN_DESERT' } }),
  Features = info({ { Type = 'FEATURE_FOREST' } }),
  Improvements = info({ { Type = 'IMPROVEMENT_FARM' }, { Type = 'IMPROVEMENT_MINE' }, { Type = 'IMPROVEMENT_LUMBERMILL' } }),
  Improvement_ResourceTypes = info({ { ImprovementType = 'IMPROVEMENT_FARM', ResourceType = 'RESOURCE_WHEAT' },
                                     { ImprovementType = 'IMPROVEMENT_MINE', ResourceType = 'RESOURCE_GOLD' } }),
  Builds = info({ { Type = 'BUILD_FARM', ImprovementType = 'IMPROVEMENT_FARM' },
                  { Type = 'BUILD_MINE', ImprovementType = 'IMPROVEMENT_MINE', PrereqTech = 'TECH_MINING' },
                  { Type = 'BUILD_LUMBERMILL', ImprovementType = 'IMPROVEMENT_LUMBERMILL' },
                  { Type = 'BUILD_ROAD', RouteType = 'ROUTE_ROAD' } }),
  BuildFeatures = info({ { BuildType = 'BUILD_FARM', FeatureType = 'FEATURE_FOREST', Remove = true } }),
  Routes = info({ { Type = 'ROUTE_ROAD', GoldMaintenance = 1 } }),
  Projects = info({}), Processes = info({}),
}
GameInfoTypes.TECH_MINING = 99

HAVE_TECH = { [0] = { TECH_POTTERY = true, TECH_WRITING = true }, [1] = { TECH_POTTERY = true } }
Teams = {}
for t = 0, 1 do
  Teams[t] = { IsHasTech = function(_, id) for k, v in pairs(HAVE_TECH[t]) do if GameInfoTypes[k] == id then return v end end return false end,
               IsAtWar = function(_, other) return other == 63 end, IsHasMet = function() return true end }
end

-- plots: x,y -> options
P = {}
function plot(x, y, o)
  o = o or {}
  local p = { o = o,
    GetX = function() return x end, GetY = function() return y end,
    IsRevealed = function() return o.revealed ~= false end,
    IsVisible = function() return o.revealed ~= false and o.fog ~= true end,
    GetTerrainType = function() return GameInfoTypes[o.terrain or 'TERRAIN_GRASS'] end,
    IsHills = function() return false end, IsWater = function() return o.water == true end,
    IsLake = function() return false end, IsRiver = function() return false end, IsCity = function() return o.city == true end,
    GetResourceType = function() return o.resource and GameInfoTypes[o.resource] or -1 end,
    GetRevealedImprovementType = function() return -1 end,
    GetRevealedOwner = function() return o.owner or -1 end,
    GetOwner = function() return o.owner or -1 end,
    IsBeingWorked = function() return o.worked == true end,
    GetWorkingCity = function() return o.owner == 0 and CITIES[1] or nil end,
    GetBuildTurnsLeft = function(_, b) return 4 end,
    CanHaveImprovement = function(_, imp) return o.can_have ~= false end,
    GetFeatureProduction = function() return 20 end,
    CalculateYield = function(_, i) return (o.yields or {})[i] or 0 end,
    GetYieldWithBuild = function(_, b, i) return ((o.yields or {})[i] or 0) + ((o.gain or {})[i] or 0) end,
  }
  p.GetFeatureType = function() return o.forest and GameInfoTypes.FEATURE_FOREST or -1 end
  if o.fog then
    for _, k in ipairs({ 'GetFeatureType', 'CalculateYield', 'GetYieldWithBuild', 'IsBeingWorked', 'GetOwner' }) do p[k] = forbidden(k) end
  end
  P[x .. ',' .. y] = p
  return p
end
for y = 0, 6 do for x = 0, 6 do plot(x, y) end end
plot(3, 3, { owner = 0, city = true })
plot(4, 3, { owner = 0, worked = true, water = true, terrain = 'TERRAIN_COAST', resource = 'RESOURCE_FISH', yields = { [0] = 3 } })
plot(2, 3, { owner = 0, resource = 'RESOURCE_WHEAT', yields = { [0] = 1 }, gain = { [0] = 1 } })
plot(3, 4, { owner = 0, worked = true, forest = true, yields = { [0] = 1, [1] = 1 }, gain = { [0] = 1, [1] = -1 } })
plot(3, 2, { owner = 0, resource = 'RESOURCE_GOLD', terrain = 'TERRAIN_DESERT', yields = { [2] = 2 }, gain = { [1] = 1 } })
plot(4, 4, { fog = true, owner = 0 })
plot(5, 5, { owner = 1, yields = { [0] = 2 } })

Map = {
  GetPlot = function(x, y) return P[x .. ',' .. y] end,
  PlotDistance = function(x1, y1, x2, y2) return math.max(math.abs(x1 - x2), math.abs(y1 - y2)) end,
  PlotXYWithRangeCheck = function(x, y, dx, dy, r)
    if math.max(math.abs(dx), math.abs(dy)) > r then return nil end
    return P[(x + dx) .. ',' .. (y + dy)]
  end,
}

function city(id, owner, o)
  o = o or {}
  local c = { o = o }
  c.GetID = function() return id end
  c.GetName = function() return o.name or ('City' .. id) end
  c.GetOwner = function() return owner end
  c.IsPuppet = function() return o.puppet == true end
  c.GetProductionNameKey = function() return 'Warrior' end
  c.GetPopulation = function() return 4 end
  c.IsCoastal = function() return o.coastal == true end
  c.Plot = function() return P['3,3'] end
  c.CanTrain = function(_, id) local u = GameInfo.Units[id]; return (o.trainable or {})[u.Type] == true end
  c.CanConstruct = function(_, id) local b = GameInfo.Buildings[id]; return (o.buildable or {})[b.Type] == true end
  c.GetUnitProductionNeeded = function(_, id) return 40 + id end
  c.GetUnitProduction = function(_, id) return id == GameInfoTypes.UNIT_WORKER and 12 or 0 end
  c.GetUnitProductionTurnsLeft = function() return 7 end
  c.GetBuildingProductionNeeded = function(_, id) return 60 + id end
  c.GetBuildingProduction = function() return 0 end
  c.GetBuildingProductionTurnsLeft = function() return 12 end
  c.GetUnitPurchaseCost = function(_, id) return 200 end
  c.GetBuildingPurchaseCost = function(_, id) return 150 end
  c.GetUnitFaithPurchaseCost = function() return 0 end
  c.GetBuildingFaithPurchaseCost = function() return 0 end
  c.IsCanPurchase = function(_, test_cost, _, uid, bid, _, yield)
    if yield ~= YieldTypes.YIELD_GOLD then return false end
    local t = uid >= 0 and GameInfo.Units[uid].Type or GameInfo.Buildings[bid].Type
    if not (o.buyable or {})[t] then return false end
    return (not test_cost) or (uid >= 0 and 200 or 150) <= GOLD[owner]
  end
  c.GetNumBuilding = function(_, id) return (o.has or {})[GameInfo.Buildings[id].Type] and 1 or 0 end
  c.GetBaseYieldRate = function(_, i) return ({ [0] = 10, 5, 4, 6, 2, 0 })[i] end
  c.GetBaseYieldRateModifier = function(_, i) return i == 3 and 125 or 100 end
  c.GetCurrentProductionDifferenceTimes100 = function() return 500 end
  c.GetNumCityPlots = function() return 5 end
  local mine = { P['3,3'], P['4,3'], P['2,3'], P['3,4'], P['3,2'] }
  c.GetCityIndexPlot = function(_, i) return mine[i + 1] end
  CITIES[id] = c
  return c
end
CITIES, GOLD = {}, { [0] = 180, [1] = 50 }
city(1, 0, { name = 'Venice', coastal = true, has = { BUILDING_MONUMENT = true },
             trainable = { UNIT_WORKER = true }, buildable = { BUILDING_LIBRARY = true, BUILDING_GRANARY = true },
             buyable = { UNIT_WORKER = true, BUILDING_LIBRARY = true, BUILDING_GRANARY = true } })
city(2, 0, { name = 'Wittenberg', puppet = true, trainable = { UNIT_WORKER = true }, buyable = { UNIT_WORKER = true } })
city(3, 1, { name = 'Karakorum', trainable = { UNIT_SETTLER = true } })
city(4, 1, { name = 'Puppetgrad', puppet = true })

UNITS = {}
Players = {}
for pid = 0, 1 do
  Players[pid] = {
    GetTeam = function() return pid end,
    GetCivilizationType = function() return pid end,
    GetCivilizationShortDescription = function() return pid == 0 and 'Venice' or 'Mongolia' end,
    MayNotAnnex = function() return pid == 0 end,
    IsBarbarian = function() return false end, IsMinorCiv = function() return false end, IsAlive = function() return true end,
    GetCityByID = function(_, id) local c = CITIES[id]; return (c and c:GetOwner() == pid) and c or nil end,
    Cities = function() local l = {}; for _, c in pairs(CITIES) do if c:GetOwner() == pid then l[#l + 1] = c end end
                        local i = 0; return function() i = i + 1; return l[i] end end,
    GetGold = function() return GOLD[pid] end, GetFaith = function() return 0 end,
    CalculateUnitCost = function() return 3 end, GetNumUnits = function() return 6 end,
    GetNumResourceAvailable = function(_, res) return 0 end,
    GetBuildingClassCount = function() return 0 end,
    GetScience = function() return 10 end, GetCurrentResearch = function() return GameInfoTypes.TECH_SAILING end,
    GetResearchCost = function(_, id) return 100 + 10 * id end,
    GetResearchProgress = function(_, id) return id == GameInfoTypes.TECH_PHILOSOPHY and 30 or 0 end,
    CanResearch = function(_, id) return id == GameInfoTypes.TECH_SAILING or id == GameInfoTypes.TECH_PHILOSOPHY end,
    CanEverResearch = function(_, id) return id ~= GameInfoTypes.TECH_FUTURE end,
    GetResearchTurnsLeft = function() return 9 end,
    GetUnitByID = function(_, id) return UNITS[id] end,
    Units = function() return function() return nil end end,
  }
end
Players[63] = { IsBarbarian = function() return true end, IsAlive = function() return true end, GetTeam = function() return 63 end,
                Units = function() local l = BARBS; local i = 0; return function() i = i + 1; return l[i] end end }
BARBS = {}
Game = { GetGameTurn = function() return 42 end, GetActivePlayer = function() return 0 end,
         IsBuildingClassMaxedOut = function() return false end,
         GetResourceUsageType = function(res) return res == GameInfoTypes.RESOURCE_GOLD and 2 or (res == GameInfoTypes.RESOURCE_HORSE and 1 or 0) end }
GameDefines = {}

UNITS[7] = { GetX = function() return 3 end, GetY = function() return 3 end, GetUnitType = function() return GameInfoTypes.UNIT_WORKER end,
             WorkRate = function() return 100 end,
             CanBuild = function(_, pl, b)
               local t = GameInfo.Builds[b].Type
               if t == 'BUILD_ROAD' or t == 'BUILD_MINE' and pl:GetResourceType() ~= GameInfoTypes.RESOURCE_GOLD then return false end
               if t == 'BUILD_LUMBERMILL' then return false end
               return pl.o.owner == 0 and not pl.o.city and not pl.o.water
             end }
H.tech_grant_index = function() return {} end
H.tech_buttons = function(tech) if tech.Type == 'TECH_PHILOSOPHY' then return { { kind = 'building', type = 'BUILDING_TEMPLE', name = 'Temple' } } end return {} end
"""


class CompareLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_production_refusals_name_the_rule_they_found(self):
        self.run_lua("""
        local r = H.compare_production(1, { 'UNIT_SETTLER', 'UNIT_TRIREME', 'UNIT_HORSEMAN', 'BUILDING_MONUMENT',
                                            'BUILDING_UNIVERSITY', 'BUILDING_MYSTERY', 'UNIT_NOPE' }, 0, false)
        assert(r.ok and r.turn == 42 and r.city.name == 'Venice' and r.city.production_per_turn == 5, 'context')
        local by = {}; for _, row in ipairs(r.rows) do by[row.item] = row end
        assert(by.UNIT_SETTLER.can_produce == false)
        assert(by.UNIT_SETTLER.why[1]:find('NoAnnexing'), by.UNIT_SETTLER.why[1])
        assert(by.UNIT_TRIREME.why[1]:find('Sailing'), 'the tech by its name')
        assert(by.UNIT_HORSEMAN.why[1]:find('needs 1 RESOURCE_HORSE %(0 available%)'), by.UNIT_HORSEMAN.why[1])
        assert(by.BUILDING_MONUMENT.why[1] == 'already built in this city')
        assert(by.BUILDING_UNIVERSITY.why[1] == 'needs BUILDING_LIBRARY in this city', by.BUILDING_UNIVERSITY.why[1])
        assert(by.BUILDING_MYSTERY.why_unknown == true and by.BUILDING_MYSTERY.why[1]:find('names no rule'), 'unknown is said')
        assert(by.UNIT_NOPE.err:find('not a unit'), 'an unknown name is an error row, not a crash')
        assert(r.restrictions[1]:find('Venice'), 'the civ restriction is at the top')
        """)

    def test_prices_only_where_the_buy_button_exists_and_the_treasury_gap(self):
        self.run_lua("""
        local r = H.compare_production(1, { 'UNIT_WORKER', 'BUILDING_LIBRARY', 'UNIT_SETTLER' }, 0, true)
        local w, l, s = r.rows[1], r.rows[2], r.rows[3]
        assert(w.can_produce and w.turns == 7 and w.stored == 12 and w.cost == 41, 'engine cost, stored, turns')
        assert(w.gold == 200 and w.gold_can_buy == false and w.gold_short == 20, 'listed but 20 short')
        assert(w.maintenance.gold == nil and w.maintenance.note:find('empire%-wide'), 'unit upkeep is not a zero')
        assert(w.help == 'Builds improvements.', 'full adds the game help')
        assert(l.gold == 150 and l.gold_can_buy == true and l.gold_short == nil)
        assert(l.maintenance.gold == 1)
        assert(s.gold == nil and s.gold_can_buy == nil, 'no buy button, no price')
        assert(r.treasury.gold == 180 and r.unit_upkeep.gold_per_turn == 3)
        """)

    def test_estimate_formula_and_conditional_rows(self):
        self.run_lua("""
        local r = H.compare_production(1, { 'BUILDING_LIBRARY', 'BUILDING_UNIVERSITY', 'BUILDING_GRANARY', 'BUILDING_LIGHTHOUSE' }, 0, false)
        local lib, uni, gra, lh = r.rows[1], r.rows[2], r.rows[3], r.rows[4]
        -- science: base 6 at 125%; library adds 0.5 x pop 4 = 2 -> (6 + 2) x 1.25 - 7.5 = 2.5
        assert(lib.effects.yields_per_pop.science == 0.5 and lib.estimated_change.science == 2.5, tostring(lib.estimated_change.science))
        -- university: +50% -> 6 x 1.75 - 7.5 = 3
        assert(uni.effects.yield_percent.science == 50 and uni.estimated_change.science == 3)
        -- granary: +2 flat, +1 per worked wheat (wheat is owned, not worked) -> +2 food
        assert(gra.estimated_change.food == 2)
        local wheat, banana
        for _, c in ipairs(gra.conditional) do
          if c.when:find('WHEAT') then wheat = c end
          if c.when:find('BANANA') then banana = c end
        end
        assert(wheat.worked_now == 0 and wheat.owned_unworked == 1 and banana.owned_unworked == 0)
        -- lighthouse: the fish tile is a worked sea plot with fish -> +2 food
        assert(lh.estimated_change.food == 2, tostring(lh.estimated_change.food))
        assert(lh.effects == nil, 'no flat effects: absent, never an empty list')
        """)

    def test_a_trade_unit_is_refused_by_the_route_cap_when_every_slot_has_one(self):
        # live t139: Venice, four trade units on four routes, the caravan came back "names no rule"
        self.run_lua("""
        local trade = { IsTrade = function() return true end }
        Players[0].Units = function() local l = { trade, trade }; local i = 0; return function() i = i + 1; return l[i] end end
        Players[0].GetNumInternationalTradeRoutesAvailable = function() return 2 end
        local r = H.compare_production(1, { 'UNIT_CARAVAN' }, 0, false)
        local row = r.rows[1]
        assert(row.can_produce == false and row.why[1]:find('every trade%-route slot already has a caravan'), H.json(row))
        assert(row.why[1]:find('2 of 2'), row.why[1])
        Players[0].GetNumInternationalTradeRoutesAvailable = function() return 3 end
        r = H.compare_production(1, { 'UNIT_CARAVAN' }, 0, false)
        assert(r.rows[1].why_unknown == true, 'room for one more: the cap is not the rule, and no other is named: ' .. H.json(r.rows[1]))
        """)

    def test_a_venice_puppet_is_purchase_only_and_other_puppets_are_refused(self):
        self.run_lua("""
        local r = H.compare_production(2, { 'UNIT_WORKER' }, 0, false)
        assert(r.ok and r.purchase_only and r.producing == 'Warrior')
        local w = r.rows[1]
        assert(w.can_produce == false and w.turns == nil and w.gold == 200, 'buy button kept, turns gone')
        assert(w.why[1]:find('puppet'))
        local m = H.compare_production(4, { 'UNIT_WORKER' }, 1, false)
        assert(m.ok == false and m.err:find('annex first'), 'a puppet of a civ that may annex is refused')
        local k = H.compare_production(3, { 'UNIT_SETTLER' }, 1, false)
        assert(k.rows[1].can_produce == true and k.restrictions == nil, 'Mongolia trains settlers')
        assert(H.compare_production(3, { 'UNIT_WORKER' }, 0, false).ok == false, 'not your city')
        """)

    def test_research_path_and_status(self):
        self.run_lua("""
        local r = H.compare_research({ 'TECH_WRITING', 'TECH_SAILING', 'TECH_PHILOSOPHY', 'TECH_THEOLOGY', 'TECH_FUTURE', 'TECH_NOPE' }, 1)
        assert(r.science_per_turn == 10 and r.current == 'TECH_SAILING')
        local w, s, ph, th, fu, no = table.unpack(r.rows)
        assert(s.status == 'current' and s.turns == 9 and s.cost == 120)
        assert(ph.status == 'available' and ph.progress == 30 and ph.unlocks[1].type == 'BUILDING_TEMPLE')
        assert(w.status == 'locked' and w.missing_prereqs == nil or #w.missing_prereqs == 0, 'writing needs only pottery, which seat 1 has')
        assert(th.status == 'locked' and #th.missing_prereqs == 2, 'writing and philosophy, each once')
        assert(th.missing_prereqs[1] == 'TECH_WRITING' and th.missing_prereqs[2] == 'TECH_PHILOSOPHY', 'ancestors first')
        -- writing 110 + philosophy 130 - 30 stored + theology 140
        assert(th.path_beakers == 350, tostring(th.path_beakers))
        assert(fu.status == 'never' and fu.why[1]:find('never'))
        assert(no.err == 'not a tech type')
        local v = H.compare_research({ 'TECH_WRITING' }, 0)
        assert(v.rows[1].status == 'researched' and v.rows[1].cost == nil)
        """)

    def test_improvements_tile_versus_empire_fog_and_connections(self):
        self.run_lua("""
        local r = H.compare_improvements(7, {}, {}, 0)
        assert(r.ok and r.unit.work_rate == 100)
        local by = {}; for _, row in ipairs(r.rows) do by[row.x .. ',' .. row.y .. ' ' .. row.build] = row end
        local wheat = by['2,3 BUILD_FARM']
        assert(wheat.tile_change.food == 1 and wheat.empire_change == nil and wheat.empire_note:find('no city works'))
        assert(wheat.connects == nil, 'a bonus resource is never connected')
        local forest = by['3,4 BUILD_FARM']
        assert(forest.empire_change.food == 1 and forest.empire_change.production == -1, 'worked: the gain reaches the empire')
        assert(forest.removes == 'FOREST' and forest.chop_production == 20)
        local gold = by['3,2 BUILD_MINE']
        assert(gold.connects.resource == 'GOLD' and gold.connects.usage == 'luxury' and gold.connects.happiness_if_first == 4)
        assert(by['4,4 BUILD_FARM'] == nil, 'no build is read on a fogged plot')
        local fogged
        for _, p in ipairs(r.plots) do if p.x == 4 and p.y == 4 then fogged = p end end
        assert(fogged.note:find('fog') and fogged.yields_now == nil)
        assert(by['2,3 BUILD_ROAD'] == nil, 'roads only when asked')
        """)

    def test_improvements_asked_builds_carry_their_refusal(self):
        self.run_lua("""
        P['2,3'].o.can_have = false
        local r = H.compare_improvements(7, { { 2, 3 }, { 9, 9 } }, { 'BUILD_MINE', 'BUILD_LUMBERMILL', 'BUILD_ROAD' }, 0)
        local by = {}; for _, row in ipairs(r.rows) do by[row.build] = row end
        assert(by.BUILD_MINE.legal == false and by.BUILD_MINE.why[1]:find('MINING') or by.BUILD_MINE.why[1]:find('Mining'))
        assert(by.BUILD_LUMBERMILL.why[1]:find('cannot have it'))
        assert(by.BUILD_ROAD.why_unknown == true)
        assert(r.plots[2].err == 'off the map')
        assert(H.compare_improvements(99, {}, {}, 0).ok == false)
        """)

    def test_trade_hazards_count_fog_and_never_say_safe(self):
        self.run_lua("""
        UNITS[8] = { GetX = function() return 3 end, GetY = function() return 3 end, GetPlot = function() return P['3,3'] end }
        P['3,3'].GetPlotCity = function() return CITIES[1] end
        H.available_trade_routes = function() return {
          { x = 5, y = 5, kind = 'international', gold = 6, science = 1, target_player_id = 1, details = 'long hover' },
          { x = 1, y = 1, kind = 'food', food = 4, target_player_id = 0 } } end
        P['6,6'].o.fog = true
        P['6,6'].IsVisible = function() return false end
        local barb = { IsCombatUnit = function() return true end, GetPlot = function() return P['1,0'] end,
                       GetX = function() return 1 end, GetY = function() return 0 end, IsInvisible = function() return false end,
                       GetUnitType = function() return GameInfoTypes.UNIT_HORSEMAN end }
        BARBS[1] = barb
        local r = H.compare_trade_routes(8, 0, 2)
        assert(r.ok and r.origin.name == 'Venice')
        local far, near = r.rows[1], r.rows[2]
        assert(far.distance == 2 and far.hazard.danger == 'none_visible' and far.hazard.not_visible >= 1)
        assert(near.hazard.danger == 'visible_threat' and near.hazard.hostile_units[1].owner == 'Barbarians')
        H.available_trade_routes = function() return { ok = false, err = 'not a trade unit (caravan or cargo ship)' } end
        assert(H.compare_trade_routes(8, 0, 2).err:find('not a trade unit'))
        """)


class CompareValidationTests(unittest.TestCase):
    def test_arguments_are_checked_with_what_to_pass(self):
        cases = [
            ({"kind": "cities"}, "kind must be"),
            ({"kind": "production", "candidates": ["UNIT_WORKER"]}, "city_id"),
            ({"kind": "production", "city_id": 1}, "available_production"),
            ({"kind": "research"}, "available_research"),
            ({"kind": "improvements"}, "unit_id"),
            ({"kind": "trade", "unit_id": 3, "candidates": ["X"]}, "takes no candidates"),
            ({"kind": "research", "candidates": ["T"] * 2}, "repeat"),
            ({"kind": "research", "candidates": [f"T{i}" for i in range(9)]}, "at most 8"),
            ({"kind": "research", "candidates": ["T"], "sort": "gold"}, "order of candidates"),
            ({"kind": "trade", "unit_id": 3, "sort": "happiness"}, "sort must be"),
            ({"kind": "trade", "unit_id": 3, "limit": 0}, "limit"),
            ({"kind": "trade", "unit_id": 3, "plots": [[1, 2]]}, "plots is for kind='improvements'"),
            ({"kind": "improvements", "unit_id": 3, "plots": [[1]]}, "[x, y]"),
            ({"kind": "trade", "unit_id": 3, "detail": "normal"}, "detail"),
        ]
        for kw, needle in cases:
            with self.subTest(kw=kw):
                self.assertIn(needle, C.validate(**kw))
        self.assertIsNone(C.validate("improvements", unit_id=3, plots=[[1, 2]], candidates=["BUILD_FARM"], sort="food"))

    def test_lua_calls(self):
        self.assertEqual(C.lua_call("production", 0, city_id=5, candidates=["UNIT_WORKER"], detail="full"),
                         'return H.compare_production(5, {"UNIT_WORKER"}, 0, true)')
        self.assertEqual(C.lua_call("improvements", 1, unit_id=7, plots=[[1, 2]], candidates=[]),
                         "return H.compare_improvements(7, {{1,2}}, {}, 1)")
        self.assertEqual(C.lua_call("trade", 0, unit_id=9), "return H.compare_trade_routes(9, 0, 2)")
        self.assertEqual(C.lua_call("research", 0, candidates=['A"B']), 'return H.compare_research({"A\\"B"}, 0)')


class CompareShapeTests(unittest.TestCase):
    ARGS = {"pid": 0, "city_id": 5, "unit_id": 7, "candidates": []}

    def test_production_context_sources_and_omitted(self):
        raw = {"ok": True, "turn": 42, "city": {"id": 5, "name": "Venice"}, "treasury": {"gold": 10},
               "rows": [{"item": "UNIT_WORKER", "kind": "unit", "maintenance": {"note": "x"}},
                        {"item": "BUILDING_GRANARY", "kind": "building", "maintenance": {"gold": 1},
                         "conditional": [{"when": "a", "worked_now": 0, "owned_unworked": 0},
                                         {"when": "b", "worked_now": 1, "owned_unworked": 0}]},
                        {"item": "BUILDING_LIBRARY", "kind": "building"}]}
        out = C.shape("production", raw, self.ARGS, limit=2)
        self.assertEqual(out["context"], {"seat": 0, "turn": 42, "city": {"id": 5, "name": "Venice"}})
        self.assertEqual((out["n"], out["returned"]), (3, 2))
        self.assertEqual(out["rows"][0]["maintenance"]["gold"], "unknown")
        self.assertEqual(out["rows"][1]["conditional"], [{"when": "b", "worked_now": 1, "owned_unworked": 0}])
        self.assertEqual(out["rows"][1]["conditional_not_here"], 1)
        self.assertEqual(out["omitted"]["args"], {"kind": "production", "city_id": 5, "candidates": ["BUILDING_LIBRARY"]})
        self.assertIn("turns", out["sources"])
        self.assertTrue(any("estimated_change" in a for a in out["assumptions"]))

    def test_research_path_turns_and_unlock_names(self):
        raw = {"ok": True, "turn": 42, "science_per_turn": 8, "current": "TECH_X",
               "rows": [{"tech": "TECH_A", "status": "locked", "path_beakers": 255,
                         "unlocks": [{"kind": "building", "type": "BUILDING_MINT", "name": "Mint"}]},
                        {"tech": "TECH_B", "status": "locked", "path_beakers": 10}]}
        out = C.shape("research", raw, self.ARGS)
        self.assertEqual(out["rows"][0]["path_turns_estimate"], 32)
        self.assertEqual(out["rows"][0]["unlocks"], ["Mint (building)"])
        raw["science_per_turn"] = 0
        self.assertEqual(C.shape("research", raw, self.ARGS)["rows"][1]["path_turns_estimate"], "unknown")
        full = C.shape("research", dict(raw, science_per_turn=8), self.ARGS, detail="full")
        self.assertIsInstance(full["rows"][0]["unlocks"][0], dict)
        raw["rows"][0]["missing_prereqs"] = [f"TECH_{i}" for i in range(18)]
        short = C.shape("research", raw, self.ARGS)["rows"][0]
        self.assertEqual((len(short["missing_prereqs"]), short["missing_prereqs_count"]), (6, 18))
        self.assertEqual(len(C.shape("research", raw, self.ARGS, detail="full")["rows"][0]["missing_prereqs"]), 18)

    def test_improvements_sort_limit_and_plots(self):
        raw = {"ok": True, "turn": 42, "unit": {"id": 7},
               "plots": [{"x": 1, "y": 1}, {"x": 2, "y": 2}, {"x": 3, "y": 3}, {"x": 9, "y": 9, "err": "off the map"}],
               "rows": [{"x": 1, "y": 1, "build": "BUILD_FARM", "legal": True, "tile_change": {"food": 1}, "turns": 5},
                        {"x": 2, "y": 2, "build": "BUILD_MINE", "legal": True, "tile_change": {"production": 1}, "turns": 3},
                        {"x": 3, "y": 3, "build": "BUILD_FARM", "legal": True, "tile_change": {"food": 2}, "turns": 6}]}
        out = C.shape("improvements", json.loads(json.dumps(raw)), self.ARGS, sort="food", limit=2)
        self.assertEqual([(r["x"], r["build"]) for r in out["rows"]], [(3, "BUILD_FARM"), (1, "BUILD_FARM")])
        self.assertEqual([(p["x"], p["y"]) for p in out["plots"]], [(1, 1), (3, 3), (9, 9)])
        self.assertEqual(out["omitted"]["args"], {"kind": "improvements", "unit_id": 7, "plots": [[2, 2]]})
        self.assertEqual(out["omitted"]["rows"], [[2, 2, "BUILD_MINE"]])
        by_turns = C.shape("improvements", json.loads(json.dumps(raw)), self.ARGS, sort="turns")
        self.assertEqual([r["turns"] for r in by_turns["rows"]], [3, 5, 6])
        empty = C.shape("improvements", {"ok": True, "rows": [], "plots": []}, self.ARGS)
        self.assertIn("no legal build", empty["note"])

    def test_trade_sort_hazard_note_and_summary_drops_hover(self):
        raw = {"ok": True, "turn": 42, "radius": 2, "unit": {"id": 7},
               "rows": [{"x": 1, "gold": 3, "distance": 9, "details": "hover",
                         "hazard": {"danger": "none_visible", "not_visible": 4, "plots": 13, "hostile_units": []}},
                        {"x": 2, "gold": 7, "distance": 4, "details": "hover",
                         "hazard": {"danger": "visible_threat", "not_visible": 0, "plots": 13,
                                    "hostile_units": [{"unit": "A"}] * 5}}]}
        out = C.shape("trade", json.loads(json.dumps(raw)), self.ARGS, sort="gold")
        self.assertEqual([r["x"] for r in out["rows"]], [2, 1])
        self.assertNotIn("details", out["rows"][0])
        self.assertEqual(len(out["rows"][0]["hazard"]["hostile_units"]), 3)
        self.assertEqual(out["rows"][0]["hazard"]["hostile_units_more"], 2)
        self.assertIn("4 of 13 plots within 2 are not visible", out["rows"][1]["hazard"]["note"])
        full = C.shape("trade", json.loads(json.dumps(raw)), self.ARGS, sort="distance", detail="full", limit=1)
        self.assertEqual(full["rows"][0]["details"], "hover")
        self.assertEqual(full["omitted"]["count"], 1)

    def test_a_refusal_passes_through(self):
        self.assertEqual(C.shape("trade", {"ok": False, "err": "x"}, self.ARGS), {"ok": False, "err": "x"})
        self.assertFalse(C.shape("trade", None, self.ARGS)["ok"])


class CompareGameTests(unittest.TestCase):
    def test_game_validates_then_reads_once(self):
        g = Game.__new__(Game)
        g.seat = 1
        seen = []
        g.q = lambda code, timeout=None: seen.append(code) or {"ok": True, "turn": 3, "rows": []}
        self.assertFalse(g.compare("production", candidates=["UNIT_WORKER"])["ok"])
        self.assertEqual(seen, [], "a bad call never reaches the game")
        out = g.compare("research", candidates=["TECH_WRITING"])
        self.assertEqual(seen, ['return H.compare_research({"TECH_WRITING"}, 1)'])
        self.assertEqual(out["context"]["seat"], 1)

    def test_the_tool_is_a_read(self):
        from harness import mcp_server
        self.assertIn("compare", mcp_server.READ_TOOLS)
        self.assertTrue(callable(mcp_server.compare))


if __name__ == "__main__":
    unittest.main()
