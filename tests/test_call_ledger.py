"""The opt-in call ledger (CIV5_CALL_LOG) and its per-turn report (GitLab #36)."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness import call_ledger as L

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import ledger_report as R  # noqa: E402


def tool_names() -> set[str]:
    src = (ROOT / "harness" / "mcp_server.py").read_text()
    return set(re.findall(r"@mcp\.tool\(\)\s*\n(?:@guarded\s*\n)?def (\w+)", src))


class RowTests(unittest.TestCase):
    def test_every_named_tool_exists(self):
        names = tool_names()
        self.assertGreater(len(names), 100)
        self.assertEqual(L.READ_TOOLS - names, set(), "a read named in the ledger is not a tool")
        self.assertEqual(L.WAIT_TOOLS - names, set())

    def test_kinds(self):
        self.assertEqual(L.kind("briefing"), "read")
        self.assertEqual(L.kind("tactical_view"), "read")
        self.assertEqual(L.kind("move_unit"), "write")
        self.assertEqual(L.kind("give_order"), "write")
        self.assertEqual(L.kind("do"), "write")
        self.assertEqual(L.kind("finish_turn"), "wait")

    def test_refusal_and_turn(self):
        r = L.row("move_unit", 0, json.dumps({"ok": False, "err": "x" * 500, "turn": 43}), 0.25, 2, now=1.0)
        self.assertEqual((r["ok"], len(r["err"]), r["turn"], r["trips"], r["kind"]), (False, 120, 43, 2, "write"))
        ok = L.row("finish_turn", 0, json.dumps({"status": {"turn": 44}}), 30.0, 40)
        self.assertEqual((ok["ok"], ok["turn"], ok["kind"]), (True, 44, "wait"))
        plain = L.row("recall", 1, "not json", 0.1, None)
        self.assertEqual((plain["ok"], plain["bytes"], "turn" in plain), (True, 8, False))

    def test_bytes_are_utf8(self):
        self.assertEqual(L.row("units", 0, "é", 0, 0)["bytes"], 2)

    def test_reply_text_shapes(self):
        class C:
            def __init__(self, t):
                self.text = t
        self.assertEqual(L.reply_text("abc"), "abc")
        self.assertEqual(L.reply_text([C("a"), C("b")]), "ab")
        self.assertEqual(L.reply_text(([C("a")], {"result": "a"})), "a")

    def test_unwritable_path_is_ignored(self):
        L.append("/nonexistent-dir/x/calls.jsonl", {"tool": "units"})


class ReportTests(unittest.TestCase):
    def rows(self):
        mk = lambda tool, turn=None, ok=True, b=100, s=1.0: {  # noqa: E731
            "tool": tool, "kind": L.kind(tool), "bytes": b, "seconds": s, "trips": 3, "ok": ok, "seat": 0,
            **({"turn": turn} if turn is not None else {}), **({} if ok else {"err": "no"})}
        return [mk("briefing", 42), mk("tactical_view", 42), mk("move_unit", 42, ok=False), mk("give_order", 42),
                mk("finish_turn", 43, s=60.0),
                mk("briefing", b=50), mk("end_turn", ok=False, s=0.5), mk("end_turn", 44, s=40.0),
                mk("briefing", 44)]

    def test_turns_split_at_waits_and_keep_waiting_apart(self):
        ts = R.turns(self.rows())
        self.assertEqual([t["turn"] for t in ts], [42, 43, 43, 44])
        first = ts[0]
        self.assertEqual((first["reads"], first["read_bytes"], first["writes"], first["refused"]), (2, 200, 2, 1))
        self.assertEqual((first["wait_seconds"], first["read_seconds"]), (60.0, 2.0))
        self.assertEqual(ts[1]["wait_refused"], 1, "a refused end_turn is a wait that did not end the turn")
        self.assertTrue(ts[-1]["open"])

    def test_seat_filter(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            for r in self.rows():
                f.write(json.dumps(r) + "\n")
            f.write(json.dumps({**self.rows()[0], "seat": 1}) + "\n")
        self.addCleanup(os.unlink, f.name)
        self.assertEqual(len(R.load(f.name, 0)), 9)
        self.assertEqual(len(R.load(f.name, 1)), 1)


class ServerHookTests(unittest.TestCase):
    """The MCP call wrapper appends one row per call when CIV5_CALL_LOG is set, and nothing when it is not."""

    def setUp(self):
        from harness import mcp_server
        self.m = mcp_server
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = os.path.join(self.tmp.name, "calls.jsonl")
        saved = mcp_server._game
        self.addCleanup(setattr, mcp_server, "_game", saved)
        g = mock.MagicMock()
        g.seat = 0
        g.c.trips = 7
        g.notebook.return_value.recall.return_value = [{"id": 1, "text": "hold the hill"}]
        mcp_server._game = g   # no tunerd: recall is a notebook read

    def call(self, tool, args):
        return asyncio.run(self.m.mcp.call_tool(tool, args))

    def test_a_call_is_logged_with_its_bytes(self):
        with mock.patch.dict(os.environ, {"CIV5_CALL_LOG": self.log}):
            self.call("recall", {})
        rows = [json.loads(line) for line in open(self.log)]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["tool"], rows[0]["kind"], rows[0]["seat"], rows[0]["ok"]), ("recall", "read", 0, True))
        self.assertEqual(rows[0]["bytes"], len('[{"id":1,"text":"hold the hill"}]'))
        self.assertEqual(rows[0]["trips"], 0, "trips are the difference over the call")

    def test_a_validation_error_is_logged_as_refused(self):
        with mock.patch.dict(os.environ, {"CIV5_CALL_LOG": self.log}):
            with self.assertRaises(Exception):
                self.call("move_unit", {"unit_id": "not-a-number", "x": 1, "y": 1})
        rows = [json.loads(line) for line in open(self.log)]
        self.assertEqual((rows[0]["tool"], rows[0]["ok"]), ("move_unit", False))

    def test_off_by_default(self):
        env = {k: v for k, v in os.environ.items() if k != "CIV5_CALL_LOG"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.call("recall", {})
        self.assertFalse(os.path.exists(self.log))


if __name__ == "__main__":
    unittest.main()
