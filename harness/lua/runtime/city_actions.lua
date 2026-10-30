-- Shared by earlier fragments (load order: harness/runtime_source.py MANIFEST).
local FOCUS_IDS, city_focus_name = H._ns.FOCUS_IDS, H._ns.city_focus_name

local function own_city(city_id, pid)
  if Game.GetActivePlayer() ~= pid then
    return nil, { ok = false, err = "this seat is not active" }
  end
  local c = Players[pid]:GetCityByID(city_id)
  if not c then return nil, { ok = false, err = "no such city" } end
  return c, nil
end

-- A city whose production the engine, not this seat, decides. Puppets always are; a city a human put
-- on production automation is too. Neither raises ENDTURN_BLOCKING_PRODUCTION when its queue empties.
function H.production_is_automated(c)
  local aut
  if not pcall(function() aut = c:IsProductionAutomated() end) then return c:IsPuppet() and true or false end
  return aut and true or false
end

-- A puppet's city screen is read-only: no production picker, no tile purchase, no citizen management.
-- Some of those the engine refuses by itself and some it does not, which is the trap. `IsCanPurchase`
-- answers false for a puppet (rush-buy), but `CityPushOrder` and `CanBuyPlotAt` do not -- live t193,
-- all three puppets offered buyable plots with real costs, and at t192 a Worker pushed into captured
-- Cusco stuck across the turn boundary (7001 turns at that city's production), displacing the puppet
-- AI's own pick for good. So every city write checks this itself rather than trusting the engine.
function H.puppet_guard(c, what)
  local puppet
  if not pcall(function() puppet = c:IsPuppet() end) then return nil end
  if not puppet then return nil end
  local out = { ok = false, puppet = true }
  -- Venice may not annex (GitLab #15, live Doge t215): its way out is the purchase list, not city_task.
  local venice = false
  pcall(function() venice = Players[c:GetOwner()]:MayNotAnnex() end)
  if venice then
    out.err = "puppet cities " .. (what or "are run by the AI") .. "; Venice cannot annex -- buy here with order(to='city', action='purchase') (state(what='city', view='production') lists the prices)"
  else
    out.err = "puppet cities " .. (what or "are run by the AI") .. "; annex first (order(to='city', action='status')) to direct this one"
  end
  -- the name the production popup prints, not its text key (live t215: TXT_KEY_BUILDING_OBSERVATORY)
  pcall(function() out.producing = H.L(c:GetProductionNameKey()) end)
  return out
end

function H.city_production_guard(c)
  return H.puppet_guard(c, "choose their own production")
end

function H.set_auto_specialists(city_id, automatic, pid)
  local c, err = own_city(city_id, pid)
  if not c then return err end
  if c:IsPuppet() then return { ok = false, err = "puppet cities are run by the AI; annex first" } end
  Network.SendDoTask(c:GetID(), TaskTypes.TASK_NO_AUTO_ASSIGN_SPECIALISTS, -1, -1, not automatic, false, false, false)
  return { ok = true, city_id = c:GetID(), requested = automatic }
end

function H.change_specialist(city_id, building, add, pid)
  local c, err = own_city(city_id, pid)
  if not c then return err end
  if c:IsPuppet() then return { ok = false, err = "puppet cities are run by the AI; annex first" } end
  local b = GameInfo.Buildings[building]
  if not b or not b.SpecialistType or not c:IsHasBuilding(b.ID) then
    return { ok = false, err = "city has no specialist slots in that building" }
  end
  local before = c:GetNumSpecialistsInBuilding(b.ID)
  if add and not c:IsCanAddSpecialistToBuilding(b.ID) then return { ok = false, err = "cannot add a specialist to that building" } end
  if not add and before <= 0 then return { ok = false, err = "no specialist assigned to that building" } end
  if not c:IsNoAutoAssignSpecialists() then H.set_auto_specialists(city_id, false, pid) end
  Network.SendDoTask(c:GetID(), add and TaskTypes.TASK_ADD_SPECIALIST or TaskTypes.TASK_REMOVE_SPECIALIST,
    GameInfoTypes[b.SpecialistType], b.ID, false, false, false, false)
  return { ok = true, city_id = c:GetID(), building = b.Type, before = before, expected = before + (add and 1 or -1) }
end

function H.set_city_focus(city_id, focus, pid)
  local c, err = own_city(city_id, pid)
  if not c then return err end
  if c:IsPuppet() then return { ok = false, err = "puppet cities are run by the AI; annex first" } end
  local key = FOCUS_IDS[focus]
  if not key then
    local allowed = {}
    for k, _ in pairs(FOCUS_IDS) do allowed[#allowed + 1] = k end
    return { ok = false, err = "unknown focus " .. tostring(focus), allowed = allowed }
  end
  local id = CityAIFocusTypes and CityAIFocusTypes[key]
  if id == nil then return { ok = false, err = "CityAIFocusTypes missing " .. key } end
  Network.SendSetCityAIFocus(c:GetID(), id)
  return { ok = true, city_id = city_id, focus = city_focus_name(c), sent = focus }
end

function H.set_avoid_growth(city_id, avoid, pid)
  local c, err = own_city(city_id, pid)
  if not c then return err end
  if c:IsPuppet() then return { ok = false, err = "puppet cities are run by the AI; annex first" } end
  Network.SendSetCityAvoidGrowth(c:GetID(), avoid and true or false)
  return { ok = true, city_id = city_id, avoid_growth = (c.IsForcedAvoidGrowth and c:IsForcedAvoidGrowth()) or false, sent = avoid and true or false }
end

function H.change_working_plot(city_id, x, y, pid)
  local c, err = own_city(city_id, pid)
  if not c then return err end
  if c:IsPuppet() then return { ok = false, err = "puppet cities are run by the AI; annex first" } end
  local idx
  local nplots = c.GetNumCityPlots and c:GetNumCityPlots() or 0
  for i = 1, nplots - 1 do  -- 0 is the city tile; the UI ignores clicks on it
    local plot = c:GetCityIndexPlot(i)
    if plot and plot:GetX() == x and plot:GetY() == y then idx = i; break end
  end
  if not idx then return { ok = false, err = "plot is not in this city's workable radius", x = x, y = y } end
  Network.SendDoTask(c:GetID(), TaskTypes.TASK_CHANGE_WORKING_PLOT, idx, -1, false, false, false, false)
  local plot = c:GetCityIndexPlot(idx)
  local worked = c:IsWorkingPlot(plot)
  return { ok = true, city_id = city_id, x = x, y = y, worked = worked }
end

function H.buy_city_plot(city_id, x, y, pid)
  local c, err = own_city(city_id, pid)
  if not c then return err end
  -- CanBuyPlotAt says yes for a puppet (live t193: all three offered plots, 65-130g); the stock city
  -- screen never shows the buy control there. The other four tile/citizen writes already refuse.
  local puppet = H.puppet_guard(c, "manage their own tiles")
  if puppet then return puppet end
  local okb, buy = pcall(function() return c:CanBuyPlotAt(x, y, false) end)
  if not (okb and buy) then return { ok = false, err = "cannot buy that plot from this city right now", x = x, y = y } end
  local okp, cost = pcall(function() return c:GetBuyPlotCost(x, y) end)
  if okp and cost and Players[pid]:GetGold() < cost then
    return { ok = false, err = "not enough gold", cost = cost, gold = Players[pid]:GetGold() }
  end
  Network.SendCityBuyPlot(c:GetID(), x, y)
  -- The purchase lands on a later game update: the treasury read here is the one BEFORE it (GitLab #129, Siam t26:
  -- `gold_after` 166 beside `gold` 136 a moment later). The Python side reads gold_after once it moved.
  return { ok = true, city_id = city_id, x = x, y = y, cost = cost, gold_before = Players[pid]:GetGold() }
end

function H.city_task(city_id, action, pid)
  local c, err = own_city(city_id, pid)
  if not c then return err end
  local p = Players[pid]
  if action == "annex" then
    if not c:IsPuppet() then return { ok = false, err = "city is not a puppet" } end
    if p.MayNotAnnex and p:MayNotAnnex() then return { ok = false, err = "this civ cannot annex (Venice)" } end
    Network.SendDoTask(c:GetID(), TaskTypes.TASK_ANNEX_PUPPET, -1, -1, false, false, false, false)
  elseif action == "raze" then
    if c:IsCapital() then return { ok = false, err = "cannot raze a capital" } end
    if not (p.CanRaze and p:CanRaze(c)) then return { ok = false, err = "cannot raze this city" } end
    Network.SendDoTask(c:GetID(), TaskTypes.TASK_RAZE, -1, -1, false, false, false, false)
  elseif action == "unraze" then
    if not c:IsRazing() then return { ok = false, err = "city is not razing" } end
    Network.SendDoTask(c:GetID(), TaskTypes.TASK_UNRAZE, -1, -1, false, false, false, false)
  else
    return { ok = false, err = "unknown action " .. tostring(action), allowed = { "annex", "raze", "unraze" } }
  end
  return { ok = true, city_id = city_id, action = action, puppet = c:IsPuppet(), razing = c:IsRazing() }
end

-- City-screen sell (Network.SendSellBuilding). One building per city per turn is the usual engine gate;
-- IsBuildingSellable goes false afterwards. Puppets refuse (stock UI never offers the click).
function H.sell_building(city_id, building_name, pid)
  local c, err = own_city(city_id, pid)
  if not c then return err end
  if c:IsPuppet() then return { ok = false, err = "puppet cities are run by the AI; annex first" } end
  local id = GameInfoTypes[building_name]
  if id == nil then return { ok = false, err = "unknown building " .. tostring(building_name) } end
  if not (c.IsBuildingSellable and c:IsBuildingSellable(id)) then
    return { ok = false, err = "cannot sell that building right now" }
  end
  local refund
  pcall(function() refund = c:GetSellBuildingRefund(id) end)
  local gold_before = Players[pid]:GetGold()
  Network.SendSellBuilding(c:GetID(), id)
  return { ok = true, sent = true, city_id = city_id, building = building_name, refund = refund, gold_before = gold_before }
end

---------------------------------------------------------------- production orders and purchases (v285)
-- These bodies were composed in harness/game_parts/cities.py until the seat binding moved the Lua to the
-- runtime (docs/ROADMAP.md "A seat bound to its channel", stage 3); the comments there moved with them.
local function queue_of(city)
  local queue = {}
  pcall(function()
    for i = 0, city:GetOrderQueueLength() - 1 do
      local orderType, data = city:GetOrderFromQueue(i)
      local row = (orderType == OrderTypes.ORDER_TRAIN and GameInfo.Units[data])
               or (orderType == OrderTypes.ORDER_CONSTRUCT and GameInfo.Buildings[data])
               or (orderType == OrderTypes.ORDER_CREATE and GameInfo.Projects[data])
               or (orderType == OrderTypes.ORDER_MAINTAIN and GameInfo.Processes[data]) or nil
      queue[#queue + 1] = row and row.Type or tostring(data)
    end
  end)
  return queue
end

local CAN_FN = { ORDER_TRAIN = "CanTrain", ORDER_CONSTRUCT = "CanConstruct", ORDER_CREATE = "CanCreate", ORDER_MAINTAIN = "CanMaintain" }

-- The matching Can{Construct,Train,Create,Maintain}() guard before an order: CityPushOrder itself accepts and
-- silently drops an invalid order (a building the city already has, confirmed live).
function H.production_check(city_id, order, item, pid)
  local city = Players[pid]:GetCityByID(city_id)
  if not city then return { ok = false, err = "no such city" } end
  local puppet = H.city_production_guard(city)
  if puppet then return puppet end
  local id = GameInfoTypes[item]
  if id == nil then return { ok = false, err = "unknown item" } end
  local can_fn = CAN_FN[order]
  if not can_fn then return { ok = false, err = "unknown order " .. tostring(order) } end
  if not city[can_fn](city, id, 0) then
    local r = { ok = false, err = "city cannot build this (missing prereq, already built, or one-per-city)" }
    -- v276: name the rule compare_production would name (live Assyria t66: a second Royal Library was
    -- refused with the three-way guess above; the rule was "already built in this city")
    if H.production_why then
      local okw, why = pcall(H.production_why, city, pid, item)
      if okw and type(why) == "table" and #why > 0 then
        r.err = "city cannot build this: " .. table.concat(why, "; ")
        r.why = why
      end
    end
    -- a wonder/building already sitting in this city's queue is refused too (live t437 Hubble)
    pcall(function()
      for i = 0, city:GetOrderQueueLength() - 1 do
        local _, data = city:GetOrderFromQueue(i)
        if data == id then r.err = "already in this city's production queue (position " .. (i + 1) .. ")" end
      end
    end)
    -- per-player unit caps (spaceship parts: 3 boosters) count units already built plus ones in any
    -- city's queue (live t437: a 4th booster refused while three cities were building one)
    local u = order == "ORDER_TRAIN" and GameInfo.Units[id]
    local uc = u and GameInfo.UnitClasses[u.Class]
    if uc and (uc.MaxPlayerInstances or -1) > 0 then
      local p = Players[pid]
      local have, making = p:GetUnitClassCount(uc.ID), p:GetUnitClassMaking(uc.ID)
      if have + making >= uc.MaxPlayerInstances then
        r.err = "player limit reached: " .. have .. " built + " .. making .. " in production of max " .. uc.MaxPlayerInstances
      end
    end
    -- caravans / cargo ships: the engine trains none beyond the routes possible, counting the ones
    -- alive and the ones queued in any city (H.trade_unit_count; live t139 Venice "4 of 8" refused)
    if u and (u.Trade == true or u.Trade == 1) then
      local tu = H.trade_unit_count(Players[pid])
      if tu.remaining and tu.remaining <= 0 then
        r.err = "every trade-route slot already has a caravan or cargo ship (" .. tu.alive .. " alive"
                .. (tu.queued > 0 and (" + " .. tu.queued .. " queued") or "") .. " of " .. tostring(tu.possible)
                .. "): the engine trains no more; route the idle ones (state(what='empire').idle_trade_units) or wait for a slot"
      elseif city.CanTrainTooltip and H.tooltip_text then
        -- the second gate (runtime v253): with slots free the engine still refuses while no city of mine
        -- could start a new route of this unit's kind (live t152 Venice, 4 of 8 free, both kinds refused)
        local tip = H.tooltip_text(city:CanTrainTooltip(id))
        if tip:lower():find("trade route") then
          r.err = tip .. " -- the engine trains a trade unit only while one of my cities could start a new "
                  .. "route of its kind now (" .. tostring(tu.remaining) .. " slot(s) free); a route ending or a "
                  .. "city coming in range changes that"
        end
      end
    end
    return r
  end
  return { ok = true, id = id }
end

-- append=true is the production screen's shift-click (productionpopup.lua passes `not g_append` as the 5th
-- argument): the item goes behind what the city is building instead of replacing it.
function H.city_push_order(city_id, order, item_id, append, pid)
  local city = Players[pid]:GetCityByID(city_id)
  if not city then return { ok = false, err = "no such city" } end
  if OrderTypes[order] == nil then return { ok = false, err = "unknown order " .. tostring(order) } end
  local before = queue_of(city)
  Game.CityPushOrder(city, OrderTypes[order], item_id, false, not append, true)
  -- GitLab #114: without append the push replaces the whole queue; the caller names what was dropped.
  return { ok = true, before = before }
end
H.queue_items = queue_of   -- shared with events.lua's queue watch (#114)

function H.city_queue(city_id, pid)
  local city = Players[pid]:GetCityByID(city_id)
  if not city then return { ok = false, err = "no such city" } end
  local rate
  pcall(function() rate = city:GetYieldRate(YieldTypes.YIELD_PRODUCTION) end)
  return { ok = true, production = H.L(city:GetProductionNameKey()), turns = city:GetProductionTurnsLeft(), queue = queue_of(city),
           production_per_turn = rate }
end

-- city:PopOrder(index, 0, 0): CvCity::popOrder(iNum, bFinish, bChoose) with a 0-based index and numbers for
-- the flags (booleans answer "bad argument #2 to 'PopOrder'", live 2026-09-27). `position` is 1-based.
function H.city_pop_order(city_id, position, pid)
  local city = Players[pid]:GetCityByID(city_id)
  if not city then return { ok = false, err = "no such city" } end
  local puppet = H.city_production_guard(city)
  if puppet then return puppet end
  local n = city:GetOrderQueueLength()
  if n == 0 then return { ok = false, err = "the production queue is empty" } end
  if position > n then
    return { ok = false, err = "the queue has " .. n .. " item(s); there is no position " .. position }
  end
  local queue = queue_of(city)
  city:PopOrder(position - 1, 0, 0)
  return { ok = true, queue = queue }
end

local function purchase_ids(order, id)
  if order == "ORDER_TRAIN" then return id, -1, -1 end
  if order == "ORDER_CONSTRUCT" then return -1, id, -1 end
  return -1, -1, id
end
local COST_FN = { ORDER_TRAIN = "GetUnitPurchaseCost", ORDER_CONSTRUCT = "GetBuildingPurchaseCost", ORDER_CREATE = "GetProjectPurchaseCost" }
-- no project-faith-specific getter found; the gold one is reused for ORDER_CREATE
local FAITH_COST_FN = { ORDER_TRAIN = "GetUnitFaithPurchaseCost", ORDER_CONSTRUCT = "GetBuildingFaithPurchaseCost", ORDER_CREATE = "GetProjectPurchaseCost" }
-- What a human actually reads when the button is greyed out: the stock production popup appends the engine's
-- own tooltip to a disabled row (productionpopup.lua, "Disabled help text" -- one getter per order x yield).
local TIP_FN = { ORDER_TRAIN = { GOLD = "GetPurchaseUnitTooltip", FAITH = "GetFaithPurchaseUnitTooltip" },
                 ORDER_CONSTRUCT = { GOLD = "GetPurchaseBuildingTooltip", FAITH = "GetFaithPurchaseBuildingTooltip" } }
local PURCHASE_FN = { ORDER_TRAIN = "CityPurchaseUnit", ORDER_CONSTRUCT = "CityPurchaseBuilding", ORDER_CREATE = "CityPurchaseProject" }
local function yield_of(yield_type) if yield_type == "FAITH" then return YieldTypes.YIELD_FAITH end return YieldTypes.YIELD_GOLD end
local function balance_of(p, yield_type) if yield_type == "FAITH" then return p:GetFaith() end return p:GetGold() end

-- Read-only: the cost to rush-buy `item` now and whether it is purchasable (city:IsCanPurchase(true, true, ...),
-- the gate purchase_production checks before spending). The reason ladder is our guesswork; engine_reason is
-- the game's own answer (live t205: a Pagoda refused in a puppet that follows another religion).
function H.purchase_cost(city_id, order, item, yield_type, pid)
  local buyer = Players[pid]
  local city = buyer:GetCityByID(city_id)
  if not city then return { ok = false, err = "no such city" } end
  local id = GameInfoTypes[item]
  if id == nil then return { ok = false, err = "unknown item" } end
  if not COST_FN[order] then return { ok = false, err = "unknown order " .. tostring(order) } end
  local uid, bid, prid = purchase_ids(order, id)
  local yt = yield_of(yield_type)
  local cost
  if yield_type ~= "FAITH" then cost = city[COST_FN[order]](city, id)
  elseif order == "ORDER_TRAIN" then cost = city[FAITH_COST_FN[order]](city, id, true)
  else cost = city[FAITH_COST_FN[order]](city, id) end
  local balance = balance_of(buyer, yield_type)
  local can = city:IsCanPurchase(true, true, uid, bid, prid, yt)
  local out = { ok = true, cost = cost, can_purchase = can, balance = balance }
  -- GitLab #126 (Siam t14): the price of one item came with no build turns, which the itemless view has.
  pcall(function()
    if order == "ORDER_TRAIN" then out.build_turns = city:GetUnitProductionTurnsLeft(id, 0)
    elseif order == "ORDER_CONSTRUCT" then out.build_turns = city:GetBuildingProductionTurnsLeft(id, 0)
    elseif order == "ORDER_CREATE" then out.build_turns = city:GetProjectProductionTurnsLeft(id, 0) end
    out.production_per_turn = city:GetCurrentProductionDifferenceTimes100(false, false) / 100
  end)
  if not can then
    -- The engine's own sentence first (the greyed button's tooltip): GitLab #76 (Assyria t249, t251) called a
    -- buyable spaceship part "cannot be bought here at all" while the tooltip said a unit stood on the tile and
    -- the gold was short -- the price-gap branch below needs IsCanPurchase(false) true, which the stacking denies.
    local tip
    local tip_fn = TIP_FN[order] and TIP_FN[order][yield_type]
    if tip_fn and city[tip_fn] then
      local okt, t = pcall(function() return city[tip_fn](city, id) end)
      if okt and type(t) == "string" and t ~= "" then tip = t end
    end
    local function tile_blockers()
      local plot, blockers = city:Plot(), {}
      local row = GameInfo.Units[id]
      pcall(function()
        local combat = row and (row.Combat or 0) > 0
        for i = 0, plot:GetNumUnits() - 1 do
          local u = plot:GetUnit(i)
          if u and u:GetOwner() == city:GetOwner() and (u:IsCombatUnit() == combat)
             and GameInfo.Units[u:GetUnitType()].Domain == row.Domain then
            blockers[#blockers + 1] = { unit_id = u:GetID(), type = GameInfo.Units[u:GetUnitType()].Type }
          end
        end
      end)
      return blockers
    end
    local short_of = type(cost) == "number" and cost > 0 and cost > balance
    -- The purchase screen only greys the button out. Say why when it is knowable (live t319: 975
    -- gold vs a 960 Great War Infantry, refused because a Swordsman stood on the city tile).
    if tip and tip:find("stationed in this City", 1, true) then
      out.reason = "a unit stands on the city tile: a bought unit needs the tile free, move it out first"
                   .. (short_of and ("; and not enough " .. string.lower(yield_type) .. " (" .. balance .. " of " .. cost .. ")") or "")
      local blockers = tile_blockers()
      if #blockers > 0 then out.blocking_units = blockers end
    elseif tip and tip:find("not have enough", 1, true) and short_of then
      out.reason = "not enough " .. string.lower(yield_type) .. " (" .. balance .. " of " .. cost .. ")"
    elseif yield_type == "FAITH" and (cost or 0) <= 0 then
      out.reason = "not sold for faith (faith buys religious units, and Great People or other units only with the belief/policy/era that unlocks them)"
    elseif yield_type == "FAITH" and order == "ORDER_TRAIN"
           and ((GameInfo.Units[id] or {}).ReligionSpreads or 0) > 0 and city:GetReligiousMajority() < 0 then
      -- live t409: a Missionary spreads the religion of the city it is bought in; Guangzhou had none
      out.reason = "religious units spread the city's majority religion: this city has none -- buy it in a city that follows your religion"
    elseif order == "ORDER_CONSTRUCT" and not city:IsHasBuilding(id) and (function()
             local okw, taken = pcall(function()
               local cls = GameInfo.BuildingClasses[GameInfo.Buildings[id].BuildingClass]
               return cls and cls.MaxGlobalInstances > 0 and Game.GetBuildingClassCreatedCount(cls.ID) > 0
             end)
             return okw and taken
           end)() then
      -- GitLab #115 (Maya t153): Leaning Tower read "no gold price" while it was already built elsewhere
      out.reason = "a world wonder already built elsewhere (announced to every player): nothing to buy or build here"
      out.taken = true
      out.cost = nil
    elseif type(cost) == "number" and cost < 0 then
      -- live t403: SS_COCKPIT priced -1 -- no gold price exists for it at all
      out.reason = "this item has no gold price (spaceship parts, wonders, projects): it can only be built"
      out.cost = nil
    elseif order == "ORDER_CONSTRUCT" and city:IsHasBuilding(id) then
      out.reason = "already built in this city"  -- live t431: Nanjing's Spaceship Factory, read as 'cannot be bought here at all'
    elseif city.IsPuppet and city:IsPuppet()
           and not (buyer.MayNotAnnex and buyer:MayNotAnnex()) then
      -- The purchase screen does not open for a puppet at all: productionpopup.lua returns early on IsPuppet()
      -- unless the player MayNotAnnex() (Venice). So the engine has no tooltip to offer either -- live t205.
      out.reason = "this city is a puppet: the purchase screen does not open for puppets (annex it to buy here)"
    elseif type(cost) == "number" and cost > balance
           and city:IsCanPurchase(false, true, uid, bid, prid, yt) then
      -- Before the "cannot be bought here at all" catch-all: live t205, a 1050-gold Factory against 385 gold
      -- was called unbuildable while the engine's own tooltip said "You do not have enough Gold to buy this."
      -- Only where the buy button exists: Venice's Settler (live t42, v225) was "not enough gold (189 of 370)"
      -- though Venice can never have one.
      out.reason = "not enough " .. string.lower(yield_type) .. " (" .. balance .. " of " .. cost .. ")"
    elseif not city:IsCanPurchase(false, false, uid, bid, prid, yt) then
      out.reason = "this item cannot be bought here at all (wonders/projects, or not buildable in this city)"
    elseif not city:IsCanPurchase(false, true, uid, bid, prid, yt) then
      out.reason = "this city cannot train or build it, so there is no buy button (state(what='compare', kind='production') names the rule)"
    elseif order == "ORDER_TRAIN" then
      local plot, blockers = city:Plot(), {}
      local row = GameInfo.Units[id]
      local combat = row and (row.Combat or 0) > 0
      for i = 0, plot:GetNumUnits() - 1 do
        local u = plot:GetUnit(i)
        if u and u:GetOwner() == city:GetOwner() and (u:IsCombatUnit() == combat)
           and GameInfo.Units[u:GetUnitType()].Domain == row.Domain then
          blockers[#blockers + 1] = { unit_id = u:GetID(), type = GameInfo.Units[u:GetUnitType()].Type }
        end
      end
      if #blockers > 0 then
        out.reason = "a unit of the same kind already stands in the city (one per tile); move it out first"
        out.blocking_units = blockers
      else
        out.reason = "the game refuses the purchase this turn (already bought something here this turn?)"
      end
    else
      out.reason = "the game refuses the purchase this turn"
    end
    if tip then out.engine_reason = tip end
  end
  return out
end

-- The real "can actually complete this" gate the UI reads to grey the purchase button out.
function H.purchase_check(city_id, order, item, yield_type, pid)
  local city = Players[pid]:GetCityByID(city_id)
  if not city then return { ok = false, err = "no such city" } end
  local id = GameInfoTypes[item]
  if id == nil then return { ok = false, err = "unknown item" } end
  local uid, bid, prid = purchase_ids(order, id)
  if not city:IsCanPurchase(true, true, uid, bid, prid, yield_of(yield_type)) then
    return { ok = false, err = "cannot purchase this right now (not enough currency, already queued, or not purchasable this way)" }
  end
  return { ok = true, id = id }
end

-- productionpopup.lua OnProductionButtonClick: Game.CityPurchaseUnit/CityPurchaseBuilding/CityPurchaseProject(city, id, eYield).
function H.city_purchase(city_id, order, item_id, yield_type, pid)
  local city = Players[pid]:GetCityByID(city_id)
  if not city then return { ok = false, err = "no such city" } end
  local fn = PURCHASE_FN[order]
  if not fn then return { ok = false, err = "unknown order " .. tostring(order) } end
  Game[fn](city, item_id, yield_of(yield_type))
  return { ok = true }
end

function H.city_after_purchase(city_id, yield_type, pid)
  local p = Players[pid]
  local city = p:GetCityByID(city_id)
  if not city then return { ok = false, err = "no such city" } end
  return { ok = true, production = H.L(city:GetProductionNameKey()), turns = city:GetProductionTurnsLeft(),
           balance = balance_of(p, yield_type) }
end
