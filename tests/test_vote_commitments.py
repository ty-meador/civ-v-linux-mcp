"""World Congress vote commitments on the trade table (GitLab #7): the Python-side gate.

tradelogic.lua RefreshPocketVotes only lists (proposal, choice) pairs that pass IsPossibleToTradeItem for
that direction, and OnChoosePocketVote -> AddVoteCommitment is unconditional. _check_deal_items applies
the pocket's gate from trade_catalog().vote_commitments before any screen opens.
"""
import unittest

import test_mcp_safety as support


class VoteCommitmentLegalityTests(unittest.TestCase):
    CATALOG = {"ok": True, "gold": {"us": True, "them": True, "us_available": 500, "them_available": 40},
               "gold_per_turn": {"us": True, "them": True, "us_available": 20, "them_available": 3},
               "resources": [], "cities": {"us": [], "them": []},
               "vote_commitments": [
                   {"resolution_id": 3, "choice_id": 1, "repeal": False, "name": "World Leader", "choice": "Bravo",
                    "us": True, "them": False, "votes_us": 8, "votes_them": 4},
                   {"resolution_id": 7, "choice_id": 0, "repeal": True, "name": "Arts Funding", "choice": "Yea",
                    "us": True, "them": True, "votes_us": 8, "votes_them": 4}]}

    def game(self):
        from harness.game import Game
        g = Game.__new__(Game)
        g.seat = 0
        g.trade_catalog = lambda other, pid=None: dict(self.CATALOG)
        return g

    def check(self, *items):
        return self.game()._check_deal_items(1, list(items), 0)

    def test_listed_pledges_pass_in_their_legal_direction(self):
        self.assertTrue(self.check({"type": "VOTE_COMMITMENT", "from_us": True, "resolution_id": 3, "choice_id": 1})["ok"])
        self.assertTrue(self.check({"type": "VOTE_COMMITMENT", "from_us": False, "resolution_id": 7, "choice_id": 0, "repeal": True})["ok"])

    def test_the_other_direction_is_refused_when_the_pocket_would_not_list_it(self):
        r = self.check({"type": "VOTE_COMMITMENT", "from_us": False, "resolution_id": 3, "choice_id": 1})
        self.assertFalse(r["ok"])
        self.assertEqual(r["tradeable_votes"], self.CATALOG["vote_commitments"])

    def test_unknown_proposal_choice_or_wrong_repeal_flag_is_refused(self):
        self.assertFalse(self.check({"type": "VOTE_COMMITMENT", "from_us": True, "resolution_id": 99, "choice_id": 1})["ok"])
        self.assertFalse(self.check({"type": "VOTE_COMMITMENT", "from_us": True, "resolution_id": 3, "choice_id": 2})["ok"])
        self.assertFalse(self.check({"type": "VOTE_COMMITMENT", "from_us": True, "resolution_id": 3, "choice_id": 1, "repeal": True})["ok"])

    def test_ids_must_be_integers(self):
        for bad in ({"resolution_id": "3", "choice_id": 1}, {"resolution_id": 3}, {"choice_id": 1}, {"resolution_id": True, "choice_id": 1}):
            r = self.check({"type": "VOTE_COMMITMENT", "from_us": True, **bad})
            self.assertFalse(r["ok"], repr(bad))
            self.assertIn("resolution_id", r["err"])


class VoteCommitmentReadTests(unittest.TestCase):
    """H.deal_items keeps all four payload fields and labels the row as DisplayDeal does."""
    run_lua = support.LuaRuntimeTests.run_lua

    WORLD = r"""
    TradeableItems = { TRADE_ITEM_VOTE_COMMITMENT = 15, TRADE_ITEM_GOLD_PER_TURN = 2 }
    Players = { [0] = { GetTeam = function() return 0 end }, [1] = { GetTeam = function() return 1 end } }
    H.enum_name = function(_, _, v) return v == 15 and 'TRADE_ITEM_VOTE_COMMITMENT' or 'TRADE_ITEM_GOLD_PER_TURN' end
    GameInfo = { Resolutions = { RESOLUTION_DIPLOMATIC_VICTORY = { Type = 'RESOLUTION_DIPLOMATIC_VICTORY', VoterDecision = 'RESOLUTION_DECISION_MAJOR_CIV_MEMBER' },
                                 RESOLUTION_ARTS_FUNDING = { Type = 'RESOLUTION_ARTS_FUNDING', VoterDecision = 'RESOLUTION_DECISION_YES_OR_NO' } },
                 ResolutionDecisions = { RESOLUTION_DECISION_MAJOR_CIV_MEMBER = { ID = 4 }, RESOLUTION_DECISION_YES_OR_NO = { ID = 1 },
                                         RESOLUTION_DECISION_REPEAL = { ID = 9 } } }
    LEAGUE = {
      GetEnactProposals = function() return { { Type = 'RESOLUTION_DIPLOMATIC_VICTORY', ID = 3, ProposerDecision = -1 } } end,
      GetRepealProposals = function() return { { Type = 'RESOLUTION_ARTS_FUNDING', ID = 7, ProposerDecision = -1 } } end,
      GetChoicesForDecision = function(_, d) if d == 4 then return { 0, 1 } elseif d == 9 then return { 0, 1 } end return {} end,
      GetResolutionName = function(_, typ, id, dec) return '[COLOR_POSITIVE_TEXT]' .. typ:gsub('RESOLUTION_', '') .. '[ENDCOLOR]' end,
      GetTextForChoice = function(_, d, c) if d == 4 then return ({ [0] = 'Alpha', [1] = 'Bravo' })[c] end return ({ [0] = 'Nay', [1] = 'Yea' })[c] end,
      GetCoreVotesForMember = function(_, p) return p == 0 and 8 or 4 end,
    }
    Game.GetNumActiveLeagues = function() return 1 end
    Game.GetActiveLeague = function() return LEAGUE end
    local i = 0
    DEAL = { ResetIterator = function() i = 0 end, GetNextItem = function()
      i = i + 1
      if i == 1 then return 15, 0, 0, 3, 1, 8, false, 0 end   -- Alpha pledges 8 votes to Bravo for World Leader
      if i == 2 then return 15, 0, 0, 7, 1, 4, true, 1 end    -- Bravo pledges Yea on repealing Arts Funding
    end }
    """

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua("Locale={ConvertTextKey=function(s) return s end}")
        self.run_lua(self.WORLD)

    def test_rows_carry_ids_votes_repeal_and_the_screen_labels(self):
        self.run_lua("""
        local r = H.deal_items(DEAL, 0)
        assert(#r == 2, H.json(r))
        local a, b = r[1], r[2]
        assert(a.type == 'VOTE_COMMITMENT' and a.from_us == true and a.resolution_id == 3 and a.choice_id == 1 and a.votes == 8 and a.repeal == false, H.json(a))
        assert(a.name == 'DIPLOMATIC_VICTORY' and a.choice == 'Bravo' and a.direction == 'enact' and a.resolution_type == 'RESOLUTION_DIPLOMATIC_VICTORY', H.json(a))
        assert(b.from_us == false and b.resolution_id == 7 and b.choice_id == 1 and b.votes == 4 and b.repeal == true, H.json(b))
        assert(b.name == 'ARTS_FUNDING' and b.choice == 'Yea' and b.direction == 'repeal', H.json(b))
        """)

    def test_without_a_league_the_payload_still_survives(self):
        self.run_lua("""
        Game.GetNumActiveLeagues = function() return 0 end
        local r = H.deal_items(DEAL, 0)
        assert(r[1].resolution_id == 3 and r[1].choice_id == 1 and r[1].votes == 8 and r[1].repeal == false, H.json(r[1]))
        assert(r[1].name == nil)
        """)

    def test_catalog_lists_the_pocket_both_ways_with_each_sides_votes(self):
        self.run_lua("""
        local asked = {}
        local deal = { IsPossibleToTradeItem = function(_, from, to, typ, id, choice, n, repeal)
          asked[#asked + 1] = { from, to, typ, id, choice, n, repeal }
          -- Alpha may pledge World Leader to Bravo only; the repeal is open both ways
          if id == 3 then return from == 0 and choice == 1 end
          return true
        end }
        local rows = H.vote_commitment_catalog(deal, 0, 1)
        assert(#rows == 3, H.json(rows))
        assert(rows[1].resolution_id == 3 and rows[1].choice_id == 1 and rows[1].us == true and rows[1].them == false, H.json(rows[1]))
        assert(rows[1].votes_us == 8 and rows[1].votes_them == 4 and rows[1].choice == 'Bravo' and rows[1].name == 'DIPLOMATIC_VICTORY')
        assert(rows[2].resolution_id == 7 and rows[2].repeal == true and rows[2].us and rows[2].them and rows[2].direction == 'repeal')
        assert(rows[3].choice == 'Yea')
        for _, q in ipairs(asked) do
          assert(q[3] == 15, 'wrong item type')
          assert((q[1] == 0 and q[6] == 8) or (q[1] == 1 and q[6] == 4), 'the committing side\\'s own core votes go into the gate')
        end
        """)

    def test_vote_gate_reports_each_directions_reason(self):
        """The Votes pocket header: Player:CanCommitVote(other) enables it, GetCommitVoteDetails(other) is the
        tooltip (tradelogic.lua ~1653). Both directions, tags stripped."""
        self.run_lua("""
        local us = { GetID = function() return 0 end, CanCommitVote = function(_, o) return false end,
                     GetCommitVoteDetails = function(_, o) return '[NEWLINE][NEWLINE][COLOR_WARNING_TEXT]They need a Spy as a [ICON_DIPLOMAT] Diplomat in our [ICON_CAPITAL] Capital.[ENDCOLOR]' end }
        local them = { GetID = function() return 1 end, CanCommitVote = function(_, o) return true end,
                       GetCommitVoteDetails = function(_, o) return '' end }
        local g = H.vote_gate(us, them)
        assert(g.us == false and g.them == true, H.json(g))
        assert(g.us_note and g.us_note:find('Diplomat in our') and not g.us_note:find('%[', 1), g.us_note)
        assert(g.them_note == nil)
        assert(H.vote_gate({}, them) == nil, 'no API, no field')
        """)


if __name__ == "__main__":
    unittest.main()
