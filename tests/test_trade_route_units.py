"""trade_routes: which caravan is on which route (harness/lua/runtime/trade_routes.lua assign_own_caravans).

The engine's route rows name cities, not units, so a caravan is placed by standing on a route's line. Routes
share plots, and before runtime v252 two caravans from one origin swapped between reads (live t142). Now the
first read that finds a caravan on exactly one open route records the binding in H.route_units, and later
reads keep it while the unit is still an automated trade unit on that route's line and the route is the same
instance (turns_left counting down from the recorded turn).
"""
import unittest

import test_mcp_safety as support
from test_revealed_map import ROUTES

UNITS = """
local function tunit(id, x, y, auto)
  return {GetID = function() return id end, GetOwner = function() return 0 end,
    GetX = function() return x end, GetY = function() return y end, GetUnitType = function() return 0 end,
    IsTrade = function() return true end, IsAutomated = function() return auto ~= false end,
    IsCombatUnit = function() return false end, GetCurrHitPoints = function() return 100 end,
    IsInvisible = function() return false end, GetPlot = function() return Map.GetPlot(x, y) end}
end
function SET_UNITS(list) Players[0].Units = function() local i = 0; return function() i = i + 1; return list[i] end end end
function UNIT_OF(r, i) return r.outgoing[i].unit and r.outgoing[i].unit.id end
TUNIT = tunit
"""


class TradeRouteUnitTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(ROUTES)
        self.run_lua(UNITS)

    def test_a_caravan_on_one_route_is_recorded_and_the_other_follows_by_elimination(self):
        self.run_lua("""
        -- 11 at (5,5): only route A runs there. 12 at (2,5): A and B share the plot, but A is taken.
        SET_UNITS({TUNIT(12, 2, 5), TUNIT(11, 5, 5)})
        local r = H.trade_routes(0)
        assert(UNIT_OF(r, 1) == 11 and UNIT_OF(r, 2) == 12, H.json({UNIT_OF(r, 1), UNIT_OF(r, 2)}))
        assert(r.outgoing[1].unit.matched == 'line' and r.outgoing[2].unit.matched == 'line', H.json(r.outgoing))
        local m = H.route_units[0]
        assert(m[11].key == 'Moson Kahni -> Adwa' and m[12].key == 'Moson Kahni -> Addis Ababa', H.json(m))
        assert(m[11].turn == 1 and m[11].turns_left == 5 and m[12].turns_left == 2, H.json(m))
        """)

    def test_the_recorded_binding_survives_both_caravans_standing_on_a_shared_plot(self):
        self.run_lua("""
        SET_UNITS({TUNIT(12, 2, 5), TUNIT(11, 5, 5)})
        H.trade_routes(0)
        -- both back on the shared stretch, 12 listed first: the old plot match gave A to 12 and B to 11
        SET_UNITS({TUNIT(12, 1, 5), TUNIT(11, 1, 5)})
        local r = H.trade_routes(0)
        assert(UNIT_OF(r, 1) == 11 and UNIT_OF(r, 2) == 12, 'kept: ' .. H.json({UNIT_OF(r, 1), UNIT_OF(r, 2)}))
        assert(r.outgoing[1].unit.matched == 'recorded' and r.outgoing[2].unit.matched == 'recorded', H.json(r.outgoing))
        """)

    def test_nothing_recorded_on_a_shared_plot_is_said_to_be_ambiguous(self):
        self.run_lua("""
        SET_UNITS({TUNIT(12, 1, 5), TUNIT(11, 1, 5)})
        local r = H.trade_routes(0)
        assert(r.outgoing[1].unit and r.outgoing[2].unit, 'both rows still get a caravan')
        assert(r.outgoing[1].unit.matched == 'line_ambiguous' and r.outgoing[2].unit.matched == 'line_ambiguous', H.json(r.outgoing))
        assert(next(H.route_units[0]) == nil, 'an ambiguous placement is never recorded: ' .. H.json(H.route_units))
        """)

    def test_a_record_is_dropped_when_the_route_is_a_new_instance_or_the_unit_left_its_line(self):
        self.run_lua("""
        SET_UNITS({TUNIT(12, 2, 5), TUNIT(11, 5, 5)})
        H.trade_routes(0)
        -- two turns later the rows still say 5 and 2 turns left: routes re-established, not the ones recorded
        Game.GetGameTurn = function() return 3 end
        SET_UNITS({TUNIT(12, 1, 5), TUNIT(11, 1, 5)})
        local r = H.trade_routes(0)
        assert(r.outgoing[1].unit.matched == 'line_ambiguous', H.json(r.outgoing))
        Game.GetGameTurn = function() return 1 end
        -- recorded again from a telling plot; then 11 stands off route A's line (3,3 is B only)
        SET_UNITS({TUNIT(12, 2, 5), TUNIT(11, 5, 5)})
        H.trade_routes(0)
        SET_UNITS({TUNIT(11, 3, 3)})
        r = H.trade_routes(0)
        assert(UNIT_OF(r, 1) == nil and UNIT_OF(r, 2) == 11 and r.outgoing[2].unit.matched == 'line', H.json(r.outgoing))
        assert(H.route_units[0][11].key == 'Moson Kahni -> Addis Ababa' and H.route_units[0][12] == nil, 'unit 12 is gone: ' .. H.json(H.route_units))
        """)

    def test_a_caravan_no_longer_automated_loses_its_record(self):
        self.run_lua("""
        SET_UNITS({TUNIT(12, 2, 5), TUNIT(11, 5, 5)})
        H.trade_routes(0)
        SET_UNITS({TUNIT(12, 2, 5), TUNIT(11, 0, 5, false)})
        local r = H.trade_routes(0)
        assert(H.route_units[0][11] == nil and H.route_units[0][12].key == 'Moson Kahni -> Addis Ababa', H.json(H.route_units))
        assert(UNIT_OF(r, 1) == nil and UNIT_OF(r, 2) == 12, H.json(r.outgoing))
        """)

    def test_the_bindings_are_carried_across_a_runtime_reload(self):
        self.run_lua("""
        SET_UNITS({TUNIT(12, 2, 5), TUNIT(11, 5, 5)})
        H.trade_routes(0)
        """)
        support.LuaRuntimeTests.load_runtime(self)
        self.run_lua("""
        assert(H.route_units[0][11].key == 'Moson Kahni -> Adwa', 'carried: ' .. H.json(H.route_units))
        SET_UNITS({TUNIT(12, 1, 5), TUNIT(11, 1, 5)})
        local r = H.trade_routes(0)
        assert(UNIT_OF(r, 1) == 11 and r.outgoing[1].unit.matched == 'recorded', H.json(r.outgoing))
        """)


if __name__ == "__main__":
    unittest.main()
