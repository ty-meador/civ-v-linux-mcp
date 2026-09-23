"""The icons on a tech-tree button, for this civilization, not the paragraph alone.

techbuttoninclude.lua draws our unit and building (the class default, or our unique), a revealed
resource, and the ability the column turns on. Another civ's unique is not a button. England's
Ship of the Line does not appear for the Shoshone, and Portugal's Feitoria does not either.
"""
import unittest

import test_mcp_safety as support

WORLD = r"""
Locale = { ConvertTextKey = function(k)
  local names = {
    TXT_KEY_UNIT_FRIGATE = "Frigate",
    TXT_KEY_UNIT_FRIGATE_HELP = "Renaissance warship.",
    TXT_KEY_UNIT_PRIVATEER = "Privateer",
    TXT_KEY_UNIT_SHIPOFTHELINE = "Ship of the Line",
    TXT_KEY_UNIT_CAVALRY = "Cavalry",
    TXT_KEY_UNIT_SHOSHONE_COMANCHE_RIDERS = "Comanche Riders",
    TXT_KEY_BUILDING_SEAPORT = "Seaport",
    TXT_KEY_BUILDING_SEAPORT_HELP = "+1 Production from sea resources.",
    TXT_KEY_RESOURCE_IRON = "Iron",
    TXT_KEY_BUILD_FEITORIA = "Construct a Feitoria",
    TXT_KEY_TECH_NAVIGATION_HELP = "Allows the [COLOR_POSITIVE_TEXT]Frigate[ENDCOLOR].",
    TXT_KEY_ALLOWS_EMBARKING = "Allows embarking.",
    TXT_KEY_ALLOWS_CROSSING_OCEANS = "Allows crossing oceans.",
    TXT_KEY_FASTER_EMBARKED_MOVEMENT = "Faster embarked movement.",
    TXT_KEY_ALLOWS_BRIDGES = "Allows bridges.",
    TXT_KEY_ADDITIONAL_INTERNATIONAL_TRADE_ROUTE = "An additional trade route.",
    TXT_KEY_REVEALS_RESOURCE_ON_MAP = "Reveals the resource.",
  }
  return names[k] or k
end }

local function iter(rows)
  local i = 0
  return function() i = i + 1; return rows[i] end
end

GameInfo = {
  Civilizations = { [0] = { Type = "CIVILIZATION_SHOSHONE" }, [1] = { Type = "CIVILIZATION_PORTUGAL" } },
  UnitClasses = function() return iter({
    { Type = "UNITCLASS_FRIGATE", DefaultUnit = "UNIT_FRIGATE" },
    { Type = "UNITCLASS_PRIVATEER", DefaultUnit = "UNIT_PRIVATEER" },
    { Type = "UNITCLASS_CAVALRY", DefaultUnit = "UNIT_CAVALRY" },
  }) end,
  Civilization_UnitClassOverrides = function() return iter({
    { CivilizationType = "CIVILIZATION_SHOSHONE", UnitClassType = "UNITCLASS_CAVALRY",
      UnitType = "UNIT_SHOSHONE_COMANCHE_RIDERS" },
    { CivilizationType = "CIVILIZATION_ENGLAND", UnitClassType = "UNITCLASS_FRIGATE",
      UnitType = "UNIT_ENGLISH_SHIPOFTHELINE" },
  }) end,
  Units = function() return iter({
    { ID = 10, Type = "UNIT_FRIGATE", Class = "UNITCLASS_FRIGATE", PrereqTech = "TECH_NAVIGATION",
      Description = "TXT_KEY_UNIT_FRIGATE", Help = "TXT_KEY_UNIT_FRIGATE_HELP",
      Cost = 185, Combat = 25, RangedCombat = 28, Range = 2, Moves = 5, Domain = "DOMAIN_SEA" },
    { ID = 11, Type = "UNIT_ENGLISH_SHIPOFTHELINE", Class = "UNITCLASS_FRIGATE", PrereqTech = "TECH_NAVIGATION",
      Description = "TXT_KEY_UNIT_SHIPOFTHELINE", Cost = 170, Combat = 30, RangedCombat = 28, Range = 2,
      Moves = 5, Domain = "DOMAIN_SEA" },
    { ID = 12, Type = "UNIT_PRIVATEER", Class = "UNITCLASS_PRIVATEER", PrereqTech = "TECH_NAVIGATION",
      Description = "TXT_KEY_UNIT_PRIVATEER", Cost = 150, Combat = 20, Moves = 4, Domain = "DOMAIN_SEA" },
    { ID = 13, Type = "UNIT_CAVALRY", Class = "UNITCLASS_CAVALRY", PrereqTech = "TECH_MILITARY_SCIENCE",
      Description = "TXT_KEY_UNIT_CAVALRY", Cost = 225, Combat = 34, Moves = 4, Domain = "DOMAIN_LAND" },
    { ID = 14, Type = "UNIT_SHOSHONE_COMANCHE_RIDERS", Class = "UNITCLASS_CAVALRY",
      PrereqTech = "TECH_MILITARY_SCIENCE", Description = "TXT_KEY_UNIT_SHOSHONE_COMANCHE_RIDERS",
      Cost = 225, Combat = 34, Moves = 4, Domain = "DOMAIN_LAND" },
  }) end,
  BuildingClasses = function() return iter({
    { Type = "BUILDINGCLASS_SEAPORT", DefaultBuilding = "BUILDING_SEAPORT" },
  }) end,
  Civilization_BuildingClassOverrides = function() return iter({}) end,
  Buildings = function() return iter({
    { ID = 20, Type = "BUILDING_SEAPORT", BuildingClass = "BUILDINGCLASS_SEAPORT",
      PrereqTech = "TECH_NAVIGATION", Description = "TXT_KEY_BUILDING_SEAPORT",
      Help = "TXT_KEY_BUILDING_SEAPORT_HELP", Cost = 120, GoldMaintenance = 1 },
  }) end,
  Resources = function() return iter({
    { ID = 3, Type = "RESOURCE_IRON", Description = "TXT_KEY_RESOURCE_IRON", TechReveal = "TECH_BRONZE_WORKING" },
  }) end,
  Improvements = function() return iter({
    { Type = "IMPROVEMENT_FEITORIA", CivilizationType = "CIVILIZATION_PORTUGAL" },
  }) end,
  Builds = function() return iter({
    { Type = "BUILD_FEITORIA", PrereqTech = "TECH_NAVIGATION", ShowInTechTree = true,
      ImprovementType = "IMPROVEMENT_FEITORIA", Description = "TXT_KEY_BUILD_FEITORIA" },
  }) end,
  Technologies = setmetatable({
    TECH_NAVIGATION = { ID = 1, Type = "TECH_NAVIGATION", Era = "ERA_RENAISSANCE",
      Help = "TXT_KEY_TECH_NAVIGATION_HELP" },
    TECH_MILITARY_SCIENCE = { ID = 2, Type = "TECH_MILITARY_SCIENCE", Era = "ERA_INDUSTRIAL" },
    TECH_OPTICS = { ID = 3, Type = "TECH_OPTICS", Era = "ERA_ANCIENT", AllowsEmbarking = true },
    TECH_ASTRONOMY = { ID = 4, Type = "TECH_ASTRONOMY", Era = "ERA_RENAISSANCE",
      EmbarkedAllWaterPassage = true, EmbarkedMoveChange = 1 },
    TECH_ENGINEERING = { ID = 5, Type = "TECH_ENGINEERING", Era = "ERA_CLASSICAL",
      BridgeBuilding = true, InternationalTradeRoutesChange = 1 },
    TECH_BRONZE_WORKING = { ID = 6, Type = "TECH_BRONZE_WORKING", Era = "ERA_ANCIENT" },
  }, { __call = function(t)
    local rows = { t.TECH_NAVIGATION, t.TECH_MILITARY_SCIENCE, t.TECH_OPTICS, t.TECH_ASTRONOMY,
                   t.TECH_ENGINEERING, t.TECH_BRONZE_WORKING }
    return iter(rows)
  end }),
}
GameInfo.Technologies[1] = GameInfo.Technologies.TECH_NAVIGATION
GameInfo.Technologies[2] = GameInfo.Technologies.TECH_MILITARY_SCIENCE
GameInfo.Technologies[3] = GameInfo.Technologies.TECH_OPTICS

local function player(civ_id)
  return {
    GetTeam = function() return 0 end,
    GetCivilizationType = function() return civ_id end,
    GetCurrentResearch = function() return 1 end,
    CanResearch = function(_, id) return id == 1 or id == 2 or id == 3 end,
    CanEverResearch = function() return true end,
    GetResearchTurnsLeft = function() return 4 end,
    GetResearchCost = function() return 900 end,
    GetResearchProgress = function() return 10 end,
    GetQueuePosition = function() return -1 end,
    GetUnitProductionNeeded = function(_, id) return id == 10 and 185 or 100 end,
    GetBuildingProductionNeeded = function() return 120 end,
    IsAlive = function() return true end,
    IsMinorCiv = function() return false end,
  }
end
Players = { [0] = player(0), [1] = player(1) }
Teams = { [0] = { IsHasTech = function(_, id) return id == 4 or id == 5 or id == 6 end, GetTeam = function() return 0 end } }
GameDefines = { MAX_MAJOR_CIVS = 1 }
Game.GetNumResourceRequiredForUnit = function(uid, rid) return (uid == 10 and rid == 3) and 1 or 0 end
"""


class TechUnlockTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_shoshone_buttons_are_ours_and_not_someone_elses_unique(self):
        self.run_lua(r"""
        local r = H.tech_tree(0)
        assert(r.ok and r.current == "NAVIGATION")
        local by = {}
        for _, t in ipairs(r.techs) do by[t.tech] = t end
        -- Astronomy, Engineering, and Bronze Working are already researched.
        assert(by.TECH_ASTRONOMY == nil and by.TECH_ENGINEERING == nil)
        local nav = by.TECH_NAVIGATION
        assert(nav.help == "Allows the Frigate.", nav.help)
        local kinds = {}
        for _, b in ipairs(nav.unlocks) do kinds[#kinds + 1] = b.type or b.kind end
        assert(kinds[1] == "UNIT_FRIGATE", table.concat(kinds, ","))
        assert(kinds[2] == "UNIT_PRIVATEER")
        assert(kinds[3] == "BUILDING_SEAPORT")
        local joined = table.concat(kinds, ",")
        assert(not joined:find("SHIPOFTHELINE"), joined)
        assert(not joined:find("FEITORIA"), joined)
        assert(not joined:find("CAVALRY") or joined:find("COMANCHE"), joined)
        local fr = nav.unlocks[1]
        assert(fr.name == "Frigate" and fr.cost == 185 and fr.strength == 25)
        assert(fr.ranged_strength == 28 and fr.range == 2 and fr.moves == 5)
        assert(fr.help == "Renaissance warship.")
        assert(fr.resources[1].resource == "RESOURCE_IRON" and fr.resources[1].amount == 1)
        assert(nav.unlocks[3].name == "Seaport" and nav.unlocks[3].cost == 120)
        assert(nav.unlocks[3].gold_maintenance == 1)
        local mil = by.TECH_MILITARY_SCIENCE
        assert(#mil.unlocks == 1 and mil.unlocks[1].type == "UNIT_SHOSHONE_COMANCHE_RIDERS",
               mil.unlocks[1] and mil.unlocks[1].type)
        local opt = by.TECH_OPTICS
        assert(#opt.unlocks == 1 and opt.unlocks[1].ability == "embark")
        assert(opt.unlocks[1].text == "Allows embarking.")
        local iron = H.tech_buttons(GameInfo.Technologies.TECH_BRONZE_WORKING, H.tech_grant_index(0))
        assert(iron[1].kind == "resource" and iron[1].type == "RESOURCE_IRON")
        assert(iron[1].name == "Iron" and iron[1].text == "Reveals the resource.")
        """)

    def test_portugal_sees_the_feitoria_and_ability_order_matches_the_button_row(self):
        self.run_lua(r"""
        local por = H.tech_grant_index(1)
        local builds = por.build.TECH_NAVIGATION
        assert(builds and #builds == 1 and builds[1].type == "BUILD_FEITORIA", "feitoria is Portugal's button")
        local sho = H.tech_grant_index(0)
        assert(sho.build.TECH_NAVIGATION == nil)
        local ast = H.tech_buttons(GameInfo.Technologies.TECH_ASTRONOMY, {})
        assert(ast[1].ability == "faster_embarked_movement" and ast[2].ability == "ocean")
        local eng = H.tech_buttons(GameInfo.Technologies.TECH_ENGINEERING, {})
        assert(eng[1].ability == "bridges" and eng[2].ability == "trade_route" and eng[2].extra == 1)
        """)
