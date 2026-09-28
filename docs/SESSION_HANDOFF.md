# Resume here -- 2026-09-27 (latest): runtime v252 committed (trade cap, caravan-route binding); game quit, live check owed

- 845a60a: the trade-unit cap names its rule (`H.trade_unit_count`: alive + queued of possible;
  `overview.trade_units_queued`, `free_trade_route_slots` = available - used - queued, `trade_note`, `compare` /
  `set_production` refusals) and `trade_routes` keeps a caravan on its route across reads (`H.route_units`,
  `unit.matched` = recorded / line / line_ambiguous). GAPS closes both open trade rows. 1128 tests green.
- Runtime v252 has NOT run in a live game yet: the game was quit before the check. On the next cold start
  ([[project-cold-start-stack]]: Steam is still up, so `scripts/launch_civ5.sh main`, wait for 4318, tunerd
  reconnects, `load_latest`), the first call re-injects (~70 s): then read `overview` for `trade_units_queued` /
  `free_trade_route_slots` / `trade_note` on both seats, `trade_routes` for `unit.matched`, and queue a Caravan
  in a city with one slot left to see `trade_units_queued: 1` and the second one refused.
- Everything below (the server in parts, how_to_play, v244-v251, the hotseat at t153+) still holds.

# Resume here -- 2026-09-27 (earlier): the MCP server in parts, how_to_play, runtime v251; the hotseat at t153+

- The server is a core plus one tool module per domain (`harness/mcp_tools/`), every tool still an attribute of
  `harness.mcp_server`; `python -m harness.mcp_server` runs the importable module (the `__main__` copy served
  no tools after the split, caught by the first stdio client; `tests/test_stdio_server.py` now starts the real
  server). `READ_TOOLS` is the call ledger's list (seven reads had claimed the turn). `load_save` / `load_latest`
  work again (the mixin split had moved `LUA_DIR`).
- Claude Code shows ~2000 characters of the instructions and of each description: both are under that now, and
  `how_to_play(topic)` serves `docs/PLAYBOOK.md` by topic plus `docs/TOOL_REPLIES.md` (the long reply references
  moved there verbatim). `tests/test_guide.py` enforces the cap. 143 tools.
- Runtime v244 (civilian one-per-tile refusal, trade units out of `todo.stacked`) is merged; v245/v247 reword
  the `expiring_deals` hint (a resource can be re-offered only once the deal has ended); v246 adds
  `active_turn_active` so the wait gate names the AI round; v248 adds `territory` to unit rows. The gate names
  `accept_deal` for a deal on the table (`trade_state` used to be popped off the status), and
  `accept_deal` / `refuse_deal` / `dismiss_discussion` hand over the next queued leader (`next`, `gate`).
  The `lua-civilian-refusal` branch and its worktree are gone. Later the same evening: `end_turn` re-sends
  once against a stale blocker, `dismiss_discussion` clicks through queued greetings, runtime v249 names the
  trade-route cap in `compare`, the briefing's idle-caravan row names its unit, v250 stops permanent deals
  reading as expiring, v251 puts an adoptable policy on the checklist, `scripts/hotseat_rounds.py` advances
  both seats until a decision; the game stands at t153+. Both seats hold Declarations of Friendship with
  Portugal and Russia (Mongolia declined Portugal's war on Russia at t153); Venice's spy Niccolo was sent to
  Karakorum by a careless script and should move to a rival capital; Venice builds Oxford University.
  with both seats' plans in their notebooks (Venice: Astronomy, trade; Mongolia: Porcelain Tower, Academy at
  (28,23) by order 14, spy in London).
- The game: Venice/Mongolia hotseat relaunched cold and loaded with `load_latest` at t135; one player (Claude)
  runs every seat through `scripts/mcp_call.py` / `scripts/mcp_session.py --seat N`; no Grok or Codex loops.
  The Claude Code session server predates the split and runtime v245: do not call `mcp__civ5__*` from it (a
  call would re-inject its older runtime); use the scripts.
- `scripts/check.sh` needs `luac` (see below).

# Resume here -- 2026-09-27 (latest): 1.6.0 cut (runtime v242); the Venice/Mongolia hotseat at t53, seat 0 on screen

- Milestone 1.6.0 is done and tagged: #42 the runtime split, merged from the GitHub PR (ty-meador/civ-v-linux-mcp#1)
  and smoke-tested live t52-t53 (CHANGELOG 1.6.0; the record with save, versions and digests is at the top of
  `docs/GAPS.md`). One fix came out of the smoke: the game's Lua prints chunk names verbatim, so the installer now
  names chunks by their bare file name (runtime v242, `542bd5a`) and an error reads `turn.lua:379:` in the game.
- The game holds the hotseat at t53 (quick-saved), seat 0's turn open with nothing to decide: Venice builds a
  Caravan (8 turns; the Library finished t53), research Trapping (3 turns), orders 10 and 12 still active
  (pasture at (69,36), mine at (67,37)), note 5 is the smoke's marker. Seat 1 (Mongolia) builds a Caravan too.
  A barbarian archer (4 str, 100 hp) stands at (72,41) next to the 82-hp warrior 40962; a 4-hp barbarian galley
  is at (74,31).
- Restart any MCP server started before `542bd5a` (the Claude Code session server included) before its next
  civ5 call: one built before the merge would look for `harness/lua/runtime.lua`, which no longer exists.
- `scripts/check.sh` needs `luac`; without root, `apt-get download lua5.4 && dpkg -x` into a scratch directory
  and put its `usr/bin` on PATH.
- Open in 1.6.0's wake: #43 (the `finish_turn` reply size).

# Resume here -- 2026-09-27 (latest): #42 runtime split merged onto 1.5.0 (runtime v241); live smoke test still owed

- #42: `harness/lua/runtime.lua` is gone; the runtime is 38 files under `harness/lua/runtime/` (that directory's
  `README.md`: which file owns what, how files share helpers through `H._ns`, how to add one). The load order is
  `MANIFEST` in `harness/runtime_source.py`; `Game.ensure_runtime` ships the assembled text as before and a small
  installer runs each file as its own named chunk, so a Lua error now reads `events.lua:57:`. `H.*`, response
  shapes and the network-command paths are unchanged; `H.install_hooks()` runs from `install.lua`, last. Every
  runtime edit still bumps `RUNTIME_VERSION` (`bootstrap.lua`, now 241: the branch's v226-v240 were numbered in
  parallel with #32's v226-v227; the merge takes the next free number); the digest reloads a forgotten bump. #32's
  `H.order_facts` lives in `assignments.lua`, its `H.resume_moves(pid, skip)` in `movement.lua`.
- Not done, needs the game: the live smoke on a recorded save -- fresh client, inject, read player/city/turn state,
  one legal action, `ensure_runtime(force=True)`, check events/state continuity and hotseat ownership across a
  hand-off (and the LAN check where the setup allows). Record save, version, digest and results in `docs/GAPS.md`
  and tick the issue's checklist. Injection cost is unchanged (same bytes, one extra small chunk for the installer).
- Restart any MCP server started before d14391b before its next civ5 call (it would re-inject v225 from a path
  that no longer exists). `scripts/check.sh` now needs liblua5.4, lupa and luac (`apt install lua5.4`) and
  refuses to run without them; 1000 tests.

# Resume here -- 2026-09-27 (latest): 1.5.0 cut (runtime v227); the Venice/Mongolia hotseat at t52, seat 0 on screen

- Milestone 1.5.0 is done and tagged: #32 conditional orders, #36 closed with the measured turn loop (`docs/NOTES.md`
  top section; ledgers in `docs/measurements/`; `CIV5_CALL_LOG` + `scripts/ledger_report.py` are the instrument).
  Next is milestone 1.6.0: #42 the runtime split.
- The game holds the hotseat at t52 (quick-saved), seat 0's turn open with nothing to decide; the save
  `Venice-Mongolia_0048 orders-validated` is the t48 starting point of both measured runs. Seat 0's notebook
  has orders 10 (Worker 65541, pasture at (69,36)) and 12 (Worker 49155, mine at (67,37)) active, 11 completed;
  notes 1-2 only. Seat 1 was driven by a script during the runs (Library, Masonry, Landed Elite, God of the
  Open Sky).
- `a0b2692` changed `harness/game.py` / `action_lock.py`: restart any MCP server started before it (the Claude
  Code session server included) before its next civ5 call.

# Resume here -- 2026-09-27 (latest): 1.4.0 cut (runtime v225); the Venice/Mongolia hotseat at t42, seat 0 on screen

- Milestone 1.4.0 is done and tagged: #33 assignments, #34 `compare`, used together on one live t42 turn
  (CHANGELOG 1.4.0). Next is milestone 1.5.0 in `docs/ROADMAP.md` order: #32 conditional unit orders, then #36
  tracking.
- The game holds the hotseat reloaded from `codex-grokadile_0042 measure-baseline`, seat 0's turn open,
  runtime v225 injected; no unit was moved, seat 0's notebook has no active assignment (id 5 closed as
  cancelled). Restart any MCP server started before 61cb931 before its next civ5 call.

# Resume here -- 2026-09-27 (latest): #34 comparisons shipped (runtime v225); the Venice/Mongolia hotseat at t42, seat 0 on screen

- #34: `compare(kind=production|research|improvements|trade, ...)`, `GET /compare`; `harness/compare.py` (pure),
  `H.compare_*` in `runtime.lua`. Design and live numbers at the top of `docs/NOTES.md`. Also fixed:
  `purchase_cost` called a Settler Venice can never buy "not enough gold". Milestone 1.4.0's issues (#33, #34)
  are done: next is cutting 1.4.0, then 1.5.0 (#32 conditional orders, #36 tracking).
- S5 and S1 were loaded for the live checks; the hotseat was reloaded from `codex-grokadile_0042
  measure-baseline` afterwards (t42, seat 0 to move, runtime v225 injected). No save in `saves/` changed.
- The Claude Code session server of this session carries v224: restart it before its next civ5 call, or it
  re-injects v224.

# Resume here -- 2026-09-26 (latest): #33 assignments shipped (runtime v224); the Venice/Mongolia hotseat at t42, seat 0 on screen

- #33: `assign` / `assignments` / `amend_assignment` / `close_assignment`, the briefing's `assignments` section;
  `harness/assignments.py` (pure), `H.assignment_facts` (one fog-safe read), storage in `harness/notes.py`.
  Design and live numbers at the top of `docs/NOTES.md`. Next: #34 compact comparisons, then cut 1.4.0.
- Not played live: a real unit loss or upgrade (disbanding on the measurement baseline was declined). The
  first game that upgrades an assigned Warrior should confirm the "upgrade on its last plot" reason.
- The four live test assignments on seat 0's notebook for this game are closed as cancelled; no unit was
  moved. Runtime v224 is injected. The Claude Code session server of this session carries v222 (it was moved
  to seat 0 with `set_seat`): restart it before its next civ5 call.

# Resume here -- 2026-09-26 (latest): 1.3.0 cut (runtime v223); the Venice/Mongolia hotseat at t42, seat 0 on screen

- Milestone 1.3.0 is done and tagged: #35 summary rows, #30 `briefing`, #31 `tactical_view`, checked together on
  one live t42 turn (CHANGELOG 1.3.0 says what each showed). v223 blanks tactical-grid cells beyond `radius`
  (they were drawn although `occupants` / `fog` never counted them).
- Next is milestone 1.4.0 in `docs/ROADMAP.md` order: #33 structured assignments on the notebook, then #34
  compact comparisons (production, improvements, research, trade).
- The game holds the same hotseat, seat 0's turn open, runtime v223 injected (by a `scripts/mcp_session.py`
  server); no unit was moved. The Claude Code session server of the release session carries v222 and was
  moved to seat 0 with `set_seat`: restart it before its next civ5 call, or it re-injects v222.

# Resume here -- 2026-09-26 (latest): #31 tactical view shipped (runtime v222); the Venice/Mongolia hotseat at t42, seat 0 on screen

- #31: `tactical_view(unit_id, radius=2, detail="summary"|"full")`, `GET /tactical_view`; `H.tactical_view` in
  `runtime.lua`, move_unit's pre-send checks now `H.move_refusal` (shared, fog-safe for the view). Design and
  live numbers at the top of `docs/NOTES.md`. Milestone 1.3.0's three issues (#35, #30, #31) are done: next is
  cutting 1.3.0 (version bump, CHANGELOG section, tag), then 1.4.0 (#33 structured assignments, #34 comparisons).
- Not seen live: a river-side unit, a crowded own stack, a melee `attack` neighbour with moves. S1 has all three.
- The game holds the same hotseat (`codex-grokadile_0042 measure-baseline`), seat 0's turn open, runtime v222
  injected; no unit was moved. The MCP server started for the #31 session still carries v221: restart any
  server started before this commit before its next call, or it re-injects v221.

# Resume here -- 2026-09-26 (latest): #30 briefing shipped (runtime v221); the Venice/Mongolia hotseat at t42, seat 0 on screen

- #30: `briefing(since, limit)`, `finish_turn(briefing=true)`, `GET /briefing`; `harness/briefing.py` composes,
  `H.briefing_board` reads threats, camps, the leader trait and the event log with its own cursor. Baseline
  per game and seat in the notebook file. Measurements and design notes at the top of `docs/NOTES.md`.
  Next: #31 the tactical view (the briefing's `threats` rows are distance only; #31 is where odds belong).
- S1 was loaded for the measurements and played t266 -> t267 through `finish_turn(briefing=true)` (Ethiopia's
  remark answered "Very well."); `exit_to_main_menu` saved it as a quicksave. The repo's `saves/` are untouched.
- The game holds the hotseat reloaded again from `Saves/hotseat/codex-grokadile_0042 measure-baseline`, seat 0's
  turn open, runtime v221 injected. A server started before this commit carries v220: restart it first.
- Seen, not fixed: the `finish_turn` answer that stopped on a mid-turn discussion (S1 t266, AI phase) carried
  gate `turn_not_active`, not `discussion`; `discussion()` and `respond_discussion` worked.

# Resume here -- 2026-09-26 (latest): #35 summary level shipped (runtime v220); the Venice/Mongolia hotseat at t42, seat 0 on screen

- #35: `todo_actions(detail="summary"|"normal"|"full", limit)`, v220 `hp` on damaged rows, and the baseline
  table in `docs/NOTES.md` from `scripts/measure_reads.py` (S1 t266 and Venice t42). Next: #30 the compact
  briefing, which renders the 1.2.0 status fields and uses the summary rows; then #31.
- The game holds the hotseat reloaded from `Saves/hotseat/codex-grokadile_0042 measure-baseline` (a quicksave
  copy made before S1 was loaded for the measurements), seat 0's turn open, runtime v220 injected. An MCP
  server started before 7914f48 carries v219 and would re-inject it on its next call: restart servers first.

# Resume here -- 2026-09-26 (latest): 1.2.0 cut (runtime v219); the Venice/Mongolia hotseat at t42, seat 0 on screen

- Milestone 1.2.0 is done: #40 notebook replace guard, #41 turn claim, #39 `alerts`, #37 `todo.ongoing`,
  #38 `expiring_deals` / `expiring_friendships`, on top of v213-v216 (`todo_actions`, one-query screens,
  `gate`, the rule book). CHANGELOG 1.2.0 has each row and where it was checked live.
- Next is milestone 1.3.0 in `docs/ROADMAP.md` order: #35 compact response modes first, and first of all
  its baseline (bytes, client tokens, tuner trips, inspection calls per turn) on an early empire, a
  developed empire (S1) and a hotseat context-recovery case; then #30 briefing, #31 tactical view.
- The game process holds the two-seat hotseat at t42 with seat 0's turn open (seat 1 at happiness 1).

# Resume here -- 2026-09-25 (latest): runtime v214, the loop timed and the screen reads folded into one query; S1 at t272

- The open "where does a late turn go" row is answered: `scripts/play_loop.py --profile` logs, per turn,
  the wall time of every loop phase and every `Game` method's tuner trips (a wrapper on `Civ5.call`
  attributes each trip to the outermost `game.py` frame). S1 t270 before the change: 97 s, 278 trips at
  ~0.35 s each; `turn_state` 8 trips, the popup sweep ~20, both repeated on every `wait_for_my_turn`
  poll, `end_turn` 93 trips. The "15 min" in the older notes below was never reproduced.
- v214: `H.CONTEXT_PATHS` / `H.screen_up` / `H.modal_flags` in `runtime.lua` read every popup context's
  `IsHidden()` from InGame by control path; `H.turn_state` carries the five flags plus `trade_state`
  (popped into `Game._trade_state`); `Game._screens()` is the one read behind `_modal_flags`,
  `leader_greeting_pending`, `discussion_pending`, `tech_popup_pending`, `_trade_up`, `_discussion_up`,
  `_leader_up`, `discussion()`; `dismiss_pending_popups(ts)`, `_drop_stale_popup_records(ts, up)` and
  `_process_orphaned_popups(handlers, ts, sc)` take what the caller already read. `_visible_in_state`
  stays for the rare choosers (Maya, archaeology, free item, faith GP).
- Path gotchas, verified live t271: children of the `BulkUI` container answer as `/InGame/<ID>`, and a
  `/InGame/BulkUI/<anything>` path answers with BulkUI itself (visible) -- the first probe read every
  popup as "up" that way. `LeaderHeadRoot` is `/LeaderHeadRoot` (engine-mounted at the root), its
  dialogs `/LeaderHeadRoot/DiscussionDialog` and `/LeaderHeadRoot/DiploTrade`; `SimpleDiploTrade` is
  `/InGame/WorldView/DiploCorner/SimpleDiplo`; `TechPopup` is
  `/InGame/WorldView/InfoCorner/TechPanel/TechPopup`; the ID differs from the file for
  `GreatWorkPopup` (`GreatWorkSplash`) and `ChooseIdeologyPopup` (`ChooseIdeology`). Stock Lua's own
  `LookUpControl("/InGame/WorldView/InfoCorner")` calls were the hint.
- Live after: `turn_state` 0.37 s / 1 trip, sweep 1 trip, `end_turn` 8 trips; a Lua-raised
  `BUTTONPOPUP_TEXT` showed as `screens.TextPopup = true`, `pending_popups` BUTTONPOPUP_TEXT, `popup_up`
  true, and the sweep closed it (5 trips). t271 with the new runtime: 90 s for a turn with PRODUCTION,
  UNITS and STACKED_UNITS blockers plus Ahmad al-Mansur's approach declined; `unit_mission` 93 trips for
  ~13 orders and the bot's `set_production` candidate walk (70 trips for two cities) are what is left.
- Game: S1 (solo Shoshone, Pocatello, seat 0) is at t272 after the two profiled turns; `end_turn`
  quicksaved each. The repo's `saves/` files are untouched. The Claude Code session's MCP server still
  runs runtime v213 (it re-injects v214 on its next call, ~50 s; use a long timeout).

# Resume here -- 2026-09-25 (earlier): 1.1.0 cut (runtime v212); S1 solo Shoshone loaded around t270-t271

- The loop is one call now: `finish_turn` (end_turn + wait_for_my_turn + turn_digest, `skip_quiet_turns`,
  progress every 5 s, default timeout 600 s, verified in Claude Code: a call past 120 s becomes a
  background task and lands when done). `do` runs a list of orders, `action_id` makes any retry a replay,
  `remember`/`recall`/`forget` keep per-game notes, `set_seat` names and changes the seat, and
  `exit_to_main_menu` gets from a loaded game back to where load_save works. All in CHANGELOG 1.1.0.
- An MCP server started before 4f388e9 has none of set_seat / finish_turn / do; Claude Code cannot reload
  its own server without losing the tools for the session, so live checks from such a session go through
  `scripts/mcp_session.py` (fresh stdio server, all tools).
- `todo_actions` (runtime v213) reads the legal actions of every unit on the todo list (plus promotion-ready
  ones) in one call; live S1 t270, 38 units in 0.5 s. Measured on the way: one `available_unit_actions` is
  0.37 s, so the "~15 min in per-unit calls" below was wrong about the cause; the loop's time is unmeasured.
- The game process died overnight (GPU context lost, `logs/civ5.err`) and was relaunched 2026-09-25 late
  with `scripts/launch_civ5.sh main`; the LegalScreen splash needed `UIManager:DequeuePopup(ContextPtr)`
  before `load_latest` (S1 quicksave, t270) worked. tunerd reconnected by itself.
- The game process holds S1 (solo Shoshone, Pocatello) at t270-t271 after the finish_turn / action_id
  live checks; quicksaves are at those turns. The repo's `saves/` files are untouched.

# Resume here -- 2026-09-25 (earlier): 1.0.0 cut (runtime v207); the game now holds S1 played to t269 (solo Shoshone, Pocatello's turn open)

- After the S6 work below, S1 `Pocatello_0266 solo-final` was loaded (copied into `Saves/single/`,
  `Events.ExitToMainMenu()`, `mcp_call --seat 0 load_save`) and `scripts/play_loop.py --seat 0` played
  t266, t267 and t268 unattended: UNITS and PRODUCTION blockers cleared, a leader approach declined, a
  Caravan routed, three Workers automated, no stall, no stale blocker, no orphaned popup. Stopped by hand
  at t269 (each late-game turn takes the loop ~15 min: `available_unit_actions` per unit over 38 units).
  `end_turn` autosaved every turn, so the game's quicksave is t268/t269; the repo's S1 file is untouched.
  Then `v1.0.0` was tagged (pyproject/uv.lock 1.0.0, CHANGELOG, ROADMAP #26/#29). The Persia S6 line's
  live state at t217 (below) was left unsaved past the t215 quicksave; the S6 file stays t214.

# Resume here -- 2026-09-25 (earlier): runtime v207 (Persia "Shah", live t217, Persia's turn open on ENDTURN_BLOCKING_PRODUCTION)

- Loaded: the S6 line played on to t217 while closing GitLab #23. The map is a test bench now: Infantry
  40964 at (35,10), 73736 at (33,7), 81929 at (34,9), 32771 at (27,4) (all fortified, scattered toward
  Zanzibar/Melbourne), the Settlers asleep, culture zeroed by Lua, Tradition open, Freedom chosen, a
  World Congress proposal made, Persepolis building an Aqueduct. Zanzibar (27), Vancouver (29) and
  Melbourne (26) are met; Vilnius 23, Lhasa 24, Bratislava 25, Malacca 28 are not. The named S6 file is
  still t214; the quicksave is t215 (before the experiments).
- #23 root cause, found by meeting a city-state through a unit's own move instead of `Teams:Meet`: the
  engine does not re-evaluate `GetEndTurnBlockingType` while a popup is up. Recipe that reproduces it every
  time: blocker UNITS with one ready unit -> raise any announcement popup (`UI.AddPopup{Type=
  ButtonPopupTypes.BUTTONPOPUP_TEXT, Text=...}` is enough) -> give that unit its order -> blocking stays
  UNITS, `HasReadyUnit()` false, todo empty, until the popup is processed. Contact with a city-state needs
  its *city* (not its territory) in sight: `Plot:CanSeePlot(cityPlot, team, 2, -1)` tells which tiles do;
  hills and forest block it, a river crossing eats the rest of the move.
- v207: `turn_status.blocking_stale` + `popup_up`, the stale hint, `end_turn` refusing on the popup, and
  `Game._process_orphaned_popups` (a popup the engine waits on with no screen drawn gets its Processed
  event + DequeuePopup, announcement types only). The orphan path is unit-tested, not live-exercised: an
  `AddPopup` greeting hidden with `SetHide(true)` was not "up" for the engine any more.
- Gotchas met: every edit to `runtime.lua` makes the next `Game` call re-inject the whole runtime (~70 s
  through the tuner); a 30 s client timeout kills it half-way and every later call restarts it, which
  looks like the game hanging (`ping` connected, `exec` fine, `query` never answers). Use a long timeout
  on the first call after an edit. A fresh `mcp_session.py` server sweeps announcement popups on its
  first tool call, so a popup under test must be driven from one long-lived `Game` object (like
  `finish_turn.py`). `SetActivityType`, `GetLengthMissionQueue`, `GetMissionTimer` are not in this Lua
  build; `Plot:SetRevealed(team, true, -1)` (third argument numeric).

# Resume here -- 2026-09-25 (earlier): runtime v206 (Persia one-human hotseat "Shah", live t214, Persia's turn open, at war with England)

- Loaded: a new hotseat hosted for GitLab #21 the same way as the Venice one (`host_hotseat(human_seats=[0],
  world_size="WORLDSIZE_DUEL", launch=False)`, then `PreGame.SetCivilization(0, CIVILIZATION_PERSIA)`, ERA_POSTMODERN,
  GAMESPEED_QUICK in the StagingRoom, `LaunchGame()`). Seat 0 Persia (nick Shah) vs England AI, t214, Atomic start (3 Settlers,
  5 Infantry, 2 Workers, no city yet). Lua gave `Players[0]:ChangeGoldenAgeTurns(10)`, spawned two English Warriors at (29,12)
  and (29,11), `Teams[0]:Meet(1, false)`, `Teams[0]:DeclareWar(1)`. Through `mcp_session.py --seat 0`: `available_unit_actions`
  on Infantry 32771 / 40964 listed the Warriors as attack_targets with "Golden Age Bonus +10" in `preview.modifiers.mine`
  (70 -> 77, 84 with flanking); the row vanished with the golden age removed and came back when restored. #21 closed;
  0.5.0 now has only #23 open. Save S6 `Shah_0214 golden-age` (repo `saves/` and the game's `hotseat/`; the golden age is on).
- Crash on the way: the first attempt spawned the enemy as a barbarian (`Players[63]:InitUnit`) and Civ5XP died at once --
  the barbarian player is not alive in a fresh game (`IsEverAlive` false). Relaunch: `scripts/launch_civ5.sh main` with Steam
  still up; tunerd reconnected by itself (48 states) but the front end sat on the LegalScreen splash (`status` said
  screen "?"): `c.exec("LegalScreen", "UIManager:DequeuePopup(ContextPtr)")` and the MainMenu showed.
- #23, third attempt, did not reproduce: after the S6 save, `Teams[0]:Meet(22, false)` (Samarkand) put the
  CityStateGreeting popup (type 61, data1 22, gold 30) in `pending_popups` with ENDTURN_BLOCKING_UNITS and 10 units in todo;
  `scripts/finish_turn.py --seat 0` cleared UNITS -> PRODUCTION -> RESEARCH -> UNITS in four passes and ended t214. The live
  game is now at t215 (Persia has a city, 7 idle units, BUTTONPOPUP_LEAGUE_SPLASH pending); the S6 file stays at t214.
- The Doge game (S5 line) was quick-saved at t216 before leaving it (`Saves/single/quick/` was then overwritten by S6's
  quicksave; `Doge_0215 venice-puppet` is the named copy). The Alpha/Bravo line is still at t239 past S4, unsaved.

# Resume here -- 2026-09-25 (later): runtime v206 (Venice one-human hotseat "Doge", live t216, Venice's turn open)

- Loaded: a new hotseat hosted for GitLab #15: seat 0 Venice (nick Doge), Carthage AI, Duel / Quick /
  ERA_POSTMODERN, started t214. Hosted with `host_hotseat(human_seats=[0], world_size="WORLDSIZE_DUEL",
  launch=False)`, then in the StagingRoom state `PreGame.SetCivilization(0, GameInfo.Civilizations.CIVILIZATION_VENICE.ID)`,
  `PreGame.SetEra(GameInfo.Eras.ERA_POSTMODERN.ID)`, `PreGame.SetGameSpeed(...)`, `Network.BroadcastPlayerInfo()`,
  `LaunchGame()`, `_save_rejoin`, `wait_ingame`, `_dismiss_load_screen`. Venice founded at (5,13); Wittenberg (10,8)
  met through `Teams[0]:Meet(team, false)`, Merchant 8192 teleported beside it with `SetXY` and bought it at t215;
  Monument purchased in the puppet; Patronage unlocked; the turn still blocks on ENDTURN_BLOCKING_POLICY with
  seven idle units. Save S5 `Doge_0215 venice-puppet` (before Patronage). An Atomic start gives Venice three
  Merchants of Venice for free. Then (v206) `finish_turn --seat 0` adopted Oligarchy and Legalism, chose Freedom
  and ended t215; t216 opens on ENDTURN_BLOCKING_PRODUCTION (Venice's queue). Buenos Aires is met too.
- Play loop lessons from this game: `resolve_policy` now reads `available_policies` (its static lists were
  useless for an Atomic start's free policies) and there is a `resolve_ideology` handler; an already-open
  branch is refused by `unlock_policy_branch` since v206.
- The Alpha/Bravo line was left at t239 right after the ideology switch, unsaved past S4 (the pre-switch save).
- #23: the CityStateGreeting popup (type 61, data1 23) sat in `pending_popups` beside ENDTURN_BLOCKING_POLICY and a
  full todo; after a fresh server injected v205 it was gone unanswered. The empty-todo ENDTURN_BLOCKING_UNITS case
  did not appear. Still open in 0.5.0: #23 only.

# Resume here -- 2026-09-25: runtime v204 (Alpha vs Bravo, live t239, Alpha's turn open, at war, Alpha in anarchy)

- Loaded: the S2b line one turn on. Bravo declared war on Alpha at t237 (Lua `Teams[1]:DeclareWar(0)`) and holds
  a captured Alpha Worker; at t238 Bravo's eight spawned Great Musicians toured Alpha's land (536 influence,
  Popular), and at t239 Alpha switched Autocracy -> Order through `change_ideology` (GitLab #13 closed live).
  Alpha is in anarchy for 2 turns; the turn is blocked on ENDTURN_BLOCKING_LEAGUE_CALL_FOR_VOTES plus 10 idle
  units. Saved before the switch as S4 `Alpha-Bravo_0239 ideology-pressure` (repo `saves/` and the game's `hotseat/`).
- Manufacturing ideological pressure: `Players[1]:InitUnit(GameInfoTypes.UNIT_MUSICIAN, x, y)` on a tile the
  target owns (works during the other seat's turn); each blast is `max(10 * tourism, 100) * speed%` = 67 at Quick
  with zero tourism, so count blasts against the target's `GetJONSCultureEverGenerated` (Exotic 10%, Familiar 30%,
  Popular 60%). `Unit:CanStartMission(m, -1, -1, plot)` takes four arguments in this build (a fifth boolean errors);
  `Unit:CanBlastTourism` does not exist. Public opinion recomputes at the target's next turn start and again the
  instant the switch lands.
- Still open in 0.5.0: #15 needs a Venice human seat; #23 needs the empty-todo CityStateGreeting state.

# Resume here -- 2026-09-24: runtime v191 (Alpha vs Bravo, live t230, Alpha's turn open, at peace)

- Same two-human hotseat as below (seat 0 Alpha/Korea, seat 1 Bravo/Austria). Quicksaved at t230 with
  Alpha's turn open. The map now has ~20 barbarian units spawned for tests around Seoul/Busan (AA guns
  at (8,13), (2,11), (6,6), (6,15) with Infantry beside each, more near (10,15), (30,8), (32,5)) and
  four barbarian-held Workers; Alpha has two surviving damaged Bombers in Seoul (13 hp, 10 hp) and one at
  1 hp. Clean them up with `Unit:Kill(false, -1)` through `harness.cli lua` before a "real" game, or
  reload `Saves/hotseat/Alpha-Bravo_0227 peace.Civ5Save`.
- Closed this session, all validated live through `scripts/mcp_session.py`: `attack.intercepted` /
  `interceptor` / `shot_down` on an air strike (read from GetInterceptorCount before/after, not from a
  banner -- the engine prints none for a strike); previews clamped to the health bar with
  `my_unit_would_die` / `target_would_die`; `unit_captured` in the digest naming the Worker, its tile, the
  nearest revealed camp and a hint (roster-based: the destroy event fires after the unit is gone);
  hotseat `turn_end` filed for the seat that ended (GetActivePlayer already says the next seat), hp
  snapshots per seat, a human seat's loss during the barbarian phase filed for that seat.
- Things learned about the engine: `GetAirStrikeDefenseDamage` leaves the attacker at 1 hp (a 25 hp
  Bomber came back with 1), interception can kill; an AA gun intercepts once per turn and then drops out
  of `GetInterceptorCount`; `Unit:GetBestInterceptor(plot, defender, false, true)` exists and returns
  the unit that will fire (also for fogged interceptors -- the runtime only names a visible one);
  `IsOutOfInterceptions` / `GetInterceptionDamage` are not in this Lua build. `Unit:PushMission(SLEEP)`
  from raw Lua does not take (activity stayed AWAKE); `unit_mission MISSION_SLEEP` through the harness
  does, but `finish_turn.py` still automates a sleeping Worker.
- `finish_turn.py` gave up twice on ENDTURN_BLOCKING_UNITS with `todo.units` empty and no ready unit;
  a fresh `mcp_session end_turn` then ended the turn at once (blocking_before -1). Both times a
  CityStateGreetingPopup (type 61) was in H.popups for the seat. Not diagnosed further.
- Test command: `PYTHONPATH=. .venv/bin/python -m unittest discover -s tests` (391 passing; the pytest
  form below needs pytest installed).

# Resume here -- 2026-09-24: two-human hotseat, runtime v187 (Alpha vs Bravo, live t227, at peace)

- The solo Shoshone game is parked: `Saves/single/Pocatello_0266 solo-final.Civ5Save` (its live
  quicksave was `Saves/single/quick/QuickSave.Civ5Save`, not the stale one beside it). The game now
  loaded is a two-human hotseat hosted by the harness: seat 0 "Alpha" (Korea), seat 1 "Bravo"
  (Austria), Duel / Quick / start era ERA_POSTMODERN (Civ5's enum for Atomic; there is no
  ERA_ATOMIC), started t214. Named copy at the peace: `Saves/hotseat/Alpha-Bravo_0227 peace.Civ5Save`;
  the hotseat quicksave also lands in `Saves/single/quick/`.
- Drive a seat with `scripts/mcp_session.py --seat N` (fresh server, newest runtime) and clear a
  seat's bookkeeping with `scripts/finish_turn.py --seat N`; `scripts/play_loop.py --seats 0 1` plays
  both seats unattended. Scenarios are built through `harness.cli lua`: `Player:InitUnit`,
  `Team:SetHasTech`, `Team:Meet`, `Player:ChangeGold`, `ChangeMinorCivFriendshipWithMajor`.
- Validated live this session, all through the MCP surface: war on a human (`war_consequences`,
  `declare_war`), a Worker captured on the move (`captured_unit_id`, "A Worker was captured by Alpha!"
  on the victim's digest), Artillery set-up + bombardment, city strike and melee from the other seat,
  Salzburg taken at 1 hp (`city_capture_options` with unhappiness + warmonger text, puppet -> annex
  -> raze -> unraze), air-strike target page with "Known Enemy Anti-Air Units: 1" and a Bomber lost
  to an AA gun, pillage with moves (31 gold, `improvement_pillaged`), `todo.stacked` cleared by the
  loop's unstacker, Budapest allied and `gift_tile_improvement` bought a Gems mine, and peace between
  humans: `make_peace` opens the table with the treaty, `accept_deal` proposes it (and now closes the
  leftover leader scene), the other seat sees `incoming_deal` (and `todo.incoming_deal`) and
  `accept_deal` ends the war; `current_deals` lists the treaty with turns_left.
- Fixed on the way: v185 standing moves keyed per seat; v186 `relationship` of a human seat has no AI
  approach/opinion; v187 accept/refuse empty the scratch table and the todo names a waiting proposal;
  actions refuse under a leader screen (it freezes the engine loop -- units pushed beneath it stay
  "busy"); stale H.popups records (the Congress splash) are dropped; pillage at 0 moves is refused;
  `gift_tile_improvement` waits for the purchase to land; `leader_greeting_pending` also sees the
  post-proposal "Anything else?" scene the engine flag misses.
- Still open: a barbarian/enemy capture notice does not name the lost unit's id or last plot (Bravo's
  Settler taken by barbarians at t217 was only `unit_destroyed` + the generic notice); an air strike
  lost to interception reads "died attacking", the engine's own words, with no `intercepted` flag;
  air previews report expected_damage_taken above max hp (194 vs a fortified Infantry).
- Test command: `uv run --offline --with pytest python -m pytest -q tests` (376 passing).

# Resume here -- 2026-09-24: the swap, runtime v184 (live t252, turn still open)

- **v184** `move_unit` says when the engine swapped the mover with one of our own units on the
  destination: `swapped_with` {id, type, x, y, moves} plus a note. Live t252 Worker 778244 into
  Goshute traded places with Worker 819222 (now at (45,29), 0 moves).
- Live t252, my turn, `NO_ENDTURN_BLOCKING_TYPE` after research went to Scientific Theory (12t).
  Workers 778244 (46,29, in Goshute), 819222 (45,29), 745484 (47,29), 827421 (46,30) are all idle
  and unautomated; the play loop skips them each turn -- AUTOMATE_BUILD would be the human's
  choice. Gold ~250, six trade routes (Goshute->Moson Kahni production, Moson Kahni->Addis Ababa,
  a Caravan to Adwa). Metallurgy and Architecture were stolen. The turn was not ended.
  Do not unload this save. Never call `Plot:MovementCost`.
- A stale MCP server (started before a runtime bump) re-injects its own older text on every call;
  verify new runtimes through `scripts/mcp_call.py --seat 0 <tool> '{json}'` (fresh server), never
  while the play loop is running (the tuner is busy during AI turns and the call times out).
- `todo.stacked` (v183) still has regression coverage only: moving onto an own unit swaps, it does
  not stack, so a live stack needs a city to spawn a unit under a civilian.
- Test command: `uv run --offline --with pytest python -m pytest -q tests` (355 passing).

# Resume here -- 2026-09-23: the stacked tile, runtime v183 (play loop ran t242 onward)

- **v183** `turn_status.todo.stacked`: the tile(s) behind ENDTURN_BLOCKING_STACKED_UNITS with the
  units on them (id, type, moves) by class. `scripts/play_loop.py` gained `resolve_steal_tech`
  (dearest tech from each victim), `ensure_trade_routes` (a finished Caravan / Cargo Ship takes the
  row with the most gold, else the most food or production delivered), and its unstacker now tries
  every walkable unit on the tile, skipping trade units and aircraft.
- Live: t242 stole Architecture from Ethiopia; Goshute built a Caravan that stacked on a Worker in
  the city and the old loop stalled eleven attempts (the Caravan was the only unit it tried). Routed
  it to Moson Kahni (production 5) by hand, then the fixed loop routed the next one to Adwa (13 gold)
  on its own. Research went to Economics. The loop declines every AI trade approach on principle.
- While the loop runs, `scripts/mcp_call.py` and `harness.cli lua` time out during AI turns (the
  tuner is busy); verify runtimes between loop runs, not during.
- Test command: `uv run --offline --with pytest python -m pytest -q tests` (353 passing).

# Resume here -- 2026-09-23: the greyed gift button, runtime v182 (live t241, turn still open)

- Session start: every civ5 tool answered `[Errno 2] No such file or directory` -- tunerd was gone
  (its socket with it) and the game process had been relaunched to the main menu. Fix without
  restarting the MCP server: `nohup .venv/bin/python -m harness.tunerd --port 4318 --sock
  /run/user/1000/civ5-tuner.sock >> logs/tunerd.log &`, then `load_latest` (came back at t241).
- Latest scope is still the information-parity audit in `docs/GAPS.md`.
- **v182** `gift_tile_improvement_options` / `city_state_actions.gift_tile_improvement` `why_not`
  explains a greyed button past allies-only and the price: the ally's revealed resource tiles and
  whether each is improved (`resource_tiles`, `search_radius`), never a resource we have not revealed.
- Live t241: sold 1 Salt to Morocco for 200 gold (32 -> 232); the idle Moson Kahni caravan now runs
  to Addis Ababa (18.35 gpt, 30 turns; 3 routes active, 2 slots free, no trade units). Sidon is
  already our ally (85 influence), but the button stays grey: its Wine plantation, Bison camp, and an
  Aluminum mine we have not revealed are all improved. `gift_tile_improvement` refuses with that
  sentence. The turn was not ended. Do not unload this save. Never call `Plot:MovementCost`.
- Still next: the write itself needs an ally with an unimproved resource tile (Lhasa and Wittenberg
  are at 0 influence; 1000 gold would ally one); then the war-only gaps (peace with terms, a captured
  civilian, interception) on a second hotseat, not by unloading this save.
- Test command: `uv run --offline --with pytest python -m pytest -q tests` (352 passing).

# Resume here -- 2026-09-22: the trade route hover, runtime v181 (live t241, turn still open)

- Latest scope is still the information-parity audit in `docs/GAPS.md`.
- **v181** `trade_routes` and `available_trade_routes` carry the Trade Route Overview's religion
  columns and the gold/science hover. `from_religion` / `from_pressure` are the left arrow,
  `to_religion` / `to_pressure` the right, omitted when the cell is blank. `details` is the hover
  (`BuildTradeRouteToolTipString`): base gold, both cities' gold, only the nonzero bonuses, then
  the science paragraph. A route with no international gold has no hover.
- Live t241, nothing ordered. All 7 routes matched the stock tooltip. Moson Kahni to Adwa is
  Eastern Orthodoxy +6 coming back and Tengriism +9 going out; Te-Moak to Addis Ababa is
  Orthodoxy +12 / Tengriism +9. Addis Ababa to Agaidika and to Tiwanaku have blank religion cells.
  The call for proposals is already answered (we proposed World Religion: Tengriism);
  `NO_ENDTURN_BLOCKING_TYPE`. The turn was not ended. Do not unload this save.
  Never call `Plot:MovementCost`.
- Still next: ally Sidon (250g) and press `gift_tile_improvement` live; then the war-only gaps
  (peace with terms, a captured civilian, interception) on a second hotseat, not by unloading this save.
- Test command: `uv run --offline --with pytest python -m pytest -q tests` (349 passing).

# Resume here -- 2026-09-22: World Congress names, runtime v180 (live t241, turn still open)

- Latest scope is still the information-parity audit in `docs/GAPS.md`.
- **v180** `league_status` `name` is the resolution button with the choice's icon tag removed.
  `GetResolutionName` returns "World Religion: [ICON_RELIGION_TENGRIISM] Tengriism"; the screen draws
  the icon, so the harness says "World Religion: Tengriism". Same cleanup the tooltips already had.
- Live t241, nothing ordered this pass. The call for proposals is already answered: we proposed
  World Religion (Tengriism), `remaining_proposals` is 0, and `turn_status` is
  `NO_ENDTURN_BLOCKING_TYPE` (no unit still needs an order). Arts Funding is in effect and is not
  repealable while the proposal slot is spent. The turn was not ended. Do not unload this save.
  Never call `Plot:MovementCost`.
- Still next: ally Sidon (250g) and press `gift_tile_improvement` live; the trade-route overview's
  religion columns and gold/science hover are not on `trade_routes` yet; then the war-only gaps
  (peace with terms, a captured civilian, interception) on a second hotseat, not by unloading this save.
- Test command: `uv run --offline --with pytest python -m pytest -q tests` (347 passing).

# Resume here -- 2026-09-22: the resource list and the tile hover, runtime v179 (live t241, turn still open)

- Latest scope is still the information-parity audit in `docs/GAPS.md`.
- **v179** `overview.bonus_resources` is the resource list's bonus stack (Wheat, Cattle, and the rest):
  a row only when the empire's total is above zero or some is exported. A revealed strategic now
  carries `used` when that column would print. A resource tile, fogged or not, carries the hover:
  `resource_happiness`, `resource_improved_yields` (when improved and worked, not the tile's current
  yields), and `resource_help`.
- Live t241, nothing ordered. Bonus stack: Bison 1, Cow 2, Deer 1, Sheep 1, Stone 2.
  Horses 18 spare of 19, 1 used, 1 imported. A Horse tile's hover is "Used by Mounted Units" and
  +1 production when improved; fogged Incense/Silk/Cotton are +4 happiness and +2 gold, with no
  current yields. Iron's hover is "Used by powerful early-game Units" and +1 production.
  Turn still open on `ENDTURN_BLOCKING_LEAGUE_CALL_FOR_PROPOSALS`. Do not unload this save.
  Never call `Plot:MovementCost`.
- Still next, in order: answer the World Congress (`league_status`, then enact or repeal) and move the
  Keshik; ally Sidon (250g) and press `gift_tile_improvement` live; then the war-only gaps (peace with
  terms, a captured civilian, interception) on a second hotseat, not by unloading this save.
- Test command: `uv run --offline --with pytest python -m pytest -q tests` (347 passing).

# Resume here -- 2026-09-22: the Happiness screen's rows, runtime v178 (live t241, turn still open)

- Latest scope is still the information-parity audit in `docs/GAPS.md`.
- **v178** `overview.happiness_breakdown` now has the rows the Happiness screen expands, not only the
  top-bar totals. `happiness.by_luxury` is each luxury's happiness. `league` and `difficulty` are the
  two lines the old buckets skipped (`difficulty` is the screen's residual, so garrison happiness sits
  in it). `cities` is building happiness, local happiness, connection happiness, unhappiness, and
  occupied; a zero the screen prints as a dash is left out. `unhappiness.tooltips` is the hover on
  Number of Cities and Citizens. `unhappy` / `penalties` are the red sentences when the empire is
  unhappy, very unhappy, or in revolt.
- Live t241, nothing ordered: 8 luxuries at 4 (32), difficulty 9, local happiness 37, connection 7,
  eight cities, citizens 59, citizen hover "-5% the usual amount". Cusco is not occupied. 341 tests.
  Turn still open on `ENDTURN_BLOCKING_LEAGUE_CALL_FOR_PROPOSALS`. Do not unload this save. Never call
  `Plot:MovementCost`.
- Still next, in order: answer the World Congress (`league_status`, then enact or repeal) and move the
  Keshik; ally Sidon (250g) and press `gift_tile_improvement` live; then the war-only gaps (peace with
  terms, a captured civilian, interception) on a second hotseat, not by unloading this save.
- Test command: `uv run --offline --with pytest python -m pytest -q tests` (341 passing).

# Resume here -- 2026-09-22: the tech tree's buttons, runtime v177 (live t241, turn still open)

- Latest scope is still the information-parity audit in `docs/GAPS.md`.
- **v177** `unlocks` on `tech_tree` and `available_research`: the icons on a tech button, for this
  civilization. A class default is replaced by our unique, so the Shoshone see Comanche Riders rather
  than Cavalry, and do not see England's Ship of the Line or Portugal's Feitoria. Unit buttons carry
  cost, moves, range, strengths, resources, and the written help (`GetHelpTextForUnit` is not in this
  Lua state). Ability icons use the same text keys as the screen (embark, cross oceans, embassy, an
  extra trade route, the World Congress). The help paragraph drops color and icon tags.
- Live t241, nothing ordered: Navigation (current) was Frigate (185 / str 25 / rng 28 / range 2 /
  moves 5 / 1 Iron), Privateer, Seaport. 298 tests. Turn still open on
  `ENDTURN_BLOCKING_LEAGUE_CALL_FOR_PROPOSALS`. Do not unload this save. Never call `Plot:MovementCost`.
- Still next, in order: answer the World Congress (`league_status`, then enact or repeal) and move the
  Keshik; ally Sidon (250g) and press `gift_tile_improvement` live; then the war-only gaps (peace with
  terms, a captured civilian, interception) on a second hotseat, not by unloading this save.
- Test command: `uv run --offline --with pytest python -m pytest -q tests` (298 passing).

# Resume here -- 2026-09-21: the screens before the decision, runtime v169 (live t221-t222)

- Latest scope is still the information-parity audit in `docs/GAPS.md`.
- User requirement: **launch Civ V through the harness and test changes live**; offline regression tests alone
  are not sufficient. `scripts/launch_civ5.sh civ5`, wait for the main menu (several minutes -- the tuner port
  opens long before the Lua states do), then MCP `load_latest`.
- **Never call `Plot:MovementCost`**: it crashes the process even inside pcall.
- Save is **Shoshone t241** (Pocatello), loaded by `load_latest` this session -- newer than the t233
  note below. Our turn is open. `turn_status` blocks on `ENDTURN_BLOCKING_LEAGUE_CALL_FOR_PROPOSALS`
  (one Keshik still needs orders). No proposal was made and the turn was not ended. Civ5 and tunerd
  are running.
- Four runtime versions this session, each live-verified before commit:
  - **v165** `gift_tile_improvement_options` / `gift_tile_improvement` (the city-state screen's last closed
    write). A greyed button lists no plots and says why; an open one lists exactly the hexes stock would
    highlight. **The write has no live coverage yet: it needs an ally.** Sidon is the cheapest at 55 more
    influence -- a 1000-gold large gift makes it in one step.
  - **v167** `H.action_help`: the unit-action button's sentence on every action, nearby-build and
    interface-mode row, plus stock's computed cases (upgrade/scrap/golden age/paradrop/no-fortify).
  - **v168** an empty `available_trade_routes` says why, and `idle_trade_units` says which caravans could
    actually take a route.
  - **v169** `available_production` rows carry the chooser `name` (BUILDING_THEATRE is "Zoo").
  - **v170** `city_state_gifts` tiers say whether the gift actually takes the alliance (`makes_ally` /
    `short_by`), after a 1000-gold gift to Sidon landed 4 Influence under Ethiopia at t231.
  - **v171** `unit_home_options`: the Change Home City / Change Port choosers for trade units and Great
    Admirals, which had no harness equivalent at all.
  - **v172** a finished build says what it changed: the improvement, the tiles a Citadel claimed and who
    lost them, and whether the Great Person was expended. Live t233 on the Ethiopian border.
  - **v173** `notification_log`: the log screen, including already-dismissed entries (99 held live).
  - **v174** `city_screen.meters`: the city screen's food, production and culture-to-border meters,
    fractional gold/science, and the red price of a tile this city cannot afford. Live t241 Moson
    Kahni: culture 137/225 (8 turns), food 66/139 (+6, 13 turns), Wealth at 33 production/turn with
    no cost, gold 44.56, science 48.92, two unaffordable tiles. Matched the stock getters.
  - **v175** League projects. `league_status.projects` and `available_production`'s `league_project`
    on the process row. Live t241 World's Fair is active and Moson Kahni can build it: 0% of 2100
    production, 0 contributed, 350 per civ, bronze at 175, silver at 350. The details string matched
    `GetProjectDetails`. Other civs' contributions are withheld until the completion popup. Wealth
    and Research process rows now carry their Help text. 295 tests. Runtime injected into the
    already-loaded game; the turn was not ended and no proposal was made.
  - **v176** League Overview text. `details` on proposable, repealable, pending, and votable rows;
    `unavailable_enact` for the greyed ones; `active_resolutions`; `active_effects`; met members'
    delegate hover. Live t241, proposal still unmade (1 remaining): effects were host Morocco,
    World's Fair, and Arts Funding's +33%/−33% great-person rates. Arts Funding is the one repeal.
    10 enact options (embargo, ban luxury, world religion, sciences funding, …) and 8 greyed
    (World Leader, World's Fair, ISS, …). Morocco 11 delegates, everyone else 3. 296 tests.
  - **tuner.query** had not run any Lua since v158 (the `execute` call was dropped when the wrapper
    was extracted). A new tunerd answered `NameError: name 'res' is not defined`. Fixed; the
    running tunerd was restarted against the already-loaded game and the port accepted it.
- Treasury note: t231 left us at 3 gold. Sidon is 4 Influence short of ours, so the *250-gold* tier now
  takes the alliance (`makes_ally: true` on all three tiers) -- then `gift_tile_improvement` costs 200 more.
- Next, in order: answer the World Congress call for proposals (`league_status`, then enact or
  repeal) and move the Keshik, without ending the turn until that is a decision; ally Sidon (250g)
  and press `gift_tile_improvement` live; then the war-only gaps that a second hotseat instance
  would unlock (peace with terms, a second capture, razing, annexing, interception).
- `scripts/play_loop.py` now asks `available_research` before its hardcoded tech ladder; it stalled at t232
  because every tech on that ladder was long since researched.
- Test command: `uv run --offline --with pytest python -m pytest -q tests` (295 passing).

# Resume here — 2026-09-20: information-parity audit, runtime v151 (live t183)

- Latest scope is the information-parity audit in `docs/GAPS.md`; older play handoffs below are historical.
- User requirement: **launch Civ V through the harness and test changes live**; offline regression tests alone
  are not sufficient. Use `scripts/launch_civ5.sh civ5`, then MCP `load_latest` when recovering this save.
- **Never call `Plot:MovementCost`**: it crashes the process even inside pcall.
- v151 adds the panel's itemised combat-modifier rows: `H.combat_modifiers` / `H.city_strike_modifiers` port
  all 131 rows of `UpdateCombatOddsUnitVsUnit` / `UnitVsCity` / `CityVsUnit` and attach to every melee, ranged
  and city-strike preview as `modifiers.mine` / `modifiers.theirs` (`{text, value, percent, key}`; the panel's
  value-less warnings/notes carry no value). It also fixes `available_city_strikes`, which capped at the
  target's remaining hp instead of the panel's maximum hp, and now reports both strengths. 157 regressions
  pass. **Live t182: 1008/1008 comparisons against the real `EnemyUnitPanel` matched**, over 12 own units x 28
  visible targets and 7 own cities x 24 visible units; 12 distinct row types appeared live (details in
  GAPS.md / NOTES.md; full results in the ignored `logs/combat_modifiers_v151_live.json`).
  The verification probe hooks the shared `InstanceManager.GetInstance`, because the panel's two instance
  managers are file-locals; it hands the panel recording proxies so no real control is touched.
- **Seat is now on t183 (1230 AD), no blocker.** Turn 182 was played: the standing gold crisis is over.
  Disbanded five obsolete unupgradeable units (2 Catapults 188428/270350, Composite Bowman 221199, Swordsman
  245778, Horseman 262161) — **gpt −11 → +1, treasury 0 → 54, science 44 → 55** (the `budget_deficit` that was
  eating 11 science is gone). Queued a Caravan behind the capital's National College for the one free trade
  slot. t183: gold 59 / +5 gpt (Machu's city connection completed), science 55, happiness 2, faith 402/500,
  Steel 7t, 19 units of 37 supply.
- Next: live nonzero fire support / interceptors, a nonempty legal air-strike target page, and live examples of
  the modifier rows that only have regression coverage (they need war, barbarians, a golden age or specific
  promotions). Peace-with-terms remains closed after the native `AddPeaceTreaty` crash. CS tile-improvement
  gift write is still open. Full inventory: `docs/GAPS.md`.
- Test command: `uv run --offline --with pytest python -m pytest -q tests`.

# Historical handoff — 2026-09-20: runtime v150 (live t182)

- Latest scope is the information-parity audit in `docs/GAPS.md`; older play handoffs below are historical.
- User requirement: **launch Civ V through the harness and test changes live**; offline regression tests alone
  are not sufficient. Use `scripts/launch_civ5.sh civ5`, then MCP `load_latest` when recovering this save.
- Last recorded live save is **Shoshone t182**, recovered after the t183 MovementCost probe crash.
  Gold 0 / −11 gpt, science 44, happiness 2, Lhasa friendship influence 46. See GAPS.md for worker jobs.
  **Never call `Plot:MovementCost`**: it crashes the process even inside pcall. No turn was advanced this session.
- v149 adds ranged combat strengths, air-strike retaliation plus visible interceptor counts/warnings,
  and previews on air-strike `unit_mission_targets` pages. 134 regressions pass. **Live t182:** 13 preview
  comparisons match the stock `EnemyUnitPanel` damage and strength controls exactly (bomber/fighter/bow;
  city, pikeman, crossbowman, worker, warrior). Peaceful visible targets use the same reads as Alt-hover.
  Bomber's MCP target list correctly returns empty while at peace. No war declared or turn advanced.
- v150 adds melee fire-support damage (both its reduction of outgoing damage and addition to incoming damage)
  plus the stock panel's maximum-HP caps for unit/city melee previews. 139 regressions pass. **Live t182:**
  all 115 comparisons against the stock panel matched damage and strengths (5 owned melee units × 23 visible
  targets; 95 unit / 20 city comparisons). 27 outgoing unit estimates hit the 100-HP cap. All fire-support reads
  were zero; nonzero support has regression coverage but still needs a live example. No gameplay changes.
- Next: individual combat modifier rows; live nonzero fire support / interceptors and a nonempty legal air-strike
  target page when an enemy is available. Peace-with-terms remains closed after the native `AddPeaceTreaty`
  crash. Full current inventory: `docs/GAPS.md`.
- Test command: `uv run --offline --with pytest python -m pytest -q tests`.

# Historical handoff — 2026-09-19 (twenty-third session, later still): Shoshone t150, runtime v136

- Took Machu (t119, puppet) and got Tiwanaku ceded in the t128 peace; peace expired t139. Happiness -6, gold
  -8/turn is the pressing problem (Guilds researching for trading posts). Cusco (Inca capital) not yet located.
- Harness t101-t150: see NOTES.md "t101-t150". v136 city-assault fix still unexercised.

# Resume here — 2026-09-19 (twenty-third session, later): Shoshone t100, runtime v134

- Game: 5 cities, Tengriism (Church Property + Pagodas), Liberty done. Science ~29, gold ~+15, happiness about 0.
  Continent is full; next step is the war on the Inca: Machu (47,10) north of Agaidika. Army staged near Agaidika:
  2 Catapults, Composite Bowman (city), Archer, Great General; capital building a Composite Bowman, Swordsmen once
  the Iron mine (50,17) yields iron. Check war_consequences(2) first; still verify city_capture_options on a capture.
- Harness v130-v134 fixes: see NOTES.md "t34-t100". Tests: `PYTHONPATH=. uv run --with pytest pytest -q tests`.
- Open: #2 peace terms (coverage audit), "move then build" convenience.

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
  `civ5-tunerd`. Full how-to: `docs/DECK_HOWTO.md`; LLM-player playbook: `docs/PLAYBOOK.md`.
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
