"""Advance a two-seat hotseat game until someone has to decide something.

Alternates the seats: waits for a seat's turn, opens it (first-meeting greetings clicked through; with
--accept-swaps, plain embassy / open-borders exchanges accepted), ends the turn when the briefing lists no
decision, and stops at the first turn that lists one (or a leader with a real question), printing that
briefing. Nothing else is decided for the seat: units, cities, research and every other offer are left to
whoever plays it. Each call runs through scripts/mcp_session.py, so a fresh server (the code on disk) plays.

    .venv/bin/python scripts/hotseat_rounds.py --first-seat 0 --turns 10 [--accept-swaps]

Written 2026-09-27 while one operator played both seats of the Venice/Mongolia game.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent)
ENV = {**os.environ}
if "CIV5_TUNERD_SOCK" not in ENV and os.environ.get("XDG_RUNTIME_DIR"):
    ENV["CIV5_TUNERD_SOCK"] = os.path.join(os.environ["XDG_RUNTIME_DIR"], "civ5-tuner.sock")
ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--first-seat", type=int, default=0, help="the seat to wait for first")
ap.add_argument("--turns", type=int, default=6, help="at most this many turn ends")
ap.add_argument("--wait", type=int, default=800, help="wait_for_my_turn timeout per seat, seconds")
ap.add_argument("--accept-swaps", action="store_true", help="accept offers made only of embassies / open borders")
args = ap.parse_args()
seat = args.first_seat
MAX_TURNS = args.turns


def call(seat, *pairs):
    cmd = [f"{ROOT}/.venv/bin/python", f"{ROOT}/scripts/mcp_session.py", "--seat", str(seat), "--keep-going", *pairs]
    out = subprocess.run(cmd, cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=1500).stdout
    res = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("=="):
            continue
        try:
            res.append(json.loads(line))
        except ValueError:
            res.append({"raw": line[:300]})
    return res or [{}]


def open_turn(seat) -> dict | None:
    """Clear what can be cleared without a decision; the briefing, or None when a real decision is pending."""
    for _ in range(8):
        status = call(seat, "turn_status", "{}")[0]
        gate = status.get("gate")
        if gate is None:
            break
        name = gate.get("name")
        if name == "leader_screen":
            r = call(seat, "dismiss_discussion", "{}")[0]
            print(f"  seat {seat}: greeting closed ({r.get('closed_count')}), next={json.dumps(r.get('next'))[:120]}", flush=True)
            continue
        if name == "discussion":
            d = call(seat, "discussion", "{}")[0]
            if d.get("screen") == "trade":
                items = (call(seat, "incoming_deal", "{}")[0]).get("items") or []
                kinds = sorted({it.get("type") for it in items})
                desc = [(it.get("type"), it.get("resource"), it.get("amount"), it.get("from_us")) for it in items]
                if args.accept_swaps and items and all(k in ("ALLOW_EMBASSY", "OPEN_BORDERS") for k in kinds):
                    r = call(seat, "accept_deal", "{}")[0]
                    print(f"  seat {seat}: accepted {desc} from {d.get('leader')}: {r.get('remark')}", flush=True)
                    continue
                print(f"  seat {seat}: offer from {d.get('leader')} needs a decision: {desc}", flush=True)
                return None
            print(f"  seat {seat}: {d.get('leader')} ({d.get('mood')}) asks: {d.get('speech')}", flush=True)
            print(f"  buttons: {json.dumps(d.get('buttons'))}", flush=True)
            return None
        print(f"  seat {seat}: gate {json.dumps(gate)[:200]}", flush=True)
        return None
    return call(seat, "briefing", json.dumps({"limit": 8}))[0]


for _ in range(MAX_TURNS):
    status = call(seat, "wait_for_my_turn", json.dumps({"timeout_seconds": args.wait}))[0]
    turn = status.get("turn")
    if status.get("timed_out"):
        print(f"seat {seat}: wait timed out at turn {turn}", flush=True)
        break
    brief = open_turn(seat)
    if brief is None:
        break
    decisions = brief.get("decisions") or []
    print(f"seat {seat} turn {turn}: decisions={len(decisions)} warnings={len(brief.get('warnings') or [])}", flush=True)
    if brief.get("orders"):
        print(f"  orders: {json.dumps(brief['orders'])[:400]}", flush=True)
    if decisions:
        print(json.dumps({k: brief.get(k) for k in ("decisions", "warnings", "opportunities", "cities")})[:2500], flush=True)
        events = ((brief.get("changes") or {}).get("events") or {}).get("items") or []
        print("events:", json.dumps(events)[:800], flush=True)
        break
    end = call(seat, "end_turn", "{}")[0]
    print(f"seat {seat} end_turn -> ok={end.get('ok')} {end.get('err') or ''}", flush=True)
    if not end.get("ok"):
        break
    seat = 1 - seat
else:
    print("turn budget spent", flush=True)
