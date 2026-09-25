# Road to 1.0.0

Reconciled `docs/GAPS.md` §0 against `harness/` at runtime v191 on 2026-09-24 (progress through v201 the same day: 0.2.0 closed, 0.3.0 complete and tagged, 22 of 29 issues closed or declared): every open item is still open in code (grep-verified; the suite is at 401 passing, not the 391 the doc said). Planned on GitLab: milestones 0.2.0–1.0.0, one issue per gap with the game state that closes it, tracking issue [#29](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/29), board "Road to 1.0.0".

Order is by dependency: boundary first (nothing new may leak), then the trade table (its hotseat war/peace states feed 0.5.0), then the remaining screens, then live verification, then release hygiene. Package version follows the milestone; `RUNTIME_VERSION` keeps its own counter (see #26).

## Game states the plan depends on

| Key | Save | Used for |
|---|---|---|
| S1 | `single/Pocatello_0266 solo-final.Civ5Save` (Shoshone, Emperor, t266) | embassies, World Congress, spies, late-game culture/religion screens, city hovers |
| S2 | `hotseat/Alpha-Bravo_0227 peace.Civ5Save` (Korea vs Austria, Duel, Atomic, at peace) | PvP deals, peace with terms, third-party items, scratch-deal payload reads, greeting popup |
| S2b | `hotseat/Alpha-Bravo_0237 peace-terms.Civ5Save` (Bravo's t237, right after accepting peace + Silk + Salzburg; treaty to t247, deal to t262) | the ceded city's first turns, the peace-with-terms deal rows, a fresh 10-turn forced peace |
| S3 | `single/Pocatello_0266 combat-lab.Civ5Save` (S1 + barbarian Warrior on the hills at 49,18, Archer at 48,18, raider at 47,13 beside a sleeping Worker; Musketman 630799 has Drill I) -- replaces the overwritten t230 hotseat quicksave | modifier rows, captor visibility (fire support is off in stock BNW) |
| New | hotseat with Venice in a human seat | puppet purchases (#15) |

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
| [#13](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/13) | Change ideology: unhappiness hover, switch cost, and the switch itself | parity-read, parity-write, area::culture, needs-game-state |
| [#14](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/14) | ~~City screen: per-yield hover breakdowns~~ closed (v193) | parity-read, area::city |
| [#15](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/15) | Purchases in Venice's puppets -- catalog landed v201 (regression-tested); live check needs the Venice hotseat | parity-read, area::city, needs-game-state |
| [#16](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/16) | ~~Specialist yields on the city screen~~ closed (v193) | parity-read, area::city |
| [#17](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/17) | ~~Help text on buildings the city already owns~~ closed (v193) | parity-read, area::city |
| [#18](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/18) | ~~Stored research on non-current techs~~ closed (v193) | parity-read, area::tech |
| [#19](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/19) | ~~Remembered terrain features under fog (last-seen cache)~~ closed (v196) | parity-read, area::map, needs-game-state |

## 0.5.0 Live verification

Reads with regression coverage only, closed by a live reproduction, plus the open turn-loop defect.

| # | Issue | Labels |
|---|---|---|
| [#20](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/20) | ~~Live: nonzero melee fire support~~ closed as declared limitation: `FIRE_SUPPORT_DISABLED = 1` in stock BNW, engine returns no support unit even with every gate satisfied (S1 t266) | live-verify, area::combat, blocked-engine |
| [#21](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/21) | Live: golden-age and rough-terrain combat modifier rows -- rough/open terrain and flanking rows live S1 t266; golden-age row needs a Persian seat in a golden age (trait modifier), declared | live-verify, area::combat, needs-game-state |
| [#22](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/22) | Live: captured civilian with a visible captor (done S1 t267, v203 fixed the notice-first ordering and the stale roster plot), and capture by the other human seat (open: needs S2b at war, t247+) | live-verify, area::combat, needs-game-state |
| [#23](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/23) | Bug: CityStateGreeting popup leaves ENDTURN_BLOCKING_UNITS with an empty todo -- did not reproduce t237 (Bravo, greeting pending with a nonempty todo: finish_turn swept it and the turn ended); the empty-todo case still needs its state | bug, area::turn-loop, needs-game-state |

## 1.0.0 Release

CI, semantic version and tags, CHANGELOG, docs refresh, save library, declared engine limitations.

| # | Issue | Labels |
|---|---|---|
| [#24](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/24) | ~~Engine limitation: path overlay and movement cost~~ declared in `docs/LIMITATIONS.md` (with fire support, lump gold, LOS, forced peace) | blocked-engine, area::map |
| [#25](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/25) | ~~CI: run the regression suite on every push~~ resolved locally: no shared GitLab runner minutes for this project, so `scripts/check.sh` (locked `dev` group + pytest) is the pre-push check and `.gitlab-ci.yml` was removed 2026-09-25 | release, area::infra |
| [#26](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/26) | Versioning: semantic version, tags, CHANGELOG, runtime-version mapping -- `CHANGELOG.md` added with the two-counter rule and the runtime map; tags start at the 0.3.0 cut | release, area::infra |
| [#27](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/27) | Docs: README/ARCHITECTURE refreshed 2026-09-25; declared limitations split out to `docs/LIMITATIONS.md`, GAPS.md kept as the audit log | release |
| [#28](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/28) | ~~Save library for the reproduction states~~ `saves/` holds S1, S2, S2a, S2v, S2b, S3 with a README | release, needs-game-state |
| [#29](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/29) | Road to 1.0.0 (tracking) | release |
