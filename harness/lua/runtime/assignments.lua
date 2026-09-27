-- Shared by earlier fragments (load order: harness/runtime_source.py MANIFEST).
local info_type, move_denom, require_revealed_plot, short = H._ns.info_type, H._ns.move_denom, H._ns.require_revealed_plot, H._ns.short

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
-- Conditional orders (#32): what the notebook's orders need to decide their next step, in one read.
-- `spec` (harness/orders.py builds it): units {id, type, created, x, y} as fingerprinted, `radius` for the
-- hostiles, `dests` {unit_id, x, y} for the current move steps, `builds` {unit_id, build, x, y} for the current
-- build steps. Units come from H.assignment_facts (the same fingerprint and last-plot reads) plus what a step
-- needs: max moves, activity, the build in progress, the standing move. Hostiles are every visible combat unit
-- at war with this seat within `radius` of the unit, not just the nearest. A destination answers move_unit's
-- own refusal and whether an enemy stands on it (the order never attacks); a build answers what it makes,
-- whether its plot already has it, and whether the unit could start it there now.
function H.order_facts(pid, spec)
  local p = Players[pid]
  local team = p:GetTeam()
  spec = spec or {}
  local out = H.assignment_facts(pid, { units = spec.units or {} })
  out.dests, out.builds = {}, {}
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
            hostiles[#hostiles + 1] = { id = d:GetID(), owner_id = other, owner = H.owner_label(other, pid),
                                        unit = short(info_type(GameInfo.Units, d:GetUnitType())),
                                        x = d:GetX(), y = d:GetY(), hp = d:GetCurrHitPoints() }
          end
        end
      end
    end
  end
  for _, r in ipairs(spec.units or {}) do
    local row = out.units[tostring(r.id)]
    local u = p:GetUnitByID(r.id)
    if row and not row.missing and u then
      row.max_moves = u:MaxMoves() / move_denom()
      local act = u.GetActivityType and u:GetActivityType() or nil
      if act then row.activity = H.activity_name(act) end
      pcall(function()
        local bt = u.GetBuildType and u:GetBuildType() or -1
        if bt and bt >= 0 and GameInfo.Builds[bt] then row.build = GameInfo.Builds[bt].Type end
      end)
      row.going_to = H.going_to(u, pid)
      local near = {}
      for _, h in ipairs(hostiles) do
        local d = Map.PlotDistance(row.x, row.y, h.x, h.y)
        if d <= radius then
          near[#near + 1] = { id = h.id, owner_id = h.owner_id, owner = h.owner, unit = h.unit, x = h.x, y = h.y,
                              hp = h.hp, distance = d }
        end
      end
      table.sort(near, function(a, b) return a.distance < b.distance end)
      while #near > 6 do table.remove(near) end
      if #near > 0 then row.hostiles = near end
      row.hostile = nil
    end
  end
  for _, r in ipairs(spec.dests or {}) do
    local k = r.unit_id .. ":" .. r.x .. "," .. r.y
    local u = p:GetUnitByID(r.unit_id)
    local q = Map.GetPlot(r.x, r.y)
    local row = {}
    if not q then
      row.refusal = "that plot is off the map"
    elseif u then
      local blocked = require_revealed_plot(r.x, r.y, pid, u)
      if blocked then row.refusal = blocked.err end
      if H.melee_defender(u, q, pid) or H.enemy_city_at(q, pid) then row.enemy = true end
      if not row.refusal and not row.enemy then
        local ok, refused = pcall(function() return H.move_refusal(u, q, pid, false) end)
        if ok and refused then row.refusal = refused.err end
      end
    end
    out.dests[k] = row
  end
  for _, r in ipairs(spec.builds or {}) do
    local k = r.unit_id .. ":" .. r.build
    local row = { known = false }
    local b = GameInfo.Builds and GameInfo.Builds[r.build]
    local bu = p:GetUnitByID(r.unit_id)
    if (r.x == nil or r.x < 0) and bu then r.x, r.y = bu:GetX(), bu:GetY() end   -- no plot given: where it stands
    local q = Map.GetPlot(r.x, r.y)
    if b and q then
      row.known = true
      local imp = b.ImprovementType and GameInfoTypes[b.ImprovementType]
      local route = b.RouteType and GameInfoTypes[b.RouteType]
      if imp then
        row.improvement = b.ImprovementType
        local pillaged = q.IsImprovementPillaged and q:IsImprovementPillaged()
        row.done = q:GetImprovementType() == imp and not pillaged
      elseif route then
        row.route = b.RouteType
        local pillaged = q.IsRoutePillaged and q:IsRoutePillaged()
        row.done = q:GetRouteType() == route and not pillaged
      elseif b.Type == "BUILD_REMOVE_ROUTE" then
        row.done = q:GetRouteType() < 0
      else
        -- A build that makes nothing (chop, clear, scrub) is done when the feature it removes is gone: a
        -- REMOVE_FOREST step paused as "cannot start" the turn after the chop had paid out, live 2026-09-27
        -- (Grok, t64), because nothing ever said it was finished.
        local removes = {}
        pcall(function()
          for fr in GameInfo.BuildFeatures{ BuildType = b.Type } do
            if fr.BuildType == b.Type and fr.FeatureType and (fr.Remove == true or fr.Remove == 1) then
              removes[#removes + 1] = fr.FeatureType
            end
          end
        end)
        if #removes > 0 then
          row.removes = removes
          local feat = q:GetFeatureType()
          local here = feat >= 0 and info_type(GameInfo.Features, feat) or nil
          row.done = true
          for _, ft in ipairs(removes) do if ft == here then row.done = false end end
        end
      end
      if bu and bu:GetX() == r.x and bu:GetY() == r.y then
        -- Unit:CanBuild(plot, build) only: a third argument raises "number expected" (live t43), and a call that
        -- raised is no answer at all -- can_build stays unset rather than reading as "cannot".
        local ok, can = pcall(function() return bu:CanBuild(q, b.ID) end)
        if ok then row.can_build = can and true or false end
      end
    end
    out.builds[k] = row
  end
  return out
end

