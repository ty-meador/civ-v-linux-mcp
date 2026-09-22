"""An empty trade-route list has to say why it is empty.

Stock puts the Create Trade Route button on the unit panel only while the trade unit stands in one
of my own cities, and the chooser it opens can still come up empty when nothing is in range. The
harness returned a bare `[]` for both, and `overview.idle_trade_units` listed every caravan as idle
whether or not it could be given a route -- live t221, three caravans walking home with 0 moves.
"""
import unittest

import test_mcp_safety as support

WORLD = """
GameDefines = { MOVE_DENOMINATOR = 60 }
GameInfo = { Units = {[3] = {Type = 'UNIT_CARAVAN'}} }
Map = {
  PlotDistance = function(x1, y1, x2, y2)
    return math.max(math.abs(x1 - x2), math.abs(y1 - y2))
  end,
}
destinations = {}
moves = 120

local function city(name, x, y, owner)
  return { GetName = function() return name end, GetX = function() return x end,
           GetY = function() return y end, GetOwner = function() return owner or 0 end }
end
capital = city('Moson Kahni', 49, 19)
far = city('Goshute', 46, 29)

function make_unit(x, y, on_city)
  local plot = { IsCity = function() return on_city ~= nil end,
                 GetPlotCity = function() return on_city end }
  return { GetID = function() return 671748 end, GetX = function() return x end,
           GetY = function() return y end, GetPlot = function() return plot end,
           IsTrade = function() return true end, IsAutomated = function() return false end,
           MovesLeft = function() return moves end,
           GetUnitType = function() return 3 end }
end
field_unit = make_unit(46, 18, nil)
city_unit = make_unit(49, 19, capital)

player = {
  GetID = function() return 0 end,
  GetUnitByID = function() return unit_under_test end,
  Cities = function()
    local list, i = {capital, far}, 0
    return function() i = i + 1; return list[i] end
  end,
  Units = function()
    local list, i = my_units, 0
    return function() i = i + 1; return list[i] end
  end,
  GetPotentialInternationalTradeRouteDestinations = function() return destinations end,
}
Players = { [0] = player }
unit_under_test = field_unit
my_units = { field_unit }
"""


class TradeRouteReasonTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_a_unit_in_the_field_is_told_where_to_take_it(self):
        self.run_lua("""
        local r = H.available_trade_routes(671748, 0)
        assert(r.ok == false and #r.routes == 0)
        assert(r.err:find('inside one of my own cities') and r.err:find('46,18'), r.err)
        assert(r.nearest_city.name == 'Moson Kahni' and r.nearest_city.distance == 3,
               'the nearest city is the one to walk to (mock metric; live hex distance was 4)')
        assert(r.hint:find('Moson Kahni'), r.hint)
        assert(r.moves_left == 0 or r.note == nil, 'no moves note while it can still move')
        """)

    def test_no_moves_left_is_part_of_the_answer(self):
        self.run_lua("""
        moves = 0
        local r = H.available_trade_routes(671748, 0)
        assert(r.moves_left == 0 and r.note:find('no moves left'), tostring(r.note))
        """)

    def test_in_a_city_with_nothing_in_range_says_so_instead(self):
        self.run_lua("""
        unit_under_test = city_unit
        local r = H.available_trade_routes(671748, 0)
        assert(r.ok == false and r.err:find('Moson Kahni') and r.err:find('in range'), r.err)
        assert(r.nearest_city == nil, 'it is already in a city; do not send it anywhere')
        """)

    def test_a_real_destination_still_comes_back_as_a_plain_list(self):
        """The success shape is the one every caller already reads."""
        self.run_lua("""
        YieldTypes = { YIELD_GOLD = 0, YIELD_SCIENCE = 1, YIELD_FOOD = 2, YIELD_PRODUCTION = 3,
                       YIELD_CULTURE = 4, YIELD_FAITH = 5 }
        Map.GetPlot = function() return { GetPlotCity = function()
          return { GetName = function() return 'Harar' end, GetOwner = function() return 4 end } end } end
        Players[4] = { GetCivilizationDescription = function() return 'Ethiopia' end }
        destinations = { { X = 30, Y = 30, TradeConnectionType = 0,
                           Yields = { {Mine = 611, Theirs = 200}, {Mine = 0, Theirs = 0} } } }
        local r = H.available_trade_routes(671748, 0)
        assert(r.ok == nil and #r == 1, 'a non-empty answer stays a bare list')
        assert(r[1].city_name == 'Harar' and r[1].gold == 6.11 and r[1].kind == 'international')
        """)

    def test_a_non_trade_unit_is_refused_by_name(self):
        self.run_lua("""
        unit_under_test = { IsTrade = function() return false end }
        local r = H.available_trade_routes(671748, 0)
        assert(r.ok == false and r.err:find('caravan'), r.err)
        unit_under_test = nil
        assert(H.available_trade_routes(1, 0).err == 'no such unit')
        """)

    def test_the_overview_says_which_idle_caravans_can_actually_be_used(self):
        self.run_lua("""
        my_units = { field_unit, city_unit }
        local rows = H.idle_trade_units(player, 0)
        assert(#rows == 2)
        local field, home = rows[1], rows[2]
        assert(field.in_city == false and field.nearest_city.name == 'Moson Kahni', 'field caravan')
        assert(field.hint:find('move it'), field.hint)
        assert(home.in_city == 'Moson Kahni' and home.hint == nil, 'one standing in a city is ready')
        """)


if __name__ == "__main__":
    unittest.main()
