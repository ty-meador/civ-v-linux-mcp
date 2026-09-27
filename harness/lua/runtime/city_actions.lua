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
    out.err = "puppet cities " .. (what or "are run by the AI") .. "; Venice cannot annex -- buy here with purchase_production (available_production lists the prices)"
  else
    out.err = "puppet cities " .. (what or "are run by the AI") .. "; annex first (city_task) to direct this one"
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
  return { ok = true, city_id = city_id, x = x, y = y, cost = cost, gold_after = Players[pid]:GetGold() }
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
