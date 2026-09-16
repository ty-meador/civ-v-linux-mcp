-- Harness runtime injected into the InGame Lua state through the tuner.
-- Everything lives under the global table H so re-injection is idempotent.
local RUNTIME_VERSION = 13
if H and H.version == RUNTIME_VERSION then return end
local old = H
-- _enum_names is intentionally NOT carried over from `old`: it is a pure cache derived from live game
-- globals, not accumulated state, and carrying a stale (possibly wrong, e.g. built by since-fixed buggy
-- code) cache across a version bump is exactly how a real fix here silently failed to take effect once
-- already -- caught live. Only genuinely irreplaceable state (recorded events, hook closures needed to
-- Events.Remove() them) belongs in the carry-over list below.
H = { version = RUNTIME_VERSION, events = old and old.events or {}, event_seq = old and old.event_seq or 0,
      cursor = old and old.cursor or 0, hook_fns = old and old.hook_fns or {}, _enum_names = {} }

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

-- City ranged attack: the game's own citybannermanager.lua/worldview.lua CityBombard() flow --
-- UI.SelectCity + Game.SelectedCitiesGameNetMessage(GAMEMESSAGE_DO_TASK, TASK_RANGED_ATTACK, x, y) --
-- validated first by city:CanRangeStrike()/CanRangeStrikeAt(), which is exactly the check an earlier
-- unguarded raw-Lua probe for this skipped, crashing the game outright.
function H.city_ranged_attack(city_id, x, y, pid)
  local p = Players[pid]
  local city = p:GetCityByID(city_id)
  if not city then return { ok = false, err = "no such city" } end
  if not city:CanRangeStrike() then return { ok = false, err = "city cannot range strike (no ranged combat / already struck this turn?)" } end
  if not city:CanRangeStrikeAt(x, y, true, true) then return { ok = false, err = "cannot strike that plot from this city" } end
  UI.SelectCity(city)
  Game.SelectedCitiesGameNetMessage(GameMessageTypes.GAMEMESSAGE_DO_TASK, TaskTypes.TASK_RANGED_ATTACK, x, y)
  return { ok = true }
end

-- Social policies: same Network.SendUpdatePolicies(id, isPolicy, true) call the confirm-yes button in
-- socialpolicypopup.lua makes. isPolicy=true adopts a policy within an unlocked branch; isPolicy=false
-- unlocks a branch itself (both share the same underlying call with the id field reused for either).
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
function H.found_pantheon(belief_name, pid)
  local id = GameInfoTypes[belief_name]
  if id == nil then return { ok = false, err = "unknown belief " .. tostring(belief_name) } end
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
function H.propose_deal(other_player, items, pid)
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

-- Trade routes: Game.SelectionListGameNetMessage with MISSION_ESTABLISH_TRADE_ROUTE / _PLUNDER_TRADE_ROUTE
-- (confirmed in ui/ingame/popups/chooseinternationaltraderoutepopup.lua, declarewarpopup.lua), same shape
-- as any other unit mission push. dest is a plot index (Map.GetPlot(x,y):GetPlotIndex()), trade_type is
-- the domain-specific trade type id from the available-routes list.
function H.establish_trade_route(unit_id, dest_x, dest_y, trade_type, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  local plot = Map.GetPlot(dest_x, dest_y)
  if not plot then return { ok = false, err = "no such plot" } end
  UI.SelectUnit(u)
  Game.SelectionListGameNetMessage(GameMessageTypes.GAMEMESSAGE_PUSH_MISSION, MissionTypes.MISSION_ESTABLISH_TRADE_ROUTE,
    plot:GetPlotIndex(), trade_type, 0, false, nil)
  return { ok = true }
end

function H.plunder_trade_route(unit_id, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  UI.SelectUnit(u)
  Game.SelectionListGameNetMessage(GameMessageTypes.GAMEMESSAGE_PUSH_MISSION, MissionTypes.MISSION_PLUNDER_TRADE_ROUTE, -1, -1, 0, false, false)
  return { ok = true }
end

function H.available_trade_routes(pid)
  local p = Players[pid]
  if not p.GetTradeRoutesAvailable then return {} end
  local out = {}
  for _, r in ipairs(p:GetTradeRoutesAvailable()) do
    out[#out + 1] = r
  end
  return out
end

-- Espionage: read-only for now (see docs/NOTES.md -- no MissionTypes.MISSION_*SPY* constants were found in
-- this build's Lua, so spy movement/missions likely use a different, not-yet-researched mechanism; do not
-- guess at a write call here).
function H.spies(pid)
  local p = Players[pid]
  return { count = p.GetNumSpies and p:GetNumSpies() or 0 }
end

function H.turn_state(pid)
  local p = Players[pid]
  local net = Game.IsNetworkMultiPlayer()
  local sent = net and Network.HasSentNetTurnComplete() or false
  local mode = PreGame.IsHotSeatGame() and "hotseat" or (net and (PreGame.IsInternetGame() and "internet" or "lan")) or "single"
  local gs = Game.GetGameState()
  local blocking = p:GetEndTurnBlockingType()
  return {
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
    alive = p:IsAlive(),
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
