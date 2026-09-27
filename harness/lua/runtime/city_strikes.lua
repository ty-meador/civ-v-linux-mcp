-- Shared by earlier fragments (load order: harness/runtime_source.py MANIFEST).
local info_type, short = H._ns.info_type, H._ns.short

-- City bombard: Network.SendDoTask is the selection-free city-task path (cityview.lua /
-- puppetcitypopup.lua). Do not UI.SelectCity -- that is the old worldview.lua CityBombard()
-- flow and is not needed once the city id is in the net message.
function H.available_city_strikes(city_id, pid)
  local city = Players[pid]:GetCityByID(city_id)
  if not city then return { ok = false, err = "no such city" } end
  -- CanRangeStrike is "this city has bombard" (true on a turn-7 capital with no
  -- garrison). CanRangeStrikeNow is "can fire this turn". Live: Now() was false
  -- while Strike() was true; do not use `and/or` here — false Now() is falsy
  -- and would fall through to CanRangeStrike() and report can=true.
  local can_now
  if city.CanRangeStrikeNow then
    can_now = city:CanRangeStrikeNow()
  else
    can_now = city:CanRangeStrike()
  end
  if not can_now then return { ok = true, can = false, targets = {} } end
  local cx, cy = city:GetX(), city:GetY()
  local r = (GameDefines and GameDefines.MAX_CITY_ATTACK_RANGE) or 2
  local team = Players[pid]:GetTeam()
  local targets = {}
  for dx = -r, r do
    for dy = -r, r do
      local plot = Map.PlotXYWithRangeCheck(cx, cy, dx, dy, r)
      if plot then
        local x, y = plot:GetX(), plot:GetY()
        local ok, legal = pcall(function() return city:CanRangeStrikeAt(x, y, true, true) end)
        if ok and legal then
          local t = { x = x, y = y }
          if plot.IsVisible and plot:IsVisible(team, false) then
            local n = plot.GetNumUnits and plot:GetNumUnits() or 0
            if n > 0 and plot.GetUnit then
              local u = plot:GetUnit(0)
              if u then
                t.unit = { owner = u:GetOwner(), id = u:GetID(), hp = u:GetCurrHitPoints(),
                           type = short(info_type(GameInfo.Units, u:GetUnitType())) }
                -- enemyunitpanel.lua UpdateCombatOddsCityVsUnit. The panel caps the estimate at the
                -- unit's MAXIMUM hit points, not the hp it has left, and prints both strengths.
                pcall(function()
                  t.preview = { expected_damage_dealt = math.min(GameDefines.MAX_HIT_POINTS,
                                                                 city:RangeCombatDamage(u, nil)),
                                expected_damage_taken = 0 }
                  pcall(function()
                    t.preview.my_strength = city:GetStrengthValue() / 100
                    t.preview.their_strength = city:RangeCombatUnitDefense(u) / 100
                  end)
                  t.preview.modifiers = H.city_strike_modifiers(city, u)
                end)
              end
            end
            if plot.IsCity and plot:IsCity() then
              local c = plot:GetPlotCity()
              if c then t.city = { name = c:GetName(), owner = c:GetOwner() } end
            end
          end
          targets[#targets + 1] = t
        end
      end
    end
  end
  return { ok = true, can = true, targets = targets }
end

-- Who is on a plot right now, as the given team sees it (nil when not visible): the top enemy/any
-- units with hp, and the city if any. Used for before/after reads around attacks.
function H.plot_units(x, y, team)
  local plot = Map.GetPlot(x, y)
  if not plot then return { ok = false, err = "no such plot" } end
  if not plot:IsVisible(team, false) then return { ok = true, visible = false, units = {} } end
  local units = {}
  for i = 0, plot:GetNumUnits() - 1 do
    local u = plot:GetUnit(i)
    if u and not u:IsInvisible(team, false) then
      units[#units + 1] = { id = u:GetID(), owner = u:GetOwner(), type = short(info_type(GameInfo.Units, u:GetUnitType())),
                            hp = u:GetMaxHitPoints() - u:GetDamage() }
    end
  end
  local out = { ok = true, visible = true, units = units }
  if plot:IsCity() then
    local c = plot:GetPlotCity()
    out.city = { name = c:GetName(), owner = c:GetOwner(), hp = c:GetMaxHitPoints() - c:GetDamage() }
  end
  return out
end

function H.city_ranged_attack(city_id, x, y, pid)
  local p = Players[pid]
  local city = p:GetCityByID(city_id)
  if not city then return { ok = false, err = "no such city" } end
  if not city:CanRangeStrike() then return { ok = false, err = "city cannot range strike (no ranged combat / already struck this turn?)" } end
  if city.CanRangeStrikeNow and not city:CanRangeStrikeNow() then
    return { ok = false, err = "city cannot range strike this turn" }
  end
  if not city:CanRangeStrikeAt(x, y, true, true) then return { ok = false, err = "cannot strike that plot from this city" } end
  if not Network or not Network.SendDoTask then
    return { ok = false, err = "SendDoTask unavailable" }
  end
  Network.SendDoTask(city:GetID(), TaskTypes.TASK_RANGED_ATTACK, x, y, false, false, false, false)
  return { ok = true }
end
