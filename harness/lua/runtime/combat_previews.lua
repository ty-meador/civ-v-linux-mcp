-- Shared by earlier fragments (load order: harness/runtime_source.py MANIFEST).
local info_type, short = H._ns.info_type, H._ns.short

-- The pre-commit numbers the game shows when a human hovers a melee attack (EnemyUnitPanel.lua's
-- formula, bIncludeRand=false: the expected damage, the real roll varies around it). Live-audited
-- 2026-09-18: the human at the screen sees this before committing; the harness showed no attack at all.
local function melee_fire_support_damage(u, owner, plot)
  local support = u:GetFireSupportUnit(owner, plot:GetX(), plot:GetY())
  -- The stock panel exposes this aggregate even without identifying the supporting unit.
  -- Return only its displayed damage; never expose the unit's identity or location.
  if support then return support:GetRangeCombatDamage(u, nil, false) end
  return 0
end

-- The health bars' verdict: enemyunitpanel.lua paints a death when current damage plus the expected hit
-- reaches the maximum. Say it in words rather than leave the caller to add hp and damage (a city is never
-- taken by damage alone, so only units get one).
local function preview_deaths(out, u, t)
  pcall(function()
    local max = GameDefines.MAX_HIT_POINTS
    if out.expected_damage_taken and u:GetDamage() + out.expected_damage_taken >= max then out.my_unit_would_die = true end
    if t and out.expected_damage_dealt and t:GetDamage() + out.expected_damage_dealt >= max then out.target_would_die = true end
  end)
end

function H.melee_preview(u, d)
  local out = {}
  local support = 0
  pcall(function()
    local plot = d:GetPlot()
    local mine = u:GetMaxAttackStrength(u:GetPlot(), plot, d)
    local theirs = d:GetMaxDefenseStrength(plot, u)
    out.my_strength, out.their_strength = mine / 100, theirs / 100
    support = melee_fire_support_damage(u, d:GetOwner(), plot)
    out.fire_support_damage = support
    out.expected_damage_dealt = math.min(GameDefines.MAX_HIT_POINTS,
      u:GetCombatDamage(mine, theirs, u:GetDamage() + support, false, false, false))
    out.expected_damage_taken = math.min(GameDefines.MAX_HIT_POINTS,
      d:GetCombatDamage(theirs, mine, d:GetDamage(), false, false, false) + support)
  end)
  preview_deaths(out, u, d)
  out.modifiers = H.combat_modifiers(u, d, nil, false, support)
  return out
end

-- The enemy city a melee move onto `plot` would assault: visible, owned by a team we are at war with.
function H.enemy_city_at(plot, pid)
  local team = Players[pid]:GetTeam()
  if not plot or not plot:IsVisible(team, false) then return nil end
  local c = plot:GetPlotCity()
  if c and c:GetOwner() ~= pid and Teams[team]:IsAtWar(Players[c:GetOwner()]:GetTeam()) then return c end
  return nil
end

-- enemyunitpanel.lua UpdateCombatOddsUnitVsCity, melee branch (city strength is already x100).
function H.melee_city_preview(u, c)
  local out = {}
  local support = 0
  pcall(function()
    local plot = c:Plot()
    local mine = u:GetMaxAttackStrength(u:GetPlot(), plot, nil)
    local theirs = c:GetStrengthValue()
    out.my_strength, out.their_strength = mine / 100, theirs / 100
    support = melee_fire_support_damage(u, c:GetOwner(), plot)
    out.fire_support_damage = support
    out.expected_damage_dealt = math.min(c:GetMaxHitPoints(),
      u:GetCombatDamage(mine, theirs, u:GetDamage() + support, false, false, true))
    out.expected_damage_taken = math.min(GameDefines.MAX_HIT_POINTS,
      u:GetCombatDamage(theirs, mine, c:GetDamage(), false, true, false) + support)
  end)
  preview_deaths(out, u, nil)
  out.modifiers = H.combat_modifiers(u, nil, c, false, support)
  return out
end

-- EnemyUnitPanel's ranged branch, including air retaliation and its visible-only AA count.
-- Interception damage is NOT in the estimate; the stock panel always warns for an air strike,
-- even when no interceptors are visible. Never turn a failed retaliation read into zero damage.
function H.ranged_preview(u, t, c)
  local out = {}
  pcall(function()
    out.expected_damage_dealt = u:GetRangeCombatDamage(t, c, false)
    if u:GetDomainType() == DomainTypes.DOMAIN_AIR then
      out.interception_possible = true
      out.interception_warning = "Air strikes may be intercepted; expected_damage_taken excludes interception."
      out.expected_damage_taken = (c or t):GetAirStrikeDefenseDamage(u, false)
    else
      out.expected_damage_taken = 0
    end
  end)
  -- enemyunitpanel.lua clamps both numbers to the health bar (MAX_HIT_POINTS for a unit, the city's own
  -- maximum for a city) before drawing them: live 2026-09-24 the raw AA number for a Bomber read above 100.
  -- A clamp that cannot be read leaves the raw number rather than losing it.
  pcall(function()
    local my_max = GameDefines.MAX_HIT_POINTS
    local their_max = c and c:GetMaxHitPoints() or my_max
    if out.expected_damage_dealt then out.expected_damage_dealt = math.min(their_max, out.expected_damage_dealt) end
    if out.expected_damage_taken then out.expected_damage_taken = math.min(my_max, out.expected_damage_taken) end
  end)
  if c then preview_deaths(out, u, nil) else preview_deaths(out, u, t) end
  pcall(function()
    local mine = u:GetMaxRangedCombatStrength(t, c, true, true)
    local theirs
    if c then
      theirs = c:GetStrengthValue()
    else
      if t:IsEmbarked() then theirs = t:GetEmbarkedUnitDefense()
      else theirs = t:GetMaxRangedCombatStrength(u, nil, false, true) end
      if theirs == 0 or t:GetDomainType() == DomainTypes.DOMAIN_SEA or t:IsRangedSupportFire() then
        theirs = t:GetMaxDefenseStrength(t:GetPlot(), u, true)
      end
    end
    out.my_strength, out.their_strength = mine / 100, theirs / 100
  end)
  if out.interception_possible then
    pcall(function()
      out.visible_interceptors = u:GetInterceptorCount(c and c:Plot() or t:GetPlot(), t, true, true)
    end)
  end
  out.modifiers = H.combat_modifiers(u, t, c, true, 0, out.interception_possible, out.visible_interceptors)
  return out
end

-- Share the same visible, hostile target and preview between ranged actions and airstrike targets.
-- City strength includes the garrison: never preview its unit instead of the city.
function H.ranged_target_info(u, plot, pid)
  local team = Players[pid]:GetTeam()
  if not plot:IsVisible(team, false) then return {} end
  local c = H.enemy_city_at(plot, pid)
  if c then
    return { city = c:GetName(), owner = c:GetOwner(), hp = c:GetMaxHitPoints() - c:GetDamage(),
      preview = H.ranged_preview(u, nil, c) }
  end
  for i = 0, plot:GetNumUnits() - 1 do
    local t = plot:GetUnit(i)
    if t and not t:IsInvisible(team, false) and t:GetOwner() ~= pid then
      local owner = Players[t:GetOwner()]
      if owner and Teams[team]:IsAtWar(owner:GetTeam()) then
        local out = H.combat_side(t:GetOwner(), t:GetID(), pid) or {}
        out.preview = H.ranged_preview(u, t, nil)
        return out
      end
    end
  end
  return {}
end

function H.melee_targets(u, pid)
  local out = {}
  if not u:IsCombatUnit() or H.ranged_strength(u) > 0 or u:MovesLeft() <= 0 then return out end
  for dx = -1, 1 do for dy = -1, 1 do
    local q = Map.PlotXYWithRangeCheck(u:GetX(), u:GetY(), dx, dy, 1)
    if q and (q:GetX() ~= u:GetX() or q:GetY() ~= u:GetY()) then
      -- A garrisoned city is fought as the city (its strength includes the garrison); listing the garrison
      -- unit showed a unit-vs-unit preview for a city assault (live t119, Machu's Composite Bowman).
      local c = H.enemy_city_at(q, pid)
      local d = not c and H.melee_defender(u, q, pid)
      if d then
        local e = H.combat_side(d:GetOwner(), d:GetID(), pid) or {}
        e.how = "move_unit onto this plot attacks"
        e.preview = H.melee_preview(u, d)
        out[#out + 1] = e
      end
      if c then
        out[#out + 1] = { x = q:GetX(), y = q:GetY(), city = c:GetName(), owner = c:GetOwner(),
                          hp = c:GetMaxHitPoints() - c:GetDamage(), how = "move_unit onto this plot assaults the city",
                          preview = H.melee_city_preview(u, c) }
      end
    end
  end end
  return out
end

-- Plots a ranged unit could shoot this turn, the way the unit panel's Ranged Attack cursor highlights
-- them: engine CanRangeStrikeAt over the unit's Range, only plots showing a visible unit or city.
-- Live t316: a Chu-Ko-Nu two tiles from a barbarian listed no action and no target, yet
-- MISSION_RANGE_ATTACK on that plot hit for 39 (the one-arg CanStartMission check needs a target).
function H.ranged_targets(u, pid)
  local out = {}
  if not (u.IsRanged and u:IsRanged()) or u:MovesLeft() <= 0 then return out end
  if u.CanRangeStrike and not u:CanRangeStrike() then return out end
  local row = GameInfo.Units[u:GetUnitType()]
  local range = row and row.Range or 0
  if range <= 0 then return out end
  local team = Players[pid]:GetTeam()
  for dx = -range, range do for dy = -range, range do
    local q = Map.PlotXYWithRangeCheck(u:GetX(), u:GetY(), dx, dy, range)
    if q and q:IsVisible(team, false) and (q:GetX() ~= u:GetX() or q:GetY() ~= u:GetY()) then
      local ok, can = pcall(function() return u:CanRangeStrikeAt(q:GetX(), q:GetY(), true, true) end)
      if ok and can then
        local e = { x = q:GetX(), y = q:GetY(), how = "unit_mission MISSION_RANGE_ATTACK with x, y" }
        for k, v in pairs(H.ranged_target_info(u, q, pid)) do e[k] = v end
        out[#out + 1] = e
      end
    end
  end end
  return out
end

-- move_unit bookkeeping for a melee attack: who stands on the destination before the order, and what
-- became of both sides after it (the Python wrapper calls attack_before, the order, then attack_after).
-- An air unit does not walk: a strike is legal this instant or not at all, and the engine answers an
-- out-of-range one by doing nothing at all. Live t184: a Fighter at (49,19) was sent at Cusco (42,23),
-- nine plots away against a range of eight; the order was accepted and simply had no effect, so the
-- reply was ok=true with both sides' hp unchanged -- the "accepted but wrong" shape this harness keeps
-- running into. Report the engine's own predicate so the caller can refuse instead of guessing.
local function air_strike_legality(u, x, y)
  local air = false
  pcall(function() air = u.CanAirAttack and u:CanAirAttack() end)
  if not air then return nil end
  local ok, can = pcall(function() return u:CanRangeStrikeAt(x, y, true, true) end)
  return { air = true, can_strike = (ok and can) and true or false,
           range = (pcall(function() return u:Range() end) and u:Range() or nil) }
end

-- The interceptor picture before an air strike, as the stock panel has it: the count of visible interceptors
-- of every domain ("Known Enemy Anti-Air Units" is the land-only cut of the same getter) and the unit the
-- engine would send up -- named only when we can see it. GetBestInterceptor knows about interceptors under
-- fog as well; an unseen one leaves `best` nil rather than be named. Live 2026-09-24: an AA gun at (2,11),
-- count 1, best = that gun.
function H.interception_before(u, plot, d, pid)
  local out = {}
  pcall(function() out.count = u:GetInterceptorCount(plot, d, false, true) end)
  pcall(function()
    local team = Players[pid]:GetTeam()
    local b = u:GetBestInterceptor(plot, d, false, true)
    if b and b:GetPlot():IsVisible(team, false) and not b:IsInvisible(team, false) then
      out.best = { player = b:GetOwner(), id = b:GetID(), owner = H.owner_label(b:GetOwner(), pid),
                   unit = short(info_type(GameInfo.Units, b:GetUnitType())), x = b:GetX(), y = b:GetY() }
    end
  end)
  return out
end
-- After the strike: the same count. An interceptor that fired is out of interceptions for the turn and drops
-- out of the count (live 2026-09-24: 1 before, 0 after the gun fired). No Lua getter says so per unit, and a
-- dead attacker cannot ask -- the caller then reasons from the untouched target instead.
function H.interception_after(unit_id, x, y, def_player, def_unit, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  local out = {}
  if not u or u:IsDelayedDeath() then
    -- The count is about the interceptors around the plot, not about the asker (live 2026-09-24: a Bomber
    -- that had already struck read the same 0 as the one that died there); any other aircraft of ours asks.
    u = nil
    for other in Players[pid]:Units() do
      local ok, air = pcall(function() return other.CanAirAttack and other:CanAirAttack() end)
      if ok and air and not other:IsDelayedDeath() then u = other; out.asked_by = other:GetID(); break end
    end
    if not u then return out end
  end
  pcall(function()
    local d = (def_unit and def_unit >= 0 and Players[def_player]) and Players[def_player]:GetUnitByID(def_unit) or nil
    out.count = u:GetInterceptorCount(Map.GetPlot(x, y), d, false, true)
  end)
  return out
end

function H.attack_before(unit_id, x, y, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  if u then pcall(H.note_unit, u, pid) end
  local air = u and air_strike_legality(u, x, y) or nil
  local c = u and H.enemy_city_at(Map.GetPlot(x, y), pid)
  if c then
    return { attack = true, city = true, def_player = c:GetOwner(), def_unit = -1,
             def_hp = c:GetMaxHitPoints() - c:GetDamage(), my_hp = u:GetCurrHitPoints(),
             air = air, interception = air and H.interception_before(u, Map.GetPlot(x, y), nil, pid) or nil,
             defender = { city = c:GetName(), owner = H.owner_label(c:GetOwner(), pid), x = x, y = y } }
  end
  local d = u and H.melee_defender(u, Map.GetPlot(x, y), pid)
  if not d then return { attack = false } end
  return { attack = true, def_player = d:GetOwner(), def_unit = d:GetID(), def_hp = d:GetCurrHitPoints(),
           my_hp = u:GetCurrHitPoints(), air = air,
           interception = air and H.interception_before(u, Map.GetPlot(x, y), d, pid) or nil,
           defender = H.combat_side(d:GetOwner(), d:GetID(), pid) }
end
function H.attack_after(unit_id, def_player, def_unit, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  local d = Players[def_player] and Players[def_player]:GetUnitByID(def_unit)
  local out = {}
  if not u or u:IsDelayedDeath() then out.my_unit_killed = true else out.my_hp = u:GetCurrHitPoints() end
  if not d or d:IsDelayedDeath() or d:GetCurrHitPoints() <= 0 then out.defender_killed = true
  else out.def_hp = d:GetCurrHitPoints() end
  return out
end

function H.city_attack_after(unit_id, x, y, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  local out = {}
  if not u or u:IsDelayedDeath() then out.my_unit_killed = true else out.my_hp = u:GetCurrHitPoints() end
  local pl = Map.GetPlot(x, y)
  local c = pl and pl:GetPlotCity()
  if c and c:GetOwner() == pid then out.city_captured = true
  elseif c then out.def_hp = c:GetMaxHitPoints() - c:GetDamage() end
  return out
end

-- A civilian "defender" that vanished was captured when a unit of that type is now ours on its plot (live t112:
-- an Inca Worker taken by a Warrior read as defender_killed). Returns the new unit id or nil.
function H.captured_at(x, y, type_name, pid)
  local pl = Map.GetPlot(x, y)
  if not pl then return nil end
  for i = 0, pl:GetNumUnits() - 1 do
    local c = pl:GetUnit(i)
    if c and c:GetOwner() == pid and not c:IsCombatUnit()
       and GameInfo.Units[c:GetUnitType()] and GameInfo.Units[c:GetUnitType()].Type:gsub("^UNIT_", "") == type_name:gsub("^UNIT_", "") then
      return c:GetID()
    end
  end
  return nil
end
