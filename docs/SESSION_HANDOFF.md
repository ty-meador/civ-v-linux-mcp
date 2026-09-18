# Resume here — 2026-09-18 (seventeenth session): LAN game vs Grok on the Deck, staged but NOT launched

## What the user wants next session

Start the staged 2-LLM LAN game and play seat 0 to win, manually, turn by turn (same standing rules as
the solo game: quick_save every turn, human-visible info only, no play loops, commit incrementally).
The solo China game (t313, runtime v85) is SAVED by the user and untouched; do not load it.

## Exact state at hand-off (2026-09-17 ~22:50)

- Desktop (10.10.10.2): game in **StagingRoom**, `is_host: true`, `everyone_connected: true`. Slots:
  - 0 = "Native Coder" (Claude, HANDICAP 5 = Emperor), connected
  - 1 = "raidenphoenix711" (Grok on the Steam Deck, handicap 3 = Prince), connected
  - 2-5 = AI (SS_COMPUTER), 6-7 = unused
  - The user set the game up by hand (map/options unknown to me; `staging_status()` does not carry them).
    A single-player save could not be loaded into co-op, hence a fresh game.
- Steam Deck (deck@10.10.10.171): harness rsynced to the desktop's v85 tree; game at the lobby/staging
  screen as the joined client; user units `civ5-tunerd` and `civ5-supervisor` active (`civ5-game` is not
  a unit; the game was launched by `scripts/launch_deck.sh`, reaper pid in `logs/civ5-deck.pid`).
  Supervisor runs with `--grace-seconds 240 --menu-timeout 480` (defaults were too short for the Deck's
  cold boot + intro video and caused one spurious relaunch).
- Grok's client: Grok Build CLI on the desktop, seat directory `~/projects/grok-deck-seat` (outside
  this repo): `.grok/config.toml` = one stdio MCP server whose command is
  `ssh -T -o BatchMode=yes deck@10.10.10.171 "cd civ_v_llm_harness && env CIV5_TUNERD_SOCK=... XDG_RUNTIME_DIR=/run/user/1000 .venv/bin/python -m harness.mcp_server --seat auto"`,
  `AGENTS.md` = GROK_PLAYBOOK.md, folder trusted. `grok mcp doctor`: handshake OK, 71 tools (raw `lua`
  gated off). End-to-end `turn_status` over that SSH line verified. Notes: `~/projects/grok-deck-seat/RUN.md`.
  **The user starts Grok** (`cd ~/projects/grok-deck-seat && grok ...`); Claude never touches that seat.

## Steps to start the game (Claude does these)

1. Sanity: `XDG_RUNTIME_DIR=/run/user/1000 .venv/bin/python -m harness.cli status` on the desktop ->
   StagingRoom, slot 1 connected. Over SSH on the Deck: `systemctl --user is-active civ5-tunerd
   civ5-supervisor` and `cli status`. If slot 1 is not connected: on the Deck
   `XDG_RUNTIME_DIR=/run/user/1000 .venv/bin/python -m harness.cli join-lan 10.10.10.2`.
2. Launch from the desktop: `.venv/bin/python -m harness.cli launch` (or `ready` first if the host must
   be ready; `slots` shows the table). Then `cli wait-ingame`.
3. Tell the user the game is launched so they start Grok. Then play seat 0 through the repo `.mcp.json`
   `civ5` server (seat `auto` = local player in a network game): `wait_for_my_turn` -> `turn_digest` ->
   `turn_status` -> act -> `quick_save` -> `end_turn`. `scripts/et.sh` background pattern still applies.
4. First-turn checks worth logging in NOTES.md: `turn_state()` (mode should be `lan`; note the MP turn
   option — simultaneous vs sequential — because `wait_for_my_turn` semantics differ), whether the
   Deck seat's turns end promptly (Grok idle = game stalls; tell the user, do not poke the Deck).

## Gotchas fresh in mind

- LAN: `end_turn` refuses a second call (it would un-ready us); `turn_complete_sent` in turn_state.
- Deck crash class (gamecore null-deref, NOTES.md 2026-09-17) is unexplained; the supervisor replays
  `join_lan` automatically. Host does not need to restart. `turn_digest` reports `reconnected`.
- The Deck boots with an intro video; a key press on the Deck skips it. Tuner appears only after.
- Never read the Deck's tunerd socket or logs; that is the other player's private game.
- Desktop socket for Claude's seat: `/run/user/1000/civ5-tuner.sock` (the sandbox needs
  `XDG_RUNTIME_DIR=/run/user/1000`).

---

# Resume here — 2026-09-17 (fifteenth session, solo China game)

## User directive for the next session

The user will set up a **fresh game for Claude to play alone** (single LLM seat, in-game AI opponents)
and sleep. Play it to win, manually, turn by turn, and fix/catalog harness bugs as they come up.
Standing rules: [[feedback-civ5-play-manually]] (no heuristic play loops), quick_save every turn,
human-visible information only, don't flip 2D/3D, commit incrementally, don't push.

Victory conditions the user prefers: domination, science or culture. Diplomatic victory OFF (too easy on
a small map). Difficulty "hard" = HANDICAP_EMPEROR on the human slot(s).

## How to control the game (no MCP client attached in the last session)

```sh
.venv/bin/python scripts/mcp_call.py --seat 0 turn_status '{}'      # goes through the real MCP tool layer
.venv/bin/python scripts/mcp_call.py --seat 0 wait_for_my_turn '{"timeout": 360}'
```

Seat: `--seat 0` for a game hosted from this desktop (LAN host or single human). The desktop instance is
launched by `scripts/launch_civ5.sh` (shim + 8-CPU taskset), bridge by `python -m harness.tunerd`
(socket `$XDG_RUNTIME_DIR/civ5-tuner.sock`). If the user hosts through the game UI, `cli.py status`
shows `StagingRoom`; ready up with the Lua in the "Ready up" snippet below, then `launch_game()`.

Ready up + launch from a user-made lobby:
```python
from harness.game import Game; g=Game(); c=g.c; stg=c.wait_state("StagingRoom",5)
c.exec(stg,"local me=Matchmaking.GetLocalID(); PreGame.SetNickName(me,'Claude'); PreGame.SetReady(me,true); Network.BroadcastPlayerInfo()")
g.launch_game(); g.wait_ingame(); g.detect_seat(); g.quick_save()
```
`cli.py host-lan` now takes `--map continents.lua --size WORLDSIZE_SMALL --close 3 --handicap HANDICAP_EMPEROR`.

## What happened this session (2026-09-17, ~00:00-01:00)

- Steam Deck (`deck@10.10.10.171`) set up as a second LLM seat for Grok: switched Civ V from Proton to
  the native Linux build, harness + venv installed, user systemd units `steam-harness`, `civ5-game`,
  `civ5-tunerd`. Full how-to: `docs/DECK_HOWTO.md`; LLM-player playbook: `docs/GROK_PLAYBOOK.md`.
- Two 3-seat LAN games were started (Claude host on desktop, Grok/Siam on the Deck, 1 AI). The user is
  parking the Deck idea for now: the Deck crashed once (new signature, gamecore DLL null-deref, see
  NOTES.md) and driving both seats by hand was clumsy. The current LAN game (turn 2, Claude = Indonesia,
  Jakarta at (38,29), Pottery researching, Scout in production) is effectively abandoned.
- Harness fixes committed this session:
  - `dismiss_pending_popups` now closes `TextPopup` (BUTTONPOPUP_TEXT message boxes, e.g. "player
    disconnected") and cancels `DeclareWarPopup` confirmations (BUTTONPOPUP_DECLAREWARMOVE "entering that
    territory would trigger war") via `HideWindow()`, then clears the stale H.popups record because
    HideWindow does not fire PopupProcessed. **Neither has been re-verified live after the final edit**
    -- the Deck seat's stuck DECLAREWARMOVE was cleared by hand with the same calls, which is the evidence.
  - `host_lan` gained map_script / world_size / closed_seats / handicap.
  - `launch_civ5.sh` gained CIV5_STEAM_LIB / CIV5_SLR_LIB overrides; `scripts/launch_deck.sh` preset.

## Known gotchas fresh in mind

- `move_unit` into an unrevealed plot is refused ("plot is not revealed") -- use `map_window` first.
- `move_unit` toward a city-state/rival border silently pops the war-move confirmation; the unit does not
  move and `MISSION_SKIP` does not clear ENDTURN_BLOCKING_UNITS until that popup is dismissed.
- The game rewrites config.ini on exit; a relaunch by the user through Steam's UI (no shim) leaves the
  tuner disabled in MP. Always relaunch through the harness launcher.
- The mcp guard blocks every action tool with "popup needs a decision" while any recorded popup remains;
  `wait_for_my_turn` runs the sweep.

## Current game state (2026-09-17, fifteenth session, ~20:00)

Solo China game (Wu Zetian, Emperor), **turn 314 (my turn, nothing pending)** (check `logs/et_last.log` /
`python3 scripts/turn_brief.py` first; the session runner sometimes kills the background `et.sh`
job "for low memory" -- the game is unaffected, `turn_status` tells whether end_turn went through).
Runtime v85 (sixteenth session: raw `lua` tool opt-in via CIV5_ALLOW_LUA=1 / --allow-lua; propose_deal city/amount gates -- see NOTES). Same driving recipe (`mcp_call.py --seat 0`, `scripts/et.sh > logs/et_last.log` in the
background, `--wait-only` after answering an AI).

- **Ideology Order** (t311, Socialist Realism tenet). Five cities: Beijing National Epic, Shanghai
  Seaport, Guangzhou Windmill, Nanjing Hospital, Xian Lighthouse. Happiness 20, science ~340, gold
  ~960 at +90/turn, culture 1065/1695, faith 495 (Missionary 400 buyable; nothing bought yet).
- Research Rifling (2t). Plastics needs Electricity first (Refrigeration done t310). A free Great
  Scientist (786444) sleeps in Beijing for a later bulb.
- Research Agreements: Poland (t286), America (t296), Sweden (t297). Friends: Poland, America,
  Sweden. Wars around us: Venice vs America, Sweden vs Poland, India vs America, Sidon vs Venice/Monaco.
  We decline every co-op war request. Spies: Liu rigging Zanzibar, Wu rigging Antwerp, Yang -> Stockholm.
- Trade: 5/5 routes (Beijing->Antwerp/Ur/Shanghai-prod, Nanjing->Antwerp, Shanghai->Venice by Cargo
  Ship 27 gpt). A second caravan (770063) sleeps in Nanjing (no slot). Deals: Gems <-> Spices with
  America (t304-334); Gems from Sweden ends ~t313 (then our Gems copy is the exported one -- renew or
  lose 4 happiness); Copper to Venice/Sweden; Dye to America.
- Caravel 540678 on a multi-turn engine path to (54,29); do NOT MISSION_SKIP it (v83 refuses).
- Zanzibar ally (75 vs India 47), Genoa/Antwerp friends. Worker 49155 asleep in Xian; Musketman at (43,11).

## Immediate next work

1. Read `logs/et_last.log`; act on `todo`. Rifling -> Electricity -> Plastics (Research Labs).
2. Renew/replace Sweden's Gems around t313 (watch `incoming_deal.last_copy` / happiness).
3. Archaeologist for the antiquity sites at (41,12) and near Nanjing (CHOOSE_ARCHAEOLOGY untested).
4. Untested still: ADD_REFORMATION_BELIEF, ANNEX/PUPPET popups through `answer_popup`.

## Thirteenth session (2026-09-17, ~14:00-14:30)

- New `explore_frontier(unit_id, limit)` tool/route (runtime v64-v66): fog-edge plots of the unit's
  domain, nearest first, `unrevealed_neighbors`, terrain, `map_edge` on polar rows. Caveat: `distance`
  is hex distance, not path length (see NOTES thirteenth session).
- `mcp_call.py` tool errors exit 1 cleanly (no ExceptionGroup traceback).
- Tests 34/34: `uv run --with pytest pytest -q tests`.

## Tenth session (2026-09-17, ~09:30-): propose_deal works (real trade screen)

`propose_deal(player_id, items, ask_counter)` and `negotiate_deal(player_id, items, mode)` are live MCP tools
now (see NOTES.md tenth session). They drive LeaderHeadRoot.OnTrade -> DiploTrade pocket handlers ->
OnPropose and close everything themselves; results carry measured `effects`. Venice holds one of my Copper
for free until t261 (dev accident, see NOTES). Game still at **turn 231** when this was written.

## Immediate next work

1. Read `logs/et_last.log` (turn_brief.py): act on `todo`, `blocking_hint`, any discussion.
2. Nanjing Settler -> eastern strip (see route above). This is the first live embark + cross-sea settle;
   expect move_unit / MISSION_FOUND edge cases and fix them.
3. Navigation -> Seaport in Shanghai; then a Cargo Ship once a trade-route slot frees (t282 earliest,
   `trade_routes` shows turns_left) to test sea trade routes.
4. Untested still: CHOOSE_IDEOLOGY (3 factories or Modern era), ADD_REFORMATION_BELIEF, CHOOSE_ARCHAEOLOGY.
5. Harness idea: `explore_frontier` cannot report path length (Unit:GeneratePath NYI); consider marking
   plots on the far side of land as `same_water_body=false` via a flood fill over revealed water.
