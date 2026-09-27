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
  pcall(function() out.gift_tile_improvement = H.gift_tile_improvement_status(minor_id, pid) end)
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

-- Stock UI: citystatediplopopup.lua's "Gift Improvement" button (allies only, greyed otherwise) enters
-- INTERFACEMODE_GIFT_TILE_IMPROVEMENT; ingame.lua HighlightImprovableCityStatePlots then highlights every
-- plot within GameDefines.MINOR_CIV_RESOURCE_SEARCH_RADIUS of the city-state's capital where
-- CanMajorGiftTileImprovementAtPlot is true, and clicking one calls Game.DoMinorGiftTileImprovement.
-- The engine also greys the button when no plot within that radius of the capital passes
-- CanMajorGiftTileImprovementAtPlot. Live t241: Sidon (ally, 232 gold against a 200 cost) owned three
-- resource tiles -- a Wine plantation, a Bison camp, and a mine over Aluminum we had not revealed --
-- every one already improved, and the button stayed grey. A human works that out by looking at the
-- city-state's tiles, so the reason is told the same way: the resource tiles of theirs we can see,
-- and whether each is improved. A resource our team has not revealed is not named (describe_plot's
-- fog rules), so a hidden strategic under a plain mine reads as no resource at all, as on the map.
local function gift_resource_tiles(o, minor_id, team)
  local cap = o:GetCapitalCity()
  if not cap then return nil end
  local r = GameDefines.MINOR_CIV_RESOURCE_SEARCH_RADIUS or 3
  local tiles = {}
  for dx = -r, r do for dy = -r, r do
    local plot = Map.PlotXYWithRangeCheck(cap:GetX(), cap:GetY(), dx, dy, r)
    if plot then
      local e = H.describe_plot(plot, team)
      if e and e.resource and e.owner == minor_id then tiles[#tiles + 1] = e end
    end
  end end
  return tiles, r, cap
end

local function gift_greyed_reason(o, minor_id, name, team)
  local tiles, r = gift_resource_tiles(o, minor_id, team)
  if not tiles then return "this city-state has no capital" end
  if #tiles == 0 then
    return string.format("the engine finds no tile of %s's to improve: none of its revealed tiles " ..
      "within %d hexes of the capital has a resource", name, r), tiles, r
  end
  local improved, rows = 0, {}
  for _, e in ipairs(tiles) do
    if e.improvement then improved = improved + 1 end
    rows[#rows + 1] = string.format("%s %s at (%d,%d)", e.resource:lower(),
      e.improvement and e.improvement:lower() or "unimproved", e.x, e.y)
  end
  local list = table.concat(rows, ", ")
  if improved == #tiles then
    return string.format("%s has no tile left to improve: %s revealed resource tile%s within %d hexes " ..
      "of the capital %s already improved (%s)", name, #tiles == 1 and "its one" or ("its " .. #tiles),
      #tiles == 1 and "" or "s", r, #tiles == 1 and "is" or "are", list), tiles, r
  end
  return string.format("the engine finds no tile of %s's it would let us improve; its revealed resource " ..
    "tiles within %d hexes of the capital: %s", name, r, list), tiles, r
end

function H.gift_tile_improvement_status(minor_id, pid)
  local o, p = Players[minor_id], Players[pid]
  local gold, cost, can = p:GetGold(), nil, false
  pcall(function() cost = o:GetGiftTileImprovementCost(pid) end)
  pcall(function() can = o:CanMajorGiftTileImprovement(pid) and true or false end)
  local allied = o.IsAllies and o:IsAllies(pid) and true or false
  local out = { can = can, cost = cost, gold = gold, allied = allied }
  if not can then
    if not allied then out.why_not = "only this city-state's ally can gift a tile improvement"
    elseif cost and gold < cost then
      out.why_not = string.format("costs %d gold, the treasury has %d", cost, gold)
    else
      local okr, why, tiles, r = pcall(gift_greyed_reason, o, minor_id, o:GetName(), p:GetTeam())
      if okr and why then
        out.why_not, out.resource_tiles, out.search_radius = why, tiles, r
      else out.why_not = "the button is greyed out" end
    end
  end
  return out
end

function H.gift_tile_improvement_options(minor_id, pid)
  local o, p = Players[minor_id], Players[pid]
  if not o or not Teams[p:GetTeam()]:IsHasMet(o:GetTeam()) then
    return { ok = false, err = "have not met this player yet" }
  end
  if not o:IsMinorCiv() or not o:IsAlive() then return { ok = false, err = "not a living city-state" } end
  if Teams[p:GetTeam()]:IsAtWar(o:GetTeam()) then return { ok = false, err = "at war with this city-state" } end
  local out = H.gift_tile_improvement_status(minor_id, pid)
  out.ok, out.minor_id, out.name = true, minor_id, o:GetName()
  out.influence = o:GetMinorCivFriendshipWithMajor(pid)
  -- Greyed button: the interface mode never opens, so no hex is highlighted and there is nothing to list.
  if not out.can then return out end
  local cap = o:GetCapitalCity()
  if not cap then
    out.plots, out.why_not = {}, "this city-state has no capital"
    return out
  end
  local team = p:GetTeam()
  local r = GameDefines.MINOR_CIV_RESOURCE_SEARCH_RADIUS or 3
  out.search_radius = r
  out.capital = { name = cap:GetName(), x = cap:GetX(), y = cap:GetY() }
  local plots = {}
  for dx = -r, r do for dy = -r, r do
    local plot = Map.PlotXYWithRangeCheck(cap:GetX(), cap:GetY(), dx, dy, r)
    if plot then
      local x, y = plot:GetX(), plot:GetY()
      local okc, legal = pcall(function() return o:CanMajorGiftTileImprovementAtPlot(pid, x, y) end)
      if okc and legal then
        -- The stock highlight says only "this hex is a legal target"; an unrevealed one gets that and
        -- nothing else, because describe_plot's fog rules would otherwise be bypassed here.
        plots[#plots + 1] = H.describe_plot(plot, team) or { x = x, y = y, vis = false, revealed = false }
      end
    end
  end end
  out.plots = plots
  return out
end

function H.gift_tile_improvement(minor_id, x, y, pid)
  if Game.GetActivePlayer() ~= pid then return { ok = false, err = "this seat is not active" } end
  local opts = H.gift_tile_improvement_options(minor_id, pid)
  if not opts.ok then return opts end
  if not opts.can then return { ok = false, err = opts.why_not, options = opts } end
  local found
  for _, e in ipairs(opts.plots or {}) do if e.x == x and e.y == y then found = e end end
  if not found then
    return { ok = false, options = opts, err = string.format(
      "(%d,%d) is not one of the %d plots this city-state would take an improvement on",
      x, y, #(opts.plots or {})) }
  end
  local p = Players[pid]
  local before = { gold = p:GetGold(), influence = opts.influence }
  Game.DoMinorGiftTileImprovement(pid, minor_id, x, y)
  local after = { gold = p:GetGold(),
                  influence = Players[minor_id]:GetMinorCivFriendshipWithMajor(pid) }
  local plot = Map.GetPlot(x, y)
  if plot then
    local imp = plot:GetImprovementType()
    if imp and imp >= 0 then after.improvement = short(info_type(GameInfo.Improvements, imp)) end
  end
  return { ok = true, minor_id = minor_id, name = opts.name, x = x, y = y, cost = opts.cost,
           plot = found, before = before, after = after, gold_spent = before.gold - after.gold }
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
  local mine = o.GetMinorCivFriendshipWithMajor and o:GetMinorCivFriendshipWithMajor(pid) or 0
  -- How much more Influence the ally tooltip is asking for (nil when already ours). The tiers use it
  -- so "would this gift actually buy the alliance?" is answered before the gold is spent: live t231 a
  -- 1000-gold large gift moved Sidon from 5 to 80 and left Ethiopia ally at 83, and nothing on the
  -- tier said it would land 4 short.
  local ally_gap = (function()
    local iAlly = o.GetAlly and o:GetAlly() or -1
    if iAlly == pid then return nil end
    if iAlly == nil or iAlly == -1 then return (GameDefines.FRIENDSHIP_THRESHOLD_ALLIES or 60) - mine end
    return o:GetMinorCivFriendshipWithMajor(iAlly) - mine + 1
  end)()
  local function tier(amount)
    local inf = o.GetFriendshipFromGoldGift and o:GetFriendshipFromGoldGift(pid, amount) or nil
    local row = { amount = amount, friendship = inf, affordable = gold >= amount }
    if inf then
      row.influence_after = mine + inf
      if ally_gap == nil then row.makes_ally = true            -- already ours; the gift only extends it
      else
        row.makes_ally = inf >= ally_gap
        if not row.makes_ally then row.short_by = ally_gap - inf end
      end
    end
    return row
  end
  return {
    ok = true, id = minor_id,
    gold = gold,
    friendship = mine,
    friends = o.IsFriends and o:IsFriends(pid) or false,
    allied = o.IsAllies and o:IsAllies(pid) or false,
    at_war = myTeam:IsAtWar(o:GetTeam()) or false,
    small = tier(small), medium = tier(med), large = tier(large),
    -- Human-visible only: citystatestatushelper.lua's GetAllyToolTip shows the current ally (by name only
    -- when met) and "N more Influence to become ally" -- nothing about other majors' influence. The old
    -- `rivals` list gave every met major's influence, which no screen shows (fixed t339).
    ally = (function()
      local iAlly = o.GetAlly and o:GetAlly() or -1
      if iAlly == nil or iAlly == -1 then
        return { none = true, to_become_ally = ally_gap }
      end
      if iAlly == pid then return { us = true } end
      local met = myTeam:IsHasMet(Players[iAlly]:GetTeam())
      return { player = met and iAlly or nil, civ = met and Players[iAlly]:GetCivilizationShortDescription() or nil,
               met = met, to_become_ally = ally_gap }
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
