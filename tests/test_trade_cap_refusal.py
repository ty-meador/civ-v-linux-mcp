"""set_production on a Caravan / Cargo Ship the engine refuses names the trade-unit cap (harness/game_parts/cities.py
pre-check, H.trade_unit_count): trade units alive plus trade-unit orders queued in any city against the routes
possible -- the overview's used count is the alive half only (live t139: Venice "4 of 8" and CanTrain false)."""
import unittest

import test_mcp_safety as support
from harness.game import Game


class TradeCapRefusalTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)

    def pre_check_lua(self):
        g = Game.__new__(Game)
        g._pid = lambda pid=None: 0
        bodies = []

        def q(body, **kw):
            bodies.append(body)
            return {"ok": False, "err": "stop"}
        g.q = q
        g.set_production(8192, "ORDER_TRAIN", "UNIT_CARAVAN")
        return bodies[0]

    def test_a_refused_caravan_names_the_alive_and_queued_trade_units(self):
        self.run_lua("""
        GameInfoTypes = { UNIT_CARAVAN = 5 }
        GameInfo = { Units = { [5] = { Type = 'UNIT_CARAVAN', Class = 'UNITCLASS_CARAVAN', Trade = true } },
                     UnitClasses = { UNITCLASS_CARAVAN = { ID = 1, MaxPlayerInstances = -1 } } }
        local city = { IsPuppet = function() return false end, CanTrain = function() return false end,
                       GetOrderQueueLength = function() return 2 end,
                       GetOrderFromQueue = function(_, i) if i == 0 then return 1, 9, 9 end return 0, 5, 38 end,
                       GetOwner = function() return 0 end }
        local trade = { IsTrade = function() return true end }
        Players = { [0] = { GetCityByID = function() return city end,
                            Units = function() local l = { trade, trade }; local i = 0; return function() i = i + 1; return l[i] end end,
                            Cities = function() local l = { city }; local i = 0; return function() i = i + 1; return l[i] end end,
                            GetNumInternationalTradeRoutesAvailable = function() return 3 end,
                            MayNotAnnex = function() return false end } }
        """)
        self.run_lua("local r = (function()\n" + self.pre_check_lua() + "\nend)()\n"
                     "assert(r.ok == false and r.err:find('2 alive %+ 1 queued of 3'), H.json(r))\n"
                     "assert(r.err:find('idle_trade_units'), r.err)")

    def test_room_for_one_more_keeps_the_generic_refusal(self):
        self.run_lua("""
        GameInfoTypes = { UNIT_CARAVAN = 5 }
        GameInfo = { Units = { [5] = { Type = 'UNIT_CARAVAN', Class = 'UNITCLASS_CARAVAN', Trade = true } },
                     UnitClasses = { UNITCLASS_CARAVAN = { ID = 1, MaxPlayerInstances = -1 } } }
        local city = { IsPuppet = function() return false end, CanTrain = function() return false end,
                       GetOrderQueueLength = function() return 0 end, GetOwner = function() return 0 end }
        local trade = { IsTrade = function() return true end }
        Players = { [0] = { GetCityByID = function() return city end,
                            Units = function() local l = { trade }; local i = 0; return function() i = i + 1; return l[i] end end,
                            Cities = function() local l = { city }; local i = 0; return function() i = i + 1; return l[i] end end,
                            GetNumInternationalTradeRoutesAvailable = function() return 3 end,
                            MayNotAnnex = function() return false end } }
        """)
        self.run_lua("local r = (function()\n" + self.pre_check_lua() + "\nend)()\n"
                     "assert(r.ok == false and r.err:find('city cannot build this'), H.json(r))")


if __name__ == "__main__":
    unittest.main()
