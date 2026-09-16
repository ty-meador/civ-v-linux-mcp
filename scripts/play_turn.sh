#!/usr/bin/env bash
# Play ONE turn of the LLM's seat with Claude Code in headless mode, showing its reasoning.
# Usage: scripts/play_turn.sh [extra instructions]
# Loop it:  while scripts/play_turn.sh; do :; done
# Env: CIV5_SEAT (default auto: network games use this instance's local player, hotseat uses seat 1)
#      CIV5_TUNERD_SOCK (LAN mode: the LLM instance's tunerd, e.g. $XDG_RUNTIME_DIR/civ5-llm.sock)
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/1000}"
export CIV5_SEAT="${CIV5_SEAT:-auto}"
export CIV5_TUNERD_SOCK="${CIV5_TUNERD_SOCK:-$XDG_RUNTIME_DIR/civ5-tuner.sock}"

# Block here (outside the model) until it is our seat's turn. Prints "<seat> <mode>" on stdout.
READY="$(python3 - <<'PY'
import os, sys
sys.path.insert(0, ".")
from harness.game import Game
g = Game()
seat = os.environ["CIV5_SEAT"]
if seat == "auto":
    g.seat = 1
    if g.mode() != "hotseat":
        g.detect_seat()
else:
    g.seat = int(seat)
while True:
    try:
        ts = g.wait_for_my_turn(timeout=3600, poll=2.0)
        print(f"[play_turn] turn {ts['turn']} ({ts['mode']}): seat {g.seat} is active", file=sys.stderr, flush=True)
        break
    except TimeoutError:
        continue
print(g.seat, ts["mode"])
PY
)" || exit 1
SEAT="${READY% *}"; MODE="${READY#* }"
export CIV5_SEAT="$SEAT"
MODE_HINT="hotseat game"
[ "$MODE" = "lan" ] && MODE_HINT="LAN game (the other humans play at the same time; after end_turn the game waits for them)"

PROMPT="You are playing Civilization V as seat $SEAT in a live $MODE_HINT against humans and AI. It is your turn now.
1. Call turn_digest, overview, units, cities (and map_window around your units/cities as needed) to see what happened since your last turn and where you stand.
2. Think out loud briefly: what matters this turn, then decide.
3. Act with move_unit / unit_mission / set_production / set_research. Every unit with moves should get an order (explore with scouts/warriors, fortify when useful).
4. Finish by calling end_turn exactly once, then stop. Do not call wait_for_my_turn. ${1:-}"

claude -p "$PROMPT" \
  --mcp-config .mcp.json --strict-mcp-config \
  --allowedTools "mcp__civ5__*" \
  --permission-mode bypassPermissions \
  --max-turns 40 \
  --output-format text
