"""The promotion chooser must arrive readable, not as enum strings.

Live t184 (Shoshone vs the Inca): a Fighter earned a promotion and
available_unit_actions offered ["PROMOTION_INSTA_HEAL", "PROMOTION_INTERCEPTION_1",
"PROMOTION_DOGFIGHTING_1"]. The human at the same screen reads a name and an effect
line under each button; "DOGFIGHTING_1" against "INTERCEPTION_1" is not a choice
anyone can make from the enum alone.
"""
import unittest

import test_mcp_safety as support


WORLD = """
Locale={ConvertTextKey=function(key) return ({
  TXT_KEY_PROMOTION_INTERCEPTION_1='Interception I',
  TXT_KEY_PROMOTION_HELP_INTERCEPTION_1='+33% chance to intercept enemy air units',
  TXT_KEY_PROMOTION_DOGFIGHTING_1='Dogfighting I',
  TXT_KEY_PROMOTION_HELP_DOGFIGHTING_1='+33% Combat Strength when intercepting',
  TXT_KEY_PROMOTION_INSTA_HEAL='Heal Instantly',
})[key] or key end}
GameInfo={UnitPromotions=function()
  local rows={
    {ID=1,Type='PROMOTION_INTERCEPTION_1',Description='TXT_KEY_PROMOTION_INTERCEPTION_1',
     Help='TXT_KEY_PROMOTION_HELP_INTERCEPTION_1'},
    {ID=2,Type='PROMOTION_DOGFIGHTING_1',Description='TXT_KEY_PROMOTION_DOGFIGHTING_1',
     Help='TXT_KEY_PROMOTION_HELP_DOGFIGHTING_1'},
    {ID=3,Type='PROMOTION_INSTA_HEAL',Description='TXT_KEY_PROMOTION_INSTA_HEAL'},
    {ID=4,Type='PROMOTION_NOT_YET',Description='TXT_KEY_PROMOTION_NOT_YET'},
  }
  local i=0
  return function() i=i+1 return rows[i] end
end}

function unit_allowing(ids)
  local allowed={}
  for _,id in ipairs(ids) do allowed[id]=true end
  return {CanPromote=function(_,id) return allowed[id]==true end}
end
"""


class PromotionOptionsTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_each_offered_promotion_carries_its_name_and_effect(self):
        self.run_lua("""
        local rows=H.promotion_options(unit_allowing({1,2,3}))
        assert(#rows==3, 'expected the three promotions the unit can take, got '..#rows)
        assert(rows[1].promotion=='PROMOTION_INTERCEPTION_1')
        assert(rows[1].name=='Interception I', 'name: '..tostring(rows[1].name))
        assert(rows[1].help=='+33% chance to intercept enemy air units', 'help: '..tostring(rows[1].help))
        assert(rows[2].name=='Dogfighting I')
        assert(rows[2].help=='+33% Combat Strength when intercepting')
        """)

    def test_a_promotion_without_help_text_still_carries_its_name(self):
        self.run_lua("""
        local rows=H.promotion_options(unit_allowing({3}))
        assert(#rows==1 and rows[1].promotion=='PROMOTION_INSTA_HEAL')
        assert(rows[1].name=='Heal Instantly')
        assert(rows[1].help==nil, 'a missing Help row must drop only the help field')
        """)

    def test_promotions_the_unit_cannot_take_are_not_offered(self):
        self.run_lua("""
        local rows=H.promotion_options(unit_allowing({2}))
        assert(#rows==1 and rows[1].promotion=='PROMOTION_DOGFIGHTING_1')
        """)

    def test_a_unit_that_cannot_promote_at_all_yields_nothing(self):
        self.run_lua("assert(#H.promotion_options({})==0)")
        self.run_lua("assert(#H.promotion_options(nil)==0)")


if __name__ == "__main__":
    unittest.main()
