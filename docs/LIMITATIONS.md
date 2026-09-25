# Declared limitations

What the harness will not do, and why, as of runtime v203 (2026-09-25). Each item was checked against the
engine, not inferred; the check is named. `docs/GAPS.md` keeps the full audit history.

## Engine rules that look like missing features

- **Melee fire support never fires.** Stock Brave New World ships `FIRE_SUPPORT_DISABLED = 1` in
  `GlobalDefines` (base and expansion2), so `Unit:GetFireSupportUnit` returns nothing even with a ranged unit
  adjacent to the defender, in range, with line of sight and attacks left (S1 t266). The preview's
  `fire_support_damage` is a faithful 0; it would light up under a mod that flips the define.
- **Lump-sum gold needs a Declaration of Friendship.** A Brave New World rule for humans and AIs alike;
  gold per turn is not gated. The stock pocket just hides the Gold row; `trade_catalog.gold.note` says why
  (checked S1 t266: of four met civs only the friend traded lump gold either way).
- **Ranged units need line of sight** unless they have Indirect Fire (`CanRangeStrikeAt` false through a
  hill), exactly as the stock game plays it.
- **The golden-age combat row** exists only for a civ whose trait sets `GetTraitGoldenAgeCombatModifier`
  (Persia). Other seats can never show it. Seen live S6 t214 (Persia, "Golden Age Bonus +10").
- **Forced peace lasts through the treaty's final turn.** `declare_war` is refused with "forced peace in
  effect" on the treaty's `final_turn` itself (S2b t236); war is possible from the next turn.

## Engine calls the harness refuses to make

- **Path overlay and movement cost.** `Unit:GeneratePath` throws (not implemented), `GetPathEndTurnPlot`
  needs the mouse pathfinder, and `Plot:MovementCost` crashed the process (t183) even inside `pcall`. The
  harness never invents turns-to-reach; `explore_frontier` reports hex distance over the revealed map, and
  the tile carries its yields, fresh water, routes and resource hover instead.
- **Headless deal building.** Every `Add*` on `UI.GetScratchDeal()` outside a real trade session crashed
  the game (eight crashes, 2026-09-16). All deals, peace terms, demands and vote pledges drive the real
  leader and trade screens and read the reply from them.
- **Choosing a puppet's production, buying its plots or managing its citizens.** The engine accepts these
  orders; the stock city screen never offers them. Venice's puppets expose only their purchase list
  (`purchase_only`), as the stock production popup does.
- **Running the gamecore from another seat.** Every read and write is refused unless that seat is active
  (`this seat is not active`), so nothing about another human's pending answer leaks before their turn.

## Information the harness withholds on purpose

The seat sees what a human in that seat sees, and no more: fogged tiles carry last-seen features and
improvements but no live occupants; unmet civs stay masked in demographics and league rows; a rival's tech
list is never listed behind an embassy (only techs ahead of us, as the stock screen shows); deal rows carry
coordinates only for revealed cities; no private AI state (approach, deal valuation) is ever read.

## Still to be seen live

Reads with regression coverage only, waiting for a game state: the Switch Ideology button enabled and the
switch with anarchy (needs a rival ideology exerting tourism pressure on us); a capture of our civilian by
the other human seat (S2b at war from t247); Venice buying in a puppet (needs Venice in a human seat); the
city-state greeting popup that leaves `ENDTURN_BLOCKING_UNITS` with an empty todo (GitLab #23, did not
reproduce at S2b t237 with a nonempty todo).
