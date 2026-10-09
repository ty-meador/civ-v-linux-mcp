#!/usr/bin/env python3
"""Finish ONE seat's current turn with the play loop's heuristics and end it.

`scripts/play_loop.py` plays turn after turn unattended; this is the single-turn cut of it for a
session where a person (or an LLM) makes the interesting decisions by hand and wants the
bookkeeping -- empty production queues, promotions, idle Workers, World Congress proposals,
a unit still needing orders -- cleared so the turn can end. Nothing here attacks, trades, or
signs anything: a diplomatic approach is declined, exactly as the loop does.

Usage:
    .venv/bin/python scripts/finish_turn.py --seat 1 [--attempts 12]

Exit 0 once end_turn is accepted, 2 when the same blocker survives every attempt.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.game import Game  # noqa: E402

_spec = importlib.util.spec_from_file_location("play_loop", ROOT / "scripts" / "play_loop.py")
play_loop = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(play_loop)


def propose_something(g: Game, seat: int) -> bool:
    """ENDTURN_BLOCKING_LEAGUE_CALL_FOR_PROPOSALS: propose the first resolution that needs no choice."""
    st = g.league_status(seat) or {}
    for row in st.get("proposable_enact") or []:
        rt = row.get("resolution_type")
        if rt and g.league_propose_enact(rt, -1, seat).get("ok"):
            play_loop.log(f"  proposed {rt}")
            return True
    for row in st.get("proposable_repeal") or []:
        rid = row.get("resolution_id", row.get("id"))
        if rid is not None and g.league_propose_repeal(int(rid), seat).get("ok"):
            play_loop.log(f"  proposed repealing {row.get('name') or rid}")
            return True
    return False


HANDLERS = dict(play_loop.BLOCKER_HANDLERS)
HANDLERS.setdefault("ENDTURN_BLOCKING_LEAGUE_CALL_FOR_PROPOSALS", propose_something)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seat", type=int, required=True)
    ap.add_argument("--attempts", type=int, default=12)
    a = ap.parse_args()
    g = Game()
    g.seat = a.seat
    ts = g.wait_for_my_turn(timeout=120)
    for attempt in range(1, a.attempts + 1):
        blocking = ts.get("blocking_name")
        if blocking and blocking != "NO_ENDTURN_BLOCKING_TYPE":
            play_loop.log(f"seat {a.seat} turn {ts.get('turn')}: {blocking} (attempt {attempt})")
            handler = HANDLERS.get(blocking)
            if handler is None:
                play_loop.log(f"  no handler for {blocking}")
                return 2
            try:
                if not handler(g, a.seat):
                    play_loop.log("  handler could not resolve it this pass")
            except Exception as e:
                play_loop.log(f"  handler raised {e!r}")
            time.sleep(0.5)
            ts = g.turn_state(a.seat)
            continue
        play_loop.ensure_production(g, a.seat)
        play_loop.ensure_trade_routes(g, a.seat)
        play_loop.resolve_units_need_orders(g, a.seat)
        r = g.end_turn()
        if r.get("ok"):
            play_loop.log(f"seat {a.seat} ended turn {ts.get('turn')}")
            return 0
        if "diplomatic decision pending" in str(r.get("err", "")):
            play_loop.log(f"  declined a diplomatic approach ({play_loop.decline_diplomacy(g, a.seat)})")
        else:
            play_loop.log(f"  end_turn refused: {str(r.get('err'))[:160]}")
        time.sleep(0.5)
        ts = g.turn_state(a.seat)
    play_loop.log("gave up")
    return 2


if __name__ == "__main__":
    sys.exit(main())
