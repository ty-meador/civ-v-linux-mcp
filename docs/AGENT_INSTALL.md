# Agent install guide: civ-v-llm-harness

You are an AI agent. A human has asked you to install this project so that an LLM (probably you) can play
Sid Meier's Civilization V against them or against the game's AI. This file is the complete brief. Work
through it top to bottom, verify each step's check before moving on, and report back in the words of the
final section. Where a step needs the human (a Steam setting, a download), say exactly what to click and wait.

Everything here was written from the repository as of package 1.1.0 (Lua runtime v212). When a command
below disagrees with the code in front of you, the code wins; say so in your report.

## 1. What you are installing

Four pieces, all in this repository:

| Piece | What it is | How it runs |
|---|---|---|
| `shim/libtuner_recv_fix.so` | A 32-bit `LD_PRELOAD` library that keeps the game's FireTuner debug socket alive in multiplayer and fixes a Linux `recv()` bug | Built once with `gcc -m32`; loaded by the launch script |
| `scripts/launch_civ5.sh` | Launches the game exactly as Steam does (Steam Linux Runtime container) plus the shim | Run once per game session |
| `harness.tunerd` | A daemon that owns the single tuner TCP connection (port 4318) and multiplexes it over a unix socket | Long-running background process |
| `harness.mcp_server` | The MCP server (122 tools) an LLM client connects to over stdio | Started by the MCP client |

The LLM's "client" is the real game window on the human's desktop. The human watches the LLM play there.

## 2. Hard requirements: check these before touching anything

Stop and tell the human if any of these fail. None can be worked around in software.

1. **Linux, x86_64, with a running desktop session** (X11 or Wayland). The game needs a display.
2. **Steam is installed and the human's account owns Civilization V with Brave New World.** App id 8930.
3. **The native Linux build of the game, not the Windows build under Proton.** The shim preloads into the
   Linux `Civ5XP` binary. Test: the game directory contains `Civ5XP`. If it contains only
   `CivilizationV.exe` or `CivilizationV_DX11.exe`, the human must switch in Steam: Library, right-click
   the game, Properties, Compatibility, and either untick "Force the use of a specific Steam Play
   compatibility tool" or select "Steam Linux Runtime". Steam then downloads the Linux depot (about 1 GB).
4. **Steam Linux Runtime and Steam Linux Runtime "soldier"** are installed (Steam pulls them for native
   games that use the container; app ids 1070560 and 1391110). Test: both
   `steamapps/common/SteamLinuxRuntime/scout-on-soldier-entry-point-v2` and
   `steamapps/common/SteamLinuxRuntime_soldier/_v2-entry-point` exist in some Steam library.
5. **Python 3.11 or newer** and **[uv](https://docs.astral.sh/uv/)**.
6. **A C compiler with 32-bit support**: `gcc -m32` must work. Debian/Ubuntu: `gcc-multilib`.
   Fedora: `glibc-devel.i686`. Arch: `lib32-glibc` plus the `multilib` repo. SteamOS has no compiler: build
   the shim on another machine and copy the `.so` over.
7. `taskset` (util-linux) and `ss` (iproute2), both standard.

```bash
python3 --version; uv --version; gcc --version | head -1; echo 'int main(){return 0;}' > /tmp/m32.c && gcc -m32 /tmp/m32.c -o /tmp/m32 && echo "m32 ok"
pgrep -x steam >/dev/null && echo "steam running" || echo "steam NOT running"
```

## 3. Locate the Steam library that holds the game

The launch script defaults to the original author's library path, which will not exist on this machine.
Find the right one and export it for every later step.

```bash
for lib in $(grep -oP '"path"\s+"\K[^"]+' ~/.local/share/Steam/steamapps/libraryfolders.vdf) ~/.local/share/Steam ~/.steam/steam; do
  [ -e "$lib/steamapps/common/Sid Meier's Civilization V/Civ5XP" ] && echo "GAME LIB: $lib"
  [ -e "$lib/steamapps/common/SteamLinuxRuntime_soldier/_v2-entry-point" ] && echo "SLR LIB: $lib"
done
```

- `export CIV5_STEAM_LIB="<GAME LIB>"`.
- If the runtimes live in a different library (Steam Deck: SD card), also `export CIV5_SLR_LIB="<SLR LIB>"`.
- Put both exports in the human's shell profile or a `env.sh` in the repo (not committed), because
  `launch_civ5.sh` needs them every time.

## 4. Clone and install the Python side

```bash
git clone https://gitlab.com/Tyler-Meador/civ-v-linux-mcp.git civ_v_llm_harness
cd civ_v_llm_harness
uv sync --group dev          # creates .venv with mcp, fastapi, uvicorn, pytest, lupa
scripts/check.sh             # the regression suite; needs no game. Expect "528 passed" or more.
```

If the suite fails on import of `lupa`, the wheel did not build; `uv sync --group dev` again after
installing your distro's Python headers.

## 5. Build the shim

The compiled library is deliberately not in git (`*.so` is ignored), so every fresh clone builds it.

```bash
cd shim && gcc -m32 -O2 -shared -fPIC -o libtuner_recv_fix.so tuner_recv_fix.c -ldl && cd ..
file shim/libtuner_recv_fix.so    # must say "ELF 32-bit LSB shared object"
```

## 6. Enable the tuner in the game's config

The game reads `~/.local/share/Aspyr/Sid Meier's Civilization 5/config.ini`, section `[Debugging]`.

```bash
CFG="$HOME/.local/share/Aspyr/Sid Meier's Civilization 5/config.ini"
ls "$CFG"                                          # missing? the game has never run: see below
sed -i 's/^EnableTuner = .*/EnableTuner = 1/' "$CFG"
grep -n '^EnableTuner' "$CFG"                      # must print EnableTuner = 1
```

- If the file does not exist, the human must launch the game once from Steam and quit it from the main
  menu; the file is created on first run.
- The game rewrites this file when it exits through its own menu. If the tuner ever stops listening after a
  quit, re-run the `grep` above.

With the tuner on, the game listens on **TCP 0.0.0.0:4318**, that is, every interface, and anyone who can
reach it can run Lua inside the game. Bind it to loopback unless a LAN game needs otherwise:
`export CIV5_TUNER_BIND=127.0.0.1` (the shim remaps the bind). Do this by default.

## 7. Launch the game

Steam must already be running as the desktop user (`pgrep -x steam`). If it is not, the human starts it
normally, or from a shell with the desktop's variables:
`env DISPLAY=:1 WAYLAND_DISPLAY=wayland-1 XDG_RUNTIME_DIR=/run/user/$UID steam -silent &` (adjust `:1` and
`wayland-1` to the session's real values from `echo $DISPLAY $WAYLAND_DISPLAY`).

```bash
export CIV5_STEAM_LIB=...  CIV5_TUNER_BIND=127.0.0.1          # from steps 3 and 6
scripts/launch_civ5.sh                                          # prints "launched (reaper pid=N) ..."
tail -f logs/civ5.err                                           # optional; Ctrl-C to stop watching
```

Then wait for the tuner port. Do **not** connect anything to it yourself (no `nc`, no probe script): the
game accepts exactly one tuner client, and it must be `tunerd`.

```bash
until ss -ltn | grep -q ':4318 '; do sleep 5; done; echo "tuner is listening"
```

A cold start takes 45 to 120 seconds to reach the main menu. Notes:

- The script pins the game to CPUs 0-7 (`CIV5_TASKSET`, default `0-7`) because the Linux port crashes on
  machines with more than eight logical CPUs. Leave that alone.
- Never start anything on port 4318 before the game does; the game aborts at init if the port is taken.
- `logs/civ5.pid` holds the reaper pid. `kill $(cat logs/civ5.pid)` stops the instance.

## 8. Start the tuner bridge

`tunerd` must outlive your shell. Prefer a user systemd unit; fall back to `nohup`.

```bash
SOCK="${XDG_RUNTIME_DIR:-/run/user/$UID}/civ5-tuner.sock"
systemd-run --user --unit=civ5-tunerd --working-directory="$PWD" \
  -E XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$UID}" "$PWD/.venv/bin/python" -m harness.tunerd --port 4318 --sock "$SOCK"
# or: nohup .venv/bin/python -m harness.tunerd --port 4318 --sock "$SOCK" > logs/tunerd.log 2>&1 &

sleep 5; journalctl --user -u civ5-tunerd -n 5 --no-pager      # or: tail -5 logs/tunerd.log
CIV5_TUNERD_SOCK="$SOCK" .venv/bin/python -m harness.cli status
```

Expected: the log says `listening on <sock>; game tuner at 127.0.0.1:4318` and later `48 lua states` (the
number varies a little; what matters is that it is not 0). `cli status` prints JSON with `"screen": "MainMenu"`.

- `0 lua states` means tunerd connected before the front end existed; it retries on the next request.
  Wait and call `status` again.
- Restarting tunerd is always safe. Restarting the MCP server never fixes a tunerd problem.

## 9. Configure the MCP client

The server is `python -m harness.mcp_server` over stdio. It needs one environment variable,
`CIV5_TUNERD_SOCK`, pointing at the socket from step 8. `--seat auto` picks the local player; in a
hotseat game with the LLM in seat 1, use `--seat 1`.

**Claude Code.** The repo root has `.mcp.json` declaring server `civ5`. Its socket path assumes uid 1000;
if `id -u` is not 1000, edit it to the real `$XDG_RUNTIME_DIR`. Then run `claude` from the repo root and
the `civ5` tools appear.

**Codex CLI** does not read `.mcp.json`; register the server once (it lands in `~/.codex/config.toml`),
with the seat this agent plays:

```bash
codex mcp add civ5 --env CIV5_TUNERD_SOCK=/run/user/1000/civ5-tuner.sock \
  --env PYTHONPATH=/ABS/PATH/civ_v_llm_harness -- /ABS/PATH/civ_v_llm_harness/.venv/bin/python -m harness.mcp_server --seat 0
```

then start a new Codex session. **Grok CLI** reads `.mcp.json` as is (`--seat auto`, which is seat 1 in a
hotseat game). Two agents in one hotseat game each run their own server, one per seat; they share one lock
per tuner socket, held per operation, so both may wait at once. Give each an explicit `--seat`: a pinned
server refuses `set_seat` onto the other human seat, which is the only way one agent could read the
other's map through the harness (`--seat auto` may still move, for a save loaded on the wrong seat).

**Any other MCP client** (Claude Desktop, Cursor, a custom host): the same shape, with absolute paths.

```json
{
  "mcpServers": {
    "civ5": {
      "command": "/ABS/PATH/civ_v_llm_harness/.venv/bin/python",
      "args": ["-m", "harness.mcp_server", "--seat", "auto"],
      "env": { "CIV5_TUNERD_SOCK": "/run/user/1000/civ5-tuner.sock" }
    }
  }
}
```

Do not add `--allow-lua` or `CIV5_ALLOW_LUA=1` unless the human asks for it. The raw `lua` tool can crash
the game process outright and is off by default for that reason.

Verify with one real MCP call through a fresh stdio server, no client needed:

```bash
CIV5_TUNERD_SOCK="$SOCK" .venv/bin/python scripts/mcp_call.py --list | tr ',' '\n' | wc -l      # 122
CIV5_TUNERD_SOCK="$SOCK" .venv/bin/python scripts/mcp_call.py --seat 0 turn_status '{}'
```

At the main menu `turn_status` answers `{"ok": true, "ingame": false, "screen": "MainMenu"}`. That is the
install working end to end.

## 10. Get into a game

Three ways. Ask the human which one they want if they have not said.

**Solo against the AI** (the LLM is seat 0):
```bash
CIV5_TUNERD_SOCK="$SOCK" .venv/bin/python -m harness.cli start-single --civ CIVILIZATION_ROME --handicap HANDICAP_PRINCE
```
Omit `--civ` for a random leader. Map, size, pace and victory types are whatever the game's "Play Now"
settings hold. The command returns once the map is live.

**Hotseat with the human on the same machine** (human seat 0, LLM seat 1):
```bash
CIV5_TUNERD_SOCK="$SOCK" .venv/bin/python -m harness.cli host-hotseat --humans 0 1 --nick 1=Claude
```
Start the MCP server with `--seat 1`. The human plays their turn in the game window; the LLM's
`wait_for_my_turn` blocks until the hand-off. After loading a hotseat save the game sits paused on the
hand-off screen until the active seat's server presses Continue, which any of its calls does (the answer
carries `hand_off_cleared: true`). A server started with `--seat auto`
plays seat 1 in hotseat; `turn_status.seat` says which seat a server is on, and `set_seat(player_id)`
moves it to another human seat without a restart (a restart is what loses the MCP tools in a Claude Code
session).

**LAN, the LLM as its own network player**: `scripts/launch_llm_client.sh` starts a second game instance
(own profile, tuner on 4319), a second `tunerd` on `civ5-llm.sock`, then
`harness.cli lan-games` / `join-lan <host-ip> --nick Claude` / `wait-ingame`. Details in the README
section "Ways to play" and `docs/ARCHITECTURE.md`.

**Resume**: `scripts/mcp_call.py --seat 0 load_latest '{}'` loads the newest save; `load_save
'{"filename": "Name"}'` a named one. Both work only from the main menu; `exit_to_main_menu` gets there from
a loaded game. `end_turn` quick-saves by default into the game's one quick-save slot
(`Saves/single/quick/QuickSave.Civ5Save`), so copy anything worth keeping to a named file.

## 11. Hand over the controls

Whoever plays the seat needs the turn loop and the blocker table. Both are in `docs/PLAYBOOK.md`
(the loop is the same in every mode). The short version, per turn:

```
finish_turn (returns status + digest + notes) -> overview / units / cities / known_world
-> act (check available_* before each action) -> turn_status until blocking_name is clear
-> remember(what future-you needs) -> finish_turn (once; it quick-saves first)
```

`finish_turn` sends MCP progress notifications every 5 s while it waits. Its default `timeout_seconds` is
600; on `timed_out: true` call it again and it only waits, it never ends a second turn. Verified in Claude
Code on 2026-09-25: a `wait_for_my_turn(timeout_seconds=420)` came back with the server's own timeout, not
a client cutoff. Claude Code moves any MCP call that runs past 120 s to a background task and delivers the
result as a notification, so the model keeps working meanwhile. With another client, try one long call
first and stay under its per-call limit if it has one.

The MCP server also sends these rules as its `instructions` string, so a client that honours server
instructions already has them.

What the pieces do is a separate document: `reference(section)` (also the MCP resource `civ5://reference`
and `GET /reference` over HTTP) is the rule book, read once from the running game's database, so mods and
DLC are in it. Hand it to the model at the start of a game, whole or section by section; no tool answer
repeats that text, and a model that has not read it is choosing promotions and beliefs by name alone. The
whole book is also written to `$XDG_DATA_HOME/civ5-harness/reference/<game>.md` the first time it is read.

## 12. Troubleshooting

| Symptom | Meaning | Fix |
|---|---|---|
| Every tool answers `No such file or directory` | tunerd is not running or the socket path is wrong | Restart tunerd (step 8); check `CIV5_TUNERD_SOCK` |
| `tunerd lost its connection` / `connection refused` | The game exited or crashed | `pgrep -x Civ5XP`; relaunch (step 7); `load_latest` |
| `0 lua states` forever | tunerd connected too early | Wait, call `cli status` again; if still 0 after 2 min, restart tunerd |
| Game aborts at init with "uncaught exception ... of type int" | Port 4318 was taken | Kill whatever holds it; never bind it before the game |
| `missing: .../Civ5XP (set CIV5_STEAM_LIB / CIV5_SLR_LIB)` | Wrong library path | Step 3 |
| `Steam client is not running` | The script borrows Steam's session env | Start Steam first |
| `turn_status` says `ingame: false` | No game loaded | Step 10 |
| First MCP call after a runtime change hangs about 70 s | The Lua runtime is being re-injected | Use a 120 s timeout on that call; nothing is wrong |
| Repeated segfaults every 6-30 min | More than 8 logical CPUs without the pin | Keep `CIV5_TASKSET=0-7` |

Logs: `logs/civ5.out`, `logs/civ5.err` (game), the tunerd unit journal or `logs/tunerd.log`.
The game's own logs are under `~/.local/share/Aspyr/Sid Meier's Civilization 5/Logs/` if
`LoggingEnabled = 1` in `config.ini`.

## 13. Stopping and restarting

```bash
kill $(cat logs/civ5.pid)                     # the game (reaper pid; the whole tree follows)
systemctl --user stop civ5-tunerd             # or kill the nohup'd tunerd
```
Order on restart: game, wait for port 4318, tunerd, then the MCP client. `harness.supervisor` can relaunch
the game and reload the last save after a crash:
`python -m harness.supervisor --sock "$SOCK" --name civ5 --pid-file logs/civ5.pid --launch-cmd scripts/launch_civ5.sh`.

## 14. Report back to the human

Tell them, in this order:

1. Which of the checks in section 2 passed, and anything you had to ask them to change in Steam.
2. Where the game is running (their desktop window) and that they should leave that window alone during
   the LLM's turn; in hotseat they play their own turn in it.
3. Which MCP client you configured and the exact `turn_status` reply you got in step 9.
4. Which game mode you started (section 10) and the seat number.
5. Two cautions: the tuner port is bound to loopback (or is not, if they asked for LAN), and the game
   crashes now and then, so `end_turn` quick-saves and `load_latest` brings it back.
