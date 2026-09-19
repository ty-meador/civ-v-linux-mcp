#!/usr/bin/env python3
"""Inject harness/lua/audit.lua and drain its raw event log to logs/event_audit.jsonl until killed.

Debug tool for the event audit: a human plays and notes what they see; the JSONL is reconciled against
those notes offline. The log is unfiltered (not human-visible-safe) -- keep it out of MCP reads.

    .venv/bin/python scripts/event_audit.py [--sock PATH] [--interval 2]
"""
import argparse
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.client import TunerdError  # noqa: E402
from harness.game import Game  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sock", default=os.environ.get("CIV5_TUNERD_SOCK", "/run/user/1000/civ5-tuner.sock"))
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--out", default=str(ROOT / "logs" / "event_audit.jsonl"))
    a = ap.parse_args()
    g = Game(a.sock)
    g.load_lua("InGame", (ROOT / "harness" / "lua" / "audit.lua").read_text(), "harness_audit")
    print("missing:", json.dumps(g.c.query("InGame", "return HA.missing")), flush=True)
    with open(a.out, "a") as f:
        while True:
            try:
                # a game relaunch loses HA; re-inject rather than die
                if g.c.exec("InGame", "print(type(HA) == 'table')") != ["true"]:
                    g.load_lua("InGame", (ROOT / "harness" / "lua" / "audit.lua").read_text(), "harness_audit")
                for e in g.c.query("InGame", "return HA.take()") or []:
                    e["wall"] = time.time()
                    f.write(json.dumps(e) + "\n")
                f.flush()
            except TunerdError as e:
                print(f"drain failed: {e}", flush=True)
            time.sleep(a.interval)


if __name__ == "__main__":
    raise SystemExit(main())
