# Resume here — 2026-09-19 (twenty-third session): NEW solo game, Shoshone (Pocatello), Emperor — domination + religion (runtime v119)

- User directive: new game, random leader, Emperor, go for a victory type not yet played so new MCP needs surface;
  check religion / combat / diplomacy coverage. Plan: **Domination with a founded religion**. Settings were the
  persisted ones: Continents, Small, Standard, victories Space/Domination/Cultural (Diplomatic off).
- Started by `cli start-single --handicap HANDICAP_EMPEROR` (new `Game.start_single_player`: Single Player > Set Up
  Game, random civ = -1, presses the Dawn of Man Continue button). Game boots with `scripts/launch_civ5.sh civ5`.
- Capital Moson Kahni (49,19): river, coast, 2 Salt, Ivory. Pottery first (Shrine), Pathfinder -> more scouting.
  Ruins choice at t2 (new `goody_hut_options` / `choose_goody_hut`): took population. Second ruin at (50,23).
- `docs/COVERAGE_AUDIT_2026-09-19.md`: static audit of religion/combat/diplomacy vs the stock UI, ranked gaps.
  t22-t33 (runtime v129): pantheon Earth Mother founded via the tool (guard fix), first combat matched the preview,
  refused orders keep standing moves. Settler due ~t35 (site not chosen yet), Archer next to clear the camp at (43,29)
  with the Warrior healing on the hill (45,28). Met Ethiopia (embassy deal accepted).
  t13-t18 (runtime v128): #8 war_consequences, #3 city_capture_options/choose_city_capture (UNVERIFIED on a real
  capture), BUILD_* missions, rival pantheons in religion_overview. **Only #2 peace terms is still open.**
  Done t0-t11 (runtime v125): #7 faith GP, #4/#5 previews + city-assault standing-move fix, #10 religion_overview,
  #9 city_state_actions/action, trade_catalog x,y leak. Still open: #2 peace terms, #3 city capture popup, #8 declare-war
  consequences. Met: Sidon (pledged), Inca.
  Earlier: #1 belief listing (`available_beliefs`), #6 `add_reformation_belief`, slot validation in
  found/enhance. Next in order: #7 faith great person tool + hint, #10 religion overview, #4/#5 attack previews
  (city melee, ranged) and the standing-move re-attack bug, #3 city capture popup, #2 peace terms, #9 city-state
  actions, #8 declare-war consequences, trade_catalog unrevealed-city x,y leak (rule 2).
- Play loop unchanged: `bash scripts/et.sh > logs/et_last.log` in the background; do not call mcp_call while it
  runs (the action lock makes both sides wait/refuse).

# Resume here — 2026-09-19 (twenty-second session): solo China game WON — Science Victory t457 (runtime v117)

- SS Engine finished in Beijing t457; `unit_mission MISSION_SPACESHIP` replied spaceship 1/1, 1/1, 1/1, 3/3 and the
  game went straight to GAMESTATE_OVER (`turn_status.game_over:true`, digest notification "Wu Zetian has Won!").
  No separate launch step was needed. Venice was at 18 of 30 delegates, UN session 2 turns away.
- Last turns: Great Writer -> MISSION_GIVE_POLICIES (731 culture) -> Young Pioneers; refused Sweden's open-borders
  offer (Venice reported Sweden plotting). Quicksave at t457 is from just BEFORE the engine was added.
- Next: the solo game is finished. Open harness item unchanged: fogged plots read the live feature. The
  multi-seat Deck/observer game (eighteenth-session section below) is the remaining goal.

# Resume here — 2026-09-19 (twenty-first session, late): China t429, space race under way (runtime v114)

## State at t429
- Science ~850/turn, Future era. Apollo done t403. Ship (`spaceship_status`): Cockpit IN (t424); Stasis Chamber
  building in Beijing (Spaceship Factory bought); Boosters x3 queued after Spaceship Factories in Guangzhou/Nanjing
  and after Shanghai's Factory; Engine needs TECH_PARTICLE_PHYSICS (research path Telecom -> Mobile Tactics -> PP).
  Parts cannot be bought (no gold price); production is the bottleneck (Factories + Spaceship Factories + caravan
  production routes into Beijing).
- **Diplomatic threat: Venice** (UN host, World Religion) 18-22 of 30 delegates; China 14. City-state allies swing
  2 delegates each; Sweden/Venice outbid me for Monaco/Quebec repeatedly. My World Religion repeals failed twice;
  pending proposal: repeal Historical Landmarks. No World Leader vote scheduled yet (league_status
  turns_until_world_leader_vote absent). Watch `league_status.members` every session.
- Friends: America (DoF renewed t395, RA partner). Decline war requests (use respond_discussion expect="no interest").

# Resume here — 2026-09-19 (twenty-first session): solo China game t319-347, harness pass (runtime v101 -> v107)

## State
- Solo China save (Wu Zetian, Emperor), turn ~347, Modern era. 5 cities; science ~540/turn with Laboratories in
  Shanghai, Guangzhou, Nanjing (Beijing's queued after Walls). Research path set to TECH_COMPUTERS (queue).
- Research agreements running with America, Sweden, India (350 gold each). DoF: America renewed via the new
  `propose_friendship` (Sweden declined t345 -- ask again later). America is at war with / denounced Poland and
  denounced India: do not DoF those two.
- World Congress: my Sciences Funding proposal votes ~t349.
- Play loop: `bash scripts/et.sh` as a background job (save -> end_turn -> wait -> digest); `--wait-only` after
  answering an AI question. Direct calls: `XDG_RUNTIME_DIR=/run/user/1000 uv run python scripts/mcp_call.py --seat 0 <tool> '<json>'`.
- Tests: `uv run --with pytest --with lupa python -m pytest -q tests` (69); use `set -o pipefail` when chaining a
  commit after it (a `| tail` hid a failure once).

## Harness changes this session (details in NOTES.md, twentieth/t320-347 entries)
- Game.q ships bodies > 2 KB in chunks (tuner truncates at ~2.5 KB -> bare "Syntax Error").
- Replies: markup stripped; digest dedupes notifications; unknown tool / item / tech names get did_you_mean;
  rejected args show the tool signature; illegal missions list legal ones (+ stacking reason).
- New: propose_friendship, set_production append=true (queue), league pending_proposals, overview.idle_trade_units,
  research-agreement gold_cost, renewal flags on deals, great-person effect before/after.
- Visibility audit (v106-v107): city-state rivals' influence, third-party defensive pacts / CS friendships,
  unmet CS ally, trade_catalog them_available -- all removed/gated to what the stock UI shows.
- Open: fogged plots read the live feature (no revealed-feature getter found).

---

# Resume here — 2026-09-18 (eighteenth session): Claude plays FROM THE DECK; desktop hosts an observer game

## What the user wants next session

Do what Grok tried this run, but from the Deck seat: the user hosts an **observer game** on the desktop
(10.10.10.2), Claude joins from the Steam Deck (`deck@10.10.10.171`) through the SSH-stdio MCP server and
plays that seat to win, manually, turn by turn (quick_save every turn, human-visible info only, no play
loops, commit incrementally, don't push).

## How Claude connects to the Deck seat

- Start Claude Code from `~/projects/claude-deck-seat` (its `.mcp.json` is the one `civ5` server: an SSH
  line into the Deck running `harness.mcp_server --seat auto` against the Deck's tunerd socket; `CLAUDE.md`
  there has the checks). Do NOT start inside `civ_v_llm_harness` for that role — its `.mcp.json` is the
  desktop seat, and the desktop's tunerd socket is the observer's/host's private instance.
- Deck side: user units `civ5-tunerd` + `civ5-supervisor` (`--grace-seconds 240 --menu-timeout 480`),
  game launched by `scripts/launch_deck.sh`; `cli status` over SSH shows the screen. Join the desktop's
  lobby with `cli join-lan 10.10.10.2` on the Deck (the supervisor replays it after a crash).
- Harness edits: in the desktop git repo, then rsync to the Deck (command in claude-deck-seat/CLAUDE.md).
  The Deck tree is at v86 now. `harness.game.ensure_runtime` reloads the Lua runtime by digest, so a
  rsync + a new MCP session is enough.

## What happened this session (2026-09-17 evening)

- Launched the staged LAN game (Claude host = Huns, Grok/Deck = Carthage, then a restaged "hybrid" lobby).
  Grok's seat was marked **defeated at turn 1**: his founding/moves were applied only to the Deck's local
  gamecore, the host force-resynced him to a city-less state. Full analysis + fix: NOTES.md 2026-09-17
  (seventeenth session). Commit 27cfa83 = runtime v86: all unit orders go through
  `UI.SelectUnit` + `Game.SelectionListGameNetMessage` (the game's own UI path), never `Unit:PushMission` /
  `Unit:DoCommand`; effects are polled. 56 tests pass. **Not yet verified live.**
- The user's standing decision: **always use the game's network commands for every state change**, so
  the harness behaves the same on a single seat, a LAN host and a LAN client.

## First things to verify live (log them in NOTES.md)

1. A move_unit / MISSION_FOUND from the Deck seat: does the host's `net_message_debug.log` (desktop,
   `~/.local/share/Aspyr/Sid Meier's Civilization 5/Logs/`) stay free of `Out Of Sync` /
   `NetForceResync` at the next rollover? (The desktop's own game log is the host's; reading it is fine.
   Never read the Deck's tunerd socket or the other player's logs when a second LLM plays.)
2. Does `SelectionListGameNetMessage` work from the tuner context at all, and does selection land in the
   same call or through the `select_pending` retry (`Game._order`)? If orders silently do nothing, the
   fallback to investigate is `Game.HandleAction` / `Game.SelectionListMove` (also selection-based).
3. `turn_status` flags for hybrid turns (`simultaneous`, `dynamic_turns`) — see NOTES.

## Gotchas fresh in mind

- LAN: `end_turn` refuses a second call; `turn_complete_sent` in turn_status.
- `wait_for_my_turn` takes no arguments (no `timeout`); `turn_state` is not a tool (use `turn_status`).
- Tech ids for set_research are `TECH_*` (`set_research MINING` -> "unknown tech").
- The Deck boots with an intro video; a key press on the Deck skips it. Tuner appears only after.

---

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
