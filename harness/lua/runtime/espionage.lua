-- Shared by earlier fragments (load order: harness/runtime_source.py MANIFEST).
local L, plain_key, plain_text = H._ns.L, H._ns.plain_key, H._ns.plain_text

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

-- espionageoverview.lua BuildPotentialModifierTT: the buildings in that city, the wonders its owner
-- holds elsewhere, and the owner's policies that change a spy's potential there. Only called in the
-- states where the stock hover prints them (a positive effective potential under established
-- surveillance, or one of our own cities) -- never as a way to read a foreign city's buildings.
function H.spy_potential_modifiers(owner_id, city)
  local owner = Players[owner_id]
  local mods = { buildings = {}, wonders = {}, policies = {} }
  if not (owner and city) then return mods end
  pcall(function()
    for b in GameInfo.Buildings() do
      local local_mod = city:GetBuildingEspionageModifier(b.ID)
      local global_mod = city:GetBuildingGlobalEspionageModifier(b.ID)
      if city:IsHasBuilding(b.ID) then
        if local_mod and local_mod ~= 0 then
          mods.buildings[#mods.buildings + 1] = { building = b.Type, name = plain_key(b.Description), pct = local_mod }
        end
      elseif owner:GetBuildingClassCount(GameInfo.BuildingClasses[b.BuildingClass].ID) > 0 then
        if global_mod and global_mod ~= 0 then
          mods.wonders[#mods.wonders + 1] = { building = b.Type, name = plain_key(b.Description), pct = global_mod }
        end
      end
    end
  end)
  pcall(function()
    for pol in GameInfo.Policies() do
      if owner:HasPolicy(pol.ID) and not owner:IsPolicyBlocked(pol.ID) then
        local m = owner:GetPolicyEspionageModifier(pol.ID)
        if m and m ~= 0 then
          mods.policies[#mods.policies + 1] = { policy = pol.Type, name = plain_key(pol.Description), pct = m }
        end
      end
    end
  end)
  for k, v in pairs(mods) do if #v == 0 then mods[k] = nil end end
  if next(mods) then return mods end
  return nil
end

-- espionageoverview.lua BuildExtraCatchSpiesModifierTT: the owner's policies that raise the chance
-- of catching spies in their cities. `who` says whose policy it is, as the two text keys do.
function H.spy_catch_modifiers(owner_id, pid)
  local owner = Players[owner_id]
  local out = {}
  if not owner then return nil end
  pcall(function()
    for pol in GameInfo.Policies() do
      if owner:HasPolicy(pol.ID) and not owner:IsPolicyBlocked(pol.ID) then
        local m = owner:GetPolicyEspionageCatchSpiesModifier(pol.ID)
        if m and m ~= 0 then
          out[#out + 1] = { policy = pol.Type, name = plain_key(pol.Description), pct = m,
                            who = owner_id == pid and "you" or plain_text(owner:GetName()) }
        end
      end
    end
  end)
  if #out > 0 then return out end
  return nil
end

-- The potential hover on the city row a spy sits in (espionageoverview.lua ApplyGenericEntrySettings,
-- the "not a city-state" branch). Three states, exactly as drawn: `potential` (surveillance established
-- and effective potential positive: the number, the base, the modifiers, the catch-spies lines),
-- `cannot_steal` (surveillance established, effective potential not positive: the base only), and
-- `once_known` (no surveillance yet: the base we once saw). A base potential of 0 is `unknown`.
-- GitLab #10. `status` is one row of Player:GetEspionageCityStatus.
function H.spy_city_potential(status, established, owner_id, city, pid)
  if not status then return { state = "unknown" } end
  local base = status.BasePotential or 0
  if base <= 0 then return { state = "unknown" } end
  if established then
    local eff = status.Potential or 0
    if eff > 0 then
      return { state = "potential", potential = eff, base_potential = base,
               modifiers = H.spy_potential_modifiers(owner_id, city),
               catch_spies = H.spy_catch_modifiers(owner_id, pid) }
    end
    return { state = "cannot_steal", base_potential = base }
  end
  return { state = "once_known", base_potential = base }
end

-- The coup button on a spy's row (espionageoverview.lua, the minor-civ branch): the percent the
-- enabled button and its confirm both print, or the reason the button is grey in the stock order --
-- dead, surveillance not yet established, no ally to overthrow, or the ally is us (GitLab #9).
function H.spy_coup(p, v, city, pid)
  local out = {}
  local owner = city and Players[city:GetOwner()]
  if not (owner and owner:IsMinorCiv()) then return out end
  local can = p.CanSpyStageCoup and p:CanSpyStageCoup(v.AgentID) or false
  local dead = v.State == "TXT_KEY_SPY_STATE_DEAD"
  local ally = -1
  pcall(function() ally = owner:GetAlly() end)
  if ally and ally >= 0 and Players[ally] then
    out.coup_ally = ally
    pcall(function() out.coup_ally_name = plain_key(Players[ally]:GetCivilizationShortDescriptionKey()) end)
  end
  out.can_stage_coup = can and not dead
  if dead then
    out.coup_why_not = "spy_dead"
  elseif not can then
    local est = false
    pcall(function() est = p:HasSpyEstablishedSurveillance(v.AgentID) end)
    if not est then
      out.coup_why_not = "surveillance_pending"
    elseif ally == -1 then
      out.coup_why_not = "no_ally"
    else
      out.coup_why_not = "we_are_ally"
    end
  else
    local okc, chance = pcall(function() return p:GetCoupChanceOfSuccess(city) end)
    if okc and type(chance) == "number" then out.coup_chance = chance end
  end
  return out
end

function H.spies(pid)
  local p = Players[pid]
  if not p.GetEspionageSpies then return {} end
  local status = {}
  pcall(function()
    for _, c in ipairs(p:GetEspionageCityStatus()) do status[c.PlayerID .. ":" .. c.CityID] = c end
  end)
  local out = {}
  for _, v in ipairs(p:GetEspionageSpies()) do
    local plot = Map.GetPlot(v.CityX, v.CityY)
    local city = plot and plot:GetPlotCity()
    local row = {
      agent_id = v.AgentID, name = L(v.Name), rank = L(v.Rank), state = L(v.State),
      state_key = v.State,  -- the raw TXT_KEY_SPY_STATE_* for programmatic checks
      turns_left = v.TurnsLeft, percent_complete = v.PercentComplete,
      is_diplomat = v.IsDiplomat or false, established_surveillance = v.EstablishedSurveillance or false,
      city_name = city and city:GetName() or nil, city_owner = city and city:GetOwner() or nil,
      can_stage_coup = p.CanSpyStageCoup and p:CanSpyStageCoup(v.AgentID) or false,
    }
    if city then
      local owner_id = city:GetOwner()
      local owner = Players[owner_id]
      if owner and owner:IsMinorCiv() then
        for k, val in pairs(H.spy_coup(p, v, city, pid)) do row[k] = val end
      elseif owner_id ~= pid then
        row.city_potential = H.spy_city_potential(status[owner_id .. ":" .. city:GetID()],
                                                  v.EstablishedSurveillance, owner_id, city, pid)
      end
    end
    out[#out + 1] = row
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
    local row = { target_player_id = v.PlayerID, city_id = v.CityID, name = v.Name,
      potential = base > 0 and base or "unknown", population = v.Population, is_minor_civ = Players[v.PlayerID]:IsMinorCiv() }
    -- RefreshMyCities: our own city's row hovers its modifiers and catch-spies lines (GitLab #10)
    if v.PlayerID == pid and base > 0 then
      local c = p:GetCityByID(v.CityID)
      row.modifiers = H.spy_potential_modifiers(pid, c)
      row.catch_spies = H.spy_catch_modifiers(pid, pid)
    end
    out[#out + 1] = row
  end
  return out
end

function H.move_spy(agent_id, target_player_id, target_city_id, as_diplomat, pid)
  Network.SendMoveSpy(pid, agent_id, target_player_id, target_city_id, as_diplomat or false)
  return { ok = true }
end

function H.stage_coup(agent_id, pid)
  local p = Players[pid]
  local spy, city
  for _, v in ipairs(p:GetEspionageSpies()) do
    if v.AgentID == agent_id then
      spy = v
      local plot = Map.GetPlot(v.CityX, v.CityY)
      city = plot and plot:GetPlotCity()
    end
  end
  if not spy then return { ok = false, err = "no spy with that agent_id" } end
  local coup = H.spy_coup(p, spy, city, pid)
  if not coup.can_stage_coup then
    return { ok = false, err = "cannot stage a coup with this spy right now",
             why_not = coup.coup_why_not or "not in a city-state", coup_ally = coup.coup_ally_name }
  end
  -- The confirm popup prints the same percent (TXT_KEY_EO_STAGE_COUP_QUESTION); the outcome arrives
  -- as a NOTIFICATION_SPY_YOU_STAGE_COUP_* notification once the engine handles the net message, so
  -- game.py waits for the notification count to grow past `held_before` and reports the new text.
  local held = 0
  pcall(function() held = p:GetNumNotifications() end)
  Network.SendStageCoup(pid, agent_id)
  return { ok = true, chance = coup.coup_chance, city = city and city:GetName() or nil,
           city_owner = city and city:GetOwner() or nil, against = coup.coup_ally_name, held_before = held }
end
