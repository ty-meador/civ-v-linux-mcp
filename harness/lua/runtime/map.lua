-- Shared by earlier fragments (load order: harness/runtime_source.py MANIFEST).
local info_type, plain_key, plot_yields = H._ns.info_type, H._ns.plain_key, H._ns.plot_yields
local short = H._ns.short

-- resourcetooltipgenerator.lua: the hover on a resource tile. Happiness and the yield changes
-- are the resource's own stats ("when improved" / "when improved and worked"), not this tile's
-- current yields, and they are the same under fog. Help is the strategic blurb, tags stripped.
-- v179 put this on every plot; v216 prints it once per resource in H.reference (see below).
local function resource_hover(res_id)
  local info = GameInfo.Resources and GameInfo.Resources[res_id]
  if type(info) ~= "table" then return nil end
  local hover = {}
  if type(info.Happiness) == "number" and info.Happiness ~= 0 then
    hover.happiness = info.Happiness
  end
  local help = plain_key(info.Help)
  if help then hover.help = help end
  -- Civ5 exposes GameInfo tables as callable userdata, not Lua functions (tests: a function, or a
  -- table with __call); calling it is the one thing they all do.
  local changes = GameInfo.Resource_YieldChanges
  local iter
  if info.Type and changes ~= nil then
    local okc, it = pcall(changes)
    if okc and type(it) == "function" then iter = it end
  end
  if iter then
    local yields = {}
    local names = {
      YIELD_FOOD = "food", YIELD_PRODUCTION = "production", YIELD_GOLD = "gold",
      YIELD_SCIENCE = "science", YIELD_CULTURE = "culture", YIELD_FAITH = "faith",
    }
    for row in iter do
      if type(row) == "table" and row.ResourceType == info.Type
         and type(row.Yield) == "number" and row.Yield ~= 0 then
        local key = names[row.YieldType]
        if key then yields[key] = row.Yield end
      end
    end
    if next(yields) then hover.improved_yields = yields end
  end
  if next(hover) then return hover end
end

-- Last-seen feature cache (GitLab #19). The stock map keeps drawing the forest a fogged tile had
-- when last seen; the engine gives Lua no GetRevealedFeatureType, so the harness remembers what
-- it saw while a plot was visible. Seeded once per team from every plot visible at that moment
-- (what the screen showed when the harness loaded), then kept by every visible describe_plot.
-- -1 is remembered too: a tile seen bare stays bare even if a feature grows there under fog.
-- A plot never visible since load has no entry and reports no feature, as before.
local function feature_key(plot) return plot:GetX() * 4096 + plot:GetY() end

function H.seed_seen_features(team)
  local cache = {}
  H.seen_features[team] = cache
  pcall(function()
    for i = 0, Map.GetNumPlots() - 1 do
      local pl = Map.GetPlotByIndex(i)
      if pl and pl:IsVisible(team, false) then cache[feature_key(pl)] = pl:GetFeatureType() end
    end
  end)
  return cache
end

function H.remember_feature(plot, team, feature)
  local cache = H.seen_features[team] or H.seed_seen_features(team)
  cache[feature_key(plot)] = feature
end

function H.remembered_feature(plot, team)
  local cache = H.seen_features[team] or H.seed_seen_features(team)
  local f = cache[feature_key(plot)]
  if f == nil or f < 0 then return nil end
  return short(info_type(GameInfo.Features, f))
end

-- One revealed plot. vis=true: currently in sight. vis=false: discovered but fogged —
-- terrain/resource only, plus the remembered feature; never live units, owners, improvements,
-- cities, or the live feature.
function H.describe_plot(plot, team)
  if not plot or not plot:IsRevealed(team, false) then return nil end
  local vis = plot:IsVisible(team, false) and true or false
  local e = {
    x = plot:GetX(), y = plot:GetY(),
    t = short(info_type(GameInfo.Terrains, plot:GetTerrainType())),
    vis = vis,
  }
  if plot:IsHills() then e.hills = true end
  if plot:IsMountain() then e.mountain = true end
  if plot:IsRiver() then e.river = true end
  pcall(function() if plot:IsLake() then e.lake = true end end)
  local res = plot:GetResourceType(team)
  if res >= 0 then
    e.resource = short(info_type(GameInfo.Resources, res))
    local okq, qty = pcall(function() return plot:GetNumResource() end)
    if okq and qty and qty > 1 then e.resource_qty = qty end
    -- plotmouseoverinclude GetResourceString: "requires TECH to use" until TechCityTrade.
    pcall(function()
      local info = GameInfo.Resources[res]
      local tech = info and info.TechCityTrade
      if not tech then return end
      local tid = GameInfoTypes and GameInfoTypes[tech]
      local techs = Teams[team] and Teams[team].GetTeamTechs and Teams[team]:GetTeamTechs()
      if tid and techs and techs.HasTech and not techs:HasTech(tid) then
        e.resource_requires_tech = tech
        e.resource_usable = false
      end
    end)
    -- The resource hover (happiness, improved yields, blurb) is the resource's own text, identical on
    -- every tile that carries it: since v216 it is printed once in reference("resources"), not per plot.
  end
  if not vis then
    -- A fogged tile still shows a human what was there when last seen (ruins, camps, roads, borders):
    -- the engine keeps that per team as the "revealed" values, which can be stale -- that is the point.
    -- (live 2026-09-18: a "Ruins discovered" bubble whose GOODY_HUT the map read did not show.)
    -- There is no GetRevealedFeatureType and GetFeatureType is live (a forest chopped in fog would
    -- leak), so the feature comes from H.seen_features: what this team last saw there while the plot
    -- was visible since the harness loaded (GitLab #19). Never the live read.
    local remembered = H.remembered_feature(plot, team)
    if remembered then e.feature = remembered; e.remembered = true end
    local rimp = plot:GetRevealedImprovementType(team, false)
    if rimp >= 0 then e.improvement = short(info_type(GameInfo.Improvements, rimp)) end
    local rrt = plot:GetRevealedRouteType(team, false); if rrt >= 0 then e.route = short(info_type(GameInfo.Routes, rrt)) end
    local rown = plot:GetRevealedOwner(team, false); if rown >= 0 then e.owner = rown end
    -- Kill-camp quest overlay is the CS quest data, not live plot state (plotmouseoverinclude.lua).
    if e.improvement == "BARBARIAN_CAMP" then
      local q = H.kill_camp_quest_minors(e.x, e.y)
      if q and #q > 0 then e.cs_quest = q end
    end
    return e
  end
  local f = plot:GetFeatureType(); if f >= 0 then e.feature = short(info_type(GameInfo.Features, f)) end
  H.remember_feature(plot, team, f)
  local imp = plot:GetImprovementType(); if imp >= 0 then e.improvement = short(info_type(GameInfo.Improvements, imp)) end
  -- a pillaged improvement still reports its type; without this flag a caller can't tell what
  -- needs BUILD_REPAIR (live: barbarian horsemen pillaging Guangzhou, turn 175-185). Visible plots
  -- only: a fogged tile's pillaged state is live information a human player cannot see.
  if imp >= 0 and plot.IsImprovementPillaged and plot:IsImprovementPillaged() then e.pillaged = true end
  local rt = plot:GetRouteType(); if rt >= 0 then e.route = short(info_type(GameInfo.Routes, rt)) end
  pcall(function() if plot:IsRoutePillaged() then e.route_pillaged = true end end)
  pcall(function() if plot:IsTradeRoute() then e.trade_route = true end end)
  -- plothelpmanager.lua under-construction line (visible only: GetBuildProgress is live).
  pcall(function()
    if not GameInfo.Builds then return end
    for b in GameInfo.Builds() do
      if b and b.ID and plot:GetBuildProgress(b.ID) > 0 then
        local row = { build = b.Type }
        local okt, turns = pcall(function() return plot:GetBuildTurnsLeft(b.ID, 0, 0) end)
        if okt and type(turns) == "number" and turns > 0 and turns < 4000 then
          row.turns_left = turns + 1
        end
        e.under_construction = row
        break
      end
    end
  end)
  local owner = plot:GetOwner(); if owner >= 0 then e.owner = owner end
  if e.improvement == "BARBARIAN_CAMP" then
    local q = H.kill_camp_quest_minors(e.x, e.y)
    if q and #q > 0 then e.cs_quest = q end
  end
  e.yields = plot_yields(plot)
  local okfw, fresh = pcall(function() return plot:IsFreshWater() end)
  if okfw and fresh then e.fresh_water = true end
  local okw, worked = pcall(function() return plot:IsBeingWorked() end)
  if okw and worked then e.worked = true end
  if plot:IsCity() then
    local c = plot:GetPlotCity()
    local city = { name = c:GetName(), owner = c:GetOwner(), pop = c:GetPopulation(), hp = c:GetMaxHitPoints() - c:GetDamage() }
    pcall(function() city.strength = c:GetStrengthValue() / 100 end)
    pcall(function() city.garrisoned = c:GetGarrisonedUnit() ~= nil end)
    if c.IsPuppet and c:IsPuppet() then city.puppet = true end
    if c.IsRazing and c:IsRazing() then city.razing = true end
    pcall(function()
      local maj = c.GetReligiousMajority and c:GetReligiousMajority() or -1
      if maj and maj > 0 and Game.GetReligionName then city.religion = H.L(Game.GetReligionName(maj)) end
      if maj == 0 then city.religion = "PANTHEON" end
    end)
    if c.GetNumFollowers and GameInfo.Religions then city.religions = H.city_religions(c) end
    e.city = city
  end
  local n = plot:GetNumUnits()
  if n > 0 then
    e.units = {}
    for i = 0, n - 1 do
      local u = plot:GetUnit(i)
      if u and not u:IsInvisible(team, false) then
        local ue = { owner = u:GetOwner(), id = u:GetID(), type = short(info_type(GameInfo.Units, u:GetUnitType())), hp = u:GetCurrHitPoints() }
        pcall(function() ue.strength = u:GetBaseCombatStrength() end)
        pcall(function() ue.ranged = u:GetRangedCombatStrength() end)
        local promos = H.unit_promotions(u)
        if #promos > 0 then ue.promotions = promos end
        e.units[#e.units + 1] = ue
      end
    end
    if #e.units == 0 then e.units = nil end
  end
  return e
end

function H.plots_around(x, y, r, team)
  team = team or Game.GetActiveTeam()
  local out = {}
  for dx = -r, r do for dy = -r, r do
    local plot = Map.PlotXYWithRangeCheck(x, y, dx, dy, r)
    local e = plot and H.describe_plot(plot, team)
    if e then out[#out + 1] = e end
  end end
  return out
end

function H.revealed_plots(team)
  team = team or Game.GetActiveTeam()
  local out = {}
  if Map.GetNumPlots and Map.GetPlotByIndex then
    for i = 0, Map.GetNumPlots() - 1 do
      local e = H.describe_plot(Map.GetPlotByIndex(i), team)
      if e then out[#out + 1] = e end
    end
    return out
  end
  local w, h = Map.GetGridSize()
  for y = 0, h - 1 do
    for x = 0, w - 1 do
      local e = H.describe_plot(Map.GetPlot(x, y), team)
      if e then out[#out + 1] = e end
    end
  end
  return out
end

function H.known_world(pid)
  local team = Players[pid]:GetTeam()
  return {
    empire = H.player_summary(pid),
    units = H.units(pid),
    cities = H.cities(pid),
    met = H.diplomacy(pid),
    plots = H.revealed_plots(team),
    notifications = H.notifications(pid),
  }
end

-- The whole revealed map as character grids, one byte per plot per layer, so a Huge map after Satellites
-- (10k revealed plots) costs ~10 KB a layer instead of ~140 B a plot. The point of the read is the `vis`
-- layer: a fogged plot ('~') shows what this team last saw there, which may be stale until a unit gets
-- eyes back on it -- exactly the human's situation. Every layer uses the same fog rules as describe_plot:
-- terrain/elevation/river are static; feature under fog is the remembered one (or '?' when the plot has
-- not been seen since the harness loaded, never the live read); improvement/route/owner under fog are the
-- engine's Revealed* values; resource is the team-gated GetResourceType. Live occupants and pillage state
-- appear only on visible plots. Legends are built from what is actually on the map, so a letter means
-- the same thing in every row of one reply (and may differ between replies).
local GRID_LAYERS = { "vis", "terrain", "elevation", "river", "owner", "feature", "improvement", "resource", "route" }
local TERRAIN_CHARS = { TERRAIN_GRASS = "G", TERRAIN_PLAINS = "P", TERRAIN_DESERT = "D", TERRAIN_TUNDRA = "T",
                        TERRAIN_SNOW = "S", TERRAIN_COAST = "C", TERRAIN_OCEAN = "O", TERRAIN_MOUNTAIN = "M",
                        TERRAIN_HILL = "H" }
local LEGEND_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

-- A dynamic legend: the first time a type is seen it gets the next letter; `.` is "none".
local function legend_new()
  return { chars = {}, names = {}, n = 0 }
end
local function legend_char(lg, name)
  if not name then return "." end
  local c = lg.chars[name]
  if c then return c end
  lg.n = lg.n + 1
  if lg.n > #LEGEND_ALPHABET then return "*" end  -- more kinds than letters: '*' = "other, see plot read"
  c = LEGEND_ALPHABET:sub(lg.n, lg.n)
  lg.chars[name] = c
  lg.names[c] = name
  return c
end

function H.revealed_map(pid, layers, x0, y0, x1, y1)
  local p = Players[pid]
  if not p then return { ok = false, err = "no such player" } end
  local team = p:GetTeam()
  local w, h = Map.GetGridSize()
  x0, y0 = math.max(0, x0 or 0), math.max(0, y0 or 0)
  x1, y1 = math.min(w - 1, x1 or (w - 1)), math.min(h - 1, y1 or (h - 1))
  if x1 < x0 or y1 < y0 then return { ok = false, err = "empty window", w = w, h = h } end
  local want = {}
  if type(layers) == "table" and #layers > 0 then
    for _, l in ipairs(layers) do want[l] = true end
  else
    for _, l in ipairs(GRID_LAYERS) do want[l] = true end
  end
  for l in pairs(want) do
    local known = false
    for _, g in ipairs(GRID_LAYERS) do if g == l then known = true end end
    if not known then return { ok = false, err = "unknown layer " .. tostring(l), layers = GRID_LAYERS } end
  end
  local out = { ok = true, w = w, h = h, window = { x0 = x0, y0 = y0, x1 = x1, y1 = y1 },
                turn = Game.GetGameTurn(), revealed = 0, visible = 0, fogged = 0,
                row_order = "rows[1] is y = y1 (north); each string runs x = x0 .. x1; odd rows sit half a hex to the east",
                layers = {}, legend = {} }
  local lg = { owner = legend_new(), feature = legend_new(), improvement = legend_new(), resource = legend_new(), route = legend_new() }
  local rows = {}
  for _, l in ipairs(GRID_LAYERS) do if want[l] then rows[l] = {} end end
  local owner_names = {}
  for y = y1, y0, -1 do
    local line = {}
    for _, l in ipairs(GRID_LAYERS) do if want[l] then line[l] = {} end end
    for x = x0, x1 do
      local plot = Map.GetPlot(x, y)
      local revealed = plot and plot:IsRevealed(team, false)
      local vis = revealed and plot:IsVisible(team, false)
      local c = {}
      if not revealed then
        for _, l in ipairs(GRID_LAYERS) do c[l] = " " end
      else
        out.revealed = out.revealed + 1
        if vis then out.visible = out.visible + 1 else out.fogged = out.fogged + 1 end
        c.vis = vis and "#" or "~"
        local tt = info_type(GameInfo.Terrains, plot:GetTerrainType())
        c.terrain = TERRAIN_CHARS[tt or ""] or "?"
        c.elevation = plot:IsMountain() and "M" or (plot:IsHills() and "^" or ".")
        c.river = plot:IsRiver() and "r" or "."
        local owner, imp, rt, feat
        if vis then
          owner = plot:GetOwner()
          imp = plot:GetImprovementType()
          rt = plot:GetRouteType()
          local f = plot:GetFeatureType()
          feat = (f >= 0) and short(info_type(GameInfo.Features, f)) or nil
          H.remember_feature(plot, team, f)
          if imp >= 0 and plot.IsImprovementPillaged and plot:IsImprovementPillaged() then imp = -2 end
          local okp, rp = pcall(function() return plot:IsRoutePillaged() end)
          if rt >= 0 and okp and rp then rt = -2 end
        else
          owner = plot:GetRevealedOwner(team, false)
          imp = plot:GetRevealedImprovementType(team, false)
          rt = plot:GetRevealedRouteType(team, false)
          feat = H.remembered_feature(plot, team)
          if feat == nil and H.seen_features and H.seen_features[team]
             and H.seen_features[team][feature_key(plot)] == nil then feat = "?" end
        end
        if owner and owner >= 0 then
          c.owner = legend_char(lg.owner, tostring(owner))
          if not owner_names[owner] then
            local o = Players[owner]
            local known = o and (owner == pid or (o.GetTeam and Teams[team]:IsHasMet(o:GetTeam())))
            owner_names[owner] = known and H.L(o:GetCivilizationShortDescription()) or "unmet"
          end
        else c.owner = "." end
        c.feature = (feat == "?") and "?" or legend_char(lg.feature, feat)
        c.improvement = (imp == -2) and "!" or ((imp and imp >= 0) and legend_char(lg.improvement, short(info_type(GameInfo.Improvements, imp))) or ".")
        c.route = (rt == -2) and "!" or ((rt and rt >= 0) and legend_char(lg.route, short(info_type(GameInfo.Routes, rt))) or ".")
        local res = plot:GetResourceType(team)
        c.resource = (res >= 0) and legend_char(lg.resource, short(info_type(GameInfo.Resources, res))) or "."
      end
      for _, l in ipairs(GRID_LAYERS) do if want[l] then line[l][#line[l] + 1] = c[l] end end
    end
    for _, l in ipairs(GRID_LAYERS) do if want[l] then rows[l][#rows[l] + 1] = table.concat(line[l]) end end
  end
  for _, l in ipairs(GRID_LAYERS) do if want[l] then out.layers[l] = rows[l] end end
  out.legend.common = { [" "] = "unrevealed", ["."] = "none" }
  if want.vis then out.legend.vis = { ["#"] = "visible now", ["~"] = "revealed but fogged: what you see there is what was last seen and may be stale" } end
  if want.terrain then
    local t = {}
    for k, v in pairs(TERRAIN_CHARS) do t[v] = short(k) end
    t["?"] = "other"
    out.legend.terrain = t
  end
  if want.elevation then out.legend.elevation = { ["^"] = "hills", ["M"] = "mountain", ["."] = "flat" } end
  if want.river then out.legend.river = { ["r"] = "river on an edge" } end
  if want.owner then
    local t = {}
    for name, ch in pairs(lg.owner.chars) do
      local id = tonumber(name)
      t[ch] = { player_id = id, name = owner_names[id] }
    end
    out.legend.owner = t
  end
  if want.feature then
    local t = {}
    for ch, name in pairs(lg.feature.names) do t[ch] = name end
    t["?"] = "not seen since load: feature unknown under fog"
    out.legend.feature = t
  end
  if want.improvement then
    local t = {}
    for ch, name in pairs(lg.improvement.names) do t[ch] = name end
    t["!"] = "pillaged improvement (visible plots only)"
    out.legend.improvement = t
  end
  if want.resource then
    local t = {}
    for ch, name in pairs(lg.resource.names) do t[ch] = name end
    out.legend.resource = t
  end
  if want.route then
    local t = {}
    for ch, name in pairs(lg.route.names) do t[ch] = name end
    t["!"] = "pillaged route (visible plots only)"
    out.legend.route = t
  end
  out.note = "vis '~' plots are stale: units, cities, borders, improvements and features there may have changed since last seen. map_window(x, y, r) reads one area in full; map_index lists cities, camps and resources."
  return out
end

-- Compact Strategic View-style index: what a human actually scans the map for, instead of every plot.
-- Fogged tiles use revealed resource/improvement/owner only; never live feature or occupants.
function H.map_index(pid)
  local p = Players[pid]
  if not p then return { ok = false, err = "no such player" } end
  local team, team_obj = p:GetTeam(), Teams[p:GetTeam()]
  local resources, camps, ruins, cities, nws, wonders = {}, {}, {}, {}, {}, {}
  for i = 0, GameDefines.MAX_CIV_PLAYERS - 1 do
    local o = Players[i]
    if o and o:IsAlive() and i ~= pid and team_obj:IsHasMet(o:GetTeam()) then
      for c in o:Cities() do
        local plot = c:Plot()
        if plot and plot:IsRevealed(team, false) then
          local vis = plot:IsVisible(team, false) and true or false
          local row = { name = c:GetName(), owner = i, x = c:GetX(), y = c:GetY(), vis = vis }
          if o:IsMinorCiv() then row.minor = true end
          if c:IsCapital() then row.capital = true end
          cities[#cities + 1] = row
        end
      end
    end
  end
  local nplots = Map.GetNumPlots and Map.GetNumPlots() or 0
  for i = 0, nplots - 1 do
    local plot = Map.GetPlotByIndex(i)
    if plot and plot:IsRevealed(team, false) then
      local vis = plot:IsVisible(team, false) and true or false
      local res = plot:GetResourceType(team)
      if res >= 0 then
        local info = GameInfo.Resources[res]
        if info and info.ResourceClassType ~= "RESOURCECLASS_BONUS" then
          local e = { x = plot:GetX(), y = plot:GetY(), resource = info.Type, vis = vis }
          if vis then
            local okq, qty = pcall(function() return plot:GetNumResource() end)
            if okq and qty and qty > 1 then e.qty = qty end
          end
          resources[#resources + 1] = e
        end
      end
      local imp = vis and plot:GetImprovementType() or plot:GetRevealedImprovementType(team, false)
      if imp and imp >= 0 then
        local t = info_type(GameInfo.Improvements, imp)
        if t == "IMPROVEMENT_BARBARIAN_CAMP" then
          local camp = { x = plot:GetX(), y = plot:GetY(), vis = vis }
          local q = H.kill_camp_quest_minors(camp.x, camp.y, pid)
          if q and #q > 0 then camp.cs_quest = q end
          camps[#camps + 1] = camp
        elseif t == "IMPROVEMENT_GOODY_HUT" then
          ruins[#ruins + 1] = { x = plot:GetX(), y = plot:GetY(), vis = vis }
        end
      end
      if vis then
        local f = plot:GetFeatureType()
        if f and f >= 0 then
          local feat = GameInfo.Features[f]
          if feat and (feat.NaturalWonder == true or feat.NaturalWonder == 1) then
            nws[#nws + 1] = { x = plot:GetX(), y = plot:GetY(), feature = feat.Type }
          end
        end
      end
    end
  end
  local wo = H.wonder_overview(pid)
  for _, row in ipairs(wo.wonders or {}) do
    if row.x then wonders[#wonders + 1] = row end
  end
  return { ok = true, resources = resources, camps = camps, ruins = ruins,
    foreign_cities = cities, natural_wonders = nws, wonders = wonders }
end

-- Shared with later fragments, which import these at their top (load order: harness/runtime_source.py MANIFEST).
H._ns.resource_hover = resource_hover
