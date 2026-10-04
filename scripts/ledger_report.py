#!/usr/bin/env python3
"""Per-turn cost of play from a call ledger (`CIV5_CALL_LOG`, harness/call_ledger.py; GitLab #36).

A turn is every call up to and including the wait that ends it (end_turn / finish_turn / wait_for_my_turn).
Inspection (reads) and orders (writes) are counted apart from waiting, whose seconds are the AIs' turns and the
bridge, not the model's overhead. `~tok` is bytes / 4: no client tokenizer is available here.

A row's `client` (CIV5_CLIENT in the server's environment, else the MCP client's name/version) says who made
the call: `--client codex` keeps the rows whose label contains that text, and the footer lists every label seen
with its rows and turns, so two models on the same seat stay apart.

Usage:
    .venv/bin/python scripts/ledger_report.py calls.jsonl [--seat 0] [--client codex] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys


def load(path: str, seat: int | None, client: str | None = None) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if seat is not None and r.get("seat") != seat:
                continue
            if client is not None and client not in (r.get("client") or ""):
                continue
            rows.append(r)
    return rows


def clients(rows: list[dict]) -> list[dict]:
    """Every `client` label in the rows (None for rows without one): rows, seats and the turns it spans."""
    by: dict = {}
    for r in rows:
        c = by.setdefault(r.get("client"), {"client": r.get("client"), "rows": 0, "seats": set(), "turns": []})
        c["rows"] += 1
        c["seats"].add(r.get("seat"))
        if isinstance(r.get("turn"), int):
            c["turns"].append(r["turn"])
    out = []
    for c in by.values():
        ts = sorted(c["turns"])
        out.append({"client": c["client"], "rows": c["rows"], "seats": sorted(c["seats"], key=str),
                    "first_turn": ts[0] if ts else None, "last_turn": ts[-1] if ts else None})
    return sorted(out, key=lambda c: (c["client"] is None, str(c["client"])))


def turns(rows: list[dict]) -> list[dict]:
    """Split rows into turns at each wait that succeeded (a refused end_turn leaves the turn open); waits
    straight after it (end_turn, then wait_for_my_turn) belong to the same turn. The turn number is the first
    one a non-wait answer named, else the one the previous wait returned."""
    groups, cur, closed = [], [], False
    for r in rows:
        if closed and r["kind"] != "wait":
            groups.append(cur)
            cur, closed = [], False
        cur.append(r)
        if r["kind"] == "wait" and r["ok"]:
            closed = True
    out, last_turn = [], None
    for g in groups + ([cur] if cur else []):
        t = summarize(g, last_turn)
        last_turn = next((r["turn"] for r in reversed(g) if r["kind"] == "wait" and isinstance(r.get("turn"), int)),
                         last_turn)
        out.append(t)
    if cur and not closed:
        out[-1]["open"] = True
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
    ap.add_argument("--client", help="only rows whose `client` label contains this text (e.g. codex, grok, claude)")
    ap.add_argument("--json", action="store_true", help="one JSON object per turn instead of the table")
    a = ap.parse_args()
    rows = load(a.ledger, a.seat, a.client)
    ts = turns(rows)
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
    for c in clients(rows):
        span = f"t{c['first_turn']}-t{c['last_turn']}" if c["first_turn"] is not None else "no turn"
        print(f"client {c['client'] or '(none)'}: {c['rows']} rows, seat {','.join(map(str, c['seats']))}, {span}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
