"""The page's ES modules (web/viz/js) under node: every module parses, and the DOM-free timeline/player (the
scrubber's clock) behaves -- a seek forward applies the rows between, a seek backwards rebuilds from the first
row, playing skips recorded silence, a live tail is followed again once the clock catches up, duplicate SSE rows
are dropped by seq, and the turn boundaries come from the snapshots. Skipped without node."""
from __future__ import annotations

import json
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
console.log(JSON.stringify(out));
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
