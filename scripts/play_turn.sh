#!/usr/bin/env bash
# Play ONE turn of the LLM's seat with Claude Code in headless mode, showing its reasoning.
# Usage: scripts/play_turn.sh [extra instructions]
# Loop it:  while scripts/play_turn.sh; do :; done
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/1000}"
SEAT="${CIV5_SEAT:-1}"

# Block here (outside the model) until it is our seat's turn.
python3 - "$SEAT" <<'PY' || exit 1
import sys, time
sys.path.insert(0, ".")
from harness.game import Game
g = Game(); g.seat = int(sys.argv[1])
while True:
    try:
        ts = g.wait_for_my_turn(timeout=3600, poll=2.0)
        print(f"[play_turn] turn {ts['turn']}: seat {g.seat} is active", flush=True)
        break
    except TimeoutError:
        continue
PY

PROMPT="You are playing Civilization V as seat $SEAT in a live hotseat game against humans and AI. It is your turn now.
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
