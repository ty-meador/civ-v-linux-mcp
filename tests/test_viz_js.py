"""The page's ES modules (web/viz/js) under node: every module parses, and the DOM-free timeline/player (the
scrubber's clock) behaves -- a seek forward applies the rows between, a seek backwards rebuilds from the first
row, a jump applies every call but only the latest hello / snapshot / notebook-per-seat before the target
(Timeline.plan), playing skips recorded silence, a live tail is followed again once the clock catches up,
duplicate SSE rows are dropped by seq, and the turn boundaries come from the snapshots; feed.readLines parses
the recording off a byte stream one line at a time. Skipped without node."""
from __future__ import annotations

import json
import math
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
JS = ROOT / "web" / "viz" / "js"
NODE = shutil.which("node")

PLAYER_SCRIPT = """
import { Timeline, Player, MAX_GAP } from "%(url)s";
const out = {};
const tl = new Timeline();
const rows = [
  { seq: 1, t: 100.0, type: "hello", data: { map: { w: 2, h: 2 } } },
  { seq: 2, t: 101.0, type: "snapshot", data: { turn: 5, active: 0 } },
  { seq: 3, t: 100.5, type: "call", data: { tool: "units", seat: 0 } },      // a ledger row's own t is earlier
  { seq: 4, t: 103.0, type: "call", data: { tool: "move_unit", seat: 0 } },
  { seq: 5, t: 103.0, type: "snapshot", data: { turn: 5, active: 1 } },     // the other seat's turn begins
  { seq: 6, t: 200.0, type: "snapshot", data: { turn: 6, active: 0 } },     // after 97 s of silence
  { seq: 6, t: 201.0, type: "call", data: { tool: "dup" } },                // the SSE repeating a recorded row
];
out.added = rows.map((r) => tl.add(r));
out.tm = tl.rows.map((r) => r.tm);
out.countAt = [tl.countAt(99), tl.countAt(101), tl.countAt(103), tl.countAt(1000)];
out.turns = tl.turns().map((b) => [b.turn, b.active, b.t]);

const log = [];
let now = 10000;
const hooks = {
  apply: (row, arrived, jump) => log.push(["apply", row.seq, Math.round(arrived), jump]),
  reset: () => log.push(["reset"]),
  settled: () => log.push(["settled"]),
};
const p = new Player(tl, hooks, { mode: "live", now: () => now });
p.seek(101.0);                                   // forward from nothing: hello, snapshot, the early call
out.seek1 = { cursor: p.cursor, clock: p.clock, following: p.following, log: log.splice(0) };
p.seek(100.0);                                   // backwards: rebuild from the first row
out.seek2 = { cursor: p.cursor, log: log.splice(0) };
p.play();
now += 1000; p.step(now);                        // clock 101.0: rows 2 and 3 fall due
out.step1 = { cursor: p.cursor, clock: p.clock, log: log.splice(0) };
now += 2000; p.step(now);                        // clock 103.0: rows 4 and 5
out.step2 = { cursor: p.cursor, clock: p.clock, log: log.splice(0) };
now += 100; p.step(now);                         // 97 s of silence ahead: the clock jumps to row 6 and applies it
out.step3 = { cursor: p.cursor, clock: p.clock, following: p.following, playing: p.playing, log: log.splice(0), gap: MAX_GAP };
out.pushDup = p.push({ seq: 6, t: 201.0, type: "call", data: {} });
out.pushNew = p.push({ seq: 7, t: 202.0, type: "call", data: { tool: "end_turn" } });   // following: applied at once
out.afterPush = { cursor: p.cursor, clock: p.clock, log: log.splice(0) };
p.seek(101.0);                                   // back in time: not following any more, the tail only lengthens
out.pushBehind = p.push({ seq: 8, t: 203.0, type: "snapshot", data: { turn: 7, active: 1 } });
out.behind = { cursor: p.cursor, following: p.following, length: tl.length, applied: log.filter((l) => l[0] === "apply" && l[1] === 8).length };
p.live();
out.live = { cursor: p.cursor, following: p.following, clock: p.clock };

const r = new Player(new Timeline(), hooks, { mode: "replay", now: () => now });
for (const row of rows.slice(0, 2)) r.tl.add(row);
r.toStart(); r.play(); now += 5000; r.step(now);
out.replayEnd = { playing: r.playing, cursor: r.cursor, following: r.following };

// a jump through a long stretch: every call/event/status row; of hello, snapshot and each seat's notebook only the
// latest before each call and before the target
const big = new Timeline();
[
  { seq: 1, t: 1, type: "hello", data: { map: {} } },
  { seq: 2, t: 2, type: "snapshot", data: { turn: 1, active: 0 } },
  { seq: 3, t: 3, type: "snapshot", data: { turn: 1, active: 1 } },          // replaces 2
  { seq: 4, t: 4, type: "notebook", data: { seat: 0, notes: ["a"] } },
  { seq: 5, t: 5, type: "notebook", data: { seat: 0, notes: ["a", "b"] } },  // replaces 4
  { seq: 6, t: 6, type: "call", data: { tool: "units", seat: 0 } },          // painted against 3 and 5
  { seq: 7, t: 7, type: "snapshot", data: { turn: 1, active: 1 } },
  { seq: 8, t: 8, type: "event", data: { kind: "turn" } },                    // reads no state: 7 need not stay
  { seq: 9, t: 9, type: "snapshot", data: { turn: 2, active: 0 } },
  { seq: 10, t: 10, type: "notebook", data: { seat: 1, notes: [] } },
  { seq: 11, t: 11, type: "hello", data: { map: {} } },                       // the spectator re-attached
  { seq: 12, t: 12, type: "status", data: { source: "ledger" } },
  { seq: 13, t: 13, type: "snapshot", data: { turn: 2, active: 1 } },         // replaces 9
  { seq: 14, t: 14, type: "call", data: { tool: "end_turn", seat: 1 } },
].forEach((row) => big.add(row));
out.planAll = big.plan(0, 14).map((i) => big.rows[i].seq);
out.planMid = big.plan(0, 5).map((i) => big.rows[i].seq);
out.planFrom = big.plan(6, 14).map((i) => big.rows[i].seq);
const applied = [];
const q = new Player(big, { apply: (row) => applied.push(row.seq), reset: () => applied.push("reset") }, { mode: "replay", now: () => now });
q.seek(14); out.seekAll = { cursor: q.cursor, applied: applied.splice(0) };
q.seek(5); out.seekBack = { cursor: q.cursor, applied: applied.splice(0) };
q.seek(13); out.seekOn = { cursor: q.cursor, applied: applied.splice(0) };
console.log(JSON.stringify(out));
"""

READLINES_SCRIPT = """
import { readLines } from "%(url)s";
const enc = new TextEncoder();
const chunks = ['{"seq":1,"type":"call"}\\n{"seq":2,"ty', 'pe":"snapshot","data":{"u":"\\u00e9"}}\\n', '\\n{"seq":3}\\n{"seq":4,"half', ''];
let i = 0;
const reader = new ReadableStream({ pull(c) { if (i < chunks.length) c.enqueue(enc.encode(chunks[i++])); else c.close(); } }).getReader();
const rows = [];
const n = await readLines(reader, (row) => rows.push(row));
console.log(JSON.stringify({ n, rows }));
"""


@unittest.skipUnless(NODE, "node is not installed")
class VizModuleTests(unittest.TestCase):
    def node(self, script: str) -> str:
        r = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_every_module_parses(self):
        files = sorted(JS.glob("*.js"))
        self.assertGreaterEqual(len(files), 10)
        for f in files:
            with self.subTest(module=f.name):
                r = subprocess.run([NODE, "--input-type=module", "--check"], input=f.read_text(encoding="utf-8"),
                                   capture_output=True, text=True, timeout=30)
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_timeline_and_player(self):
        out = json.loads(self.node(PLAYER_SCRIPT % {"url": (JS / "timeline.js").as_uri()}))
        self.assertEqual(out["added"], [True] * 6 + [False])                       # the repeated seq is dropped
        self.assertEqual(out["tm"], [100.0, 101.0, 101.0, 103.0, 103.0, 200.0])    # time never goes back
        self.assertEqual(out["countAt"], [0, 3, 5, 6])
        self.assertEqual(out["turns"], [[5, 0, 101.0], [5, 1, 103.0], [6, 0, 200.0]])
        # a seek forward applies the rows between as a jump, with arrival times set back by their age
        s1 = out["seek1"]
        self.assertEqual((s1["cursor"], s1["clock"], s1["following"]), (3, 101.0, False))
        self.assertEqual(s1["log"], [["apply", 1, 9000, True], ["apply", 2, 10000, True], ["apply", 3, 10000, True], ["settled"]])
        # backwards: reset, then from the first row
        self.assertEqual(out["seek2"], {"cursor": 1, "log": [["reset"], ["apply", 1, 10000, True], ["settled"]]})
        # playing at 1x: the clock advances with the page's clock and rows fall due, as live arrivals
        self.assertEqual(out["step1"]["cursor"], 3)
        self.assertEqual([entry[1:] for entry in out["step1"]["log"]], [[2, 11000, False], [3, 11000, False]])
        self.assertEqual((out["step2"]["cursor"], out["step2"]["clock"]), (5, 103.0))
        # silence longer than MAX_GAP is skipped; the tail reached in live mode means following again
        s3 = out["step3"]
        self.assertEqual((s3["cursor"], s3["clock"], s3["following"], s3["playing"]), (6, 200.0, True, True))
        self.assertEqual([entry[1] for entry in s3["log"] if entry[0] == "apply"], [6])
        self.assertEqual((out["pushDup"], out["pushNew"]), (False, True))
        self.assertEqual((out["afterPush"]["cursor"], out["afterPush"]["clock"]), (7, 202.0))
        self.assertEqual([entry[1:] for entry in out["afterPush"]["log"]], [[7, 13100, False]])
        # behind the tail a pushed row only lengthens the slider
        self.assertEqual(out["pushBehind"], True)
        self.assertEqual(out["behind"], {"cursor": 3, "following": False, "length": 8, "applied": 0})
        self.assertEqual(out["live"], {"cursor": 8, "following": True, "clock": 203.0})
        # a replayed file simply ends
        self.assertEqual(out["replayEnd"], {"playing": False, "cursor": 2, "following": False})
        # a jump keeps every call/event/status row, and of the state rows (hello, snapshot, a seat's notebook) the latest
        # before each call and before the target: 2 and 4 are replaced before the call at 6, 7 and 9 before 13
        self.assertEqual(out["planAll"], [1, 3, 5, 6, 8, 10, 11, 12, 13, 14])
        self.assertEqual(out["planMid"], [1, 3, 5])                         # up to row 5: no call, the latest of each
        self.assertEqual(out["planFrom"], [8, 10, 11, 12, 13, 14])          # from row 7 on
        self.assertEqual(out["seekAll"], {"cursor": 14, "applied": [1, 3, 5, 6, 8, 10, 11, 12, 13, 14]})
        self.assertEqual(out["seekBack"], {"cursor": 5, "applied": ["reset", 1, 3, 5]})
        self.assertEqual(out["seekOn"], {"cursor": 13, "applied": [6, 8, 10, 11, 12, 13]})   # forward: the rows between, likewise

    def test_readlines_streams_the_recording(self):
        out = json.loads(self.node(READLINES_SCRIPT % {"url": (JS / "feed.js").as_uri()}))
        # lines split across chunks are joined, a blank line is skipped, a non-ASCII character decodes, and the half
        # line a file ends on is dropped
        self.assertEqual(out["n"], 3)
        self.assertEqual(out["rows"], [{"seq": 1, "type": "call"}, {"seq": 2, "type": "snapshot", "data": {"u": "é"}}, {"seq": 3}])


HEX_SCRIPT = """
import * as H from "%(url)s";
const out = {};
const w = 10, h = 7;
// every plot's centre maps back to the plot; a point just inside each corner still does; the wrap column wraps
let bad = 0, corner = 0;
for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
  const [cx, cy] = H.centre(x, y, h);
  const p = H.plotAt(cx, cy, w, h);
  if (!p || p[0] !== x || p[1] !== y) bad++;
  for (let i = 0; i < 6; i++) {
    const a = Math.PI / 180 * (60 * i - 30);
    const q = H.plotAt(cx + H.R * 0.9 * Math.cos(a), cy + H.R * 0.9 * Math.sin(a), w, h);
    if (!q || q[0] !== x || q[1] !== y) corner++;
  }
}
out.bad = bad; out.corner = corner;
const [ex, ey] = H.centre(w, 3, h);                        // one hex past the east edge of an odd row
out.wrapped = H.plotAt(ex, ey, w, h);
out.unwrapped = H.plotAt(ex, ey, w, h, false);
out.offNorth = H.plotAt(5, -3 * H.R, w, h);
// the fit transform shows the whole map; a close zoom shows a window around its centre; a transform off the map shows nothing
const mapW = (w + 0.5) * H.HW, mapH = (h - 1) * H.VS + 2 * H.R, W = 800, Hh = 600;
const k = Math.min(W / mapW, Hh / mapH);
out.fit = H.visibleRange({ k, x: (W - mapW * k) / 2, y: (Hh - mapH * k) / 2 }, W, Hh, w, h);
const [mx, my] = H.centre(5, 3, h), K = 40;
out.close = H.visibleRange({ k: K, x: W / 2 - mx * K, y: Hh / 2 - my * K }, W, Hh, w, h);
out.off = H.visibleRange({ k: 1, x: -5000, y: 0 }, W, Hh, w, h);
// tracePath draws six corners and closes, scaled
const calls = [];
const stub = { moveTo: (x, y) => calls.push(["m", +x.toFixed(2), +y.toFixed(2)]), lineTo: (x, y) => calls.push(["l", +x.toFixed(2), +y.toFixed(2)]), closePath: () => calls.push(["z"]) };
H.tracePath(stub, 100, 50, 0.5);
out.trace = calls;
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "node is not installed")
class HexHelperTests(unittest.TestCase):
    """The canvas helpers in hex.js: plotAt inverts centre (every plot, points near the corners, the wrap column),
    visibleRange clips a transform's window to the map, tracePath traces six corners onto any path-like object."""

    def test_plot_at_visible_range_trace_path(self):
        r = subprocess.run([NODE, "--input-type=module", "-e", HEX_SCRIPT % {"url": (JS / "hex.js").as_uri()}],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["bad"], 0)
        self.assertEqual(out["corner"], 0)
        self.assertEqual(out["wrapped"], [0, 3])
        self.assertIsNone(out["unwrapped"])
        self.assertIsNone(out["offNorth"])
        self.assertEqual(out["fit"], {"x0": 0, "x1": 9, "y0": 0, "y1": 6})
        close = out["close"]
        self.assertTrue(close["x0"] <= 5 <= close["x1"] and close["y0"] <= 3 <= close["y1"], close)
        self.assertLess(close["x1"] - close["x0"], 9, close)                      # a window, not the whole map
        self.assertIsNone(out["off"])
        self.assertEqual(out["trace"][0][0], "m")
        self.assertEqual([c[0] for c in out["trace"]], ["m"] + ["l"] * 5 + ["z"])
        # the first corner is at -30 degrees from the centre, scaled by 0.5
        self.assertAlmostEqual(out["trace"][0][1], 100 + 9 * 0.5 * math.cos(-math.pi / 6), places=1)
        self.assertAlmostEqual(out["trace"][0][2], 50 + 9 * 0.5 * math.sin(-math.pi / 6), places=1)
