"""Delegate counts agree inside one league read, or say why they differ (GitLab #79).

Assyria t251: the members block said 32 vs 14 while every proposal's text tallied 24 vs 24 -- the session fixed each
delegation when it opened (what can be cast), while the text followed the allies of the moment (Siam had just taken
five city-states). Both numbers ride on the member row, with a note.
"""
import unittest

import test_mcp_safety as support

WORLD = """
local stub = { __index = function() return function() return nil end end }
IN_SESSION = true
LEAGUE = setmetatable({
  IsInSession = function() return IN_SESSION end, GetID = function() return 1 end, GetName = function() return 'United Nations' end,
  GetHostMember = function() return 0 end, IsMember = function(_, i) return i == 0 or i == 2 end,
  CalculateStartingVotesForMember = function(_, i) return 24 end,
  GetRemainingVotesForMember = function(_, i) return i == 0 and 32 or 14 end,
  GetSpentVotesForMember = function() return 0 end,
  GetRemainingProposalsForMember = function() return 0 end, CanPropose = function() return false end,
  GetEnactProposals = function() return {} end, GetRepealProposals = function() return {} end,
  GetActiveResolutions = function() return {} end, GetInactiveResolutions = function() return {} end,
  GetTurnsUntilSession = function() return 0 end, IsInSpecialSession = function() return false end,
}, stub)
Game.GetNumActiveLeagues = function() return 1 end
Game.GetActiveLeague = function() return LEAGUE end
Game.GetVotesNeededForDiploVictory = function() return 42 end
GameDefines = { MAX_MAJOR_CIVS = 3, MAX_CIV_PLAYERS = 3 }
GameInfo = GameInfo or {}
GameInfo.LeagueProjects = function() return function() return nil end end
local function civ(i, name)
  return setmetatable({ IsAlive = function() return true end, IsMinorCiv = function() return false end, GetTeam = function() return i end,
                        GetCivilizationShortDescription = function() return name end }, stub)
end
Players = { [0] = civ(0, 'Assyria'), [1] = civ(1, 'Portugal'), [2] = civ(2, 'Siam') }
Teams = { [0] = setmetatable({ IsHasMet = function() return true end }, stub) }
H.league_projects = function() return {} end
"""


class LeagueDelegateTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_in_session_both_counts_ride_on_the_member_row(self):
        self.run_lua("""
        local r = H.league_status(0)
        assert(r.in_session == true and r.members, H.json(r))
        local by = {}
        for _, m in ipairs(r.members) do by[m.civ] = m end
        assert(by.Assyria.delegates == 32 and by.Assyria.delegates_now == 24, H.json(by.Assyria))
        assert(by.Assyria.delegates_note:find('fixed when the session opened', 1, true), by.Assyria.delegates_note)
        assert(by.Siam.delegates == 14 and by.Siam.delegates_now == 24, H.json(by.Siam))
        assert(r.remaining_votes == 32, 'what can be cast is the fixed delegation')
        """)

    def test_between_sessions_one_number_is_enough(self):
        self.run_lua("""
        IN_SESSION = false
        local r = H.league_status(0)
        for _, m in ipairs(r.members) do
          assert(m.delegates == 24 and m.delegates_now == nil and m.delegates_note == nil, H.json(m))
        end
        """)


if __name__ == "__main__":
    unittest.main()
