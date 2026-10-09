-- Shared by earlier fragments (load order: harness/runtime_source.py MANIFEST).
local L, plain_text = H._ns.L, H._ns.plain_text

-- World Congress / League. ENDTURN_BLOCKING_LEAGUE_CALL_FOR_PROPOSALS is a HARD block, confirmed live
-- (2026-09-16, turn 213): unlike every other popup-shaped blocker in this file, merely opening+closing the
-- World's Fair / International Games / ISS. The production tooltip (infotooltipinclude.lua
-- GetHelpTextForProcess) is GetProjectDetails: percent complete, our hammers, reward text.
-- Other civs' contributions appear only on the completion popup (leagueprojectpopup.lua),
-- which names an unmet civ "unmet" but still prints their hammers. Until then, the split
-- is not on screen -- only the total percent -- so an active project does not list it.
local function league_hammers(x)
  return math.floor((tonumber(x) or 0) / 100)
end

local function league_tier_at(per_hammers, define)
  if not GameDefines or GameDefines[define] == nil then return nil end
  local v = tonumber(GameDefines[define])
  if not v then return nil end
  if v > 1 then v = v / 100 end   -- live Lua reports 0.5 and 1; the XML defines are 50 and 100
  return math.floor(per_hammers * v + 1e-6)
end

-- League Overview tooltips are the same strings the buttons show, with color and newline tags.
local function league_plain(s)
  return plain_text(s)
end

-- GetResolutionName embeds the choice's icon ("[ICON_RELIGION_TENGRIISM] Tengriism"). The screen
-- draws that as a picture; the tag itself is not a word. Same cleanup as the tooltip.
local function resolution_name(league, typ, id, decision)
  local name
  local ok = pcall(function()
    name = league:GetResolutionName(typ, id or -1, decision or -1, false)
  end)
  if not ok then return nil end
  return league_plain(name)
end

-- World Congress vote commitments on the trade table (GitLab #7). tradelogic.lua UpdateLeagueVotes
-- builds one pocket entry per (pending proposal, voter choice), enact and repeal; a deal item carries
-- data1 = resolution id, data2 = the voter's choice, data3 = the votes committed (the committing side's
-- GetCoreVotesForMember), flag1 = repeal. The screen labels each with GetResolutionName(type, id,
-- proposer's choice) and GetTextForChoice(voter decision, choice); these rows carry the same words.
local function active_league()
  if not (Game and Game.GetNumActiveLeagues and Game.GetActiveLeague) then return nil end
  local ok, league = pcall(function()
    if Game.GetNumActiveLeagues() > 0 then return Game.GetActiveLeague() end
    return nil
  end)
  if ok then return league end
  return nil
end

local function league_vote_list(league)
  local list = {}
  local function add(props, repeal)
    for _, t in ipairs(props or {}) do
      local info = GameInfo.Resolutions[t.Type]
      local d
      if repeal then
        d = GameInfo.ResolutionDecisions["RESOLUTION_DECISION_REPEAL"]
      else
        d = info and GameInfo.ResolutionDecisions[info.VoterDecision] or nil
      end
      if d and d.ID then
        for _, choice in ipairs(league:GetChoicesForDecision(d.ID) or {}) do
          list[#list + 1] = { type = t.Type, resolution_type = info and info.Type or nil, decision = d.ID, id = t.ID,
                              proposer_choice = t.ProposerDecision, choice = choice, repeal = repeal }
        end
      end
    end
  end
  pcall(function() add(league:GetEnactProposals(), false) end)
  pcall(function() add(league:GetRepealProposals(), true) end)
  return list
end

local function vote_row(league, v)
  local row = { resolution_id = v.id, resolution_type = v.resolution_type, choice_id = v.choice,
                direction = v.repeal and "repeal" or "enact", repeal = v.repeal,
                name = resolution_name(league, v.type, v.id, v.proposer_choice) }
  local okc, txt = pcall(function() return league:GetTextForChoice(v.decision, v.choice) end)
  if okc and type(txt) == "string" then row.choice = league_plain(txt) end
  return row
end

-- The words the deal screen prints for one commitment, or nil when the league no longer lists it.
function H.describe_vote_commitment(id, choice, repeal)
  local league = active_league()
  if not league then return nil end
  for _, v in ipairs(league_vote_list(league)) do
    if v.id == id and v.choice == choice and v.repeal == (repeal and true or false) then return vote_row(league, v) end
  end
  return nil
end

-- Pocket Votes: every (proposal, choice) either side may commit right now, with the votes it would
-- commit (RefreshPocketVotes' IsPossibleToTradeItem gate, both directions).
function H.vote_commitment_catalog(deal, pid, other)
  local league = active_league()
  if not league or not (TradeableItems and TradeableItems.TRADE_ITEM_VOTE_COMMITMENT) then return {} end
  local T = TradeableItems.TRADE_ITEM_VOTE_COMMITMENT
  local function votes(p)
    local ok, n = pcall(function() return league:GetCoreVotesForMember(p) end)
    if ok and type(n) == "number" then return n end
    return 0
  end
  local vu, vt = votes(pid), votes(other)
  local out = {}
  for _, v in ipairs(league_vote_list(league)) do
    local function possible(from, to, n)
      local ok, r = pcall(function() return deal:IsPossibleToTradeItem(from, to, T, v.id, v.choice, n, v.repeal) end)
      return ok and r and true or false
    end
    local us, them = possible(pid, other, vu), possible(other, pid, vt)
    if us or them then
      local row = vote_row(league, v)
      row.us, row.them, row.votes_us, row.votes_them = us, them, vu, vt
      out[#out + 1] = row
    end
  end
  return out
end

local function resolution_details(league, typ, pid, id, decision)
  local text
  local ok = pcall(function()
    text = league:GetResolutionDetails(typ, pid, id or -1, decision or -1)
  end)
  if not ok then return nil end
  return league_plain(text)
end

function H.league_projects(pid)
  if not (Game and Game.GetNumActiveLeagues and Game.GetActiveLeague and GameInfo and GameInfo.LeagueProjects) then
    return {}
  end
  local ok, n = pcall(function() return Game.GetNumActiveLeagues() end)
  if not ok or not n or n == 0 then return {} end
  local league = Game.GetActiveLeague()
  if not league then return {} end
  local me = Players and Players[pid]
  local myTeam = me and Teams and Teams[me:GetTeam()] or nil
  local max_maj = (GameDefines and GameDefines.MAX_MAJOR_CIVS) or 22
  local projects = {}
  for t in GameInfo.LeagueProjects() do
    if t and t.ID then
      local active, complete = false, false
      pcall(function() active = league:IsProjectActive(t.ID) and true or false end)
      pcall(function() complete = league:IsProjectComplete(t.ID) and true or false end)
      if active or complete then
        local cost, per = 0, 0
        pcall(function() cost = league:GetProjectCost(t.ID) or 0 end)
        pcall(function() per = league:GetProjectCostPerPlayer(t.ID) or 0 end)
        local total_x100, contributors = 0, {}
        for i = 0, max_maj - 1 do
          local q = Players and Players[i]
          if q and not (q.IsMinorCiv and q:IsMinorCiv()) then
            local c, tier = 0, 0
            pcall(function() c = league:GetMemberContribution(i, t.ID) or 0 end)
            total_x100 = total_x100 + c
            local alive = (not q.IsAlive) or q:IsAlive()
            local member = false
            pcall(function() member = league:IsMember(i) and true or false end)
            if complete and alive and member then
              pcall(function() tier = league:GetMemberContributionTier(i, t.ID) or 0 end)
              local met = i == pid or (myTeam and myTeam:IsHasMet(q:GetTeam()))
              local row = { contribution = league_hammers(c), tier = tier }
              if met then
                row.player = i
                row.civ = q.GetCivilizationShortDescription and q:GetCivilizationShortDescription() or nil
                if i == pid then row.you = true end
              else
                row.civ = "unknown"
              end
              contributors[#contributors + 1] = row
            end
          end
        end
        table.sort(contributors, function(a, b)
          if a.tier ~= b.tier then return a.tier > b.tier end
          return a.contribution > b.contribution
        end)
        local our, our_tier, details = 0, 0, nil
        pcall(function() our = league:GetMemberContribution(pid, t.ID) or 0 end)
        pcall(function() our_tier = league:GetMemberContributionTier(pid, t.ID) or 0 end)
        -- Two-arg form is the production tooltip (percent, our hammers, rewards).
        pcall(function() details = league:GetProjectDetails(t.ID, pid) end)
        local rewards = {}
        for tier_n = 1, 3 do
          local text
          pcall(function() text = league:GetProjectRewardTierDetails(tier_n, t.ID) end)
          if text and text ~= "" then rewards[#rewards + 1] = { tier = tier_n, text = text } end
        end
        local per_h = league_hammers(per)
        local percent = (cost > 0) and math.floor(100 * total_x100 / cost) or 0
        local name = t.Description and L(t.Description) or nil
        if name == "" or name == t.Description then name = nil end
        local row = {
          project = t.Type, name = name, process = t.Process,
          active = active, complete = complete,
          progress_percent = percent,
          cost = league_hammers(cost), cost_per_player = per_h,
          our_contribution = league_hammers(our), our_tier = our_tier,
          tier_1_at = league_tier_at(per_h, "LEAGUE_PROJECT_REWARD_TIER_1_THRESHOLD"),
          tier_2_at = league_tier_at(per_h, "LEAGUE_PROJECT_REWARD_TIER_2_THRESHOLD"),
          details = details, rewards = rewards,
        }
        if complete then row.contributors = contributors end
        projects[#projects + 1] = row
      end
    end
  end
  return projects
end

-- LeagueOverview popup (Events.SerialEventGameMessagePopup + OnClose(), the same trick that clears
-- TechPopup/discussion/greeting popups) does NOT clear it -- only a real Network.SendLeagueProposeEnact/
-- Repeal call does, the same shape as leagueoverview.lua's ProposalController:CommitProposals. Confirmed
-- `league:CanPropose(pid)`/`CanProposeEnactAnyChoice(type, pid)` already fold in the remaining-proposal-count
-- check (both flip to false once GetRemainingProposalsForMember hits 0), so no extra gating is needed here.
-- ENDTURN_BLOCKING_LEAGUE_CALL_FOR_VOTES needs the equivalent real Network.SendLeagueVoteEnact/Repeal/
-- Abstain call (VoteController:CommitVotes) by the same logic, and that too is confirmed live (turn 243,
-- First Rio de Janeiro Conference): casting the session's single available vote cleared the blocker in the
-- same call, blocking_name back to NO_ENDTURN_BLOCKING_TYPE. See Game.league_cast_votes in game.py for the
-- t315 row-shape trap (`votes` instead of `num_votes` silently abstained four delegates).
function H.league_status(pid)
  if Game.GetNumActiveLeagues() == 0 then return { has_league = false } end
  local league = Game.GetActiveLeague()
  if not league then return { has_league = false } end
  local in_session = league:IsInSession()
  local out = {
    has_league = true, league_id = league:GetID(), name = league:GetName(), in_session = in_session,
    remaining_proposals = league:GetRemainingProposalsForMember(pid), can_propose = league:CanPropose(pid),
    projects = H.league_projects(pid),
  }
  -- v265: a special session (a host change when civs reach a new era) votes on that alone; the proposals the
  -- "will convene in N turns" notice named wait for the regular session (live 2026-10-08, England t123: the
  -- Choose Host vote came one turn before the Embargo England vote, and the read listed only the host).
  local ok, special = pcall(function() return league:IsInSpecialSession() end)
  if ok and special ~= nil then out.special_session = special and true or false end
  local ok2, until_session = pcall(function() return league:GetTurnsUntilSession() end)
  if ok2 and type(until_session) == "number" then out.turns_until_session = until_session end
  if in_session and out.special_session then
    out.note = "a special session: only the host choice is voted on now; the regular session with the proposed " ..
               "resolutions follows (turns_until_session)"
  end
  -- The League Overview's member column (leagueoverview.lua: CalculateStartingVotesForMember, or remaining +
  -- spent while in session; host first) and the Victory Progress screen's diplomatic line
  -- (Game.GetVotesNeededForDiploVictory, turns until the World Leader session once the UN is active).
  -- Hover text is GetMemberDetails. An unmet member stays "unknown" with no tooltip: that string names them.
  local function met_player(i)
    if i == pid then return true end
    local q = Players and Players[i]
    if not q then return false end
    local ok, has = pcall(function() return Teams[Players[pid]:GetTeam()]:IsHasMet(q:GetTeam()) end)
    return ok and has and true or false
  end
  local function proposer_of(i)
    local extra = {}
    if type(i) ~= "number" or i < 0 then return extra end
    local q = Players and Players[i]
    if met_player(i) and q then
      extra.proposer = i
      extra.proposer_civ = q.GetCivilizationShortDescription and q:GetCivilizationShortDescription() or nil
      if i == pid then extra.proposer_you = true end
    else
      extra.proposer_civ = "unknown"
    end
    return extra
  end
  pcall(function()
    local summary = league:GetCurrentEffectsSummary()
    local effects = {}
    if type(summary) == "table" then
      for _, line in ipairs(summary) do
        local plain = league_plain(line)
        if plain then effects[#effects + 1] = plain end
      end
    else
      local plain = league_plain(summary)
      if plain then effects[1] = plain end
    end
    if #effects > 0 then out.active_effects = effects end
  end)
  pcall(function()
    local host, members = league:GetHostMember(), {}
    local myTeam = Teams[Players[pid]:GetTeam()]
    for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
      local q = Players[i]
      if q and q:IsAlive() and not q:IsMinorCiv() and league:IsMember(i) then
        local votes = league:CalculateStartingVotesForMember(i)
        if in_session then votes = league:GetRemainingVotesForMember(i) + league:GetSpentVotesForMember(i) end
        local met = i == pid or myTeam:IsHasMet(q:GetTeam())
        local row = { player = met and i or nil, civ = met and q:GetCivilizationShortDescription() or "unknown",
                      delegates = votes, host = (i == host) or nil, you = (i == pid) or nil }
        if met then
          local tip
          pcall(function() tip = league:GetMemberDetails(i, pid) end)
          row.details = league_plain(tip)
        end
        members[#members + 1] = row
      end
    end
    table.sort(members, function(a, b) return a.delegates > b.delegates end)
    out.members = members
    out.votes_needed_for_diplo_victory = Game.GetVotesNeededForDiploVictory()
    if Game.IsUnitedNationsActive() then
      local t = league:GetTurnsUntilVictorySession()
      if t and t < 999 then out.turns_until_world_leader_vote = t end  -- 999 (live t394) = none scheduled yet
    end
  end)
  -- Every active resolution, including ones this seat cannot repeal. The propose popup lists those in grey
  -- with the same GetResolutionDetails tooltip.
  pcall(function()
    local rows = {}
    for _, t in ipairs(league:GetActiveResolutions()) do
      local info = GameInfo.Resolutions[t.Type]
      local decision = t.ProposerDecision or -1
      local can = false
      pcall(function() can = league:CanProposeRepeal(t.ID, pid) and true or false end)
      local row = {
        resolution_id = t.ID,
        resolution_type = info and info.Type or nil,
        name = resolution_name(league, t.Type, t.ID, decision),
        details = resolution_details(league, t.Type, pid, t.ID, decision),
      }
      if can then row.can_repeal = true end
      rows[#rows + 1] = row
    end
    if #rows > 0 then out.active_resolutions = rows end
  end)
  if not in_session then
    out.turns_until_session = league:GetTurnsUntilSession()
    local enactable, unavailable = {}, {}
    for _, t in ipairs(league:GetInactiveResolutions()) do
      local info = GameInfo.Resolutions[t.Type]
      local name = resolution_name(league, t.Type, -1, -1)
      local details = resolution_details(league, t.Type, pid, -1, -1)
      if league:CanProposeEnactAnyChoice(t.Type, pid) then
        local choices = nil
        if info.ProposerDecision ~= "RESOLUTION_DECISION_NONE" then
          choices = {}
          local decisionId = GameInfo.ResolutionDecisions[info.ProposerDecision].ID
          for _, cid in ipairs(league:GetChoicesForDecision(decisionId, pid)) do
            local choice = { id = cid, text = league_plain(league:GetTextForChoice(decisionId, cid)),
              disabled = not league:CanProposeEnact(t.Type, pid, cid) }
            choice.details = resolution_details(league, t.Type, pid, -1, cid)
            choices[#choices + 1] = choice
          end
        end
        enactable[#enactable + 1] = { resolution_type = info.Type, name = name, details = details, choices = choices }
      else
        unavailable[#unavailable + 1] = { resolution_type = info and info.Type or nil, name = name, details = details }
      end
    end
    out.proposable_enact = enactable
    if #unavailable > 0 then out.unavailable_enact = unavailable end
    local repealable = {}
    for _, t in ipairs(league:GetActiveResolutions()) do
      if league:CanProposeRepeal(t.ID, pid) then
        local decision = t.ProposerDecision or -1
        repealable[#repealable + 1] = { resolution_id = t.ID, resolution_type = GameInfo.Resolutions[t.Type].Type,
          name = resolution_name(league, t.Type, t.ID, decision),
          details = resolution_details(league, t.Type, pid, t.ID, decision) }
      end
    end
    out.proposable_repeal = repealable
    -- What is already on the table for the next session (the League screen lists these, including grey
    -- "on hold" rows; live t329 a successful proposal came back as a bare ok:true with nothing to read
    -- it back from). An unmet proposer is "unknown" -- the player id would name a civ this seat has not met.
    local pending = {}
    local function push_proposal(v, direction, held)
      local info = GameInfo.Resolutions[v.Type]
      local decision = v.ProposerDecision or -1
      local row = {
        direction = direction,
        resolution_type = info.Type,
        name = resolution_name(league, v.Type, v.ID, decision),
        details = resolution_details(league, v.Type, pid, v.ID, decision),
      }
      row.resolution_id = v.ID  -- repeal proposals and vote commitments (GitLab #7) both address it
      if held then row.on_hold = true end
      for k, val in pairs(proposer_of(v.ProposalPlayer)) do row[k] = val end
      pending[#pending + 1] = row
    end
    local ok = pcall(function()
      for _, v in ipairs(league:GetEnactProposals()) do push_proposal(v, "enact", false) end
      for _, v in ipairs(league:GetRepealProposals()) do push_proposal(v, "repeal", false) end
    end)
    if ok then
      pcall(function()
        if league.GetEnactProposalsOnHold then
          for _, v in ipairs(league:GetEnactProposalsOnHold()) do push_proposal(v, "enact", true) end
        end
        if league.GetRepealProposalsOnHold then
          for _, v in ipairs(league:GetRepealProposalsOnHold()) do push_proposal(v, "repeal", true) end
        end
      end)
      out.pending_proposals = pending
    end
  else
    out.remaining_votes = league:GetRemainingVotesForMember(pid)
    local votes = {}
    local addProposal = function(v, direction)
      local info = GameInfo.Resolutions[v.Type]
      local decision = v.ProposerDecision or -1
      local choices = nil
      if info.VoterDecision ~= "RESOLUTION_DECISION_YES_OR_NO" then
        choices = {}
        local decisionId = GameInfo.ResolutionDecisions[info.VoterDecision].ID
        for _, cid in ipairs(league:GetChoicesForDecision(decisionId, pid)) do
          local choice = { id = cid, text = league_plain(league:GetTextForChoice(decisionId, cid)) }
          choice.details = resolution_details(league, v.Type, pid, v.ID, cid)
          choices[#choices + 1] = choice
        end
      end
      local row = { resolution_id = v.ID, resolution_type = info.Type, direction = direction,
        name = resolution_name(league, v.Type, v.ID, decision),
        details = resolution_details(league, v.Type, pid, v.ID, decision),
        choices = choices, yes_no = choices == nil or nil }
      for k, val in pairs(proposer_of(v.ProposalPlayer)) do row[k] = val end
      -- A luxury ban names its resource (the proposer's decision); say whether we own it, as the top bar
      -- would (live t448: "Ban Luxury: Wine" needed a raw query to learn we had none).
      if info.ProposerDecision == "RESOLUTION_DECISION_ANY_LUXURY_RESOURCE" and decision >= 0 then
        local res = GameInfo.Resources[v.ProposerDecision]
        if res then
          row.resource = res.Type
          row.us_have = Players[pid]:GetNumResourceTotal(res.ID, true)
        end
      end
      votes[#votes + 1] = row
    end
    for _, v in ipairs(league:GetEnactProposals()) do addProposal(v, "enact") end
    for _, v in ipairs(league:GetRepealProposals()) do addProposal(v, "repeal") end
    out.votable = votes
  end
  return out
end

function H.league_propose_enact(resolution_type, choice, pid)
  local id = GameInfoTypes[resolution_type]
  if id == nil then return { ok = false, err = "unknown resolution " .. tostring(resolution_type) } end
  local league = Game.GetActiveLeague()
  if not league then return { ok = false, err = "no active league" } end
  local info = GameInfo.Resolutions[id]
  local c = choice or -1
  if info.ProposerDecision ~= "RESOLUTION_DECISION_NONE" and c == -1 then
    return { ok = false, err = "this resolution requires a choice -- see league_status()'s choices list" }
  end
  if not league:CanProposeEnactAnyChoice(id, pid) then return { ok = false, err = "cannot propose this resolution right now" } end
  if c ~= -1 and not league:CanProposeEnact(id, pid, c) then return { ok = false, err = "cannot propose this specific choice" } end
  Network.SendLeagueProposeEnact(league:GetID(), id, pid, c)
  return { ok = true }
end

function H.league_propose_repeal(resolution_id, pid)
  local league = Game.GetActiveLeague()
  if not league then return { ok = false, err = "no active league" } end
  if not league:CanProposeRepeal(resolution_id, pid) then return { ok = false, err = "cannot propose repeal of this resolution" } end
  Network.SendLeagueProposeRepeal(league:GetID(), resolution_id, pid)
  return { ok = true }
end

-- votes: array of { resolution_id, direction = "enact"|"repeal", choice (optional, default kChoiceNone),
-- num_votes }. Any votes left over after these (GetRemainingVotesForMember - sum(num_votes)) are sent as an
-- explicit abstain, matching VoteController:CommitVotes's own always-abstain-the-remainder behaviour.
function H.league_cast_votes(votes, pid)
  local league = Game.GetActiveLeague()
  if not league then return { ok = false, err = "no active league" } end
  -- Network.SendLeagueVoteEnact/Repeal do NOT validate server-side that a session is actually in progress --
  -- confirmed live (2026-09-16): calling this out-of-session against a nonexistent resolution_id came back
  -- {ok:true, votes_cast:1} with no error and no visible effect, the same "accepted but silently wrong"
  -- shape as the MISSION_BUILD/trade-route bugs documented elsewhere in this file. Gate on IsInSession()
  -- ourselves rather than trusting the network call to reject it.
  if not league:IsInSession() then return { ok = false, err = "no World Congress session is in progress right now" } end
  local remaining = league:GetRemainingVotesForMember(pid)
  local spent = 0
  for _, v in ipairs(votes) do
    local n = v.num_votes or 0
    if n > 0 then
      local choice = v.choice or -1
      if v.direction == "enact" then
        Network.SendLeagueVoteEnact(league:GetID(), v.resolution_id, pid, n, choice)
      elseif v.direction == "repeal" then
        Network.SendLeagueVoteRepeal(league:GetID(), v.resolution_id, pid, n, choice)
      else
        return { ok = false, err = "direction must be 'enact' or 'repeal'" }
      end
      spent = spent + n
    end
  end
  local leftover = remaining - spent
  if leftover > 0 then Network.SendLeagueVoteAbstain(league:GetID(), pid, leftover) end
  return { ok = true, votes_cast = spent, abstained = leftover > 0 and leftover or 0 }
end

-- Shared with later fragments, which import these at their top (load order: harness/runtime_source.py MANIFEST).
H._ns.league_plain = league_plain
