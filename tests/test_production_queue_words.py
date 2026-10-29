"""A city's production queue never loses an item without a word (GitLab #114).

Live Maya t153 / t182: a replacing produce dropped three queued items and the reply said nothing; t172: the
dequeue refusal did not say position is 1-based and 1 the current build; t173-t178: Korea completed the Porcelain
Tower and Palenque's queued copy left the queue silently, the city idle five turns later.
"""
import unittest
from unittest import mock

import test_mcp_safety as support
from harness.game import Game
from harness.surface import dispatch as D


class ReplacedQueueTests(unittest.TestCase):
    def _game(self, before, append_queue):
        g = Game.__new__(Game)
        g.seat = 0
        g._pid = lambda pid=None: 0
        g.h = Game.h.__get__(g)
        calls = []

        def q(call, timeout=None):
            calls.append(call.fn)
            if call.fn == "production_check":
                return {"ok": True, "id": 5}
            if call.fn == "city_push_order":
                return {"ok": True, "before": before}
            if call.fn == "city_queue":
                return {"ok": True, "production": "Theatre", "turns": 6, "queue": append_queue}
            return {"ok": True}
        g.q = q
        return g

    def test_a_replacing_produce_names_what_it_dropped(self):
        g = self._game(["BUILDING_WORKSHOP", "BUILDING_AMPHITHEATER", "BUILDING_GARDEN"], ["BUILDING_THEATRE"])
        with mock.patch("harness.game.time.sleep", lambda s: None):
            r = g.set_production(8192, "ORDER_CONSTRUCT", "BUILDING_THEATRE")
        self.assertTrue(r["ok"])
        self.assertEqual(r["replaced"], ["BUILDING_WORKSHOP", "BUILDING_AMPHITHEATER", "BUILDING_GARDEN"])
        self.assertIn("append: true adds behind", r["note"])

    def test_an_append_and_an_empty_queue_say_nothing(self):
        g = self._game(["BUILDING_WORKSHOP"], ["BUILDING_WORKSHOP", "BUILDING_THEATRE"])
        with mock.patch("harness.game.time.sleep", lambda s: None):
            r = g.set_production(8192, "ORDER_CONSTRUCT", "BUILDING_THEATRE", append=True)
        self.assertNotIn("replaced", r)
        g = self._game([], ["BUILDING_THEATRE"])
        with mock.patch("harness.game.time.sleep", lambda s: None):
            r = g.set_production(8192, "ORDER_CONSTRUCT", "BUILDING_THEATRE")
        self.assertNotIn("replaced", r)

    def test_the_dequeue_shape_refusal_says_one_based(self):
        r = D.resolve("order", {"to": "city", "action": "dequeue"}, {"id": 8192, "index": 1})
        self.assertIsInstance(r, D.Refusal)
        self.assertIn("1 is the item being built now", r.err)
        self.assertIn("does not take index", r.err)


WORLD = """
GameInfo = GameInfo or {}
GameInfo.Buildings = { BUILDING_PORCELAIN_TOWER = { ID = 40 }, BUILDING_LIBRARY = { ID = 41 } }
GameInfo.Units = { UNIT_WARRIOR = { ID = 1 } }
GameInfo.Projects = { PROJECT_APOLLO_PROGRAM = { ID = 3 } }
Teams = { [0] = { GetProjectCount = function() return 0 end } }
RECORDED = {}
H.record = function(kind, data, audience) RECORDED[#RECORDED + 1] = { kind = kind, data = data, audience = audience } end
QUEUES = {}
H.queue_items = function(city) return QUEUES[city:GetID()] or {} end
function city(id, name, has, can)
  return { GetID = function() return id end, GetName = function() return name end, GetTeam = function() return 0 end,
           IsHasBuilding = function(_, b) return has[b] == true end,
           CanConstruct = function(_, b) return can[b] ~= false end,
           CanTrain = function() return true end, CanCreate = function() return true end }
end
CITIES = {}
Players = { [0] = { Cities = function() local i = 0; return function() i = i + 1; return CITIES[i] end end } }
"""


class QueueWatchLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_a_queued_wonder_built_elsewhere_is_an_event_and_a_completed_one_is_not(self):
        self.run_lua("""
        CITIES = { city(1, 'Palenque', {}, { [40] = false }), city(2, 'Tikal', { [41] = true }, {}) }
        QUEUES = { [1] = { 'BUILDING_MUSICIANS_GUILD', 'BUILDING_PORCELAIN_TOWER' }, [2] = { 'BUILDING_LIBRARY', 'UNIT_WARRIOR' } }
        H.queue_snapshot(0)
        -- the turn passes: Korea built the Tower (Palenque cannot construct it now); Tikal finished its Library
        -- and trained its Warrior
        QUEUES = { [1] = { 'BUILDING_MUSICIANS_GUILD' }, [2] = {} }
        H.queue_compare(0)
        assert(#RECORDED == 1, H.json(RECORDED))
        assert(RECORDED[1].kind == 'production_dropped' and RECORDED[1].audience == 0, H.json(RECORDED[1]))
        assert(RECORDED[1].data.city == 1 and RECORDED[1].data.name == 'Palenque' and RECORDED[1].data.item == 'BUILDING_PORCELAIN_TOWER', H.json(RECORDED[1]))
        assert(RECORDED[1].data.reason:find('wonder completed elsewhere', 1, true), RECORDED[1].data.reason)
        assert(H.queue_snap[0] == nil, 'the snapshot is spent')
        H.queue_compare(0)
        assert(#RECORDED == 1, 'nothing to compare against twice')
        """)

    def test_an_item_still_buildable_that_left_the_queue_is_the_seats_own_doing(self):
        self.run_lua("""
        CITIES = { city(1, 'Palenque', {}, {}) }
        QUEUES = { [1] = { 'BUILDING_LIBRARY' } }
        H.queue_snapshot(0)
        QUEUES = { [1] = { 'UNIT_WARRIOR' } }
        H.queue_compare(0)
        assert(#RECORDED == 0, H.json(RECORDED))
        """)


if __name__ == "__main__":
    unittest.main()
