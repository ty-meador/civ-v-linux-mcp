function H.approach_name(v) return H.enum_name("MajorCivApproachTypes", MajorCivApproachTypes, v) end
-- Relationship between `pid` and major civ `other`, plus `other`'s public standing with everyone `pid` has
-- met. Everything here is what the in-game Diplomacy overview / leader tooltip already shows a human:
-- GetApproachTowardsUsGuess + GetOpinionTable are the visible guess, not the AI's hidden true approach.
function H.relationship(pid, other)
  local p, o = Players[pid], Players[other]
  if not (p and o and o:IsAlive()) then return { ok = false, err = "no such player" } end
  local myTeam, oTeam = Teams[p:GetTeam()], Teams[o:GetTeam()]
  if not myTeam:IsHasMet(o:GetTeam()) then return { ok = false, err = "not met" } end
  local function try(f, ...) local ok, v = pcall(f, ...); if ok then return v end return nil end
  local out = {
    ok = true, player = other, civ = o:GetCivilizationShortDescription(), leader = o:GetName(),
    minor = o:IsMinorCiv() or false, at_war = myTeam:IsAtWar(o:GetTeam()) or false,
    turns_locked_in_war = try(function() return myTeam:GetNumTurnsLockedIntoWar(o:GetTeam()) end),
  }
  if out.minor then
    out.friends = try(function() return o:IsFriends(pid) end)
    out.allied = try(function() return o:IsAllies(pid) end)
    out.influence = try(function() return o:GetMinorCivFriendshipWithMajor(pid) end)
    -- The ally is named only when we have met it (citystatestatushelper.lua: TXT_KEY_CITY_STATE_ALLY_UNKNOWN_TT).
    local ally = try(function() return o:GetAlly() end)
    if ally and ally >= 0 and ally ~= pid and not myTeam:IsHasMet(Players[ally]:GetTeam()) then
      out.ally_of, out.ally_unknown = nil, true
    else
      out.ally_of = ally
    end
    return out
  end
  -- A human seat has no AI approach or opinion: the stock diplomacy list blanks the status tooltip for a
  -- human (diplolist.lua: `IsHuman() ... SetToolTipString(" ")`) and only asks GetApproachTowardsUsGuess /
  -- GetOpinionTable of an AI. The engine still answers for a human (live 2026-09-24, two-human hotseat:
  -- "They have some early concerns about your warmongering" attributed to the other human), so gate here.
  out.human = try(function() return o:IsHuman() end) or false
  if not out.human then
    out.approach_guess = H.approach_name(try(function() return p:GetApproachTowardsUsGuess(other) end))
  end
  out.declaration_of_friendship = try(function() return p:IsDoF(other) end) or false
  if out.declaration_of_friendship then
    out.dof_turns_left = try(function() return GameDefines.DOF_EXPIRATION_TIME - p:GetDoFCounter(other) end)
  end
  out.they_denounced_us = try(function() return o:IsDenouncedPlayer(pid) end) or false
  out.we_denounced_them = try(function() return p:IsDenouncedPlayer(other) end) or false
  out.our_embassy_with_them = try(function() return oTeam:HasEmbassyAtTeam(p:GetTeam()) end)
  out.their_embassy_with_us = try(function() return myTeam:HasEmbassyAtTeam(o:GetTeam()) end)
  out.open_borders_we_have = try(function() return myTeam:IsAllowsOpenBordersToTeam(o:GetTeam()) end)
  out.open_borders_they_have = try(function() return oTeam:IsAllowsOpenBordersToTeam(p:GetTeam()) end)
  out.research_agreement = try(function() return myTeam:IsHasResearchAgreement(o:GetTeam()) end) or false
  out.defensive_pact = try(function() return myTeam:IsHasDefensivePact(o:GetTeam()) end) or false
  out.wars_fought = try(function() return p:GetNumWarsFought(other) end)
  out.opinion = {}
  local t = (not out.human) and try(function() return o:GetOpinionTable(pid) end) or nil
  if type(t) == "table" then for _, v in ipairs(t) do out.opinion[#out.opinion + 1] = tostring(v) end end
  -- Their public standing with every other civ we have met (visible in the Diplomacy overview).
  out.relations = {}
  local last = (GameDefines.MAX_CIV_PLAYERS or GameDefines.MAX_MAJOR_CIVS) - 1
  for third = 0, last do
    if third ~= other and third ~= pid then
      local q = Players[third]
      if q and q:IsAlive() and myTeam:IsHasMet(q:GetTeam()) and oTeam:IsHasMet(q:GetTeam()) then
        local e = { player = third, civ = q:GetCivilizationShortDescription(), at_war = oTeam:IsAtWar(q:GetTeam()) or false }
        if q:IsMinorCiv() then
          e.minor = true
          -- Global Relations (diploglobalrelationships.lua:281) shows a third party's city-state ALLIANCES
          -- only; friendship (30+ influence) is shown nowhere, so it is not read (audit t341).
          e.allied = try(function() return q:IsAllies(other) end)
          if e.at_war or e.allied then out.relations[#out.relations + 1] = e end
        else
          e.declaration_of_friendship = try(function() return o:IsDoF(third) end) or false
          e.they_denounced = try(function() return o:IsDenouncedPlayer(third) end) or false
          e.denounced_them = try(function() return q:IsDenouncedPlayer(other) end) or false
          out.relations[#out.relations + 1] = e
        end
      end
    end
  end
  -- Discuss-screen buttons a human would see (discussiondialog.lua). stop_spreading_religion
  -- is the ask-them-to-stop row, gated on conversion points from our cities (live t179: Ethiopian
  -- missionary on our lumbermill after Machu flipped).
  local spies = try(function() return o:GetEspionageSpies() end)
  out.discuss = {
    share_intrigue = try(function() return p:HasRecentIntrigueAbout(other) end) or false,
    stop_spreading_religion = ((try(function() return p:GetNegativeReligiousConversionPoints(other) end) or 0) > 0)
      and not (try(function() return o:IsAskedToStopConverting(pid) end) or false),
    stop_spying = (not (try(function() return o:IsStopSpyingMessageTooSoon(pid) end) or false))
      and type(spies) == "table" and #spies > 0,
    dont_settle = not (try(function() return o:IsDontSettleMessageTooSoon(pid) end) or false),
    stop_digging = ((try(function() return p:GetNegativeArchaeologyPoints(other) end) or 0) > 0)
      and not (try(function() return o:IsAskedToStopDigging(pid) end) or false),
    declare_friendship = not out.declaration_of_friendship
      and not (try(function() return o:IsDoFMessageTooSoon(pid) end) or false),
  }
  -- What they have said to us lately (the AILeaderMessage hook, newest last).
  out.history = {}
  for i = #H.events, 1, -1 do
    local e = H.events[i]
    if e.kind == "leader_message" and e.audience == pid and e.data.player == other then
      table.insert(out.history, 1, { turn = e.turn, state = e.data.state, text = e.data.text })
      if #out.history >= 12 then break end
    end
  end
  return out
end
