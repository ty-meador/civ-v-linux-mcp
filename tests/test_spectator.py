"""The spectator behind the live visualization (harness/spectator, docs/VISUALIZATION.md): the ledger tail, the
notebook watcher, the feed's ring/state/recording/replay, the live poller's cadence, and the SSE server."""
from __future__ import annotations

import http.client
import json
import os
import pathlib
import tempfile
import threading
import time
import unittest

from harness.spectator import feed as F
from harness.spectator import ledger_tail, notebook_watch, server


class LedgerTailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "calls.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, s: str, mode: str = "a") -> None:
        with open(self.path, mode, encoding="utf-8") as f:
            f.write(s)

    def test_new_rows_only_and_partial_lines_wait(self):
        self.write('{"tool":"old"}\n')
        t = ledger_tail.LedgerTail(self.path)            # starts at the end: the old row is not replayed
        self.assertEqual(t.poll(), [])
        self.write('{"tool":"a"}\n{"tool":"b"')
        self.assertEqual([r["tool"] for r in t.poll()], ["a"])
        self.write('}\nnot json\n{"tool":"c"}\n')
        self.assertEqual([r["tool"] for r in t.poll()], ["b", "c"])
        self.assertEqual(t.poll(), [])

    def test_from_start_and_truncation(self):
        self.write('{"tool":"a"}\n{"tool":"b"}\n')
        t = ledger_tail.LedgerTail(self.path, from_start=True)
        self.assertEqual([r["tool"] for r in t.poll()], ["a", "b"])
        self.write('{"tool":"z"}\n', mode="w")           # rotated: shorter than the offset
        self.assertEqual([r["tool"] for r in t.poll()], ["z"])

    def test_missing_file_is_quiet(self):
        t = ledger_tail.LedgerTail(os.path.join(self.tmp.name, "nope.jsonl"))
        self.assertEqual(t.poll(), [])


class NotebookWatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name: str, data: dict, mtime: float | None = None) -> None:
        p = self.dir / name
        p.write_text(json.dumps(data), encoding="utf-8")
        if mtime is not None:
            os.utime(p, (mtime, mtime))

    def test_newest_file_per_seat_once_per_change(self):
        self.put("Wu_Zetian-China-Pangaea-Beijing-seat0.json",
                 {"notes": [{"id": i, "text": f"n{i}"} for i in range(50)], "assignments": [{"role": "settle"}],
                  "briefing": {"big": "private"}}, mtime=100)
        self.put("Old_Game-seat0.json", {"notes": [{"id": 1, "text": "stale"}]}, mtime=50)
        self.put("Wu_Zetian-China-Pangaea-Beijing-seat1.json", {"notes": []}, mtime=100)
        self.put("unrelated.json", {"notes": []})
        w = notebook_watch.NotebookWatch(str(self.dir))
        recs = w.poll()
        self.assertEqual([r["seat"] for r in recs], [0, 1])
        r0 = recs[0]
        self.assertEqual(r0["game"], "Wu_Zetian-China-Pangaea-Beijing")
        self.assertEqual(len(r0["notes"]), notebook_watch.NOTE_LIMIT)
        self.assertEqual(r0["notes"][-1]["text"], "n49")
        self.assertEqual(r0["assignments"], [{"role": "settle"}])
        self.assertEqual(r0["orders"], [])
        self.assertNotIn("briefing", r0)
        self.assertEqual(w.poll(), [])
        self.put("Wu_Zetian-China-Pangaea-Beijing-seat1.json", {"notes": [{"id": 1, "text": "new"}]}, mtime=200)
        again = w.poll()
        self.assertEqual([(r["seat"], r["notes"][0]["text"]) for r in again], [(1, "new")])

    def test_bad_json_is_skipped(self):
        (self.dir / "g-seat0.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(notebook_watch.NotebookWatch(str(self.dir)).poll(), [])


class FeedTests(unittest.TestCase):
    def test_ring_state_and_since(self):
        f = F.Feed(ring=3)
        f.push("hello", {"map": {"w": 1}})
        f.push("snapshot", {"turn": 1})
        f.push("call", {"tool": "units", "seat": 0})
        f.push("notebook", {"seat": 0, "notes": []})
        f.push("event", {"kind": "combat"})
        f.push("snapshot", {"turn": 2})
        self.assertEqual([e["seq"] for e in f.since(0)], [4, 5, 6])          # the ring kept the last three
        st = f.state()
        self.assertEqual((st["seq"], st["hello"], st["snapshot"]["turn"]), (6, {"map": {"w": 1}}, 2))
        self.assertEqual(list(st["notebooks"]), [0])
        self.assertEqual([c["data"]["tool"] for c in st["calls"]], ["units"])
        self.assertEqual([c["data"]["kind"] for c in st["events"]], ["combat"])

    def test_wait_wakes_on_push(self):
        f = F.Feed()
        got = []
        th = threading.Thread(target=lambda: got.extend(f.wait(0, 5.0)))
        th.start()
        time.sleep(0.05)
        f.push("status", {"x": 1})
        th.join(2.0)
        self.assertEqual([e["type"] for e in got], ["status"])
        self.assertEqual(f.wait(1, 0.01), [])

    def test_record_and_replay_keep_order_and_spacing(self):
        with tempfile.TemporaryDirectory() as d:
            rec = os.path.join(d, "rec.jsonl")
            f = F.Feed(record_path=rec)
            f.push("hello", {"map": 1}, t=100.0)
            f.push("call", {"tool": "units"}, t=101.0)
            f.push("call", {"tool": "move_unit"}, t=104.0)
            slept: list[float] = []
            g = F.Feed()
            n = F.replay(rec, g, speed=2.0, sleep=slept.append)
            self.assertEqual(n, 3)
            self.assertEqual([round(s, 3) for s in slept], [0.5, 1.5])
            self.assertEqual([e["type"] for e in g.since(0)], ["hello", "call", "call"])
            self.assertEqual([e["t"] for e in g.since(0)], [100.0, 101.0, 104.0])   # original times are kept
            instant: list[float] = []
            F.replay(rec, F.Feed(), speed=0, sleep=instant.append)
            self.assertEqual(instant, [])


class FakeClient:
    """Answers the three queries the live poller runs, by what the Lua body starts with."""

    def __init__(self):
        self.calls: list[str] = []
        self.events: list[dict] = []
        self.event_seq = 0
        self.fail_map = False

    def query(self, state, body, timeout=None):
        assert state == "InGame"
        if "Map.IsWrapX()" in body and "legend" in body:
            self.calls.append("map")
            if self.fail_map:
                raise OSError("tunerd gone")
            return {"ok": True, "w": 2, "h": 2, "wrap": True,
                    "layers": {"terrain": ["GC", "PO"], "elev": ["..", ".."], "feature": ["..", ".."],
                               "river": ["..", ".."], "resource": ["..", ".."]}, "legend": {}}
        if "H.events" in body:
            self.calls.append("events")
            since = int(body.split("local since = ")[1].split("\n")[0])
            return {"events": [e for e in self.events if e["seq"] > since], "seq": self.event_seq}
        if "GetActivePlayer" in body:
            self.calls.append("snapshot")
            return {"ok": True, "turn": 5, "active": 0, "players": [], "cities": [], "units": []}
        raise AssertionError(body[:80])


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = os.path.join(self.tmp.name, "calls.jsonl")
        open(self.ledger, "w").close()
        self.notes = os.path.join(self.tmp.name, "notes")
        os.mkdir(self.notes)

    def tearDown(self):
        self.tmp.cleanup()

    def test_hello_then_cadence(self):
        feed, client = F.Feed(), FakeClient()
        live = F.Live(feed, client, self.ledger, self.notes, events_every=2.0, snapshot_every=8.0, notes_every=2.0,
                      settle=0.6, sleep=lambda s: None)
        self.assertTrue(live.step_hello())
        self.assertEqual(feed.state()["hello"]["map"]["w"], 2)
        live.tick(1000.0)                                    # first tick: events + snapshot + notes all due
        self.assertEqual(client.calls, ["map", "events", "snapshot"])
        live.tick(1000.5)                                    # nothing due
        self.assertEqual(len(client.calls), 3)
        with open(self.ledger, "a") as f:
            f.write(json.dumps({"t": 1000.7, "tool": "tactical_view", "kind": "read", "seat": 0}) + "\n")
            f.write(json.dumps({"t": 1000.8, "tool": "move_unit", "kind": "write", "seat": 0}) + "\n")
        live.tick(1001.0)
        calls = [e["data"]["tool"] for e in feed.since(0) if e["type"] == "call"]
        self.assertEqual(calls, ["tactical_view", "move_unit"])
        self.assertEqual(len(client.calls), 3, "a write asks for a snapshot after it settles, not at once")
        live.tick(1001.7)
        self.assertEqual(client.calls[-1], "snapshot")
        client.events = [{"seq": 1, "kind": "combat", "audience": 0}]
        client.event_seq = 1
        live.tick(1002.1)
        evs = [e["data"]["kind"] for e in feed.since(0) if e["type"] == "event"]
        self.assertEqual(evs, ["combat"])
        self.assertEqual(live.event_seq, 1)
        client.event_seq = 0                                 # a reload emptied the ring
        client.events = []
        live.tick(1004.2)
        self.assertEqual(live.event_seq, 0)

    def test_call_events_keep_the_ledger_time(self):
        feed, client = F.Feed(), FakeClient()
        live = F.Live(feed, client, self.ledger, self.notes, sleep=lambda s: None)
        with open(self.ledger, "a") as f:
            f.write(json.dumps({"t": 123.5, "tool": "units", "kind": "read"}) + "\n")
        live.step_ledger(999.0)
        self.assertEqual(feed.since(0)[0]["t"], 123.5)

    def test_map_failure_is_a_status_not_a_crash(self):
        feed, client = F.Feed(), FakeClient()
        client.fail_map = True
        live = F.Live(feed, client, self.ledger, self.notes, sleep=lambda s: None)
        self.assertFalse(live.step_hello())
        st = feed.since(0)
        self.assertEqual((st[0]["type"], st[0]["data"]["source"]), ("status", "map"))
        self.assertIn("tunerd gone", st[0]["data"]["err"])

    def test_notebooks_flow(self):
        feed, client = F.Feed(), FakeClient()
        live = F.Live(feed, client, self.ledger, self.notes, sleep=lambda s: None)
        pathlib.Path(self.notes, "g-seat1.json").write_text(json.dumps({"notes": [{"text": "hi"}]}))
        live.step_notes()
        nb = feed.state()["notebooks"]
        self.assertEqual(nb[1]["notes"][0]["text"], "hi")


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        web = pathlib.Path(cls.tmp.name)
        (web / "index.html").write_text("<!doctype html><title>viz</title>", encoding="utf-8")
        (web / "js").mkdir()
        (web / "js" / "app.js").write_text("export const x = 1;", encoding="utf-8")
        cls.feed = F.Feed()
        cls.feed.push("hello", {"map": {"w": 1}})
        cls.httpd = server.serve(cls.feed, "127.0.0.1", 0, web, background=True)
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def get(self, path: str, headers: dict | None = None) -> http.client.HTTPResponse:
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", path, headers=headers or {})
        return c.getresponse()

    def test_static_and_state(self):
        r = self.get("/")
        self.assertEqual((r.status, r.getheader("Content-Type")), (200, "text/html; charset=utf-8"))
        self.assertIn(b"viz", r.read())
        r = self.get("/js/app.js")
        self.assertEqual(r.status, 200)
        self.assertTrue(r.getheader("Content-Type").startswith(("text/javascript", "application/javascript")))
        self.assertEqual(self.get("/js/../../etc/passwd").status, 404)
        self.assertEqual(self.get("/nope.css").status, 404)
        st = json.loads(self.get("/state").read())
        self.assertEqual(st["hello"], {"map": {"w": 1}})

    def test_sse_resumes_from_last_event_id(self):
        r = self.get("/events", {"Last-Event-ID": "1"})
        self.assertEqual(r.getheader("Content-Type"), "text/event-stream; charset=utf-8")
        self.feed.push("call", {"tool": "units"})
        buf = b""
        r.fp.raw._sock.settimeout(3)  # type: ignore[attr-defined]
        while b"\n\n" not in buf:
            chunk = r.fp.read1(4096)
            if not chunk:
                break
            buf += chunk
        text = buf.decode()
        self.assertNotIn('"type":"hello"', text)
        self.assertIn("event: call\n", text)
        self.assertIn("id: 2\n", text)
        self.assertEqual(json.loads(text.split("data: ", 1)[1].split("\n")[0])["data"], {"tool": "units"})

    def test_sse_frame(self):
        self.assertEqual(server.sse({"seq": 3, "type": "x", "t": 1.0, "data": {}}),
                         b'id: 3\nevent: x\ndata: {"seq":3,"type":"x","t":1.0,"data":{}}\n\n')
