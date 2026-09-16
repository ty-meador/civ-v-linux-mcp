# Civ V LLM harness — architecture

Goal: an MCP server that lets an LLM play Sid Meier's Civilization V (Linux/Steam) in the same game as
humans and the built-in AI, using the game's own multiplayer.

## Why not a from-scratch network client
Civ V multiplayer is lockstep-deterministic: every client runs the full simulation and the wire carries
player commands only (hence the game's "out of sync" checks). A custom client would need to reimplement
the whole rules engine to know the state of the world. So the LLM's "client" is a real game instance
that we drive programmatically.

## Layers

```
┌────────────────────────────────────────────────────────────────────────────┐
│ LLM (Claude) ── MCP tools ──▶ mcp server (harness/mcp_server.py)            │
│                                   │ Python API                               │
│                              harness/game.py  (state snapshots, actions,    │
│                                   │            turn loop, event log)         │
│                              harness/client.py  JSON over unix socket        │
│                                   │                                          │
│                              harness/tunerd.py  owns THE tuner connection    │
│                                   │ TCP 127.0.0.1:4318  (FireTuner protocol) │
│ Civ5XP  (+ shim/libtuner_recv_fix.so via LD_PRELOAD, EnableTuner=1)          │
│   └─ Lua states: FrontEnd, MainMenu, StagingRoom, InGame, PlayerChange, ...  │
└────────────────────────────────────────────────────────────────────────────┘
```

* **FireTuner** (Firaxis "Nexus" protocol) is a remote Lua REPL into every UI Lua context of the game.
  Verified wire format and quirks: see NOTES.md and harness/tuner.py.
* **shim/** fixes two things at load time (no file patching): the Linux `recv(fd,NULL,0)` disconnect
  probe, and the anti-cheat `Disable()` of the tuner when a multiplayer game launches.
* **tunerd** exists because the game serves one tuner connection per arming; a long-lived process
  keeps it and multiplexes local clients. It also buffers unsolicited print output (the game's Lua
  prints) as an event stream.
* **game.py** is the only place that knows Lua. It injects a small runtime into the InGame state
  (JSON encoder, event recorder hooked on `Events.*`, helpers) and exposes typed Python calls.
* **mcp_server.py** maps Python calls to MCP tools with LLM-friendly, compact text/JSON output.

## Game modes
1. **Hotseat (v1, single machine).** One game instance. Humans and the LLM take turns at the same
   machine; AI civs fill the rest. The LLM owns one hotseat seat. On its turn the `PlayerChange` modal
   appears (pauses the game); the harness dismisses it (`OnContinue()`), plays, and ends the turn.
   Everything is local; no networking involved.
2. **LAN (v2).** A second game instance (own HOME / user-data dir, headless-ish window) joins the
   humans' LAN game as the LLM's player via `Matchmaking.JoinIPAddress`. Same harness, different
   lobby driver. Needs: port separation, second Steam identity or LAN-without-Steam behaviour (TBD).

## Turn loop (hotseat)
```
wait until Game.GetActivePlayer() == seat and PlayerChange modal is up (or turn active)
  → dismiss modal  → snapshot state  → LLM reasons + issues actions (tools)
  → end turn (Game.DoControl(CONTROL_ENDTURN) / handle EndTurnBlocking reasons)
  → "since your last turn" digest = recorded Events + notifications since previous snapshot
```

## Security note
With `EnableTuner = 1` the game listens on **0.0.0.0:4318**: anyone on the LAN can execute Lua in the
game. Firewall the port or add a bind hook to the shim before using this on untrusted networks.

## Repo layout
```
harness/   tuner.py (protocol), tunerd.py (daemon), client.py, game.py, mcp_server.py
shim/      tuner_recv_fix.c -> libtuner_recv_fix.so (gcc -m32)
scripts/   launch_civ5.sh, tuner_probe.py (protocol sniffing aid)
docs/      NOTES.md (findings), lua_api_surface.md, lua_command_patterns.md
logs/      (gitignored) game stdout/stderr, tunerd log
```
