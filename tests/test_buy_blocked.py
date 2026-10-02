"""A priced production row whose buy button is greyed out says why (runtime v255).

`available_production` carried `gold` and `can_buy` per row since v60, and nothing else: live t156
Karakorum sat on 2570 gold with every unit `can_buy: false`, and only a second call per row
(`purchase_cost`) said that a Worker on the city tile blocked them (one civilian per tile). The row now
carries `buy_blocked` {reason, text}, the same ladder purchase_cost climbs, cheap reads first:
`gold` (balance of cost, only where the buy button exists), `stacking` (with `blocking_units`),
`unbuyable` (no buy button here), the engine's own tooltip (`engine`), else `refused`. A row that can be
bought, or has no price at all, carries nothing.

Runs the shipped Lua in lupa against a stub city.
"""
import unittest

import test_mcp_safety as support

WORLD = """
YieldTypes = { YIELD_GOLD = 2, YIELD_FAITH = 5 }
Locale = { ConvertTextKey = function(k) return k end }
GOLD = 2570
TIP = ''
UNITS = { { ID = 1, Type = 'UNIT_WORKER', Combat = 0, Domain = 'DOMAIN_LAND' },
          { ID = 2, Type = 'UNIT_MUSKETMAN', Combat = 24, Domain = 'DOMAIN_LAND' },
          { ID = 3, Type = 'UNIT_CARAVAN', Combat = 0, Domain = 'DOMAIN_LAND' } }
GameInfo = {
  Units = setmetatable({ [1] = UNITS[1], [2] = UNITS[2], [3] = UNITS[3] }, { __call = function()
    local i = 0
    return function() i = i + 1; return UNITS[i] end
  end }),
  Buildings = function()
    local rows, i = { { ID = 10, Type = 'BUILDING_MARKET' }, { ID = 11, Type = 'BUILDING_STOCK_EXCHANGE' },
                      { ID = 12, Type = 'BUILDING_OXFORD_UNIVERSITY' } }, 0
    return function() i = i + 1; return rows[i] end
  end,
}
-- BUYABLE[item id] = {listed = the button exists, now = affordable and allowed right now}
BUYABLE = { [1] = { listed = true, now = false }, [2] = { listed = true, now = true },
            [3] = { listed = true, now = false },
            [10] = { listed = true, now = false }, [11] = { listed = false, now = false },
            [12] = { listed = false, now = false } }
COST = { [1] = 300, [2] = 450, [3] = 320, [10] = 500, [11] = 9000, [12] = -1 }
local worker_in_city = { GetOwner = function() return 0 end, IsCombatUnit = function() return false end,
                         GetUnitType = function() return 1 end, GetID = function() return 65540 end }
local city = {
  IsPuppet = function() return false end,
  IsProductionAutomated = function() return false end,
  CanTrain = function() return true end,
  CanConstruct = function() return true end,
  GetOwner = function() return 0 end,
  Plot = function() return { GetNumUnits = function() return 1 end,
                             GetUnit = function() return worker_in_city end } end,
  GetUnitProductionTurnsLeft = function() return 3 end,
  GetBuildingProductionTurnsLeft = function() return 11 end,
  GetUnitPurchaseCost = function(_, id) return COST[id] end,
  GetBuildingPurchaseCost = function(_, id) return COST[id] end,
  IsCanPurchase = function(_, test_cost, test_train, uid, bid)
    local b = BUYABLE[uid >= 0 and uid or bid]
    if test_cost then return b.now end
    return b.listed
  end,
  GetPurchaseUnitTooltip = function() return TIP end,
  GetPurchaseBuildingTooltip = function() return TIP end,
}
Players = { [0] = { GetCityByID = function() return city end, GetGold = function() return GOLD end } }
"""


class BuyBlockedTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def rows(self):
        return self.run_lua("""
        local r = H.available_production(1, 0)
        assert(r.ok, r.err)
        local by = {}
        for _, e in ipairs(r.items) do by[e.item] = e end
        BY = by
        return by
        """)

    def test_a_worker_on_the_tile_names_the_stacking_rule_with_the_unit(self):
        self.rows()
        self.run_lua("""
        local w, c = BY['UNIT_WORKER'], BY['UNIT_CARAVAN']
        assert(w.can_buy == false and w.gold == 300)
        assert(w.buy_blocked and w.buy_blocked.reason == 'stacking', tostring(w.buy_blocked and w.buy_blocked.reason))
        assert(w.buy_blocked.blocking_units[1].unit_id == 65540 and w.buy_blocked.blocking_units[1].type == 'UNIT_WORKER')
        assert(w.buy_blocked.text:find('UNIT_WORKER already stands in the city', 1, true), w.buy_blocked.text)
        -- a Caravan is a civilian too: the same Worker blocks it
        assert(c.buy_blocked and c.buy_blocked.reason == 'stacking')
        """)

    def test_a_buyable_row_and_a_combat_unit_carry_nothing(self):
        self.rows()
        self.run_lua("""
        local m = BY['UNIT_MUSKETMAN']
        assert(m.can_buy == true and m.buy_blocked == nil, 'a row that can be bought explains nothing')
        """)

    def test_not_enough_gold_comes_before_every_other_guess(self):
        self.run_lua("GOLD = 100")
        self.rows()
        self.run_lua("""
        local w = BY['UNIT_WORKER']
        assert(w.buy_blocked.reason == 'gold', w.buy_blocked.reason)
        assert(w.buy_blocked.text == 'not enough gold (100 of 300)', w.buy_blocked.text)
        assert(w.buy_blocked.blocking_units == nil)
        """)

    def test_a_row_without_a_buy_button_is_unbuyable_and_a_priceless_one_is_silent(self):
        self.rows()
        self.run_lua("""
        local se, ox = BY['BUILDING_STOCK_EXCHANGE'], BY['BUILDING_OXFORD_UNIVERSITY']
        -- 9000 > 2570 but the button does not exist: the gold line would be a false promise
        assert(se.buy_blocked and se.buy_blocked.reason == 'unbuyable', tostring(se.buy_blocked and se.buy_blocked.reason))
        assert(ox.gold == nil and ox.buy_blocked == nil, 'a national wonder has no price and no buy_blocked')
        """)

    def test_the_engine_tooltip_is_the_fallback_before_a_shrug(self):
        self.run_lua("TIP = 'You have already purchased a unit here this turn.'")
        self.rows()
        self.run_lua("""
        local mk = BY['BUILDING_MARKET']
        assert(mk.buy_blocked.reason == 'engine', mk.buy_blocked.reason)
        assert(mk.buy_blocked.text == 'You have already purchased a unit here this turn.')
        """)
        self.run_lua("TIP = ''")
        self.rows()
        self.run_lua("""
        local mk = BY['BUILDING_MARKET']
        assert(mk.buy_blocked.reason == 'refused', mk.buy_blocked.reason)
        """)


if __name__ == "__main__":
    unittest.main()
