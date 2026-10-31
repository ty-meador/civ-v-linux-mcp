---------------------------------------------------------------- great people: yields, withheld missions, outcomes
-- A Great Person is a once-in-many-turns resource. The unit panel lists the missions the engine allows right
-- now and nothing about the ones it withholds: a Great Writer with every writing slot full showed the treatise
-- alone, a Great Musician at home showed nothing of the concert tour (GitLab #142, Maya t207-t234). The stock
-- panel greys those buttons out and prints `DisabledHelp` under them; this file does the same in words the
-- seat can act on -- how many slots are filled, where the nearest plot that qualifies is.
local L = H._ns.L

-- The Great Person missions a unit CLASS has, from the Units table columns the engine reads for them
-- (CIV5Units.xml and the expansions' schemas). CanStartMission(mission, -1, -1, bTestVisible=true) is not this
-- test: its visible form says yes to a Warrior for the great-person missions.
local CLASS_MISSIONS = {
  MISSION_CREATE_GREAT_WORK = function(ut) return ut.GreatWorkType ~= nil end,
  MISSION_ONE_SHOT_TOURISM = function(ut) return (ut.OneShotTourism or 0) > 0 end,
  MISSION_GIVE_POLICIES = function(ut) return (ut.BaseCultureTurnsToCount or 0) > 0 end,
  MISSION_TRADE = function(ut) return (ut.BaseGold or 0) > 0 end,
  MISSION_BUY_CITY_STATE = function(ut) return ut.CanBuyCityState == true or ut.CanBuyCityState == 1 end,
  MISSION_HURRY = function(ut) return (ut.BaseHurry or 0) > 0 end,
  MISSION_DISCOVER = function(ut) return (ut.BaseBeakersTurnsToCount or 0) > 0 end,
  MISSION_GOLDEN_AGE = function(ut) return (ut.GoldenAgeTurns or 0) > 0 end,
  MISSION_CULTURE_BOMB = function(ut) return (ut.CultureBombRadius or 0) > 0 end,
  MISSION_SELL_EXOTIC_GOODS = function(ut) return (ut.NumExoticGoods or 0) > 0 end,
  MISSION_FOUND_RELIGION = function(ut) return ut.FoundReligion == true or ut.FoundReligion == 1 end,
  MISSION_SPREAD_RELIGION = function(ut) return (ut.ReligionSpreads or 0) > 0 end,
  MISSION_REMOVE_HERESY = function(ut) return ut.RemoveHeresy == true or ut.RemoveHeresy == 1 end,
}

-- Which of the missions above this unit's class has: { MISSION_X = true, ... } (empty for a Warrior).
function H.gp_class_missions(u)
  local out = {}
  local ut = GameInfo and GameInfo.Units and u.GetUnitType and GameInfo.Units[u:GetUnitType()]
  if not ut then return out end
  for mission, has in pairs(CLASS_MISSIONS) do
    local ok, v = pcall(has, ut)
    if ok and v then out[mission] = true end
  end
  return out
end

-- Every Great Work slot of one type in my empire: how many, how many filled, and the buildings that carry
-- such a slot (the stock Create Great Work disabled line says "a slot of the appropriate type available
-- somewhere in your empire" and no more; the seat needs the count and what to build).
function H.great_work_slot_census(pid, slot_type)
  local out = { slot_type = slot_type, total = 0, filled = 0, free = 0, buildings = {} }
  local p = Players[pid]
  if not (p and GameInfo and GameInfo.Buildings) then return out end
  local carriers = {}
  for b in GameInfo.Buildings() do
    if b.GreatWorkSlotType == slot_type and (b.GreatWorkCount or 0) > 0 then
      carriers[#carriers + 1] = b
      -- a wonder is one civ's once; the line names the buildings any city may raise, cheapest first
      local cls = GameInfo.BuildingClasses and GameInfo.BuildingClasses[b.BuildingClass]
      local wonder = cls and ((cls.MaxGlobalInstances or -1) > 0 or (cls.MaxPlayerInstances or -1) > 0)
      if not wonder then out.buildings[#out.buildings + 1] = { name = L(b.Description), cost = b.Cost or 0 } end
    end
  end
  table.sort(out.buildings, function(a, b) return a.cost < b.cost end)
  for i, row in ipairs(out.buildings) do out.buildings[i] = row.name end
  for c in p:Cities() do
    for _, b in ipairs(carriers) do
      if c:IsHasBuilding(b.ID) then
        local cls = GameInfo.BuildingClasses[b.BuildingClass].ID
        for i = 0, b.GreatWorkCount - 1 do
          out.total = out.total + 1
          local work = c:GetBuildingGreatWork(cls, i)
          if work and work >= 0 then out.filled = out.filled + 1 end
        end
      end
    end
  end
  out.free = out.total - out.filled
  return out
end

-- Who owns a plot, for a mission's soil test: "unowned", "mine", "a city-state", "a major civ", with the
-- owner's id and name when there is one.
local function soil(plot, pid)
  local owner = plot and plot:GetOwner() or -1
  if owner == nil or owner < 0 then return { kind = "unowned" } end
  local o = Players[owner]
  local name = o and o.GetCivilizationShortDescription and L(o:GetCivilizationShortDescription()) or nil
  if owner == pid then return { kind = "mine", id = owner, name = name } end
  if o and o.IsMinorCiv and o:IsMinorCiv() then return { kind = "city-state", id = owner, name = name } end
  return { kind = "major", id = owner, name = name }
end

local function at_war(pid, other)
  local ok, v = pcall(function() return Teams[Players[pid]:GetTeam()]:IsAtWar(Players[other]:GetTeam()) end)
  return ok and v == true
end

-- The nearest revealed plot around the unit whose owner passes `accept(owner_pid)`, within `radius`: the plot,
-- its owner's name and the distance. nil when none is in reach of the scan.
local function nearest_plot(u, pid, radius, accept)
  local ux, uy = u:GetX(), u:GetY()
  local team = Players[pid]:GetTeam()
  local best
  for dx = -radius, radius do
    for dy = -radius, radius do
      local q = Map.GetPlotXY and Map.GetPlotXY(ux, uy, dx, dy) or nil
      if q and q:IsRevealed(team, false) then
        local owner = q:GetOwner()
        if owner and owner >= 0 and owner ~= pid and accept(owner) then
          local d = Map.PlotDistance(ux, uy, q:GetX(), q:GetY())
          if not best or d < best.distance then
            local o = Players[owner]
            best = { x = q:GetX(), y = q:GetY(), distance = d, owner = owner,
                     name = o and o.GetCivilizationShortDescription and L(o:GetCivilizationShortDescription()) or nil }
          end
        end
      end
    end
  end
  return best
end

local function here_text(s)
  if s.kind == "unowned" then return "unowned" end
  if s.kind == "mine" then return "yours" end
  return (s.name or "?") .. "'s (" .. s.kind .. ")"
end

-- Why the engine withholds one of this unit's class missions right now, as a row for `missing`:
-- { mission, why, ... facts }. The soil missions name the nearest plot that qualifies; the Great Work says
-- how many slots are filled and what carries one; anything else gets the stock button's disabled line.
function H.gp_withheld(u, action, pid)
  local mission = action.Type
  local row = { mission = mission }
  local plot = u:GetPlot()
  local s = soil(plot, pid)
  if u:MovesLeft() <= 0 then
    row.why = "no moves left this turn; give the mission next turn before moving"
    return row
  end
  if mission == "MISSION_CREATE_GREAT_WORK" then
    local slot_id = u.GetGreatWorkSlotType and u:GetGreatWorkSlotType() or -1
    local slot = GameInfo and GameInfo.GreatWorkSlots and GameInfo.GreatWorkSlots[slot_id]
    local census = slot and H.great_work_slot_census(pid, slot.Type) or nil
    row.slots = census
    if census and census.free <= 0 then
      local kind = slot.Type:gsub("^GREAT_WORK_SLOT_", ""):lower():gsub("_", "/")   -- literature, music, art/artifact
      row.why = "no free " .. kind .. " Great Work slot in the empire (" .. census.filled .. "/" .. census.total .. " filled)"
      if #census.buildings > 0 then
        row.why = row.why .. "; build one of: " .. table.concat(census.buildings, ", ", 1, math.min(4, #census.buildings))
      end
      row.why = row.why .. "; or spend the unit on its other mission"
    else
      row.why = "stand in or next to one of your cities"
      pcall(function()
        local c = Players[pid]:GetCityOfClosestGreatWorkSlot(u:GetX(), u:GetY(), slot_id)
        if c then row.nearest = { city = c:GetName(), x = c:GetX(), y = c:GetY() } end
      end)
    end
  elseif mission == "MISSION_ONE_SHOT_TOURISM" then
    row.why = "needs a plot owned by another major civ (the tour plays to the plot's owner); here: " .. here_text(s)
    row.nearest = nearest_plot(u, pid, 10, function(o)
      local p = Players[o]
      return p and p:IsAlive() and not (p.IsMinorCiv and p:IsMinorCiv())
    end)
  elseif mission == "MISSION_TRADE" or mission == "MISSION_BUY_CITY_STATE" then
    row.why = "needs a plot inside a city-state's borders you are not at war with; here: " .. here_text(s)
    row.nearest = nearest_plot(u, pid, 10, function(o)
      local p = Players[o]
      return p and p:IsAlive() and p.IsMinorCiv and p:IsMinorCiv() and not at_war(pid, o)
    end)
  elseif mission == "MISSION_HURRY" then
    row.why = "stand in one of your cities; here: " .. here_text(s)
  else
    local text = action.DisabledHelp and action.DisabledHelp ~= "" and L(action.DisabledHelp) or nil
    row.why = text or "the engine withholds it on this plot (reference(section='actions') has the rule)"
  end
  return row
end

-- What a concert tour from this plot would do: the tourism, who receives it, the share every other civ gets.
-- Read before MISSION_ONE_SHOT_TOURISM so the mission's reply can say what happened (the engine's reply is a
-- bare ok and the unit is gone).
function H.concert_tour_preview(unit_id, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  local ut = GameInfo and GameInfo.Units and GameInfo.Units[u:GetUnitType()]
  local out = { ok = true, tourism = u.GetBlastTourism and u:GetBlastTourism() or nil,
                others_percent = ut and ut.OneShotTourismPercentOthers or nil }
  local s = soil(u:GetPlot(), pid)
  if s.kind == "major" then
    out.to = { id = s.id, civ = s.name }
  else
    out.legal_here = false
    out.here = here_text(s)
  end
  return out
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
  elseif mission == "MISSION_HURRY" then
    local y = { production = get("GetHurryProduction", plot) }
    -- GitLab #118 (Maya t152): the engine caps a hurry at what the item still needs (Workshop: 30 of 80 read as
    -- "50"); say so, or the Great Engineer looks weak and the rest of the charge is lost unnoticed.
    pcall(function()
      local city = plot and plot:GetPlotCity()
      if city and y.production then
        local remaining = city:GetProductionNeeded() - city:GetProduction()
        if remaining >= 0 and y.production >= remaining then
          y.capped_by_item, y.item_needs = true, remaining
          y.note = "capped: the hurry gives only what the current item still needs and the rest of the charge is lost; "
                .. "set a bigger item first, or hurry in a city whose item needs more"
        end
      end
    end)
    return y
  elseif mission == "MISSION_TRADE" then
    return { gold = get("GetTradeGold", plot), influence = get("GetTradeInfluence", plot) }
  elseif mission == "MISSION_GIVE_POLICIES" then return { culture = get("GetGivePoliciesCulture") }
  elseif mission == "MISSION_ONE_SHOT_TOURISM" then return { tourism = get("GetBlastTourism") }
  elseif mission == "MISSION_GOLDEN_AGE" then return { golden_age_turns = get("GetGoldenAgeTurns") }
  elseif mission == "MISSION_SPREAD_RELIGION" then
    -- Which religion this charge would spread: the unit's own, which the panel prints beside its name.
    local y = { spreads_left = get("GetSpreadsLeft") }
    local rel = -1
    pcall(function()
      rel = u.GetReligion and u:GetReligion() or -1
      if rel and rel >= 0 and Game.GetReligionName then y.religion = H.L(Game.GetReligionName(rel)) end
    end)
    -- GitLab #112 (Maya t119): a charge spent on a city that already followed the religion bought nothing. The
    -- target the charge would hit: the city on or beside the unit's plot, with its majority and followers.
    pcall(function()
      local here = u:GetPlot()
      local city = here:GetPlotCity()
      if not city then
        for d = 0, 5 do
          local q = Map.PlotDirection(here:GetX(), here:GetY(), d)
          if q and q:IsCity() then city = q:GetPlotCity(); break end
        end
      end
      if city then
        local maj = city:GetReligiousMajority()
        local t = { city = city:GetName(), owner = city:GetOwner() }
        if maj and maj >= 0 then t.majority = H.L(Game.GetReligionName(maj)); t.followers_majority = city:GetNumFollowers(maj) end
        if rel and rel >= 0 then
          t.followers_mine = city:GetNumFollowers(rel)
          t.already_majority = (maj == rel) or false
          if t.already_majority then t.note = "this city already follows the religion: the charge would buy little or nothing" end
        end
        y.target = t
      end
    end)
    return y
  end
end
