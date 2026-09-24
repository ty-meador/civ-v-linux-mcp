"""Deals between two human seats (GitLab #4): the receiving seat's view.

tradelogic.lua OnOpenPlayerDealScreen loads a proposal that exists between the two seats
(UI.ProposedDealExists -> UI.LoadProposedDeal) before showing it. incoming_deal does the same so the
seat can read it without the screen, and turn_status names the proposer.
"""
import unittest

import test_mcp_safety as support

WORLD = r"""
GameDefines = { MAX_MAJOR_CIVS = 4 }
TradeableItems = { TRADE_ITEM_GOLD_PER_TURN = 2, TRADE_ITEM_RESOURCES = 4 }
Players = { [0] = { GetTeam = function() return 0 end }, [1] = { GetTeam = function() return 1 end }, [2] = { GetTeam = function() return 2 end } }
PROPOSED = {}          -- "from:to" -> true
MADE = -1              -- UI.HasMadeProposal(us)
local scratch = { items = {}, from = -1, to = -1 }
SCRATCH = scratch
function scratch:ResetIterator() self.i = 0 end
function scratch:GetNextItem()
  self.i = self.i + 1
  local it = self.items[self.i]
  if not it then return nil end
  return it.type, 0, 0, it.data1, it.data2 or 0, 0, 0, it.from
end
function scratch:GetFromPlayer() return self.from end
function scratch:GetToPlayer() return self.to end
LOADED = {}
UI = {
  GetScratchDeal = function() return scratch end,
  ProposedDealExists = function(a, b) return PROPOSED[a .. ':' .. b] == true end,
  LoadProposedDeal = function(a, b)
    LOADED[#LOADED + 1] = { a, b }
    scratch.from, scratch.to = a, b
    scratch.items = { { type = 2, data1 = 5, from = a } }
  end,
  HasMadeProposal = function(us) return MADE end,
}
H.enum_name = function(_, _, v) return v == 2 and 'TRADE_ITEM_GOLD_PER_TURN' or 'TRADE_ITEM_RESOURCES' end
"""


class PvpDealReadTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_turn_status_names_the_proposer(self):
        self.run_lua("""
        assert(H.pending_deal_from(1) == nil)
        PROPOSED['0:1'] = true
        assert(H.pending_deal_from(1) == 0)
        assert(H.pending_deal_from(0) == nil, 'the proposer has nothing pending for itself')
        assert(H.pending_deal_from(2) == nil)
        """)

    def test_incoming_deal_loads_the_pending_proposal_into_the_scratch(self):
        self.run_lua("""
        PROPOSED['0:1'] = true
        local r = H.incoming_deal(1)
        assert(#LOADED == 1 and LOADED[1][1] == 0 and LOADED[1][2] == 1, 'LoadProposedDeal(them, us)')
        assert(r.n == 1 and r.items[1].type == 'GOLD_PER_TURN' and r.items[1].amount == 5 and r.items[1].from_us == false, H.json(r))
        assert(r.pending == true and r.proposed_by == 0 and r.from == 0 and r.to == 1)
        """)

    def test_a_proposal_the_engine_already_loaded_is_still_flagged_pending(self):
        self.run_lua("""
        PROPOSED['0:1'] = true
        SCRATCH.from, SCRATCH.to = 0, 1
        SCRATCH.items = { { type = 2, data1 = 5, from = 0 } }
        local r = H.incoming_deal(1)
        assert(#LOADED == 0, 'nothing reloaded')
        assert(r.pending == true and r.proposed_by == 0, H.json(r))
        """)

    def test_our_own_sent_proposal_reads_as_ours_pending(self):
        self.run_lua("""
        MADE = 1
        SCRATCH.from, SCRATCH.to = 0, 1
        SCRATCH.items = { { type = 2, data1 = 5, from = 0 } }
        local r = H.incoming_deal(0)
        assert(r.ours_pending == true and r.pending == nil and r.proposed_by == nil, H.json(r))
        """)

    def test_an_empty_table_with_no_proposal_stays_empty(self):
        self.run_lua("""
        local r = H.incoming_deal(1)
        assert(r.n == 0 and r.pending == nil and r.proposed_by == nil and #LOADED == 0)
        """)


if __name__ == "__main__":
    unittest.main()
