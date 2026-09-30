"""The server's read/response/anytime classification of its tools is complete and agrees with the call ledger.

A tool the server does not know as a read is treated as an order: refused while a popup or a leader remark is
pending, and it claims the turn for its process (GitLab #41). Seven reads had drifted off the server's own
list by 2026-09-27 (notification_log, todo_actions, revealed_map, the *_options readers); the list is now the
ledger's, and this keeps a new read from drifting again.
"""
import re
import unittest
from pathlib import Path

from harness import call_ledger as L
from harness import mcp_server as m

ROOT = Path(__file__).resolve().parent.parent
READ_LIKE = re.compile(r"^(available_|.*_options$|.*_status$|.*_overview$|.*_progress$|.*_catalog$|.*_log$|"
                       r"orders$|spies$|units$|cities$|players$|diplomacy$|demographics$|overview$)")


def tool_names() -> set[str]:
    src = "\n".join(p.read_text() for p in [ROOT / "harness" / "mcp_server.py", *sorted((ROOT / "harness" / "mcp_tools").glob("*.py"))])
    return set(re.findall(r"@mcp\.tool\(\)\s*\n(?:@guarded\s*\n)?def (\w+)", src))


class ReadToolsTests(unittest.TestCase):
    def test_every_ledger_read_is_a_server_read(self):
        self.assertEqual(L.READ_TOOLS - m.READ_TOOLS, set())

    def test_a_read_named_like_one_is_classified(self):
        classified = m.READ_TOOLS | m.RESPONSE_TOOLS | m.ANYTIME_TOOLS | m.WAIT_TOOLS | m.MENU_TOOLS
        unclassified = {t for t in tool_names() if t not in classified and READ_LIKE.match(t)}
        self.assertEqual(unclassified, set(), "a read the server would treat as an order")

    def test_orders_are_not_reads(self):
        for tool in ("move_unit", "unit_mission", "set_production", "set_research", "end_turn", "declare_war",
                     "give_order", "remember"):
            self.assertNotIn(tool, m.READ_TOOLS, tool)

    def test_a_read_skips_every_refusal(self):
        class G:
            seat = 1
            def discussion_pending(self):
                return True
        ts = {"paused": True, "processing": False, "my_turn": False, "blocking_name": "", "pending_popups": [],
              "active_player": 1, "turn": 3}
        self.assertIsNone(m._refusal_for(G(), ts, "notification_log"))
        self.assertIsNotNone(m._refusal_for(G(), ts, "move_unit"))


class ProductionOrderTests(unittest.TestCase):
    def test_prefix_picks_the_order_and_junk_is_none(self):
        self.assertEqual(m._production_order("UNIT_WARRIOR"), "ORDER_TRAIN")
        self.assertEqual(m._production_order("building_monument"), "ORDER_CONSTRUCT")
        self.assertEqual(m._production_order("PROJECT_APOLLO_PROGRAM"), "ORDER_CREATE")
        self.assertEqual(m._production_order("PROCESS_WEALTH"), "ORDER_MAINTAIN")
        self.assertIsNone(m._production_order("BOGUS_THING"))
        self.assertIsNone(m._purchase_order("PROCESS_WEALTH"))
        self.assertEqual(m._purchase_order("BUILDING_MARKET"), "ORDER_CONSTRUCT")


class ProductionNameResolutionTests(unittest.TestCase):
    """set_production("Zoo") / ("BUILDING_ZOO"): the chooser's button name resolves to the enum in the city's list
    (live t151: BNW's Zoo is BUILDING_THEATRE; the guess got did_you_mean of unrelated buildings)."""

    class G:
        def __init__(self, items):
            self.items = items
            self.calls = []
            self.seat = 0
        def turn_state(self, pid=None):
            import test_set_seat as seat_support
            return seat_support.FakeGame(mode="hotseat", humans=(0, 1), active=0, seat=0).turn_state(pid)
        def discussion_pending(self):
            return False
        def available_production(self, city_id):
            return {"ok": True, "items": self.items}
        def set_production(self, city_id, order, item, append=False):
            self.calls.append((order, item, append))
            return {"ok": True, "queue": [item]} if item == "BUILDING_THEATRE" else {"ok": False, "err": "unknown item"}

    ITEMS = [{"item": "BUILDING_THEATRE", "name": "Zoo", "kind": "building"},
             {"item": "UNIT_PIKEMAN", "name": "Pikeman", "kind": "unit"},
             {"item": "PROCESS_WEALTH", "name": "Wealth", "kind": "process"}]

    def test_a_button_name_resolves_to_its_enum(self):
        g = self.G(self.ITEMS)
        self.assertEqual(m._resolve_production_name(g, 1, "Zoo"), "BUILDING_THEATRE")
        self.assertEqual(m._resolve_production_name(g, 1, " zoo "), "BUILDING_THEATRE")
        self.assertEqual(m._resolve_production_name(g, 1, "BUILDING_ZOO"), "BUILDING_THEATRE")
        self.assertEqual(m._resolve_production_name(g, 1, "UNIT_ZOO"), "BUILDING_THEATRE")   # the tail alone
        self.assertIsNone(m._resolve_production_name(g, 1, "Aquarium"))
        self.assertIsNone(m._resolve_production_name(g, 1, "BUILDING_THEATRE"))   # an enum is not a name
        self.assertIsNone(m._resolve_production_name(self.G([]), 1, "Zoo"))

    def test_two_items_with_one_name_do_not_resolve(self):
        g = self.G(self.ITEMS + [{"item": "BUILDING_ZOO_X", "name": "Zoo", "kind": "building"}])
        self.assertIsNone(m._resolve_production_name(g, 1, "Zoo"))

    def test_set_production_uses_the_resolved_enum_and_says_so(self):
        import json
        from unittest import mock
        g = self.G(self.ITEMS)
        with mock.patch.object(m, "game", lambda: g), mock.patch.object(m, "_seat_rechecked", True):
            r = json.loads(m.set_production(1, "Zoo"))
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["resolved"], {"asked": "Zoo", "item": "BUILDING_THEATRE"})
        self.assertEqual(g.calls, [("ORDER_CONSTRUCT", "BUILDING_THEATRE", False)])
