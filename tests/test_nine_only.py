"""A server that knows the nine tools alone (stage 2e, GitLab #52): `CIV5_RETIRED_NAMES=off`.

The 145 old names are off the listing and answer only through the retirement map; with the map switched off
(`--retired-names off`) an old name is unknown and everything a turn needs is still there under the nine. This
is what a session that was never shown an old name must be able to play on (stage 4's live check), and what
`scripts/check.sh` runs a second time with the map off: the tests marked `new_vocabulary` speak nothing else.
"""
import json
import os
import unittest
from unittest import mock

import anyio
import pytest

from harness import mcp_server as m
from tests.test_do_batch import FakeGame, session


class NineGame(FakeGame):
    def units(self):
        return [{"id": 1, "x": 3, "y": 4, "type": "UNIT_WARRIOR"}]

    def quick_save(self):
        self.calls.append(("quick_save",))
        return {"ok": True, "saved": "QuickSave"}

    def expiring_city_states(self, *a, **k):
        return []

    def notebook(self):
        fake = self

        class Book:
            def recall(self, *a, **k):
                fake.calls.append(("recall",))
                return []
        return Book()


@pytest.mark.new_vocabulary
class NineOnlyTests(unittest.TestCase):
    def setUp(self):
        self.fake = NineGame()
        self.patches = [mock.patch.object(m, "game", lambda: self.fake),
                        mock.patch.dict(os.environ, {"CIV5_TUNERD_SOCK": "/tmp/civ5-test-nine.sock", "CIV5_RETIRED_NAMES": "off"}),
                        mock.patch.dict(m._RECENT, {}, clear=True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_the_listing_is_the_nine(self):
        self.assertEqual({t.name for t in m.mcp._tool_manager.list_tools()},
                         {"turn", "state", "order", "question", "answer", "notebook", "batch", "session", "reference"})
        self.assertEqual(len(m.retired_tools()), 144)   # the 145 less `reference`, the ninth, which grew a `book`
        self.assertFalse(m.retired_names_on())
        self.assertNotIn("units", m.known_tool_names())

    def test_a_turn_through_the_nine_alone(self):
        status, units, moved, batch, notes, saved, question = anyio.run(session, [
            ("turn", {"action": "status"}),
            ("state", {"what": "units"}),
            ("order", {"to": "unit", "action": "move", "id": 1, "args": {"x": 5, "y": 6}}),
            ("batch", {"actions": [{"tool": "order", "args": {"to": "unit", "action": "mission", "id": 1, "args": {"mission": "MISSION_FORTIFY"}}},
                                   {"tool": "state", "args": {"what": "units"}}]}),
            ("notebook", {"action": "recall"}),
            ("session", {"action": "save"}),
            ("question", {}),
        ])
        self.assertEqual(status["turn"], 7)
        self.assertIsNone(status.get("gate"))
        self.assertEqual(units[0]["id"], 1)
        self.assertTrue(moved["ok"])
        self.assertEqual((batch["ok"], batch["done"]), (True, 2))
        self.assertEqual(notes, [])
        self.assertTrue(saved["ok"])
        self.assertFalse(question["pending"])
        self.assertEqual([c[0] for c in self.fake.calls], ["move_unit", "unit_mission", "recall", "quick_save"])
        for reply in (status, moved, batch, saved, question):
            self.assertNotIn("renamed", reply, "nothing was called by an old name")

    def test_an_old_name_is_unknown_with_the_map_off(self):
        out, = anyio.run(session, [("units", {})])
        self.assertTrue(out["is_error"])
        self.assertIn("Unknown tool: units", out["text"])
        self.assertNotIn("units", out["text"].split("Unknown tool: units")[1], "no retired name is suggested")
        out, = anyio.run(session, [("batch", {"actions": [{"tool": "move_unit", "args": {"unit_id": 1, "x": 5, "y": 6}}]})])
        self.assertFalse(out["ok"])
        self.assertIn("Unknown tool", json.dumps(out))
        self.assertEqual(self.fake.calls, [])

    def test_with_the_map_on_the_same_old_name_answers_with_renamed(self):
        with mock.patch.dict(os.environ, {"CIV5_RETIRED_NAMES": "on"}):
            out, = anyio.run(session, [("units", {})])
        self.assertEqual(out[0]["id"], 1)     # a list reply cannot carry `renamed`; the object replies do


if __name__ == "__main__":
    unittest.main()
