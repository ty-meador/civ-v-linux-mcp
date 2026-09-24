"""The policy screen's Switch Ideology button and its confirm (GitLab #13).

socialpolicypopup.lua enables the button only while GetPublicOpinionUnhappiness is positive, hovers
GetPublicOpinionUnhappinessTooltip on the figure, and the confirm prints the anarchy turns and the
tenets kept (held minus SWITCH_POLICY_BRANCHES_TENETS_LOST, never below 0). Yes sends
Network.SendChangeIdeology.
"""
import unittest

import test_mcp_safety as support

WORLD = r"""
PublicOpinionTypes = { PUBLIC_OPINION_CONTENT = 0, PUBLIC_OPINION_DISSIDENTS = 1 }
GameDefines = { SWITCH_POLICY_BRANCHES_ANARCHY_TURNS = 2, SWITCH_POLICY_BRANCHES_TENETS_LOST = 2 }
GameInfo = { PolicyBranchTypes = { [9] = { Type = 'POLICY_BRANCH_FREEDOM' }, [10] = { Type = 'POLICY_BRANCH_ORDER' } } }
UNH = 0; TREE = 9; TENETS = 5; PREF = 10
SENT = 0
Network = { SendChangeIdeology = function() SENT = SENT + 1 end }
Players = { [0] = {
  GetPublicOpinionType = function() return UNH > 0 and 1 or 0 end,
  GetPublicOpinionUnhappiness = function() return UNH end,
  GetPublicOpinionPreferredIdeology = function() return PREF end,
  GetPublicOpinionTooltip = function() return 'opinion tip' end,
  GetPublicOpinionUnhappinessTooltip = function() return '[ICON_BULLET]-4 from Dissidents[NEWLINE]' end,
  GetLateGamePolicyTree = function() return TREE end,
  GetNumPoliciesInBranch = function(_, tree) assert(tree == TREE); return TENETS end,
} }
"""


class IdeologySwitchTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_content_empire_has_a_grey_button_and_no_cost(self):
        self.run_lua("""
        local po = H.public_opinion(0)
        assert(po.ideology == 'POLICY_BRANCH_FREEDOM' and po.can_switch == false and po.switch_cost == nil, H.json(po))
        assert(po.unhappiness == nil and po.unhappiness_tooltip == '• -4 from Dissidents')
        local r = H.change_ideology(0)
        assert(r.ok == false and SENT == 0 and r.ideology == 'POLICY_BRANCH_FREEDOM')
        """)

    def test_unhappiness_enables_the_button_with_the_confirms_numbers(self):
        self.run_lua("""
        UNH = 4
        local po = H.public_opinion(0)
        assert(po.can_switch == true and po.unhappiness == 4 and po.preferred_ideology == 'POLICY_BRANCH_ORDER')
        assert(po.switch_cost.anarchy_turns == 2 and po.switch_cost.tenets_now == 5 and po.switch_cost.tenets_kept == 3 and po.switch_cost.to == 'POLICY_BRANCH_ORDER', H.json(po.switch_cost))
        TENETS = 1
        assert(H.public_opinion(0).switch_cost.tenets_kept == 0, 'never below zero')
        local r = H.change_ideology(0)
        assert(r.ok and SENT == 1 and r.from == 'POLICY_BRANCH_FREEDOM' and r.to == 'POLICY_BRANCH_ORDER' and r.cost.tenets_kept == 0, H.json(r))
        """)

    def test_no_ideology_yet(self):
        self.run_lua("""
        TREE = -1
        local po = H.public_opinion(0)
        assert(po.ideology == nil and po.can_switch == nil)
        local r = H.change_ideology(0)
        assert(r.ok == false and SENT == 0)
        """)


if __name__ == "__main__":
    unittest.main()
