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
- **Canvas migration, phases 0 to 3 (c5f3084, 903c6cf, 5323cda and the commit after it)**: `docs/CANVAS_MIGRATION.md` is
  the plan and carries the SVG baseline measured in Chrome on 2026-10-08 (synthetic recordings from
  `scripts/synth_recording.py --size WxH`, served with `--replay` on ports 8771-8773, since stopped; the files are
  under `logs/synth/`, ignored). The helpers `hex.plotAt` / `visibleRange` / `tracePath` are in and tested.
  `web/viz/js/map_canvas.js` is the canvas renderer behind `?renderer=canvas` (the SVG stays the default): two
  screen-space caches (terrain; fog + borders) over the visible plot window, re-rendered at a zoom gesture's end,
  and a live pass each redraw; seen in Chrome on the 2026-09-30 replay (port 8766, still running) and the 128x80
  synthetic, observer and seat views, a wheel zoom, console clean; a stub-context node test in
  `tests/test_viz_js.py`. Phase 3 is in: the live pass indexes its pieces by plot, `tipAt` names the unit disc or
  the plot under a point, the pointer handler fills `#tip`; probed in Chrome against the SVG titles at the same
  screen points (1x, word for word) and at a 4.6x zoom. Phase 4 is done on the synthetic recordings (the commit
  after accc701): the canvas page measured beside the SVG page under one script on the three sizes, a table in
  the plan; every gesture and the live redraw sit on the 16.7 ms frame at every size, a seat switch paints in
  33 ms, the rebuild in 50 at 200x120, heap below the SVG page's; parity captured at a 3.7x seat view and at the
  fit; a resize refits; console clean. The profile led to `paintHexes` (hexes eight to a path for the fills and
  the opaque edges, 2.5x cheaper; one path for everything is 50x slower in Chrome). Still to do before phase 5:
  the same side-by-side on the live England game (it was not running) and ideally a real Huge recording. Then
  phase 5: default to canvas, delete `map.js` and the flag, drop `svg#map` from the CSS, update VISUALIZATION.md,
  cut a release. When re-measuring: a background Chrome tab never fires animation frames, keep the page in the
  only tab of the automation group; the measurement script is the one in the plan's phase 4 section in spirit
  (view switch timed to the second animation frame, 20 wheel ticks one per frame, Home/End keys).
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
