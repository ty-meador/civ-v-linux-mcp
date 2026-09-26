#!/usr/bin/env bash
# End my turn and block until it is my turn again, then print the new turn: one finish_turn call.
# Usage: scripts/et.sh [--no-save] [--quiet N]   (env: CIV5_SEAT, default 0)
#   --wait-only  the turn already ended (an AI's question interrupted the wait and was answered): finish_turn
#                notices it is not my turn and only waits, so this flag is accepted and ignored.
#   --quiet N    let up to N uneventful turns pass (finish_turn's skip_quiet_turns).
# Designed to run in the background: the caller is woken when this exits, no polling needed.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/1000}"
SEAT="${CIV5_SEAT:-0}"
M=".venv/bin/python scripts/mcp_call.py --seat $SEAT"
SAVE=true; QUIET=0
while [ $# -gt 0 ]; do
  case "$1" in
    --no-save) SAVE=false ;;
    --wait-only) ;;
    --quiet) shift; QUIET="${1:-0}" ;;
  esac
  shift
done
# The MCP parameter names are timeout_seconds / skip_quiet_turns (an unknown key is rejected by the server).
# 1500 s of waiting is fine here: mcp_call.py has no tool-call timeout of its own.
echo "== finish_turn"
$M finish_turn "{\"autosave\": $SAVE, \"timeout_seconds\": 1500, \"skip_quiet_turns\": $QUIET}" 2>&1 | head -c 12000; echo
