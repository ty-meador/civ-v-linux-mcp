"""remove_from_queue drops one queued item the way the city screen does (harness/game_parts/cities.py): the engine
call is `city:PopOrder(index, 0, 0)` with a 0-based index and NUMERIC flags -- booleans answer "bad argument #2 to
'PopOrder' (number expected, got boolean)" (live 2026-09-27, Babylon t24, a test Caravan behind the Library). The pop
is verified by re-reading the queue, as set_production verifies its push."""
import json
import re
import unittest

import test_mcp_safety as support
from harness.game import Game


def _game(replies, bodies=None):
    g = Game.__new__(Game)
    g._pid = lambda pid=None: 0
    it = iter(replies)

    def q(body, **kw):
        if bodies is not None:
            bodies.append(body)
        return next(it)
    g.q = q
    return g


class RemoveFromQueuePythonTests(unittest.TestCase):
    def setUp(self):
        import harness.game
        self._sleep = harness.game.time.sleep
        harness.game.time.sleep = lambda s: None

    def tearDown(self):
        import harness.game
        harness.game.time.sleep = self._sleep

    def test_position_is_one_based_and_checked_before_any_lua(self):
        bodies = []
        g = _game([], bodies)
        for bad in (0, -1, True, "2"):
            r = g.remove_from_queue(8192, bad)
            self.assertFalse(r["ok"], bad)
            self.assertIn("1-based", r["err"])
        self.assertEqual(bodies, [])

    def test_the_pop_uses_a_zero_based_index_and_numeric_flags(self):
        bodies = []
        g = _game([{"ok": True, "queue": ["BUILDING_LIBRARY", "UNIT_CARAVAN"]},
                   {"ok": True, "production": "Library", "turns": 8, "queue": ["BUILDING_LIBRARY"]}], bodies)
        r = g.remove_from_queue(8192, 2)
        self.assertTrue(r["ok"], r)
        self.assertIn("city:PopOrder(1, 0, 0)", bodies[0])
        self.assertNotRegex(bodies[0], r"PopOrder\([^)]*(true|false)")
        self.assertEqual(r["removed"], "UNIT_CARAVAN")
        self.assertEqual(r["queue"], ["BUILDING_LIBRARY"])
        self.assertEqual(r["production"], "Library")

    def test_an_unchanged_queue_is_a_refusal(self):
        g = _game([{"ok": True, "queue": ["BUILDING_LIBRARY", "UNIT_CARAVAN"]},
                   {"ok": True, "production": "Library", "turns": 8, "queue": ["BUILDING_LIBRARY", "UNIT_CARAVAN"]}])
        r = g.remove_from_queue(8192, 2)
        self.assertFalse(r["ok"])
        self.assertIn("still queued", r["err"])

    def test_removing_the_head_says_the_queue_is_empty(self):
        g = _game([{"ok": True, "queue": ["BUILDING_LIBRARY"]},
                   {"ok": True, "production": "", "turns": 2147483647, "queue": []}])
        r = g.remove_from_queue(8192, 1)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["removed"], "BUILDING_LIBRARY")
        self.assertIsNone(r["production"])
        self.assertIsNone(r["turns"])
        self.assertIn("set_production", r["note"])

    def test_engine_side_refusals_pass_through(self):
        g = _game([{"ok": False, "err": "the queue has 1 item(s); there is no position 3"}])
        r = g.remove_from_queue(8192, 3)
        self.assertFalse(r["ok"])
        self.assertIn("no position 3", r["err"])


class RemoveFromQueueLuaTests(unittest.TestCase):
    """The pre-check body under the real runtime (H.city_production_guard) with a stub city."""
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)

    def body(self, position):
        bodies = []
        g = _game([{"ok": False, "err": "stop"}], bodies)
        g.remove_from_queue(8192, position)
        return bodies[0]

    STUB = """
        OrderTypes = { ORDER_TRAIN = 0, ORDER_CONSTRUCT = 1, ORDER_CREATE = 2, ORDER_MAINTAIN = 3 }
        GameInfo = { Units = { [5] = { Type = 'UNIT_CARAVAN' } }, Buildings = { [9] = { Type = 'BUILDING_LIBRARY' } },
                     Projects = {}, Processes = {} }
        popped = nil
        local orders = { { 1, 9 }, { 0, 5 } }
        local city = { IsPuppet = function() return false end, GetOwner = function() return 0 end,
                       GetOrderQueueLength = function() return #orders end,
                       GetOrderFromQueue = function(_, i) return orders[i + 1][1], orders[i + 1][2] end,
                       PopOrder = function(_, i, a, b) popped = { i, type(a), type(b) } end }
        Players = { [0] = { GetCityByID = function() return city end, MayNotAnnex = function() return false end } }
    """

    def test_position_two_pops_index_one_with_numbers(self):
        self.run_lua(self.STUB)
        self.run_lua("local r = (function()\n" + self.body(2) + "\nend)()\n"
                     "assert(r.ok == true, H.json(r))\n"
                     "assert(r.queue[1] == 'BUILDING_LIBRARY' and r.queue[2] == 'UNIT_CARAVAN', H.json(r.queue))\n"
                     "assert(popped[1] == 1 and popped[2] == 'number' and popped[3] == 'number', H.json(popped))")

    def test_a_position_past_the_end_pops_nothing(self):
        self.run_lua(self.STUB)
        self.run_lua("local r = (function()\n" + self.body(3) + "\nend)()\n"
                     "assert(r.ok == false and r.err:find('no position 3'), H.json(r))\n"
                     "assert(popped == nil)")


class RemoveFromQueueToolTests(unittest.TestCase):
    def test_the_tool_is_registered_beside_set_production(self):
        import harness.mcp_server as server
        self.assertTrue(callable(getattr(server, "remove_from_queue", None)))
        doc = server.remove_from_queue.__doc__ or ""
        self.assertIn("1-based", doc)
        self.assertLess(len(doc), 2000)


if __name__ == "__main__":
    unittest.main()
