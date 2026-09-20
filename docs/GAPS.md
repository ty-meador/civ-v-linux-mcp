# Information-parity gaps (human seat vs LLM)

Date: 2026-09-19 (updated same day, runtime **v139**, Shoshone t176). Goal: the LLM should have the same information a human in this seat would have, in every situation. Rule 2 still holds: never more than that (fogged tiles carry no live occupants, unmet civs do not exist, no private AI state).

This is a **read** audit. Action-only holes are listed only where they also hide information a human gets by opening the same screen.

`docs/COVERAGE_AUDIT_2026-09-19.md` is partly stale. Most of its ranked list was implemented during the Shoshone game. v137 used this save as a feedback loop: open the screen that was blocking a real decision, implement it, verify live, play the turn.

Sources: `harness/mcp_server.py`, `harness/lua/runtime.lua` (`H.*` snapshots), `harness/game.py`, stock BNW UI. Live notes: this file (t163–176) and `docs/NOTES.md`.

---

## Already at parity (do not re-open)

Play loop, fog/met gating, combat previews (melee vs unit and city, ranged, city bombard), religion / culture / league / spy overviews, trade catalog + current table, diplomacy and relationship (visible approach, opinion lines, public relations), war-declaration consequences, city-capture options with unhappiness and warmonger text, city-state gifts/quests/pledge/tribute, spaceship progress, explore-frontier, “refused actions say why.”

**Landed v137 (live on Pocatello t163):** city screen; top-bar luxuries / happiness / gold / golden-age meter; plot yields + fresh water + worked; own-unit promotions / XP-to-next / upgrade preview; visible-plot unit strength+promotions and city banner (strength, garrison, puppet/razing, majority religion); specialist GP meters on `city_screen`; fogged plots no longer leak live `GetFeatureType`.

**Landed v138 (live on Pocatello t173):** `tech_tree` (have / current / available / unavailable+prereqs+missing; embassy rivals’ ahead techs); `current_deals` (who, items, turns remaining — LoadCurrentDeal only while scratch is empty, then ClearItems).

**Landed v139:** foreign visible-city `religions` (followers/pressure/holy city, majority+followers only); `great_person_progress` (city specialist meters + national General/Admiral + Prophet faith); `change_specialist` / `set_auto_specialists`; `archaeology_options`/`choose_archaeology` and `maya_options`/`choose_maya_bonus`; `unit_mission_targets` (visible rebase/paradrop/airlift/nuke/airstrike; fog never queried); `domination_progress`, `wonder_overview` (locations only in sight), `espionage_intrigue`, `city_state_bonuses`, `demographics` (public aggregates; unmet best/worst identities masked), `culture_works`. Partial-move stalls now appear in `turn_status` todo.

---

## 0. Ranked remaining reads

| # | Gap | Status |
|---|-----|--------|
| 1 | City screen | **Done v137.** `city_screen(city_id)` + writes `set_city_focus` / `set_avoid_growth` / `change_working_plot` / `buy_city_plot` / `city_task`. Specialist slot add/remove is **v139** `change_specialist`. Live: Agaidika was not starving — empire −4 happiness; it already had Library/Granary/Pagoda/Colosseum and an empty queue. |
| 2 | Top-bar tooltips | **Done v137.** `overview.luxuries`, `happiness_breakdown`, `gold_breakdown`, `golden_age_progress`/`threshold`. Live t163: −4 happiness = 46 vs 50 (21 from city count, 20.9 pop, 6.65 puppet pop); −4 gpt = 55 city income vs 40 unit + 37 building maintenance. Four luxuries, all `last_copy`. |
| 3 | Plot yields | **Done v137.** Visible plots carry `yields` / `fresh_water` / `worked`. Fogged plots do not (live yield would leak chopped forests). |
| 4 | Tech tree as a tree | **Done v138.** `tech_tree()`: `have`, `techs` (current / available / unavailable with `prereqs` + `missing` + turns), `rivals` (embassy only, techs they have that we do not). Live t173: Machinery current 2t; Guilds already in `have`; Inca ahead Sailing/Optics/Education; Ethiopia ahead Sailing/Chivalry/Machinery. `available_research` stays the leaf list. |
| 5 | Promotions on *own* units | **Done v137.** `units()` lists `promotions`, `xp_needed`, `upgrade_to`/`upgrade_gold`/`can_upgrade`. Live: Trebuchets ACCURACY_1, upgrade Cannon 140g not yet. |
| 6 | Visible-enemy / city hover | **Done v137** on the plot (strength, ranged, promotions; city strength/garrison/puppet/religion). Not exercised on a live *enemy* this session (front was idle). |
| 7 | Current deals with turns remaining | **Done v138.** `current_deals()`: other civ, items, `ends_on` / `turns_left`. Refuses if scratch is occupied; LoadCurrentDeal + ClearItems only on an empty table (verified t173: 4 deals, incoming_deal empty afterwards). Live: Ethiopia OB 12t; Inca salt 4 gpt 19t; Ethiopia salt 60g lump 28t; Inca silk 4 gpt 30t (just signed). |
| 8 | Great Person meters | **Done v137** on `city_screen.specialists[]`. **v139** `great_person_progress()` adds national General/Admiral XP and next Prophet faith, plus every city that has a specialist meter. |
| 9 | Foreign city banners | **Done v139.** Visible city plots carry `religions` (followers, pressure_per_turn, holy_city) for majority + religions with followers — same as the banner tooltip. Invisible religions are not queried. |
| 10 | Air / nuke / paradrop / rebase / airlift targets | **Done v139** as `unit_mission_targets` (paginated, visible plots only). `available_unit_actions` now lists those interface missions with `target_tool`. No air units on this save yet — unit tests cover fog/pagination. |

---

## Live loop (t174–176, Pocatello)

t174: spy Tetoharsky traveling to Cusco to steal (1t). Unmet civ Renaissance. t175: Machinery done; Education 10t. Faith 58, saving Holy Warriors Crossbow 240f. Capital pop 9, National College 12t. Happiness +2, gold 141 at −3/turn. Game left after `end_turn` t175; named save `Pocatello_0176 AD-1160`.

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

Specialist slot click is **v139** `change_specialist(city_id, building, add)` via `Network.SendDoTask` (`TASK_NO_AUTO_ASSIGN_SPECIALISTS` then ADD/REMOVE). Puppets still refuse citizen writes (AI runs them; annex first).

---

## 2. Top bar

**Implemented v137** on `overview` / `H.player_summary`:

- `luxuries`: revealed `RESOURCECLASS_LUXURY` with `available`/`total`/`imported`/`exported`/`last_copy`
- `happiness_breakdown`: toppanel.lua HappinessTipHandler buckets (luxuries, buildings, city count, population, puppets, specialists, …)
- `gold_breakdown`: city income, connections, deal gpt, unit/building/improvement maintenance
- `golden_age_progress` / `golden_age_threshold` (meter; `golden_age_turns` still the active-age timer)

Science / culture / tourism tooltip line-items are still omitted (rates are already on `overview`).

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

---

## 6. Diplomacy reads still missing

| Human screen | Tool today | Gap |
|---|---|---|
| Current deals (what, with whom, turns left) | `current_deals` (v138) | OK. Uses LoadCurrentDeal only while scratch is empty, then ClearItems. `incoming_deal` remains the open table. Deal city items still omit the name (x,y only). |
| Incoming table | `incoming_deal` | OK |
| Trade pockets | `trade_catalog` | OK; city rows can omit the name and keep only x,y |
| Relationship / global relations | `relationship` | OK (v107 gated third-party DP / CS friendship / unmet ally) |
| Declare-war confirmation | `war_consequences` | OK |
| City-state screen | `city_state_gifts` + `city_state_actions` + `city_state_bonuses` (v139) | Quests, influence, ally, pledge, tribute, trait/personality tooltips, current bonus amounts, unique unit, exported resources. Gift-a-unit still missing. |
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
| Path overlay | Still missing. `Unit:GeneratePath` throws in this build; `explore_frontier` is hex distance, not path length. Document or approximate; don’t fake it. |

Air / nuke / paradrop / rebase / airlift: **Done v139** `available_unit_actions` lists the interface missions; `unit_mission_targets` enumerates currently visible legal plots (fog never queried). Issue the order with `unit_mission`.

---

## 8. Smaller quality holes

- Production queue: `city_screen.queue` has the full list; `cities()` is still the head item only.
- Combat results: pillage gold is only in the digest; a city strike that kills omits `damage_dealt`; a barbarian-captured civilian is not linked to the capture notice.
- Deal city items: x,y without the city name (trade catalog can also omit the name).
- Partial-move / stalled MOVE_TO units: **Done v139** — they appear in `todo.units` with `stalled_mission`.
- `known_world` size: large revealed maps still stress the tuner. A compact “resources / camps / foreign cities / wonders” index would match how a human actually looks at the map, instead of dumping every plot.

---

## 9. Leak (too much information)

**Fixed v137:** fogged plots no longer call `GetFeatureType`. Stock UI has `GetRevealedImprovementType` / `GetRevealedRouteType` / `GetRevealedOwner` (already used) but no revealed-feature getter, so `feature` is omitted on `vis=false` rather than leaking a chopped forest. Tests now fail if `GetFeatureType` is touched under fog.

---

## 10. Action gaps that also hide information

Not reads, but a human cannot get the information without the matching action:

- Peace with terms (see §6). Native `AddPeaceTreaty` crashed this process; leave it closed.
- Third-party war/peace and human demand (see §6).
- Raze / unraze / annex: `city_task` exists (v137); not live-exercised this session.
- Tile / citizen management: focus, avoid-growth, work-plot, buy-plot (v137) and specialist slot add/remove (v139). Puppets still refuse.
- Gift a unit to a city-state (`Network.SendGiftUnit` after `CanDistanceGift`).

---

## Suggested implementation order

Done v137: city screen + writes, top-bar breakdowns, plot yields, own promotions, visible unit/city hover, specialist GP meters, fog feature leak.

Done v138: tech tree; current deals with turns remaining.

Done v139: foreign-city religions, national GP, specialist clicks, archaeology/Maya, air-mission targets, domination/wonders/intrigue/CS bonuses, demographics, culture works, stalled-move todo.

Next:

1. Gift a unit to a city-state (`CanDistanceGift` + confirm popup + `SendGiftUnit`).
2. Deal/trade-catalog city names when the city is revealed.
3. Compact map index (resources / camps / foreign cities / wonders) so `known_world` is not the only map read.
4. Combat-result holes (pillage gold, city-strike kill damage).
5. Peace with terms — only if a non-crashing path is found; do not call `AddPeaceTreaty`.

The play loop, fog/met gating, combat previews, city screen, top bar, hover yields, tech tree, current-deal timers, and the late-game overview screens are in good shape. Remaining work is CS unit gifts, named deal cities, a compact map index, and the still-closed peace-with-terms path.
