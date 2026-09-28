# Information-parity gaps (human seat vs LLM)

> This is the live audit log, turn by turn. The short list of what the harness will not do, and why, is
> `docs/LIMITATIONS.md`; the plan is `docs/ROADMAP.md`; the saves every claim names are in `saves/`.

Date: 2026-09-24 (runtime **v191**, source audit rechecked). The open list is §0. Goal: the LLM should have the same information a human in this seat would have, in every situation. Rule 2 still holds: never more than that (fogged tiles carry no live occupants, unmet identities stay masked, no private AI state). §0 includes two remaining information leaks; the earlier fixes do not establish blanket privacy parity.

This is a **read** audit. Action-only holes are listed only where they also hide information a human gets by opening the same screen.

`docs/COVERAGE_AUDIT_2026-09-19.md` is partly stale. Most of its ranked list was implemented during the Shoshone game. v137 used this save as a feedback loop: open the screen that was blocking a real decision, implement it, verify live, play the turn.

Sources: `harness/mcp_server.py`, `harness/lua/runtime.lua` (`H.*` snapshots), `harness/game.py`, stock BNW UI.

**Writing a new read or write:** the tuner truncates an inbound command at 2048 bytes (measured t193). `Game.q_fits_inline()` measures the encoded, wrapped command and `Game.string_chunks()` cuts on escaped bytes, so a Unicode or escape-heavy body is chunked correctly (fixed for GitLab #3; before that the check counted characters and cut at 1500 of them before escaping). A two-line guard added to `set_production` previously caused a bare "Syntax Error" through wrapper overflow. Live notes: this file (t163–176) and `docs/NOTES.md`.

## One player at both seats: the server in parts, live t135-t137 (2026-09-27, Venice/Mongolia hotseat)

Game relaunched cold (the game process had died; tunerd survived), `load_latest` at t135, both seats played by
one operator through fresh servers (`scripts/mcp_session.py --seat N`). What the rounds turned up, each fixed
the same day (CHANGELOG "the server in parts"):

- `load_latest` failed on the popup shim's path: the mixin split had moved `LUA_DIR` into `game_parts/`.
- Seven reads (`todo_actions`, `notification_log`, `revealed_map`, the `*_options` readers) claimed the turn
  and were refused under popups: the server's hand-kept read list had drifted from the ledger's.
- `python -m harness.mcp_server` served no tools after the tool-module split (the `__main__` copy); the first
  stdio client caught it. `tests/test_stdio_server.py` now runs the real server.
- The 300 s wait for seat 0 timed out inside one AI round (t135 -> t136 took over five minutes); the gate
  said only "seat 1 is on screen". Runtime v246 adds `active_turn_active` and the gate names the AI round.
- At seat 1's t136 start three AI offers were queued (a luxury for 6 gpt + embassy, Portugal's and Russia's
  open-borders renewals). The gate said `respond_discussion` for a trade table (no buttons): `turn_state`
  popped `trade_state` off the status. Fixed; `accept_deal` / `refuse_deal` / `dismiss_discussion` now hand
  over the next queued leader (`next`, `gate`).
- The `expiring_deals` hint sent the seat into a refusal on the deal's last turn (the committed copy is not
  spare until the deal has ended): reworded, runtime v245/v247. The renewal went through the turn after
  (Ivory for 4 gpt to t161, accepted).
- "Trespassing in Kiev!" (t137, Mongolia) named the city-state and no read said which unit; a human sees the
  border under the unit. Runtime v248: `units()` rows and `tactical_view.unit` carry `territory`
  {player_id, owner, city_state} on another player's land.
- ~~Open: Venice t139-t142 cannot train a Caravan or Cargo Ship~~ **Closed runtime v252 (2026-09-27).** The
  engine's gate (`CvPlayer::canTrain` -> `CvPlayerTrade::GetNumTradeRoutesRemaining(false)`) is routes possible
  minus trade units alive minus trade-unit orders queued in any of the player's cities
  (`CvCity::getNumTrainUnitAI(UNITAI_TRADE_UNIT)`, puppets included); `Player:GetNumInternationalTradeRoutesUsed`
  is the alive half only, and no Lua accessor gives the remainder (`GetNumAvailableTradeUnits(domain)` is the
  top bar's idle count -- checked live t154, both seats 0). `H.trade_unit_count` reads the queues the way the
  engine does: `overview.trade_units_queued`, `free_trade_route_slots` = available - used - queued, the
  `trade_note` routes idle units and builds for the empty slots (an idle caravan holds a used slot, it never
  covers a free one -- the v249 note said the opposite), `compare` and `set_production` name "N alive + Q
  queued of P" when the engine refuses. Live t154: Mongolia 5 alive of 5, `CanTrain` false; Venice 4 alive of 8
  with nothing queued, `CanTrain` true. The queued term is from the engine source and the t139 refusal is
  explained by it only if Venice's queue then held trade orders, which no record shows. Confirmed live
  2026-09-27 (solo Babylon t24, 1 slot): a Caravan appended behind the Library gave `trade_units_queued: 1`,
  no `free_trade_route_slots`, the "in production fill the last slot(s)" note, and both `compare` and a second
  `set_production` refused with "0 alive + 1 queued of 1".
- ~~Open: the `unit` on a route row can be swapped between two caravans from one origin~~ **Closed runtime v252
  (2026-09-27).** The engine's route rows name cities, not units (`Player:GetTradeRoutes` has no unit field;
  `GetInternationalTradeRoutePlotMouseoverToolTip` on the caravan's plot names only "codex: Venetian Caravan",
  checked live t154 on all nine caravans of both seats). So the binding is remembered: the first read that
  finds an automated trade unit on exactly one open route's line records unit -> route in `H.route_units`
  (carried across re-injection; a second caravan then fits one route by elimination), and later reads keep it
  while the unit is still an automated trade unit on that line and the route is the same instance
  (`turns_left` counting down from the recorded turn). `unit.matched` says `recorded`, `line` (recorded now)
  or `line_ambiguous` (shared plots, nothing recorded yet). Also observed t142: `trade_routes_used` 5 of 5
  with an idle sixth caravan and the engine still accepted its route -- consistent with the rule above: the
  cap gates training, not `CanCreateTradeRoute`.
- Open: nothing removes one item from a city's production queue (the city screen's click-to-remove);
  `set_production` replaces the head or appends, and re-setting the head answers "already in this city's
  production queue". The engine path is `city:PopOrder(index, 0, 0)` (0-based; the Lua binding wants numbers,
  not booleans, for the finish/choose flags; `Network.SendPopOrder` and `Game.CityPopOrder` do not exist in
  this build) -- used by hand on 2026-09-27 to drop the test Caravan above. A `remove_from_queue(city_id,
  position)` tool is owed.
- Three first-meeting greetings queued at seat 0's t145 start (a cargo ship reached a new shore: England,
  Babylon, Portugal); `dismiss_discussion` closed one per call and answered ok=false with the next one up.
  It now clicks through the queue (`closed_count`), stopping at a real question.
- `set_production` then `end_turn` in one batch (t139, Mongolia) was refused with PRODUCTION named and no
  empty city: the engine re-reads the blocker on its next update. `end_turn` re-sends once against a stale
  blocker (`resent` in the reply).
- The briefing's idle-caravan row printed `id: null` (rows say `unit_id`); fixed.
- An embassy swap read as "expiring" the turn it was signed (t145; permanent items have duration 0): runtime
  v250 counts only timed items. A policy that could be adopted was not on the checklist while the engine
  named PRODUCTION first (t149): runtime v251 adds `todo.policy` and the briefing's `policy` decision.
- Verified on the way: `do` batches (production + trade route + automate), `compare(kind="trade")`,
  `city_state_gifts` -> `minor_gold_gift` (Tyre 31 -> 51), `set_production` refusing an unknown prefix
  readably, `how_to_play` over stdio without a game.

## #42 smoke: the split runtime injected over a live game (2026-09-27, Venice/Mongolia hotseat t52-t53)

Save: the t52 quicksave of the Venice/Mongolia hotseat (played from `Venice-Mongolia_0048 orders-validated`, the 1.5.0
measurement's starting point); the game had runtime **v227** (digest `2c55093135800a0f…`) from the 1.5.0 session.
Fresh client (`scripts/mcp_session.py --seat 0`), one `turn_status` call: v227 -> **v241** (digest `993e8e864b5d…`),
carrying the 56 recorded events (same Lua table), `event_seq` 56, 18 hook closures, rosters for two seats, one hp
snapshot, known sites, `alive_majors`; `_enum_names` and `_ns` rebuilt (`_ns` 25 shared names). Reads: `briefing`,
`cities`, `units`, `orders` (10 and 12 active), `available_research`, shapes unchanged. Action: `set_research`
Trapping -> Masonry -> Trapping (`Network.SendResearch`; re-setting the current tech is refused as before).
`Game.ensure_runtime(force=True)`: 59 s, every carried field identical afterwards, `_enum_names` back to empty.
Hand-off: seat 0 `end_turn`; seat 1 `wait_for_my_turn` (`turn_seat` 1, events 62, a city-state greeting screen
gated `end_turn` until the wait closed it), `set_production` Caravan, `end_turn`; seat 0 `wait_for_my_turn` gave
t53 (`turn_seat` 0, events 67, still 18 hooks) and `briefing(since="turn")` listed the turn's four events and the
empire deltas. Found: the game's Lua prints chunk names verbatim (`=turn.lua:379:`), fixed in **v242** (digest
`39160f69215ee3898516c848dd5bd40c900e1606f5186771b290688d68bee0c1`), re-injected live at t53: `turn.lua:379:`,
`city_views.lua:405:`. Not repeated: the LAN hand-off (no LAN table was up). Wheel built and installed in a venv
outside the repository assembled all 38 fragments (version 242, 601,102 bytes).

---

## Implemented coverage (remaining exceptions in §0)

Implemented areas include the play loop, fog/met guards, combat previews (melee vs unit and city, ranged, city bombard, interception on the strike result), religion / culture / league / spy overviews, trade catalog + current table, diplomacy and relationship (visible approach, opinion lines, public relations), war-declaration consequences, city-capture options with unhappiness and warmonger text, city-state gifts/quests/pledge/tribute and the tile-improvement gift, spaceship progress including rivals who finished Apollo, explore-frontier, and reasons for refused actions. These are coverage summaries, not claims that every field or case is complete. Versioned live results below are historical; current exceptions and verification limits are in §0.

**Landed v137 (live on Pocatello t163):** city screen; top-bar luxuries / happiness / gold / golden-age meter; plot yields + fresh water + worked; own-unit promotions / XP-to-next / upgrade preview; visible-plot unit strength+promotions and city banner (strength, garrison, puppet/razing, majority religion); specialist GP meters on `city_screen`; fogged plots no longer leak live `GetFeatureType`.

**Landed v138 (live on Pocatello t173):** `tech_tree` (have / current / available / unavailable+prereqs+missing; embassy rivals’ ahead techs, now identified as an information leak in §0); `current_deals` (who, items, turns remaining — LoadCurrentDeal only while scratch is empty, then ClearItems).

**Landed v139:** foreign visible-city `religions` (followers/pressure/holy city, majority+followers only); `great_person_progress` (city specialist meters + national General/Admiral + Prophet faith); `change_specialist` / `set_auto_specialists`; `archaeology_options`/`choose_archaeology` and `maya_options`/`choose_maya_bonus`; `unit_mission_targets` (visible rebase/paradrop/airlift/nuke/airstrike; fog never queried); `domination_progress`, `wonder_overview` (locations only in sight), `espionage_intrigue`, `city_state_bonuses`, `demographics` (public aggregates; unmet best/worst identities masked), `culture_works`. Partial-move stalls now appear in `turn_status` todo.

**Landed v140:** `map_index` (revealed luxuries/strategics, camps, ruins, met foreign cities, visible natural wonders, in-sight world wonders); deal `CITIES` items now carry `name`/`city_id`; `gift_unit_options` / `gift_unit` (`CanDistanceGift` + `Network.SendGiftUnit`).

**Landed v141 (live on Pocatello t178):** top-bar `science_breakdown` / `culture_breakdown` / `tourism_breakdown` / `faith_breakdown` (toppanel.lua Science/Culture/Tourism/FaithTipHandler); `gold_breakdown` now splits city output vs international trade routes and includes religion/traits gpt. Combat: city-strike/ranged kill now reports `damage_dealt` (remaining hp of the vanished defender); `MISSION_PILLAGE` / `MISSION_PILLAGE_ROUTE` return `effect.gold_gained`.

**Landed v142 (live on Pocatello t179–180):** conversion notices attach the city-banner tooltip (`religions` + majority, or a tie note when none); empty production is no longer labelled as Wealth/Research; `religion_overview` pressure uses banner units (raw / multiplier); `relationship.discuss` lists the Discuss-screen buttons a human would see (share intrigue, stop spreading, stop spying, don’t settle, stop digging, declare friendship).

**Landed v143 (live on Pocatello t181):** `turn_status.todo.steal_tech` lists the pending spy-steal chooser even when `blocking_name` is still POLICY (engine reports one blocker at a time; a human still sees the Steal Technology notice). The notice itself now attaches the victim and tech list (`TECH_SAILING` from Inca). `steal_tech_options` / `steal_tech` were already the write path.

**Landed v144 (live on Pocatello t182):** `gold_breakdown.losing_science_from_deficit` when gold+GPT < 0 (top-bar “expenses come out of science”; `IsStrike` was still false at −23). Losing Gold notice attaches gold/GPT/strike. City-screen sell: `city_screen` buildings carry `can_sell`/`sell_gold`/`gold_maintenance` (puppets omitted); `sell_building` → `Network.SendSellBuilding`. Live: two Airports (100g/5 maint each) + two Colosseums (25g) → 250g, gpt −23→−11.

**Landed v145 (live on Pocatello t183):** Military Overview unit supply on `overview.unit_supply` (cap split handicap/cities/population, remaining or deficit + production_penalty). Economic Overview unit-maintenance tooltip on `gold_breakdown.expenses` (`unit_paid` / `unit_free` / `unit_cost_per`). Per-city `building_maintenance` and `connection_gold` on `cities()` (connection gold only when already connected; the getter still returns a number for an unconnected city). `units().garrisoned`. Live: 24/37 supply remaining 13; 22 paid units at 2.36g; Goshute/Pohokwi/Tiwanaku unconnected.

**Landed v146 (live on Pocatello t182/t183):** Unit-panel worker job on `units()` (`build` + `build_turns_left`, matching “Trading Post (6)”). Plot hover: `under_construction`, `trade_route`, `lake`, `resource_requires_tech` when TechCityTrade is missing. City-state screen `quest_list` (type, turns, contest scores, kill-camp x/y only when the camp is revealed) plus the same overlay on camp plots / `map_index.camps`. Live t182: lumbermill 3t matches the plot; Lhasa SPREAD_RELIGION Tengriism; Sidon faith contest 811 vs 966 (6t) + FIND_NATURAL_WONDER + Great Admiral; Wittenberg faith contest leading 225 (26t) + Pyramids. `Plot:MovementCost` crashed the t183 process — do not call it. Recovered from `Saves/single/quick/QuickSave` (t182 after the Airport/Colosseum sales and Lhasa gift).

**Landed v147 (live on Pocatello t182):** Trade Route Overview `incoming` (`GetTradeRoutesToYou`, unmet owners omitted). Score tooltip on `overview.score_breakdown` (cities/pop/land/wonders/techs/policies/great works/religion). City banner `blockaded` / `wltkd_turns`. Live: two caravans Moson Kahni/Te-Moak → Addis; Inca sea route Cusco → Tiwanaku (incoming); score 606 = 64 cities + 171 pop + 104 land + 112 techs + 44 policies + 4 GW + 107 religion; Tiwanaku WLTKD 6t; no blockade.

**Landed v148 (live on Pocatello t182):** `available_research` / `available_production` carry the Civilopedia/chooser `help` text. `nearby_builds.build_info` has unit-panel turns and yield_delta. `overview.public_opinion` is the Policy/Culture Overview opinion (NO_PUBLIC_OPINION until an ideology). CS screen `gift_tile_improvement` can/cost (write still closed). Live: Steel “Longswordsman + Armory”; pasture on horses 6t +1 production; forest farm −1 production +2 food; CS tile gift 200g, can=false.

**Landed v149 (live t182, 134 tests passing):** Ranged previews now include both combat strengths, using the stock panel's embarked/naval/support-fire defense branches. Air strikes report target retaliation instead of zero, visible interceptor count, and the stock interception warning even when that count is zero. Interception damage is excluded from the estimate. `unit_mission_targets` air-strike pages include the same visible target details/preview as `ranged_targets`; fog, invisible units, and peaceful occupants are excluded from those details. City targets preview the city, not its garrison. After harness launch/load, 13 live previews matched the stock combat panel's displayed damage and strengths exactly: bomber/fighter/bow against visible city, pikeman, crossbowman, worker, warrior. At peace these are Alt-hover-equivalent reads; the public bomber target tool correctly returned empty. At v149 a nonempty legal target page and nonzero interceptor count still needed live coverage; the v185–v191 hotseat supplied both later.

**Landed v150 (live t182, 139 tests passing):** Melee previews against units and cities include `fire_support_damage`, applied before calculating damage dealt and added to damage taken, matching `EnemyUnitPanel`. Only the displayed damage is exposed, never the supporting unit's identity/location. Failed support reads leave damage unknown. Melee estimates are capped at the panel's maximum HP (unit or city), not remaining HP. All 115 live comparisons matched stock damage and strengths: 5 owned melee units × 23 visible targets (95 unit / 20 city cases), including 27 outgoing unit estimates capped at 100. All support reads were zero; nonzero support remains regression-tested only. No gameplay orders or turn advance.

**Landed v151 (live t182, 157 tests passing):** The panel's itemised combat-modifier rows. `H.combat_modifiers` / `H.city_strike_modifiers` port every row of `UpdateCombatOddsUnitVsUnit` / `UpdateCombatOddsUnitVsCity` / `UpdateCombatOddsCityVsUnit` -- same conditions, same text keys, same arguments, same order, same column -- and hang off every melee, ranged and city-strike `preview` as `modifiers.mine` / `modifiers.theirs`. Rows carry the localized `text`, the `value`, `percent`, and the raw `key`; the panel's value-less rows (both interception warnings, the visible-AA count, the capture chance) come through as notes without a value. A modifier that cannot be read drops its own row rather than being reported as a zero. Also fixed on the way: `available_city_strikes` capped its estimate at the target's *remaining* hp where the panel caps at the unit's maximum hp (the v150 fix had not reached this path), and it now reports both strengths (`GetStrengthValue` / `RangeCombatUnitDefense`) as the panel prints them. **Live t182: 1008 of 1008 comparisons against the real `EnemyUnitPanel` matched** -- 12 own combat units x 28 visible foreign targets (576 unit/city comparisons) plus 7 own cities x 24 visible units (336 city-strike comparisons), 460 of them with at least one row. 12 distinct row types appeared live and every one matched: GG_NEAR, FIGHT_AT_HOME_BONUS, TRAIT_SMALL_SIZE_BONUS, TERRAIN_MODIFIER, ROUGH_TERRAIN_DEF_BONUS, OPEN_TERRAIN_RANGE_BONUS, ADJACENT_FRIEND_UNIT_BONUS, DEFENSE_BONUS, ATTACK_CITIES, ATTACK_CITIES_PENALTY, OPEN_TERRAIN_BONUS, BONUS_VS_CLASS. The remaining rows have regression coverage only. Verification hooked the shared `InstanceManager.GetInstance` (the panel's two instance managers are file-locals) and handed the panel recording proxies, so no real control was touched and nothing on screen changed. Read-only: no orders, no attacks, no turn advance.

**Landed v152-v156 (live on Shoshone t182-t190, the first war this harness has fought).** Declared war
on the Inca, captured Cusco on t190, puppeted it. Nine turns of fighting produced five defects that
peace could not reach; `docs/NOTES.md` "the first war" has the full account. In short:

- **v152** `available_unit_actions.promotions` are the chooser's rows -- `{promotion, name, help}` --
  not bare enums. Live: Dogfighting I is "+33% Combat Strength when performing an Air Sweep", not the
  interception bonus its name implies.
- **v153** An air strike is `MISSION_MOVE_TO` onto the target plot, so it never reported anything;
  move_unit's melee reporting is now shared and every air strike carries `attack` with both sides'
  hp. An out-of-range strike, which the engine silently discards, is refused up front with the unit's
  range instead of returning ok with nothing changed. `H.owner_label` makes an attacked city name its
  owner like an attacked unit does.
- **v154** `steal_tech` takes `player_id` like every other civ-targeting tool; `steal_tech_options`
  victims carry `player_id` so the read round-trips into the write.
- **v155** `todo()` and the `MISSION_SKIP` guard had drifted apart about stalled multi-turn moves and
  deadlocked the turn between them; both now ask `H.is_stalled_mission(u)`.
- **v156** `end_turn` reports `H.end_turn_diagnosis` as `engine` -- above all `UI.CanEndTurn()`, the
  flag the stock HUD greys its own button with -- instead of guessing "a unit or decision still
  blocks it" when the engine is discarding CONTROL_ENDTURN outright.

New live coverage this bought:

- **A nonempty legal air-strike target page** (v149's outstanding item): bomber at Te-Moak, 4 legal
  targets with previews, strengths and modifier rows.
- **A combat-modifier row never seen live**: `TXT_KEY_EUPANEL_STRATEGIC_RESOURCE` -50% on every
  bomber strike (the empire is in strategic deficit).
- **The whole city-capture chain**: `attack.city_captured` -> `city_capture_options` (Cusco, pop 5,
  157 gold, 0 great works/culture, happiness_now 1, annex +11 vs puppet +7 unhappiness, MAJOR
  warmonger on both, no raze because it is a capital) -> the defeat leader screen opening *on top* of
  the capture popup, so `choose_city_capture` refused with "diplomatic decision pending" until
  `dismiss_discussion()` -> `choose_city_capture("puppet")` -> `after` happiness -6 (= 1 - 7, matching
  the preview), puppet true, razing false, occupied false.
- **`domination_progress` with a captured capital**: Cusco, `original_player 2`, `controlled_by_us
  true`, `lost_capital true`.
- **`incoming_deal` with a real PEACE_TREATY**: Pachacuti sued for white peace on t188 (mutual
  PEACE_TREATY, duration 10, no concessions) with Cusco at 1 hp. Refused.
- **`war_consequences` with real content on both candidates**: Ethiopia would have broken a
  Declaration of Friendship with 11 turns left and pulled in Wittenberg, plus two of our trade routes;
  the Inca cost only their incoming route.

- **`civ_eliminated`, live for the first time**: Cusco was the Inca's last city, so taking it ended
  them. The row arrived at the t191 turn start (`H.check_eliminations` compares snapshots on
  `ActivePlayerTurnStart`, so a civ that dies during our turn is reported at the *next* one).
- **v157** fixed the `city_captured` row, which carried the previous owner's per-player city id as
  `city` -- 8192, which resolves to our own capital in `cities()`. It now carries `name`, `city_id`,
  `owner`, `x`/`y` and `former_city_id`. Regression-tested only: no second capture to verify against.

Still uncovered at v157: nonzero fire support, a nonzero interceptor count (no civ in this game has Flight),
an actual interception, razing a non-capital, peace *with terms* accepted (the Inca offered a white
peace and were refused, then destroyed), annexing rather than puppeting, and the modifier rows that
need barbarians, a golden age or specific promotions. A second capture would also live-verify v157.
Interception, a nonempty air-strike page, razing, annexing, and a white peace were all live on
2026-09-24 (v185–v191). What is still open is §0.

**Landed v165-v169 (live on Shoshone t221-t222, after a fresh launch + `load_latest`).** A session
spent on the screens a human reads *before* deciding, rather than on the result of a decision:

- **v165** `gift_tile_improvement_options` / `gift_tile_improvement` -- the city-state screen's last
  closed write (GAPS item 3). Stock only opens INTERFACEMODE_GIFT_TILE_IMPROVEMENT when
  `CanMajorGiftTileImprovement` is true, so a greyed button lists **no** plots and says why instead;
  an open one lists exactly the hexes `HighlightImprovableCityStatePlots` would light, with an
  unrevealed target reduced to bare coordinates. Live t221: Sidon, not an ally, cost 200 against 736
  gold, no `plots` key. At t221 the write still needed a live ally; it was bought later on the hotseat (Budapest, a Gems mine).
- **v167** `H.action_help` -- the sentence under a unit-action button (unitpanel.lua TipHandler) on
  every action row, nearby-plot build row and interface-mode row. Live t221 BUILD_CITADEL was
  annotated only "+1 production, -1 food" and said nothing about claiming territory or +100%
  defence. Stock's computed cases are ported: upgrade names unit and price, scrap names the gold,
  golden age its length, paradrop its range, MISSION_ALERT the sleep sentence for a unit that cannot
  fortify. Also fixed: GameInfoActions spells "no help" as the string "NONE" and ConvertTextKey
  echoes back what it cannot resolve, so MISSION_SWAP_UNITS read as help "None".
- **v168** An empty `available_trade_routes` says why: in a city with nothing in range, or not in a
  city at all -- where stock does not put the button on the panel -- with the nearest city to walk
  to and a note when moves are spent. `overview.idle_trade_units` rows carry `in_city` and the same
  hint, so "idle" stops meaning "ready". Live t221: caravan 671748 in the field at (46,18), 0 moves,
  nearest Moson Kahni distance 4.
- **v169** `available_production` rows carry the chooser's `name` when it differs from the enum. BNW
  renamed items without renaming types: live t222 `set_production(BUILDING_THEATRE)` answered
  `production: "Zoo"`, and `cities()` prints that localized name -- so the city's own build could
  not be found in its own list. Live: Work Boat, Pathfinder, Pyramids, Statue of Zeus,
  Artists'/Musicians' Guild, Great Prophet, Wealth, Research. Faith-only rows also gained `help`.

- **v170** Each `city_state_gifts` tier carries `influence_after` / `makes_ally` / `short_by`. Paid
  for live at t231: Sidon read `ally.none` ten turns earlier, a 1000-gold large gift took us 5 -> 80,
  and Ethiopia -- ally at 83 by then -- kept it. The gap was already in the same answer's `ally`
  block and nowhere near the button being pressed. `minor_gold_gift` reports `still_short` too.
- **v171** `unit_home_options` -- choosetradeunitnewhome.lua / chooseadmiralnewport.lua, the two
  popups with no harness equivalent. `unit_mission` could already push
  MISSION_CHANGE_TRADE_UNIT_HOME_CITY; the engine's candidate list (GetPotentialTradeUnitNewHomeCity
  / GetPotentialAdmiralNewPort) lived only in the popup, and that list is the decision. Outside one
  of my cities stock shows no button, so the answer says that rather than an empty list. Live t232:
  caravan in Moson Kahni offered all seven other cities; one in the field refused by name.

- **v172** A finished `MISSION_BUILD` reports `improvement`, `claimed_plots` (with the civ each tile
  was `taken_from`) and `unit_consumed`. The old diff watched one plot's improvement/route/feature,
  which is the least interesting half of a Citadel. Live t233: a Great General built one at (46,15)
  and claimed three tiles, two off Ethiopia -- who had already denounced us over that same border.

- **v173** `notification_log` -- the stock Notification Log, which lists every entry the gamecore
  still holds, dismissed ones included. `notifications()`/`turn_digest` only ever carried what the
  panel was still showing, so anything read once and dismissed was unreachable while the engine held
  99 of them. Live t233: an "Upcoming Session" of the World Congress that nothing else had surfaced.

- **v174** `city_screen.meters` -- the corner of the city screen, which `cities()` does not show.
  Food stored/needed and the growth label (a settler, `IsFoodProduction`, is stagnant even when the
  banner's `FoodDifference(true)` is not; turns only while growing). Production stored/needed/per
  turn from `GetCurrentProductionDifferenceTimes100` (not multiplied by the modifier a second time;
  a process has no needed). Culture stored/needed and turns until the next border tile
  (`ceil((threshold-stored)/per_turn)`, at least 1, hidden when culture per turn is 0). Fractional
  gold and science (`GetYieldRateTimes100`), faith, tourism. `GAMEOPTION_NO_SCIENCE` /
  `NO_RELIGION` omit those yields, matching the "Off" label. A tile the screen prices in red
  (`CanBuyPlotAt` with ignore-gold) carries `buy_gold` and `can_afford: false` instead of
  `buyable`. An owned tile another of our cities is working names it (`worked_by`); a blockaded
  water tile or a visible enemy unit is marked. **Live t241, Moson Kahni** (pop 12, building Wealth):
  culture 137/225, 11/turn, 8 turns to the next tile; food 66/139, +6, growing in 13; production
  stored 0 at 33/turn with no cost (it is a process); gold 44.56 and science 48.92 (the fractional
  corner, not the floored banner); faith 8, tourism 2. Two tiles the city cannot afford still
  carried a price (`can_afford: false`); none were buyable. Every one of those figures matched
  the city-view getters read back independently. 291 tests. Found on the way: `TunerClient.query`
  has not executed its Lua since v158 (the wrapper was extracted and the `execute` call dropped),
  so a freshly started tunerd answered `NameError: name 'res' is not defined` for every read.
  A tunerd left running from before that edit kept working, which is why play did.

- **v175** League projects. `league_status.projects` and a league process's `league_project` on
  `available_production` carry what the production tooltip prints (`GetProjectDetails`): percent
  complete (`floor(100 * sum of contributions / GetProjectCost)`), our hammers, total and per-civ
  cost, and the bronze/silver thresholds. Other civs' contributions stay off that answer until the
  project is complete -- the completion popup is the first screen that lists them, and an unmet
  contributor is `civ: "unknown"` with no player id. Process rows also carry their own Help text
  (Wealth / Research had none). **Live t241**, World's Fair active, Moson Kahni can build it:
  0% of 2100, 0 contributed, 350 per civ, bronze at 175, silver at 350. The details string matched
  `GetProjectDetails` exactly, and the active project had no contributor list. 295 tests.

Still open at the time of that paragraph (before the hotseat): nonzero fire support, interception,
razing, peace with terms, annexing, a second capture, modifier rows that need a golden age, and
the tile-improvement gift. Interception, razing, annexing, a bare peace, and the gift were live
on 2026-09-24. The list that is still open is §0.

---

## 0. Open as of runtime v207 (2026-09-25)

Tracked on GitLab: one issue per item below, milestones 0.2.0-1.0.0, tracking issue #29; the route and the game state each item needs are in `docs/ROADMAP.md`. Re-verified against the code on 2026-09-24 (442 tests passing). GitLab #23 (turn loop: `ENDTURN_BLOCKING_UNITS` with an empty todo beside a CityStateGreeting popup) closed at runtime v207 on 2026-09-25 -- the engine does not re-evaluate its blocker while a popup is up; reproduced live on the S6 line at t215-t216 with a unit meeting a city-state on its own move and again with a bare `UI.AddPopup` text box; details in `docs/ROADMAP.md`, `docs/LIMITATIONS.md` and `CHANGELOG.md` (495 tests passing).

Checked the installed stock BNW Lua under `steamassets/assets/dlc/expansion2/ui` against `harness/lua/runtime.lua`, `harness/game.py`, and the MCP tools. Stock paths below are relative to that UI directory. This recheck used source comparison, the existing regression suite (**391 tests passed**), five temporary Lua reproductions of the deal payloads, public-opinion tooltip, Venice purchase-list refusal, and research disclosure/progress, plus two Python command-size checks. Those reproductions confirmed defects; passing existing tests does not mean those defects are fixed. No live game actions or new live screen comparisons were performed. Historical live claims are supported by the existing session notes, especially `docs/SESSION_HANDOFF.md`'s v187/v191 entries.

### Information leaks (priority)

- ~~**Embassy rivals' full technology list.**~~ **Closed v192 (GitLab #1).** `H.tech_tree` no longer reads any rival team's `IsHasTech`; the `rivals` key is gone. The steal-tech chooser keeps its own `CanResearch` gate. Regression: `test_tech_tree_have_prereqs_and_embassy_rivals` now asserts the absence, and `test_tech_tree_never_reads_a_rival_teams_techs` fails if a rival team's techs are read behind an embassy. Live on S1 (Shoshone t266, embassies held with the Maya and Morocco): `tech_tree` answers `current`/`have`/`techs` only, 43 have and 38 rows, no rival anywhere in the payload; `steal_tech_options` unchanged (no pending steal).
- ~~**Unrevealed city coordinates in deals.**~~ **Closed v192 (GitLab #2).** `H.deal_items` city rows carry `x`/`y` only when `Map.GetPlot(x,y):IsRevealed(ourTeam)`; without a map API they stay name-only. Rows now carry `pop` as `DisplayDeal` does. Regression: three tests in `test_information_parity.py` cover revealed, unrevealed and no-map. Live on S1: Persia's Pasargadae (unrevealed, pop 15) put on the scratch deal from Lua came back through `incoming_deal` as name + city_id + pop with no `x`/`y`; Ecbatana (revealed, pop 1) came back with (57,19). Scratch cleared afterwards.

### Blocked

- **Fire support.** Off in stock Brave New World (`FIRE_SUPPORT_DISABLED = 1`); the preview's `fire_support_damage` is a faithful 0. See §0 "Seen in code".
- **Path overlay and movement cost.** `Unit:GeneratePath` throws (NYI). `GetPathEndTurnPlot` is nil without the mouse pathfinder (`UI.SendPathfinderUpdate` uses `UI.GetMouseOverHex()`). `Plot:MovementCost` crashed the process on t183 even inside `pcall`. Do not call it, and do not invent turns-to-reach. `explore_frontier` stays hex distance over the revealed map. Plot yields, fresh water, routes, and the resource hover are already on the tile. **Trade-route lines are not part of this gap (v212):** the plot hover's route list (`Player:GetInternationalTradeRoutePlotToolTip`, called by plothelptext.lua on any revealed plot) gives every route's plots, so `trade_routes()` rows carry `path` ordered from the origin (fogged plots marked, `path_gaps` for unrevealed stretches), the caravan on the line with `escorted_by` (own combat units on its plot), and `enemies_near_path` (visible enemy combat units within one hex). Live S1 t269: four own routes and three incoming, 8–15 plots each, caravans placed on the right route when two routes share eleven plots. `Plot:IsTradeRoute()` is the city-connection flag (plothelpmanager.lua), not a caravan line. The map at a glance is `revealed_map` (v212): character grids per layer with `vis` separating in-sight from fogged-and-stale plots, ~1 byte per plot per layer, windowed for large maps.
- ~~**Remembered features under fog.**~~ **Closed v196 (GitLab #19).** `H.seen_features` remembers, per team, the feature of every plot seen visible since the harness loaded (seeded from the visible set at first use, carried across reloads); fogged plots report it with `remembered: true`, never the live read. Live S1 t270: a scout spawned on a fogged forest at (50,8) then killed; the forest chopped by Lua under fog still read FOREST remembered, and a never-seen fogged neighbour with a live feature reported none.

### Trade table

- ~~**Peace with extra terms.**~~ **Closed v200 (GitLab #5), live Alpha/Bravo t237.** `make_peace(other, items)` is `propose_deal` with `PEACE_TREATY` on both sides, so any propose_deal term rides along; `trade_catalog().peace` is the leader screen's Negotiate Peace gate (`can_change_war_peace`, `locked_turns`, the locked-into-war reason) and `_check_deal_items` applies it to every deal proposed at war. Live: t236 `declare_war` refused "forced peace in effect" while the t226 treaty ran its last turn; t237 Alpha declared war (`FROM_UI_DIPLO_EVENT_HUMAN_DECLARES_WAR`, Bravo's war-echo leader screen froze the engine until `dismiss_discussion`), the gate read `ok, locked_turns 0`, and `make_peace(1, [Silk, Salzburg])` answered `pending` with a four-row table (both treaties, SILK marked `last_copy`, CITIES Salzburg pop 4). Bravo t237: `incoming_deal` showed the same rows as `from_us: false` (Silk "new luxury for us"), `accept_deal` -> `at_war: false`, `current_deals` on both seats carry PEACE_TREATY x2 + SILK + CITIES to t262, Salzburg is Bravo's (ordinary city, empty queue, in `todo.cities`) and gone from Alpha's `cities()`; Alpha's t238 digest: "You have made peace with Bravo!", "Deal Accepted". Previously (before v200) only a bare treaty was reachable and the AI path was `HUMAN_NEGOTIATE_PEACE` with the reply read as `incoming_deal`. Save: `Saves/hotseat/Alpha-Bravo_0237 peace-terms`.
- ~~**General trade proposals to humans.**~~ **Closed 886fe67 (GitLab #4), live Alpha/Bravo t227–229.** `propose_deal` to a human seat builds the table on the `SimpleDiploTrade` PvP screen and sends it (`pvp: true`, `pending: true`); the proposer's `incoming_deal` shows `ours_pending: true` until answered. The receiving seat sees `turn_status.pending_deal_from` and `incoming_deal` (`proposed_by`, `pending: true`; detection uses `UI.ProposedDealExists`, since the engine pre-loads the scratch table) and answers with `accept_deal` or `refuse_deal`. Live: t227 Ivory + embassies proposed by Alpha, accepted by Bravo, both seats' `current_deals` agree; t228 a one-sided 3 GPT gift proposed by Alpha, refused by Bravo, the table clears on both seats and Alpha's t229 `notification_log` carries the engine's "Offer Rejected" ("Deal Proposed" / "Deal Accepted" likewise). The inactive seat's reads refuse (`this seat is not active`), so nothing about the answer leaks before the proposer's turn. Lump-sum gold needs a Declaration of Friendship (Brave New World rule; `IsPossibleToTradeItem` false both ways without one, for humans and AIs alike -- `trade_catalog.gold.note` says so since v202); gold per turn, resources, embassies, open borders, pacts are not gated.
- ~~**Third-party war / peace and the Demand button.**~~ *Third-party items closed v199 (GitLab #6, live Alpha/Bravo t234).* `H.deal_items` THIRD_PARTY_WAR/PEACE rows carry `team` (the item's data1) and the leader the screen names (`other` player id, `other_name`, `minor`); before v199 the team id was reported as `other`. `trade_catalog.third_party.war|peace.us|them` mirrors the Other Players pocket (tradelogic.lua ShowOtherPlayerChooser): every living player both sides have met, `ok` from `IsPossibleToTradeItem(from, to, type, team)`, greyed rows with the screen's tooltip ("These players are not at war.", "A peace treaty prevents these players from going to war for a period of time.", "These players are allies."). `propose_deal` takes `{type: THIRD_PARTY_WAR|THIRD_PARTY_PEACE, other}` through ShowOtherPlayerChooser + LeaderSelected. Live t234: catalog listed five city-states as `ok` for war from either side and Budapest greyed (allied to Alpha / peace-treaty-locked for Bravo), all six "not at war" for peace; Alpha proposed "Bravo declares war on Hong Kong", the row read back named, Bravo saw it as `from_us: true` and refused, table cleared. **Demand button closed v202 (GitLab #6), live S1 t266.** `demand(other, items)` is propose_deal through leaderheadroot.lua OnDemand -> UI.OnHumanDemand: the DiploTrade table opens in DIPLO_UI_STATE_HUMAN_DEMAND with our pocket hidden, only their items may go on (from_us false, refused otherwise), OnPropose calls UI.DoDemand() and the leader answers on the spot. Refused up front when the button is greyed (at war) or absent (human seats). Live: Persia (no DoF) -- lump gold refused by the catalog's DoF rule; 20 gpt + Fur demanded, Darius: "Asking for the fruits of others' labor yet again? Your greed is legendary. I will not give in to you.", `accepted: false`, `relationship.history` shows DIPLO_UI_STATE_HUMAN_DEMAND, and his opinion gained "You made a trade demand of them!" -- the stock memory of a demand. An AI's own demand remains the incoming table (`UI.IsAIRequestingConcessions`).
- ~~**World Congress vote commitment.**~~ **Closed v198 (GitLab #7), live Alpha/Bravo t229–233.** `H.deal_items` VOTE_COMMITMENT rows carry `resolution_id` (data1), `choice_id` (data2), `votes` (data3), `repeal` (flag1) and, while the league still lists the proposal, the screen's `name` (GetResolutionName), `choice` (GetTextForChoice), `direction`, `resolution_type`. `trade_catalog` lists `vote_commitments` (the Pocket Votes rows both ways, `votes_us`/`votes_them` = GetCoreVotesForMember) and `votes` (the pocket header: `Player:CanCommitVote(other)` with `GetCommitVoteDetails` as `us_note`/`them_note`). `propose_deal` takes `{type: VOTE_COMMITMENT, resolution_id, choice_id, repeal}` through tradelogic's own UpdateLeagueVotes / GetLeagueVoteIndexFromData / OnChoosePocketVote; `league_status.pending_proposals` rows carry `resolution_id` for enact too. Live t229: World Leader pending, `IsPossibleToTradeItem` false both ways, header notes "They need a Spy as a Diplomat in our Capital." / "We need a Spy as a Diplomat in their Capital." -- a vote is bought from the civ whose capital hosts your Diplomat; a headless `AddVoteCommitment` under that gate adds nothing (no crash). t233, Alpha's spy schmoozing in Vienna and Alpha (host) having proposed Cultural Heritage Sites (id 4): the catalog listed Bravo's Yea/Nay pledges (`them: true`, 4 delegates; `us: false`, note "They need a Spy..."), `propose_deal` refused 2 GPT at a -1 gold rate, then put open borders + Bravo's Yea pledge on the PvP table (row fully labelled), Bravo read it as `from_us: true` and accepted, and both seats' `current_deals` show OPEN_BORDERS + VOTE_COMMITMENT ending t258. Save: `Saves/hotseat/Alpha-Bravo_0233 vote-pledge`.
- ~~**City population on the trade table.**~~ **Closed v192 (GitLab #8).** `H.deal_items` city rows and `H.trade_catalog` `cities.us`/`cities.them` carry `pop` (`City:GetPopulation`), the number `tradelogic.lua` prints next to the name.

### Missing screen details

- ~~**Coup odds.**~~ **Closed v194 (GitLab #9).** `spies()` rows in a city-state carry `coup_chance` when the button is enabled, else `coup_why_not` in the stock order (spy_dead, surveillance_pending, no_ally, we_are_ally) and `coup_ally`; `stage_coup` refuses with the reason, returns the percent the confirm prints, waits for the outcome notification and reports `succeeded` from the city-state's ally afterwards. Live S1 t266-270: Cameahwait sent to Wittenberg (ally Ethiopia) read surveillance_pending while travelling, then `coup_chance: 71` once surveillance was established; the coup succeeded (Wittenberg's ally became the Shoshone, the row then read we_are_ally). No coup notification arrived within 6 s, so the ally check is the result.
- ~~**Spy-city potential hover.**~~ **Closed v194 (GitLab #10).** `spies()` rows in a foreign major city carry `city_potential` in the three tooltip states (potential / cannot_steal / once_known, plus unknown); building, wonder and policy modifiers and the catch-spies lines are built only in the `potential` state, and own-city rows of `available_spy_cities` carry them too. Live S1: Tetoharsky in Marrakech read potential 9882 on base 6588 with Constabulary -25%; Cameahwait under surveillance in Addis Ababa (effective -1) read cannot_steal with base 5554.
- ~~**Religion automatic faith purchase.**~~ **Closed v194 (GitLab #11).** `religion_overview.auto_purchase` lists the pull-down's entries with faith costs and the current selection; `set_faith_purchase(kind, index)` sends Network.SendFaithPurchase for listed entries only. Live S1 t270 (Industrial, 2305 faith): nothing plus eight units (Lancer 740 ... Missionary 400, Inquisitor 400, Prophet 500), no save-for-prophet entry (Industrial era, as stock); set to Missionary read back as current, save_prophet was refused as unlisted, set back to nothing.
- ~~**Great-work swap.**~~ **Closed v195 (GitLab #12).** `culture_works.swap` = our put-up work per class with the pull-down's candidates, and every met civ's offered writing/art/artifact; `set_swappable_great_work` and `swap_great_works` are the pull-down and the Swap button with their gates. Live S1 t270: Persia offered the Aeneid and an Industrial art, Ethiopia a writing; Martin Fierro put up, then swapped for the Aeneid, after which our writing candidate was the Aeneid and Persia's writing offer was gone.
- ~~**Change ideology and unhappiness hover.**~~ **Closed: read v197, live switch v204 (GitLab #13), Alpha/Bravo t238-239.** `public_opinion` (overview / culture_overview) now carries `unhappiness_tooltip`, `ideology`, `can_switch` and, when enabled, `switch_cost` (anarchy turns, tenets now/kept, target); `change_ideology` sends Network.SendChangeIdeology only while the button is enabled. Live S1 t270: Freedom unlocked by Lua read `ideology: POLICY_BRANCH_FREEDOM`, no unhappiness, `change_ideology` refused as the grey button. Live S4 (hotseat t238-239): Alpha (Autocracy, lifetime culture 717, no tenets) against Bravo (Order). Eight Great Musicians spawned for Bravo on Alpha's land each listed `MISSION_ONE_SHOT_TOURISM` with `tourism: 67` (the 100-tourism minimum blast at Quick speed; legal at war), and `unit_mission` consumed each: 536 influence, Popular. Alpha's t239 `overview.public_opinion`: `PUBLIC_OPINION_CIVIL_RESISTANCE`, `unhappiness: 6`, `unhappiness_tooltip` "Public Opinion is generating 6 / Which is greater of: 2 per city OR 1 per 5 population", the pressure tooltip naming Austria's Order, `preferred_ideology: POLICY_BRANCH_ORDER`, `can_switch: true`, `switch_cost {anarchy_turns 2, tenets_now 0, tenets_kept 0}`. `change_ideology` answered `from AUTOCRACY, to ORDER, cost`; the same turn `GetLateGamePolicyTree` read Order, Autocracy was no longer unlocked, `IsAnarchy` true with 2 turns, public opinion back to Content (happiness -4 -> +2), and the science/culture/faith hovers carried `anarchy_turns: 2` while the gold hover did not: v204 adds it (stock GoldTipHandler prints TXT_KEY_TP_ANARCHY too). Save `Alpha-Bravo_0239 ideology-pressure` (S4: button enabled, before the switch).
- ~~**City yield breakdowns.**~~ **Closed v193 (GitLab #14).** `city_screen.meters.breakdown[food|production|gold|science|culture|faith]` is the hover behind each meter (infotooltipinclude.lua `GetYieldTooltip` sources, the food usage line, the engine's `GetYieldModifierTooltip` lines, and the total; culture and faith follow their own source lists with the player/city/wonder/puppet percentages); `breakdown.tourism` is `GetTourismTooltip` as lines. Live t266 Te-Moak: food 21 terrain + 2 buildings, 20 eaten, +3; science 10 population + 5 per-population, City Modifier 33%, 19.95; gold modifiers include the 13.36 trade-route line. Machu (puppet): production 9 base, 5% policy modifier, 9.45 total (the meter's number), science and culture carry the -25% puppet modifier.
- ~~**Purchases in Venice's puppets.**~~ **Closed v201 / v205 (GitLab #15), live Doge t215.** Stock `ingame/popups/productionpopup.lua` opens a puppet's window in purchase mode when the player `MayNotAnnex()`. `H.available_production` now answers a Venice puppet with `ok`, `puppet: true`, `purchase_only: true`, `producing` (the AI's pick) and only the rows that carry a `gold` or `faith` price (projects, processes and unpriced rows are the production picker's, which stays closed); every other player's puppet keeps the blanket refusal, and `set_production` keeps its own guard. `purchase_cost`/`purchase_production` already accepted the Venice case. Live S5 (one-human hotseat as Venice, Atomic start, t215): a Merchant of Venice inside Wittenberg's borders listed `MISSION_BUY_CITY_STATE` with the stock help and `unit_mission` bought the city-state (puppet, Venice's second city, its units taken over). `available_production` on the puppet: `ok`, `puppet`, `purchase_only`, `producing: Observatory`, 22 priced rows (units 60-280 gold, Harbor 170, Zoo 220, Monument 70); `purchase_production BUILDING_MONUMENT` bought it (6134 -> 6095 gold, `city_now_building: Observatory`, `IsHasBuilding` true) and `set_production` refused. Seen live and fixed in v205: `producing` was the raw text key TXT_KEY_BUILDING_OBSERVATORY in both the list and the refusal (now the printed name; `H.L` also survives a missing Locale), and the refusal told Venice to annex first, which Venice cannot (now: buy here with purchase_production). Save `Doge_0215 venice-puppet` (S5).

### Smaller

- ~~**Specialist yields.**~~ **Closed v193 (GitLab #16).** `city_screen.specialists[].yields` and `buildings[].specialist_yields` are `City:GetSpecialistYield` per yield plus the specialist's culture and great-person points, the numbers cityview.lua prints beside a slot. Live t266: Engineer +2 production +3 GP in Te-Moak, Merchant +2 gold +3 GP in Machu.
- ~~**Help on a building we already own.**~~ **Closed v193 (GitLab #17).** Built rows on `city_screen` carry `help`, the same localized help `available_production` printed. Live t266: 11 of Te-Moak's 15 buildings have help text (the rest have no Help key).
- ~~**Stored research after switching techs.**~~ **Closed v193 (GitLab #18).** `tech_tree` and `available_research` carry `progress` on every unfinished tech with stored beakers (the current tech always). Live t266: switching Industrialization (487 stored) to Rifling left Industrialization `available` with `progress: 487` in both reads; switched back afterwards.

**Removed false gap:** Military Overview does not display a numeric fortify-turn count. `ingame/popups/militaryoverview.lua` tests `GetFortifyTurns() > 0` and prints `TXT_KEY_UNIT_STATUS_FORTIFIED`, matching `units().fortified`. Combat previews already include the defender's fortification bonus.

### Read transport

- ~~**Query chunking still exceeds the byte limit for some bodies.**~~ **Closed (GitLab #3).** `Game.q_fits_inline` measures the encoded wrapped command; `Game.string_chunks` cuts on `lua_str_len` (the escaped byte width of each character) so every `{var} = {var} .. "..."` append stays under `command_budget()` = `COMMAND_MAX - Q_MARGIN`. `load_lua` shares the cutter. Both captured bodies (1000 x `界`, 3000 backslashes) run in the lupa test.

### Seen in code, not yet seen live

These reads exist. A later game still has to hit the case.

- ~~Nonzero fire support~~ **cannot occur in stock Brave New World (GitLab #20, closed as a declared limitation 2026-09-25).** `GlobalDefines.FIRE_SUPPORT_DISABLED = 1` in both the base and the expansion2 XML, so `CvUnitCombat::GetFireSupportUnit` returns nothing and the stock EnemyUnitPanel's fire-support branch is dead code; `fire_support_damage` stays 0 (it would light up under a mod that flips the define). Checked live S1 t266 with a barbarian Archer adjacent to the defender, in range, with line of sight and attacks left: `Unit:GetFireSupportUnit` nil while `CanRangeStrikeAt` true.
- ~~Rough-terrain attacker promotion rows~~ **live S1 t266 (GitLab #21, part):** Musketman with Drill I attacking a barbarian Warrior on hills read "Rough Terrain Attack Bonus +15" next to river -20, Great General +15, friendly lands +15, vs Barbarians +53, defender "Terrain Modifier +25"; the same Musketman (Shock I) against an Archer on flat read "Open Terrain Attack Bonus +15" and "Flanking Bonus +10" on both sides. **Golden-age row live S6 t214 (GitLab #21 closed):** a one-human hotseat hosted as Persia (`TRAIT_ENHANCED_GOLDEN_AGES`, GoldenAgeCombatModifier 10), `Players[0]:ChangeGoldenAgeTurns(10)` by Lua, two English Warriors spawned beside our Infantry and `Teams[0]:DeclareWar(1)`: `available_unit_actions` on Infantry 32771 listed both as `attack_targets` with `preview.modifiers.mine` = "Golden Age Bonus +10" (my_strength 77 = 70 x 1.10; 84 with the Flanking +10 row against the second Warrior), the defenders' rows Terrain +25 / Flanking +10 giving their 10.8. Contrast: with the golden age removed the row was gone and my_strength read 70 (77 with flanking); restored afterwards. The Shoshone seat can never show it. Spawning a *barbarian* for this in the fresh game crashed Civ5XP: `Players[63]` is not alive until the engine's first camp, so scenario spawns in a new game must use the AI major. Interception and a nonempty air-strike page were live on the hotseat (v188–v191).
- ~~`unit_captured.captor` on a tile that stays visible~~ **live S1 t267 (GitLab #22, part; runtime v203).** A barbarian Warrior placed onto a Worker at (45,28) in sight: one `unit_captured` row, `summary` "your WORKER at (45,28) was captured by the Barbarians", `captor {owner Barbarians, unit WARRIOR, hp 100, x 45, y 28}`, `nearest_revealed_camp` (51,7) and the recovery hint, and the notice row carries the same. Two defects found on the way and fixed in v203: the destroy event is delayed graphics and can arrive AFTER the notice (seq 28 then 29 live), so `H.link_late_capture` now ties them from the destroy side too; and a unit the harness moved and then lost during our own turn was placed at its turn-start plot, so `move_unit` refreshes the roster entry on arrival. `LocalMachineUnitPositionChanged` was tried for engine-driven moves and rejected (fires before the plot changes, world coordinates only). **Other human seat as captor: live S2b t237-238 (GitLab #22 closed).** `Teams[1]:DeclareWar(0)` by Lua (the Lua API has no `SetForcePeace`; the engine call bypasses the UI gate), an Alpha Worker spawned at (34,11) beside Bravo's Infantry 49157, Bravo `move_unit` onto it -> the move result itself said `attack.captured: true, captured_unit_id`; Bravo's digest "You have captured an enemy Worker"; Alpha's next-turn digest: `unit_captured` "your WORKER at (34,11) was captured by Bravo" with `captor {owner Austria, unit INFANTRY, hp 100}` and the notice "A Worker was captured by Bravo!" carrying the same link. Here the destroy row came first (during Bravo's turn) and the notice at Alpha's turn start, so both orders are now seen live. Small wording gap: the captor's `owner` is the civ name (Austria) while the notice says the player name (Bravo). Caveat: several same-type captures in one turn are paired by order, since the notice names only the unit type -- exactly what a human reads.

`todo.stacked` has recorded live coverage: the v187 handoff says a real stack was cleared. The earlier v184 note that it had regression coverage only is stale. The specific city-spawn origin is not identified in the v187 record, so it should not be claimed as that exact scenario's verification.

`gift_tile_improvement` is implemented (v165, greyed reason v182) and was bought live on the hotseat (Budapest, a Gems mine). The solo Shoshone save has no bare allied resource tile left. That is not an open gap.

---

## Live loop (t182, Pocatello) — v151 modifier rows

Same save, still t182. Verified v151 against the live `EnemyUnitPanel` (1008/1008, see above), then played
the turn. Gold was the standing problem: 0 in the treasury at −11 gpt, which was taking 11 of 44 science
through `budget_deficit`. Notable stock quirk found while porting: `UpdateCombatOddsUnitVsUnit` tests
`pToPlot:IsFriendlyTerritory(c)` with an undefined `c` for the attacker's fight-at-home rows (the correct
player id is passed two rows further down). The port uses the evident intent, the attacker's player id, and
all 144 live FIGHT_AT_HOME_BONUS comparisons still matched the panel exactly.

## Live loop (t182 recovered, Pocatello)

Seat reloaded after a `Plot:MovementCost` crash on t183. QuickSave is t182 after the Airport/Colosseum sales and Lhasa 250 gift: gold 0 / −11 gpt, science 44, happiness 2, Lhasa friends influence 46. Airports gone; Agaidika and Goshute Colosseums gone. Workers: lumbermill (51,12) 3t, road (49,28) 4t, road (47,11) 1t, trading posts (49,12) 6t and (50,14) 3t. v146 live. Do not end_turn until the human wants t183 replayed (AI will re-simulate).

## Live loop (t183, Pocatello) — lost on crash

Gold 0 / −6 gpt, still Losing Gold (science 49, budget deficit −6.26). v145: unit supply 24/37 remaining 13 (handicap 5 + cities 14 + pop 18) — not over cap, so the 52 unit gold is ordinary maintenance (22 paid at 2.36g, 2 free). Building maint 37 (Moson Kahni 9, several 6). Connection gold only on Te-Moak/Agaidika/Machu (5.85 each); Goshute, Pohokwi, Tiwanaku still unconnected. Steel 8t, faith 402/500, culture 26t to Honor finisher (Military Tradition / Professional Army). Free caravan slot. Tetoharsky Cusco 2t, Cameahwait Addis 31t. Worker 114694 had started `MISSION_ROUTE_TO` Pohokwi. Process died on a MovementCost probe; this turn was not quick-saved.

## Live loop (t182, Pocatello)

Losing Gold! at gold 0 / −23 gpt (science 32 via budget deficit; `IsStrike` false, `GetStrikeTurns` 0). Lhasa friends 1t, small gift 250g. v144 sold Moson Kahni + Te-Moak Airports and Agaidika + Goshute Colosseums (250g, gpt −11) then gifted Lhasa (influence 31→46, gold back to 0). Steel 13t. Seat still on t182 after the gift.

## Live loop (t181, Pocatello)

Turn 181 (1210 AD). Gold 0 at −37/turn (science crashed to 18 via budget deficit); after Moson Kahni caravan → Addis (15.35g+2s) gpt −22 and science 35. Happiness 1 → 6 from **Military Caste**. Tetoharsky stole from Cusco: notification named the Inca but not the tech; `steal_tech_options` had only Sailing (we still lacked it in Industrial). `blocking_name` was POLICY with `pending_popups` empty — steal sat behind the policy pick. v143 `todo.steal_tech` listed it; stole Sailing; TechAwardPopup swept. Worker 253971 trading post (49,12) 6t. Lhasa friends 2t, gold too low to gift. Ethiopia offered 1 horse for 12g+1 gpt (declined). Steel 13t. Faith 312/500.

A second hotseat/pitboss instance is the right way to manufacture war, peace-with-terms, and captures; this solo seat is still at peace.

## Live loop (t179, Pocatello)

Machu conversion notice had `religion: null` — 2 Tengriism vs 2 Orthodoxy (pressure 22 vs 36 after the banner-unit fix; raw 225 vs 360). Goshute Granary finished; empty queue was mislabelled as an ongoing process (now omitted). Ethiopian missionary 376852 visible on our lumbermill (50,16); `relationship(4).discuss.stop_spreading_religion` true → asked; they agreed (“missionaries will no longer share the one true faith”). Workshop queued in Goshute 19t. Worker 352258 lumbermill at (51,12) 6t (0 moves on arrival). Steel 9t, culture 2t to policy, faith 222/+45. Path probe: `Unit:GeneratePath` still NYI; `GetPathEndTurnPlot` nil.

t180: Cameahwait (Addis) uncovered Ethiopia plotting against Inca; `relationship(2).discuss.share_intrigue` true, Ethiopia false. Te-Moak caravan returned → Addis again (9.84g+2s, 26t). Lhasa friends 3t (influence 34); gold too low to gift.

## Live loop (t178, Pocatello)

Persia (id 3, Darius) offered 1 ivory (of 2) + their embassy for 5 gpt; accepted (`gpt` −23 → −18, 5 deals). Wittenberg 30-turn faith contest. Machu flipped to Eastern Orthodoxy (2 Orthodoxy vs 1 Tengriism, pressure 360 vs 225). Worker 253971 `BUILD_ROAD` at (50,13) 2t; bomber 466967 slept (0 airstrike targets). Faith 177/+45; missionary 400f so save. Tetoharsky gathering intel in Cusco 3t; Cameahwait surveillance Addis 2t. Cusco now visible — Great Lighthouse in sight. `have` includes Archaeology; visible antiquity sites, no archaeologist yet. Steel 11t. Persia embassy unlocked `tech_tree.rivals` for Darius (ahead Sailing/Optics/Chivalry). v141 top-bar verified live (Church Property 14 gpt was missing from the old gold tooltip).

## Live loop (t177, Pocatello)

Education completed (Scientist bulb). Set **Steel** (11t) for longswords. Both fighters on air patrol; infantry fortified; worker 278548 trading post completed immediately at (50,14). Faith 132 (pagoda still 200). Cameahwait establishing surveillance in Addis (3t); Tetoharsky Cusco 1t. `map_index` live: 6 foreign cities (Cusco/Addis fogged, Harar and Sidon visible), 1 fogged camp (51,7), antiquity `RESOURCE_ARTIFACTS`, no in-sight world wonders. `gift_unit_options` listed every combat unit for each met CS (`CanDistanceGift` true at range on this save — engine gate, not a leak of unmet players). Did not gift.

## Live loop (t176, Pocatello)

Named save `Pocatello_0176 AD-1160`. Turn 176 (1160 AD), era reports Industrial (militaristic CS / mixed army includes Fighter, Bomber, Paratrooper, Infantry alongside trebuchets). Education 114/570; Great Scientist bulbed it to 1t. Faith 87/+45, prophet 500. Happiness +2, gold 137 at −26/turn (53 unit + 48 building maintenance). Lhasa and Wittenberg friends from the Scientist quest (+8 faith each). New spy Cameahwait sent to Addis Ababa (1t travel); Tetoharsky establishing surveillance in Cusco (2t). Fighter 458773 healing on capital; Paratrooper 475136 fortified (paradrop listed but 0 targets with 1.5 moves left). `unit_mission_targets` rebase listed all 6 cities. v139 overviews verified live (GP: Tiwanaku 2 writers 28/300; domination capitals; wonders by met owners without fogged coords; demographics rank 5 population / 1 land; CS bonuses including Sidon Keshik).

t174: spy Tetoharsky traveling to Cusco to steal (1t). Unmet civ Renaissance. t175: Machinery done; Education 10t. Faith 58, saving Holy Warriors Crossbow 240f. Capital pop 9, National College 12t. Happiness +2, gold 141 at −3/turn. Game left after `end_turn` t175.

## Live loop (t173, Pocatello)

Turn 173 (1130 AD). Machinery 2 turns (561/624). Happiness +1, gold 147 at about −2/turn after re-selling silk to Inca for 4 gpt. Great Prophet spawned → `MISSION_ENHANCE_RELIGION` then `enhance_religion` **Holy Warriors + Religious Texts** (verified on `religion_overview`). Worker 253971 trading post at (50,13).

What the new reads changed:

- `tech_tree.have` includes Guilds / Physics / Theology / Civil Service — no more inferring from Workshop. Next after Machinery is a real choice: Education 12t (Inca already has it), Steel, Chivalry (Ethiopia has it), Sailing.
- `current_deals` showed the silk/GPT-with-Inca expiry that `turn_digest` had only named after the fact, plus salt exports (Inca 4 gpt 19t; Ethiopia 60g lump 28t) and Ethiopia open borders 12t.

`cities()` stays the banner list. Open one city with `city_screen(city_id)`.

## Live loop (t163–164, Pocatello)

Save `Pocatello_0163 AD-1030`. Shoshone, Emperor, 7 cities, Medieval, domination + religion.

What the v137 reads changed:

- Agaidika’s empty production was **not** a citizen bug. `city_screen` showed Granary/Library/Temple/Pagoda/Colosseum, 5 worked tiles, balanced focus, surplus 0 because empire happiness was −4.
- Happiness/gold tooltips said to stop guessing: too many cities (21 unhappiness) and 40 unit + 37 building maintenance. Cotton plantation (52,16) and marble quarry (48,31) started t163 for new luxuries. Ethiopia refused horse/gold for silver.
- Research: Guilds already in (Workshop listed). Set **Machinery** (crossbows). Agaidika queued **Market**.
- t164: Agaidika converted to Eastern Orthodoxy (pressure 240 vs Tengriism 240). Missionary spread at Tiwanaku (adjacent) flipped it back to Tengriism, 1 spread left.

---

## 1. City screen

**Implemented v137.** `H.city_screen` / MCP `city_screen(city_id)` returns buildings, specialists + GP meters, every city-radius plot (worked / forced / can_work / buyable+buy_gold / yields), full production `queue`, `focus`, `avoid_growth`, `auto_specialists`, resistance/razing turns, `resource_demanded`, `can_annex`/`can_raze`/`can_unraze`. **v174** adds `meters` (food, production, culture-to-border, fractional gold/science, faith, tourism) and the red price of a tile this city cannot afford (`buy_gold` + `can_afford: false`). An owned tile worked by another of our cities, a blockaded water tile, or a visible enemy unit is marked on the plot.

Still missing at that time: per-city yield breakdown hovers, specialist yields, built-building help (closed v193), and a purchase catalog for Venice's puppets (landed v201, live pending).

Writes (stock paths, no city-screen UI):

- `set_city_focus` → `Network.SendSetCityAIFocus` (`balanced` / `food` / `production` / `gold` / `science` / `culture` / `great_people` / `faith`)
- `set_avoid_growth` → `Network.SendSetCityAvoidGrowth`
- `change_working_plot` → `Network.SendDoTask(TASK_CHANGE_WORKING_PLOT)`
- `buy_city_plot` → `Network.SendCityBuyPlot`
- `city_task` `annex`/`raze`/`unraze` → `TASK_ANNEX_PUPPET` / `TASK_RAZE` / `TASK_UNRAZE`
- `sell_building` (v144) → `Network.SendSellBuilding`. `city_screen` buildings carry `can_sell` / `sell_gold` / `gold_maintenance`. Puppets refuse.

Specialist slot click is **v139** `change_specialist(city_id, building, add)` via `Network.SendDoTask` (`TASK_NO_AUTO_ASSIGN_SPECIALISTS` then ADD/REMOVE). Puppets still refuse citizen writes (AI runs them; annex first).

---

## 2. Top bar

**Implemented v137** on `overview` / `H.player_summary`:

- `luxuries`: revealed `RESOURCECLASS_LUXURY` with `available`/`total`/`imported`/`exported`/`last_copy`
- `bonus_resources` (v179): the resource list's bonus stack. A row only when `GetNumResourceTotal` > 0 or something is exported. Strategics and luxuries are not repeated here. A revealed strategic also carries `used` when that column would print.
- `happiness_breakdown`: toppanel.lua HappinessTipHandler buckets (luxuries, buildings, city count, population, puppets, specialists, …)
- `gold_breakdown`: city income vs international trade routes, connections, deal gpt, traits, religion, unit/building/improvement maintenance. **v145** `expenses.unit_paid` / `unit_free` / `unit_cost_per` (Economic Overview unit tooltip).
- `unit_supply` (v145): Military Overview header — cap (handicap/cities/population), remaining or deficit + production_penalty. Top-bar unit-supply string only appears when already over; the overview always has the numbers.
- `golden_age_progress` / `golden_age_threshold` (meter; `golden_age_turns` still the active-age timer)
- `science_breakdown` (v141): cities vs ITR, budget deficit, city-states, happiness, research agreements, `tech_city_cost_mod`
- `culture_breakdown` (v141): cities / happiness / traits / CS / religion / golden-age remainder, turns to next policy, `policy_city_cost_mod`
- `tourism_breakdown` (v141): tourism, great-work fill, influential_on/needed when cultural victory is on
- `faith_breakdown` (v141): cities / CS / religion, next great-person faith threshold

Live t178: gold `income.religion` 14 (Church Property) was previously omitted, so the old tooltip did not add up to `gold_per_turn`.

**v178** adds the Happiness screen's expandable rows to `happiness_breakdown` (happinessinfo.lua), not only the tooltip totals. `happiness.by_luxury` is each luxury that actually gives happiness. `league` and `difficulty` are the two totals the screen shows and the old buckets skipped; `difficulty` is the residual, so garrison happiness lands there the way the screen's "from Difficulty Level" line does. `cities` lists building happiness, local happiness, connection happiness, unhappiness, and occupied. A zero the screen prints as a dash is omitted. `unhappiness.tooltips` is the Number of Cities / Citizens hover, including the difficulty, map, trait, and policy lines. `unhappy` / `penalties` are the red sentences (unhappy, very unhappy, revolt). Live t241: 8 luxuries at 4 each (32, matching the luxury total), difficulty 9 matching the residual, local happiness 37 and connection happiness 7 matching those totals, eight city rows, citizens 59, and the citizen hover "produce -5% the usual amount" from the empire modifier. Cusco was not occupied, so that stack stayed hidden. The turn was not ended.

---

## 3. Plot tooltip

**Implemented v137** on visible plots: `yields` (`plot:CalculateYield`, same as `GetYieldString`), `fresh_water`, `worked`, `resource_qty`. Fogged plots keep revealed-stale terrain/resource/improvement/owner and **omit** live feature, yields, and occupants.

**v179** adds the resource hover (`resourcetooltipgenerator.lua`) on every revealed resource tile, fogged or not, because it is the resource's own text: `resource_happiness` (the "+N happiness" when improved), `resource_improved_yields` (the yields when improved and worked — not the tile's current `yields`), and `resource_help` (the strategic blurb, color tags stripped). A zero happiness and a zero yield change are left off.

Movement cost and remembered features under fog are still missing (§0). No safe plot-level movement getter is established; do not fake path length or restore live features under fog.

---

## 4. Tech tree

**Implemented v138.** `H.tech_tree` / MCP `tech_tree()` exposes techtree.lua statuses, with the remaining progress and disclosure problems in §0:

- `have`: short names already researched (`Team:IsHasTech`)
- `techs`: current / available (`CanResearch`) / unavailable (prereqs missing). Each has `prereqs` from `GameInfo.Technology_PrereqTechs`, `missing` of those we do not have, `turns` / `cost`, `queue` when set. `CanEverResearch` false (other-civ uniques) is omitted.
- no `rivals` key since v192: v138-v191 listed every met embassy rival's `ahead` techs, which no stock screen shows (§9, GitLab #1).

`available_research` is still the leaf list `set_research` consumes. Live t173: Machinery 561/624, 2 turns; Education/Chivalry/Steel/Sailing available; Inca already has Education.

**v177** adds the button row (`unlocks`) on `tech_tree` and `available_research`, the icons `AddSmallButtonsToTechButton` draws. A unit or building button is the class default unless this civilization's override replaces it, so another civ's unique is not listed. The unit button carries the same facts as `GetHelpTextForUnit` (that function is not in this Lua state): cost, moves, range, strengths, resources, written help. Ability buttons (embark, ocean, embassy, an extra trade route, the World Congress) use the same text keys as the icon. Researched techs stay in `have` without the row. Live t241, Shoshone, Navigation current and still unproposed: Frigate (185 production, strength 25, ranged 28, range 2, moves 5, 1 Iron), Privateer, Seaport — not England's Ship of the Line and not Portugal's Feitoria. Military Science offers Comanche Riders, not Cavalry. The help paragraph is the same words with the color and icon tags removed.

---

## 5. Units and combat hover

**Implemented v137** for own units (`promotions`, `xp`/`xp_needed`, `upgrade_to`/`upgrade_gold`/`can_upgrade`) and for visible plot units (strength, ranged, promotions). Visible city plots carry strength, garrison, puppet/razing, majority religion.

Combat previews include the stock EnemyUnitPanel's itemised modifiers as of v151. Foreign-city followers/pressure are on the visible plot as of v139. Remaining live-coverage limits are in §0.

**v149:** Ranged combat strengths and air retaliation/interception warnings match the stock panel's getters. Air-strike target pages also carry previews. Live t182: 13 comparisons matched stock panel damage/strengths; all air cases had zero visible interceptors.

**v150:** Melee fire-support damage and maximum-HP caps now match the stock panel. Live t182: 115 comparisons matched damage/strengths; all support reads were zero.

**v151** added the itemised modifier rows (see the parity log). **v188–v191** verified a nonempty air-strike page and a real interception live. Nonzero fire support, and the modifier rows that need a golden age or a specific promotion, still have regression coverage only (§0).

---

## 6. Diplomacy

| Human screen | Tool today | Gap |
|---|---|---|
| Current deals (what, with whom, turns left) | `current_deals` (v138) | Uses LoadCurrentDeal only while scratch is empty, then ClearItems. `CITIES` items have `name`/`city_id`, but lack population and leak unrevealed coordinates; vote commitments lose their payload (§0). |
| Incoming table | `incoming_deal` | An AI demand (`UI.IsAIRequestingConcessions`) is this table: accept or refuse. Shares `H.deal_items`' city-coordinate, population, and vote-commitment gaps (§0). |
| Trade pockets | `trade_catalog` | Covers gold, GPT, resources, cities, open borders, embassy, research agreement, defensive pact, and trade agreement. City names are returned, coordinates are reveal-gated, but population is missing. Vote commitment, third-party war/peace, and a peace treaty are absent from this catalog (§0). |
| Relationship / global relations | `relationship` | OK (v107 gated third-party defensive pacts / city-state friendship / an unmet ally). A human seat has no AI approach or opinion (v186). |
| Declare-war confirmation | `war_consequences` | OK |
| City-state screen | `city_state_gifts` + `city_state_actions` + `city_state_bonuses` (v139) + `gift_unit` (v140) + `gift_tile_improvement` (v165, why-not v182) | Quests, influence, ally, pledge, tribute, trait/personality, current bonus amounts, unique unit, exported resources, unit gift, tile-improvement gift. |
| Peace with extra terms | `make_peace` | Bare treaty verified between humans; AI offers, when made, are readable. No tool edits the seeded table. The unsafe headless call is not the same as the working stock UI flow (§0). |
| General human-to-human trades | `trade_catalog`, `incoming_deal`, accept/refuse | `propose_deal` and `negotiate_deal` reject human recipients. Bare-peace support does not provide a general PvP editor (§0). |
| Third-party war/peace, human demand, vote commitment | incoming third-party rows name `other` | Not proposable. A vote-commitment row drops resolution, choice, vote count, and enact/repeal. The leader Demand button is not a tool. |

---

## 7. Other screens a human opens

| Human screen | Status |
|---|---|
| Great Person progress | **Done v139** `great_person_progress`. Faith Prophet threshold also in `religion_overview`. |
| Foreign city banner (visible) | **Done v139** `city.religions` on visible plots. |
| Archaeology popup | **Done v139** `archaeology_options` / `choose_archaeology`. Unmet artifact origins masked. |
| Maya Long Count | **Done v139** `maya_options` / `choose_maya_bonus`. |
| Demographics / Who’s Winning | **Done v139** `demographics`: our value/rank plus public best/average/worst. Unmet identities masked. |
| Victory Progress (domination) | **Done v139** `domination_progress`: met capitals, holder, revealed coords only. |
| Wonder Overview | **Done v139** `wonder_overview`: met owners; city/x/y/captured only when the city is in sight. |
| Culture Overview extras | **Done v139** `culture_works` (slots, theming, tourism modifiers). Victory race is `culture_overview`, including turns to Influential. The swap tab (works on offer, and the swap itself) is still open (§0). |
| Espionage intrigue | **Done v139** `espionage_intrigue`. Spy list, relocation cities, and `BasePotential` are on `spies` / `available_spy_cities`. Coup percent, the greyed-coup reason, and the potential hover's building/policy lines are still open (§0). |
| Religion automatic faith purchase | **Open.** The dropdown (`GetFaithPurchaseType` / `GetFaithPurchaseIndex`, `Network.SendFaithPurchase`) is not exposed. Founding, beliefs, and per-city faith buys are. |
| Change ideology | **Open.** `public_opinion` has pressure and its tooltip, but omits the separate unhappiness tooltip. Switch cost (anarchy turns, tenets retained with a zero floor) and `Network.SendChangeIdeology` are not exposed. |
| Path overlay | **Blocked.** `Unit:GeneratePath` is NYI (throws). `GetPathEndTurnPlot` is nil without the mouse pathfinder (`UI.SendPathfinderUpdate` uses `UI.GetMouseOverHex()`). Live t183: `Plot:MovementCost` crashed the process even inside pcall — do not call it. `explore_frontier` stays hex distance / known-map connectivity, not path length. Do not fake turns-to-reach. |

Air / nuke / paradrop / rebase / airlift: **Done v139** `available_unit_actions` lists the interface missions; `unit_mission_targets` enumerates currently visible legal plots (fog never queried). Issue the order with `unit_mission`.

---

## 8. Smaller quality holes

- Production queue: `city_screen.queue` has the full list; `cities()` is still the head item only. The Economic Overview's current-production column matches that head item.
- City yield breakdowns, specialist yields, help text on a building already in the city, stored progress on noncurrent research, and city population on trade rows: still open (§0). Numeric fortify turns were a false gap.
- Combat results: **v141** pillage `effect.gold_gained` (gold before/after the mission); city-strike/ranged kill now includes `damage_dealt` (remaining hp of the vanished unit). **v191** links a captured civilian to its notice as one `unit_captured` row (live t230: the Worker and the nearest revealed camp; the captor was unnamed because the tile had gone back to fog).
- Conversion notice: **Done v142** — banner `religions` + majority, or a tie note (live t179 Machu 2–2).
- Empty production labelled as a process: **Done v142** (live t179 Goshute Granary finished).
- Religion overview pressure: **Done v142** — same banner units as `city_religions` (Machu Orthodoxy 36, not 360).
- Discuss-screen buttons: **Done v142** `relationship.discuss` (live t179 Ethiopia stop-spreading true then false after they agreed; t180 Inca `share_intrigue` true after Cameahwait’s plot notice).
- Steal-tech chooser hidden behind another `blocking_name`: **Done v143** — `todo.steal_tech` + notice attaches victim/techs (live t181 Sailing from Inca while POLICY was current).
- Empty-treasury / Losing Gold: **Done v144** — `gold_breakdown.losing_science_from_deficit` + notice attaches gold/GPT. Strike flags when `IsStrike` is true.
- City-screen sell building: **Done v144** `sell_building` (live t182 two Airports + two Colosseums). Puppets refuse.
- Military Overview unit supply / Economic Overview unit+city gold rows: **Done v145** — `overview.unit_supply`, `gold_breakdown.expenses.unit_paid/unit_free/unit_cost_per`, `cities().building_maintenance` + `connection_gold` (connected only), `units().garrisoned`. Live t183: 24/37 remaining 13; 22 paid at 2.36g; Goshute/Pohokwi/Tiwanaku unconnected (getter still returned gold; omitted).
- Worker job / plot construction / CS quest coords: **Done v146** — `units().build` + `build_turns_left`; plot `under_construction` / `trade_route` / `resource_requires_tech`; `city_state_actions.quest_list` (kill-camp x/y only if revealed). Live t182 lumbermill 3t; Sidon/Wittenberg faith contests named with scores.
- Deal city names: **Done v140** — `name` / `city_id` on `CITIES` rows. Trade catalog withholds x,y for unrevealed plots, but deal rows do not; both omit the displayed population (§0).
- Partial-move / stalled MOVE_TO units: **Done v139** — they appear in `todo.units` with `stalled_mission`.
- `known_world` size: **Done v140** `map_index` (resources / camps / ruins / foreign cities / visible natural wonders / in-sight world wonders). `known_world` remains the full plot dump.

---

## 9. Information boundaries

**Fixed v137:** fogged plots no longer call `GetFeatureType`. Stock UI has `GetRevealedImprovementType` / `GetRevealedRouteType` / `GetRevealedOwner` (already used) but no revealed-feature getter, so `feature` is omitted on `vis=false` rather than leaking a chopped forest. Tests now fail if `GetFeatureType` is touched under fog.

**Fixed v192 (GitLab #1, #2):** `tech_tree` no longer carries a rival technology list (an embassy is not a basis for one), and `H.deal_items` city rows withhold coordinates until the plot is revealed, the gate `trade_catalog` already applied. The remembered-feature omission (#19) is a separate missing-information gap; the v137 privacy fix remains correct.

---

## 10. Action gaps that also hide information

Workflows whose missing choices or confirmation details also limit informed decisions:

- Peace with extra terms, general proposals to humans, third-party war/peace, a human demand, and a World Congress vote commitment (see §0 and §6). Leave the crashed headless `AddPeaceTreaty` path closed; stock UI treaty seeding already works.
- Great-work swap, religion automatic faith purchase, and changing ideology (see §0). Each has pre-action choices or costs visible in the stock screen that the harness omits.
- Raze / unraze / annex: `city_task` (v137). Live on the hotseat, 2026-09-24: Salzburg puppet, then annex, raze, unraze.
- Tile / citizen management: focus, avoid-growth, work-plot, buy-plot (v137), specialist slot add/remove (v139), sell building (v144). Puppets still refuse. The yield a specialist adds is the read still missing (§0).
- Production in a puppet: **closed v158.** `set_production` was the one city write missing the puppet guard, and live t192 an order pushed into captured Cusco stuck permanently (the stock city screen has no production picker for a puppet). `turn_status.todo` no longer lists production-automated cities. `available_production` also refuses puppets, which is correct for production but hides Venice's legal purchase choices (§0). `purchase_cost` explains ordinary puppet refusals and recognizes `MayNotAnnex()`; it does not replace the missing catalog.
- Gift a unit to a city-state: **Done v140** `gift_unit_options` / `gift_unit`.

---

## Implementation history

Done v137: city screen + writes, top-bar breakdowns, plot yields, own promotions, visible unit/city hover, specialist GP meters, fog feature leak.

Done v138: tech tree; current deals with turns remaining.

Done v139: foreign-city religions, national GP, specialist clicks, archaeology/Maya, air-mission targets, domination/wonders/intrigue/CS bonuses, demographics, culture works, stalled-move todo.

Done v140: compact `map_index`, named deal cities, CS unit gift.

Done v141: science/culture/tourism/faith top-bar line-items; gold ITR/religion split; pillage gold and city-strike kill damage on the action result.

Done v142: conversion-notice banner, empty-queue vs process, overview pressure units, Discuss-button flags.

Done v143: pending steal-tech in `todo` and on the Steal Technology notice (live t181, behind POLICY).

Done v144: gold-deficit flag + Losing Gold notice; city-screen sell building.

Done v145: Military Overview unit supply; Economic Overview unit cost-per-paid-unit and per-city building/connection gold; `units().garrisoned`.

Done v146: worker job turns on `units()`, plot construction/trade-route/unusable-resource tooltip, structured CS quests with revealed kill-camp coords.

Done v147: incoming trade routes, score tooltip breakdown, city blockade / We Love the King.

Done v148: tech/production Help, nearby_builds turns + yield delta, public opinion, CS tile-improvement gift read.

Done v149: ranged strengths, air retaliation/interception warning and visible count, air-strike target previews.

Done v150: melee fire-support damage and maximum-HP caps; 115 live stock-panel comparisons.

Done v151: itemised combat-modifier rows on every preview; city-strike max-HP cap and strengths.

Done v174: city-screen corner meters (food / production / culture-to-border / gold / science / faith / tourism) and the red price of an unaffordable tile. Live t241 Moson Kahni matched the city-view getters, including two unaffordable tiles and a Wealth process with no production cost.

Done v175: World's Fair / International Games / ISS on `league_status.projects` and on the production row (`league_project`), matching the production tooltip. Other civs' hammers only after the project completes. Live t241 World's Fair: 0% of 2100, bronze 175, silver 350.

Done v176: the League Overview's words, not just its names. `league_status` now carries the tooltip on every proposable, repealable, pending, and votable row (`details`), the greyed resolutions (`unavailable_enact`), every passed resolution (`active_resolutions`), the on-screen effects list (`active_effects`), and the delegate hover on met members. Choice labels drop the icon tags. An unmet proposer stays `proposer_civ: "unknown"`. Live t241, still the call for proposals, nothing proposed: Arts Funding is in effect (repealable; Maya and Persia would be angry), host Morocco has 11 delegates, 10 enact options and 8 greyed ones all had tooltips, World's Fair still 0%.

Done v177: the tech-tree button row (`unlocks`) on `tech_tree` and `available_research`. Our unit and building, not another civ's unique; the ability icon's sentence; revealed resources; worker builds that `ShowInTechTree`. Live t241 Navigation was Frigate / Privateer / Seaport, and Military Science was Comanche Riders. The turn was not ended.

Done v178: the Happiness screen's rows on `happiness_breakdown`. Per luxury, per city (buildings, local, connection, unhappiness, occupied), the difficulty residual, league happiness, and the Number of Cities / Citizens hovers. Live t241 the eight luxury rows summed to the luxury total (32), difficulty matched the residual (9), and local/connection sums matched those buckets (37 and 7). The turn was not ended.

Done v179: the resource list's bonus stack on `bonus_resources`, `used` on a revealed strategic, and the resource hover on a plot (`resource_happiness`, `resource_improved_yields`, `resource_help`). **v216 moved the hover off the plot**: it is the resource's own text, identical on every tile, so it is printed once in `reference("resources")` and a plot carries `resource` / `resource_qty` / `resource_requires_tech` only. The hover is the resource's own text, so fog still omits live yields and features. Live t241: Bison 1, Cow 2, Deer 1, Sheep 1, Stone 2; Horses 18/19 with 1 used and 1 imported; fogged Incense was +4 happiness and +2 gold with no current yields; a visible Horse was "+1 production when improved". The turn was not ended.

Done v180: World Congress `name` drops the choice icon `GetResolutionName` embeds. The screen draws `[ICON_RELIGION_TENGRIISM]` as a picture; the tag is not a word. Live t241 the pending row reads "World Religion: Tengriism". The turn was not ended.

Done v181: Trade Route Overview religion columns and the gold/science hover. `from_religion` / `from_pressure` are the left arrow, `to_religion` / `to_pressure` the right, and both are omitted when that cell is blank. `details` is `BuildTradeRouteToolTipString` (base gold, both cities, only the nonzero bonuses, then science). The same hover is on a chooser row. Live t241 all 7 routes matched the stock tooltip, including Moson Kahni to Adwa (Eastern Orthodoxy +6 back, Tengriism +9 out) and a sea route's "Sea route: 2x". The turn was not ended.

Done v182: the greyed "Gift Improvement" button explains itself. Beyond allies-only and the price, the engine greys it when no plot within MINOR_CIV_RESOURCE_SEARCH_RADIUS of the capital passes the plot check, and the old reading was "the button is greyed out". `why_not` now says what a human sees on the map: the ally's revealed resource tiles and whether each is improved (`resource_tiles`, `search_radius`); a resource we have not revealed is not named. Live t241 Sidon (ally, 232 gold against 200 after selling Salt to Morocco): "no tile left to improve: its 2 revealed resource tiles within 5 hexes of the capital are already improved (bison camp at (52,15), wine plantation at (53,11))" -- the third, an Aluminum mine, stayed hidden as it is on the map. The write refuses with the same sentence. The turn was not ended.

Done v183: `turn_status.todo.stacked` names the tile behind ENDTURN_BLOCKING_STACKED_UNITS. The engine's blocker names no unit, and the hint alone ("move_unit one of them off it") sent the play loop at a Caravan -- which cannot be walked -- for eleven attempts at t245. Each entry is the plot, the class (combat with combat, civilian with civilian; aircraft share a city freely), and the units with ids, types and moves, so the caller can pick the one that can leave. Play loop: unstacking tries every walkable unit on the tile, a finished Caravan / Cargo Ship gets the best route on offer instead of a walk (`ensure_trade_routes`), and a spy's finished steal is answered with the dearest tech (`resolve_steal_tech`).

Done v184: `move_unit` reports a swap. A move onto one of our own units of the same class trades places with it, and the reply only said "arrived"; a human watches the other unit hop. The order now remembers who stood on the destination (`swap_candidates`), and once the mover has settled there, the one of them now on the mover's old plot is `swapped_with` (id, type, plot, moves left) with a note. Live t252: a Worker ordered from (45,29) into Goshute traded places with the Worker there, which came back with 0 moves. Found while trying to build a live stack for v183's `todo.stacked`: the engine swapped rather than stacked, so that session did not live-verify the field. The v187 hotseat later cleared a real stack (§0).

Done v185–v187 (2026-09-24, the first two-human hotseat: Alpha/Korea vs Bravo/Austria, Duel, Atomic start, every seat the harness's own, scenarios built through `harness.cli lua`). Live through the MCP surface: war on a human and its `war_consequences`; a Worker captured on the move (`captured_unit_id`; the victim's digest says "A Worker was captured by Alpha!"); Artillery set-up and bombardment, city strike and melee from the other seat; Salzburg taken at 1 hp with `city_capture_options` (unhappiness, warmonger text) and puppet -> annex -> raze -> unraze; the air-strike target page with "Known Enemy Anti-Air Units: 1" and a Bomber lost to an AA gun; pillage with moves (31 gold, `improvement_pillaged`); `todo.stacked` cleared live; Budapest allied and `gift_tile_improvement` bought a Gems mine; peace between humans (`make_peace` seeds the table, `accept_deal` proposes, the other seat's `incoming_deal` / `todo.incoming_deal`, `accept_deal` ends the war, `current_deals` lists the treaty with turns_left). Fixed: standing moves keyed per seat (v185); `relationship` of a human seat carries no AI approach or opinion (v186); accept/refuse empty the scratch table (v187); actions refuse under a leader screen, which freezes the engine loop; stale popup records are dropped; pillage at 0 moves is refused and a pillage says whether the plot changed; the tile gift waits for the purchase; the post-proposal "Anything else?" scene counts as a greeting. The three defects this game left open are closed in v188–v191 below.

Done v188–v191 (2026-09-24, same hotseat, t227–t230, barbarians spawned through `harness.cli lua` as the enemy the peace treaty rules out):

- **Interception on the air-strike result.** The engine's banner for a strike is only "Your Bomber bombarded an enemy Infantry! (87 damage)" -- no interception line -- so the result reads it the way the stock panel counts: `GetInterceptorCount` (all domains, visible only) before and after; a visible interceptor that fired is out of interceptions for the turn and drops out (1 -> 0 live, three times). `attack.intercepted`, `attack.interceptor` (the unit `GetBestInterceptor` would send up, named only when its plot was in sight before the strike), `attack.shot_down`, `visible_interceptors_before`, and a note that `my_hp` includes the interception damage the preview excluded. A dead aircraft cannot ask, so another of ours asks (same count, verified live); with no aircraft left, a dead attacker beside an unhurt target is still a shoot-down. Banner texts that do say "was intercepted by" / "was shot down by" are honoured. Live t227: Bomber 100 -> 13 hp against an AA gun at (2,11) while the Infantry lost 11 (`intercepted`, interceptor ANTI_AIRCRAFT_GUN (2,11)); a 40 hp Bomber into a fresh gun at (6,15) died with the strike landing for 1 (`shot_down`); a second Bomber into an exhausted gun took only the air defence (24) with no flag.
- **Previews stay inside the health bar.** `ranged_preview` clamps `expected_damage_dealt` to the target's maximum (a city's own) and `expected_damage_taken` to MAX_HIT_POINTS, as enemyunitpanel.lua does before drawing; every preview also says `my_unit_would_die` / `target_would_die` when current damage plus the hit reaches the maximum (a city is never killed by damage). A clamp that cannot be read leaves the raw number.
- **A captured civilian is one row, named and placed.** `SerialEventUnitDestroyed` arrives after the unit is gone (`Unit:Kill()` fired nothing synchronously; `GetUnitByID` was nil inside the hook), so the runtime keeps a roster of each seat's own units (turn start, turn end, and any unit ordered into a fight) and names a loss from it: `unit_destroyed` rows carry `unit_type` / `x` / `y`. The capture notice ("A Worker was captured by the Barbarians!") is tied to the most recent such row whose unit name is in the text and whose unit is really gone: `unit_id`, `unit`, `x`, `y`, the `captor` standing there when the tile is in sight, `nearest_revealed_camp` for barbarians, and a hint. The digest folds the destroy row, the notice's link and the hp-compare fallback into one `unit_captured` with a summary. Live t230: Worker 286742 at (33,4), nearest revealed camp (36,7) five hexes away; the tile was under fog afterwards, so no captor was named.
- **Hotseat bookkeeping that was silently wrong.** When `ActivePlayerTurnEnd` fires, `GetActivePlayer()` already names the next seat: Alpha's turn end was filed for Bravo and Bravo's units were the ones snapshotted, so `unit_lost` / `unit_hurt` never appeared for either seat. The seat whose turn started last is the one that ended (`H.turn_seat`), snapshots are per seat, and a loss belonging to another human seat during the barbarian/AI phase is filed for that seat (same rule as damage rows).

The open list is §0. Path length cannot be closed on this build. A bare peace and a captured civilian no longer wait on a war this solo seat does not have: both were live on the two-human hotseat (v185–v191).
