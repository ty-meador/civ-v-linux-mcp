#!/usr/bin/env python3
"""Poll the running game for anything that needs a human/LLM decision and print one line per
new/changed condition: a new discussion (trade offer, DoF, coop-war...), a World Congress
session in progress, a tech-discovered popup waiting on the next research pick, or turn/blocking
state changing. Meant to run continuously alongside manual play (e.g. under Claude Code's Monitor
tool, or plain `python3 scripts/watch_game.py | tee -a logs/watch.log`) so events that happen
between explicit turn actions -- an AI trade offer, a stuck popup -- get noticed instead of only
surfacing when a human watching the actual game window flags it.

Also opportunistically calls dismiss_pending_popups() each poll -- ONLY the known-safe, purely
informational sweep (Wonder/GoldenAge/NaturalWonder/etc, GreatWork/WhosWinning splash screens, and
TechPopup but only once research is already chosen). Never auto-decides a discussion, trade offer,
or League vote -- those always get surfaced as an event for a human/LLM to act on, per
discussion_pending()'s own docstring: blind auto-resolution of real decisions is its own bug.
"""
import sys
import time
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harness.game import Game
from harness.client import TunerdError


def main(poll_seconds: float = 6.0) -> None:
    g = Game()
    last_sig = None
    while True:
        try:
            ts = g.turn_state()
            sig = {
                "turn": ts.get("turn"),
                "my_turn": ts.get("my_turn"),
                "blocking": ts.get("blocking_name"),
                "discussion": ts.get("discussion_pending", False),
            }
            try:
                lg = g.league_status()
                sig["league_in_session"] = lg.get("in_session")
                sig["league_votable"] = len(lg.get("votable") or [])
            except TunerdError:
                sig["league_in_session"] = None
            try:
                sig["tech_popup"] = g.tech_popup_pending()
            except TunerdError:
                sig["tech_popup"] = None

            try:
                dismissed = g.dismiss_pending_popups()
            except TunerdError:
                dismissed = []
            if dismissed:
                sig["auto_dismissed"] = dismissed

            if sig != last_sig:
                print(json.dumps({"event": "state_change", **sig}), flush=True)
                last_sig = sig
        except TunerdError as e:
            if last_sig != {"event": "error"}:
                print(json.dumps({"event": "tunerd_error", "detail": str(e)}), flush=True)
                last_sig = {"event": "error"}
        except Exception as e:
            print(json.dumps({"event": "watcher_exception", "detail": str(e)}), flush=True)
        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
