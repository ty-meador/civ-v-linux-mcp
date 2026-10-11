"""choose_policy's refusal names the reason (live Assyria t21: POLICY_MONARCHY answered a bare "cannot adopt this
policy right now" with Aristocracy adopted and Oligarchy the one adoptable policy)."""
import unittest

import test_mcp_safety as support


class PolicyRefusalTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua("""
        SENT = nil
        Network = { SendUpdatePolicies = function(id, isPolicy, confirm) SENT = id end }
        GameInfoTypes = { POLICY_MONARCHY = 5, POLICY_LEGALISM = 3, POLICY_ARISTOCRACY = 2, POLICY_BRANCH_TRADITION = 9 }
        local pol = { [5] = {ID = 5, Type = 'POLICY_MONARCHY', PolicyBranchType = 'POLICY_BRANCH_TRADITION'},
                      [3] = {ID = 3, Type = 'POLICY_LEGALISM', PolicyBranchType = 'POLICY_BRANCH_TRADITION'},
                      [2] = {ID = 2, Type = 'POLICY_ARISTOCRACY', PolicyBranchType = 'POLICY_BRANCH_TRADITION'} }
        for _, r in pairs({pol[5], pol[3], pol[2]}) do pol[r.Type] = r end
        GameInfo = GameInfo or {}
        GameInfo.Policies = pol
        GameInfo.Policy_PrereqPolicies = function(f)
          local rows = { {PolicyType = 'POLICY_MONARCHY', PrereqPolicy = 'POLICY_LEGALISM'},
                         {PolicyType = 'POLICY_MONARCHY', PrereqPolicy = 'POLICY_ARISTOCRACY'} }
          local i = 0
          return function()
            repeat i = i + 1 until rows[i] == nil or rows[i].PolicyType == f.PolicyType
            return rows[i]
          end
        end
        HAS = { [2] = true }; CAN = false; UNLOCKED = true
        Players = { [0] = { CanAdoptPolicy = function() return CAN end, HasPolicy = function(self, id) return HAS[id] == true end,
                            IsPolicyBranchUnlocked = function() return UNLOCKED end } }
        """)

    def test_the_missing_prerequisite_is_named(self):
        self.run_lua("""
        local r = H.choose_policy('POLICY_MONARCHY', 0)
        assert(r.ok == false and r.err:find('needs POLICY_LEGALISM first') and not r.err:find('ARISTOCRACY'), r.err)
        assert(#r.needs == 1 and r.needs[1] == 'POLICY_LEGALISM', H.json(r))
        assert(SENT == nil)
        """)

    def test_a_locked_branch_and_an_adopted_policy_are_named(self):
        self.run_lua("""
        UNLOCKED = false
        local r = H.choose_policy('POLICY_MONARCHY', 0)
        assert(r.err:find('not unlocked') and r.branch == 'POLICY_BRANCH_TRADITION', r.err)
        UNLOCKED = true; HAS[5] = true
        r = H.choose_policy('POLICY_MONARCHY', 0)
        assert(r.err == 'POLICY_MONARCHY is already adopted', r.err)
        CAN = true
        assert(H.choose_policy('POLICY_MONARCHY', 0).ok and SENT == 5)
        """)


if __name__ == "__main__":
    unittest.main()
