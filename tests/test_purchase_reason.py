"""A refused purchase should say what the greyed-out button says.

`purchase_cost` explains a refusal with its own ladder of guesses. The stock production popup does
something better for a disabled row: it appends the engine's own tooltip (productionpopup.lua,
"Disabled help text" -- GetPurchaseUnitTooltip / GetFaithPurchaseUnitTooltip /
GetPurchaseBuildingTooltip / GetFaithPurchaseBuildingTooltip). Live t205: a faith Pagoda refused in
all three puppet cities came back as "this item cannot be bought here at all", which is true and
tells the seat nothing about what to change.

Runs the shipped Lua body in lupa so the real getters are exercised, not a paraphrase of them.
"""
import unittest

from harness.game import Game
from test_query_chunking import LuaClient


CITY_ENV = """
YieldTypes = {YIELD_GOLD = 1, YIELD_FAITH = 2}
GameInfoTypes = {BUILDING_PAGODA = 7, UNIT_MISSIONARY = 11}
GameInfo = {Units = {[11] = {Type = 'UNIT_MISSIONARY', ReligionSpreads = 1, Domain = 0, Combat = 0}},
            Buildings = {[7] = {Type = 'BUILDING_PAGODA'}}}
local city = {
  GetBuildingFaithPurchaseCost = function() return 400 end,
  GetBuildingPurchaseCost = function() return 900 end,
  -- LISTED: the buy button exists (IsCanPurchase with the cost test off), as it does while saving up
  IsCanPurchase = function(_, test_cost) return (not test_cost) and LISTED end,
  IsHasBuilding = function() return false end,
  GetReligiousMajority = function() return -1 end,
  GetFaithPurchaseBuildingTooltip = function(_, id) return TIP end,
  GetPurchaseBuildingTooltip = function(_, id) return TIP end,
  Plot = function() return {GetNumUnits = function() return 0 end} end,
  IsPuppet = function() return PUPPET end,
}
Players = {[0] = {GetCityByID = function() return city end,
                  GetFaith = function() return 1160 end,
                  MayNotAnnex = function() return VENICE end,
                  GetGold = function() return 385 end}}
"""


class PurchaseReasonTest(unittest.TestCase):
    def setUp(self):
        try:
            import lupa
        except ImportError:
            self.skipTest("lupa not installed (uv run --with lupa)")
        self.lua = lupa.LuaRuntime()
        self.lua.execute("loadstring = load")
        self.g = Game.__new__(Game)
        self.g.c = LuaClient(self.lua)
        self.g.seat = 0
        self.g.ensure_runtime = lambda: None

    def _cost(self, tip, puppet=False, venice=False, listed=False, **kw):
        self.lua.execute(f"TIP = {tip} PUPPET = {str(puppet).lower()} VENICE = {str(venice).lower()} "
                         f"LISTED = {str(listed).lower()}")
        self.lua.execute(CITY_ENV)
        return self.g.purchase_cost(1, kw.pop("order", "ORDER_CONSTRUCT"),
                                    kw.pop("item", "BUILDING_PAGODA"), kw.pop("yield_type", "FAITH"))

    def test_the_engines_own_sentence_comes_back_with_the_refusal(self):
        out = self._cost("'You must have a majority religion in this city.'")
        self.assertFalse(out["can_purchase"])
        self.assertEqual(out["engine_reason"], "You must have a majority religion in this city.")
        self.assertIn("cannot be bought here", out["reason"], "our own hint is still there")

    def test_no_tooltip_means_no_field_rather_than_an_empty_one(self):
        self.assertNotIn("engine_reason", self._cost("''"))
        self.assertNotIn("engine_reason", self._cost("nil"))

    def test_a_getter_the_build_does_not_have_is_not_an_error(self):
        """Older/modded builds may not expose every tooltip getter; the read must survive that."""
        self.lua.execute("TIP = '' PUPPET = false VENICE = false")
        self.lua.execute(CITY_ENV + "\nPlayers[0].GetCityByID = function() local c = {} "
                         "for k, v in pairs(city) do c[k] = v end "
                         "c.GetFaithPurchaseBuildingTooltip = nil return c end")
        out = self.g.purchase_cost(1, "ORDER_CONSTRUCT", "BUILDING_PAGODA", "FAITH")
        self.assertFalse(out["can_purchase"])
        self.assertNotIn("engine_reason", out)

    def test_a_successful_purchase_read_is_not_cluttered_with_it(self):
        self.lua.execute("TIP = 'should not be asked for' PUPPET = false VENICE = false")
        self.lua.execute(CITY_ENV + "\nPlayers[0].GetCityByID = function() local c = {} "
                         "for k, v in pairs(city) do c[k] = v end "
                         "c.IsCanPurchase = function() return true end return c end")
        out = self.g.purchase_cost(1, "ORDER_CONSTRUCT", "BUILDING_PAGODA", "FAITH")
        self.assertTrue(out["can_purchase"])
        self.assertNotIn("engine_reason", out)
        self.assertNotIn("reason", out)

    def test_a_puppet_says_so_instead_of_calling_the_building_unbuildable(self):
        """productionpopup.lua returns early for a puppet, so no screen and no tooltip exist.

        Live t205: Tiwanaku, a puppet that follows our religion and has no Pagoda, refused a faith
        Pagoda as "cannot be bought here at all" with nothing else to go on."""
        out = self._cost("''", puppet=True)
        self.assertIn("puppet", out["reason"])
        self.assertIn("annex", out["reason"])

    def test_venice_can_still_buy_in_its_puppets(self):
        """MayNotAnnex() is the one case the stock popup lets through for a puppet."""
        out = self._cost("''", puppet=True, venice=True)
        self.assertNotIn("puppet", out["reason"])

    def test_an_unaffordable_item_is_priced_out_before_it_is_called_unbuildable(self):
        """Live t205: a 1050-gold Factory against 385 gold read as "cannot be bought here at all"
        while the engine's own tooltip said "You do not have enough Gold to buy this."."""
        out = self._cost("'You do not have enough Gold to buy this.'", yield_type="GOLD", listed=True)
        self.assertEqual(out["reason"], "not enough gold (385 of 900)")
        self.assertEqual(out["engine_reason"], "You do not have enough Gold to buy this.")

    def test_no_buy_button_is_never_a_price_gap(self):
        """Live t42 (v225): Venice's Settler read "not enough gold (189 of 370)"; Venice can never have one."""
        out = self._cost("''", yield_type="GOLD", listed=False)
        self.assertNotIn("not enough", out["reason"])


if __name__ == "__main__":
    unittest.main()
