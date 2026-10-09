"""Runtime v265, found playing Grok's abandoned England seat (2026-10-08, t118-t126).

1. A unit the engine moves between our turn end and our turn start, with no order of ours behind it, is a
   `unit_displaced` row: the Great General sleeping in London stood one plot outside the city at the next turn
   start whenever a Caravan shared the city tile (bought at t120, built at t124). A unit on a standing move of
   ours or on automation is the engine's to move and is left out.
2. `turn_state.wars`: every war this seat is in, with the leader screen's Negotiate Peace gate, and the
   briefing's `at_war` warning built from it. Grok sat twenty turns in a siege while all three enemies would
   have taken a white peace on the first ask; no read said so.
3. `league_status.special_session`: the host vote comes alone, the proposed resolutions one session later.
"""
import unittest

import test_mcp_safety as support
from harness import briefing as B

WORLD = """
GameDefines = { MAX_HIT_POINTS = 100, MAX_CIV_PLAYERS = 6 }
Locale = { Lookup = function(k) return k end, ConvertTextKey = function(k, n) return k .. ':' .. tostring(n) end }
GameInfo = { Units = { [1] = { Type = 'UNIT_GREAT_GENERAL' }, [2] = { Type = 'UNIT_CARAVAN' }, [3] = { Type = 'UNIT_SCOUT' } } }
Teams = { [0] = { IsHasMet = function() return false end } }

function unit(id, utype, x, y, opts)
  opts = opts or {}
  local u = { GetOwner = function() return 0 end, GetID = function() return id end,
              GetUnitType = function() return utype end, GetX = function() return x end, GetY = function() return y end,
              GetCurrHitPoints = function() return 100 end, IsDelayedDeath = function() return false end,
              IsAutomated = function() return opts.automated or false end,
              GetLengthMissionQueue = function() return opts.queued or 0 end,
              IsTrade = function() return opts.trade or false end }
  function u.place(nx, ny) x, y = nx, ny end
  return u
end
GG = unit(196613, 1, 60, 40)
CARAVAN = unit(327687, 2, 60, 40, { trade = true })
SCOUT = unit(24576, 3, 66, 34, { queued = 1 })
UNITS = { GG, CARAVAN, SCOUT }
Players = { [0] = { GetTeam = function() return 0 end,
                    Units = function() local i = 0; return function() i = i + 1; return UNITS[i] end end,
                    GetUnitByID = function(_, id) for _, u in ipairs(UNITS) do if u:GetID() == id then return u end end end } }
Map = { GetPlot = function(x, y)
  local here = {}
  for _, u in ipairs(UNITS) do if u:GetX() == x and u:GetY() == y then here[#here + 1] = u end end
  return { GetNumUnits = function() return #here end, GetUnit = function(_, i) return here[i + 1] end }
end }
"""


class DisplacedUnitTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_a_general_bumped_out_of_the_city_is_reported_with_the_caravan_that_shares_its_tile(self):
        self.run_lua("""
        H.hp_snapshot(0)                       -- our turn ends: GG and Caravan in London, Scout on a move
        GG.place(59, 39)                       -- the AI round: the engine jumps the General out
        SCOUT.place(66, 33)                    -- the engine carries the Scout's standing move on
        H.displaced_compare(0)
        local rows = {}
        for _, e in ipairs(H.events) do if e.kind == 'unit_displaced' then rows[#rows + 1] = e.data end end
        assert(#rows == 1, 'one row, the General: ' .. #rows)
        local d = rows[1]
        assert(d.unit_id == 196613 and d.unit == 'GREAT_GENERAL', H.json(d))
        assert(d.from_x == 60 and d.from_y == 40 and d.x == 59 and d.y == 39, H.json(d))
        assert(d.shared_with and d.shared_with.unit_id == 327687 and d.shared_with.unit == 'CARAVAN', H.json(d))
        assert(d.summary:find('no order of yours') and d.summary:find('CARAVAN of yours shares the tile'), d.summary)
        """)

    def test_a_unit_that_stayed_or_that_the_engine_was_meant_to_move_is_quiet(self):
        self.run_lua("""
        H.hp_snapshot(0)
        SCOUT.place(66, 33)                    -- standing move carried on (moving at the snapshot)
        CARAVAN.place(58, 40)                  -- a trade unit walking its route
        H.displaced_compare(0)
        for _, e in ipairs(H.events) do assert(e.kind ~= 'unit_displaced', H.json(e)) end
        """)

    def test_the_turn_start_hook_runs_it_before_the_roster_is_rewritten(self):
        self.run_lua("""
        TURN_START = nil
        Events = { ActivePlayerTurnStart = { Add = function(fn) TURN_START = fn end, Remove = function() end },
                   ActivePlayerTurnEnd = { Add = function() end, Remove = function() end } }
        H.check_eliminations = function() end
        H.install_hooks()
        H.hp_snapshot(0)
        GG.place(59, 39)
        TURN_START()
        local last
        for _, e in ipairs(H.events) do if e.kind == 'unit_displaced' then last = e.data end end
        assert(last and last.unit_id == 196613, 'the hook reported the General')
        assert(H.roster[0][196613].x == 59, 'the roster now holds the new plot')
        """)


WARS = """
GameDefines = { MAX_CIV_PLAYERS = 24 }
Locale = { Lookup = function(k) return k end, ConvertTextKey = function(k, n) return 'locked ' .. tostring(n) end }
Game.IsOption = function() return false end
GameOptionTypes = { GAMEOPTION_ALWAYS_WAR = 1, GAMEOPTION_NO_CHANGING_WAR_PEACE = 2 }
local function civ(i, name, leader, minor, alive)
  return { IsAlive = function() return alive ~= false end, IsMinorCiv = function() return minor or false end,
           GetTeam = function() return i end, GetName = function() return leader end,
           GetCivilizationShortDescriptionKey = function() return name end }
end
Players = { [0] = civ(0, 'England', 'Elizabeth'), [1] = civ(1, 'Persia', 'Darius'), [3] = civ(3, 'Portugal', 'Maria'),
            [6] = civ(6, 'Songhai', 'Askia'), [7] = civ(7, 'Ghost', 'Nobody', false, false), [22] = civ(22, 'Hong Kong', 'Hong Kong', true) }
AT_WAR = { [3] = true, [6] = true, [22] = true }
LOCKED = { [3] = 4 }
Teams = { [0] = { IsHasMet = function(_, t) return t ~= 7 end, IsAtWar = function(_, t) return AT_WAR[t] or false end,
                  CanChangeWarPeace = function(_, t) return t ~= 6 end,
                  GetNumTurnsLockedIntoWar = function(_, t) return LOCKED[t] or 0 end } }
"""


class WarsTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WARS)

    def test_every_war_with_its_peace_gate(self):
        self.run_lua("""
        local w = H.wars(0)
        assert(#w.majors == 2 and #w.minors == 1, H.json(w))
        local by = {}
        for _, r in ipairs(w.majors) do by[r.player_id] = r end
        assert(by[3].civ == 'Portugal' and by[3].leader == 'Maria', H.json(by[3]))
        assert(by[3].peace.ok == false and by[3].peace.locked_turns == 4 and by[3].peace.note == 'locked 4', H.json(by[3]))
        assert(by[6].peace.ok == false and by[6].peace.note:find('cannot be changed'), H.json(by[6]))
        assert(w.minors[1].player_id == 22 and w.minors[1].peace == nil, H.json(w.minors))
        AT_WAR[6] = nil; Teams[0].CanChangeWarPeace = function() return true end; LOCKED[3] = nil
        w = H.wars(0)
        assert(#w.majors == 1 and w.majors[1].peace.ok == true and w.majors[1].peace.locked_turns == 0, H.json(w))
        AT_WAR = {}
        assert(H.wars(0) == nil, 'no wars: nil, the key stays off the status')
        """)


class WarWarningTests(unittest.TestCase):
    def test_the_briefing_names_each_enemy_and_whether_peace_can_be_asked_for(self):
        ts = {"alerts": [], "todo": {}, "wars": {
            "majors": [{"player_id": 6, "civ": "Songhai", "leader": "Askia", "peace": {"ok": True, "locked_turns": 0}},
                       {"player_id": 3, "civ": "Portugal", "leader": "Maria I",
                        "peace": {"ok": False, "locked_turns": 4, "note": "locked into war for 4 more turns"}}],
            "minors": [{"player_id": 22, "civ": "Hong Kong"}, {"player_id": 23, "civ": "Florence"}]}}
        w = B.warnings(ts)
        self.assertEqual([r["kind"] for r in w], ["at_war", "at_war", "at_war_city_states"])
        self.assertTrue(w[0]["peace_possible"])
        self.assertIn("make_peace(6)", w[0]["hint"])
        self.assertFalse(w[1]["peace_possible"])
        self.assertEqual((w[1]["locked_turns"], w[1]["peace_note"]), (4, "locked into war for 4 more turns"))
        self.assertNotIn("hint", w[1])
        self.assertEqual(w[2]["count"], 2)
        self.assertEqual([c["player_id"] for c in w[2]["civs"]], [22, 23])

    def test_no_wars_add_nothing(self):
        self.assertEqual(B.warnings({"alerts": [], "todo": {}}), [])
        self.assertEqual(B.warnings({"alerts": [], "todo": {}, "wars": None}), [])


LEAGUE = """
Locale = { ConvertTextKey = function(k) return k end, Lookup = function(k) return k end }
GameDefines = { MAX_MAJOR_CIVS = 2 }
Players = { [0] = { IsAlive = function() return true end, IsMinorCiv = function() return false end, GetTeam = function() return 0 end,
                    GetCivilizationShortDescription = function() return 'England' end } }
Teams = { [0] = { IsHasMet = function() return false end } }
SPECIAL = true
league = {
  IsInSession = function() return true end, IsInSpecialSession = function() return SPECIAL end,
  GetID = function() return 0 end, GetName = function() return 'First Congress of Gao' end,
  GetRemainingProposalsForMember = function() return 0 end, CanPropose = function() return false end,
  GetHostMember = function() return 0 end, CalculateStartingVotesForMember = function() return 2 end,
  GetRemainingVotesForMember = function() return 2 end, GetSpentVotesForMember = function() return 0 end,
  GetTurnsUntilSession = function() return 1 end, GetInactiveResolutions = function() return {} end,
  GetActiveResolutions = function() return {} end, GetEnactProposals = function() return {} end,
  GetRepealProposals = function() return {} end, IsProjectActive = function() return false end,
  IsProjectComplete = function() return false end, GetMemberDetails = function() return '' end,
  IsMember = function() return true end,
}
GameInfo = { LeagueProjects = function() return function() return nil end end, Resolutions = {} }
Game.GetNumActiveLeagues = function() return 1 end
Game.GetActiveLeague = function() return league end
Game.GetVotesNeededForDiploVictory = function() return 44 end
"""


class SpecialSessionTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(LEAGUE)

    def test_the_host_vote_is_marked_as_a_special_session(self):
        self.run_lua("""
        local s = H.league_status(0)
        assert(s.in_session == true and s.special_session == true, H.json(s))
        assert(s.turns_until_session == 1, H.json(s))
        assert(s.note and s.note:find('special session'), tostring(s.note))
        SPECIAL = false
        s = H.league_status(0)
        assert(s.special_session == false and s.note == nil, H.json(s))
        """)


if __name__ == "__main__":
    unittest.main()
