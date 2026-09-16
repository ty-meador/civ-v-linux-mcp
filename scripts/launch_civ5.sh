#!/usr/bin/env bash
# Launch Civ5XP directly (outside Steam's launcher) on the user's desktop.
# Usage: launch_civ5.sh [instance_name]   -> logs to logs/<instance_name>.{out,err}
set -u
GAME_DIR="/mnt/8c26d645-51a3-43ea-82f6-96987298c294/steam_library/steamapps/common/Sid Meier's Civilization V"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="${1:-civ5}"
mkdir -p "$HERE/logs"

# Borrow the desktop session environment from the running Steam client.
STEAM_PID="$(pgrep -f 'steam.sh' | head -1)"
if [ -n "$STEAM_PID" ]; then
  for v in DISPLAY WAYLAND_DISPLAY XDG_RUNTIME_DIR XAUTHORITY DBUS_SESSION_BUS_ADDRESS XDG_SESSION_TYPE; do
    val="$(tr '\0' '\n' < /proc/$STEAM_PID/environ | sed -n "s/^$v=//p")"
    [ -n "$val" ] && export "$v=$val"
  done
fi
export DISPLAY="${DISPLAY:-:1}"
export SteamAppId=8930 SteamGameId=8930
export SDL_VIDEODRIVER=x11

# LD_PRELOAD shim: lets the FireTuner listener notice client disconnects (see shim/).
if [ "${HARNESS_SHIM:-1}" = "1" ] && [ -f "$HERE/shim/libtuner_recv_fix.so" ]; then
  export LD_PRELOAD="$HERE/shim/libtuner_recv_fix.so${LD_PRELOAD:+:$LD_PRELOAD}"
fi

cd "$GAME_DIR" || exit 1
nohup setsid ./Civ5XP > "$HERE/logs/$NAME.out" 2> "$HERE/logs/$NAME.err" < /dev/null &
echo "launched Civ5XP pid=$! display=$DISPLAY logs=$HERE/logs/$NAME.*"
