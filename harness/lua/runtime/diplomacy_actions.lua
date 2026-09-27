function H.diplomacy(pid)
  local p = Players[pid]
  local myTeam = Teams[p:GetTeam()]
  local out = {}
  local last = (GameDefines.MAX_CIV_PLAYERS or GameDefines.MAX_MAJOR_CIVS) - 1
  for other = 0, last do
    if other ~= pid then
      local o = Players[other]
      if o and o:IsAlive() and o:IsEverAlive() and myTeam:IsHasMet(o:GetTeam()) then
        local minor = o.IsMinorCiv and o:IsMinorCiv() or false
        local e = {
          id = other, civ = o:GetCivilizationShortDescription(), leader = o:GetName(),
          human = o:IsHuman(), met = true, at_war = myTeam:IsAtWar(o:GetTeam()) or false,
        }
        if minor then
          e.minor = true
          local ok, allied = pcall(function() return o:IsAllies(pid) end)
          if ok then e.allied = allied end
          local ok2, friends = pcall(function() return o:IsFriends(pid) end)
          if ok2 then e.friends = friends end
          -- What befriending it buys (the city-state screen's own info): trait + influence.
          pcall(function()
            local tr = GameInfo.MinorCivTraits[o:GetMinorCivTrait()]
            if tr then e.trait = short(tr.Type) end  -- CULTURED / MARITIME / MERCANTILE / MILITARISTIC / RELIGIOUS
            e.influence = o:GetMinorCivFriendshipWithMajor(pid)
          end)
          -- The influence tooltip's own per-turn change (citystatestatushelper.lua:230). With it, say when
          -- the status lapses: live t352 the Monaco alliance (7 Oil, +13 culture, happiness) ran out at 59/60
          -- with nothing in any read warning it was one turn away.
          pcall(function()
            local chg = o:GetFriendshipChangePerTurnTimes100(pid) / 100
            e.influence_per_turn = chg
            if chg < 0 and e.influence then
              local lim = e.allied and (GameDefines.FRIENDSHIP_THRESHOLD_ALLIES or 60)
                          or (e.friends and (GameDefines.FRIENDSHIP_THRESHOLD_FRIENDS or 30)) or nil
              if lim then e.turns_until_status_lost = math.floor((e.influence - lim) / -chg) + 1 end
            end
          end)
        else
          e.score = o:GetScore()
        end
        -- Where it is, as the map shows it: the capital's plot once revealed (live t409: finding Quebec City
        -- for a missionary quest took a raw query).
        pcall(function()
          local cap = o:GetCapitalCity()
          if cap and cap:Plot():IsRevealed(p:GetTeam(), false) then e.capital = { name = cap:GetName(), x = cap:GetX(), y = cap:GetY() } end
        end)
        out[#out + 1] = e
      end
    end
  end
  return out
end

-- Reverse lookup for an enum table (DiploUIStateTypes, EndTurnBlockingTypes, GameStateTypes, ...), built
-- lazily and cached under `cache_key`. NOTE: `_G` does not exist in this Lua environment (Civ5's UI
-- contexts run under a custom sandboxed environment, not the standard Lua globals table -- confirmed live:
-- `type(_G) == "nil"` in InGame), so the enum TABLE must be passed directly by each caller below rather
-- than looked up by name string; an earlier version of this function tried `_G[name]` and silently
-- returned every value unresolved (the pcall failed, indexing a nil `_G`) -- caught live, not in review.
H._enum_names = H._enum_names or {}
function H.enum_name(cache_key, enum_table, v)
  local cache = H._enum_names[cache_key]
  if not cache then
    local ok, names = pcall(function()
      local t = {}
      for k, id in pairs(enum_table) do t[id] = k end
      return t
    end)
    cache = ok and names or {}
    H._enum_names[cache_key] = cache
  end
  return cache[v] or v
end

function H.diplo_state_name(v) return H.enum_name("DiploUIStateTypes", DiploUIStateTypes, v) end
function H.blocking_name(v) return H.enum_name("EndTurnBlockingTypes", EndTurnBlockingTypes, v) end
-- NOTE: Game.GetGameState() pairs with the global GameplayGameStateTypes (GAMESTATE_ON/_EXTENDED/_OVER),
-- NOT the differently-named global GameStateTypes (a separate, real enum -- the UI's screen/view state
-- machine: CIV5_GS_EXIT/MAIN_MENU/MAINGAMEVIEW/...). An earlier version of this file used the wrong one
-- (a grep for the enum name had no left boundary and silently matched the tail of the longer
-- "GameplayGameStateTypes" identifier), so game_state_name/game_over always compared against a nil field
-- and game_over was silently always false -- caught live, not in review.
function H.game_state_name(v) return H.enum_name("GameplayGameStateTypes", GameplayGameStateTypes, v) end

-- Fire a diplomatic event directly on the engine, bypassing the leader-head/discussion UI entirely.
-- `event_name` is the FromUIDiploEventTypes key with or without its FROM_UI_DIPLO_EVENT_ prefix.
-- See docs/NOTES.md for the full enum and which files call each one (from static analysis of the
-- game's own Lua).
--
-- War/peace gating (v12, tightened v13 -- see NOTES.md): leaderheadroot.lua's OnShowHide never even shows
-- the war/peace button unless `pActiveTeam:CanChangeWarPeace(otherTeam)`, and OnWarOrPeace itself branches
-- on `IsAtWar(otherTeam)` first -- at war fires NEGOTIATE_PEACE, at peace opens the declare-war popup --
-- so the two events are mutually exclusive by current war state, not just by their own separate gates.
-- The leaderhead screen this all lives on also cannot open at all without `IsHasMet(otherTeam)` first.
-- v12 mirrored `CanChangeWarPeace` plus each direction's own gate (`GetNumTurnsLockedIntoWar(otherTeam) > 0`
-- -- the "locked into war" cooldown after declaring/being declared on, confirmed live: ~10 turns -- for
-- peace; `IsForcePeace`/`CanDeclareWar` for war) but NOT `IsHasMet`/`IsAtWar`, so live-testing (v12, same
-- day) found `make_peace` against a player never met and never at war still returned a blind {ok=true}:
-- `CanChangeWarPeace` and a 0 locked-war-turn count are both trivially true when no war has ever happened,
-- same false-success shape this whole file has been hunting all day for `propose_deal`. v13 adds the
-- `IsHasMet` precondition and the `IsAtWar` branch explicitly so NEGOTIATE_PEACE/DECLARES_WAR can only ever
-- fire on the side of that branch the real UI would have offered. DENOUNCE has no equivalent precondition
-- in discussiondialog.lua (just a confirm click straight to DoFromUIDiploEvent) so it stays unguarded here.
function H.diplo_event(event_name, other_player, data1, data2)
  local key = event_name
  if not key:match("^FROM_UI_DIPLO_EVENT_") then key = "FROM_UI_DIPLO_EVENT_" .. key end
  local id = FromUIDiploEventTypes[key]
  if id == nil then return { ok = false, err = "unknown diplo event " .. tostring(event_name) } end

  if key == "FROM_UI_DIPLO_EVENT_HUMAN_NEGOTIATE_PEACE" or key == "FROM_UI_DIPLO_EVENT_HUMAN_DECLARES_WAR" then
    local myTeam = Teams[Game.GetActiveTeam()]
    local otherTeam = Players[other_player]:GetTeam()
    if not myTeam:IsHasMet(otherTeam) then
      return { ok = false, err = "have not met this player yet" }
    end
    if not myTeam:CanChangeWarPeace(otherTeam) then
      return { ok = false, err = "war/peace not negotiable with this player right now" }
    end
    local atWar = myTeam:IsAtWar(otherTeam)
    if key == "FROM_UI_DIPLO_EVENT_HUMAN_NEGOTIATE_PEACE" then
      if not atWar then
        return { ok = false, err = "not at war with this player" }
      end
      local lockedTurns = myTeam:GetNumTurnsLockedIntoWar(otherTeam)
      if lockedTurns > 0 then
        return { ok = false, err = "locked into war for " .. lockedTurns .. " more turns; peace cannot be negotiated yet" }
      end
    else
      if atWar then
        return { ok = false, err = "already at war with this player" }
      end
      if myTeam:IsForcePeace(otherTeam) then
        return { ok = false, err = "forced peace in effect; cannot declare war on this player right now" }
      end
      if not myTeam:CanDeclareWar(otherTeam) then
        return { ok = false, err = "cannot declare war on this player right now" }
      end
    end
  end

  Game.DoFromUIDiploEvent(id, other_player, data1 or 0, data2 or 0)
  return { ok = true, event = key }
end
