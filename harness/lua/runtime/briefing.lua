-- Shared by earlier fragments (load order: harness/runtime_source.py MANIFEST).
local L, info_type, plain_key, short = H._ns.L, H._ns.info_type, H._ns.plain_key, H._ns.short

-- The board half of the turn briefing (#30), in one read for `pid`'s own view:
--   events: the seat's recorded events after `since_seq` (H.events_since: the digest cursor is not moved,
--           so the briefing and turn_digest / finish_turn each see every event once and neither eats the
--           other's); -1 means after the seat's last turn_end; nil reads none. event_seq is the log's head,
--           the next baseline.
--   threats: visible combat units of a player this seat is at war with (barbarians included) within 4
--           plots of one of its cities or 2 of one of its units, with the nearest of each. Only plots the
--           seat sees now are read, as on the map; nothing is estimated here.
--   camps: revealed barbarian camps within 4 plots of a city (the map shows a camp on a revealed plot).
--   traits: the leader's trait name and text, the rule the civilization plays under (Venice: no settlers).
--   territory: every plot this seat owns now, as "x,y" (v270). The next briefing diffs it against the
--           baseline's list: a plot gone from it is land a neighbour's Citadel took or a city lost, which the
--           map shows as a border change and the notification only names by civ (live England t216:
--           "Ashurbanipal used a Great General to steal some of your land!", no plot).
-- Another seat's units, cities, events or fog are never read.
function H.briefing_board(pid, since_seq)
  local p = Players[pid]
  local out = { event_seq = H.event_seq or 0, threats = {}, camps = {} }
  if Map.GetNumPlots and Map.GetPlotByIndex then
    local owned = {}
    for i = 0, Map.GetNumPlots() - 1 do
      local q = Map.GetPlotByIndex(i)
      if q and q:GetOwner() == pid then owned[#owned + 1] = q:GetX() .. "," .. q:GetY() end
    end
    out.territory = owned
  end
  if since_seq == -1 then
    -- "this turn": everything after the seat's own last turn_end -- the other players' moves, then this turn.
    since_seq = 0
    for i = #H.events, 1, -1 do
      local e = H.events[i]
      if e.audience == pid and e.kind == "turn_end" then since_seq = e.seq; break end
    end
  end
  if since_seq ~= nil then out.since_seq = since_seq; out.events = H.events_since(since_seq, pid) end
  local team = p:GetTeam()
  local cities, mine = {}, {}
  for c in p:Cities() do cities[#cities + 1] = { id = c:GetID(), name = c:GetName(), x = c:GetX(), y = c:GetY() } end
  for u in p:Units() do
    if not u:IsDelayedDeath() then
      mine[#mine + 1] = { id = u:GetID(), type = short(info_type(GameInfo.Units, u:GetUnitType())), x = u:GetX(), y = u:GetY() }
    end
  end
  local function nearest(list, x, y)
    local best, bd
    for _, r in ipairs(list) do
      local d = Map.PlotDistance(r.x, r.y, x, y)
      if not bd or d < bd then best, bd = r, d end
    end
    return best, bd
  end
  for other = 0, 63 do
    local dp = Players[other]
    if other ~= pid and dp and (not dp.IsAlive or dp:IsAlive())
       and (dp:IsBarbarian() or Teams[team]:IsAtWar(dp:GetTeam())) then
      for d in dp:Units() do
        local q = d:GetPlot()
        if d:IsCombatUnit() and not d:IsDelayedDeath() and q and q:IsVisible(team, false) and not d:IsInvisible(team, false) then
          local c, cd = nearest(cities, d:GetX(), d:GetY())
          local u, ud = nearest(mine, d:GetX(), d:GetY())
          if (cd and cd <= 4) or (ud and ud <= 2) then
            local row = { id = d:GetID(), owner = H.owner_label(other, pid), player_id = other,
                          unit = short(info_type(GameInfo.Units, d:GetUnitType())), x = d:GetX(), y = d:GetY(),
                          hp = d:GetCurrHitPoints(), strength = d:GetBaseCombatStrength() }
            local rs = H.ranged_strength(d)
            if rs > 0 then row.ranged_strength = rs end
            if c then row.near_city = { id = c.id, name = c.name, distance = cd } end
            if u then row.near_unit = { id = u.id, type = u.type, distance = ud } end
            out.threats[#out.threats + 1] = row
          end
        end
      end
    end
  end
  local camp = GameInfoTypes and GameInfoTypes.IMPROVEMENT_BARBARIAN_CAMP
  if camp then
    local seen = {}
    for _, c in ipairs(cities) do
      for dx = -4, 4 do for dy = -4, 4 do
        local q = Map.PlotXYWithRangeCheck(c.x, c.y, dx, dy, 4)
        if q and q:IsRevealed(team, false) and q:GetRevealedImprovementType(team, false) == camp then
          local k = q:GetX() .. "," .. q:GetY()
          if not seen[k] then
            seen[k] = true
            out.camps[#out.camps + 1] = { x = q:GetX(), y = q:GetY(), visible = q:IsVisible(team, false),
                                          near_city = { id = c.id, name = c.name,
                                                        distance = Map.PlotDistance(c.x, c.y, q:GetX(), q:GetY()) } }
          end
        end
      end end
    end
  end
  pcall(function()
    local leader = GameInfo.Leaders[p:GetLeaderType()]
    local traits = {}
    for row in GameInfo.Leader_Traits{ LeaderType = leader.Type } do
      local t = GameInfo.Traits[row.TraitType]
      if t then traits[#traits + 1] = { trait = t.Type, name = plain_key(t.ShortDescription) or L(t.ShortDescription),
                                        text = plain_key(t.Description) or L(t.Description) } end
    end
    out.traits = traits
  end)
  return out
end

-- The plots the baseline listed as mine and the board no longer does, as they stand now: owner (by the
-- seat's own map: GetRevealedOwner on a fogged plot), the improvement, the resource (a revealed one), the
-- city on it. Read only when the diff found a loss, so a quiet turn costs nothing extra. `plots` is
-- {{x, y}, ...}. The resource the plot carried is what the loss costs; nothing is estimated here.
function H.territory_now(pid, plots)
  local team = Players[pid]:GetTeam()
  local out = {}
  for _, r in ipairs(plots or {}) do
    local x, y = r[1] or r.x, r[2] or r.y
    local q = Map.GetPlot(x, y)
    local row = { x = x, y = y }
    if q then
      local vis = q:IsVisible(team, false) and true or false
      row.vis = vis and "visible" or "fogged"
      local own = vis and q:GetOwner() or q:GetRevealedOwner(team, false)
      if own >= 0 then row.owner = own; row.owner_name = H.owner_label(own, pid) end
      local imp = vis and q:GetImprovementType() or q:GetRevealedImprovementType(team, false)
      if imp >= 0 then row.improvement = short(info_type(GameInfo.Improvements, imp)) end
      local res = q:GetResourceType(team)
      if res and res >= 0 then row.resource = short(info_type(GameInfo.Resources, res)) end
      if vis and q:IsCity() then
        local c = q:GetPlotCity()
        row.city = { id = c:GetID(), name = c:GetName(), owner = c:GetOwner(), owner_name = H.owner_label(c:GetOwner(), pid) }
      end
    else
      row.off_map = true
    end
    out[#out + 1] = row
  end
  return out
end
