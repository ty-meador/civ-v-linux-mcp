# MCP coverage audit for a Domination + founded-religion game (2026-09-19)

Read-only audit. No source was edited and nothing talked to the tuner socket. Sources read:
`harness/mcp_server.py` (76 tools), `harness/game.py`, `harness/lua/runtime.lua` (`H.*`),
`harness/lua/generic_popup_shim.lua`, and the stock BNW UI.

Path shorthand for stock UI (all under
`.../Sid Meier's Civilization V/steamassets/assets/`):

- `BNW/` = `dlc/expansion2/ui/ingame/`
- `BASE/` = `ui/ingame/` (only used where BNW does not override the file)

Status legend: **OK** covered, **PART** partly covered, **NONE** no tool.
Nothing below was live-tested; every "should work" is a static reading and needs a live probe before use.

---

## 0. Ranked gap list (most likely to block or mislead first)

| # | Gap | Area | Why it matters |
|---|-----|------|----------------|
| 1 | No belief listing (pantheon / founder / follower / enhancer / bonus / reformation) | Religion | The LLM must choose `BELIEF_*` names blind: no list of what is still available, no descriptions. Picks already taken by another civ are sent anyway (no guard in `H.found_religion` / `H.enhance_religion`), so the call returns `ok` and the block stays. |
| 2 | Peace cannot be negotiated on the trade table | Diplomacy | `PEACE_TREATY` is not in `_DEAL_ITEM_TYPES`; `make_peace` only fires `HUMAN_NEGOTIATE_PEACE`. A domination game needs peace with terms (cities, gold, third-party peace) and needs to read what the AI will accept. |
| 3 | City-capture decision is only reachable through the generic popup shim, and the shim drops the tooltips | Combat | Annex/puppet/raze/liberate works only if the shim was installed before the popup opened; the unhappiness numbers and the warmonger preview live in the button tooltips, which `AddButton`'s wrapper does not record. |
| 4 | Melee attack on a CITY is not listed, not previewed, and the standing-move record re-fires it | Combat | `H.melee_defender` looks at units only. An empty enemy city has no defender, so `H.move_unit` stores `pending_moves` and `H.resume_moves` re-pushes the attack next turn unordered (the exact bug fixed for units on 2026-09-18). |
| 5 | No ranged / air / city-target damage preview | Combat | `H.melee_preview` exists; `H.ranged_targets` lists targets with hp only. The stock panel shows expected damage both ways for ranged, air (incl. interceptors) and unit-vs-city. |
| 6 | Reformation belief cannot be chosen | Religion | `ENDTURN_BLOCKING_ADD_REFORMATION_BELIEF` hint says "no dedicated tool yet". The stock UI sends the same `Network.SendFoundPantheon`; `H.found_pantheon` refuses it because of its `CanCreatePantheon()` guard. This is an end-turn block with no tool. |
| 7 | Faith Great Person choice is routed to the wrong call | Religion | `blocking_hint` for `ENDTURN_BLOCKING_FAITH_GREAT_PERSON` points at `choose_free_great_person`, which requires `GetNumFreeGreatPeople() > 0` and sends `SendGreatPersonChoice`. Stock UI sends `Network.SendFaithGreatPersonChoice`. End-turn block with no working tool (Industrial era onward). |
| 8 | Declare-war consequences are never shown | Diplomacy | `declare_war` bypasses the BNW Declare War popup; that popup (its own Lua state, not GenericPopup) lists what breaks: DoFs, deals, trade routes, protected city-states, league effects. `dismiss_pending_popups` answers it "No" automatically. |
| 9 | City-state war / peace / pledge / bully / quests have no tools | Diplomacy | Only gold gifts exist. War on a minor goes through `DoFromUIDiploEvent` (stock uses `Network.SendChangeWar`); peace with a minor has no path at all. |
| 10 | Religion overview read is missing | Religion | No read for own religion + beliefs, holy city, world religions / holy cities / city counts, faith breakdown, next-prophet threshold, per-city pressure. `cities()` gives the majority name only. |
| 11 | Raze / unraze / annex-a-puppet later | Combat | No city-task tool besides the city strike. |
| 12 | Air, nuke, paradrop, airlift, rebase: no target listing | Combat | `unit_mission` can send them (mission + x,y), but nothing lists legal targets; `H.ranged_targets` was written for land/sea ranged units. |
| 13 | Human demand, third-party war/peace items, unit gifting | Diplomacy | Not in the deal item types / no tool. |
| 14 | Enemy unit strength is not in plot reads | Combat | `map_window` units carry owner/type/hp; a human hovering sees strength and promotions. |

---

## 1. Religion

### 1.1 What the stock UI offers vs. tool coverage

| Human action / screen | Tool | Status |
|---|---|---|
| Pantheon pick with belief list + descriptions | `found_pantheon(belief)` | PART: write only, no list |
| Found religion: pick religion icon/name, pantheon (if none), founder, follower, (Byzantium bonus) | `found_religion` | PART: write only, no list, no guard |
| Enhance: follower 2 + enhancer | `enhance_religion` | PART: same |
| Reformation belief | none | NONE (end-turn block) |
| Faith purchase of units/buildings in a city | `available_production` (faith, faith_can_buy, faith_only), `purchase_cost`, `purchase_production(yield_type="FAITH")` | OK |
| Faith Great Person choice (block) | hint points to `choose_free_great_person` | NONE in practice (wrong call) |
| Automatic faith purchase setting (Religion Overview dropdown) | none | NONE (low priority) |
| Spread religion / remove heresy | `unit_mission` with before/after `effects` (`H.religion_target`, `H.city_religion_state`) | OK |
| Great Prophet holy site | `available_unit_actions` lists `BUILD_HOLY_SITE` on the current plot, `unit_mission(MISSION_BUILD, build=...)` | OK (static reading) |
| Religion Overview: your religion, world religions, beliefs tabs | none | NONE |
| City religion breakdown (banner tooltip: followers per religion, pressure, holy city) | only majority name in `cities()`; followers only inside a spread result | PART |

### 1.2 Gaps with stock references

**G-R1. Belief listing.** `BNW/popups/choosereligionpopup.lua`:
`OnPantheonBeliefClick` -> `Game.GetAvailablePantheonBeliefs()`, `OnFounderBeliefClick` ->
`Game.GetAvailableFounderBeliefs()`, `OnFollowerBeliefClick` / `OnFollowerBelief2Click` ->
`Game.GetAvailableFollowerBeliefs()`, `OnEnhancerBeliefClick` -> `Game.GetAvailableEnhancerBeliefs()`,
`OnBonusBeliefClick` -> `Game.GetAvailableBonusBeliefs()`. Each returns belief IDs; rows are
`GameInfo.Beliefs[id]` with `.Type`, `.ShortDescription`, `.Description` (localize both).
`BNW/popups/choosepantheonpopup.lua` (~line 91 and ~103) does the same for pantheon and
`Game.GetAvailableReformationBeliefs()`. Available religions: `RefreshReligions()` in
choosereligionpopup.lua. A single read tool `available_beliefs()` returning every category plus
the religions still free covers all four decisions. All of this is on screen for a human.

**G-R2. Guards on found/enhance.** `CheckifCanCommit()` (choosereligionpopup.lua ~563) only enables
Confirm when every slot is filled; `OnYes()` (~584-622) sends
`Network.SendFoundReligion(player, religionID, customName, b1, b2, b3, b4, cityX, cityY)` or
`Network.SendEnhanceReligion(player, religionID, customName, b4, b5, cityX, cityY)`.
The harness sends the same calls but never checks that each belief is in the matching
`GetAvailable*` list or that the religion is unfounded. An invalid pick is dropped silently by the
engine. Recommend validating against the lists and polling for the effect.

**G-R3. Reformation.** `BNW/popups/choosepantheonpopup.lua`: `OnPopupMessage` takes
`BUTTONPOPUP_FOUND_PANTHEON` with `Data2` = pantheon flag; when it is 0 the screen lists
`Game.GetAvailableReformationBeliefs()` and `OnYes()` (~line 163) sends the SAME
`Network.SendFoundPantheon(Game.GetActivePlayer(), g_BeliefID)`. `H.found_pantheon` (runtime.lua
1231) blocks this with `CanCreatePantheon()`. Needs a separate path (or a relaxed guard when the
block is `ADD_REFORMATION_BELIEF`). The runtime.lua comment at 1255 says no call site was found;
this is it.

**G-R4. Faith Great Person.** `BNW/popups/choosefaithgreatperson.lua`: list filter
`player:CanTrain(info.ID, true, true, true, false)` (~line 30), confirm sends
`Network.SendFaithGreatPersonChoice(playerID, unit.ID)` (~line 128), popup type
`BUTTONPOPUP_CHOOSE_FAITH_GREAT_PERSON`. Fix `blocking_hint` (runtime.lua 2908) and add the call.

**G-R5. Religion overview read.** `BNW/popups/religionoverview.lua`:
`RefreshYourReligion()` -> `player:GetFaith()`, `GetMinimumFaithNextGreatProphet()`,
`GetFaithPerTurnFromCities()`, `GetFaithPerTurnFromMinorCivs()`, `GetFaithPerTurnFromReligion()`,
`GetReligionCreatedByPlayer()`, `Game.GetBeliefsInReligion(eReligion)`; `GetReligiousStatus()` ->
`Game.GetMinimumFaithNextPantheon()`; `RefreshWorldReligions()` ->
`Game.GetHolyCityForReligion(eReligion, iPlayer)`, `Game.GetNumCitiesFollowing(eReligion)`,
`Game.GetNumReligionsStillToFound()`; `RefreshBeliefs()` lists every religion's beliefs.
Visibility: the stock screen hides the founder/holy city name for unmet civs; mirror that
(check `Teams:IsHasMet` the way `RefreshWorldReligions` does) to stay inside rule 2.
"Religions still to found" is a race clock the LLM needs.

**G-R6. City religion breakdown.** `BNW/infotooltipinclude.lua` `GetReligionTooltip(city)`
(~1200-1290): per religion `city:GetNumFollowers(eReligion)`, `city:IsHolyCityForReligion`,
`city:GetPressurePerTurn(eReligion)` (returns pressure, trade-route count; divide by
`GameDefines.RELIGION_MISSIONARY_PRESSURE_MULTIPLIER`). A human sees this on any visible city
banner, so it is allowed for own cities and for foreign cities on visible/revealed plots.
Needed to pick missionary/inquisitor targets.

**G-R7. Auto faith purchase.** religionoverview.lua ~419-425:
`player:GetFaithPurchaseType()`, `Network.SendFaithPurchase(player, type, index)`. Low priority.

---

## 2. Combat

### 2.1 Coverage table

| Human action / read | Tool | Status |
|---|---|---|
| Melee attack on a unit (right-click move) | `move_unit` + `attack_targets` with `preview` | OK |
| Melee attack on a city | `move_unit` works by static reading; not listed, no preview, standing-move bug | PART (G-C1) |
| Ranged attack | `unit_mission(MISSION_RANGE_ATTACK, x, y)` + `ranged_targets` | OK, no damage preview (G-C2) |
| City bombard | `available_city_strikes`, `city_ranged_attack` | OK, no preview |
| Combat preview (EnemyUnitPanel) | melee vs unit only | PART |
| City captured: annex / puppet / raze / liberate | `generic_popup` + `answer_popup` | PART (G-C3) |
| Raze later / stop razing / annex a puppet later | none | NONE (G-C4) |
| Pillage, heal, fortify, alert, sleep, set up ranged, embark | `unit_mission` (generic `CanStartMission` guard + net path) | OK |
| Air strike / air sweep / intercept / rebase | `unit_mission` can send; no target lists | PART (G-C5) |
| Nuke, paradrop, airlift | same; `_with_target_result` wraps NUKE and PARADROP | PART (G-C5) |
| Great General citadel | `BUILD_CITADEL` via `available_unit_actions` + `MISSION_BUILD` | OK (static) |
| Upgrade, promote, disband | `upgrade_unit`, `choose_promotion`, `disband_unit` | OK |
| Gift a unit | none | NONE (G-C6) |
| Barbarian camps | `map_window` / `known_world` improvement (also the fogged "revealed" value) | OK |
| Visible enemy units | `map_window` plot `units` (owner, id, type, hp); `turn_digest` hostiles near a named city | PART (G-C7) |
| War state | `diplomacy().at_war`, `relationship().turns_locked_in_war` | OK. No war-score read: BNW shows none to the player, so none is owed. |
| Path / turns-to-reach | none (`Unit:GeneratePath` throws in this build); `explore_frontier` has a BFS hint | NONE (G-C8) |
| Declare war by moving / shooting | popup auto-answered "No" | see G-D2 |

### 2.2 Gaps with stock references

**G-C1. City as a melee target.** `H.melee_defender` (runtime.lua 2247) scans `plot:GetUnit(i)`
only. Consequences: `H.melee_targets` never lists an adjacent enemy city; `H.attack_before`
returns `attack=false`, so `move_unit` reports a plain move; and `H.move_unit` (end of function)
stores `H.pending_moves[unit_id]`, which `H.resume_moves` re-pushes next turn. Stock reference:
`BNW/worldview/enemyunitpanel.lua` `UpdateCombatOddsUnitVsCity(pMyUnit, pCity)` (~281-343):
`pMyUnit:GetMaxAttackStrength(fromPlot, toPlot, nil)`, `pCity:GetStrengthValue()`,
`pMyUnit:GetCombatDamage(iMyStrength, iTheirStrength, pMyUnit:GetDamage() + fireSupport, false, false, true)`
and `pMyUnit:GetCombatDamage(iTheirStrength, iMyStrength, pCity:GetDamage(), false, true, false)`.
The order itself is the normal right-click: `BNW/worldview/worldview.lua` `MovementRButtonUp`
(~642-709), `Game.SelectionListGameNetMessage(GAMEMESSAGE_PUSH_MISSION, MISSION_MOVE_TO, x, y, ...)`.
Fix: treat an enemy (at-war) visible city on the destination as an attack: list it, preview it,
never store a standing move, and report city hp before/after and capture.

**G-C2. Ranged / air / city-strike preview.** enemyunitpanel.lua `UpdateCombatOddsUnitVsUnit`
(~637-707): ranged `pMyUnit:GetMaxRangedCombatStrength(pTheirUnit, nil, true, true)` and
`pMyUnit:GetRangeCombatDamage(pTheirUnit, nil, false)`; vs city
`GetRangeCombatDamage(nil, pCity, false)`; air: retaliation
`pTheirUnit:GetAirStrikeDefenseDamage(pMyUnit, false)` /
`pCity:GetAirStrikeDefenseDamage(pMyUnit, false)` and
`pMyUnit:GetInterceptorCount(plot, pTheirUnit, true, true)` (visible AA only). City shooting a
unit: `UpdateCombatOddsCityVsUnit(myCity, theirUnit)` (~1684). Add `preview` to every
`ranged_targets` / `available_city_strikes` row.

**G-C3. City captured popup.** `BNW/popupsgeneric/puppetcitypopup.lua`,
`PopupLayouts[BUTTONPOPUP_CITY_CAPTURED]`:
- Liberate: `Network.SendLiberateMinor(iLiberatedPlayer, cityID)` (only when a liberated player is offered)
- Annex: `Network.SendDoTask(cityID, TaskTypes.TASK_ANNEX_PUPPET, -1, -1, false, false, false, false)`
- Puppet: `Network.SendDoTask(cityID, TaskTypes.TASK_CREATE_PUPPET, -1, -1, false, false, false, false)`
- Raze: guard `activePlayer:CanRaze(newCity)`, `Network.SendDoTask(cityID, TaskTypes.TASK_RAZE, ...)`
- Tooltips carry `iUnhappinessForAnnexing`, `iUnhappinessForPuppeting` and
  `activePlayer:GetWarmongerPreviewString(iPreviousOwner)` (lines 73-105).

The shim (`generic_popup_shim.lua`) stores `text` and `fn` but drops the third `AddButton`
argument, so the unhappiness and warmonger numbers never reach the LLM. It also fails when the
popup opened before the shim loaded (the code says so). Recommend a dedicated
`city_capture_options()` / `resolve_captured_city(choice)` that reads the same values and sends
the same calls, plus recording `tip` in the shim. `BASE/popupsgeneric/liberateminorpopup.lua`
(`BUTTONPOPUP_LIBERATE_MINOR`) is the sibling case.

**G-C4. Raze / unraze / annex later.** `BNW/cityview/cityview.lua`: raze button guards
`pCity:IsOccupied()`, `pPlayer:CanRaze(pCity, false)` (~1581-1607) and opens
`BUTTONPOPUP_CONFIRM_CITY_TASK` with `Data2 = TaskTypes.TASK_RAZE` (~2474;
`BASE/popupsgeneric/confirmcitytaskpopup.lua` sends the `Network.SendDoTask`). Unraze:
`Network.SendDoTask(pCity:GetID(), TaskTypes.TASK_UNRAZE, -1, -1, false, false, false, false)`
(~2494), guard `pCity:IsRazing()`. Annex a puppet: `BASE/popupsgeneric/annexcitypopup.lua`
(`BUTTONPOPUP_ANNEX_CITY`), `TASK_ANNEX_PUPPET`. `cities()` should also expose
`puppet` / `occupied` / `razing` / `resistance turns` if it does not already.

**G-C5. Air, nuke, paradrop, airlift, rebase targets.** Orders: worldview.lua `AirStrike`
(~409-426) and `missionTypeLButtonUpHandler` (~364-374) both end in
`Game.SelectionListGameNetMessage(GAMEMESSAGE_PUSH_MISSION, eInterfaceModeMission, plotX, plotY, 0, false, bShift)`
which is what `unit_mission` already does. Target highlighting with the guards is in
`BNW/ingame.lua`: `pHeadSelectedUnit:CanRebaseAt(plot, x, y)` (~608),
`CanParadropAt(plot, x, y)` (~644), `CanAirliftAt(plot, x, y)` (~674); nuke uses
`CanNukeAt(x, y)`; air sweep `CanAirSweepAt(x, y)` (not in the UI grep, verify the method exists
before calling). `available_unit_actions` should return `rebase_targets`, `paradrop_targets`,
`nuke_range` etc. the same way it returns `ranged_targets`. Also confirm live that
`H.ranged_targets` lists targets for an air unit (it keys on `IsRanged()` and the `Range` column).
Unit-panel buttons that open an interface mode (`INTERFACEMODE_*`) are skipped by
`available_unit_actions`, so the LLM may not learn that a rebase or paradrop is possible at all.

**G-C6. Gift unit.** `BNW/popups/citystatediplopopup.lua` `OnGiftUnit` (~901) sets
`INTERFACEMODE_GIFT_UNIT`; `BNW/ingame.lua` `GiftUnit` (~190-215) guards
`pUnit:CanDistanceGift(iToPlayer)` and raises `BUTTONPOPUP_GIFT_CONFIRM`;
`BASE/popupsgeneric/confirmgiftpopup.lua` sends `Network.SendGiftUnit(iGiftedPlayer, iUnitIndex)`.

**G-C7. Enemy unit detail.** `H.describe_plot` gives owner/id/type/hp. A human hover
(enemyunitpanel.lua `UpdateUnitStats`, `UpdateUnitPromotions`, `UpdateCityStats`) also shows
base/ranged strength, moves, promotions, and for cities strength + hp. All visible-plot
information; add it so the LLM can judge a front without attacking. A "visible hostiles within N
of my units/cities" read would save many `map_window` calls during a siege.

**G-C8. Path turns / ZOC.** No stock Lua gives this outside the pathfinder event
(`worldview.lua` `OnUIPathFinderUpdate`, `UpdatePathFromSelectedUnitToMouse`), which needs the
mouse. Not blocking; document that `move_unit` multi-turn orders are re-pushed by
`H.resume_moves` and that ZOC will stop a unit early.

---

## 3. Diplomacy

### 3.1 Coverage table

| Human action / read | Tool | Status |
|---|---|---|
| Trade: gold, GPT, resources, embassy, open borders, DP, RA, cities | `trade_catalog`, `propose_deal`, `negotiate_deal` | OK |
| Peace treaty on the table, with terms | none (`make_peace` fires an event only) | NONE (G-D1) |
| Third-party war / peace items | read in `incoming_deal`; not proposable | PART (G-D5) |
| Human demand | none | NONE (G-D5) |
| Declare war with the consequence list | `declare_war` (no preview) | PART (G-D2) |
| Denounce, DoF propose/accept | `denounce`, `propose_friendship`, `accept_friendship` | OK |
| AI requests (coop war, don't settle, stop spying, stop converting, denounce request) | `discussion`, `respond_discussion`, `diplo_event` | OK (button-driven) |
| Human asks AI: don't settle, stop spying, stop spreading religion, stop digging, coop war, share intrigue | `diplo_event` escape hatch only | PART (G-D6) |
| City-state gold gift | `city_state_gifts`, `minor_gold_gift` | OK |
| City-state pledge / revoke, bully gold / unit, war, peace, tile improvement gift, unit gift, stop unit spawning, quests | none | NONE (G-D3, G-D4) |
| World Congress | `league_status`, `league_propose_enact`, `league_propose_repeal`, `league_cast_votes` | OK |
| Warmonger preview | none | NONE (G-D2, G-C3) |

### 3.2 Gaps with stock references

**G-D1. Peace deals.** `BNW/leaderhead/leaderheadroot.lua` `OnWarOrPeace` (~267-277): at war ->
`Game.DoFromUIDiploEvent(FROM_UI_DIPLO_EVENT_HUMAN_NEGOTIATE_PEACE, g_iAIPlayer, 0, 0)`, which
makes the AI open the trade screen; guards in `OnShowHide` (~150-194): `CanChangeWarPeace`,
`GetNumTurnsLockedIntoWar`. `BNW/worldview/tradelogic.lua` then seeds the table itself (~300-302):
`g_Deal:AddPeaceTreaty(g_iUs, GameDefines.PEACE_TREATY_LENGTH)` +
`g_Deal:AddPeaceTreaty(g_iThem, ...)`; durations from `Game.GetDealDuration()` /
`Game.GetPeaceDuration()` (lines 33-34); proposal `UI.DoProposeDeal()` (~842/869); helper buttons
`UI.DoEqualizeDealWithHuman()` (~886) and `UI.DoWhatDoesAIWant()` (~898). While at war the UI
restricts the pockets (~631, ~1026, ~1414). Since headless `AddPeaceTreaty` crashed the game
(runtime.lua 1350 comment), the route is the one `propose_deal` already uses: drive the real
screen. After `HUMAN_NEGOTIATE_PEACE` the treaty is already on the table; add city/gold items with
the existing pocket handlers, then press equalize / what-do-you-want / propose. Today `make_peace`
returns `ok` and leaves an open trade or leader screen for the generic discussion tools, with no
way to add terms. `_DEAL_ITEM_TYPES` (game.py 2768) needs a peace mode, and `trade_catalog` should
say which items are legal while at war.

**G-D2. Declare-war consequences and warmonger preview.** `BNW/popups/declarewarpopup.lua` is a
separate Lua state with its OWN `AddButton` / `HideWindow` (lines 24-48), hosting
`BUTTONPOPUP_DECLAREWARMOVE` (~658), `BUTTONPOPUP_DECLAREWARRANGESTRIKE` (~725) and
`BUTTONPOPUP_DECLAREWAR_PLUNDER_TRADE_ROUTE` (~606). `GatherData(RivalId, Text)` (~127-400) builds
what the human reads before confirming: their city-state allies and protected minors
(`GetAlly`, `IsProtectingMinor`), DoF/denounce state (`IsDoF`, `IsDenouncedPlayer`), current deals
that will be cancelled (`GetNumCurrentDeals`, scratch deal iteration), trade routes lost
(`GetTradeRoutes`, `GetTradeRoutesToYou`), and league effects. The Yes handler sends
`Network.SendChangeWar(eRivalTeam, true)` and then, for a major,
`Game.DoFromUIDiploEvent(FROM_UI_DIPLO_EVENT_HUMAN_DECLARES_WAR, Teams[eRivalTeam]:GetLeaderID(), 0, 0)`
(~629-634, 697-702, 739-744). The harness: (a) `declare_war` sends only the DoFromUIDiploEvent and
shows none of this; (b) `dismiss_pending_popups` (game.py ~962-991) closes `DeclareWarPopup` with
`HideWindow` = "No", so an attack-move into a neutral civ silently does nothing; (c) the
GenericPopup shim cannot see this popup because it lives in another state.
Add `declare_war_preview(player_id)` using the same getters. The per-city warmonger text is
`activePlayer:GetWarmongerPreviewString(iOwner)` (`BNW/citybannermanager.lua` ~215, enemy city
banner tooltip, and puppetcitypopup.lua 76/90/105); expose it on visible enemy cities.

**G-D3. City-state actions.** `BNW/popups/citystatediplopopup.lua`:
- Pledge: `OnPledgeButtonClicked` (~625) guard `pPlayer:CanMajorStartProtection(iActivePlayer)`,
  `Game.DoMinorPledgeProtection(activePlayer, minorID, true)`; revoke (~640)
  `CanMajorWithdrawProtection`, same call with `false`.
- Bully: `OnYesBully` (~1073) `Game.DoMinorBullyGold(iActivePlayer, minorID)` /
  `Game.DoMinorBullyUnit(...)`; guards `CanMajorBullyGold`, `CanMajorBullyUnit` (~958, ~971),
  amount `GetMinorCivBullyGoldAmount(iActivePlayer)` (~955); the tooltip shows the bully score breakdown.
- War: `OnWarButtonClicked` (~670) raises `BUTTONPOPUP_DECLAREWARMOVE` with the minor's TEAM id,
  whose Yes sends `Network.SendChangeWar(team, true)`.
- Peace: `OnPeaceButtonClicked` (~678) `Network.SendChangeWar(g_iMinorCivTeamID, false)`, guard
  `pPlayer:IsPeaceBlocked(iActiveTeam)` (~458, allied to someone at war with you) .
- Tile improvement gift: `CanMajorGiftTileImprovement`, `GetGiftTileImprovementCost` (~831-833, ~914).
- Unit spawning toggle: `Network.SendMinorNoUnitSpawning(minorID, bool)` (~704).
- Buyout: `CanMajorBuyout` / `Game.DoMinorBuyout` (~655) n/a unless Austria/Venice.

Harness state: `declare_war(minor)` goes out as `DoFromUIDiploEvent(HUMAN_DECLARES_WAR)` with no
minor check in `H.diplo_event`; the stock UI never does that for a minor. `make_peace(minor)`
fires `HUMAN_NEGOTIATE_PEACE`, which has no meaning for a minor. Both should switch to
`Network.SendChangeWar` for minors with the guards above. These matter in a domination game:
city-states allied to the target join the war, and peace with them is the cheap way to clear a flank.

**G-D4. Quests.** Same file ~587-598: `GetActiveQuestText(iActivePlayer, minorID)` and
`GetActiveQuestToolTip(...)` (defined in `BNW/citystatestatushelper.lua`; verify the file name).
No tool lists quests; `ENDTURN_BLOCKING_MINOR_QUEST` popups are swept by `wait_for_my_turn`, so
the quest text is likely lost unless `turn_digest` records the notification. "Spread your
religion" and "kill the camp" quests are directly relevant.

**G-D5. Demand and third-party items.** Demand: leaderheadroot.lua `OnDemand` (~256)
`UI.OnHumanDemand(g_iAIPlayer)`; tradelogic.lua state `DIPLO_UI_STATE_HUMAN_DEMAND`, button
`UI.DoDemand()` (~861-862). Third party: tradelogic.lua ~3150-3190 builds the lists (guards via
`IsPossibleToTradeItem(..., TRADE_ITEM_THIRD_PARTY_WAR / _PEACE, team)`), and ~3280-3282
`g_Deal:AddThirdPartyWar(iWho, iOtherTeam)` /
`g_Deal:AddThirdPartyPeace(iWho, iOtherTeam, GameDefines.PEACE_TREATY_LENGTH)`. Bribing a
neighbour into the war is a staple of domination play. Given the headless-deal crash history,
drive the UI pockets as `propose_deal` does.

**G-D6. Human-initiated discussion requests.** `BNW/leaderhead/discussiondialog.lua` events used:
`HUMAN_DISCUSSION_DONT_SETTLE`, `HUMAN_DISCUSSION_STOP_SPYING`,
`HUMAN_DISCUSSION_STOP_SPREADING_RELIGION`, `HUMAN_DISCUSSION_STOP_DIGGING`,
`HUMAN_DISCUSSION_SHARE_INTRIGUE`, `COOP_WAR_OFFER` (data1 = target), `DENOUNCE`,
`HUMAN_DISCUSSION_WORK_WITH_US` / `END_WORK_WITH_US`. All go through
`Game.DoFromUIDiploEvent`, so `diplo_event` can send them, but the stock dialog only shows each
button under conditions (look at the button-visibility block in discussiondialog.lua before the
callbacks). `diplo_event` applies no such guard and its tool doc does not list these names.
Add thin wrappers or at least document them; "stop spreading religion" and coop war are the
relevant ones.

---

## 4. Rule review of existing tools

Rule 1 (network path only):

- No live `Unit:PushMission` / `Unit:DoCommand` call remains in runtime.lua; every grep hit is a
  comment or a `CanDoCommand` guard. Orders go through `net_unit_message`
  (`Game.SelectionListGameNetMessage`). Good.
- `declare_war` on a city-state: sends `DoFromUIDiploEvent` where the stock UI sends
  `Network.SendChangeWar`. Not a direct state mutation, but not the stock path either; whether it
  syncs on LAN for a minor is unverified. See G-D3.
- `H.propose_deal_headless_reference` (runtime.lua 1297) still contains `deal:Add*` calls and the
  crashing `AddPeaceTreaty`. It is reference code; make sure nothing can reach it from a tool.
- `H.trade_catalog` calls `deal:SetFromPlayer` / `SetToPlayer` on the scratch deal. Local UI
  scratch object, same as the stock trade screen does; acceptable, but it can disturb a trade
  screen that is open at that moment.
- `dismiss_*` helpers use `ContextPtr:SetHide(true)` / `UIManager:DequeuePopup`: UI only, no game state.
- `H.move_unit` standing-move record re-issuing an attack on a city (G-C1) is not a rule-1
  violation but it is an unordered state change.

Rule 2 (human-visible reads only):

- `H.trade_catalog` `tradeable_cities(them, us)` returns `x`, `y` for every city the other civ
  could trade, without an `IsRevealed` check. The trade screen shows the city NAME and population
  only; coordinates of an unrevealed city leak map knowledge. Gate x/y on
  `city:Plot():IsRevealed(team, false)` as `H.diplomacy` already does for capitals.
- `H.relationship` uses `GetApproachTowardsUsGuess` and `GetOpinionTable`, the same calls the
  stock diplo tooltip uses. Fine.
- `H.describe_plot`, `H.melee_defender`, `H.ranged_targets`, `H.hostiles_near_named_city`,
  `H.combat_side` all gate on `IsVisible` and `IsInvisible`. Fine.
- Any new religion/world read must copy the met-civ gating from religionoverview.lua, and any new
  combat preview must only count VISIBLE interceptors (`GetInterceptorCount(..., true, true)`).

---

## 5. Suggested implementation order

1. `available_beliefs()` + validation in found/enhance; reformation path; faith great person fix (G-R1..R4). Small, read-mostly, and they remove two end-turn blocks.
2. City-as-melee-target fix incl. the standing-move bug, and previews for ranged / city strike (G-C1, G-C2).
3. Dedicated city-capture read + resolve, with unhappiness and warmonger text; raze / unraze / annex (G-C3, G-C4).
4. Peace negotiation through the real trade screen (G-D1), then third-party war and demand (G-D5).
5. `declare_war_preview` and correct handling of the BNW DeclareWarPopup state (G-D2).
6. City-state war / peace / pledge / bully / quests (G-D3, G-D4).
7. `religion_overview()` and per-city religion breakdown (G-R5, G-R6).
8. Air / nuke / paradrop / rebase target lists, unit gifting, enemy unit detail (G-C5..C7).
