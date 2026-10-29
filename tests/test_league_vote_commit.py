"""One vote call commits the whole delegation (GitLab #89).

Live Assyria t258 (2026-10-27): order(to="league", action="vote") with 20 of 28 delegates on the embargo answered
votes_cast 20, abstained 8; a second call with the 8 on Arts Funding answered votes_cast 8 and counted nowhere
(the engine had already committed the delegation; the network layer dropped the message). The runtime now refuses
what cannot count: a spent delegation, a resolution not up for a vote, more votes than remain, and delegates left
unassigned unless abstain is passed.
"""
import unittest

import test_mcp_safety as support
from harness.game import Game

LEAGUE = """
sent = {}
local remaining = 28
LEAGUE = {
  IsInSession = function() return true end, GetID = function() return 1 end,
  GetRemainingVotesForMember = function() return remaining end,
  GetEnactProposals = function() return { { ID = 17 }, { ID = 18 } } end,
  GetRepealProposals = function() return { { ID = 5 } } end,
}
function set_remaining(n) remaining = n end
Game.GetActiveLeague = function() return LEAGUE end
Network = {
  SendLeagueVoteEnact = function(lid, rid, pid, n, c) sent[#sent + 1] = { 'enact', rid, n, c } end,
  SendLeagueVoteRepeal = function(lid, rid, pid, n, c) sent[#sent + 1] = { 'repeal', rid, n, c } end,
  SendLeagueVoteAbstain = function(lid, pid, n) sent[#sent + 1] = { 'abstain', n } end,
}
"""


class LeagueVoteCommitLuaTests(support.LuaRuntimeTests):
    def test_a_partial_delegation_is_refused_unless_abstain_is_meant(self):
        self.run_lua(LEAGUE)
        self.run_lua("""
        local r = H.league_cast_votes({ { resolution_id = 17, direction = 'enact', num_votes = 20, choice = 1 } }, 0, false)
        assert(r.ok == false and r.nothing_cast and r.unassigned == 8 and r.remaining_votes == 28, H.json(r))
        assert(r.err:find('abstain=true', 1, true) and r.err:find('votable', 1, true), r.err)
        assert(#sent == 0, 'nothing reached the wire')
        r = H.league_cast_votes({ { resolution_id = 17, direction = 'enact', num_votes = 20, choice = 1 } }, 0, true)
        assert(r.ok == true and r.votes_cast == 20 and r.abstained == 8 and r.committed == true and r.delegation == 28, H.json(r))
        assert(#sent == 2 and sent[1][1] == 'enact' and sent[2][1] == 'abstain' and sent[2][2] == 8, H.json(sent))
        """)

    def test_the_whole_delegation_across_two_proposals_goes_in_one_call(self):
        self.run_lua(LEAGUE)
        self.run_lua("""
        local r = H.league_cast_votes({ { resolution_id = 17, direction = 'enact', num_votes = 20, choice = 1 },
                                        { resolution_id = 18, direction = 'enact', num_votes = 8, choice = 0 } }, 0, false)
        assert(r.ok == true and r.votes_cast == 28 and r.abstained == 0, H.json(r))
        assert(#sent == 2 and sent[2][2] == 18 and sent[2][3] == 8, H.json(sent))
        """)

    def test_a_spent_delegation_an_unknown_resolution_and_too_many_votes_are_refused(self):
        self.run_lua(LEAGUE)
        self.run_lua("""
        local r = H.league_cast_votes({ { resolution_id = 19, direction = 'enact', num_votes = 28, choice = 1 } }, 0, false)
        assert(r.ok == false and r.err:find('19 is not up for a vote', 1, true), H.json(r))
        r = H.league_cast_votes({ { resolution_id = 5, direction = 'enact', num_votes = 28, choice = 1 } }, 0, false)
        assert(r.ok == false and r.err:find('proposal to repeal, not to enact', 1, true), H.json(r))
        r = H.league_cast_votes({ { resolution_id = 17, direction = 'enact', num_votes = 30, choice = 1 } }, 0, false)
        assert(r.ok == false and r.err:find('ask for 30 votes and 28 remain', 1, true), H.json(r))
        assert(#sent == 0, H.json(sent))
        set_remaining(0)
        r = H.league_cast_votes({ { resolution_id = 18, direction = 'enact', num_votes = 8, choice = 0 } }, 0, false)
        assert(r.ok == false and r.remaining_votes == 0 and r.err:find('already committed', 1, true), H.json(r))
        assert(#sent == 0, 'the second call of t258 reaches nothing')
        """)

    def test_an_empty_list_abstains_on_purpose(self):
        self.run_lua(LEAGUE)
        self.run_lua("""
        local r = H.league_cast_votes({}, 0, false)
        assert(r.ok == true and r.votes_cast == 0 and r.abstained == 28, H.json(r))
        assert(#sent == 1 and sent[1][1] == 'abstain' and sent[1][2] == 28, H.json(sent))
        """)


class AbstainReachesTheRuntime(unittest.TestCase):
    def test_the_flag_rides_after_the_votes(self):
        g = Game.__new__(Game)
        g._pid = lambda pid=None: 0
        g.sent = []
        g.q = lambda body: g.sent.append(body) or {"ok": True}
        g.league_cast_votes([{"resolution_id": 17, "direction": "enact", "choice": "yes", "num_votes": 3}], abstain=True)
        self.assertEqual(g.sent[-1].args, [[{"resolution_id": 17, "direction": "enact", "choice": 1, "num_votes": 3}], True])
        g.league_cast_votes([{"resolution_id": 17, "direction": "enact", "choice": "yes", "num_votes": 3}])
        self.assertEqual(g.sent[-1].args[1], False)


if __name__ == "__main__":
    unittest.main()
