-- Harness runtime injected into the InGame Lua state through the tuner.
-- Everything lives under the global table H so re-injection is idempotent.
local RUNTIME_VERSION = 4
if H and H.version == RUNTIME_VERSION then return end
local old = H
H = { version = RUNTIME_VERSION, events = old and old.events or {}, event_seq = old and old.event_seq or 0,
      cursor = old and old.cursor or 0, hook_fns = old and old.hook_fns or {} }

---------------------------------------------------------------- JSON
local function esc(s)
  return s:gsub('[%c"\\]', function(c)
    if c == '"' then return '\\"' elseif c == '\\' then return '\\\\'
    elseif c == '\n' then return '\\n' elseif c == '\r' then return '\\r' elseif c == '\t' then return '\\t'
    else return string.format('\\u%04x', c:byte()) end end)
end
function H.json(v, depth)
  depth = depth or 0
  local t = type(v)
  if t == "nil" then return "null"
  elseif t == "boolean" then return v and "true" or "false"
  elseif t == "number" then
    if v ~= v or v == math.huge or v == -math.huge then return "null" end
    if v == math.floor(v) then return string.format("%d", v) end
    return string.format("%.6g", v)
  elseif t == "string" then return '"' .. esc(v) .. '"'
  elseif t == "table" then
    if depth > 14 then return '"<deep>"' end
    if v[1] ~= nil or next(v) == nil then
      local parts = {}
      for i = 1, #v do parts[i] = H.json(v[i], depth + 1) end
      return "[" .. table.concat(parts, ",") .. "]"
    end
    local parts = {}
    for k, val in pairs(v) do parts[#parts + 1] = '"' .. esc(tostring(k)) .. '":' .. H.json(val, depth + 1) end
    return "{" .. table.concat(parts, ",") .. "}"
  else return '"<' .. t .. '>"' end
end
function H.emit(v) print("@@HJ@@" .. H.json(v) .. "@@HJ@@") end

---------------------------------------------------------------- helpers
local function L(key) -- localize a TXT_KEY
  if key == nil or key == "" then return "" end
  local ok, s = pcall(Locale.ConvertTextKey, key)
  return ok and s or tostring(key)
end
H.L = L
local function info_type(tbl, id) local r = tbl[id]; return r and r.Type or nil end
local function short(t) return t and t:gsub("^[A-Z]+_", "") or nil end  -- UNIT_WARRIOR -> WARRIOR

---------------------------------------------------------------- event recorder
function H.record(kind, data)
  H.event_seq = H.event_seq + 1
  H.events[#H.events + 1] = { seq = H.event_seq, turn = Game.GetGameTurn(), kind = kind, data = data }
  if #H.events > 3000 then table.remove(H.events, 1) end
end
function H.events_since(seq)
  local out = {}
  for _, e in ipairs(H.events) do if e.seq > seq then out[#out + 1] = e end end
  return out
end
function H.take_events()  -- everything since the previous take_events() call; cursor lives in the game
  local out = H.events_since(H.cursor)
  H.cursor = H.event_seq
  return out
end
function H.install_hooks()
  local function hook(name, fn)
    local ev = Events[name]
    if not ev then return end
    local prev = H.hook_fns[name]
    if prev then local ok = pcall(function() ev.Remove(prev) end) end
    local wrapped = function(...) local ok, err = pcall(fn, ...); if not ok then H.record("hook_error", {name=name, err=tostring(err)}) end end
    ev.Add(wrapped)
    H.hook_fns[name] = wrapped
  end
  hook("ActivePlayerTurnStart", function() H.record("turn_start", { player = Game.GetActivePlayer() }) end)
  hook("ActivePlayerTurnEnd", function() H.record("turn_end", { player = Game.GetActivePlayer() }) end)
  hook("GameplaySetActivePlayer", function(new, old) H.record("active_player", { new = new, old = old }) end)
  hook("SerialEventUnitDestroyed", function(playerID, unitID) H.record("unit_destroyed", { player = playerID, unit = unitID }) end)
  hook("SerialEventCityCreated", function(hex, playerID, cityID) H.record("city_created", { player = playerID, city = cityID, x = hex and hex.x, y = hex and hex.y }) end)
  hook("SerialEventCityDestroyed", function(hex, playerID, cityID) H.record("city_destroyed", { player = playerID, city = cityID }) end)
  hook("SerialEventCityCaptured", function(hex, playerID, cityID, newPlayerID) H.record("city_captured", { player = playerID, city = cityID, by = newPlayerID }) end)
  hook("WarStateChanged", function(team1, team2, atWar) H.record("war_state", { team1 = team1, team2 = team2, at_war = atWar }) end)
  hook("GameMessageChat", function(from, to, text, target) H.record("chat", { from = from, to = to, text = text, target = target }) end)
  hook("EndCombatSim", function(attPlayer, attUnit, attDmg, attFinal, attMax, defPlayer, defUnit, defDmg, defFinal, defMax)
    H.record("combat", { att_player = attPlayer, att_unit = attUnit, att_dmg = attDmg, att_hp = attFinal, def_player = defPlayer, def_unit = defUnit, def_dmg = defDmg, def_hp = defFinal }) end)
  hook("NotificationAdded", function(id, type, toolTip, summary, data1, data2, playerID)
    H.record("notification", { id = id, ntype = type, text = toolTip, summary = summary, d1 = data1, d2 = data2, player = playerID }) end)
  hook("AILeaderMessage", function(playerID, diploState, message, animation, data1)
    H.record("leader_message", { player = playerID, state = H.diplo_state_name(diploState), text = message })
  end)
  hook("GameplayAlertMessage", function(text) H.record("alert", { text = text }) end)
  hook("SerialEventEnterCityScreen", function() end)
end

---------------------------------------------------------------- snapshots
function H.player_summary(pid)
  local p = Players[pid]
  local research = p:GetCurrentResearch()
  local era = GameInfo.Eras[p:GetCurrentEra()]
  return {
    id = pid, name = p:GetName(), civ = p:GetCivilizationShortDescription(), leader = L(GameInfo.Leaders[p:GetLeaderType()].Description),
    human = p:IsHuman(), alive = p:IsAlive(), turn_active = p:IsTurnActive(), team = p:GetTeam(), score = p:GetScore(),
    gold = p:GetGold(), gold_per_turn = p:CalculateGoldRate(), science = p:GetScience(),
    research = research >= 0 and short(info_type(GameInfo.Technologies, research)) or nil,
    research_turns_left = research >= 0 and p:GetResearchTurnsLeft(research, true) or nil,
    culture = p:GetJONSCulture(), culture_per_turn = p:GetTotalJONSCulturePerTurn(), next_policy_cost = p:GetNextPolicyCost(),
    faith = p:GetFaith(), faith_per_turn = p:GetTotalFaithPerTurn(),
    happiness = p:GetExcessHappiness(), golden_age_turns = p:GetGoldenAgeTurns(), era = era and short(era.Type),
    num_cities = p:GetNumCities(), num_units = p:GetNumUnits(), military_might = p:GetMilitaryMight(),
    turn = Game.GetGameTurn(), year = Game.GetGameTurnYear(),
  }
end

function H.units(pid)
  local p = Players[pid]
  local out = {}
  for u in p:Units() do
    local plot = u:GetPlot()
    local mission = u.GetMissionType and u:GetMissionType() or -1
    out[#out + 1] = {
      id = u:GetID(), type = short(info_type(GameInfo.Units, u:GetUnitType())), name = u:GetName(),
      x = u:GetX(), y = u:GetY(), moves = u:MovesLeft() / GameDefines.MOVE_DENOMINATOR, max_moves = u:MaxMoves() / GameDefines.MOVE_DENOMINATOR,
      hp = u:GetCurrHitPoints(), max_hp = u:GetMaxHitPoints(), strength = u:GetBaseCombatStrength(),
      ranged = (u.GetRangedCombatStrength and u:GetRangedCombatStrength() or 0), range = (u.Range and u:Range() or 0),
      embarked = u:IsEmbarked(), fortified = u:GetFortifyTurns() > 0, automated = u:IsAutomated(), ready = u:IsReadyToMove(),
      mission = mission, domain = short(info_type(GameInfo.Domains, u:GetDomainType())),
      level = u.GetLevel and u:GetLevel() or nil, xp = u.GetExperience and u:GetExperience() or nil,
      can_found = (u.CanFound and plot and u:CanFound(plot)) or false,
      in_city = plot and plot:IsCity() or false,
    }
  end
  return out
end

function H.cities(pid)
  local p = Players[pid]
  local out = {}
  for c in p:Cities() do
    local prod = c:GetProductionNameKey()
    out[#out + 1] = {
      id = c:GetID(), name = c:GetName(), x = c:GetX(), y = c:GetY(), pop = c:GetPopulation(), capital = c:IsCapital(),
      puppet = c:IsPuppet(), occupied = c:IsOccupied(), razing = c:IsRazing(), hp = c:GetMaxHitPoints() - c:GetDamage(), max_hp = c:GetMaxHitPoints(),
      strength = c:GetStrengthValue() / 100,
      production = prod ~= "" and L(prod) or nil, production_turns = c:GetProductionTurnsLeft(), queue_len = c:GetOrderQueueLength(),
      food = c:GetYieldRate(YieldTypes.YIELD_FOOD), production_yield = c:GetYieldRate(YieldTypes.YIELD_PRODUCTION),
      gold = c:GetYieldRate(YieldTypes.YIELD_GOLD), science = c:GetYieldRate(YieldTypes.YIELD_SCIENCE),
      culture = c:GetJONSCulturePerTurn(), faith = c:GetFaithPerTurn(),
      food_stored = c:GetFood(), growth_turns = c:GetFoodTurnsLeft(), local_happiness = c:GetLocalHappiness(),
      garrisoned = c:GetGarrisonedUnit() ~= nil, coastal = c:IsCoastal(),
    }
  end
  return out
end

-- plots within radius r of (x,y) that the active team can see/has revealed
function H.plots_around(x, y, r, team)
  team = team or Game.GetActiveTeam()
  local out = {}
  for dx = -r, r do for dy = -r, r do
    local plot = Map.PlotXYWithRangeCheck(x, y, dx, dy, r)
    if plot and plot:IsRevealed(team, false) then
      local vis = plot:IsVisible(team, false)
      local e = { x = plot:GetX(), y = plot:GetY(), t = short(info_type(GameInfo.Terrains, plot:GetTerrainType())) }
      if plot:IsHills() then e.hills = true end
      if plot:IsMountain() then e.mountain = true end
      if plot:IsRiver() then e.river = true end
      local f = plot:GetFeatureType(); if f >= 0 then e.feature = short(info_type(GameInfo.Features, f)) end
      local res = plot:GetResourceType(team); if res >= 0 then e.resource = short(info_type(GameInfo.Resources, res)) end
      local imp = plot:GetImprovementType(); if imp >= 0 then e.improvement = short(info_type(GameInfo.Improvements, imp)) end
      local rt = plot:GetRouteType(); if rt >= 0 then e.route = short(info_type(GameInfo.Routes, rt)) end
      local owner = plot:GetOwner(); if owner >= 0 then e.owner = owner end
      if plot:IsCity() then local c = plot:GetPlotCity(); e.city = { name = c:GetName(), owner = c:GetOwner(), pop = c:GetPopulation(), hp = c:GetMaxHitPoints() - c:GetDamage() } end
      if vis then
        e.vis = true
        local n = plot:GetNumUnits()
        if n > 0 then
          e.units = {}
          for i = 0, n - 1 do
            local u = plot:GetUnit(i)
            if u then e.units[#e.units + 1] = { owner = u:GetOwner(), id = u:GetID(), type = short(info_type(GameInfo.Units, u:GetUnitType())), hp = u:GetCurrHitPoints() } end
          end
        end
      end
      out[#out + 1] = e
    end
  end end
  return out
end

function H.notifications(pid)
  local p = Players[pid]
  local out = {}
  local n = p:GetNumNotifications()
  for i = 0, n - 1 do
    if not p:GetNotificationDismissed(i) then
      out[#out + 1] = { index = i, turn = p:GetNotificationTurn(i), summary = p:GetNotificationSummaryStr(i), text = p:GetNotificationStr(i) }
    end
  end
  return out
end

function H.diplomacy(pid)
  local p = Players[pid]
  local myTeam = Teams[p:GetTeam()]
  local out = {}
  for other = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
    local o = Players[other]
    if other ~= pid and o:IsAlive() and o:IsEverAlive() then
      local met = myTeam:IsHasMet(o:GetTeam())
      out[#out + 1] = {
        id = other, civ = o:GetCivilizationShortDescription(), leader = o:GetName(), human = o:IsHuman(), met = met,
        at_war = met and myTeam:IsAtWar(o:GetTeam()) or false,
        approach = met and (o.GetMajorCivApproach and o:GetMajorCivApproach(pid)) or nil,
        score = met and o:GetScore() or nil, cities = met and o:GetNumCities() or nil,
      }
    end
  end
  return out
end

-- Reverse lookup for DiploUIStateTypes, built lazily and cached (the enum is a live global, not
-- necessarily present the moment the runtime loads).
function H.diplo_state_name(v)
  if not H._diplo_names then
    local ok, names = pcall(function()
      local t = {}
      for k, id in pairs(DiploUIStateTypes) do t[id] = k end
      return t
    end)
    H._diplo_names = ok and names or {}
  end
  return H._diplo_names[v] or v
end

-- Fire a diplomatic event directly on the engine, bypassing the leader-head/discussion UI entirely.
-- `event_name` is the FromUIDiploEventTypes key with or without its FROM_UI_DIPLO_EVENT_ prefix.
-- See docs/NOTES.md for the full enum and which files call each one (from static analysis of the
-- game's own Lua). NOT exhaustively live-verified: HUMAN_DECLARES_WAR / HUMAN_NEGOTIATE_PEACE / DENOUNCE
-- were confirmed to resolve to real enum ids; actually firing one was not tested against a live game.
function H.diplo_event(event_name, other_player, data1, data2)
  local key = event_name
  if not key:match("^FROM_UI_DIPLO_EVENT_") then key = "FROM_UI_DIPLO_EVENT_" .. key end
  local id = FromUIDiploEventTypes[key]
  if id == nil then return { ok = false, err = "unknown diplo event " .. tostring(event_name) } end
  Game.DoFromUIDiploEvent(id, other_player, data1 or 0, data2 or 0)
  return { ok = true, event = key }
end

function H.turn_state(pid)
  local p = Players[pid]
  local net = Game.IsNetworkMultiPlayer()
  local sent = net and Network.HasSentNetTurnComplete() or false
  local mode = PreGame.IsHotSeatGame() and "hotseat" or (net and (PreGame.IsInternetGame() and "internet" or "lan")) or "single"
  return {
    active_player = Game.GetActivePlayer(), my_turn = Game.GetActivePlayer() == pid and p:IsTurnActive() and not sent,
    turn = Game.GetGameTurn(), blocking = p:GetEndTurnBlockingType(), num_units_needing_moves = p.GetNumUnitsNeedingMoves and p:GetNumUnitsNeedingMoves() or nil,
    processing = Game.IsProcessingMessages(), paused = Game.IsPaused(), hotseat = PreGame.IsHotSeatGame(),
    mode = mode, turn_complete_sent = sent,
    simultaneous = net and Game.IsOption(GameOptionTypes.GAMEOPTION_SIMULTANEOUS_TURNS) or false,
    dynamic_turns = net and Game.IsOption(GameOptionTypes.GAMEOPTION_DYNAMIC_TURNS) or false,
    turn_timer = net and Game.IsOption(GameOptionTypes.GAMEOPTION_END_TURN_TIMER_ENABLED) or false,
    everyone_connected = net and Network.IsEveryoneConnected() or nil,
    game_state = Game.GetGameState(),
  }
end

-- Human players in a network game: who is connected / has ended their turn (for "waiting on" digests).
function H.net_players()
  local out = {}
  for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
    local p = Players[i]
    if p and p:IsEverAlive() and p:IsHuman() then
      out[#out+1] = { id = i, name = p:GetName(), civ = L(p:GetCivilizationShortDescriptionKey()), alive = p:IsAlive(),
                      turn_active = p:IsTurnActive(), connected = Network.IsPlayerConnected(i),
                      ended_turn = p.HasReceivedNetTurnComplete and p:HasReceivedNetTurnComplete() or nil }
    end
  end
  return out
end

H.install_hooks()
