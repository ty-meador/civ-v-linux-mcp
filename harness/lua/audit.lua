-- Passive event audit (debug tool, not part of the player-facing runtime): records every firing of a
-- broad list of Events.* / GameEvents.* with its raw arguments, unfiltered, so a human's notes on what
-- they saw on screen can be reconciled against what actually fired. Read-only: no game state changes.
-- Unfiltered means it is NOT human-visible-safe: drain it to a file (scripts/event_audit.py) for offline
-- reconciliation; never surface it through an MCP read. Positional spam (UnitMove/SetXY) is left out.
local old = HA
HA = { log = old and old.log or {}, seq = old and old.seq or 0, fns = old and old.fns or {}, missing = {} }

local UI_EVENTS = {
  "ActivePlayerTurnStart", "ActivePlayerTurnEnd", "GameplaySetActivePlayer", "RemotePlayerTurnEnd",
  "AIProcessingStartedForPlayer", "AIProcessingEndedForPlayer",
  "RunCombatSim", "EndCombatSim", "SerialEventUnitSetDamage", "SerialEventUnitCreated", "SerialEventUnitDestroyed",
  "SerialEventCityCreated", "SerialEventCityDestroyed", "SerialEventCityCaptured", "SerialEventCityPopulationChanged",
  "SerialEventCitySetDamage", "SerialEventImprovementCreated", "SerialEventImprovementDestroyed",
  "SerialEventGameMessagePopup", "SerialEventGameMessagePopupShown", "SerialEventGameMessagePopupProcessed",
  "NotificationAdded", "NotificationRemoved", "GameplayAlertMessage", "AddPopupTextEvent",
  "AILeaderMessage", "LeavingLeaderViewMode", "WarStateChanged", "TechAcquired", "SerialEventEraChanged",
  "NaturalWonderRevealed", "EventPoliciesDirty", "SerialEventEndTurnDirty", "EndGameShow", "GameMessageChat",
}
local GAME_EVENTS = {
  "PlayerDoTurn", "TeamTechResearched", "TeamSetHasTech", "TeamMeet", "PlayerAdoptPolicy", "PlayerAdoptPolicyBranch",
  "PlayerCityFounded", "CityCaptureComplete", "CityTrained", "CityConstructed", "CityCreated", "CityBoughtPlot",
  "SetPopulation", "GreatPersonExpended", "PantheonFounded", "ReligionFounded", "ReligionEnhanced",
  "MinorFriendsChanged", "MinorAlliesChanged", "UnitPrekill", "UnitGetSpecialExploreTarget",
}

local function flat(v)
  local t = type(v)
  if t == "number" or t == "string" or t == "boolean" then return v end
  if t == "table" then
    local o = {}
    for k, x in pairs(v) do
      local tx = type(x)
      if tx == "number" or tx == "string" or tx == "boolean" then o[tostring(k)] = x end
    end
    return o
  end
  return "<" .. t .. ">"
end

local function install(src, tbl, names)
  for _, name in ipairs(names) do
    local key = src .. "." .. name
    local ok, ev = pcall(function() return tbl[name] end)
    if ok and ev then
      if HA.fns[key] then pcall(function() ev.Remove(HA.fns[key]) end) end
      local fn = function(...)
        local args = {}
        for i = 1, select("#", ...) do args[i] = flat((select(i, ...))) end
        HA.seq = HA.seq + 1
        HA.log[#HA.log + 1] = { seq = HA.seq, turn = Game.GetGameTurn(), active = Game.GetActivePlayer(),
                                clock = os and os.clock and os.clock() or nil, ev = key, args = args }
        if #HA.log > 5000 then table.remove(HA.log, 1) end
      end
      if pcall(function() ev.Add(fn) end) then HA.fns[key] = fn else HA.missing[#HA.missing + 1] = key end
    else
      HA.missing[#HA.missing + 1] = key
    end
  end
end
install("Events", Events, UI_EVENTS)
if GameEvents then install("GameEvents", GameEvents, GAME_EVENTS) else HA.missing[#HA.missing + 1] = "GameEvents(table)" end

function HA.take()
  local out = HA.log
  HA.log = {}
  return out
end
