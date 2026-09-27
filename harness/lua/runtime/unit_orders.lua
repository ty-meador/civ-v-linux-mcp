-- Unit promotion: GAMEMESSAGE_DO_COMMAND(COMMAND_PROMOTION) via the selection list (v86), the same
-- message the unit panel's promotion action sends, so every peer applies it.
function H.choose_promotion(unit_id, promotion_name, pid)
  local id = GameInfoTypes[promotion_name]
  if id == nil then return { ok = false, err = "unknown promotion " .. tostring(promotion_name) } end
  local u = Players[pid]:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  if not u:CanAcquirePromotion(id) then return { ok = false, err = "cannot acquire this promotion right now" } end
  -- GAMEMESSAGE_DO_COMMAND(COMMAND_PROMOTION) is what the unit panel's action sends; it runs
  -- CvUnit::promote() on every peer: raises the level, consumes the promotion, and applies one-shot
  -- effects (PROMOTION_INSTA_HEAL). A bare SetHasPromotion(id, true) did none of that -- it left
  -- the unit at level 1 and unhealed with a dangling promotion flag (live, turn 18 of the China game).
  local lvl0, dmg0 = u:GetLevel(), u:GetDamage()
  local cmd = CommandTypes.COMMAND_PROMOTION
  if not u:CanDoCommand(cmd, id, -1) then
    -- Seen live right after the unit's own ranged attack (still "busy"): do NOT fall back to a bare
    -- SetHasPromotion here -- that leaves a level-1 unit with the promotion flag set and no level-up.
    return { ok = false, err = "unit cannot promote right now (busy or mid-mission); retry shortly" }
  end
  local sent = do_command(u, cmd, id, -1)
  if not sent.ok then return sent end
  -- Applied on a later game update: the Python wrapper polls H.promotion_check.
  return { ok = true, pending = true, promotion_id = id, level_before = lvl0,
           hp_before = u:GetMaxHitPoints() - dmg0 }
end

function H.promotion_check(unit_id, promotion_id, pid)
  local u = Players[pid]:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  return { ok = true, level = u:GetLevel(), has = u:IsHasPromotion(promotion_id),
           hp = u:GetMaxHitPoints() - u:GetDamage(), promotion_ready = u:IsPromotionReady() }
end

-- Upgrade a unit in place (Warrior -> Swordsman etc.) for gold. No Network.Send* exists for this
-- (probed live: Network.SendDoCommand is nil); GAMEMESSAGE_DO_COMMAND(COMMAND_UPGRADE) is what the
-- unit panel's action sends. The engine replaces the unit object: the old id dies and a new unit of
-- the upgraded type appears on the same plot, so the Python wrapper polls H.upgrade_unit_check for it.
function H.upgrade_unit(unit_id, pid)
  local p = Players[pid]
  local u = p:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  local ut = u:GetUpgradeUnitType()
  if ut == nil or ut < 0 then return { ok = false, err = "no upgrade path for this unit" } end
  local target = GameInfo.Units[ut].Type
  local price = u:UpgradePrice(ut)
  local gold = p:GetGold()
  if u.CanUpgradeRightNow and not u:CanUpgradeRightNow() then
    return { ok = false, err = "cannot upgrade right now (needs own/allied territory, full moves, gold " .. tostring(price) .. " of " .. tostring(gold) .. ", and the strategic resource)", target = target, price = price, gold = gold }
  end
  local cmd = CommandTypes.COMMAND_UPGRADE
  if not u:CanDoCommand(cmd, -1, -1) then
    return { ok = false, err = "COMMAND_UPGRADE not available for this unit right now", target = target, price = price, gold = gold }
  end
  local x, y = u:GetX(), u:GetY()
  local sent = do_command(u, cmd, -1, -1)
  if not sent.ok then return sent end
  return { ok = true, pending = true, old_unit_id = unit_id, x = x, y = y, target_type_id = ut,
           old_type_id = u:GetUnitType(), target = target, price = price, gold_before = gold }
end

function H.upgrade_unit_check(unit_id, x, y, ut, old_type, pid)
  local p = Players[pid]
  local pl = Map.GetPlot(x, y)
  local new_id, new_type = nil, nil
  if pl then
    for i = 0, pl:GetNumUnits() - 1 do
      local v = pl:GetUnit(i)
      if v and v:GetOwner() == pid and v:GetUnitType() == ut then new_id, new_type = v:GetID(), GameInfo.Units[v:GetUnitType()].Type end
    end
  end
  local still = p:GetUnitByID(unit_id)
  return { ok = true, unit_id = new_id, type = new_type, gold = p:GetGold(),
           old_still_exists = still ~= nil and still:GetUnitType() == old_type }
end

-- Disband a unit (the unit panel's "Disband" button: COMMAND_DELETE). Frees its maintenance and any
-- strategic resource it consumed. Confirms by re-reading the unit and the resource counts.
function H.disband_unit(unit_id, pid)
  local p = Players[pid]
  local u = p:GetUnitByID(unit_id)
  if not u then return { ok = false, err = "no such unit" } end
  local cmd = CommandTypes.COMMAND_DELETE
  if not u:CanDoCommand(cmd, -1, -1) then
    -- live t59: a Pathfinder that spent its moves on a resumed standing order could not be disbanded
    if u:MovesLeft() <= 0 then
      return { ok = false, err = "a unit with no moves left this turn cannot be disbanded; try again next turn before it moves" }
    end
    return { ok = false, err = "COMMAND_DELETE not available for this unit right now (not this player's turn, or the unit cannot be disbanded)" }
  end
  local utype = GameInfo.Units[u:GetUnitType()].Type
  local before = { units = p:GetNumUnits(), strategic = H.strategic_resources(pid) }
  local sent = do_command(u, cmd, -1, -1)
  if not sent.ok then return sent end
  -- COMMAND_DELETE is applied on a later game tick (live t277: the unit still existed here, and was
  -- gone by the next call). The Python wrapper polls H.disband_unit_check.
  return { ok = true, pending = true, unit_id = unit_id, type = utype, before = before }
end

function H.disband_unit_check(unit_id, pid)
  local p = Players[pid]
  local still = p:GetUnitByID(unit_id)
  return { gone = still == nil, units = p:GetNumUnits(), strategic = H.strategic_resources(pid) }
end
