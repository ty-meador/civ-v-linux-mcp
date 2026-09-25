# Changelog

Two counters, on purpose (GitLab #26):

- **Package version** (`pyproject.toml`, git tag `vX.Y.Z`) follows the milestones in `docs/ROADMAP.md`:
  0.2.0 information boundary, 0.3.0 trade table, 0.4.0 screens before the decision, 0.5.0 live
  verification, 1.0.0 release.
- **`RUNTIME_VERSION`** (`harness/lua/runtime.lua`, read back by `harness/game.py`) counts injections of
  the Lua runtime. It goes up whenever `runtime.lua` changes, because the game keeps the old `H` table
  alive until a newer number arrives; a stale MCP server re-injects the version it started with.
  Commit subjects carry it as `runtime vNNN`, so `git log --grep 'runtime v'` is the full map.

Dates are the day the change was committed; "live tNNN" is the game turn it was checked on.

## Unreleased -- 0.3.0 trade table (in progress)

- **v202** The leader screen's Demand button: `demand(other, items)` through OnDemand / UI.OnHumanDemand /
  UI.DoDemand, their items only, refused at war or toward a human seat (#6; live t266, Darius refused).
  `trade_catalog.gold.note` explains the Brave New World rule that lump-sum gold needs a Declaration of
  Friendship (gold per turn is not gated).
- **v201** Venice buys in its puppets: `available_production` opens in purchase mode for a puppet when
  the player `MayNotAnnex()`, as the stock production popup does (#15; regression-tested, live check
  needs a Venice seat).
- **v200** Peace with terms through the real screens: `make_peace(other, items)` is `propose_deal` with
  the treaty on both sides; `trade_catalog().peace` is the Negotiate Peace gate with the locked-into-war
  reason (#5; live t237: Silk + Salzburg accepted by the other human seat).
- **v199** Third-party war and peace on the trade table, with the Other Players pocket as
  `trade_catalog.third_party` (#6; live t234). The AI-only Demand button stays open.
- **v198** World Congress vote commitments on the trade table, with the Diplomat requirement (#7; live
  t233).
- **v197** Switch Ideology: the unhappiness hover, the switch cost and the switch itself (#13; the
  enabled button is not yet seen live).
- **v196** Remembered terrain features under fog, a last-seen cache like the stock map's (#19).
- **v195** The Culture Overview swap tab (#12; live t270).
- **v194** Coup odds and grey reasons, the spy potential hover, the faith purchase pull-down (#9, #10, #11).
- **v193** The hovers behind the city screen meters, specialist yields, help on owned buildings, stored
  beakers on every tech (#14, #16, #17, #18).
- CI runs the regression suite on every push (`.gitlab-ci.yml`, locked `dev` group) (#25).
- Deals between human seats: `propose_deal`, `incoming_deal`, `accept_deal`, `refuse_deal` on the
  `SimpleDiploTrade` table; `load_save` finds hotseat and network saves (#4; live t227/t228).

## 0.2.0 -- information boundary (2026-09-24)

Nothing new may leak and no read may truncate.

- **v192** No rival tech list behind an embassy; deal city rows are reveal-gated and carry population
  (#1, #2, #8).
- Query chunking budgets escaped bytes, not characters: the tuner truncates at 2048 bytes (#3).
- **v185–v191** The first two-human hotseat: a standing move belongs to one seat, the stacked tile's
  units, the swap a move causes, deals between humans and the leader scene a proposal leaves behind,
  intercepted strikes, clamped previews, captured civilians named.

## 0.1.x -- the solo Shoshone game (2026-09-15 to 2026-09-23)

`RUNTIME_VERSION` v125–v184: the information-parity reads and writes built against a solo Emperor game
(Pocatello, t1–t266), each one opened because it was blocking a real decision and verified live the
same turn. `docs/GAPS.md` and `docs/SESSION_HANDOFF.md` hold the turn-by-turn notes.

## Runtime version map

Recent runtime versions and the commit that introduced each:

| Runtime | Date | Commit | Change |
|---|---|---|---|
| v201 | 2026-09-24 | `a6be7be` | Venice buys in its puppets (#15) |
| v200 | 2026-09-24 | `2d1d857` | peace with terms through the real screens (#5) |
| v199 | 2026-09-24 | `e0fef85` | third-party war/peace on the trade table (#6) |
| v198 | 2026-09-24 | `c3dd709` | World Congress vote commitments on the trade table (#7) |
| v197 | 2026-09-24 | `cfaa529` | the Switch Ideology button, its hover and the switch (#13) |
| v196 | 2026-09-24 | `da91929` | remembered terrain features under fog (#19) |
| v195 | 2026-09-24 | `e70930a` | the Culture Overview swap tab (#12) |
| v194 | 2026-09-24 | `6ca1580` | coup odds and grey reasons, the spy potential hover, and the faith purchase pull-down (#9, #10, #11) |
| v193 | 2026-09-24 | `153d0c0` | the hovers behind the city screen and stored beakers on every tech (#14, #16, #17, #18) |
| v192 | 2026-09-24 | `a8b2ce6` | no rival tech list behind an embassy, deal city rows reveal-gated and carry pop (#1, #2, #8) |
| v191 | 2026-09-24 | `8b07491` | intercepted strikes, clamped previews, captured civilians named |
| v187 | 2026-09-24 | `7190cf9` | deals between humans, and the leader scene a proposal leaves behind |
| v185 | 2026-09-24 | `3a5c6f0` | a standing move belongs to one seat |

<details><summary>v125–v184</summary>

| Runtime | Date | Commit | Change |
|---|---|---|---|
| v183–v184 | 2026-09-24 | `e33a166` | the stacked tile's units, and the swap a move causes |
| v182 | 2026-09-23 | `371e10c` | the greyed Gift Improvement button says why |
| v181 | 2026-09-22 | `2de406e` | the trade route screen's religion columns and gold hover |
| v180 | 2026-09-22 | `ce8887a` | World Congress names drop the choice's icon tag |
| v179 | 2026-09-22 | `bc33a3c` | the resource list's bonus stack, and the tile hover |
| v178 | 2026-09-22 | `48945fa` | the Happiness screen's rows, not just the totals |
| v177 | 2026-09-22 | `0b34980` | the tech tree's buttons, not just the paragraph |
| v176 | 2026-09-22 | `47e2603` | the World Congress screen's tooltips, not just the names |
| v175 | 2026-09-22 | `76318e4` | World's Fair progress on the league screen and the production row |
| v174 | 2026-09-22 | `f786ccd` | the city screen's meters, including a tile you cannot afford |
| v173 | 2026-09-21 | `d7c772f` | the Notification Log, not just the panel |
| v172 | 2026-09-21 | `2167b2a` | a finished build says what it changed, including the borders it moved |
| v171 | 2026-09-21 | `c2389d0` | the Change Home City chooser, for caravans and Great Admirals |
| v170 | 2026-09-21 | `81c9dc3` | a gift tier says whether it actually buys the alliance |
| v169 | 2026-09-21 | `dead011` | the production chooser says Zoo, not BUILDING_THEATRE |
| v168 | 2026-09-21 | `1b247f9` | an idle caravan says why it has nowhere to go |
| v167 | 2026-09-21 | `11d7c96` | what the unit-action button says it does |
| v165 | 2026-09-21 | `06b0ec6` | the Gift Improvement button, and the hexes it lights up |
| v164 | 2026-09-21 | `953b724` | say which great work a Great Person became, and where it went |
| v163 | 2026-09-21 | `c6a55e7` | refuse a move onto another player's city instead of letting it rot |
| v162 | 2026-09-21 | `27add30` | an idle spy is as invisible as an idle caravan used to be |
| v161 | 2026-09-21 | `406c756` | a missionary says which faith it carries, and a no-op spread says so |
| v160 | 2026-09-21 | `0c0ebcb` | a negative TurnsLeft is a blank column, not an overdue route |
| v159 | 2026-09-21 | `409367b` | buy_city_plot had the same puppet hole, and now a lint says so |
| v158 | 2026-09-21 | `ca9884b` | a puppet is not ours to run, and the inline-query budget was a guess |
| v157 | 2026-09-20 | `1ef40ec` | a captured-city row pointed at the wrong city |
| v156 | 2026-09-20 | `b57c0d0` | say why the turn will not end, in the engine's words |
| v155 | 2026-09-20 | `093cf6e` | turn_status and unit_mission agreed about stalled units |
| v154 | 2026-09-20 | `f1a4198` | steal_tech takes player_id like every other civ-targeting tool |
| v153 | 2026-09-20 | `bbaf461` | refuse an air strike the engine would ignore |
| v152 | 2026-09-20 | `c4de752` | the promotion chooser as a human reads it |
| v151 | 2026-09-20 | `d98b0b1` | itemised combat modifier rows on every preview |
| v150 | 2026-09-20 | `ac2dcd7` | include melee fire support and cap preview damage |
| v149 | 2026-09-20 | `4a40b14` | air-strike retaliation and ranged combat previews |
| v148 | 2026-09-19 | `79e2670` | tech/production help, nearby build turns, public opinion |
| v147 | 2026-09-19 | `8acb5c2` | incoming trade routes, score breakdown, WLTKD/blockade |
| v146 | 2026-09-19 | `f93bc4e` | worker job turns, CS quest list, plot construction tooltip |
| v145 | 2026-09-19 | `ee5ea13` | Military Overview unit supply and Economic Overview gold rows |
| v144 | 2026-09-19 | `c561ad5` | gold deficit flag and city-screen sell building |
| v143 | 2026-09-19 | `c477c08` | pending steal-tech in todo and on the notice |
| v142 | 2026-09-19 | `5a8943c` | conversion banner, empty-queue vs process, Discuss flags |
| v141 | 2026-09-19 | `436e356` | top-bar science/culture/tourism/faith; combat result holes |
| v140 | 2026-09-19 | `e5ec3dd` | map index, named deal cities, CS unit gift |
| v139 | 2026-09-19 | `53fda00` | remaining information-parity reads |
| v136 | 2026-09-19 | `7325f84` | docs: notes + handoff through t150 |
| v136 | 2026-09-19 | `30e6363` | attack_targets / move_unit: a garrisoned enemy city is fought as the city; result says city_captured |
| v135 | 2026-09-19 | `7846f17` | move_unit: a captured civilian reports captured + the new unit id, not defender_killed |
| v134 | 2026-09-19 | `cad1951` | docs: notes + handoff through t100 |
| v134 | 2026-09-19 | `5e7b5c8` | free_great_person_options / choose: only this civ's own great people |
| v133 | 2026-09-19 | `b1bae90` | unit_mission builds: name the build in progress and its turns left; say when a feature removal runs first |
| v132 | 2026-09-19 | `2192fe0` | disband_unit: say when the refusal is 'no moves left this turn' |
| v131 | 2026-09-19 | `1907dcb` | move_unit / resume_moves: refuse a destination held by a civ we are at peace with |
| v130 | 2026-09-19 | `4ff285a` | available_city_strikes: target hp + expected damage (UpdateCombatOddsCityVsUnit) |
| v129 | 2026-09-19 | `f752d7a` | docs: notes + handoff through t33 |
| v129 | 2026-09-19 | `c47e282` | unit_mission: a refused order keeps the unit's standing move |
| v128 | 2026-09-19 | `9dfbbbe` | docs: notes + handoff through t19 |
| v128 | 2026-09-19 | `6f5d2fc` | religion_overview: rival pantheons as the Beliefs tab lists them |
| v127 | 2026-09-19 | `2959d92` | city_capture_options / choose_city_capture: BUTTONPOPUP_CITY_CAPTURED with unhappiness deltas + warmonger preview |
| v126 | 2026-09-19 | `77a1078` | war_consequences: the declare-war confirmation's warnings as a read |
| v125 | 2026-09-19 | `7d49e36` | docs: notes + handoff through t11 |
| v125 | 2026-09-19 | `8739bcd` | city_state_actions / city_state_action: quests, pledge, tribute, war and peace as the city-state screen does them |
| v124 | 2026-09-19 | `4ff475d` | trade_catalog: a tradeable city's x,y only once its plot is revealed |
| v123 | 2026-09-19 | `2fc3250` | religion_overview: the Religion Overview screen's three tabs, unmet founders masked |
| v121 | 2026-09-19 | `67b3f8e` | attack previews for city assault and ranged shots; enemy-city melee listed and never stored as a standing move |
| v119 | 2026-09-19 | `5345a35` | available_beliefs + add_reformation_belief; found/enhance validate each belief against its slot's available list |
| v118 | 2026-09-19 | `fcf3cb6` | goody_hut_options / choose_goody_hut: Shoshone Pathfinder ruins choice via Network.SendGoodyChoice |
| v117 | 2026-09-19 | `a7ced23` | league_status votable: yes_no flag; luxury bans name the resource and our count |
| v116 | 2026-09-19 | `c1814d7` | incoming_deal: say whether a luxury we would receive is new to us |
| v115 | 2026-09-19 | `979328c` | culture_overview tool; civ_eliminated digest event |
| v87 | 2026-09-18 | `ad98816` | Combat provenance in turn_digest: named attacker/defender, plots, hp; hp-diff fallback across the AI phase |
| v83 | 2026-09-17 | `4ea6311` | unit_mission: refuse MISSION_SKIP on a unit mid multi-turn move |
| v82 | 2026-09-17 | `ba6e6a1` | city_state_gifts: rivals influence list |
| v81 | 2026-09-17 | `9c8d4a5` | incoming_deal: us_owned undoes export-net totals; renewals are not last copies |
| v80 | 2026-09-17 | `499b7b3` | incoming_deal: resource items we would give carry copies/import/export and last_copy |
| v79 | 2026-09-17 | `87804b3` | available_production: faith rows listed before they are affordable, faith_can_buy |
| v78 | 2026-09-17 | `38987ea` | available_production: faith purchase costs and faith-only rows |
| v77 | 2026-09-17 | `e3f469c` | cities: majority religion name |
| v76 | 2026-09-17 | `bd95025` | explore_frontier: reachability respects borders |
| v75 | 2026-09-17 | `892efb2` | generic_popup / answer_popup: drive the game's yes/no confirmations |
| v72 | 2026-09-17 | `455d983` | explore_frontier: reachable flag via flood fill over the revealed map |
| v71 | 2026-09-17 | `469290f` | disband_unit: COMMAND_DELETE with polled confirmation and measured effects |
| v69 | 2026-09-17 | `7f72ec1` | overview: strategic_resources with available/total for revealed resources |
| v67 | 2026-09-17 | `7ff0363` | trade_catalog: per-resource copy counts and last_copy luxury warning |
| v65 | 2026-09-17 | `1621921` | explore_frontier: flag polar map_edge plots |
| v63 | 2026-09-17 | `aa7ccd2` | unit_mission: measured effects for MISSION_SPREAD_RELIGION / REMOVE_HERESY |

</details>
