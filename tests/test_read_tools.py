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
