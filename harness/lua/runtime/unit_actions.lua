-- Shared by earlier fragments (load order: harness/runtime_source.py MANIFEST).
local L, info_type, plain_text, short = H._ns.L, H._ns.info_type, H._ns.plain_text, H._ns.short

-- Interface-mode orders have MissionType=-1 in GameInfoActions. Read their mapping
-- from InterfaceModes, and use the same target predicates as the stock highlights.
function H.targeted_missions(u)
  local out = {}
  local function add(mode, enabled)
    local row = GameInfo.InterfaceModes[mode]
    if enabled and row and row.Mission then
      out[#out + 1] = { type = mode, kind = "interface", mission = row.Mission,
        target_view = "targets", help = H.action_help(u, mode, row.Help) }
    end
  end
  local air = u:GetDomainType() == DomainTypes.DOMAIN_AIR
  local sweep = false
  if air then
    for pr in GameInfo.UnitPromotions() do
      if pr.AirSweepCapable and u:IsHasPromotion(pr.ID) then sweep = true end
    end
  end
  add("INTERFACEMODE_REBASE", air)
  add("INTERFACEMODE_AIRSTRIKE", air and u:CanAirAttack())
  add("INTERFACEMODE_AIR_SWEEP", sweep)
  add("INTERFACEMODE_PARADROP", u:GetDropRange() > 0)
  add("INTERFACEMODE_AIRLIFT", u:CanAirlift(u:GetPlot(), false))
  add("INTERFACEMODE_NUKE", u:CanNuke())
  return out
end

-- GitLab #87 (Assyria t239-t273): MISSION_TRADE is legal only inside a city-state's land, so the plot-by-plot
-- targets read never listed it for a Great Merchant standing at home. The merchant's targets are the met
-- city-states: the nearest revealed plot of each one's land to the unit, the distance, and the engine's own gold
-- and influence for the mission there (Unit:GetTradeGold / GetTradeInfluence).
function H.trade_mission_targets(unit_id, pid)
  local p = Players[pid]
  local u = p:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  local team = p:GetTeam()
  local ux, uy = u:GetX(), u:GetY()
  local out = {}
  for i = 0, (GameDefines.MAX_CIV_PLAYERS or 64) - 1 do
    local o = Players[i]
    local okm, minor = pcall(function() return o and o:IsAlive() and o:IsMinorCiv() and Teams[team]:IsHasMet(o:GetTeam()) end)
    if okm and minor then
      pcall(function()
        local cap = o:GetCapitalCity()
        if not cap then return end
        local cx, cy = cap:GetX(), cap:GetY()
        local best, bd = nil, nil
        for dx = -3, 3 do for dy = -3, 3 do
          local q = Map.PlotXYWithRangeCheck(cx, cy, dx, dy, 3)
          if q and q:IsRevealed(team, false) and q:GetOwner() == i then
            local d = Map.PlotDistance(ux, uy, q:GetX(), q:GetY())
            if not bd or d < bd then best, bd = q, d end
          end
        end end
        if not best then return end
        local row = { city_state = cap:GetName(), player_id = i, x = best:GetX(), y = best:GetY(), distance = bd,
                      capital = { x = cx, y = cy } }
        pcall(function() row.gold = u:GetTradeGold(best) end)
        pcall(function() row.influence = u:GetTradeInfluence(best) end)
        pcall(function() if Teams[team]:IsAtWar(o:GetTeam()) then row.at_war = true end end)
        out[#out + 1] = row
      end)
    end
  end
  table.sort(out, function(a, b) return (a.distance or 999) < (b.distance or 999) end)
  return { ok = true, unit_id = unit_id, mission = "MISSION_TRADE", targets = out, total = #out,
           note = "a trade mission runs inside a city-state's land: move onto the plot (x, y), then MISSION_TRADE there; "
               .. "gold and influence are the engine's figures for that plot" }
end

-- GitLab #106 (Maya t18-t54): three Settlers were placed from map windows around guesses. The engine's own site
-- value (Plot:GetFoundValue, what its AI settles by) for every revealed plot within six of the Settler where a
-- city may be founded, with what a human reads off the tile: fresh water, river, coast, hills, the resources in
-- the first ring, the distance to walk and to the nearest city of ours. The value is given only where the first
-- ring is fully revealed (the engine's number counts tiles the seat has not seen); the rest say so.
function H.settle_sites(unit_id, pid)
  local p = Players[pid]
  local u = p:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  local team = p:GetTeam()
  local ux, uy = u:GetX(), u:GetY()
  local cities = {}
  for c in p:Cities() do cities[#cities + 1] = { name = c:GetName(), x = c:GetX(), y = c:GetY() } end
  local out = {}
  for dx = -6, 6 do for dy = -6, 6 do
    local q = Map.PlotXYWithRangeCheck(ux, uy, dx, dy, 6)
    if q and q:IsRevealed(team, false) then
      local okf, can = pcall(function() return u:CanFound(q) end)
      if okf and can then
        local row = { x = q:GetX(), y = q:GetY(), distance = Map.PlotDistance(ux, uy, q:GetX(), q:GetY()) }
        pcall(function() row.fresh_water = q:IsFreshWater() and true or false end)
        pcall(function() row.river = q:IsRiver() and true or false end)
        pcall(function() row.coastal = q:IsCoastalLand() and true or false end)
        pcall(function() row.hills = q:IsHills() and true or false end)
        local ring_ok, resources = true, {}
        for d = 0, 5 do
          local n = Map.PlotDirection(q:GetX(), q:GetY(), d)
          if not n or not n:IsRevealed(team, false) then ring_ok = false
          else
            pcall(function()
              local res = n:GetResourceType(team)
              if res and res >= 0 then resources[#resources + 1] = short(info_type(GameInfo.Resources, res)) end
            end)
          end
        end
        row.ring_resources = resources
        if ring_ok then
          pcall(function() row.value = q:GetFoundValue(pid) end)
        else
          row.value_note = "first ring not fully revealed: the engine's site value would count tiles you have not seen"
        end
        local best, bd
        for _, c in ipairs(cities) do
          local d = Map.PlotDistance(c.x, c.y, q:GetX(), q:GetY())
          if not bd or d < bd then best, bd = c, d end
        end
        if best then row.nearest_city = { name = best.name, distance = bd } end
        out[#out + 1] = row
      end
    end
  end end
  table.sort(out, function(a, b)
    local av, bv = a.value or -1, b.value or -1
    if av ~= bv then return av > bv end
    return a.distance < b.distance
  end)
  local top = {}
  for i = 1, math.min(10, #out) do top[i] = out[i] end
  return { ok = true, unit_id = unit_id, mission = "MISSION_FOUND", targets = top, total = #out,
           note = "revealed plots within six where a city can be founded, best engine site value first (the AI's own measure; "
               .. "null where the first ring is not all revealed); move there, then MISSION_FOUND -- a Settler arriving with moves "
               .. "left founds the same turn" }
end

function H.unit_mission_targets(unit_id, mission, pid, offset, limit)
  local u = Players[pid]:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  local supported, mode = false, nil
  for _, row in ipairs(H.targeted_missions(u)) do
    if row.mission == mission then supported, mode = true, row.type end
  end
  if not supported then
    if mission == "MISSION_TRADE" then return H.trade_mission_targets(unit_id, pid) end
    if mission == "MISSION_FOUND" then return H.settle_sites(unit_id, pid) end
    if mission == "MISSION_MOVE_TO" or mission == "MISSION_ROUTE_TO" then
      -- GitLab #135: a move has no target list; the destination is any revealed plot.
      return { ok = false, missions = H.targeted_missions(u),
               err = "a move has no target list: any revealed plot is a destination. state(what='unit', id, view='tactical') "
                     .. "lists the six neighbours with move open / refused and the grid; order(to='unit', action='move', args={x, y}) goes there" }
    end
    return { ok = false, err = "mission is not offered for this unit", missions = H.targeted_missions(u) }
  end
  offset, limit = math.max(0, offset or 0), math.max(1, math.min(100, limit or 100))
  local out, total = {}, 0
  local origin, team = u:GetPlot(), Players[pid]:GetTeam()
  for i = 0, Map.GetNumPlots() - 1 do
    local pl = Map.GetPlotByIndex(i)
    -- Target legality can otherwise reveal hidden occupants. Never query it under fog.
    if pl:IsVisible(team, false) then
      local x, y, legal = pl:GetX(), pl:GetY(), false
      if mission == "MISSION_REBASE" then legal = u:CanRebaseAt(origin, x, y)
      elseif mission == "MISSION_PARADROP" then legal = u:CanParadropAt(origin, x, y)
      elseif mission == "MISSION_AIRLIFT" then legal = u:CanAirliftAt(origin, x, y)
      elseif mission == "MISSION_NUKE" then legal = u:CanNukeAt(x, y)
      elseif mode == "INTERFACEMODE_AIRSTRIKE" then legal = u:CanRangeStrikeAt(x, y, true, true)
      else legal = u:CanStartMission(GameInfoTypes[mission], x, y, false) end
      if legal and u:MovesLeft() > 0 then
        total = total + 1
        if total > offset and #out < limit then
          local target = { x = x, y = y }
          if mode == "INTERFACEMODE_AIRSTRIKE" then
            for k, v in pairs(H.ranged_target_info(u, pl, pid)) do target[k] = v end
          end
          out[#out + 1] = target
        end
      end
    end
  end
  return { ok = true, unit_id = unit_id, mission = mission, targets = out, total = total,
    next_offset = offset + #out < total and offset + #out or nil, scope = "currently visible plots only" }
end

-- The sentence under a unit-action button (unitpanel.lua TipHandler). Most buttons print
-- `action.Help` straight from GameInfoActions; a handful print a computed line instead (upgrade
-- names the unit and the price, scrap the gold, a golden age its length, paradrop its range).
-- Live t221: BUILD_CITADEL listed "+1 production, -1 food" and nothing about claiming territory,
-- which is the only reason anyone builds one. Same defect class as v152's promotion names.
-- v216 splits the two: the static sentences are printed once per action in reference("actions")
-- (H.action_static_help); only the computed ones, which change per unit, still ride on the row.
local ACTION_HELP_KEY = {
  MISSION_DISCOVER = "TXT_KEY_MISSION_DISCOVER_TECH_HELP",
  MISSION_HURRY = "TXT_KEY_MISSION_HURRY_PRODUCTION_HELP",
  MISSION_TRADE = "TXT_KEY_MISSION_CONDUCT_TRADE_MISSION_HELP",
  MISSION_GIVE_POLICIES = "TXT_KEY_MISSION_GIVE_POLICIES_HELP",
  MISSION_ONE_SHOT_TOURISM = "TXT_KEY_MISSION_ONE_SHOT_TOURISM_HELP",
  MISSION_SELL_EXOTIC_GOODS = "TXT_KEY_MISSION_SELL_EXOTIC_GOODS_HELP",
  MISSION_SPREAD_RELIGION = "TXT_KEY_MISSION_SPREAD_RELIGION_HELP",
  MISSION_CREATE_GREAT_WORK = "TXT_KEY_MISSION_CREATE_GREAT_WORK_HELP",
}

function H.action_help(u, atype, raw_help)
  local function num(fn, ...)
    if not u or not u[fn] then return nil end
    local ok, v = pcall(u[fn], u, ...)
    if ok and type(v) == "number" then return v end
  end
  local function key(k, ...)
    local ok, s = pcall(Locale.ConvertTextKey, k, ...)
    if ok and type(s) == "string" and s ~= "" then return s end
  end
  if atype == "COMMAND_UPGRADE" then
    local to = num("GetUpgradeUnitType")
    local row = to and to >= 0 and GameInfo.Units[to]
    if row then return key("TXT_KEY_UPGRADE_HELP", row.Description, num("UpgradePrice", to) or 0) end
  elseif atype == "COMMAND_DELETE" then
    return key("TXT_KEY_SCRAP_HELP", num("GetScrapGold") or 0)
  elseif atype == "MISSION_GOLDEN_AGE" then
    return key("TXT_KEY_MISSION_START_GOLDENAGE_HELP", num("GetGoldenAgeTurns") or 0)
  elseif atype == "INTERFACEMODE_PARADROP" then
    return key("TXT_KEY_INTERFACEMODE_PARADROP_HELP_WITH_RANGE", num("GetDropRange") or 0)
  elseif atype == "MISSION_ALERT" then
    -- The panel replaces the fortify text on a unit that can never fortify (civilians, air).
    local ok, fortifyable = pcall(function() return u:IsEverFortifyable() end)
    if ok and not fortifyable then return key("TXT_KEY_MISSION_ALERT_NO_FORTIFY_HELP") end
  end
  return nil  -- static text: reference("actions")
end

-- The static sentence for one action (the panel's default `action.Help`, or the great-person key the
-- panel substitutes), for the reference. nil when the row has none.
function H.action_static_help(atype, raw_help)
  if ACTION_HELP_KEY[atype] then
    local ok, s = pcall(Locale.ConvertTextKey, ACTION_HELP_KEY[atype])
    if ok and type(s) == "string" and s ~= "" then return plain_text(s) end
  end
  -- The Actions table spells "no help" as the string "NONE"/"None", and ConvertTextKey hands back
  -- anything it cannot resolve unchanged -- so MISSION_SWAP_UNITS read as help "None" (live t221).
  if raw_help == nil or raw_help == "" or raw_help == "NONE" or raw_help == "None" then return nil end
  local s = L(raw_help)
  if s == "" or s == raw_help then return nil end
  return plain_text(s)
end

-- Stock: choosetradeunitnewhome.lua and chooseadmiralnewport.lua. Both popups open on a unit standing
-- in one of my cities, list the engine's own candidate set
-- (Player:GetPotentialTradeUnitNewHomeCity / GetPotentialAdmiralNewPort) and push
-- MISSION_CHANGE_TRADE_UNIT_HOME_CITY / MISSION_CHANGE_ADMIRAL_PORT at the chosen city's plot.
-- `unit_mission` could already send those missions; nothing said which cities were on the list, and
-- a caravan re-homed nearer a rich partner is the difference between a 6-gold route and a 12-gold one.
local HOME_MISSIONS = {
  trade = { mission = "MISSION_CHANGE_TRADE_UNIT_HOME_CITY", getter = "GetPotentialTradeUnitNewHomeCity",
            what = "trade unit" },
  admiral = { mission = "MISSION_CHANGE_ADMIRAL_PORT", getter = "GetPotentialAdmiralNewPort",
              what = "Great Admiral" },
}
H.home_mission_names = { MISSION_CHANGE_TRADE_UNIT_HOME_CITY = true, MISSION_CHANGE_ADMIRAL_PORT = true }

local function home_kind(u)
  local ok, trade = pcall(function() return u:IsTrade() end)
  if ok and trade then return "trade" end
  local row = GameInfo.Units[u:GetUnitType()]
  if row and (row.Class == "UNITCLASS_GREAT_ADMIRAL" or row.Type == "UNIT_GREAT_ADMIRAL") then
    return "admiral"
  end
end

function H.unit_home_options(unit_id, pid)
  local p = Players[pid]
  local u = p:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  local kind = home_kind(u)
  if not kind then
    return { ok = false, err = "only a trade unit or a Great Admiral has a home city to change" }
  end
  local spec = HOME_MISSIONS[kind]
  local out = { ok = true, unit_id = unit_id, kind = kind, mission = spec.mission,
                how_to_apply = "order(to='unit', id=" .. unit_id .. ", action='mission', args={mission='" .. spec.mission .. "', x=<x>, y=<y>})" }
  -- The popup's "Starting City" line is the city the unit is standing in; outside one there is no
  -- button to press at all.
  local plot = u:GetPlot()
  local here = plot and plot:IsCity() and plot:GetPlotCity()
  if not (here and here:GetOwner() == pid) then
    out.ok, out.can, out.cities = false, false, {}
    out.err = "a " .. spec.what .. " changes its home city from inside one of my cities; this one is at ("
              .. u:GetX() .. "," .. u:GetY() .. ")"
    return out
  end
  out.current_home = { name = here:GetName(), x = here:GetX(), y = here:GetY() }
  local m = MissionTypes and MissionTypes[spec.mission]
  local okc, can = pcall(function() return u:CanStartMission(m, -1, -1, false) end)
  out.can = (okc and can) and true or false
  local cities = {}
  if p[spec.getter] then
    pcall(function()
      for _, v in ipairs(p[spec.getter](p, u)) do
        local pl = Map.GetPlot(v.X, v.Y)
        local c = pl and pl:GetPlotCity()
        if c then cities[#cities + 1] = { name = c:GetName(), x = v.X, y = v.Y, owner = c:GetOwner() } end
      end
    end)
  end
  out.cities = cities
  if #cities == 0 and out.can then
    out.note = "the engine offers no other city for this unit right now"
  end
  return out
end

-- GitLab #130 (Grok, Siam t30): a Worker on jungle cocoa with Calendar known was refused BUILD_PLANTATION with the
-- bare legal list, and the plot never appeared among the build plots. The engine's rule (CIV5Builds.xml,
-- BuildFeatures): a build on a plot with a feature removes the feature as part of the work and needs that
-- removal's tech -- a plantation on Jungle needs Bronze Working, on Forest Mining, on Marsh Masonry. Name it.
local function has_tech(team, tech_type)
  local ok, v = pcall(function()
    local id = GameInfoTypes[tech_type]
    return id ~= nil and Teams[team]:IsHasTech(id) or false
  end)
  return ok and v or false
end

function H.feature_tech_gap(build_type, pl, team)
  local f = pl:GetFeatureType()
  if not f or f < 0 then return nil end
  local ftype = info_type(GameInfo.Features, f)
  local gap
  pcall(function()
    for fr in GameInfo.BuildFeatures{ BuildType = build_type } do
      if fr.BuildType == build_type and fr.FeatureType == ftype and fr.PrereqTech and not has_tech(team, fr.PrereqTech) then
        gap = { needs_tech = fr.PrereqTech, feature = short(ftype) }
      end
    end
  end)
  return gap
end

-- The builds a plot's resource calls for that this unit cannot start there because a feature-removal tech is
-- missing: { build, needs_tech, feature, reason }. Empty for a plot without a resource or a feature.
function H.blocked_builds(u, pl, team)
  local out = {}
  local res = pl:GetResourceType(team)
  if not res or res < 0 then return out end
  local rtype = info_type(GameInfo.Resources, res)
  pcall(function()
    for b in GameInfo.Builds() do
      if b.ImprovementType then
        local fits = false
        for r in GameInfo.Improvement_ResourceTypes{ ImprovementType = b.ImprovementType, ResourceType = rtype } do
          if r.ResourceType == rtype then fits = true end
        end
        if fits then
          local okc, can = pcall(function() return u:CanBuild(pl, b.ID) end)
          if not (okc and can) then
            local gap = H.feature_tech_gap(b.Type, pl, team)
            if gap then
              out[#out + 1] = { build = b.Type, needs_tech = gap.needs_tech, feature = gap.feature,
                                reason = b.Type .. " on " .. gap.feature .. " removes the " .. gap.feature .. " as part of the build, which needs "
                                         .. gap.needs_tech .. " (state(what='options', view='research'))" }
            end
          end
        end
      end
    end
  end)
  return out
end

-- The reason a MISSION_BUILD was refused on the unit's own plot, when the engine's rule is one the harness can name
-- (#130): nil when it cannot.
function H.build_refusal_why(unit_id, build_type, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  if not u then return nil end
  local gap = H.feature_tech_gap(build_type, u:GetPlot(), Players[pid]:GetTeam())
  if gap then
    return build_type .. " on " .. gap.feature .. " removes the " .. gap.feature .. " as part of the build, which needs "
           .. gap.needs_tech .. "; research it (state(what='options', view='research')) or improve another plot meanwhile"
  end
  return nil
end

-- The city-state that owns the plot a unit stands on: COMMAND_GIFT's recipient (TXT_KEY_COMMAND_GIFT_HELP: "the
-- player who controls the land the unit is standing on"). nil on unowned land, mine, or a major civ's -- a gift
-- to a major is not an order the harness takes (live Maya t234: a Musician on Venice's plot was offered gift_unit).
function H.gift_target(u, pid)
  local plot = u.GetPlot and u:GetPlot() or nil
  local owner = plot and plot:GetOwner() or -1
  if owner == nil or owner < 0 or owner == pid then return nil end
  local o = Players[owner]
  if not (o and o.IsMinorCiv and o:IsMinorCiv()) then return nil end
  return { id = owner, name = L(o:GetCivilizationShortDescription()), minor = true }
end

function H.available_unit_actions(unit_id, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  -- Do not UI.SelectUnit / CanHandleAction here: selecting a unit flips 2D/3D.
  -- Per-unit CanStartMission / CanBuild / CanDoCommand / CanAutomate are selection-free.
  local actions = {}
  local build_ids = {}   -- builds legal on the CURRENT plot (for the nearby scan below)
  local all_builds = {}  -- every BUILD_* action this unit class could ever do
  local help_by_type = {}  -- the computed button line (upgrade price, scrap gold, ...); static help is in reference("actions")
  -- GitLab #142: the Great Person missions this unit's class has but the engine withholds right now go to
  -- `missing`, each with why (great_people.lua) -- the stock panel's greyed-out buttons, in words.
  local class_missions, missing = H.gp_class_missions(u), {}
  if GameInfoActions then
    for i = 0, #GameInfoActions do
      local a = GameInfoActions[i]
      if a and a.Type then
        local kind = "other"
        if a.Type:match("^BUILD_") and a.MissionData and a.MissionData ~= -1 then
          all_builds[#all_builds + 1] = { id = a.MissionData, type = a.Type }
        end
        if a.Type:match("^MISSION_") then kind = "mission"
        elseif a.Type:match("^BUILD_") then kind = "build"
        elseif a.Type:match("^COMMAND_") then kind = "command"
        elseif a.Type:match("^INTERFACEMODE_") then kind = "interface" end
        if kind == "interface" or a.Type:match("^CONTROL_") or a.Type == "COMMAND_HOTKEY"
           or a.Type:match("^PROMOTION_") or a.Type == "MISSION_SWAP_UNITS" then
          -- MISSION_SWAP_UNITS: CanStartMission says yes to every unit, the engine accepts the order and no unit
          -- moves (live England t225), and the GAMEMESSAGE_SWAP_UNITS path crashed the game. unit_mission refuses
          -- it with the two-move recipe; a row that is never legal to run is not advertised (GitLab #71).
          -- skip: global UI, not a unit order. PROMOTION_* rows are the chooser's buttons (CommandType
          -- COMMAND_PROMOTION with the promotion in CommandData): CanDoCommand without the data says yes to
          -- every one of them once the unit can promote at all, so a wounded Spearman listed the whole
          -- catalogue, 200 rows, live 2026-09-27 (Grok, t62). The chooser's real rows are `promotions`.
        else
          local legal = false
          if kind == "build" and u.CanBuild and a.MissionData and a.MissionData ~= -1 then
            -- Unit:CanBuild(plot, build) -- the one-arg form errors and the pcall hid it, so no
            -- BUILD_* action was ever listed for a Worker (fixed v48, China game t247).
            local ok, v = pcall(function() return u:CanBuild(u:GetPlot(), a.MissionData) end)
            legal = ok and v
            if legal then build_ids[#build_ids + 1] = { id = a.MissionData, type = a.Type } end
          elseif a.MissionType and a.MissionType ~= -1 and u.CanStartMission then
            -- One-arg CanStartMission is too loose (great-person missions return true
            -- on a warrior). The unit-panel shape is (mission, -1, -1, bTestVisible=false).
            local ok, v = pcall(function() return u:CanStartMission(a.MissionType, -1, -1, false) end)
            legal = ok and v
          elseif a.Type:match("^AUTOMATE_") and u.CanAutomate and a.AutomateType and a.AutomateType ~= -1 then
            local ok, v = pcall(function() return u:CanAutomate(a.AutomateType) end)
            legal = ok and v
          elseif a.CommandType and a.CommandType ~= -1 and u.CanDoCommand then
            local ok, v = pcall(function() return u:CanDoCommand(a.CommandType) end)
            legal = ok and v
          end
          if legal and kind == "mission" and H.NEEDS_MOVES and H.NEEDS_MOVES[a.Type] and u:MovesLeft() <= 0 then
            legal = false   -- #112 / #83: a mission that acts cannot run at 0 moves; unit_mission would refuse it
          end
          -- COMMAND_GIFT gives the unit to the plot's owner; the harness gifts to city-states alone, so the row
          -- is listed on a city-state's plot only and names it (#142: on Venice's land it offered gift_unit).
          local gift = legal and a.Type == "COMMAND_GIFT" and H.gift_target(u, pid) or nil
          if legal and a.Type == "COMMAND_GIFT" and not gift then legal = false end
          if legal then
            help_by_type[a.Type] = H.action_help(u, a.Type, a.Help)
            actions[#actions + 1] = {
              type = a.Type, kind = kind,
              mission = (kind == "build" and "MISSION_BUILD") or (kind == "mission" and a.Type or nil),
              yield = H.great_person_yield(u, a.Type),
              help = help_by_type[a.Type],
              -- These two open a chooser rather than acting: say where its list lives.
              target_view = H.home_mission_names[a.Type] and "home" or nil,
              owner = gift, minor_id = gift and gift.id or nil,
            }
          elseif kind == "mission" and class_missions[a.Type] then
            missing[#missing + 1] = H.gp_withheld(u, a, pid)
          end
        end
      end
    end
  end
  if GameInfo and GameInfo.InterfaceModes and u.GetDomainType then
    for _, row in ipairs(H.targeted_missions(u)) do actions[#actions + 1] = row end
  end
  -- The promotion chooser's rows: enum + the name on the button. The effect text ("+33% Combat
  -- Strength when intercepting" vs "+33% chance to intercept") is in reference("promotions").
  local promotions = H.promotion_options(u)
  -- Workers / work boats: where nearby could this unit build something? Radius-2 scan of plots
  -- I own (or that carry a resource), each with the builds legal THERE. Routes (road/railroad)
  -- are legal almost everywhere so they are listed separately and never make a plot "interesting".
  local nearby = nil
  local is_worker = false
  if u.WorkRate then
    local ok, v = pcall(function() return u:WorkRate(true) end)
    is_worker = ok and type(v) == "number" and v > 0
  end
  if u.CanBuild and #all_builds > 0 and (is_worker or #build_ids > 0) then
    nearby = {}
    local team = Players[pid]:GetTeam()
    local ux, uy = u:GetX(), u:GetY()
    for dy = -2, 2 do
      for dx = -2, 2 do
        local pl = Map.GetPlot(ux + dx, uy + dy)
        if pl and not (dx == 0 and dy == 0) and Map.PlotDistance(ux, uy, pl:GetX(), pl:GetY()) <= 2
           and pl:IsRevealed(team, false) and (pl:GetOwner() == pid or pl:GetResourceType(team) >= 0) then
          -- Only plots that still NEED work: no improvement yet, or a pillaged one. Replacing a
          -- working improvement (every plot lists FARM/TRADING_POST/FORT over what is there) is
          -- rarely what a player wants and buried the real work in noise on the first live run.
          local imp = pl:GetImprovementType()
          local pillaged = imp >= 0 and pl:IsImprovementPillaged()
          if imp < 0 or pillaged then
            local builds, routes = {}, {}
            for _, b in ipairs(all_builds) do
              local ok, v = pcall(function() return u:CanBuild(pl, b.id) end)
              if ok and v then
                if b.type == "BUILD_ROAD" or b.type == "BUILD_RAILROAD" then routes[#routes + 1] = b.type
                elseif b.type ~= "BUILD_FORT" and b.type ~= "BUILD_REMOVE_ROUTE" then builds[#builds + 1] = b.type end
              end
            end
            local blocked = H.blocked_builds(u, pl, team)
            if #builds > 0 or #blocked > 0 then
              local info = {}
              for _, btype in ipairs(builds) do
                local row = { build = btype }
                local bid
                for _, b in ipairs(all_builds) do if b.type == btype then bid = b.id end end
                if bid then
                  pcall(function()
                    local extra = 0
                    if u.WorkRate then extra = u:WorkRate(true, bid) or 0 end
                    local turns = pl:GetBuildTurnsLeft(bid, pid, extra, extra)
                    if type(turns) == "number" and turns > 0 and turns < 4000 then row.turns = turns end
                  end)
                  pcall(function()
                    local delta, names = {}, { "food", "production", "gold", "science", "culture", "faith" }
                    for i = 0, 5 do
                      local with = pl:GetYieldWithBuild(bid, i, false, pid)
                      local now = pl:CalculateYield(i)
                      local d = (with or 0) - (now or 0)
                      if d ~= 0 then delta[names[i + 1]] = d end
                    end
                    if next(delta) then row.yield_delta = delta end
                  end)
                end
                -- No help row here: a build's sentence is static (reference("actions")); the numbers
                -- that differ per plot are turns and yield_delta above.
                info[#info + 1] = row
              end
              local e = { x = pl:GetX(), y = pl:GetY(), builds = builds, build_info = info, owned = pl:GetOwner() == pid,
                          t = short(info_type(GameInfo.Terrains, pl:GetTerrainType())) }
              if pl:IsHills() then e.hills = true end
              local f = pl:GetFeatureType()
              if f >= 0 then e.feature = short(info_type(GameInfo.Features, f)) end
              if #routes > 0 then e.routes = routes end
              if imp >= 0 then
                e.improvement = short(info_type(GameInfo.Improvements, imp))
                e.pillaged = true
              end
              local res = pl:GetResourceType(team)
              if res >= 0 then e.resource = short(info_type(GameInfo.Resources, res)) end
              if #blocked > 0 then e.blocked = blocked end
              nearby[#nearby + 1] = e
            end
          end
        end
      end
    end
  end
  local here_blocked = nil
  if u.CanBuild and #all_builds > 0 and is_worker then
    local okb, b = pcall(H.blocked_builds, u, u:GetPlot(), Players[pid]:GetTeam())
    if okb and type(b) == "table" and #b > 0 then here_blocked = b end
  end
  return {
    ok = true, actions = actions, promotions = promotions, blocked_builds = here_blocked,
    missing = (#missing > 0) and missing or nil,   -- Great Person missions withheld here, with why (#142)
    x = u:GetX(), y = u:GetY(),
    moves = u:MovesLeft() / GameDefines.MOVE_DENOMINATOR,
    nearby_builds = nearby,
    dig_sites = H.dig_sites and H.dig_sites(u, pid) or nil,   -- Archaeologists only (builds.lua, #140)
    attack_targets = H.melee_targets(u, pid),
    ranged_targets = H.ranged_targets(u, pid),
  }
end

-- Legal actions for many units in one read (v213). Step 4 of the loop called available_unit_actions
-- once per unit: on the late S1 map (38 units) that was 38 tuner round-trips a turn, most of the ~15
-- minutes scripts/play_loop.py spent on one turn. One query answers for every unit that still needs
-- an order (H.todo's units) plus every unit with a promotion waiting, or for exactly the ids given.
-- `full` keeps the computed button line (upgrade price, scrap gold) on each action row; without it a row keeps type / kind / mission /
-- yield / target_view and the reply is a fraction of the size. Promotion rows always keep name and
-- help: that text is the choice.
function H.todo_actions(pid, ids, full)
  local p = Players[pid]
  local list, source = {}, "ids"
  if ids == nil or #ids == 0 then
    source = "todo"
    local todo = H.todo(pid)
    if not todo then
      return { ok = false, err = "this seat is not active: nothing is on the todo list until it is our turn (pass unit_ids to read specific units anyway)" }
    end
    local seen = {}
    for _, u in ipairs(todo.units) do
      if not seen[u.id] then seen[u.id] = true; list[#list + 1] = u.id end
    end
    for _, id in ipairs(todo.promotions or {}) do
      if not seen[id] then seen[id] = true; list[#list + 1] = id end
    end
  else
    for _, id in ipairs(ids) do list[#list + 1] = id end
  end
  local out = { ok = true, source = source, n = #list, units = {} }
  for _, id in ipairs(list) do
    local r = H.available_unit_actions(id, pid)
    r.id = id
    local u = p:GetUnitByID(id)
    if u then
      local ut = GameInfo and GameInfo.Units and GameInfo.Units[u:GetUnitType()]
      r.type = ut and short(ut.Type) or u:GetUnitType()
      if u.IsPromotionReady and u:IsPromotionReady() then r.promotion_ready = true end
      -- A damaged unit's hit points ride on its row (v220, #35): the summary level keeps them, and whether
      -- to heal, fortify or attack starts there. A full-health unit carries neither key.
      if u.GetDamage and u:GetDamage() > 0 and u.GetCurrHitPoints then
        r.hp, r.max_hp = u:GetCurrHitPoints(), u:GetMaxHitPoints()
      end
    end
    if not full then
      for _, a in ipairs(r.actions or {}) do a.help = nil end
      for _, e in ipairs(r.nearby_builds or {}) do
        for _, row in ipairs(e.build_info or {}) do row.help = nil end
      end
    end
    out.units[#out.units + 1] = r
  end
  return out
end
