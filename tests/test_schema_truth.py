"""Reads and schemas tell the truth: the refusal names the 2.x call, the state schema says which view takes which
selector, a produce refusal carries the engine's reason, and the notebook's contract is what give_order does
(GitLab #146, #163, #164, #166).
"""
import unittest

import test_mcp_safety as support
from harness import mcp_server as core
from harness.surface import dispatch as D


def _param(tool: str, name: str) -> str:
    return core.mcp._tool_manager.get_tool(tool).parameters["properties"][name]["description"]


class RefusalsNameTheNewCallTests(unittest.TestCase):
    def test_a_missing_id_is_refused_with_the_state_call_it_needs(self):
        r = D.resolve("state", {"what": "map", "view": "frontier"}, {"limit": 15})          # #164
        self.assertIsInstance(r, D.Refusal)
        self.assertIn("needs id", r.err)
        self.assertEqual(r.accepts, 'state(what="map", view="frontier", id: integer, limit: integer = 12)')
        self.assertNotIn("explore_frontier", r.accepts)
        r = D.resolve("state", {"what": "options", "view": "trade_routes"}, {})               # #146
        self.assertTrue(r.accepts.startswith('state(what="options", view="trade_routes", id: integer'), r.accepts)
        self.assertIn("args={sort: string = 'gold'}", r.accepts, "what rides under args is shown there")

    def test_an_extra_selector_is_refused_with_the_view_s_own_arguments(self):
        r = D.resolve("state", {"what": "unit", "view": "tactical"}, {"id": 24576, "x": 27, "y": 11, "radius": 2})   # #163
        self.assertIsInstance(r, D.Refusal)
        self.assertIn("does not take x, y", r.err)
        self.assertTrue(r.accepts.startswith('state(what="unit", view="tactical", id: integer, radius: integer/null'), r.accepts)

    def test_the_digest_refusal_says_the_rule_not_the_retired_name(self):
        r = D.resolve("turn", {"action": "briefing"}, {"since": "turn", "detail": "digest"})   # #146
        self.assertIsInstance(r, D.Refusal)
        self.assertIn("detail='digest' takes no since", r.err)
        self.assertEqual(r.accepts, 'turn(action="briefing", detail="digest")')

    def test_an_ambiguous_view_lists_the_new_calls(self):
        for key, names in D.INDEX.items():
            if len(names) > 1 and key not in D.DISAMBIGUATE:
                r = D.pick(key, {})
                if isinstance(r, D.Refusal) and r.accepts:
                    for a in r.accepts:
                        self.assertTrue(a.startswith(key[0].partition(":")[0] + "("), a)


class StateSchemaTests(unittest.TestCase):
    def test_x_and_y_are_the_map_s_and_the_tactical_view_takes_radius_alone(self):
        self.assertIn("map/window", _param("state", "x"))
        self.assertNotIn("tactical", _param("state", "x"))
        self.assertIn("unit/tactical: tiles around the unit", _param("state", "radius"))
        self.assertIn("map/frontier", _param("state", "id"))
        doc = core.mcp._tool_manager.get_tool("state").description
        self.assertIn("radius alone for unit/tactical", doc)
        self.assertIn("id for map/frontier", doc)


class NotebookContractTests(unittest.TestCase):
    def test_the_description_says_an_order_runs_now_and_steps_follow_each_other(self):
        doc = core.mcp._tool_manager.get_tool("notebook").description
        self.assertNotIn("one step per turn", doc)
        self.assertNotIn("nothing here moves a unit now", doc)
        self.assertIn("run its first steps NOW", doc)
        self.assertIn("each step runs at most once per turn and the next starts as soon as one completes", doc)
        self.assertLess(len(doc), 2000, "the client shows about 2000 characters of a description")


PRODUCTION_WORLD = """
GameInfoTypes = { UNIT_ARCHAEOLOGIST = 4 }
GameInfo = { Units = { [4] = { Type = 'UNIT_ARCHAEOLOGIST', Class = 'UNITCLASS_ARCHAEOLOGIST' } },
             UnitClasses = { UNITCLASS_ARCHAEOLOGIST = { ID = 4, MaxPlayerInstances = -1 } } }
TIP = '[COLOR_WARNING_TEXT]Requires the University in this City.[ENDCOLOR]'
WHY = {}
H.production_why = function() return WHY end
city = { IsPuppet = function() return false end, CanTrain = function() return false end,
         CanTrainTooltip = function(_, id) return TIP end, GetOrderQueueLength = function() return 0 end }
Players = { [0] = { GetCityByID = function() return city end, MayNotAnnex = function() return false end } }
"""


class ProduceRefusalLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(PRODUCTION_WORLD)

    def test_the_refusal_carries_the_engine_s_reason_when_no_rule_is_named(self):
        self.run_lua("""
        local r = H.production_check(1, 'ORDER_TRAIN', 'UNIT_ARCHAEOLOGIST', 0)
        assert(r.ok == false and r.err == 'city cannot build this: Requires the University in this City.', H.json(r))
        assert(r.engine_reason == 'Requires the University in this City.', H.json(r))
        assert(r.why == nil)
        -- a rule the ladder names stays the refusal; the engine's sentence rides beside it
        WHY = { 'needs the tech Archaeology' }
        r = H.production_check(1, 'ORDER_TRAIN', 'UNIT_ARCHAEOLOGIST', 0)
        assert(r.err == 'city cannot build this: needs the tech Archaeology' and r.engine_reason, H.json(r))
        -- no tooltip: the old three-way guess
        WHY, TIP = {}, ''
        r = H.production_check(1, 'ORDER_TRAIN', 'UNIT_ARCHAEOLOGIST', 0)
        assert(r.err:find('missing prereq', 1, true) and r.engine_reason == nil, H.json(r))
        """)


if __name__ == "__main__":
    unittest.main()
