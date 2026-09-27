-- Shared by earlier fragments (load order: harness/runtime_source.py MANIFEST).
local info_type, move_denom, short = H._ns.info_type, H._ns.move_denom, H._ns.short

-- Whether unit type `new` (short, "SWORDSMAN") is what `old` ("WARRIOR") upgrades to: Unit_ClassUpgrades names
-- the class. An upgrade gives the unit a new id on the same plot, so this is how an assignment finds it again.
function H.is_upgrade_of(old, new)
  local ok, yes = pcall(function()
    local n = GameInfo.Units["UNIT_" .. new]
    if not n then return false end
    for row in GameInfo.Unit_ClassUpgrades{ UnitType = "UNIT_" .. old } do
      if row.UnitClassType == n.Class then return true end
    end
    return false
  end)
  return ok and yes or false
end

-- Structured assignments (#33): the facts the notebook's assignments are reconciled against, in one read.
-- `spec` lists what they reference (harness/assignments.py builds it): my units and cities by id with the
-- plot they were last seen on, target plots, foreign units by owner and id, players, techs. My own units and
-- cities are read live (a human sees their own); everything else is fog-safe: a fogged plot answers with the
-- team's revealed owner and improvement and nothing about units or cities that may have changed there, a
-- foreign unit only while it stands in sight (a dead one and a hidden one read the same: not in sight).
function H.assignment_facts(pid, spec)
  local p = Players[pid]
  local team = p:GetTeam()
  spec = spec or {}
  local out = { turn = Game.GetGameTurn(), units = {}, cities = {}, plots = {}, foreign_units = {}, players = {},
                techs = {} }
  local function utype(u) return short(info_type(GameInfo.Units, u:GetUnitType())) end
  local function created(u)
    local ok, t = pcall(function() return u:GetGameTurnCreated() end)
    return ok and t or nil
  end
  local radius = tonumber(spec.radius) or 0
  local hostiles = {}
  if radius > 0 then
    for other = 0, 63 do
      local dp = Players[other]
      if other ~= pid and dp and (not dp.IsAlive or dp:IsAlive())
         and (dp:IsBarbarian() or Teams[team]:IsAtWar(dp:GetTeam())) then
        for d in dp:Units() do
          local q = d:GetPlot()
          if d:IsCombatUnit() and not d:IsDelayedDeath() and q and q:IsVisible(team, false) and not d:IsInvisible(team, false) then
            hostiles[#hostiles + 1] = { id = d:GetID(), unit = utype(d), owner = H.owner_label(other, pid), x = d:GetX(),
                                        y = d:GetY(), hp = d:GetCurrHitPoints() }
          end
        end
      end
    end
  end
  local function nearest_hostile(x, y)
    local best, bd
    for _, h in ipairs(hostiles) do
      local d = Map.PlotDistance(x, y, h.x, h.y)
      if d <= radius and (not bd or d < bd) then best, bd = h, d end
    end
    if best then
      return { id = best.id, unit = best.unit, owner = best.owner, x = best.x, y = best.y, hp = best.hp, distance = bd }
    end
  end

  for _, r in ipairs(spec.units or {}) do
    local u = p:GetUnitByID(r.id)
    local row = { id = r.id }
    if u and not u:IsDelayedDeath() then
      row.type, row.created, row.x, row.y = utype(u), created(u), u:GetX(), u:GetY()
      row.hp, row.max_hp, row.moves = u:GetCurrHitPoints(), u:GetMaxHitPoints(), u:MovesLeft() / move_denom()
      row.hostile = nearest_hostile(row.x, row.y)
    else
      row.missing = true
    end
    local changed = row.missing or (r.type and row.type ~= r.type) or (r.created and row.created ~= r.created)
    if changed and r.x and r.y then
      -- My units on the plot it was last seen on (my own units are always mine to see): an upgrade or a
      -- replacement stands there with a new id.
      local q = Map.GetPlot(r.x, r.y)
      local here = {}
      for i = 0, (q and q:GetNumUnits() or 0) - 1 do
        local o = q:GetUnit(i)
        if o and o:GetOwner() == pid and o:GetID() ~= r.id and not o:IsDelayedDeath() then
          local c = { id = o:GetID(), type = utype(o), created = created(o) }
          if r.type and H.is_upgrade_of(r.type, c.type) then c.upgrade_of = r.type end
          here[#here + 1] = c
        end
      end
      if #here > 0 then row.on_last_plot = here end
    end
    out.units[tostring(r.id)] = row
  end

  for _, r in ipairs(spec.cities or {}) do
    local c = p:GetCityByID(r.id)
    local row = { id = r.id }
    if c then
      row.name, row.x, row.y, row.pop = c:GetName(), c:GetX(), c:GetY(), c:GetPopulation()
      pcall(function() row.founded = c:GetGameTurnFounded() end)
      row.hp, row.max_hp = c:GetMaxHitPoints() - c:GetDamage(), c:GetMaxHitPoints()
      row.hostile = nearest_hostile(row.x, row.y)
      if r.buildings then
        row.has = {}
        for _, b in ipairs(r.buildings) do
          local id = GameInfoTypes and GameInfoTypes[b]
          row.has[b] = (id and c:IsHasBuilding(id)) and true or false
        end
      end
    else
      row.missing = true
    end
    out.cities[tostring(r.id)] = row
  end

  local found_range = (GameDefines and tonumber(GameDefines.MIN_CITY_RANGE)) or 2
  for _, r in ipairs(spec.plots or {}) do
    local k = r.x .. "," .. r.y
    local q = Map.GetPlot(r.x, r.y)
    if not q then
      out.plots[k] = { off_map = true }
    elseif not q:IsRevealed(team, false) then
      out.plots[k] = { vis = "unrevealed" }
    else
      local vis = q:IsVisible(team, false) and true or false
      local row = { vis = vis and "visible" or "fogged" }
      local own = vis and q:GetOwner() or q:GetRevealedOwner(team, false)
      if own >= 0 then row.owner = own; row.owner_name = H.owner_label(own, pid) end
      local imp = vis and q:GetImprovementType() or q:GetRevealedImprovementType(team, false)
      if imp >= 0 then
        row.improvement = short(info_type(GameInfo.Improvements, imp))
        if vis and q.IsImprovementPillaged and q:IsImprovementPillaged() then row.pillaged = true end
      end
      if vis then
        if q:IsCity() then
          local c = q:GetPlotCity()
          row.city = { id = c:GetID(), name = c:GetName(), owner = c:GetOwner(), owner_name = H.owner_label(c:GetOwner(), pid) }
        end
        local units = {}
        for i = 0, q:GetNumUnits() - 1 do
          local o = q:GetUnit(i)
          if o and not o:IsDelayedDeath() and (o:GetOwner() == pid or not o:IsInvisible(team, false)) then
            units[#units + 1] = { id = o:GetID(), owner = o:GetOwner(), unit = utype(o) }
          end
        end
        if #units > 0 then row.units = units end
      end
      if r.site then
        -- A city site: the nearest city this team knows of within the founding range. Only plots in sight
        -- answer live; a fogged one gives the banner the team has seen (City:IsRevealed) and its revealed owner.
        local best
        for dx = -found_range, found_range do for dy = -found_range, found_range do
          local o = Map.PlotXYWithRangeCheck(r.x, r.y, dx, dy, found_range)
          if o and o:IsRevealed(team, false) and o:IsCity() then
            local c = o:GetPlotCity()
            local seen = o:IsVisible(team, false) or (c and c:IsRevealed(team, false))
            if c and seen then
              local d = Map.PlotDistance(r.x, r.y, o:GetX(), o:GetY())
              if not best or d < best.distance then
                local cown = o:IsVisible(team, false) and c:GetOwner() or o:GetRevealedOwner(team, false)
                best = { name = c:GetName(), x = o:GetX(), y = o:GetY(), distance = d, owner = cown,
                         owner_name = H.owner_label(cown, pid) }
              end
            end
          end
        end end
        if best then row.city_within_range = best end
        row.found_range = found_range
      end
      out.plots[k] = row
    end
  end

  for _, r in ipairs(spec.foreign_units or {}) do
    local k = r.owner .. ":" .. r.id
    local row = { owner = r.owner, id = r.id, in_sight = false }
    local fp = Players[r.owner]
    local u = fp and fp:GetUnitByID(r.id)
    local q = u and not u:IsDelayedDeath() and u:GetPlot()
    if q and q:IsVisible(team, false) and not u:IsInvisible(team, false) then
      row.in_sight, row.type, row.x, row.y, row.hp = true, utype(u), u:GetX(), u:GetY(), u:GetCurrHitPoints()
    elseif r.x and r.y then
      local lq = Map.GetPlot(r.x, r.y)
      row.last_plot_visible = (lq and lq:IsVisible(team, false)) and true or false
    end
    out.foreign_units[k] = row
  end

  for _, id in ipairs(spec.players or {}) do
    local op = Players[id]
    local row = { id = id }
    if op then
      local met = Teams[team]:IsHasMet(op:GetTeam()) and true or false
      row.met = met
      row.name = H.owner_label(id, pid)
      if met then
        row.alive = (not op.IsAlive or op:IsAlive()) and true or false
        row.at_war = Teams[team]:IsAtWar(op:GetTeam()) and true or false
      end
    end
    out.players[tostring(id)] = row
  end

  for _, t in ipairs(spec.techs or {}) do
    local id = GameInfoTypes and GameInfoTypes[t]
    out.techs[t] = (id and Teams[team]:IsHasTech(id)) and true or false
  end
  return out
end
