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
│                            harness/game.py+game_parts/  turn loop, deals, digest│
│                                 │ Game.q(lua) -> JSON   (chunked over 2048 B)   │
│                            harness/lua/runtime/*.lua  H.* reads/writes, hooks,  │
│                                 │  event log, roster; one file per domain, loaded │
│                                 │  in harness/runtime_source.py MANIFEST order    │
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
* **harness/lua/runtime/** is the Lua runtime, one file per game domain (38 fragments; `README.md` there says
  which owns what). `harness/runtime_source.py` holds the load order (`MANIFEST`), reads every file once per
  load, hashes the assembled text and emits the small installer that runs each fragment as its own named Lua
  chunk inside the InGame state; it is installed at the next call after `RUNTIME_VERSION` (bootstrap.lua; it goes
  up with every change) or the source digest differs from what the game holds -- by tunerd for a seat-bound
  connection (`ensure_runtime` in `harness/tunerd.py`, the one installer for every bound client since runtime
  v285), by the client's own `Game.ensure_runtime` on a plain daemon -- and only a load whose every chunk ran is
  marked current. Files share helpers through
  `H._ns` (owner exports at its end, consumer imports at its top); everything else is an `H.*` function. The
  runtime holds every read and write, the JSON encoder, the `Events.*` hooks that feed the event log
  (installed by `install.lua`, last), the per-seat unit roster and hp snapshots, and the fog caches (last-seen
  features). Ports of the stock UI's own Lua (combat panel modifier rows, trade pocket legality, city-screen
  hovers, league tooltips) live here so a read says what the screen says.
* **game.py** owns the turn loop, the screen drivers and the digest. Anything the stock game only offers
  through a screen is driven through that screen: the leader scene and the DiploTrade / SimpleDiploTrade
  tables for every deal, peace, demand and pledge; the popups for captures, promotions, great people. It
  verifies what it did (the right leader on screen, every item on the table at the asked amount) because
  the engine clamps or drops silently. It also refuses orders the stock UI never offers (a puppet's
  production, a plot buy in a puppet, a move onto a friendly civ's city) since the gamecore would accept
  them. The quiet-turn run inside `Game.finish_turn` wakes on `_wake_reasons`: todo, blockers, popups, digest
  events and words, and the `alerts` the runtime puts on every status (low happiness, an unhappy tier,
  strategic deficits) -- those only when they worsen against the previous turn this process saw
  (`_note_happiness` / `_alert_wake_reasons`), never on a steady low total. `todo.ongoing` (automated
  units and standing moves, #37) wakes only through a row's `attention` (a visible camp or hostile beside
  the unit, an unreachable destination), never by being non-empty. `expiring_deals` (<= 3 turns) and
  `expiring_friendships` (<= 5) wake it whenever present (#38); the runtime reads them on the seat's own
  turn only and skips the deal snapshot while the shared scratch trade table is occupied.
  The class is one mixin per domain under `harness/game_parts/` (front_end, turn, popups, events, reads,
  cities, units, unit_orders, notebook, diplomacy, espionage, deals, policies, trade routes -- the same cut
  as the Lua runtime's files) plus `support.py` for the helpers they share; `game.py` itself keeps the
  transport (tunerd, runtime injection, `q`) and assembles `Game`. `self` is always the whole Game.
* **mcp_server.py** maps Python calls to MCP tools; the docstrings are the manual the model reads, so each
  says what the tool shows, what the refusal means and which tool to call next. `@guarded` serializes
  actions (`action_lock.py`), lets one client own a seat's turn between calls (`turn_claim.py`) and turns
  tunerd loss into a clear error.
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
   its own seats (`Game.wait_for_my_turn`), plays, and ends the turn. Two harness-driven human seats (Alpha and
   Bravo) are the test bench for everything war- or deal-shaped: `scripts/mcp_session.py`,
   `scripts/finish_turn.py`, `scripts/play_loop.py`. Bookkeeping is per seat: rosters, hp snapshots, event
   audiences, so a loss during the barbarian phase is filed for the seat that owned the unit.
2. **LAN.** The LLM's own game instance joins the humans' LAN game (`Game.join_lan`; `Game.host_lan` for
   the reverse) with its own profile (`XDG_DATA_HOME`) and tuner port (shim `bind()` remap). The local
   player is the active player, so the seat is auto-detected (`Game.detect_seat()`).
3. **Several LLMs ("pitboss").** One instance and one `tunerd` per LLM seat in one shared LAN game
   (`scripts/launch_seat.sh`, `harness/seats.example.json`), each with its own MCP server pointed at its
   tunerd's socket (`CIV5_TUNERD_SOCK`, `--seat`). The HTTP/JSON server that once served this mode was
   removed on 2026-09-27: it bypassed the guard and had fallen 28 tools behind.

## Turn loop and digest
```
Game.wait_for_my_turn: hotseat -> GetActivePlayer() == seat and the hand-off is dismissed
                  LAN     -> Players[seat]:IsTurnActive() and not Network.HasSentNetTurnComplete()
                  returns early when an AI opens a leader screen mid-turn (discussion_pending)
Game.turn_digest: events recorded by the Lua hooks since this seat's last read, folded in game.py:
                  combat rows carry both sides' hp; a captured civilian is one unit_captured row with the
                  captor on the tile when in sight; a unit gone during our own turn with no combat is
                  unit_spent; leader chatter the harness itself provoked is hidden
Game.turn_status: todo (units, cities, promotions, research, pending chooser; ongoing = automated units and
                  standing moves with going_to + attention) + blocking_name and the tool that clears it,
                  read from the engine's EndTurnBlockingType
end_turn:         Game.DoControl(CONTROL_ENDTURN) after sweeping announcement popups; quick-saves first
```

## Tests
`scripts/check.sh` (1063, no game) runs the suite after checking that liblua5.4, lupa and luac are installed:
without them the 50 Lua test files would skip and a green run would say nothing about the runtime. The shipped
runtime is loaded exactly as the game loads it (through `harness/runtime_source.py`) under liblua5.4 or lupa's
Lua 5.1 against fake `Players`/`Map`/`UI` objects, so the tests exercise the real Lua, not a paraphrase; the
Python layer runs against a fake tunerd client that executes the generated Lua in the same runtime.
`tests/test_runtime_source.py` covers the loader itself (reloads, failures, state carry-over, one handler per
event) and lints each fragment compiled alone with luac.
Live verification is recorded per turn in `docs/GAPS.md` against the saves in `saves/`.

## Security note
With `EnableTuner = 1` the game listens on **0.0.0.0:4318**: anyone on the LAN can execute Lua in the game.
Set `CIV5_TUNER_BIND=127.0.0.1` (shim bind hook; the LLM-client preset does this) or firewall the port
before using this on untrusted networks.

## Repo layout
```
harness/     tuner.py (protocol), tunerd.py (daemon), client.py, game.py (+ game_parts/, one mixin per domain), cli.py (lobby/staging/lua CLI),
             mcp_server.py (MCP core: game handle, guard, tool sets) + mcp_tools/ (the tools, one module per domain),
             rows.py (the row shape: act / pick / is_row / rows_in, a leaf), gate.py (the gate and its rows),
             affordances/ (every `{tool, args}` row a reply hands back, one module per concern: decisions, units, questions, choices, objects),
             surface/ (milestone 2.0.0: the nine tools' vocabulary, the retirement map from the old names, the dispatch onto the old handlers (new -> old), the forward map (old -> new: an unlisted old name or alias runs its handler and the reply carries `renamed`), the schemas leaf, the listing's `order` schema per client, classes.py (every set the server and the ledger sort a call by, keyed `(tool, action)`), the survey and audit),
             mcp_tools/surface.py (the nine tools of 2.0.0, the listing; the 145 old handlers are registered and retired at once with `@retired`),
             guide.py (the playbook by topic), supervisor.py (crash/restart),
             action_lock.py, turn_claim.py, runtime_source.py (runtime manifest, digest, installer),
             lua/runtime/*.lua (the injected runtime, one file per domain), lua/audit.lua, lua/generic_popup_shim.lua
shim/        tuner_recv_fix.c -> libtuner_recv_fix.so (gcc -m32)
scripts/     launch_civ5.sh, launch_llm_client.sh, launch_seat.sh, llm_seat_loop.py (an LLM CLI on a seat, turn after turn),
             mcp_call.py (one tool call, fresh server), mcp_session.py (drive a seat), hotseat_rounds.py (advance both
             seats until a decision), scripts/finish_turn.py, play_loop.py (the heuristic player), ledger_report.py,
             measure_reads.py, spectator_demo.py / synth_recording.py (recordings for the page with no game), watch_game.py,
             event_audit.py / tuner_probe.py / mem_watch.sh (debug), check.sh
saves/       the reproduction states S1-S3 (README lists what each shows)
tests/       113 files; liblua5.4/lupa-backed Lua tests and Python-layer tests
docs/        LIMITATIONS.md (declared), ROADMAP.md (GitLab plan), GAPS.md (live audit log), NOTES.md
             (protocol and engine findings), PLAYBOOK.md + TOOL_REPLIES.md (served by `reference(book="playbook")`), AGENT_INSTALL.md,
             VISUALIZATION.md + CANVAS_MIGRATION.md (the spectator page), SESSION_HANDOFF.md,
             COVERAGE_AUDIT_2026-09-19.md (historical, with a status table), lua_api_full.md / lua_api_surface.md /
             lua_command_patterns.md (engine method names and the stock UI's command lines, for `call` and new reads)
web/viz/     the spectator page (harness/spectator serves it): d3 map, canvas renderer behind ?renderer=canvas
CHANGELOG.md package versions <-> RUNTIME_VERSION; scripts/check.sh runs the suite before a push (no hosted CI)
```

## The `order` schema and the three clients (milestone 2.0.0, GitLab #49)

`order(to, action, id, args)` is the one tool whose valid `action` words depend on another argument. Its
listed `inputSchema` is written from the action tables of `harness/surface/vocabulary.py` by
`harness/surface/listing.py`: `to` an enum, `action` a string whose description lists the verbs by target, one
shape for every client. Stage 2b first listed the per-target enums as a `oneOf` on `to` (one branch per target,
`to` fixed with `const`, `action` its enum), with this flat shape as a per-client fallback (`FLAT_CLIENTS`,
`CIV5_ORDER_SCHEMA`), on the premise that a client rendering `oneOf` would show the model the right verbs and
reject a wrong pair itself. The measurement below ended the premise: no client validated, two rendered the
`oneOf` wrongly, and the one that passed it through gained nothing the description did not already say. TDQS
also counts each `oneOf` branch as invocation cost (14 against `answer`'s 3) and flagged `order` as shadowed by
its cheaper sibling; flat, `order` costs 2 and the lint is clean (2026-10-27). The variant machinery is gone.

The server validates itself: `harness/surface/dispatch.py` refuses `order(to="unit", action="produce")` with
`order:unit has no 'produce'` and the unit's verbs under `choices`, and a missing argument with the shape and
one example row. What each client rendered of the `oneOf`, the measurement that decided this:

| Client | Shows the per-target enums | Validates the pair client-side | Passes a malformed call to the server's refusal | Measured |
|---|---|---|---|---|
| Claude Code (`claude-code/2.1.311`) | no, since 2.1.311: `ToolSearch` renders the `oneOf` as one sentence, *"Input constraint: Provide parameters for exactly one of: (to, action)"*, which is not what it says, and the branches' enums are gone (on 2026-10-25 an earlier build showed the `oneOf` with its branches). **Shown flat since 2026-10-27** (`FLAT_CLIENTS`): the description lists the verbs by target, so nothing is lost and the misleading line goes. | no | yes: `order(to="unit", action="produce")` sent from Claude Code at Assyria t238 reached the server and came back as `order:unit has no 'produce'` with the unit's verbs | 2026-10-25, 2026-10-27 |
| Codex (`codex-mcp-client` 0.160.0) | no: its `exec` declaration renders the schema as TypeScript and turns the `oneOf` into a union of the branches alone, `{action?: ...; to?: "unit"} \| ...`, so `id`, `args` and `action_id` vanish and both words read optional. **Shown flat since 2026-10-26** (`FLAT_CLIENTS`); the flat declaration carries every argument. | no (the union makes the pair optional) | yes: at Assyria t247 it copied Ur's gift row with the `id` and `args` the declaration never showed, and the call ran | 2026-10-26 |
| Grok CLI (`grok-shell-civ5/1.0.70`, Grok Build 1.0.70) | yes: its `search_tool` hands the model the listed `input_schema` verbatim, `oneOf` and all ("both shapes were visible at once"); it keeps the oneOf variant | no: `use_tool` says the arguments must match the schema and sends them unchanged | yes: the same malformed order at Assyria t238 reached the server and came back as the server's refusal, in the server's shape; no client error exists to tell apart (`docs/measurements/2026-10-27-assyria-t238-grok-session.md`) | 2026-10-27 |

`scripts/tool_survey.py` counts the whole listing.

## Classification by `(tool, action)` (milestone 2.0.0, GitLab #51)

Everything that decides how a call is treated -- a menu tool, usable while it is not my turn, a wait that
sleeps outside the lock, a read that skips the refusals and never claims the turn, a response whose input is
the pending thing, a save that runs under a popup, what a batch may not carry, which popups an order may run
under, the ledger's read / write / wait and the spectator's focus -- is a set in `harness/surface/classes.py`
keyed by `(tool, action)`: `("turn", "status")` is a read and `("turn", "finish")` a wait, `("state", "*")`
every read of the world. A call's key comes from its arguments (`classes.of_call`: a new tool's fixed fields,
an old name's or alias's row in the retirement map), and the guard keys the old handler it wraps by its row
(`classes.of_handler`), so the league read by its old name and `state(what="league")` are one key and no set in the
server, the gate (`resolutions_by_key`) or the ledger names a bare tool. A ledger row carries the same words:
`tool` (one of the nine), `action` (the label; an answer's actual choice) and `called` when the client used
an old name or an alias; the spectator prints `tool · action`. With nine listed tools nothing needs hiding, so
`--tools compact` is gone and the by-name call tool is retired: off the listing, still answering by name through
the retirement map (`mcp_server.retire`, the first occupant of the retired-handler table).

Since stage 2e (#52) the table holds every old handler: each tool module writes `@retired` where `@mcp.tool()`
stood, which registers the handler (its schema, guard, ledger and replay wrappers) and takes it off the listing
at once, so `tools/list` is the nine and nothing else. An old name reaches its handler through `find_tool` and
the map, with `renamed` on the reply and the request context passed on (a finish by its old name keeps
its progress notifications; a bad argument is raised as the SDK's error, as it was when listed); the nine reach
the handler they dispatch to by its exact name (`find_tool(exact=True)`), never through the map, so they answer
whether or not the old names do. `--retired-names off` (`CIV5_RETIRED_NAMES`) switches the map off: an old
name is then unknown and no retired name is suggested, the state a session that was never shown an old name
plays in; `scripts/check.sh` runs the tests marked `new_vocabulary` a second time that way.
