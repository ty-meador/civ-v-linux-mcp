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
  (JSON encoder, event recorder hooked on `Events.*`, helpers) and exposes typed Python calls. Diplomatic
  actions (`declare_war`, `make_peace`, `denounce`, the `diplo_event` escape hatch) call
  `Game.DoFromUIDiploEvent` directly -- the same engine call the leader-head UI buttons make -- so no
  popup ever needs to be detected or clicked through.
* **mcp_server.py** maps Python calls to MCP tools with LLM-friendly, compact text/JSON output.

## Game modes
1. **Hotseat (v1, single machine).** One game instance. Humans and the LLM take turns at the same
   machine; AI civs fill the rest. The LLM owns one hotseat seat. On its turn the `PlayerChange` modal
   appears (pauses the game); the harness dismisses it (`OnContinue()`), plays, and ends the turn.
   Everything is local; no networking involved.
2. **LAN (v2, working).** A game instance that is *the LLM's own client* joins the humans' LAN game
   (`Game.join_lan(ip | serverID)`; `Game.host_lan()` for the reverse). The humans play on another
   machine, or on this machine in the normal instance while the LLM gets a second instance:
   `scripts/launch_llm_client.sh` gives it its own profile (`XDG_DATA_HOME`) and its own tuner port
   (shim `bind()` remap, `CIV5_TUNER_PORT`), and one `tunerd` per instance multiplexes each tuner
   (`CIV5_TUNERD_SOCK` selects the instance for `Game`, the CLI and the MCP server). Game traffic needs
   no remap: discovery is UDP broadcast and the join worked with both instances on one host. The same
   Steam account can run both instances. In a network game the local player *is* the active player, so
   the seat is auto-detected (`Game.detect_seat()`); there is no hand-off modal.

## Turn loop
```
hotseat: wait until Game.GetActivePlayer() == seat and PlayerChange modal is up → dismiss modal
LAN:     wait until Players[seat]:IsTurnActive() and not Network.HasSentNetTurnComplete()
  → snapshot state  → LLM reasons + issues actions (tools)
  → end turn (Game.DoControl(CONTROL_ENDTURN); LAN: refuse a second call, it would un-ready us)
  → "since your last turn" digest = recorded Events + notifications since previous snapshot
```
`H.turn_state()` reports `mode` (hotseat|lan|internet|single), `turn_complete_sent`, the MP turn options
(simultaneous / dynamic / timer) and `everyone_connected`; `H.net_players()` lists the humans.

## Security note
With `EnableTuner = 1` the game listens on **0.0.0.0:4318**: anyone on the LAN can execute Lua in the
game. Set `CIV5_TUNER_BIND=127.0.0.1` (shim bind hook; the LLM-client preset does this) or firewall the
port before using this on untrusted networks.

## Repo layout
```
harness/   tuner.py (protocol), tunerd.py (daemon), client.py, game.py, cli.py (lobby/staging CLI), mcp_server.py
shim/      tuner_recv_fix.c -> libtuner_recv_fix.so (gcc -m32): recv fix, MP tuner-disable NOP, bind() port remap
scripts/   launch_civ5.sh, launch_llm_client.sh (2nd instance preset), play_turn.sh, tuner_probe.py
docs/      NOTES.md (findings), lua_api_surface.md, lua_command_patterns.md
logs/      (gitignored) game stdout/stderr, tunerd log
```
