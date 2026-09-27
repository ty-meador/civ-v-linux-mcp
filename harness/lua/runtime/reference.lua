---------------------------------------------------------------- reference: the rule book (v216)
-- Every static sentence the stock UI shows in a hover or under a button -- what a unit, building,
-- wonder, project, process, promotion, policy, technology, belief, resource, terrain, feature,
-- improvement, specialist or unit action does -- read once from this game's own database (GameInfo,
-- so mods and DLC are honoured) instead of repeated on every row of every answer. harness/reference.py
-- renders it as Markdown; the MCP tool `reference`, the resource civ5://reference and HTTP GET
-- /reference serve it. Nothing here is per player or per turn, so no visibility question arises: it
-- is the civilopedia, which every seat may read at any time.
local YIELD_SHORT = { YIELD_FOOD = "food", YIELD_PRODUCTION = "production", YIELD_GOLD = "gold",
                      YIELD_SCIENCE = "science", YIELD_CULTURE = "culture", YIELD_FAITH = "faith" }

-- Rows of a GameInfo table in a stable order. The game's tables are callable (a database cursor);
-- a plain Lua table (tests, or a table someone indexed by id) is walked by ascending key instead.
local function ref_each(tbl)
  if tbl == nil then return function() return nil end end
  local ok, iter = pcall(tbl)
  if ok and type(iter) == "function" then return iter end
  if type(tbl) ~= "table" then return function() return nil end end
  local keys = {}
  for k in pairs(tbl) do keys[#keys + 1] = k end
  table.sort(keys, function(a, b)
    if type(a) == type(b) and type(a) == "number" then return a < b end
    return tostring(a) < tostring(b)
  end)
  local i = 0
  return function() i = i + 1; local k = keys[i]; if k ~= nil then return tbl[k] end end
end

-- A row's ID, or the key it sits under when the table is a plain one without ID columns.
local function ref_id(tbl, row)
  if type(row.ID) == "number" then return row.ID end
  if type(tbl) == "table" then for k, v in pairs(tbl) do if v == row then return k end end end
end

-- One pass over a yield-change table (Terrain_Yields, Improvement_Yields, ...): key -> {yield = n}.
-- One pass, not one per row of the parent table: GameInfo iteration is a database cursor.
local function yields_by(tbl, field)
  local out = {}
  for row in ref_each(GameInfo and GameInfo[tbl]) do
    if type(row) == "table" and row[field] and type(row.Yield) == "number" and row.Yield ~= 0 then
      local k = YIELD_SHORT[row.YieldType] or row.YieldType
      local y = out[row[field]] or {}
      y[k] = (y[k] or 0) + row.Yield
      out[row[field]] = y
    end
  end
  return out
end

-- One pass over a link table: key -> list of the other column's values.
local function lists_by(tbl, field, other)
  local out = {}
  for row in ref_each(GameInfo and GameInfo[tbl]) do
    if type(row) == "table" and row[field] and row[other] and row[other] ~= "" then
      local l = out[row[field]] or {}
      l[#l + 1] = row[other]
      out[row[field]] = l
    end
  end
  return out
end

local function num_or_nil(v) if type(v) == "number" and v ~= 0 then return v end end
local function pos_or_nil(v) if type(v) == "number" and v > 0 then return v end end
local function str_or_nil(v) if type(v) == "string" and v ~= "" then return v end end
local function flag_or_nil(v) if v == true or v == 1 then return true end end

-- The action rows whose sentence is computed per unit and therefore stays on the action row
-- (H.action_help); the reference names them so a reader knows where to look.
local COMPUTED_ACTION_HELP = {
  COMMAND_UPGRADE = "the action row names the unit it upgrades to and the gold price",
  COMMAND_DELETE = "the action row names the gold refunded",
  MISSION_GOLDEN_AGE = "the action row names the golden age length",
  INTERFACEMODE_PARADROP = "the action row names the drop range",
  MISSION_ALERT = "the action row says so when this unit can never fortify and will sleep instead",
}

local REFERENCE_SECTIONS = { "terrain", "resources", "improvements", "units", "buildings", "projects",
                             "processes", "promotions", "policies", "techs", "beliefs", "specialists", "actions" }
H.reference_sections = REFERENCE_SECTIONS

local reference_build = {}

reference_build.terrain = function()
  local out = { terrains = {}, features = {} }
  local ty = yields_by("Terrain_Yields", "TerrainType")
  for t in ref_each(GameInfo.Terrains) do
    if type(t) == "table" and t.Type then
      out.terrains[#out.terrains + 1] = {
        type = t.Type, name = plain_name(t.Description), yields = ty[t.Type],
        movement = num_or_nil(t.Movement), defense = num_or_nil(t.DefenseModifier),
        water = flag_or_nil(t.Water), impassable = flag_or_nil(t.Impassable),
      }
    end
  end
  local fy = yields_by("Feature_YieldChanges", "FeatureType")
  for f in ref_each(GameInfo.Features) do
    if type(f) == "table" and f.Type then
      out.features[#out.features + 1] = {
        type = f.Type, name = plain_name(f.Description), yields = fy[f.Type], help = plain_name(f.Help),
        movement = num_or_nil(f.Movement), defense = num_or_nil(f.Defense),
        impassable = flag_or_nil(f.Impassable), natural_wonder = flag_or_nil(f.NaturalWonder),
        no_city = flag_or_nil(f.NoCity),
      }
    end
  end
  return out
end

reference_build.resources = function()
  local out = {}
  local imps = lists_by("Improvement_ResourceTypes", "ResourceType", "ImprovementType")
  for r in ref_each(GameInfo.Resources) do
    if type(r) == "table" and r.Type then
      local id = ref_id(GameInfo.Resources, r)
      local hover = (id ~= nil and resource_hover(id)) or {}
      out[#out + 1] = {
        type = r.Type, name = plain_name(r.Description), class = short(str_or_nil(r.ResourceClassType)),
        happiness = hover.happiness, improved_yields = hover.improved_yields, help = hover.help,
        tech_reveal = str_or_nil(r.TechReveal), tech_use = str_or_nil(r.TechCityTrade),
        improvements = imps[r.Type],
      }
    end
  end
  return out
end

reference_build.improvements = function()
  local out = {}
  local iy = yields_by("Improvement_Yields", "ImprovementType")
  local res = lists_by("Improvement_ResourceTypes", "ImprovementType", "ResourceType")
  local build_tech, build_type = {}, {}
  for b in ref_each(GameInfo.Builds) do
    if type(b) == "table" and str_or_nil(b.ImprovementType) then
      build_tech[b.ImprovementType] = str_or_nil(b.PrereqTech)
      build_type[b.ImprovementType] = b.Type
    end
  end
  for i in ref_each(GameInfo.Improvements) do
    if type(i) == "table" and i.Type then
      out[#out + 1] = {
        type = i.Type, name = plain_name(i.Description), help = plain_name(i.Help),
        yields = iy[i.Type], resources = res[i.Type], build = build_type[i.Type], tech = build_tech[i.Type],
        defense = num_or_nil(i.DefenseModifier), pillage_gold = num_or_nil(i.PillageGold),
        fresh_water = flag_or_nil(i.FreshWaterMakesValid) or flag_or_nil(i.RequiresFreshWater),
        barbarian_camp = flag_or_nil(i.BarbarianCamp), goody_hut = flag_or_nil(i.GoodyHut),
      }
    end
  end
  return out
end

reference_build.units = function()
  local out = {}
  for u in ref_each(GameInfo.Units) do
    if type(u) == "table" and u.Type then
      out[#out + 1] = {
        type = u.Type, name = plain_name(u.Description), help = plain_name(u.Help), strategy = plain_name(u.Strategy),
        cost = pos_or_nil(u.Cost), faith_cost = pos_or_nil(u.FaithCost),
        strength = pos_or_nil(u.Combat), ranged_strength = pos_or_nil(u.RangedCombat), range = pos_or_nil(u.Range),
        moves = pos_or_nil(u.Moves), domain = short(str_or_nil(u.Domain)), combat_class = short(str_or_nil(u.CombatClass)),
        tech = str_or_nil(u.PrereqTech), obsolete_tech = str_or_nil(u.ObsoleteTech),
        requirements = plain_name(u.Requirements),
      }
    end
  end
  return out
end

reference_build.buildings = function()
  local out = {}
  local by = yields_by("Building_YieldChanges", "BuildingType")
  local wonder = {}
  for c in ref_each(GameInfo.BuildingClasses) do
    if type(c) == "table" and c.Type then
      if c.MaxGlobalInstances == 1 then wonder[c.Type] = "world"
      elseif c.MaxPlayerInstances == 1 then wonder[c.Type] = "national" end
    end
  end
  for b in ref_each(GameInfo.Buildings) do
    if type(b) == "table" and b.Type then
      out[#out + 1] = {
        type = b.Type, name = plain_name(b.Description), help = plain_name(b.Help), strategy = plain_name(b.Strategy),
        cost = pos_or_nil(b.Cost), faith_cost = pos_or_nil(b.FaithCost), gold_maintenance = num_or_nil(b.GoldMaintenance),
        happiness = num_or_nil(b.Happiness), yields = by[b.Type], tech = str_or_nil(b.PrereqTech),
        wonder = b.BuildingClass and wonder[b.BuildingClass] or nil,
        specialist = short(str_or_nil(b.SpecialistType)), specialist_slots = pos_or_nil(b.SpecialistCount),
        great_work_slots = pos_or_nil(b.GreatWorkCount),
      }
    end
  end
  return out
end

reference_build.projects = function()
  local out = {}
  for p in ref_each(GameInfo.Projects) do
    if type(p) == "table" and p.Type then
      out[#out + 1] = { type = p.Type, name = plain_name(p.Description), help = plain_name(p.Help),
                        cost = pos_or_nil(p.Cost), tech = str_or_nil(p.TechPrereq) }
    end
  end
  return out
end

reference_build.processes = function()
  local out = {}
  for p in ref_each(GameInfo.Processes) do
    if type(p) == "table" and p.Type then
      out[#out + 1] = { type = p.Type, name = plain_name(p.Description), help = plain_name(p.Help),
                        tech = str_or_nil(p.TechPrereq) }
    end
  end
  return out
end

reference_build.promotions = function()
  local out = {}
  for p in ref_each(GameInfo.UnitPromotions) do
    if type(p) == "table" and p.Type then
      out[#out + 1] = { type = p.Type, name = plain_name(p.Description), help = plain_name(p.Help) }
    end
  end
  return out
end

reference_build.policies = function()
  local out = { branches = {}, policies = {} }
  for br in ref_each(GameInfo.PolicyBranchTypes) do
    if type(br) == "table" and br.Type then
      out.branches[#out.branches + 1] = {
        type = br.Type, name = plain_name(br.Description), help = plain_name(br.Help),
        era = str_or_nil(br.EraPrereq), ideology = flag_or_nil(br.PurchaseByLevel),
      }
    end
  end
  for pol in ref_each(GameInfo.Policies) do
    if type(pol) == "table" and pol.Type then
      out.policies[#out.policies + 1] = {
        type = pol.Type, name = plain_name(pol.Description), help = plain_name(pol.Help),
        branch = str_or_nil(pol.PolicyBranchType), level = pos_or_nil(pol.Level),
      }
    end
  end
  return out
end

reference_build.techs = function()
  local out = {}
  local prereqs = lists_by("Technology_PrereqTechs", "TechType", "PrereqTech")
  for t in ref_each(GameInfo.Technologies) do
    if type(t) == "table" and t.Type then
      out[#out + 1] = {
        type = t.Type, name = plain_name(t.Description), help = plain_name(t.Help),
        era = short(str_or_nil(t.Era)), cost = pos_or_nil(t.Cost), prereqs = prereqs[t.Type],
      }
    end
  end
  return out
end

reference_build.beliefs = function()
  local out = {}
  for b in ref_each(GameInfo.Beliefs) do
    if type(b) == "table" and b.Type then
      local kind = (flag_or_nil(b.Pantheon) and "pantheon") or (flag_or_nil(b.Founder) and "founder")
        or (flag_or_nil(b.Follower) and "follower") or (flag_or_nil(b.Enhancer) and "enhancer")
        or (flag_or_nil(b.Reformation) and "reformation") or nil
      out[#out + 1] = { type = b.Type, name = plain_name(b.ShortDescription), kind = kind,
                        description = plain_name(b.Description) }
    end
  end
  return out
end

reference_build.specialists = function()
  local out = {}
  local sy = yields_by("SpecialistYields", "SpecialistType")
  for s in ref_each(GameInfo.Specialists) do
    if type(s) == "table" and s.Type then
      out[#out + 1] = {
        type = s.Type, name = plain_name(s.Description), yields = sy[s.Type],
        great_person_points = pos_or_nil(s.GreatPeopleRateChange),
        great_person = short(str_or_nil(s.GreatPeopleUnitClass)),
      }
    end
  end
  return out
end

reference_build.actions = function()
  local out = {}
  if GameInfoActions then
    for i = 0, #GameInfoActions do
      local a = GameInfoActions[i]
      if type(a) == "table" and type(a.Type) == "string" and not a.Type:match("^CONTROL_") and a.Type ~= "COMMAND_HOTKEY" then
        local kind = (a.Type:match("^MISSION_") and "mission") or (a.Type:match("^BUILD_") and "build")
          or (a.Type:match("^COMMAND_") and "command") or (a.Type:match("^AUTOMATE_") and "automate")
          or (a.Type:match("^INTERFACEMODE_") and "interface") or nil
        if kind then
          local help = H.action_static_help(a.Type, a.Help)
          local computed = COMPUTED_ACTION_HELP[a.Type]
          if help or computed then
            out[#out + 1] = { type = a.Type, kind = kind, name = plain_name(a.TextKey), help = help, computed = computed }
          end
        end
      end
    end
  end
  -- The targeted missions (H.targeted_missions) come from InterfaceModes, with their own Help column.
  for row in ref_each(GameInfo and GameInfo.InterfaceModes) do
    if type(row) == "table" and row.Type and str_or_nil(row.Mission) then
      local help = H.action_static_help(row.Type, row.Help)
      local computed = COMPUTED_ACTION_HELP[row.Type]
      if help or computed then
        out[#out + 1] = { type = row.Type, kind = "interface", mission = row.Mission, help = help, computed = computed }
      end
    end
  end
  return out
end

-- section = nil: everything, keyed by section name, in `order`. One name: just that section's rows.
-- A section that fails is reported in `errors`, not fatal: one odd mod table must not lose the book.
function H.reference(section)
  if section ~= nil then
    local build = reference_build[section]
    if not build then
      return { ok = false, err = "unknown reference section " .. tostring(section), sections = REFERENCE_SECTIONS }
    end
    local ok, rows = pcall(build)
    if not ok then return { ok = false, err = "reference section " .. section .. " failed: " .. tostring(rows) } end
    return { ok = true, section = section, rows = rows }
  end
  local out = { ok = true, sections = {}, order = REFERENCE_SECTIONS, runtime = RUNTIME_VERSION }
  for _, name in ipairs(REFERENCE_SECTIONS) do
    local ok, rows = pcall(reference_build[name])
    if ok then out.sections[name] = rows
    else out.errors = out.errors or {}; out.errors[name] = tostring(rows) end
  end
  return out
end

-- Shared with later fragments, which import these at their top (load order: harness/runtime_source.py MANIFEST).
H._ns.YIELD_SHORT = YIELD_SHORT
H._ns.lists_by = lists_by
H._ns.ref_each = ref_each
H._ns.str_or_nil = str_or_nil
