# Civ V LLM harness -- architecture

Goal: an MCP server that lets an LLM play Sid Meier's Civilization V (Linux/Steam, Brave New World) in the
same game as humans and the built-in AI, using the game's own multiplayer, with exactly the information a
human in that seat has.

## Why not a from-scratch network client
Civ V multiplayer is lockstep-deterministic: every client runs the full simulation and the wire carries
player commands only (hence the game's "out of sync" checks). A custom client would need to reimplement the
whole rules engine to know the state of the world. So the LLM's "client" is a real game instance that we
drive programmatically, through the FireTuner Lua socket the game already exposes.

## Layers

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ LLM ── MCP tools (121) ──▶ harness/mcp_server.py   docstrings = the LLM's manual│
│                                 │ Python API                                    │
│                            harness/game.py   turn loop, screens, deals, digest  │
│                                 │ Game.q(lua) -> JSON   (chunked over 2048 B)   │
│                            harness/lua/runtime.lua  H.* reads/writes, hooks,    │
│                                 │        event log, roster; RUNTIME_VERSION      │
│                            harness/client.py  JSON over a unix socket           │
│                                 │                                               │
│                            harness/tunerd.py  owns THE tuner connection         │
│                                 │ TCP 127.0.0.1:4318  (FireTuner protocol)      │
│ Civ5XP  (+ shim/libtuner_recv_fix.so via LD_PRELOAD, EnableTuner=1)             │
│   └─ Lua states: FrontEnd, MainMenu, InGame, LeaderHeadRoot, DiploTrade, ...    │
└──────────────────────────────────────────────────────────────────────────────┘
```

* **FireTuner** (Firaxis "Nexus" protocol) is a remote Lua REPL into every UI Lua context of the game.
  Wire format and quirks: `docs/NOTES.md`, `harness/tuner.py`. An inbound command is truncated at 2048
  bytes, so `Game.q` measures the escaped, wrapped body and chunks it through string pieces.
* **shim/** fixes three things at load time (no file patching): the Linux `recv(fd,NULL,0)` disconnect
  probe, the anti-cheat `Disable()` of the tuner when a multiplayer game launches, and an optional `bind()`
  port remap for a second instance.
* **tunerd** exists because the game serves one tuner connection per arming; a long-lived process keeps
  it and multiplexes local clients over a unix socket (`CIV5_TUNERD_SOCK`). A connection made before the
  front end has created its Lua states reports `0 lua states` and is treated as provisional.
* **runtime.lua** is injected into the InGame state once per `RUNTIME_VERSION` (the counter goes up with
  every change; an older server re-injects its older copy, so verify new runtimes through a fresh server).
  It holds every read and write as an `H.*` function, the JSON encoder, the `Events.*` hooks that feed the
  event log, the per-seat unit roster and hp snapshots, and the fog caches (last-seen features). Ports of
  the stock UI's own Lua (combat panel modifier rows, trade pocket legality, city-screen hovers, league
  tooltips) live here so a read says what the screen says.
* **game.py** owns the turn loop, the screen drivers and the digest. Anything the stock game only offers
  through a screen is driven through that screen: the leader scene and the DiploTrade / SimpleDiploTrade
  tables for every deal, peace, demand and pledge; the popups for captures, promotions, great people. It
  verifies what it did (the right leader on screen, every item on the table at the asked amount) because
  the engine clamps or drops silently. It also refuses orders the stock UI never offers (a puppet's
  production, a plot buy in a puppet, a move onto a friendly civ's city) since the gamecore would accept
  them.
* **mcp_server.py** maps Python calls to MCP tools; the docstrings are the manual the model reads, so each
  says what the tool shows, what the refusal means and which tool to call next. `@guarded` serializes
  actions (`action_lock.py`) and turns tunerd loss into a clear error.
* **http_server.py** exposes the same calls over HTTP/JSON for non-MCP agents, one API key per seat.
* **supervisor.py** relaunches the game and reloads the last save after a crash (single and LAN modes).

## The information boundary
The seat sees what a human in that seat sees, and no more. Reads query only what the stock screen queries:
fogged plots report last-seen terrain, features, improvements and owner, never live occupants; unmet civs
stay masked in demographics, deal rows and league lists; a rival's tech list is never read behind an
embassy (only techs ahead of us, as the stock screen shows); deal rows carry coordinates only for revealed
cities; no AI-private state (approach, deal valuation, planned moves) is ever read. Writes are refused when
the stock UI would not offer the button, with the button's own tooltip as the reason. `docs/LIMITATIONS.md`
lists what stays out by engine rule; `tests/test_information_parity.py`, `test_puppet_guards.py` and
`test_mcp_safety.py` are the lints that keep new reads and writes inside the boundary.

## Game modes
1. **Hotseat (single machine).** One game instance; humans and LLM seats take turns at the same machine.
   On a seat's turn the `PlayerChange` hand-off appears and pauses the game; the harness dismisses it for
   its own seats (`wait_for_my_turn`), plays, and ends the turn. Two harness-driven human seats (Alpha and
   Bravo) are the test bench for everything war- or deal-shaped: `scripts/mcp_session.py`,
   `scripts/finish_turn.py`, `scripts/play_loop.py`. Bookkeeping is per seat: rosters, hp snapshots, event
   audiences, so a loss during the barbarian phase is filed for the seat that owned the unit.
2. **LAN.** The LLM's own game instance joins the humans' LAN game (`Game.join_lan`; `Game.host_lan` for
   the reverse) with its own profile (`XDG_DATA_HOME`) and tuner port (shim `bind()` remap). The local
   player is the active player, so the seat is auto-detected (`Game.detect_seat()`).
3. **Multi-LLM HTTP ("pitboss").** One instance and one `tunerd` per LLM seat in one shared game, all
   served by `http_server.py`; `X-API-Key` maps to exactly one seat's `Game()`.

## Turn loop and digest
```
wait_for_my_turn: hotseat -> GetActivePlayer() == seat and the hand-off is dismissed
                  LAN     -> Players[seat]:IsTurnActive() and not Network.HasSentNetTurnComplete()
                  returns early when an AI opens a leader screen mid-turn (discussion_pending)
turn_digest:      events recorded by the Lua hooks since this seat's last read, folded in game.py:
                  combat rows carry both sides' hp; a captured civilian is one unit_captured row with the
                  captor on the tile when in sight; a unit gone during our own turn with no combat is
                  unit_spent; leader chatter the harness itself provoked is hidden
turn_status:      todo (units, cities, promotions, research, pending chooser) + blocking_name and the tool
                  that clears it, read from the engine's EndTurnBlockingType
end_turn:         Game.DoControl(CONTROL_ENDTURN) after sweeping announcement popups; quick-saves first
```

## Tests
`uv run --frozen python -m pytest -q tests` (482, no game). The shipped `runtime.lua` runs under lupa or
liblua5.4 against fake `Players`/`Map`/`UI` objects, so the tests exercise the real Lua, not a paraphrase;
the Python layer runs against a fake tunerd client that executes the generated Lua in the same runtime.
Live verification is recorded per turn in `docs/GAPS.md` against the saves in `saves/`.

## Security note
With `EnableTuner = 1` the game listens on **0.0.0.0:4318**: anyone on the LAN can execute Lua in the game.
Set `CIV5_TUNER_BIND=127.0.0.1` (shim bind hook; the LLM-client preset does this) or firewall the port
before using this on untrusted networks. The HTTP server's raw `lua` route is off per seat by default.

## Repo layout
```
harness/     tuner.py (protocol), tunerd.py (daemon), client.py, game.py, cli.py (lobby/staging/lua CLI),
             mcp_server.py (MCP tools), http_server.py (multi-LLM HTTP API), supervisor.py (crash/restart),
             action_lock.py, lua/runtime.lua (the injected runtime), lua/audit.lua, lua/generic_popup_shim.lua
shim/        tuner_recv_fix.c -> libtuner_recv_fix.so (gcc -m32)
scripts/     launch_civ5.sh, launch_llm_client.sh, launch_seat.sh, mcp_call.py (one tool call, fresh server),
             mcp_session.py (drive a seat), finish_turn.py, play_loop.py, play_turn.sh, watch_game.py
saves/       the reproduction states S1-S3 (README lists what each shows)
tests/       53 files; lupa-backed Lua tests and Python-layer tests
docs/        LIMITATIONS.md (declared), ROADMAP.md (GitLab plan), GAPS.md (live audit log), NOTES.md
             (protocol and engine findings), SESSION_HANDOFF.md, lua_api_*.md
CHANGELOG.md package versions <-> RUNTIME_VERSION; scripts/check.sh runs the suite before a push (no hosted CI)
```
