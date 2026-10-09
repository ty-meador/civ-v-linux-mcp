"""The rule book (runtime v216): static help printed once, not on every row.

Until v215 every chooser row carried its hover text -- the same Library blurb in every city's
`available_production` every turn, the same Salt blurb on every Salt tile of every `map_window`.
`H.reference()` reads the game's own database once; harness/reference.py renders it as Markdown;
the MCP tool `reference(section)`, the resources civ5://reference[/{section}] and HTTP GET /reference
serve it. The rows keep enums, names and live numbers.
"""
import os
import tempfile
from pathlib import Path
import unittest
from unittest import mock

import anyio

import test_mcp_safety as support
from harness import mcp_server as m
from harness.game import Game
from harness.reference import SECTIONS, TITLES, render_markdown


# GameInfo tables in the game are callable (a cursor) AND indexable by id; the mock does both.
WORLD = """
local function T(rows)
  local by = {}
  for _, r in ipairs(rows) do by[r.ID] = r; if r.Type then by[r.Type] = r end end
  return setmetatable(by, { __call = function() local i = 0; return function() i = i + 1; return rows[i] end end })
end
local TXT = {
  TXT_KEY_UNIT_WARRIOR = 'Warrior', TXT_KEY_UNIT_WARRIOR_HELP = 'Ancient era melee unit.',
  TXT_KEY_UNIT_WARRIOR_STRATEGY = 'Cheap, and the [COLOR_POSITIVE_TEXT]first[ENDCOLOR] escort.',
  TXT_KEY_UNIT_SETTLER = 'Settler', TXT_KEY_UNIT_SETTLER_HELP = 'Founds a new city.',
  TXT_KEY_BUILDING_LIBRARY = 'Library', TXT_KEY_BUILDING_LIBRARY_HELP = '+1 [ICON_RESEARCH] Science for every 2 [ICON_CITIZEN] Citizens.',
  TXT_KEY_BUILDING_PYRAMIDS = 'Pyramids', TXT_KEY_BUILDING_PYRAMIDS_HELP = '+25% Worker speed.[NEWLINE]Two free Workers.',
  TXT_KEY_TECH_POTTERY = 'Pottery', TXT_KEY_TECH_POTTERY_HELP = 'Allows the Granary and the Shrine.',
  TXT_KEY_TECH_WRITING = 'Writing', TXT_KEY_TECH_WRITING_HELP = 'Allows the Library.',
  TXT_KEY_POLICY_BRANCH_TRADITION = 'Tradition', TXT_KEY_POLICY_BRANCH_TRADITION_HELP = '+3 Culture in the capital.',
  TXT_KEY_POLICY_ARISTOCRACY = 'Aristocracy', TXT_KEY_POLICY_ARISTOCRACY_HELP = '+15% Production on Wonders.',
  TXT_KEY_POLICY_BRANCH_FREEDOM = 'Freedom', TXT_KEY_POLICY_CIVIL_SOCIETY = 'Civil Society',
  TXT_KEY_POLICY_CIVIL_SOCIETY_HELP = 'Specialists eat half.',
  TXT_KEY_BELIEF_GOD_OF_THE_SEA = 'God of the Sea', TXT_KEY_BELIEF_GOD_OF_THE_SEA_DESC = '+1 Production from Fishing Boats.',
  TXT_KEY_BELIEF_TITHE = 'Tithe', TXT_KEY_BELIEF_TITHE_DESC = '+1 Gold for every 4 followers.',
  TXT_KEY_RESOURCE_SALT = 'Salt', TXT_KEY_RESOURCE_SALT_HELP = 'A luxury.',
  TXT_KEY_TERRAIN_GRASS = 'Grassland', TXT_KEY_FEATURE_FOREST = 'Forest',
  TXT_KEY_IMPROVEMENT_MINE = 'Mine', TXT_KEY_IMPROVEMENT_MINE_HELP = 'Works hills and mineral resources.',
  TXT_KEY_PROMOTION_DRILL_1 = 'Drill I', TXT_KEY_PROMOTION_DRILL_1_HELP = '+15% Combat Strength in rough terrain.',
  TXT_KEY_PROJECT_APOLLO = 'Apollo Program', TXT_KEY_PROJECT_APOLLO_HELP = 'Allows spaceship parts.',
  TXT_KEY_PROCESS_WEALTH = 'Wealth', TXT_KEY_PROCESS_WEALTH_HELP = 'Converts 25% of production to gold.',
  TXT_KEY_SPECIALIST_SCIENTIST = 'Scientist',
  TXT_KEY_MISSION_FORTIFY = 'Fortify', TXT_KEY_MISSION_FORTIFY_HELP = 'Dig in: +50% defense.',
  TXT_KEY_COMMAND_UPGRADE = 'Upgrade', TXT_KEY_MISSION_DISCOVER_TECH_HELP = 'Discover a new technology.',
  TXT_KEY_INTERFACEMODE_RANGE_ATTACK_HELP = 'Attack a target at range.',
}
Locale = { ConvertTextKey = function(k) return TXT[k] or k end, Lookup = function(k) return TXT[k] or k end }
GameInfo = {
  Units = T{
    { ID = 0, Type = 'UNIT_WARRIOR', Description = 'TXT_KEY_UNIT_WARRIOR', Help = 'TXT_KEY_UNIT_WARRIOR_HELP',
      Strategy = 'TXT_KEY_UNIT_WARRIOR_STRATEGY', Cost = 40, Combat = 8, RangedCombat = 0, Range = 0, Moves = 2,
      Domain = 'DOMAIN_LAND', CombatClass = 'UNITCOMBAT_MELEE', PrereqTech = nil, ObsoleteTech = 'TECH_METAL_CASTING' },
    { ID = 1, Type = 'UNIT_SETTLER', Description = 'TXT_KEY_UNIT_SETTLER', Help = 'TXT_KEY_UNIT_SETTLER_HELP',
      Cost = 106, Combat = 0, Moves = 2, Domain = 'DOMAIN_LAND' },
  },
  Buildings = T{
    { ID = 0, Type = 'BUILDING_LIBRARY', Description = 'TXT_KEY_BUILDING_LIBRARY', Help = 'TXT_KEY_BUILDING_LIBRARY_HELP',
      Cost = 75, GoldMaintenance = 1, PrereqTech = 'TECH_WRITING', BuildingClass = 'BUILDINGCLASS_LIBRARY',
      SpecialistType = 'SPECIALIST_SCIENTIST', SpecialistCount = 1 },
    { ID = 1, Type = 'BUILDING_PYRAMIDS', Description = 'TXT_KEY_BUILDING_PYRAMIDS', Help = 'TXT_KEY_BUILDING_PYRAMIDS_HELP',
      Cost = 185, GoldMaintenance = 0, PrereqTech = 'TECH_MASONRY', BuildingClass = 'BUILDINGCLASS_PYRAMIDS' },
  },
  BuildingClasses = T{
    { ID = 0, Type = 'BUILDINGCLASS_LIBRARY', MaxGlobalInstances = -1, MaxPlayerInstances = -1 },
    { ID = 1, Type = 'BUILDINGCLASS_PYRAMIDS', MaxGlobalInstances = 1, MaxPlayerInstances = -1 },
  },
  Building_YieldChanges = T{ { ID = 0, BuildingType = 'BUILDING_LIBRARY', YieldType = 'YIELD_SCIENCE', Yield = 1 } },
  Technologies = T{
    { ID = 0, Type = 'TECH_POTTERY', Description = 'TXT_KEY_TECH_POTTERY', Help = 'TXT_KEY_TECH_POTTERY_HELP', Era = 'ERA_ANCIENT', Cost = 35 },
    { ID = 1, Type = 'TECH_WRITING', Description = 'TXT_KEY_TECH_WRITING', Help = 'TXT_KEY_TECH_WRITING_HELP', Era = 'ERA_ANCIENT', Cost = 55 },
  },
  Technology_PrereqTechs = T{ { ID = 0, TechType = 'TECH_WRITING', PrereqTech = 'TECH_POTTERY' } },
  PolicyBranchTypes = T{
    { ID = 0, Type = 'POLICY_BRANCH_TRADITION', Description = 'TXT_KEY_POLICY_BRANCH_TRADITION', Help = 'TXT_KEY_POLICY_BRANCH_TRADITION_HELP', EraPrereq = 'ERA_ANCIENT' },
    { ID = 1, Type = 'POLICY_BRANCH_FREEDOM', Description = 'TXT_KEY_POLICY_BRANCH_FREEDOM', PurchaseByLevel = true },
  },
  Policies = T{
    { ID = 0, Type = 'POLICY_ARISTOCRACY', Description = 'TXT_KEY_POLICY_ARISTOCRACY', Help = 'TXT_KEY_POLICY_ARISTOCRACY_HELP', PolicyBranchType = 'POLICY_BRANCH_TRADITION' },
    { ID = 1, Type = 'POLICY_CIVIL_SOCIETY', Description = 'TXT_KEY_POLICY_CIVIL_SOCIETY', Help = 'TXT_KEY_POLICY_CIVIL_SOCIETY_HELP', PolicyBranchType = 'POLICY_BRANCH_FREEDOM', Level = 2 },
  },
  Beliefs = T{
    { ID = 0, Type = 'BELIEF_GOD_OF_THE_SEA', ShortDescription = 'TXT_KEY_BELIEF_GOD_OF_THE_SEA', Description = 'TXT_KEY_BELIEF_GOD_OF_THE_SEA_DESC', Pantheon = true },
    { ID = 1, Type = 'BELIEF_TITHE', ShortDescription = 'TXT_KEY_BELIEF_TITHE', Description = 'TXT_KEY_BELIEF_TITHE_DESC', Founder = 1 },
  },
  Resources = T{ { ID = 0, Type = 'RESOURCE_SALT', Description = 'TXT_KEY_RESOURCE_SALT', Help = 'TXT_KEY_RESOURCE_SALT_HELP',
                   ResourceClassType = 'RESOURCECLASS_LUXURY', Happiness = 4, TechCityTrade = 'TECH_MINING' } },
  Resource_YieldChanges = T{ { ID = 0, ResourceType = 'RESOURCE_SALT', YieldType = 'YIELD_GOLD', Yield = 1 },
                             { ID = 1, ResourceType = 'RESOURCE_SALT', YieldType = 'YIELD_FOOD', Yield = 1 } },
  Improvement_ResourceTypes = T{ { ID = 0, ImprovementType = 'IMPROVEMENT_MINE', ResourceType = 'RESOURCE_SALT' } },
  Terrains = T{ { ID = 0, Type = 'TERRAIN_GRASS', Description = 'TXT_KEY_TERRAIN_GRASS', Movement = 1, DefenseModifier = 0, Water = false } },
  Terrain_Yields = T{ { ID = 0, TerrainType = 'TERRAIN_GRASS', YieldType = 'YIELD_FOOD', Yield = 2 } },
  Features = T{ { ID = 0, Type = 'FEATURE_FOREST', Description = 'TXT_KEY_FEATURE_FOREST', Movement = 2, Defense = 25 } },
  Feature_YieldChanges = T{ { ID = 0, FeatureType = 'FEATURE_FOREST', YieldType = 'YIELD_PRODUCTION', Yield = 1 },
                            { ID = 1, FeatureType = 'FEATURE_FOREST', YieldType = 'YIELD_FOOD', Yield = -1 } },
  Improvements = T{ { ID = 0, Type = 'IMPROVEMENT_MINE', Description = 'TXT_KEY_IMPROVEMENT_MINE', Help = 'TXT_KEY_IMPROVEMENT_MINE_HELP', PillageGold = 10 } },
  Improvement_Yields = T{ { ID = 0, ImprovementType = 'IMPROVEMENT_MINE', YieldType = 'YIELD_PRODUCTION', Yield = 1 } },
  Builds = T{ { ID = 0, Type = 'BUILD_MINE', ImprovementType = 'IMPROVEMENT_MINE', PrereqTech = 'TECH_MINING', Time = 600 } },
  UnitPromotions = T{ { ID = 0, Type = 'PROMOTION_DRILL_1', Description = 'TXT_KEY_PROMOTION_DRILL_1', Help = 'TXT_KEY_PROMOTION_DRILL_1_HELP' } },
  Projects = T{ { ID = 0, Type = 'PROJECT_APOLLO_PROGRAM', Description = 'TXT_KEY_PROJECT_APOLLO', Help = 'TXT_KEY_PROJECT_APOLLO_HELP', Cost = 750, TechPrereq = 'TECH_ROCKETRY' } },
  Processes = T{ { ID = 0, Type = 'PROCESS_WEALTH', Description = 'TXT_KEY_PROCESS_WEALTH', Help = 'TXT_KEY_PROCESS_WEALTH_HELP', TechPrereq = 'TECH_CURRENCY' } },
  Specialists = T{ { ID = 0, Type = 'SPECIALIST_SCIENTIST', Description = 'TXT_KEY_SPECIALIST_SCIENTIST', GreatPeopleRateChange = 3, GreatPeopleUnitClass = 'UNITCLASS_SCIENTIST' } },
  SpecialistYields = T{ { ID = 0, SpecialistType = 'SPECIALIST_SCIENTIST', YieldType = 'YIELD_SCIENCE', Yield = 3 } },
  InterfaceModes = T{ { ID = 0, Type = 'INTERFACEMODE_RANGE_ATTACK', Mission = 'MISSION_RANGE_ATTACK', Help = 'TXT_KEY_INTERFACEMODE_RANGE_ATTACK_HELP' } },
}
GameInfoActions = {
  [0] = { Type = 'MISSION_FORTIFY', TextKey = 'TXT_KEY_MISSION_FORTIFY', Help = 'TXT_KEY_MISSION_FORTIFY_HELP' },
  [1] = { Type = 'MISSION_SWAP_UNITS', Help = 'NONE' },
  [2] = { Type = 'COMMAND_UPGRADE', TextKey = 'TXT_KEY_COMMAND_UPGRADE', Help = 'NONE' },
  [3] = { Type = 'MISSION_DISCOVER', Help = 'TXT_KEY_WRONG' },
  [4] = { Type = 'CONTROL_NEXTUNIT', Help = 'TXT_KEY_MISSION_FORTIFY_HELP' },
}
"""


class ReferenceLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_the_whole_book_has_every_section_in_order(self):
        self.run_lua("""
        local r = H.reference()
        assert(r.ok and r.errors == nil, tostring(r.errors and next(r.errors)))
        assert(#r.order == 13 and r.order[1] == 'terrain' and r.order[13] == 'actions')
        for _, name in ipairs(r.order) do assert(r.sections[name] ~= nil, name) end
        assert(r.runtime == H.version)
        """)

    def test_units_and_buildings_carry_the_words_and_the_static_numbers(self):
        self.run_lua("""
        local u = H.reference('units').rows
        assert(#u == 2 and u[1].type == 'UNIT_WARRIOR' and u[1].name == 'Warrior')
        assert(u[1].help == 'Ancient era melee unit.' and u[1].strategy == 'Cheap, and the first escort.', tostring(u[1].strategy))
        assert(u[1].cost == 40 and u[1].strength == 8 and u[1].moves == 2 and u[1].domain == 'LAND' and u[1].combat_class == 'MELEE')
        assert(u[1].ranged_strength == nil and u[1].range == nil, 'zeros are left off')
        assert(u[1].obsolete_tech == 'TECH_METAL_CASTING' and u[2].strength == nil)
        local b = H.reference('buildings').rows
        assert(b[1].type == 'BUILDING_LIBRARY' and b[1].help == '+1 Science for every 2 Citizens.', tostring(b[1].help))
        assert(b[1].gold_maintenance == 1 and b[1].yields.science == 1 and b[1].tech == 'TECH_WRITING' and b[1].wonder == nil)
        assert(b[1].specialist == 'SCIENTIST' and b[1].specialist_slots == 1)
        assert(b[2].wonder == 'world' and b[2].gold_maintenance == nil and b[2].help:find('\\n'), 'NEWLINE kept as a line break')
        """)

    def test_techs_policies_beliefs_and_the_rest(self):
        self.run_lua("""
        local t = H.reference('techs').rows
        assert(t[2].type == 'TECH_WRITING' and t[2].help == 'Allows the Library.' and t[2].era == 'ANCIENT' and t[2].cost == 55)
        assert(t[2].prereqs[1] == 'TECH_POTTERY' and t[1].prereqs == nil)
        local p = H.reference('policies').rows
        assert(#p.branches == 2 and p.branches[1].help == '+3 Culture in the capital.' and p.branches[1].era == 'ERA_ANCIENT')
        assert(p.branches[2].ideology == true and p.branches[1].ideology == nil)
        assert(p.policies[2].branch == 'POLICY_BRANCH_FREEDOM' and p.policies[2].level == 2 and p.policies[1].level == nil)
        local be = H.reference('beliefs').rows
        assert(be[1].kind == 'pantheon' and be[1].name == 'God of the Sea' and be[1].description == '+1 Production from Fishing Boats.')
        assert(be[2].kind == 'founder')
        local r = H.reference('resources').rows[1]
        assert(r.name == 'Salt' and r.class == 'LUXURY' and r.happiness == 4 and r.help == 'A luxury.')
        assert(r.improved_yields.gold == 1 and r.improved_yields.food == 1 and r.tech_use == 'TECH_MINING')
        assert(r.improvements[1] == 'IMPROVEMENT_MINE')
        local ter = H.reference('terrain').rows
        assert(ter.terrains[1].name == 'Grassland' and ter.terrains[1].yields.food == 2 and ter.terrains[1].movement == 1 and ter.terrains[1].defense == nil)
        assert(ter.features[1].yields.production == 1 and ter.features[1].yields.food == -1 and ter.features[1].defense == 25)
        local imp = H.reference('improvements').rows[1]
        assert(imp.build == 'BUILD_MINE' and imp.tech == 'TECH_MINING' and imp.yields.production == 1 and imp.resources[1] == 'RESOURCE_SALT' and imp.pillage_gold == 10)
        assert(H.reference('promotions').rows[1].help == '+15% Combat Strength in rough terrain.')
        assert(H.reference('projects').rows[1].cost == 750 and H.reference('processes').rows[1].tech == 'TECH_CURRENCY')
        local s = H.reference('specialists').rows[1]
        assert(s.yields.science == 3 and s.great_person_points == 3 and s.great_person == 'SCIENTIST')
        """)

    def test_actions_keep_the_static_sentence_and_name_the_computed_ones(self):
        self.run_lua("""
        local a = H.reference('actions').rows
        local by = {}
        for _, row in ipairs(a) do by[row.type] = row end
        assert(by.MISSION_FORTIFY.help == 'Dig in: +50% defense.' and by.MISSION_FORTIFY.name == 'Fortify' and by.MISSION_FORTIFY.kind == 'mission')
        assert(by.MISSION_SWAP_UNITS == nil, 'NONE is not a sentence')
        assert(by.COMMAND_UPGRADE.help == nil and by.COMMAND_UPGRADE.computed:find('gold price'), 'computed lines are named, not printed')
        assert(by.MISSION_DISCOVER.help == 'Discover a new technology.', 'the panel key, not the action row')
        assert(by.CONTROL_NEXTUNIT == nil, 'global UI controls are not unit actions')
        assert(by.INTERFACEMODE_RANGE_ATTACK.help == 'Attack a target at range.' and by.INTERFACEMODE_RANGE_ATTACK.mission == 'MISSION_RANGE_ATTACK')
        """)

    def test_an_unknown_section_is_refused_with_the_list(self):
        self.run_lua("""
        local r = H.reference('wonders')
        assert(r.ok == false and r.err:find('wonders') and #r.sections == 13)
        """)

    def test_a_broken_table_loses_one_section_not_the_book(self):
        self.run_lua("""
        -- A row whose columns blow up on read (a mod's half-migrated table).
        local bad = setmetatable({ ID = 0, Type = 'BELIEF_BROKEN' }, { __index = function() error('mod table exploded') end })
        GameInfo.Beliefs = setmetatable({ [0] = bad }, { __call = function() local done = false
          return function() if done then return nil end; done = true; return bad end end })
        local r = H.reference()
        assert(r.ok and r.sections.units ~= nil and r.sections.beliefs == nil)
        assert(r.errors.beliefs:find('mod table exploded'), tostring(r.errors.beliefs))
        """)


SAMPLE = {
    "ok": True, "runtime": 216,
    "order": list(SECTIONS),
    "sections": {
        "terrain": {"terrains": [{"type": "TERRAIN_GRASS", "name": "Grassland", "yields": {"food": 2}, "movement": 1}],
                    "features": [{"type": "FEATURE_FOREST", "name": "Forest", "yields": {"production": 1, "food": -1}, "defense": 25}]},
        "resources": [{"type": "RESOURCE_SALT", "name": "Salt", "class": "LUXURY", "happiness": 4, "help": "A luxury.",
                       "improved_yields": {"gold": 1, "food": 1}, "improvements": ["IMPROVEMENT_MINE"], "tech_use": "TECH_MINING"}],
        "improvements": [{"type": "IMPROVEMENT_MINE", "name": "Mine", "build": "BUILD_MINE", "yields": {"production": 1}, "help": "Works hills."}],
        "units": [{"type": "UNIT_WARRIOR", "name": "Warrior", "cost": 40, "strength": 8, "moves": 2, "domain": "LAND",
                   "help": "Ancient era melee unit.", "strategy": "Cheap escort."}],
        "buildings": [{"type": "BUILDING_PYRAMIDS", "name": "Pyramids", "wonder": "world", "cost": 185, "help": "+25% Worker speed.\nTwo free Workers."}],
        "projects": [{"type": "PROJECT_APOLLO_PROGRAM", "name": "Apollo Program", "cost": 750, "help": "Allows spaceship parts."}],
        "processes": [{"type": "PROCESS_WEALTH", "name": "Wealth", "help": "Converts 25% of production to gold."}],
        "promotions": [{"type": "PROMOTION_DRILL_1", "name": "Drill I", "help": "+15% in rough terrain."}],
        "policies": {"branches": [{"type": "POLICY_BRANCH_TRADITION", "name": "Tradition", "help": "+3 Culture.", "era": "ERA_ANCIENT"},
                                  {"type": "POLICY_BRANCH_FREEDOM", "name": "Freedom", "ideology": True}],
                     "policies": [{"type": "POLICY_CIVIL_SOCIETY", "name": "Civil Society", "branch": "POLICY_BRANCH_FREEDOM", "level": 2, "help": "Specialists eat half."},
                                  {"type": "POLICY_ARISTOCRACY", "name": "Aristocracy", "branch": "POLICY_BRANCH_TRADITION", "help": "+15% on Wonders."}]},
        "techs": [{"type": "TECH_POTTERY", "name": "Pottery", "era": "ANCIENT", "cost": 35, "help": "Allows the Granary."},
                  {"type": "TECH_PHYSICS", "name": "Physics", "era": "MEDIEVAL", "cost": 485, "prereqs": ["TECH_ENGINEERING"], "help": "Allows the Trebuchet."}],
        "beliefs": [{"type": "BELIEF_TITHE", "name": "Tithe", "kind": "founder", "description": "+1 Gold per 4 followers."},
                    {"type": "BELIEF_GOD_OF_THE_SEA", "name": "God of the Sea", "kind": "pantheon", "description": "+1 Production from Fishing Boats."}],
        "specialists": [{"type": "SPECIALIST_SCIENTIST", "name": "Scientist", "yields": {"science": 3}, "great_person_points": 3, "great_person": "SCIENTIST"}],
        "actions": [{"type": "MISSION_FORTIFY", "kind": "mission", "name": "Fortify", "help": "Dig in."},
                    {"type": "COMMAND_UPGRADE", "kind": "command", "name": "Upgrade", "computed": "the action row names the unit it upgrades to and the gold price"}],
    },
}


class RenderMarkdownTests(unittest.TestCase):
    def test_the_whole_book_reads_top_to_bottom(self):
        md = render_markdown(SAMPLE)
        self.assertTrue(md.startswith("# Civilization V reference"))
        for name in SECTIONS:
            self.assertIn(f"## {TITLES[name]}", md)
        self.assertLess(md.index("## Terrain"), md.index("## Unit actions"), "sections come in the declared order")
        # A row: bold name, enum in code, stats, then the sentence.
        self.assertIn("- **Warrior** `UNIT_WARRIOR` — cost 40, strength 8, moves 2, land. Ancient era melee unit.", md)
        self.assertIn("  _Cheap escort._", md)
        self.assertIn("- **Pyramids** `BUILDING_PYRAMIDS` — World Wonder, cost 185. +25% Worker speed. Two free Workers.", md)
        self.assertIn("+2 food", md)
        self.assertIn("-1 food, +1 production", md)  # yields in the game's own order: food first
        self.assertIn("luxury, happiness +4, improved: +1 food, +1 gold, improved by IMPROVEMENT_MINE, usable with TECH_MINING. A luxury.", md)
        self.assertIn("### Freedom", md)
        self.assertIn("tenet level 2", md)
        self.assertIn("### Medieval", md)
        self.assertIn("after TECH_ENGINEERING", md)
        self.assertIn("### Pantheon", md)
        self.assertLess(md.index("### Pantheon"), md.index("### Founder"), "beliefs in slot order, not database order")
        self.assertIn("3 toward Scientist", md)
        self.assertIn("_the action row names the unit it upgrades to and the gold price_", md)
        self.assertIn("`reference(section=...)`", md)

    def test_one_section_is_just_that_heading(self):
        md = render_markdown(SAMPLE, "promotions")
        self.assertTrue(md.startswith("## Promotions"))
        self.assertIn("Drill I", md)
        self.assertNotIn("Warrior", md)
        self.assertNotIn("# Civilization V reference", md)

    def test_a_single_section_reply_from_lua_renders_too(self):
        md = render_markdown({"ok": True, "section": "units", "rows": SAMPLE["sections"]["units"]})
        self.assertTrue(md.startswith("## Units"))
        self.assertIn("Warrior", md)

    def test_unknown_section_and_lost_section(self):
        with self.assertRaises(ValueError) as cm:
            render_markdown(SAMPLE, "wonders")
        self.assertIn("promotions", str(cm.exception))
        broken = {**SAMPLE, "sections": {k: v for k, v in SAMPLE["sections"].items() if k != "beliefs"},
                  "errors": {"beliefs": "mod table exploded"}}
        md = render_markdown(broken)
        self.assertIn("## Beliefs", md)
        self.assertIn("could not be read from the game: mod table exploded", md)
        self.assertIn("## Units", md)

    def test_an_empty_section_says_so(self):
        md = render_markdown({**SAMPLE, "sections": {**SAMPLE["sections"], "projects": []}}, "projects")
        self.assertIn("nothing in this game's database", md)


class GameReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = mock.patch.dict(os.environ, {"CIV5_NOTES_DIR": os.path.join(self.tmp.name, "notes")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.g = Game.__new__(Game)
        self.g.seat = 0
        self.g.q = mock.Mock(return_value=SAMPLE)
        self.g.game_key = lambda: "Test-LLEADER-CCIV"

    def test_one_lua_read_per_process_then_cached(self):
        first = self.g.reference_markdown()
        self.assertIsInstance(first, str)
        self.assertIn("# Civilization V reference", first)
        again = self.g.reference_markdown("units")
        self.assertTrue(again.startswith("## Units"))
        self.assertEqual(self.g.q.call_count, 1, "the book is read from the game once and cached")
        self.assertEqual(self.g.q.call_args.args[0], "return H.reference()")

    def test_the_whole_book_is_saved_beside_the_notebooks_for_the_human(self):
        self.g.reference_markdown()
        path = os.path.join(self.tmp.name, "reference", "Test-LLEADER-CCIV.md")
        self.assertTrue(os.path.exists(path), path)
        self.assertIn("# Civilization V reference", Path(path).read_text())
        self.assertEqual(self.g.reference_path, path)

    def test_unknown_section_is_a_refusal_not_a_read(self):
        out = self.g.reference_markdown("wonders")
        self.assertEqual(out["ok"], False)
        self.assertIn("promotions", out["sections"])
        self.assertEqual(self.g.q.call_count, 0)

    def test_a_game_refusal_passes_through(self):
        self.g.q = mock.Mock(return_value={"ok": False, "err": "no InGame state"})
        out = self.g.reference_markdown()
        self.assertEqual(out, {"ok": False, "err": "no InGame state"})
        self.assertIsNone(getattr(self.g, "_reference", None), "a refusal is not cached")


class ServersExposeTheReferenceTests(unittest.TestCase):
    def test_mcp_tool_resource_and_template(self):
        self.assertIn("reference", m.ANYTIME_TOOLS, "the civilopedia is readable between turns")
        tools = {t.name for t in anyio.run(m.mcp.list_tools)}
        self.assertIn("reference", tools)
        resources = {str(r.uri) for r in anyio.run(m.mcp.list_resources)}
        self.assertIn("civ5://reference", resources)
        templates = {getattr(t, "uri_template", None) or getattr(t, "uriTemplate", None)
                     for t in anyio.run(m.mcp.list_resource_templates)}
        self.assertIn("civ5://reference/{section}", templates)

    def test_mcp_tool_returns_markdown_and_refuses_unknown_sections_as_json(self):
        fake = mock.Mock()
        fake.reference_markdown.side_effect = lambda s=None: (
            {"ok": False, "err": "unknown reference section 'x'", "sections": list(SECTIONS)} if s == "x" else "## Units\n\n- x")
        with mock.patch.object(m, "game", return_value=fake):
            self.assertEqual(m.reference.__wrapped__("units"), "## Units\n\n- x")
            self.assertIn('"ok":false', m.reference.__wrapped__("x"))


if __name__ == "__main__":
    unittest.main()
