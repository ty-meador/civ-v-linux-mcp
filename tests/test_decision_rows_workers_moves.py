"""Every worker build and every move is a row to copy (GitLab #102, #135).

Maya t31: build_plots listed a mine two plots away with no call, and MISSION_BUILD with that plot answered "not
currently legal"; Denmark t20: the move row carried no plot, the tactical view's open neighbours no call, and the
targets read refused MISSION_MOVE_TO with an empty list.
"""
import unittest

import test_mcp_safety as support
from harness import affordances as A
from harness.game import Game
from harness.game_parts.support import _summary_unit_row


class RowsTests(unittest.TestCase):
    def test_a_move_row_carries_the_tactical_read_and_the_plot_to_choose(self):
        rows = A.action_rows(32770, {"kind": "mission", "type": "MISSION_MOVE_TO", "mission": "MISSION_MOVE_TO"})
        self.assertEqual(rows[0], {"tool": "inspect", "args": {"what": "unit", "view": "tactical", "id": 32770}})
        self.assertEqual((rows[1]["tool"], rows[1]["args"]["action"], rows[1]["choose"]), ("order", "move", ["x", "y"]))
        route = A.action_rows(32770, {"kind": "mission", "type": "MISSION_ROUTE_TO", "mission": "MISSION_ROUTE_TO"})
        self.assertEqual(route[0]["args"]["view"], "tactical")
        self.assertEqual(route[1]["args"]["args"]["mission"], "MISSION_ROUTE_TO")

    def test_a_build_plot_carries_one_order_per_build_and_the_summary_keeps_them(self):
        calls = A.build_plot_calls(65540, {"x": 35, "y": 62, "builds": ["BUILD_MINE", "BUILD_FARM"], "resource": "IRON"})
        self.assertEqual([c["args"]["args"] for c in calls],
                         [{"mission": "MISSION_BUILD", "build": "BUILD_MINE", "x": 35, "y": 62},
                          {"mission": "MISSION_BUILD", "build": "BUILD_FARM", "x": 35, "y": 62}])
        row = _summary_unit_row({"id": 65540, "type": "WORKER", "x": 34, "y": 62, "moves": 2, "actions": [],
                                 "nearby_builds": [{"x": 35, "y": 62, "builds": ["BUILD_MINE"], "resource": "IRON", "build_info": []}]})
        self.assertEqual(row["build_plots"][0]["calls"][0]["args"]["id"], 65540)
        u = {"id": 65540, "actions": [], "nearby_builds": [{"x": 35, "y": 62, "builds": ["BUILD_MINE"]}]}
        A.annotate_unit(u)
        self.assertEqual(len(u["nearby_builds"][0]["calls"]), 1)


class RemoteBuildTests(unittest.TestCase):
    def _game(self, pos, give_result):
        g = Game.__new__(Game)
        g.seat = 0
        g._pid = lambda pid=None: 0
        g.h = Game.h.__get__(g)
        given = []
        g.q = lambda call, timeout=None: {"ok": True, "x": pos[0], "y": pos[1], "moves": 2} if call.fn == "unit_pos" else {"ok": True}
        g.give_order = lambda uid, steps, purpose="", **kw: given.append((uid, steps, purpose)) or give_result
        return g, given

    def test_a_build_elsewhere_becomes_a_walk_then_build_order(self):
        g, given = self._game((34, 62), {"ok": True, "order": {"id": 3, "status": "walking"}})
        r = g.unit_mission(65540, "MISSION_BUILD", 35, 62, build="BUILD_MINE")
        self.assertTrue(r["ok"])
        self.assertEqual(given, [(65540, [{"kind": "move", "x": 35, "y": 62}, {"kind": "build", "build": "BUILD_MINE"}], "build BUILD_MINE at (35,62)")])
        self.assertEqual(r["remote_build"], {"build": "BUILD_MINE", "x": 35, "y": 62})
        self.assertIn("walks it to (35,62)", r["note"])

    def test_a_refused_order_says_the_unit_must_stand_there(self):
        g, _given = self._game((34, 62), {"ok": False, "err": "no path to (35,62)"})
        r = g.unit_mission(65540, "MISSION_BUILD", 35, 62, build="BUILD_MINE")
        self.assertFalse(r["ok"])
        self.assertIn("must stand on (35,62)", r["err"])
        self.assertIn("no path", r["err"])

    def test_the_own_plot_is_the_plain_build(self):
        g, given = self._game((35, 62), {"ok": True})
        self.assertIsNone(g._remote_build(65540, "BUILD_MINE", 35, 62))
        self.assertEqual(given, [])


class TacticalNeighbourCallsTests(unittest.TestCase):
    def test_open_neighbours_and_an_attack_carry_the_move(self):
        g = Game.__new__(Game)
        g.seat = 0
        g._pid = lambda pid=None: 0
        g.h = Game.h.__get__(g)
        g.q = lambda call, timeout=None: {"ok": True, "neighbors": [
            {"dir": "NE", "x": 52, "y": 37, "move": "open"}, {"dir": "E", "x": 53, "y": 36, "move": "refused", "why": "water"},
            {"dir": "SE", "x": 52, "y": 35, "move": "attack"}, {"dir": "W", "off_map": True, "move": "refused"}]}
        v = g.tactical_view(32770)
        calls = [(n["dir"], n.get("call", {}).get("args", {}).get("args")) for n in v["neighbors"]]
        self.assertEqual(calls, [("NE", {"x": 52, "y": 37}), ("E", None), ("SE", {"x": 52, "y": 35}), ("W", None)])


class MoveTargetsRefusalLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)

    def test_a_move_has_no_target_list_and_the_refusal_says_where_destinations_come_from(self):
        self.run_lua("""
        local stub = { __index = function() return function() return false end end }
        local unit = setmetatable({ GetDomainType = function() return 0 end, GetDropRange = function() return 0 end }, stub)
        Players = { [0] = { GetUnitByID = function() return unit end, GetTeam = function() return 0 end } }
        GameInfo = GameInfo or {}
        GameInfo.InterfaceModes = {}
        DomainTypes = { DOMAIN_AIR = 2 }
        local r = H.unit_mission_targets(1, 'MISSION_MOVE_TO', 0, 0, 100)
        assert(r.ok == false and r.err:find('a move has no target list', 1, true) and r.err:find("view='tactical'", 1, true), H.json(r))
        r = H.unit_mission_targets(1, 'MISSION_NUKE', 0, 0, 100)
        assert(r.ok == false and r.err == 'mission is not offered for this unit', H.json(r))
        """)


if __name__ == "__main__":
    unittest.main()
