"""A captured-city row must not carry an id that resolves to the wrong city.

Civ5 city ids are per-player, and SerialEventCityCaptured hands over the *previous* owner's id.
Live t190 (Shoshone vs the Inca): capturing Cusco recorded {player: 2, city: 8192, by: 0}, and 8192
looked up in cities() is our own capital, Moson Kahni. An id that silently resolves to the wrong
city is worse than no id at all.
"""
import unittest

import test_mcp_safety as support


WORLD = """
Game.GetActivePlayer=function() return 0 end
ToGridFromHex=function(hx, hy) return hx + 8, hy end
Map={GetPlot=function(x, y)
  if x == 42 and y == 23 then
    return {GetPlotCity=function()
      return {GetName=function() return 'Cusco' end,
              GetID=function() return 65543 end,
              GetOwner=function() return 0 end}
    end}
  end
  return {GetPlotCity=function() return nil end}
end}

-- Replay the engine hook's payload the way runtime.lua builds it.
function capture(hex, playerID, cityID, newPlayerID)
  local d = { player = playerID, by = newPlayerID, former_city_id = cityID }
  if hex then d.x, d.y = ToGridFromHex(hex.x, hex.y) end
  pcall(function()
    local pl = (d.x and d.y) and Map.GetPlot(d.x, d.y) or nil
    local c = pl and pl:GetPlotCity()
    if c then d.name, d.city_id, d.owner = c:GetName(), c:GetID(), c:GetOwner() end
  end)
  H.record('city_captured', d)
  return d
end
"""


class CityCapturedEventTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_the_row_names_the_city_and_its_new_id(self):
        self.run_lua("""
        local d = capture({x = 34, y = 23}, 2, 8192, 0)
        assert(d.name == 'Cusco', tostring(d.name))
        assert(d.city_id == 65543, tostring(d.city_id))
        assert(d.x == 42 and d.y == 23, tostring(d.x) .. ',' .. tostring(d.y))
        assert(d.owner == 0)
        """)

    def test_the_previous_owners_id_is_not_offered_as_a_city_id(self):
        self.run_lua("""
        local d = capture({x = 34, y = 23}, 2, 8192, 0)
        assert(d.city == nil, "`city` would be read as one of OUR city ids")
        assert(d.former_city_id == 8192, tostring(d.former_city_id))
        """)

    def test_an_unreadable_plot_still_records_the_capture(self):
        """Losing the name must not lose the event -- who captured what from whom still matters."""
        self.run_lua("""
        local d = capture(nil, 2, 8192, 0)
        assert(d.name == nil and d.city_id == nil)
        assert(d.player == 2 and d.by == 0 and d.former_city_id == 8192)
        """)

    def test_the_runtime_hook_builds_the_same_shape(self):
        source = open("harness/lua/runtime.lua").read()
        hook = source[source.index('hook("SerialEventCityCaptured"'):]
        hook = hook[:hook.index("H.record(")]
        self.assertIn("former_city_id = cityID", hook)
        self.assertNotIn("city = cityID", hook)


if __name__ == "__main__":
    unittest.main()
