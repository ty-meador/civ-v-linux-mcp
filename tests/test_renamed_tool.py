"""`inspect` is `state` (the one verb among nine nouns; Glama / TDQS naming 4/5, 2026-10-28).

A listed tool renamed is retired like the 145 old names: `inspect(...)` still answers, running `state` with the
same arguments and carrying `renamed` (the call to make now); the ledger and the batch classify it by the new
call's key; with the retired names off it is unknown. The runtime audit forbids the old word in Lua strings.
"""
import os
import unittest
from unittest import mock

import anyio

from harness import mcp_server as m
from harness.surface import classes as C, dispatch as D, forward, retirement as R, runtime_audit as RA, vocabulary as V
from tests.test_do_batch import FakeGame, session


class RenamedToolTableTests(unittest.TestCase):
    def test_state_is_listed_and_inspect_is_the_renamed_old_name(self):
        self.assertIn("state", V.TOOLS)
        self.assertNotIn("inspect", V.TOOLS)
        self.assertEqual(R.RENAMED_TOOLS, {"inspect": "state"})
        self.assertEqual(forward.old_name("inspect"), "state")
        self.assertEqual(forward.renamed("inspect", {"what": "units", "view": "actions", "id": None}),
                         'state(what="units", view="actions")')

    def test_the_key_and_the_ledger_row_are_the_new_calls(self):
        self.assertEqual(C.of_call("inspect", {"what": "units", "view": "actions"}), ("state", "units/actions"))
        self.assertEqual(C.of_call("inspect", {"what": "empire"}), C.of_call("state", {"what": "empire"}))
        row = C.called_as("inspect", {"what": "city", "view": "production", "id": 3})
        self.assertEqual((row["tool"], row["action"], row["called"]), ("state", "city/production", "inspect"))
        self.assertIn(C.of_call("inspect", {"what": "units"}), C.READ, "an inspect rides in a batch as a read")
        self.assertEqual(D.old_call("inspect", {"what": "units"}), D.old_call("state", {"what": "units"}))

    def test_the_runtime_audit_forbids_the_old_word(self):
        self.assertIn("inspect", RA.names())
        self.assertNotIn("state", RA.names())
        self.assertEqual(RA.scan(), [], "no runtime string names a retired tool, `inspect` included")

    def test_no_nine_tool_description_or_instruction_names_inspect(self):
        text = m.mcp.instructions + "".join((t.description or "") for t in m.mcp._tool_manager.list_tools())
        self.assertNotRegex(text, r"\binspect\b")
        self.assertIn('state(what="units", view="actions")', m.mcp.instructions)


class RenamedGame(FakeGame):
    def units(self):
        return []

    def overview(self):
        return {"ok": True, "turn": 7, "gold": 12}


class RenamedToolCallTests(unittest.TestCase):
    def setUp(self):
        self.fake = RenamedGame()
        self.patches = [mock.patch.object(m, "game", lambda: self.fake),
                        mock.patch.dict(os.environ, {"CIV5_TUNERD_SOCK": "/tmp/civ5-test-renamed.sock"}),
                        mock.patch.dict(m._RECENT, {}, clear=True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_inspect_runs_state_and_says_the_call_to_make(self):
        old, new = anyio.run(session, [("inspect", {"what": "empire"}), ("state", {"what": "empire"})])
        self.assertEqual(old.get("renamed"), 'state(what="empire")')
        self.assertNotIn("renamed", new)
        self.assertEqual({k: v for k, v in old.items() if k != "renamed"}, new, "the same reply under either name")
        # a list reply (units) has nowhere to carry `renamed`, as for every old name: the list itself is the same
        old, new = anyio.run(session, [("inspect", {"what": "units"}), ("state", {"what": "units"})])
        self.assertEqual(old, new)

    def test_a_batch_row_by_the_old_name_runs_as_a_read(self):
        (out,) = anyio.run(session, [("batch", {"actions": [{"tool": "inspect", "args": {"what": "units"}}]})])
        self.assertEqual(out["done"], 1, out)
        self.assertEqual(out["results"][0]["tool"], "inspect")

    def test_with_the_retired_names_off_inspect_is_unknown(self):
        with mock.patch.dict(os.environ, {"CIV5_RETIRED_NAMES": "off"}):
            self.assertNotIn("inspect", m.known_tool_names())
            self.assertIsNone(m.find_tool("inspect"))
        self.assertIn("inspect", m.known_tool_names())


if __name__ == "__main__":
    unittest.main()
