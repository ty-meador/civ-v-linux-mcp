# Road to 1.0.0

Reconciled `docs/GAPS.md` §0 against `harness/` at runtime v191 on 2026-09-24 (progress through v201 the same day: 0.2.0 closed, 0.3.0 complete and tagged, 23 of 29 issues closed or declared; open: #23, #29 tracking; #13 and #15 closed live 2026-09-25; #21 closed live and 0.5.0 tagged `v0.5.0` = runtime v206 on 2026-09-25 with #23 left open until a state reproduces it; #23 closed v207 the same day -- the engine freezes its blocker while a popup is up, reproduced by meeting a city-state through a unit's own move; 1.0.0 tagged `v1.0.0` = runtime v207 on 2026-09-25 after a three-turn `play_loop` pass on a clean S1 load): every open item is still open in code (grep-verified; the suite is at 401 passing, not the 391 the doc said). Planned on GitLab: milestones 0.2.0–1.0.0, one issue per gap with the game state that closes it, tracking issue [#29](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/29), board "Road to 1.0.0".

Order is by dependency: boundary first (nothing new may leak), then the trade table (its hotseat war/peace states feed 0.5.0), then the remaining screens, then live verification, then release hygiene. Package version follows the milestone; `RUNTIME_VERSION` keeps its own counter (see #26).

## Game states the plan depends on

| Key | Save | Used for |
|---|---|---|
| S1 | `single/Pocatello_0266 solo-final.Civ5Save` (Shoshone, Emperor, t266) | embassies, World Congress, spies, late-game culture/religion screens, city hovers |
| S2 | `hotseat/Alpha-Bravo_0227 peace.Civ5Save` (Korea vs Austria, Duel, Atomic, at peace) | PvP deals, peace with terms, third-party items, scratch-deal payload reads, greeting popup |
| S2b | `hotseat/Alpha-Bravo_0237 peace-terms.Civ5Save` (Bravo's t237, right after accepting peace + Silk + Salzburg; treaty to t247, deal to t262) | the ceded city's first turns, the peace-with-terms deal rows, a fresh 10-turn forced peace |
| S3 | `single/Pocatello_0266 combat-lab.Civ5Save` (S1 + barbarian Warrior on the hills at 49,18, Archer at 48,18, raider at 47,13 beside a sleeping Worker; Musketman 630799 has Drill I) -- replaces the overwritten t230 hotseat quicksave | modifier rows, captor visibility (fire support is off in stock BNW) |
| S5 | `hotseat/Doge_0215 venice-puppet.Civ5Save` (Venice, one human seat, Wittenberg bought at t215) | puppet purchases (#15) |
| S6 | `hotseat/Shah_0214 golden-age.Civ5Save` (Persia "Shah", one human seat vs England, Duel / Quick / Atomic; 10 golden-age turns granted by Lua, at war with England, two English Warriors beside Infantry 32771 and 40964) | the golden-age combat modifier row (#21) |

Saves live under `~/.local/share/Aspyr/Sid Meier's Civilization 5/Saves/`. Scenario surgery goes through `harness.cli lua`.

## 0.2.0 Information boundary

Nothing new may leak and no read may truncate. Saves: S1 (embassies), S2 (deal payloads via Lua).

| # | Issue | Labels |
|---|---|---|
| [#1](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/1) | ~~Leak: embassy exposes a rival's full technology list~~ closed (v192) | leak, area::tech, needs-game-state |
| [#2](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/2) | ~~Leak: deal rows carry coordinates of unrevealed cities~~ closed (v192) | leak, area::trade, needs-game-state |
| [#3](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/3) | ~~Query chunking budgets characters, not escaped bytes~~ closed (a18f4ea) | transport, bug, area::infra |

## 0.3.0 Trade table

Everything a human can put on, read from, or answer on the trade table. Primary state: the Alpha/Bravo hotseat, re-entering war where needed.

| # | Issue | Labels |
|---|---|---|
| [#4](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/4) | ~~Trade proposals between human seats (PvP deal screen)~~ closed (886fe67, live accept t227 / refuse t228) | parity-write, parity-read, area::trade, needs-game-state |
| [#5](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/5) | ~~Peace with terms (gold, cities, resources) through the real screen~~ closed (v200, live t237: Silk + Salzburg accepted by the other human seat) | parity-write, area::trade, needs-game-state |
| [#6](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/6) | ~~Third-party war/peace items and the Demand button~~ closed (third-party v199 live t234; Demand v202 live S1 t266, Darius refused) | parity-write, parity-read, area::trade, needs-game-state |
| [#7](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/7) | ~~World Congress vote commitments on the trade table~~ closed (v198, live pledge accepted t233) | parity-read, parity-write, area::trade, needs-game-state |
| [#8](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/8) | ~~City population on trade rows and in trade_catalog~~ closed (v192) | parity-read, area::trade |

## 0.4.0 Screens before the decision

The remaining screens and hovers a human reads before deciding.

| # | Issue | Labels |
|---|---|---|
| [#9](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/9) | ~~Coup odds and why the coup button is grey~~ closed (v194) | parity-read, area::espionage, needs-game-state |
| [#10](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/10) | ~~Spy-city potential hover (effective potential, modifiers, catch-spies lines)~~ closed (v194) | parity-read, area::espionage, needs-game-state |
| [#11](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/11) | ~~Religion Overview: automatic faith purchase selection~~ closed (v194) | parity-read, parity-write, area::religion, needs-game-state |
| [#12](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/12) | ~~Culture Overview: great-work swap tab~~ closed (v195) | parity-read, parity-write, area::culture, needs-game-state |
| [#13](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/13) | ~~Change ideology: unhappiness hover, switch cost, and the switch itself~~ closed: read v197; live switch S4 t239 (Bravo's eight concert tours put Alpha in Civil Resistance, Autocracy -> Order with 2 turns of anarchy); the gold hover's anarchy line v204 | parity-read, parity-write, area::culture, needs-game-state |
| [#14](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/14) | ~~City screen: per-yield hover breakdowns~~ closed (v193) | parity-read, area::city |
| [#15](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/15) | ~~Purchases in Venice's puppets~~ closed: catalog v201, live S5 Doge t215 (Wittenberg bought with a Merchant of Venice, Monument purchased in the puppet); v205 localized `producing` and gave Venice the purchase hint instead of "annex first" | parity-read, area::city, needs-game-state |
| [#16](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/16) | ~~Specialist yields on the city screen~~ closed (v193) | parity-read, area::city |
| [#17](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/17) | ~~Help text on buildings the city already owns~~ closed (v193) | parity-read, area::city |
| [#18](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/18) | ~~Stored research on non-current techs~~ closed (v193) | parity-read, area::tech |
| [#19](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/19) | ~~Remembered terrain features under fog (last-seen cache)~~ closed (v196) | parity-read, area::map, needs-game-state |

## 0.5.0 Live verification

Reads with regression coverage only, closed by a live reproduction, plus the open turn-loop defect.

| # | Issue | Labels |
|---|---|---|
| [#20](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/20) | ~~Live: nonzero melee fire support~~ closed as declared limitation: `FIRE_SUPPORT_DISABLED = 1` in stock BNW, engine returns no support unit even with every gate satisfied (S1 t266) | live-verify, area::combat, blocked-engine |
| [#21](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/21) | ~~Live: golden-age and rough-terrain combat modifier rows~~ closed: rough/open terrain and flanking rows live S1 t266; golden-age row live S6 t214 (Persia in a Lua-granted golden age, Infantry vs England's Warriors: "Golden Age Bonus +10", 70 -> 77 strength, row gone with the golden age off) | live-verify, area::combat, needs-game-state |
| [#22](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/22) | ~~Live: captured civilian with a visible captor, and capture by the other human seat~~ closed: barbarian captor S1 t267, Bravo's Infantry as captor S2b t237-238 (v203 fixed the notice-first ordering and the stale roster plot) | live-verify, area::combat, needs-game-state |
| [#23](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/23) | ~~Bug: CityStateGreeting popup leaves ENDTURN_BLOCKING_UNITS with an empty todo~~ closed v207: reproduced live S6 line t215 once the meeting came from a unit's own move (the three `Teams:Meet` attempts never could: the engine rule is that `GetEndTurnBlockingType` is not re-evaluated while a popup is up, so the last ready unit's order plus any announcement popup -- a city-state met on the way, a natural wonder, a plain text box -- leaves UNITS on the books with `HasReadyUnit()` false). `turn_status` now says `blocking_stale` with the true hint, `end_turn` treats the popup as the blocker, and the sweep processes a popup the engine waits on that nothing draws | bug, area::turn-loop |

## 1.0.0 Release

CI, semantic version and tags, CHANGELOG, docs refresh, save library, declared engine limitations.

| # | Issue | Labels |
|---|---|---|
| [#24](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/24) | ~~Engine limitation: path overlay and movement cost~~ declared in `docs/LIMITATIONS.md` (with fire support, lump gold, LOS, forced peace) | blocked-engine, area::map |
| [#25](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/25) | ~~CI: run the regression suite on every push~~ resolved locally: no shared GitLab runner minutes for this project, so `scripts/check.sh` (locked `dev` group + pytest) is the pre-push check and `.gitlab-ci.yml` was removed 2026-09-25 | release, area::infra |
| [#26](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/26) | Versioning: semantic version, tags, CHANGELOG, runtime-version mapping -- `CHANGELOG.md` added with the two-counter rule and the runtime map; tags `v0.3.0` (runtime v202), `v0.5.0` (runtime v206) and `v1.0.0` (runtime v207) | release, area::infra |
| [#27](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/27) | Docs: README/ARCHITECTURE refreshed 2026-09-25; declared limitations split out to `docs/LIMITATIONS.md`, GAPS.md kept as the audit log | release |
| [#28](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/28) | ~~Save library for the reproduction states~~ `saves/` holds S1, S2, S2a, S2v, S2b, S3, S4, S5, S6 with a README | release, needs-game-state |
| [#29](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/29) | ~~Road to 1.0.0 (tracking)~~ every row above closed or declared; `v1.0.0` tagged 2026-09-25 (runtime v207, 495 tests) | release |

## After 1.0.0

Everything a model needs to play a turn as one call, then whatever a live game shows is still slow or
unseen. The 0.3.0-1.0.0 milestones were closed on 2026-09-26; the post-1.1 plan is below.

| Version | Item | State |
|---|---|---|
| 1.1.0 | `finish_turn` (end_turn + wait + digest, `skip_quiet_turns`), MCP progress every 5 s, notebook `remember`/`recall`/`forget`, `do` batches, `action_id` replay, `set_seat`, `exit_to_main_menu`, finish_turn default 600 s | tagged `v1.1.0` 2026-09-25 (runtime v212) |
| 1.2.0 | `gate`, the rule book, `todo_actions`, one-query screen reads, turn claim (#41), notebook replace guard (#40), `alerts` (#39), `todo.ongoing` (#37), `expiring_deals` / `expiring_friendships` (#38) | tagged `v1.2.0` 2026-09-26 (runtime v219); see the ranked table below |
| 1.3.0 | `todo_actions(detail="summary")` (#35), `briefing` and `finish_turn(briefing=true)` (#30), `tactical_view` (#31) | tagged `v1.3.0` 2026-09-26 (runtime v223); see the ranked table below |
| 1.4.0 | structured assignments (#33), `compare` (#34) | tagged `v1.4.0` 2026-09-27 (runtime v225); see the ranked table below |
| next | ~~Legal actions for many units in one read~~ `todo_actions` (runtime v213, live S1 t270: 38 units in one 0.5 s query). The per-unit read turned out to cost 0.37 s, so the ~15 min a late `play_loop.py` turn takes is not this; where it goes is unmeasured | closed |
| next | ~~Where a late-game `scripts/play_loop.py` turn spends its time~~ timed with `play_loop.py --profile` (runtime v214): S1 t270 took 97 s, not 15 min, and 250 of its 278 tuner trips were popup-screen reads (`turn_state` 8 trips, the sweep ~20, both on every wait poll). `H.modal_flags` reads every screen in one query; `turn_state` is 1 trip, `end_turn` 8 (was 93) | closed |
| next | ~~`unit_mission` trips: a plain order is 2 (order + `unit_pos`), a refused one 3; the automate path's confirmation poll (up to 12 x 0.25 s `automate_check`)~~ measured live t151 with an in-process trace of every query: the gate's `discussion_pending()` was a second trip on every mutating call (`H.turn_state` carries the flag since v214; the gate now reads it), a `do` batch reads every unit order back in one query at its end (`after_pending` markers), and the fixed 0.2-0.25 s waits before the first read are 50 ms (an order lands on the next frame). Lone order 6 -> 5 ledger trips (0.30 -> 0.21 s), two-order batch 10 -> 7 (0.50 -> 0.31 s). A refused order still explains itself with two more reads | closed (unreleased) |
| later | LAN mode since 0.5.0 and `declare_war` on a city-state syncing over LAN (`docs/LIMITATIONS.md`) | needs a LAN game |
| later | ~~Game over: `turn_status.game_over` against a stale PRODUCTION blocker, seen once at t457, no regression state~~ seen a second time at t502 (S7 `Wu Zetian_0502 science-victory-eve` is the state one call before the win; the blocker froze at UNITS this time); `spaceship_status.complete` and the completing mission's `game_over` / `victory` fields shipped in 1.9.0 | closed |

## 1.2.0-1.6.0: LLM play usability

Ranked 2026-09-26 from the 2026-09-26 hotseat play review (tracking issue
[#36](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/36), which carries the reasoning). One
GitLab milestone per group; the issue board's Manual sort follows the rank. Do the work in this order:
small fixes found in live play first, then the shared compact-response controls, then the reads built on
them, then persistent intent, then the orders that depend on it.

| Rank | Issue | Milestone | Depends on |
|---|---|---|---|
| 1 | [#40](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/40) `remember(replace_id)` refuses a different tag, returns the previous text | 1.2.0 Turn status tells the whole turn | -- |
| 2 | [#41](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/41) One client claims a seat's turn | 1.2.0 | -- |
| 3 | [#39](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/39) Happiness and strategic-deficit alerts on `turn_status` | 1.2.0 | -- |
| 4 | [#37](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/37) Automated units and standing-move destinations on the checklist | 1.2.0 | -- |
| 5 | [#38](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/38) Expiring deals and declarations of friendship | 1.2.0 | -- |
| 6 | [#35](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/35) Compact response modes with drill-down (record the baseline first) | 1.3.0 Compact briefing and tactical view | -- |
| 7 | [#30](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/30) Compact turn briefing | 1.3.0 | #35, #37-#39 |
| 8 | [#31](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/31) Unit-centered tactical view | 1.3.0 | #35; no #24 probes |
| 9 | [#33](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/33) Structured assignments on the notebook | 1.4.0 Plans that survive a context reset | #40, #30 |
| 10 | [#34](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/34) Compact comparisons for production, improvements, research, trade | 1.4.0 | #35 |
| 11 | [#42](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/42) Split the runtime file (tech debt, ahead of the rest of 1.5.0) | 1.6.0 Runtime split | -- |
| 12 | [#32](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/32) Conditional unit orders | 1.5.0 | #33, #30, #41; lands in `movement.lua` / `turn.lua` |
| 13 | [#36](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/36) Tracking | 1.5.0 | all of the above |
| 14 | [#43](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/43) The size of the `finish_turn` reply: notes ride once, threats compact and `seen`, orders not twice | 1.7.0 | #36 |

1.2.0 also ships the runtime v215 (`gate`) and v216 (rule book) work. Its five issues are closed and one
live hotseat turn (t42, both seats) showed the new status fields: tagged `v1.2.0` 2026-09-26 (runtime v219,
840 tests). 1.3.0 so far: #35 `todo_actions(detail="summary")` (runtime v220) and #30 the `briefing` tool and
`finish_turn(briefing=true)` (runtime v221, 873 tests), both checked live on Venice t42 and S1 t266-t267;
#31 the `tactical_view` tool (runtime v222, 885 tests), checked live on Venice t42. With those three the
milestone's issues are done. Checked together on one live hotseat turn (t42) and tagged `v1.3.0` 2026-09-26
(runtime v223: the tactical grid now stops at `radius`, 886 tests). Next: milestone 1.4.0, #33 then #34.
1.4.0 so far: #33 structured assignments (runtime v224, 913 tests), checked live read-only on Venice t42; a
real unit loss and upgrade were not played out live (tests cover both). #34 compact comparisons (runtime v225,
931 tests), checked live on Venice t42, S5 t215 (the Venice puppet) and S1 t266 (trade, through an AI
caravan: seat 0's four were all on routes). With those two the milestone's issues are done. Used together on one live hotseat turn (t42) and tagged
`v1.4.0` 2026-09-27 (runtime v225, 931 tests). 1.5.0: #32 conditional unit orders (runtime v226-v227, 970
tests), checked live t42-t48 on the Venice/Mongolia hotseat; #36 closed with a measured turn loop (t48-t51 played
twice: 8.0 -> 4.25 calls a turn, two refusals -> none, bytes level; `docs/NOTES.md`). Tagged `v1.5.0` 2026-09-27
(runtime v227, 983 tests). 1.6.0: #42 the runtime split (runtime v241-v242, 1000 tests): one Lua file per domain under
`harness/lua/runtime/`, each its own named chunk, loaded in `harness/runtime_source.py` order; checked live on the
Venice/Mongolia hotseat t52-t53 (inject over v227, reads, one `set_research`, forced reload, a hand-off both ways).
Tagged `v1.6.0` 2026-09-27 (runtime v242, 1000 tests). 1.7.0: #43 the size of the `finish_turn` reply (1058 tests, no runtime change): measured by replaying the #36 replies through the new composer and by playing the same t48-t51 save live again, 26% off the wait reply, a third on turns with open orders (`docs/NOTES.md`). Tagged `v1.7.0` 2026-09-27 (runtime v242, 1058 tests). 1.8.0 (no issue; the day's work after the milestones): the
MCP server in one core plus a tool module per domain, `how_to_play(topic)` with the instructions and descriptions
under the client's 2000-character cut, gates that name the right tool, runtime v244-v252 (civilian one-per-tile,
the wait gate's AI round, `territory`, permanent deals, `todo.policy`, the trade-unit cap and stable
caravan-route rows), `remove_from_queue`, `scripts/hotseat_rounds.py`, and an install that needs neither
gcc nor uv (Steam Deck). Tagged `v1.8.0` 2026-09-27 (runtime v252, 144 tools, 1136 tests). 1.9.0 (no issue): a
unit order one trip cheaper and a `do` batch one per order (measured live t151), and the science-victory end state
(live t502, S7 saved). Tagged `v1.9.0` 2026-09-29 (runtime v252, 144 tools, 1158 tests). 1.10.0 (no issue): the live visualization
(`harness/spectator`, `web/viz`, the ledger's attention fields), checked on the Pocatello solo save and one
Venice/Mongolia hotseat round (t150-t152); `set_production` by button name. Tagged `v1.10.0` 2026-09-30 (runtime
v252, 144 tools, 1200 tests). 1.11.0 (no issue): a seat view that draws only what that seat's screen shows,
a spectator snapshot read when the world moves and pushed when it changed (72 MB -> 532 KB for a hotseat
round), and runtime v253, the trade unit's second gate (`CanTrain` per city and kind with the engine's own
sentence), all checked on the Venice/Mongolia hotseat at t152-t153. Tagged `v1.11.0` 2026-10-01 (runtime v253,
144 tools, 1208 tests). 1.12.0 (no issue): a turn's closing orders and its end are one
call (`finish_turn(actions=[...])`, a move's `revealed`, `--tools compact` with `call`), a call ledger that
names the client behind each row and a turn claim that recognises its own client, refusals that say what to
do instead (`did_you_mean` and the unit's legal missions, the sleep/fortify equivalent, `skip_actions` for
leftover movement, the engine's sentence on a greyed button, a purchase, peace, a ranged attack), runtime
v254-v263 (a seat's digest at the hand-off, ranged strength, tactical_view sized to sight, free tenets,
deal givers and renewals), all checked on the Venice/Mongolia hotseat at t153-t256 and Codex's 73 turns as
Portugal. Tagged `v1.12.0` 2026-10-04 (runtime v263, 145 tools, 1430 tests). 1.13.0 (no issue): the spectator's
scrubber (play/pause, speed, a slider with turn ticks, `/recording`), a turn that arrives before its first order
when no wait of ours opened it, a tuner stream that resyncs after a timed-out command, a finished game as the
wait's answer with the winner, and what a human sees in a siege -- `wars` with the Negotiate Peace gate and the
briefing's `at_war` rows, a leader screen outranking "turn not active" in the gate, `unit_displaced` for a unit
the engine moved, the league's special session, `occupied` frontier plots (runtime v264-v266), found and checked
on Codex's Portugal game (t83-t95) and Grok's abandoned England game, played from t118 to t133. Tagged
`v1.13.0` 2026-10-08 (runtime v266, 145 tools, 1469 tests). 1.14.0 (no issue): the spectator map moved from SVG
to a canvas (`docs/CANVAS_MIGRATION.md`: the plan, the SVG baseline, the side-by-side on synthetic maps up to
200x120 and on two real recordings; on the frame everywhere the SVG spent 44-148 ms a frame), with
`scripts/viz_bench.mjs` to re-measure through the DevTools protocol; the spectator dumps the map again when a
snapshot's `map_key` changes, a seek applies the latest snapshot before its target, the `civ5://playbook`
resource reads the shipped playbook, and two tech-debt sweeps (dead code out, seven more ruff rules, the slow
tests' sleeps patched, the 2026-09-19 coverage audit marked historical with its closure table; runtime v267).
Tagged `v1.14.0` 2026-10-09 (runtime v267, 145 tools, 1475 tests). 1.15.0 (no issue): five fixes found playing
Grok's England game from t133 to t214 -- `explore_frontier` keeps the held plots within the cut and names a
foreign city on a frontier plot (runtime v268); a melee attack the engine drops is reported as a refused attack
naming the first closed gate (the t200 rule itself still needs a war); a turn that began while a leader screen
was being answered is handed back unended (`unseen_turn`); `compare(kind="production")` reads a queued building
as queued, not refused (runtime v269); and `upgrade_unit` carries the assignments and the open order onto the
new id (`carried_over`). Tagged `v1.15.0` 2026-10-10 (runtime v269, 145 tools, 1495 tests). 1.16.0 (no issue):
twenty-eight fixes from the end of Grok's England game (t214-t226) and a solo Assyria game played from its first
turn to t208 -- a quiet run stays quiet on what decides nothing for this seat (other players' wars, alliances,
denouncements and quests, a swept splash, a leader's plain remark, a happiness dip inside the comfortable band;
one wake per expiring deal); a refusal names its rule (the Buildings table's location, resource and policy-branch
columns, an ideology tenet's level gate, a Prophet that has spent a spread, a closed border's rival-territory
flag, `did_you_mean` for a policy name); a unit our own order used up is `unit_spent` with the reason and a
plundered caravan says so; the briefing names the plots a neighbour took, a repair step completes when the plot
is mended, the Ottoman war's four reads (narration carry-over, the swap refusal, the open-borders embassy note,
a note-only amend), a defeat read with the last city, and a new game's first turns (runtime v270-v283). Tagged
`v1.16.0` 2026-10-24 (runtime v283, 145 tools, 1548 tests).

## A seat bound to its channel (fair play by mechanism)

Raised 2026-10-24 (`docs/GAPS.md`, "The seat is bound to the agent's own process"). Today a `--seat N` server
refuses `set_seat` onto the other human seat, and nothing else stands between one agent and the other's map:
tunerd forwards any Lua for any caller, a second server, `scripts/mcp_call.py --seat N` or `harness.cli lua`
reach the same socket, and two agents on one machine are one user. The guard catches a mistake, not intent.
The fix moves the seat binding to tunerd, the one process every path already crosses, and makes the per-seat
Lua something the daemon writes rather than something the caller sends.

Needs a two-agent hotseat game to check live (the Venice/Mongolia and Codex/Grok shapes; a solo game shows
only that nothing changed). Opt-in throughout: a daemon with no seat table is today's daemon.

| Stage | Work | Done when |
|---|---|---|
| 1 | tunerd learns seats: `--seats <file>` (token-to-seat, or uid-to-seat for `SO_PEERCRED`); a connection's first message binds it or it is refused; `states` / `events` / `ping` stay open, `exec` / `query` need a binding | a raw client with no token is refused on a daemon with a table; the same client works on a daemon without one. **Done 2026-10-24** (`harness/tunerd.py` `SeatTable` / `gate`, `harness/client.py` sends `CIV5_TUNERD_TOKEN` as the first message of every connection, `harness/tunerd-seats.example.json`; 21 tests, and the real daemon checked on a scratch socket with no game). Both identities at once: a token in a first `hello` *and* the peer uid, the table in a file (`--seats`, `CIV5_TUNERD_SEATS`); a uid-bound connection takes only its own seat's token. Not yet seen from a second agent's sandbox in a live hotseat (stage 4's check). |
| 2 | survey `harness/lua/runtime/*.lua`: every `H.*` read and write takes the acting seat as its own argument and never a caller-chosen player id in that role; list the Python call sites that compose Lua ad hoc (`game.py`, `game_parts/*`) | the survey is a table in `docs/GAPS.md` with the exceptions named. **Done 2026-10-25** (`scripts/seat_survey.py`; GAPS "Stage 2, the survey"): 207 of 263 entries carry `pid` (90 first, 102 last, 15 in the middle, so the slot is per entry, not positional); the exceptions reached from Python are `H.diplo_event` (a write as the active team), `H.plot_units` and `H.plots_around` (a caller-chosen team); every `Game` method resolves `pid=None` to `Game.seat`, the one attribute stage 3 replaces; 137 ad-hoc Lua bodies in Python: 49 front end, 40 screen buttons and probes, 48 `InGame` bodies to fold into named entries. |
| 3 | `{"op": "call", "fn": "H.<name>", "args": [...]}`: tunerd writes `H.<name>(<bound seat>, ...)` itself; the server's `Game.q` / `Game.lua` take that path on a bound connection and free Lua text is refused there; the ad-hoc call sites move into named runtime entries | the server plays a full turn loop through `call` only (fake-bridge tests and one live turn). **Done 2026-10-25** (runtime v285; `harness/lua_wire.py`, `dispatch.lua` with `H._seat_slot` generated at build, `Game.h` / `Game.hs`, tunerd `call` and `runtime` ops, `tests/test_seat_call.py`, 32 tests): every `InGame` read and write of the Python side is a named entry, the daemon installs the runtime itself, and a bound connection's Lua text is refused for `InGame` and forwarded to a screen state only while its seat is active. Seen live the same evening (Assyria t238, cold start): on a daemon without a table every read of a turn (`turn_status`, `units`, `cities`, `todo_actions`, `briefing`, `overview`, `league_status`, `trade_routes`, ...) came through `call`; on a daemon with a one-seat token table a tokened session read the same and its `generic_popup` screen read passed as the active seat, an untokened session was refused unbound, and a tokened `harness.cli lua` to `InGame` was refused with the named-calls hint. No turn was ended (the user's campaign); the live *turn* through `call` is the next session's first `finish_turn`. |
| 4 | the escape hatches connect like any client: `harness.cli lua`, `--allow-lua`, `scripts/mcp_call.py`, `scripts/mcp_session.py`; no bypass flag on a daemon with a table | from seat 0's sandbox, `mcp_call.py --seat 1 overview` and `cli lua` are refused at the daemon, live. **Done 2026-10-25** (`Game.bound_seat`; `tests/test_seat_escape_hatches.py`, 9 tests): a server whose connection is bound plays the binding and nothing else. A different `--seat` (what `scripts/mcp_call.py` and `scripts/mcp_session.py` pass as `CIV5_SEAT`) is refused on every tool, naming the binding and the fix, instead of being overridden in silence; `set_seat` onto another seat is refused with `bound` and `set_seat()` lands on the binding without asking the engine; `detect_seat` returns the binding; the raw `lua` tool (`--allow-lua`) refuses before any trip; and the harness client without a token is unbound, so there is no flag to bypass. Seen live at Assyria t238 from this sandbox on a one-seat token table: `mcp_call.py --seat 1 overview` refused, `set_seat(1)` refused, `set_seat()` -> seat 0, `turn_status` as seat 0 fine, the `lua` tool refused, a tokened `cli lua` refused at the daemon, an untokened `mcp_call.py` and `cli lua` refused unbound; tunerd was restored without a table. Still to see: the same refusals from a *second* agent's sandbox in a two-agent hotseat (stage 5). |
| 5 | the two-agent recipe: one sandbox or OS user per agent holding its token, `docs/AGENT_INSTALL.md` (Codex registered with `--seat auto` for solo play, a pinned seat and a token for a shared hotseat, the reason stated once for every client), `docs/PLAYBOOK.md`, one README "Fair play" sentence, `docs/LIMITATIONS.md` on the shared display and the save files | a two-agent hotseat played a few turns on bound sockets with the usual loop unchanged. The words are written (2026-10-25: `docs/AGENT_INSTALL.md` "Two agents, one game", `docs/PLAYBOOK.md`, README "Fair play", `docs/LIMITATIONS.md` on the shared display and the save files). **Done 2026-10-25** (seen live the same night): the Alpha/Bravo hotseat (S2a, t229, loaded on a plain daemon after the Assyria game was quick-saved as `Ashurbanipal_0238 pre-stage5`) on a two-seat token table, one process per seat holding only its own token in its environment (`scripts/play_loop.py --seat N`, the `Game` object bound through the one client; the two processes were one OS user on one machine, so the token secrecy was organisational, as the words say it must be): the usual loop unchanged, blockers resolved, a Settler queued, two promotions, seat 0 ended t229-t231 and seat 1 t229-t230 in under a minute (the AI round between humans is short in this game), the tunerd log shows only `connection bound to seat N by token` and no refusal, and every turn end went through `call` on a bound daemon (the live turn through `call` stage 3 left open). From each agent's own process the eight escape-hatch probes landed as stage 4 says: a wrong pinned `--seat` refused naming the binding and the fix, `set_seat` onto the other seat refused with `bound`, `set_seat()` and `--seat auto` on the binding, `cli lua` to `InGame` refused with the named-calls hint, an untokened client refused unbound, the own seat's reads fine, and a seat's `units` read while the other seat is on screen answers `this seat is not active`. Saved as `Alpha-Bravo_0231 two-agents-bound`; the Assyria game reloaded after, tunerd restored without a table. |

Decisions taken in the first stage (2026-10-24): both identities, since they cost the same code -- a token in
a first `hello` (works across users and machines, needs a secret per sandbox) and the peer uid (nothing to
remember, needs one user per agent); the seat table is a file (a token on a command line is in every `ps`).
The token never appears in a tool reply, a refusal, the daemon's log, the call ledger or the spectator (the
no-other-seat-metadata rule holds for it too); the daemon warns when the table file is readable by others.
What stage 1 does not do: scope the Lua. A bound connection still sends free text and tunerd still forwards
it; the binding is only *known* at the daemon (`Bridge.handle(req, seat=...)`) until stage 3 uses it.

## The tool surface (model the game, not its buttons)

Raised 2026-10-25 by the Glama listing's marks (completeness 5/5, naming 4/5, disambiguation 3/5, tool
count 1/5: 145 tools against a rubric that wants 3 to 15). Tracking issue #59 holds the model: a game
is a clock, a world of objects each carrying the actions the engine allows right now, the questions the
game asks, my notebook and the session, so the surface is nine tools -- `turn`, `inspect(what, id, view)`,
`order(to, id, action, args)`, `question`, `answer`, `notebook`, `batch`, `session`, `reference` -- and
every reply that lists what can be done hands back the `order` / `answer` row itself instead of a prose
hint. A new feature is a new view or action, never a new tool. Every one of the 145 names stays callable
through a retirement map (checked by script: each maps to exactly one row). Python and docs only; the Lua
runtime does not move except for one text-only bump at the end. A first draft that folded families into
enums (ac28a1b, 87 tools plus a hidden tier) was dropped the same day as still modelling the interface.
Planned on GitLab 2026-10-25: milestone [2.0.0 The tool surface](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/milestones/11), tracking issue [#59](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/59), one issue per item: stage 0 #44; stage 1 #45 (todo rows), #46 (question-shaped reads and the gate's rows), #47 (`available_*`, object reads, the live turn from rows); stage 2 #48 (`harness/surface.py`), #49 (`oneOf` on three clients), #50 (the retirement map), #51 (gate, ledger, tool sets, spectator), #52 (unregister the 145); stage 3 #53 (instructions and playbook), #54 (the other docs), #55 (`tests/test_tool_surface.py`); stage 4 #56 (the two live sessions); stage 5 #57 (the runtime strings), #58 (release 2.0.0 and the Glama marks). Work proceeds from the issues, in that order; this table is the summary. The plan document (`docs/TOOL_SURFACE.md`) was folded into the issues the same day and deleted: #59 carries the model, the vocabulary, the touch list and the risks, #50 the mapping table from each old name, #44 the baseline count, #48 the action and view tables; the issues are linked in dependency order.

| Stage | Work | Done when |
|---|---|---|
| 0 | `scripts/tool_survey.py`: catalog by module, listing size, every name's row in the mapping, the affordance audit (which replies carry `{tool, args}` rows, which carry prose) | its tables reproduce the baseline on #44, under `docs/measurements/`. **Done 2026-10-25** (`harness/surface/`: `vocabulary.py` the nine tools' words, `retirement.py` the 145-row map with argument renames, `survey.py` the counts and the listing's size, `audit.py` the affordance scan; `scripts/tool_survey.py --write` -> `docs/measurements/tool_survey.md`; `tests/test_tool_survey.py`): 145 tools / 35 zero-argument reads by module and the eight shapes reproduce #44 exactly, every name maps to one row and none is left over, the full listing is 110 KB (~27.6k tokens at bytes/4) and `--tools compact` 33 KB, the seam is 77 sites (the briefing's 11 todo sentences, the gate's 41 bare names, 25 refusal hints naming a tool), and of the 31 replies that list what can be done only `todo_actions` carries a `{tool, args}` row today. |
| 1 | affordances as data in today's vocabulary: todo rows, popup / discussion reads and every `available_*` reply carry `actions: [{tool, args}]`; `attention.py` reads only rows | a fake-bridge turn and one live Assyria turn play from affordance rows alone. **1a done 2026-10-25** (#45; `harness/affordances.py` is the one place a row is written: every `decisions` / `opportunities` row of `briefing` and `finish_turn(briefing=true)` carries `actions` -- the read as is, then the order, `choose` naming the arguments left to pick -- and the `todo_actions` summary's `actions` are the unit's orders themselves (one row per non-routine action, melee target, ranged target, promotion; a targeted mission as its targets read then the order); the prose `tools` map stays one release with `tools_note`; `attention.py` walks `actions` rows for any tool; the audit counts a reply calling into the module as rows (`briefing`, `finish_turn`, `todo_actions`); `tests/test_affordances.py` plays a fake-bridge turn from the rows alone and checks its own source types no tool name but `do`; seen live at Assyria t238: an Infantry's and a Worker's summary rows, the empty t238 briefing). 1b (#46) and 1c (#47) open. |
| 2 | `harness/surface.py`: the nine tools dispatching to the existing functions, per-action validation with a refusal that names the shape, `oneOf` on `order` (checked on Claude Code, Codex, Grok; string fallback), the retirement map with `renamed`, gate and ledger by `(tool, action)`, `--tools compact` and `call` retired, the 145 unregistered | `mcp_call.py --list` prints 9; the suite passes through the retirement map and again with it emptied |
| 3 | the words: instructions, PLAYBOOK, TOOL_REPLIES, AGENT_INSTALL, README, ARCHITECTURE; `reference("playbook", "orders")` prints the action table from the validator's own data; `tests/test_tool_surface.py` | the README teaches the loop in four lines: `turn` -> `question` -> `inspect` -> `order` |
| 4 | live: a full Assyria turn from a fresh Claude Code session and a fresh Codex session; `play_loop --profile` before and after | both reach a city-state gift and a league vote without a name they were not shown; trip count unchanged |
| 5 | runtime strings naming retired tools (one text-only `RUNTIME_VERSION` bump in a quiet window); release 2.0.0; re-submit to Glama and record the marks | the new marks sit next to today's on #59 and in the 2.0.0 changelog entry |
