-- Shared by earlier fragments (load order: harness/runtime_source.py MANIFEST).
local L, info_type, league_plain, short = H._ns.L, H._ns.info_type, H._ns.league_plain, H._ns.short

-- The icons on a tech-tree button (techtree/techbuttoninclude.lua AddSmallButtonsToTechButton).
-- GetHelpTextForUnit is not in this Lua state, so a unit button carries the same facts that
-- tooltip prints: production cost, moves, range, strengths, resources, and the written help.
-- Another civilization's unique is not a button for us. GatherInfoAboutUniqueStuff's rule:
-- the class default, replaced by our Civilization_*ClassOverrides row.
local function each_info(tbl)
  if tbl == nil then return function() return nil end end
  local ok, iter = pcall(tbl)
  if ok and type(iter) == "function" then return iter end
  return function() return nil end
end

local function info_prereq(row)
  if not row then return nil end
  local t = row.PrereqTech
  if t == nil or t == "" then t = row.PreReqTech end
  if t == nil or t == "" then t = row.TechPrereq end
  if t == nil or t == "" then return nil end
  return t
end

local function flag_on(v)
  return v == true or v == 1
end

local function civ_type_of(pid)
  local p = Players and Players[pid]
  if not (p and p.GetCivilizationType and GameInfo and GameInfo.Civilizations) then return nil end
  local ok, id = pcall(function() return p:GetCivilizationType() end)
  if not ok or id == nil then return nil end
  local row = GameInfo.Civilizations[id]
  return row and row.Type or nil
end

local function class_defaults(classes, default_field, overrides, class_field, repl_field, civ)
  local valid = {}
  for row in each_info(classes) do
    if row and row.Type and row[default_field] and row[default_field] ~= "" then
      valid[row.Type] = row[default_field]
    end
  end
  if civ then
    for row in each_info(overrides) do
      if row and row.CivilizationType == civ and row[class_field] then
        local repl = row[repl_field]
        valid[row[class_field]] = (repl ~= nil and repl ~= "") and repl or nil
      end
    end
  end
  return valid
end

local function plain_name(key)
  if key == nil or key == "" then return nil end
  return league_plain(L(key))
end

local function plain_fmt(key, ...)
  if key == nil or key == "" then return nil end
  local ok, s = pcall(Locale.ConvertTextKey, key, ...)
  if not ok or s == nil then return league_plain(tostring(key)) end
  return league_plain(s)
end

local function unit_button(u, p)
  local e = { kind = "unit", type = u.Type, name = plain_name(u.Description) }
  if p and p.GetUnitProductionNeeded and u.ID and u.Cost and u.Cost > 0 then
    local ok, cost = pcall(function() return p:GetUnitProductionNeeded(u.ID) end)
    if ok and type(cost) == "number" then e.cost = cost end
  end
  if u.Domain ~= "DOMAIN_AIR" and type(u.Moves) == "number" and u.Moves ~= 0 then e.moves = u.Moves end
  if type(u.Range) == "number" and u.Range ~= 0 then e.range = u.Range end
  if type(u.RangedCombat) == "number" and u.RangedCombat ~= 0 then e.ranged_strength = u.RangedCombat end
  if type(u.Combat) == "number" and u.Combat ~= 0 then e.strength = u.Combat end
  if Game and Game.GetNumResourceRequiredForUnit and u.ID then
    local req = {}
    for res in each_info(GameInfo and GameInfo.Resources) do
      if res and res.ID then
        local ok, n = pcall(Game.GetNumResourceRequiredForUnit, u.ID, res.ID)
        if ok and type(n) == "number" and n > 0 then
          req[#req + 1] = { resource = res.Type, name = plain_name(res.Description), amount = n }
        end
      end
    end
    if #req > 0 then e.resources = req end
  end
  local reqtxt = plain_name(u.Requirements)
  if reqtxt then e.requirements = reqtxt end
  return e
end

local function building_button(b, p)
  local e = { kind = "building", type = b.Type, name = plain_name(b.Description) }
  if p and p.GetBuildingProductionNeeded and b.ID and b.Cost and b.Cost > 0 then
    local ok, cost = pcall(function() return p:GetBuildingProductionNeeded(b.ID) end)
    if ok and type(cost) == "number" then e.cost = cost end
  end
  if type(b.GoldMaintenance) == "number" and b.GoldMaintenance ~= 0 then e.gold_maintenance = b.GoldMaintenance end
  return e
end

-- Satellite rows of one tech, in the order AddSmallButtonsToTechButton walks them.
-- Column flags (embark, ocean, embassy, ...) are not rows; tech_buttons appends those.
function H.tech_grant_index(pid)
  local buckets = {
    unit = {}, building = {}, resource = {}, project = {}, build = {}, process = {},
    movement = {}, yield = {}, yield_dry = {}, yield_fresh = {}, trade_range = {}, promotion = {},
  }
  local function add(bucket, tech, item)
    if not tech or tech == "" or not item then return end
    local list = buckets[bucket][tech]
    if not list then list = {}; buckets[bucket][tech] = list end
    list[#list + 1] = item
  end
  if not GameInfo then return buckets end
  local civ = civ_type_of(pid)
  local p = Players and Players[pid]
  local units = class_defaults(GameInfo.UnitClasses, "DefaultUnit",
    GameInfo.Civilization_UnitClassOverrides, "UnitClassType", "UnitType", civ)
  local buildings = class_defaults(GameInfo.BuildingClasses, "DefaultBuilding",
    GameInfo.Civilization_BuildingClassOverrides, "BuildingClassType", "BuildingType", civ)
  local imps = {}
  for imp in each_info(GameInfo.Improvements) do
    if imp and imp.Type then
      local owner = imp.CivilizationType
      if owner == nil or owner == "" or owner == civ then imps[imp.Type] = imp.Type end
    end
  end
  for u in each_info(GameInfo.Units) do
    local tech = info_prereq(u)
    if tech and u.Class and u.Type and units[u.Class] == u.Type then
      add("unit", tech, unit_button(u, p))
    end
  end
  for b in each_info(GameInfo.Buildings) do
    local tech = info_prereq(b)
    if tech and b.BuildingClass and b.Type and buildings[b.BuildingClass] == b.Type then
      add("building", tech, building_button(b, p))
    end
  end
  for res in each_info(GameInfo.Resources) do
    if res and res.TechReveal and res.TechReveal ~= "" then
      add("resource", res.TechReveal, {
        kind = "resource", type = res.Type, name = plain_name(res.Description),
        text = plain_fmt("TXT_KEY_REVEALS_RESOURCE_ON_MAP", res.Description),
      })
    end
  end
  for proj in each_info(GameInfo.Projects) do
    local tech = proj and proj.TechPrereq
    if tech and tech ~= "" and proj.Type then
      local e = { kind = "project", type = proj.Type, name = plain_name(proj.Description) }
      if p and p.GetProjectProductionNeeded and proj.ID then
        local ok, cost = pcall(function() return p:GetProjectProductionNeeded(proj.ID) end)
        if ok and type(cost) == "number" then e.cost = cost end
      end
      add("project", tech, e)
    end
  end
  for b in each_info(GameInfo.Builds) do
    local show = b and (b.ShowInTechTree == true or b.ShowInTechTree == 1)
    local tech = show and info_prereq(b) or nil
    if tech and b.Type then
      local imp = b.ImprovementType
      if imp == "" then imp = nil end
      if not imp or imps[imp] == imp then
        local e = { kind = "build", type = b.Type, name = plain_name(b.Description) }
        if imp then e.improvement = imp end
        add("build", tech, e)
      end
    end
  end
  for proc in each_info(GameInfo.Processes) do
    local tech = proc and proc.TechPrereq
    if tech and tech ~= "" and proc.Type then
      local e = {
        kind = "process", type = proc.Type, name = plain_name(proc.Description),
        text = plain_fmt("TXT_KEY_ENABLE_PRODUCITON_CONVERSION", proc.Description),
      }
      add("process", tech, e)
    end
  end
  for row in each_info(GameInfo.Route_TechMovementChanges) do
    if row and row.TechType and row.RouteType and GameInfo.Routes and GameInfo.Routes[row.RouteType] then
      local route = GameInfo.Routes[row.RouteType]
      add("movement", row.TechType, {
        kind = "movement", route = row.RouteType,
        text = plain_fmt("TXT_KEY_FASTER_MOVEMENT", route.Description),
      })
    end
  end
  local yield_groups = {}
  for row in each_info(GameInfo.Improvement_TechYieldChanges) do
    if row and row.TechType and row.ImprovementType and GameInfo.Improvements and GameInfo.Yields then
      local imp = GameInfo.Improvements[row.ImprovementType]
      local yield = GameInfo.Yields[row.YieldType]
      if imp and yield then
        local by_imp = yield_groups[row.TechType]
        if not by_imp then by_imp = {}; yield_groups[row.TechType] = by_imp end
        local lines = by_imp[row.ImprovementType]
        if not lines then lines = {}; by_imp[row.ImprovementType] = lines end
        lines[#lines + 1] = plain_fmt("TXT_KEY_YIELD_IMPROVED", imp.Description, yield.Description, row.Yield) or ""
      end
    end
  end
  for tech, by_imp in pairs(yield_groups) do
    local keys = {}
    for imp in pairs(by_imp) do keys[#keys + 1] = imp end
    table.sort(keys)
    for _, imp in ipairs(keys) do
      table.sort(by_imp[imp])
      add("yield", tech, {
        kind = "improvement_yield", improvement = imp,
        text = league_plain(table.concat(by_imp[imp], "\n")),
      })
    end
  end
  local function water_yield(tbl, bucket, fresh)
    for row in each_info(tbl) do
      if row and row.TechType and row.ImprovementType and GameInfo.Improvements and GameInfo.Yields then
        local imp = GameInfo.Improvements[row.ImprovementType]
        local yield = GameInfo.Yields[row.YieldType]
        if imp and yield then
          local key = fresh and "TXT_KEY_FRESH_WATER" or "TXT_KEY_NO_FRESH_WATER"
          add(bucket, row.TechType, {
            kind = "improvement_yield", improvement = row.ImprovementType, fresh_water = fresh,
            text = plain_fmt(key, imp.Description, yield.Description, row.Yield),
          })
        end
      end
    end
  end
  water_yield(GameInfo.Improvement_TechNoFreshWaterYieldChanges, "yield_dry", false)
  water_yield(GameInfo.Improvement_TechFreshWaterYieldChanges, "yield_fresh", true)
  for row in each_info(GameInfo.Technology_TradeRouteDomainExtraRange) do
    if row and row.TechType and type(row.Range) == "number" and row.Range > 0 then
      local dom = row.DomainType
      local which
      if dom == "DOMAIN_LAND" then which = "land"
      elseif dom == "DOMAIN_SEA" then which = "sea"
      elseif GameInfo.Domains and DomainTypes and GameInfo.Domains[dom] then
        local id = GameInfo.Domains[dom].ID
        if id == DomainTypes.DOMAIN_LAND then which = "land"
        elseif id == DomainTypes.DOMAIN_SEA then which = "sea" end
      end
      if which then
        local key = which == "land" and "TXT_KEY_EXTENDS_LAND_TRADE_ROUTE_RANGE"
          or "TXT_KEY_EXTENDS_SEA_TRADE_ROUTE_RANGE"
        add("trade_range", row.TechType, { kind = "trade_range", domain = which, text = plain_fmt(key) })
      end
    end
  end
  for row in each_info(GameInfo.Technology_FreePromotions) do
    if row and row.TechType and row.PromotionType and GameInfo.UnitPromotions then
      local promo = GameInfo.UnitPromotions[row.PromotionType]
      if promo then
        -- Name only; what the promotion does is in reference("promotions") (v216).
        add("promotion", row.TechType, {
          kind = "promotion", type = promo.Type, name = plain_name(promo.Description),
        })
      end
    end
  end
  return buckets
end

function H.tech_buttons(tech, buckets)
  local out = {}
  if not tech or not tech.Type then return out end
  buckets = buckets or {}
  local function take(bucket)
    local list = buckets[bucket] and buckets[bucket][tech.Type]
    if not list then return end
    for _, e in ipairs(list) do out[#out + 1] = e end
  end
  local function ability(id, text, extra)
    local e = { kind = "ability", ability = id, text = text }
    if extra then
      for k, v in pairs(extra) do e[k] = v end
    end
    out[#out + 1] = e
  end
  take("unit"); take("building"); take("resource"); take("project"); take("build"); take("process")
  take("movement"); take("yield"); take("yield_dry"); take("yield_fresh")
  if type(tech.EmbarkedMoveChange) == "number" and tech.EmbarkedMoveChange > 0 then
    ability("faster_embarked_movement", plain_fmt("TXT_KEY_FASTER_EMBARKED_MOVEMENT"))
  end
  if flag_on(tech.AllowsEmbarking) then ability("embark", plain_fmt("TXT_KEY_ALLOWS_EMBARKING")) end
  if flag_on(tech.AllowsDefensiveEmbarking) then
    ability("defensive_embark", plain_fmt("TXT_KEY_ABLTY_DEFENSIVE_EMBARK_STRING"))
  end
  if flag_on(tech.EmbarkedAllWaterPassage) then ability("ocean", plain_fmt("TXT_KEY_ALLOWS_CROSSING_OCEANS")) end
  if type(tech.UnitFortificationModifier) == "number" and tech.UnitFortificationModifier > 0 then
    ability("fortify", plain_fmt("TXT_KEY_UNIT_FORTIFICATION_MOD", tech.UnitFortificationModifier),
      { value = tech.UnitFortificationModifier })
  end
  if type(tech.UnitBaseHealModifier) == "number" and tech.UnitBaseHealModifier > 0 then
    ability("heal", plain_fmt("TXT_KEY_UNIT_BASE_HEAL_MOD", tech.UnitBaseHealModifier),
      { value = tech.UnitBaseHealModifier })
  end
  if flag_on(tech.AllowEmbassyTradingAllowed) then ability("embassy", plain_fmt("TXT_KEY_ALLOWS_EMBASSY")) end
  if flag_on(tech.OpenBordersTradingAllowed) then ability("open_borders", plain_fmt("TXT_KEY_ALLOWS_OPEN_BORDERS")) end
  if flag_on(tech.DefensivePactTradingAllowed) then
    ability("defensive_pact", plain_fmt("TXT_KEY_ALLOWS_DEFENSIVE_PACTS"))
  end
  if flag_on(tech.ResearchAgreementTradingAllowed) then
    ability("research_agreement", plain_fmt("TXT_KEY_ALLOWS_RESEARCH_AGREEMENTS"))
  end
  if flag_on(tech.TradeAgreementTradingAllowed) then
    ability("trade_agreement", plain_fmt("TXT_KEY_ALLOWS_TRADE_AGREEMENTS"))
  end
  if flag_on(tech.BridgeBuilding) then ability("bridges", plain_fmt("TXT_KEY_ALLOWS_BRIDGES")) end
  if flag_on(tech.MapVisible) then ability("reveal_map", plain_fmt("TXT_KEY_REVEALS_ENTIRE_MAP")) end
  if type(tech.InternationalTradeRoutesChange) == "number" and tech.InternationalTradeRoutesChange > 0 then
    ability("trade_route", plain_fmt("TXT_KEY_ADDITIONAL_INTERNATIONAL_TRADE_ROUTE"),
      { extra = tech.InternationalTradeRoutesChange })
  end
  -- ScenarioTechButton 3 and 4 are pushed twice in the stock file (the second copy is a hardcoded
  -- "pillage" line). This is not a scenario; one button, the text key the first copy uses.
  local scenario = tech.ScenarioTechButton
  if scenario == 1 or scenario == 2 or scenario == 3 or scenario == 4 then
    ability("scenario_" .. scenario, plain_fmt("TXT_KEY_SCENARIO_TECH_BUTTON_" .. scenario))
  end
  take("trade_range")
  if type(tech.InfluenceSpreadModifier) == "number" and tech.InfluenceSpreadModifier > 0 then
    ability("double_tourism", plain_fmt("TXT_KEY_DOUBLE_TOURISM"))
  end
  if flag_on(tech.AllowsWorldCongress) then ability("world_congress", plain_fmt("TXT_KEY_ALLOWS_WORLD_CONGRESS")) end
  if type(tech.ExtraVotesPerDiplomat) == "number" and tech.ExtraVotesPerDiplomat > 0 then
    ability("diplomat_votes", plain_fmt("TXT_KEY_EXTRA_VOTES_FROM_DIPLOMATS", tech.ExtraVotesPerDiplomat),
      { extra = tech.ExtraVotesPerDiplomat })
  end
  take("promotion")
  return out
end

local function decorate_tech(e, tech, buckets)
  if not tech then return end
  -- tech.Help ("Allows the Frigate.") is static: reference("techs") has it once (v216).
  local list = H.tech_buttons(tech, buckets)
  if list and #list > 0 then e.unlocks = list end
end

-- Read-only catalogs of currently legal choices. Used by the MCP so callers do not have to guess
-- tech/build/mission names, and so illegal orders can be refused before they touch the engine.
function H.available_research(pid)
  local p = Players[pid]
  local current = p:GetCurrentResearch()
  local out = {}
  if not (GameInfo and GameInfo.Technologies) then return out end
  local buckets = H.tech_grant_index(pid)
  for tech in GameInfo.Technologies() do
    if tech and tech.ID and p:CanResearch(tech.ID) then
      local e = { tech = tech.Type, name = short(tech.Type),
                  turns = p:GetResearchTurnsLeft(tech.ID, true), cost = p:GetResearchCost(tech.ID) }
      -- stored beakers, as the tech hover prints them (GitLab #18); the current tech always carries it
      local okp, prog = pcall(function() return p:GetResearchProgress(tech.ID) end)
      if okp and type(prog) == "number" and (prog > 0 or tech.ID == current) then e.progress = prog end
      decorate_tech(e, tech, buckets)
      if current == tech.ID then e.current = true end
      out[#out + 1] = e
    end
  end
  return out
end

-- Full tech tree (techtree.lua RefreshDisplayOfSpecificTech): have / current / available /
-- unavailable (prereqs missing) / locked (CanEverResearch false, omitted). Prereqs from
-- GameInfo.Technology_PrereqTechs. No rival techs: see the note at the end of the function.
-- `unlocks` is the button row on that tech (our units and buildings, not another civ's
-- uniques). Researched techs stay in `have` without it.
function H.tech_tree(pid)
  local p = Players[pid]
  if not p then return { ok = false, err = "no such player" } end
  local team = Teams and Teams[p:GetTeam()] or nil
  local function we_have(id)
    if not team then return false end
    if team.IsHasTech then
      local ok, v = pcall(function() return team:IsHasTech(id) end)
      if ok then return v and true or false end
    end
    if team.GetTeamTechs then
      local ok, v = pcall(function() return team:GetTeamTechs():HasTech(id) end)
      if ok then return v and true or false end
    end
    return false
  end
  if not (GameInfo and GameInfo.Technologies) then
    return { ok = true, have = {}, techs = {}, rivals = {} }
  end
  local prereq = {}
  if GameInfo.Technology_PrereqTechs then
    for row in GameInfo.Technology_PrereqTechs() do
      if row and row.TechType and row.PrereqTech then
        local t = prereq[row.TechType] or {}
        t[#t + 1] = row.PrereqTech
        prereq[row.TechType] = t
      end
    end
  end
  local rows = {}
  for tech in GameInfo.Technologies() do
    if tech and tech.ID and tech.Type then rows[#rows + 1] = tech end
  end
  local have, have_id = {}, {}
  for _, tech in ipairs(rows) do
    if we_have(tech.ID) then
      have[#have + 1] = short(tech.Type)
      have_id[tech.ID] = true
    end
  end
  local have_short = {}
  for _, n in ipairs(have) do have_short[n] = true end
  local function have_type(typ)
    if have_short[short(typ)] then return true end
    local info = GameInfo.Technologies[typ]
    return info and info.ID and have_id[info.ID] or false
  end
  local current = p:GetCurrentResearch()
  local techs = {}
  local buckets = H.tech_grant_index(pid)
  for _, tech in ipairs(rows) do
    local id = tech.ID
    local ever = true
    if p.CanEverResearch then
      local ok, v = pcall(function() return p:CanEverResearch(id) end)
      if ok then ever = v and true or false end
    end
    if have_id[id] then
      -- researched techs live in `have` (compact); Future Tech can still be CanResearch
      if p:CanResearch(id) then
        local e = { tech = tech.Type, name = short(tech.Type), status = "available", have = true }
        if tech.Era then e.era = short(tech.Era) end
        local okc, cost = pcall(function() return p:GetResearchCost(id) end)
        if okc then e.cost = cost end
        local okt, turns = pcall(function() return p:GetResearchTurnsLeft(id, true) end)
        if okt then e.turns = turns end
        if current == id then e.status = "current"; e.current = true end
        decorate_tech(e, tech, buckets)
        techs[#techs + 1] = e
      end
    elseif ever then
      local e = { tech = tech.Type, name = short(tech.Type) }
      if tech.Era then e.era = short(tech.Era) end
      local okc, cost = pcall(function() return p:GetResearchCost(id) end)
      if okc then e.cost = cost end
      local okt, turns = pcall(function() return p:GetResearchTurnsLeft(id, true) end)
      if okt then e.turns = turns end
      local pre = prereq[tech.Type]
      if pre and #pre > 0 then
        e.prereqs = pre
        local missing = {}
        for _, pt in ipairs(pre) do
          if not have_type(pt) then missing[#missing + 1] = pt end
        end
        if #missing > 0 then e.missing = missing end
      end
      -- techhelpinclude.lua GetHelpTextForTech prints the stored beakers of any unfinished tech
      -- that has some, not only the current one: switching research must not hide what the
      -- previous tech already banked (GitLab #18). The current tech keeps `progress` even at 0.
      local okp, prog = pcall(function() return p:GetResearchProgress(id) end)
      if current == id then
        e.status = "current"; e.current = true
        if okp then e.progress = prog end
      else
        if okp and type(prog) == "number" and prog > 0 then e.progress = prog end
        if p:CanResearch(id) then
          e.status = "available"
        else
          e.status = "unavailable"
        end
      end
      local okq, qpos = pcall(function() return p:GetQueuePosition(id) end)
      if okq and type(qpos) == "number" and qpos and qpos > 0 then e.queue = qpos end
      decorate_tech(e, tech, buckets)
      techs[#techs + 1] = e
    end
  end
  local current_name
  if type(current) == "number" and current >= 0 then
    current_name = short(info_type(GameInfo.Technologies, current))
  end
  -- No rival column. v138-v191 scanned every met civ's IsHasTech behind an embassy and listed the
  -- techs they had that we did not; no stock screen does that (techtree.lua reads another team's
  -- techs only inside the steal-tech chooser, gated by CanResearch, which H.steal_tech_options keeps).
  -- An embassy on the Diplomacy Overview shows a capital and unlocks agreements, not a tech list
  -- (GitLab #1).
  return { ok = true, current = current_name, have = have, techs = techs }
end

-- Shared with later fragments, which import these at their top (load order: harness/runtime_source.py MANIFEST).
H._ns.civ_type_of = civ_type_of
H._ns.class_defaults = class_defaults
H._ns.flag_on = flag_on
H._ns.plain_name = plain_name
