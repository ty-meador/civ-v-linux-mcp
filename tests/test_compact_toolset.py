"""--tools compact: the client lists CORE_TOOLS only; every other tool still runs.

The full catalog is ~100 KB of descriptions and schemas (144 tools, 2026-10-03), paid on every request by a
client that does not defer tool schemas. In compact mode the hidden tools run through `call(tool, args)`,
inside `do` / finish_turn(actions) batches, and by their own name when a client sends one anyway (a gate's
clear_with, a todo_actions row); `call()` is the catalog and call(tool, describe=true) one tool's reference.
"""
import os
import unittest
from unittest import mock

import anyio

from harness import mcp_server as m
from tests.test_do_batch import FakeGame, session


class HiddenGame(FakeGame):
    def set_city_focus(self, city_id, focus):
        self.calls.append(("set_city_focus", city_id, focus))
        return {"ok": True}


class CompactToolsetTests(unittest.TestCase):
    def setUp(self):
        self.fake = HiddenGame()
        self.patches = [mock.patch.object(m, "game", lambda: self.fake),
                        mock.patch.dict(os.environ, {"CIV5_TUNERD_SOCK": "/tmp/civ5-test-compact.sock"}),
                        mock.patch.dict(m._RECENT, {}, clear=True)]
        for p in self.patches:
            p.start()
        self.full = {t.name for t in m.mcp._tool_manager.list_tools()}
        m.apply_toolset("compact")
        self.addCleanup(m.apply_toolset, "full")

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def listed(self):
        return {t.name for t in m.mcp._tool_manager.list_tools()}

    def test_the_client_sees_the_core_set_only_and_full_restores_everything(self):
        names = self.listed()
        self.assertEqual(names, set(m.CORE_TOOLS) & self.full)
        self.assertIn("finish_turn", names)
        self.assertIn("call", names)
        self.assertNotIn("set_city_focus", names)
        self.assertGreater(len(m.hidden_tools()), 100)
        self.assertEqual(m.toolset_mode(), "compact")
        self.assertTrue(m.mcp._lowlevel_server.instructions.endswith(m.COMPACT_NOTE))
        m.apply_toolset("full")
        self.assertEqual(self.listed(), self.full)
        self.assertEqual(m.hidden_tools(), {})
        self.assertNotIn(m.COMPACT_NOTE, m.mcp._lowlevel_server.instructions)

    def test_call_runs_a_hidden_tool_with_its_own_arguments(self):
        (out,) = anyio.run(session, [("call", {"tool": "set_city_focus", "args": {"city_id": 1, "focus": "FOOD"}})])
        self.assertEqual(out, {"ok": True})
        self.assertEqual(self.fake.calls, [("set_city_focus", 1, "FOOD")])

    def test_a_hidden_tool_sent_by_name_still_runs(self):
        (out,) = anyio.run(session, [("set_city_focus", {"city_id": 1, "focus": "FOOD"})])
        self.assertEqual(out, {"ok": True})
        self.assertEqual(self.fake.calls, [("set_city_focus", 1, "FOOD")])

    def test_a_batch_reaches_hidden_tools(self):
        (out,) = anyio.run(session, [("do", {"actions": [{"tool": "set_city_focus", "args": {"city_id": 1, "focus": "FOOD"}}]})])
        self.assertTrue(out["ok"])
        self.assertEqual(out["done"], 1)

    def test_call_lists_the_catalog_and_describes_one_tool_without_running_it(self):
        catalog, one = anyio.run(session, [("call", {}), ("call", {"tool": "set_city_focus", "describe": True})])
        self.assertEqual(catalog["mode"], "compact")
        rows = catalog["tools"]["cities"]
        self.assertTrue(any(r.startswith("set_city_focus(") for r in rows), rows[:3])
        total = sum(len(v) for v in catalog["tools"].values())
        self.assertEqual(total, len(self.full))
        self.assertTrue(one["accepts"].startswith("set_city_focus("))
        self.assertIn("city_id", one["accepts"])
        self.assertTrue(one["description"])
        self.assertEqual(self.fake.calls, [])

    def test_call_refuses_the_batches_and_hints_an_unknown_name(self):
        a, b, c = anyio.run(session, [("call", {"tool": "do"}), ("call", {"tool": "call"}),
                                      ("call", {"tool": "set_city_focs", "args": {}})])
        self.assertFalse(a["ok"])
        self.assertFalse(b["ok"])
        self.assertIn("set_city_focus", c["err"])

    def test_a_bad_argument_names_the_signature(self):
        (out,) = anyio.run(session, [("call", {"tool": "set_city_focus", "args": {"city": 1}})])
        self.assertFalse(out["ok"])
        self.assertTrue(out["accepts"].startswith("set_city_focus("))


if __name__ == "__main__":
    unittest.main()
