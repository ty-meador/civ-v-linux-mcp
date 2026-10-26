"""`call` and `--tools compact` retired (GitLab #51, stage 2d): with nine listed tools nothing is hidden, so the
tool that reached hidden ones is off the listing -- and still answers by its name, as every old name does, with
the inner call's new name on the reply. A batch row is classified by its `(tool, action)` key: `turn(action=
"status")` rides in a batch, `turn(action="finish")` does not, whichever name the row uses.
"""
import os
import unittest
from unittest import mock

import anyio

from harness import mcp_server as m
from harness.surface import classes as C
from tests.test_do_batch import FakeGame, session


class RetiredGame(FakeGame):
    def set_city_focus(self, city_id, focus):
        self.calls.append(("set_city_focus", city_id, focus))
        return {"ok": True}

    def quick_save(self):
        self.calls.append(("quick_save",))
        return {"ok": True, "saved": "QuickSave"}

    discussion = False

    def turn_state(self, pid=None):
        return {**super().turn_state(pid), "discussion_pending": self.discussion}

    def units(self):
        return []


class RetiredCallTests(unittest.TestCase):
    def setUp(self):
        self.fake = RetiredGame()
        self.patches = [mock.patch.object(m, "game", lambda: self.fake),
                        mock.patch.dict(os.environ, {"CIV5_TUNERD_SOCK": "/tmp/civ5-test-retired.sock"}),
                        mock.patch.dict(m._RECENT, {}, clear=True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def listed(self):
        return {t.name for t in m.mcp._tool_manager.list_tools()}

    def test_call_is_off_the_listing_and_the_flag_is_gone(self):
        self.assertNotIn("call", self.listed())
        self.assertIn("call", m.retired_tools())
        self.assertIn("batch", self.listed())
        self.assertFalse(hasattr(m, "apply_toolset"))
        self.assertFalse(hasattr(m, "CORE_TOOLS"))
        with self.assertRaises(SystemExit):
            with mock.patch("sys.stderr"):
                m.main(["--tools", "compact"])

    def test_call_still_runs_a_tool_by_name_with_the_inner_calls_new_name(self):
        (out,) = anyio.run(session, [("call", {"tool": "set_city_focus", "args": {"city_id": 1, "focus": "FOOD"}})])
        self.assertEqual(out, {"ok": True, "renamed": 'order(to="city", action="governor", id=1, args={"focus": "FOOD"})'})
        self.assertEqual(self.fake.calls, [("set_city_focus", 1, "FOOD")])
        # a listed inner name: the reply carries the inner call's new name, not `batch(...)`
        (out,) = anyio.run(session, [("call", {"tool": "quick_save"})])
        self.assertEqual(out["renamed"], 'session(action="save")')
        (out,) = anyio.run(session, [("call", {"tool": "session", "args": {"action": "save"}})])
        self.assertEqual(out["renamed"], 'session(action="save")', "call itself is retired: the reply says the call to make")

    def test_call_lists_the_catalog_and_describes_one_tool_without_running_it(self):
        catalog, one = anyio.run(session, [("call", {}), ("call", {"tool": "set_city_focus", "describe": True})])
        self.assertNotIn("mode", catalog)
        rows = catalog["tools"]["cities"]
        self.assertTrue(any(r.startswith("set_city_focus(") for r in rows), rows[:3])
        self.assertTrue(any(r.startswith("call(") for r in catalog["tools"]["batch"]), "retired names are listed too")
        self.assertTrue(one["accepts"].startswith("set_city_focus("))
        self.assertIn("city_id", one["accepts"])
        self.assertEqual(one["renamed"], 'order(to="city", action="governor")')
        self.assertEqual(self.fake.calls, [])

    def test_call_refuses_what_a_batch_row_cannot_be_and_hints_an_unknown_name(self):
        a, b, c, d = anyio.run(session, [("call", {"tool": "do"}), ("call", {"tool": "call"}),
                                         ("call", {"tool": "turn", "args": {"action": "finish"}}),
                                         ("call", {"tool": "set_city_focs", "args": {}})])
        for r in (a, b, c):
            self.assertFalse(r["ok"], r)
            self.assertIn("not a batch row", r["err"])
        self.assertIn("set_city_focus", d["err"])

    def test_a_bad_argument_names_the_signature(self):
        (out,) = anyio.run(session, [("call", {"tool": "set_city_focus", "args": {"city": 1}})])
        self.assertFalse(out["ok"])
        self.assertTrue(out["accepts"].startswith("set_city_focus("))

    def test_a_batch_row_is_classified_by_its_key(self):
        rows = [{"tool": "inspect", "args": {"what": "units"}}, {"tool": "units", "args": {}},
                {"tool": "session", "args": {"action": "save"}}, {"tool": "quick_save", "args": {}},
                {"tool": "turn", "args": {"action": "finish"}}, {"tool": "finish_turn", "args": {}},
                {"tool": "session", "args": {"action": "load_latest"}}, {"tool": "load_latest", "args": {}}]
        (out,) = anyio.run(session, [("do", {"actions": rows, "stop_on_refusal": False})])
        results = [r["result"].get("ok") if isinstance(r["result"], dict) else True for r in out["results"]]   # units() is a list
        self.assertEqual(results[:4], [True, True, True, True], out["results"][:4])
        self.assertEqual(results[4:], [False, False, False, False], out["results"][4:])
        for r in out["results"][4:]:
            self.assertIn("cannot run inside a batch", r["result"]["err"])
        self.assertEqual(self.fake.calls.count(("quick_save",)), 2)

    def test_the_guard_classifies_the_handler_by_key(self):
        """A read by any name runs under a leader remark; an order is refused."""
        self.fake.discussion = True
        out, order = anyio.run(session, [("inspect", {"what": "units"}),
                                         ("order", {"to": "city", "action": "governor", "id": 1, "args": {"focus": "FOOD"}})])
        self.assertEqual(out, [])
        self.assertFalse(order["ok"])
        self.assertIn("diplomatic decision pending", order["err"])
        self.assertEqual(C.of_handler("set_city_focus"), ("order", "city/governor"))


if __name__ == "__main__":
    unittest.main()
