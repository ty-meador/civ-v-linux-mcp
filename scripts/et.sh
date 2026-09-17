#!/usr/bin/env bash
# End my turn and block until it is my turn again, then print a compact picture of the new turn.
# Usage: scripts/et.sh [--no-save]   (env: CIV5_SEAT, default 0)
# Designed to run in the background: the caller is woken when this exits, no polling needed.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/1000}"
SEAT="${CIV5_SEAT:-0}"
M=".venv/bin/python scripts/mcp_call.py --seat $SEAT"
if [ "${1:-}" != "--no-save" ]; then
  echo "== quick_save"; $M quick_save '{}' 2>&1 | head -c 300; echo
fi
echo "== end_turn"; $M end_turn '{}' 2>&1 | head -c 400; echo
echo "== wait_for_my_turn"; $M wait_for_my_turn '{"timeout": 900}' 2>&1 | head -c 1500; echo
echo "== turn_digest"; $M turn_digest '{}' 2>&1 | head -c 4000; echo
echo "== overview"; $M overview '{}' 2>&1 | head -c 800; echo
