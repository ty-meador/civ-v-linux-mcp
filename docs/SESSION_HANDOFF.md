# Resume here -- 2026-10-10 (evening): main = 1.14.0 + the frontier cut fix, the refused-attack wording and the unseen-turn hand-back and the queued-building compare row and the upgrade carry-over (runtime v269, 145 tools, 1495 tests; CHANGELOG "Unreleased"); GROK'S ENGLAND GAME is the live game, at t214 (Modern era, Freedom, denounced by every Order civ) after Claude took the seat at t118; the Venice/Mongolia hotseat is over (Russia won t253); Codex's Portugal is at t118 in `single/Codex_as_Portugal`

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
  Played t133-t138 on 2026-10-09 (late): Castle built, East India Company building (4t), Rome's and the
  Ottomans' coop-war requests declined (Songhai, Mongolia), Persia's DoF expired t135 and the renewal was refused
  t136 (ask again ~t146; the engine says "already friends" until the expiry notification), the Mongolia copper
  deal ends t141 (reoffer t142). Notes 1-3 and assignments 42-43 current; order 96 holds the scout fortified at
  (63,14) (the order completed t139). Banking came in at t139 and Physics is researching (5t). Played t139-t150 on 2026-10-09 (late night, through the session server): a Caravan
  bought t139 and two more (one built, one back from Madrid) routed to Tombouctu, Madrid and Gao (five routes,
  +100 gpt in the Golden Age that began t145); the Bank bought t145, Amphitheater built, Oxford University
  building (done t151); Steel in t147, Gunpowder researching; mutual open borders renewed with Mongolia, Rome,
  Spain, Songhai (new) and the Ottomans; copper to Mongolia renewed to t166; DoFs accepted from Portugal (t145)
  and Rome (t147); RAs signed with Rome (t148, 234g) and Portugal (t149, 201g); four coop-war requests declined
  (Spain vs Songhai, Rome vs Germany, Portugal vs Persia, Rome vs Songhai); Persia's DoF still "asked too
  recently" at t146 (its RA boosts t152, its open borders end t153); the Congress votes went to Rome's Pearls
  ban and Portugal's World's Fair (both passed). The scout explores south along x=69-70 under assignment 45.
  Then t150-t170 the same night: Rationalism opened (t150); Oxford built and its free tech was Navigation (t151);
  Caravansary, Garden, Forge (bought), Windmill built, a Musketman (Shock I, fortified on the mine (60,39),
  assignment 46), Zoo building (t168, 3t) for the happiness dip; research Steel -> Gunpowder -> Printing Press ->
  Economics -> Chemistry -> Acoustics (4t from t167), Industrialization stolen from the Ottomans (t160; the Industrial
  era came with it); spy Andrew sent to Rome (t161); RAs: Rome t148 (boost t173), Portugal t149 (t174), Spain t152
  (t177), the Ottomans t158 (t183); DoFs renewed: the Ottomans t163, Spain t169 (Germany's and Assyria's DoF offers
  declined); every open-borders renewal accepted (Persia, Mongolia x2, Songhai, Germany, Assyria), copper renewed
  to Mongolia (t191) and Persia (iron + 5gpt, t180); Congress: Portugal kept the host (our 3 votes), the Songhai
  embargo got our 3 no votes, the city-state embargo passed; coop-war asks declined from Assyria (vs Spain) and Rome
  (vs Persia); Persia refused a DoF again t156 (next ask ~t166+). **Lesson (note 5)**: accepting Songhai's "renewal"
  of a long-ended copper deal at t166 exported our last spare copper and dropped happiness 11 -> 7; read
  `us_available` on a resource renewal first. The scout holds (75,30) fortified inside the Ottoman-Persian war zone
  (assignment 47, review t175); seven caravans on routes (Madrid, Tombouctu, Gao, Karakorum, Lisbon, Seville, York).
  Notes 1-5 current as of t170 (saved as `single/Elizabeth_0170 claude`).
  Played t170-t214 on 2026-10-10 (evening, through the session server, no code change): Wine bought from Rome
  (9gpt + 2 iron, happiness 7 -> 11; the Ottomans refused Gems short of our Marble, Rome asked 28gpt for a second
  luxury); Zoo, Circus Maximus, Writers' Guild, Opera House, National Epic, Hermitage, Stock Exchange,
  Constabulary, Museum, Hospital, Hydro Plant (aluminum from Germany for the spare copper, t202) built, Public
  School bought (t177), Stadium building; two Great Scientists planted Academies at (59,40) and (60,38), two Great
  Writers made Great Works (Amphitheater, Heroic Epic); 2 scientists + 1 writer assigned by hand; research
  Scientific Theory -> Electricity -> Archaeology -> Biology -> Radio -> Metallurgy -> Rifling -> Steam Power ->
  Replaceable Parts, goal TECH_PLASTIC (buy the Research Lab), Refrigeration stolen from the Ottomans (t200);
  Secularism (t186), Humanism (t199), **Freedom** (t200, no free tenets), Universal Healthcare (t213, +9
  happiness); science 133 -> ~250. Diplomacy: every open-borders renewal accepted, RAs re-signed with Rome (t174,
  t200), Portugal (t175, t201), Spain (t178, t204), the Ottomans (t184); Persia's and Songhai's DoF asks declined
  (at war with our friends); Rome's spy-kill promise (t188: never spy on Rome); Portugal's DoF renewed t195,
  Rome's t197; coop-war asks declined from Germany, Mongolia, Portugal (x2), Rome. Congress: Confucianism (our 2
  Yea) failed, Cultural Heritage passed, Persia embargo passed (our Yea), Freedom and Order as World Ideology both
  failed, Copper ban passed (happiness -4), International Games passed, Portugal kept the host twice. **After
  Freedom (t200) the Order bloc denounced us one by one: Germany t205, Rome/Assyria/Songhai t206, Mongolia t207,
  Spain t207, the Ottomans t208** (Rome's and the Ottomans' DoFs broke, their RAs are no longer legal; Rome
  "backed with nuclear weapons", Germany mocks the army; threat note 8). Public opinion costs 7 unhappiness
  (Order preferred, Rome's tourism). Defence bought: Musket -> Rifleman, Longbow -> Gatling Gun, a second Gatling
  Gun (t206); Budapest (friend, 250g gifts t188/t204) sent a Pikeman and a Cannon. Lesson (note 7): Portugal
  re-buys any city-state alliance the same turn (750g lost on Bratislava t190). Persia was eliminated t203, Spain
  t214 (the Spain RA cancelled unpaid). Saves: `single/Elizabeth_0209 denounced-by-all`, `single/Elizabeth_0214
  claude` (= the quick save). Notes 1 (plan, t200), 6 (diplomacy), 7 (lesson), 8 (threat) current; assignments
  42/46 were amended onto the Gatling Gun 671747 and the Rifleman at t214, and the Rifleman was then upgraded to
  Great War Infantry 704524 (135 gold; `upgrade_unit` moved assignment 46 onto it itself, see below). The game sits
  at **t214, my turn, nothing to order**; gold 2526 at
  +130 gpt, happiness 19, six caravans on routes (Ecbatana, Persepolis, Goa, Karakorum, Lisbon, Susa).
- **Codex's Portugal game** (gpt-6.1-sol) is at t118 in `single/Codex_as_Portugal.Civ5Save` (its own quick save
  was overwritten by Grok's game); the arrival fix (a104091) was found on it at t95.
- **The Venice/Mongolia hotseat is finished** (Russia, Science Victory, t253; notes 119-128 in seat 1's notebook).
- **The stack** (2026-10-10 18:22): Steam and Civ5XP (pid 9177) were up but at the LegalScreen with tunerd dead;
  tunerd restarted (pid 9921) on `/run/user/1000/civ5-tuner.sock`, `load_latest` took the t170 quick save. The
  session's MCP server (pid 6499) was started this session from the v269 source. Memory rule: two servers built
  from different runtime sources re-inject each other into one game -- `/mcp` reconnect the session server
  before using its civ5 tools again.

## Where the code is

- **`upgrade_unit` carries the notebook over (2026-10-10, no runtime change)**: `Game.carry_unit_over(old, new)`
  re-points the active assignments and the open order naming an upgraded unit's old id at the new unit (one
  `assignment_facts` read, a history line, the order's `issued` dropped) and the reply says so under `carried_over`.
  Live t214 through scripts/mcp_call.py: Rifleman 630793 -> Great War Infantry 704524, `carried_over.assignments`
  [{46, defend}], `assignments()` 46 on_track. The upgraded unit keeps the original's creation turn (162), so only
  the type tells an upgrade apart in a fingerprint. Three tests. CHANGELOG Unreleased, PLAYBOOK.
- **Queued building in compare (runtime v269, 2026-10-09, late)**: `compare(kind="production")` read London's
  Windmill under construction as refused with no rule (`canConstruct` with bContinue=false refuses a queued
  building); the row now says `can_produce: true`, `in_queue: N`, turns left. Verified live through
  scripts/mcp_call.py (see CHANGELOG). The session's MCP server (pid 61155) was built from v268 Python and never
  re-injects; `/mcp` reconnect it before the next session so its Python carries the unseen-turn hand-back too.
- **Unseen-turn hand-back (2026-10-09, late; no runtime change)**: found live at t147. Spain's renewal came at the end
  of t146, `accept_deal` answered it, the AI round finished during the answer and the next `finish_turn` met t147
  cold and tried to end it (only research-unset refused). `Game.unseen_turn` (arrival due + the turn's `turn_start`
  undelivered to the seat's digest) makes `finish_turn` hand such a turn back unended (`unseen_turn`, woke_because
  `turn_unseen`); a quiet one still passes under `skip_quiet_turns`; `finish_turn(actions=...)` skips the batch on
  one. `test_unseen_turn` (8). CHANGELOG, PLAYBOOK.
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
  The README test count went with the 1.14.0 cut. The
  traceback the suite sometimes printed was the spectator server's thread on a client reset between keep-alive
  requests (`ConnectionResetError` out of `handle_one_request`'s readline): fixed with a test (`test_spectator.py`).
- **main = 1.14.0, tagged 2026-10-09** (runtime v267, 145 tools, 1475 tests; the CHANGELOG section holds the seven
  entries since 1.13.0: the canvas switch and its measurements, the two tech-debt sweeps, the playbook resource fix
  inside the first sweep, the canvas plan, and the two below). README has the release row, the test count and the
  canvas in the spectator bullet; ROADMAP the release paragraph; AGENT_INSTALL says 1.14.0. Of the two
  pre-sweep commits: the spectator dumps the map again
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
  England is at peace with everyone now, so a live read needs another war. Rome (t134) and the Ottomans (t136)
  each asked for a coop war and were declined; neither is a war of ours.
- ~~`explore_frontier.occupied` unit-tested only~~ **read live t138 and found hidden (fixed, runtime v268,
  2026-10-09)**: the scout walked (65,14) -> (64,12) -> (65,10) (the tundra strip ends at the coast there) and back
  to (63,14); from there an Ottoman Rifleman stood on the frontier plot (63,16) two plots away and Edirne's plot
  (64,17) three away held its Great General, and both rows existed in `H.explore_frontier` (59th and 60th of 143,
  read with `harness.cli lua`) but no `limit` the tool accepts could show them, because held rows sorted behind
  every free plot before the cut. Now the cut keeps the held rows within the distance band shown, and a foreign
  city plot carries `city`; verified through `scripts/mcp_call.py explore_frontier` on the same state (12 free
  rows, then the Rifleman's plot and Edirne's with `occupied` + `city`). Open on it: nothing. The session's MCP
  server (pid 44919) was built from v267 and kept working after the v268 injection by the mcp_call process (it
  never re-injects); `/mcp` reconnect it before the next game session all the same.
- The t200 refused melee attack (GAPS §0 Blocked): the *wording* is done (2026-10-09, no runtime change) -- a dropped
  order whose pre-read found a defender says "the engine refused the melee attack on ... from inside a city across a
  river", names the first closed gate it can read, and carries `refused_attack`; `Unit:CanMoveInto` is nil in this
  build and `Unit:CanMoveOrAttackInto` is false for every neighbour (probed live t139, at peace), so the engine's own
  answer is not readable. The *rule* is still open and needs a war with the t200 shape; England is at peace, so the
  new wording has unit tests only (six, `test_refused_attack`), not a live read.
- Spectator page: it still holds every parsed row of a recording (fine since the cadence fix; the 72 MB pre-fix
  file was 122 MB of heap under node, 70-72 MB in Chrome). The seek/stream change was seen in Chrome on 2026-10-08
  (forward and backward drags on the 2026-09-30 replay, above); nothing open on it.
- The rest: `docs/GAPS.md`.
