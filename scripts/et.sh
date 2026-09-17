#!/usr/bin/env bash
# End my turn and block until it is my turn again, then print a compact picture of the new turn.
# Usage: scripts/et.sh [--no-save]   (env: CIV5_SEAT, default 0)
# Designed to run in the background: the caller is woken when this exits, no polling needed.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/1000}"
SEAT="${CIV5_SEAT:-0}"
M=".venv/bin/python scripts/mcp_call.py --seat $SEAT"
# --wait-only: my turn already ended (e.g. an AI question interrupted the wait and was answered);
# just resume waiting. --no-save: end the turn without the quick save.
if [ "${1:-}" != "--wait-only" ]; then
  if [ "${1:-}" != "--no-save" ]; then
    echo "== quick_save"; $M quick_save '{}' 2>&1 | head -c 300; echo
  fi
  echo "== end_turn"; ET="$($M end_turn '{}' 2>&1 | head -c 1500)"; echo "$ET"
  case "$ET" in *'"ok":true'*) ;; *) echo "== end_turn refused; not waiting"; exit 2 ;; esac
fi
# The MCP parameter is timeout_seconds (an unknown key is silently ignored and the 90s default used --
# that is what an earlier draft of this script did). Loop until it is really my turn or an AI is asking.
for i in 1 2 3 4 5 6 7 8 9 10; do
  echo "== wait_for_my_turn"; W="$($M wait_for_my_turn '{"timeout_seconds": 300}' 2>&1 | head -c 6000)"; echo "$W"
  case "$W" in *'"my_turn":true'*|*'"discussion_pending":true'*|*'"alive":false'*|*Error*|*Traceback*) break ;; esac
done
case "$W" in *'"discussion_pending":true'*)
  # An AI wants an answer: show what it said and what is on the table so the decision needs no extra reads.
  echo "== discussion"; $M discussion '{}' 2>&1 | head -c 12000; echo
  echo "== incoming_deal"; $M incoming_deal '{}' 2>&1 | head -c 2000; echo
  ;;
esac
echo "== turn_digest"; $M turn_digest '{}' 2>&1 | head -c 8000; echo
echo "== overview"; $M overview '{}' 2>&1 | head -c 800; echo
