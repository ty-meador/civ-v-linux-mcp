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
| next | `unit_mission` trips: a plain order is 2 (order + `unit_pos`, 0.88 s live S1 t272), a refused one 3 (it explains itself with `available_unit_actions` + `units`). The loop's 93 trips for ~13 orders were the automate path's confirmation poll (up to 12 x 0.25 s `automate_check`) and refusals, not selection retries. Worth a look: `AUTOMATE_BUILD` confirming in one read, and `do` skipping `unit_pos` on all but the last order of a batch | open, `--profile` shows it |
| later | LAN mode since 0.5.0 and `declare_war` on a city-state syncing over LAN (`docs/LIMITATIONS.md`) | needs a LAN game |
| later | Game over: `turn_status.game_over` against a stale PRODUCTION blocker, seen once at t457, no regression state | needs a finished game |

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
Tagged `v1.6.0` 2026-09-27 (runtime v242, 1000 tests). 1.7.0: #43 the size of the `finish_turn` reply (1055 tests, no runtime change): measured by replaying the #36 replies through the new composer and by playing the same t48-t51 save live again, 26% off the wait reply, a third on turns with open orders (`docs/NOTES.md`). Tagged `v1.7.0` 2026-09-27 (runtime v242, 1055 tests).
