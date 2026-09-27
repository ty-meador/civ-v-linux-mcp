#!/usr/bin/env python3
"""Per-turn cost of play from a call ledger (`CIV5_CALL_LOG`, harness/call_ledger.py; GitLab #36).

A turn is every call up to and including the wait that ends it (end_turn / finish_turn / wait_for_my_turn).
Inspection (reads) and orders (writes) are counted apart from waiting, whose seconds are the AIs' turns and the
bridge, not the model's overhead. `~tok` is bytes / 4: no client tokenizer is available here.

Usage:
    .venv/bin/python scripts/ledger_report.py calls.jsonl [--seat 0] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys


def load(path: str, seat: int | None) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if seat is None or r.get("seat") == seat:
                rows.append(r)
    return rows


def turns(rows: list[dict]) -> list[dict]:
    """Split rows into turns at each wait; the turn number is the first one a non-wait answer named, else the
    one the previous wait returned."""
    out, cur, last_turn = [], [], None
    for r in rows:
        cur.append(r)
        if r["kind"] == "wait":
            out.append(summarize(cur, last_turn))
            last_turn = r.get("turn", last_turn)
            cur = []
    if cur:
        out.append({**summarize(cur, last_turn), "open": True})
    return out


def summarize(rows: list[dict], fallback_turn: int | None) -> dict:
    reads = [r for r in rows if r["kind"] == "read"]
    writes = [r for r in rows if r["kind"] == "write"]
    waits = [r for r in rows if r["kind"] == "wait"]
    turn = next((r["turn"] for r in rows if r["kind"] != "wait" and isinstance(r.get("turn"), int)), fallback_turn)
    return {
        "turn": turn,
        "reads": len(reads), "read_bytes": sum(r["bytes"] for r in reads),
        "read_trips": sum(r.get("trips") or 0 for r in reads),
        "read_seconds": round(sum(r["seconds"] for r in reads), 1),
        "writes": len(writes), "write_bytes": sum(r["bytes"] for r in writes),
        "refused": sum(1 for r in writes if not r["ok"]),
        "refused_reads": sum(1 for r in reads if not r["ok"]),
        "wait_refused": sum(1 for r in waits if not r["ok"]),
        "wait_seconds": round(sum(r["seconds"] for r in waits), 1),
        "tools": sorted({r["tool"] for r in reads}),
        "refusals": [f"{r['tool']}: {r.get('err', '')}" for r in rows if not r["ok"]],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ledger")
    ap.add_argument("--seat", type=int)
    ap.add_argument("--json", action="store_true", help="one JSON object per turn instead of the table")
    a = ap.parse_args()
    ts = turns(load(a.ledger, a.seat))
    if a.json:
        for t in ts:
            print(json.dumps(t))
        return 0
    print(f"{'turn':>5} {'reads':>5} {'bytes':>7} {'~tok':>6} {'trips':>5} {'read s':>6} "
          f"{'writes':>6} {'refused':>7} {'wait s':>7}")
    for t in ts:
        mark = " (open)" if t.get("open") else ""
        print(f"{t['turn']!s:>5} {t['reads']:>5} {t['read_bytes']:>7} {t['read_bytes'] // 4:>6} {t['read_trips']:>5} "
              f"{t['read_seconds']:>6} {t['writes']:>6} {t['refused']:>7} {t['wait_seconds']:>7}{mark}")
    done = [t for t in ts if not t.get("open")]
    if done:
        n = len(done)
        print(f"{'mean':>5} {sum(t['reads'] for t in done) / n:>5.1f} {sum(t['read_bytes'] for t in done) / n:>7.0f} "
              f"{sum(t['read_bytes'] for t in done) / n / 4:>6.0f} {sum(t['read_trips'] for t in done) / n:>5.1f} "
              f"{sum(t['read_seconds'] for t in done) / n:>6.1f} {sum(t['writes'] for t in done) / n:>6.1f} "
              f"{sum(t['refused'] for t in done) / n:>7.1f} {sum(t['wait_seconds'] for t in done) / n:>7.1f}"
              f"   over {n} completed turn(s)")
    for t in ts:
        for msg in t["refusals"]:
            print(f"  t{t['turn']} refused {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
