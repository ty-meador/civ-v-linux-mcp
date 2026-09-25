# Road to 1.0.0

Reconciled `docs/GAPS.md` §0 against `harness/` at runtime v191 on 2026-09-24 (progress through v196 the same day: 0.2.0 closed, 13 of 29 issues closed): every open item is still open in code (grep-verified; the suite is at 401 passing, not the 391 the doc said). Planned on GitLab: milestones 0.2.0–1.0.0, one issue per gap with the game state that closes it, tracking issue [#29](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/29), board "Road to 1.0.0".

Order is by dependency: boundary first (nothing new may leak), then the trade table (its hotseat war/peace states feed 0.5.0), then the remaining screens, then live verification, then release hygiene. Package version follows the milestone; `RUNTIME_VERSION` keeps its own counter (see #26).

## Game states the plan depends on

| Key | Save | Used for |
|---|---|---|
| S1 | `single/Pocatello_0266 solo-final.Civ5Save` (Shoshone, Emperor, t266) | embassies, World Congress, spies, late-game culture/religion screens, city hovers |
| S2 | `hotseat/Alpha-Bravo_0227 peace.Civ5Save` (Korea vs Austria, Duel, Atomic, at peace) | PvP deals, peace with terms, third-party items, scratch-deal payload reads, greeting popup |
| S3 | ~~`single/quick/QuickSave` t230 (S2 + barbarian test units)~~ overwritten by a solo quicksave on 2026-09-24; rebuild from S2 with the Lua spawns in the *Hotseat 1v1 setup* memory note | fire support, modifier rows, captor visibility |
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
| [#5](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/5) | Peace with terms (gold, cities, resources) through the real screen | parity-write, area::trade, needs-game-state |
| [#6](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/6) | Third-party war/peace items and the Demand button | parity-write, parity-read, area::trade, needs-game-state |
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
| [#15](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/15) | Purchases in Venice's puppets | parity-read, area::city, needs-game-state |
| [#16](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/16) | ~~Specialist yields on the city screen~~ closed (v193) | parity-read, area::city |
| [#17](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/17) | ~~Help text on buildings the city already owns~~ closed (v193) | parity-read, area::city |
| [#18](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/18) | ~~Stored research on non-current techs~~ closed (v193) | parity-read, area::tech |
| [#19](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/19) | ~~Remembered terrain features under fog (last-seen cache)~~ closed (v196) | parity-read, area::map, needs-game-state |

## 0.5.0 Live verification

Reads with regression coverage only, closed by a live reproduction, plus the open turn-loop defect.

| # | Issue | Labels |
|---|---|---|
| [#20](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/20) | Live: nonzero melee fire support | live-verify, area::combat, needs-game-state |
| [#21](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/21) | Live: golden-age and rough-terrain combat modifier rows | live-verify, area::combat, needs-game-state |
| [#22](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/22) | Live: captured civilian with a visible captor, and capture by the other human seat | live-verify, area::combat, needs-game-state |
| [#23](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/23) | Bug: CityStateGreeting popup leaves ENDTURN_BLOCKING_UNITS with an empty todo | bug, area::turn-loop, needs-game-state |

## 1.0.0 Release

CI, semantic version and tags, CHANGELOG, docs refresh, save library, declared engine limitations.

| # | Issue | Labels |
|---|---|---|
| [#24](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/24) | Engine limitation: path overlay and movement cost | blocked-engine, area::map |
| [#25](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/25) | CI: run the regression suite on every push | release, area::infra |
| [#26](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/26) | Versioning: semantic version, tags, CHANGELOG, runtime-version mapping | release, area::infra |
| [#27](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/27) | Docs: README/ARCHITECTURE refresh and GAPS.md reduced to declared limitations | release |
| [#28](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/28) | Save library for the reproduction states | release, needs-game-state |
| [#29](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/29) | Road to 1.0.0 (tracking) | release |
