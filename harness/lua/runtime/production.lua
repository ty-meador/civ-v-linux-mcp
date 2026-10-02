-- Shared by earlier fragments (load order: harness/runtime_source.py MANIFEST).
local L = H._ns.L

function H.available_production(city_id, pid)
  local city = Players[pid]:GetCityByID(city_id)
  if not city then return { ok = false, err = "no such city" } end
  local puppet = H.city_production_guard(city)
  -- Venice exception (GitLab #15): productionpopup.lua opens a puppet's window in *purchase* mode when
  -- the player MayNotAnnex() (OnPopup: "You're super-special Venice and are able to update the window"),
  -- so Venice's human sees, and buys from, its puppets' gold/faith lists while still never choosing
  -- their production. Any other player's puppet stays refused: listing choices it cannot be given is a
  -- false offer.
  local venice = false
  if puppet then
    local p = Players[pid]
    if not (p and p.MayNotAnnex and p:MayNotAnnex()) then return puppet end
    venice = true
  end
  local items = {}
  -- The chooser button is a name, not an enum, and BNW renamed several of them: BUILDING_THEATRE is
  -- "Zoo" on screen (live t222 -- set_production answered `production: "Zoo"` for the item that was
  -- asked for by its Theatre enum), UNIT_SHOSHONE_PATHFINDER is "Pathfinder". `cities()` prints the
  -- localized name too, so without this the city's current build cannot be found in its own list.
  -- No `help` on a row since v216: the unit/building/project/process blurbs are static text and live
  -- once in reference("units") etc. instead of on every chooser row of every city, every turn.
  local function add(item, kind, turns, gold, can_buy, name)
    local row = { item = item, kind = kind, turns = turns, gold = gold, can_buy = can_buy }
    if name and name ~= "" and name ~= item then row.name = name end
    items[#items + 1] = row
  end
  -- Gold rush-buy cost + purchasability per entry, so "can I just buy this?" needs no second call.
  -- Same matched getter/IsCanPurchase pairs as purchase_cost (a mismatched pair crashed the game once);
  -- projects/wonders are never purchasable in vanilla BNW and get no gold field.
  local gold_yield = YieldTypes and YieldTypes.YIELD_GOLD or 2
  local function unit_gold(id)
    local ok, cost = pcall(function() return city:GetUnitPurchaseCost(id) end)
    local ok2, can = pcall(function() return city:IsCanPurchase(true, true, id, -1, -1, gold_yield) end)
    if ok and cost == -1 then cost = nil end  -- -1 = cannot be bought at all (national wonders etc.)
    return (ok and cost or nil), (ok2 and can or false)
  end
  local function building_gold(id)
    local ok, cost = pcall(function() return city:GetBuildingPurchaseCost(id) end)
    local ok2, can = pcall(function() return city:IsCanPurchase(true, true, -1, id, -1, gold_yield) end)
    if ok and cost == -1 then cost = nil end
    return (ok and cost or nil), (ok2 and can or false)
  end
  -- A priced row with can_buy false gets `buy_blocked` {reason, text}: the sentence under the greyed
  -- buy button (v255; live t156 Karakorum: 2570 gold, every unit can_buy false, and only purchase_cost
  -- said a Worker stood on the city tile). purchase_cost's ladder, cheap reads first: `gold` (balance
  -- of cost, only where the button exists), `stacking` (one per tile -- `blocking_units`), `unbuyable`
  -- (no buy button here at all), else the engine's own tooltip (`engine`) or `refused`.
  local balance = nil
  pcall(function() balance = Players[pid]:GetGold() end)
  local function can_purchase(test_cost, test_train, uid, bid)
    local ok, v = pcall(function() return city:IsCanPurchase(test_cost, test_train, uid, bid, -1, gold_yield) end)
    return ok and v and true or false
  end
  local function plot_blockers(unit_row)
    local blockers = {}
    pcall(function()
      local plot = city:Plot()
      local combat = (unit_row.Combat or 0) > 0
      for i = 0, plot:GetNumUnits() - 1 do
        local u = plot:GetUnit(i)
        if u and u:GetOwner() == city:GetOwner() and (u:IsCombatUnit() == combat) then
          local ur = GameInfo.Units[u:GetUnitType()]
          if ur and ur.Domain == unit_row.Domain then
            blockers[#blockers + 1] = { unit_id = u:GetID(), type = ur.Type,
                                        name = ur.Description and L(ur.Description) or ur.Type }
          end
        end
      end
    end)
    return blockers
  end
  local function buy_blocked(uid, bid, cost, unit_row)
    if type(cost) ~= "number" or type(balance) ~= "number" then return nil end
    if cost > balance and can_purchase(false, true, uid, bid) then
      return { reason = "gold", text = "not enough gold (" .. balance .. " of " .. cost .. ")" }
    end
    if unit_row then
      local blockers = plot_blockers(unit_row)
      if #blockers > 0 then
        local names = {}
        for _, b in ipairs(blockers) do names[#names + 1] = b.name end
        return { reason = "stacking", blocking_units = blockers,
                 text = "one per tile: " .. table.concat(names, ", ") .. " already stands in the city -- move it out first" }
      end
    end
    if not can_purchase(false, false, uid, bid) then
      return { reason = "unbuyable", text = "cannot be bought in this city (no buy button)" }
    end
    local tip_fn = (uid >= 0) and city.GetPurchaseUnitTooltip or city.GetPurchaseBuildingTooltip
    if tip_fn then
      local okt, tip = pcall(tip_fn, city, (uid >= 0) and uid or bid)
      if okt and type(tip) == "string" and tip ~= "" then return { reason = "engine", text = tip } end
    end
    return { reason = "refused", text = "the game refuses the purchase this turn" }
  end
  if GameInfo and GameInfo.Units then
    for u in GameInfo.Units() do
      if u and u.ID and city:CanTrain(u.ID, 0) then
        local gold, can = unit_gold(u.ID)
        add(u.Type, "unit", city:GetUnitProductionTurnsLeft(u.ID), gold, can,
            u.Description and L(u.Description) or nil)
        if gold and not can then items[#items].buy_blocked = buy_blocked(u.ID, -1, gold, u) end
      end
    end
  end
  if GameInfo and GameInfo.Buildings then
    for b in GameInfo.Buildings() do
      if b and b.ID and city:CanConstruct(b.ID, 0) then
        local gold, can = building_gold(b.ID)
        add(b.Type, "building", city:GetBuildingProductionTurnsLeft(b.ID), gold, can,
            b.Description and L(b.Description) or nil)
        if gold and not can then items[#items].buy_blocked = buy_blocked(-1, b.ID, gold, nil) end
      end
    end
  end
  -- Faith purchases (the city screen's faith tab): Missionaries/Inquisitors, Great People once the
  -- matching policy branch is finished, religious buildings from beliefs. Most are NOT trainable, so
  -- they are missing from the CanTrain loop above; every unit/building is asked instead. Same
  -- pcall-guarded matched pairs as gold. `faith_only` marks entries that exist only as a purchase.
  local faith_yield = YieldTypes and YieldTypes.YIELD_FAITH or 5
  local seen = {}
  for _, it in ipairs(items) do seen[it.item] = it end
  -- IsCanPurchase(bTestPurchaseCost, bTestTrainable, ...): with the cost test off the row still shows
  -- while we save up (live t292: a 400-faith Missionary was invisible at 267 faith); `faith_can_buy`
  -- is the affordable-now answer.
  local function faith_check(uid, bid)
    local ok2, can = pcall(function() return city:IsCanPurchase(false, true, uid, bid, -1, faith_yield) end)
    if not (ok2 and can) then return nil end
    local ok, cost = pcall(function()
      if uid >= 0 then return city:GetUnitFaithPurchaseCost(uid, true) end
      return city:GetBuildingFaithPurchaseCost(bid)
    end)
    if not (ok and cost and cost > 0) then return nil end
    local ok3, now = pcall(function() return city:IsCanPurchase(true, true, uid, bid, -1, faith_yield) end)
    return cost, (ok3 and now) and true or false
  end
  if GameInfo and GameInfo.Units and city.GetUnitFaithPurchaseCost then
    for u in GameInfo.Units() do
      if u and u.ID then
        local cost, now = faith_check(u.ID, -1)
        if cost then
          if seen[u.Type] then seen[u.Type].faith = cost; seen[u.Type].faith_can_buy = now
          else items[#items + 1] = { item = u.Type, kind = "unit", faith = cost, faith_can_buy = now,
                                     faith_only = true, name = u.Description and L(u.Description) or nil } end
        end
      end
    end
  end
  if GameInfo and GameInfo.Buildings and city.GetBuildingFaithPurchaseCost then
    for b in GameInfo.Buildings() do
      if b and b.ID then
        local cost, now = faith_check(-1, b.ID)
        if cost then
          if seen[b.Type] then seen[b.Type].faith = cost; seen[b.Type].faith_can_buy = now
          else items[#items + 1] = { item = b.Type, kind = "building", faith = cost, faith_can_buy = now,
                                     faith_only = true, name = b.Description and L(b.Description) or nil } end
        end
      end
    end
  end
  if GameInfo and GameInfo.Projects then
    for proj in GameInfo.Projects() do
      if proj and proj.ID and city:CanCreate(proj.ID, 0) then
        add(proj.Type, "project", city:GetProjectProductionTurnsLeft(proj.ID), nil, nil,
            proj.Description and L(proj.Description) or nil)
      end
    end
  end
  if GameInfo and GameInfo.Processes then
    -- A league process also carries the tooltip paragraph: percent, our hammers, rewards -- live
    -- numbers, so they stay on the row. Not the other civs' split (see league_projects).
    local league_by_process = {}
    local ok_lp, projects = pcall(H.league_projects, pid)
    if ok_lp and type(projects) == "table" then
      for _, proj in ipairs(projects) do
        if proj.process then league_by_process[proj.process] = proj end
      end
    end
    for proc in GameInfo.Processes() do
      if proc and proc.ID and city:CanMaintain(proc.ID, 0) then
        add(proc.Type, "process", nil, nil, nil,
            proc.Description and L(proc.Description) or nil)
        local proj = league_by_process[proc.Type]
        if proj then
          items[#items].league_project = {
            project = proj.project, name = proj.name,
            progress_percent = proj.progress_percent,
            our_contribution = proj.our_contribution, our_tier = proj.our_tier,
            cost = proj.cost, cost_per_player = proj.cost_per_player,
            tier_1_at = proj.tier_1_at, tier_2_at = proj.tier_2_at,
            details = proj.details,
          }
        end
      end
    end
  end
  if venice then
    -- Purchase mode shows only what has a price: projects, processes and unpriced rows are the
    -- production picker's, which this puppet does not have. `turns` is the puppet AI's schedule, not
    -- an offer, so it goes too; `producing` names what the AI has chosen (as the guard does).
    local buyable = {}
    for _, it in ipairs(items) do
      if it.gold or it.faith then it.turns = nil; buyable[#buyable + 1] = it end
    end
    local out = { ok = true, items = buyable, puppet = true, purchase_only = true,
                  note = "puppet: Venice may buy here (purchase_production) but cannot choose its production" }
    pcall(function() out.producing = H.L(city:GetProductionNameKey()) end)
    return out
  end
  return { ok = true, items = items }
end
