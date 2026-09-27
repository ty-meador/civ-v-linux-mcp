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
  if p:IsPolicyBranchUnlocked(id) then
    return { ok = false, err = "this branch is already unlocked; choose_policy adopts inside it", unlocked = true }
  end
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
        options[#options + 1] = { unit = u.Type, name = H.L(u.Description),
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
