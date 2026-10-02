-- Shared by earlier fragments (load order: harness/runtime_source.py MANIFEST).
local info_type, plain_text, short = H._ns.info_type, H._ns.plain_text, H._ns.short

-- Item-based trade deals: UI.GetScratchDeal() returns a shared "scratch" deal object with a dedicated Add*
-- method per item type (there is no generic AddItemOfType -- each type has its own method and argument
-- shape, confirmed by reading every Add* call site in ui/ingame/worldview/tradelogic.lua). Same call path
-- for a human or an AI recipient: build the deal, SetFromPlayer/SetToPlayer, UI.DoProposeDeal(). An AI
-- either accepts (deal resolves) or doesn't; a human recipient sees it as an incoming offer.
-- `items`: a list of { type = "GOLD"|"GOLD_PER_TURN"|"RESOURCES"|"OPEN_BORDERS"|"DEFENSIVE_PACT"|
--   "RESEARCH_AGREEMENT"|"TRADE_AGREEMENT"|"ALLOW_EMBASSY"|"DECLARATION_OF_FRIENDSHIP"|"PEACE_TREATY"|
--   "CITIES", from_us = true|false, ...type-specific fields (amount / resource / city_id) }.
--
-- ROOT CAUSE of the 2026-09-16 crash (see docs/NOTES.md "Phase 3a"): every Add* method in the real UI is
-- only reachable through a pocket button that tradelogic.lua populates by first calling
-- `deal:IsPossibleToTradeItem(from, to, TradeableItems.TRADE_ITEM_*, ...)` -- e.g. lines ~1124 (embassy),
-- ~1057 (gold), ~1283 (research agreement) of ui/ingame/worldview/tradelogic.lua. An item that fails that
-- check is never offered to the player at all. This function used to skip that gate entirely and call
-- Add* unconditionally, so a single ALLOW_EMBASSY item that was NOT actually valid between the two players
-- (e.g. an embassy already existed, one side doesn't allow embassy trading) reached UI.DoProposeDeal() as
-- part of an invalid deal and crashed the process natively. Fixed by validating every item with the same
-- IsPossibleToTradeItem call the UI itself uses before adding it, and by mirroring the two other guards
-- OnPropose()/OnOpenPlayerDealScreen() apply: refuse an empty deal, and refuse a second proposal while one
-- is already outstanding (UI.HasMadeProposal). NOT yet re-verified live -- test against a throwaway game
-- before trusting this in a real session.
-- RETIRED 2026-09-17: the headless Add*/DoProposeDeal path below crashed the game eight times. Deals now
-- go through the real trade screen from Python (Game.propose_deal in harness/game.py drives
-- LeaderHeadRoot.OnTrade + tradelogic.lua's pocket handlers + OnPropose). The body is kept only as a
-- reference for the per-item IsPossibleToTradeItem shapes (H.trade_catalog uses the same ones).
function H.propose_deal(other_player, items, pid)
  return { ok = false, err = "headless propose_deal is retired; use Game.propose_deal (real trade screen)" }
end
function H.propose_deal_headless_reference(other_player, items, pid)
  if #items == 0 then return { ok = false, err = "no items in deal" } end
  local existing = UI.HasMadeProposal(pid)
  if existing ~= -1 and existing ~= other_player then
    return { ok = false, err = "a proposal to another player is already outstanding" }
  end
  local deal = UI.GetScratchDeal()
  deal:ClearItems()
  local duration = Game.GetDealDuration()
  for _, item in ipairs(items) do
    local from = item.from_us and pid or other_player
    local to = item.from_us and other_player or pid
    local t = item.type
    local possible, extra
    if t == "GOLD" then
      possible = deal:IsPossibleToTradeItem(from, to, TradeableItems.TRADE_ITEM_GOLD, item.amount)
      extra = function() deal:AddGoldTrade(from, item.amount) end
    elseif t == "GOLD_PER_TURN" then
      possible = deal:IsPossibleToTradeItem(from, to, TradeableItems.TRADE_ITEM_GOLD_PER_TURN, item.amount, duration)
      extra = function() deal:AddGoldPerTurnTrade(from, item.amount, duration) end
    elseif t == "RESOURCES" then
      local rid = GameInfoTypes[item.resource]
      if rid == nil then return { ok = false, err = "unknown resource " .. tostring(item.resource) } end
      possible = deal:IsPossibleToTradeItem(from, to, TradeableItems.TRADE_ITEM_RESOURCES, rid, item.amount)
      extra = function() deal:AddResourceTrade(from, rid, item.amount, duration) end
    elseif t == "OPEN_BORDERS" then
      possible = deal:IsPossibleToTradeItem(from, to, TradeableItems.TRADE_ITEM_OPEN_BORDERS, duration)
      extra = function() deal:AddOpenBorders(from, duration) end
    elseif t == "DEFENSIVE_PACT" then
      possible = deal:IsPossibleToTradeItem(from, to, TradeableItems.TRADE_ITEM_DEFENSIVE_PACT, duration)
      extra = function() deal:AddDefensivePact(from, duration) end
    elseif t == "RESEARCH_AGREEMENT" then
      possible = deal:IsPossibleToTradeItem(from, to, TradeableItems.TRADE_ITEM_RESEARCH_AGREEMENT, duration)
      extra = function() deal:AddResearchAgreement(from, duration) end
    elseif t == "TRADE_AGREEMENT" then
      possible = deal:IsPossibleToTradeItem(from, to, TradeableItems.TRADE_ITEM_TRADE_AGREEMENT, duration)
      extra = function() deal:AddTradeAgreement(from, duration) end
    elseif t == "ALLOW_EMBASSY" then
      possible = deal:IsPossibleToTradeItem(from, to, TradeableItems.TRADE_ITEM_ALLOW_EMBASSY, duration)
      extra = function() deal:AddAllowEmbassy(from) end
    elseif t == "DECLARATION_OF_FRIENDSHIP" then
      -- CRASHED THE GAME live (2026-09-16, round 2 of this same fix pass): tradelogic.lua only ever
      -- populates/checks this item when g_bPVPTrade is true ("Only PvP trade, with the AI there is a
      -- dedicated interface for this trade", line ~1399) -- deal:IsPossibleToTradeItem() itself crashed
      -- natively when called for this item type against an AI recipient. Block it before touching the
      -- engine at all; use H.diplo_event with a DoF-related FromUIDiploEventTypes event for AI instead
      -- (see docs/NOTES.md diplomacy section).
      if not Players[other_player]:IsHuman() then
        deal:ClearItems()
        return { ok = false, err = "DECLARATION_OF_FRIENDSHIP is PvP-only; use diplo_event for an AI" }
      end
      possible = deal:IsPossibleToTradeItem(from, to, TradeableItems.TRADE_ITEM_DECLARATION_OF_FRIENDSHIP, duration)
      extra = function() deal:AddDeclarationOfFriendship(from) end
    elseif t == "PEACE_TREATY" then
      -- CRASHED THE GAME live (2026-09-16, third crash of this pass, see docs/NOTES.md "Phase 3a live
      -- verification") even with both required sides added exactly as below, matching
      -- OnOpenPlayerDealScreen's own AddPeaceTreaty(us,...)+AddPeaceTreaty(them,...) pair -- this is NOT
      -- fixed, the crash is in the native Add* call itself, not a missing validation. Left implemented
      -- (and now matching the real UI's paired-sides shape, which the original single-sided version did
      -- not) only so a future session that finds a real fix doesn't also have to rediscover this
      -- asymmetry; do not call PEACE_TREATY (or re-expose propose_deal at all) until that's resolved.
      -- No IsPossibleToTradeItem gate for this one in the real UI either (tradelogic.lua adds it
      -- unconditionally when IsAtWar); mirror that same precondition instead.
      local fromTeam = Players[from]:GetTeam()
      local toTeam = Players[to]:GetTeam()
      possible = Teams[fromTeam]:IsAtWar(toTeam)
      extra = function()
        deal:AddPeaceTreaty(from, GameDefines.PEACE_TREATY_LENGTH)
        deal:AddPeaceTreaty(to, GameDefines.PEACE_TREATY_LENGTH)
      end
    elseif t == "CITIES" then
      local city = Players[from]:GetCityByID(item.city_id)
      if not city then deal:ClearItems(); return { ok = false, err = "no such city" } end
      possible = deal:IsPossibleToTradeItem(from, to, TradeableItems.TRADE_ITEM_CITIES, city:GetX(), city:GetY())
      extra = function() deal:AddCityTrade(from, item.city_id) end
    else
      deal:ClearItems()
      return { ok = false, err = "unsupported item type " .. tostring(t) }
    end
    if not possible then
      deal:ClearItems()
      return { ok = false, err = "item not tradeable: " .. tostring(t) .. " from " .. tostring(from) .. " to " .. tostring(to) }
    end
    extra()
  end
  deal:SetFromPlayer(pid)
  deal:SetToPlayer(other_player)
  UI.DoProposeDeal()
  return { ok = true }
end

-- One deal object's items (scratch or a LoadCurrentDeal snapshot). Read-only: no Add*/ClearItems.
-- GetNextItem's third value is the turn the timed item ends (diplocurrentdeals.lua "ENDS ON").
function H.deal_items(deal, pid)
  local items = {}
  if not (deal and deal.ResetIterator and deal.GetNextItem) then return items end
  -- v259: an item's own from-player can name a third civ (live t162 Mongolia: Catherine's renewal offer, deal
  -- from 1 to 7, carried England's id 2 on her open borders and gold per turn). The trade screen places an item
  -- by "ours or not", so the giver of anything not ours is the deal's other player; the raw id rides along as
  -- `from_engine` only when it differs.
  local other
  pcall(function() other = deal.GetOtherPlayer and deal:GetOtherPlayer(pid) or nil end)
  if type(other) ~= "number" or other < 0 then other = nil end
  deal:ResetIterator()
  local itemType, duration, finalTurn, data1, data2, data3, flag1, fromPlayer = deal:GetNextItem()
  local turn = Game and Game.GetGameTurn and Game.GetGameTurn() or nil
  while itemType ~= nil do
    local name = H.enum_name("TradeableItems", TradeableItems, itemType)
    if type(name) == "string" then name = name:gsub("^TRADE_ITEM_", "") end
    local e = { type = name, from = fromPlayer, from_us = fromPlayer == pid, duration = duration }
    if not e.from_us and other and fromPlayer ~= other then e.from, e.from_engine = other, fromPlayer end
    if type(finalTurn) == "number" and finalTurn > 0 then
      e.final_turn = finalTurn
      if type(turn) == "number" then e.turns_left = finalTurn - turn end
    end
    if name == "GOLD" or name == "GOLD_PER_TURN" then
      e.amount = data1
    elseif name == "RESOURCES" then
      e.resource = GameInfo and short(info_type(GameInfo.Resources, data1)) or data1
      e.amount = data2
      -- what giving it costs us (renewal offers name a resource trade_catalog no longer lists because
      -- it is still under the expiring deal; live t292 America's Dye renewal). Same numbers the
      -- top bar / trade screen show a human.
      if e.from_us and Players and Players[pid] then
        local pl, info = Players[pid], GameInfo and GameInfo.Resources and GameInfo.Resources[data1] or nil
        local function num(f) local okc, v = pcall(function() return pl[f](pl, data1, true) end) if okc and type(v) == "number" then return v end return nil end
        local function num1(f) local okc, v = pcall(function() return pl[f](pl, data1) end) if okc and type(v) == "number" then return v end return nil end
        e.class = info and info.ResourceClassType or nil
        e.us_total, e.us_available = num("GetNumResourceTotal"), num("GetNumResourceAvailable")
        e.us_imported, e.us_exported = num1("GetResourceImport"), num1("GetResourceExport")
        -- GetNumResourceTotal is already net of exports (live t292: Copper total 1, exported 2,
        -- available 1 = three copies owned, two under deals). us_owned undoes that so a renewal of an
        -- existing export is not mistaken for selling our only copy.
        if e.us_total then e.us_owned = e.us_total - (e.us_imported or 0) + (e.us_exported or 0) end
        if e.class == "RESOURCECLASS_LUXURY" and e.us_owned and e.us_owned <= (e.amount or 1) then
          e.last_copy = true
          e.note = "our only copy: exporting it removes its happiness from the empire"
        elseif e.us_available and e.us_available < (e.amount or 1) then
          e.note = "no spare copy: either this renews an export already counted in us_exported (no change), or it takes a copy we use"
        end
      elseif Players and Players[pid] then
        -- what receiving it gives us: a luxury we already have adds no happiness (live t444: Venice offered
        -- Spices for Copper and nothing said whether Spices was new). Our own count, as the top bar shows.
        local pl, info = Players[pid], GameInfo and GameInfo.Resources and GameInfo.Resources[data1] or nil
        e.class = info and info.ResourceClassType or nil
        local okc, have = pcall(function() return pl:GetNumResourceAvailable(data1, true) end)
        if okc and type(have) == "number" then
          e.us_have = have
          if e.class == "RESOURCECLASS_LUXURY" then
            e.note = have > 0 and "we already have this luxury: no extra happiness" or "new luxury for us: adds its happiness"
          end
        end
      end
    elseif name == "CITIES" then
      -- The deal screen (tradelogic.lua DisplayDeal) names the city and shows its population, never
      -- its coordinates. data1/data2 are the plot; they are the item's identity for us, but they only
      -- reach the row once the plot is revealed to this seat -- the same gate trade_catalog applies.
      -- Until v191 they were copied unconditionally, so a deal could place a city we had never seen
      -- (GitLab #2).
      local owner = Players and Players[fromPlayer]
      if owner and owner.Cities then
        for c in owner:Cities() do
          if c:GetX() == data1 and c:GetY() == data2 then
            e.name, e.city_id = c:GetName(), c:GetID()
            local okp, pop = pcall(function() return c:GetPopulation() end)
            if okp and type(pop) == "number" then e.pop = pop end
            break
          end
        end
      end
      local revealed = false
      if Map and Map.GetPlot and Players and Players[pid] then
        pcall(function()
          local plot = Map.GetPlot(data1, data2)
          revealed = plot and plot:IsRevealed(Players[pid]:GetTeam(), false) or false
        end)
      end
      if revealed then e.x, e.y = data1, data2 end
    elseif name == "THIRD_PARTY_PEACE" or name == "THIRD_PARTY_WAR" then
      -- tradelogic.lua LeaderSelected: AddThirdPartyWar/Peace(who, otherTEAM); DisplayOtherPlayerItem then
      -- shows that team's leader button. data1 is the team; `other` is the player the screen names
      -- (until v199 the raw team id was reported as `other`, which is a player id only by luck; GitLab #6).
      e.team = data1
      if H.third_party_player then
        local okp, who = pcall(H.third_party_player, data1)
        if okp and type(who) == "table" then for k, v in pairs(who) do e[k] = v end end
      end
    elseif name == "VOTE_COMMITMENT" then
      -- tradelogic.lua DisplayDeal: data1 resolution id, data2 the voter choice, data3 the votes
      -- committed, flag1 repeal (GetLeagueVoteIndexFromData). Until v198 all four were dropped, so an
      -- incoming commitment was a bare type name (GitLab #7). The screen labels it with the resolution's
      -- name and the choice text; the same words go on the row when the league still lists the proposal.
      local repeal = (flag1 == true or flag1 == 1)
      e.resolution_id, e.choice_id, e.votes, e.repeal = data1, data2, data3, repeal
      if H.describe_vote_commitment then
        local okv, d = pcall(H.describe_vote_commitment, data1, data2, repeal)
        if okv and type(d) == "table" then for k, v in pairs(d) do e[k] = v end end
      end
    end
    items[#items + 1] = e
    itemType, duration, finalTurn, data1, data2, data3, flag1, fromPlayer = deal:GetNextItem()
  end
  return items
end

-- Read the current scratch deal WITHOUT Add*/ClearItems/DoProposeDeal.
-- tradelogic.lua DisplayDeal() iterates with ResetIterator + GetNextItem; that is a
-- read of whatever is already on the table (empty, our draft, or an AI offer).
-- The seat that has a deal proposal waiting for us (UI.ProposedDealExists(them, us)), or nil. The
-- stock game announces it with a notification whose click opens the PvP deal screen; turn_status
-- names the proposer so the seat knows to read incoming_deal (GitLab #4).
function H.pending_deal_from(pid)
  if not (UI and UI.ProposedDealExists) then return nil end
  local max = (GameDefines and GameDefines.MAX_MAJOR_CIVS) or 22
  for i = 0, max - 1 do
    local okp, exists = pcall(function() return i ~= pid and Players[i] and UI.ProposedDealExists(i, pid) end)
    if okp and exists then return i end
  end
  return nil
end

function H.incoming_deal(pid)
  if not UI or not UI.GetScratchDeal then
    return { ok = true, items = {}, n = 0 }
  end
  local ok, deal = pcall(function() return UI.GetScratchDeal() end)
  if not ok or deal == nil then return { ok = true, items = {}, n = 0 } end
  local items = H.deal_items(deal, pid)
  local proposed_by
  if #items == 0 and UI.ProposedDealExists and UI.LoadProposedDeal then
    -- A proposal from another human seat is not on the scratch table until the deal screen loads it
    -- (tradelogic.lua OnOpenPlayerDealScreen: ProposedDealExists(them, us) -> LoadProposedDeal). Do
    -- the same so the receiving seat can read it, then accept_deal / refuse_deal (GitLab #4).
    local max = (GameDefines and GameDefines.MAX_MAJOR_CIVS) or 22
    for i = 0, max - 1 do
      local okp, exists = pcall(function() return i ~= pid and Players[i] and UI.ProposedDealExists(i, pid) end)
      if okp and exists then
        pcall(function() UI.LoadProposedDeal(i, pid) end)
        items = H.deal_items(deal, pid)
        proposed_by = i
        break
      end
    end
  end
  local from = deal.GetFromPlayer and deal:GetFromPlayer() or nil
  local to = deal.GetToPlayer and deal:GetToPlayer() or nil
  -- The engine may already have loaded another seat's proposal into the scratch (live t227: Bravo's
  -- table held Alpha's three items before anything asked for them); it is still their pending offer.
  if proposed_by == nil and #items > 0 and type(from) == "number" and from ~= pid and UI.ProposedDealExists then
    local okp, exists = pcall(function() return UI.ProposedDealExists(from, pid) end)
    if okp and exists then proposed_by = from end
  end
  local ours_pending
  if type(from) == "number" and from == pid and UI.HasMadeProposal then
    local okh, made = pcall(function() return UI.HasMadeProposal(pid) end)
    if okh and made == to then ours_pending = true end
  end
  return { ok = true, items = items, n = #items, from = from, to = to, proposed_by = proposed_by,
           pending = proposed_by ~= nil or nil, ours_pending = ours_pending }
end

-- Diplomacy Overview "Current Deals" tab (diplocurrentdeals.lua PopulateDealChooser).
-- Stock loads each row into the scratch deal via UI.LoadCurrentDeal. That is the same object
-- propose_deal / incoming_deal use, so this refuses when the table already has items and
-- ClearItems afterwards so a leftover current-deal does not look like an incoming offer.
-- Never Add* / DoProposeDeal.
function H.current_deals(pid)
  if not UI or not UI.GetNumCurrentDeals or not UI.LoadCurrentDeal then
    return { ok = false, err = "current-deals UI unavailable", deals = {}, n = 0 }
  end
  local scratch = H.incoming_deal(pid)
  if (scratch.n or 0) > 0 then
    return { ok = false, err = "trade table is occupied; answer incoming_deal first", deals = {}, n = 0 }
  end
  local okn, n = pcall(function() return UI.GetNumCurrentDeals(pid) end)
  if not okn or type(n) ~= "number" or n <= 0 then
    return { ok = true, deals = {}, n = 0 }
  end
  local okd, deal = pcall(function() return UI.GetScratchDeal() end)
  if not okd or deal == nil then
    return { ok = false, err = "no scratch deal to snapshot current deals into", deals = {}, n = 0 }
  end
  local turn = Game and Game.GetGameTurn and Game.GetGameTurn() or 0
  local out = {}
  for i = 0, n - 1 do
    local okl = pcall(function() UI.LoadCurrentDeal(pid, i) end)
    if okl then
      local items = H.deal_items(deal, pid)
      local other
      pcall(function() other = deal:GetOtherPlayer(pid) end)
      local start_turn, duration
      pcall(function() start_turn = deal:GetStartTurn() end)
      pcall(function() duration = deal:GetDuration() end)
      local ends_on
      if type(start_turn) == "number" and type(duration) == "number" then
        ends_on = start_turn + duration
      end
      local civ
      if other and Players and Players[other] and Players[other].GetCivilizationShortDescription then
        local met = true
        if Teams and Players[pid] then
          pcall(function() met = Teams[Players[pid]:GetTeam()]:IsHasMet(Players[other]:GetTeam()) end)
        end
        if met then civ = Players[other]:GetCivilizationShortDescription() end
      end
      local e = { other = other, civ = civ, items = items, n = #items,
                  start_turn = start_turn, duration = duration, ends_on = ends_on }
      if ends_on then e.turns_left = ends_on - turn end
      out[#out + 1] = e
    end
  end
  if deal.ClearItems then pcall(function() deal:ClearItems() end) end
  return { ok = true, deals = out, n = #out }
end

-- Finalize an EXISTING scratch deal (AI/human offer already on the table).
-- Never Add* — that path crashed the process. Stock UI: tradelogic.lua
-- UI.DoFinalizePlayerDeal(them, us, true/false) for PvP accept/refuse.
function H.accept_deal(pid)
  local d = H.incoming_deal(pid)
  if not d.ok or (d.n or 0) == 0 then return { ok = false, err = "no incoming deal" } end
  local them = d.from
  if them == pid then them = d.to end
  if them == nil or them == pid then return { ok = false, err = "deal has no other player" } end
  if not UI or not UI.DoFinalizePlayerDeal then
    return { ok = false, err = "DoFinalizePlayerDeal unavailable" }
  end
  UI.DoFinalizePlayerDeal(them, pid, true)
  -- The stock screen hides itself after finalizing and its hide handler empties the scratch table;
  -- without that the accepted items lingered as a fresh "incoming deal" and current_deals refused
  -- with "trade table is occupied" (live 2026-09-24 t226, peace between two humans).
  H.clear_scratch_deal()
  return { ok = true, other = them }
end

function H.clear_scratch_deal()
  pcall(function()
    local deal = UI and UI.GetScratchDeal and UI.GetScratchDeal()
    if deal and deal.ClearItems then deal:ClearItems() end
  end)
end

function H.refuse_deal(pid)
  local d = H.incoming_deal(pid)
  if not d.ok or (d.n or 0) == 0 then return { ok = false, err = "no incoming deal" } end
  local them = d.from
  if them == pid then them = d.to end
  if them == nil or them == pid then return { ok = false, err = "deal has no other player" } end
  if not UI or not UI.DoFinalizePlayerDeal then
    return { ok = false, err = "DoFinalizePlayerDeal unavailable" }
  end
  UI.DoFinalizePlayerDeal(them, pid, false)
  H.clear_scratch_deal()
  return { ok = true, other = them }
end

-- What can currently go on a deal with `other`, using only IsPossibleToTradeItem.
-- Never Add*/ClearItems/DoProposeDeal. SetFromPlayer/SetToPlayer is required for
-- some item types to report correctly (live: lump GOLD stayed false until from/to
-- were set; GPT was already true). Skips DECLARATION_OF_FRIENDSHIP vs AI (native
-- crash) and PEACE_TREATY (AddPeaceTreaty crashed even when valid).
-- Peace on the trade table (GitLab #5). Neither stock screen has a Peace Treaty pocket button: tradelogic.lua
-- OnOpenPlayerDealScreen seeds TRADE_ITEM_PEACE_TREATY on BOTH sides itself when two humans at war open a table,
-- and after HUMAN_NEGOTIATE_PEACE the engine opens the AI's table with the same pair already on it (the "Deal can
-- already have items in it if, say, we're at war" comment in tradelogic.lua OnShowHide). What a human sees before
-- that is the leader screen's Negotiate Peace button (leaderheadroot.lua OnShowHide): hidden when CanChangeWarPeace
-- is false, greyed with TXT_KEY_DIPLO_NEGOTIATE_PEACE_BLOCKED_TT while GetNumTurnsLockedIntoWar > 0. `us`/`them`
-- are the engine's own IsPossibleToTradeItem(PEACE_TREATY) answers; `ok`/`note` is the whole gate, as the screen
-- shows it. Read-only; the headless AddPeaceTreaty crashed the game and is never called here.
function H.peace_catalog(deal, pid, other)
  if not (Players and Teams and TradeableItems) then return nil end
  local T = TradeableItems
  if not T.TRADE_ITEM_PEACE_TREATY then return nil end
  local usTeam, themTeam = Players[pid]:GetTeam(), Players[other]:GetTeam()
  local function try(f) local ok, v = pcall(f); if ok then return v end return nil end
  local at_war = try(function() return Teams[usTeam]:IsAtWar(themTeam) end) or false
  local length = try(function() return GameDefines.PEACE_TREATY_LENGTH end)
  local out = { at_war = at_war, duration = try(function() return Game.GetPeaceDuration() end) or length }
  if not at_war then
    out.ok, out.note = false, "not at war"
    return out
  end
  out.can_change_war_peace = try(function() return Teams[usTeam]:CanChangeWarPeace(themTeam) end)
  out.locked_turns = try(function() return Teams[usTeam]:GetNumTurnsLockedIntoWar(themTeam) end)
  out.us = try(function() return deal:IsPossibleToTradeItem(pid, other, T.TRADE_ITEM_PEACE_TREATY, length) end) and true or false
  out.them = try(function() return deal:IsPossibleToTradeItem(other, pid, T.TRADE_ITEM_PEACE_TREATY, length) end) and true or false
  local fixed = try(function()
    return Game.IsOption(GameOptionTypes.GAMEOPTION_ALWAYS_WAR) or Game.IsOption(GameOptionTypes.GAMEOPTION_NO_CHANGING_WAR_PEACE)
  end)
  if fixed then
    out.ok, out.note = false, "the game options do not allow changing war and peace"
  elseif out.can_change_war_peace == false then
    out.ok, out.note = false, "war and peace cannot be changed with this player"
  elseif (out.locked_turns or 0) > 0 then
    out.ok = false
    out.note = try(function() return Locale.ConvertTextKey("TXT_KEY_DIPLO_NEGOTIATE_PEACE_BLOCKED_TT", out.locked_turns) end)
               or ("locked into war for " .. out.locked_turns .. " more turns")
  elseif not (out.us and out.them) then
    out.ok, out.note = false, "the engine does not allow a peace treaty between these players right now"
  else
    out.ok = true
  end
  return out
end

function H.trade_catalog(other, pid)
  if Game.GetActivePlayer() ~= pid then return { ok = false, err = "this seat is not active" } end
  local o = Players[other]
  if not o or not o:IsAlive() then return { ok = false, err = "no such player" } end
  if o.IsMinorCiv and o:IsMinorCiv() then
    return { ok = false, err = "city-states are not trade-table deals; use city_state_gifts" }
  end
  local myTeam = Teams[Players[pid]:GetTeam()]
  if not myTeam:IsHasMet(o:GetTeam()) then return { ok = false, err = "have not met this player yet" } end
  if not UI or not UI.GetScratchDeal then return { ok = false, err = "scratch deal unavailable" } end
  local deal = UI.GetScratchDeal()
  if not deal then return { ok = false, err = "scratch deal unavailable" } end
  deal:SetFromPlayer(pid)
  deal:SetToPlayer(other)
  local duration = Game.GetDealDuration()
  local T = TradeableItems
  local function possible(from, to, typ, a, b)
    local ok, v = pcall(function()
      if b ~= nil then return deal:IsPossibleToTradeItem(from, to, typ, a, b) end
      if a ~= nil then return deal:IsPossibleToTradeItem(from, to, typ, a) end
      return deal:IsPossibleToTradeItem(from, to, typ)
    end)
    return ok and v and true or false
  end
  local function pair(typ, a, b)
    return {
      us = possible(pid, other, typ, a, b),
      them = possible(other, pid, typ, a, b),
    }
  end
  local resources = {}
  if GameInfo and GameInfo.Resources then
    for res in GameInfo.Resources() do
      if res and res.ID then
        local us = possible(pid, other, T.TRADE_ITEM_RESOURCES, res.ID, 1)
        local them = possible(other, pid, T.TRADE_ITEM_RESOURCES, res.ID, 1)
        if us or them then
          -- copies each side holds (the trade screen shows these numbers to a human), and a warning when
          -- the requested export is our only copy of a luxury: selling it costs the empire its happiness.
          -- The trade screen shows their count only for what they can trade us, and without imports
          -- (diplorelationships.lua:374-377 passes false); ours keeps imports for the last-copy check.
          local function avail(pl, withImports)
            local okc, v = pcall(function() return pl:GetNumResourceAvailable(res.ID, withImports) end)
            if okc and type(v) == "number" then return v end
            return nil
          end
          local entry = { resource = res.Type, us = us, them = them, class = res.ResourceClassType,
                          us_available = avail(Players[pid], true), them_available = them and avail(o, false) or nil }
          if us and res.ResourceClassType == "RESOURCECLASS_LUXURY" and entry.us_available == 1 then
            entry.last_copy = true
            entry.note = "our only copy: exporting it removes its happiness from the empire"
          end
          resources[#resources + 1] = entry
        end
      end
    end
  end
  -- Cities the deal would accept from each side: the exact IsPossibleToTradeItem(..., x, y) gate the
  -- trade screen's Pocket Cities list is built from. tradelogic's OnChooseCity -> deal:AddCityTrade is
  -- unconditional, so a city id that fails this gate must never reach it (v85).
  local function tradeable_cities(from, to)
    local out = {}
    local pl = Players[from]
    if pl and pl.Cities then
      for c in pl:Cities() do
        if c and possible(from, to, T.TRADE_ITEM_CITIES, c:GetX(), c:GetY()) then
          -- the trade screen lists the name; where the city is shows only once its plot is revealed to us
          -- the Pocket Cities list (tradelogic.lua) prints "name (pop)" for every entry, ours and theirs
          local seen = c:Plot():IsRevealed(Players[pid]:GetTeam(), false)
          local okp, pop = pcall(function() return c:GetPopulation() end)
          out[#out + 1] = { id = c:GetID(), name = c:GetName(), pop = okp and type(pop) == "number" and pop or nil,
                            x = seen and c:GetX() or nil, y = seen and c:GetY() or nil }
        end
      end
    end
    return out
  end
  local function num(f)
    local okn, v = pcall(f)
    if okn and type(v) == "number" then return v end
    return nil
  end
  local gold = pair(T.TRADE_ITEM_GOLD, 1)
  gold.us_available = num(function() return deal:GetGoldAvailable(pid, -1) end)
  gold.them_available = num(function() return deal:GetGoldAvailable(other, -1) end)
  -- Brave New World: a lump sum ("flat fee") is tradeable only under a Declaration of Friendship; gold
  -- per turn is not gated. The stock pocket just hides the Gold row (tradelogic.lua 1057 asks the same
  -- IsPossibleToTradeItem(..., TRADE_ITEM_GOLD, 1)); say why, since the rule is the game's own (engine-
  -- checked 2026-09-25: only the one friend among four met civs traded lump gold either way).
  if not (gold.us or gold.them) then
    local dof = false
    pcall(function() dof = Players[pid]:IsDoF(other) end)
    gold.declaration_of_friendship = dof and true or false
    if not dof then
      gold.note = "lump-sum gold needs a Declaration of Friendship with this civ (Brave New World rule); gold per turn does not"
    end
  end
  local gpt = pair(T.TRADE_ITEM_GOLD_PER_TURN, 1, duration)
  gpt.us_available = num(function() return Players[pid]:CalculateGoldRate() end)
  gpt.them_available = num(function() return o:CalculateGoldRate() end)
  return {
    ok = true, other = other, duration = duration,
    gold = gold,
    gold_per_turn = gpt,
    cities = { us = tradeable_cities(pid, other), them = tradeable_cities(other, pid) },
    open_borders = pair(T.TRADE_ITEM_OPEN_BORDERS, duration),
    embassy = pair(T.TRADE_ITEM_ALLOW_EMBASSY, duration),
    research_agreement = pair(T.TRADE_ITEM_RESEARCH_AGREEMENT, duration),
    defensive_pact = pair(T.TRADE_ITEM_DEFENSIVE_PACT, duration),
    at_war = myTeam:IsAtWar(o:GetTeam()) or false,
    -- the Negotiate Peace gate; the treaty itself is seeded on both sides of any table by the screens (GitLab #5)
    peace = H.peace_catalog and H.peace_catalog(deal, pid, other) or nil,
    resources = resources,
    -- the Other Players pocket (tradelogic.lua ShowOtherPlayerChooser), GitLab #6
    third_party = H.third_party_catalog and H.third_party_catalog(deal, pid, other) or nil,
    -- the Pocket Votes list (tradelogic.lua RefreshPocketVotes), GitLab #7
    vote_commitments = H.vote_commitment_catalog and H.vote_commitment_catalog(deal, pid, other) or {},
    -- the Votes pocket header: enabled by Player:CanCommitVote(other), tooltip GetCommitVoteDetails(other)
    -- (why not: no World Congress, not a member, in session, no proposals yet, no Spy as a Diplomat in
    -- the other capital, delegates already traded this session). Both directions, as the screen shows.
    votes = H.vote_gate and H.vote_gate(Players[pid], o) or nil,
  }
end

-- Third-party war / peace on the trade table (GitLab #6). The deal item names a TEAM; the screen's
-- Other Players pocket shows one leader button per met, living player of it. Same lookup here.
function H.third_party_player(team)
  if not (Players and GameDefines) then return nil end
  local max = GameDefines.MAX_CIV_PLAYERS or 63
  for p = 0, max - 1 do
    local pl = Players[p]
    if pl and pl:IsAlive() and pl:GetTeam() == team then
      local minor = pl.IsMinorCiv and pl:IsMinorCiv() or false
      local okn, name = pcall(function() return pl:GetName() end)
      return { other = p, other_name = okn and name or nil, minor = minor }
    end
  end
  return nil
end

-- tradelogic.lua ShowOtherPlayerChooser: every living player both sides have met (not us, not them)
-- is a button; IsPossibleToTradeItem(from, to, type, team) enables it, otherwise it is greyed with the
-- reason the screen puts in its tooltip. `ok` rows are what propose_deal will accept.
function H.third_party_catalog(deal, pid, other)
  if not (Players and Teams and GameDefines and TradeableItems) then return nil end
  local T = TradeableItems
  if not (T.TRADE_ITEM_THIRD_PARTY_WAR and T.TRADE_ITEM_THIRD_PARTY_PEACE) then return nil end
  local usTeam, themTeam = Players[pid]:GetTeam(), Players[other]:GetTeam()
  local function reason(from, loop, loopTeam, war)
    local fromTeam = Players[from]:GetTeam()
    local r
    pcall(function()
      if not war then
        if not Teams[loopTeam]:IsAtWar(fromTeam) then r = "TXT_KEY_DIPLO_NOT_AT_WAR"
        elseif loop:IsMinorCiv() then
          local ally = loop:GetAlly()
          if loop:IsMinorPermanentWar(from) then r = "TXT_KEY_DIPLO_MINOR_PERMANENT_WAR"
          elseif ally ~= -1 and Teams[Players[ally]:GetTeam()]:IsAtWar(fromTeam) then r = "TXT_KEY_DIPLO_MINOR_ALLY_AT_WAR" end
        else
          if not Players[from]:IsWillAcceptPeaceWithPlayer(loop:GetID()) then r = "TXT_KEY_DIPLO_MINOR_THIS_GUY_WANTS_WAR"
          elseif not loop:IsWillAcceptPeaceWithPlayer(from) then r = "TXT_KEY_DIPLO_MINOR_OTHER_GUY_WANTS_WAR" end
        end
      else
        if Teams[loopTeam]:IsAtWar(fromTeam) then r = "TXT_KEY_DIPLO_ALREADY_AT_WAR"
        elseif Teams[fromTeam]:IsForcePeace(loopTeam) then r = "TXT_KEY_DIPLO_FORCE_PEACE"
        elseif loop:IsMinorCiv() and loop:GetAlly() == from then r = "TXT_KEY_DIPLO_NO_WAR_ALLIES" end
      end
    end)
    if r and Locale and Locale.ConvertTextKey then
      local okl, txt = pcall(Locale.ConvertTextKey, r)
      if okl and type(txt) == "string" then return plain_text(txt) end
    end
    return r
  end
  local out = { war = { us = {}, them = {} }, peace = { us = {}, them = {} } }
  local max = GameDefines.MAX_CIV_PLAYERS or 63
  for p = 0, max - 1 do
    local pl = Players[p]
    if pl and p ~= pid and p ~= other and pl:IsAlive() then
      local t = pl:GetTeam()
      if t ~= usTeam and t ~= themTeam and Teams[usTeam]:IsHasMet(t) and Teams[themTeam]:IsHasMet(t) then
        local okn, name = pcall(function() return pl:GetName() end)
        local minor = pl.IsMinorCiv and pl:IsMinorCiv() or false
        for _, kind in ipairs({ { "war", T.TRADE_ITEM_THIRD_PARTY_WAR, true }, { "peace", T.TRADE_ITEM_THIRD_PARTY_PEACE, false } }) do
          for _, side in ipairs({ { "us", pid, other }, { "them", other, pid } }) do
            local okq, possible = pcall(function() return deal:IsPossibleToTradeItem(side[2], side[3], kind[2], t) end)
            possible = okq and possible and true or false
            local row = { player = p, team = t, name = okn and name or nil, minor = minor, ok = possible,
                          at_war_with_them = Teams[t]:IsAtWar(Players[side[2]]:GetTeam()) or false }
            if not possible then row.note = reason(side[2], pl, t, kind[3]) end
            local list = out[kind[1]][side[1]]
            list[#list + 1] = row
          end
        end
      end
    end
  end
  return out
end

function H.vote_gate(us, them)
  if not (us and them and us.CanCommitVote) then return nil end
  local function side(a, b)
    local okc, can = pcall(function() return a:CanCommitVote(b:GetID()) end)
    local okd, det = pcall(function() return a:GetCommitVoteDetails(b:GetID()) end)
    local r = { can = okc and can and true or false }
    if okd and type(det) == "string" and det ~= "" then r.note = plain_text(det) end
    return r
  end
  local u, t = side(us, them), side(them, us)
  return { us = u.can, us_note = u.note, them = t.can, them_note = t.note }
end
