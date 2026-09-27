-- Shared by earlier fragments (load order: harness/runtime_source.py MANIFEST).
local L, info_type, plain_text, short = H._ns.L, H._ns.info_type, H._ns.plain_text, H._ns.short

-- GetProductionTurnsLeft is INT_MAX for an empty queue and for a process (Wealth / Research).
-- Only a process should carry the "never completes" note (live t179: Goshute's empty queue was
-- labelled as an ongoing process).
local function production_turns_and_note(c)
  local turns = c:GetProductionTurnsLeft()
  if type(turns) == "number" and turns >= 2147483647 then turns = nil end
  local note
  if c.IsProductionProcess and c:IsProductionProcess() then
    note = "ongoing process: converts production every turn, never completes"
  end
  return turns, note
end

function H.cities(pid)
  local p = Players[pid]
  local out = {}
  for c in p:Cities() do
    local prod = c:GetProductionNameKey()
    local turns, pnote = production_turns_and_note(c)
    out[#out + 1] = {
      id = c:GetID(), name = c:GetName(), x = c:GetX(), y = c:GetY(), pop = c:GetPopulation(), capital = c:IsCapital(),
      puppet = c:IsPuppet(), occupied = c:IsOccupied(), razing = c:IsRazing(), hp = c:GetMaxHitPoints() - c:GetDamage(), max_hp = c:GetMaxHitPoints(),
      strength = c:GetStrengthValue() / 100,
      production = prod ~= "" and L(prod) or "", needs_production = prod == "", production_turns = turns,
      production_note = pnote, queue_len = c:GetOrderQueueLength(),
      food = c:GetYieldRate(YieldTypes.YIELD_FOOD), production_yield = c:GetYieldRate(YieldTypes.YIELD_PRODUCTION),
      gold = c:GetYieldRate(YieldTypes.YIELD_GOLD), science = c:GetYieldRate(YieldTypes.YIELD_SCIENCE),
      culture = c:GetJONSCulturePerTurn(), faith = c:GetFaithPerTurn(),
      food_stored = c:GetFood(), local_happiness = c:GetLocalHappiness(),
      -- GetFoodTurnsLeft() returns a huge sentinel (thousands of turns) for a city with no surplus;
      -- report the state by name instead so a reader never mistakes "stagnant" for "grows in 5165 turns".
      food_surplus = c:FoodDifference(true),
      growth = (c:FoodDifference(true) > 0 and "growing") or (c:FoodDifference(true) < 0 and "starving") or "stagnant",
      growth_turns = (c:FoodDifference(true) > 0) and c:GetFoodTurnsLeft() or nil,
      garrisoned = c:GetGarrisonedUnit() ~= nil, coastal = c:IsCoastal(),
      -- the city banner's religion icon: majority religion by name, nil when none ("Your City
      -- Converted" notifications were otherwise unreadable, live t287)
      religion = (function()
        local maj = c.GetReligiousMajority and c:GetReligiousMajority() or -1
        if maj and maj > 0 and Game.GetReligionName then return H.L(Game.GetReligionName(maj)) end
        if maj == 0 then return "PANTHEON" end
        return nil
      end)(),
      -- City connection (road/harbor to the capital) pays gold per turn; a Worker's road job is
      -- invisible otherwise. The capital reports true for itself.
      connected_to_capital = c:IsCapital() or (p.IsCapitalConnectedToCity and p:IsCapitalConnectedToCity(c)) or false,
      -- economicgeneralinfo.lua expandable stacks: per-city building maintenance and connection gold.
      building_maintenance = (function()
        local ok, v = pcall(function() return c:GetTotalBaseBuildingMaintenance() end)
        if ok and v and v > 0 then return v end
      end)(),
      connection_gold = (function()
        -- economicgeneralinfo.lua only lists cities that are already connected; the getter
        -- still returns a number for an unconnected city (live t183 Goshute/Pohokwi/Tiwanaku).
        if c:IsCapital() then return nil end
        if not (p.IsCapitalConnectedToCity and p:IsCapitalConnectedToCity(c)) then return nil end
        local ok, v = pcall(function() return p:GetCityConnectionRouteGoldTimes100(c) / 100 end)
        if ok and v and v > 0 then return v end
      end)(),
      resistance_turns = (c.IsResistance and c:IsResistance() and c.GetResistanceTurns and c:GetResistanceTurns()) or nil,
      razing_turns = (c.IsRazing and c:IsRazing() and c.GetRazingTurns and c:GetRazingTurns()) or nil,
      blockaded = (function()
        local ok, v = pcall(function() return c:IsBlockaded() end)
        if ok and v then return true end
      end)(),
      wltkd_turns = (function()
        local ok, v = pcall(function() return c:GetWeLoveTheKingDayCounter() end)
        if ok and type(v) == "number" and v > 0 then return v end
      end)(),
    }
  end
  return out
end

local function plot_yields(plot)
  local y, names = {}, { "food", "production", "gold", "science", "culture", "faith" }
  for i = 0, 5 do
    local ok, n = pcall(function() return plot:CalculateYield(i, true) end)
    if ok and n and n > 0 then y[names[i + 1]] = n end
  end
  return next(y) and y or nil
end

local function city_focus_name(city)
  local ok, ft = pcall(function() return city:GetFocusType() end)
  if not ok or ft == nil or not CityAIFocusTypes then return "balanced" end
  if ft == CityAIFocusTypes.CITY_AI_FOCUS_TYPE_FOOD then return "food" end
  if ft == CityAIFocusTypes.CITY_AI_FOCUS_TYPE_PRODUCTION then return "production" end
  if ft == CityAIFocusTypes.CITY_AI_FOCUS_TYPE_GOLD then return "gold" end
  if ft == CityAIFocusTypes.CITY_AI_FOCUS_TYPE_SCIENCE then return "science" end
  if ft == CityAIFocusTypes.CITY_AI_FOCUS_TYPE_CULTURE then return "culture" end
  if ft == CityAIFocusTypes.CITY_AI_FOCUS_TYPE_GREAT_PEOPLE then return "great_people" end
  if ft == CityAIFocusTypes.CITY_AI_FOCUS_TYPE_FAITH then return "faith" end
  return "balanced"
end

local FOCUS_IDS = {
  balanced = "NO_CITY_AI_FOCUS_TYPE", food = "CITY_AI_FOCUS_TYPE_FOOD", production = "CITY_AI_FOCUS_TYPE_PRODUCTION",
  gold = "CITY_AI_FOCUS_TYPE_GOLD", science = "CITY_AI_FOCUS_TYPE_SCIENCE", culture = "CITY_AI_FOCUS_TYPE_CULTURE",
  great_people = "CITY_AI_FOCUS_TYPE_GREAT_PEOPLE", faith = "CITY_AI_FOCUS_TYPE_FAITH",
}

-- BNW gplist.lua: progress is per city and GP class; generals/admirals use national XP.
function H.specialist_meter(c, s, p)
  local cls = GameInfo.UnitClasses[s.GreatPeopleUnitClass]
  if not cls then return nil end
  local count = c:GetSpecialistCount(s.ID)
  local progress = c:GetSpecialistGreatPersonProgress(s.ID)
  local base = s.GreatPeopleRateChange * count
  for b in GameInfo.Buildings() do
    if b.SpecialistType == s.Type and c:IsHasBuilding(b.ID) then
      base = base + b.GreatPeopleRateChange
    end
  end
  local mod = p:GetGreatPeopleRateModifier() + c:GetGreatPeopleRateModifier()
  local suffix = { UNITCLASS_WRITER = "Writer", UNITCLASS_ARTIST = "Artist", UNITCLASS_MUSICIAN = "Musician",
                   UNITCLASS_SCIENTIST = "Scientist", UNITCLASS_MERCHANT = "Merchant", UNITCLASS_ENGINEER = "Engineer" }
  local kind = suffix[s.GreatPeopleUnitClass]
  if kind then mod = mod + p["GetGreat" .. kind .. "RateModifier"](p) end
  if p:GetGoldenAgeTurns() > 0 and (kind == "Writer" or kind == "Artist" or kind == "Musician") then
    mod = mod + p["GetGoldenAgeGreat" .. kind .. "RateModifier"](p)
  end
  return { specialist = s.Type, unit_class = cls.Type, count = count, gp_progress = progress,
           gp_threshold = c:GetSpecialistUpgradeThreshold(cls.ID), gp_per_turn = math.floor(base * (100 + mod) / 100) }
end

function H.great_person_progress(pid)
  local p, cities = Players[pid], {}
  for c in p:Cities() do
    local meters = {}
    for s in GameInfo.Specialists() do
      if s.GreatPeopleUnitClass then
        local m = H.specialist_meter(c, s, p)
        if m and (m.gp_progress > 0 or m.gp_per_turn > 0 or m.count > 0) then meters[#meters + 1] = m end
      end
    end
    if #meters > 0 then cities[#cities + 1] = { city_id = c:GetID(), name = c:GetName(), meters = meters } end
  end
  return { ok = true, cities = cities,
    general = { progress = p:GetCombatExperience(), threshold = p:GreatGeneralThreshold() },
    admiral = { progress = p:GetNavalCombatExperience(), threshold = p:GreatAdmiralThreshold() },
    prophet = { faith = p:GetFaith(), next_faith = p:GetMinimumFaithNextGreatProphet() } }
end

-- Religion banner tooltip: only majority and religions with followers are displayed.
-- Keep the engine's raw pressure alongside the scaled integer printed by the UI.
function H.city_religions(c)
  local rows = {}
  local majority = c:GetReligiousMajority()
  for rel in GameInfo.Religions() do
    local n = c:GetNumFollowers(rel.ID)
    if rel.ID >= 0 and (rel.ID == majority or n > 0) then
      local raw, routes = c:GetPressurePerTurn(rel.ID)
      rows[#rows + 1] = { religion = rel.Type, name = H.L(Game.GetReligionName(rel.ID)), followers = n,
        majority = rel.ID == majority, pressure_raw = raw,
        pressure_per_turn = math.floor(raw / GameDefines.RELIGION_MISSIONARY_PRESSURE_MULTIPLIER),
        trade_routes = routes or c:GetNumTradeRoutesAddingPressure(rel.ID), holy_city = c:IsHolyCityForReligion(rel.ID) }
    end
  end
  return rows
end

-- City screen for one of my cities (buildings, specialists, worked tiles, queue, focus, buy-plot).
-- cities() stays the banner; this is what opening the city shows.

-- cityview.lua's corner meters, which are not the integer banner numbers cities() prints.
-- CanBuyPlotAt's third argument is "ignore gold": false is the enabled button, true is the red
-- price shown when the tile is buyable but unaffordable (TXT_KEY_CITYVIEW_NEED_MONEY_BUY_TILE).
local function option_on(name)
  if not (Game and Game.IsOption and GameOptionTypes and GameOptionTypes[name]) then return false end
  local ok, v = pcall(Game.IsOption, GameOptionTypes[name])
  return ok and v and true or false
end

-- Lines of an engine tooltip string (GetYieldModifierTooltip, GetTourismTooltip): tags stripped,
-- one entry per [NEWLINE], blank and rule lines dropped.
local function tooltip_lines(s)
  if type(s) ~= "string" then return nil end
  -- the engine's trade-route line is tagged [BULLET], not [ICON_BULLET] (live t266 Te-Moak gold hover)
  local t = plain_text((s:gsub("%[BULLET%]", "[ICON_BULLET]")))
  if not t then return nil end
  local out = {}
  for line in (t .. "\n"):gmatch("(.-)\n") do
    line = line:gsub("^%s*•%s*", ""):gsub("^%s+", ""):gsub("%s+$", "")
    if line ~= "" and not line:match("^%-%-%-+$") then out[#out + 1] = line end
  end
  if #out == 0 then return nil end
  return out
end

-- The hover on a city-screen yield (infotooltipinclude.lua GetYieldTooltipHelper / GetYieldTooltip):
-- the base sources the stock text bullets, the food usage line, the engine's modifier lines and
-- the total. Zero sources are omitted, as the tooltip omits them. `misc` is the science tooltip's
-- "from population" line when the yield is science (the stock text swaps the key, not the number).
local function city_yield_breakdown(c, ytype, is_food, is_science, is_production)
  local b = {}
  local function num(f)
    local ok, v = pcall(f)
    if ok and type(v) == "number" then return v end
    return nil
  end
  local function put(k, v) if v and v ~= 0 then b[k] = v end end
  put("terrain", num(function() return c:GetBaseYieldRateFromTerrain(ytype) end))
  put("buildings", num(function() return c:GetBaseYieldRateFromBuildings(ytype) end))
  put("specialists", num(function() return c:GetBaseYieldRateFromSpecialists(ytype) end))
  local misc = num(function() return c:GetBaseYieldRateFromMisc(ytype) end)
  if misc and misc ~= 0 then
    if is_science then b.population = misc else b.misc = misc end
  end
  local per_pop = num(function() return c:GetYieldPerPopTimes100(ytype) end)
  local pop_extra = 0
  if per_pop and per_pop ~= 0 then
    pop_extra = per_pop * c:GetPopulation() / 100
    put("per_population", pop_extra)
  end
  put("religion", num(function() return c:GetBaseYieldRateFromReligion(ytype) end))
  local base = num(function() return c:GetBaseYieldRate(ytype) end)
  local total
  if is_production then
    -- GetProductionTooltip: base is the bare GetBaseYieldRate and the total is the production-specific
    -- rate (live t266 Machu: yield rate 9, production difference 9.45 -- the meter's number)
    total = num(function() return c:GetCurrentProductionDifferenceTimes100(false, false) / 100 end)
  elseif base then
    base = base + pop_extra
  end
  if is_food then
    local gross = num(function() return c:GetYieldRate(ytype, false) end)
    local no_trade = num(function() return c:GetYieldRate(ytype, true) end)
    if gross and no_trade and gross - no_trade ~= 0 then b.trade_routes = gross - no_trade end
    local eaten = num(function() return c:FoodConsumption(true, 0) end)
    if eaten and eaten ~= 0 then
      b.eaten = eaten
      if gross then b.gross = gross; base = gross - eaten end
    end
    total = num(function() return c:FoodDifferenceTimes100() / 100 end)
  elseif not is_production then
    total = num(function() return c:GetYieldRateTimes100(ytype) / 100 end)
  end
  if base then b.base = base end
  local okm, mods = pcall(function() return c:GetYieldModifierTooltip(ytype) end)
  if okm then
    local lines = tooltip_lines(mods)
    if lines then b.modifiers = lines end
  end
  if total then b.total = total end
  return b
end

-- infotooltipinclude.lua GetCultureTooltip: the sources it bullets and the three modifiers it names.
local function city_culture_breakdown(c, p)
  local b = {}
  local function put(k, f)
    local ok, v = pcall(f)
    if ok and type(v) == "number" and v ~= 0 then b[k] = v end
  end
  put("buildings", function() return c:GetJONSCulturePerTurnFromBuildings() end)
  put("policies", function() return c:GetJONSCulturePerTurnFromPolicies() end)
  put("specialists", function() return c:GetJONSCulturePerTurnFromSpecialists() end)
  put("great_works", function() return c:GetJONSCulturePerTurnFromGreatWorks() end)
  put("religion", function() return c:GetJONSCulturePerTurnFromReligion() end)
  put("leagues", function() return c:GetJONSCulturePerTurnFromLeagues() end)
  put("terrain", function() return c:GetBaseYieldRateFromTerrain(YieldTypes.YIELD_CULTURE) end)
  put("traits", function() return c:GetJONSCulturePerTurnFromTraits() end)
  put("player_modifier_pct", function() return p:GetCultureCityModifier() end)
  put("city_modifier_pct", function() return c:GetCultureRateModifier() end)
  pcall(function()
    if c:GetNumWorldWonders() > 0 then
      local w = p:GetCultureWonderMultiplier()
      if w ~= 0 then b.wonder_bonus_pct = w end
    end
  end)
  pcall(function()
    if c:IsPuppet() and GameDefines and GameDefines.PUPPET_CULTURE_MODIFIER and GameDefines.PUPPET_CULTURE_MODIFIER ~= 0 then
      b.puppet_modifier_pct = GameDefines.PUPPET_CULTURE_MODIFIER
    end
  end)
  put("total", function() return c:GetJONSCulturePerTurn() end)
  return b
end

-- infotooltipinclude.lua GetFaithTooltip, minus the followers block (city_screen.religions has it).
local function city_faith_breakdown(c)
  local b = {}
  local function put(k, f)
    local ok, v = pcall(f)
    if ok and type(v) == "number" and v ~= 0 then b[k] = v end
  end
  put("buildings", function() return c:GetFaithPerTurnFromBuildings() end)
  put("traits", function() return c:GetFaithPerTurnFromTraits() end)
  put("terrain", function() return c:GetBaseYieldRateFromTerrain(YieldTypes.YIELD_FAITH) end)
  put("policies", function() return c:GetFaithPerTurnFromPolicies() end)
  put("religion", function() return c:GetFaithPerTurnFromReligion() end)
  pcall(function()
    if c:IsPuppet() and GameDefines and GameDefines.PUPPET_FAITH_MODIFIER and GameDefines.PUPPET_FAITH_MODIFIER ~= 0 then
      b.puppet_modifier_pct = GameDefines.PUPPET_FAITH_MODIFIER
    end
  end)
  put("total", function() return c:GetFaithPerTurn() end)
  return b
end

local function city_screen_meters(c, p)
  local m = {}
  -- Growth label: a settler (IsFoodProduction) or a zero FoodDifferenceTimes100 is "stagnant"
  -- even when the banner's FoodDifference(true) is not. Turns are only shown while growing.
  pcall(function()
    local per100 = c:FoodDifferenceTimes100()
    local diff = c:FoodDifference()
    local food = { stored = c:GetFood(), needed = c:GrowthThreshold(), per_turn = per100 / 100 }
    if c:IsFoodProduction() or per100 == 0 then
      food.state = "stagnant"
    elseif diff < 0 then
      food.state = "starving"
    else
      food.state = "growing"
      food.turns = c:GetFoodTurnsLeft()
    end
    m.food = food
  end)
  -- Production meter. The modifier is NOT applied again: cityview.lua reads
  -- GetCurrentProductionDifferenceTimes100 and then comments out the second multiply.
  -- A process has no "needed" (the bar is empty).
  pcall(function()
    local prod = {
      stored = c:GetProductionTimes100() / 100,
      per_turn = c:GetCurrentProductionDifferenceTimes100(false, false) / 100,
    }
    if not c:IsProductionProcess() then prod.needed = c:GetProductionNeeded() end
    local okm, mod = pcall(function() return c:GetProductionModifier() end)
    if okm and type(mod) == "number" and mod ~= 0 then prod.modifier = mod end
    m.production = prod
  end)
  -- Culture until the next border tile. The label is hidden when culture per turn is 0;
  -- otherwise ceil((threshold - stored) / per_turn), and never less than 1.
  pcall(function()
    local stored = c:GetJONSCultureStored()
    local needed = c:GetJONSCultureThreshold()
    local per = c:GetJONSCulturePerTurn()
    local culture = { stored = stored, needed = needed, per_turn = per }
    if per > 0 then
      local turns = math.ceil((needed - stored) / per)
      if turns < 1 then turns = 1 end
      culture.turns = turns
    end
    m.culture = culture
  end)
  pcall(function() m.gold = c:GetYieldRateTimes100(YieldTypes.YIELD_GOLD) / 100 end)
  if not option_on("GAMEOPTION_NO_SCIENCE") then
    pcall(function() m.science = c:GetYieldRateTimes100(YieldTypes.YIELD_SCIENCE) / 100 end)
  end
  if not option_on("GAMEOPTION_NO_RELIGION") then
    pcall(function() m.faith = c:GetFaithPerTurn() end)
  end
  pcall(function() m.tourism = c:GetBaseTourism() end)
  pcall(function()
    if p:IsEmpireVeryUnhappy() then m.empire_very_unhappy = true end
  end)
  -- The hovers behind each meter (GitLab #14). Kept beside the meters rather than inside them so the
  -- scalar gold/science/faith/tourism fields stay what they were.
  local br = {}
  local function add(k, f)
    local ok, b = pcall(f)
    if ok and type(b) == "table" and next(b) then br[k] = b end
  end
  add("food", function() return city_yield_breakdown(c, YieldTypes.YIELD_FOOD, true, false) end)
  add("production", function() return city_yield_breakdown(c, YieldTypes.YIELD_PRODUCTION, false, false, true) end)
  add("gold", function() return city_yield_breakdown(c, YieldTypes.YIELD_GOLD, false, false) end)
  if not option_on("GAMEOPTION_NO_SCIENCE") then
    add("science", function() return city_yield_breakdown(c, YieldTypes.YIELD_SCIENCE, false, true) end)
  end
  if not option_on("GAMEOPTION_NO_POLICIES") then
    add("culture", function() return city_culture_breakdown(c, p) end)
  end
  if not option_on("GAMEOPTION_NO_RELIGION") then
    add("faith", function() return city_faith_breakdown(c) end)
  end
  add("tourism", function() return tooltip_lines(c:GetTourismTooltip()) end)
  if next(br) then m.breakdown = br end
  return m
end

-- The numbers the city screen prints beside a specialist slot (cityview.lua, the building row's
-- tooltip): City:GetSpecialistYield per yield -- which already includes the player's extra yield --
-- the specialist's culture, and its great-person points (GitLab #16).
function H.specialist_yields(c, s)
  local y = {}
  if GameInfo and GameInfo.Yields then
    for yi in GameInfo.Yields() do
      local ok, v = pcall(function() return c:GetSpecialistYield(s.ID, yi.ID) end)
      if ok and type(v) == "number" and v > 0 then y[short(yi.Type)] = v end
    end
  end
  local okc, cul = pcall(function() return c:GetCultureFromSpecialist(s.ID) end)
  if okc and type(cul) == "number" and cul > 0 then y.CULTURE = (y.CULTURE or 0) + cul end
  if s.GreatPeopleRateChange and s.GreatPeopleRateChange > 0 then y.GREAT_PEOPLE = s.GreatPeopleRateChange end
  if next(y) then return y end
  return nil
end

function H.city_screen(city_id, pid)
  local p = Players[pid]
  local c = p:GetCityByID(city_id)
  if not c then return { ok = false, err = "no such city" } end
  local buildings, specialists, plots, queue = {}, {}, {}, {}
  if GameInfo and GameInfo.Buildings then
    for b in GameInfo.Buildings() do
      if b and b.ID then
        local n = c.GetNumRealBuilding and c:GetNumRealBuilding(b.ID) or 0
        local free = c.GetNumFreeBuilding and c:GetNumFreeBuilding(b.ID) or 0
        if n > 0 or free > 0 then
          local e = { building = b.Type, name = short(b.Type) }
          if n > 1 then e.count = n end
          if free > 0 then e.free = free end
          -- The building row's hover (GitLab #17) is static text: reference("buildings") carries it once (v216).
          -- City-screen "click to sell": puppets are run by the AI (BNW cityview.lua).
          if not c:IsPuppet() then
            local ok_s, sell = pcall(function() return c:IsBuildingSellable(b.ID) end)
            if ok_s and sell then
              e.can_sell = true
              local ok_r, refund = pcall(function() return c:GetSellBuildingRefund(b.ID) end)
              if ok_r then e.sell_gold = refund end
              if b.GoldMaintenance and b.GoldMaintenance > 0 then e.gold_maintenance = b.GoldMaintenance end
            end
          end
          if b.SpecialistType and c.GetNumSpecialistsInBuilding then
            local assigned = c:GetNumSpecialistsInBuilding(b.ID)
            local slots = c.GetNumSpecialistsAllowedByBuilding and c:GetNumSpecialistsAllowedByBuilding(b.ID) or 0
            if slots > 0 or assigned > 0 then
              e.specialist = b.SpecialistType
              e.specialist_assigned = assigned
              e.specialist_slots = slots
              local sinfo = GameInfo.Specialists and GameInfo.Specialists[b.SpecialistType]
              if sinfo and sinfo.ID then e.specialist_yields = H.specialist_yields(c, sinfo) end
            end
          end
          buildings[#buildings + 1] = e
        end
      end
    end
  end
  if GameInfo and GameInfo.Specialists then
    for s in GameInfo.Specialists() do
      if s and s.ID and s.Type ~= "SPECIALIST_CITIZEN" then
        local m = H.specialist_meter(c, s, p)
        if m and (m.count > 0 or m.gp_progress > 0 or m.gp_per_turn > 0) then
          m.yields = H.specialist_yields(c, s)
          specialists[#specialists + 1] = m
        end
      end
    end
  end
  pcall(function()
    for i = 0, c:GetOrderQueueLength() - 1 do
      local orderType, data = c:GetOrderFromQueue(i)
      local row = (orderType == OrderTypes.ORDER_TRAIN and GameInfo.Units[data])
               or (orderType == OrderTypes.ORDER_CONSTRUCT and GameInfo.Buildings[data])
               or (orderType == OrderTypes.ORDER_CREATE and GameInfo.Projects[data])
               or (orderType == OrderTypes.ORDER_MAINTAIN and GameInfo.Processes[data])
      queue[#queue + 1] = row and row.Type or tostring(data)
    end
  end)
  local nplots = c.GetNumCityPlots and c:GetNumCityPlots() or 0
  for i = 0, nplots - 1 do
    local plot = c.GetCityIndexPlot and c:GetCityIndexPlot(i)
    if plot then
      local e = { x = plot:GetX(), y = plot:GetY(), i = i }
      if i == 0 then e.city_tile = true end
      local okw, worked = pcall(function() return c:IsWorkingPlot(plot) end)
      if okw and worked then e.worked = true end
      local okf, forced = pcall(function() return c:IsForcedWorkingPlot(plot) end)
      if okf and forced then e.forced = true end
      local okc, can = pcall(function() return c:CanWork(plot) end)
      if okc and can then e.can_work = true end
      local x, y = plot:GetX(), plot:GetY()
      local ok_now, now = pcall(function() return c:CanBuyPlotAt(x, y, false) end)
      local ok_show, show = pcall(function() return c:CanBuyPlotAt(x, y, true) end)
      if (ok_now and now) or (ok_show and show) then
        local okp, cost = pcall(function() return c:GetBuyPlotCost(x, y) end)
        if okp then e.buy_gold = cost end
        if ok_now and now then
          e.buyable = true
        else
          e.can_afford = false
        end
      end
      -- Icons the city screen draws on a tile this city owns but is not simply "unworked":
      -- another of our cities is working it, a blockaded water tile, or a visible enemy unit.
      pcall(function()
        if plot:GetOwner() ~= c:GetOwner() then return end
        local other = plot.GetWorkingCity and plot:GetWorkingCity()
        if other and other:GetID() ~= c:GetID() and other:IsWorkingPlot(plot) then
          e.worked_by = other:GetName()
        end
        if plot:IsWater() and c.IsPlotBlockaded and c:IsPlotBlockaded(plot) then
          e.blockaded = true
        end
        if plot.IsVisibleEnemyUnit and plot:IsVisibleEnemyUnit(c:GetOwner()) then
          e.enemy_unit = true
        end
      end)
      if plot:IsVisible(p:GetTeam(), false) then e.yields = plot_yields(plot) end
      plots[#plots + 1] = e
    end
  end
  local demanded
  pcall(function()
    local r = c:GetResourceDemanded()
    if r and r >= 0 then demanded = short(info_type(GameInfo.Resources, r)) end
  end)
  local turns, pnote = production_turns_and_note(c)
  local screen = {
    ok = true, id = c:GetID(), name = c:GetName(), x = c:GetX(), y = c:GetY(), pop = c:GetPopulation(),
    capital = c:IsCapital(), puppet = c:IsPuppet(), occupied = c:IsOccupied(), razing = c:IsRazing(),
    focus = city_focus_name(c),
    avoid_growth = (c.IsForcedAvoidGrowth and c:IsForcedAvoidGrowth()) or false,
    auto_specialists = not (c.IsNoAutoAssignSpecialists and c:IsNoAutoAssignSpecialists()),
    buildings = buildings, specialists = specialists, plots = plots, queue = queue,
    production = H.L(c:GetProductionNameKey()),
    production_turns = turns, production_note = pnote,
    food_surplus = c:FoodDifference(true),
    growth = (c:FoodDifference(true) > 0 and "growing") or (c:FoodDifference(true) < 0 and "starving") or "stagnant",
    growth_turns = (c:FoodDifference(true) > 0) and c:GetFoodTurnsLeft() or nil,
    resistance_turns = (c.IsResistance and c:IsResistance() and c.GetResistanceTurns and c:GetResistanceTurns()) or nil,
    razing_turns = (c.IsRazing and c:IsRazing() and c.GetRazingTurns and c:GetRazingTurns()) or nil,
    resource_demanded = demanded,
    blockaded = (function()
      local ok, v = pcall(function() return c:IsBlockaded() end)
      if ok and v then return true end
    end)(),
    wltkd_turns = (function()
      local ok, v = pcall(function() return c:GetWeLoveTheKingDayCounter() end)
      if ok and type(v) == "number" and v > 0 then return v end
    end)(),
    can_annex = c:IsPuppet() and not (p.MayNotAnnex and p:MayNotAnnex()),
    can_raze = (not c:IsCapital()) and p.CanRaze and p:CanRaze(c) or false,
    can_unraze = c:IsRazing() or false,
  }
  local meters = city_screen_meters(c, p)
  if next(meters) then screen.meters = meters end
  return screen
end

-- Shared with later fragments, which import these at their top (load order: harness/runtime_source.py MANIFEST).
H._ns.plot_yields = plot_yields
H._ns.FOCUS_IDS = FOCUS_IDS
H._ns.city_focus_name = city_focus_name
