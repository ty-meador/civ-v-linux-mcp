-- Shared by earlier fragments (load order: harness/runtime_source.py MANIFEST).
local L = H._ns.L

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

-- Shared with later fragments, which import these at their top (load order: harness/runtime_source.py MANIFEST).
H._ns.peaceful_occupant_err = peaceful_occupant_err
