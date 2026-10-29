"""The World Congress's call for proposals is visible before finish refuses, and the league read has a compact
form (GitLab #117).

Live Maya t197: the status named PRODUCTION; the proposal blocker surfaced only when finish was refused, and the
league read to pick a proposal was 25 KB of repeated resolution text.
"""
import unittest

import test_mcp_safety as support
from harness.briefing import decisions
from harness.game_parts.diplomacy import league_compact
from harness import affordances as A

WORLD = """
GameDefines = { MOVE_DENOMINATOR = 60 }
GameInfo = GameInfo or {}
GameInfo.Units = {}
LEAGUE = { IsInSession = function() return IN_SESSION end, CanPropose = function(_, pid) return CAN end,
           GetRemainingProposalsForMember = function() return 2 end }
Game.GetNumActiveLeagues = function() return 1 end
Game.GetActiveLeague = function() return LEAGUE end
Game.GetActivePlayer = function() return 0 end
Players = { [0] = { IsTurnActive = function() return true end, GetCurrentResearch = function() return 4 end,
                    Units = function() return function() return nil end end,
                    Cities = function() return function() return nil end end,
                    GetTeam = function() return 0 end, GetEndTurnBlockingType = function() return -1 end } }
H.incoming_deal = function() return nil end
H.religion_choice = function() return nil end
IN_SESSION, CAN = false, true
"""


class LeagueProposalTodoLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_a_pending_proposal_is_in_the_todo_whatever_the_blocker_says(self):
        self.run_lua("""
        local t = H.todo(0)
        assert(t.league_proposal and t.league_proposal.remaining == 2, H.json(t))
        assert(t.league_proposal.hint:find('propose', 1, true), t.league_proposal.hint)
        CAN = false
        assert(H.todo(0).league_proposal == nil, 'nothing to propose')
        CAN, IN_SESSION = true, true
        assert(H.todo(0).league_proposal == nil, 'in a session the proposals are closed')
        """)


class LeagueProposalDecisionTests(unittest.TestCase):
    def test_the_decision_row_carries_the_read_and_both_orders_and_the_blocker_is_not_repeated(self):
        ts = {"todo": {"units": [], "cities": [], "league_proposal": {"remaining": 2}},
              "blocking_name": "ENDTURN_BLOCKING_PRODUCTION", "blocking_hint": "x", "pending_popups": []}
        rows = decisions(ts, [])
        lp = [r for r in rows if r["kind"] == "league_proposal"]
        self.assertEqual(len(lp), 1)
        tools = [(a["tool"], a["args"].get("what") or a["args"].get("action")) for a in lp[0]["actions"]]
        self.assertEqual(tools, [("inspect", "league"), ("order", "propose"), ("order", "repeal")])
        self.assertEqual(lp[0]["actions"][0]["args"].get("detail"), "compact")
        ts["blocking_name"] = "ENDTURN_BLOCKING_LEAGUE_CALL_FOR_PROPOSALS"
        kinds = [r["kind"] for r in decisions(ts, [])]
        self.assertEqual(kinds, ["league_proposal"])


class CompactLeagueReadTests(unittest.TestCase):
    def test_compact_drops_the_repeated_prose_and_keeps_every_id(self):
        r = {"ok": True, "in_session": False, "active_effects": "long text",
             "proposable_enact": [{"resolution_type": "RESOLUTION_BAN_LUXURY", "name": "Ban Luxury", "details": "once",
                                   "choices": [{"id": 5, "text": "Wine", "disabled": False, "details": "a paragraph"},
                                               {"id": 6, "text": "Gems", "disabled": True, "details": "a paragraph"}]}],
             "members": [{"player": 0, "civ": "Maya", "delegates": 4, "details": "Their interests are largely a mystery"}]}
        c = league_compact(r)
        self.assertEqual(c["proposable_enact"][0]["details"], "once")
        self.assertEqual(c["proposable_enact"][0]["choices"], [{"id": 5, "text": "Wine", "disabled": False},
                                                               {"id": 6, "text": "Gems", "disabled": True}])
        self.assertEqual(c["members"], [{"player": 0, "civ": "Maya", "delegates": 4}])
        self.assertNotIn("active_effects", c)
        self.assertEqual(c["detail"], "compact")
        self.assertIn("active_effects", r, "the full read is untouched")

    def test_a_choices_vote_row_says_what_choice_takes(self):
        r = {"ok": True, "in_session": True, "remaining_votes": 4,
             "votable": [{"resolution_id": 9, "direction": "enact", "choices": [{"id": 2, "text": "Maya"}]},
                         {"resolution_id": 10, "direction": "repeal", "yes_no": True}]}
        A.league_rows(r)
        self.assertIn("choices[].id", r["votable"][0]["choice_note"])
        self.assertNotIn("choice_note", r["votable"][1])


if __name__ == "__main__":
    unittest.main()
