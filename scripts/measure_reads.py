#!/usr/bin/env python3
"""What the reads of one turn cost a model: response bytes, entities, tuner trips and wall time per read.

Read-only baseline for GitLab #35 (compact response modes): it calls the MCP tool functions in this
process, so each answer is the exact string a client receives (`J(...)`, color markup stripped), and it
counts the tuner round-trips behind each one by wrapping `Civ5.call` (as `play_loop.py --profile` does).
Nothing here ends a turn, gives an order, or consumes the turn digest.

Token counts: no client tokenizer is available here, so `~tok` is bytes / 4 and says so; compare bytes.

Usage:
    .venv/bin/python scripts/measure_reads.py --seat 0 --label "Venice t42"
    .venv/bin/python scripts/measure_reads.py --seat 0 --read todo_actions '{"detail": "summary"}'
    .venv/bin/python scripts/measure_reads.py --seat 0 --json out.jsonl   # append one JSON row per read
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])

# What a fresh context reads before it can decide (the context-recovery case), then the detail levels of
# the one high-volume read, then the broad read #30 contrasts the briefing with.
DEFAULT_READS: list[tuple[str, dict]] = [
    ("turn_status", {}),
    ("recall", {}),
    ("overview", {}),
    ("cities", {}),
    ("units", {}),
    ("todo_actions", {}),
    ("todo_actions", {"full": True}),
    ("todo_actions", {"unit_ids": "all"}),
    ("todo_actions", {"unit_ids": "all", "full": True}),
    ("known_world", {}),
]
RECOVERY = ["turn_status", "recall", "overview", "cities", "units", "todo_actions"]


def entities(v) -> int | None:
    """How many rows the answer carries: the list itself, or the list a known envelope wraps."""
    if isinstance(v, list):
        return len(v)
    if isinstance(v, dict):
        for k in ("units", "notes", "cities", "rows"):
            if isinstance(v.get(k), list):
                return len(v[k])
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seat", default="0")
    ap.add_argument("--label", default="")
    ap.add_argument("--read", nargs=2, action="append", metavar=("TOOL", "ARGS_JSON"),
                    help='measure this read instead of the default set (repeatable); "unit_ids": "all" '
                         'expands to every unit id')
    ap.add_argument("--json", help="append one JSON row per read to this file")
    args = ap.parse_args()
    os.environ["CIV5_SEAT"] = str(args.seat)
    os.environ.setdefault("CIV5_TUNERD_SOCK", os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000"),
                                                           "civ5-tuner.sock"))
    from harness import mcp_server as srv

    g = srv.game()
    trips = [0]
    inner = g.c.call

    def call(**req):
        trips[0] += 1
        return inner(**req)
    g.c.call = call

    reads = [(t, json.loads(a)) for t, a in args.read] if args.read else DEFAULT_READS
    rows = []
    for tool, targs in reads:
        fn = getattr(srv, tool)
        label_args = dict(targs)
        if targs.get("unit_ids") == "all":
            # The documented v213 case: every unit of the empire, not only the ones awaiting orders.
            targs = {**targs, "unit_ids": [u["id"] for u in json.loads(srv.units())]}
        trips[0] = 0
        t0 = time.perf_counter()
        out = fn(**targs)
        secs = time.perf_counter() - t0
        try:
            parsed = json.loads(out)
        except ValueError:
            parsed = None
        n = len(out.encode("utf-8"))
        rows.append({"label": args.label, "seat": g.seat, "tool": tool, "args": label_args, "bytes": n,
                     "approx_tokens": n // 4, "entities": entities(parsed), "trips": trips[0],
                     "seconds": round(secs, 2),
                     "ok": not (isinstance(parsed, dict) and parsed.get("ok") is False)})

    print(f"{args.label or '-'} (seat {g.seat})")
    print(f"{'read':<44} {'bytes':>8} {'~tok':>7} {'rows':>5} {'trips':>5} {'s':>6}")
    for r in rows:
        name = r["tool"] + (json.dumps(r["args"], separators=(",", ":")) if r["args"] else "")
        ent = "" if r["entities"] is None else r["entities"]
        flag = "" if r["ok"] else "  REFUSED"
        print(f"{name:<44} {r['bytes']:>8} {r['approx_tokens']:>7} {ent!s:>5} {r['trips']:>5} {r['seconds']:>6}{flag}")
    rec = [r for r in rows if r["tool"] in RECOVERY and not r["args"]]
    if rec:
        print(f"{'context recovery (' + str(len(rec)) + ' calls)':<44} {sum(r['bytes'] for r in rec):>8} "
              f"{sum(r['approx_tokens'] for r in rec):>7} {'':>5} {sum(r['trips'] for r in rec):>5} "
              f"{round(sum(r['seconds'] for r in rec), 2):>6}")
    if args.json:
        with open(args.json, "a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
