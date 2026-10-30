"""The small reply gaps of milestone 2.6.0 (GitLab #126, #132, #107, #113, #118)."""
import unittest

import test_mcp_safety as support
from harness import briefing as B
from harness import orders
from harness.surface import dispatch as D
from harness.surface import forward


class DispatchTests(unittest.TestCase):
    def test_map_grid_takes_a_centre_and_a_radius(self):
        call = D.resolve("state", {"what": "map", "view": "grid"}, {"x": 10, "y": 20, "radius": 3})
        self.assertIsInstance(call, D.Call)
        self.assertEqual({k: call.args[k] for k in ("x0", "y0", "x1", "y1")}, {"x0": 7, "y0": 17, "x1": 13, "y1": 23})

    def test_city_state_and_civ_default_to_the_summary(self):
        self.assertEqual(D.resolve("state", {"what": "city_state"}, {"id": 20}).tool, "city_state_actions")
        self.assertIsInstance(D.resolve("state", {"what": "civ"}, {"id": 2}), D.Call)

    def test_a_missing_mission_or_kind_lists_the_legal_values(self):
        r = D.resolve("state", {"what": "unit", "view": "targets"}, {"id": 5})
        self.assertIsInstance(r, D.Refusal)
        self.assertIn("MISSION_FOUND", r.choices)
        r = D.resolve("state", {"what": "options", "view": "beliefs"}, {})
        self.assertIsInstance(r, D.Refusal)
        self.assertEqual(r.choices[0], "pantheon")

    def test_propose_deal_example_has_a_real_item(self):
        ex = forward.example("propose_deal")
        items = ex["args"]["args"]["items"] if "args" in ex["args"] and isinstance(ex["args"].get("args"), dict) else ex["args"]["items"]
        self.assertEqual(items[0]["type"], "GOLD_PER_TURN")


class BriefingTests(unittest.TestCase):
    def test_board_warnings_name_unconnected_cities_and_unimproved_resources(self):
        board = {"cities": [{"id": 1, "name": "Tikal", "connected": True}, {"id": 2, "name": "Palenque", "connected": False}],
                 "unimproved_resources": [{"x": 36, "y": 66, "resource": "IRON", "class": "strategic", "build": "BUILD_MINE", "city": "Palenque"}]}
        w = B.board_warnings(board)
        kinds = [r["kind"] for r in w]
        self.assertEqual(kinds, ["unconnected_cities", "unimproved_resources"])
        self.assertEqual(w[0]["cities"], [{"id": 2, "name": "Palenque"}])
        row = w[1]["plots"][0]
        self.assertEqual(row["actions"][0]["args"]["args"]["build"] if "args" in row["actions"][0]["args"] and isinstance(row["actions"][0]["args"].get("args"), dict) else row["actions"][0]["args"]["build"], "BUILD_MINE")
        self.assertEqual(B.board_warnings({"cities": [{"id": 1, "connected": True}]}), [])

    def test_settle_first_only_when_the_board_has_no_city(self):
        ts = {"todo": {"research_unset": True}}
        self.assertNotIn("note", B.decisions(ts, None)[0], "question() reads no cities: nothing said")
        self.assertIn("settle first", B.decisions(ts, [])[0]["note"])
        self.assertNotIn("note", B.decisions(ts, [{"id": 1, "name": "Tikal"}])[0])

    def test_baseline_age_is_said(self):
        self.assertIn("62 turns ago", B.baseline_state({"turn": 38}, 100, None)["note"])
        self.assertNotIn("note", B.baseline_state({"turn": 99}, 100, None))

    def test_orders_block_counts_open_rows(self):
        done = {"id": 1, "unit": {"id": 5, "type": "WORKER"}, "status": "completed", "steps": [{"kind": "move", "x": 1, "y": 1}], "step": 1}
        self.assertEqual(orders.briefing_section([done], 5)["open"], 0)
        self.assertEqual(orders.briefing_section([done], 5)["closed"], 1)

    def test_give_order_shape_refusal_names_the_shapes(self):
        with self.assertRaises(orders.OrderError) as cm:
            orders.normalize_steps([{"tool": "order", "args": {}}])
        self.assertIn("{kind: 'move', x, y}", str(cm.exception))


class LuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)

    def test_my_dead_unit_is_named_from_the_roster(self):
        self.run_lua("""
        Game = Game or {}; Game.GetActivePlayer = function() return 0 end
        Players = { [0] = { GetUnitByID = function() return nil end, GetTeam = function() return 0 end } }
        H.owner_label = function() return 'you' end
        H.roster = { [0] = { [77] = { unit = 'ATLATLIST', x = 36, y = 66 } } }
        local s = H.combat_side(0, 77)
        assert(s.unit == 'ATLATLIST' and s.x == 36 and s.killed == true and s.hp == 0, H.json(s))
        """)

    def test_a_city_state_that_fell_is_a_row(self):
        self.run_lua("""
        GameDefines = GameDefines or {}; GameDefines.MAX_MAJOR_CIVS = 2; GameDefines.MAX_CIV_PLAYERS = 4
        Game = Game or {}; Game.GetActivePlayer = function() return 0 end
        ALIVE = true
        local cap = { GetX = function() return 5 end, GetY = function() return 6 end, GetName = function() return 'Zurich' end }
        local venice = { IsAlive = function() return true end, IsMinorCiv = function() return false end, GetTeam = function() return 1 end,
                         GetCivilizationShortDescription = function() return 'Venice' end }
        Players = { [0] = { IsAlive = function() return true end, IsMinorCiv = function() return false end, GetTeam = function() return 0 end },
                    [1] = venice,
                    [2] = { IsMinorCiv = function() return true end, IsAlive = function() return ALIVE end, GetTeam = function() return 2 end,
                            GetCapitalCity = function() return cap end },
                    [3] = nil }
        Teams = { [0] = { IsHasMet = function() return true end } }
        Map = Map or {}; Map.GetPlot = function() return { GetPlotCity = function() return { GetOwner = function() return 1 end } end } end
        RECORDED = {}
        H.record = function(kind, data) RECORDED[#RECORDED + 1] = { kind = kind, data = data } end
        H.alive_majors = nil
        H.check_eliminations(0)
        assert(H.minor_caps[2].name == 'Zurich')
        ALIVE = false
        H.check_eliminations(0)
        local rows = {}
        for _, r in ipairs(RECORDED) do if r.kind == 'city_state_fell' then rows[#rows + 1] = r end end
        assert(#rows == 1 and rows[1].data.name == 'Zurich' and rows[1].data.by == 'Venice' and rows[1].data.by_player == 1, H.json(RECORDED))
        """)


if __name__ == "__main__":
    unittest.main()
