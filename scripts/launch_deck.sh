#!/usr/bin/env bash
# Steam Deck preset for scripts/launch_civ5.sh.
#
# On the Deck the game lives in the internal Steam library while the Steam Linux Runtime containers
# (SteamLinuxRuntime + SteamLinuxRuntime_soldier) were installed to the SD-card library, so the two
# library roots differ. The Deck has exactly 8 logical CPUs, so the >8-core affinity workaround is a no-op
# either way; it is disabled here to keep the process tree simple.
#
# Usage: scripts/launch_deck.sh [instance_name]     (defaults: instance "civ5-deck", tuner on 127.0.0.1:4318)
# Requires: Steam running on the Deck (desktop mode), and Civ V installed as the NATIVE LINUX build
# (Properties -> Compatibility -> "Steam Linux Runtime 1.0 (scout)"), not Proton -- the tuner-keepalive
# shim is an LD_PRELOAD on the Linux Civ5XP binary and cannot patch the Windows build.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export CIV5_STEAM_LIB="${CIV5_STEAM_LIB:-$HOME/.local/share/Steam}"
if [ -z "${CIV5_SLR_LIB:-}" ]; then
  for lib in "$CIV5_STEAM_LIB" /run/media/deck/*/; do
    lib="${lib%/}"
    [ -e "$lib/steamapps/common/SteamLinuxRuntime/scout-on-soldier-entry-point-v2" ] && { export CIV5_SLR_LIB="$lib"; break; }
  done
fi
export CIV5_TASKSET="${CIV5_TASKSET-}"
export CIV5_TUNER_BIND="${CIV5_TUNER_BIND:-127.0.0.1}"
exec "$HERE/scripts/launch_civ5.sh" "${1:-civ5-deck}"
