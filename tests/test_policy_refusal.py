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

    def test_an_unknown_name_suggests_the_policy_behind_a_shown_name(self):
        """Live Assyria t181 (2026-10-11): choose_policy('POLICY_AVANT_GARDE') was refused bare; the tenet shown as
        "Avant Garde" is POLICY_OPEN_SOCIETY. The refusal now carries the policies whose shown name or enum
        carries the asked words; a name matching nothing stays bare."""
        self.run_lua("""
        local pol = GameInfo.Policies
        pol[7] = {ID = 7, Type = 'POLICY_OPEN_SOCIETY', Description = 'Avant Garde', PolicyBranchType = 'POLICY_BRANCH_FREEDOM'}
        pol[5].Description = 'Monarchy'
        setmetatable(pol, { __call = function()
          local ids, i = {2, 3, 5, 7}, 0
          return function() i = i + 1; return ids[i] and pol[ids[i]] or nil end
        end })
        local r = H.choose_policy('POLICY_AVANT_GARDE', 0)
        assert(r.ok == false and r.err == 'unknown policy POLICY_AVANT_GARDE', r.err)
        assert(r.did_you_mean and #r.did_you_mean == 1 and r.did_you_mean[1].policy == 'POLICY_OPEN_SOCIETY'
               and r.did_you_mean[1].name == 'Avant Garde', H.json(r))
        assert(r.hint:find("inspect(what='options', view='policies')", 1, true), r.hint)
        r = H.choose_policy('POLICY_MONARCH', 0)
        assert(r.did_you_mean[1].policy == 'POLICY_MONARCHY', 'a truncated enum still finds it')
        r = H.choose_policy('POLICY_NOTHING_LIKE_IT', 0)
        assert(r.ok == false and r.did_you_mean == nil and r.hint == nil, 'nothing close: bare refusal')
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

    def test_an_ideology_tenets_level_gate_is_named(self):
        """Live Assyria t208 (2026-10-14): Universal Suffrage (level 2) answered a bare "cannot adopt this policy
        right now" with Avant Garde + Civil Society (level 1) and New Deal (level 2) held. socialpolicypopup.lua
        opens level-2 slot i once level-1 slot i+1 is filled: a second level-2 tenet needs a third level-1."""
        self.run_lua("""
        GameInfoTypes.POLICY_UNIVERSAL_SUFFRAGE = 40; GameInfoTypes.POLICY_BRANCH_FREEDOM = 12
        local F = 'POLICY_BRANCH_FREEDOM'
        local rows = { {ID = 40, Type = 'POLICY_UNIVERSAL_SUFFRAGE', PolicyBranchType = F, Level = 2},
                       {ID = 41, Type = 'POLICY_OPEN_SOCIETY', PolicyBranchType = F, Level = 1},
                       {ID = 42, Type = 'POLICY_CIVIL_SOCIETY', PolicyBranchType = F, Level = 1},
                       {ID = 43, Type = 'POLICY_CREATIVE_EXPRESSION', PolicyBranchType = F, Level = 1},
                       {ID = 44, Type = 'POLICY_NEW_DEAL', PolicyBranchType = F, Level = 2} }
        local pol = {}
        for _, r in ipairs(rows) do pol[r.ID] = r; pol[r.Type] = r end
        setmetatable(pol, { __call = function()
          local i = 0
          return function() i = i + 1; return rows[i] end
        end })
        GameInfo.Policies = pol
        HAS = { [41] = true, [42] = true, [44] = true }; CAN = false
        local r = H.choose_policy('POLICY_UNIVERSAL_SUFFRAGE', 0)
        assert(r.ok == false and r.err:find('a level%-2 tenet needs 3 level%-1 tenets'), r.err)
        assert(r.err:find('you hold 2 level%-1 and 1 level%-2'), r.err)
        assert(r.tenet_rule.needed_below == 3 and r.tenet_rule.held_below == 2 and r.tenet_rule.held_at == 1, H.json(r))
        HAS[43] = true
        r = H.choose_policy('POLICY_UNIVERSAL_SUFFRAGE', 0)
        assert(r.err == 'cannot adopt this policy right now' and r.tenet_rule == nil, r.err)
        assert(SENT == nil)
        """)


if __name__ == "__main__":
    unittest.main()
