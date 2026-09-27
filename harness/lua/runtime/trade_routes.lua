-- Shared by earlier fragments (load order: harness/runtime_source.py MANIFEST).
local L, info_id, info_type, plain_key = H._ns.L, H._ns.info_id, H._ns.info_type, H._ns.plain_key
local plain_text, push_mission, short = H._ns.plain_text, H._ns.push_mission, H._ns.short

-- Trade routes: Game.SelectionListGameNetMessage with MISSION_ESTABLISH_TRADE_ROUTE / _PLUNDER_TRADE_ROUTE
-- (confirmed in ui/ingame/popups/chooseinternationaltraderoutepopup.lua, declarewarpopup.lua), same shape
-- as any other unit mission push. dest is a plot index (Map.GetPlot(x,y):GetPlotIndex()), trade_type is
-- the domain-specific trade type id from the available-routes list.
function H.establish_trade_route(unit_id, dest_x, dest_y, trade_type, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  if not u:IsTrade() then return {ok=false, err="unit is not a caravan or cargo ship"} end
  if u:MovesLeft() <= 0 then return {ok=false, err="unit has no moves left"} end
  local valid = false
  for _, route in ipairs(H.available_trade_routes(unit_id, pid)) do
    if route.x == dest_x and route.y == dest_y and route.trade_connection_type == trade_type then valid = true end
  end
  if not valid then return {ok=false, err="route is not currently available to this unit"} end
  local plot = Map.GetPlot(dest_x, dest_y)
  if not plot then return { ok = false, err = "no such plot" } end
  -- The caravan's model is torn down when the route starts, which the digest otherwise reads as a unit
  -- "spent" by my order (live t324). Remember who left for where so turn_digest can say so.
  local dest = plot:GetPlotCity()
  H.route_starts = H.route_starts or {}
  table.insert(H.route_starts, { unit_id = unit_id, unit = short(GameInfo.Units[u:GetUnitType()].Type),
                                 to = dest and dest:GetName() or nil, turn = Game.GetGameTurn() })
  while #H.route_starts > 20 do table.remove(H.route_starts, 1) end
  local m = info_id("MISSION_ESTABLISH_TRADE_ROUTE")
  if m == nil then m = MissionTypes and MissionTypes.MISSION_ESTABLISH_TRADE_ROUTE end
  if m == nil then return { ok = false, err = "unknown mission" } end
  return push_mission(u, m, plot:GetPlotIndex(), trade_type)
end

-- The Trade Route Overview's religion columns. The screen prints an icon and "+N" only when the
-- religion id is positive and the pressure is not zero (traderouteoverview.lua). The chooser uses
-- the same rule with FromPressureAmount / ToPressureAmount (chooseinternationaltraderoutepopup.lua).
local function trade_route_religion(id)
  if not id or id <= 0 or not (GameInfo and GameInfo.Religions) then return nil end
  local rel = GameInfo.Religions[id]
  if not rel then return nil end
  local name = rel.Description and L(rel.Description) or nil
  if not name or name == "" or name == rel.Description then name = short(rel.Type) end
  return plain_text(name)
end

local function trade_route_pressure(id, amount)
  if not amount or amount == 0 then return nil, nil end
  local name = trade_route_religion(id)
  if not name then return nil, nil end
  return name, amount
end

-- Hover on every Trade Route Overview cell and on each chooser row
-- (traderoutehelpers.lua BuildTradeRouteToolTipString). Gold lines that are always on the tooltip
-- stay even at zero; a zero policy, building, resource, river, or trait line is left off, matching
-- the screen. Returns nil when the screen's own gate does (no international gold on the route).
local function trade_route_hover(origin, target, domain, pid)
  if (type(origin) ~= "table" and type(origin) ~= "userdata") or not origin.GetOwner then return nil end
  if (type(target) ~= "table" and type(target) ~= "userdata") or not target.GetOwner then return nil end
  local owner = origin:GetOwner()
  local other_id = target:GetOwner()
  local p = Players and Players[owner]
  local o = Players and Players[other_id]
  if not p or not o or not p.GetInternationalTradeRouteTotal then return nil end
  local gate = p:GetInternationalTradeRouteTotal(origin, target, true, true)
  if not gate or gate <= 0 then return nil end
  local function leader(q)
    local nick = q.GetNickName and q:GetNickName() or ""
    local net = false
    if Game and Game.IsNetworkMultiPlayer then
      local ok, v = pcall(function() return Game:IsNetworkMultiPlayer() end)
      net = ok and v and true or false
    end
    if nick ~= "" and net then return nick end
    return (q.GetName and q:GetName()) or ""
  end
  local mine = owner == pid
  local lines = {}
  local function add(s) if s and s ~= "" then lines[#lines + 1] = s end end
  add(mine and plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_YOUR_REVENUE")
            or plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_THEIR_REVENUE"))
  add(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_BASE",
                p:GetInternationalTradeRouteBaseBonus(origin, target, true) / 100))
  -- Both city lines use the "yours" key. That is what the screen calls, and the two strings match.
  add(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_GPT_YOURS",
                origin:GetNameKey(), p:GetInternationalTradeRouteGPTBonus(origin, target, true) / 100))
  add(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_GPT_YOURS",
                target:GetNameKey(), p:GetInternationalTradeRouteGPTBonus(origin, target, false) / 100))
  local policy = p:GetInternationalTradeRoutePolicyBonus(origin, target, domain)
  if policy ~= 0 then
    add(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_POLICIES", policy / 100))
  end
  local your_b = p:GetInternationalTradeRouteYourBuildingBonus(origin, target, domain, true)
  if your_b ~= 0 then
    add(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_BUILDING", origin:GetNameKey(), your_b / 100))
  end
  local their_b = p:GetInternationalTradeRouteTheirBuildingBonus(origin, target, domain, true)
  if their_b ~= 0 then
    add(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_BUILDING", target:GetNameKey(), their_b / 100))
  end
  -- GameInfo.Resources is a database cursor (userdata with a call metamethod), not a Lua function.
  if GameInfo and GameInfo.Resources and Game.GetResourceUsageType and ResourceUsageTypes then
    local header = false
    for res in GameInfo.Resources() do
      if res and res.ID then
        local usage = Game.GetResourceUsageType(res.ID)
        if (usage == ResourceUsageTypes.RESOURCEUSAGE_LUXURY or usage == ResourceUsageTypes.RESOURCEUSAGE_STRATEGIC)
           and origin:IsHasResourceLocal(res.ID) ~= target:IsHasResourceLocal(res.ID) then
          local mod = p.GetInternationalTradeRouteResourceTraitModifier and p:GetInternationalTradeRouteResourceTraitModifier() or 0
          local gold = 50 * (100 + mod) / 100
          if not header then
            add(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_RESOURCE_HEADER"))
            header = true
          end
          add(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_RESOURCE_DIFFERENT",
                        res.IconString or "", res.Description, gold / 100))
        end
      end
    end
  end
  -- The screen ends the base/resource block with a newline, then adds another before the total,
  -- unless a river, sea, or exclusive line (none of which carry their own newline) was last.
  -- That is the blank line above "Total". A trait line ends with a newline, so it does not close it.
  local closed = true
  local excl = p:GetInternationalTradeRouteExclusiveBonus(origin, target)
  if excl ~= 0 then
    add(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_EXCLUSIVE_CONNECTION", excl / 100))
    closed = false
  end
  local trait = p:GetInternationalTradeRouteOtherTraitBonus(origin, target, domain, true)
  if trait ~= 0 then
    add(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_OTHER_TRAIT",
                  o:GetCivilizationAdjectiveKey(), trait / 100))
    closed = true
  end
  local river = p:GetInternationalTradeRouteRiverModifier(origin, target, domain, true)
  if river ~= 0 then
    add(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_RIVER_MODIFIER", river))
    closed = false
  end
  local sea
  local dom_mod = p.GetInternationalTradeRouteDomainModifier and p:GetInternationalTradeRouteDomainModifier(domain) or 0
  if dom_mod ~= 0 and DomainTypes and domain == DomainTypes.DOMAIN_SEA then
    sea = plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_DOMAIN_SEA_MODIFIER", (dom_mod + 100) / 100)
    add(sea)
    closed = false
  end
  if closed then lines[#lines + 1] = "" end
  add(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_TOTAL",
                p:GetInternationalTradeRouteTotal(origin, target, domain, true) / 100))
  local their_amt = o.GetInternationalTradeRouteTotal and o:GetInternationalTradeRouteTotal(origin, target, domain, false) or 0
  if their_amt ~= 0 then
    lines[#lines + 1] = ""
    add(mine and plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_THEIR_REVENUE")
              or plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_YOUR_REVENUE"))
    local other_base = o:GetInternationalTradeRouteBaseBonus(origin, target, false)
    if other_base ~= 0 then
      add(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_BASE", other_base / 100))
    end
    local other_river = p:GetInternationalTradeRouteRiverModifier(origin, target, domain, false)
    if other_river ~= 0 then
      add(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_RIVER_MODIFIER", other_river))
    end
    if sea then add(sea) end
    local other_b = o:GetInternationalTradeRouteTheirBuildingBonus(origin, target, domain, false)
    if other_b ~= 0 then
      add(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_BUILDING", target:GetNameKey(), other_b / 100))
    end
    add(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_TRADEE_TOTAL", leader(o), their_amt / 100))
  end
  local function science_lines()
    local out = {}
    local function sadd(s) if s and s ~= "" then out[#out + 1] = s end end
    local ours = p:GetInternationalTradeRouteScience(origin, target, domain, true) / 100
    local theirs = o:GetInternationalTradeRouteScience(origin, target, domain, false) / 100
    if ours > 0 then
      local techs = p:GetNumTechDifference(other_id)
      local infl = p:GetInfluenceTradeRouteScienceBonus(other_id)
      if mine then
        sadd(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_YOUR_SCIENCE_GAIN"))
        sadd(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_YOUR_SCIENCE_EXPLAINED",
                       leader(o), techs, infl))
        sadd(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_YOUR_SCIENCE_TOTAL", ours))
      else
        sadd(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_THEIR_SCIENCE_GAIN"))
        sadd(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_THEIR_SCIENCE_EXPLAINED",
                       techs, leader(p), infl))
        sadd(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_THEIR_SCIENCE_TOTAL", leader(p), ours))
      end
    end
    if theirs > 0 then
      if #out > 0 then out[#out + 1] = "" end
      local techs = o:GetNumTechDifference(owner)
      local infl = o:GetInfluenceTradeRouteScienceBonus(owner)
      if mine then
        sadd(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_THEIR_SCIENCE_GAIN"))
        sadd(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_THEIR_SCIENCE_EXPLAINED",
                       techs, leader(o), infl))
        sadd(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_THEIR_SCIENCE_TOTAL", leader(o), theirs))
      else
        sadd(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_YOUR_SCIENCE_GAIN"))
        sadd(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_YOUR_SCIENCE_EXPLAINED",
                       leader(p), techs, infl))
        sadd(plain_key("TXT_KEY_CHOOSE_INTERNATIONAL_TRADE_ROUTE_ITEM_TT_YOUR_SCIENCE_TOTAL", theirs))
      end
    end
    if #out == 0 then return nil end
    return table.concat(out, "\n")
  end
  local science = science_lines()
  if science then
    lines[#lines + 1] = ""
    lines[#lines + 1] = science
  end
  return plain_text(table.concat(lines, "\n"))
end

local function attach_route_screen(row, from_rel, from_amt, to_rel, to_amt, origin, target, domain, pid)
  local name, amt = trade_route_pressure(from_rel, from_amt)
  if name then row.from_religion, row.from_pressure = name, amt end
  name, amt = trade_route_pressure(to_rel, to_amt)
  if name then row.to_religion, row.to_pressure = name, amt end
  local details
  local ok = pcall(function() details = trade_route_hover(origin, target, domain, pid) end)
  if ok and details then row.details = details end
end

-- Active trade routes this player owns, as the Trade Route Overview shows them. Yields are x100 in the
-- engine table; reported here per turn. `turns_left` is when the unit comes home and needs a new order.
-- A negative TurnsLeft is the engine's "no answer", not a countdown that ran out: the stock panel prints
-- an empty turns column for it (`if v.TurnsLeft >= 0` in TradeRouteOverview.lua), and it is what other
-- civs' routes into our cities carry (live t205: four incoming Ethiopian routes at -9, -11, -17, -28).
-- Passing it through read as "28 turns overdue", so omit the field exactly where the panel blanks it.
local function encode_trade_route(r, pid)
  local from_id, to_id = r.FromID, r.ToID
  local other = (from_id == pid) and to_id or from_id
  if other and other ~= pid then
    local o = Players[other]
    local team = Teams[Players[pid]:GetTeam()]
    if o and team and o.GetTeam and not team:IsHasMet(o:GetTeam()) then
      return nil
    end
  end
  local row = {
    from_city = r.FromCityName, to_city = r.ToCityName,
    from_player_id = from_id, to_player_id = to_id,
    domain = (r.Domain == 2) and "land" or "sea",
    turns_left = (type(r.TurnsLeft) == "number" and r.TurnsLeft >= 0) and r.TurnsLeft or nil,
    gold = (r.FromGPT or 0) / 100, science = (r.FromScience or 0) / 100,
    gold_them = (r.ToGPT or 0) / 100, science_them = (r.ToScience or 0) / 100,
    food_them = (r.ToFood or 0) / 100, production_them = (r.ToProduction or 0) / 100,
  }
  attach_route_screen(row, r.FromReligion, r.FromPressure, r.ToReligion, r.ToPressure,
                      r.FromCity, r.ToCity, r.Domain, pid)
  return row
end

-- Route paths. The engine draws every route's line on the map, and the plot hover names the routes that
-- cross a plot (plothelptext.lua OnMouseOverHex -> GetInternationalTradeRouteString ->
-- Player:GetInternationalTradeRoutePlotToolTip), gated on IsRevealed only. So a route's path is the set
-- of revealed plots whose hover names it: "Goshute (The Shoshone) [ICON_TURNS_REMAINING] Wittenberg (...)".
-- One scan of the map serves every row; the plots are then chained from the origin city by hex distance.
local function route_key(from_city, to_city) return from_city .. " -> " .. to_city end

local function route_paths(p, team)
  local paths = {}
  if not (p.GetInternationalTradeRoutePlotToolTip and Map and Map.GetNumPlots and Map.GetPlotByIndex) then return paths end
  -- Every revealed plot is asked, as the hover would be. (`Plot:IsTradeRoute()` is not a gate for this:
  -- it flags city-connection plots, and live t269 it skipped most of a caravan's line.)
  for i = 0, Map.GetNumPlots() - 1 do
    local plot = Map.GetPlotByIndex(i)
    if plot:IsRevealed(team, false) then
      local okt, tips = pcall(function() return p:GetInternationalTradeRoutePlotToolTip(plot) end)
      if okt and type(tips) == "table" then
        for _, tip in ipairs(tips) do
          local s = tip and tip.String
          local a, b
          -- (`x and s:match()` would keep only the first capture)
          if type(s) == "string" then a, b = s:match("^(.-) %(.-%) %[ICON_TURNS_REMAINING%] (.-) %(") end
          if a and b then
            local k = route_key(a, b)
            paths[k] = paths[k] or {}
            local e = { x = plot:GetX(), y = plot:GetY() }
            if not plot:IsVisible(team, false) then e.vis = false end
            paths[k][#paths[k] + 1] = e
          end
        end
      end
    end
  end
  return paths
end

-- Chain the plots from the origin. Unrevealed stretches split the line into pieces, so first group the
-- plots into adjacent runs, order the runs by distance from the origin, and walk each run from its end
-- nearest the previous plot. Returns the ordered plots and the number of gaps (runs - 1).
local function order_path(plots, sx, sy)
  local n = #plots
  local comp = {}
  local ncomp = 0
  for i = 1, n do
    if not comp[i] then
      ncomp = ncomp + 1
      comp[i] = ncomp
      local stack = { i }
      while #stack > 0 do
        local a = table.remove(stack)
        for j = 1, n do
          if not comp[j] and Map.PlotDistance(plots[a].x, plots[a].y, plots[j].x, plots[j].y) <= 1 then
            comp[j] = ncomp
            stack[#stack + 1] = j
          end
        end
      end
    end
  end
  local out, done, cx, cy = {}, {}, sx, sy
  for _ = 1, ncomp do
    -- next run: the one holding the unvisited plot nearest the current position
    local bi, bd
    for i = 1, n do
      if not done[comp[i]] then
        local d = cx and Map.PlotDistance(cx, cy, plots[i].x, plots[i].y) or i
        if not bd or d < bd then bi, bd = i, d end
      end
    end
    local c = comp[bi]
    done[c] = true
    local rest = {}
    for i = 1, n do if comp[i] == c then rest[#rest + 1] = plots[i] end end
    -- walk the run from an end (a plot with at most one neighbour in the run), the end nearest to
    -- where we are; otherwise the run would be entered mid-way and doubled back
    local si, sd
    for i, e in ipairs(rest) do
      local nb = 0
      for j, f in ipairs(rest) do
        if i ~= j and Map.PlotDistance(e.x, e.y, f.x, f.y) <= 1 then nb = nb + 1 end
      end
      if nb <= 1 then
        local d = cx and Map.PlotDistance(cx, cy, e.x, e.y) or i
        if not sd or d < sd then si, sd = i, d end
      end
    end
    if si then cx, cy = rest[si].x, rest[si].y else cx, cy = plots[bi].x, plots[bi].y end
    while #rest > 0 do
      local ri, rd
      for i, e in ipairs(rest) do
        local d = Map.PlotDistance(cx, cy, e.x, e.y)
        if not rd or d < rd then ri, rd = i, d end
      end
      local e = table.remove(rest, ri)
      out[#out + 1] = e
      cx, cy = e.x, e.y
    end
  end
  return out, math.max(0, ncomp - 1)
end

-- Visible enemy combat units (players at war with us, barbarians always) within one hex of a path plot:
-- the units a human sees standing beside the route line. Nothing under fog is read.
local function enemies_near_path(path, pid, team, ux, uy)
  local found, near = {}, {}
  local on_path = {}
  for _, e in ipairs(path) do on_path[e.x * 4096 + e.y] = true end
  local our_team = Teams[team]
  for i = 0, GameDefines.MAX_CIV_PLAYERS - 1 do
    local o = Players[i]
    if o and i ~= pid and o:IsAlive() and (o:IsBarbarian() or our_team:IsAtWar(o:GetTeam())) then
      for u in o:Units() do
        local plot = u:GetPlot()
        if plot and plot:IsVisible(team, false) and not u:IsInvisible(team, false) and u:IsCombatUnit() then
          local best
          for _, e in ipairs(path) do
            local d = Map.PlotDistance(u:GetX(), u:GetY(), e.x, e.y)
            if d <= 1 and (not best or d < best) then best = d end
          end
          if best then
            local row = { id = u:GetID(), owner = i, type = short(info_type(GameInfo.Units, u:GetUnitType())),
                          x = u:GetX(), y = u:GetY(), hp = u:GetCurrHitPoints(), dist_to_route = best }
            if ux then row.dist_to_caravan = Map.PlotDistance(u:GetX(), u:GetY(), ux, uy) end
            near[#near + 1] = row
          end
        end
      end
    end
  end
  return near
end

-- Our own trade unit travelling this route (any of our units is always known to us), with the combat
-- units sharing its plot: a caravan stacked with a military unit cannot be plundered without first
-- defeating that unit, so `escorted_by` is the fact a player weighs when routing through contested land.
local function caravan_row(u, pid)
  local row = { id = u:GetID(), type = short(info_type(GameInfo.Units, u:GetUnitType())), x = u:GetX(), y = u:GetY(),
                escorted_by = {} }
  local plot = u:GetPlot()
  for i = 0, plot:GetNumUnits() - 1 do
    local d = plot:GetUnit(i)
    if d and d:GetOwner() == pid and d:IsCombatUnit() then
      row.escorted_by[#row.escorted_by + 1] = { id = d:GetID(), type = short(info_type(GameInfo.Units, d:GetUnitType())), hp = d:GetCurrHitPoints() }
    end
  end
  if #row.escorted_by == 0 then row.escorted_by = nil; row.escorted = false else row.escorted = true end
  return row
end

-- Routes share plots (live t269: two Addis Ababa routes ran the same eleven plots), so a caravan that
-- fits only one route is placed first, and the rest take the first route still without a unit.
local function assign_own_caravans(rows, on_paths, p, pid)
  local units, cands = {}, {}
  for u in p:Units() do
    if u:IsTrade() and u:IsAutomated() then
      local key = u:GetX() * 4096 + u:GetY()
      local c = {}
      for i, row in ipairs(rows) do if on_paths[i] and on_paths[i][key] then c[#c + 1] = i end end
      if #c > 0 then units[#units + 1] = u; cands[#units] = c end
    end
  end
  local taken = {}
  for pass = 1, 2 do
    for k, u in ipairs(units) do
      if cands[k] and (pass == 2 or #cands[k] == 1) then
        for _, i in ipairs(cands[k]) do
          if not taken[i] then
            taken[i] = true
            rows[i].unit = caravan_row(u, pid)
            cands[k] = nil
            break
          end
        end
      end
    end
  end
end

-- A foreign caravan on a visible plot of its route: the unit a human sees moving along the line.
local function foreign_caravan_on(path, owner, team)
  for _, e in ipairs(path) do
    if e.vis ~= false then
      local plot = Map.GetPlot(e.x, e.y)
      for i = 0, plot:GetNumUnits() - 1 do
        local u = plot:GetUnit(i)
        if u and u:GetOwner() == owner and u:IsTrade() and not u:IsInvisible(team, false) then
          return { id = u:GetID(), type = short(info_type(GameInfo.Units, u:GetUnitType())), x = e.x, y = e.y }
        end
      end
    end
  end
  return nil
end

-- Adds `path` (ordered from the origin), `path_plots`, `path_fogged`, `path_gaps` to the row and, for a
-- foreign route, the caravan in sight. Returns the set of plot keys on the line (city plots included)
-- so own caravans can be placed afterwards.
local function attach_route_path(row, r, paths, team)
  local plots = paths[route_key(r.FromCityName or "", r.ToCityName or "")]
  if not plots then return nil end
  local fc, tc = r.FromCity, r.ToCity
  local path, gaps = order_path(plots, fc and fc:GetX(), fc and fc:GetY())
  row.path = path
  row.path_plots = #path
  if gaps > 0 then row.path_gaps = gaps end
  local fogged = 0
  for _, e in ipairs(path) do if e.vis == false then fogged = fogged + 1 end end
  if fogged > 0 then row.path_fogged = fogged end
  local on_path = {}
  for _, e in ipairs(path) do on_path[e.x * 4096 + e.y] = true end
  if fc then on_path[fc:GetX() * 4096 + fc:GetY()] = true end
  if tc then on_path[tc:GetX() * 4096 + tc:GetY()] = true end
  return on_path
end

local function attach_enemies(row, pid, team)
  if not row.path then return end
  local ux, uy = row.unit and row.unit.x, row.unit and row.unit.y
  local near = enemies_near_path(row.path, pid, team, ux, uy)
  if #near > 0 then row.enemies_near_path = near end
end

function H.trade_routes(pid)
  local p = Players[pid]
  if not p.GetTradeRoutes then return { ok = false, err = "GetTradeRoutes unavailable" } end
  local team = p:GetTeam()
  local outgoing, incoming = {}, {}
  local paths = route_paths(p, team)
  local on_paths = {}
  for _, r in ipairs(p:GetTradeRoutes() or {}) do
    local e = encode_trade_route(r, pid)
    if e then
      outgoing[#outgoing + 1] = e
      local ok, set = pcall(attach_route_path, e, r, paths, team)
      if ok then on_paths[#outgoing] = set end
    end
  end
  pcall(assign_own_caravans, outgoing, on_paths, p, pid)
  for _, e in ipairs(outgoing) do pcall(attach_enemies, e, pid, team) end
  -- Trade Route Overview tab "With You": other civs' caravans into our cities.
  pcall(function()
    if not p.GetTradeRoutesToYou then return end
    for _, r in ipairs(p:GetTradeRoutesToYou() or {}) do
      local e = encode_trade_route(r, pid)
      if e then
        incoming[#incoming + 1] = e
        pcall(attach_route_path, e, r, paths, team)
        if e.path and r.FromID and r.FromID ~= pid then
          pcall(function() e.unit = foreign_caravan_on(e.path, r.FromID, team) end)
        end
        pcall(attach_enemies, e, pid, team)
      end
    end
  end)
  local out = { ok = true, outgoing = outgoing, incoming = incoming }
  if next(paths) then
    out.note = "path is the route line the map draws, ordered from the origin (plot hover names it on any revealed plot; vis=false plots are fogged; path_gaps counts unrevealed stretches). unit is the caravan/cargo ship on the line with escorted_by = own combat units on its plot; enemies_near_path are visible enemy combat units within one hex of the line."
  end
  return out
end

function H.plunder_trade_route(unit_id, pid)
  return H.unit_mission(unit_id, "MISSION_PLUNDER_TRADE_ROUTE", -1, -1, nil, pid)
end

-- `Players[pid]:GetTradeRoutesAvailable()` (the old implementation here) is the WRONG API for this: it
-- returns entries with an `eDomain` (0/2) field, not the `TradeConnectionType` that
-- `MISSION_ESTABLISH_TRADE_ROUTE`'s data2 slot actually wants -- confirmed live, passing a Domain value
-- there gets an unconditional {ok=true} back but the unit never leaves the city (mission stays -1). The
-- real game UI (chooseinternationaltraderoutepopup.lua's RefreshData) gets its list, and the exact
-- TradeConnectionType it later passes back into the mission call, from the *per-unit*
-- `player:GetPotentialInternationalTradeRouteDestinations(unit)` instead. This mirrors that.
-- Why this trade unit has nowhere to go. Stock puts the Create Trade Route button on the unit panel
-- only inside one of my cities, and the chooser it opens can still come up empty when nothing is in
-- range. An empty list said neither (live t221: three caravans walking home with 0 moves, and
-- `overview.idle_trade_units` calling all three idle).
function H.no_trade_route_reason(u, p, pid)
  local plot = u:GetPlot()
  local city = plot and plot:IsCity() and plot:GetPlotCity()
  if city and city:GetOwner() == pid then
    return { err = "no trade route from " .. city:GetName() .. " is available right now: nothing in range, or every destination already has one" }
  end
  -- Not in one of my cities: the button is not on the panel at all. Say where to take it.
  local best, best_d
  for c in p:Cities() do
    local d = Map.PlotDistance(u:GetX(), u:GetY(), c:GetX(), c:GetY())
    if not best_d or d < best_d then best, best_d = c, d end
  end
  local out = { err = "a trade route starts inside one of my own cities; this unit is in the field at ("
                      .. u:GetX() .. "," .. u:GetY() .. ")" }
  if best then
    out.nearest_city = { name = best:GetName(), x = best:GetX(), y = best:GetY(), distance = best_d }
    out.hint = "move it to " .. best:GetName() .. " (" .. best:GetX() .. "," .. best:GetY() .. "), then ask again"
  end
  if u:MovesLeft() == 0 then out.moves_left = 0; out.note = "it has no moves left this turn" end
  return out
end

function H.available_trade_routes(unit_id, pid)
  local p = Players[pid]
  local u = p:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  if not u:IsTrade() then return { ok = false, err = "not a trade unit (caravan or cargo ship)" } end
  if not p.GetPotentialInternationalTradeRouteDestinations then return {} end
  local out = {}
  for _, v in ipairs(p:GetPotentialInternationalTradeRouteDestinations(u)) do
    local plot = Map.GetPlot(v.X, v.Y)
    local city = plot and plot:GetPlotCity()
    local owner = city and city:GetOwner()
    -- Yields come back x100 (611 = 6.11/turn, what the trade-route chooser shows as +6). Report per
    -- turn for both ends: `gold`/`science`/`food`/`production` are what MY end receives, `*_them` what
    -- the destination gets (internal food/production routes deliver to the destination city, so for
    -- those the useful number is food_them/production_them).
    local mine, theirs = {}, {}
    for j, y in ipairs(v.Yields) do
      local yieldType = j - 1
      local key = ({ [YieldTypes.YIELD_GOLD] = "gold", [YieldTypes.YIELD_SCIENCE] = "science",
                     [YieldTypes.YIELD_FOOD] = "food", [YieldTypes.YIELD_PRODUCTION] = "production",
                     [YieldTypes.YIELD_CULTURE] = "culture", [YieldTypes.YIELD_FAITH] = "faith" })[yieldType]
      if key then mine[key] = (y.Mine or 0) / 100; theirs[key] = (y.Theirs or 0) / 100 end
    end
    local kind = ({ [0] = "international", [1] = "food", [2] = "production" })[v.TradeConnectionType] or tostring(v.TradeConnectionType)
    local row = {
      x = v.X, y = v.Y, trade_connection_type = v.TradeConnectionType, kind = kind,
      city_name = city and city:GetName() or nil,
      civ_name = owner and Players[owner]:GetCivilizationDescription() or nil,
      target_player_id = owner, gold = mine.gold or 0, science = mine.science or 0,
      food = mine.food or 0, production = mine.production or 0,
      gold_them = theirs.gold or 0, science_them = theirs.science or 0,
      food_them = theirs.food or 0, production_them = theirs.production or 0,
      prev_route = v.OldTradeRoute and true or false,
    }
    local origin_plot = u.GetPlot and u:GetPlot() or nil
    local origin_city = origin_plot and origin_plot.GetPlotCity and origin_plot:GetPlotCity() or nil
    local domain
    if u.GetDomainType then
      local ok_d, d = pcall(function() return u:GetDomainType() end)
      if ok_d then domain = d end
    end
    attach_route_screen(row, v.FromReligion, v.FromPressureAmount or v.FromPressure,
                        v.ToReligion, v.ToPressureAmount or v.ToPressure,
                        origin_city, city, domain, pid)
    out[#out + 1] = row
  end
  if #out == 0 then
    local why = H.no_trade_route_reason(u, p, pid)
    why.ok, why.unit_id, why.routes = false, unit_id, {}
    return why
  end
  return out
end
