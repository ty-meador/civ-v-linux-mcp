# Resume here -- 2026-10-24 (evening): main = 1.16.0, tagged 2026-10-24 (runtime v283, 145 tools, 1548 tests; CHANGELOG Unreleased holds the three t238 reads of the late evening: runtime v284, in the game since 22:10) + the fair-play design note (8728ded: GAPS "The seat is bound to the agent's own process", ROADMAP "A seat bound to its channel"); the LIVE GAME is the solo Assyria game (Claude, Ashurbanipal, seat 0, Prince, Pangaea, Tiny, Quick) at **t238**, loaded this evening from the quick save of 2026-10-15 00:07 (also copied to `single/Ashurbanipal_0238 international-games`, S10): Future era, four cities, science victory under way (Apollo t223, Cockpit in the ship t225, the Stasis Chamber building in Assur, Atomic Theory researching toward the Engine, the three Boosters still need Advanced Ballistics), UN host with 24 of 52 delegates, Siam (Order) denounced me t235; the game, tunerd and the Claude Code session server (pid 25370, started from main before v284) are all up as of 21:45.

This file holds the current state only. Earlier "Resume here" sections (58 of them, 2026-09-19 to 2026-10-11) live
in git: `git log -p -- docs/SESSION_HANDOFF.md`; the 2026-10-11 version carries this game's t0-t163 turn by turn.
Shipped work is in `CHANGELOG.md` (the 1.16.0 section holds t164-t208's fixes); known gaps are inventoried in
`docs/GAPS.md`.

## Where the game is

- **The save and the lost turn.** The newest file is the quick save written 2026-10-15 00:07 at **t238** (now also
  `single/Ashurbanipal_0238 international-games`); the engine's autosaves stop at t230. The notebook's briefing
  baseline says t239: the last session ended one turn past the save, and that turn's work is in no file. `load_latest`
  opens t238; the briefing then rightly says the baseline restarts.
- **t238, turn start, nothing blocks.** `gate` null, `decisions` empty, `todo.units` / `cities` empty, no threats in
  sight, no war. Eight units are `ongoing` (two automated Workers 475160 / 507929, six Caravans on routes). Events
  at the turn start: International Games PASSED (14 Yea from me, 9 Siam, 2 more), Ban Luxury: Crab FAILED (my 10
  Nay against Siam 7 + Portugal 5 Yea), two "Great Person born" notices, Sofia cancelled a quest, Antwerp seeks a
  Great Writer. **Look first:** the units list shows no new Great Person beyond Great Engineer 1130538 (t221) and
  Great General 1122345 (t220), so whoever was born at t238 was spent before the quick save or is not what the
  notice says -- `units` / `great_person_progress` settle it.
- **Empire (t238).** Assur (16,27) pop 25, Nineveh (20,28) 20, Nimrud (18,23) 16, Kar-Tukulti-Ninurta (12,26) 15;
  all Judaism, all garrisoned, all growing. Gold 2334 at +56, science 850, culture 275 a turn with 2691 stored
  (next policy 3575), faith 1065 at +94, happiness 68, 53 units, score 1607. Golden Age over (t235). Era: Future
  (Satellites t224).
- **Science victory.** Apollo Program done t223 in Assur; SS Cockpit bought (2160 g, t224) and added t225. Now:
  Assur builds the **SS Stasis Chamber** (8 turns; Nanotechnology is known), Nineveh and Nimrud finish **Spaceship
  Factories next turn** (Assur has one), K-T-N runs the Research process. The **SS Engine** needs Particle Physics
  (Atomic Theory researching, 5 turns, 408 stored; then Particle Physics); the **three SS Boosters** need Advanced
  Ballistics, not yet in `available_research` (Archaeology 1 turn and Lasers 7 are the other two offered). No rival
  has Apollo (`spaceship_status.rivals` empty). The habit that got here: faith-buy a Great Scientist whenever faith
  allows (2680 at t228) and bulb it; Hubble (t226) gave two; the Great Engineer rushed Hubble.
- **Policies.** Tradition and Patronage done, Rationalism finished t188 (free Flight), Freedom since t200: Avant
  Garde, Civil Society, New Deal (t195), Creative Expression / Space Procurements (t209-t213), Capitalism (t216),
  Volunteer Army (t221: six Foreign Legions), Treaty Organization (t225), Cultural Diplomacy (t230), Merchant
  Confederacy (t231). Universal Suffrage was refused at t208 by the level gate (runtime v283 names it).
- **Diplomacy** (note 2, t236, is the full picture). SIAM (Ramkhamhaeng, player 2) adopted Order t234 and
  **denounced me t235**, three turns after renewing the DoF: the largest army on the continent, borders Nimrud and
  Nineveh from the north, at war with Shaka since t229-t230; a war risk from now on. Deals running with Siam: the
  Research Agreement signed t220 (pays t245; I gave 268 g + 5 Coal + 3 Aluminum + 9 gpt), Marble for 5 gpt to t248,
  open borders to t249 (consider not renewing), and **Salt for 5 gpt ended this turn (reoffer t239)**. PORTUGAL
  (Maria, player 1): neutral-friendly, Salt for Truffles to t247 (Truffles is my only copy). ZULU (Shaka, player
  3): friendly, open borders to t250, **Fur + 4 Iron for Dye ended this turn (reoffer t239; Dye is my only copy;
  Nimrud's WLTKD ended t234 and it now wants Crab)**. Promised t201: no more conversions in Siam.
- **United Nations.** I host; 24 delegates (4 + 2 host + 18 from nine allies) against Siam 16, Portugal 8, Zulu 4.
  World Leader needs 42 and is **"Not allowed by this game's options"** (diplomatic victory is off in this game).
  Active: Sciences Funding, World Religion Buddhism, Cultural Heritage Sites (+3 culture per wonder), and now the
  **International Games project** (cost 1929; 482 production for tier 2, the top contributor gets +100% tourism for
  20 turns and a free policy; I have contributed 0 -- Nineveh and Nimrud are free after their factories). My
  proposal **International Space Station** (free Great Scientist, research boost, the ISS wonder) is pending;
  Siam says Yea (16); the session is in 6 turns (t244). World's Fair finished with me at tier 3 (644 of 938).
- **City-states.** Nine allies (2 delegates each); the t196 list was Mombasa, Yerevan, Malacca, La Venta,
  M'banza-Kongo, Ormus, Monaco, Sofia, with Belgrade added t216 and Colombo / Antwerp lost to Portugal at t231;
  `city_state_bonuses` is the live list. Siam buys city-states aggressively (Bratislava, Byblos, Zurich flip back
  and forth); Treaty Organization plus caravan routes to La Venta, Malacca, Sofia and Nobamba is the counter.
  Gifted units keep arriving (Paratroopers from Belgrade t231 and M'banza-Kongo t233, Rocket Artillery, an
  Infantry); the spare Knights 868385 / 892934 are `gift_unit` candidates.
- **Assignments and orders.** Two active garrison roles, both `on_track`: 4 (Nimrud; Swordsman 335873 -- which
  stands on (16,24), not in the city, see Still open) and 6 (Nineveh; French Musketeer 704517 in place). No open
  standing order: the last, 51 (Scout 98304 home to (14,26)), completed t229. Notes: 1 (t93 plan, stale), 2 (t236
  diplomacy, current), 3 (t196 plan, the strategy; its numbers are stale), 4 (t98 diplomacy, stale). A fresh plan
  note at t238 is the first thing to write.
- **Military.** 53 units: six Foreign Legions, four Infantry, two Paratroopers, two Rocket Artillery, an Artillery,
  four Hwacha, a Gatling Gun, an Anti-Aircraft Gun, and a long tail of obsolete units (Swordsmen, Pikemen,
  Crossbowmen, a Trebuchet, a Lancer, Knights, a Horseman, a Musketman, Ski Infantry); plus five Workers and six
  Caravans. Upgrades were never a priority; with Siam hostile they may become one (`upgrade_unit` carries the
  notebook over).

## Where the code is

- **main = 1.16.0, tagged 2026-10-24** (runtime v283, 145 tools, 1548 tests): the twenty-eight fixes since 1.15.0
  (runtime v270-v283) found on the end of the England game (t214-t226) and this game's t0-t208 -- the quiet-run
  filters, the rule-naming refusals, the `unit_spent` reads, the war and defeat reads, a new game's first turns.
  README has the release row, the test count and six bullets refreshed; ROADMAP the release paragraph;
  AGENT_INSTALL says 1.16.0.
- **The fair-play design note (8728ded, 2026-10-24).** A `--seat N` server refuses `set_seat` onto the other human
  seat and nothing else stands between one agent and the other's map (tunerd forwards any Lua for any caller; a
  second server, `scripts/mcp_call.py --seat N` and `harness.cli lua` reach the same socket). `docs/GAPS.md` has
  the threat model and a first count of runtime entries by seat argument (81 take `pid` first, about a hundred
  take a unit / city / plot and get their seat from the owner); `docs/ROADMAP.md` the five-stage route with tunerd
  as the enforcement point. Not started. A small follow-up is still open: `docs/AGENT_INSTALL.md`'s Codex
  paragraph reads as if Codex needed a pinned seat; it should say `--seat auto` for solo play and a pin only for a
  shared hotseat, with the reason stated once for every client.
- **Live processes (2026-10-24 21:45).** Game pid 38183 (launched 21:42 by `scripts/launch_civ5.sh main`; Steam was
  already up), tunerd on `/run/user/1000/civ5-tuner.sock` since 21:44 (48 Lua states on its first connect), the
  Claude Code session server pid 25370 started 21:02 from current main. The quick save was loaded through
  `load_latest` at 21:45; runtime v283 answered the first briefing. Runtime v284 has been in the game since
  22:10 (injected by a fresh `scripts/mcp_session.py` server for the live checks above); the session server pid
  25370 still runs the v283 Python, so its `assignments` rows lack `distance` and an `amend_assignment` through it
  would refuse `review.max_distance` as an unknown key until it is restarted from current main.
- **Where t208-t238 is written down.** Nowhere in the repo: those turns were played on 2026-10-14/15 without a
  code change (the commits stop at t208). The notebook (note 2) and the saves are the record; the memory plugin's
  observations hold a turn-by-turn narrative outside the repo.
- **Memory-rule reminders**: the ctx sandbox lacks XDG_RUNTIME_DIR, export
  `CIV5_TUNERD_SOCK=/run/user/1000/civ5-tuner.sock` before any `harness.cli` call there; `pkill -f` in a
  compound Bash call kills the shell; disband is denied to the auto-mode classifier; copy QuickSave to a named
  file before loading another save into a live game (done this evening: S10).

## Still open

- **Seen at t238, understood and read since (runtime v284, 2026-10-24 late evening; CHANGELOG Unreleased).** (1) The
  two "Great Person born" notices were a Great Scientist (bulbed: Nanotechnology) and a Great Musician (a Great
  Work), both spent on 2026-10-15 in the same t238 before the quick save -- the call ledger's `do` row at 00:07
  has both missions; `notification_log` now names the person (`unit: SCIENTIST` / `MUSICIAN`, `of_type_now: 0`)
  and a notice whose person the hook saw born reads `unit_gone` once it is spent. The Great Person count of
  t238 is therefore right: nothing is missing. (2) Assignment 4's Swordsman 335873 stands THREE plots from Nimrud
  (Map.PlotDistance agrees), not two; every assignment unit row now carries `distance`, both garrison assignments
  (4 and 6) carry `review.max_distance: 0`, and assignment 4 reads needs_review ("3 plot(s) from its post (18,23)")
  until the Swordsman is back on (18,23) or the assignment is amended. (3) `league_status` carries
  `diplomatic_victory_enabled: false` with `diplo_victory_note`; the 42 is moot in this game.
- **The Siam risk.** Denounced t235, Order against my Freedom, their army the largest, open borders running to t249.
  Nothing in the harness is missing for a war (the England siege read everything), but the garrison roles and the
  obsolete army are the seat's own problem; the renewals due t239 (Zulu Dye, Siam Salt) are the first decisions.
- **Not yet seen live**: `quick_save` under a decision popup (coded 2026-10-11), the `fogged_destination` hint on a
  "no path" refusal (unit tests only), S9's RETURN_CIVILIAN re-raise on load, the refused-melee *rule* (GAPS §0
  Blocked: needs a war with the t200 shape -- a city tile, a river, a second unit in the city; only the wording is
  done).
- **Two tests failed once, together, on the first `scripts/check.sh` run of 2026-10-10 evening** (the 1.15.0 cut):
  `test_ranged_preview.py::test_ground_ranged_has_no_retaliation_or_interceptor_read` and
  `test_runtime_source.py::test_a_failure_midway_is_not_current_and_the_corrected_retry_carries_state`; one of the
  two failed once more in a loop of three runs of just those two files. The assertion text was not captured
  either time. Not reproduced since: every full run through 2026-10-24 (three today, 1548 green) and 37 runs of the
  pair. Both build a Lua state from `runtime_source.snapshot()` (one under ctypes liblua5.4, one under lupa). If it
  shows again, keep the `E` lines: a `pairs`-order dependency under a randomized string-hash seed is the first
  suspect, load the second.
- `unit_displaced` (read live England t131): a *route* caravan on the city tile at the turn end did not move the
  General, only an idle trade unit does; why the engine moves the civilian and not the trade unit, and whether a
  Worker or Settler is moved the same way, is not known; the row reports the fact either way.
- Spectator page: it still holds every parsed row of a recording (fine since the cadence fix; the 72 MB pre-fix
  file was 122 MB of heap under node, 70-72 MB in Chrome); a bounded window is the ROADMAP's open visualization
  item.
- **Seat binding, stage 1 done (2026-10-24 late evening, uncommitted runtime untouched):** tunerd `--seats FILE`
  binds connections by token or uid and refuses unbound `exec`/`query` (`tests/test_tunerd_seats.py`, 21 tests).
  The live tunerd runs without a table (solo game; nothing to bind). **Stage 2 done 2026-10-25**
  (`scripts/seat_survey.py`, GAPS "Stage 2, the survey"): the seat slot is per entry (90 first / 102 last / 15
  middle), three Python-reached entries lack one (`H.diplo_event`, `H.plot_units`, `H.plots_around`), `Game.seat`
  is the one attribute stage 3 replaces, and 48 `InGame` ad-hoc bodies become named entries. **Stage 3 done
  2026-10-25 evening (runtime v285, `tests/test_seat_call.py`), not yet seen live:** tunerd's `call` / `runtime`
  ops write the seat and install the runtime; `Game.h` names entries; no Lua text goes to `InGame` from the Python
  side. Seen live the same evening after a cold start (Steam was up, the game was not): `load_latest` and every
  read of the turn through `call` on a plain daemon; then on a daemon with a one-seat token table a tokened
  `mcp_session.py` read `turn_status` / `units` / `todo_actions` / `generic_popup` / `tactical_view`, an untokened
  one was refused unbound, and a tokened `cli lua` was refused for `InGame`. The stack was left up: the game at
  t238 (nothing ordered, no turn ended), tunerd restarted **without** a table (the new code; the idle Claude Code
  servers reconnect by themselves). **Next session's first `finish_turn` is the live turn through `call`**: watch
  `logs/calls.jsonl` trips stay the usual (the daemon adds no trip once the runtime is checked) and the tunerd log
  for a single `runtime v285 ... installed` on a bound daemon. **Stage 4 done 2026-10-25 late evening**
  (`tests/test_seat_escape_hatches.py`): a bound server plays its binding only (a wrong `--seat` is refused on every
  tool, `set_seat` moves nowhere else, the `lua` tool refuses), seen live at t238 on a one-seat table from this
  sandbox (eight probes), tunerd restored **without** a table again. Stage 5's words are written; its live
  two-agent hotseat on bound sockets waits for a second agent's sandbox. The tool-surface plan is now GitLab
  milestone 2.0.0 (one issue per stage item, tracking issue listed in `docs/ROADMAP.md`); work from the issues.
- The rest: `docs/GAPS.md` (§0 for the read gaps, the 2026-10-24 section for the seat-binding design gap).
