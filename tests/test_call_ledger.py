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
    src = "\n".join(p.read_text() for p in [ROOT / "harness" / "mcp_server.py", *sorted((ROOT / "harness" / "mcp_tools").glob("*.py"))])
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
        with mock.patch.dict(L._LAST_TURN, {}, clear=True):   # no turn stamped by an earlier test's rows
            r = L.row("move_unit", 0, json.dumps({"ok": False, "err": "x" * 500, "turn": 43}), 0.25, 2, now=1.0)
            self.assertEqual((r["ok"], len(r["err"]), r["turn"], r["trips"], r["kind"]), (False, 120, 43, 2, "write"))
            ok = L.row("finish_turn", 0, json.dumps({"status": {"turn": 44}}), 30.0, 40)
            self.assertEqual((ok["ok"], ok["turn"], ok["kind"]), (True, 44, "wait"))
            plain = L.row("recall", 1, "not json", 0.1, None)
            self.assertEqual((plain["ok"], plain["bytes"], "turn" in plain), (True, 8, False))

    def test_a_row_without_a_turn_is_stamped_with_the_seats_latest_and_says_so(self):
        """Codex 2026-10-03: 368 of 443 rows (every read and order) named no turn; only the waits did."""
        with mock.patch.dict(L._LAST_TURN, {}, clear=True):
            first = L.row("units", 0, "[]", 0.1, 1)
            self.assertNotIn("turn", first, "nothing to infer from yet")
            wait = L.row("finish_turn", 0, json.dumps({"ok": True, "ended": True, "turn": 31}), 9.0, 20)
            read = L.row("tactical_view", 0, json.dumps({"ok": True, "neighbors": []}), 0.1, 2)
            self.assertEqual((wait["turn"], "turn_inferred" in wait), (31, False))
            self.assertEqual((read["turn"], read["turn_inferred"]), (31, True))
            other = L.row("units", 1, "[]", 0.1, 1)
            self.assertNotIn("turn", other, "per seat")
            named = L.row("move_unit", 0, json.dumps({"ok": True, "turn": 32}), 0.1, 1)
            self.assertEqual((named["turn"], "turn_inferred" in named), (32, False))

    def test_the_refusal_reason_is_found_where_the_reply_keeps_it(self):
        """finish_turn's refusal is `end_turn.err`; the report printed an empty reason for every one (t35, t37...)."""
        nested = {"ok": False, "ended": False, "turn": 35,
                  "end_turn": {"ok": False, "err": "CONTROL_ENDTURN was sent but the turn did not end: every unit "
                                                   "in todo.units still has moves", "blocking": "ENDTURN_BLOCKING_UNITS"}}
        self.assertTrue(L.row("finish_turn", 0, json.dumps(nested), 5.0, 9)["err"].startswith("CONTROL_ENDTURN"))
        batch = {"ok": False, "ended": False, "batch": {"ok": False, "results": [
            {"index": 0, "tool": "set_research", "result": {"ok": True}},
            {"index": 1, "tool": "move_unit", "result": {"ok": False, "err": "plot is not revealed"}}]}}
        self.assertEqual(L.refusal_reason(batch), "move_unit: plot is not revealed")
        self.assertEqual(L.refusal_reason({"ok": False, "err": "mine", "end_turn": {"err": "inner"}}), "mine")
        self.assertEqual(L.refusal_reason({"ok": False, "hint": "read the state"}), "read the state")
        self.assertEqual(L.refusal_reason({"ok": False}), "")

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

    def test_client_label(self):
        """CIV5_CLIENT wins; else clientInfo name/version (object or dict); else none, and no `client` key."""
        class Info:
            name, version = "codex-mcp-client", "0.42"
        env = {k: v for k, v in os.environ.items() if k != L.CLIENT_ENV}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertIsNone(L.client())
            self.assertEqual(L.client(Info()), "codex-mcp-client/0.42")
            self.assertEqual(L.client({"name": "claude-code"}), "claude-code")
            self.assertNotIn("client", L.row("units", 0, "[]", 0.1, 1))
        with mock.patch.dict(os.environ, {L.CLIENT_ENV: "grok/grok-4-fast"}):
            self.assertEqual(L.client(Info()), "grok/grok-4-fast", "the operator's label beats the handshake")
            self.assertEqual(L.row("units", 0, "[]", 0.1, 1, client_label=L.client())["client"], "grok/grok-4-fast")


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
        rows = self.rows()
        rows.insert(5, {**rows[4], "tool": "wait_for_my_turn", "seconds": 5.0})   # end_turn's own wait
        ts = R.turns(rows)
        self.assertEqual([t["turn"] for t in ts], [42, 43, 44])
        first = ts[0]
        self.assertEqual((first["reads"], first["read_bytes"], first["writes"], first["refused"]), (2, 200, 2, 1))
        self.assertEqual((first["wait_seconds"], first["read_seconds"]), (65.0, 2.0), "both waits close turn 42")
        self.assertEqual(ts[1]["wait_refused"], 1, "a refused end_turn does not end the turn")
        self.assertEqual(ts[1]["wait_seconds"], 40.5)
        self.assertTrue(ts[-1]["open"])
        self.assertNotIn("open", ts[1])

    def test_seat_filter(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            for r in self.rows():
                f.write(json.dumps(r) + "\n")
            f.write(json.dumps({**self.rows()[0], "seat": 1}) + "\n")
        self.addCleanup(os.unlink, f.name)
        self.assertEqual(len(R.load(f.name, 0)), 9)
        self.assertEqual(len(R.load(f.name, 1)), 1)

    def test_client_filter_and_summary(self):
        rows = self.rows()
        for r in rows[:4]:
            r["client"] = "codex/gpt-5"
        for r in rows[4:7]:
            r["client"] = "grok/grok-4"
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        self.addCleanup(os.unlink, f.name)
        self.assertEqual(len(R.load(f.name, None, "codex")), 4)
        self.assertEqual(len(R.load(f.name, 0, "grok")), 3)
        self.assertEqual(len(R.load(f.name, None, "claude")), 0)
        summary = R.clients(rows)
        self.assertEqual([c["client"] for c in summary], ["codex/gpt-5", "grok/grok-4", None], "unlabelled rows last")
        self.assertEqual((summary[0]["rows"], summary[0]["first_turn"], summary[0]["last_turn"]), (4, 42, 42))
        self.assertEqual((summary[1]["rows"], summary[1]["seats"]), (3, [0]))


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
            with self.assertRaises(Exception):  # noqa: B017 -- the ledger row is the point, not the SDK's error type
                self.call("move_unit", {"unit_id": "not-a-number", "x": 1, "y": 1})
        rows = [json.loads(line) for line in open(self.log)]
        self.assertEqual((rows[0]["tool"], rows[0]["ok"]), ("move_unit", False))

    def test_the_client_label_rides_on_every_row(self):
        with mock.patch.dict(os.environ, {"CIV5_CALL_LOG": self.log, "CIV5_CLIENT": "codex/gpt-5-codex"}):
            self.call("recall", {})
            with self.assertRaises(Exception):  # noqa: B017
                self.call("move_unit", {"unit_id": "x", "x": 1, "y": 1})
        rows = [json.loads(line) for line in open(self.log)]
        self.assertEqual([r.get("client") for r in rows], ["codex/gpt-5-codex"] * 2, "the refusal row too")

    def test_off_by_default(self):
        env = {k: v for k, v in os.environ.items() if k != "CIV5_CALL_LOG"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.call("recall", {})
        self.assertFalse(os.path.exists(self.log))


if __name__ == "__main__":
    unittest.main()
