# Running the harness on a Steam Deck

Set up 2026-09-17 on `deck@10.10.10.171` (SteamOS, desktop mode, Steam account raidenphoenix).
Everything below runs over SSH from any machine; nothing needs the Deck's screen except the game window itself.

## What was done once (already in place)

1. **Civ V switched from Proton to the native Linux build.** The Deck had the Windows build under Proton.
   The harness's tuner-keepalive shim is an `LD_PRELOAD` on the Linux `Civ5XP` binary, so Proton cannot
   work. Steam was shut down, `~/.local/share/Steam/config/config.vdf` got a `CompatToolMapping` entry
   `"8930" { "name" "steamlinuxruntime" ... }` (backup at `~/config.vdf.bak-*`), and Steam re-downloaded
   the Linux depot (~1 GB delta). To undo: remove that entry in Steam's UI (Properties -> Compatibility).
2. **Harness copied** to `~/civ_v_llm_harness` (rsync from the desktop repo, minus `.venv`, `logs`,
   `seats.json`). Python venv at `~/civ_v_llm_harness/.venv` with `mcp` (plain `python3 -m venv` + pip; no `uv` on SteamOS).
   The prebuilt 32-bit `shim/libtuner_recv_fix.so` from the repo works as-is (no compiler on SteamOS).
3. **`EnableTuner = 1`** in `~/.local/share/Aspyr/Sid Meier's Civilization 5/config.ini`.
   The game rewrites this file on exit, so re-check it if the game was ever quit from its own menu.
4. Steam runs as a user systemd unit (`steam-harness.service`) so it survives SSH sessions ending.

Deck quirks the scripts account for: the game is in the internal library, the Steam Linux Runtime
containers are on the SD card (`/run/media/deck/<uuid>/steamapps/common/SteamLinuxRuntime*`), and the Deck
has exactly 8 logical CPUs, so the >8-core affinity workaround is disabled. `scripts/launch_deck.sh` sets all
of that (`CIV5_STEAM_LIB`, `CIV5_SLR_LIB`, `CIV5_TASKSET=""`).

## Start everything (each step from SSH)

```bash
ssh deck@10.10.10.171
cd ~/civ_v_llm_harness

# 0. Steam must be running (desktop mode). If `pgrep -x steam` is empty:
systemd-run --user --unit=steam-harness -E DISPLAY=:0 -E WAYLAND_DISPLAY=wayland-0 \
  -E XDG_RUNTIME_DIR=/run/user/1000 -E DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
  -E XAUTHORITY=/run/user/1000/xauth_TVCOVE /usr/bin/steam -silent

# 1. Launch the game with the shim (logs -> logs/civ5-deck.{out,err}, reaper pid in logs/civ5-deck.pid)
scripts/launch_deck.sh

# 2. Bridge daemon (owns the single tuner connection; unix socket at /run/user/1000/civ5-tuner.sock).
#    Run it as a user unit so it outlives the SSH session:
systemd-run --user --unit=civ5-tunerd --working-directory=$HOME/civ_v_llm_harness \
  -E XDG_RUNTIME_DIR=/run/user/1000 $HOME/civ_v_llm_harness/.venv/bin/python -m harness.tunerd

# 3. Wait for the tuner (cold boot to a responsive tuner is 45-90 s, sometimes longer), then:
.venv/bin/python -m harness.cli status        # -> screen MainMenu once it is ready
```

## Give the LLM seat the controls

The MCP server is `python -m harness.mcp_server` over stdio; `.mcp.json` in the repo root already
declares it as server `civ5` (`CIV5_TUNERD_SOCK=/run/user/1000/civ5-tuner.sock`, seat `auto`). Point
whatever MCP client the LLM runs in at that file, or copy this into its config:

```json
{"mcpServers": {"civ5": {"command": "/home/deck/civ_v_llm_harness/.venv/bin/python",
  "args": ["-m", "harness.mcp_server", "--seat", "auto"],
  "env": {"CIV5_TUNERD_SOCK": "/run/user/1000/civ5-tuner.sock"}}}}
```

Hand the LLM `docs/PLAYBOOK.md` as its instructions. It contains the join/launch flow and the
stuck-state checklist.

Joining the LAN game (Claude hosts on the desktop, 10.10.10.2): once the host's lobby is up,
either the LLM calls the MCP `join_lan` flow described in the playbook, or from SSH:

```bash
.venv/bin/python -m harness.cli join-lan 10.10.10.2      # or the host's serverID from the lobby list
```

## Stop / restart

```bash
kill "$(cat logs/civ5-deck.pid)"          # game (reaper exits when the whole tree is gone)
systemctl --user stop civ5-tunerd         # bridge
systemctl --user restart civ5-tunerd      # after a game relaunch (the shim lets the game re-accept)
```

If the game dies on its own: `journalctl -k | tail` for a segfault line, `logs/civ5-deck.err` for the
game's stderr, then relaunch with step 1 and restart tunerd. LAN seats can rejoin a game in progress with
`join-lan` again; the host does not need to restart.

## Sanity checks

- `ss -ltnp | grep 4318` shows `Civ5XP` listening on 127.0.0.1:4318 (shim bind remap, `[tuner_fix]` lines
  in `logs/civ5-deck.err`).
- `.venv/bin/python -m harness.cli status` answers within a few seconds. If it hangs, tunerd is up but
  the game has not armed the tuner yet; wait and retry. If it errors with "connection refused", tunerd
  is not running.
- `grep EnableTuner ~/.local/share/Aspyr/Sid\ Meier\'s\ Civilization\ 5/config.ini` must be `1`.
