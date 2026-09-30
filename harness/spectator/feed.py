"""One sequenced stream out of every source, with a recorder, a replayer and the live poller.

Event shape: `{"seq": n, "t": unix_time, "type": ..., "data": {...}}`. Types: `hello` (the map and how to draw it),
`snapshot` (snapshot.py), `call` (one ledger row), `event` (one runtime event with its audience), `notebook` (one
seat's notes/assignments/orders), `status` (the spectator's own health). The ring keeps the last RING events for
SSE resumes; `state()` is what a page that just opened needs to draw the world at once.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable

from . import events as events_mod
from . import ledger_tail, mapdump, notebook_watch, snapshot

RING = 6000
RECENT_CALLS = 300
RECENT_EVENTS = 300


class Feed:
    def __init__(self, record_path: str | None = None, ring: int = RING):
        self.ring: list[dict] = []
        self.ring_max = ring
        self.seq = 0
        self.cond = threading.Condition()
        self.record_path = record_path
        self.hello: dict | None = None
        self.snapshot: dict | None = None
        self.notebooks: dict[int, dict] = {}
        self.calls: list[dict] = []
        self.events: list[dict] = []

    def push(self, type_: str, data: dict, t: float | None = None) -> dict:
        with self.cond:
            self.seq += 1
            ev = {"seq": self.seq, "t": round(t if t is not None else time.time(), 3), "type": type_, "data": data}
            self.ring.append(ev)
            if len(self.ring) > self.ring_max:
                del self.ring[: len(self.ring) - self.ring_max]
            self._remember(ev)
            self.cond.notify_all()
        if self.record_path:
            try:
                with open(self.record_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(ev, separators=(",", ":"), ensure_ascii=False) + "\n")
            except OSError:
                pass
        return ev

    def _remember(self, ev: dict) -> None:
        t, d = ev["type"], ev["data"]
        if t == "hello":
            self.hello = d
        elif t == "snapshot":
            self.snapshot = d
        elif t == "notebook" and isinstance(d.get("seat"), int):
            self.notebooks[d["seat"]] = d
        elif t == "call":
            self.calls.append(ev)
            del self.calls[:-RECENT_CALLS]
        elif t == "event":
            self.events.append(ev)
            del self.events[:-RECENT_EVENTS]

    def since(self, seq: int) -> list[dict]:
        with self.cond:
            return [e for e in self.ring if e["seq"] > seq]

    def wait(self, seq: int, timeout: float) -> list[dict]:
        """Events after `seq`, waiting up to `timeout` for the first one."""
        with self.cond:
            self.cond.wait_for(lambda: self.seq > seq, timeout=timeout)
            return [e for e in self.ring if e["seq"] > seq]

    def state(self) -> dict:
        with self.cond:
            return {"seq": self.seq, "hello": self.hello, "snapshot": self.snapshot,
                    "notebooks": dict(self.notebooks), "calls": list(self.calls), "events": list(self.events)}


# ------------------------------------------------------------------ live

class Live:
    """Poll every source into a feed. `client` is a raw harness.client.Civ5 (query only)."""

    def __init__(self, feed: Feed, client: Any, ledger_path: str | None, notes_dir: str | None = None,
                 ledger_every: float = 0.5, events_every: float = 2.0, snapshot_every: float = 8.0,
                 notes_every: float = 2.0, settle: float = 0.6, sleep: Callable[[float], None] = time.sleep):
        self.feed, self.client = feed, client
        self.tail = ledger_tail.LedgerTail(ledger_path) if ledger_path else None
        self.notes = notebook_watch.NotebookWatch(notes_dir)
        self.ledger_every, self.events_every = ledger_every, events_every
        self.snapshot_every, self.notes_every, self.settle = snapshot_every, notes_every, settle
        self.sleep = sleep
        self.event_seq = 0
        self.snapshot_due = 0.0          # a write-kind call asks for a snapshot `settle` seconds later
        self.last = {"events": 0.0, "snapshot": 0.0, "notes": 0.0}
        self.stop = threading.Event()
        self.map_key: str | None = None

    # each source is one guarded step so a tunerd blip never takes the others down
    def step_hello(self) -> bool:
        try:
            m = mapdump.read(self.client)
        except Exception as e:  # noqa: BLE001
            self.feed.push("status", {"source": "map", "err": str(e)[:200]})
            return False
        if not mapdump.valid(m):
            self.feed.push("status", {"source": "map", "err": f"unexpected map reply {str(m)[:120]}"})
            return False
        self.feed.push("hello", {"map": m})
        return True

    def step_ledger(self, now: float) -> None:
        if not self.tail:
            return
        for row in self.tail.poll():
            self.feed.push("call", row, t=row.get("t") if isinstance(row.get("t"), (int, float)) else None)
            if row.get("kind") in ("write", "wait"):
                self.snapshot_due = now + self.settle

    def step_events(self) -> None:
        try:
            evs, seq = events_mod.read(self.client, self.event_seq)
        except Exception as e:  # noqa: BLE001
            self.feed.push("status", {"source": "events", "err": str(e)[:200]})
            return
        if seq < self.event_seq:            # the ring was reset: start over
            self.event_seq = 0
            return
        for e in evs:
            self.feed.push("event", e)
        self.event_seq = seq

    def step_snapshot(self) -> None:
        try:
            s = snapshot.read(self.client)
        except Exception as e:  # noqa: BLE001
            self.feed.push("status", {"source": "snapshot", "err": str(e)[:200]})
            return
        if snapshot.valid(s):
            self.feed.push("snapshot", s)

    def step_notes(self) -> None:
        for rec in self.notes.poll():
            self.feed.push("notebook", rec)

    def tick(self, now: float) -> None:
        self.step_ledger(now)
        if now - self.last["events"] >= self.events_every:
            self.step_events()
            self.last["events"] = now
        if (self.snapshot_due and now >= self.snapshot_due) or now - self.last["snapshot"] >= self.snapshot_every:
            self.snapshot_due = 0.0
            self.step_snapshot()
            self.last["snapshot"] = now
        if now - self.last["notes"] >= self.notes_every:
            self.step_notes()
            self.last["notes"] = now

    def run(self) -> None:
        while not self.stop.is_set() and not self.step_hello():
            self.sleep(5.0)
        while not self.stop.is_set():
            self.tick(time.time())
            self.sleep(self.ledger_every)


# ------------------------------------------------------------------ replay

def replay(path: str, feed: Feed, speed: float = 1.0, sleep: Callable[[float], None] = time.sleep,
           stop: threading.Event | None = None) -> int:
    """Re-push a recorded stream with its original spacing divided by `speed` (0 = as fast as possible).
    Returns how many events were pushed."""
    n = 0
    prev: float | None = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            if stop is not None and stop.is_set():
                break
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if not isinstance(ev, dict) or "type" not in ev:
                continue
            t = ev.get("t")
            if speed > 0 and prev is not None and isinstance(t, (int, float)):
                gap = (t - prev) / speed
                if gap > 0:
                    sleep(min(gap, 30.0 / speed))
            if isinstance(t, (int, float)):
                prev = t
            feed.push(ev["type"], ev.get("data") or {}, t=t if isinstance(t, (int, float)) else None)
            n += 1
    return n
