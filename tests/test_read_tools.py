"""The server's classification of its calls -- read, response, anytime, wait, menu -- is by `(tool, action)` key
(harness/surface/classes.py, GitLab #51) and complete.

A call the server does not know as a read is treated as an order: refused while a popup or a leader remark is
pending, and it claims the turn for its process (GitLab #41). Seven reads had drifted off a hand-kept name list
by 2026-09-27; since #51 there is no name list to drift from: an old name classifies as the new call it means,
and every inspect, question and reference is a read by its tool alone.
"""
import re
import unittest
from pathlib import Path

from harness import mcp_server as m
from harness.surface import classes as C
from harness.surface import retirement as R

ROOT = Path(__file__).resolve().parent.parent
READ_LIKE = re.compile(r"^(available_|.*_options$|.*_status$|.*_overview$|.*_progress$|.*_catalog$|.*_log$|"
                       r"orders$|spies$|units$|cities$|players$|diplomacy$|demographics$|overview$)")


def tool_names() -> set[str]:
    src = "\n".join(p.read_text() for p in [ROOT / "harness" / "mcp_server.py", *sorted((ROOT / "harness" / "mcp_tools").glob("*.py"))])
    return set(re.findall(r"@mcp\.tool\(\)\s*\n(?:@guarded\s*\n)?def (\w+)", src))


class ReadToolsTests(unittest.TestCase):
    def test_every_read_is_harmless(self):
        for key in C.READ:
            self.assertIn(key, C.HARMLESS)
        self.assertIn(("notebook", "assign"), C.HARMLESS)
        self.assertNotIn(("notebook", "assign"), C.READ, "an assignment is a write in the ledger")

    def test_a_read_named_like_one_is_classified(self):
        classified = C.HARMLESS | C.RESPONSE | C.ANYTIME | C.WAIT | C.MENU
        unclassified = {t for t in tool_names() if C.of_handler(t) not in classified and READ_LIKE.match(t)}
        self.assertEqual(unclassified, set(), "a read the server would treat as an order")

    def test_every_old_name_has_a_key_in_the_vocabulary(self):
        tools = {"turn", "inspect", "order", "question", "answer", "notebook", "batch", "session", "reference"}
        for name in R.RETIRED:
            self.assertIn(C.of_handler(name)[0], tools, name)
        self.assertEqual(C.of_handler("lua"), ("lua", ""))

    def test_orders_are_not_reads(self):
        for tool in ("move_unit", "unit_mission", "set_production", "set_research", "end_turn", "declare_war",
                     "give_order", "remember"):
            self.assertNotIn(C.of_handler(tool), C.READ, tool)
            self.assertNotIn(C.of_handler(tool), C.HARMLESS, tool)

    def test_the_sets_by_action_not_name(self):
        """One tool, several kinds: `turn` reads as status, sleeps as finish; `notebook` reads as recall, writes as remember."""
        self.assertIn(C.of_call("turn", {"action": "status"}), C.READ)
        self.assertIn(C.of_call("turn", {"action": "finish"}), C.WAIT)
        self.assertNotIn(C.of_call("turn", {"action": "status"}), C.WAIT)
        self.assertIn(C.of_call("turn", {"action": "end"}), C.LEDGER_WAIT)
        self.assertNotIn(C.of_call("turn", {"action": "end"}), C.WAIT, "end_turn holds the lock; only the sleepers do not")
        self.assertIn(C.of_call("notebook", {"action": "recall"}), C.READ)
        self.assertNotIn(C.of_call("notebook", {"action": "remember"}), C.READ)
        self.assertIn(C.of_call("notebook", {"action": "remember"}), C.ANYTIME)
        self.assertIn(C.of_call("session", {"action": "save"}), C.SAVE)
        self.assertIn(C.of_call("session", {"action": "load"}), C.MENU)
        self.assertIn(C.of_call("answer", {"choice": "accept"}), C.RESPONSE)
        self.assertNotIn(C.of_call("answer", {"choice": "GOODY_GOLD"}), C.RESPONSE, "a decision popup's answer runs under its allow-list")
        self.assertIn(C.of_handler("answer_popup"), C.RESPONSE)
        self.assertIn(C.of_handler("respond_discussion"), C.RESPONSE)
        self.assertNotIn(C.of_handler("choose_goody_hut"), C.RESPONSE)
        self.assertIn(C.of_handler("diplo_event"), C.RESPONSE)
        self.assertIn(C.of_handler("quick_save"), C.SAVE)
        self.assertEqual(C.REQUIRED_BLOCKER[C.of_handler("found_religion")], "ENDTURN_BLOCKING_FOUND_RELIGION")

    def test_an_old_name_and_its_new_call_are_one_key(self):
        pairs = [("league_status", ("inspect", {"what": "league"})),
                 ("tactical_view", ("inspect", {"what": "unit", "view": "tactical", "id": 3})),
                 ("finish_turn", ("turn", {"action": "finish"})),
                 ("set_production", ("order", {"to": "city", "action": "produce", "id": 1, "args": {"item": "x"}})),
                 ("quick_save", ("session", {"action": "save"})),
                 ("how_to_play", ("reference", {"book": "playbook"})),
                 ("reference", ("reference", {})),
                 ("accept_deal", ("answer", {"choice": "accept"})),
                 ("do", ("batch", {"actions": []}))]
        for old, (tool, args) in pairs:
            self.assertEqual(C.of_handler(old), C.of_call(tool, args), old)
            self.assertEqual(C.of_call(old, {}), C.of_call(tool, args), old)
        # a city-state button is its own action; a wildcard set holds every one
        self.assertEqual(C.of_handler("city_state_action"), ("order", "city_state/<action>"))
        self.assertIn(("order", "city_state/pledge"), C.Keys({("order", "city_state/*")}))

    def test_a_read_skips_every_refusal(self):
        class G:
            seat = 1
            def discussion_pending(self):
                return True
        ts = {"paused": True, "processing": False, "my_turn": False, "blocking_name": "", "pending_popups": [],
              "active_player": 1, "turn": 3}
        self.assertIsNone(m._refusal_for(G(), ts, C.of_handler("notification_log")))
        self.assertIsNone(m._refusal_for(G(), ts, C.of_call("inspect", {"what": "notifications"})))
        self.assertIsNone(m._refusal_for(G(), ts, C.of_handler("assign")))
        self.assertIsNotNone(m._refusal_for(G(), ts, C.of_handler("move_unit")))
        self.assertIsNotNone(m._refusal_for(G(), ts, C.of_call("order", {"to": "unit", "action": "move"})))


class KeysTests(unittest.TestCase):
    def test_wildcards_and_union(self):
        keys = C.Keys({("inspect", "*"), ("order", "city/*"), ("turn", "status")})
        self.assertIn(("inspect", "league"), keys)
        self.assertIn(("inspect", "unit/tactical"), keys)
        self.assertIn(("order", "city/produce"), keys)
        self.assertNotIn(("order", "unit/move"), keys)
        self.assertIn(("turn", "status"), keys)
        self.assertNotIn(("turn", "finish"), keys)
        self.assertNotIn("inspect", keys)
        both = keys | C.Keys({("turn", "finish")})
        self.assertIn(("turn", "finish"), both)
        self.assertEqual(len(both), 4)
        self.assertEqual(list(C.Keys({("b", "1"), ("a", "2")})), [("a", "2"), ("b", "1")])

    def test_the_action_label(self):
        self.assertEqual(C.action("inspect", {"what": "league"}), "league")
        self.assertEqual(C.action("inspect", {"what": "league", "view": "default"}), "league")
        self.assertEqual(C.action("inspect", {"what": "unit", "view": "tactical"}), "unit/tactical")
        self.assertEqual(C.action("order", {"to": "city", "action": "produce"}), "city/produce")
        self.assertEqual(C.action("answer", {"choice": 3}), "3")
        self.assertEqual(C.action("reference", {}), "rules")
        self.assertEqual(C.action("question", {}), "")
        self.assertEqual(C.action("batch", {"actions": []}), "")

    def test_called_as(self):
        self.assertEqual(C.called_as("league_status"), {"tool": "inspect", "action": "league", "called": "league_status"})
        self.assertEqual(C.called_as("inspect", {"what": "league"}), {"tool": "inspect", "action": "league"})
        self.assertEqual(C.called_as("summary"), {"tool": "inspect", "action": "empire", "called": "summary"})
        self.assertEqual(C.called_as("answer_popup", {"button": 2}), {"tool": "answer", "action": "2", "called": "answer_popup"})
        self.assertEqual(C.called_as("answer_popup"), {"tool": "answer", "action": "<button>", "called": "answer_popup"})
        self.assertEqual(C.called_as("city_state_action", {"player_id": 30, "action": "pledge"}),
                         {"tool": "order", "action": "city_state/pledge", "called": "city_state_action"})
        self.assertEqual(C.called_as("do", {"actions": []}), {"tool": "batch", "called": "do"})
        self.assertEqual(C.called_as("question"), {"tool": "question"})
        self.assertEqual(C.called_as("lua", {"code": "1"}), {"tool": "lua"})


class ProductionOrderTests(unittest.TestCase):
    def test_prefix_picks_the_order_and_junk_is_none(self):
        self.assertEqual(m._production_order("UNIT_WARRIOR"), "ORDER_TRAIN")
        self.assertEqual(m._production_order("building_monument"), "ORDER_CONSTRUCT")
        self.assertEqual(m._production_order("PROJECT_APOLLO_PROGRAM"), "ORDER_CREATE")
        self.assertEqual(m._production_order("PROCESS_WEALTH"), "ORDER_MAINTAIN")
        self.assertIsNone(m._production_order("BOGUS_THING"))
        self.assertIsNone(m._purchase_order("PROCESS_WEALTH"))
        self.assertEqual(m._purchase_order("BUILDING_MARKET"), "ORDER_CONSTRUCT")


if __name__ == "__main__":
    unittest.main()
