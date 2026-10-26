"""Affordances as rows (GitLab #45, stage 1a of "The tool surface"): every decision the briefing lists and every
unit the todo_actions summary returns carries `actions: [{tool, args}]`, the very rows do() takes, so a turn is
played from the rows alone -- the test below types no tool name but the batch carrier's.
"""
import ast
import os
import pathlib
import unittest
from unittest import mock

import anyio

from test_set_seat import session
from test_todo_actions import NORMAL, game_answering
from harness import affordances as A
from harness import briefing as B
from harness.call_ledger import kind
from harness import gate
from harness import mcp_server as m
from harness.game import Game
from harness.surface import survey


class RowShapeTests(unittest.TestCase):
    def test_a_row_is_what_do_takes_and_a_pick_names_what_is_left_to_choose(self):
        self.assertEqual(A.act("set_research", tech="TECH_MINING"), {"tool": "set_research", "args": {"tech": "TECH_MINING"}})
        row = A.pick("set_production", ["item"], city_id=7)
        self.assertEqual(row, {"tool": "set_production", "args": {"city_id": 7}, "choose": ["item"]})
        self.assertTrue(A.is_row(row))
        self.assertFalse(A.is_row({"tool": "x"}))

    def test_every_decision_kind_opens_with_a_read_and_closes_with_the_order(self):
        for rows in (A.unit_orders(5), A.promotion(5), A.city_production(8), A.research(), A.incoming_deal(),
                     A.steal_tech(), A.policy(), A.idle_trade_unit(9), A.idle_spy(2)):
            self.assertTrue(rows and all(A.is_row(r) for r in rows), rows)
            self.assertNotIn("choose", rows[0], "the first row is a read that runs as is")
        self.assertEqual(A.promotion(5)[1]["args"], {"unit_id": 5})
        self.assertEqual(A.idle_spy(None), [])

    def test_stacked_names_the_unit_with_moves_on_each_tile(self):
        tiles = [{"x": 1, "y": 1, "units": [{"id": 6, "moves": 0}, {"id": 5, "moves": 2}]},
                 {"x": 2, "y": 2, "units": [{"id": 7, "moves": 0}]}, {"x": 3, "y": 3}]
        rows = A.stacked(tiles)
        self.assertEqual([r["args"]["unit_id"] for r in rows], [5, 5, 7, 7])
        self.assertEqual(rows[1]["choose"], ["x", "y"])

    def test_popup_rows_follow_the_gate(self):
        for name, r in gate.POPUP_RESOLUTIONS.items():
            rows = A.popup(name)
            self.assertEqual(rows[-1]["tool"], r["clear_with"])
            if r.get("read_first"):
                self.assertEqual(rows[0], A.act(r["read_first"]))
            self.assertEqual(rows[-1]["choose"], [a.strip() for a in gate.POPUP_CHOICE_ARGS[name].split(",")])
        self.assertEqual(A.popup("BUTTONPOPUP_RETURN_CIVILIAN"),
                         [A.act("generic_popup"), A.pick("answer_popup", ["button"])])

    def test_unit_actions_cover_every_kind_of_action_row(self):
        u = {"id": 9, "actions": [
            {"type": "MISSION_HEAL", "kind": "mission", "mission": "MISSION_HEAL"},
            {"type": "BUILD_FARM", "kind": "build", "mission": "MISSION_BUILD"},
            {"type": "COMMAND_UPGRADE", "kind": "command"},
            {"type": "COMMAND_GIFT", "kind": "command"}, {"type": "COMMAND_HOTKEY", "kind": "command"},
            {"type": "INTERFACEMODE_PARADROP", "kind": "interface", "mission": "MISSION_PARADROP",
             "target_tool": "unit_mission_targets"},
            {"type": "AUTOMATE_BUILD", "kind": "other"},
            {"type": "MISSION_CHANGE_TRADE_UNIT_HOME", "kind": "mission", "mission": "MISSION_CHANGE_TRADE_UNIT_HOME",
             "target_tool": "unit_home_options"}, "junk"],
            "attack_targets": [{"x": 4, "y": 4, "unit": "BRUTE"}], "ranged_targets": [{"x": 5, "y": 5}],
            "promotions": [{"promotion": "PROMOTION_SHOCK_1"}, "PROMOTION_DRILL_1"]}
        rows = A.unit_actions(u)
        self.assertEqual(rows, [
            A.act("unit_mission", unit_id=9, mission="MISSION_HEAL"),
            A.act("unit_mission", unit_id=9, mission="MISSION_BUILD", build="BUILD_FARM"),
            A.act("upgrade_unit", unit_id=9),
            A.pick("gift_unit", ["minor_id"], unit_id=9),
            A.act("unit_mission_targets", unit_id=9, mission="MISSION_PARADROP"),
            A.pick("unit_mission", ["x", "y"], unit_id=9, mission="MISSION_PARADROP"),
            A.act("unit_mission", unit_id=9, mission="AUTOMATE_BUILD"),
            A.act("unit_home_options", unit_id=9),
            A.pick("unit_mission", ["x", "y"], unit_id=9, mission="MISSION_CHANGE_TRADE_UNIT_HOME"),
            A.act("move_unit", unit_id=9, x=4, y=4),
            A.act("unit_mission", unit_id=9, mission="MISSION_RANGE_ATTACK", x=5, y=5),
            A.act("choose_promotion", unit_id=9, promotion="PROMOTION_SHOCK_1"),
            A.act("choose_promotion", unit_id=9, promotion="PROMOTION_DRILL_1"),
        ])
        self.assertEqual(A.unit_actions({"id": 1}), [])

    def test_rows_in_finds_every_actions_list_but_not_the_engine_action_dicts(self):
        reply = {"decisions": [{"kind": "research", "actions": A.research()}],
                 "units": [{"id": 1, "actions": [{"type": "MISSION_HEAL", "kind": "mission"}]}],
                 "opportunities": [{"actions": A.idle_spy(3)}]}
        self.assertEqual([r["tool"] for r in A.rows_in(reply)],
                         ["available_research", "set_research", "available_spy_cities", "move_spy"])

    def test_every_row_names_a_catalog_tool(self):
        names = {t.name for t in survey.tools()}
        u = {"id": 9, "actions": [{"type": "COMMAND_UPGRADE", "kind": "command"}, {"type": "COMMAND_DELETE", "kind": "command"},
                                  {"type": "INTERFACEMODE_NUKE", "kind": "interface", "mission": "MISSION_NUKE",
                                   "target_tool": "unit_mission_targets"}],
             "attack_targets": [{"x": 1, "y": 1}], "ranged_targets": [{"x": 1, "y": 2}], "promotions": ["PROMOTION_X"]}
        rows = (A.unit_orders(1) + A.promotion(1) + A.city_production(1) + A.research() + A.incoming_deal() + A.steal_tech()
                + A.policy() + A.stacked([{"units": [{"id": 1, "moves": 1}]}]) + A.idle_trade_unit(1) + A.idle_spy(1)
                + A.unit_actions(u) + [r for n in [*gate.POPUP_RESOLUTIONS, "BUTTONPOPUP_OTHER"] for r in A.popup(n)])
        self.assertFalse({r["tool"] for r in rows} - names)


class BriefingRowsTests(unittest.TestCase):
    def test_every_decision_and_opportunity_carries_its_rows_and_the_sentence_is_marked_for_retirement(self):
        from test_briefing import CITY, SUMMARY, status
        todo = {"units": [{"id": 5, "type": "WARRIOR", "x": 1, "y": 1, "moves": 2}], "cities": [{"id": 8192, "name": "Venice"}],
                "promotions": [7], "research_unset": True, "incoming_deal": {"from": 1}, "steal_tech": [{"player_id": 3}],
                "policy": {"culture": 500}}
        ts = status(todo=todo, blocking_name="ENDTURN_BLOCKING_UNITS", pending_popups=[{"name": "BUTTONPOPUP_CHOOSE_GOODY_HUT_REWARD"}])
        summary = {**SUMMARY, "idle_trade_units": [{"unit_id": 44, "type": "CARAVAN", "in_city": "Venice"}],
                   "idle_spies": [{"agent_id": 2, "name": "Marco"}]}
        out, _ = B.build(ts, summary, [CITY], [], {}, {"comparable": False}, None, [], limit=8, include_rules=False)
        for row in out["decisions"] + out["opportunities"]:
            if row["kind"] in ("blocker", "free_trade_route_slots"):
                continue
            self.assertTrue(row.get("actions") and all(A.is_row(r) for r in row["actions"]), row)
            self.assertNotIn("tool", row)
        by_kind = {r["kind"]: r for r in out["decisions"] + out["opportunities"]}
        self.assertEqual(by_kind["unit_orders"]["actions"], A.unit_orders(5))
        self.assertEqual(by_kind["city_production"]["actions"][1]["args"], {"city_id": 8192})
        self.assertEqual(by_kind["popup"]["actions"][0]["tool"], "goody_hut_options")
        self.assertEqual(by_kind["idle_trade_unit"]["actions"][0]["args"], {"unit_id": 44})
        self.assertEqual(by_kind["idle_spy"]["actions"][1]["args"], {"agent_id": 2})
        self.assertIn("unit_orders", out["tools"], "the sentence stays one release")
        self.assertIn("retired in 2.0.0", out["tools_note"])


# --- a turn played from the rows alone -----------------------------------------------------------------
PRODUCTION = {"ok": True, "items": [{"item": "UNIT_WARRIOR", "kind": "unit", "turns": 5}]}
RESEARCH = [{"tech": "TECH_MINING", "cost": 35, "name": "Mining"}]


class FakeGame:
    """The fake bridge: reads answer with live-shaped replies, writes are recorded."""
    seat = 0
    settle_announcements = None   # the guard's optional sweep of announcement screens: none to sweep

    def __init__(self):
        self.writes = []
        self._units = game_answering(NORMAL)

    def has_state(self, name):
        return True

    def mode(self):
        return "single"

    def turn_state(self, pid=None):
        todo = {"units": [{"id": u["id"], "type": u["type"], "x": u["x"], "y": u["y"], "moves": u["moves"]}
                          for u in NORMAL["units"]],
                "cities": [{"id": 8192, "name": "Venice"}], "promotions": [11], "research_unset": True}
        return {"turn": 270, "active_player": 0, "my_turn": True, "processing": False, "paused": False,
                "hotseat": False, "mode": "single", "blocking_name": "ENDTURN_BLOCKING_UNITS", "todo": todo,
                "pending_popups": []}

    def discussion_pending(self):
        return False

    def clear_hand_off(self, ts):
        return ts

    def todo_actions(self, unit_ids=None, full=False, detail=None, limit=None):
        return Game.todo_actions(self._units, unit_ids, full, detail=detail, limit=limit)

    def available_production(self, city_id):
        return PRODUCTION

    def available_research(self):
        return RESEARCH

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def write(*a, **kw):
            self.writes.append((name, a, kw))
            return {"ok": True}
        return write


def fill(row: dict, read_reply) -> dict:
    """A `choose` argument takes the first value under the same key anywhere in the read's reply."""
    args = dict(row["args"])
    for key in row.get("choose") or []:
        stack = [read_reply]
        while stack:
            v = stack.pop()
            if isinstance(v, dict):
                if key in v:
                    args[key] = v[key]
                    break
                stack.extend(v.values())
            elif isinstance(v, list):
                stack.extend(v)
    return {"tool": row["tool"], "args": args}


class TurnFromRowsTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeGame()
        self.patches = [mock.patch.object(m, "game", lambda: self.fake),
                        mock.patch.dict(os.environ, {"CIV5_TUNERD_SOCK": "/tmp/civ5-test-rows.sock", "CIV5_SEAT": "0"}),
                        mock.patch.object(m, "_seat_rechecked", True),
                        mock.patch.dict(m._RECENT, {}, clear=True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _do(self, rows):
        return anyio.run(session, [(BATCH, {"actions": rows})])[0]["results"]

    def test_a_turn_plays_from_the_todo_rows_alone(self):
        decisions = B.decisions(self.fake.turn_state(), [{"id": 8192, "name": "Venice"}])
        reads = [row for d in decisions for row in d["actions"] if "choose" not in row]
        results = self._do(reads)
        self.assertFalse([r for r in results if isinstance(r["result"], dict) and r["result"].get("ok") is False], results)
        replies = {i: r["result"] for i, r in enumerate(results)}
        orders = []
        for d in decisions:
            own_reads = [i for i, r in enumerate(reads) if r in d["actions"]]
            read_reply = replies[own_reads[0]] if own_reads else {}
            # a unit's read hands back the unit's own rows (its complete orders are played, its further reads
            # and half-chosen rows are not); the other reads hand back the values to choose
            orders.extend(r for r in A.rows_in(read_reply) if "choose" not in r and kind(r["tool"]) == "write")
            orders.extend(fill(r, read_reply) for r in d["actions"] if "choose" in r)
        results = self._do(orders)
        self.assertTrue(all(r["result"]["ok"] for r in results), results)
        tools = {name for name, _a, _kw in self.fake.writes}
        args = {name: (a, kw) for name, a, kw in self.fake.writes}
        self.assertEqual(args["set_research"][0], ("TECH_MINING",))
        self.assertEqual(args["set_production"][0][0], 8192)
        self.assertIn("UNIT_WARRIOR", args["set_production"][0])
        self.assertIn("choose_promotion", tools)
        self.assertIn("move_unit", tools, "the warrior's melee target became a move_unit row")
        self.assertIn("unit_mission", tools, "the warrior's MISSION_HEAL became a unit_mission row")
        self.assertNotIn("unit_mission_targets", tools, "a read never lands among the writes")

    def test_the_turn_above_types_no_tool_name_but_the_batch_carrier(self):
        """Outside its assertions, the test above names no catalog tool: every call it makes came from a reply."""
        tree = ast.parse(pathlib.Path(__file__).read_text())
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "test_a_turn_plays_from_the_todo_rows_alone")
        typed = set()
        for stmt in fn.body:
            call = stmt.value if isinstance(stmt, ast.Expr) else None
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr.startswith("assert"):
                continue
            typed |= {n.value for n in ast.walk(stmt) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        names = {t.name for t in survey.tools()}
        self.assertEqual(typed & names, set())
        self.assertEqual(BATCH, "do")


BATCH = "do"


if __name__ == "__main__":
    unittest.main()
