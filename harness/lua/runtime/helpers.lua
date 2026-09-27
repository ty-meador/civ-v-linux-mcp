---------------------------------------------------------------- helpers
local function L(key) -- localize a TXT_KEY
  if key == nil or key == "" then return "" end
  local ok, s = pcall(function() return Locale.ConvertTextKey(key) end) -- Locale itself may be absent (tests)
  return (ok and s) and s or tostring(key)
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

-- Shared with later fragments, which import these at their top (load order: harness/runtime_source.py MANIFEST).
H._ns.L = L
H._ns.info_type = info_type
H._ns.short = short
H._ns.move_denom = move_denom
