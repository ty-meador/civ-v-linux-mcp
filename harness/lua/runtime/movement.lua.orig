-- Shared by earlier fragments (load order: harness/runtime_source.py MANIFEST).
local do_command, info_id, info_type = H._ns.do_command, H._ns.info_id, H._ns.info_type
local move_denom, own_active_unit = H._ns.move_denom, H._ns.own_active_unit
local peaceful_occupant_err, push_mission = H._ns.peaceful_occupant_err, H._ns.push_mission
local require_revealed_plot, short = H._ns.require_revealed_plot, H._ns.short

-- Snapshot of the city a religious unit (Missionary / Inquisitor / Prophet) would act on: the city on
-- its own plot or an adjacent one. Used by unit_mission to measure MISSION_SPREAD_RELIGION /
-- MISSION_REMOVE_HERESY instead of trusting PushMission's unconditional acceptance.
function H.religion_target(unit_id, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  local rel = u.GetReligion and u:GetReligion() or -1
  local city = nil
  local here = Map.GetPlot(u:GetX(), u:GetY())
  if here and here:IsCity() then city = here:GetPlotCity() end
  if not city then
    for d = 0, DirectionTypes.NUM_DIRECTION_TYPES - 1 do
      local p = Map.PlotDirection(u:GetX(), u:GetY(), d)
      if p and p:IsCity() then city = p:GetPlotCity(); break end
    end
  end
  local out = { ok = true, unit_religion = rel, spreads_left = u.GetSpreadsLeft and u:GetSpreadsLeft() or nil,
                strength = u.GetConversionStrength and u:GetConversionStrength() or nil }
  if rel and rel >= 0 and Game.GetReligionName then out.unit_religion_name = H.L(Game.GetReligionName(rel)) end
  if not city then out.city = nil; return out end
  return H.city_religion_state(city, rel, pid, out)
end

-- The city half of religion_target, keyed by city plot so it can be re-read after the acting unit
-- was consumed by its last charge (unit_id is gone by then).
function H.city_religion_at(x, y, rel, pid)
  local p = Map.GetPlot(x, y)
  if not p or not p:IsCity() then return { ok = false, err = "no city at that plot" } end
  return H.city_religion_state(p:GetPlotCity(), rel, pid, { ok = true, unit_religion = rel })
end

function H.city_religion_state(city, rel, pid, out)
  local owner = city:GetOwner()
  local maj = city:GetReligiousMajority()
  out.city = city:GetName(); out.city_owner = owner; out.x = city:GetX(); out.y = city:GetY()
  out.population = city:GetPopulation()
  out.majority = maj
  if maj >= 0 and Game.GetReligionName then out.majority_name = H.L(Game.GetReligionName(maj)) end
  out.followers = (rel and rel >= 0) and city:GetNumFollowers(rel) or nil
  out.majority_followers = maj >= 0 and city:GetNumFollowers(maj) or nil
  local op = Players[owner]
  if op and op:IsMinorCiv() then out.influence = op:GetMinorCivFriendshipWithMajor(pid) end
  return out
end

function H.move_unit(unit_id, x, y, pid)
  local u, err = own_active_unit(unit_id, pid)
  if not u then return err end
  local blocked = require_revealed_plot(x, y, pid, u)
  if blocked then return blocked end
  local m = info_id("MISSION_MOVE_TO")
  if m == nil then return { ok = false, err = "unknown mission" } end
  local legal = false
  if u.CanStartMission then
    local ok, v = pcall(function() return u:CanStartMission(m, x, y, false) end)
    legal = ok and v
  end
  if not legal then return { ok = false, err = "move is not currently legal" } end
  -- CanStartMission(MOVE_TO) is true for any valid plot, even one no path reaches (a natural
  -- wonder / mountain, or across unexplored water): the engine then drops the mission silently.
  local dest = Map.GetPlot(x, y)
  local refused = H.move_refusal(u, dest, pid, false)
  if refused then return refused end
  local x0, y0, m0 = u:GetX(), u:GetY(), u:MovesLeft()
  -- A move onto one of our own units of the same class is a swap: the engine walks the other unit
  -- back to this plot (live t252: a Worker ordered into Goshute traded places with the Worker there,
  -- which ended the turn on the far tile with no moves). A human watches the second unit hop; the
  -- reply only said "arrived". Remember who stood on the destination so _move_unit can report the
  -- one now standing here as `swapped_with`.
  local swap_candidates = nil
  pcall(function()
    if not dest then return end
    for i = 0, dest:GetNumUnits() - 1 do
      local o = dest:GetUnit(i)
      if o and o:GetOwner() == pid and o:GetID() ~= u:GetID() and not o:IsDelayedDeath()
         and not (DomainTypes and o:GetDomainType() == DomainTypes.DOMAIN_AIR) then
        swap_candidates = swap_candidates or {}
        local ot = GameInfo.Units[o:GetUnitType()]
        swap_candidates[#swap_candidates + 1] = { id = o:GetID(), type = ot and short(ot.Type) or o:GetUnitType() }
      end
    end
  end)
  local pushed = push_mission(u, m, x, y)
  if not pushed.ok then return pushed end
  -- Remember the destination: a MOVE_TO that needs more than this turn does NOT resume by itself at the
  -- next turn start (live, Caravel t256-264), so H.resume_moves re-pushes it until the unit arrives.
  -- Never for an attack: the unit does not "arrive", so the standing order re-fired as a second,
  -- unordered attack at the next turn start (live 2026-09-18, warrior vs a camp Brute: 73 -> 42 hp).
  if H.melee_defender(u, Map.GetPlot(x, y), pid) or H.enemy_city_at(Map.GetPlot(x, y), pid) then
    H.pending_moves[H.pm_key(unit_id, pid)] = nil
  else
    H.pending_moves[H.pm_key(unit_id, pid)] = { x = x, y = y, pid = pid, unit_id = unit_id }
  end
  return { ok = true, x = x0, y = y0, moves = m0 / move_denom(), swap_candidates = swap_candidates }
end

-- The destination checks move_unit makes before it sends anything: each is an order the engine accepts and
-- then drops without a word. Shared with H.tactical_view so the view's "refused" is exactly move_unit's.
-- fog_safe (the view) reads a fogged plot's owner as the last-seen one, never the live one; move_unit keeps
-- its live read (the engine's own answer to the order would use it too).
function H.move_refusal(u, dest, pid, fog_safe)
  -- Unit:GeneratePath is NYI in this build (throws). Plot:MovementCost crashed the live process
  -- (t183, 2026-09-19) even inside pcall -- do not call it. GetPathEndTurnPlot is nil without a
  -- mouse-driven UI pathfinder. Do not fake turns-to-reach. So the checks are per-destination-plot:
  -- IsImpassable catches natural wonders (Uluru), IsMountain catches mountains (whose terrain type
  -- still reads GRASS/PLAINS, so callers can't tell from the map), CanMoveOrAttackInto catches the rest.
  if dest and dest:IsImpassable() and not (u.CanMoveImpassable and u:CanMoveImpassable()) then
    return { ok = false, err = "destination plot is impassable" }
  end
  -- Domain: a ship ordered onto land (or a land unit onto water before Optics) is dropped silently by
  -- the engine (live t252: Caravel -> a newly sighted plains plot, ok:true, never moved). Say so.
  if dest and DomainTypes then
    local dom = u:GetDomainType()
    if dom == DomainTypes.DOMAIN_SEA and not dest:IsWater() and not dest:IsCity() then
      return { ok = false, err = "destination is land; a sea unit can only enter water plots or a coastal city" }
    end
    -- Unit:CanEmbark(plot) asks whether it can embark FROM that plot: false for any inland unit even with
    -- Optics (live t412: a Missionary at (35,29), team can embark, refused as "needs Optics"). Ask whether the
    -- unit can embark at all: its embarkation promotion, or the team-wide ability.
    local canEmbark = false
    pcall(function() canEmbark = u:IsHasPromotion(GameInfoTypes.PROMOTION_EMBARKATION) end)
    if not canEmbark then pcall(function() canEmbark = Teams[u:GetTeam()]:CanEmbark() end) end
    if dom == DomainTypes.DOMAIN_LAND and dest:IsWater() and not canEmbark then
      return { ok = false, err = "destination is water and this unit cannot embark (needs Optics; a ship or cargo ship is the alternative)" }
    end
  end
  if dest and dest:IsMountain() then
    local ok, can = pcall(function() return u:CanMoveOrAttackInto(dest) end)
    if not (ok and can) then return { ok = false, err = "destination plot is a mountain" } end
  end
  -- NOTE: CanMoveOrAttackInto(dest) is false for perfectly legal multi-step destinations (live: a
  -- warrior moving into its own adjacent city), so it is only consulted for the mountain case above.
  -- One combat unit per tile: a move whose destination already holds one of our own combat units
  -- (e.g. "send the new bowman to Nanjing" while a warrior garrisons it) has no legal end plot and is
  -- dropped silently by the engine (live, turn 110). Refuse it up front.
  if dest and u:IsCombatUnit() then
    for i = 0, dest:GetNumUnits() - 1 do
      local o = dest:GetUnit(i)
      if o and o:GetOwner() == u:GetOwner() and o:GetID() ~= u:GetID() and o:IsCombatUnit()
         and o:GetDomainType() == u:GetDomainType() then
        return { ok = false, err = "destination already holds one of your combat units (one per tile); pick an adjacent plot or move that unit first" }
      end
    end
  end
  -- Nobody enters another player's city plot at peace: CanStartMission says yes, the engine drops the
  -- mission silently, and the unit sits there with full moves blocking the turn. Live t213: a Missionary
  -- ordered onto Lhasa's own plot (49,5) to answer its spread-religion quest lost two turns to this
  -- before an adjacent plot worked; the same shape is noted at t266 in resume_moves. At war the move is
  -- an attack and stays legal. Only for a plot we have revealed -- that is when a human sees the banner
  -- and would be refused by the same rule.
  local occupied_city = nil
  pcall(function()
    local myTeam = Players[pid]:GetTeam()
    if not (dest and dest:IsCity() and dest:IsRevealed(myTeam)) then return end
    local c = dest:GetPlotCity()
    if not c or c:GetOwner() == pid or c:GetTeam() == myTeam then return end
    -- The view never names a city founded in the fog since the plot was last seen: the engine's per-team
    -- city reveal flag is the banner a human has on the map.
    if fog_safe and not dest:IsVisible(myTeam, false) and not c:IsRevealed(myTeam, false) then return end
    if Teams[myTeam]:IsAtWar(c:GetTeam()) then return end
    occupied_city = { ok = false, err = "that plot is the city of " .. c:GetName() ..
      ", which cannot be entered while at peace; move to a plot next to it instead (a Missionary, "
      .. "Great Person or trade unit does its job from an adjacent plot)",
      city = { name = c:GetName(), owner = c:GetOwner(), x = dest:GetX(), y = dest:GetY() } }
  end)
  if occupied_city then return occupied_city end
  -- Another major civ's territory is closed without open borders (or war); the engine finds no path
  -- and drops the order silently (live t256: Caravel -> India's coast). Name the owner instead.
  local closed = nil
  pcall(function()
    local owner = dest and dest:GetOwner() or -1
    if fog_safe and dest and not dest:IsVisible(Players[pid]:GetTeam(), false) then
      owner = dest:GetRevealedOwner(Players[pid]:GetTeam(), false)
    end
    if owner >= 0 and owner ~= pid then
      local o = Players[owner]
      local myTeam, theirTeam = Teams[Players[pid]:GetTeam()], o and Teams[o:GetTeam()] or nil
      if o and theirTeam and not o:IsMinorCiv() and not myTeam:IsAtWar(o:GetTeam())
         and not (theirTeam.IsAllowsOpenBordersToTeam and theirTeam:IsAllowsOpenBordersToTeam(Players[pid]:GetTeam())) then
        closed = { ok = false, err = "destination is inside " .. o:GetCivilizationShortDescription()
                   .. "'s borders and you have no open-borders agreement with them (trade one via propose_deal, or path around)",
                   owner_player_id = owner }
      end
    end
  end)
  if closed then return closed end
  local occ = H.peaceful_occupant(dest, pid)
  if occ then return { ok = false, err = peaceful_occupant_err(occ) } end
  return nil
end

-- Every seat's units share one id space (seat 0 and seat 1 both start with a Worker 57350), so a standing
-- order is filed under the seat as well as the unit. Live 2026-09-24 t214 (two-human hotseat): seat 1's
-- untouched Worker was refused MISSION_SKIP as "already on a multi-turn move" -- the record was seat 0's
-- Worker of the same id, and seat 0's Settler orders were being overwritten by seat 1's in the same way.
function H.pm_key(unit_id, pid)
  return tostring(pid or 0) .. ":" .. tostring(unit_id)
end

-- Where a standing move is taking `u` (#37): the destination move_unit stored for it, nil when there is
-- none or the unit already stands on it (an arrived record is stale bookkeeping, not a plan).
function H.going_to(u, pid)
  local pm = H.pending_moves[H.pm_key(u:GetID(), pid)]
  if not pm or pm.pid ~= pid then return nil end
  if pm.x == u:GetX() and pm.y == u:GetY() then return nil end
  return { x = pm.x, y = pm.y }
end

-- Why an ongoing unit (automated, or walking a standing move) needs the seat back this turn (#37): a
-- barbarian camp on or beside its plot, a hostile combat unit beside it, or a destination the seat can no
-- longer path to. Only plots this seat can see are read (a fogged neighbour is as unknown here as on the
-- map); nothing is read about the destination beyond the static revealed/impassable facts. nil when the
-- unit is merely moving: an explorer walking into the unknown is the ordinary case, not an alert.
function H.ongoing_attention(u, pid, going)
  local out = {}
  local p = Players[pid]
  local team = p:GetTeam()
  local imp = GameInfoTypes and GameInfoTypes.IMPROVEMENT_BARBARIAN_CAMP
  local x, y = u:GetX(), u:GetY()
  pcall(function()
    for dy = -1, 1 do
      for dx = -1, 1 do
        local q = Map.GetPlot(x + dx, y + dy)
        if q and Map.PlotDistance(x, y, q:GetX(), q:GetY()) <= 1 and q:IsVisible(team, false) then
          if imp and q:GetRevealedImprovementType(team, false) == imp then
            out[#out + 1] = { kind = "camp", x = q:GetX(), y = q:GetY() }
          end
          if not (dx == 0 and dy == 0) then
            for i = 0, q:GetNumUnits() - 1 do
              local d = q:GetUnit(i)
              if d and d:GetOwner() ~= pid and d:IsCombatUnit() and not d:IsInvisible(team, false) then
                local dp = Players[d:GetOwner()]
                if dp and (dp:IsBarbarian() or Teams[team]:IsAtWar(dp:GetTeam())) then
                  out[#out + 1] = { kind = "hostile", owner = H.owner_label(d:GetOwner(), pid),
                                    unit = short(info_type(GameInfo.Units, d:GetUnitType())),
                                    x = q:GetX(), y = q:GetY(), hp = d:GetCurrHitPoints() }
                end
              end
            end
          end
        end
      end
    end
  end)
  if going then
    local q = Map.GetPlot(going.x, going.y)
    if not q then
      out[#out + 1] = { kind = "destination_gone", x = going.x, y = going.y }
    elseif not q:IsRevealed(team, false) then
      out[#out + 1] = { kind = "destination_unrevealed", x = going.x, y = going.y }
    else
      local oki, imp2 = pcall(function() return q:IsImpassable() end)
      if oki and imp2 then out[#out + 1] = { kind = "destination_impassable", x = going.x, y = going.y } end
    end
  end
  return #out > 0 and out or nil
end

-- After a move settled: which of `ids` (the units that stood on the destination when the order went
-- out) now stands on (x, y), the mover's old plot. That unit was swapped, not stepped over.
function H.swapped_unit(ids, x, y, pid)
  local p = Players[pid]
  for _, id in ipairs(ids or {}) do
    local o = p:GetUnitByID(id)
    if o and not o:IsDelayedDeath() and o:GetX() == x and o:GetY() == y then
      local ot = GameInfo.Units[o:GetUnitType()]
      return { ok = true, unit = { id = id, type = ot and short(ot.Type) or o:GetUnitType(), x = x, y = y,
                                   moves = o:MovesLeft() / move_denom() } }
    end
  end
  return { ok = true }
end

-- A multi-turn move pushed from Lua does NOT resume at the next turn start (live: Caravel, t256-258):
-- the unit sits in ACTIVITY_MISSION with a queued MOVE_TO, moves still in hand, and the engine will
-- not spend them. That is the "stalled" shape, and such a unit DOES block end_turn. todo() and the
-- MISSION_SKIP guard both have to agree about it -- they did not (live t186: turn_status listed Great
-- General 335877 as blocking with stalled_mission=true while unit_mission(MISSION_SKIP) refused it as
-- "already on a multi-turn move and does not block end_turn"), so they now ask the same function.
-- A Worker mid-build also idles at full moves and is not stalled.
function H.is_stalled_mission(u)
  if not (u and u.GetActivityType and u:GetActivityType() == 6) then return false end
  if not (u.MovesLeft and u:MovesLeft() > 0) then return false end
  if u.GetBuildType and u:GetBuildType() ~= -1 then return false end
  return true
end

-- Re-issue standing move orders whose unit is idle at full moves (the "stalled_mission" shape) and drop
-- the ones that arrived or whose unit is gone. Called by wait_for_my_turn once the turn is ours.
function H.resume_moves(pid)
  local out = {}
  for key, pm in pairs(H.pending_moves) do
    if pm.pid == pid then
      local id = pm.unit_id or key
      local u = Players[pid]:GetUnitByID(id)
      if not u or u:IsDelayedDeath() then
        H.pending_moves[key] = nil
      elseif u:GetX() == pm.x and u:GetY() == pm.y then
        H.pending_moves[key] = nil
        out[#out + 1] = { unit_id = id, x = pm.x, y = pm.y, arrived = true }
      elseif u:MovesLeft() > 0 and u:MovesLeft() == u:MaxMoves()
             and not (u.GetBuildType and u:GetBuildType() ~= -1) then
        -- No progress since the last resume (same plot a whole turn later) means the engine keeps
        -- dropping the path (e.g. a Missionary ordered INTO a foreign city plot, t266): stop re-issuing
        -- and tell the caller, rather than pushing the same dead order every turn forever.
        if H.melee_defender(u, Map.GetPlot(pm.x, pm.y), pid) or H.enemy_city_at(Map.GetPlot(pm.x, pm.y), pid) then
          -- An enemy now stands on the destination: re-issuing the move would be an attack nobody ordered.
          H.pending_moves[key] = nil
          out[#out + 1] = { unit_id = id, x = pm.x, y = pm.y, dropped = true,
                            err = "an enemy unit now stands on the destination; move_unit there again to attack it" }
        elseif H.peaceful_occupant(Map.GetPlot(pm.x, pm.y), pid) then
          H.pending_moves[key] = nil
          out[#out + 1] = { unit_id = id, x = pm.x, y = pm.y, dropped = true,
                            err = peaceful_occupant_err(H.peaceful_occupant(Map.GetPlot(pm.x, pm.y), pid)) }
        elseif pm.last_x == u:GetX() and pm.last_y == u:GetY() then
          H.pending_moves[key] = nil
          out[#out + 1] = { unit_id = id, x = pm.x, y = pm.y, dropped = true,
                            err = "no progress toward the destination for a full turn; the engine finds no path -- pick another plot" }
        else
          pm.last_x, pm.last_y = u:GetX(), u:GetY()
          local r = H.move_unit(id, pm.x, pm.y, pid)
          if r.ok then
            H.pending_moves[key] = pm  -- H.move_unit replaced the record; keep the progress marker
            out[#out + 1] = { unit_id = id, x = pm.x, y = pm.y, resumed = true }
          else
            H.pending_moves[key] = nil
            out[#out + 1] = { unit_id = id, x = pm.x, y = pm.y, dropped = true, err = r.err }
          end
        end
      end
    end
  end
  return out
end

-- MISSION_FOUND pre/post check. PushMission(MISSION_FOUND) returns "ok" even when the settler has no
-- moves left (live t283: the standing order had just walked it onto the site, activity went to HOLD and
-- no city appeared), so the wrapper reads this before and after. (x, y) is the settler's plot, kept by
-- the caller because the unit is consumed on success.
function H.found_check(unit_id, x, y, pid)
  local p = Players[pid]
  local u = p:GetUnitByID(unit_id)
  local out = { ok = true, unit_exists = u ~= nil }
  if u then
    x, y = u:GetX(), u:GetY()
    out.x, out.y = x, y
    out.moves = u:MovesLeft() / GameDefines.MOVE_DENOMINATOR
    -- Unit:CanFound(plot, n) wants a number for arg 2 (a boolean raises "number expected", the pcall
    -- swallowed it and every MISSION_FOUND was refused as "cannot found"; live t284). Omit it.
    local okc, v = pcall(function() return u:CanFound(u:GetPlot()) end)
    out.can_found = okc and v and true or false
  end
  local pl = (x and y) and Map.GetPlot(x, y) or nil
  if pl and pl:IsCity() then
    local c = pl:GetPlotCity()
    out.city = { id = c:GetID(), name = c:GetName(), owner = c:GetOwner(), x = x, y = y }
  end
  return out
end

-- A refused order must not cost the unit its standing move (live t26: a BUILD_FARM refused mid-walk wiped
-- the Worker's move_unit record, so resume_moves skipped it and it idled a turn as "stalled_mission").
function H.unit_mission(unit_id, mission, x, y, build, pid)
  local key = H.pm_key(unit_id, pid)
  local standing = H.pending_moves[key]
  local r = H.unit_mission_order(unit_id, mission, x, y, build, pid)
  local u = Players[pid] and Players[pid]:GetUnitByID(unit_id)
  local arrived = u and standing and u:GetX() == standing.x and u:GetY() == standing.y
  if type(r) == "table" and r.ok == false and standing and not arrived and H.pending_moves[key] == nil then
    H.pending_moves[key] = standing
    r.standing_move_kept = { x = standing.x, y = standing.y }
  end
  return r
end

function H.unit_mission_order(unit_id, mission, x, y, build, pid)
  local u, err = own_active_unit(unit_id, pid)
  if not u then return err end
  if mission == "MISSION_SKIP" then
    -- A skip on a unit that is mid-way through a multi-turn move cancels the engine's path (live t306:
    -- the Caravel's standing order to (54,29) died to a reflex MISSION_SKIP and it sat at (54,13) with
    -- 4 moves next turn). Such a unit does not block end_turn, so refuse instead of cancelling.
    -- A standing order whose destination the unit already stands on is finished, not "mid-way" (live
    -- t315: the Caravel arrived with 1 move left, the stale record refused every skip while the engine
    -- kept ENDTURN_BLOCKING_UNITS on it -- a refusal deadlock).
    local key = H.pm_key(unit_id, pid)
    local pm = H.pending_moves[key]
    if pm and pm.x == u:GetX() and pm.y == u:GetY() then H.pending_moves[key] = nil end
    local busy = (u.GetLengthMissionQueue and u:GetLengthMissionQueue() or 0) > 0
    if not busy and u.GetActivityType and ActivityTypes and u:GetActivityType() == ActivityTypes.ACTIVITY_MISSION then busy = true end
    -- ...but a stalled one blocks end_turn (todo() lists it), and refusing the skip there is a
    -- deadlock: turn_status says "this unit stops the turn", unit_mission says "it does not".
    -- A human at the same screen just presses Space.
    if (busy or H.pending_moves[key]) and not H.is_stalled_mission(u) then
      return { ok = false, err = "unit is already on a multi-turn move and does not block end_turn; "
                                 .. "MISSION_SKIP would cancel that path (give it a new move_unit instead)",
               x = u:GetX(), y = u:GetY() }
    end
  end
  H.pending_moves[H.pm_key(unit_id, pid)] = nil  -- a new order replaces any standing move
  if build ~= nil and build ~= "" and mission ~= "MISSION_BUILD" then
    return { ok = false, err = "build requires MISSION_BUILD" }
  end
  if type(mission) == "string" and mission:match("^AUTOMATE_") then
    -- Automation is a command, not a mission: the unit panel's button goes through Game.HandleAction ->
    -- GAMEMESSAGE_DO_COMMAND(COMMAND_AUTOMATE, automate type). Live t316: AUTOMATE_EXPLORE resolved to
    -- GameInfoTypes id 1 and went out as mission 1 = MISSION_ROUTE_TO(-1,-1), which "succeeded".
    local a = GameInfoTypes and GameInfoTypes[mission]
    if a == nil or not (CommandTypes and CommandTypes.COMMAND_AUTOMATE) then return { ok = false, err = "unknown automation" } end
    local ok, can = pcall(function() return u:CanAutomate(a) end)
    if not (ok and can) then return { ok = false, err = "action is not currently legal" } end
    local sent = do_command(u, CommandTypes.COMMAND_AUTOMATE, a, -1)
    if not sent.ok then return sent end
    return { ok = true, automate_pending = a }
  end
  -- COMMAND_* (delete/disband, wake, cancel...) are listed by available_unit_actions and go out as
  -- GAMEMESSAGE_DO_COMMAND like the unit panel's buttons; t370 unit_mission refused COMMAND_DELETE as an
  -- "unknown mission" although the action list offered it. Promotion/upgrade keep their own tools.
  if type(mission) == "string" and mission:match("^COMMAND_") then
    local c = CommandTypes and CommandTypes[mission]
    if c == nil then return { ok = false, err = "unknown command" } end
    if mission == "COMMAND_PROMOTION" or mission == "COMMAND_UPGRADE" then
      return { ok = false, err = "use choose_promotion / upgrade_unit for this command" }
    end
    local ok, can = pcall(function() return u:CanDoCommand(c, -1, -1) end)
    if not (ok and can) then return { ok = false, err = "action is not currently legal" } end
    local sent = do_command(u, c, -1, -1)
    if not sent.ok then return sent end
    return { ok = true, command_pending = mission }
  end
  -- Only real mission names: GameInfoTypes also maps builds, automates, units... to small ints that
  -- collide with mission ids (the AUTOMATE_EXPLORE -> MISSION_ROUTE_TO accident above).
  if not (MissionTypes and MissionTypes[mission] ~= nil) then
    return { ok = false, err = "unknown mission (use a MISSION_* name from available_unit_actions; "
                               .. "AUTOMATE_* names are accepted too, builds go in build= with MISSION_BUILD)" }
  end
  local m = MissionTypes[mission]
  local d1, d2 = -1, -1
  if type(x) == "number" then d1 = x end
  if type(y) == "number" then d2 = y end
  if build ~= nil and build ~= "" then
    local b = info_id(build)
    if b == nil then return { ok = false, err = "unknown build" } end
    local legal = false
    if u.CanBuild then
      -- Unit:CanBuild(plot, build): with only the build id the call errors ("Instance does not
      -- exist"), the pcall swallows it, and every MISSION_BUILD was refused as "not legal".
      local ok, v = pcall(function() return u:CanBuild(u:GetPlot(), b) end)
      legal = ok and v
    end
    if not legal then return { ok = false, err = "action is not currently legal" } end
    -- The engine applies this turn's work the moment the build mission starts. A short build
    -- (BUILD_REPAIR, chops, anything whose remaining work fits in one turn) therefore FINISHES
    -- inside PushMission and GetBuildType() is already -1 again on return -- seen live twice
    -- (pasture + quarry repairs, China game t196/t198) and misreported as "did not start a
    -- build". Snapshot the plot so an instant completion is recognised instead.
    local pl = u:GetPlot()
    -- Owners of this plot and its neighbours: a Citadel annexes every adjacent tile, which is the
    -- only reason anyone builds one, and the old before/after diff watched improvements only.
    local before = { imp = pl:GetImprovementType(), pillaged = pl:IsImprovementPillaged(),
                     route = pl:GetRouteType(), route_pillaged = pl:IsRoutePillaged(),
                     feature = pl:GetFeatureType(), moves = u:MovesLeft(),
                     owners = H.plot_owners_around(pl, 1) }
    local pushed = push_mission(u, m, b, -1)
    if not pushed.ok then return pushed end
    -- The order lands on a later game update; the Python wrapper polls H.build_check with `before`.
    return { ok = true, pending = true, build_id = b, x = pl:GetX(), y = pl:GetY(), before = before }
  end
  if d1 >= 0 and d2 >= 0 then
    local blocked = require_revealed_plot(d1, d2, pid)
    if blocked then return blocked end
  else
    d1, d2 = -1, -1
  end
  local legal = false
  if u.CanStartMission then
    local ok, v = pcall(function() return u:CanStartMission(m, d1, d2, false) end)
    legal = ok and v
  end
  if not legal then return { ok = false, err = "action is not currently legal" } end
  local pushed = push_mission(u, m, d1, d2)
  if not pushed.ok then return pushed end
  return { ok = true }
end

-- Poll after an AUTOMATE_* command: the engine flags the unit automated once the command lands (and
-- an explorer may already have moved on the same update).
function H.automate_check(unit_id, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  if not u then return { ok = true, gone = true } end
  return { ok = true, automated = u:IsAutomated(),
           x = u:GetX(), y = u:GetY(), moves = u:MovesLeft() / move_denom() }
end

-- Poll after a MISSION_BUILD: `started` when GetBuildType() shows the build, `completed` when the plot
-- already changed (a short build -- BUILD_REPAIR, a chop -- finishes the moment it starts and
-- GetBuildType() is -1 again; seen live twice, China game t196/t198).
-- Owners of a plot and its neighbours, for the before/after diff of a build that moves borders.
-- Every read is guarded: this runs on the way into an ordinary worker build, where a missing getter
-- must cost the diff and nothing else.
function H.plot_owners_around(plot, r)
  local out = {}
  if not plot or not Map then return out end
  for dx = -r, r do for dy = -r, r do
    local ok, p2 = pcall(function()
      if Map.PlotXYWithRangeCheck then
        return Map.PlotXYWithRangeCheck(plot:GetX(), plot:GetY(), dx, dy, r)
      end
      return Map.GetPlot and Map.GetPlot(plot:GetX() + dx, plot:GetY() + dy) or nil
    end)
    if ok and p2 then
      pcall(function() out[p2:GetX() .. "," .. p2:GetY()] = p2:GetOwner() end)
    end
  end end
  return out
end

function H.build_check(unit_id, x, y, before, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  local pl = Map.GetPlot(x, y)
  local out = { ok = true, unit_exists = u ~= nil }
  if u then
    out.buildtype = u.GetBuildType and u:GetBuildType() or -1
    out.moves = u:MovesLeft() / move_denom()
    out.started = out.buildtype ~= -1
    -- Name it: a bare id (15 for both a Silk plantation and a forest-hill mine, live t79) said nothing.
    local row = out.started and GameInfo.Builds[out.buildtype] or nil
    if row then
      out.build = row.Type
      if pl then
        local okt, t = pcall(function() return pl:GetBuildTurnsLeft(out.buildtype, pid, 0, 0) end)
        if okt then out.turns_left = t end
      end
    end
  end
  if pl and before then
    out.completed = pl:GetImprovementType() ~= before.imp or pl:IsImprovementPillaged() ~= before.pillaged
      or pl:GetRouteType() ~= before.route or pl:IsRoutePillaged() ~= before.route_pillaged
      or pl:GetFeatureType() ~= before.feature
    if out.completed then
      pcall(function()
        local imp = pl:GetImprovementType()
        if imp and imp >= 0 and GameInfo.Improvements then
          out.improvement = short(info_type(GameInfo.Improvements, imp))
        end
      end)
      -- A Great Person is expended by its build; saying "the unit is gone" beats leaving the caller
      -- to notice that unit_exists went false.
      if not u then out.unit_consumed = true end
      if before.owners then
        local claimed = {}
        for key, was in pairs(before.owners) do
          local sx, sy = key:match("^(-?%d+),(-?%d+)$")
          local p2 = sx and Map.GetPlot(tonumber(sx), tonumber(sy))
          if p2 and p2:GetOwner() ~= was and p2:GetOwner() == pid then
            local row = { x = tonumber(sx), y = tonumber(sy) }
            -- Taking a tile off another civ is an incident the stock tooltip warns about; name them.
            if was and was >= 0 then
              row.taken_from = was
              row.taken_from_name = H.owner_label(was, pid)
            end
            claimed[#claimed + 1] = row
          end
        end
        if #claimed > 0 then out.claimed_plots = claimed end
      end
    end
  end
  return out
end
