-- Compact comparisons (#34): facts about a few caller-chosen candidates, side by side, in one read.
-- Each H.compare_* returns engine answers (costs, turns, legality, yields) and static table rows
-- (GameInfo) as separate fields; harness/compare.py adds the context, sources, sorting and limits.
-- Nothing here ranks candidates or calls one best, and nothing unknown is reported as zero: a
-- getter that fails leaves its field out, and a refusal whose rule this read cannot name says so.
local CMP = { YIELDS = { [0] = "food", "production", "gold", "science", "culture", "faith" } }

function CMP.num(fn)
  local ok, v = pcall(fn)
  if ok and type(v) == "number" then return v end
end

function CMP.turns(fn)
  local v = CMP.num(fn)
  if v and v > 0 and v < 100000 then return v end
end

function CMP.name(row) return row and row.Description and L(row.Description) or nil end

function CMP.round1(v) return math.floor(v * 10 + 0.5) / 10 end

-- The civ's own unit / building for each class (Civilization_*ClassOverrides over the class default).
function CMP.civ_classes(pid)
  local civ = civ_type_of(pid)
  return class_defaults(GameInfo.UnitClasses, "DefaultUnit", GameInfo.Civilization_UnitClassOverrides,
                        "UnitClassType", "UnitType", civ),
         class_defaults(GameInfo.BuildingClasses, "DefaultBuilding", GameInfo.Civilization_BuildingClassOverrides,
                        "BuildingClassType", "BuildingType", civ)
end

function CMP.rows(tbl, field, value)
  local out = {}
  for r in ref_each(GameInfo and GameInfo[tbl]) do
    if type(r) == "table" and r[field] == value then out[#out + 1] = r end
  end
  return out
end

function CMP.has_tech(team, tech)
  local id = tech and GameInfoTypes and GameInfoTypes[tech]
  if not id then return true end
  return Teams[team]:IsHasTech(id) and true or false
end

function CMP.tech_name(tech)
  local row = tech and GameInfo.Technologies[tech]
  return (row and CMP.name(row)) or tech
end

-- Gold and faith buttons of the city screen for one unit (uid) or building (bid); matched getter /
-- IsCanPurchase pairs as available_production uses (a mismatched pair crashed the game once).
function CMP.purchase(city, p, row, uid, bid)
  local gold_y = YieldTypes and YieldTypes.YIELD_GOLD or 2
  local faith_y = YieldTypes and YieldTypes.YIELD_FAITH or 5
  -- a price only where the city screen shows a buy button (cost test off: it shows while saving up)
  local okl, gold_listed = pcall(function() return city:IsCanPurchase(false, true, uid, bid, -1, gold_y) end)
  local gold = (okl and gold_listed) and CMP.num(function()
    if uid >= 0 then return city:GetUnitPurchaseCost(uid) end
    return city:GetBuildingPurchaseCost(bid)
  end) or nil
  if gold and gold > 0 then
    row.gold = gold
    local ok, can = pcall(function() return city:IsCanPurchase(true, true, uid, bid, -1, gold_y) end)
    row.gold_can_buy = (ok and can) and true or false
    local have = CMP.num(function() return p:GetGold() end)
    if have and have < gold then row.gold_short = gold - have end
  end
  local ok, listed = pcall(function() return city:IsCanPurchase(false, true, uid, bid, -1, faith_y) end)
  if ok and listed then
    local faith = CMP.num(function()
      if uid >= 0 then return city:GetUnitFaithPurchaseCost(uid, true) end
      return city:GetBuildingFaithPurchaseCost(bid)
    end)
    if faith and faith > 0 then
      row.faith = faith
      local ok2, now = pcall(function() return city:IsCanPurchase(true, true, uid, bid, -1, faith_y) end)
      row.faith_can_buy = (ok2 and now) and true or false
      local have = CMP.num(function() return p:GetFaith() end)
      if have and have < faith then row.faith_short = faith - have end
    end
  end
end

function CMP.unit_effects(u, p)
  local e = {}
  if type(u.Combat) == "number" and u.Combat > 0 then e.strength = u.Combat end
  if type(u.RangedCombat) == "number" and u.RangedCombat > 0 then e.ranged_strength = u.RangedCombat end
  if type(u.Range) == "number" and u.Range > 0 then e.range = u.Range end
  if type(u.Moves) == "number" and u.Moves > 0 then e.moves = u.Moves end
  e.domain = short(str_or_nil(u.Domain))
  local req = {}
  for r in ref_each(GameInfo.Unit_ResourceQuantityRequirements) do
    if type(r) == "table" and r.UnitType == u.Type and r.ResourceType then
      local res = GameInfo.Resources[r.ResourceType]
      local row = { resource = r.ResourceType, amount = r.Cost or 1 }
      if res and res.ID then row.available = CMP.num(function() return p:GetNumResourceAvailable(res.ID, true) end) end
      req[#req + 1] = row
    end
  end
  if #req > 0 then e.resources = req end
  return e
end

-- Why CanTrain said no, as far as the tables and getters name it.
function CMP.unit_why(u, city, p, pid, team, units_for_class)
  local why = {}
  local own = u.Class and units_for_class[u.Class]
  if u.Class and own ~= u.Type then
    if own then why[#why + 1] = "this civilization builds " .. own .. " in this class instead"
    else why[#why + 1] = "this civilization has no unit of this class" end
  end
  if u.PrereqTech and not CMP.has_tech(team, u.PrereqTech) then
    why[#why + 1] = "needs the tech " .. CMP.tech_name(u.PrereqTech)
  end
  if str_or_nil(u.ObsoleteTech) and CMP.has_tech(team, u.ObsoleteTech) then
    why[#why + 1] = "obsolete: " .. CMP.tech_name(u.ObsoleteTech) .. " is researched"
  end
  if flag_on(u.Found) then
    local ok, noannex = pcall(function() return p:MayNotAnnex() end)
    if ok and noannex then
      why[#why + 1] = "this civilization's trait forbids units that found cities (Traits.NoAnnexing, Venice)"
    end
  end
  if u.Domain == "DOMAIN_SEA" then
    local ok, coastal = pcall(function() return city:IsCoastal() end)
    if ok and not coastal then why[#why + 1] = "a sea unit needs a coastal city" end
  end
  for r in ref_each(GameInfo.Unit_ResourceQuantityRequirements) do
    if type(r) == "table" and r.UnitType == u.Type and r.ResourceType then
      local res = GameInfo.Resources[r.ResourceType]
      local have = res and res.ID and CMP.num(function() return p:GetNumResourceAvailable(res.ID, true) end)
      if have and have < (r.Cost or 1) then
        why[#why + 1] = "needs " .. (r.Cost or 1) .. " " .. r.ResourceType .. " (" .. have .. " available)"
      end
    end
  end
  return why
end

-- Flat, per-population and percent yields of a building, and the plot-conditional rows measured
-- against the tiles this city works now (and the other tiles it owns, which it could work).
function CMP.building_effects(b, city, pid)
  local e, cond = {}, {}
  local flat, per_pop, pct = {}, {}, {}
  for r in ref_each(GameInfo.Building_YieldChanges) do
    if type(r) == "table" and r.BuildingType == b.Type and type(r.Yield) == "number" and r.Yield ~= 0 then
      local k = YIELD_SHORT[r.YieldType] or r.YieldType
      flat[k] = (flat[k] or 0) + r.Yield
    end
  end
  for r in ref_each(GameInfo.Building_YieldChangesPerPop) do
    if type(r) == "table" and r.BuildingType == b.Type and type(r.Yield) == "number" and r.Yield ~= 0 then
      local k = YIELD_SHORT[r.YieldType] or r.YieldType
      per_pop[k] = (per_pop[k] or 0) + r.Yield / 100
    end
  end
  for r in ref_each(GameInfo.Building_YieldModifiers) do
    if type(r) == "table" and r.BuildingType == b.Type and type(r.Yield) == "number" and r.Yield ~= 0 then
      local k = YIELD_SHORT[r.YieldType] or r.YieldType
      pct[k] = (pct[k] or 0) + r.Yield
    end
  end
  if next(flat) then e.yields = flat end
  if next(per_pop) then e.yields_per_pop = per_pop end
  if next(pct) then e.yield_percent = pct end
  local happy = (tonumber(b.Happiness) or 0) + (tonumber(b.UnmoddedHappiness) or 0)
  if happy ~= 0 then e.happiness = happy end
  if type(b.Defense) == "number" and b.Defense > 0 then e.defense = b.Defense / 100 end
  if type(b.ExtraCityHitPoints) == "number" and b.ExtraCityHitPoints > 0 then e.city_hp = b.ExtraCityHitPoints end
  if str_or_nil(b.SpecialistType) and type(b.SpecialistCount) == "number" and b.SpecialistCount > 0 then
    e.specialists = { type = short(b.SpecialistType), slots = b.SpecialistCount }
  end
  if type(b.GreatWorkCount) == "number" and b.GreatWorkCount > 0 then
    e.great_work_slots = { type = short(str_or_nil(b.GreatWorkSlotType)), slots = b.GreatWorkCount }
  end
  local xp = {}
  for r in ref_each(GameInfo.Building_DomainFreeExperiences) do
    if type(r) == "table" and r.BuildingType == b.Type and type(r.Experience) == "number" then
      xp[short(r.DomainType) or "?"] = r.Experience
    end
  end
  if next(xp) then e.free_experience = xp end
  if not next(e) then e = nil end

  -- The city's plots, once: worked or merely owned, with what the conditional tables test.
  local plots = {}
  pcall(function()
    local n = city:GetNumCityPlots()
    for i = 0, n - 1 do
      local pl = city:GetCityIndexPlot(i)
      if pl and pl:GetOwner() == pid then
        plots[#plots + 1] = { worked = pl:IsBeingWorked() and true or false, resource = pl:GetResourceType(Players[pid]:GetTeam()),
                              feature = pl:GetFeatureType(), terrain = pl:GetTerrainType(), water = pl:IsWater(),
                              lake = pl.IsLake and pl:IsLake() or false, river = pl:IsRiver(), city = pl:IsCity() }
      end
    end
  end)
  local function count(test)
    local worked, owned = 0, 0
    for _, q in ipairs(plots) do
      if not q.city and test(q) then
        owned = owned + 1
        if q.worked then worked = worked + 1 end
      end
    end
    return worked, owned
  end
  local function add(tbl, key_field, label, test_of)
    for r in ref_each(GameInfo[tbl]) do
      if type(r) == "table" and r.BuildingType == b.Type and type(r.Yield) == "number" and r.Yield ~= 0 then
        local key = key_field and r[key_field]
        local test = test_of(key)
        if test then
          local worked, owned = count(test)
          cond[#cond + 1] = { when = label .. (key and (" " .. short(key)) or ""), yield = YIELD_SHORT[r.YieldType] or r.YieldType,
                              per_plot = r.Yield, worked_now = worked, owned_unworked = owned - worked }
        end
      end
    end
  end
  local function id_of(tbl, t) local row = t and GameInfo[tbl][t]; return row and row.ID end
  add("Building_ResourceYieldChanges", "ResourceType", "worked plot with", function(k)
    local id = id_of("Resources", k); return id and function(q) return q.resource == id end end)
  add("Building_FeatureYieldChanges", "FeatureType", "worked plot with", function(k)
    local id = id_of("Features", k); return id and function(q) return q.feature == id end end)
  add("Building_TerrainYieldChanges", "TerrainType", "worked plot of", function(k)
    local id = id_of("Terrains", k); return id and function(q) return q.terrain == id end end)
  add("Building_SeaPlotYieldChanges", nil, "worked sea plot", function()
    return function(q) return q.water and not q.lake end end)
  add("Building_LakePlotYieldChanges", nil, "worked lake plot", function()
    return function(q) return q.lake end end)
  add("Building_RiverPlotYieldChanges", nil, "worked river plot", function()
    return function(q) return q.river end end)
  add("Building_SeaResourceYieldChanges", nil, "worked sea resource", function()
    return function(q) return q.water and q.resource >= 0 end end)
  return e, cond, flat, per_pop, pct
end

-- Estimated change of the city's yields: (base + added) * (modifier% + building%) / 100 - now,
-- with `added` = flat + per-pop x population + conditional x tiles worked now. City yields only:
-- empire-level modifiers, policies and beliefs are not applied (compare.py says so).
function CMP.building_estimate(city, flat, per_pop, pct, cond)
  local added = {}
  for k, v in pairs(flat) do added[k] = (added[k] or 0) + v end
  local pop = CMP.num(function() return city:GetPopulation() end) or 0
  for k, v in pairs(per_pop) do added[k] = (added[k] or 0) + v * pop end
  for _, c in ipairs(cond) do added[c.yield] = (added[c.yield] or 0) + c.per_plot * c.worked_now end
  local out = {}
  for i = 0, 5 do
    local k = CMP.YIELDS[i]
    if (added[k] or 0) ~= 0 or (pct[k] or 0) ~= 0 then
      local base = CMP.num(function() return city:GetBaseYieldRate(i) end)
      local mod = CMP.num(function() return city:GetBaseYieldRateModifier(i) end)
      if base and mod then
        local now = base * mod / 100
        local after = (base + (added[k] or 0)) * (mod + (pct[k] or 0)) / 100
        out[k] = CMP.round1(after - now)
      end
    end
  end
  return next(out) and out or nil
end

function CMP.building_why(b, city, p, pid, team, buildings_for_class)
  local why = {}
  local own = b.BuildingClass and buildings_for_class[b.BuildingClass]
  if b.BuildingClass and own ~= b.Type then
    if own then why[#why + 1] = "this civilization builds " .. own .. " in this class instead"
    else why[#why + 1] = "this civilization has no building of this class" end
  end
  if b.PrereqTech and not CMP.has_tech(team, b.PrereqTech) then
    why[#why + 1] = "needs the tech " .. CMP.tech_name(b.PrereqTech)
  end
  local id = b.ID
  local ok, n = pcall(function() return city:GetNumBuilding(id) end)
  if ok and type(n) == "number" and n > 0 then why[#why + 1] = "already built in this city" end
  for _, r in ipairs(CMP.rows("Building_ClassesNeededInCity", "BuildingType", b.Type)) do
    local need = buildings_for_class[r.BuildingClassType]
    local nid = need and GameInfoTypes[need]
    local okh, has = pcall(function() return nid and city:GetNumBuilding(nid) > 0 end)
    if not (okh and has) then why[#why + 1] = "needs " .. (need or r.BuildingClassType) .. " in this city" end
  end
  for _, r in ipairs(CMP.rows("Building_PrereqBuildingClasses", "BuildingType", b.Type)) do
    local need = buildings_for_class[r.BuildingClassType]
    local nid = need and GameInfoTypes[need]
    local have, cities = 0, 0
    for c in p:Cities() do
      cities = cities + 1
      local okh, has = pcall(function() return nid and c:GetNumBuilding(nid) > 0 end)
      if okh and has then have = have + 1 end
    end
    local want = (r.NumBuildingNeeded == -1) and cities or (r.NumBuildingNeeded or 1)
    if have < want then
      why[#why + 1] = "needs " .. (need or r.BuildingClassType) .. " in " .. (r.NumBuildingNeeded == -1 and "every city" or (want .. " cities"))
                      .. " (" .. have .. " of " .. cities .. " have it)"
    end
  end
  local class = b.BuildingClass and GameInfo.BuildingClasses[b.BuildingClass]
  if class then
    if class.MaxGlobalInstances == 1 then
      local okm, maxed = pcall(function() return Game.IsBuildingClassMaxedOut(class.ID) end)
      if okm and maxed then why[#why + 1] = "world wonder already completed (announced to every player)" end
    end
    if class.MaxPlayerInstances == 1 then
      local okc, cnt = pcall(function() return p:GetBuildingClassCount(class.ID) end)
      if okc and type(cnt) == "number" and cnt > 0 and not (ok and n and n > 0) then
        why[#why + 1] = "national wonder already built in another city"
      end
    end
  end
  local function need_flag(flag, test, text)
    if flag_on(b[flag]) then
      local okt, v = pcall(test)
      if okt and not v then why[#why + 1] = text end
    end
  end
  need_flag("Water", function() return city:IsCoastal() end, "needs a coastal city")
  need_flag("River", function() return city:Plot():IsRiver() end, "needs a city on a river")
  need_flag("FreshWater", function() return city:Plot():IsFreshWater() end, "needs a city with fresh water")
  need_flag("Mountain", function() return city.IsNearMountain and city:IsNearMountain() end, "needs a mountain next to the city")
  need_flag("NearbyMountainRequired", function() return city.IsNearMountain and city:IsNearMountain() end,
            "needs a mountain next to the city")
  need_flag("Hill", function() return city:Plot():IsHills() end, "needs a city on a hill")
  for _, r in ipairs(CMP.rows("Building_ResourceQuantityRequirements", "BuildingType", b.Type)) do
    local res = GameInfo.Resources[r.ResourceType]
    local have = res and res.ID and CMP.num(function() return p:GetNumResourceAvailable(res.ID, true) end)
    if have and have < (r.Cost or 1) then
      why[#why + 1] = "needs " .. (r.Cost or 1) .. " " .. r.ResourceType .. " (" .. have .. " available)"
    end
  end
  return why
end

function H.compare_production(city_id, items, pid, full)
  local p = Players[pid]
  local city = p and p:GetCityByID(city_id)
  if not city then return { ok = false, err = "no such city of yours: " .. tostring(city_id) } end
  local puppet = H.city_production_guard(city)
  local venice = false
  if puppet then
    local ok, v = pcall(function() return p:MayNotAnnex() end)
    if not (ok and v) then return puppet end
    venice = true
  end
  local team = p:GetTeam()
  local units_for_class, buildings_for_class = CMP.civ_classes(pid)
  local out = { ok = true, turn = Game.GetGameTurn(), city = { id = city_id, name = city:GetName() }, rows = {} }
  out.city.production_per_turn = CMP.num(function() return city:GetCurrentProductionDifferenceTimes100(false, false) / 100 end)
  out.city.population = CMP.num(function() return city:GetPopulation() end)
  out.treasury = { gold = CMP.num(function() return p:GetGold() end), faith = CMP.num(function() return p:GetFaith() end) }
  out.unit_upkeep = { gold_per_turn = CMP.num(function() return p:CalculateUnitCost() end),
                      units = CMP.num(function() return p:GetNumUnits() end) }
  if venice then
    out.purchase_only = true
    out.producing = H.L(city:GetProductionNameKey())
  end
  local ok_noannex, noannex = pcall(function() return p:MayNotAnnex() end)
  if ok_noannex and noannex then
    out.restrictions = { "Venice (Traits.NoAnnexing): cannot train units that found cities or annex puppets; puppets may be bought in, never directed" }
  end
  for _, item in ipairs(items or {}) do
    local u, b, pr, proc = GameInfo.Units[item], GameInfo.Buildings[item], GameInfo.Projects[item], GameInfo.Processes[item]
    local row = { item = item }
    if u and u.ID then
      row.kind, row.name = "unit", CMP.name(u)
      row.can_produce = city:CanTrain(u.ID, 0) and true or false
      row.cost = CMP.num(function() return city:GetUnitProductionNeeded(u.ID) end)
      local stored = CMP.num(function() return city:GetUnitProduction(u.ID) end)
      if stored and stored > 0 then row.stored = stored end
      if row.can_produce then row.turns = CMP.turns(function() return city:GetUnitProductionTurnsLeft(u.ID) end) end
      CMP.purchase(city, p, row, u.ID, -1)
      row.effects = CMP.unit_effects(u, p)
      row.maintenance = { gold = nil, note = "unit upkeep is empire-wide (unit_upkeep); the next unit's share is not exposed" }
      local base = u.Class and GameInfo.UnitClasses[u.Class]
      if base and base.DefaultUnit and base.DefaultUnit ~= item and units_for_class[u.Class] == item then
        row.unique_replaces = base.DefaultUnit
      end
      if not row.can_produce then row.why = CMP.unit_why(u, city, p, pid, team, units_for_class) end
      if full then row.help = plain_name(u.Help) end
    elseif b and b.ID then
      row.kind, row.name = "building", CMP.name(b)
      row.can_produce = city:CanConstruct(b.ID, 0) and true or false
      row.cost = CMP.num(function() return city:GetBuildingProductionNeeded(b.ID) end)
      local stored = CMP.num(function() return city:GetBuildingProduction(b.ID) end)
      if stored and stored > 0 then row.stored = stored end
      if row.can_produce then row.turns = CMP.turns(function() return city:GetBuildingProductionTurnsLeft(b.ID) end) end
      CMP.purchase(city, p, row, -1, b.ID)
      local e, cond, flat, per_pop, pct = CMP.building_effects(b, city, pid)
      row.effects = e
      if #cond > 0 then row.conditional = cond end
      row.estimated_change = CMP.building_estimate(city, flat, per_pop, pct, cond)
      row.maintenance = { gold = tonumber(b.GoldMaintenance) or 0 }
      local class = b.BuildingClass and GameInfo.BuildingClasses[b.BuildingClass]
      if class and class.DefaultBuilding and class.DefaultBuilding ~= item and buildings_for_class[b.BuildingClass] == item then
        row.unique_replaces = class.DefaultBuilding
      end
      if class and class.MaxGlobalInstances == 1 then row.wonder = "world"
      elseif class and class.MaxPlayerInstances == 1 then row.wonder = "national" end
      if not row.can_produce then row.why = CMP.building_why(b, city, p, pid, team, buildings_for_class) end
      -- no table effect (a Garden's great-person rate, a Pyramid's workers): the help text is all there is
      if full or (row.effects == nil and not row.conditional) then row.help = plain_name(b.Help) end
    elseif pr and pr.ID then
      row.kind, row.name = "project", CMP.name(pr)
      row.can_produce = city:CanCreate(pr.ID, 0) and true or false
      row.cost = CMP.num(function() return city:GetProjectProductionNeeded(pr.ID) end)
      if row.can_produce then row.turns = CMP.turns(function() return city:GetProjectProductionTurnsLeft(pr.ID) end) end
      if not row.can_produce then
        row.why = {}
        local tech = str_or_nil(pr.TechPrereq)
        if tech and not CMP.has_tech(team, tech) then row.why[1] = "needs the tech " .. CMP.tech_name(tech) end
      end
      row.help = plain_name(pr.Help)  -- a project's effect exists only as text
    elseif proc and proc.ID then
      row.kind, row.name = "process", CMP.name(proc)
      row.can_produce = city:CanMaintain(proc.ID, 0) and true or false
      row.note = "converts production every turn and never completes: no cost or turns"
      if full then row.help = plain_name(proc.Help) end
    else
      row.err = "not a unit, building, project or process type (available_production lists this city's names)"
    end
    if venice and row.kind then
      -- the puppet's chooser is its AI's; only the purchase buttons are Venice's (GitLab #15)
      row.turns, row.can_produce = nil, false
      local why = { "puppet: its AI chooses production; Venice may only buy here" }
      for _, w in ipairs(row.why or {}) do why[#why + 1] = w end
      row.why = why
    end
    if row.why and #row.why == 0 then
      row.why = { "the engine refuses it; this read names no rule (not a prerequisite, tech, resource or civ restriction it checks)" }
      row.why_unknown = true
    end
    out.rows[#out.rows + 1] = row
  end
  return out
end

-- Every unresearched ancestor of `tech` (Technology_PrereqTechs), each once.
function CMP.missing_path(tech_type, team, prereqs)
  local seen, order = {}, {}
  local function visit(t)
    for _, pre in ipairs(prereqs[t] or {}) do
      if not seen[pre] and not CMP.has_tech(team, pre) then
        seen[pre] = true
        visit(pre)
        order[#order + 1] = pre
      end
    end
  end
  visit(tech_type)
  return order
end

function H.compare_research(techs, pid)
  local p = Players[pid]
  if not p then return { ok = false, err = "no such player" } end
  local team = p:GetTeam()
  local science = CMP.num(function() return p:GetScience() end)
  local current = CMP.num(function() return p:GetCurrentResearch() end)
  local out = { ok = true, turn = Game.GetGameTurn(), science_per_turn = science, rows = {} }
  if current and current >= 0 then out.current = GameInfo.Technologies[current] and GameInfo.Technologies[current].Type end
  local buckets = H.tech_grant_index(pid)
  local prereqs = lists_by("Technology_PrereqTechs", "TechType", "PrereqTech")
  for _, t in ipairs(techs or {}) do
    local tech = GameInfo.Technologies[t]
    local row = { tech = t }
    if not (tech and tech.ID) then
      row.err = "not a tech type"
    else
      row.name, row.era = CMP.name(tech), short(str_or_nil(tech.Era))
      if Teams[team]:IsHasTech(tech.ID) then
        row.status = "researched"
      else
        row.cost = CMP.num(function() return p:GetResearchCost(tech.ID) end)
        local prog = CMP.num(function() return p:GetResearchProgress(tech.ID) end)
        if prog and prog > 0 then row.progress = prog end
        if p:CanResearch(tech.ID) then
          row.status = (current == tech.ID) and "current" or "available"
          row.turns = CMP.turns(function() return p:GetResearchTurnsLeft(tech.ID, true) end)
        else
          local okc, ever = pcall(function() return p:CanEverResearch(tech.ID) end)
          if okc and not ever then
            row.status = "never"
            row.why = { "this civilization can never research it (CanEverResearch)" }
          else
            row.status = "locked"
            local path = CMP.missing_path(t, team, prereqs)
            local names, total, known = {}, 0, true
            for _, pre in ipairs(path) do
              local id = GameInfoTypes[pre]
              local c = id and CMP.num(function() return p:GetResearchCost(id) end)
              local pg = id and CMP.num(function() return p:GetResearchProgress(id) end) or 0
              if c then total = total + math.max(0, c - pg) else known = false end
              names[#names + 1] = pre
            end
            row.missing_prereqs = names
            if known and row.cost then
              row.path_beakers = total + math.max(0, row.cost - (prog or 0))
            end
          end
        end
      end
      local list = H.tech_buttons(tech, buckets)
      if list and #list > 0 then
        local u = {}
        for _, e in ipairs(list) do u[#u + 1] = { kind = e.kind, type = e.type or e.ability, name = e.name } end
        row.unlocks = u
      end
    end
    out.rows[#out.rows + 1] = row
  end
  return out
end

-- Worker jobs: plots x builds, each with the tile's yields now and with the build, what it removes,
-- what it connects and whether a city works the tile (the tile gain reaches the empire only then).
function H.compare_improvements(unit_id, plots, builds, pid)
  local p = Players[pid]
  local u = p and p:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit of yours: " .. tostring(unit_id) } end
  local team = p:GetTeam()
  local rate = CMP.num(function() return u:WorkRate(true) end) or 0
  local ux, uy = u:GetX(), u:GetY()
  local all = {}
  for b in ref_each(GameInfo.Builds) do
    if type(b) == "table" and b.Type then all[#all + 1] = b end
  end
  local asked = {}
  for _, bt in ipairs(builds or {}) do asked[bt] = true end
  local explicit_builds = next(asked) ~= nil
  local explicit_plots = plots and #plots > 0
  local targets = {}
  if explicit_plots then
    for _, xy in ipairs(plots) do targets[#targets + 1] = { x = xy[1], y = xy[2] } end
  else
    for dy = -2, 2 do for dx = -2, 2 do
      local pl = Map.PlotXYWithRangeCheck(ux, uy, dx, dy, 2)
      if pl and pl:IsRevealed(team, false) and (pl:GetRevealedOwner(team, false) == pid or pl:GetResourceType(team) >= 0) then
        targets[#targets + 1] = { x = pl:GetX(), y = pl:GetY() }
      end
    end end
  end
  local out = { ok = true, turn = Game.GetGameTurn(), unit = { id = unit_id, x = ux, y = uy,
                type = short(info_type(GameInfo.Units, u:GetUnitType())), work_rate = rate }, rows = {}, plots = {} }
  local seen, legal_rows = {}, 0
  for _, t in ipairs(targets) do
    local pl = Map.GetPlot(t.x, t.y)
    local key = t.x .. "," .. t.y
    if not pl then
      out.plots[#out.plots + 1] = { x = t.x, y = t.y, err = "off the map" }
    elseif not pl:IsRevealed(team, false) then
      out.plots[#out.plots + 1] = { x = t.x, y = t.y, err = "unrevealed: nothing is known about it" }
    elseif not seen[key] then
      seen[key] = true
      local info = { x = t.x, y = t.y, distance = Map.PlotDistance(ux, uy, t.x, t.y),
                     terrain = short(info_type(GameInfo.Terrains, pl:GetTerrainType())), yields_now = {} }
      if pl:IsHills() then info.hills = true end
      local visible = pl:IsVisible(team, false)
      info.visible = visible and true or false
      local feature = visible and pl:GetFeatureType() or -1
      if feature >= 0 then info.feature = short(info_type(GameInfo.Features, feature)) end
      local res = pl:GetResourceType(team)
      if res >= 0 then info.resource = short(info_type(GameInfo.Resources, res)) end
      local imp = pl:GetRevealedImprovementType(team, false)
      if imp >= 0 then info.improvement = short(info_type(GameInfo.Improvements, imp)) end
      local owner = pl:GetRevealedOwner(team, false)
      if owner >= 0 then info.owner = H.owner_label(owner, pid) end
      out.plots[#out.plots + 1] = info
      if visible then
        if owner == pid then
          info.worked = pl:IsBeingWorked() and true or false
          local wc = pl:GetWorkingCity()
          if wc then info.city = wc:GetName() end
        end
        for i = 0, 5 do
          local v = CMP.num(function() return pl:CalculateYield(i, true) end)
          if v and v ~= 0 then info.yields_now[CMP.YIELDS[i]] = v end
        end
      else
        -- a fogged plot's live yields and build legality would show changes made out of sight
        info.yields_now = nil
        info.note = "not visible now: yields and builds are not read under fog"
      end
      for _, b in ipairs(visible and all or {}) do
        local wanted = asked[b.Type] or (not explicit_builds and b.Type ~= "BUILD_REMOVE_ROUTE" and b.Type ~= "BUILD_FORT"
                                          and b.Type ~= "BUILD_ROAD" and b.Type ~= "BUILD_RAILROAD")
        if wanted then
          local okb, legal = pcall(function() return u:CanBuild(pl, b.ID) end)
          legal = okb and legal and true or false
          if legal or explicit_builds then
            local row = { x = t.x, y = t.y, build = b.Type, legal = legal }
            if legal then
              legal_rows = legal_rows + 1
              local extra = CMP.num(function() return u:WorkRate(true, b.ID) end) or 0
              row.turns = CMP.turns(function() return pl:GetBuildTurnsLeft(b.ID, pid, extra, extra) end)
              local with, delta = {}, {}
              for i = 0, 5 do
                local w = CMP.num(function() return pl:GetYieldWithBuild(b.ID, i, false, pid) end)
                if w then
                  if w ~= 0 then with[CMP.YIELDS[i]] = w end
                  local d = w - (info.yields_now[CMP.YIELDS[i]] or 0)
                  if d ~= 0 then delta[CMP.YIELDS[i]] = d end
                end
              end
              row.tile_yields_after = with
              row.tile_change = delta
              if owner == pid and info.worked then
                row.empire_change = delta
              else
                row.empire_change = nil
                row.empire_note = "no city works this tile now: the empire gains nothing until one does"
              end
              if feature >= 0 then
                for r in ref_each(GameInfo.BuildFeatures) do
                  if type(r) == "table" and r.BuildType == b.Type and r.FeatureType == info_type(GameInfo.Features, feature)
                     and flag_on(r.Remove) then
                    row.removes = short(r.FeatureType)
                    local chop = CMP.num(function() return pl:GetFeatureProduction(b.ID, team) end)
                    if chop and chop > 0 then row.chop_production = chop end
                  end
                end
              end
              if imp >= 0 and b.ImprovementType then row.replaces = info.improvement end
              local imp_row = str_or_nil(b.ImprovementType) and GameInfo.Improvements[b.ImprovementType]
              if imp_row and res >= 0 and owner == pid then
                local rrow = GameInfo.Resources[res]
                for r in ref_each(GameInfo.Improvement_ResourceTypes) do
                  local usage = CMP.num(function() return Game.GetResourceUsageType(res) end)
                  local bonus = ResourceUsageTypes and usage == ResourceUsageTypes.RESOURCEUSAGE_BONUS
                  if type(r) == "table" and r.ImprovementType == imp_row.Type and rrow and r.ResourceType == rrow.Type
                     and not bonus then
                    -- a bonus resource is never "connected": only luxuries and strategics count for the empire
                    local now = CMP.num(function() return p:GetNumResourceAvailable(res, true) end)
                    row.connects = { resource = short(rrow.Type), usage = (ResourceUsageTypes and usage == ResourceUsageTypes.RESOURCEUSAGE_LUXURY)
                                     and "luxury" or "strategic", available_now = now }
                    if now == 0 and (tonumber(rrow.Happiness) or 0) > 0 then row.connects.happiness_if_first = rrow.Happiness end
                  end
                end
              end
              local maint = imp_row and tonumber(imp_row.GoldMaintenance)
              if maint and maint > 0 then row.maintenance = { gold = maint } end
              local route = str_or_nil(b.RouteType) and GameInfo.Routes[b.RouteType]
              if route and (tonumber(route.GoldMaintenance) or 0) > 0 then row.maintenance = { gold = route.GoldMaintenance } end
            else
              local why = {}
              if str_or_nil(b.PrereqTech) and not CMP.has_tech(team, b.PrereqTech) then
                why[#why + 1] = "needs the tech " .. CMP.tech_name(b.PrereqTech)
              end
              if owner >= 0 and owner ~= pid and not flag_on(b.Kill) then why[#why + 1] = "the plot belongs to " .. (H.owner_label(owner, pid) or "another player") end
              local imp_row = str_or_nil(b.ImprovementType) and GameInfo.Improvements[b.ImprovementType]
              if imp_row and imp == imp_row.ID then why[#why + 1] = "already has this improvement" end
              if imp_row and imp ~= imp_row.ID then
                local okh, can = pcall(function() return pl:CanHaveImprovement(imp_row.ID, team, false) end)
                if okh and not can then why[#why + 1] = "this plot cannot have it (terrain, feature or resource rule)" end
              end
              if #why == 0 then
                why[1] = "the engine refuses it here; this read names no rule"
                row.why_unknown = true
              end
              row.why = why
            end
            out.rows[#out.rows + 1] = row
          end
        end
      end
    end
  end
  if rate <= 0 and legal_rows == 0 then
    return { ok = false, err = "this unit does not build improvements (work rate 0 and no legal build on these plots)" }
  end
  return out
end

-- Trade destinations with what each end receives (the chooser's numbers) plus what is visible near
-- the destination. The caravan's path is not known before the route is set, so nothing about the way
-- there is claimed; fogged plots are counted, never called empty.
function H.compare_trade_routes(unit_id, pid, radius)
  local p = Players[pid]
  local u = p and p:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit of yours: " .. tostring(unit_id) } end
  local routes = H.available_trade_routes(unit_id, pid)
  if type(routes) ~= "table" or routes.ok == false then return routes end
  radius = radius or 2
  local team = p:GetTeam()
  local ox, oy = u:GetX(), u:GetY()
  local hostile_players = {}
  for other = 0, 63 do
    local dp = Players[other]
    if other ~= pid and dp and (not dp.IsAlive or dp:IsAlive()) and (dp:IsBarbarian() or Teams[team]:IsAtWar(dp:GetTeam())) then
      hostile_players[#hostile_players + 1] = other
    end
  end
  local camp = GameInfoTypes and GameInfoTypes.IMPROVEMENT_BARBARIAN_CAMP
  local function around(x, y)
    local seen = { hostile_units = {}, camps = {}, not_visible = 0, plots = 0 }
    for dy = -radius, radius do for dx = -radius, radius do
      local q = Map.PlotXYWithRangeCheck(x, y, dx, dy, radius)
      if q then
        seen.plots = seen.plots + 1
        if not q:IsVisible(team, false) then seen.not_visible = seen.not_visible + 1 end
        if camp and q:IsRevealed(team, false) and q:GetRevealedImprovementType(team, false) == camp then
          seen.camps[#seen.camps + 1] = { x = q:GetX(), y = q:GetY(), visible = q:IsVisible(team, false) and true or false }
        end
      end
    end end
    for _, other in ipairs(hostile_players) do
      for d in Players[other]:Units() do
        local q = d:GetPlot()
        if d:IsCombatUnit() and q and q:IsVisible(team, false) and not d:IsInvisible(team, false)
           and Map.PlotDistance(x, y, d:GetX(), d:GetY()) <= radius then
          seen.hostile_units[#seen.hostile_units + 1] = { owner = H.owner_label(other, pid),
            unit = short(info_type(GameInfo.Units, d:GetUnitType())), x = d:GetX(), y = d:GetY() }
        end
      end
    end
    return seen
  end
  local out = { ok = true, turn = Game.GetGameTurn(), unit = { id = unit_id, x = ox, y = oy }, radius = radius, rows = {} }
  local oc = u:GetPlot():GetPlotCity()
  if oc then out.origin = { name = oc:GetName(), x = ox, y = oy } end
  out.origin_area = around(ox, oy)
  for _, r in ipairs(routes) do
    r.distance = Map.PlotDistance(ox, oy, r.x, r.y)
    local a = around(r.x, r.y)
    a.danger = (#a.hostile_units > 0 or #a.camps > 0) and "visible_threat" or "none_visible"
    r.hazard = a
    if r.target_player_id and r.target_player_id ~= pid then
      local op = Players[r.target_player_id]
      if op and op:IsMinorCiv() then r.city_state = true end
    end
    out.rows[#out.rows + 1] = r
  end
  return out
end
