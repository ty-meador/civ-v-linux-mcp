# civ_v_llm_harness

Lets an LLM play **Sid Meier's Civilization V** (Steam, Linux, Brave New World) in the same game as humans
and the built-in AI, through an MCP server with 121 tools. The LLM's "client" is a real game instance driven
over the game's own FireTuner Lua socket; humans play at the same machine (hotseat) or over LAN (the LLM
runs its own game instance and joins like any other player).

The rule the whole project is built around: **the seat sees what a human in that seat sees, and no more.**
Every screen, hover and refusal reason a human reads is a tool result; fog, unmet civs and private AI state
stay hidden. `docs/LIMITATIONS.md` says what the harness will not do and why; `docs/ROADMAP.md` tracks the
road to 1.0.0; `CHANGELOG.md` maps package versions to the Lua runtime's own counter.

## One-time setup
1. `config.ini` (`~/.local/share/Aspyr/Sid Meier's Civilization 5/config.ini`): `EnableTuner = 1`.
   Optional: `LoggingEnabled = 1`.
2. Build the 32-bit shim: `cd shim && gcc -m32 -O2 -shared -fPIC -o libtuner_recv_fix.so tuner_recv_fix.c -ldl`
3. Python env: `uv sync --group dev` (the `dev` group adds pytest and lupa for the regression suite).
4. Steam must be running before the game launches. Headless machine or fresh login:
   `env DISPLAY=:1 WAYLAND_DISPLAY=wayland-1 XDG_RUNTIME_DIR=/run/user/$UID steam -silent &`

## Bringing the stack up
```bash
scripts/launch_civ5.sh                      # the game via Steam's container runtime + shim; ~2 min to the menu
ss -ltn | grep 4318                         # poll until the tuner port listens (never run tuner_probe.py here)
python -m harness.tunerd --port 4318 --sock $XDG_RUNTIME_DIR/civ5-tuner.sock &   # owns THE tuner connection
scripts/mcp_call.py --seat 0 turn_status '{}'   # one real MCP call through a fresh stdio server
scripts/mcp_call.py --seat 0 load_latest '{}'   # or load_save '{"filename": "Alpha-Bravo_0237 peace-terms"}'
```
`tunerd` logs `48 lua states` once the front end is up; `0 lua states` means it connected too early, and the
connection is retried on the next request. Restarting `tunerd` is always safe (the shim lets the game
re-accept). Every civ5 tool answering `No such file or directory` means `tunerd` is gone, not the server.

## Playing a seat
The turn loop the model runs: `wait_for_my_turn` -> `turn_digest` (what happened since last time, one row
per event, captures and combats linked to their notices) -> `turn_status` (todo, and which tool clears the
block) -> reads (`overview`, `cities`, `units`, `map_window`, `city_screen`, `diplomacy`, `relationship`,
`trade_catalog`, ...) -> actions -> `end_turn` (quick-saves by default). A refused action says why and what
to do instead; nothing crashes the game.

- **Hotseat, one machine.** `python -c 'from harness.game import Game; g = Game(); g.host_hotseat(human_seats=[0, 1], nicknames={1: "Claude"}); g.wait_ingame()'`,
  then attach an MCP client (`.mcp.json`, Claude Code picks it up here). Two harness-driven human seats are
  how war-only situations are manufactured: `scripts/mcp_session.py --seat N` drives one seat interactively,
  `scripts/finish_turn.py --seat N` clears a seat's bookkeeping so its turn can end, `scripts/play_loop.py
  --seats 0 1` plays both unattended.
- **LAN, the LLM as its own network player.** `scripts/launch_llm_client.sh` (own profile, tuner on 4319),
  `python -m harness.tunerd --port 4319 --sock $XDG_RUNTIME_DIR/civ5-llm.sock &`, `export
  CIV5_TUNERD_SOCK=...`, then `python -m harness.cli lan-games | join-lan <id> --nick Claude | slots |
  wait-ingame`. To host instead: `python -m harness.cli host-lan --open 1 2 --nick Claude`, then `launch`.
- **Multi-LLM pitboss.** One Civ5 instance and one `tunerd` per seat (`scripts/launch_seat.sh <name>`,
  entries in `harness/seats.json`, copied from `seats.example.json`), served by `python -m
  harness.http_server --port 8765`: routes mirror the MCP tools 1:1, `X-API-Key` maps to exactly one seat,
  OpenAPI at `/openapi.json`. The raw `lua` route is off per seat unless `"allow_lua": true`.

## Diplomacy and trade
All of it goes through the game's real screens, because headless deal building crashes the engine.
`trade_catalog(player_id)` is the pocket: what each side may put up (gold, gold per turn, resources, cities
with population, embassies, open borders, pacts, World Congress vote pledges, third-party war and peace) with
the screen's reason when a row is grey, and `peace` as the Negotiate Peace gate. `propose_deal` proposes and
reads the reply (`accepted`, `reply`, measured `effects`); to a human seat it sends the table, which that seat
reads as `incoming_deal` and answers with `accept_deal` / `refuse_deal`. `negotiate_deal` asks the AI what
would make a deal work without proposing it. `make_peace(player_id, items)` is peace with terms; `demand`
is the leader screen's Demand button; `declare_war`, `denounce`, `propose_friendship`, `discussion` /
`respond_discussion` and the `diplo_event` escape hatch cover the rest. `turn_digest` carries
`leader_message` rows when an AI approaches you, and `wait_for_my_turn` returns early with
`discussion_pending` when one does so mid-turn.

## Tests
```bash
scripts/check.sh                              # 482 tests, no game needed; run it before every push
```
The Lua runtime (`harness/lua/runtime.lua`) runs under lupa / liblua5.4 against fake game objects; the
Python layer runs against fake tunerd clients. There is no hosted CI by choice (no shared runner minutes).
Live checks are recorded per turn in `docs/GAPS.md` against the saves in `saves/` (see its README).

## Gotchas
- Never bind TCP 4318 before the game does: the game aborts at init. A second instance needs
  `CIV5_TUNER_PORT` (the shim remaps the game's bind), which `launch_llm_client.sh` sets.
- The tuner listens on 0.0.0.0:4318 by default: set `CIV5_TUNER_BIND=127.0.0.1` or firewall it on untrusted
  networks (anyone can run Lua in your game).
- A running MCP server keeps the Lua it loaded at start and re-injects that version; after changing
  `runtime.lua`, verify through `scripts/mcp_call.py` (a fresh server per call) or restart the server.
- The tuner truncates an inbound command at 2048 bytes; `Game.q` chunks long Lua itself, so write reads and
  writes as `H.*` functions in the runtime rather than long inline bodies.
- In LAN games `end_turn` a second time would un-ready the player; the harness refuses it and reports
  `turn_complete_sent` instead.
- Quick saves from every mode land in `Saves/single/quick/QuickSave.Civ5Save`, one slot: copy anything worth
  keeping to a named file at once.
- More than eight logical CPUs crash the Linux port periodically; `launch_civ5.sh` pins the game to 0-7
  (`CIV5_TASKSET`).
