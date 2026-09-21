# Information-parity gaps (human seat vs LLM)

Date: 2026-09-20 (runtime **v157**, live on Shoshone t182 after harness launch/load; recovered from the t183 MovementCost crash). Goal: the LLM should have the same information a human in this seat would have, in every situation. Rule 2 still holds: never more than that (fogged tiles carry no live occupants, unmet civs do not exist, no private AI state).

This is a **read** audit. Action-only holes are listed only where they also hide information a human gets by opening the same screen.

`docs/COVERAGE_AUDIT_2026-09-19.md` is partly stale. Most of its ranked list was implemented during the Shoshone game. v137 used this save as a feedback loop: open the screen that was blocking a real decision, implement it, verify live, play the turn.

Sources: `harness/mcp_server.py`, `harness/lua/runtime.lua` (`H.*` snapshots), `harness/game.py`, stock BNW UI.

**Writing a new read or write:** the tuner truncates an inbound command at 2048 bytes (measured t193). `Game.q` chunks anything past `Game.q_inline_max()` -- computed from that limit minus the real `query()` wrapper -- so a long body is safe, but a body that grows past the line without the budget noticing is not: that is how a two-line guard added to `set_production` turned into a bare "Syntax Error". Live notes: this file (t163–176) and `docs/NOTES.md`.

---

## Already at parity (do not re-open)

Play loop, fog/met gating, combat previews (melee vs unit and city, ranged, city bombard), religion / culture / league / spy overviews, trade catalog + current table, diplomacy and relationship (visible approach, opinion lines, public relations), war-declaration consequences, city-capture options with unhappiness and warmonger text, city-state gifts/quests/pledge/tribute, spaceship progress, explore-frontier, “refused actions say why.”

**Landed v137 (live on Pocatello t163):** city screen; top-bar luxuries / happiness / gold / golden-age meter; plot yields + fresh water + worked; own-unit promotions / XP-to-next / upgrade preview; visible-plot unit strength+promotions and city banner (strength, garrison, puppet/razing, majority religion); specialist GP meters on `city_screen`; fogged plots no longer leak live `GetFeatureType`.

**Landed v138 (live on Pocatello t173):** `tech_tree` (have / current / available / unavailable+prereqs+missing; embassy rivals’ ahead techs); `current_deals` (who, items, turns remaining — LoadCurrentDeal only while scratch is empty, then ClearItems).

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

**Landed v149 (live t182, 134 tests passing):** Ranged previews now include both combat strengths, using the stock panel's embarked/naval/support-fire defense branches. Air strikes report target retaliation instead of zero, visible interceptor count, and the stock interception warning even when that count is zero. Interception damage is excluded from the estimate. `unit_mission_targets` air-strike pages include the same visible target details/preview as `ranged_targets`; fog, invisible units, and peaceful occupants are excluded from those details. City targets preview the city, not its garrison. After harness launch/load, 13 live previews matched the stock combat panel's displayed damage and strengths exactly: bomber/fighter/bow against visible city, pikeman, crossbowman, worker, warrior. At peace these are Alt-hover-equivalent reads; the public bomber target tool correctly returned empty. A nonempty legal target page and nonzero interceptor count still need live coverage.

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

Still uncovered: nonzero fire support, a nonzero interceptor count (no civ in this game has Flight),
an actual interception, razing a non-capital, peace *with terms* accepted (the Inca offered a white
peace and were refused, then destroyed), annexing rather than puppeting, and the modifier rows that
need barbarians, a golden age or specific promotions. A second capture would also live-verify v157.

---

## 0. Ranked remaining reads

| # | Gap | Status |
|---|-----|--------|
| 1 | City screen | **Done v137.** `city_screen(city_id)` + writes `set_city_focus` / `set_avoid_growth` / `change_working_plot` / `buy_city_plot` / `city_task`. Specialist slot add/remove is **v139** `change_specialist`. Live: Agaidika was not starving — empire −4 happiness; it already had Library/Granary/Pagoda/Colosseum and an empty queue. |
| 2 | Top-bar tooltips | **Done v137** luxuries/happiness/gold/GA. **v141** science/culture/tourism/faith line-items + gold ITR/religion split. Live t178: science 55 = 51.75 cities + 4 ITR; culture 35 cities, 3t to policy; tourism 3 (1 GW, 0/5 influential); faith 45 = 29 cities + 16 CS, next GP 500; gold cities 31 + ITR 22.72 + connections 11.7 + deals 13 + Church Property 14. |
| 3 | Plot yields | **Done v137.** Visible plots carry `yields` / `fresh_water` / `worked`. Fogged plots do not (live yield would leak chopped forests). |
| 4 | Tech tree as a tree | **Done v138.** `tech_tree()`: `have`, `techs` (current / available / unavailable with `prereqs` + `missing` + turns), `rivals` (embassy only, techs they have that we do not). Live t173: Machinery current 2t; Guilds already in `have`; Inca ahead Sailing/Optics/Education; Ethiopia ahead Sailing/Chivalry/Machinery. `available_research` stays the leaf list. |
| 5 | Promotions on *own* units | **Done v137.** `units()` lists `promotions`, `xp_needed`, `upgrade_to`/`upgrade_gold`/`can_upgrade`. Live: Trebuchets ACCURACY_1, upgrade Cannon 140g not yet. |
| 6 | Visible-enemy / city hover | **Done v137** on the plot (strength, ranged, promotions; city strength/garrison/puppet/religion). Not exercised on a live *enemy* this session (front was idle). |
| 7 | Current deals with turns remaining | **Done v138.** `current_deals()`: other civ, items, `ends_on` / `turns_left`. Refuses if scratch is occupied; LoadCurrentDeal + ClearItems only on an empty table (verified t173: 4 deals, incoming_deal empty afterwards). Live: Ethiopia OB 12t; Inca salt 4 gpt 19t; Ethiopia salt 60g lump 28t; Inca silk 4 gpt 30t (just signed). |
| 8 | Great Person meters | **Done v137** on `city_screen.specialists[]`. **v139** `great_person_progress()` adds national General/Admiral XP and next Prophet faith, plus every city that has a specialist meter. |
| 9 | Foreign city banners | **Done v139.** Visible city plots carry `religions` (followers, pressure_per_turn, holy_city) for majority + religions with followers — same as the banner tooltip. Invisible religions are not queried. |
| 10 | Air / nuke / paradrop / rebase / airlift targets | **Done v139** as `unit_mission_targets` (paginated, visible plots only). `available_unit_actions` now lists those interface missions with `target_tool`. Live t178: bomber 466967 airstrike listed 0 visible targets (peace); rebase still offered. |

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

**Implemented v137.** `H.city_screen` / MCP `city_screen(city_id)` returns buildings, specialists + GP meters, every city-radius plot (worked / forced / can_work / buyable+buy_gold / yields), full production `queue`, `focus`, `avoid_growth`, `auto_specialists`, resistance/razing turns, `resource_demanded`, `can_annex`/`can_raze`/`can_unraze`.

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
- `happiness_breakdown`: toppanel.lua HappinessTipHandler buckets (luxuries, buildings, city count, population, puppets, specialists, …)
- `gold_breakdown`: city income vs international trade routes, connections, deal gpt, traits, religion, unit/building/improvement maintenance. **v145** `expenses.unit_paid` / `unit_free` / `unit_cost_per` (Economic Overview unit tooltip).
- `unit_supply` (v145): Military Overview header — cap (handicap/cities/population), remaining or deficit + production_penalty. Top-bar unit-supply string only appears when already over; the overview always has the numbers.
- `golden_age_progress` / `golden_age_threshold` (meter; `golden_age_turns` still the active-age timer)
- `science_breakdown` (v141): cities vs ITR, budget deficit, city-states, happiness, research agreements, `tech_city_cost_mod`
- `culture_breakdown` (v141): cities / happiness / traits / CS / religion / golden-age remainder, turns to next policy, `policy_city_cost_mod`
- `tourism_breakdown` (v141): tourism, great-work fill, influential_on/needed when cultural victory is on
- `faith_breakdown` (v141): cities / CS / religion, next great-person faith threshold

Live t178: gold `income.religion` 14 (Church Property) was previously omitted, so the old tooltip did not add up to `gold_per_turn`.

---

## 3. Plot tooltip

**Implemented v137** on visible plots: `yields` (`plot:CalculateYield`, same as `GetYieldString`), `fresh_water`, `worked`, `resource_qty`. Fogged plots keep revealed-stale terrain/resource/improvement/owner and **omit** live feature, yields, and occupants.

Movement cost is still missing (no safe plot-level getter found; do not fake path length).

---

## 4. Tech tree

**Implemented v138.** `H.tech_tree` / MCP `tech_tree()` matches techtree.lua statuses:

- `have`: short names already researched (`Team:IsHasTech`)
- `techs`: current / available (`CanResearch`) / unavailable (prereqs missing). Each has `prereqs` from `GameInfo.Technology_PrereqTechs`, `missing` of those we do not have, `turns` / `cost`, `queue` when set. `CanEverResearch` false (other-civ uniques) is omitted.
- `rivals`: met majors where `HasEmbassyAtTeam` is true, listing `ahead` (techs they have that we do not). Unmet civs are not mentioned.

`available_research` is still the leaf list `set_research` consumes. Live t173: Machinery 561/624, 2 turns; Education/Chivalry/Steel/Sailing available; Inca already has Education.

---

## 5. Units and combat hover

**Implemented v137** for own units (`promotions`, `xp`/`xp_needed`, `upgrade_to`/`upgrade_gold`/`can_upgrade`) and for visible plot units (strength, ranged, promotions). Visible city plots carry strength, garrison, puppet/razing, majority religion.

Stock still has more on EnemyUnitPanel (combat modifiers from terrain/flanking as hover, not only base strength). Previews remain the place for “if I attack.” Foreign-city followers/pressure are on the visible plot as of v139.

**v149:** Ranged combat strengths and air retaliation/interception warnings match the stock panel's getters. Air-strike target pages also carry previews. Live t182: 13 comparisons matched stock panel damage/strengths; all air cases had zero visible interceptors.

**v150:** Melee fire-support damage and maximum-HP caps now match the stock panel. Live t182: 115 comparisons matched damage/strengths; all support reads were zero. Individual combat modifier rows remain absent. Nonzero fire support/interceptors and nonempty legal air-strike target pages still need live verification.

---

## 6. Diplomacy reads still missing

| Human screen | Tool today | Gap |
|---|---|---|
| Current deals (what, with whom, turns left) | `current_deals` (v138) | OK. Uses LoadCurrentDeal only while scratch is empty, then ClearItems. `incoming_deal` remains the open table. Deal `CITIES` items include `name`/`city_id` as of v140. |
| Incoming table | `incoming_deal` | OK |
| Trade pockets | `trade_catalog` | OK; city rows can omit the name and keep only x,y |
| Relationship / global relations | `relationship` | OK (v107 gated third-party DP / CS friendship / unmet ally) |
| Declare-war confirmation | `war_consequences` | OK |
| City-state screen | `city_state_gifts` + `city_state_actions` + `city_state_bonuses` (v139) + `gift_unit` (v140) | Quests, influence, ally, pledge, tribute, trait/personality tooltips, current bonus amounts, unique unit, exported resources, gift unit. |
| Peace-with-terms | `make_peace` fires `HUMAN_NEGOTIATE_PEACE` | Cannot see what the AI will accept (cities, gold). `PEACE_TREATY` Add* crashed the process live; do not re-expose. |
| Third-party war/peace, human demand | readable on an incoming deal | Not proposable, so the AI’s price is never shown |

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
| Culture Overview extras | **Done v139** `culture_works` (slots, theming, tourism modifiers). Victory race remains `culture_overview`. |
| Espionage intrigue | **Done v139** `espionage_intrigue`. |
| Path overlay | **Blocked.** `Unit:GeneratePath` is NYI (throws). `GetPathEndTurnPlot` is nil without the mouse pathfinder (`UI.SendPathfinderUpdate` uses `UI.GetMouseOverHex()`). Live t183: `Plot:MovementCost` crashed the process even inside pcall — do not call it. `explore_frontier` stays hex distance / known-map connectivity, not path length. Do not fake turns-to-reach. |

Air / nuke / paradrop / rebase / airlift: **Done v139** `available_unit_actions` lists the interface missions; `unit_mission_targets` enumerates currently visible legal plots (fog never queried). Issue the order with `unit_mission`.

---

## 8. Smaller quality holes

- Production queue: `city_screen.queue` has the full list; `cities()` is still the head item only.
- Combat results: **v141** pillage `effect.gold_gained` (gold before/after the mission); city-strike/ranged kill now includes `damage_dealt` (remaining hp of the vanished unit). A barbarian-captured civilian is still not linked to the capture notice. Pillage/kill not live-exercised this turn (peace).
- Conversion notice: **Done v142** — banner `religions` + majority, or a tie note (live t179 Machu 2–2).
- Empty production labelled as a process: **Done v142** (live t179 Goshute Granary finished).
- Religion overview pressure: **Done v142** — same banner units as `city_religions` (Machu Orthodoxy 36, not 360).
- Discuss-screen buttons: **Done v142** `relationship.discuss` (live t179 Ethiopia stop-spreading true then false after they agreed; t180 Inca `share_intrigue` true after Cameahwait’s plot notice).
- Steal-tech chooser hidden behind another `blocking_name`: **Done v143** — `todo.steal_tech` + notice attaches victim/techs (live t181 Sailing from Inca while POLICY was current).
- Empty-treasury / Losing Gold: **Done v144** — `gold_breakdown.losing_science_from_deficit` + notice attaches gold/GPT. Strike flags when `IsStrike` is true.
- City-screen sell building: **Done v144** `sell_building` (live t182 two Airports + two Colosseums). Puppets refuse.
- Military Overview unit supply / Economic Overview unit+city gold rows: **Done v145** — `overview.unit_supply`, `gold_breakdown.expenses.unit_paid/unit_free/unit_cost_per`, `cities().building_maintenance` + `connection_gold` (connected only), `units().garrisoned`. Live t183: 24/37 remaining 13; 22 paid at 2.36g; Goshute/Pohokwi/Tiwanaku unconnected (getter still returned gold; omitted).
- Worker job / plot construction / CS quest coords: **Done v146** — `units().build` + `build_turns_left`; plot `under_construction` / `trade_route` / `resource_requires_tech`; `city_state_actions.quest_list` (kill-camp x/y only if revealed). Live t182 lumbermill 3t; Sidon/Wittenberg faith contests named with scores.
- Deal city items: **Done v140** — `name` / `city_id` on `CITIES` rows. Trade catalog still withholds x,y for unrevealed plots and already lists the name.
- Partial-move / stalled MOVE_TO units: **Done v139** — they appear in `todo.units` with `stalled_mission`.
- `known_world` size: **Done v140** `map_index` (resources / camps / ruins / foreign cities / visible natural wonders / in-sight world wonders). `known_world` remains the full plot dump.

---

## 9. Leak (too much information)

**Fixed v137:** fogged plots no longer call `GetFeatureType`. Stock UI has `GetRevealedImprovementType` / `GetRevealedRouteType` / `GetRevealedOwner` (already used) but no revealed-feature getter, so `feature` is omitted on `vis=false` rather than leaking a chopped forest. Tests now fail if `GetFeatureType` is touched under fog.

---

## 10. Action gaps that also hide information

Not reads, but a human cannot get the information without the matching action:

- Peace with terms (see §6). Native `AddPeaceTreaty` crashed this process; leave it closed.
- Third-party war/peace and human demand (see §6).
- Raze / unraze / annex: `city_task` exists (v137); not live-exercised this session.
- Tile / citizen management: focus, avoid-growth, work-plot, buy-plot (v137), specialist slot add/remove (v139), sell building (v144). Puppets still refuse.
- Production in a puppet: **closed v158.** `set_production` was the one city write missing the puppet guard, and live t192 an order pushed into captured Cusco stuck permanently (the stock city screen has no production picker for a puppet). `available_production` refuses there too, and `turn_status.todo` no longer lists production-automated cities -- its blocking hint was what led into the illegal order. `purchase_cost` needed no guard: `IsCanPurchase` is already false for a puppet.
- Gift a unit to a city-state: **Done v140** `gift_unit_options` / `gift_unit`.

---

## Suggested implementation order

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

Next:

1. Live nonzero fire support / interceptors, a nonempty legal air-strike target page, and live examples of the 119 modifier rows that only have regression coverage (they need war, barbarians, a golden age, rough attacker promotions).
2. Path overlay — **blocked** (GeneratePath NYI; MovementCost crashed live t183). Do not fake; do not call MovementCost.
3. CS tile-improvement gift write (`Game.DoMinorGiftTileImprovement`) when `can` is true.
4. Peace with terms — only via the real trade screen after `HUMAN_NEGOTIATE_PEACE` seeds PEACE_TREATY; do not call `AddPeaceTreaty`. Needs a second hotseat instance.
5. Link a barbarian-captured civilian to the capture notice (no `SerialEventUnitCaptured`). Needs war/barbs on a second instance.

The play loop, fog/met gating, combat previews, city screen, top bar, hover yields, tech tree, current-deal timers, late-game overviews, Military/Economic Overview gold+supply rows, worker jobs, and CS quest lists are in good shape. Path length cannot be closed on this build. Peace/capture still need war this solo seat does not have.
