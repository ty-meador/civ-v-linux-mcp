-- Harness runtime injected into the InGame Lua state through the tuner.
-- Everything lives under the global table H so re-injection is idempotent.
local RUNTIME_VERSION = 155
if H and H.version == RUNTIME_VERSION then return end
local old = H
-- _enum_names is intentionally NOT carried over from `old`: it is a pure cache derived from live game
-- globals, not accumulated state, and carrying a stale (possibly wrong, e.g. built by since-fixed buggy
-- code) cache across a version bump is exactly how a real fix here silently failed to take effect once
-- already -- caught live. Only genuinely irreplaceable state (recorded events, hook closures needed to
-- Events.Remove() them) belongs in the carry-over list below.
H = { version = RUNTIME_VERSION, events = old and old.events or {}, event_seq = old and old.event_seq or 0,
      cursors = old and old.cursors or {}, popups = old and old.popups or {},
      hook_fns = old and old.hook_fns or {}, _enum_names = {},
      -- dedupe memory for engine events that fire more than once (notifications re-added at the hotseat
      -- hand-off, popups re-queued, war state per direction): wiping it on a reload re-reports them
      seen_notes = old and old.seen_notes or {}, popup_rows = old and old.popup_rows or {},
      last_war_key = old and old.last_war_key or nil,
      known_sites = old and old.known_sites or {},  -- team -> plot index -> true: ruins/camps already reported (H.new_sites)
      pending_moves = old and old.pending_moves or {},  -- unit_id -> {x, y}: standing move orders (see H.resume_moves)
      alive_majors = old and old.alive_majors or nil }  -- player id -> true at the last turn start (H.check_eliminations)

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

-- Unit orders go through the game's own network path (v86). Unit:PushMission / Unit:DoCommand mutate
-- only THIS process's gamecore: fine for a single human seat, and it survived on a LAN host because the
-- host's copy wins every resync, but on a LAN client the host never sees the order. Live 2026-09-17:
-- the Deck seat founded its capital that way, the host logged "sync request for City which does not
-- exist locally", force-resynced the client to a state with no city, and the game marked that player
-- defeated at turn 1. Civ5XP has no Network.SendPushMission/SendDoCommand; the UI (unitpanel.lua,
-- worldview.lua) uses Game.SelectionListGameNetMessage on the selected unit, so that is what we do.
-- UI.SelectUnit flips 2D/3D on the local screen (the old reason for avoiding it); correctness wins.
local function own_active_unit(unit_id, pid)
  if Game.GetActivePlayer() ~= pid then
    return nil, { ok = false, err = "this seat is not active" }
  end
  local u = Players[pid]:GetUnitByID(unit_id)
  if not u then return nil, { ok = false, err = "no such unit" } end
  return u, nil
end

local function info_id(name)
  if name == nil or name == "" then return nil end
  if GameInfoTypes and GameInfoTypes[name] ~= nil then return GameInfoTypes[name] end
  if MissionTypes and MissionTypes[name] ~= nil then return MissionTypes[name] end
  return nil
end

local function move_denom()
  return (GameDefines and GameDefines.MOVE_DENOMINATOR) or 60
end

local function require_revealed_plot(x, y, pid, u)
  -- Revealed-but-fogged is legal to path into; unrevealed is not. Do not read
  -- live occupants here — IsRevealed is static discovered info.
  if x == nil or y == nil or x < 0 or y < 0 then return nil end
  local plot = Map.GetPlot(x, y)
  if not plot then return { ok = false, err = "no such plot" } end
  local team = Players[pid]:GetTeam()
  if plot.IsRevealed and not plot:IsRevealed(team) then
    -- Help an explorer: the nearest revealed plots around the target (same domain as the unit when
    -- known), so the caller can step to the edge of the known map instead of guessing coordinates.
    local near = {}
    pcall(function()  -- advisory only: never let the hint break the refusal itself
      local want_water = nil
      if u and u.GetDomainType and DomainTypes then want_water = (u:GetDomainType() == DomainTypes.DOMAIN_SEA) end
      for r = 1, 4 do
        for dy = -r, r do
          for dx = -r, r do
            local q = Map.GetPlot(x + dx, y + dy)
            if q and Map.PlotDistance(x, y, q:GetX(), q:GetY()) == r and q:IsRevealed(team)
               and (want_water == nil or q:IsWater() == want_water) and not q:IsImpassable() then
              near[#near + 1] = { x = q:GetX(), y = q:GetY(), distance = r }
            end
          end
        end
        if #near >= 3 then break end
      end
    end)
    return { ok = false, err = "plot is not revealed",
             hint = "use map_window to see the known map; nearest_revealed lists revealed plots near the target (same domain as the unit)",
             nearest_revealed = near }
  end
  return nil
end

local function selected_is(u)
  local ok, h = pcall(function() return UI.GetHeadSelectedUnit() end)
  return ok and h ~= nil and h:GetID() == u:GetID() and h:GetOwner() == u:GetOwner()
end

-- Send a GAMEMESSAGE_PUSH_MISSION / GAMEMESSAGE_DO_COMMAND for `u` the way the unit panel does:
-- select the unit, then Game.SelectionListGameNetMessage(msg, d2, d3, d4, flags, alt, shift). Selection
-- can land on a later frame (a same-call SelectUnit+send silently no-op'd in an earlier build), so when
-- the head-selected unit is not `u` after SelectUnit this returns select_pending=true and the Python
-- wrapper (Game._order) re-issues the same call. The order itself is applied on a later game update
-- (network round trip, even locally), so callers must poll for the effect, never read it back inline.
local function net_unit_message(u, msg, d2, d3, d4)
  if not (Game and Game.SelectionListGameNetMessage) then
    return { ok = false, err = "Game.SelectionListGameNetMessage unavailable" }
  end
  if not selected_is(u) then
    local ok, err = pcall(function() UI.SelectUnit(u) end)
    if not ok then return { ok = false, err = "UI.SelectUnit failed: " .. tostring(err) } end
    if not selected_is(u) then
      return { ok = false, select_pending = true, err = "unit selected; the order must be re-issued" }
    end
  end
  local ok, err = pcall(function()
    Game.SelectionListGameNetMessage(msg, d2, d3, d4, 0, false, false)
  end)
  if not ok then return { ok = false, err = "SelectionListGameNetMessage failed: " .. tostring(err) } end
  return { ok = true }
end

local function push_mission(u, mission, d1, d2)
  local msg = GameMessageTypes and GameMessageTypes.GAMEMESSAGE_PUSH_MISSION
  if msg == nil then return { ok = false, err = "GAMEMESSAGE_PUSH_MISSION unavailable" } end
  return net_unit_message(u, msg, mission, d1, d2)
end

local function do_command(u, cmd, d1, d2)
  local msg = GameMessageTypes and GameMessageTypes.GAMEMESSAGE_DO_COMMAND
  if msg == nil then return { ok = false, err = "GAMEMESSAGE_DO_COMMAND unavailable" } end
  return net_unit_message(u, msg, cmd, d1, d2)
end

---------------------------------------------------------------- event recorder
-- Who fought, as the combat animation shows it to the active player: captured inside the EndCombatSim
-- hook, while the unit still exists (a killed unit is in delayed death, not gone yet). Our own side is
-- always described; the other side only while its plot is visible to us and the unit is not invisible
-- (submarines), and its owner is named only once met -- otherwise "Unknown", like the unit flag.
-- Who owns something, as the viewer is allowed to know it: "you", "Barbarians", the civ's short name
-- once met, "Unknown" otherwise. Never leaks the identity of a civ we have not met.
function H.owner_label(pid, viewer)
  viewer = viewer or Game.GetActivePlayer()
  local p = Players[pid]
  if viewer < 0 or not p then return nil end
  if pid == viewer then return "you" end
  if p:IsBarbarian() then return "Barbarians" end
  if Teams[Players[viewer]:GetTeam()]:IsHasMet(p:GetTeam()) then return p:GetCivilizationShortDescription() end
  return "Unknown"
end

function H.combat_side(pid, uid, viewer)
  viewer = viewer or Game.GetActivePlayer()
  local p = Players[pid]
  if viewer < 0 or not p then return nil end
  local team = Players[viewer]:GetTeam()
  local out = { owner = H.owner_label(pid, viewer) }
  local u = p:GetUnitByID(uid)
  if not u then return out end
  local plot = u:GetPlot()
  if pid ~= viewer and not (plot and plot:IsVisible(team, false) and not u:IsInvisible(team, false)) then return out end
  out.unit = short(info_type(GameInfo.Units, u:GetUnitType()))
  out.x, out.y = u:GetX(), u:GetY()
  out.hp, out.max_hp = u:GetCurrHitPoints(), u:GetMaxHitPoints()
  out.killed = u:IsDelayedDeath() or u:GetCurrHitPoints() <= 0 or nil
  out.ranged = (u.GetRangedCombatStrength and u:GetRangedCombatStrength() or 0) > 0 or nil
  return out
end

-- With quick combat on (always, in multiplayer) RunCombatSim/EndCombatSim never fire: a fight is two
-- SerialEventUnitSetDamage(player, unit, newDamage, oldDamage) -- defender, then attacker -- followed
-- by the GameplayAlertMessage banner ("Your Warrior (29 damage) attacked an enemy Brute (36 damage)!").
-- Live-audited 2026-09-18 with a human at the screen, three fights, identical each time. One `damage`
-- row per unit the viewer can see; healing (newDamage < oldDamage) is not combat and is skipped.
-- Hotseat: the AI phase runs while the PREVIOUS human is still the active player, so a hit on another
-- human seat's unit is filed for that seat, not for whoever happens to be active.
function H.unit_damaged(pid, uid, newDmg, oldDmg)
  local dmg = (newDmg or 0) - (oldDmg or 0)
  local viewer = Game.GetActivePlayer()
  local p = Players[pid]
  if dmg <= 0 or viewer < 0 or not p then return end
  -- AI-phase events arrive in a batch after every fight has resolved, so the unit's live hp is the
  -- FINAL value for each of them (live: two hits on a Scout both read "46 left"): take it from the event.
  local function at_event(side)
    if side and side.max_hp then
      side.hp = math.max(0, side.max_hp - newDmg)
      if side.hp <= 0 then side.killed = true end
    end
    return side
  end
  if pid ~= viewer and p:IsHuman() and PreGame.IsHotSeatGame() then
    H.record("damage", { player = pid, unit_id = uid, dmg = dmg, side = at_event(H.combat_side(pid, uid, pid)) }, pid)
  end
  local side = H.combat_side(pid, uid)
  if not side or (pid ~= viewer and not side.unit) then return end  -- side.unit is only set when we can see it
  H.record("damage", { player = pid, unit_id = uid, dmg = dmg, side = at_event(side) })
end

-- Hit points of our own units, snapshotted when our turn ends and compared when the next one starts:
-- EndCombatSim is a graphics event and does not fire for combat the engine resolves without an
-- animation (quick combat, off-screen AI phase), so an unexplained loss is reported on its own.
function H.hp_snapshot(pid)
  local snap = {}
  for u in Players[pid]:Units() do
    snap[u:GetID()] = { hp = u:GetCurrHitPoints(), unit = short(info_type(GameInfo.Units, u:GetUnitType())), x = u:GetX(), y = u:GetY() }
  end
  H.hp_snap = { player = pid, units = snap }
end
function H.hp_compare(pid)
  local s = H.hp_snap
  if not s or s.player ~= pid then return end
  H.hp_snap = nil
  local p = Players[pid]
  for id, was in pairs(s.units) do
    local u = p:GetUnitByID(id)
    if not u or u:IsDelayedDeath() then
      H.record("unit_lost", { player = pid, unit_id = id, unit = was.unit, x = was.x, y = was.y, hp_before = was.hp })
    elseif u:GetCurrHitPoints() < was.hp then
      H.record("unit_hurt", { player = pid, unit_id = id, unit = was.unit, x = u:GetX(), y = u:GetY(),
                              hp_before = was.hp, hp = u:GetCurrHitPoints() })
    end
  end
end

-- A met major civ that died since the last turn start (the game announces it to everyone who knew it). Live
-- t444: India conquered America, our declaration-of-friendship partner, and the digest only showed four
-- "deal ended" notices. The first call just takes the snapshot.
function H.check_eliminations(viewer)
  local now = {}
  for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
    local p = Players[i]
    if p and p:IsAlive() and not p:IsMinorCiv() then now[i] = true end
  end
  local before = H.alive_majors
  H.alive_majors = now
  if not before or viewer < 0 then return end
  local team = Teams[Players[viewer]:GetTeam()]
  for i in pairs(before) do
    local p = Players[i]
    if not now[i] and i ~= viewer and team:IsHasMet(p:GetTeam()) then
      H.record("civ_eliminated", { player = i, civ = Locale.Lookup(p:GetCivilizationShortDescriptionKey()),
                                   leader = p:GetName() })
    end
  end
end

-- `audience` overrides who the row is for (default: the active player); only H.unit_damaged passes it.
function H.record(kind, data, audience)
  local viewer = Game.GetActivePlayer()
  if viewer < 0 then return end
  -- Engine events include information which the active player cannot see.
  -- Capture the audience now; never infer visibility later after the fog changes.
  if kind == "unit_destroyed" or kind == "city_created" or kind == "city_destroyed" then
    if data.player ~= viewer then return end
  elseif kind == "city_captured" then
    if data.player ~= viewer and data.by ~= viewer then return end
  elseif kind == "combat" then
    if data.att_player ~= viewer and data.def_player ~= viewer then return end
  elseif kind == "notification" then
    if data.player ~= viewer then return end
    -- Hotseat re-adds every live notification when the panel is rebuilt at the hand-off: same id, same
    -- text, fired twice (live 2026-09-18). One bubble on screen is one row here.
    H.seen_notes = H.seen_notes or {}
    local key = data.player .. ":" .. tostring(data.id)
    if H.seen_notes[key] == data.text then return end
    H.seen_notes[key] = data.text
    pcall(H.locate_notification, data)  -- never lose the row over its location
  elseif kind == "war_state" then
    local team = Players[viewer]:GetTeam()
    if data.team1 ~= team and data.team2 ~= team then return end
    -- The engine fires it once per direction ([0,3,true] then [3,0,true], live 2026-09-18): one row.
    local a, b = math.min(data.team1, data.team2), math.max(data.team1, data.team2)
    local key = a .. ":" .. b .. ":" .. tostring(data.at_war) .. ":" .. Game.GetGameTurn()
    if H.last_war_key == key then return end
    H.last_war_key = key
  elseif kind == "chat" then
    -- Target enum semantics vary by mode; only record our own outgoing chat.
    if data.from ~= viewer then return end
  end
  H.event_seq = H.event_seq + 1
  H.events[#H.events + 1] = { seq = H.event_seq, turn = Game.GetGameTurn(), audience = audience or viewer, kind = kind, data = data }
  if #H.events > 3000 then table.remove(H.events, 1) end
end
function H.events_since(seq, pid)
  local out = {}
  for _, e in ipairs(H.events) do
    if e.seq > seq and e.audience == pid then
      if e.data.site_pending then  -- the plot was not revealed yet inside the hook: one retry, at read time
        pcall(H.locate_notification, e.data)
        e.data.site_pending = nil
      end
      out[#out + 1] = e
    end
  end
  return out
end

-- Where a notification points. A human clicks the bubble and the camera jumps there; the event itself
-- carries no plot (live 2026-09-18: "Ruins discovered" / "Barbarian Encampment discovered" arrive with
-- data -1,-1), so the place is read back from what the team can see.
-- Ruins/camps: visible plots showing that improvement which no earlier row reported. The first call for
-- a team seeds the memory with the sites it knows but cannot see right now.
function H.new_sites(team, improvement)
  local imp = GameInfoTypes[improvement]
  if not imp then return {} end
  local known = H.known_sites[team]
  local seed = known == nil
  if seed then known = {}; H.known_sites[team] = known end
  local out = {}
  for i = 0, Map.GetNumPlots() - 1 do
    local plot = Map.GetPlotByIndex(i)
    if plot:IsRevealed(team, false) and plot:GetRevealedImprovementType(team, false) == imp and not known[i] then
      if plot:IsVisible(team, false) then
        known[i] = true
        out[#out + 1] = { x = plot:GetX(), y = plot:GetY() }
      elseif seed then
        known[i] = true
      end
    end
  end
  return out
end
local SITE_NOTIFICATIONS = { NOTIFICATION_GOODY = "IMPROVEMENT_GOODY_HUT", NOTIFICATION_BARBARIAN = "IMPROVEMENT_BARBARIAN_CAMP" }
function H.locate_notification(data)
  local p = Players[data.player]
  if not p then return end
  for name, improvement in pairs(SITE_NOTIFICATIONS) do
    if data.ntype and NotificationTypes[name] == data.ntype then
      local sites = H.new_sites(p:GetTeam(), improvement)
      if #sites > 0 then data.sites = sites; data.site_pending = nil else data.site_pending = true end
      return
    end
  end
  -- City growth carries the city id in d1 (live: "Venice has Grown!" d1 = 8192).
  if data.ntype == NotificationTypes.NOTIFICATION_CITY_GROWTH then
    local city = p:GetCityByID(data.d1 or -1)
    if city then data.x, data.y = city:GetX(), city:GetY() end
  -- A promotion carries the unit id in d2 (live: d1 = 83 unit type, d2 = 16385).
  elseif data.ntype == NotificationTypes.NOTIFICATION_UNIT_PROMOTION then
    local unit = p:GetUnitByID(data.d2 or -1)
    if unit then data.unit_id = data.d2; data.x, data.y = unit:GetX(), unit:GetY() end
  end
  -- "Machu has been converted to another religion!" never names the new majority (live t179: a
  -- 2-2 tie, cities().religion was nil). Attach the city-banner tooltip the click would show.
  H.attach_conversion_banner(data, p)
  -- "Steal Technology" names the victim civ but not which tech (live t181: Inca, only Sailing).
  -- The click opens BUTTONPOPUP_CHOOSE_TECH_TO_STEAL; attach the same list steal_tech_options returns.
  H.attach_steal_tech(data, p)
  -- "Losing Gold!" names the empty treasury but not current GPT / strike / that unpaid
  -- expenses come out of science (live t182: gold 0, gpt −23, IsStrike still false).
  H.attach_gold_deficit(data, p)
end

-- Pending spy-steal chooser. The engine's EndTurnBlockingType is one-at-a-time, so this can sit
-- behind POLICY/PRODUCTION/etc. (live t181: blocking_name was POLICY, pending_popups empty,
-- GetNumTechsToSteal(Inca) == 1). A human still sees the notification and can open the chooser.
function H.attach_steal_tech(data, p)
  if not (data and p) then return end
  local text = type(data.text) == "string" and data.text or ""
  local summary = type(data.summary) == "string" and data.summary or ""
  if not (summary:find("Steal Technology", 1, true) or text:find("steal a technology", 1, true)) then
    return
  end
  local ok, steal = pcall(H.steal_tech_options, data.player or Game.GetActivePlayer())
  if ok and type(steal) == "table" and (steal.n or 0) > 0 then
    data.steal_tech = steal.victims
    data.hint = "steal_tech_options then steal_tech"
  end
end

-- Empty-treasury notice: GPT, whether units are already on strike, and the science hit.
function H.attach_gold_deficit(data, p)
  if not (data and p) then return end
  local text = type(data.text) == "string" and data.text or ""
  local summary = type(data.summary) == "string" and data.summary or ""
  if not (summary:find("Losing Gold", 1, true) or text:find("treasury is empty", 1, true)) then
    return
  end
  pcall(function() data.gold = p:GetGold() end)
  pcall(function() data.gold_per_turn = p:CalculateGoldRate() end)
  local ok_s, strike = pcall(function() return p:IsStrike() end)
  if ok_s then data.is_strike = strike and true or false end
  local ok_t, turns = pcall(function() return p:GetStrikeTurns() end)
  if ok_t and turns and turns > 0 then data.strike_turns = turns end
  data.hint = "unpaid expenses come out of science (science_breakdown.budget_deficit); city_screen buildings with can_sell / sell_building raise gold. Units disband if GPT stays at the threshold named in this notice."
  -- Military Overview / toppanel unit-supply string: over the cap is extra gold + a production penalty.
  local ok_u, supply = pcall(H.unit_supply, data.player)
  if ok_u and type(supply) == "table" and supply.deficit then
    data.unit_supply = supply
    data.hint = data.hint .. " Over the unit supply cap (overview.unit_supply): extra maintenance and a production penalty; disband or wait for more cities/pop."
  end
end

-- Banner tooltip for a "city converted / adopted a religion" notice: majority name when there is
-- one, else note the tie, plus followers/pressure for every religion the banner lists.
function H.attach_conversion_banner(data, p)
  if not (data and type(data.text) == "string" and p) then return end
  local text = data.text
  if not (text:find("converted to another religion", 1, true) or text:find("has adopted a religion", 1, true)) then
    return
  end
  for c in p:Cities() do
    local name = c:GetName()
    if name and name ~= "" and text:find(name, 1, true) then
      data.city_id = c:GetID()
      data.x, data.y = c:GetX(), c:GetY()
      local maj = c.GetReligiousMajority and c:GetReligiousMajority() or -1
      if maj and maj > 0 then
        if Game.GetReligionName then data.religion = H.L(Game.GetReligionName(maj)) end
        if GameInfo.Religions and GameInfo.Religions[maj] then data.majority = GameInfo.Religions[maj].Type end
      elseif maj == 0 then
        data.religion = "PANTHEON"
        data.majority = "RELIGION_PANTHEON"
      else
        data.religion = nil
        data.majority = nil
        data.note = "no religion holds a majority in this city now"
      end
      if c.GetNumFollowers and GameInfo.Religions then data.religions = H.city_religions(c) end
      return
    end
  end
end
function H.take_events(pid)
  local out = H.events_since(H.cursors[pid] or 0, pid)
  H.cursors[pid] = H.event_seq
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
  hook("ActivePlayerTurnStart", function()
    H.record("turn_start", { player = Game.GetActivePlayer() }); H.hp_compare(Game.GetActivePlayer())
    pcall(H.check_eliminations, Game.GetActivePlayer())
  end)
  hook("ActivePlayerTurnEnd", function() H.record("turn_end", { player = Game.GetActivePlayer() }); H.hp_snapshot(Game.GetActivePlayer()) end)
  hook("GameplaySetActivePlayer", function(new, old) H.record("active_player", { new = new, old = old }) end)
  hook("SerialEventUnitDestroyed", function(playerID, unitID) H.record("unit_destroyed", { player = playerID, unit = unitID }) end)
  hook("SerialEventCityCreated", function(hex, playerID, cityID)
    -- `hex` is in hex space, not plot coordinates (live: Rio at plot (46,24) arrived as hex x=34).
    local x, y
    if hex then x, y = ToGridFromHex(hex.x, hex.y) end
    H.record("city_created", { player = playerID, city = cityID, x = x, y = y })
  end)
  hook("SerialEventUnitSetDamage", function(playerID, unitID, newDamage, oldDamage) H.unit_damaged(playerID, unitID, newDamage, oldDamage) end)
  hook("SerialEventCityDestroyed", function(hex, playerID, cityID) H.record("city_destroyed", { player = playerID, city = cityID }) end)
  hook("SerialEventCityCaptured", function(hex, playerID, cityID, newPlayerID) H.record("city_captured", { player = playerID, city = cityID, by = newPlayerID }) end)
  hook("WarStateChanged", function(team1, team2, atWar) H.record("war_state", { team1 = team1, team2 = team2, at_war = atWar }) end)
  hook("GameMessageChat", function(from, to, text, target) H.record("chat", { from = from, to = to, text = text, target = target }) end)
  hook("EndCombatSim", function(attPlayer, attUnit, attDmg, attFinal, attMax, defPlayer, defUnit, defDmg, defFinal, defMax)
    H.record("combat", { att_player = attPlayer, att_unit = attUnit, att_dmg = attDmg, att_hp = attFinal, def_player = defPlayer, def_unit = defUnit, def_dmg = defDmg, def_hp = defFinal,
                         attacker = H.combat_side(attPlayer, attUnit), defender = H.combat_side(defPlayer, defUnit) }) end)
  hook("NotificationAdded", function(id, type, toolTip, summary, data1, data2, playerID)
    H.record("notification", { id = id, ntype = type, text = toolTip, summary = summary, d1 = data1, d2 = data2, player = playerID }) end)
  hook("AILeaderMessage", function(playerID, diploState, message, animation, data1)
    -- harness_initiated: said while the harness itself had the leader/trade screen open (propose_deal,
    -- negotiate_deal); it is the reply to OUR visit, not the AI approaching us. turn_digest hides these.
    H.record("leader_message", { player = playerID, state = H.diplo_state_name(diploState), text = message,
                                 harness_initiated = H.harness_diplo or nil })
  end)
  hook("GameplayAlertMessage", function(text)
    if text == "Quicksaving..." then return end  -- our own quick_save, fired twice per save: digest noise
    local row = { text = text }
    -- "The enemy has been spotted near Nanjing!" names a city but no plot; a human looks at the map
    -- next to it. Attach the hostile units visible within 3 plots of any own city the text names.
    local ok, near = pcall(H.hostiles_near_named_city, text, Game.GetActivePlayer())
    if ok and near then row.city = near.city; row.hostiles = near.hostiles end
    H.record("alert", row)
  end)
  -- The digest row is recorded when the popup is QUEUED: the harness's own popup sweep can close a
  -- popup before it is ever "Shown" (live 2026-09-18: the barbarian-camp reward never reached the
  -- digest). The same popup can be queued repeatedly (hotseat, reopened screens): one row per turn.
  hook("SerialEventGameMessagePopup", function(info)
    local key = Game.GetGameTurn() .. ":" .. Game.GetActivePlayer() .. ":" .. tostring(info.Type) .. ":" .. tostring(info.Data1) .. ":" .. tostring(info.Data2)
    H.popup_rows = H.popup_rows or {}
    if H.popup_rows[key] then return end
    H.popup_rows[key] = true
    local row = { type = info.Type, name = H.enum_name("ButtonPopupTypes", ButtonPopupTypes, info.Type) }
    if info.Type == ButtonPopupTypes.BUTTONPOPUP_GOODY_HUT_REWARD then
      local g = GameInfo.GoodyHuts[info.Data1]   -- Data1 = GoodyHuts row id, Data2 = amount (gold, culture...) when any
      row.reward = g and g.Type or nil
      if (info.Data2 or 0) > 0 then row.amount = info.Data2 end
    elseif info.Type == ButtonPopupTypes.BUTTONPOPUP_BARBARIAN_CAMP_REWARD then
      row.gold = info.Data1   -- live 2026-09-18: Data1 = 16 with "...recovered 16 Gold!"
    elseif info.Type == ButtonPopupTypes.BUTTONPOPUP_NATURAL_WONDER_REWARD then
      row.x, row.y = info.Data1, info.Data2   -- live: [46, 17] = the wonder's plot
      local plot = Map.GetPlot(info.Data1, info.Data2)
      local f = plot and plot:GetFeatureType() or -1
      if f >= 0 then row.wonder = short(info_type(GameInfo.Features, f)) end
    elseif info.Type == ButtonPopupTypes.BUTTONPOPUP_CITY_STATE_GREETING then
      local cs = Players[info.Data1]              -- live: [31, 30] = minor player id, gold gift on meeting
      row.city_state = cs and cs:GetName() or nil
      if (info.Data2 or 0) > 0 then row.gold_gift = info.Data2 end
    end
    H.record("popup_shown", row)
  end)
  hook("SerialEventGameMessagePopupShown", function(info)
    H.popups[info.Type] = {type=info.Type, player=Game.GetActivePlayer(), data1=info.Data1, data2=info.Data2, data3=info.Data3,
                           data4=info.Data4, data5=info.Data5, option1=info.Option1, option2=info.Option2}
  end)
  hook("SerialEventGameMessagePopupProcessed", function(kind)
    H.popups[kind] = nil
  end)
  hook("SerialEventEnterCityScreen", function() end)
end

---------------------------------------------------------------- snapshots
-- Strategic resources as the top bar shows them to a human: only those the team has revealed, with the
-- spare count (negative = deficit: units/buildings consume more than we own; they fight/produce worse).
local function resource_revealed(res, team)
  -- Team:IsResourceRevealed does not exist in this build; the top bar's rule is "the team knows the
  -- resource's TechReveal tech" (resources without one are always shown).
  if not res.TechReveal then return true end
  local ok, revealed = pcall(function() return team:GetTeamTechs():HasTech(GameInfoTypes[res.TechReveal]) end)
  return ok and revealed
end

function H.strategic_resources(pid)
  local p = Players[pid]
  local team = Teams[p:GetTeam()]
  local out = {}
  if not (GameInfo and GameInfo.Resources) then return out end
  for res in GameInfo.Resources() do
    if res and res.ID and (res.ResourceClassType == "RESOURCECLASS_RUSH" or res.ResourceClassType == "RESOURCECLASS_MODERN")
       and not res.Type:find("ARTIFACTS") then  -- RESOURCE_HIDDEN_ARTIFACTS is an archaeology marker, not a stockpile
      if resource_revealed(res, team) then
        local oka, avail = pcall(function() return p:GetNumResourceAvailable(res.ID, true) end)
        local okt, total = pcall(function() return p:GetNumResourceTotal(res.ID, true) end)
        out[short(res.Type)] = { available = oka and avail or nil, total = okt and total or nil }
      end
    end
  end
  return out
end

-- Top-bar luxury list: owned / imported / exported copies. last_copy is the "selling this costs a
-- happiness luxury" warning the trade screen also shows.
function H.luxuries(pid)
  local p = Players[pid]
  local team = Teams[p:GetTeam()]
  local out = {}
  if not (GameInfo and GameInfo.Resources) then return out end
  for res in GameInfo.Resources() do
    if res and res.ID and res.ResourceClassType == "RESOURCECLASS_LUXURY" and resource_revealed(res, team) then
      local oka, avail = pcall(function() return p:GetNumResourceAvailable(res.ID, true) end)
      local okt, total = pcall(function() return p:GetNumResourceTotal(res.ID, true) end)
      local oki, imported = pcall(function() return p:GetResourceImport(res.ID) end)
      local oke, exported = pcall(function() return p:GetResourceExport(res.ID) end)
      avail, total = oka and avail or 0, okt and total or 0
      imported, exported = oki and imported or 0, oke and exported or 0
      if avail ~= 0 or total ~= 0 or imported ~= 0 or exported ~= 0 then
        local e = { available = avail, total = total }
        if imported ~= 0 then e.imported = imported end
        if exported ~= 0 then e.exported = exported end
        if avail == 1 then e.last_copy = true end
        out[short(res.Type)] = e
      end
    end
  end
  return out
end

-- Happiness tooltip (toppanel.lua HappinessTipHandler). Values of 0 are omitted.
function H.happiness_breakdown(pid)
  local p = Players[pid]
  local function n(fn, scale)
    local ok, v = pcall(fn)
    if not (ok and v) or v == 0 then return nil end
    return scale and (v / scale) or v
  end
  local resources = n(function() return p:GetHappinessFromResources() end)
  local variety = n(function() return p:GetHappinessFromResourceVariety() end)
  local buildings = n(function() return p:GetHappinessFromBuildings() end)
  local policies = n(function() return p:GetHappinessFromPolicies() end)
  local cities = n(function() return p:GetHappinessFromCities() end)
  local garrison = n(function() return p:GetHappinessFromGarrisonedUnits() end)
  local connected = n(function() return p:GetHappinessFromTradeRoutes() end)
  local religion = n(function() return p:GetHappinessFromReligion() end)
  local wonders = n(function() return p:GetHappinessFromNaturalWonders() end)
  local minors = n(function() return p:GetHappinessFromMinorCivs() end)
  local extra_city = n(function() return p:GetExtraHappinessPerCity() * p:GetNumCities() end)
  local total_h = n(function() return p:GetHappiness() end)
  local unh_cities = n(function() return p:GetUnhappinessFromCityCount() end, 100)
  local unh_captured = n(function() return p:GetUnhappinessFromCapturedCityCount() end, 100)
  local unh_puppet = n(function() return p:GetUnhappinessFromPuppetCityPopulation() end, 100)
  local unh_spec = n(function() return p:GetUnhappinessFromCitySpecialists() end, 100)
  local unh_pop_raw = n(function() return p:GetUnhappinessFromCityPopulation() end, 100)
  local unh_occupied = n(function() return p:GetUnhappinessFromOccupiedCities() end, 100)
  local unh_units = n(function() return p:GetUnhappinessFromUnits() end, 100)
  local unh_opinion = n(function() return p:GetUnhappinessFromPublicOpinion() end)
  local unh_total = n(function() return p:GetUnhappiness() end)
  local pop = unh_pop_raw
  if pop and unh_spec then pop = pop - unh_spec end
  if pop and unh_puppet then pop = pop - unh_puppet end
  if pop == 0 then pop = nil end
  return {
    total = p:GetExcessHappiness(),
    happiness = { total = total_h, luxuries = resources, luxury_variety = variety, buildings = buildings,
                  policies = policies, cities = cities, garrisons = garrison, connected_cities = connected,
                  religion = religion, natural_wonders = wonders, city_states = minors, extra_per_city = extra_city },
    unhappiness = { total = unh_total, number_of_cities = unh_cities, captured_cities = unh_captured,
                    population = pop, puppet_population = unh_puppet, specialists = unh_spec,
                    occupied = unh_occupied, units = unh_units, public_opinion = unh_opinion },
  }
end

-- socialpolicypopup.lua / cultureoverview.lua: Content vs Dissidents vs ... plus preferred ideology.
function H.public_opinion(pid)
  local p = Players[pid]
  if not p then return nil end
  local out = {}
  pcall(function()
    local t = p:GetPublicOpinionType()
    if t == nil then return end
    out.type = H.enum_name("PublicOpinionTypes", PublicOpinionTypes, t)
    if type(out.type) ~= "string" then out.type = t end
  end)
  pcall(function()
    local u = p:GetPublicOpinionUnhappiness()
    if type(u) == "number" and u ~= 0 then out.unhappiness = u end
  end)
  pcall(function()
    local pref = p:GetPublicOpinionPreferredIdeology()
    if pref and pref >= 0 and GameInfo.PolicyBranchTypes and GameInfo.PolicyBranchTypes[pref] then
      out.preferred_ideology = GameInfo.PolicyBranchTypes[pref].Type
    end
  end)
  pcall(function()
    local tip = p:GetPublicOpinionTooltip()
    if type(tip) == "string" and tip ~= "" then
      out.tooltip = (tip:sub(1, 8) == "TXT_KEY_") and H.L(tip) or tip
    end
  end)
  if not next(out) then return nil end
  return out
end

-- Gold tooltip (toppanel.lua GoldTipHandler). Cities vs international trade routes are split
-- the same way the panel does (GetGoldFromCitiesTimes100 minus GetGoldFromCitiesMinusTradeRoutesTimes100).
function H.gold_breakdown(pid)
  local p = Players[pid]
  local function n(fn, scale)
    local ok, v = pcall(fn)
    if not (ok and v) or v == 0 then return nil end
    return scale and (v / scale) or v
  end
  local gold = p:GetGold()
  local gpt = p:CalculateGoldRate()
  local diplo = n(function() return p:GetGoldPerTurnFromDiplomacy() end) or 0
  local from_deals, to_deals = diplo > 0 and diplo or nil, diplo < 0 and -diplo or nil
  local ok_all, cities_all = pcall(function() return p:GetGoldFromCitiesTimes100() / 100 end)
  local ok_minus, cities_minus = pcall(function() return p:GetGoldFromCitiesMinusTradeRoutesTimes100() / 100 end)
  local cities, trade_routes
  if ok_minus then
    if cities_minus and cities_minus ~= 0 then cities = cities_minus end
  elseif ok_all and cities_all and cities_all ~= 0 then
    cities = cities_all
  end
  if ok_all and ok_minus then
    local tr = (cities_all or 0) - (cities_minus or 0)
    if tr ~= 0 then trade_routes = tr end
  end
  local out = {
    gold = gold,
    gold_per_turn = gpt,
    income = {
      cities = cities,
      trade_routes = trade_routes,
      city_connections = n(function() return p:GetCityConnectionGoldTimes100() end, 100),
      deals = from_deals,
      traits = n(function() return p:GetGoldPerTurnFromTraits() end),
      religion = n(function() return p:GetGoldPerTurnFromReligion() end),
    },
    expenses = {
      unit_maintenance = n(function() return p:CalculateUnitCost() end),
      unit_supply = n(function() return p:CalculateUnitSupply() end),
      building_maintenance = n(function() return p:GetBuildingGoldMaintenance() end),
      improvement_maintenance = n(function() return p:GetImprovementGoldMaintenance() end),
      deals = to_deals,
    },
  }
  -- economicgeneralinfo.lua unit-expense tooltip: paid vs maintenance-free units and gold per paid unit.
  pcall(function()
    local total = p:GetNumUnits()
    local free = 0
    local ok_f, v = pcall(function()
      if DomainTypes and DomainTypes.NO_DOMAIN ~= nil then
        return p:GetNumMaintenanceFreeUnits(DomainTypes.NO_DOMAIN, false)
      end
      return p:GetNumMaintenanceFreeUnits()
    end)
    if ok_f and v then free = v end
    local paid = total - free
    if paid < 0 then paid = 0 end
    out.expenses.unit_paid = paid
    if free > 0 then out.expenses.unit_free = free end
    local maint = out.expenses.unit_maintenance
    if maint and paid > 0 then
      out.expenses.unit_cost_per = math.floor(maint / paid * 100 + 0.5) / 100
    end
  end)
  -- toppanel.lua GoldTipHandler / live t182 Losing Gold notice: empty treasury + negative GPT
  -- takes unpaid expenses out of science; units later go on strike (IsStrike was still false at −23).
  if gold + gpt < 0 then
    out.losing_science_from_deficit = true
    out.note = "unpaid expenses come out of science (science_breakdown.budget_deficit); city_screen buildings with can_sell / sell_building raise gold"
  end
  local ok_s, strike = pcall(function() return p:IsStrike() end)
  if ok_s and strike then out.is_strike = true end
  local ok_t, turns = pcall(function() return p:GetStrikeTurns() end)
  if ok_t and turns and turns > 0 then out.strike_turns = turns end
  return out
end

-- Science tooltip (toppanel.lua ScienceTipHandler). The boolean on GetScienceFromCitiesTimes100
-- is "exclude trade routes": true = cities only, false = cities + ITR.
function H.science_breakdown(pid)
  local p = Players[pid]
  local function n(fn, scale)
    local ok, v = pcall(fn)
    if not (ok and v) or v == 0 then return nil end
    return scale and (v / scale) or v
  end
  local ok_c, cities_raw = pcall(function() return p:GetScienceFromCitiesTimes100(true) / 100 end)
  local ok_p, plus_raw = pcall(function() return p:GetScienceFromCitiesTimes100(false) / 100 end)
  local cities = (ok_c and cities_raw ~= 0) and cities_raw or nil
  local trade
  if ok_c and ok_p then
    local tr = (plus_raw or 0) - (cities_raw or 0)
    if tr ~= 0 then trade = tr end
  end
  local anarchy
  local ok_a, is_a = pcall(function() return p:IsAnarchy() end)
  if ok_a and is_a then anarchy = n(function() return p:GetAnarchyNumTurns() end) end
  return {
    total = p:GetScience(),
    anarchy_turns = anarchy,
    budget_deficit = n(function() return p:GetScienceFromBudgetDeficitTimes100() end, 100),
    cities = cities,
    trade_routes = trade,
    city_states = n(function() return p:GetScienceFromOtherPlayersTimes100() end, 100),
    happiness = n(function() return p:GetScienceFromHappinessTimes100() end, 100),
    research_agreements = n(function() return p:GetScienceFromResearchAgreementsTimes100() end, 100),
    tech_city_cost_mod = n(function() return Game.GetNumCitiesTechCostMod() end),
  }
end

-- Culture tooltip (toppanel.lua CultureTipHandler). Golden-age remainder is total minus the
-- named sources, same as the stock panel.
function H.culture_breakdown(pid)
  local p = Players[pid]
  local function n(fn)
    local ok, v = pcall(fn)
    if not (ok and v) or v == 0 then return nil end
    return v
  end
  local function z(v) return (v and v ~= 0) and v or nil end
  local total = p:GetTotalJONSCulturePerTurn()
  local acc = p:GetJONSCulture()
  local next_cost = p:GetNextPolicyCost()
  local needed = (next_cost or 0) - (acc or 0)
  local turns
  if needed <= 0 then turns = 0
  elseif not total or total == 0 then turns = nil
  else turns = math.ceil(needed / total) end
  local free = n(function() return p:GetJONSCulturePerTurnForFree() end) or 0
  local cities = n(function() return p:GetJONSCulturePerTurnFromCities() end) or 0
  local happiness = n(function() return p:GetJONSCulturePerTurnFromExcessHappiness() end) or 0
  local traits = n(function() return p:GetJONSCulturePerTurnFromTraits() end) or 0
  local minors = n(function() return p:GetCulturePerTurnFromMinorCivs() end) or 0
  local religion = n(function() return p:GetCulturePerTurnFromReligion() end) or 0
  local bonus = n(function() return p:GetCulturePerTurnFromBonusTurns() end) or 0
  local ga = (total or 0) - free - cities - happiness - minors - religion - traits - bonus
  local anarchy
  local ok_a, is_a = pcall(function() return p:IsAnarchy() end)
  if ok_a and is_a then anarchy = n(function() return p:GetAnarchyNumTurns() end) end
  return {
    total = total, accumulated = acc, next_policy_cost = next_cost, turns = turns,
    anarchy_turns = anarchy, free = z(free), cities = z(cities), happiness = z(happiness),
    traits = z(traits), city_states = z(minors), religion = z(religion), bonus_turns = z(bonus),
    bonus_turns_remaining = bonus ~= 0 and n(function() return p:GetCultureBonusTurns() end) or nil,
    golden_age = z(ga),
    policy_city_cost_mod = n(function() return Game.GetNumCitiesPolicyCostMod() end),
  }
end

-- Tourism tooltip (toppanel.lua TourismTipHandler): great-work fill plus culture-victory progress
-- when that victory type is on.
function H.tourism_breakdown(pid)
  local p = Players[pid]
  local function n(fn)
    local ok, v = pcall(fn)
    if not ok then return nil end
    return v
  end
  local works = n(function() return p:GetNumGreatWorks() end) or 0
  local slots = n(function() return p:GetNumGreatWorkSlots() end)
  local out = {
    tourism = n(function() return p:GetTourism() end) or 0,
    great_works = works,
    empty_slots = slots and (slots - works) or nil,
  }
  local ok_v, cult = pcall(function()
    local v = GameInfo.Victories["VICTORY_CULTURAL"]
    return v and PreGame.IsVictory(v.ID)
  end)
  if ok_v and cult then
    out.influential_on = n(function() return p:GetNumCivsInfluentialOn() end)
    out.needed = n(function() return p:GetNumCivsToBeInfluentialOn() end)
  end
  return out
end

-- Faith tooltip (toppanel.lua FaithTipHandler). Next-prophet threshold is also on religion_overview.
function H.faith_breakdown(pid)
  local p = Players[pid]
  local function n(fn)
    local ok, v = pcall(fn)
    if not (ok and v) or v == 0 then return nil end
    return v
  end
  local anarchy
  local ok_a, is_a = pcall(function() return p:IsAnarchy() end)
  if ok_a and is_a then anarchy = n(function() return p:GetAnarchyNumTurns() end) end
  return {
    total = p:GetTotalFaithPerTurn(),
    accumulated = p:GetFaith(),
    anarchy_turns = anarchy,
    cities = n(function() return p:GetFaithPerTurnFromCities() end),
    city_states = n(function() return p:GetFaithPerTurnFromMinorCivs() end),
    religion = n(function() return p:GetFaithPerTurnFromReligion() end),
    next_great_person = n(function() return p:GetMinimumFaithNextGreatProphet() end),
  }
end

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
    golden_age_progress = (p.GetGoldenAgeProgressMeter and p:GetGoldenAgeProgressMeter()) or nil,
    golden_age_threshold = (p.GetGoldenAgeProgressThreshold and p:GetGoldenAgeProgressThreshold()) or nil,
    num_cities = p:GetNumCities(), num_units = p:GetNumUnits(), military_might = p:GetMilitaryMight(),
    trade_routes_used = p.GetNumInternationalTradeRoutesUsed and p:GetNumInternationalTradeRoutesUsed() or nil,
    trade_routes_available = p.GetNumInternationalTradeRoutesAvailable and p:GetNumInternationalTradeRoutesAvailable() or nil,
    idle_trade_units = H.idle_trade_units(p),
    turn = Game.GetGameTurn(), year = Game.GetGameTurnYear(),
    strategic_resources = H.strategic_resources(pid),
    luxuries = H.luxuries(pid),
    happiness_breakdown = H.happiness_breakdown(pid),
    gold_breakdown = H.gold_breakdown(pid),
    science_breakdown = H.science_breakdown(pid),
    culture_breakdown = H.culture_breakdown(pid),
    tourism_breakdown = H.tourism_breakdown(pid),
    faith_breakdown = H.faith_breakdown(pid),
    -- Military Overview header + toppanel unit-supply string (shown when over the cap).
    unit_supply = H.unit_supply(pid),
    -- Diplo list / Victory Progress score tooltip (diplolist.lua).
    score_breakdown = H.score_breakdown(pid),
    public_opinion = H.public_opinion(pid),
  }
end

function H.score_breakdown(pid)
  local p = Players[pid]
  if not p then return nil end
  local function n(fn)
    local ok, v = pcall(fn)
    if ok and type(v) == "number" and v ~= 0 then return v end
  end
  local out = {
    total = p:GetScore(),
    cities = n(function() return p:GetScoreFromCities() end),
    population = n(function() return p:GetScoreFromPopulation() end),
    land = n(function() return p:GetScoreFromLand() end),
    wonders = n(function() return p:GetScoreFromWonders() end),
    great_works = n(function() return p:GetScoreFromGreatWorks() end),
  }
  if not (Game.IsOption and GameOptionTypes and Game.IsOption(GameOptionTypes.GAMEOPTION_NO_SCIENCE)) then
    out.techs = n(function() return p:GetScoreFromTechs() end)
    out.future_tech = n(function() return p:GetScoreFromFutureTech() end)
  end
  if not (Game.IsOption and GameOptionTypes and Game.IsOption(GameOptionTypes.GAMEOPTION_NO_POLICIES)) then
    out.policies = n(function() return p:GetScoreFromPolicies() end)
  end
  if not (Game.IsOption and GameOptionTypes and Game.IsOption(GameOptionTypes.GAMEOPTION_NO_RELIGION)) then
    out.religion = n(function() return p:GetScoreFromReligion() end)
  end
  return out
end

-- militaryoverview.lua UpdateScreen / toppanel.lua UnitSupplyString: how many units the empire
-- can support. Over the cap is extra gold (CalculateUnitSupply, already in gold_breakdown) and a
-- city-production penalty (GetUnitProductionMaintenanceMod). A human opens Military Overview for
-- the handicap/cities/population split; the top bar only appears once already over.
function H.unit_supply(pid)
  local p = Players[pid]
  if not p then return nil end
  local function n(fn)
    local ok, v = pcall(fn)
    if ok then return v end
  end
  local cap = n(function() return p:GetNumUnitsSupplied() end)
  local used = n(function() return p:GetNumUnits() end)
  if cap == nil and used == nil then return nil end
  local out = {
    cap = cap, used = used,
    from_handicap = n(function() return p:GetNumUnitsSuppliedByHandicap() end),
    from_cities = n(function() return p:GetNumUnitsSuppliedByCities() end),
    from_population = n(function() return p:GetNumUnitsSuppliedByPopulation() end),
  }
  local deficit = n(function() return p:GetNumUnitsOutOfSupply() end)
  if deficit and deficit > 0 then
    out.deficit = deficit
    local pen = n(function() return p:GetUnitProductionMaintenanceMod() end)
    if pen and pen ~= 0 then out.production_penalty = pen end
  elseif cap and used then
    out.remaining = cap - used
  end
  return out
end

-- trade_routes_used counts trade UNITS, not routes: a caravan sleeping in a city fills a slot while earning
-- nothing (live t324: "6 of 6 used", two caravans idle in Nanjing, four real routes). A unit on a route is
-- automated; one that is not is idle and can take a route (establish_trade_route).
function H.idle_trade_units(p)
  local out = {}
  for u in p:Units() do
    if u:IsTrade() and not u:IsAutomated() then
      out[#out + 1] = { unit_id = u:GetID(), type = short(GameInfo.Units[u:GetUnitType()].Type), x = u:GetX(), y = u:GetY() }
    end
  end
  return out
end

-- The promotion chooser as a human reads it: the name on the button and the effect text under it,
-- not just the enum. "PROMOTION_DOGFIGHTING_1" beside "PROMOTION_INTERCEPTION_1" is not a choice
-- anyone can make -- the panel says "+33% Combat Strength when intercepting" against "+33% chance
-- to intercept". Same shape as available_policies.adoptable and available_research help.
-- Found live t184 (Shoshone vs the Inca): a Fighter earned a promotion and the three options came
-- back as bare type strings.
function H.promotion_options(u)
  local out = {}
  if not (u and u.CanPromote and GameInfo and GameInfo.UnitPromotions) then return out end
  for promo in GameInfo.UnitPromotions() do
    if promo and promo.ID and u:CanPromote(promo.ID) then
      out[#out + 1] = {
        promotion = promo.Type,
        name = promo.Description and L(promo.Description) or nil,
        help = promo.Help and L(promo.Help) or nil,
      }
    end
  end
  return out
end

-- Promotions currently on a unit (the unit panel list). Compact short names.
function H.unit_promotions(u)
  local out = {}
  if not (u and u.IsHasPromotion and GameInfo and GameInfo.UnitPromotions) then return out end
  for promo in GameInfo.UnitPromotions() do
    if promo and promo.ID and u:IsHasPromotion(promo.ID) then
      out[#out + 1] = short(promo.Type)
    end
  end
  return out
end

function H.units(pid)
  local p = Players[pid]
  local out = {}
  for u in p:Units() do
    local plot = u:GetPlot()
    local mission = u.GetMissionType and u:GetMissionType() or -1
    local e = {
      id = u:GetID(), type = short(info_type(GameInfo.Units, u:GetUnitType())), name = u:GetName(),
      x = u:GetX(), y = u:GetY(), moves = u:MovesLeft() / GameDefines.MOVE_DENOMINATOR, max_moves = u:MaxMoves() / GameDefines.MOVE_DENOMINATOR,
      hp = u:GetCurrHitPoints(), max_hp = u:GetMaxHitPoints(), strength = u:GetBaseCombatStrength(),
      ranged = (u.GetRangedCombatStrength and u:GetRangedCombatStrength() or 0), range = (u.Range and u:Range() or 0),
      embarked = u:IsEmbarked(), fortified = u:GetFortifyTurns() > 0, automated = u:IsAutomated(), ready = u:IsReadyToMove(),
      garrisoned = (u.IsGarrisoned and u:IsGarrisoned()) or false,
      mission = mission, domain = short(info_type(GameInfo.Domains, u:GetDomainType())),
      level = u.GetLevel and u:GetLevel() or nil, xp = u.GetExperience and u:GetExperience() or nil,
      can_found = (u.CanFound and plot and u:CanFound(plot)) or false,
      in_city = plot and plot:IsCity() or false,
    }
    -- Unit panel worker-progress line: "Trading Post (6)" from GetBuildType + GetBuildTurnsLeft (+1).
    if mission and mission ~= -1 then
      local okm, mn = pcall(function() return H.enum_name("MissionTypes", MissionTypes, mission) end)
      if okm and type(mn) == "string" then e.mission_name = mn end
    end
    pcall(function()
      local bt = u.GetBuildType and u:GetBuildType() or -1
      if not bt or bt < 0 then return end
      local row = GameInfo.Builds and GameInfo.Builds[bt]
      if row and row.Type then e.build = row.Type end
      if plot then
        local okt, turns = pcall(function() return plot:GetBuildTurnsLeft(bt, pid, 0, 0) end)
        if okt and type(turns) == "number" and turns < 4000 then
          e.build_turns_left = turns + 1
        end
      end
    end)
    local promos = H.unit_promotions(u)
    if #promos > 0 then e.promotions = promos end
    if u.ExperienceNeeded and e.xp then
      local ok, need = pcall(function() return u:ExperienceNeeded() end)
      if ok and need then e.xp_needed = need end
    end
    if u.GetUpgradeUnitType then
      local ok, ut = pcall(function() return u:GetUpgradeUnitType() end)
      if ok and ut and ut >= 0 and GameInfo.Units[ut] then
        e.upgrade_to = GameInfo.Units[ut].Type
        local okp, price = pcall(function() return u:UpgradePrice(ut) end)
        if okp then e.upgrade_gold = price end
        local okc, can = pcall(function() return u:CanUpgradeRightNow() end)
        if okc then e.can_upgrade = can end
      end
    end
    out[#out + 1] = e
  end
  return out
end

-- GetProductionTurnsLeft is INT_MAX for an empty queue and for a process (Wealth / Research).
-- Only a process should carry the "never completes" note (live t179: Goshute's empty queue was
-- labelled as an ongoing process).
local function production_turns_and_note(c)
  local turns = c:GetProductionTurnsLeft()
  if type(turns) == "number" and turns >= 2147483647 then turns = nil end
  local note
  if c.IsProductionProcess and c:IsProductionProcess() then
    note = "ongoing process: converts production every turn, never completes"
  end
  return turns, note
end

function H.cities(pid)
  local p = Players[pid]
  local out = {}
  for c in p:Cities() do
    local prod = c:GetProductionNameKey()
    local turns, pnote = production_turns_and_note(c)
    out[#out + 1] = {
      id = c:GetID(), name = c:GetName(), x = c:GetX(), y = c:GetY(), pop = c:GetPopulation(), capital = c:IsCapital(),
      puppet = c:IsPuppet(), occupied = c:IsOccupied(), razing = c:IsRazing(), hp = c:GetMaxHitPoints() - c:GetDamage(), max_hp = c:GetMaxHitPoints(),
      strength = c:GetStrengthValue() / 100,
      production = prod ~= "" and L(prod) or "", needs_production = prod == "", production_turns = turns,
      production_note = pnote, queue_len = c:GetOrderQueueLength(),
      food = c:GetYieldRate(YieldTypes.YIELD_FOOD), production_yield = c:GetYieldRate(YieldTypes.YIELD_PRODUCTION),
      gold = c:GetYieldRate(YieldTypes.YIELD_GOLD), science = c:GetYieldRate(YieldTypes.YIELD_SCIENCE),
      culture = c:GetJONSCulturePerTurn(), faith = c:GetFaithPerTurn(),
      food_stored = c:GetFood(), local_happiness = c:GetLocalHappiness(),
      -- GetFoodTurnsLeft() returns a huge sentinel (thousands of turns) for a city with no surplus;
      -- report the state by name instead so a reader never mistakes "stagnant" for "grows in 5165 turns".
      food_surplus = c:FoodDifference(true),
      growth = (c:FoodDifference(true) > 0 and "growing") or (c:FoodDifference(true) < 0 and "starving") or "stagnant",
      growth_turns = (c:FoodDifference(true) > 0) and c:GetFoodTurnsLeft() or nil,
      garrisoned = c:GetGarrisonedUnit() ~= nil, coastal = c:IsCoastal(),
      -- the city banner's religion icon: majority religion by name, nil when none ("Your City
      -- Converted" notifications were otherwise unreadable, live t287)
      religion = (function()
        local maj = c.GetReligiousMajority and c:GetReligiousMajority() or -1
        if maj and maj > 0 and Game.GetReligionName then return H.L(Game.GetReligionName(maj)) end
        if maj == 0 then return "PANTHEON" end
        return nil
      end)(),
      -- City connection (road/harbor to the capital) pays gold per turn; a Worker's road job is
      -- invisible otherwise. The capital reports true for itself.
      connected_to_capital = c:IsCapital() or (p.IsCapitalConnectedToCity and p:IsCapitalConnectedToCity(c)) or false,
      -- economicgeneralinfo.lua expandable stacks: per-city building maintenance and connection gold.
      building_maintenance = (function()
        local ok, v = pcall(function() return c:GetTotalBaseBuildingMaintenance() end)
        if ok and v and v > 0 then return v end
      end)(),
      connection_gold = (function()
        -- economicgeneralinfo.lua only lists cities that are already connected; the getter
        -- still returns a number for an unconnected city (live t183 Goshute/Pohokwi/Tiwanaku).
        if c:IsCapital() then return nil end
        if not (p.IsCapitalConnectedToCity and p:IsCapitalConnectedToCity(c)) then return nil end
        local ok, v = pcall(function() return p:GetCityConnectionRouteGoldTimes100(c) / 100 end)
        if ok and v and v > 0 then return v end
      end)(),
      resistance_turns = (c.IsResistance and c:IsResistance() and c.GetResistanceTurns and c:GetResistanceTurns()) or nil,
      razing_turns = (c.IsRazing and c:IsRazing() and c.GetRazingTurns and c:GetRazingTurns()) or nil,
      blockaded = (function()
        local ok, v = pcall(function() return c:IsBlockaded() end)
        if ok and v then return true end
      end)(),
      wltkd_turns = (function()
        local ok, v = pcall(function() return c:GetWeLoveTheKingDayCounter() end)
        if ok and type(v) == "number" and v > 0 then return v end
      end)(),
    }
  end
  return out
end

local function plot_yields(plot)
  local y, names = {}, { "food", "production", "gold", "science", "culture", "faith" }
  for i = 0, 5 do
    local ok, n = pcall(function() return plot:CalculateYield(i, true) end)
    if ok and n and n > 0 then y[names[i + 1]] = n end
  end
  return next(y) and y or nil
end

local function city_focus_name(city)
  local ok, ft = pcall(function() return city:GetFocusType() end)
  if not ok or ft == nil or not CityAIFocusTypes then return "balanced" end
  if ft == CityAIFocusTypes.CITY_AI_FOCUS_TYPE_FOOD then return "food" end
  if ft == CityAIFocusTypes.CITY_AI_FOCUS_TYPE_PRODUCTION then return "production" end
  if ft == CityAIFocusTypes.CITY_AI_FOCUS_TYPE_GOLD then return "gold" end
  if ft == CityAIFocusTypes.CITY_AI_FOCUS_TYPE_SCIENCE then return "science" end
  if ft == CityAIFocusTypes.CITY_AI_FOCUS_TYPE_CULTURE then return "culture" end
  if ft == CityAIFocusTypes.CITY_AI_FOCUS_TYPE_GREAT_PEOPLE then return "great_people" end
  if ft == CityAIFocusTypes.CITY_AI_FOCUS_TYPE_FAITH then return "faith" end
  return "balanced"
end

local FOCUS_IDS = {
  balanced = "NO_CITY_AI_FOCUS_TYPE", food = "CITY_AI_FOCUS_TYPE_FOOD", production = "CITY_AI_FOCUS_TYPE_PRODUCTION",
  gold = "CITY_AI_FOCUS_TYPE_GOLD", science = "CITY_AI_FOCUS_TYPE_SCIENCE", culture = "CITY_AI_FOCUS_TYPE_CULTURE",
  great_people = "CITY_AI_FOCUS_TYPE_GREAT_PEOPLE", faith = "CITY_AI_FOCUS_TYPE_FAITH",
}

-- BNW gplist.lua: progress is per city and GP class; generals/admirals use national XP.
function H.specialist_meter(c, s, p)
  local cls = GameInfo.UnitClasses[s.GreatPeopleUnitClass]
  if not cls then return nil end
  local count = c:GetSpecialistCount(s.ID)
  local progress = c:GetSpecialistGreatPersonProgress(s.ID)
  local base = s.GreatPeopleRateChange * count
  for b in GameInfo.Buildings() do
    if b.SpecialistType == s.Type and c:IsHasBuilding(b.ID) then
      base = base + b.GreatPeopleRateChange
    end
  end
  local mod = p:GetGreatPeopleRateModifier() + c:GetGreatPeopleRateModifier()
  local suffix = { UNITCLASS_WRITER = "Writer", UNITCLASS_ARTIST = "Artist", UNITCLASS_MUSICIAN = "Musician",
                   UNITCLASS_SCIENTIST = "Scientist", UNITCLASS_MERCHANT = "Merchant", UNITCLASS_ENGINEER = "Engineer" }
  local kind = suffix[s.GreatPeopleUnitClass]
  if kind then mod = mod + p["GetGreat" .. kind .. "RateModifier"](p) end
  if p:GetGoldenAgeTurns() > 0 and (kind == "Writer" or kind == "Artist" or kind == "Musician") then
    mod = mod + p["GetGoldenAgeGreat" .. kind .. "RateModifier"](p)
  end
  return { specialist = s.Type, unit_class = cls.Type, count = count, gp_progress = progress,
           gp_threshold = c:GetSpecialistUpgradeThreshold(cls.ID), gp_per_turn = math.floor(base * (100 + mod) / 100) }
end

function H.great_person_progress(pid)
  local p, cities = Players[pid], {}
  for c in p:Cities() do
    local meters = {}
    for s in GameInfo.Specialists() do
      if s.GreatPeopleUnitClass then
        local m = H.specialist_meter(c, s, p)
        if m and (m.gp_progress > 0 or m.gp_per_turn > 0 or m.count > 0) then meters[#meters + 1] = m end
      end
    end
    if #meters > 0 then cities[#cities + 1] = { city_id = c:GetID(), name = c:GetName(), meters = meters } end
  end
  return { ok = true, cities = cities,
    general = { progress = p:GetCombatExperience(), threshold = p:GreatGeneralThreshold() },
    admiral = { progress = p:GetNavalCombatExperience(), threshold = p:GreatAdmiralThreshold() },
    prophet = { faith = p:GetFaith(), next_faith = p:GetMinimumFaithNextGreatProphet() } }
end

-- Religion banner tooltip: only majority and religions with followers are displayed.
-- Keep the engine's raw pressure alongside the scaled integer printed by the UI.
function H.city_religions(c)
  local rows = {}
  local majority = c:GetReligiousMajority()
  for rel in GameInfo.Religions() do
    local n = c:GetNumFollowers(rel.ID)
    if rel.ID >= 0 and (rel.ID == majority or n > 0) then
      local raw, routes = c:GetPressurePerTurn(rel.ID)
      rows[#rows + 1] = { religion = rel.Type, name = H.L(Game.GetReligionName(rel.ID)), followers = n,
        majority = rel.ID == majority, pressure_raw = raw,
        pressure_per_turn = math.floor(raw / GameDefines.RELIGION_MISSIONARY_PRESSURE_MULTIPLIER),
        trade_routes = routes or c:GetNumTradeRoutesAddingPressure(rel.ID), holy_city = c:IsHolyCityForReligion(rel.ID) }
    end
  end
  return rows
end

-- City screen for one of my cities (buildings, specialists, worked tiles, queue, focus, buy-plot).
-- cities() stays the banner; this is what opening the city shows.
function H.city_screen(city_id, pid)
  local p = Players[pid]
  local c = p:GetCityByID(city_id)
  if not c then return { ok = false, err = "no such city" } end
  local buildings, specialists, plots, queue = {}, {}, {}, {}
  if GameInfo and GameInfo.Buildings then
    for b in GameInfo.Buildings() do
      if b and b.ID then
        local n = c.GetNumRealBuilding and c:GetNumRealBuilding(b.ID) or 0
        local free = c.GetNumFreeBuilding and c:GetNumFreeBuilding(b.ID) or 0
        if n > 0 or free > 0 then
          local e = { building = b.Type, name = short(b.Type) }
          if n > 1 then e.count = n end
          if free > 0 then e.free = free end
          -- City-screen "click to sell": puppets are run by the AI (BNW cityview.lua).
          if not c:IsPuppet() then
            local ok_s, sell = pcall(function() return c:IsBuildingSellable(b.ID) end)
            if ok_s and sell then
              e.can_sell = true
              local ok_r, refund = pcall(function() return c:GetSellBuildingRefund(b.ID) end)
              if ok_r then e.sell_gold = refund end
              if b.GoldMaintenance and b.GoldMaintenance > 0 then e.gold_maintenance = b.GoldMaintenance end
            end
          end
          if b.SpecialistType and c.GetNumSpecialistsInBuilding then
            local assigned = c:GetNumSpecialistsInBuilding(b.ID)
            local slots = c.GetNumSpecialistsAllowedByBuilding and c:GetNumSpecialistsAllowedByBuilding(b.ID) or 0
            if slots > 0 or assigned > 0 then
              e.specialist = b.SpecialistType
              e.specialist_assigned = assigned
              e.specialist_slots = slots
            end
          end
          buildings[#buildings + 1] = e
        end
      end
    end
  end
  if GameInfo and GameInfo.Specialists then
    for s in GameInfo.Specialists() do
      if s and s.ID and s.Type ~= "SPECIALIST_CITIZEN" then
        local m = H.specialist_meter(c, s, p)
        if m and (m.count > 0 or m.gp_progress > 0 or m.gp_per_turn > 0) then
          specialists[#specialists + 1] = m
        end
      end
    end
  end
  pcall(function()
    for i = 0, c:GetOrderQueueLength() - 1 do
      local orderType, data = c:GetOrderFromQueue(i)
      local row = (orderType == OrderTypes.ORDER_TRAIN and GameInfo.Units[data])
               or (orderType == OrderTypes.ORDER_CONSTRUCT and GameInfo.Buildings[data])
               or (orderType == OrderTypes.ORDER_CREATE and GameInfo.Projects[data])
               or (orderType == OrderTypes.ORDER_MAINTAIN and GameInfo.Processes[data])
      queue[#queue + 1] = row and row.Type or tostring(data)
    end
  end)
  local nplots = c.GetNumCityPlots and c:GetNumCityPlots() or 0
  for i = 0, nplots - 1 do
    local plot = c.GetCityIndexPlot and c:GetCityIndexPlot(i)
    if plot then
      local e = { x = plot:GetX(), y = plot:GetY(), i = i }
      if i == 0 then e.city_tile = true end
      local okw, worked = pcall(function() return c:IsWorkingPlot(plot) end)
      if okw and worked then e.worked = true end
      local okf, forced = pcall(function() return c:IsForcedWorkingPlot(plot) end)
      if okf and forced then e.forced = true end
      local okc, can = pcall(function() return c:CanWork(plot) end)
      if okc and can then e.can_work = true end
      local okb, buy = pcall(function() return c:CanBuyPlotAt(plot:GetX(), plot:GetY(), false) end)
      if okb and buy then
        e.buyable = true
        local okp, cost = pcall(function() return c:GetBuyPlotCost(plot:GetX(), plot:GetY()) end)
        if okp then e.buy_gold = cost end
      end
      if plot:IsVisible(p:GetTeam(), false) then e.yields = plot_yields(plot) end
      plots[#plots + 1] = e
    end
  end
  local demanded
  pcall(function()
    local r = c:GetResourceDemanded()
    if r and r >= 0 then demanded = short(info_type(GameInfo.Resources, r)) end
  end)
  local turns, pnote = production_turns_and_note(c)
  return {
    ok = true, id = c:GetID(), name = c:GetName(), x = c:GetX(), y = c:GetY(), pop = c:GetPopulation(),
    capital = c:IsCapital(), puppet = c:IsPuppet(), occupied = c:IsOccupied(), razing = c:IsRazing(),
    focus = city_focus_name(c),
    avoid_growth = (c.IsForcedAvoidGrowth and c:IsForcedAvoidGrowth()) or false,
    auto_specialists = not (c.IsNoAutoAssignSpecialists and c:IsNoAutoAssignSpecialists()),
    buildings = buildings, specialists = specialists, plots = plots, queue = queue,
    production = H.L(c:GetProductionNameKey()),
    production_turns = turns, production_note = pnote,
    food_surplus = c:FoodDifference(true),
    growth = (c:FoodDifference(true) > 0 and "growing") or (c:FoodDifference(true) < 0 and "starving") or "stagnant",
    growth_turns = (c:FoodDifference(true) > 0) and c:GetFoodTurnsLeft() or nil,
    resistance_turns = (c.IsResistance and c:IsResistance() and c.GetResistanceTurns and c:GetResistanceTurns()) or nil,
    razing_turns = (c.IsRazing and c:IsRazing() and c.GetRazingTurns and c:GetRazingTurns()) or nil,
    resource_demanded = demanded,
    blockaded = (function()
      local ok, v = pcall(function() return c:IsBlockaded() end)
      if ok and v then return true end
    end)(),
    wltkd_turns = (function()
      local ok, v = pcall(function() return c:GetWeLoveTheKingDayCounter() end)
      if ok and type(v) == "number" and v > 0 then return v end
    end)(),
    can_annex = c:IsPuppet() and not (p.MayNotAnnex and p:MayNotAnnex()),
    can_raze = (not c:IsCapital()) and p.CanRaze and p:CanRaze(c) or false,
    can_unraze = c:IsRazing() or false,
  }
end

local function own_city(city_id, pid)
  if Game.GetActivePlayer() ~= pid then
    return nil, { ok = false, err = "this seat is not active" }
  end
  local c = Players[pid]:GetCityByID(city_id)
  if not c then return nil, { ok = false, err = "no such city" } end
  return c, nil
end

function H.set_auto_specialists(city_id, automatic, pid)
  local c, err = own_city(city_id, pid)
  if not c then return err end
  if c:IsPuppet() then return { ok = false, err = "puppet cities are run by the AI; annex first" } end
  Network.SendDoTask(c:GetID(), TaskTypes.TASK_NO_AUTO_ASSIGN_SPECIALISTS, -1, -1, not automatic, false, false, false)
  return { ok = true, city_id = c:GetID(), requested = automatic }
end

function H.change_specialist(city_id, building, add, pid)
  local c, err = own_city(city_id, pid)
  if not c then return err end
  if c:IsPuppet() then return { ok = false, err = "puppet cities are run by the AI; annex first" } end
  local b = GameInfo.Buildings[building]
  if not b or not b.SpecialistType or not c:IsHasBuilding(b.ID) then
    return { ok = false, err = "city has no specialist slots in that building" }
  end
  local before = c:GetNumSpecialistsInBuilding(b.ID)
  if add and not c:IsCanAddSpecialistToBuilding(b.ID) then return { ok = false, err = "cannot add a specialist to that building" } end
  if not add and before <= 0 then return { ok = false, err = "no specialist assigned to that building" } end
  if not c:IsNoAutoAssignSpecialists() then H.set_auto_specialists(city_id, false, pid) end
  Network.SendDoTask(c:GetID(), add and TaskTypes.TASK_ADD_SPECIALIST or TaskTypes.TASK_REMOVE_SPECIALIST,
    GameInfoTypes[b.SpecialistType], b.ID, false, false, false, false)
  return { ok = true, city_id = c:GetID(), building = b.Type, before = before, expected = before + (add and 1 or -1) }
end

function H.set_city_focus(city_id, focus, pid)
  local c, err = own_city(city_id, pid)
  if not c then return err end
  if c:IsPuppet() then return { ok = false, err = "puppet cities are run by the AI; annex first" } end
  local key = FOCUS_IDS[focus]
  if not key then
    local allowed = {}
    for k, _ in pairs(FOCUS_IDS) do allowed[#allowed + 1] = k end
    return { ok = false, err = "unknown focus " .. tostring(focus), allowed = allowed }
  end
  local id = CityAIFocusTypes and CityAIFocusTypes[key]
  if id == nil then return { ok = false, err = "CityAIFocusTypes missing " .. key } end
  Network.SendSetCityAIFocus(c:GetID(), id)
  return { ok = true, city_id = city_id, focus = city_focus_name(c), sent = focus }
end

function H.set_avoid_growth(city_id, avoid, pid)
  local c, err = own_city(city_id, pid)
  if not c then return err end
  if c:IsPuppet() then return { ok = false, err = "puppet cities are run by the AI; annex first" } end
  Network.SendSetCityAvoidGrowth(c:GetID(), avoid and true or false)
  return { ok = true, city_id = city_id, avoid_growth = (c.IsForcedAvoidGrowth and c:IsForcedAvoidGrowth()) or false, sent = avoid and true or false }
end

function H.change_working_plot(city_id, x, y, pid)
  local c, err = own_city(city_id, pid)
  if not c then return err end
  if c:IsPuppet() then return { ok = false, err = "puppet cities are run by the AI; annex first" } end
  local idx
  local nplots = c.GetNumCityPlots and c:GetNumCityPlots() or 0
  for i = 1, nplots - 1 do  -- 0 is the city tile; the UI ignores clicks on it
    local plot = c:GetCityIndexPlot(i)
    if plot and plot:GetX() == x and plot:GetY() == y then idx = i; break end
  end
  if not idx then return { ok = false, err = "plot is not in this city's workable radius", x = x, y = y } end
  Network.SendDoTask(c:GetID(), TaskTypes.TASK_CHANGE_WORKING_PLOT, idx, -1, false, false, false, false)
  local plot = c:GetCityIndexPlot(idx)
  local worked = c:IsWorkingPlot(plot)
  return { ok = true, city_id = city_id, x = x, y = y, worked = worked }
end

function H.buy_city_plot(city_id, x, y, pid)
  local c, err = own_city(city_id, pid)
  if not c then return err end
  local okb, buy = pcall(function() return c:CanBuyPlotAt(x, y, false) end)
  if not (okb and buy) then return { ok = false, err = "cannot buy that plot from this city right now", x = x, y = y } end
  local okp, cost = pcall(function() return c:GetBuyPlotCost(x, y) end)
  if okp and cost and Players[pid]:GetGold() < cost then
    return { ok = false, err = "not enough gold", cost = cost, gold = Players[pid]:GetGold() }
  end
  Network.SendCityBuyPlot(c:GetID(), x, y)
  return { ok = true, city_id = city_id, x = x, y = y, cost = cost, gold_after = Players[pid]:GetGold() }
end

function H.city_task(city_id, action, pid)
  local c, err = own_city(city_id, pid)
  if not c then return err end
  local p = Players[pid]
  if action == "annex" then
    if not c:IsPuppet() then return { ok = false, err = "city is not a puppet" } end
    if p.MayNotAnnex and p:MayNotAnnex() then return { ok = false, err = "this civ cannot annex (Venice)" } end
    Network.SendDoTask(c:GetID(), TaskTypes.TASK_ANNEX_PUPPET, -1, -1, false, false, false, false)
  elseif action == "raze" then
    if c:IsCapital() then return { ok = false, err = "cannot raze a capital" } end
    if not (p.CanRaze and p:CanRaze(c)) then return { ok = false, err = "cannot raze this city" } end
    Network.SendDoTask(c:GetID(), TaskTypes.TASK_RAZE, -1, -1, false, false, false, false)
  elseif action == "unraze" then
    if not c:IsRazing() then return { ok = false, err = "city is not razing" } end
    Network.SendDoTask(c:GetID(), TaskTypes.TASK_UNRAZE, -1, -1, false, false, false, false)
  else
    return { ok = false, err = "unknown action " .. tostring(action), allowed = { "annex", "raze", "unraze" } }
  end
  return { ok = true, city_id = city_id, action = action, puppet = c:IsPuppet(), razing = c:IsRazing() }
end

-- City-screen sell (Network.SendSellBuilding). One building per city per turn is the usual engine gate;
-- IsBuildingSellable goes false afterwards. Puppets refuse (stock UI never offers the click).
function H.sell_building(city_id, building_name, pid)
  local c, err = own_city(city_id, pid)
  if not c then return err end
  if c:IsPuppet() then return { ok = false, err = "puppet cities are run by the AI; annex first" } end
  local id = GameInfoTypes[building_name]
  if id == nil then return { ok = false, err = "unknown building " .. tostring(building_name) } end
  if not (c.IsBuildingSellable and c:IsBuildingSellable(id)) then
    return { ok = false, err = "cannot sell that building right now" }
  end
  local refund
  pcall(function() refund = c:GetSellBuildingRefund(id) end)
  local gold_before = Players[pid]:GetGold()
  Network.SendSellBuilding(c:GetID(), id)
  return { ok = true, sent = true, city_id = city_id, building = building_name, refund = refund, gold_before = gold_before }
end

-- One revealed plot. vis=true: currently in sight. vis=false: discovered but fogged —
-- terrain/resource only; never live units, owners, improvements, cities, or features.
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
  end
  if not vis then
    -- A fogged tile still shows a human what was there when last seen (ruins, camps, roads, borders):
    -- the engine keeps that per team as the "revealed" values, which can be stale -- that is the point.
    -- (live 2026-09-18: a "Ruins discovered" bubble whose GOODY_HUT the map read did not show.)
    -- Feature is omitted: there is no GetRevealedFeatureType, and GetFeatureType is live (a forest
    -- chopped in fog would leak).
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

function H.approach_name(v) return H.enum_name("MajorCivApproachTypes", MajorCivApproachTypes, v) end
-- Relationship between `pid` and major civ `other`, plus `other`'s public standing with everyone `pid` has
-- met. Everything here is what the in-game Diplomacy overview / leader tooltip already shows a human:
-- GetApproachTowardsUsGuess + GetOpinionTable are the visible guess, not the AI's hidden true approach.
function H.relationship(pid, other)
  local p, o = Players[pid], Players[other]
  if not (p and o and o:IsAlive()) then return { ok = false, err = "no such player" } end
  local myTeam, oTeam = Teams[p:GetTeam()], Teams[o:GetTeam()]
  if not myTeam:IsHasMet(o:GetTeam()) then return { ok = false, err = "not met" } end
  local function try(f, ...) local ok, v = pcall(f, ...); if ok then return v end return nil end
  local out = {
    ok = true, player = other, civ = o:GetCivilizationShortDescription(), leader = o:GetName(),
    minor = o:IsMinorCiv() or false, at_war = myTeam:IsAtWar(o:GetTeam()) or false,
    turns_locked_in_war = try(function() return myTeam:GetNumTurnsLockedIntoWar(o:GetTeam()) end),
  }
  if out.minor then
    out.friends = try(function() return o:IsFriends(pid) end)
    out.allied = try(function() return o:IsAllies(pid) end)
    out.influence = try(function() return o:GetMinorCivFriendshipWithMajor(pid) end)
    -- The ally is named only when we have met it (citystatestatushelper.lua: TXT_KEY_CITY_STATE_ALLY_UNKNOWN_TT).
    local ally = try(function() return o:GetAlly() end)
    if ally and ally >= 0 and ally ~= pid and not myTeam:IsHasMet(Players[ally]:GetTeam()) then
      out.ally_of, out.ally_unknown = nil, true
    else
      out.ally_of = ally
    end
    return out
  end
  out.approach_guess = H.approach_name(try(function() return p:GetApproachTowardsUsGuess(other) end))
  out.declaration_of_friendship = try(function() return p:IsDoF(other) end) or false
  out.they_denounced_us = try(function() return o:IsDenouncedPlayer(pid) end) or false
  out.we_denounced_them = try(function() return p:IsDenouncedPlayer(other) end) or false
  out.our_embassy_with_them = try(function() return oTeam:HasEmbassyAtTeam(p:GetTeam()) end)
  out.their_embassy_with_us = try(function() return myTeam:HasEmbassyAtTeam(o:GetTeam()) end)
  out.open_borders_we_have = try(function() return myTeam:IsAllowsOpenBordersToTeam(o:GetTeam()) end)
  out.open_borders_they_have = try(function() return oTeam:IsAllowsOpenBordersToTeam(p:GetTeam()) end)
  out.research_agreement = try(function() return myTeam:IsHasResearchAgreement(o:GetTeam()) end) or false
  out.defensive_pact = try(function() return myTeam:IsHasDefensivePact(o:GetTeam()) end) or false
  out.wars_fought = try(function() return p:GetNumWarsFought(other) end)
  out.opinion = {}
  local t = try(function() return o:GetOpinionTable(pid) end)
  if type(t) == "table" then for _, v in ipairs(t) do out.opinion[#out.opinion + 1] = tostring(v) end end
  -- Their public standing with every other civ we have met (visible in the Diplomacy overview).
  out.relations = {}
  local last = (GameDefines.MAX_CIV_PLAYERS or GameDefines.MAX_MAJOR_CIVS) - 1
  for third = 0, last do
    if third ~= other and third ~= pid then
      local q = Players[third]
      if q and q:IsAlive() and myTeam:IsHasMet(q:GetTeam()) and oTeam:IsHasMet(q:GetTeam()) then
        local e = { player = third, civ = q:GetCivilizationShortDescription(), at_war = oTeam:IsAtWar(q:GetTeam()) or false }
        if q:IsMinorCiv() then
          e.minor = true
          -- Global Relations (diploglobalrelationships.lua:281) shows a third party's city-state ALLIANCES
          -- only; friendship (30+ influence) is shown nowhere, so it is not read (audit t341).
          e.allied = try(function() return q:IsAllies(other) end)
          if e.at_war or e.allied then out.relations[#out.relations + 1] = e end
        else
          e.declaration_of_friendship = try(function() return o:IsDoF(third) end) or false
          e.they_denounced = try(function() return o:IsDenouncedPlayer(third) end) or false
          e.denounced_them = try(function() return q:IsDenouncedPlayer(other) end) or false
          out.relations[#out.relations + 1] = e
        end
      end
    end
  end
  -- Discuss-screen buttons a human would see (discussiondialog.lua). stop_spreading_religion
  -- is the ask-them-to-stop row, gated on conversion points from our cities (live t179: Ethiopian
  -- missionary on our lumbermill after Machu flipped).
  local spies = try(function() return o:GetEspionageSpies() end)
  out.discuss = {
    share_intrigue = try(function() return p:HasRecentIntrigueAbout(other) end) or false,
    stop_spreading_religion = ((try(function() return p:GetNegativeReligiousConversionPoints(other) end) or 0) > 0)
      and not (try(function() return o:IsAskedToStopConverting(pid) end) or false),
    stop_spying = (not (try(function() return o:IsStopSpyingMessageTooSoon(pid) end) or false))
      and type(spies) == "table" and #spies > 0,
    dont_settle = not (try(function() return o:IsDontSettleMessageTooSoon(pid) end) or false),
    stop_digging = ((try(function() return p:GetNegativeArchaeologyPoints(other) end) or 0) > 0)
      and not (try(function() return o:IsAskedToStopDigging(pid) end) or false),
    declare_friendship = not out.declaration_of_friendship
      and not (try(function() return o:IsDoFMessageTooSoon(pid) end) or false),
  }
  -- What they have said to us lately (the AILeaderMessage hook, newest last).
  out.history = {}
  for i = #H.events, 1, -1 do
    local e = H.events[i]
    if e.kind == "leader_message" and e.audience == pid and e.data.player == other then
      table.insert(out.history, 1, { turn = e.turn, state = e.data.state, text = e.data.text })
      if #out.history >= 12 then break end
    end
  end
  return out
end

-- The social policy screen as the player sees it: adopted policies, policies adoptable right now,
-- branches with unlocked / can-unlock flags, and whether a policy is affordable this turn.
function H.available_policies(pid)
  local p = Players[pid]
  local out = { adopted = {}, adoptable = {}, branches = {}, culture = p:GetJONSCulture(),
                next_policy_cost = p:GetNextPolicyCost(), free_policies = p:GetNumFreePolicies() }
  out.can_adopt_now = out.free_policies > 0 or out.culture >= out.next_policy_cost
  for b in GameInfo.PolicyBranchTypes() do
    local blocked = false
    if p.IsPolicyBranchBlocked then blocked = p:IsPolicyBranchBlocked(b.ID) end
    local finished = false
    if p.IsPolicyBranchFinished then finished = p:IsPolicyBranchFinished(b.ID) end
    out.branches[#out.branches + 1] = { branch = b.Type, unlocked = p:IsPolicyBranchUnlocked(b.ID),
      can_unlock = p:CanUnlockPolicyBranch(b.ID), blocked = blocked, finished = finished,
      era = b.EraPrereq, ideology = b.PurchaseByLevel or false }
  end
  for pol in GameInfo.Policies() do
    local branch = pol.PolicyBranchType
    if p:HasPolicy(pol.ID) then
      out.adopted[#out.adopted + 1] = { policy = pol.Type, branch = branch }
    elseif p:CanAdoptPolicy(pol.ID, true) then  -- true: ignore the culture cost, list what the tree offers next
      out.adoptable[#out.adoptable + 1] = { policy = pol.Type, branch = branch, name = L(pol.Description), help = L(pol.Help) }
    end
  end
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
  local last = (GameDefines.MAX_CIV_PLAYERS or GameDefines.MAX_MAJOR_CIVS) - 1
  for other = 0, last do
    if other ~= pid then
      local o = Players[other]
      if o and o:IsAlive() and o:IsEverAlive() and myTeam:IsHasMet(o:GetTeam()) then
        local minor = o.IsMinorCiv and o:IsMinorCiv() or false
        local e = {
          id = other, civ = o:GetCivilizationShortDescription(), leader = o:GetName(),
          human = o:IsHuman(), met = true, at_war = myTeam:IsAtWar(o:GetTeam()) or false,
        }
        if minor then
          e.minor = true
          local ok, allied = pcall(function() return o:IsAllies(pid) end)
          if ok then e.allied = allied end
          local ok2, friends = pcall(function() return o:IsFriends(pid) end)
          if ok2 then e.friends = friends end
          -- What befriending it buys (the city-state screen's own info): trait + influence.
          pcall(function()
            local tr = GameInfo.MinorCivTraits[o:GetMinorCivTrait()]
            if tr then e.trait = short(tr.Type) end  -- CULTURED / MARITIME / MERCANTILE / MILITARISTIC / RELIGIOUS
            e.influence = o:GetMinorCivFriendshipWithMajor(pid)
          end)
          -- The influence tooltip's own per-turn change (citystatestatushelper.lua:230). With it, say when
          -- the status lapses: live t352 the Monaco alliance (7 Oil, +13 culture, happiness) ran out at 59/60
          -- with nothing in any read warning it was one turn away.
          pcall(function()
            local chg = o:GetFriendshipChangePerTurnTimes100(pid) / 100
            e.influence_per_turn = chg
            if chg < 0 and e.influence then
              local lim = e.allied and (GameDefines.FRIENDSHIP_THRESHOLD_ALLIES or 60)
                          or (e.friends and (GameDefines.FRIENDSHIP_THRESHOLD_FRIENDS or 30)) or nil
              if lim then e.turns_until_status_lost = math.floor((e.influence - lim) / -chg) + 1 end
            end
          end)
        else
          e.score = o:GetScore()
        end
        -- Where it is, as the map shows it: the capital's plot once revealed (live t409: finding Quebec City
        -- for a missionary quest took a raw query).
        pcall(function()
          local cap = o:GetCapitalCity()
          if cap and cap:Plot():IsRevealed(p:GetTeam(), false) then e.capital = { name = cap:GetName(), x = cap:GetX(), y = cap:GetY() } end
        end)
        out[#out + 1] = e
      end
    end
  end
  return out
end

-- Reverse lookup for an enum table (DiploUIStateTypes, EndTurnBlockingTypes, GameStateTypes, ...), built
-- lazily and cached under `cache_key`. NOTE: `_G` does not exist in this Lua environment (Civ5's UI
-- contexts run under a custom sandboxed environment, not the standard Lua globals table -- confirmed live:
-- `type(_G) == "nil"` in InGame), so the enum TABLE must be passed directly by each caller below rather
-- than looked up by name string; an earlier version of this function tried `_G[name]` and silently
-- returned every value unresolved (the pcall failed, indexing a nil `_G`) -- caught live, not in review.
H._enum_names = H._enum_names or {}
function H.enum_name(cache_key, enum_table, v)
  local cache = H._enum_names[cache_key]
  if not cache then
    local ok, names = pcall(function()
      local t = {}
      for k, id in pairs(enum_table) do t[id] = k end
      return t
    end)
    cache = ok and names or {}
    H._enum_names[cache_key] = cache
  end
  return cache[v] or v
end

function H.diplo_state_name(v) return H.enum_name("DiploUIStateTypes", DiploUIStateTypes, v) end
function H.blocking_name(v) return H.enum_name("EndTurnBlockingTypes", EndTurnBlockingTypes, v) end
-- NOTE: Game.GetGameState() pairs with the global GameplayGameStateTypes (GAMESTATE_ON/_EXTENDED/_OVER),
-- NOT the differently-named global GameStateTypes (a separate, real enum -- the UI's screen/view state
-- machine: CIV5_GS_EXIT/MAIN_MENU/MAINGAMEVIEW/...). An earlier version of this file used the wrong one
-- (a grep for the enum name had no left boundary and silently matched the tail of the longer
-- "GameplayGameStateTypes" identifier), so game_state_name/game_over always compared against a nil field
-- and game_over was silently always false -- caught live, not in review.
function H.game_state_name(v) return H.enum_name("GameplayGameStateTypes", GameplayGameStateTypes, v) end

-- Fire a diplomatic event directly on the engine, bypassing the leader-head/discussion UI entirely.
-- `event_name` is the FromUIDiploEventTypes key with or without its FROM_UI_DIPLO_EVENT_ prefix.
-- See docs/NOTES.md for the full enum and which files call each one (from static analysis of the
-- game's own Lua).
--
-- War/peace gating (v12, tightened v13 -- see NOTES.md): leaderheadroot.lua's OnShowHide never even shows
-- the war/peace button unless `pActiveTeam:CanChangeWarPeace(otherTeam)`, and OnWarOrPeace itself branches
-- on `IsAtWar(otherTeam)` first -- at war fires NEGOTIATE_PEACE, at peace opens the declare-war popup --
-- so the two events are mutually exclusive by current war state, not just by their own separate gates.
-- The leaderhead screen this all lives on also cannot open at all without `IsHasMet(otherTeam)` first.
-- v12 mirrored `CanChangeWarPeace` plus each direction's own gate (`GetNumTurnsLockedIntoWar(otherTeam) > 0`
-- -- the "locked into war" cooldown after declaring/being declared on, confirmed live: ~10 turns -- for
-- peace; `IsForcePeace`/`CanDeclareWar` for war) but NOT `IsHasMet`/`IsAtWar`, so live-testing (v12, same
-- day) found `make_peace` against a player never met and never at war still returned a blind {ok=true}:
-- `CanChangeWarPeace` and a 0 locked-war-turn count are both trivially true when no war has ever happened,
-- same false-success shape this whole file has been hunting all day for `propose_deal`. v13 adds the
-- `IsHasMet` precondition and the `IsAtWar` branch explicitly so NEGOTIATE_PEACE/DECLARES_WAR can only ever
-- fire on the side of that branch the real UI would have offered. DENOUNCE has no equivalent precondition
-- in discussiondialog.lua (just a confirm click straight to DoFromUIDiploEvent) so it stays unguarded here.
function H.diplo_event(event_name, other_player, data1, data2)
  local key = event_name
  if not key:match("^FROM_UI_DIPLO_EVENT_") then key = "FROM_UI_DIPLO_EVENT_" .. key end
  local id = FromUIDiploEventTypes[key]
  if id == nil then return { ok = false, err = "unknown diplo event " .. tostring(event_name) } end

  if key == "FROM_UI_DIPLO_EVENT_HUMAN_NEGOTIATE_PEACE" or key == "FROM_UI_DIPLO_EVENT_HUMAN_DECLARES_WAR" then
    local myTeam = Teams[Game.GetActiveTeam()]
    local otherTeam = Players[other_player]:GetTeam()
    if not myTeam:IsHasMet(otherTeam) then
      return { ok = false, err = "have not met this player yet" }
    end
    if not myTeam:CanChangeWarPeace(otherTeam) then
      return { ok = false, err = "war/peace not negotiable with this player right now" }
    end
    local atWar = myTeam:IsAtWar(otherTeam)
    if key == "FROM_UI_DIPLO_EVENT_HUMAN_NEGOTIATE_PEACE" then
      if not atWar then
        return { ok = false, err = "not at war with this player" }
      end
      local lockedTurns = myTeam:GetNumTurnsLockedIntoWar(otherTeam)
      if lockedTurns > 0 then
        return { ok = false, err = "locked into war for " .. lockedTurns .. " more turns; peace cannot be negotiated yet" }
      end
    else
      if atWar then
        return { ok = false, err = "already at war with this player" }
      end
      if myTeam:IsForcePeace(otherTeam) then
        return { ok = false, err = "forced peace in effect; cannot declare war on this player right now" }
      end
      if not myTeam:CanDeclareWar(otherTeam) then
        return { ok = false, err = "cannot declare war on this player right now" }
      end
    end
  end

  Game.DoFromUIDiploEvent(id, other_player, data1 or 0, data2 or 0)
  return { ok = true, event = key }
end

-- City bombard: Network.SendDoTask is the selection-free city-task path (cityview.lua /
-- puppetcitypopup.lua). Do not UI.SelectCity -- that is the old worldview.lua CityBombard()
-- flow and is not needed once the city id is in the net message.
function H.available_city_strikes(city_id, pid)
  local city = Players[pid]:GetCityByID(city_id)
  if not city then return { ok = false, err = "no such city" } end
  -- CanRangeStrike is "this city has bombard" (true on a turn-7 capital with no
  -- garrison). CanRangeStrikeNow is "can fire this turn". Live: Now() was false
  -- while Strike() was true; do not use `and/or` here — false Now() is falsy
  -- and would fall through to CanRangeStrike() and report can=true.
  local can_now
  if city.CanRangeStrikeNow then
    can_now = city:CanRangeStrikeNow()
  else
    can_now = city:CanRangeStrike()
  end
  if not can_now then return { ok = true, can = false, targets = {} } end
  local cx, cy = city:GetX(), city:GetY()
  local r = (GameDefines and GameDefines.MAX_CITY_ATTACK_RANGE) or 2
  local team = Players[pid]:GetTeam()
  local targets = {}
  for dx = -r, r do
    for dy = -r, r do
      local plot = Map.PlotXYWithRangeCheck(cx, cy, dx, dy, r)
      if plot then
        local x, y = plot:GetX(), plot:GetY()
        local ok, legal = pcall(function() return city:CanRangeStrikeAt(x, y, true, true) end)
        if ok and legal then
          local t = { x = x, y = y }
          if plot.IsVisible and plot:IsVisible(team, false) then
            local n = plot.GetNumUnits and plot:GetNumUnits() or 0
            if n > 0 and plot.GetUnit then
              local u = plot:GetUnit(0)
              if u then
                t.unit = { owner = u:GetOwner(), id = u:GetID(), hp = u:GetCurrHitPoints(),
                           type = short(info_type(GameInfo.Units, u:GetUnitType())) }
                -- enemyunitpanel.lua UpdateCombatOddsCityVsUnit. The panel caps the estimate at the
                -- unit's MAXIMUM hit points, not the hp it has left, and prints both strengths.
                pcall(function()
                  t.preview = { expected_damage_dealt = math.min(GameDefines.MAX_HIT_POINTS,
                                                                 city:RangeCombatDamage(u, nil)),
                                expected_damage_taken = 0 }
                  pcall(function()
                    t.preview.my_strength = city:GetStrengthValue() / 100
                    t.preview.their_strength = city:RangeCombatUnitDefense(u) / 100
                  end)
                  t.preview.modifiers = H.city_strike_modifiers(city, u)
                end)
              end
            end
            if plot.IsCity and plot:IsCity() then
              local c = plot:GetPlotCity()
              if c then t.city = { name = c:GetName(), owner = c:GetOwner() } end
            end
          end
          targets[#targets + 1] = t
        end
      end
    end
  end
  return { ok = true, can = true, targets = targets }
end

-- Who is on a plot right now, as the given team sees it (nil when not visible): the top enemy/any
-- units with hp, and the city if any. Used for before/after reads around attacks.
function H.plot_units(x, y, team)
  local plot = Map.GetPlot(x, y)
  if not plot then return { ok = false, err = "no such plot" } end
  if not plot:IsVisible(team, false) then return { ok = true, visible = false, units = {} } end
  local units = {}
  for i = 0, plot:GetNumUnits() - 1 do
    local u = plot:GetUnit(i)
    if u and not u:IsInvisible(team, false) then
      units[#units + 1] = { id = u:GetID(), owner = u:GetOwner(), type = short(info_type(GameInfo.Units, u:GetUnitType())),
                            hp = u:GetMaxHitPoints() - u:GetDamage() }
    end
  end
  local out = { ok = true, visible = true, units = units }
  if plot:IsCity() then
    local c = plot:GetPlotCity()
    out.city = { name = c:GetName(), owner = c:GetOwner(), hp = c:GetMaxHitPoints() - c:GetDamage() }
  end
  return out
end

function H.city_ranged_attack(city_id, x, y, pid)
  local p = Players[pid]
  local city = p:GetCityByID(city_id)
  if not city then return { ok = false, err = "no such city" } end
  if not city:CanRangeStrike() then return { ok = false, err = "city cannot range strike (no ranged combat / already struck this turn?)" } end
  if city.CanRangeStrikeNow and not city:CanRangeStrikeNow() then
    return { ok = false, err = "city cannot range strike this turn" }
  end
  if not city:CanRangeStrikeAt(x, y, true, true) then return { ok = false, err = "cannot strike that plot from this city" } end
  if not Network or not Network.SendDoTask then
    return { ok = false, err = "SendDoTask unavailable" }
  end
  Network.SendDoTask(city:GetID(), TaskTypes.TASK_RANGED_ATTACK, x, y, false, false, false, false)
  return { ok = true }
end

-- Social policies: same Network.SendUpdatePolicies(id, isPolicy, true) call the confirm-yes button in
-- socialpolicypopup.lua makes. isPolicy=true adopts a policy within an unlocked branch; isPolicy=false
-- unlocks a branch itself (both share the same underlying call with the id field reused for either).
-- Unit promotion: GAMEMESSAGE_DO_COMMAND(COMMAND_PROMOTION) via the selection list (v86), the same
-- message the unit panel's promotion action sends, so every peer applies it.
function H.choose_promotion(unit_id, promotion_name, pid)
  local id = GameInfoTypes[promotion_name]
  if id == nil then return { ok = false, err = "unknown promotion " .. tostring(promotion_name) } end
  local u = Players[pid]:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  if not u:CanAcquirePromotion(id) then return { ok = false, err = "cannot acquire this promotion right now" } end
  -- GAMEMESSAGE_DO_COMMAND(COMMAND_PROMOTION) is what the unit panel's action sends; it runs
  -- CvUnit::promote() on every peer: raises the level, consumes the promotion, and applies one-shot
  -- effects (PROMOTION_INSTA_HEAL). A bare SetHasPromotion(id, true) did none of that -- it left
  -- the unit at level 1 and unhealed with a dangling promotion flag (live, turn 18 of the China game).
  local lvl0, dmg0 = u:GetLevel(), u:GetDamage()
  local cmd = CommandTypes.COMMAND_PROMOTION
  if not u:CanDoCommand(cmd, id, -1) then
    -- Seen live right after the unit's own ranged attack (still "busy"): do NOT fall back to a bare
    -- SetHasPromotion here -- that leaves a level-1 unit with the promotion flag set and no level-up.
    return { ok = false, err = "unit cannot promote right now (busy or mid-mission); retry shortly" }
  end
  local sent = do_command(u, cmd, id, -1)
  if not sent.ok then return sent end
  -- Applied on a later game update: the Python wrapper polls H.promotion_check.
  return { ok = true, pending = true, promotion_id = id, level_before = lvl0,
           hp_before = u:GetMaxHitPoints() - dmg0 }
end

function H.promotion_check(unit_id, promotion_id, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  return { ok = true, level = u:GetLevel(), has = u:IsHasPromotion(promotion_id),
           hp = u:GetMaxHitPoints() - u:GetDamage(), promotion_ready = u:IsPromotionReady() }
end

-- Upgrade a unit in place (Warrior -> Swordsman etc.) for gold. No Network.Send* exists for this
-- (probed live: Network.SendDoCommand is nil); GAMEMESSAGE_DO_COMMAND(COMMAND_UPGRADE) is what the
-- unit panel's action sends. The engine replaces the unit object: the old id dies and a new unit of
-- the upgraded type appears on the same plot, so the Python wrapper polls H.upgrade_unit_check for it.
function H.upgrade_unit(unit_id, pid)
  local p = Players[pid]
  local u = p:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  local ut = u:GetUpgradeUnitType()
  if ut == nil or ut < 0 then return { ok = false, err = "no upgrade path for this unit" } end
  local target = GameInfo.Units[ut].Type
  local price = u:UpgradePrice(ut)
  local gold = p:GetGold()
  if u.CanUpgradeRightNow and not u:CanUpgradeRightNow() then
    return { ok = false, err = "cannot upgrade right now (needs own/allied territory, full moves, gold " .. tostring(price) .. " of " .. tostring(gold) .. ", and the strategic resource)", target = target, price = price, gold = gold }
  end
  local cmd = CommandTypes.COMMAND_UPGRADE
  if not u:CanDoCommand(cmd, -1, -1) then
    return { ok = false, err = "COMMAND_UPGRADE not available for this unit right now", target = target, price = price, gold = gold }
  end
  local x, y = u:GetX(), u:GetY()
  local sent = do_command(u, cmd, -1, -1)
  if not sent.ok then return sent end
  return { ok = true, pending = true, old_unit_id = unit_id, x = x, y = y, target_type_id = ut,
           old_type_id = u:GetUnitType(), target = target, price = price, gold_before = gold }
end

function H.upgrade_unit_check(unit_id, x, y, ut, old_type, pid)
  local p = Players[pid]
  local pl = Map.GetPlot(x, y)
  local new_id, new_type = nil, nil
  if pl then
    for i = 0, pl:GetNumUnits() - 1 do
      local v = pl:GetUnit(i)
      if v and v:GetOwner() == pid and v:GetUnitType() == ut then new_id, new_type = v:GetID(), GameInfo.Units[v:GetUnitType()].Type end
    end
  end
  local still = p:GetUnitByID(unit_id)
  return { ok = true, unit_id = new_id, type = new_type, gold = p:GetGold(),
           old_still_exists = still ~= nil and still:GetUnitType() == old_type }
end

-- Disband a unit (the unit panel's "Disband" button: COMMAND_DELETE). Frees its maintenance and any
-- strategic resource it consumed. Confirms by re-reading the unit and the resource counts.
function H.disband_unit(unit_id, pid)
  local p = Players[pid]
  local u = p:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  local cmd = CommandTypes.COMMAND_DELETE
  if not u:CanDoCommand(cmd, -1, -1) then
    -- live t59: a Pathfinder that spent its moves on a resumed standing order could not be disbanded
    if u:MovesLeft() <= 0 then
      return { ok = false, err = "a unit with no moves left this turn cannot be disbanded; try again next turn before it moves" }
    end
    return { ok = false, err = "COMMAND_DELETE not available for this unit right now (not this player's turn, or the unit cannot be disbanded)" }
  end
  local utype = GameInfo.Units[u:GetUnitType()].Type
  local before = { units = p:GetNumUnits(), strategic = H.strategic_resources(pid) }
  local sent = do_command(u, cmd, -1, -1)
  if not sent.ok then return sent end
  -- COMMAND_DELETE is applied on a later game tick (live t277: the unit still existed here, and was
  -- gone by the next call). The Python wrapper polls H.disband_unit_check.
  return { ok = true, pending = true, unit_id = unit_id, type = utype, before = before }
end

function H.disband_unit_check(unit_id, pid)
  local p = Players[pid]
  local still = p:GetUnitByID(unit_id)
  return { gone = still == nil, units = p:GetNumUnits(), strategic = H.strategic_resources(pid) }
end

-- ENDTURN_BLOCKING_STEAL_TECH: a spy finished stealing and the player must pick which tech to take
-- from that civ (BUTTONPOPUP_CHOOSE_TECH_TO_STEAL). The popup's choice is the same net message as a
-- free tech, with the victim in the 3rd slot: Network.SendResearch(tech, numFreeTechs, victim, false).
function H.steal_tech_options(pid)
  local p = Players[pid]
  local myTeam = Teams[p:GetTeam()]
  local out = { ok = true, victims = {} }
  for other = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
    local o = Players[other]
    if other ~= pid and o and o:IsAlive() and p.GetNumTechsToSteal and p:GetNumTechsToSteal(other) > 0 then
      local theirTeam = Teams[o:GetTeam()]
      local techs = {}
      for t in GameInfo.Technologies() do
        if theirTeam:IsHasTech(t.ID) and not myTeam:IsHasTech(t.ID) and p:CanResearch(t.ID) then
          techs[#techs+1] = { tech = t.Type, cost = p:GetResearchCost(t.ID), name = Locale.ConvertTextKey(t.Description) }
        end
      end
      -- `player_id` is what every other civ-targeting tool calls this (declare_war, relationship,
      -- war_consequences...); `player` is kept so older callers keep working.
      out.victims[#out.victims+1] = { player_id = other, player = other,
                                      civ = Locale.ConvertTextKey(o:GetCivilizationShortDescriptionKey()),
                                      num_to_steal = p:GetNumTechsToSteal(other), techs = techs }
    end
  end
  out.n = #out.victims
  return out
end

function H.steal_tech(tech, victim, pid)
  local p = Players[pid]
  local id = GameInfoTypes[tech]
  if id == nil then return { ok = false, err = "unknown tech " .. tostring(tech) } end
  if not (p.GetNumTechsToSteal and p:GetNumTechsToSteal(victim) > 0) then
    return { ok = false, err = "no stolen tech pending from that player" }
  end
  local myTeam = Teams[p:GetTeam()]
  if myTeam:IsHasTech(id) then return { ok = false, err = "already have that tech" } end
  if not Teams[Players[victim]:GetTeam()]:IsHasTech(id) then return { ok = false, err = "that player does not have that tech" } end
  if not p:CanResearch(id) then return { ok = false, err = "cannot research that tech yet (prereqs)" } end
  Network.SendResearch(id, p:GetNumFreeTechs(), victim, false)
  return { ok = true, sent = true }
end

function H.choose_policy(policy_name, pid)
  local id = GameInfoTypes[policy_name]
  if id == nil then return { ok = false, err = "unknown policy " .. tostring(policy_name) } end
  local p = Players[pid]
  if not p:CanAdoptPolicy(id) then return { ok = false, err = "cannot adopt this policy right now" } end
  Network.SendUpdatePolicies(id, true, true)
  return { ok = true }
end

function H.unlock_policy_branch(branch_name, pid)
  local id = GameInfoTypes[branch_name]
  if id == nil then return { ok = false, err = "unknown policy branch " .. tostring(branch_name) } end
  local p = Players[pid]
  if not p:CanUnlockPolicyBranch(id) then return { ok = false, err = "cannot unlock this branch right now" } end
  Network.SendUpdatePolicies(id, false, true)
  return { ok = true }
end

-- Religion: Network.SendFoundPantheon/SendFoundReligion, confirmed in
-- dlc/expansion2/ui/ingame/popups/{choosepantheonpopup,choosereligionpopup}.lua.
-- Free Great Person pick (ENDTURN_BLOCKING_FREE_ITEMS after finishing Liberty etc.). The UI's
-- choosefreeitem.lua Confirm button does Network.SendGreatPersonChoice(pid, unit.ID) guarded by
-- GetNumFreeGreatPeople() > 0, then UIManager:DequeuePopup (the Python side closes the popup).
function H.choose_free_great_person(unit_name, pid)
  local id = GameInfoTypes[unit_name]
  if id == nil then return { ok = false, err = "unknown unit " .. tostring(unit_name) } end
  local p = Players[pid]
  local n = p:GetNumFreeGreatPeople()
  if n <= 0 then return { ok = false, err = "no free great person to choose right now" } end
  local allowed = false
  for _, t in ipairs(H.own_great_people(pid)) do if t == unit_name then allowed = true end end
  if not allowed then
    return { ok = false, err = tostring(unit_name) .. " is not one of this civ's great people; see free_great_person_options" }
  end
  local before = p:GetNumUnits()
  Network.SendGreatPersonChoice(pid, id)
  return { ok = true, units_before = before, free_before = n }
end

-- Shoshone Pathfinder ruins choice (BUTTONPOPUP_CHOOSE_GOODY_HUT_REWARD, Data1 = player, Data2 = unit):
-- choosegoodyhutreward.lua lists GameInfo.GoodyHuts rows (goody type = row order) that pass
-- Player:CanGetGoody(plot, type, unit) and its Confirm sends Network.SendGoodyChoice(pid, x, y, type, unitID).
function H.goody_hut_options(unit_id, pid)
  local p = Players[pid]
  local u = p:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  local plot = u:GetPlot()
  local out, i = {}, 0
  for info in GameInfo.GoodyHuts() do
    if p:CanGetGoody(plot, i, u) then
      out[#out + 1] = { goody = info.Type, description = Locale.ConvertTextKey(info.ChooseDescription) }
    end
    i = i + 1
  end
  return { ok = true, unit_id = unit_id, x = plot:GetX(), y = plot:GetY(), options = out }
end

function H.choose_goody_hut(goody, unit_id, pid)
  local p = Players[pid]
  local u = p:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  local plot = u:GetPlot()
  local i, id = 0, nil
  for info in GameInfo.GoodyHuts() do
    if info.Type == goody then id = i end
    i = i + 1
  end
  if id == nil then return { ok = false, err = "unknown goody " .. tostring(goody) } end
  if not p:CanGetGoody(plot, id, u) then return { ok = false, err = "that reward is not offered here" } end
  Network.SendGoodyChoice(pid, plot:GetX(), plot:GetY(), id, unit_id)
  return { ok = true, goody = goody }
end

-- Ideology (ENDTURN_BLOCKING_CHOOSE_IDEOLOGY, BUTTONPOPUP_CHOOSE_IDEOLOGY): chooseideologypopup.lua's
-- Confirm button sends Network.SendIdeologyChoice(player, branchId) and closes. The choice is applied
-- by the engine on its next tick, so the caller polls Player:GetLateGamePolicyTree().
function H.choose_ideology(branch, pid)
  local p = Players[pid]
  local info = GameInfo and GameInfo.PolicyBranchTypes and GameInfo.PolicyBranchTypes[branch] or nil
  if not info then return { ok = false, err = "unknown policy branch" } end
  -- PolicyBranchTypes has no "late game" column in this build; ideologies are the branches bought by
  -- tenet level (PurchaseByLevel=true: Freedom/Order/Autocracy only)
  if not info.PurchaseByLevel then return { ok = false, err = "not an ideology branch (Freedom / Order / Autocracy)" } end
  local have = p.GetLateGamePolicyTree and p:GetLateGamePolicyTree() or -1
  if have and have >= 0 then
    return { ok = false, err = "an ideology is already chosen", ideology = GameInfo.PolicyBranchTypes[have].Type }
  end
  if not (Network and Network.SendIdeologyChoice) then return { ok = false, err = "Network.SendIdeologyChoice unavailable" } end
  Network.SendIdeologyChoice(pid, info.ID)
  return { ok = true, pending = true, branch = info.Type, id = info.ID }
end

function H.ideology_state(pid)
  local p = Players[pid]
  local have = p.GetLateGamePolicyTree and p:GetLateGamePolicyTree() or -1
  return { ideology = (have and have >= 0) and GameInfo.PolicyBranchTypes[have].Type or nil,
           free_tenets = p.GetNumFreeTenets and p:GetNumFreeTenets() or nil }
end

-- The great people this civ can take: its own unit for each great-person class (the class default unless
-- Civilization_UnitClassOverrides replaces it). Listing every SPECIALUNIT_PEOPLE row offered the Mongolian Khan
-- and the Venetian Merchant to the Shoshone (live t98).
function H.own_great_people(pid)
  local civ = GameInfo.Civilizations[Players[pid]:GetCivilizationType()].Type
  local out, seen = {}, {}
  for u in GameInfo.Units() do
    if u.Special == "SPECIALUNIT_PEOPLE" and u.Class ~= "UNITCLASS_PROPHET" and not seen[u.Class] then
      seen[u.Class] = true
      local unit = GameInfo.UnitClasses[u.Class] and GameInfo.UnitClasses[u.Class].DefaultUnit
      for o in GameInfo.Civilization_UnitClassOverrides{ CivilizationType = civ, UnitClassType = u.Class } do
        unit = o.UnitType
      end
      if unit then out[#out + 1] = unit end
    end
  end
  return out
end

function H.free_great_person_options(pid)
  return { count = Players[pid]:GetNumFreeGreatPeople(), options = H.own_great_people(pid) }
end

-- The Long Count popup lists trainable Great People and disables previously chosen types
-- until the cycle is complete. CanTrain's flags match choosemayabonus.lua.
function H.maya_options(pid)
  local p = Players[pid]
  local n, options = p:GetNumMayaBoosts(), {}
  if n > 0 then
    for u in GameInfo.Units{ Special = "SPECIALUNIT_PEOPLE" } do
      if p:CanTrain(u.ID, true, true, true, false) then
        local earlier = p:GetUnitBaktun(u.ID)
        options[#options + 1] = { unit = u.Type, name = H.L(u.Description), description = H.L(u.Strategy),
          available = earlier <= 0 or p:IsFreeMayaGreatPersonChoice(), previous_baktun = earlier > 0 and earlier or nil }
      end
    end
  end
  return { ok = true, count = n, options = options }
end

function H.choose_maya_bonus(unit, pid)
  if Game.GetActivePlayer() ~= pid then return { ok = false, err = "this seat is not active" } end
  local opts = H.maya_options(pid)
  for _, row in ipairs(opts.options) do
    if row.unit == unit and row.available then
      Network.SendMayaBonusChoice(pid, GameInfoTypes[unit])
      return { ok = true, before = opts.count, unit = unit }
    end
  end
  return { ok = false, err = "that Long Count reward is not available; see maya_options" }
end

function H.archaeology_options(pid)
  local p = Players[pid]
  local plot = p:GetNextDigCompletePlot()
  if not plot then return { ok = true, pending = false, options = {} } end
  local team = p:GetTeam()
  if not plot:IsVisible(team, false) then return { ok = false, err = "completed dig is not visible" } end
  local written = plot:HasWrittenArtifact()
  local art = p:HasAvailableGreatWorkSlot(GameInfo.GreatWorkSlots.GREAT_WORK_SLOT_ART_ARTIFACT.ID)
  local writing = p:HasAvailableGreatWorkSlot(GameInfo.GreatWorkSlots.GREAT_WORK_SLOT_LITERATURE.ID)
  local kind = GameInfo.GreatWorkArtifactClasses[plot:GetArchaeologyArtifactType()]
  local function identity(id)
    local other = Players[id]
    if other and (id == pid or Teams[team]:IsHasMet(other:GetTeam())) then
      return { player = id, civ = other:GetCivilizationShortDescription() }
    end
    return { civ = "unknown" }
  end
  local first, second = identity(plot:GetArchaeologyArtifactPlayer1()), identity(plot:GetArchaeologyArtifactPlayer2())
  local options = {}
  if not written and art then
    options[#options + 1] = { choice = 2, action = "artifact_player1", origin = first }
    if kind.Type ~= "ARTIFACT_BARBARIAN_CAMP" and kind.Type ~= "ARTIFACT_ANCIENT_RUIN" then
      options[#options + 1] = { choice = 3, action = "artifact_player2", origin = second }
    end
  elseif written and writing then
    options[#options + 1] = { choice = 5, action = "great_work_writing", origin = first }
  end
  options[#options + 1] = written and { choice = 4, action = "culture", culture = p:GetWrittenArtifactCulture() }
                                  or { choice = 1, action = "landmark" }
  local pop = H.popups[ButtonPopupTypes.BUTTONPOPUP_CHOOSE_ARCHAEOLOGY]
  return { ok = true, pending = true, x = plot:GetX(), y = plot:GetY(), written = written,
    artifact = kind.Type, name = H.L(Game.GetArtifactName(plot)), era = GameInfo.Eras[plot:GetArchaeologyArtifactEra()].Type,
    origins = { first, second }, art_slot = art, writing_slot = writing, options = options,
    unit_id = pop and pop.player == pid and pop.data2 or nil }
end

function H.choose_archaeology(choice, x, y, pid)
  if Game.GetActivePlayer() ~= pid then return { ok = false, err = "this seat is not active" } end
  local opts = H.archaeology_options(pid)
  if not opts.ok or not opts.pending or opts.x ~= x or opts.y ~= y then
    return { ok = false, err = "no matching completed dig; refresh archaeology_options" }
  end
  if not opts.unit_id then return { ok = false, err = "open the completed-dig notification to capture the archaeologist's popup" } end
  for _, row in ipairs(opts.options) do
    if row.choice == choice then
      Network.SendArchaeologyChoice(pid, opts.unit_id, choice)
      return { ok = true, choice = choice, x = x, y = y }
    end
  end
  return { ok = false, err = "that archaeology choice is not offered; see archaeology_options" }
end

-- The Religion Overview screen (religionoverview.lua), all three tabs. An unmet founder's civ and holy city
-- read "unknown" exactly as the World Religions / Beliefs tabs mask them.
function H.religion_overview(pid)
  local p = Players[pid]
  local team = Teams[p:GetTeam()]
  local out = { ok = true, faith = p:GetFaith(), faith_per_turn = p:GetTotalFaithPerTurn(),
                next_great_prophet_faith = p:GetMinimumFaithNextGreatProphet(),
                religions_still_to_found = Game.GetNumReligionsStillToFound() }
  local function belief_rows(ids)
    local rows = {}
    for _, v in ipairs(ids) do
      local b = GameInfo.Beliefs[v]
      if b then rows[#rows + 1] = { belief = b.Type, name = Locale.Lookup(b.ShortDescription), description = Locale.Lookup(b.Description) } end
    end
    return rows
  end
  if p:HasCreatedReligion() then
    local r = p:GetReligionCreatedByPlayer()
    out.status = "religion"
    out.religion = GameInfo.Religions[r].Type
    out.beliefs = belief_rows(Game.GetBeliefsInReligion(r))
  elseif p:HasCreatedPantheon() then
    out.status = "pantheon"
    out.beliefs = belief_rows({ p:GetBeliefInPantheon() })
  else
    out.status = "none"
    out.pantheon_faith_needed = Game.GetMinimumFaithNextPantheon()
    out.can_create_pantheon = p:CanCreatePantheon(true)  -- true = with the faith check, as the screen's status line
  end
  out.world = {}
  for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
    local o = Players[i]
    if o:IsEverAlive() and o:HasCreatedReligion() then
      local r = o:GetReligionCreatedByPlayer()
      local met = i == pid or team:IsHasMet(o:GetTeam())
      local holy = Game.GetHolyCityForReligion(r, i)
      out.world[#out.world + 1] = {
        religion = GameInfo.Religions[r].Type, cities_following = Game.GetNumCitiesFollowing(r),
        founder = met and i or "unknown", founder_civ = met and o:GetCivilizationShortDescription() or "unknown",
        holy_city = met and holy and holy:GetName() or "unknown",
        beliefs = belief_rows(Game.GetBeliefsInReligion(r)),
      }
    elseif i ~= pid and o:IsEverAlive() and o:HasCreatedPantheon() then
      -- Beliefs tab: a rival pantheon's belief is listed, its owner named only once met
      out.pantheons = out.pantheons or {}
      local met = team:IsHasMet(o:GetTeam())
      out.pantheons[#out.pantheons + 1] = { civ = met and o:GetCivilizationShortDescription() or "unknown",
                                            belief = belief_rows({ o:GetBeliefInPantheon() })[1] }
    end
  end
  out.cities = {}
  for c in p:Cities() do
    local row = { id = c:GetID(), name = c:GetName(), pop = c:GetPopulation(), religions = {} }
    local maj = c:GetReligiousMajority()
    row.majority = maj and maj >= 0 and GameInfo.Religions[maj] and GameInfo.Religions[maj].Type or nil
    -- Banner units: GetPressurePerTurn is raw; the overview prints floor(raw / multiplier)
    -- (infotooltipinclude.lua). Live t179 reported 300 here vs 30 on the city banner.
    local mult = (GameDefines and GameDefines.RELIGION_MISSIONARY_PRESSURE_MULTIPLIER) or 10
    for rel in GameInfo.Religions() do
      local n = c:GetNumFollowers(rel.ID)
      local raw, routes = c:GetPressurePerTurn(rel.ID)
      if rel.Type ~= "RELIGION_PANTHEON" and (n > 0 or (raw or 0) > 0) then
        row.religions[#row.religions + 1] = { religion = rel.Type, followers = n, pressure_raw = raw,
                                              pressure_per_turn = math.floor((raw or 0) / mult),
                                              trade_routes = routes or (c.GetNumTradeRoutesAddingPressure and c:GetNumTradeRoutesAddingPressure(rel.ID)),
                                              holy_city = c:IsHolyCityForReligion(rel.ID) or nil,
                                              majority = rel.ID == maj or nil }
      end
    end
    out.cities[#out.cities + 1] = row
  end
  return out
end

-- ENDTURN_BLOCKING_FAITH_GREAT_PERSON (choosefaithgreatperson.lua): SPECIALUNIT_PEOPLE rows passing
-- CanTrain(id, true, true, true, false); a Prophet needs a pantheon and a religion slot (or an own religion),
-- every other type its finished policy branch. Confirm sends Network.SendFaithGreatPersonChoice(pid, unitID).
H.FAITH_GP_BRANCH = {
  UNIT_MERCHANT = "POLICY_BRANCH_COMMERCE", UNIT_SCIENTIST = "POLICY_BRANCH_RATIONALISM",
  UNIT_WRITER = "POLICY_BRANCH_AESTHETICS", UNIT_ARTIST = "POLICY_BRANCH_AESTHETICS",
  UNIT_MUSICIAN = "POLICY_BRANCH_AESTHETICS", UNIT_GREAT_GENERAL = "POLICY_BRANCH_HONOR",
  UNIT_GREAT_ADMIRAL = "POLICY_BRANCH_EXPLORATION", UNIT_ENGINEER = "POLICY_BRANCH_TRADITION",
}
function H.faith_great_person_options(pid)
  local p = Players[pid]
  local out = {}
  for info in GameInfo.Units{ Special = "SPECIALUNIT_PEOPLE" } do
    if p:CanTrain(info.ID, true, true, true, false) then
      local branch = H.FAITH_GP_BRANCH[info.Type]
      local hidden
      if info.Type == "UNIT_PROPHET" then
        hidden = not p:HasCreatedPantheon() or (not p:HasCreatedReligion() and Game.GetNumReligionsStillToFound() == 0)
      else
        hidden = branch ~= nil and not p:IsPolicyBranchFinished(GameInfo.PolicyBranchTypes[branch].ID)
      end
      if not hidden then out[#out + 1] = info.Type end
    end
  end
  return { ok = true, options = out, faith = p:GetFaith() }
end

function H.choose_faith_great_person(unit_name, pid)
  local p = Players[pid]
  if H.blocking_name(p:GetEndTurnBlockingType()) ~= "ENDTURN_BLOCKING_FAITH_GREAT_PERSON" then
    return { ok = false, err = "no faith great person choice is pending" }
  end
  local opts = H.faith_great_person_options(pid).options
  for _, t in ipairs(opts) do
    if t == unit_name then
      local before = p:GetNumUnits()
      Network.SendFaithGreatPersonChoice(pid, GameInfoTypes[unit_name])
      return { ok = true, unit = unit_name, units_before = before }
    end
  end
  return { ok = false, err = "not on offer", options = opts }
end

-- Belief lists exactly as choosepantheonpopup.lua / choosereligionpopup.lua build them: one
-- Game.GetAvailable*Beliefs() getter per slot kind, rows named by ShortDescription + Description.
H.BELIEF_GETTERS = {
  pantheon = "GetAvailablePantheonBeliefs", founder = "GetAvailableFounderBeliefs",
  follower = "GetAvailableFollowerBeliefs", enhancer = "GetAvailableEnhancerBeliefs",
  bonus = "GetAvailableBonusBeliefs", reformation = "GetAvailableReformationBeliefs",
}
function H.belief_available(kind, id)
  for _, v in ipairs(Game[H.BELIEF_GETTERS[kind]]()) do
    if v == id then return true end
  end
  return false
end
function H.available_beliefs(kind, pid)
  local getter = H.BELIEF_GETTERS[kind]
  if not getter then return { ok = false, err = "kind is one of pantheon, founder, follower, enhancer, bonus, reformation" } end
  local out = {}
  for _, v in ipairs(Game[getter]()) do
    local b = GameInfo.Beliefs[v]
    if b then
      out[#out + 1] = { belief = b.Type, name = Locale.Lookup(b.ShortDescription), description = Locale.Lookup(b.Description) }
    end
  end
  local r = { ok = true, kind = kind, beliefs = out }
  if kind == "founder" then
    -- choosereligionpopup.lua: every Religions row but the pantheon, minus the ones a player already created
    local taken = {}
    for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
      local o = Players[i]
      if o:IsEverAlive() and o:HasCreatedReligion() then taken[o:GetReligionCreatedByPlayer()] = true end
    end
    r.religions = {}
    for row in GameInfo.Religions("Type <> 'RELIGION_PANTHEON'") do
      if not taken[row.ID] then r.religions[#r.religions + 1] = row.Type end
    end
  end
  return r
end

-- ENDTURN_BLOCKING_ADD_REFORMATION_BELIEF: the pantheon popup with Data2 == 0 lists the reformation
-- beliefs and its Confirm sends the same Network.SendFoundPantheon(player, beliefID).
function H.add_reformation_belief(belief_name, pid)
  local id = GameInfoTypes[belief_name]
  if id == nil then return { ok = false, err = "unknown belief " .. tostring(belief_name) } end
  local p = Players[pid]
  if H.blocking_name(p:GetEndTurnBlockingType()) ~= "ENDTURN_BLOCKING_ADD_REFORMATION_BELIEF" then
    return { ok = false, err = "no reformation belief is pending" }
  end
  if not H.belief_available("reformation", id) then
    return { ok = false, err = "not an available reformation belief", available = H.available_beliefs("reformation", pid).beliefs }
  end
  Network.SendFoundPantheon(pid, id)
  return { ok = true }
end

function H.found_pantheon(belief_name, pid)
  local id = GameInfoTypes[belief_name]
  if id == nil then return { ok = false, err = "unknown belief " .. tostring(belief_name) } end
  local p = Players[pid]
  if not p:CanCreatePantheon() then return { ok = false, err = "cannot create a pantheon right now (needs enough Faith)" } end
  if not H.belief_available("pantheon", id) then
    return { ok = false, err = "not an available pantheon belief (taken, or another kind): see available_beliefs" }
  end
  Network.SendFoundPantheon(pid, id)
  return { ok = true }
end

function H.found_religion(religion_name, belief_names, city_x, city_y, custom_name, pid)
  local religion_id = GameInfoTypes[religion_name]
  if religion_id == nil then return { ok = false, err = "unknown religion " .. tostring(religion_name) } end
  local beliefs = {}
  for i = 1, 4 do
    local n = belief_names[i]
    beliefs[i] = n and GameInfoTypes[n] or -1
    if n and beliefs[i] == nil then return { ok = false, err = "unknown belief " .. tostring(n) } end
  end
  -- slot order as choosereligionpopup.lua sends it: pantheon (only without one yet), founder, follower,
  -- bonus (Byzantium's trait)
  local p = Players[pid]
  local kinds = {}
  if not p:HasCreatedPantheon() then kinds[#kinds + 1] = "pantheon" end
  kinds[#kinds + 1] = "founder"
  kinds[#kinds + 1] = "follower"
  if p:IsTraitBonusReligiousBelief() then kinds[#kinds + 1] = "bonus" end
  if #belief_names ~= #kinds then
    return { ok = false, err = "beliefs must be exactly, in order: " .. table.concat(kinds, ", ") }
  end
  for i, kind in ipairs(kinds) do
    if not H.belief_available(kind, beliefs[i]) then
      return { ok = false, err = tostring(belief_names[i]) .. " is not an available " .. kind .. " belief (order: " .. table.concat(kinds, ", ") .. "); see available_beliefs" }
    end
  end
  Network.SendFoundReligion(pid, religion_id, custom_name or "", beliefs[1], beliefs[2], beliefs[3], beliefs[4], city_x, city_y)
  return { ok = true }
end

-- Network.SendEnhanceReligion(playerID, religionID, customName, belief4, belief5, cityX, cityY): confirmed
-- in choosereligionpopup.lua, called when ENDTURN_BLOCKING_ENHANCE_RELIGION comes up (two more belief
-- slots on top of the ones chosen at founding). Reformation-belief picks (ADD_REFORMATION_BELIEF, granted
-- by a Reformation-branch policy) were NOT resolved this pass -- no second call site was found, so it may
-- reuse this same one under a different mode flag or be a separate one not yet located; don't guess here.
function H.enhance_religion(religion_name, belief4_name, belief5_name, city_x, city_y, custom_name, pid)
  local religion_id = GameInfoTypes[religion_name]
  if religion_id == nil then return { ok = false, err = "unknown religion " .. tostring(religion_name) } end
  local b4 = GameInfoTypes[belief4_name]
  local b5 = GameInfoTypes[belief5_name]
  if b4 == nil then return { ok = false, err = "unknown belief " .. tostring(belief4_name) } end
  if b5 == nil then return { ok = false, err = "unknown belief " .. tostring(belief5_name) } end
  if not H.belief_available("follower", b4) then return { ok = false, err = "belief4 must be an available follower belief; see available_beliefs" } end
  if not H.belief_available("enhancer", b5) then return { ok = false, err = "belief5 must be an available enhancer belief; see available_beliefs" } end
  Network.SendEnhanceReligion(pid, religion_id, custom_name or "", b4, b5, city_x, city_y)
  return { ok = true }
end

-- Item-based trade deals: UI.GetScratchDeal() returns a shared "scratch" deal object with a dedicated Add*
-- method per item type (there is no generic AddItemOfType -- each type has its own method and argument
-- shape, confirmed by reading every Add* call site in ui/ingame/worldview/tradelogic.lua). Same call path
-- for a human or an AI recipient: build the deal, SetFromPlayer/SetToPlayer, UI.DoProposeDeal(). An AI
-- either accepts (deal resolves) or doesn't; a human recipient sees it as an incoming offer.
-- `items`: a list of { type = "GOLD"|"GOLD_PER_TURN"|"RESOURCES"|"OPEN_BORDERS"|"DEFENSIVE_PACT"|
--   "RESEARCH_AGREEMENT"|"TRADE_AGREEMENT"|"ALLOW_EMBASSY"|"DECLARATION_OF_FRIENDSHIP"|"PEACE_TREATY"|
--   "CITIES", from_us = true|false, ...type-specific fields (amount / resource / city_id) }.
--
-- ROOT CAUSE of the 2026-09-16 crash (see docs/NOTES.md "Phase 3a"): every Add* method in the real UI is
-- only reachable through a pocket button that tradelogic.lua populates by first calling
-- `deal:IsPossibleToTradeItem(from, to, TradeableItems.TRADE_ITEM_*, ...)` -- e.g. lines ~1124 (embassy),
-- ~1057 (gold), ~1283 (research agreement) of ui/ingame/worldview/tradelogic.lua. An item that fails that
-- check is never offered to the player at all. This function used to skip that gate entirely and call
-- Add* unconditionally, so a single ALLOW_EMBASSY item that was NOT actually valid between the two players
-- (e.g. an embassy already existed, one side doesn't allow embassy trading) reached UI.DoProposeDeal() as
-- part of an invalid deal and crashed the process natively. Fixed by validating every item with the same
-- IsPossibleToTradeItem call the UI itself uses before adding it, and by mirroring the two other guards
-- OnPropose()/OnOpenPlayerDealScreen() apply: refuse an empty deal, and refuse a second proposal while one
-- is already outstanding (UI.HasMadeProposal). NOT yet re-verified live -- test against a throwaway game
-- before trusting this in a real session.
-- RETIRED 2026-09-17: the headless Add*/DoProposeDeal path below crashed the game eight times. Deals now
-- go through the real trade screen from Python (Game.propose_deal in harness/game.py drives
-- LeaderHeadRoot.OnTrade + tradelogic.lua's pocket handlers + OnPropose). The body is kept only as a
-- reference for the per-item IsPossibleToTradeItem shapes (H.trade_catalog uses the same ones).
function H.propose_deal(other_player, items, pid)
  return { ok = false, err = "headless propose_deal is retired; use Game.propose_deal (real trade screen)" }
end
function H.propose_deal_headless_reference(other_player, items, pid)
  if #items == 0 then return { ok = false, err = "no items in deal" } end
  local existing = UI.HasMadeProposal(pid)
  if existing ~= -1 and existing ~= other_player then
    return { ok = false, err = "a proposal to another player is already outstanding" }
  end
  local deal = UI.GetScratchDeal()
  deal:ClearItems()
  local duration = Game.GetDealDuration()
  for _, item in ipairs(items) do
    local from = item.from_us and pid or other_player
    local to = item.from_us and other_player or pid
    local t = item.type
    local possible, extra
    if t == "GOLD" then
      possible = deal:IsPossibleToTradeItem(from, to, TradeableItems.TRADE_ITEM_GOLD, item.amount)
      extra = function() deal:AddGoldTrade(from, item.amount) end
    elseif t == "GOLD_PER_TURN" then
      possible = deal:IsPossibleToTradeItem(from, to, TradeableItems.TRADE_ITEM_GOLD_PER_TURN, item.amount, duration)
      extra = function() deal:AddGoldPerTurnTrade(from, item.amount, duration) end
    elseif t == "RESOURCES" then
      local rid = GameInfoTypes[item.resource]
      if rid == nil then return { ok = false, err = "unknown resource " .. tostring(item.resource) } end
      possible = deal:IsPossibleToTradeItem(from, to, TradeableItems.TRADE_ITEM_RESOURCES, rid, item.amount)
      extra = function() deal:AddResourceTrade(from, rid, item.amount, duration) end
    elseif t == "OPEN_BORDERS" then
      possible = deal:IsPossibleToTradeItem(from, to, TradeableItems.TRADE_ITEM_OPEN_BORDERS, duration)
      extra = function() deal:AddOpenBorders(from, duration) end
    elseif t == "DEFENSIVE_PACT" then
      possible = deal:IsPossibleToTradeItem(from, to, TradeableItems.TRADE_ITEM_DEFENSIVE_PACT, duration)
      extra = function() deal:AddDefensivePact(from, duration) end
    elseif t == "RESEARCH_AGREEMENT" then
      possible = deal:IsPossibleToTradeItem(from, to, TradeableItems.TRADE_ITEM_RESEARCH_AGREEMENT, duration)
      extra = function() deal:AddResearchAgreement(from, duration) end
    elseif t == "TRADE_AGREEMENT" then
      possible = deal:IsPossibleToTradeItem(from, to, TradeableItems.TRADE_ITEM_TRADE_AGREEMENT, duration)
      extra = function() deal:AddTradeAgreement(from, duration) end
    elseif t == "ALLOW_EMBASSY" then
      possible = deal:IsPossibleToTradeItem(from, to, TradeableItems.TRADE_ITEM_ALLOW_EMBASSY, duration)
      extra = function() deal:AddAllowEmbassy(from) end
    elseif t == "DECLARATION_OF_FRIENDSHIP" then
      -- CRASHED THE GAME live (2026-09-16, round 2 of this same fix pass): tradelogic.lua only ever
      -- populates/checks this item when g_bPVPTrade is true ("Only PvP trade, with the AI there is a
      -- dedicated interface for this trade", line ~1399) -- deal:IsPossibleToTradeItem() itself crashed
      -- natively when called for this item type against an AI recipient. Block it before touching the
      -- engine at all; use H.diplo_event with a DoF-related FromUIDiploEventTypes event for AI instead
      -- (see docs/NOTES.md diplomacy section).
      if not Players[other_player]:IsHuman() then
        deal:ClearItems()
        return { ok = false, err = "DECLARATION_OF_FRIENDSHIP is PvP-only; use diplo_event for an AI" }
      end
      possible = deal:IsPossibleToTradeItem(from, to, TradeableItems.TRADE_ITEM_DECLARATION_OF_FRIENDSHIP, duration)
      extra = function() deal:AddDeclarationOfFriendship(from) end
    elseif t == "PEACE_TREATY" then
      -- CRASHED THE GAME live (2026-09-16, third crash of this pass, see docs/NOTES.md "Phase 3a live
      -- verification") even with both required sides added exactly as below, matching
      -- OnOpenPlayerDealScreen's own AddPeaceTreaty(us,...)+AddPeaceTreaty(them,...) pair -- this is NOT
      -- fixed, the crash is in the native Add* call itself, not a missing validation. Left implemented
      -- (and now matching the real UI's paired-sides shape, which the original single-sided version did
      -- not) only so a future session that finds a real fix doesn't also have to rediscover this
      -- asymmetry; do not call PEACE_TREATY (or re-expose propose_deal at all) until that's resolved.
      -- No IsPossibleToTradeItem gate for this one in the real UI either (tradelogic.lua adds it
      -- unconditionally when IsAtWar); mirror that same precondition instead.
      local fromTeam = Players[from]:GetTeam()
      local toTeam = Players[to]:GetTeam()
      possible = Teams[fromTeam]:IsAtWar(toTeam)
      extra = function()
        deal:AddPeaceTreaty(from, GameDefines.PEACE_TREATY_LENGTH)
        deal:AddPeaceTreaty(to, GameDefines.PEACE_TREATY_LENGTH)
      end
    elseif t == "CITIES" then
      local city = Players[from]:GetCityByID(item.city_id)
      if not city then deal:ClearItems(); return { ok = false, err = "no such city" } end
      possible = deal:IsPossibleToTradeItem(from, to, TradeableItems.TRADE_ITEM_CITIES, city:GetX(), city:GetY())
      extra = function() deal:AddCityTrade(from, item.city_id) end
    else
      deal:ClearItems()
      return { ok = false, err = "unsupported item type " .. tostring(t) }
    end
    if not possible then
      deal:ClearItems()
      return { ok = false, err = "item not tradeable: " .. tostring(t) .. " from " .. tostring(from) .. " to " .. tostring(to) }
    end
    extra()
  end
  deal:SetFromPlayer(pid)
  deal:SetToPlayer(other_player)
  UI.DoProposeDeal()
  return { ok = true }
end

-- One deal object's items (scratch or a LoadCurrentDeal snapshot). Read-only: no Add*/ClearItems.
-- GetNextItem's third value is the turn the timed item ends (diplocurrentdeals.lua "ENDS ON").
function H.deal_items(deal, pid)
  local items = {}
  if not (deal and deal.ResetIterator and deal.GetNextItem) then return items end
  deal:ResetIterator()
  local itemType, duration, finalTurn, data1, data2, data3, flag1, fromPlayer = deal:GetNextItem()
  local turn = Game and Game.GetGameTurn and Game.GetGameTurn() or nil
  while itemType ~= nil do
    local name = H.enum_name("TradeableItems", TradeableItems, itemType)
    if type(name) == "string" then name = name:gsub("^TRADE_ITEM_", "") end
    local e = { type = name, from = fromPlayer, from_us = fromPlayer == pid, duration = duration }
    if type(finalTurn) == "number" and finalTurn > 0 then
      e.final_turn = finalTurn
      if type(turn) == "number" then e.turns_left = finalTurn - turn end
    end
    if name == "GOLD" or name == "GOLD_PER_TURN" then
      e.amount = data1
    elseif name == "RESOURCES" then
      e.resource = GameInfo and short(info_type(GameInfo.Resources, data1)) or data1
      e.amount = data2
      -- what giving it costs us (renewal offers name a resource trade_catalog no longer lists because
      -- it is still under the expiring deal; live t292 America's Dye renewal). Same numbers the
      -- top bar / trade screen show a human.
      if e.from_us and Players and Players[pid] then
        local pl, info = Players[pid], GameInfo and GameInfo.Resources and GameInfo.Resources[data1] or nil
        local function num(f) local okc, v = pcall(function() return pl[f](pl, data1, true) end) if okc and type(v) == "number" then return v end return nil end
        local function num1(f) local okc, v = pcall(function() return pl[f](pl, data1) end) if okc and type(v) == "number" then return v end return nil end
        e.class = info and info.ResourceClassType or nil
        e.us_total, e.us_available = num("GetNumResourceTotal"), num("GetNumResourceAvailable")
        e.us_imported, e.us_exported = num1("GetResourceImport"), num1("GetResourceExport")
        -- GetNumResourceTotal is already net of exports (live t292: Copper total 1, exported 2,
        -- available 1 = three copies owned, two under deals). us_owned undoes that so a renewal of an
        -- existing export is not mistaken for selling our only copy.
        if e.us_total then e.us_owned = e.us_total - (e.us_imported or 0) + (e.us_exported or 0) end
        if e.class == "RESOURCECLASS_LUXURY" and e.us_owned and e.us_owned <= (e.amount or 1) then
          e.last_copy = true
          e.note = "our only copy: exporting it removes its happiness from the empire"
        elseif e.us_available and e.us_available < (e.amount or 1) then
          e.note = "no spare copy: either this renews an export already counted in us_exported (no change), or it takes a copy we use"
        end
      elseif Players and Players[pid] then
        -- what receiving it gives us: a luxury we already have adds no happiness (live t444: Venice offered
        -- Spices for Copper and nothing said whether Spices was new). Our own count, as the top bar shows.
        local pl, info = Players[pid], GameInfo and GameInfo.Resources and GameInfo.Resources[data1] or nil
        e.class = info and info.ResourceClassType or nil
        local okc, have = pcall(function() return pl:GetNumResourceAvailable(data1, true) end)
        if okc and type(have) == "number" then
          e.us_have = have
          if e.class == "RESOURCECLASS_LUXURY" then
            e.note = have > 0 and "we already have this luxury: no extra happiness" or "new luxury for us: adds its happiness"
          end
        end
      end
    elseif name == "CITIES" then
      e.x, e.y = data1, data2
      -- The deal screen names the city. Resolve it from the offering player; coords stay as the
      -- item's identity (trade_catalog already withholds x,y for unrevealed plots).
      local owner = Players and Players[fromPlayer]
      if owner and owner.Cities then
        for c in owner:Cities() do
          if c:GetX() == data1 and c:GetY() == data2 then
            e.name, e.city_id = c:GetName(), c:GetID()
            break
          end
        end
      end
    elseif name == "THIRD_PARTY_PEACE" or name == "THIRD_PARTY_WAR" then
      e.other = data1
    end
    items[#items + 1] = e
    itemType, duration, finalTurn, data1, data2, data3, flag1, fromPlayer = deal:GetNextItem()
  end
  return items
end

-- Read the current scratch deal WITHOUT Add*/ClearItems/DoProposeDeal.
-- tradelogic.lua DisplayDeal() iterates with ResetIterator + GetNextItem; that is a
-- read of whatever is already on the table (empty, our draft, or an AI offer).
function H.incoming_deal(pid)
  if not UI or not UI.GetScratchDeal then
    return { ok = true, items = {}, n = 0 }
  end
  local ok, deal = pcall(function() return UI.GetScratchDeal() end)
  if not ok or deal == nil then return { ok = true, items = {}, n = 0 } end
  local from = deal.GetFromPlayer and deal:GetFromPlayer() or nil
  local to = deal.GetToPlayer and deal:GetToPlayer() or nil
  local items = H.deal_items(deal, pid)
  return { ok = true, items = items, n = #items, from = from, to = to }
end

-- Diplomacy Overview "Current Deals" tab (diplocurrentdeals.lua PopulateDealChooser).
-- Stock loads each row into the scratch deal via UI.LoadCurrentDeal. That is the same object
-- propose_deal / incoming_deal use, so this refuses when the table already has items and
-- ClearItems afterwards so a leftover current-deal does not look like an incoming offer.
-- Never Add* / DoProposeDeal.
function H.current_deals(pid)
  if not UI or not UI.GetNumCurrentDeals or not UI.LoadCurrentDeal then
    return { ok = false, err = "current-deals UI unavailable", deals = {}, n = 0 }
  end
  local scratch = H.incoming_deal(pid)
  if (scratch.n or 0) > 0 then
    return { ok = false, err = "trade table is occupied; answer incoming_deal first", deals = {}, n = 0 }
  end
  local okn, n = pcall(function() return UI.GetNumCurrentDeals(pid) end)
  if not okn or type(n) ~= "number" or n <= 0 then
    return { ok = true, deals = {}, n = 0 }
  end
  local okd, deal = pcall(function() return UI.GetScratchDeal() end)
  if not okd or deal == nil then
    return { ok = false, err = "no scratch deal to snapshot current deals into", deals = {}, n = 0 }
  end
  local turn = Game and Game.GetGameTurn and Game.GetGameTurn() or 0
  local out = {}
  for i = 0, n - 1 do
    local okl = pcall(function() UI.LoadCurrentDeal(pid, i) end)
    if okl then
      local items = H.deal_items(deal, pid)
      local other
      pcall(function() other = deal:GetOtherPlayer(pid) end)
      local start_turn, duration
      pcall(function() start_turn = deal:GetStartTurn() end)
      pcall(function() duration = deal:GetDuration() end)
      local ends_on
      if type(start_turn) == "number" and type(duration) == "number" then
        ends_on = start_turn + duration
      end
      local civ
      if other and Players and Players[other] and Players[other].GetCivilizationShortDescription then
        local met = true
        if Teams and Players[pid] then
          pcall(function() met = Teams[Players[pid]:GetTeam()]:IsHasMet(Players[other]:GetTeam()) end)
        end
        if met then civ = Players[other]:GetCivilizationShortDescription() end
      end
      local e = { other = other, civ = civ, items = items, n = #items,
                  start_turn = start_turn, duration = duration, ends_on = ends_on }
      if ends_on then e.turns_left = ends_on - turn end
      out[#out + 1] = e
    end
  end
  if deal.ClearItems then pcall(function() deal:ClearItems() end) end
  return { ok = true, deals = out, n = #out }
end

-- Finalize an EXISTING scratch deal (AI/human offer already on the table).
-- Never Add* — that path crashed the process. Stock UI: tradelogic.lua
-- UI.DoFinalizePlayerDeal(them, us, true/false) for PvP accept/refuse.
function H.accept_deal(pid)
  local d = H.incoming_deal(pid)
  if not d.ok or (d.n or 0) == 0 then return { ok = false, err = "no incoming deal" } end
  local them = d.from
  if them == pid then them = d.to end
  if them == nil or them == pid then return { ok = false, err = "deal has no other player" } end
  if not UI or not UI.DoFinalizePlayerDeal then
    return { ok = false, err = "DoFinalizePlayerDeal unavailable" }
  end
  UI.DoFinalizePlayerDeal(them, pid, true)
  return { ok = true, other = them }
end

function H.refuse_deal(pid)
  local d = H.incoming_deal(pid)
  if not d.ok or (d.n or 0) == 0 then return { ok = false, err = "no incoming deal" } end
  local them = d.from
  if them == pid then them = d.to end
  if them == nil or them == pid then return { ok = false, err = "deal has no other player" } end
  if not UI or not UI.DoFinalizePlayerDeal then
    return { ok = false, err = "DoFinalizePlayerDeal unavailable" }
  end
  UI.DoFinalizePlayerDeal(them, pid, false)
  return { ok = true, other = them }
end

-- What can currently go on a deal with `other`, using only IsPossibleToTradeItem.
-- Never Add*/ClearItems/DoProposeDeal. SetFromPlayer/SetToPlayer is required for
-- some item types to report correctly (live: lump GOLD stayed false until from/to
-- were set; GPT was already true). Skips DECLARATION_OF_FRIENDSHIP vs AI (native
-- crash) and PEACE_TREATY (AddPeaceTreaty crashed even when valid).
function H.trade_catalog(other, pid)
  if Game.GetActivePlayer() ~= pid then return { ok = false, err = "this seat is not active" } end
  local o = Players[other]
  if not o or not o:IsAlive() then return { ok = false, err = "no such player" } end
  if o.IsMinorCiv and o:IsMinorCiv() then
    return { ok = false, err = "city-states are not trade-table deals; use city_state_gifts" }
  end
  local myTeam = Teams[Players[pid]:GetTeam()]
  if not myTeam:IsHasMet(o:GetTeam()) then return { ok = false, err = "have not met this player yet" } end
  if not UI or not UI.GetScratchDeal then return { ok = false, err = "scratch deal unavailable" } end
  local deal = UI.GetScratchDeal()
  if not deal then return { ok = false, err = "scratch deal unavailable" } end
  deal:SetFromPlayer(pid)
  deal:SetToPlayer(other)
  local duration = Game.GetDealDuration()
  local T = TradeableItems
  local function possible(from, to, typ, a, b)
    local ok, v = pcall(function()
      if b ~= nil then return deal:IsPossibleToTradeItem(from, to, typ, a, b) end
      if a ~= nil then return deal:IsPossibleToTradeItem(from, to, typ, a) end
      return deal:IsPossibleToTradeItem(from, to, typ)
    end)
    return ok and v and true or false
  end
  local function pair(typ, a, b)
    return {
      us = possible(pid, other, typ, a, b),
      them = possible(other, pid, typ, a, b),
    }
  end
  local resources = {}
  if GameInfo and GameInfo.Resources then
    for res in GameInfo.Resources() do
      if res and res.ID then
        local us = possible(pid, other, T.TRADE_ITEM_RESOURCES, res.ID, 1)
        local them = possible(other, pid, T.TRADE_ITEM_RESOURCES, res.ID, 1)
        if us or them then
          -- copies each side holds (the trade screen shows these numbers to a human), and a warning when
          -- the requested export is our only copy of a luxury: selling it costs the empire its happiness.
          -- The trade screen shows their count only for what they can trade us, and without imports
          -- (diplorelationships.lua:374-377 passes false); ours keeps imports for the last-copy check.
          local function avail(pl, withImports)
            local okc, v = pcall(function() return pl:GetNumResourceAvailable(res.ID, withImports) end)
            if okc and type(v) == "number" then return v end
            return nil
          end
          local entry = { resource = res.Type, us = us, them = them, class = res.ResourceClassType,
                          us_available = avail(Players[pid], true), them_available = them and avail(o, false) or nil }
          if us and res.ResourceClassType == "RESOURCECLASS_LUXURY" and entry.us_available == 1 then
            entry.last_copy = true
            entry.note = "our only copy: exporting it removes its happiness from the empire"
          end
          resources[#resources + 1] = entry
        end
      end
    end
  end
  -- Cities the deal would accept from each side: the exact IsPossibleToTradeItem(..., x, y) gate the
  -- trade screen's Pocket Cities list is built from. tradelogic's OnChooseCity -> deal:AddCityTrade is
  -- unconditional, so a city id that fails this gate must never reach it (v85).
  local function tradeable_cities(from, to)
    local out = {}
    local pl = Players[from]
    if pl and pl.Cities then
      for c in pl:Cities() do
        if c and possible(from, to, T.TRADE_ITEM_CITIES, c:GetX(), c:GetY()) then
          -- the trade screen lists the name; where the city is shows only once its plot is revealed to us
          local seen = c:Plot():IsRevealed(Players[pid]:GetTeam(), false)
          out[#out + 1] = { id = c:GetID(), name = c:GetName(), x = seen and c:GetX() or nil, y = seen and c:GetY() or nil }
        end
      end
    end
    return out
  end
  local function num(f)
    local okn, v = pcall(f)
    if okn and type(v) == "number" then return v end
    return nil
  end
  local gold = pair(T.TRADE_ITEM_GOLD, 1)
  gold.us_available = num(function() return deal:GetGoldAvailable(pid, -1) end)
  gold.them_available = num(function() return deal:GetGoldAvailable(other, -1) end)
  local gpt = pair(T.TRADE_ITEM_GOLD_PER_TURN, 1, duration)
  gpt.us_available = num(function() return Players[pid]:CalculateGoldRate() end)
  gpt.them_available = num(function() return o:CalculateGoldRate() end)
  return {
    ok = true, other = other, duration = duration,
    gold = gold,
    gold_per_turn = gpt,
    cities = { us = tradeable_cities(pid, other), them = tradeable_cities(other, pid) },
    open_borders = pair(T.TRADE_ITEM_OPEN_BORDERS, duration),
    embassy = pair(T.TRADE_ITEM_ALLOW_EMBASSY, duration),
    research_agreement = pair(T.TRADE_ITEM_RESEARCH_AGREEMENT, duration),
    defensive_pact = pair(T.TRADE_ITEM_DEFENSIVE_PACT, duration),
    at_war = myTeam:IsAtWar(o:GetTeam()) or false,
    resources = resources,
  }
end

-- BUTTONPOPUP_CITY_CAPTURED (popupsgeneric/puppetcitypopup.lua): Data1 city, Data2 gold, Data3 culture,
-- Data4 great works, Data5 player to liberate (-1 none), Option1 minor-civ buyout. Buttons: Liberate
-- (Network.SendLiberateMinor), Annex (TASK_ANNEX_PUPPET, hidden by MayNotAnnex), Puppet (TASK_CREATE_PUPPET),
-- Raze (TASK_RAZE behind CanRaze); tooltips carry the unhappiness delta and GetWarmongerPreviewString.
function H.city_capture_popup(pid)
  local info = H.popups[ButtonPopupTypes.BUTTONPOPUP_CITY_CAPTURED]
  if not info or info.player ~= pid then return nil end
  return info
end
function H.city_capture_options(pid)
  local info = H.city_capture_popup(pid)
  if not info then return { ok = false, err = "no captured-city choice is pending" } end
  local p = Players[pid]
  local c = p:GetCityByID(info.data1)
  if not c then return { ok = false, err = "captured city not found" } end
  local prev = c:GetPreviousOwner()
  local base = p:GetUnhappiness()
  local annex = p:GetUnhappinessForecast(c, nil) - base
  if info.option1 then annex = p:GetUnhappinessForecast(nil, c) - base end
  local puppet = p:GetUnhappinessForecast(nil, c) - base
  local war = (prev ~= -1 and info.option2) and p:GetWarmongerPreviewString(prev) or nil
  local out = { ok = true, city = { id = c:GetID(), name = c:GetName(), x = c:GetX(), y = c:GetY(), pop = c:GetPopulation() },
                gold = info.data2, culture = info.data3, great_works = info.data4,
                happiness_now = p:GetExcessHappiness(), options = {} }
  if info.data5 and info.data5 ~= -1 then
    out.options[#out.options + 1] = { choice = "liberate", to = Players[info.data5]:GetName(),
                                      effect = p:GetLiberationPreviewString(info.data5) }
  end
  if not p:MayNotAnnex() then
    out.options[#out.options + 1] = { choice = "annex", unhappiness = annex, warmonger = war }
  end
  out.options[#out.options + 1] = { choice = "puppet", unhappiness = puppet, warmonger = war }
  if p:CanRaze(c) then
    out.options[#out.options + 1] = { choice = "raze", unhappiness = annex, warmonger = war,
                                      note = "annexed while it burns down one population per turn" }
  end
  return out
end

function H.choose_city_capture(choice, pid)
  local st = H.city_capture_options(pid)
  if not st.ok then return st end
  local offered = false
  for _, o in ipairs(st.options) do if o.choice == choice then offered = true end end
  if not offered then return { ok = false, err = "not offered for this city", options = st.options } end
  local info = H.city_capture_popup(pid)
  local id = info.data1
  if choice == "liberate" then
    Network.SendLiberateMinor(info.data5, id)
  else
    local task = ({ annex = TaskTypes.TASK_ANNEX_PUPPET, puppet = TaskTypes.TASK_CREATE_PUPPET, raze = TaskTypes.TASK_RAZE })[choice]
    Network.SendDoTask(id, task, -1, -1, false, false, false, false)
  end
  return { ok = true, choice = choice, city = st.city }
end

-- What BNW's declare-war confirmation lists (declarewarpopup.lua GatherData): DoF / denouncements with the
-- rival, city-states allied to it (they join the war), majors protecting a targeted city-state, and the
-- trade routes between us that the war cancels. Running deals with the rival end too; the popup reads them
-- through the scratch deal, which this harness never touches headlessly, so they are not itemised here.
function H.war_consequences(other, pid)
  local p, o = Players[pid], Players[other]
  if not o or not o:IsAlive() then return { ok = false, err = "no such living player" } end
  local team = Teams[p:GetTeam()]
  if not team:IsHasMet(o:GetTeam()) then return { ok = false, err = "have not met this player yet" } end
  local out = { ok = true, target = o:GetName(), minor = o:IsMinorCiv(), at_war = team:IsAtWar(o:GetTeam()),
                can_declare_war = team:CanDeclareWar(o:GetTeam()) }
  if not o:IsMinorCiv() then
    out.declaration_of_friendship = p:IsDoF(other)
    if out.declaration_of_friendship then out.dof_turns_left = GameDefines.DOF_EXPIRATION_TIME - p:GetDoFCounter(other) end
    out.we_denounced_them = p:IsDenouncedPlayer(other)
    out.they_denounced_us = o:IsDenouncedPlayer(pid)
    out.allied_city_states = {}
    for i = GameDefines.MAX_MAJOR_CIVS, GameDefines.MAX_CIV_PLAYERS - 1 do
      local cs = Players[i]
      if cs and cs:IsAlive() and cs:GetAlly() == other then
        out.allied_city_states[#out.allied_city_states + 1] = { id = i, name = cs:GetName() }
      end
    end
  else
    out.protected_by = {}
    for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
      local m = Players[i]
      if i ~= pid and m and m:IsAlive() and m:IsProtectingMinor(other) then
        out.protected_by[#out.protected_by + 1] = { id = i, civ = m:GetCivilizationShortDescription() }
      end
    end
    out.we_protect_it = p:IsProtectingMinor(other)
  end
  out.trade_routes_lost = {}
  for _, v in ipairs(p:GetTradeRoutes()) do
    if v.ToID == other then
      out.trade_routes_lost[#out.trade_routes_lost + 1] = { ours = true, from = v.FromCityName, to = v.ToCityName }
    end
  end
  for _, v in ipairs(p:GetTradeRoutesToYou()) do
    if v.FromID == other then
      out.trade_routes_lost[#out.trade_routes_lost + 1] = { ours = false, from = v.FromCityName, to = v.ToCityName }
    end
  end
  out.note = "running deals with this player end as well (see their trade screen)"
  return out
end

-- The city-state screen's other buttons (citystatediplopopup.lua): pledge / revoke protection
-- (Game.DoMinorPledgeProtection behind CanMajorStartProtection / CanMajorWithdrawProtection), tribute
-- (Game.DoMinorBullyGold / DoMinorBullyUnit behind CanMajorBullyGold / CanMajorBullyUnit, tooltip from
-- GetMajorBully*Details), war (the screen's confirm ends in Network.SendChangeWar(team, true)) and peace
-- (Network.SendChangeWar(team, false), button hidden while IsPeaceBlocked).
-- citystatestatushelper.lua quest display order. Structured so kill-camp carries revealed x,y
-- (the CS tooltip never does; the plot hover does).
local CS_QUEST_ORDER = {
  "MINOR_CIV_QUEST_CONTEST_CULTURE", "MINOR_CIV_QUEST_CONTEST_FAITH", "MINOR_CIV_QUEST_CONTEST_TECHS",
  "MINOR_CIV_QUEST_INVEST", "MINOR_CIV_QUEST_KILL_CAMP", "MINOR_CIV_QUEST_GIVE_GOLD",
  "MINOR_CIV_QUEST_PLEDGE_TO_PROTECT", "MINOR_CIV_QUEST_DENOUNCE_MAJOR", "MINOR_CIV_QUEST_TRADE_ROUTE",
  "MINOR_CIV_QUEST_SPREAD_RELIGION", "MINOR_CIV_QUEST_BULLY_CITY_STATE", "MINOR_CIV_QUEST_FIND_NATURAL_WONDER",
  "MINOR_CIV_QUEST_FIND_PLAYER", "MINOR_CIV_QUEST_KILL_CITY_STATE", "MINOR_CIV_QUEST_GREAT_PERSON",
  "MINOR_CIV_QUEST_CONSTRUCT_WONDER", "MINOR_CIV_QUEST_CONNECT_RESOURCE", "MINOR_CIV_QUEST_ROUTE",
}

local function cs_quest_short(name)
  return name and name:gsub("^MINOR_CIV_QUEST_", "") or name
end

function H.city_state_quests(minor_id, pid)
  local o, p = Players[minor_id], Players[pid]
  if not o or not p then return {} end
  local team = Teams[p:GetTeam()]
  local out = {}
  local function add(row) out[#out + 1] = row end
  local function met_player(id)
    local other = Players[id]
    if not other then return nil end
    local ot = other.GetTeam and other:GetTeam()
    if ot == nil or not team:IsHasMet(ot) then return { met = false } end
    local name
    if other.IsMinorCiv and other:IsMinorCiv() then name = other.GetName and other:GetName()
    else name = other.GetCivilizationShortDescription and other:GetCivilizationShortDescription() end
    return { id = id, name = name, met = true, minor = other.IsMinorCiv and other:IsMinorCiv() or false }
  end
  if MinorCivQuestTypes and o.IsMinorCivDisplayedQuestForPlayer then
    for _, key in ipairs(CS_QUEST_ORDER) do
      local eType = MinorCivQuestTypes[key]
      if eType ~= nil then
        local ok, shown = pcall(function() return o:IsMinorCivDisplayedQuestForPlayer(pid, eType) end)
        if ok and shown then
          local row = { type = cs_quest_short(key) }
          local d1 = select(2, pcall(function() return o:GetQuestData1(pid, eType) end))
          local d2 = select(2, pcall(function() return o:GetQuestData2(pid, eType) end))
          local turns = select(2, pcall(function()
            return o:GetQuestTurnsRemaining(pid, eType, Game.GetGameTurn() - 1)
          end))
          if type(turns) == "number" and turns >= 0 then row.turns_left = turns end
          if key == "MINOR_CIV_QUEST_KILL_CAMP" then
            if type(d1) == "number" and type(d2) == "number" then
              local plot = Map.GetPlot(d1, d2)
              if plot and plot:IsRevealed(p:GetTeam(), false) then
                row.x, row.y = d1, d2
              end
            end
          elseif key == "MINOR_CIV_QUEST_CONNECT_RESOURCE" and type(d1) == "number" then
            local res = GameInfo.Resources and GameInfo.Resources[d1]
            if res then row.resource = res.Type end
          elseif key == "MINOR_CIV_QUEST_CONSTRUCT_WONDER" and type(d1) == "number" then
            local b = GameInfo.Buildings and GameInfo.Buildings[d1]
            if b then row.building = b.Type end
          elseif key == "MINOR_CIV_QUEST_GREAT_PERSON" and type(d1) == "number" then
            local u = GameInfo.Units and GameInfo.Units[d1]
            if u then row.unit = u.Type end
          elseif key == "MINOR_CIV_QUEST_SPREAD_RELIGION" and type(d1) == "number" then
            pcall(function()
              if Game.GetReligionName then row.religion = H.L(Game.GetReligionName(d1)) end
              if GameInfo.Religions and GameInfo.Religions[d1] then row.religion_type = GameInfo.Religions[d1].Type end
            end)
          elseif key == "MINOR_CIV_QUEST_FIND_PLAYER" or key == "MINOR_CIV_QUEST_KILL_CITY_STATE"
              or key == "MINOR_CIV_QUEST_GIVE_GOLD" or key == "MINOR_CIV_QUEST_PLEDGE_TO_PROTECT"
              or key == "MINOR_CIV_QUEST_DENOUNCE_MAJOR" or key == "MINOR_CIV_QUEST_BULLY_CITY_STATE" then
            -- CS screen names the target even when unmet (that's the quest). Coords stay omitted.
            if type(d1) == "number" then
              local t = met_player(d1)
              if t then
                row.target_met = t.met
                if t.met then row.target_id, row.target = t.id, t.name end
                if not t.met then
                  -- Tooltip still names them; use the same public short description the CS screen shows.
                  pcall(function()
                    local other = Players[d1]
                    if other and other.GetCivilizationShortDescriptionKey then
                      row.target = H.L(other:GetCivilizationShortDescriptionKey())
                    elseif other and other.GetName then
                      row.target = other:GetName()
                    end
                  end)
                end
              end
            end
          elseif key == "MINOR_CIV_QUEST_CONTEST_CULTURE" or key == "MINOR_CIV_QUEST_CONTEST_FAITH"
              or key == "MINOR_CIV_QUEST_CONTEST_TECHS" then
            pcall(function()
              row.our_score = o:GetMinorCivContestValueForPlayer(pid, eType)
              row.leader_score = o:GetMinorCivContestValueForLeader(eType)
              row.winning = o:IsMinorCivContestLeader(pid, eType) and true or false
            end)
          end
          add(row)
        end
      end
    end
  end
  pcall(function()
    if o:IsThreateningBarbariansEventActiveForPlayer(pid) then add({ type = "THREATENING_BARBARIANS" }) end
  end)
  pcall(function()
    if o:IsProxyWarActiveForMajor(pid) then add({ type = "PROXY_WAR" }) end
  end)
  return out
end

-- Plot-hover overlay: which met CS wants this camp killed (GetCivStateQuestString).
function H.kill_camp_quest_minors(x, y, pid)
  pid = pid or (Game.GetActivePlayer and Game.GetActivePlayer())
  if pid == nil or not Players[pid] then return nil end
  local eType = MinorCivQuestTypes and MinorCivQuestTypes.MINOR_CIV_QUEST_KILL_CAMP
  if eType == nil then return nil end
  local team = Teams[Players[pid]:GetTeam()]
  local out = {}
  local maxp = (GameDefines and GameDefines.MAX_CIV_PLAYERS) or 63
  local min_major = (GameDefines and GameDefines.MAX_MAJOR_CIVS) or 22
  for i = min_major, maxp - 1 do
    local o = Players[i]
    if o and o.IsMinorCiv and o:IsMinorCiv() and o:IsAlive() and team:IsHasMet(o:GetTeam()) then
      local ok, shown = pcall(function() return o:IsMinorCivDisplayedQuestForPlayer(pid, eType) end)
      if ok and shown then
        local d1 = select(2, pcall(function() return o:GetQuestData1(pid, eType) end))
        local d2 = select(2, pcall(function() return o:GetQuestData2(pid, eType) end))
        if d1 == x and d2 == y then
          out[#out + 1] = { id = i, name = o:GetName(), type = "KILL_CAMP" }
        end
      end
    end
  end
  return #out > 0 and out or nil
end

function H.city_state_actions(minor_id, pid)
  local o = Players[minor_id]
  if not o or not (o.IsMinorCiv and o:IsMinorCiv()) then return { ok = false, err = "not a city-state" } end
  local team = Teams[Players[pid]:GetTeam()]
  if not team:IsHasMet(o:GetTeam()) then return { ok = false, err = "have not met this player yet" } end
  if not o:IsAlive() then return { ok = false, err = "this city-state is gone" } end
  local at_war = team:IsAtWar(o:GetTeam())
  local out = { ok = true, name = o:GetName(), at_war = at_war,
                influence = o:GetMinorCivFriendshipWithMajor(pid),
                quest_list = H.city_state_quests(minor_id, pid) }
  if at_war then
    out.peace = { can = not o:IsPeaceBlocked(Players[pid]:GetTeam()),
                  why_not = o:IsPeaceBlocked(Players[pid]:GetTeam()) and "it refuses peace with a warmonger for now" or nil }
    return out
  end
  out.protecting = o:IsProtectedByMajor(pid)
  if out.protecting then
    out.revoke_pledge = { can = o:CanMajorWithdrawProtection(pid),
                          turns_committed = math.max(0, o:GetTurnLastPledgedProtectionByMajor(pid) + 10 - Game.GetGameTurn()) }
  else
    out.pledge = { can = o:CanMajorStartProtection(pid) }
  end
  out.bully_gold = { can = o:CanMajorBullyGold(pid), gold = o:GetMinorCivBullyGoldAmount(pid),
                     details = o:GetMajorBullyGoldDetails(pid) }
  out.bully_unit = { can = o:CanMajorBullyUnit(pid), unit = "UNIT_WORKER", details = o:GetMajorBullyUnitDetails(pid) }
  out.declare_war = { can = team:CanDeclareWar(o:GetTeam()) }
  pcall(function()
    local can = o:CanMajorGiftTileImprovement(pid)
    local cost
    pcall(function() cost = o:GetGiftTileImprovementCost(pid) end)
    out.gift_tile_improvement = { can = can and true or false, cost = cost }
  end)
  return out
end

function H.city_state_action(minor_id, action, pid)
  local st = H.city_state_actions(minor_id, pid)
  if not st.ok then return st end
  local o = Players[minor_id]
  local function refuse(why) return { ok = false, err = why, state = st } end
  if action == "pledge" then
    if not (st.pledge and st.pledge.can) then return refuse("cannot pledge protection now") end
    Game.DoMinorPledgeProtection(pid, minor_id, true)
  elseif action == "revoke_pledge" then
    if not (st.revoke_pledge and st.revoke_pledge.can) then return refuse("cannot withdraw protection now") end
    Game.DoMinorPledgeProtection(pid, minor_id, false)
  elseif action == "bully_gold" then
    if not (st.bully_gold and st.bully_gold.can) then return refuse("it would refuse the demand") end
    Game.DoMinorBullyGold(pid, minor_id)
  elseif action == "bully_unit" then
    if not (st.bully_unit and st.bully_unit.can) then return refuse("it would refuse the demand") end
    Game.DoMinorBullyUnit(pid, minor_id)
  elseif action == "declare_war" then
    if not (st.declare_war and st.declare_war.can) then return refuse("cannot declare war on it now") end
    Network.SendChangeWar(o:GetTeam(), true)
  elseif action == "make_peace" then
    if not (st.peace and st.peace.can) then return refuse("peace is not available") end
    Network.SendChangeWar(o:GetTeam(), false)
  else
    return { ok = false, err = "action is one of pledge, revoke_pledge, bully_gold, bully_unit, declare_war, make_peace" }
  end
  return { ok = true, action = action, before = st }
end

function H.city_state_bonuses(minor_id, pid)
  local o, p = Players[minor_id], Players[pid]
  if not o or not Teams[p:GetTeam()]:IsHasMet(o:GetTeam()) then return { ok = false, err = "have not met this player yet" } end
  if not o:IsMinorCiv() or not o:IsAlive() then return { ok = false, err = "not a living city-state" } end
  local trait = H.enum_name("minor_trait", MinorCivTraitTypes, o:GetMinorCivTrait())
  local personality = H.enum_name("minor_personality", MinorCivPersonalityTypes, o:GetPersonality())
  local trait_key = trait:gsub("MINOR_CIV_TRAIT_", "")
  local personality_key = personality:gsub("MINOR_CIV_PERSONALITY_", "")
  local out = { ok = true, id = minor_id, trait = trait_key, personality = personality_key,
    personality_text = H.L("TXT_KEY_CITY_STATE_PERSONALITY_" .. personality_key .. "_TT"),
    bonus_text = H.L("TXT_KEY_CITY_STATE_" .. trait_key .. "_TT"),
    current = { culture = o:GetMinorCivCurrentCultureBonus(pid), faith = o:GetMinorCivCurrentFaithBonus(pid),
      happiness = o:GetMinorCivCurrentHappinessBonus(pid), capital_food = o:GetCurrentCapitalFoodBonus(pid) / 100,
      other_city_food = o:GetCurrentOtherCityFoodBonus(pid) / 100,
      science = o:GetCurrentScienceFriendshipBonusTimes100(pid) / 100,
      unit_spawn_estimate = o:GetCurrentSpawnEstimate(pid) },
    exported_resources = {} }
  if trait_key == "MILITARISTIC" then
    out.bonus_text = H.L("TXT_KEY_CITY_STATE_MILITARISTIC_NO_UU_TT")
    if o:IsMinorCivHasUniqueUnit() then
      local u = GameInfo.Units[o:GetMinorCivUniqueUnit()]
      if u then
        out.unique_unit = { unit = u.Type, prerequisite = u.PrereqTech }
        local tech = GameInfo.Technologies[u.PrereqTech or "TECH_AGRICULTURE"]
        out.bonus_text = Locale.ConvertTextKey("TXT_KEY_CITY_STATE_MILITARISTIC_TT", u.Description, tech.Description)
      end
    end
  end
  for res in GameInfo.Resources() do
    local tech = res.TechReveal and GameInfo.Technologies[res.TechReveal]
    if (not tech or Teams[p:GetTeam()]:IsHasTech(tech.ID)) and res.ResourceClassType ~= "RESOURCECLASS_BONUS" then
      local n = o:GetResourceExport(res.ID)
      if n > 0 then out.exported_resources[#out.exported_resources + 1] = { resource = res.Type, amount = n, to_us = o:IsAllies(pid) } end
    end
  end
  return out
end

-- City-state "Gift Unit" button (citystatediplopopup.lua -> INTERFACEMODE_GIFT_UNIT).
-- Stock then confirms with Network.SendGiftUnit(minor, unitID). CanDistanceGift is the legality gate.
function H.gift_unit_options(minor_id, pid)
  local o, p = Players[minor_id], Players[pid]
  if not o or not Teams[p:GetTeam()]:IsHasMet(o:GetTeam()) then
    return { ok = false, err = "have not met this player yet" }
  end
  if not o:IsMinorCiv() or not o:IsAlive() then return { ok = false, err = "not a living city-state" } end
  if Teams[p:GetTeam()]:IsAtWar(o:GetTeam()) then return { ok = false, err = "at war with this city-state" } end
  local units = {}
  for u in p:Units() do
    local ok, can = pcall(function() return u:CanDistanceGift(minor_id) end)
    if ok and can then
      units[#units + 1] = {
        id = u:GetID(), type = short(info_type(GameInfo.Units, u:GetUnitType())),
        x = u:GetX(), y = u:GetY(),
      }
    end
  end
  return { ok = true, minor_id = minor_id, name = o:GetName(),
    influence = o:GetMinorCivFriendshipWithMajor(pid), units = units }
end

function H.gift_unit(minor_id, unit_id, pid)
  if Game.GetActivePlayer() ~= pid then return { ok = false, err = "this seat is not active" } end
  local opts = H.gift_unit_options(minor_id, pid)
  if not opts.ok then return opts end
  local found
  for _, u in ipairs(opts.units) do if u.id == unit_id then found = u end end
  if not found then
    return { ok = false, err = "that unit cannot be gifted to this city-state (move adjacent first)", options = opts }
  end
  Network.SendGiftUnit(minor_id, unit_id)
  return { ok = true, minor_id = minor_id, unit_id = unit_id, unit = found.type,
    influence_before = opts.influence }
end

function H.city_state_gifts(minor_id, pid)
  local o = Players[minor_id]
  if not o or not (o.IsMinorCiv and o:IsMinorCiv()) then
    return { ok = false, err = "not a city-state" }
  end
  local myTeam = Teams[Players[pid]:GetTeam()]
  if not myTeam:IsHasMet(o:GetTeam()) then return { ok = false, err = "have not met this player yet" } end
  local p = Players[pid]
  local small = GameDefines.MINOR_GOLD_GIFT_SMALL
  local med = GameDefines.MINOR_GOLD_GIFT_MEDIUM
  local large = GameDefines.MINOR_GOLD_GIFT_LARGE
  local gold = p:GetGold()
  local function tier(amount)
    local inf = o.GetFriendshipFromGoldGift and o:GetFriendshipFromGoldGift(pid, amount) or nil
    return { amount = amount, friendship = inf, affordable = gold >= amount }
  end
  return {
    ok = true, id = minor_id,
    gold = gold,
    friendship = o.GetMinorCivFriendshipWithMajor and o:GetMinorCivFriendshipWithMajor(pid) or nil,
    friends = o.IsFriends and o:IsFriends(pid) or false,
    allied = o.IsAllies and o:IsAllies(pid) or false,
    at_war = myTeam:IsAtWar(o:GetTeam()) or false,
    small = tier(small), medium = tier(med), large = tier(large),
    -- Human-visible only: citystatestatushelper.lua's GetAllyToolTip shows the current ally (by name only
    -- when met) and "N more Influence to become ally" -- nothing about other majors' influence. The old
    -- `rivals` list gave every met major's influence, which no screen shows (fixed t339).
    ally = (function()
      local iAlly = o.GetAlly and o:GetAlly() or -1
      local mine = o.GetMinorCivFriendshipWithMajor and o:GetMinorCivFriendshipWithMajor(pid) or 0
      if iAlly == nil or iAlly == -1 then
        return { none = true, to_become_ally = (GameDefines.FRIENDSHIP_THRESHOLD_ALLIES or 60) - mine }
      end
      if iAlly == pid then return { us = true } end
      local met = myTeam:IsHasMet(Players[iAlly]:GetTeam())
      return { player = met and iAlly or nil, civ = met and Players[iAlly]:GetCivilizationShortDescription() or nil,
               met = met, to_become_ally = o:GetMinorCivFriendshipWithMajor(iAlly) - mine + 1 }
    end)(),
  }
end

-- Stock UI: citystatediplopopup.lua OnSmallGold/OnMediumGold/OnBigGold —
-- Game.DoMinorGoldGift(minorId, amount) after a gold-on-hand check. Amount
-- must be one of the three MINOR_GOLD_GIFT_* tiers.
function H.minor_gold_gift(minor_id, amount, pid)
  if Game.GetActivePlayer() ~= pid then return { ok = false, err = "this seat is not active" } end
  local info = H.city_state_gifts(minor_id, pid)
  if not info.ok then return info end
  if info.at_war then return { ok = false, err = "at war with this city-state" } end
  local allowed = { [info.small.amount] = info.small, [info.medium.amount] = info.medium, [info.large.amount] = info.large }
  local t = allowed[amount]
  if not t then return { ok = false, err = "amount must be the small, medium, or large gift tier" } end
  if not t.affordable then return { ok = false, err = "not enough gold" } end
  Game.DoMinorGoldGift(minor_id, amount)
  return {
    ok = true, amount = amount,
    friendship = Players[minor_id].GetMinorCivFriendshipWithMajor and Players[minor_id]:GetMinorCivFriendshipWithMajor(pid) or nil,
    gold = Players[pid]:GetGold(),
  }
end

-- Trade routes: Game.SelectionListGameNetMessage with MISSION_ESTABLISH_TRADE_ROUTE / _PLUNDER_TRADE_ROUTE
-- (confirmed in ui/ingame/popups/chooseinternationaltraderoutepopup.lua, declarewarpopup.lua), same shape
-- as any other unit mission push. dest is a plot index (Map.GetPlot(x,y):GetPlotIndex()), trade_type is
-- the domain-specific trade type id from the available-routes list.
function H.establish_trade_route(unit_id, dest_x, dest_y, trade_type, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  if not u:IsTrade() then return {ok=false, err="unit is not a caravan or cargo ship"} end
  if u:MovesLeft() <= 0 then return {ok=false, err="unit has no moves left"} end
  local valid = false
  for _, route in ipairs(H.available_trade_routes(unit_id, pid)) do
    if route.x == dest_x and route.y == dest_y and route.trade_connection_type == trade_type then valid = true end
  end
  if not valid then return {ok=false, err="route is not currently available to this unit"} end
  local plot = Map.GetPlot(dest_x, dest_y)
  if not plot then return { ok = false, err = "no such plot" } end
  -- The caravan's model is torn down when the route starts, which the digest otherwise reads as a unit
  -- "spent" by my order (live t324). Remember who left for where so turn_digest can say so.
  local dest = plot:GetPlotCity()
  H.route_starts = H.route_starts or {}
  table.insert(H.route_starts, { unit_id = unit_id, unit = short(GameInfo.Units[u:GetUnitType()].Type),
                                 to = dest and dest:GetName() or nil, turn = Game.GetGameTurn() })
  while #H.route_starts > 20 do table.remove(H.route_starts, 1) end
  local m = info_id("MISSION_ESTABLISH_TRADE_ROUTE")
  if m == nil then m = MissionTypes and MissionTypes.MISSION_ESTABLISH_TRADE_ROUTE end
  if m == nil then return { ok = false, err = "unknown mission" } end
  return push_mission(u, m, plot:GetPlotIndex(), trade_type)
end

-- Active trade routes this player owns, as the Trade Route Overview shows them. Yields are x100 in the
-- engine table; reported here per turn. `turns_left` is when the unit comes home and needs a new order.
local function encode_trade_route(r, pid)
  local from_id, to_id = r.FromID, r.ToID
  local other = (from_id == pid) and to_id or from_id
  if other and other ~= pid then
    local o = Players[other]
    local team = Teams[Players[pid]:GetTeam()]
    if o and team and o.GetTeam and not team:IsHasMet(o:GetTeam()) then
      return nil
    end
  end
  return {
    from_city = r.FromCityName, to_city = r.ToCityName,
    from_player_id = from_id, to_player_id = to_id,
    domain = (r.Domain == 2) and "land" or "sea", turns_left = r.TurnsLeft,
    gold = (r.FromGPT or 0) / 100, science = (r.FromScience or 0) / 100,
    gold_them = (r.ToGPT or 0) / 100, science_them = (r.ToScience or 0) / 100,
    food_them = (r.ToFood or 0) / 100, production_them = (r.ToProduction or 0) / 100,
  }
end

function H.trade_routes(pid)
  local p = Players[pid]
  if not p.GetTradeRoutes then return { ok = false, err = "GetTradeRoutes unavailable" } end
  local outgoing, incoming = {}, {}
  for _, r in ipairs(p:GetTradeRoutes() or {}) do
    local e = encode_trade_route(r, pid)
    if e then outgoing[#outgoing + 1] = e end
  end
  -- Trade Route Overview tab "With You": other civs' caravans into our cities.
  pcall(function()
    if not p.GetTradeRoutesToYou then return end
    for _, r in ipairs(p:GetTradeRoutesToYou() or {}) do
      local e = encode_trade_route(r, pid)
      if e then incoming[#incoming + 1] = e end
    end
  end)
  return { ok = true, outgoing = outgoing, incoming = incoming }
end

function H.plunder_trade_route(unit_id, pid)
  return H.unit_mission(unit_id, "MISSION_PLUNDER_TRADE_ROUTE", -1, -1, nil, pid)
end

-- `Players[pid]:GetTradeRoutesAvailable()` (the old implementation here) is the WRONG API for this: it
-- returns entries with an `eDomain` (0/2) field, not the `TradeConnectionType` that
-- `MISSION_ESTABLISH_TRADE_ROUTE`'s data2 slot actually wants -- confirmed live, passing a Domain value
-- there gets an unconditional {ok=true} back but the unit never leaves the city (mission stays -1). The
-- real game UI (chooseinternationaltraderoutepopup.lua's RefreshData) gets its list, and the exact
-- TradeConnectionType it later passes back into the mission call, from the *per-unit*
-- `player:GetPotentialInternationalTradeRouteDestinations(unit)` instead. This mirrors that.
function H.available_trade_routes(unit_id, pid)
  local p = Players[pid]
  local u = p:GetUnitByID(unit_id)
  if not u or not u:IsTrade() or not p.GetPotentialInternationalTradeRouteDestinations then return {} end
  local out = {}
  for _, v in ipairs(p:GetPotentialInternationalTradeRouteDestinations(u)) do
    local plot = Map.GetPlot(v.X, v.Y)
    local city = plot and plot:GetPlotCity()
    local owner = city and city:GetOwner()
    -- Yields come back x100 (611 = 6.11/turn, what the trade-route chooser shows as +6). Report per
    -- turn for both ends: `gold`/`science`/`food`/`production` are what MY end receives, `*_them` what
    -- the destination gets (internal food/production routes deliver to the destination city, so for
    -- those the useful number is food_them/production_them).
    local mine, theirs = {}, {}
    for j, y in ipairs(v.Yields) do
      local yieldType = j - 1
      local key = ({ [YieldTypes.YIELD_GOLD] = "gold", [YieldTypes.YIELD_SCIENCE] = "science",
                     [YieldTypes.YIELD_FOOD] = "food", [YieldTypes.YIELD_PRODUCTION] = "production",
                     [YieldTypes.YIELD_CULTURE] = "culture", [YieldTypes.YIELD_FAITH] = "faith" })[yieldType]
      if key then mine[key] = (y.Mine or 0) / 100; theirs[key] = (y.Theirs or 0) / 100 end
    end
    local kind = ({ [0] = "international", [1] = "food", [2] = "production" })[v.TradeConnectionType] or tostring(v.TradeConnectionType)
    out[#out + 1] = {
      x = v.X, y = v.Y, trade_connection_type = v.TradeConnectionType, kind = kind,
      city_name = city and city:GetName() or nil,
      civ_name = owner and Players[owner]:GetCivilizationDescription() or nil,
      target_player_id = owner, gold = mine.gold or 0, science = mine.science or 0,
      food = mine.food or 0, production = mine.production or 0,
      gold_them = theirs.gold or 0, science_them = theirs.science or 0,
      food_them = theirs.food or 0, production_them = theirs.production or 0,
      prev_route = v.OldTradeRoute and true or false,
    }
  end
  return out
end

-- World Congress / League. ENDTURN_BLOCKING_LEAGUE_CALL_FOR_PROPOSALS is a HARD block, confirmed live
-- (2026-09-16, turn 213): unlike every other popup-shaped blocker in this file, merely opening+closing the
-- LeagueOverview popup (Events.SerialEventGameMessagePopup + OnClose(), the same trick that clears
-- TechPopup/discussion/greeting popups) does NOT clear it -- only a real Network.SendLeagueProposeEnact/
-- Repeal call does, the same shape as leagueoverview.lua's ProposalController:CommitProposals. Confirmed
-- `league:CanPropose(pid)`/`CanProposeEnactAnyChoice(type, pid)` already fold in the remaining-proposal-count
-- check (both flip to false once GetRemainingProposalsForMember hits 0), so no extra gating is needed here.
-- ENDTURN_BLOCKING_LEAGUE_CALL_FOR_VOTES is presumed to need the equivalent real
-- Network.SendLeagueVoteEnact/Repeal/Abstain call (VoteController:CommitVotes) by the same logic, but has
-- NOT been hit live yet -- the in_session/votable branch below is reasoned from leagueoverview.lua's source,
-- not independently live-verified.
function H.league_status(pid)
  if Game.GetNumActiveLeagues() == 0 then return { has_league = false } end
  local league = Game.GetActiveLeague()
  if not league then return { has_league = false } end
  local in_session = league:IsInSession()
  local out = {
    has_league = true, league_id = league:GetID(), name = league:GetName(), in_session = in_session,
    remaining_proposals = league:GetRemainingProposalsForMember(pid), can_propose = league:CanPropose(pid),
  }
  -- The League Overview's member column (leagueoverview.lua: CalculateStartingVotesForMember, or remaining +
  -- spent while in session; host first) and the Victory Progress screen's diplomatic line
  -- (Game.GetVotesNeededForDiploVictory, turns until the World Leader session once the UN is active).
  pcall(function()
    local host, members = league:GetHostMember(), {}
    local myTeam = Teams[Players[pid]:GetTeam()]
    for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
      local q = Players[i]
      if q and q:IsAlive() and not q:IsMinorCiv() and league:IsMember(i) then
        local votes = league:CalculateStartingVotesForMember(i)
        if in_session then votes = league:GetRemainingVotesForMember(i) + league:GetSpentVotesForMember(i) end
        local met = i == pid or myTeam:IsHasMet(q:GetTeam())
        members[#members + 1] = { player = met and i or nil, civ = met and q:GetCivilizationShortDescription() or "unknown",
                                  delegates = votes, host = (i == host) or nil, you = (i == pid) or nil }
      end
    end
    table.sort(members, function(a, b) return a.delegates > b.delegates end)
    out.members = members
    out.votes_needed_for_diplo_victory = Game.GetVotesNeededForDiploVictory()
    if Game.IsUnitedNationsActive() then
      local t = league:GetTurnsUntilVictorySession()
      if t and t < 999 then out.turns_until_world_leader_vote = t end  -- 999 (live t394) = none scheduled yet
    end
  end)
  if not in_session then
    out.turns_until_session = league:GetTurnsUntilSession()
    local enactable = {}
    for _, t in ipairs(league:GetInactiveResolutions()) do
      if league:CanProposeEnactAnyChoice(t.Type, pid) then
        local info = GameInfo.Resolutions[t.Type]
        local choices = nil
        if info.ProposerDecision ~= "RESOLUTION_DECISION_NONE" then
          choices = {}
          local decisionId = GameInfo.ResolutionDecisions[info.ProposerDecision].ID
          for _, cid in ipairs(league:GetChoicesForDecision(decisionId, pid)) do
            choices[#choices + 1] = { id = cid, text = league:GetTextForChoice(decisionId, cid),
              disabled = not league:CanProposeEnact(t.Type, pid, cid) }
          end
        end
        enactable[#enactable + 1] = { resolution_type = info.Type, name = league:GetResolutionName(t.Type, -1, -1, false), choices = choices }
      end
    end
    out.proposable_enact = enactable
    local repealable = {}
    for _, t in ipairs(league:GetActiveResolutions()) do
      if league:CanProposeRepeal(t.ID, pid) then
        repealable[#repealable + 1] = { resolution_id = t.ID, resolution_type = GameInfo.Resolutions[t.Type].Type,
          name = league:GetResolutionName(t.Type, t.ID, t.ProposerDecision or -1, false) }
      end
    end
    out.proposable_repeal = repealable
    -- What is already on the table for the next session (the League screen lists these; live t329 a
    -- successful proposal came back as a bare ok:true with nothing to read it back from).
    local pending = {}
    local ok = pcall(function()
      for _, v in ipairs(league:GetEnactProposals()) do
        pending[#pending + 1] = { direction = "enact", proposer = v.ProposalPlayer, resolution_type = GameInfo.Resolutions[v.Type].Type,
          name = league:GetResolutionName(v.Type, v.ID, v.ProposerDecision or -1, false) }
      end
      for _, v in ipairs(league:GetRepealProposals()) do
        pending[#pending + 1] = { direction = "repeal", proposer = v.ProposalPlayer, resolution_id = v.ID,
          resolution_type = GameInfo.Resolutions[v.Type].Type, name = league:GetResolutionName(v.Type, v.ID, v.ProposerDecision or -1, false) }
      end
    end)
    if ok then out.pending_proposals = pending end
  else
    out.remaining_votes = league:GetRemainingVotesForMember(pid)
    local votes = {}
    local addProposal = function(v, direction)
      local info = GameInfo.Resolutions[v.Type]
      local choices = nil
      if info.VoterDecision ~= "RESOLUTION_DECISION_YES_OR_NO" then
        choices = {}
        local decisionId = GameInfo.ResolutionDecisions[info.VoterDecision].ID
        for _, cid in ipairs(league:GetChoicesForDecision(decisionId, pid)) do
          choices[#choices + 1] = { id = cid, text = league:GetTextForChoice(decisionId, cid) }
        end
      end
      local row = { resolution_id = v.ID, resolution_type = info.Type, direction = direction,
        proposer = v.ProposalPlayer, name = league:GetResolutionName(v.Type, v.ID, v.ProposerDecision or -1, false),
        choices = choices, yes_no = choices == nil or nil }
      -- A luxury ban names its resource (the proposer's decision); say whether we own it, as the top bar
      -- would (live t448: "Ban Luxury: Wine" needed a raw query to learn we had none).
      if info.ProposerDecision == "RESOLUTION_DECISION_ANY_LUXURY_RESOURCE" and (v.ProposerDecision or -1) >= 0 then
        local res = GameInfo.Resources[v.ProposerDecision]
        if res then
          row.resource = res.Type
          row.us_have = Players[pid]:GetNumResourceTotal(res.ID, true)
        end
      end
      votes[#votes + 1] = row
    end
    for _, v in ipairs(league:GetEnactProposals()) do addProposal(v, "enact") end
    for _, v in ipairs(league:GetRepealProposals()) do addProposal(v, "repeal") end
    out.votable = votes
  end
  return out
end

function H.league_propose_enact(resolution_type, choice, pid)
  local id = GameInfoTypes[resolution_type]
  if id == nil then return { ok = false, err = "unknown resolution " .. tostring(resolution_type) } end
  local league = Game.GetActiveLeague()
  if not league then return { ok = false, err = "no active league" } end
  local info = GameInfo.Resolutions[id]
  local c = choice or -1
  if info.ProposerDecision ~= "RESOLUTION_DECISION_NONE" and c == -1 then
    return { ok = false, err = "this resolution requires a choice -- see league_status()'s choices list" }
  end
  if not league:CanProposeEnactAnyChoice(id, pid) then return { ok = false, err = "cannot propose this resolution right now" } end
  if c ~= -1 and not league:CanProposeEnact(id, pid, c) then return { ok = false, err = "cannot propose this specific choice" } end
  Network.SendLeagueProposeEnact(league:GetID(), id, pid, c)
  return { ok = true }
end

function H.league_propose_repeal(resolution_id, pid)
  local league = Game.GetActiveLeague()
  if not league then return { ok = false, err = "no active league" } end
  if not league:CanProposeRepeal(resolution_id, pid) then return { ok = false, err = "cannot propose repeal of this resolution" } end
  Network.SendLeagueProposeRepeal(league:GetID(), resolution_id, pid)
  return { ok = true }
end

-- votes: array of { resolution_id, direction = "enact"|"repeal", choice (optional, default kChoiceNone),
-- num_votes }. Any votes left over after these (GetRemainingVotesForMember - sum(num_votes)) are sent as an
-- explicit abstain, matching VoteController:CommitVotes's own always-abstain-the-remainder behaviour.
function H.league_cast_votes(votes, pid)
  local league = Game.GetActiveLeague()
  if not league then return { ok = false, err = "no active league" } end
  -- Network.SendLeagueVoteEnact/Repeal do NOT validate server-side that a session is actually in progress --
  -- confirmed live (2026-09-16): calling this out-of-session against a nonexistent resolution_id came back
  -- {ok:true, votes_cast:1} with no error and no visible effect, the same "accepted but silently wrong"
  -- shape as the MISSION_BUILD/trade-route bugs documented elsewhere in this file. Gate on IsInSession()
  -- ourselves rather than trusting the network call to reject it.
  if not league:IsInSession() then return { ok = false, err = "no World Congress session is in progress right now" } end
  local remaining = league:GetRemainingVotesForMember(pid)
  local spent = 0
  for _, v in ipairs(votes) do
    local n = v.num_votes or 0
    if n > 0 then
      local choice = v.choice or -1
      if v.direction == "enact" then
        Network.SendLeagueVoteEnact(league:GetID(), v.resolution_id, pid, n, choice)
      elseif v.direction == "repeal" then
        Network.SendLeagueVoteRepeal(league:GetID(), v.resolution_id, pid, n, choice)
      else
        return { ok = false, err = "direction must be 'enact' or 'repeal'" }
      end
      spent = spent + n
    end
  end
  local leftover = remaining - spent
  if leftover > 0 then Network.SendLeagueVoteAbstain(league:GetID(), pid, leftover) end
  return { ok = true, votes_cast = spent, abstained = leftover > 0 and leftover or 0 }
end

-- Espionage. Confirmed live (2026-09-16): spies do NOT use the unit-mission system at all (no
-- MissionTypes.MISSION_*SPY* constant exists in this build, as previously noted) -- they're a wholly
-- separate mechanism, `Player:GetEspionageSpies()`/`GetAvailableSpyRelocationCities(agentID)` to read, and
-- two dedicated `Network.Send*` calls to act, confirmed in `ui/ingame/popups/espionageoverview.lua`:
-- `Network.SendMoveSpy(playerID, agentID, targetPlayerID, targetCityID, bAsDiplomat)` assigns/relocates a
-- spy (recall home: targetPlayerID=-1, targetCityID=-1, bAsDiplomat=false -- `RelocateAgent`'s
-- UnassignButton), and `Network.SendStageCoup(playerID, agentID)` attempts a city-state coup once a spy has
-- established surveillance there and the city has an ally to overthrow (gated by
-- `Player:CanSpyStageCoup(agentID)`, same check the real UI's StageCoupButton disables on). `bAsDiplomat`
-- only matters when the target is another MAJOR civ's capital while not at war with them -- the real UI
-- offers a spy/diplomat choice there (`TXT_KEY_SPY_BE_DIPLOMAT`); every other target (a minor civ, or a
-- non-capital city) just passes `false` unconditionally.
-- Public Victory Progress and Global Relations reads. No unmet player rows or
-- city coordinates from unrevealed plots; wonder locations require current sight.
function H.domination_progress(pid)
  local team = Teams[Players[pid]:GetTeam()]
  local rows, by_id = {}, {}
  for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
    local p = Players[i]
    if p and (i == pid or team:IsHasMet(p:GetTeam())) and p:IsEverAlive() then
      local row = { original_player = i, civ = p:GetCivilizationShortDescription(), lost_capital = p:IsHasLostCapital(), owner = "unknown" }
      rows[#rows + 1], by_id[i] = row, row
    end
  end
  for i = 0, GameDefines.MAX_CIV_PLAYERS - 1 do
    local p = Players[i]
    if p and (i == pid or team:IsHasMet(p:GetTeam())) and p:IsAlive() then
      for c in p:Cities() do
        if c:IsOriginalMajorCapital() then
          local row = by_id[c:GetOriginalOwner()]
          if row then
            row.owner, row.owner_civ, row.city = i, p:GetCivilizationShortDescription(), c:GetName()
            row.controlled_by_us = p:GetTeam() == Players[pid]:GetTeam()
            local plot = c:Plot()
            row.revealed = plot:IsRevealed(Players[pid]:GetTeam(), false)
            if row.revealed then row.x, row.y = c:GetX(), c:GetY() end
          end
        end
      end
    end
  end
  return { ok = true, capitals = rows, scope = "met civilizations; unknown holders masked" }
end

function H.wonder_overview(pid)
  local team_id, rows = Players[pid]:GetTeam(), {}
  local team = Teams[team_id]
  for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
    local p = Players[i]
    if p and (i == pid or team:IsHasMet(p:GetTeam())) and p:IsAlive() then
      for b in GameInfo.Buildings() do
        local cls = GameInfo.BuildingClasses[b.BuildingClass]
        if cls.MaxGlobalInstances > 0 and p:CountNumBuildings(b.ID) > 0 then
          local row = { building = b.Type, name = H.L(b.Description), owner = i, civ = p:GetCivilizationShortDescription() }
          for c in p:Cities() do
            if c:Plot():IsVisible(team_id, false) and c:IsHasBuilding(b.ID) then
              row.city, row.x, row.y = c:GetName(), c:GetX(), c:GetY()
              local builder = c:GetBuildingOriginalOwner(b.ID)
              row.captured = builder >= 0 and builder ~= i
              if builder >= 0 and (builder == pid or team:IsHasMet(Players[builder]:GetTeam())) then row.builder = builder end
              break
            end
          end
          rows[#rows + 1] = row
        end
      end
    end
  end
  return { ok = true, wonders = rows, scope = "met owners; locations and capture history only in visible cities" }
end

function H.espionage_intrigue(pid)
  local p, rows = Players[pid], {}
  local team = Teams[p:GetTeam()]
  for _, v in ipairs(p:GetIntrigueMessages()) do
    local row = { turn = v.Turn, text = v.String, spy = v.SpyName }
    local other = Players[v.DiscoveringPlayer]
    if other and (v.DiscoveringPlayer == pid or team:IsHasMet(other:GetTeam())) then row.discoverer = v.DiscoveringPlayer end
    rows[#rows + 1] = row
  end
  table.sort(rows, function(a, b) return a.turn > b.turn end)
  return { ok = true, messages = rows }
end

-- demographics.lua shows only these aggregates, never a table of each rival's values.
-- Unmet rivals contribute to the public statistics; their identities remain masked.
function H.demographics(pid)
  local metrics = {
    population = function(p) return p:GetRealPopulation() end,
    food = function(p) return p:CalculateTotalYield(YieldTypes.YIELD_FOOD) end,
    production = function(p) return p:CalculateTotalYield(YieldTypes.YIELD_PRODUCTION) end,
    gold = function(p) return p:CalculateGrossGold() end,
    land = function(p) return p:GetNumPlots() * 10000 end,
    soldiers = function(p) return math.sqrt(p:GetMilitaryMight()) * 2000 end,
    approval = function(p) return math.max(0, math.min(100, 60 + p:GetExcessHappiness() * 3)) end,
    literacy = function(p)
      local techs = Teams[p:GetTeam()]:GetTeamTechs()
      if not techs:HasTech(GameInfoTypes.TECH_WRITING) then return 0 end
      local n = 0
      for tech in GameInfo.Technologies() do if techs:HasTech(tech.ID) then n = n + 1 end end
      return 100 * n / #GameInfo.Technologies
    end,
  }
  local team, rows = Teams[Players[pid]:GetTeam()], {}
  local function rounded(v) return math.floor(v + 0.5) end
  local function endpoint(value, id)
    local row = { value = rounded(value) }
    if id == pid or team:IsHasMet(Players[id]:GetTeam()) then row.player = id end
    return row
  end
  for name, get in pairs(metrics) do
    local mine = get(Players[pid])
    local best, worst, best_id, worst_id, total, count, rank = nil, nil, nil, nil, 0, 0, 1
    for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
      local p = Players[i]
      if p and p:IsAlive() and not p:IsMinorCiv() then
        local v = get(p)
        if best == nil or v > best then best, best_id = v, i end
        if worst == nil or v <= worst then worst, worst_id = v, i end
        if v > mine then rank = rank + 1 end
        total, count = total + v, count + 1
      end
    end
    if count > 0 then
      rows[name] = { value = rounded(mine), rank = rank, best = endpoint(best, best_id),
        average = rounded(total / count), worst = endpoint(worst, worst_id) }
    end
  end
  return { ok = true, metrics = rows }
end

function H.culture_works(pid)
  local p, cities, modifiers = Players[pid], {}, {}
  for c in p:Cities() do
    local row = { city_id = c:GetID(), name = c:GetName(), tourism = c:GetBaseTourism(),
      tourism_tooltip = c:GetTourismTooltip(), slots_tooltip = c:GetTotalSlotsTooltip(), buildings = {} }
    for b in GameInfo.Buildings() do
      if b.GreatWorkCount > 0 and c:IsHasBuilding(b.ID) then
        local cls, slots = GameInfo.BuildingClasses[b.BuildingClass].ID, {}
        for i = 0, b.GreatWorkCount - 1 do
          local work = c:GetBuildingGreatWork(cls, i)
          local slot = { slot = i }
          if work >= 0 then
            slot.work_id, slot.name, slot.tooltip = work, H.L(Game.GetGreatWorkName(work)), Game.GetGreatWorkTooltip(work, pid)
          end
          slots[#slots + 1] = slot
        end
        row.buildings[#row.buildings + 1] = { building = b.Type, slot_type = b.GreatWorkSlotType, slots = slots,
          theming_possible = c:IsThemingBonusPossible(cls), theming_bonus = c:GetThemingBonus(cls), theming_tooltip = c:GetThemingTooltip(cls) }
      end
    end
    cities[#cities + 1] = row
  end
  local team = Teams[p:GetTeam()]
  for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
    local o = Players[i]
    if i ~= pid and o and team:IsHasMet(o:GetTeam()) and o:IsAlive() then
      modifiers[#modifiers + 1] = { player = i, percent = p:GetTourismModifierWith(i), tooltip = p:GetTourismModifierWithTooltip(i) }
    end
  end
  return { ok = true, cities = cities, tourism_modifiers = modifiers }
end

function H.spies(pid)
  local p = Players[pid]
  if not p.GetEspionageSpies then return {} end
  local out = {}
  for _, v in ipairs(p:GetEspionageSpies()) do
    local plot = Map.GetPlot(v.CityX, v.CityY)
    local city = plot and plot:GetPlotCity()
    out[#out + 1] = {
      agent_id = v.AgentID, name = L(v.Name), rank = L(v.Rank), state = L(v.State),
      state_key = v.State,  -- the raw TXT_KEY_SPY_STATE_* for programmatic checks
      turns_left = v.TurnsLeft, percent_complete = v.PercentComplete,
      is_diplomat = v.IsDiplomat or false, established_surveillance = v.EstablishedSurveillance or false,
      city_name = city and city:GetName() or nil, city_owner = city and city:GetOwner() or nil,
      can_stage_coup = p.CanSpyStageCoup and p:CanSpyStageCoup(v.AgentID) or false,
    }
  end
  return out
end

-- Cities a given spy could be sent to right now (own cities for internal counter-intel, others' for
-- stealing tech / rigging elections). Pass `city_id`/`target_player_id` straight into `move_spy`.
-- `potential` is what espionageoverview.lua draws: BasePotential from GetEspionageCityStatus, where 0 means
-- "unknown" (TXT_KEY_EO_UNKNOWN_POTENTIAL_TT -- no surveillance there yet). The relocation list's own
-- Potential field is never displayed and read 99 for every city (live t348), so it is not used.
function H.available_spy_cities(agent_id, pid)
  local p = Players[pid]
  if not p.GetAvailableSpyRelocationCities then return {} end
  local status = {}
  pcall(function()
    for _, c in ipairs(p:GetEspionageCityStatus()) do status[c.PlayerID .. ":" .. c.CityID] = c end
  end)
  local out = {}
  for _, v in ipairs(p:GetAvailableSpyRelocationCities(agent_id)) do
    local st = status[v.PlayerID .. ":" .. v.CityID]
    local base = st and st.BasePotential or 0
    out[#out + 1] = { target_player_id = v.PlayerID, city_id = v.CityID, name = v.Name,
      potential = base > 0 and base or "unknown", population = v.Population, is_minor_civ = Players[v.PlayerID]:IsMinorCiv() }
  end
  return out
end

function H.move_spy(agent_id, target_player_id, target_city_id, as_diplomat, pid)
  Network.SendMoveSpy(pid, agent_id, target_player_id, target_city_id, as_diplomat or false)
  return { ok = true }
end

function H.stage_coup(agent_id, pid)
  local p = Players[pid]
  if not p:CanSpyStageCoup(agent_id) then return { ok = false, err = "cannot stage a coup with this spy right now" } end
  Network.SendStageCoup(pid, agent_id)
  return { ok = true }
end

-- Read-only catalogs of currently legal choices. Used by the MCP so callers do not have to guess
-- tech/build/mission names, and so illegal orders can be refused before they touch the engine.
function H.available_research(pid)
  local p = Players[pid]
  local current = p:GetCurrentResearch()
  local out = {}
  if not (GameInfo and GameInfo.Technologies) then return out end
  for tech in GameInfo.Technologies() do
    if tech and tech.ID and p:CanResearch(tech.ID) then
      local e = { tech = tech.Type, name = short(tech.Type),
                  turns = p:GetResearchTurnsLeft(tech.ID, true), cost = p:GetResearchCost(tech.ID) }
      if tech.Help then e.help = L(tech.Help) end
      if current == tech.ID then e.current = true end
      out[#out + 1] = e
    end
  end
  return out
end

-- Full tech tree (techtree.lua RefreshDisplayOfSpecificTech): have / current / available /
-- unavailable (prereqs missing) / locked (CanEverResearch false, omitted). Prereqs from
-- GameInfo.Technology_PrereqTechs. Embassy column: techs a met rival has that we do not,
-- only when we have an embassy in their capital (Team:HasEmbassyAtTeam).
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
      if current == id then
        e.status = "current"; e.current = true
        local okp, prog = pcall(function() return p:GetResearchProgress(id) end)
        if okp then e.progress = prog end
      elseif p:CanResearch(id) then
        e.status = "available"
      else
        e.status = "unavailable"
      end
      local okq, qpos = pcall(function() return p:GetQueuePosition(id) end)
      if okq and type(qpos) == "number" and qpos and qpos > 0 then e.queue = qpos end
      techs[#techs + 1] = e
    end
  end
  local current_name
  if type(current) == "number" and current >= 0 then
    current_name = short(info_type(GameInfo.Technologies, current))
  end
  local rivals = {}
  local max = (GameDefines and GameDefines.MAX_MAJOR_CIVS) or 8
  for i = 0, max - 1 do
    if i ~= pid and Players and Players[i] then
      local o = Players[i]
      if o.IsAlive and o:IsAlive() and not (o.IsMinorCiv and o:IsMinorCiv()) then
        local oTeam = Teams and Teams[o:GetTeam()] or nil
        local met = false
        if team and oTeam then pcall(function() met = team:IsHasMet(o:GetTeam()) end) end
        if met then
          local embassy = false
          if team and team.HasEmbassyAtTeam then
            pcall(function() embassy = team:HasEmbassyAtTeam(o:GetTeam()) end)
          end
          if embassy and oTeam then
            local ahead = {}
            for _, tech in ipairs(rows) do
              local theirs = false
              pcall(function() theirs = oTeam:IsHasTech(tech.ID) end)
              if theirs and not have_id[tech.ID] then
                ahead[#ahead + 1] = short(tech.Type)
              end
            end
            rivals[#rivals + 1] = {
              id = i,
              civ = o.GetCivilizationShortDescription and o:GetCivilizationShortDescription() or nil,
              ahead = ahead,
            }
          end
        end
      end
    end
  end
  return { ok = true, current = current_name, have = have, techs = techs, rivals = rivals }
end

function H.available_production(city_id, pid)
  local city = Players[pid]:GetCityByID(city_id)
  if not city then return { ok = false, err = "no such city" } end
  local items = {}
  local function add(item, kind, turns, gold, can_buy, help)
    local row = { item = item, kind = kind, turns = turns, gold = gold, can_buy = can_buy }
    if help and help ~= "" then row.help = help end
    items[#items + 1] = row
  end
  -- Gold rush-buy cost + purchasability per entry, so "can I just buy this?" needs no second call.
  -- Same matched getter/IsCanPurchase pairs as purchase_cost (a mismatched pair crashed the game once);
  -- projects/wonders are never purchasable in vanilla BNW and get no gold field.
  local gold_yield = YieldTypes and YieldTypes.YIELD_GOLD or 2
  local function unit_gold(id)
    local ok, cost = pcall(function() return city:GetUnitPurchaseCost(id) end)
    local ok2, can = pcall(function() return city:IsCanPurchase(true, true, id, -1, -1, gold_yield) end)
    if ok and cost == -1 then cost = nil end  -- -1 = cannot be bought at all (national wonders etc.)
    return (ok and cost or nil), (ok2 and can or false)
  end
  local function building_gold(id)
    local ok, cost = pcall(function() return city:GetBuildingPurchaseCost(id) end)
    local ok2, can = pcall(function() return city:IsCanPurchase(true, true, -1, id, -1, gold_yield) end)
    if ok and cost == -1 then cost = nil end
    return (ok and cost or nil), (ok2 and can or false)
  end
  if GameInfo and GameInfo.Units then
    for u in GameInfo.Units() do
      if u and u.ID and city:CanTrain(u.ID, 0) then
        local gold, can = unit_gold(u.ID)
        add(u.Type, "unit", city:GetUnitProductionTurnsLeft(u.ID), gold, can, u.Help and L(u.Help) or nil)
      end
    end
  end
  if GameInfo and GameInfo.Buildings then
    for b in GameInfo.Buildings() do
      if b and b.ID and city:CanConstruct(b.ID, 0) then
        local gold, can = building_gold(b.ID)
        add(b.Type, "building", city:GetBuildingProductionTurnsLeft(b.ID), gold, can, b.Help and L(b.Help) or nil)
      end
    end
  end
  -- Faith purchases (the city screen's faith tab): Missionaries/Inquisitors, Great People once the
  -- matching policy branch is finished, religious buildings from beliefs. Most are NOT trainable, so
  -- they are missing from the CanTrain loop above; every unit/building is asked instead. Same
  -- pcall-guarded matched pairs as gold. `faith_only` marks entries that exist only as a purchase.
  local faith_yield = YieldTypes and YieldTypes.YIELD_FAITH or 5
  local seen = {}
  for _, it in ipairs(items) do seen[it.item] = it end
  -- IsCanPurchase(bTestPurchaseCost, bTestTrainable, ...): with the cost test off the row still shows
  -- while we save up (live t292: a 400-faith Missionary was invisible at 267 faith); `faith_can_buy`
  -- is the affordable-now answer.
  local function faith_check(uid, bid)
    local ok2, can = pcall(function() return city:IsCanPurchase(false, true, uid, bid, -1, faith_yield) end)
    if not (ok2 and can) then return nil end
    local ok, cost = pcall(function()
      if uid >= 0 then return city:GetUnitFaithPurchaseCost(uid, true) end
      return city:GetBuildingFaithPurchaseCost(bid)
    end)
    if not (ok and cost and cost > 0) then return nil end
    local ok3, now = pcall(function() return city:IsCanPurchase(true, true, uid, bid, -1, faith_yield) end)
    return cost, (ok3 and now) and true or false
  end
  if GameInfo and GameInfo.Units and city.GetUnitFaithPurchaseCost then
    for u in GameInfo.Units() do
      if u and u.ID then
        local cost, now = faith_check(u.ID, -1)
        if cost then
          if seen[u.Type] then seen[u.Type].faith = cost; seen[u.Type].faith_can_buy = now
          else items[#items + 1] = { item = u.Type, kind = "unit", faith = cost, faith_can_buy = now, faith_only = true } end
        end
      end
    end
  end
  if GameInfo and GameInfo.Buildings and city.GetBuildingFaithPurchaseCost then
    for b in GameInfo.Buildings() do
      if b and b.ID then
        local cost, now = faith_check(-1, b.ID)
        if cost then
          if seen[b.Type] then seen[b.Type].faith = cost; seen[b.Type].faith_can_buy = now
          else items[#items + 1] = { item = b.Type, kind = "building", faith = cost, faith_can_buy = now, faith_only = true } end
        end
      end
    end
  end
  if GameInfo and GameInfo.Projects then
    for proj in GameInfo.Projects() do
      if proj and proj.ID and city:CanCreate(proj.ID, 0) then
        add(proj.Type, "project", city:GetProjectProductionTurnsLeft(proj.ID))
      end
    end
  end
  if GameInfo and GameInfo.Processes then
    for proc in GameInfo.Processes() do
      if proc and proc.ID and city:CanMaintain(proc.ID, 0) then
        add(proc.Type, "process", nil)
      end
    end
  end
  return { ok = true, items = items }
end

-- Interface-mode orders have MissionType=-1 in GameInfoActions. Read their mapping
-- from InterfaceModes, and use the same target predicates as the stock highlights.
function H.targeted_missions(u)
  local out = {}
  local function add(mode, enabled)
    local row = GameInfo.InterfaceModes[mode]
    if enabled and row and row.Mission then
      out[#out + 1] = { type = mode, kind = "interface", mission = row.Mission,
        target_tool = "unit_mission_targets" }
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

function H.unit_mission_targets(unit_id, mission, pid, offset, limit)
  local u = Players[pid]:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  local supported, mode = false, nil
  for _, row in ipairs(H.targeted_missions(u)) do
    if row.mission == mission then supported, mode = true, row.type end
  end
  if not supported then return { ok = false, err = "mission is not offered for this unit", missions = H.targeted_missions(u) } end
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

function H.available_unit_actions(unit_id, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  -- Do not UI.SelectUnit / CanHandleAction here: selecting a unit flips 2D/3D.
  -- Per-unit CanStartMission / CanBuild / CanDoCommand / CanAutomate are selection-free.
  local actions = {}
  local build_ids = {}   -- builds legal on the CURRENT plot (for the nearby scan below)
  local all_builds = {}  -- every BUILD_* action this unit class could ever do
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
        if kind == "interface" or a.Type:match("^CONTROL_") or a.Type == "COMMAND_HOTKEY" then
          -- skip: global UI, not a unit order
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
          if legal then
            actions[#actions + 1] = {
              type = a.Type, kind = kind,
              mission = (kind == "build" and "MISSION_BUILD") or (kind == "mission" and a.Type or nil),
              yield = H.great_person_yield(u, a.Type),
            }
          end
        end
      end
    end
  end
  if GameInfo and GameInfo.InterfaceModes and u.GetDomainType then
    for _, row in ipairs(H.targeted_missions(u)) do actions[#actions + 1] = row end
  end
  -- The promotion chooser as a human reads it: the name on the button and the effect text under
  -- it, not just the enum. "PROMOTION_DOGFIGHTING_1" next to "PROMOTION_INTERCEPTION_1" is not a
  -- choice anyone can make -- the panel says "+33% Combat Strength when intercepting" vs "+33%
  -- chance to intercept". Same shape as available_policies.adoptable / available_research help.
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
            if #builds > 0 then
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
              nearby[#nearby + 1] = e
            end
          end
        end
      end
    end
  end
  return {
    ok = true, actions = actions, promotions = promotions,
    x = u:GetX(), y = u:GetY(),
    moves = u:MovesLeft() / GameDefines.MOVE_DENOMINATOR,
    nearby_builds = nearby,
    attack_targets = H.melee_targets(u, pid),
    ranged_targets = H.ranged_targets(u, pid),
  }
end

-- What a great person's one-shot mission would give right now, as the unit panel's action tooltip
-- shows it (unitpanel.lua): science for a bulb, production for a hurry, gold + influence for a trade
-- mission, and so on. nil for every other action.
function H.great_person_yield(u, mission)
  local function get(fn, ...)
    if not u[fn] then return nil end
    local ok, v = pcall(u[fn], u, ...)
    if ok and type(v) == "number" then return v end
  end
  local plot = u.GetPlot and u:GetPlot() or nil
  if mission == "MISSION_DISCOVER" then return { science = get("GetDiscoverAmount") }
  elseif mission == "MISSION_HURRY" then return { production = get("GetHurryProduction", plot) }
  elseif mission == "MISSION_TRADE" then
    return { gold = get("GetTradeGold", plot), influence = get("GetTradeInfluence", plot) }
  elseif mission == "MISSION_GIVE_POLICIES" then return { culture = get("GetGivePoliciesCulture") }
  elseif mission == "MISSION_ONE_SHOT_TOURISM" then return { tourism = get("GetBlastTourism") }
  elseif mission == "MISSION_GOLDEN_AGE" then return { golden_age_turns = get("GetGoldenAgeTurns") }
  elseif mission == "MISSION_SPREAD_RELIGION" then return { spreads_left = get("GetSpreadsLeft") }
  end
end

-- The enemy a melee move onto (x, y) would fight, as a human sees it: the visible, non-invisible unit
-- on that plot that we are at war with (barbarians always). nil when there is nothing to attack.
function H.melee_defender(u, plot, pid)
  local team = Players[pid]:GetTeam()
  if not plot or not plot:IsVisible(team, false) then return nil end
  local best
  for i = 0, plot:GetNumUnits() - 1 do
    local d = plot:GetUnit(i)
    if d and d:GetOwner() ~= pid and not d:IsInvisible(team, false) then
      local dp = Players[d:GetOwner()]
      if dp and (dp:IsBarbarian() or Teams[team]:IsAtWar(dp:GetTeam())) then
        if not best or d:GetBaseCombatStrength() > best:GetBaseCombatStrength() then best = d end
      end
    end
  end
  return best
end

-- A visible unit on `plot` owned by a player we are at peace with. A move onto it cannot end there (no
-- stacking with foreign units) and the engine answers it with BUTTONPOPUP_DECLAREWARMOVE instead of a
-- path (live t55: a resumed Settler order onto the site an Inca Settler+Warrior had just reached).
function H.peaceful_occupant(plot, pid)
  local team = Players[pid]:GetTeam()
  if not plot or not plot:IsVisible(team, false) then return nil end
  for i = 0, plot:GetNumUnits() - 1 do
    local d = plot:GetUnit(i)
    if d and d:GetOwner() ~= pid and not d:IsInvisible(team, false) then
      local dp = Players[d:GetOwner()]
      if dp and not dp:IsBarbarian() and not Teams[team]:IsAtWar(dp:GetTeam()) then return d end
    end
  end
  return nil
end

local function peaceful_occupant_err(d)
  return "(" .. d:GetX() .. "," .. d:GetY() .. ") holds a " .. Locale.ConvertTextKey(GameInfo.Units[d:GetUnitType()].Description)
         .. " of " .. Players[d:GetOwner()]:GetCivilizationShortDescription()
         .. " (not at war): units cannot share its plot and the move would ask to declare war; pick an adjacent free plot"
end

-- Visible units at war with `pid` (barbarians included) within 3 plots of the own city whose name
-- appears in `text`; nil when no own city is named or nothing hostile is in sight.
function H.hostiles_near_named_city(text, pid)
  local p = pid and pid >= 0 and Players[pid]
  if not p or type(text) ~= "string" then return nil end
  local team = p:GetTeam()
  local function scan(c, r)
    local out = {}
    for dx = -r, r do for dy = -r, r do
      local q = Map.PlotXYWithRangeCheck(c:GetX(), c:GetY(), dx, dy, r)
      if q and q:IsVisible(team, false) then
        for i = 0, q:GetNumUnits() - 1 do
          local d = q:GetUnit(i)
          local dp = d and Players[d:GetOwner()]
          if dp and d:GetOwner() ~= pid and not d:IsInvisible(team, false)
             and (dp:IsBarbarian() or Teams[team]:IsAtWar(dp:GetTeam())) then
            local e = H.combat_side(d:GetOwner(), d:GetID(), pid) or {}
            e.x, e.y = q:GetX(), q:GetY()
            e.distance = Map.PlotDistance(c:GetX(), c:GetY(), e.x, e.y)
            out[#out + 1] = e
          end
        end
      end
    end end
    return out
  end
  for c in p:Cities() do
    if text:find(c:GetName(), 1, true) then
      -- The game raises this alert for units inside our borders, which reach past 3 plots (live t327: a
      -- barbarian horseman 4 plots from Nanjing, alert with no hostiles). Widen before giving up.
      local out = scan(c, 3)
      if #out == 0 then out = scan(c, 6) end
      if #out > 0 then return { city = c:GetName(), hostiles = out } end
      return { city = c:GetName(), hostiles = {}, note = "no hostile unit visible within 6 plots now; it may have moved into fog" }
    end
  end
  return nil
end

-- ---------------------------------------------------------------- combat modifier rows
-- EnemyUnitPanel.lua itemises, beside the damage numbers, every modifier that went into the two
-- combat strengths ("+25% Fortified", "-33% Empire Unhappy", "Flanking Bonus"...). Without that list
-- the harness saw the totals but never the reasons, so it could not tell a bad attack from a bad
-- position. Ported row for row -- same conditions, same text keys, same order, same side of the
-- panel -- from UpdateCombatOddsUnitVsUnit / UpdateCombatOddsUnitVsCity / UpdateCombatOddsCityVsUnit.
-- Every read here is one the panel already makes on a plot the human is hovering, so this adds no
-- information that the screen does not show (rule 2).
--
-- A failed or missing read drops its own row instead of the whole list: a modifier we cannot read is
-- reported as absent from the list, never as a zero we invented.
local function cm_num(obj, method, ...)
  if obj == nil then return nil end
  local f = obj[method]
  if f == nil then return nil end
  local ok, v = pcall(f, obj, ...)
  if ok and type(v) == "number" then return v end
  return nil
end

local function cm_flag(obj, method, ...)
  if obj == nil then return false end
  local f = obj[method]
  if f == nil then return false end
  local ok, v = pcall(f, obj, ...)
  return ok and v and true or false
end

local function cm_obj(obj, method, ...)
  if obj == nil then return nil end
  local f = obj[method]
  if f == nil then return nil end
  local ok, v = pcall(f, obj, ...)
  if ok then return v end
  return nil
end

local function cm_text(key, arg)
  if arg == nil then return L(key) end
  local ok, s = pcall(Locale.ConvertTextKey, key, arg)
  return ok and s or L(key)
end

-- A percentage row, exactly as the panel prints it. Skipped when the modifier is zero or unreadable,
-- which is what the panel does too (it only builds an entry inside `if (iModifier ~= 0)`).
local function cm_add(list, key, value, arg)
  if value == nil or value == 0 then return end
  list[#list + 1] = { text = cm_text(key, arg), value = value, percent = true, key = key }
end

-- A row the panel shows with a number but no percent sign (defensive fire support damage).
local function cm_add_flat(list, key, value, arg)
  if value == nil or value == 0 then return end
  list[#list + 1] = { text = cm_text(key, arg), value = value, percent = false, key = key }
end

-- A row the panel shows with an empty value box (the interception warnings, visible AA count,
-- capture chance): a note, not a strength modifier.
local function cm_note(list, key, arg)
  list[#list + 1] = { text = cm_text(key, arg), key = key }
end

local function cm_define(name) local ok, v = pcall(function() return GameDefines[name] end); return ok and v or nil end

local function cm_terrain_name(id)
  local ok, s = pcall(function() return Locale.ConvertTextKey(GameInfo.Terrains[id].Description) end)
  return ok and s or nil
end

local function cm_feature_name(id)
  local ok, s = pcall(function() return Locale.ConvertTextKey(GameInfo.Features[id].Description) end)
  return ok and s or nil
end

local function cm_unit_class_name(id)
  local ok, s = pcall(function() return Locale.ConvertTextKey(GameInfo.UnitClasses[id].Description) end)
  return ok and s or nil
end

local function cm_unit_combat_name(id)
  local ok, s = pcall(function() return Locale.ConvertTextKey(GameInfo.UnitCombatInfos[id].Description) end)
  return ok and s or nil
end

local function cm_hill_id()
  local ok, v = pcall(function() return GameInfo.Terrains["TERRAIN_HILL"].ID end)
  return ok and v or nil
end

-- Great General block: the same four rows (bonus, "ignores GG", stacked, reverse) appear on both
-- sides of every panel, so the panel's own order is kept here in one place.
local function cm_great_general(list, unit, player, with_reverse)
  if cm_flag(unit, "IsNearGreatGeneral") then
    local m = cm_num(player, "GetGreatGeneralCombatBonus")
    if m ~= nil then
      m = m + (cm_num(player, "GetTraitGreatGeneralExtraBonus") or 0)
      local land = cm_num(unit, "GetDomainType") == DomainTypes.DOMAIN_LAND
      cm_add(list, land and "TXT_KEY_EUPANEL_GG_NEAR" or "TXT_KEY_EUPANEL_GA_NEAR", m)
      if cm_flag(unit, "IsIgnoreGreatGeneralBenefit") then
        cm_add(list, "TXT_KEY_EUPANEL_IGG", -m)
      end
    end
  end
  if cm_flag(unit, "IsStackedGreatGeneral") then
    cm_add(list, "TXT_KEY_EUPANEL_GG_STACKED", cm_num(unit, "GetGreatGeneralCombatModifier"))
  end
  if with_reverse then
    cm_add(list, "TXT_KEY_EUPANEL_REVERSE_GG_NEAR", cm_num(unit, "GetReverseGreatGeneralModifier"))
  end
end

local function cm_unhappy(list, unit, player)
  local m = cm_num(unit, "GetUnhappinessCombatPenalty")
  if m == nil or m == 0 then return end
  cm_add(list, cm_flag(player, "IsEmpireVeryUnhappy") and "TXT_KEY_EUPANEL_EMPIRE_VERY_UNHAPPY_PENALTY"
    or "TXT_KEY_EUPANEL_EMPIRE_UNHAPPY_PENALTY", m)
end

local function cm_adjacent(list, unit)
  local m = cm_num(unit, "GetAdjacentModifier")
  if m == nil or m == 0 then return end
  if cm_flag(unit, "IsFriendlyUnitAdjacent", true) then
    cm_add(list, "TXT_KEY_EUPANEL_ADJACENT_FRIEND_UNIT_BONUS", m)
  end
end

local function cm_capital_defense(list, unit, player)
  local m = cm_num(unit, "CapitalDefenseModifier")
  if m == nil or m <= 0 then return end
  local cap = cm_obj(player, "GetCapitalCity")
  if cap == nil then return end
  local ok, dist = pcall(function()
    return Map.PlotDistance(cap:GetX(), cap:GetY(), unit:GetX(), unit:GetY())
  end)
  if not ok or type(dist) ~= "number" then return end
  m = m + dist * (cm_num(unit, "CapitalDefenseFalloff") or 0)
  if m > 0 then cm_add(list, "TXT_KEY_EUPANEL_CAPITAL_DEFENSE_BONUS", m) end
end

-- Feature beats terrain, and a hill under a featureless plot adds its own row -- the panel's exact
-- if/else, used for both the attacker's "attacking into" rows and the defender's terrain rows.
local function cm_terrain_rows(list, unit, plot, key, feature_method, terrain_method)
  local feature = cm_num(plot, "GetFeatureType")
  if feature ~= nil and feature ~= -1 then
    cm_add(list, key, cm_num(unit, feature_method, feature), cm_feature_name(feature))
    return
  end
  local terrain = cm_num(plot, "GetTerrainType")
  if terrain ~= nil then
    cm_add(list, key, cm_num(unit, terrain_method, terrain), cm_terrain_name(terrain))
  end
  if cm_flag(plot, "IsHills") then
    local hill = cm_hill_id()
    if hill ~= nil then cm_add(list, key, cm_num(unit, terrain_method, hill), cm_terrain_name(hill)) end
  end
end

-- The defender's own rows. Shared by unit-vs-unit and city-vs-unit, which differ only in the few
-- rows city-vs-unit leaves out (`full` = the unit-vs-unit panel's longer list).
local function cm_defender_rows(list, d, attacker, plot, ranged, full)
  local player = Players[d:GetOwner()]
  cm_unhappy(list, d, player)
  cm_add(list, "TXT_KEY_EUPANEL_STRATEGIC_RESOURCE", cm_num(d, "GetStrategicResourceCombatPenalty"))
  cm_adjacent(list, d)

  local terrain_mod = cm_num(plot, "DefenseModifier", cm_num(d, "GetTeam"), false, false)
  if terrain_mod ~= nil and terrain_mod ~= 0 then
    if terrain_mod < 0 or not cm_flag(d, "NoDefensiveBonus") then
      cm_add(list, "TXT_KEY_EUPANEL_TERRAIN_MODIFIER", terrain_mod)
    end
  end
  cm_add(list, "TXT_KEY_EUPANEL_FORTIFICATION_BONUS", cm_num(d, "FortifyModifier"))
  cm_great_general(list, d, player, full)
  if full then
    cm_add(list, "TXT_KEY_EUPANEL_IMPROVEMENT_NEAR", cm_num(d, "GetNearbyImprovementModifier"))
    -- The defender is flanked by MY units adjacent to it; the panel does not apply FlankAttackModifier here.
    if not ranged then
      local friends = cm_num(attacker, "GetNumEnemyUnitsAdjacent", d)
      if friends ~= nil and friends > 0 then
        cm_add(list, "TXT_KEY_EUPANEL_FLANKING_BONUS", friends * (cm_define("BONUS_PER_ADJACENT_FRIEND") or 0))
      end
    end
  end
  cm_add(list, "TXT_KEY_EUPANEL_EXTRA_PERCENT", cm_num(d, "GetExtraCombatPercent"))

  local home = cm_flag(plot, "IsFriendlyTerritory", d:GetOwner())
  if home then
    cm_add(list, "TXT_KEY_EUPANEL_FIGHT_AT_HOME_BONUS", cm_num(d, "GetFriendlyLandsModifier"))
    cm_add(list, "TXT_KEY_EUPANEL_FRIENDLY_CITY_BELIEF_BONUS",
      cm_num(player, "GetFoundedReligionFriendlyCityCombatMod", plot))
  else
    cm_add(list, "TXT_KEY_EUPANEL_OUTSIDE_HOME_BONUS", cm_num(d, "GetOutsideFriendlyLandsModifier"))
    cm_add(list, "TXT_KEY_EUPANEL_ENEMY_CITY_BELIEF_BONUS",
      cm_num(player, "GetFoundedReligionEnemyCityCombatMod", plot))
  end
  cm_add(list, "TXT_KEY_EUPANEL_DEFENSE_BONUS", cm_num(d, "GetDefenseModifier"))

  if full then
    local my_class = cm_num(attacker, "GetUnitClassType")
    if my_class ~= nil then
      cm_add(list, "TXT_KEY_EUPANEL_BONUS_VS_CLASS", cm_num(d, "UnitClassDefenseModifier", my_class),
        cm_unit_class_name(my_class))
    end
    local my_combat = cm_num(attacker, "GetUnitCombatType")
    if my_combat ~= nil and my_combat ~= -1 then
      cm_add(list, "TXT_KEY_EUPANEL_BONUS_VS_CLASS", cm_num(d, "UnitCombatModifier", my_combat),
        cm_unit_combat_name(my_combat))
    end
    cm_add(list, "TXT_KEY_EUPANEL_BONUS_VS_DOMAIN", cm_num(d, "DomainModifier", cm_num(attacker, "GetDomainType")))
  end

  if cm_flag(plot, "IsHills") then
    cm_add(list, "TXT_KEY_EUPANEL_HILL_DEFENSE_BONUS", cm_num(d, "HillsDefenseModifier"))
  end
  if cm_flag(plot, "IsOpenGround") then
    cm_add(list, "TXT_KEY_EUPANEL_OPEN_TERRAIN_DEF_BONUS", cm_num(d, "OpenDefenseModifier"))
  end
  if cm_flag(plot, "IsRoughGround") then
    cm_add(list, "TXT_KEY_EUPANEL_ROUGH_TERRAIN_DEF_BONUS", cm_num(d, "RoughDefenseModifier"))
  end

  if full then
    if cm_num(plot, "GetOwner") == d:GetOwner() then
      local m = cm_num(player, "GetCombatBonusVsHigherTech")
      if m ~= nil and m ~= 0 and cm_flag(attacker, "IsHigherTechThan", cm_num(d, "GetUnitType")) then
        cm_add(list, "TXT_KEY_EUPANEL_TRAIT_LOW_TECH_BONUS", m)
      end
    end
    local larger = cm_num(player, "GetCombatBonusVsLargerCiv")
    if larger ~= nil and larger ~= 0 and cm_flag(attacker, "IsLargerCivThan", d) then
      cm_add(list, "TXT_KEY_EUPANEL_TRAIT_SMALL_SIZE_BONUS", larger)
    end
  end
  cm_capital_defense(list, d, player)
  cm_terrain_rows(list, d, plot, "TXT_KEY_EUPANEL_BONUS_DEFENSE_TERRAIN",
    "FeatureDefenseModifier", "TerrainDefenseModifier")
end

local function cm_golden_age(list, player)
  local m = cm_num(player, "GetTraitGoldenAgeCombatModifier")
  if m ~= nil and m ~= 0 and cm_flag(player, "IsGoldenAge") then
    cm_add(list, "TXT_KEY_EUPANEL_BONUS_GOLDEN_AGE", m)
  end
end

-- The two rows the panel appends to the defender's column for an air strike, plus the capture chance
-- it appends to a melee attack. Values are blank on screen; they are notes here.
local function cm_air_and_capture(theirs, u, d, ranged, intercept_possible, visible_aa)
  if intercept_possible then
    cm_note(theirs, "TXT_KEY_EUPANEL_AIR_INTERCEPT_WARNING1")
    cm_note(theirs, "TXT_KEY_EUPANEL_AIR_INTERCEPT_WARNING2")
  end
  if visible_aa ~= nil and visible_aa > 0 then
    cm_note(theirs, "TXT_KEY_EUPANEL_VISIBLE_AA_UNITS", visible_aa)
  end
  if not ranged and d ~= nil then
    local chance = cm_num(u, "GetCaptureChance", d)
    if chance ~= nil and chance > 0 then cm_note(theirs, "TXT_KEY_EUPANEL_CAPTURE_CHANCE", chance) end
  end
end

-- UpdateCombatOddsUnitVsUnit's attacker column, in panel order.
local function cm_attacker_unit_rows(mine, u, d, to_plot, ranged, support)
  local player = Players[u:GetOwner()]
  local their_player = Players[d:GetOwner()]
  cm_add_flat(mine, "TXT_KEY_EUPANEL_SUPPORT_DMG", support)

  if not ranged then
    local from = cm_obj(u, "GetPlot")
    if not cm_flag(u, "IsRiverCrossingNoPenalty") and cm_flag(from, "IsRiverCrossingToPlot", to_plot) then
      cm_add(mine, "TXT_KEY_EUPANEL_ATTACK_OVER_RIVER", cm_define("RIVER_ATTACK_MODIFIER"))
    end
    if not cm_flag(u, "IsAmphib") and not cm_flag(to_plot, "IsWater") and cm_flag(from, "IsWater")
      and cm_num(u, "GetDomainType") == DomainTypes.DOMAIN_LAND then
      cm_add(mine, "TXT_KEY_EUPANEL_AMPHIBIOUS_ATTACK", cm_define("AMPHIB_ATTACK_MODIFIER"))
    end
  end

  cm_great_general(mine, u, player, true)
  cm_add(mine, "TXT_KEY_EUPANEL_IMPROVEMENT_NEAR", cm_num(u, "GetNearbyImprovementModifier"))

  local turns = cm_num(player, "GetAttackBonusTurns")
  if turns ~= nil and turns > 0 then
    cm_add(mine, "TXT_KEY_EUPANEL_POLICY_ATTACK_BONUS", cm_define("POLICY_ATTACK_BONUS_MOD"), turns)
  end

  if not ranged then
    local friends = cm_num(d, "GetNumEnemyUnitsAdjacent", u)
    if friends ~= nil and friends > 0 then
      local m = friends * (cm_define("BONUS_PER_ADJACENT_FRIEND") or 0)
      local flank = cm_num(u, "FlankAttackModifier")
      if flank ~= nil and flank ~= 0 then m = m * (100 + flank) / 100 end
      cm_add(mine, "TXT_KEY_EUPANEL_FLANKING_BONUS", m)
    end
  end
  cm_add(mine, "TXT_KEY_EUPANEL_EXTRA_PERCENT", cm_num(u, "GetExtraCombatPercent"))

  -- The stock panel tests `pToPlot:IsFriendlyTerritory(c)` with an undefined `c` here (a typo for the
  -- attacker's player id, which it passes correctly two rows further down). The evident intent is used.
  if cm_flag(to_plot, "IsFriendlyTerritory", u:GetOwner()) then
    cm_add(mine, "TXT_KEY_EUPANEL_FIGHT_AT_HOME_BONUS", cm_num(u, "GetFriendlyLandsModifier"))
    cm_add(mine, "TXT_KEY_EUPANEL_ATTACK_IN_FRIEND_LANDS", cm_num(u, "GetFriendlyLandsAttackModifier"))
    cm_add(mine, "TXT_KEY_EUPANEL_FRIENDLY_CITY_BELIEF_BONUS",
      cm_num(player, "GetFoundedReligionFriendlyCityCombatMod", to_plot))
  end

  if cm_num(to_plot, "GetOwner") == u:GetOwner() then
    local m = cm_num(player, "GetCombatBonusVsHigherTech")
    if m ~= nil and m ~= 0 and cm_flag(d, "IsHigherTechThan", cm_num(u, "GetUnitType")) then
      cm_add(mine, "TXT_KEY_EUPANEL_TRAIT_LOW_TECH_BONUS", m)
    end
  end
  local larger = cm_num(player, "GetCombatBonusVsLargerCiv")
  if larger ~= nil and larger ~= 0 and cm_flag(d, "IsLargerCivThan", u) then
    cm_add(mine, "TXT_KEY_EUPANEL_TRAIT_SMALL_SIZE_BONUS", larger)
  end
  cm_capital_defense(mine, u, player)

  if not cm_flag(to_plot, "IsFriendlyTerritory", u:GetOwner()) then
    cm_add(mine, "TXT_KEY_EUPANEL_OUTSIDE_HOME_BONUS", cm_num(u, "GetOutsideFriendlyLandsModifier"))
    cm_add(mine, "TXT_KEY_EUPANEL_ENEMY_CITY_BELIEF_BONUS",
      cm_num(player, "GetFoundedReligionEnemyCityCombatMod", to_plot))
  end

  cm_unhappy(mine, u, player)
  cm_add(mine, "TXT_KEY_EUPANEL_STRATEGIC_RESOURCE", cm_num(u, "GetStrategicResourceCombatPenalty"))
  cm_adjacent(mine, u)
  cm_add(mine, "TXT_KEY_EUPANEL_ATTACK_MOD_BONUS", cm_num(u, "GetAttackModifier"))

  local their_class = cm_num(d, "GetUnitClassType")
  if their_class ~= nil then
    local name = cm_unit_class_name(their_class)
    cm_add(mine, "TXT_KEY_EUPANEL_BONUS_VS_CLASS", cm_num(u, "GetUnitClassModifier", their_class), name)
    cm_add(mine, "TXT_KEY_EUPANEL_BONUS_VS_CLASS", cm_num(u, "UnitClassAttackModifier", their_class), name)
  end
  local their_combat = cm_num(d, "GetUnitCombatType")
  if their_combat ~= nil and their_combat ~= -1 then
    cm_add(mine, "TXT_KEY_EUPANEL_BONUS_VS_CLASS", cm_num(u, "UnitCombatModifier", their_combat),
      cm_unit_combat_name(their_combat))
  end
  cm_add(mine, "TXT_KEY_EUPANEL_BONUS_VS_DOMAIN", cm_num(u, "DomainModifier", cm_num(d, "GetDomainType")))

  local fortified = cm_num(d, "GetFortifyTurns")
  if fortified ~= nil and fortified > 0 then
    cm_add(mine, "TXT_KEY_EUPANEL_BONUS_VS_FORT_UNITS", cm_num(u, "AttackFortifiedModifier"))
  end
  local wounded = cm_num(d, "GetDamage")
  if wounded ~= nil and wounded > 0 then
    cm_add(mine, "TXT_KEY_EUPANEL_BONUS_VS_WOUND_UNITS", cm_num(u, "AttackWoundedModifier"))
  end

  if cm_flag(to_plot, "IsHills") then
    cm_add(mine, "TXT_KEY_EUPANEL_HILL_ATTACK_BONUS", cm_num(u, "HillsAttackModifier"))
  end
  if cm_flag(to_plot, "IsOpenGround") then
    cm_add(mine, "TXT_KEY_EUPANEL_OPEN_TERRAIN_BONUS", cm_num(u, "OpenAttackModifier"))
    cm_add(mine, "TXT_KEY_EUPANEL_OPEN_TERRAIN_RANGE_BONUS", cm_num(u, "OpenRangedAttackModifier"))
  end
  if ranged then
    cm_add(mine, "TXT_KEY_EUPANEL_RANGED_ATTACK_MODIFIER", cm_num(u, "GetRangedAttackModifier"))
  end
  if cm_flag(to_plot, "IsRoughGround") then
    cm_add(mine, "TXT_KEY_EUPANEL_ROUGH_TERRAIN_BONUS", cm_num(u, "RoughAttackModifier"))
    cm_add(mine, "TXT_KEY_EUPANEL_ROUGH_TERRAIN_RANGED_BONUS", cm_num(u, "RoughRangedAttackModifier"))
  end
  cm_terrain_rows(mine, u, to_plot, "TXT_KEY_EUPANEL_ATTACK_INTO_BONUS",
    "FeatureAttackModifier", "TerrainAttackModifier")

  if cm_flag(d, "IsBarbarian") then
    local ok, handicap = pcall(function()
      return GameInfo.HandicapInfos[Game:GetHandicapType()].BarbarianBonus
    end)
    if ok and type(handicap) == "number" then
      cm_add(mine, "TXT_KEY_EUPANEL_VS_BARBARIANS_BONUS",
        handicap + (cm_num(player, "GetBarbarianCombatBonus") or 0))
    end
  end
  cm_golden_age(mine, player)
  local cs = cm_num(player, "GetTraitCityStateCombatModifier")
  if cs ~= nil and cs ~= 0 and cm_flag(their_player, "IsMinorCiv") then
    cm_add(mine, "TXT_KEY_EUPANEL_BONUS_CITY_STATE", cs)
  end
end

-- UpdateCombatOddsUnitVsCity's attacker column. A city target has no itemised defender column.
local function cm_attacker_city_rows(mine, u, c, to_plot, ranged, support)
  local player = Players[u:GetOwner()]
  local their_player = Players[c:GetOwner()]
  cm_add_flat(mine, "TXT_KEY_EUPANEL_SUPPORT_DMG", support)

  local city_attack = cm_num(u, "CityAttackModifier")
  if city_attack ~= nil and city_attack ~= 0 then
    cm_add(mine, city_attack >= 0 and "TXT_KEY_EUPANEL_ATTACK_CITIES"
      or "TXT_KEY_EUPANEL_ATTACK_CITIES_PENALTY", city_attack)
  end
  cm_add(mine, "TXT_KEY_EUPANEL_ENEMY_CITY_BELIEF_BONUS",
    cm_num(player, "GetFoundedReligionEnemyCityCombatMod", to_plot))
  if cm_flag(u, "IsNearSapper", c) then
    cm_add(mine, "TXT_KEY_EUPANEL_CITY_SAPPED", cm_define("SAPPED_CITY_ATTACK_MODIFIER"))
  end
  cm_golden_age(mine, player)
  local cs = cm_num(player, "GetTraitCityStateCombatModifier")
  if cs ~= nil and cs ~= 0 and cm_flag(their_player, "IsMinorCiv") then
    cm_add(mine, "TXT_KEY_EUPANEL_BONUS_CITY_STATE", cs)
  end

  if not ranged then
    local from = cm_obj(u, "GetPlot")
    if not cm_flag(u, "IsRiverCrossingNoPenalty") and cm_flag(from, "IsRiverCrossingToPlot", to_plot) then
      cm_add(mine, "TXT_KEY_EUPANEL_ATTACK_OVER_RIVER", cm_define("RIVER_ATTACK_MODIFIER"))
    end
    if not cm_flag(u, "IsAmphib") and not cm_flag(to_plot, "IsWater") and cm_flag(from, "IsWater")
      and cm_num(u, "GetDomainType") == DomainTypes.DOMAIN_LAND then
      cm_add(mine, "TXT_KEY_EUPANEL_AMPHIBIOUS_ATTACK", cm_define("AMPHIB_ATTACK_MODIFIER"))
    end
  else
    cm_add(mine, "TXT_KEY_EUPANEL_RANGED_ATTACK_MODIFIER", cm_num(u, "GetRangedAttackModifier"))
  end

  cm_great_general(mine, u, player, true)
  cm_add(mine, "TXT_KEY_EUPANEL_IMPROVEMENT_NEAR", cm_num(u, "GetNearbyImprovementModifier"))
  cm_unhappy(mine, u, player)
  cm_add(mine, "TXT_KEY_EUPANEL_STRATEGIC_RESOURCE", cm_num(u, "GetStrategicResourceCombatPenalty"))
  cm_adjacent(mine, u)
  local turns = cm_num(player, "GetAttackBonusTurns")
  if turns ~= nil and turns > 0 then
    cm_add(mine, "TXT_KEY_EUPANEL_POLICY_ATTACK_BONUS", cm_define("POLICY_ATTACK_BONUS_MOD"), turns)
  end
end

-- The panel's modifier columns for one of my units attacking `d` (a unit) or `c` (a city).
-- `support` is the defensive fire-support damage already computed for the melee estimate.
function H.combat_modifiers(u, d, c, ranged, support, intercept_possible, visible_aa)
  local out = { mine = {}, theirs = {} }
  pcall(function()
    if c ~= nil then
      local plot = c:Plot()
      cm_attacker_city_rows(out.mine, u, c, plot, ranged, support)
    else
      local plot = d:GetPlot()
      cm_attacker_unit_rows(out.mine, u, d, plot, ranged, support)
      if cm_flag(d, "IsCombatUnit") then
        cm_defender_rows(out.theirs, d, u, plot, ranged, true)
        cm_golden_age(out.theirs, Players[d:GetOwner()])
      end
    end
  end)
  pcall(function() cm_air_and_capture(out.theirs, u, c == nil and d or nil, ranged, intercept_possible, visible_aa) end)
  return out
end

-- UpdateCombatOddsCityVsUnit: one of my cities range-striking a visible unit. The city's own rows are
-- the three strike modifiers the panel shows; the unit's rows are the shorter defender list.
function H.city_strike_modifiers(city, d)
  local out = { mine = {}, theirs = {} }
  pcall(function()
    if not cm_flag(d, "IsCombatUnit") then return end
    local my_player = Players[city:GetOwner()]
    local their_player = Players[d:GetOwner()]
    local plot = d:GetPlot()
    cm_defender_rows(out.theirs, d, nil, plot, true, false)
    if cm_flag(d, "IsBarbarian") then
      local ok, handicap = pcall(function()
        return GameInfo.HandicapInfos[Game:GetHandicapType()].BarbarianBonus
      end)
      if ok and type(handicap) == "number" then
        cm_add(out.mine, "TXT_KEY_EUPANEL_VS_BARBARIANS_BONUS",
          handicap + (cm_num(my_player, "GetBarbarianCombatBonus") or 0))
      end
    end
    if cm_obj(city, "GetGarrisonedUnit") ~= nil then
      cm_add(out.mine, "TXT_KEY_EUPANEL_GARRISONED_CITY_RANGE_BONUS",
        cm_num(my_player, "GetGarrisonedCityRangeStrikeModifier"))
    end
    cm_add(out.mine, "TXT_KEY_EUPANEL_BONUS_RELIGIOUS_BELIEF",
      cm_num(city, "GetReligionCityRangeStrikeModifier"))
    if cm_flag(d, "IsNearSapper", city) then
      cm_add(out.theirs, "TXT_KEY_EUPANEL_CITY_SAPPED", cm_define("SAPPED_CITY_ATTACK_MODIFIER"))
    end
    cm_golden_age(out.theirs, their_player)
  end)
  return out
end

-- The pre-commit numbers the game shows when a human hovers a melee attack (EnemyUnitPanel.lua's
-- formula, bIncludeRand=false: the expected damage, the real roll varies around it). Live-audited
-- 2026-09-18: the human at the screen sees this before committing; the harness showed no attack at all.
local function melee_fire_support_damage(u, owner, plot)
  local support = u:GetFireSupportUnit(owner, plot:GetX(), plot:GetY())
  -- The stock panel exposes this aggregate even without identifying the supporting unit.
  -- Return only its displayed damage; never expose the unit's identity or location.
  if support then return support:GetRangeCombatDamage(u, nil, false) end
  return 0
end

function H.melee_preview(u, d)
  local out = {}
  local support = 0
  pcall(function()
    local plot = d:GetPlot()
    local mine = u:GetMaxAttackStrength(u:GetPlot(), plot, d)
    local theirs = d:GetMaxDefenseStrength(plot, u)
    out.my_strength, out.their_strength = mine / 100, theirs / 100
    support = melee_fire_support_damage(u, d:GetOwner(), plot)
    out.fire_support_damage = support
    out.expected_damage_dealt = math.min(GameDefines.MAX_HIT_POINTS,
      u:GetCombatDamage(mine, theirs, u:GetDamage() + support, false, false, false))
    out.expected_damage_taken = math.min(GameDefines.MAX_HIT_POINTS,
      d:GetCombatDamage(theirs, mine, d:GetDamage(), false, false, false) + support)
  end)
  out.modifiers = H.combat_modifiers(u, d, nil, false, support)
  return out
end

-- The enemy city a melee move onto `plot` would assault: visible, owned by a team we are at war with.
function H.enemy_city_at(plot, pid)
  local team = Players[pid]:GetTeam()
  if not plot or not plot:IsVisible(team, false) then return nil end
  local c = plot:GetPlotCity()
  if c and c:GetOwner() ~= pid and Teams[team]:IsAtWar(Players[c:GetOwner()]:GetTeam()) then return c end
  return nil
end

-- enemyunitpanel.lua UpdateCombatOddsUnitVsCity, melee branch (city strength is already x100).
function H.melee_city_preview(u, c)
  local out = {}
  local support = 0
  pcall(function()
    local plot = c:Plot()
    local mine = u:GetMaxAttackStrength(u:GetPlot(), plot, nil)
    local theirs = c:GetStrengthValue()
    out.my_strength, out.their_strength = mine / 100, theirs / 100
    support = melee_fire_support_damage(u, c:GetOwner(), plot)
    out.fire_support_damage = support
    out.expected_damage_dealt = math.min(c:GetMaxHitPoints(),
      u:GetCombatDamage(mine, theirs, u:GetDamage() + support, false, false, true))
    out.expected_damage_taken = math.min(GameDefines.MAX_HIT_POINTS,
      u:GetCombatDamage(theirs, mine, c:GetDamage(), false, true, false) + support)
  end)
  out.modifiers = H.combat_modifiers(u, nil, c, false, support)
  return out
end

-- EnemyUnitPanel's ranged branch, including air retaliation and its visible-only AA count.
-- Interception damage is NOT in the estimate; the stock panel always warns for an air strike,
-- even when no interceptors are visible. Never turn a failed retaliation read into zero damage.
function H.ranged_preview(u, t, c)
  local out = {}
  pcall(function()
    out.expected_damage_dealt = u:GetRangeCombatDamage(t, c, false)
    if u:GetDomainType() == DomainTypes.DOMAIN_AIR then
      out.interception_possible = true
      out.interception_warning = "Air strikes may be intercepted; expected_damage_taken excludes interception."
      out.expected_damage_taken = (c or t):GetAirStrikeDefenseDamage(u, false)
    else
      out.expected_damage_taken = 0
    end
  end)
  pcall(function()
    local mine = u:GetMaxRangedCombatStrength(t, c, true, true)
    local theirs
    if c then
      theirs = c:GetStrengthValue()
    else
      if t:IsEmbarked() then theirs = t:GetEmbarkedUnitDefense()
      else theirs = t:GetMaxRangedCombatStrength(u, nil, false, true) end
      if theirs == 0 or t:GetDomainType() == DomainTypes.DOMAIN_SEA or t:IsRangedSupportFire() then
        theirs = t:GetMaxDefenseStrength(t:GetPlot(), u, true)
      end
    end
    out.my_strength, out.their_strength = mine / 100, theirs / 100
  end)
  if out.interception_possible then
    pcall(function()
      out.visible_interceptors = u:GetInterceptorCount(c and c:Plot() or t:GetPlot(), t, true, true)
    end)
  end
  out.modifiers = H.combat_modifiers(u, t, c, true, 0, out.interception_possible, out.visible_interceptors)
  return out
end

-- Share the same visible, hostile target and preview between ranged actions and airstrike targets.
-- City strength includes the garrison: never preview its unit instead of the city.
function H.ranged_target_info(u, plot, pid)
  local team = Players[pid]:GetTeam()
  if not plot:IsVisible(team, false) then return {} end
  local c = H.enemy_city_at(plot, pid)
  if c then
    return { city = c:GetName(), owner = c:GetOwner(), hp = c:GetMaxHitPoints() - c:GetDamage(),
      preview = H.ranged_preview(u, nil, c) }
  end
  for i = 0, plot:GetNumUnits() - 1 do
    local t = plot:GetUnit(i)
    if t and not t:IsInvisible(team, false) and t:GetOwner() ~= pid then
      local owner = Players[t:GetOwner()]
      if owner and Teams[team]:IsAtWar(owner:GetTeam()) then
        local out = H.combat_side(t:GetOwner(), t:GetID(), pid) or {}
        out.preview = H.ranged_preview(u, t, nil)
        return out
      end
    end
  end
  return {}
end

function H.melee_targets(u, pid)
  local out = {}
  if not u:IsCombatUnit() or (u.GetRangedCombatStrength and u:GetRangedCombatStrength() or 0) > 0 or u:MovesLeft() <= 0 then return out end
  for dx = -1, 1 do for dy = -1, 1 do
    local q = Map.PlotXYWithRangeCheck(u:GetX(), u:GetY(), dx, dy, 1)
    if q and (q:GetX() ~= u:GetX() or q:GetY() ~= u:GetY()) then
      -- A garrisoned city is fought as the city (its strength includes the garrison); listing the garrison
      -- unit showed a unit-vs-unit preview for a city assault (live t119, Machu's Composite Bowman).
      local c = H.enemy_city_at(q, pid)
      local d = not c and H.melee_defender(u, q, pid)
      if d then
        local e = H.combat_side(d:GetOwner(), d:GetID(), pid) or {}
        e.how = "move_unit onto this plot attacks"
        e.preview = H.melee_preview(u, d)
        out[#out + 1] = e
      end
      if c then
        out[#out + 1] = { x = q:GetX(), y = q:GetY(), city = c:GetName(), owner = c:GetOwner(),
                          hp = c:GetMaxHitPoints() - c:GetDamage(), how = "move_unit onto this plot assaults the city",
                          preview = H.melee_city_preview(u, c) }
      end
    end
  end end
  return out
end

-- Plots a ranged unit could shoot this turn, the way the unit panel's Ranged Attack cursor highlights
-- them: engine CanRangeStrikeAt over the unit's Range, only plots showing a visible unit or city.
-- Live t316: a Chu-Ko-Nu two tiles from a barbarian listed no action and no target, yet
-- MISSION_RANGE_ATTACK on that plot hit for 39 (the one-arg CanStartMission check needs a target).
function H.ranged_targets(u, pid)
  local out = {}
  if not (u.IsRanged and u:IsRanged()) or u:MovesLeft() <= 0 then return out end
  if u.CanRangeStrike and not u:CanRangeStrike() then return out end
  local row = GameInfo.Units[u:GetUnitType()]
  local range = row and row.Range or 0
  if range <= 0 then return out end
  local team = Players[pid]:GetTeam()
  for dx = -range, range do for dy = -range, range do
    local q = Map.PlotXYWithRangeCheck(u:GetX(), u:GetY(), dx, dy, range)
    if q and q:IsVisible(team, false) and (q:GetX() ~= u:GetX() or q:GetY() ~= u:GetY()) then
      local ok, can = pcall(function() return u:CanRangeStrikeAt(q:GetX(), q:GetY(), true, true) end)
      if ok and can then
        local e = { x = q:GetX(), y = q:GetY(), how = "unit_mission MISSION_RANGE_ATTACK with x, y" }
        for k, v in pairs(H.ranged_target_info(u, q, pid)) do e[k] = v end
        out[#out + 1] = e
      end
    end
  end end
  return out
end

-- move_unit bookkeeping for a melee attack: who stands on the destination before the order, and what
-- became of both sides after it (the Python wrapper calls attack_before, the order, then attack_after).
-- An air unit does not walk: a strike is legal this instant or not at all, and the engine answers an
-- out-of-range one by doing nothing at all. Live t184: a Fighter at (49,19) was sent at Cusco (42,23),
-- nine plots away against a range of eight; the order was accepted and simply had no effect, so the
-- reply was ok=true with both sides' hp unchanged -- the "accepted but wrong" shape this harness keeps
-- running into. Report the engine's own predicate so the caller can refuse instead of guessing.
local function air_strike_legality(u, x, y)
  local air = false
  pcall(function() air = u.CanAirAttack and u:CanAirAttack() end)
  if not air then return nil end
  local ok, can = pcall(function() return u:CanRangeStrikeAt(x, y, true, true) end)
  return { air = true, can_strike = (ok and can) and true or false,
           range = (pcall(function() return u:Range() end) and u:Range() or nil) }
end

function H.attack_before(unit_id, x, y, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  local air = u and air_strike_legality(u, x, y) or nil
  local c = u and H.enemy_city_at(Map.GetPlot(x, y), pid)
  if c then
    return { attack = true, city = true, def_player = c:GetOwner(), def_unit = -1,
             def_hp = c:GetMaxHitPoints() - c:GetDamage(), my_hp = u:GetCurrHitPoints(),
             air = air,
             defender = { city = c:GetName(), owner = H.owner_label(c:GetOwner(), pid), x = x, y = y } }
  end
  local d = u and H.melee_defender(u, Map.GetPlot(x, y), pid)
  if not d then return { attack = false } end
  return { attack = true, def_player = d:GetOwner(), def_unit = d:GetID(), def_hp = d:GetCurrHitPoints(),
           my_hp = u:GetCurrHitPoints(), air = air,
           defender = H.combat_side(d:GetOwner(), d:GetID(), pid) }
end
function H.attack_after(unit_id, def_player, def_unit, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  local d = Players[def_player] and Players[def_player]:GetUnitByID(def_unit)
  local out = {}
  if not u or u:IsDelayedDeath() then out.my_unit_killed = true else out.my_hp = u:GetCurrHitPoints() end
  if not d or d:IsDelayedDeath() or d:GetCurrHitPoints() <= 0 then out.defender_killed = true
  else out.def_hp = d:GetCurrHitPoints() end
  return out
end

function H.city_attack_after(unit_id, x, y, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  local out = {}
  if not u or u:IsDelayedDeath() then out.my_unit_killed = true else out.my_hp = u:GetCurrHitPoints() end
  local pl = Map.GetPlot(x, y)
  local c = pl and pl:GetPlotCity()
  if c and c:GetOwner() == pid then out.city_captured = true
  elseif c then out.def_hp = c:GetMaxHitPoints() - c:GetDamage() end
  return out
end

-- A civilian "defender" that vanished was captured when a unit of that type is now ours on its plot (live t112:
-- an Inca Worker taken by a Warrior read as defender_killed). Returns the new unit id or nil.
function H.captured_at(x, y, type_name, pid)
  local pl = Map.GetPlot(x, y)
  if not pl then return nil end
  for i = 0, pl:GetNumUnits() - 1 do
    local c = pl:GetUnit(i)
    if c and c:GetOwner() == pid and not c:IsCombatUnit()
       and GameInfo.Units[c:GetUnitType()] and GameInfo.Units[c:GetUnitType()].Type:gsub("^UNIT_", "") == type_name:gsub("^UNIT_", "") then
      return c:GetID()
    end
  end
  return nil
end

-- ActivityTypes as the unit panel shows them (raw ints otherwise mean nothing to a caller).
local ACTIVITY_NAMES = { [0] = "AWAKE", [1] = "HOLD", [2] = "SLEEP_OR_FORTIFY", [3] = "HEAL", [4] = "SENTRY", [5] = "INTERCEPT", [6] = "MISSION" }
function H.activity_name(a) return ACTIVITY_NAMES[a] or tostring(a) end

function H.unit_pos(unit_id, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  local denom = move_denom()
  return {
    ok = true, x = u:GetX(), y = u:GetY(),
    moves = u:MovesLeft() / denom,
    activity = u.GetActivityType and u:GetActivityType() or nil,
    activity_name = u.GetActivityType and H.activity_name(u:GetActivityType()) or nil,
    buildtype = u.GetBuildType and u:GetBuildType() or nil,
  }
end

-- Where the known map ends for one unit: revealed, passable plots of the unit's domain that touch at
-- least one unrevealed plot, nearest first. This is the fog boundary a human sees on the minimap --
-- the only thing read about an unrevealed plot is that it is unrevealed (IsRevealed), never its
-- terrain, owner or occupants. move_unit refuses unrevealed targets, so an explorer uses this to pick
-- its next stop instead of guessing coordinates.
function H.explore_frontier(unit_id, pid, limit)
  local u = Players[pid]:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  local team = Players[pid]:GetTeam()
  local sea = (u:GetDomainType() == DomainTypes.DOMAIN_SEA)
  local embarked = (u.IsEmbarked and u:IsEmbarked()) and true or false
  local ux, uy = u:GetX(), u:GetY()
  local out, unrevealed = {}, 0
  local w, h = Map.GetGridSize()
  local function traversable(p)
    -- IsImpassable() is false for a mountain in this build (live 2026-09-18: (42,27) offered as reachable
    -- DESERT, move_unit refused it) -- mountains are a plot type, not an impassable terrain/feature.
    return not p:IsImpassable() and not p:IsMountain() and (p:IsWater() == sea or (embarked and p:IsWater()))
  end
  -- Borders: the engine's pathfinder will not cross another civ's territory without open borders (or a
  -- war), and refused a city-state's coast outright (live t287: Caravel -> (53,32) inside Sidon, "no
  -- path" although the flood fill said reachable). Owner is the last-seen owner a human sees on the
  -- map (GetRevealedOwner), never the true one on a fogged plot.
  local open_cache = {}
  local function closed_owner(p)
    local o = p.GetRevealedOwner and p:GetRevealedOwner(team, false) or (p.GetOwner and p:GetOwner()) or -1
    if o == nil or o < 0 or o == pid then return nil end
    if open_cache[o] == nil then
      local ot = Players[o] and Players[o]:GetTeam() or -1
      local ok = (ot == team)
      if not ok and ot >= 0 and Teams then
        local mine, theirs = Teams[team], Teams[ot]
        ok = (mine and mine.IsAtWar and mine:IsAtWar(ot)) and true or false
        if not ok and theirs and theirs.IsAllowsOpenBordersToTeam then ok = theirs:IsAllowsOpenBordersToTeam(team) and true or false end
      end
      open_cache[o] = ok
    end
    if open_cache[o] then return nil end
    return o
  end
  -- Flood fill from the unit over revealed, traversable plots: which frontier plots are reachable
  -- through the KNOWN map (Unit:GeneratePath is NYI here, so this is the only path hint). A plot on
  -- the far side of a landmass is reachable=false even when its hex distance is small (live t272:
  -- the Caravel was sent to (52,6), distance 2, and the engine detoured it west for two turns).
  -- Only IsRevealed is read on fogged plots; the fill never steps into them.
  local reached, frontier_queue, head = {}, {}, 1
  local function key(x, y) return y * w + x end
  reached[key(ux, uy)] = true
  frontier_queue[1] = Map.GetPlot(ux, uy)
  while head <= #frontier_queue do
    local c = frontier_queue[head]; head = head + 1
    local cx, cy = c:GetX(), c:GetY()
    for dx = -1, 1 do for dy = -1, 1 do
      local q = Map.PlotXYWithRangeCheck(cx, cy, dx, dy, 1)
      if q and not reached[key(q:GetX(), q:GetY())] and q:IsRevealed(team, false) and traversable(q) and not closed_owner(q) then
        reached[key(q:GetX(), q:GetY())] = true
        frontier_queue[#frontier_queue + 1] = q
      end
    end end
  end
  for i = 0, Map.GetNumPlots() - 1 do
    local p = Map.GetPlotByIndex(i)
    if p then
      if not p:IsRevealed(team, false) then
        unrevealed = unrevealed + 1
      elseif traversable(p) then
        local px, py, n = p:GetX(), p:GetY(), 0
        for dx = -1, 1 do for dy = -1, 1 do
          local q = Map.PlotXYWithRangeCheck(px, py, dx, dy, 1)
          if q and (q:GetX() ~= px or q:GetY() ~= py) and not q:IsRevealed(team, false) then n = n + 1 end
        end end
        if n > 0 then
          local e = { x = px, y = py, unrevealed_neighbors = n,
                      distance = Map.PlotDistance(ux, uy, px, py),
                      reachable = reached[key(px, py)] == true,
                      t = short(info_type(GameInfo.Terrains, p:GetTerrainType())) }
          -- The map's top/bottom rows are the polar ice a human sees on the minimap frame; a frontier
          -- plot there mostly reveals more ice, so flag it rather than let it outrank real coastline.
          -- (rows 0-1 and h-2..h-1 are the ice; a plot on row 2 only borders it, so flag it too: live
          -- t272 the whole y=2 row outranked the real eastern coastline)
          if py <= 2 or py >= h - 3 then e.map_edge = true end
          local co = closed_owner(p)
          if co then e.closed_border = co end  -- owner id: a border the unit may not cross (no open borders)
          out[#out + 1] = e
        end
      end
    end
  end
  table.sort(out, function(a, b)
    if a.reachable ~= b.reachable then return a.reachable end
    if a.distance ~= b.distance then return a.distance < b.distance end
    if a.unrevealed_neighbors ~= b.unrevealed_neighbors then return a.unrevealed_neighbors > b.unrevealed_neighbors end
    if a.x ~= b.x then return a.x < b.x end
    return a.y < b.y
  end)
  local frontier_total = #out
  limit = limit or 12
  while #out > limit do out[#out] = nil end
  return { ok = true, unit = { id = unit_id, x = ux, y = uy, domain = sea and "SEA" or "LAND", embarked = embarked },
           map = { width = w, height = h }, unrevealed_plots = unrevealed,
           frontier_total = frontier_total, frontier = out,
           note = (frontier_total == 0) and ((unrevealed == 0) and "the whole map is revealed"
                  or "no revealed plot of this unit's domain borders the fog; the remaining fog is not reachable from here without embarking or another unit") or nil }
end

-- Snapshot of the city a religious unit (Missionary / Inquisitor / Prophet) would act on: the city on
-- its own plot or an adjacent one. Used by unit_mission to measure MISSION_SPREAD_RELIGION /
-- MISSION_REMOVE_HERESY instead of trusting PushMission's unconditional acceptance.
function H.religion_target(unit_id, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  local rel = u.GetReligion and u:GetReligion() or -1
  local city = nil
  local here = Map.GetPlot(u:GetX(), u:GetY())
  if here and here:IsCity() then city = here:GetPlotCity() end
  if not city then
    for d = 0, DirectionTypes.NUM_DIRECTION_TYPES - 1 do
      local p = Map.PlotDirection(u:GetX(), u:GetY(), d)
      if p and p:IsCity() then city = p:GetPlotCity(); break end
    end
  end
  local out = { ok = true, unit_religion = rel, spreads_left = u.GetSpreadsLeft and u:GetSpreadsLeft() or nil,
                strength = u.GetConversionStrength and u:GetConversionStrength() or nil }
  if rel and rel >= 0 and Game.GetReligionName then out.unit_religion_name = H.L(Game.GetReligionName(rel)) end
  if not city then out.city = nil; return out end
  return H.city_religion_state(city, rel, pid, out)
end

-- The city half of religion_target, keyed by city plot so it can be re-read after the acting unit
-- was consumed by its last charge (unit_id is gone by then).
function H.city_religion_at(x, y, rel, pid)
  local p = Map.GetPlot(x, y)
  if not p or not p:IsCity() then return { ok = false, err = "no city at that plot" } end
  return H.city_religion_state(p:GetPlotCity(), rel, pid, { ok = true, unit_religion = rel })
end

function H.city_religion_state(city, rel, pid, out)
  local owner = city:GetOwner()
  local maj = city:GetReligiousMajority()
  out.city = city:GetName(); out.city_owner = owner; out.x = city:GetX(); out.y = city:GetY()
  out.population = city:GetPopulation()
  out.majority = maj
  if maj >= 0 and Game.GetReligionName then out.majority_name = H.L(Game.GetReligionName(maj)) end
  out.followers = (rel and rel >= 0) and city:GetNumFollowers(rel) or nil
  out.majority_followers = maj >= 0 and city:GetNumFollowers(maj) or nil
  local op = Players[owner]
  if op and op:IsMinorCiv() then out.influence = op:GetMinorCivFriendshipWithMajor(pid) end
  return out
end

function H.move_unit(unit_id, x, y, pid)
  local u, err = own_active_unit(unit_id, pid)
  if not u then return err end
  local blocked = require_revealed_plot(x, y, pid, u)
  if blocked then return blocked end
  local m = info_id("MISSION_MOVE_TO")
  if m == nil then return { ok = false, err = "unknown mission" } end
  local legal = false
  if u.CanStartMission then
    local ok, v = pcall(function() return u:CanStartMission(m, x, y, false) end)
    legal = ok and v
  end
  if not legal then return { ok = false, err = "move is not currently legal" } end
  -- CanStartMission(MOVE_TO) is true for any valid plot, even one no path reaches (a natural
  -- wonder / mountain, or across unexplored water): the engine then drops the mission silently.
  local dest = Map.GetPlot(x, y)
  -- Unit:GeneratePath is NYI in this build (throws). Plot:MovementCost crashed the live process
-- (t183, 2026-09-19) even inside pcall -- do not call it. GetPathEndTurnPlot is nil without a
-- mouse-driven UI pathfinder. Do not fake turns-to-reach.
-- Unit:GeneratePath is NYI in this build (throws), so the checks are per-destination-plot:
  -- IsImpassable catches natural wonders (Uluru), IsMountain catches mountains (whose terrain type
  -- still reads GRASS/PLAINS, so callers can't tell from the map), CanMoveOrAttackInto catches the rest.
  if dest and dest:IsImpassable() and not (u.CanMoveImpassable and u:CanMoveImpassable()) then
    return { ok = false, err = "destination plot is impassable" }
  end
  -- Domain: a ship ordered onto land (or a land unit onto water before Optics) is dropped silently by
  -- the engine (live t252: Caravel -> a newly sighted plains plot, ok:true, never moved). Say so.
  if dest and DomainTypes then
    local dom = u:GetDomainType()
    if dom == DomainTypes.DOMAIN_SEA and not dest:IsWater() and not dest:IsCity() then
      return { ok = false, err = "destination is land; a sea unit can only enter water plots or a coastal city" }
    end
    -- Unit:CanEmbark(plot) asks whether it can embark FROM that plot: false for any inland unit even with
    -- Optics (live t412: a Missionary at (35,29), team can embark, refused as "needs Optics"). Ask whether the
    -- unit can embark at all: its embarkation promotion, or the team-wide ability.
    local canEmbark = false
    pcall(function() canEmbark = u:IsHasPromotion(GameInfoTypes.PROMOTION_EMBARKATION) end)
    if not canEmbark then pcall(function() canEmbark = Teams[u:GetTeam()]:CanEmbark() end) end
    if dom == DomainTypes.DOMAIN_LAND and dest:IsWater() and not canEmbark then
      return { ok = false, err = "destination is water and this unit cannot embark (needs Optics; a ship or cargo ship is the alternative)" }
    end
  end
  if dest and dest:IsMountain() then
    local ok, can = pcall(function() return u:CanMoveOrAttackInto(dest) end)
    if not (ok and can) then return { ok = false, err = "destination plot is a mountain" } end
  end
  -- NOTE: CanMoveOrAttackInto(dest) is false for perfectly legal multi-step destinations (live: a
  -- warrior moving into its own adjacent city), so it is only consulted for the mountain case above.
  -- One combat unit per tile: a move whose destination already holds one of our own combat units
  -- (e.g. "send the new bowman to Nanjing" while a warrior garrisons it) has no legal end plot and is
  -- dropped silently by the engine (live, turn 110). Refuse it up front.
  if dest and u:IsCombatUnit() then
    for i = 0, dest:GetNumUnits() - 1 do
      local o = dest:GetUnit(i)
      if o and o:GetOwner() == u:GetOwner() and o:GetID() ~= u:GetID() and o:IsCombatUnit()
         and o:GetDomainType() == u:GetDomainType() then
        return { ok = false, err = "destination already holds one of your combat units (one per tile); pick an adjacent plot or move that unit first" }
      end
    end
  end
  -- Another major civ's territory is closed without open borders (or war); the engine finds no path
  -- and drops the order silently (live t256: Caravel -> India's coast). Name the owner instead.
  local closed = nil
  pcall(function()
    if dest and dest:GetOwner() >= 0 and dest:GetOwner() ~= pid then
      local o = Players[dest:GetOwner()]
      local myTeam, theirTeam = Teams[Players[pid]:GetTeam()], o and Teams[o:GetTeam()] or nil
      if o and theirTeam and not o:IsMinorCiv() and not myTeam:IsAtWar(o:GetTeam())
         and not (theirTeam.IsAllowsOpenBordersToTeam and theirTeam:IsAllowsOpenBordersToTeam(Players[pid]:GetTeam())) then
        closed = { ok = false, err = "destination is inside " .. o:GetCivilizationShortDescription()
                   .. "'s borders and you have no open-borders agreement with them (trade one via propose_deal, or path around)",
                   owner_player_id = dest:GetOwner() }
      end
    end
  end)
  if closed then return closed end
  local occ = H.peaceful_occupant(dest, pid)
  if occ then return { ok = false, err = peaceful_occupant_err(occ) } end
  local x0, y0, m0 = u:GetX(), u:GetY(), u:MovesLeft()
  local pushed = push_mission(u, m, x, y)
  if not pushed.ok then return pushed end
  -- Remember the destination: a MOVE_TO that needs more than this turn does NOT resume by itself at the
  -- next turn start (live, Caravel t256-264), so H.resume_moves re-pushes it until the unit arrives.
  -- Never for an attack: the unit does not "arrive", so the standing order re-fired as a second,
  -- unordered attack at the next turn start (live 2026-09-18, warrior vs a camp Brute: 73 -> 42 hp).
  if H.melee_defender(u, Map.GetPlot(x, y), pid) or H.enemy_city_at(Map.GetPlot(x, y), pid) then
    H.pending_moves[unit_id] = nil
  else
    H.pending_moves[unit_id] = { x = x, y = y, pid = pid }
  end
  return { ok = true, x = x0, y = y0, moves = m0 / move_denom() }
end

-- A multi-turn move pushed from Lua does NOT resume at the next turn start (live: Caravel, t256-258):
-- the unit sits in ACTIVITY_MISSION with a queued MOVE_TO, moves still in hand, and the engine will
-- not spend them. That is the "stalled" shape, and such a unit DOES block end_turn. todo() and the
-- MISSION_SKIP guard both have to agree about it -- they did not (live t186: turn_status listed Great
-- General 335877 as blocking with stalled_mission=true while unit_mission(MISSION_SKIP) refused it as
-- "already on a multi-turn move and does not block end_turn"), so they now ask the same function.
-- A Worker mid-build also idles at full moves and is not stalled.
function H.is_stalled_mission(u)
  if not (u and u.GetActivityType and u:GetActivityType() == 6) then return false end
  if not (u.MovesLeft and u:MovesLeft() > 0) then return false end
  if u.GetBuildType and u:GetBuildType() ~= -1 then return false end
  return true
end

-- Re-issue standing move orders whose unit is idle at full moves (the "stalled_mission" shape) and drop
-- the ones that arrived or whose unit is gone. Called by wait_for_my_turn once the turn is ours.
function H.resume_moves(pid)
  local out = {}
  for id, pm in pairs(H.pending_moves) do
    if pm.pid == pid then
      local u = Players[pid]:GetUnitByID(id)
      if not u or u:IsDelayedDeath() then
        H.pending_moves[id] = nil
      elseif u:GetX() == pm.x and u:GetY() == pm.y then
        H.pending_moves[id] = nil
        out[#out + 1] = { unit_id = id, x = pm.x, y = pm.y, arrived = true }
      elseif u:MovesLeft() > 0 and u:MovesLeft() == u:MaxMoves()
             and not (u.GetBuildType and u:GetBuildType() ~= -1) then
        -- No progress since the last resume (same plot a whole turn later) means the engine keeps
        -- dropping the path (e.g. a Missionary ordered INTO a foreign city plot, t266): stop re-issuing
        -- and tell the caller, rather than pushing the same dead order every turn forever.
        if H.melee_defender(u, Map.GetPlot(pm.x, pm.y), pid) or H.enemy_city_at(Map.GetPlot(pm.x, pm.y), pid) then
          -- An enemy now stands on the destination: re-issuing the move would be an attack nobody ordered.
          H.pending_moves[id] = nil
          out[#out + 1] = { unit_id = id, x = pm.x, y = pm.y, dropped = true,
                            err = "an enemy unit now stands on the destination; move_unit there again to attack it" }
        elseif H.peaceful_occupant(Map.GetPlot(pm.x, pm.y), pid) then
          H.pending_moves[id] = nil
          out[#out + 1] = { unit_id = id, x = pm.x, y = pm.y, dropped = true,
                            err = peaceful_occupant_err(H.peaceful_occupant(Map.GetPlot(pm.x, pm.y), pid)) }
        elseif pm.last_x == u:GetX() and pm.last_y == u:GetY() then
          H.pending_moves[id] = nil
          out[#out + 1] = { unit_id = id, x = pm.x, y = pm.y, dropped = true,
                            err = "no progress toward the destination for a full turn; the engine finds no path -- pick another plot" }
        else
          pm.last_x, pm.last_y = u:GetX(), u:GetY()
          local r = H.move_unit(id, pm.x, pm.y, pid)
          if r.ok then
            H.pending_moves[id] = pm  -- H.move_unit replaced the record; keep the progress marker
            out[#out + 1] = { unit_id = id, x = pm.x, y = pm.y, resumed = true }
          else
            H.pending_moves[id] = nil
            out[#out + 1] = { unit_id = id, x = pm.x, y = pm.y, dropped = true, err = r.err }
          end
        end
      end
    end
  end
  return out
end

-- MISSION_FOUND pre/post check. PushMission(MISSION_FOUND) returns "ok" even when the settler has no
-- moves left (live t283: the standing order had just walked it onto the site, activity went to HOLD and
-- no city appeared), so the wrapper reads this before and after. (x, y) is the settler's plot, kept by
-- the caller because the unit is consumed on success.
function H.found_check(unit_id, x, y, pid)
  local p = Players[pid]
  local u = p:GetUnitByID(unit_id)
  local out = { ok = true, unit_exists = u ~= nil }
  if u then
    x, y = u:GetX(), u:GetY()
    out.x, out.y = x, y
    out.moves = u:MovesLeft() / GameDefines.MOVE_DENOMINATOR
    -- Unit:CanFound(plot, n) wants a number for arg 2 (a boolean raises "number expected", the pcall
    -- swallowed it and every MISSION_FOUND was refused as "cannot found"; live t284). Omit it.
    local okc, v = pcall(function() return u:CanFound(u:GetPlot()) end)
    out.can_found = okc and v and true or false
  end
  local pl = (x and y) and Map.GetPlot(x, y) or nil
  if pl and pl:IsCity() then
    local c = pl:GetPlotCity()
    out.city = { id = c:GetID(), name = c:GetName(), owner = c:GetOwner(), x = x, y = y }
  end
  return out
end

-- A refused order must not cost the unit its standing move (live t26: a BUILD_FARM refused mid-walk wiped
-- the Worker's move_unit record, so resume_moves skipped it and it idled a turn as "stalled_mission").
function H.unit_mission(unit_id, mission, x, y, build, pid)
  local standing = H.pending_moves[unit_id]
  local r = H.unit_mission_order(unit_id, mission, x, y, build, pid)
  local u = Players[pid] and Players[pid]:GetUnitByID(unit_id)
  local arrived = u and standing and u:GetX() == standing.x and u:GetY() == standing.y
  if type(r) == "table" and r.ok == false and standing and not arrived and H.pending_moves[unit_id] == nil then
    H.pending_moves[unit_id] = standing
    r.standing_move_kept = { x = standing.x, y = standing.y }
  end
  return r
end

function H.unit_mission_order(unit_id, mission, x, y, build, pid)
  local u, err = own_active_unit(unit_id, pid)
  if not u then return err end
  if mission == "MISSION_SKIP" then
    -- A skip on a unit that is mid-way through a multi-turn move cancels the engine's path (live t306:
    -- the Caravel's standing order to (54,29) died to a reflex MISSION_SKIP and it sat at (54,13) with
    -- 4 moves next turn). Such a unit does not block end_turn, so refuse instead of cancelling.
    -- A standing order whose destination the unit already stands on is finished, not "mid-way" (live
    -- t315: the Caravel arrived with 1 move left, the stale record refused every skip while the engine
    -- kept ENDTURN_BLOCKING_UNITS on it -- a refusal deadlock).
    local pm = H.pending_moves[unit_id]
    if pm and pm.x == u:GetX() and pm.y == u:GetY() then H.pending_moves[unit_id] = nil end
    local busy = (u.GetLengthMissionQueue and u:GetLengthMissionQueue() or 0) > 0
    if not busy and u.GetActivityType and ActivityTypes and u:GetActivityType() == ActivityTypes.ACTIVITY_MISSION then busy = true end
    -- ...but a stalled one blocks end_turn (todo() lists it), and refusing the skip there is a
    -- deadlock: turn_status says "this unit stops the turn", unit_mission says "it does not".
    -- A human at the same screen just presses Space.
    if (busy or H.pending_moves[unit_id]) and not H.is_stalled_mission(u) then
      return { ok = false, err = "unit is already on a multi-turn move and does not block end_turn; "
                                 .. "MISSION_SKIP would cancel that path (give it a new move_unit instead)",
               x = u:GetX(), y = u:GetY() }
    end
  end
  H.pending_moves[unit_id] = nil  -- a new order replaces any standing move
  if build ~= nil and build ~= "" and mission ~= "MISSION_BUILD" then
    return { ok = false, err = "build requires MISSION_BUILD" }
  end
  if type(mission) == "string" and mission:match("^AUTOMATE_") then
    -- Automation is a command, not a mission: the unit panel's button goes through Game.HandleAction ->
    -- GAMEMESSAGE_DO_COMMAND(COMMAND_AUTOMATE, automate type). Live t316: AUTOMATE_EXPLORE resolved to
    -- GameInfoTypes id 1 and went out as mission 1 = MISSION_ROUTE_TO(-1,-1), which "succeeded".
    local a = GameInfoTypes and GameInfoTypes[mission]
    if a == nil or not (CommandTypes and CommandTypes.COMMAND_AUTOMATE) then return { ok = false, err = "unknown automation" } end
    local ok, can = pcall(function() return u:CanAutomate(a) end)
    if not (ok and can) then return { ok = false, err = "action is not currently legal" } end
    local sent = do_command(u, CommandTypes.COMMAND_AUTOMATE, a, -1)
    if not sent.ok then return sent end
    return { ok = true, automate_pending = a }
  end
  -- COMMAND_* (delete/disband, wake, cancel...) are listed by available_unit_actions and go out as
  -- GAMEMESSAGE_DO_COMMAND like the unit panel's buttons; t370 unit_mission refused COMMAND_DELETE as an
  -- "unknown mission" although the action list offered it. Promotion/upgrade keep their own tools.
  if type(mission) == "string" and mission:match("^COMMAND_") then
    local c = CommandTypes and CommandTypes[mission]
    if c == nil then return { ok = false, err = "unknown command" } end
    if mission == "COMMAND_PROMOTION" or mission == "COMMAND_UPGRADE" then
      return { ok = false, err = "use choose_promotion / upgrade_unit for this command" }
    end
    local ok, can = pcall(function() return u:CanDoCommand(c, -1, -1) end)
    if not (ok and can) then return { ok = false, err = "action is not currently legal" } end
    local sent = do_command(u, c, -1, -1)
    if not sent.ok then return sent end
    return { ok = true, command_pending = mission }
  end
  -- Only real mission names: GameInfoTypes also maps builds, automates, units... to small ints that
  -- collide with mission ids (the AUTOMATE_EXPLORE -> MISSION_ROUTE_TO accident above).
  if not (MissionTypes and MissionTypes[mission] ~= nil) then
    return { ok = false, err = "unknown mission (use a MISSION_* name from available_unit_actions; "
                               .. "AUTOMATE_* names are accepted too, builds go in build= with MISSION_BUILD)" }
  end
  local m = MissionTypes[mission]
  local d1, d2 = -1, -1
  if type(x) == "number" then d1 = x end
  if type(y) == "number" then d2 = y end
  if build ~= nil and build ~= "" then
    local b = info_id(build)
    if b == nil then return { ok = false, err = "unknown build" } end
    local legal = false
    if u.CanBuild then
      -- Unit:CanBuild(plot, build): with only the build id the call errors ("Instance does not
      -- exist"), the pcall swallows it, and every MISSION_BUILD was refused as "not legal".
      local ok, v = pcall(function() return u:CanBuild(u:GetPlot(), b) end)
      legal = ok and v
    end
    if not legal then return { ok = false, err = "action is not currently legal" } end
    -- The engine applies this turn's work the moment the build mission starts. A short build
    -- (BUILD_REPAIR, chops, anything whose remaining work fits in one turn) therefore FINISHES
    -- inside PushMission and GetBuildType() is already -1 again on return -- seen live twice
    -- (pasture + quarry repairs, China game t196/t198) and misreported as "did not start a
    -- build". Snapshot the plot so an instant completion is recognised instead.
    local pl = u:GetPlot()
    local before = { imp = pl:GetImprovementType(), pillaged = pl:IsImprovementPillaged(),
                     route = pl:GetRouteType(), route_pillaged = pl:IsRoutePillaged(),
                     feature = pl:GetFeatureType(), moves = u:MovesLeft() }
    local pushed = push_mission(u, m, b, -1)
    if not pushed.ok then return pushed end
    -- The order lands on a later game update; the Python wrapper polls H.build_check with `before`.
    return { ok = true, pending = true, build_id = b, x = pl:GetX(), y = pl:GetY(), before = before }
  end
  if d1 >= 0 and d2 >= 0 then
    local blocked = require_revealed_plot(d1, d2, pid)
    if blocked then return blocked end
  else
    d1, d2 = -1, -1
  end
  local legal = false
  if u.CanStartMission then
    local ok, v = pcall(function() return u:CanStartMission(m, d1, d2, false) end)
    legal = ok and v
  end
  if not legal then return { ok = false, err = "action is not currently legal" } end
  local pushed = push_mission(u, m, d1, d2)
  if not pushed.ok then return pushed end
  return { ok = true }
end

-- Poll after an AUTOMATE_* command: the engine flags the unit automated once the command lands (and
-- an explorer may already have moved on the same update).
function H.automate_check(unit_id, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  if not u then return { ok = true, gone = true } end
  return { ok = true, automated = u:IsAutomated(),
           x = u:GetX(), y = u:GetY(), moves = u:MovesLeft() / move_denom() }
end

-- Poll after a MISSION_BUILD: `started` when GetBuildType() shows the build, `completed` when the plot
-- already changed (a short build -- BUILD_REPAIR, a chop -- finishes the moment it starts and
-- GetBuildType() is -1 again; seen live twice, China game t196/t198).
function H.build_check(unit_id, x, y, before, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  local pl = Map.GetPlot(x, y)
  local out = { ok = true, unit_exists = u ~= nil }
  if u then
    out.buildtype = u.GetBuildType and u:GetBuildType() or -1
    out.moves = u:MovesLeft() / move_denom()
    out.started = out.buildtype ~= -1
    -- Name it: a bare id (15 for both a Silk plantation and a forest-hill mine, live t79) said nothing.
    local row = out.started and GameInfo.Builds[out.buildtype] or nil
    if row then
      out.build = row.Type
      if pl then
        local okt, t = pcall(function() return pl:GetBuildTurnsLeft(out.buildtype, pid, 0, 0) end)
        if okt then out.turns_left = t end
      end
    end
  end
  if pl and before then
    out.completed = pl:GetImprovementType() ~= before.imp or pl:IsImprovementPillaged() ~= before.pillaged
      or pl:GetRouteType() ~= before.route or pl:IsRoutePillaged() ~= before.route_pillaged
      or pl:GetFeatureType() ~= before.feature
  end
  return out
end

function H.pending_popups(pid)
  local out = {}
  for kind, info in pairs(H.popups) do
    if info.player == pid then
      out[#out+1] = {type=kind, name=H.enum_name("popup", ButtonPopupTypes, kind), data1=info.data1, data2=info.data2, data3=info.data3}
    end
  end
  table.sort(out, function(a,b) return a.type < b.type end)
  return out
end

function H.todo(pid)
  local p = Players[pid]
  if not (Game.GetActivePlayer() == pid and p:IsTurnActive()) then return nil end
  local todo = { units = {}, promotions = {}, cities = {}, research_unset = p:GetCurrentResearch() == -1 }
  for u in p:Units() do
    if u:IsReadyToMove() and not u:IsAutomated() and not u:IsDelayedDeath() then
      local ut = GameInfo.Units[u:GetUnitType()]
      todo.units[#todo.units + 1] = { id = u:GetID(), type = ut and short(ut.Type) or u:GetUnitType(), x = u:GetX(), y = u:GetY(),
                                      moves = u:MovesLeft() / GameDefines.MOVE_DENOMINATOR }
    elseif not u:IsAutomated() and not u:IsDelayedDeath() and H.is_stalled_mission(u) then
      -- A partially spent move can also stall; report any remaining movement so end_turn cannot
      -- silently miss it.
      local ut = GameInfo.Units[u:GetUnitType()]
      todo.units[#todo.units + 1] = { id = u:GetID(), type = ut and short(ut.Type) or u:GetUnitType(), x = u:GetX(), y = u:GetY(),
                                      moves = u:MovesLeft() / GameDefines.MOVE_DENOMINATOR,
                                      stalled_mission = true, note = "queued move did not resume; re-issue move_unit" }
    end
    if u.IsPromotionReady and u:IsPromotionReady() then
      todo.promotions[#todo.promotions + 1] = u:GetID()
    end
  end
  for c in p:Cities() do
    if c:GetProductionNameKey() == "" then
      todo.cities[#todo.cities + 1] = { id = c:GetID(), name = c:GetName() }
    end
  end
  -- Spy-steal can be pending while another blocker is current (live t181: POLICY in front of
  -- STEAL_TECH). Surface it the same way empty cities / promotions are listed.
  local ok, steal = pcall(H.steal_tech_options, pid)
  if ok and type(steal) == "table" and (steal.n or 0) > 0 then
    todo.steal_tech = steal.victims
    todo.steal_tech_hint = "a spy finished stealing: steal_tech_options then steal_tech (can sit behind another blocking_name)"
  end
  return todo
end

-- What a player new to this harness should do about each end-turn blocker: the tool to call.
local BLOCKING_HINTS = {
  ENDTURN_BLOCKING_UNITS = "every unit in todo.units still has moves: move_unit / unit_mission (MISSION_SKIP, MISSION_SLEEP, MISSION_FORTIFY, MISSION_BUILD...) each of them",
  ENDTURN_BLOCKING_STACKED_UNITS = "two of my units share a tile: move_unit one of them off it (skip/fortify does NOT clear this)",
  ENDTURN_BLOCKING_UNIT_NEEDS_ORDERS = "a unit needs an order: see todo.units; move_unit or unit_mission",
  ENDTURN_BLOCKING_UNIT_PROMOTION = "a unit earned a promotion: available_unit_actions(unit_id).promotions then choose_promotion (todo.promotions lists the unit ids)",
  ENDTURN_BLOCKING_RESEARCH = "no research chosen: available_research then set_research",
  ENDTURN_BLOCKING_PRODUCTION = "a city has nothing in production: todo.cities, then available_production + set_production",
  ENDTURN_BLOCKING_POLICY = "a social policy can be adopted: available_policies then choose_policy / unlock_policy_branch",
  ENDTURN_BLOCKING_FREE_POLICY = "a free social policy is waiting: available_policies then choose_policy",
  ENDTURN_BLOCKING_FREE_TECH = "a free technology is waiting: available_research then set_research",
  ENDTURN_BLOCKING_FOUND_PANTHEON = "enough faith for a pantheon: found_pantheon",
  ENDTURN_BLOCKING_FOUND_RELIGION = "a Great Prophet can found a religion: found_religion",
  ENDTURN_BLOCKING_ENHANCE_RELIGION = "a Great Prophet can enhance the religion: enhance_religion",
  ENDTURN_BLOCKING_STEAL_TECH = "a spy stole a tech and you must pick which: steal_tech_options then steal_tech",
  ENDTURN_BLOCKING_LEAGUE_CALL_FOR_PROPOSALS = "World Congress wants a proposal (hard block): league_status then league_propose_enact / league_propose_repeal",
  ENDTURN_BLOCKING_LEAGUE_CALL_FOR_VOTES = "World Congress session: league_status then league_cast_votes",
  ENDTURN_BLOCKING_DIPLO_VOTE = "a diplomatic vote is pending: league_status / league_cast_votes",
  ENDTURN_BLOCKING_FAITH_GREAT_PERSON = "a Great Person can be bought with faith: faith_great_person_options then choose_faith_great_person",
  ENDTURN_BLOCKING_FREE_ITEMS = "a free unit/building choice is pending: free_great_person_options then choose_free_great_person",
  ENDTURN_BLOCKING_CITY_RANGE_ATTACK = "a city can bombard an enemy: available_city_strikes then city_ranged_attack (or end_turn anyway once you have decided not to)",
  ENDTURN_BLOCKING_CHOOSE_IDEOLOGY = "choose_ideology(POLICY_BRANCH_FREEDOM | POLICY_BRANCH_ORDER | POLICY_BRANCH_AUTOCRACY); available_policies lists the branches, players' ideologies are public",
  ENDTURN_BLOCKING_ADD_REFORMATION_BELIEF = "a reformation belief is pending: available_beliefs(kind=reformation) then add_reformation_belief",
  ENDTURN_BLOCKING_CHOOSE_ARCHAEOLOGY = "use archaeology_options then choose_archaeology for the completed dig",
  ENDTURN_BLOCKING_MINOR_QUEST = "a city-state quest popup is pending: wait_for_my_turn sweeps it",
  ENDTURN_BLOCKING_MAYA_LONG_COUNT = "use maya_options then choose_maya_bonus for the Long Count reward",
}
function H.blocking_hint(name)
  return BLOCKING_HINTS[name] or ("no dedicated tool for " .. tostring(name) .. "; try wait_for_my_turn (sweeps popups) and turn_status")
end

function H.turn_state(pid)
  local p = Players[pid]
  local net = Game.IsNetworkMultiPlayer()
  local sent = net and Network.HasSentNetTurnComplete() or false
  local mode = PreGame.IsHotSeatGame() and "hotseat" or (net and (PreGame.IsInternetGame() and "internet" or "lan")) or "single"
  local gs = Game.GetGameState()
  local blocking = p:GetEndTurnBlockingType()
  -- `todo`: everything that still needs a decision this turn, in one place, so a caller does not have
  -- to poll units()/cities()/overview() to find out why the turn will not end or what it is leaving
  -- idle: units awaiting orders (and which of them can take a promotion), cities with an empty
  -- production queue, and research unset. Computed only for the active seat on its own turn.
  local todo = H.todo(pid)
  return {
    todo = todo,
    blocking_hint = blocking ~= -1 and H.blocking_hint(H.blocking_name(blocking)) or nil,
    active_player = Game.GetActivePlayer(), my_turn = Game.GetActivePlayer() == pid and p:IsTurnActive() and not sent,
    turn = Game.GetGameTurn(), blocking = blocking, blocking_name = H.blocking_name(blocking),
    num_units_needing_moves = p.GetNumUnitsNeedingMoves and p:GetNumUnitsNeedingMoves() or nil,
    processing = Game.IsProcessingMessages(), paused = Game.IsPaused(), hotseat = PreGame.IsHotSeatGame(),
    mode = mode, turn_complete_sent = sent,
    simultaneous = net and Game.IsOption(GameOptionTypes.GAMEOPTION_SIMULTANEOUS_TURNS) or false,
    dynamic_turns = net and Game.IsOption(GameOptionTypes.GAMEOPTION_DYNAMIC_TURNS) or false,
    turn_timer = net and Game.IsOption(GameOptionTypes.GAMEOPTION_END_TURN_TIMER_ENABLED) or false,
    everyone_connected = net and Network.IsEveryoneConnected() or nil,
    game_state = gs, game_state_name = H.game_state_name(gs), game_over = gs == GameplayGameStateTypes.GAMESTATE_OVER,
    alive = p:IsAlive(), pending_popups = H.pending_popups(pid),
    notifications = H.notification_counts(p),
  }
end

-- The notification panel's load, for crash correlation: the gamecore keeps a ~100-entry history ring
-- and dismisses entries by itself after about a turn (live t315: 99 held, 10 live), so `live` is what
-- the panel is actually showing.
function H.notification_counts(p)
  if not p.GetNumNotifications then return nil end
  local ok, n = pcall(function() return p:GetNumNotifications() end)
  if not ok or type(n) ~= "number" then return nil end
  local live = 0
  for i = 0, n - 1 do
    local okd, d = pcall(function() return p:GetNotificationDismissed(i) end)
    if okd and d == false then live = live + 1 end
  end
  return { held = n, live = live }
end

-- Human players in a network game: who is connected / has ended their turn (for "waiting on" digests).
-- The in-game player list (mplist.lua) names every human seat but shows the civ only once met.
function H.net_players(pid)
  local out = {}
  local me = Players[pid or Game.GetActivePlayer()]
  local myTeam = me and Teams[me:GetTeam()]
  for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
    local p = Players[i]
    if p and p:IsEverAlive() and p:IsHuman() then
      local met = myTeam == nil or p:GetTeam() == me:GetTeam() or myTeam:IsHasMet(p:GetTeam())
      local nick = p:GetNickName()
      if (nick == nil or nick == "") and met then nick = p:GetName() end  -- GetName falls back to the leader: civ-revealing
      out[#out+1] = { id = i, name = nick, met = met,
                      civ = met and L(p:GetCivilizationShortDescriptionKey()) or nil, alive = p:IsAlive(),
                      turn_active = p:IsTurnActive(), connected = Network.IsPlayerConnected(i),
                      ended_turn = p.HasReceivedNetTurnComplete and p:HasReceivedNetTurnComplete() or nil }
    end
  end
  return out
end

H.install_hooks()

-- The Culture Overview screen (cultureoverview.lua): its victory tab (every met major civ's influential-on count
-- out of the number needed, and tourism) and its influence tab, where any met civ can be selected to see its
-- influence level on every other living major; civs we have not met show as "unknown", as they do there.
-- Live t444: "Venice only needs ... 2 more civilizations to win a Culture Victory" with no way to see which.
function H.culture_overview(pid)
  local me = Players[pid]
  local myTeam = Teams[me:GetTeam()]
  local levels = { [0] = "exotic", "familiar", "popular", "influential", "dominant" }
  local trends = {}
  pcall(function()
    trends[InfluenceLevelTrend.INFLUENCE_TREND_FALLING] = "falling"
    trends[InfluenceLevelTrend.INFLUENCE_TREND_STATIC] = "static"
    trends[InfluenceLevelTrend.INFLUENCE_TREND_RISING] = "rising"
  end)
  local function civname(p) return Locale.Lookup(p:GetCivilizationShortDescriptionKey()) end
  local out = { civs = {} }
  for i = 0, GameDefines.MAX_CIV_PLAYERS - 1 do
    local s = Players[i]
    if s and s:IsAlive() and not s:IsMinorCiv() and myTeam:IsHasMet(s:GetTeam()) then
      local row = { player = i, civ = civname(s), influential_on = s:GetNumCivsInfluentialOn(),
                    needed = s:GetNumCivsToBeInfluentialOn(), tourism = s:GetTourism(), on = {} }
      if i == pid then row.you = true end
      for j = 0, GameDefines.MAX_CIV_PLAYERS - 1 do
        local t = Players[j]
        if j ~= i and t and t:IsAlive() and not t:IsMinorCiv() then
          local lvl = s:GetInfluenceLevel(j)
          if lvl ~= InfluenceLevelTypes.NO_INFLUENCE_LEVEL then
            local culture = t:GetJONSCultureEverGenerated()
            local e = { level = levels[lvl] or lvl,
                        percent = culture > 0 and math.floor(100 * s:GetInfluenceOn(j) / culture) or 0,
                        tourism_per_turn = math.floor(s:GetInfluencePerTurn(j)),
                        trend = trends[s:GetInfluenceTrend(j)] }
            if myTeam:IsHasMet(t:GetTeam()) then e.player = j; e.civ = civname(t) else e.civ = "unknown" end
            local turns = s:GetTurnsToInfluential(j)
            if e.trend == "rising" and lvl < 3 and turns and turns < 999 then e.turns_to_influential = turns end
            row.on[#row.on + 1] = e
          end
        end
      end
      out.civs[#out.civs + 1] = row
    end
  end
  return out
end

-- The Victory Progress screen's space race (victoryprogress.lua SetProjectValue: Team:GetProjectCount against
-- Project_VictoryThresholds, shown for every known civ that finished Apollo), plus what the tech tree / city
-- screens show a human about the parts: prerequisite tech, whether we have it, finished part units waiting to
-- be moved into the capital. Live t406: which part needs which tech took a raw GameInfo query to find out.
function H.spaceship_status(pid)
  local p = Players[pid]
  local team = Teams[p:GetTeam()]
  local apollo = GameInfoTypes.PROJECT_APOLLO_PROGRAM
  local out = { apollo_done = apollo and team:GetProjectCount(apollo) >= 1 or false, parts = {}, rivals = {} }
  local waiting = {}
  for u in p:Units() do
    local t = GameInfo.Units[u:GetUnitType()]
    if t and t.Type:find("^UNIT_SS_") then waiting[t.Type] = (waiting[t.Type] or 0) + 1 end
  end
  for v in GameInfo.Project_VictoryThresholds() do
    local proj = GameInfoTypes[v.ProjectType]
    local unitType = v.ProjectType:gsub("^PROJECT_", "UNIT_")
    local urow = GameInfo.Units[unitType]
    local tech = urow and urow.PrereqTech or nil
    out.parts[#out.parts + 1] = {
      part = unitType, needed = v.Threshold, in_ship = team:GetProjectCount(proj),
      built_not_delivered = waiting[unitType] or 0,
      tech = tech, have_tech = tech and team:IsHasTech(GameInfoTypes[tech]) or false }
  end
  for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
    local q = Players[i]
    if i ~= pid and q and q:IsEverAlive() and not q:IsMinorCiv() and team:IsHasMet(q:GetTeam()) then
      local qt = Teams[q:GetTeam()]
      if apollo and qt:GetProjectCount(apollo) >= 1 then
        local r = { player = i, civ = q:GetCivilizationShortDescription(), parts_in_ship = 0 }
        for v in GameInfo.Project_VictoryThresholds() do r.parts_in_ship = r.parts_in_ship + qt:GetProjectCount(GameInfoTypes[v.ProjectType]) end
        out.rivals[#out.rivals + 1] = r
      end
    end
  end
  out.note = "finished part units must be moved into the capital and added to the ship (the unit's action there)"
  return out
end
