#!/usr/bin/env bash
# Launch Civ5XP the way Steam does (Steam Linux Runtime "soldier" container via pressure-vessel,
# Steam compat environment), but from a script so we can add our LD_PRELOAD shim and pick logs.
# A plain ./Civ5XP outside the container reaches the menu but crashes when hosting multiplayer.
#
# Usage: launch_civ5.sh [instance_name]     logs -> logs/<instance_name>.{out,err}
# Env:   HARNESS_SHIM=0 to skip shim/libtuner_recv_fix.so
set -u
APPID=8930
LIB="/mnt/8c26d645-51a3-43ea-82f6-96987298c294/steam_library"
GAME_DIR="$LIB/steamapps/common/Sid Meier's Civilization V"
STEAM="$HOME/.local/share/Steam"
SLR="$LIB/steamapps/common/SteamLinuxRuntime"
SLR_SOLDIER="$LIB/steamapps/common/SteamLinuxRuntime_soldier"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="${1:-civ5}"
mkdir -p "$HERE/logs"

# Desktop session + Steam client identity, borrowed from the running Steam client.
STEAM_PID="$(pgrep -x steam | head -1)"
[ -z "$STEAM_PID" ] && { echo "Steam client is not running" >&2; exit 1; }
for v in DISPLAY WAYLAND_DISPLAY XDG_RUNTIME_DIR XAUTHORITY DBUS_SESSION_BUS_ADDRESS XDG_SESSION_TYPE \
         SteamUser SteamAppUser Steam3Master STEAMSCRIPT STEAMSCRIPT_VERSION STEAM_RUNTIME STEAM_RUNTIME_LIBRARY_PATH; do
  val="$(tr '\0' '\n' < /proc/$STEAM_PID/environ | sed -n "s/^$v=//p")"
  [ -n "$val" ] && export "$v=$val"
done
export DISPLAY="${DISPLAY:-:1}"

export SteamAppId=$APPID SteamGameId=$APPID SteamOverlayGameId=$APPID SteamEnv=1 SteamClientLaunch=1
export STEAM_COMPAT_APP_ID=$APPID
export STEAM_COMPAT_CLIENT_INSTALL_PATH="$STEAM"
export STEAM_COMPAT_INSTALL_PATH="$GAME_DIR"
export STEAM_COMPAT_LIBRARY_PATHS="$LIB/steamapps"
export STEAM_COMPAT_DATA_PATH="$LIB/steamapps/compatdata/$APPID"
export STEAM_COMPAT_SHADER_PATH="$LIB/steamapps/shadercache/$APPID"
export STEAM_COMPAT_TOOL_PATHS="$SLR:$SLR_SOLDIER"
export STEAM_COMPAT_MOUNTS="$SLR:$SLR_SOLDIER"
export STEAM_COMPAT_FLAGS=search-cwd
export ENABLE_VK_LAYER_VALVE_steam_overlay_1=1
export LD_PRELOAD="$STEAM/ubuntu12_32/gameoverlayrenderer.so:$STEAM/ubuntu12_64/gameoverlayrenderer.so"
if [ "${HARNESS_SHIM:-1}" = "1" ] && [ -f "$HERE/shim/libtuner_recv_fix.so" ]; then
  export LD_PRELOAD="$HERE/shim/libtuner_recv_fix.so:$LD_PRELOAD"
fi

cd "$GAME_DIR" || exit 1
nohup setsid "$STEAM/ubuntu12_32/reaper" SteamLaunch AppId=$APPID -- \
  "$SLR_SOLDIER/_v2-entry-point" --verb=waitforexitandrun -- \
  "$SLR/scout-on-soldier-entry-point-v2" -- \
  "$GAME_DIR/./Civ5XP" > "$HERE/logs/$NAME.out" 2> "$HERE/logs/$NAME.err" < /dev/null &
echo "launched (reaper pid=$!) display=$DISPLAY logs=$HERE/logs/$NAME.*"
