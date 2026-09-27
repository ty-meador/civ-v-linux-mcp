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
      if b then rows[#rows + 1] = { belief = b.Type, name = Locale.Lookup(b.ShortDescription) } end
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
  pcall(function() out.auto_purchase = H.faith_auto_purchase(pid) end)
  return out
end

-- The Religion Overview's "automatic faith purchase" pull-down (religionoverview.lua
-- RefreshAutomaticPurchase): the current selection and every entry the pull-down would list --
-- nothing; save for a Great Prophet (only while a religion can still be founded or we founded one,
-- and only before the Industrial era); each unit and building the capital could buy with faith
-- somewhere (GetUnitFaithPurchaseCost / GetBuildingFaithPurchaseCost, IsCanPurchaseAnyCity,
-- DoesUnitPassFaithPurchaseCheck), with its faith cost. GitLab #11.
function H.faith_auto_purchase(pid)
  local p = Players[pid]
  if not (p and p.GetFaithPurchaseType) then return nil end
  local FPT = FaithPurchaseTypes or {}
  local kinds = { [FPT.NO_AUTOMATIC_FAITH_PURCHASE or 0] = "nothing", [FPT.FAITH_PURCHASE_SAVE_PROPHET or 1] = "save_prophet",
                  [FPT.FAITH_PURCHASE_UNIT or 2] = "unit", [FPT.FAITH_PURCHASE_BUILDING or 3] = "building" }
  local out = { options = {} }
  local function add(kind, index, item, cost)
    out.options[#out.options + 1] = { kind = kind, index = index, item = item, faith = cost }
  end
  add("nothing", 0, nil, nil)
  local founded = -1
  pcall(function() founded = p:GetReligionCreatedByPlayer() end)
  local pantheon = ReligionTypes and ReligionTypes.RELIGION_PANTHEON or 0
  local still = 0
  pcall(function() still = Game.GetNumReligionsStillToFound() end)
  if founded > pantheon or still > 0 then
    local era, industrial = 0, 99
    pcall(function() era = p:GetCurrentEra() end)
    pcall(function() industrial = GameInfo.Eras["ERA_INDUSTRIAL"].ID end)
    if era < industrial then add("save_prophet", 0, nil, nil) end
  end
  local capital = p:GetCapitalCity()
  if capital then
    for u in GameInfo.Units() do
      local cost = 0
      pcall(function() cost = capital:GetUnitFaithPurchaseCost(u.ID, true) end)
      if cost > 0 and p:IsCanPurchaseAnyCity(false, true, u.ID, -1, YieldTypes.YIELD_FAITH)
         and p:DoesUnitPassFaithPurchaseCheck(u.ID) then
        add("unit", u.ID, u.Type, cost)
      end
    end
    for b in GameInfo.Buildings() do
      local cost = 0
      pcall(function() cost = capital:GetBuildingFaithPurchaseCost(b.ID) end)
      if cost > 0 and p:IsCanPurchaseAnyCity(false, true, -1, b.ID, YieldTypes.YIELD_FAITH) then
        add("building", b.ID, b.Type, cost)
      end
    end
  end
  local kind_id, index = p:GetFaithPurchaseType(), p:GetFaithPurchaseIndex()
  out.current = { kind = kinds[kind_id] or tostring(kind_id), index = index }
  if out.current.kind == "unit" and GameInfo.Units[index] then out.current.item = GameInfo.Units[index].Type end
  if out.current.kind == "building" and GameInfo.Buildings[index] then out.current.item = GameInfo.Buildings[index].Type end
  return out
end

-- The pull-down's selection callback: Network.SendFaithPurchase, refused unless the pair is one the
-- pull-down currently lists (the screen offers nothing else).
function H.set_faith_purchase(kind, index, pid)
  local menu = H.faith_auto_purchase(pid)
  if not menu then return { ok = false, err = "no faith purchase menu for this player" } end
  local FPT = FaithPurchaseTypes or {}
  local ids = { nothing = FPT.NO_AUTOMATIC_FAITH_PURCHASE or 0, save_prophet = FPT.FAITH_PURCHASE_SAVE_PROPHET or 1,
                unit = FPT.FAITH_PURCHASE_UNIT or 2, building = FPT.FAITH_PURCHASE_BUILDING or 3 }
  index = tonumber(index) or 0
  local chosen
  for _, o in ipairs(menu.options) do
    if o.kind == kind and ((kind == "unit" or kind == "building") and o.index == index or (kind ~= "unit" and kind ~= "building")) then
      chosen = o
      break
    end
  end
  if not chosen or ids[kind] == nil then
    local names = {}
    for _, o in ipairs(menu.options) do names[#names + 1] = o.kind .. (o.item and (":" .. o.item) or "") end
    return { ok = false, err = "not an entry of the automatic faith purchase pull-down", options = names }
  end
  Network.SendFaithPurchase(pid, ids[kind], (kind == "unit" or kind == "building") and index or 0)
  return { ok = true, selected = chosen }
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
      out[#out + 1] = { belief = b.Type, name = Locale.Lookup(b.ShortDescription) }
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
