"""A gold gift buys Influence; the alliance is a separate question.

Live t231: Sidon sat at 5 Influence with `ally.none` reported ten turns earlier. A 1000-gold large
gift took us to 80 -- and Ethiopia, who had become ally meanwhile at 83, kept it. Every number
needed to see that coming was already in the answer (`ally.to_become_ally` was 4 afterwards); none
of it was on the tier being pressed.
"""
import unittest

import test_mcp_safety as support

WORLD = """
GameDefines = { MINOR_GOLD_GIFT_SMALL = 250, MINOR_GOLD_GIFT_MEDIUM = 500,
                MINOR_GOLD_GIFT_LARGE = 1000, FRIENDSHIP_THRESHOLD_ALLIES = 60 }
mine = 5
ally_id = -1
ally_influence = 83
gold = 1000
local gift = { [250] = 15, [500] = 35, [1000] = 75 }
local minor = {
  IsMinorCiv = function() return true end,
  GetTeam = function() return 5 end,
  IsFriends = function() return mine >= 30 end,
  IsAllies = function() return ally_id == 0 end,
  GetAlly = function() return ally_id end,
  GetFriendshipFromGoldGift = function(_, _, amount) return gift[amount] end,
  GetMinorCivFriendshipWithMajor = function(_, who) return who == 0 and mine or ally_influence end,
}
Players = { [0] = { GetTeam = function() return 0 end, GetGold = function() return gold end },
            [4] = { GetTeam = function() return 4 end,
                    GetCivilizationShortDescription = function() return 'Ethiopia' end },
            [5] = minor }
Teams = { [0] = { IsHasMet = function() return true end, IsAtWar = function() return false end } }
"""


class GiftMakesAllyTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_a_tier_that_lands_under_the_current_ally_says_how_short(self):
        self.run_lua("""
        ally_id, ally_influence, mine = 4, 83, 5
        local r = H.city_state_gifts(5, 0)
        assert(r.ally.civ == 'Ethiopia' and r.ally.to_become_ally == 79, r.ally.to_become_ally)
        assert(r.large.friendship == 75 and r.large.makes_ally == false, 'the 1000-gold tier misses')
        assert(r.large.short_by == 4, r.large.short_by)
        assert(r.large.influence_after == 80)
        assert(r.small.short_by == 64 and r.medium.short_by == 44)
        """)

    def test_a_tier_that_takes_the_alliance_says_so(self):
        self.run_lua("""
        ally_id, ally_influence, mine = 4, 83, 80
        local r = H.city_state_gifts(5, 0)
        assert(r.ally.to_become_ally == 4)
        for _, t in ipairs({r.small, r.medium, r.large}) do
          assert(t.makes_ally == true and t.short_by == nil, t.amount)
        end
        assert(r.small.influence_after == 95)
        """)

    def test_an_unallied_city_state_measures_against_the_threshold(self):
        self.run_lua("""
        ally_id, mine = -1, 0
        local r = H.city_state_gifts(5, 0)
        assert(r.ally.none == true and r.ally.to_become_ally == 60)
        assert(r.small.makes_ally == false and r.small.short_by == 45)
        assert(r.large.makes_ally == true)
        """)

    def test_our_own_ally_needs_no_gap(self):
        self.run_lua("""
        ally_id, mine = 0, 90
        local r = H.city_state_gifts(5, 0)
        assert(r.allied == true and r.ally.us == true and r.ally.to_become_ally == nil)
        assert(r.large.makes_ally == true and r.large.short_by == nil,
               'a gift to our own ally only extends it')
        """)

    def test_an_unmet_ally_is_still_not_named(self):
        """The gap is on the stock tooltip; the rival's identity is not, unless we have met them."""
        self.run_lua("""
        ally_id, mine = 4, 10
        Teams[0].IsHasMet = function(_, team) return team ~= 4 end
        local r = H.city_state_gifts(5, 0)
        assert(r.ally.civ == nil and r.ally.player == nil and r.ally.met == false)
        assert(r.ally.to_become_ally == 74 and r.large.short_by == nil and r.large.makes_ally == true)
        """)


if __name__ == "__main__":
    unittest.main()
