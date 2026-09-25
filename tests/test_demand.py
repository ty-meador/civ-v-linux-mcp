"""The leader screen's Demand button (GitLab #6).

leaderheadroot.lua OnDemand -> UI.OnHumanDemand(ai) opens the same DiploTrade table in
DIPLO_UI_STATE_HUMAN_DEMAND; tradelogic.lua then hides OUR pocket ("If we're demanding something, there's
no need to show OUR items"), relabels Propose as DEMAND and, on OnPropose, calls UI.DoDemand() instead of
UI.DoProposeDeal(). The button is greyed at war (OnShowHide, with Trade and Discuss) and hidden for our
own team; there is no such button for a human seat. Those gates live in _check_deal_items /
_open_trade_screen so the caller learns why before any screen opens.
"""
import unittest

import test_mcp_safety as support


class DemandLegalityTests(unittest.TestCase):
    CATALOG = {"ok": True, "at_war": False,
               "gold": {"us": True, "them": True, "us_available": 500, "them_available": 40},
               "gold_per_turn": {"us": True, "them": True, "us_available": 20, "them_available": 3},
               "resources": [{"resource": "RESOURCE_SILK", "us": False, "them": True}],
               "cities": {"us": [], "them": [{"id": 7, "name": "Sidon", "pop": 4}]},
               "peace": {"ok": False, "at_war": False, "note": "not at war"}}

    def game(self, **over):
        from harness.game import Game
        g = Game.__new__(Game)
        g.seat = 0
        g.trade_catalog = lambda other, pid=None: dict(self.CATALOG, **over)
        return g

    def check(self, *items, **over):
        return self.game(**over)._check_deal_items(1, list(items), 0, demand=True)

    def test_their_items_pass(self):
        self.assertTrue(self.check({"type": "GOLD", "from_us": False, "amount": 40})["ok"])
        self.assertTrue(self.check({"type": "RESOURCES", "resource": "RESOURCE_SILK", "from_us": False, "amount": 1})["ok"])
        self.assertTrue(self.check({"type": "CITIES", "from_us": False, "city_id": 7})["ok"])

    def test_our_own_item_is_refused_because_the_pocket_is_hidden(self):
        r = self.check({"type": "GOLD", "from_us": True, "amount": 10})
        self.assertFalse(r["ok"]); self.assertIn("from_us: false", r["err"])
        r = self.check({"type": "OPEN_BORDERS"})   # from_us defaults to true everywhere else
        self.assertFalse(r["ok"]); self.assertIn("OPEN_BORDERS", r["err"])

    def test_no_treaty_and_never_at_war(self):
        r = self.check({"type": "PEACE_TREATY"})
        self.assertFalse(r["ok"]); self.assertIn("peace treaty", r["err"])
        r = self.check({"type": "GOLD", "from_us": False, "amount": 40}, at_war=True,
                       peace={"ok": True, "at_war": True, "locked_turns": 0})
        self.assertFalse(r["ok"]); self.assertIn("Demand button is disabled", r["err"])

    def test_the_ordinary_amount_gates_still_apply(self):
        r = self.check({"type": "GOLD", "from_us": False, "amount": 400})
        self.assertFalse(r["ok"]); self.assertIn("exceeds", r["err"])

    def test_demand_marks_every_item_as_theirs(self):
        """demand() is propose_deal(demand=True) with from_us filled in, so a caller may omit it."""
        from harness.game import Game
        g = Game.__new__(Game)
        seen = {}
        g.propose_deal = lambda other, items, ask_counter=False, pid=None, demand=False: seen.update(items=items, demand=demand) or {"ok": True}
        g.demand(1, [{"type": "GOLD", "amount": 40}, {"type": "CITIES", "city_id": 7, "from_us": False}])
        self.assertTrue(seen["demand"])
        self.assertTrue(all(i["from_us"] is False for i in seen["items"]))


class LumpGoldRuleTests(unittest.TestCase):
    """Brave New World: a lump sum needs a Declaration of Friendship; the stock pocket merely hides the
    Gold row (tradelogic.lua asks IsPossibleToTradeItem(..., TRADE_ITEM_GOLD, 1)). The catalog says why.
    Engine-checked live 2026-09-25: of four met civs only the DoF partner traded lump gold either way."""

    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua("""
        GOLD_OK = false; DOF = false
        local deal={
          SetFromPlayer=function(self,a) self.from=a end,
          SetToPlayer=function(self,a) self.to=a end,
          IsPossibleToTradeItem=function(self, from, to, typ, a, b)
            if typ==1 then return GOLD_OK end
            return typ==2
          end,
          GetGoldAvailable=function() return 300 end,
        }
        UI={GetScratchDeal=function() return deal end}
        TradeableItems={TRADE_ITEM_GOLD=1, TRADE_ITEM_GOLD_PER_TURN=2, TRADE_ITEM_OPEN_BORDERS=3,
                        TRADE_ITEM_ALLOW_EMBASSY=4, TRADE_ITEM_RESEARCH_AGREEMENT=5, TRADE_ITEM_DEFENSIVE_PACT=6,
                        TRADE_ITEM_RESOURCES=7}
        Game.GetDealDuration=function() return 25 end
        Teams={[0]={IsHasMet=function() return true end, IsAtWar=function() return false end}}
        Players={[0]={GetTeam=function() return 0 end, IsDoF=function() return DOF end, CalculateGoldRate=function() return 5 end},
                 [1]={IsAlive=function() return true end, IsMinorCiv=function() return false end, GetTeam=function() return 1 end,
                      CalculateGoldRate=function() return 9 end}}
        """)

    def test_without_friendship_the_hidden_gold_row_is_explained(self):
        self.run_lua("""
        local r=H.trade_catalog(1,0)
        assert(r.gold.us==false and r.gold.them==false)
        assert(r.gold.declaration_of_friendship==false)
        assert(r.gold.note and r.gold.note:find('Declaration of Friendship'), tostring(r.gold.note))
        assert(r.gold_per_turn.us==true, 'gold per turn is not gated')
        """)

    def test_with_friendship_there_is_nothing_to_explain(self):
        self.run_lua("""
        GOLD_OK = true; DOF = true
        local r=H.trade_catalog(1,0)
        assert(r.gold.us==true and r.gold.note==nil and r.gold.declaration_of_friendship==nil)
        """)


if __name__ == "__main__":
    unittest.main()
