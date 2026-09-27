-- Shared by earlier fragments (load order: harness/runtime_source.py MANIFEST).
local L, plain_key, plain_text = H._ns.L, H._ns.plain_key, H._ns.plain_text

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
  local swap
  pcall(function() swap = H.great_work_swap(pid) end)
  return { ok = true, cities = cities, tourism_modifiers = modifiers, swap = swap }
end

-- Great-work classes as cultureoverview.lua's swap tab numbers them (Game.GetGreatWorkClass):
-- 1 art, 2 artifact, 3 writing, 4 music (music's pull-down is commented out in stock).
local GW_CLASSES = { [1] = "art", [2] = "artifact", [3] = "writing", [4] = "music" }
local GW_CLASS_IDS = { art = 1, artifact = 2, writing = 3, music = 4 }

local function great_work_row(index, viewer)
  if index == nil or index < 0 then return nil end
  local row = { work_id = index }
  pcall(function() row.name = plain_text(L(Game.GetGreatWorkName(index))) end)
  pcall(function() row.era = plain_text(L(Game.GetGreatWorkEraShort(index))) end)
  pcall(function() row.creator = Game.GetGreatWorkCreator(index) end)
  pcall(function() row.class = GW_CLASSES[Game.GetGreatWorkClass(index)] end)
  pcall(function() row.tooltip = plain_text(Game.GetGreatWorkTooltip(index, viewer)) end)
  return row
end

-- The Culture Overview's swap tab (cultureoverview.lua RefreshSwappingItems / RefreshSwapGreatWorks):
-- `ours` is the work we have put up per class (GetSwappableGreatWriting/Art/Artifact) and the
-- pull-down each slot offers (our works of that class, plus "clear"); `theirs` is every other civ's
-- offer (Player:GetOthersGreatWorks), which the engine already limits to civs we have met. GitLab #12.
function H.great_work_swap(pid)
  local p = Players[pid]
  if not (p and p.GetOthersGreatWorks and p.GetSwappableGreatWriting) then return nil end
  local ours = {}
  local getters = { writing = "GetSwappableGreatWriting", art = "GetSwappableGreatArt", artifact = "GetSwappableGreatArtifact" }
  for class, getter in pairs(getters) do
    local slot = { offered = nil, candidates = {} }
    local okv, idx = pcall(function() return p[getter](p) end)
    if okv and type(idx) == "number" and idx >= 0 then slot.offered = great_work_row(idx, pid) end
    pcall(function()
      for _, w in ipairs(p:GetGreatWorks(GW_CLASS_IDS[class])) do
        local r = great_work_row(w.Index, pid)
        if r then
          pcall(function() r.theming_bonus = Game.GetGreatWorkCurrentThemingBonus(w.Index) end)
          slot.candidates[#slot.candidates + 1] = r
        end
      end
    end)
    ours[class] = slot
  end
  local theirs = {}
  pcall(function()
    for _, v in ipairs(p:GetOthersGreatWorks()) do
      local o = Players[v.iPlayer]
      local row = { player = v.iPlayer,
                    civ = o and plain_key(o:GetCivilizationShortDescriptionKey()) or nil }
      row.writing = great_work_row(v.WritingIndex, pid)
      row.art = great_work_row(v.ArtIndex, pid)
      row.artifact = great_work_row(v.ArtifactIndex, pid)
      if row.writing or row.art or row.artifact then theirs[#theirs + 1] = row end
    end
  end)
  return { ours = ours, theirs = theirs }
end

-- The pull-down's selection: Network.SendSetSwappableGreatWork(player, class, index), index -1 to
-- clear the spot. Only a work of ours of that class (the pull-down's entries) is accepted.
function H.set_swappable_great_work(class, work_id, pid)
  local cid = GW_CLASS_IDS[class]
  if not cid or class == "music" then return { ok = false, err = "class must be writing, art or artifact" } end
  work_id = tonumber(work_id) or -1
  if work_id >= 0 then
    local ok_mine = false
    pcall(function()
      for _, w in ipairs(Players[pid]:GetGreatWorks(cid)) do if w.Index == work_id then ok_mine = true end end
    end)
    if not ok_mine then return { ok = false, err = "not one of our " .. class .. " works (see culture_works.swap.ours." .. class .. ".candidates)" } end
  end
  Network.SendSetSwappableGreatWork(pid, cid, work_id)
  return { ok = true, class = class, work_id = work_id >= 0 and work_id or nil, cleared = work_id < 0 or nil }
end

-- The Swap button (DoSwap): Network.SendSwapGreatWorks(us, ours, partner, theirs). Enabled only when
-- `theirs` is an offer on the tab and we have a work of the same class put up (CheckAvailableSwap).
function H.swap_great_works(their_work_id, pid)
  local p = Players[pid]
  their_work_id = tonumber(their_work_id) or -1
  local partner, cls
  pcall(function()
    for _, v in ipairs(p:GetOthersGreatWorks()) do
      if v.WritingIndex == their_work_id then partner, cls = v.iPlayer, "writing" end
      if v.ArtIndex == their_work_id then partner, cls = v.iPlayer, "art" end
      if v.ArtifactIndex == their_work_id then partner, cls = v.iPlayer, "artifact" end
    end
  end)
  if not partner then return { ok = false, err = "that work is not on offer (see culture_works.swap.theirs)" } end
  local getters = { writing = "GetSwappableGreatWriting", art = "GetSwappableGreatArt", artifact = "GetSwappableGreatArtifact" }
  local mine = -1
  pcall(function() mine = p[getters[cls]](p) end)
  if not (type(mine) == "number" and mine >= 0) then
    return { ok = false, err = "we have no " .. cls .. " put up for swapping (set_swappable_great_work first)", class = cls }
  end
  Network.SendSwapGreatWorks(pid, mine, partner, their_work_id)
  return { ok = true, ours = mine, partner = partner, theirs = their_work_id, class = cls }
end

-- Every great work we hold, keyed by work id: which city and building it sits in, and the
-- tooltip the Culture Overview prints for it. Used to say what MISSION_CREATE_GREAT_WORK actually
-- made -- a Great Person is a once-in-many-turns resource and the mission reply used to be a bare
-- {ok, consumed} (live t215: "Martin Fierro" landed in Te-Moak's Amphitheater and nothing said so).
function H.great_work_index(pid)
  local out = {}
  for c in Players[pid]:Cities() do
    for b in GameInfo.Buildings() do
      if b.GreatWorkCount > 0 and c:IsHasBuilding(b.ID) then
        local cls = GameInfo.BuildingClasses[b.BuildingClass].ID
        for i = 0, b.GreatWorkCount - 1 do
          local work = c:GetBuildingGreatWork(cls, i)
          if work and work >= 0 then
            out[tostring(work)] = { work_id = work, city = c:GetName(), city_id = c:GetID(),
                                    building = b.Type, slot_type = b.GreatWorkSlotType, slot = i,
                                    name = H.L(Game.GetGreatWorkName(work)),
                                    tooltip = Game.GetGreatWorkTooltip(work, pid) }
          end
        end
      end
    end
  end
  return out
end
