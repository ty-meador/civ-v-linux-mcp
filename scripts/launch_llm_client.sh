#!/usr/bin/env bash
# LAN mode preset: launch a SECOND game instance for the LLM on this machine (the humans keep the
# normal instance). Own profile dir, own tuner port. Pair it with:
#   python3 -m harness.tunerd --port 4319 --sock $XDG_RUNTIME_DIR/civ5-llm.sock
#   CIV5_TUNERD_SOCK=$XDG_RUNTIME_DIR/civ5-llm.sock python3 -m harness.cli join-lan <host-ip>
# Env overrides: CIV5_DATA_HOME, CIV5_TUNER_PORT, CIV5_TUNER_BIND, NAME (log file base name)
# For more than one LLM seat (multi-LLM pitboss games), use scripts/launch_seat.sh <name> instead, which
# reads per-seat ports/profiles/nicknames from harness/seats.json. This script stays as the zero-config
# single-seat preset (no seats.json required).
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export CIV5_DATA_HOME="${CIV5_DATA_HOME:-$HOME/.local/share/civ5-llm}"
export CIV5_TUNER_PORT="${CIV5_TUNER_PORT:-4319}"
export CIV5_TUNER_BIND="${CIV5_TUNER_BIND:-127.0.0.1}"
exec "$HERE/scripts/launch_civ5.sh" "${NAME:-civ5-llm}"
