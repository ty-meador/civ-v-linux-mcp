# Resume here -- 2026-10-08 (night): 1.13.0 TAGGED (runtime v266, 145 tools, 1469 tests); GROK'S ENGLAND GAME is the live game, at t127 after Claude took the seat at t118 and made peace; the Venice/Mongolia hotseat is over (Russia won t253); Codex's Portugal is at t118 in `single/Codex_as_Portugal`

This file holds the current state only. Earlier "Resume here" sections (57 of them, 2026-09-19 to 2026-10-04)
live in git: `git log -p -- docs/SESSION_HANDOFF.md`. Shipped work is in `CHANGELOG.md`; known gaps are
inventoried in `docs/GAPS.md`.

## Where the game is

- **Grok's England game** (grok-shell-civ5/1.0.41, seat 0, solo, `L7-C5-Assets_Maps_continents-London`): Grok
  played t0-t118 on 2026-10-04 23:24 to 2026-10-05 05:24 (2623 ledger rows in `logs/calls.jsonl`) and stopped
  mid-turn with London alone at 68/250 hp inside a ring of twenty Songhai, Spanish and Portuguese units, at war
  with those three and eleven city-states. `load_latest` picks this game (its quick save is the newest). On
  2026-10-08 Claude took the seat from the session server: white peace with all three on the first ask at t118
  (every allied city-state along), food focus against the starvation, DoF with Spain (t119), open borders with
  Rome / Mongolia / Ottomans / Spain, caravans to Madrid (t121) and York (t125), University building, Chivalry
  researching, the Embargo England proposal defeated at the First Council of Lisbon (t126). Grok's t118 state is
  kept as `single/Grok_as_England_0118 siege` and `saves/Elizabeth_0118 grok-siege` (S8). The notebook's plan
  note (id 1) is current as of t133; assignments 42 (longbow in London) and 43 (scout exploring north of Persia).
  Played on to t133 through the reconnected session server (RA with Persia, Astronomy stolen from the Ottomans,
  a third caravan to Mongolia, Songhai's one-way passage refused, two 201-gold RAs refused as unaffordable).
  The game sits at **t133, my turn, nothing to order** (scout fortified at (65,14)); quick-saved.
- **Codex's Portugal game** (gpt-6.1-sol) is at t118 in `single/Codex_as_Portugal.Civ5Save` (its own quick save
  was overwritten by Grok's game); the arrival fix (a104091) was found on it at t95.
- **The Venice/Mongolia hotseat is finished** (Russia, Science Victory, t253; notes 119-128 in seat 1's notebook).
- **The stack** (2026-10-08 21:09): Steam, Civ5XP (pid 18367), tunerd (pid 19039) on
  `/run/user/1000/civ5-tuner.sock`. The session's MCP server is pid 33028 (started 21:42, before the v266 commit
  at 21:50: which Lua source it injected is not recorded; its t133 reads worked). Memory rule: two servers built
  from different runtime sources re-inject each other into one game -- `/mcp` reconnect the session server
  before using its civ5 tools again.

## Where the code is

- **Tech-debt sweep (2026-10-09, runtime v267, CHANGELOG "Unreleased")**: the `civ5://playbook` MCP resource is
  fixed (it read a path that never existed), dead methods / a dead Lua function / dead page helpers / two stale
  scripts removed, seven more ruff rules on and clean, the suite 63 s. The runtime bump is one deleted Lua
  function: the session's MCP server (pid 5201, started before the bump) must be reconnected (`/mcp`) before a game
  runs, or it re-injects v266 against a v267 server (memory: runtime digest ping-pong). Left alone on purpose:
  the 72 literal `time.sleep(0.x)` screen settles in `game_parts/` (tuned per screen, live), the 145 one-line
  `mcp_tools` wrappers (the docstrings are the tool schema), `_unit_mission` at 180 lines, ARG002/PLC0415 style
  findings. Session 2 (same day, docs only): `docs/COVERAGE_AUDIT_2026-09-19.md` is marked historical with a
  status table (all fourteen ranked gaps have a tool; GAPS points at it), the three `docs/lua_api_*.md` /
  `lua_command_patterns.md` extracts have provenance headers and ARCHITECTURE names them, every backticked repo
  path in the live docs resolves. Also checked and left: `_is_int` twice (a one-liner), the two `J` formatters
  (different on purpose), 21 file-local `H.*` functions, the interrupted-run mkdtemp leak in `test_liveness`.
  Still for the next release cut: the README test count (1469 there, 1475 now). The
  traceback the suite sometimes printed was the spectator server's thread on a client reset between keep-alive
  requests (`ConnectionResetError` out of `handle_one_request`'s readline): fixed with a test (`test_spectator.py`).
- **main = 1.13.0 (e3fcf96) + two commits after it** (CHANGELOG "Unreleased"): the spectator dumps the map again
  when a snapshot's `map_key` is not the hello's `key` (another game loaded under a running spectator; both keys
  read live at t133, `104x64:962744005`), and the scrubber's seek applies the
  latest hello / snapshot / notebook-per-seat before each call and before the target, and every call in order (`Timeline.plan`,
  `web/viz/js/timeline.js`), and `/recording` is parsed off its byte stream a line at a time (`feed.readLines`).
  Measured under node on the 72 MB 2026-09-30 recording: 2.6 s to load, a seek to the end applies 122 rows, not
  1,492. Opened in Chrome on 2026-10-08 22:40 against the replay server: a drag forward to 1:53:52 painted t152
  Venice, a drag back to 43:16 held t152 (the recording's last call is at 0:09:54, so nothing changes between those
  marks) and a drag back to 1:33 rebuilt t151 Mongolia with only the first nine calls and the t151 events in the
  panes; the heap sat at 70-72 MB throughout, no console errors. `scripts/check.sh` green (1472 tests).
- **Canvas migration done, phases 0 to 5 (c5f3084, 903c6cf, 5323cda, accc701, the phase 4 commit, and the switch
  commit of 2026-10-09)**: `docs/CANVAS_MIGRATION.md` is the plan as carried out, with every measurement: the SVG
  baseline and the synthetic side-by-side of 2026-10-08 (104x64 / 128x80 / 200x120 from
  `scripts/synth_recording.py`), and the real-recording side-by-side of 2026-10-09 on the England game's 2026-10-08
  recording (104x64, t133, 752 units) and the 72 MB 2026-09-30 hotseat one (80x52, 1,386 snapshots): the canvas on
  the 16.7 ms frame through every gesture where the SVG spent 44-68 ms a frame, a seat view in 33 ms against 135,
  the rebuild in 30 against 195, the heap the same on both (the recording), the seat view at the fit and at 4x the
  same to the eye, the tip the SVG's title text. The page now has one `<canvas id="map">`; `web/viz/js/map.js` and
  the `?renderer=` switch are gone (a `?renderer=svg` URL simply gets the canvas). To re-measure: a scratch-profile
  Chrome with `--remote-debugging-port=9222 --remote-allow-origins='*'` (the default profile refuses the port), a
  replay server per recording, then `node scripts/viz_bench.mjs measure|heap|shots <url>` (one JSON line a page;
  page errors on stderr; each page in a fresh tab of a 1920x1080 window, so animation frames fire and no
  back/forward-cached page sits in the heap read). The browser extension failed for this on 2026-10-09: the window
  it opened under COSMIC came up 500x37 and `visibilityState` hidden (no frames), `google-chrome
  --no-startup-window` exits at once, and `--window-size` on the launch applies to every window Chrome opens
  after. The replay servers (8781, 8782) and the scratch Chrome were stopped at the end. Not done: a real Huge
  recording (none exists; the synthetic 128x80 stands in); d3 stays, the zoom and the panels use it.
- **1.13.0 tagged 2026-10-08** (runtime v266, 145 tools, 1469 tests): the ten entries since 1.12.0 (the scrubber,
  four 2026-10-04 fixes, the arrival hook a104091, the tuner stream resync c1f4e8d, the headless-deal removal
  5a606d0, v265 and v266). README has a new "It says what a human sees on the leader screen and on the map"
  bullet and the scrubber on the spectator one; ROADMAP carries the release paragraph; AGENT_INSTALL says 1.13.0.
  CHANGELOG has no Unreleased section until the next change adds one.
- **Memory-rule reminders**: the ctx sandbox lacks XDG_RUNTIME_DIR, export
  `CIV5_TUNERD_SOCK=/run/user/1000/civ5-tuner.sock` before any `harness.cli` call there; `pkill -f` in a
  compound Bash call kills the shell; disband is denied to the auto-mode classifier; copy QuickSave to a named
  file before loading another save into a live game.

## Still open

- `unit_displaced` was read live at the t131 start (the General out of London, `shared_with` the Caravan built at
  t130; the event woke the turn). Narrowed at t133: a *route* caravan standing on the city tile at the turn end
  (t132) did not move the General; only an idle trade unit does. Why the engine moves the civilian and not the
  trade unit, and whether a Worker or Settler is moved the same way: not known; the row reports the fact either way.
- The `at_war` warning and `wars` status: coded from the t118 catalog reads (peace gate open with all three);
  England is at peace with everyone now, so a live read needs another war. `explore_frontier.occupied` (v266) is
  likewise unit-tested only; the Ottoman units north of Persia are where to read it. Tried at t133 (2026-10-08
  22:10): the scout at (65,14) sees an Ottoman Cannon at (67,14), but that plot is inside the revealed map, not on
  the frontier (frontier_total 150, nearest rows all tundra at distance 2, none occupied), so no `occupied` row
  yet; the scout would have to walk north-west for one.
- Spectator page: it still holds every parsed row of a recording (fine since the cadence fix; the 72 MB pre-fix
  file was 122 MB of heap under node, 70-72 MB in Chrome). The seek/stream change was seen in Chrome on 2026-10-08
  (forward and backward drags on the 2026-09-30 replay, above); nothing open on it.
- The rest: `docs/GAPS.md`.
