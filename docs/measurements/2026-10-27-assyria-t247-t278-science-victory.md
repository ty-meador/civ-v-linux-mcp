# Assyria t247-t278 through the nine tools: the science victory (2026-10-27)

The solo Assyria game (Claude Code, seat 0, Ashurbanipal, Prince, Pangaea, Tiny, Quick) was played from the
quick save of 2026-10-26 23:32 (t247, after Ur's gift; the Codex session's turn end of t247 was not in any file
and was replayed) to the **Science Victory at t278**, by one Claude Code session on main at 2.0.0 (runtime v287)
through the nine tools alone. The ledger rows are beside this file
(`2026-10-27-assyria-t247-t278-science-victory-ledger.jsonl`, 117 rows, 2567 trips, 333 s of game time,
17:57-18:17 EDT). The stack was cold-started first (Steam, `scripts/launch_civ5.sh main`, tunerd; 48 Lua states at
17:57) and the quick save copied to `single/Ashurbanipal_0248 before-2026-10-27` before the load.

## The calls

| Call | Rows | Of note |
|---|---|---|
| `turn(action="finish")` | 41 | every turn end, most with `actions` rows and `skip_quiet_turns`; 18 of the 117 rows are refusals, all of them a single order inside a finish or batch (an illegal mission, the Booster cap, a queued item that cannot be bought), each answered with the legal list |
| `batch` | 11 | the unit gifts (8 in one call), the purchases, the spaceship parts |
| `turn(action="wait")` | 9 | after a leader screen |
| `inspect` | 42 reads in all | city/production (6), unit/actions (6), league (5), screen/culture (3), city_state (4), options (6), unit/tactical (2), map/index, spaceship, trade_catalog |
| `answer` | 9 | accept x4 (Portugal's counter, Shaka's two renewals and Marble), refuse (Shaka's RA), buttons |
| `order` | the rest inside batches | gift_gold, gift_unit, propose_deal, negotiate, vote, propose, produce, purchase, mission, trade_route, research, policy |

No name outside the nine was typed; every order came from a row a read handed back or from the action table.

## The game, turn by turn

- **t247-t248.** Colombo (ally, 1 turn from lapsing) gifted 500 gold (60 -> 100). Portugal refused Salt for Truffles
  outright ("not even close"; `negotiate` for Truffles alone: "no way"), then offered Salt for an embassy + 3 gpt at
  the turn end: accepted. Siam's open borders left to lapse (t249).
- **t249.** A Great Scientist bulbed Advanced Ballistics (3861 science); Particle Physics was not offered, and
  `order(to="empire", action="research", args={tech: TECH_PARTICLE_PHYSICS})` queued the eight missing steps
  (Archaeology, Biology, Refrigeration, Penicillin, Ecology, Telecom, Mobile Tactics, PP). Three Boosters ordered
  (Nineveh 12 turns, Nimrud 11, K-T-N 15).
- **t251 UN.** 34 delegates: 23 Yea World Ideology: Freedom (passed 23-10), 11 Nay Ban Furs (failed). A Golden Age.
  Siam read as a Culture Victory contender: dominant on Portugal, 92% on the Zulu, 22% on me at +106 tourism a
  turn. The Booster cap met: "player limit reached: 0 built + 3 in production of max 3" -- K-T-N's moved to Assur
  (6 turns). Proposed Embargo Siam.
- **t254-t256.** Shaka's Declaration of Friendship accepted. A Great Merchant walked to La Venta (two turns; the
  standing order paused on a Zulu Impi on the target plot) and ran its trade mission: +670 gold, +30 influence.
  Policy Arsenal of Democracy; eight obsolete units gifted to eight city-states in one batch (+20 influence
  each; the supply alert of 60 of 53 cleared). Monaco flipped back on a caravan's trade-route quest (+26 culture).
- **t257.** The ISS completed (Siam top contributor; my 606 took tier 2): a free Great Scientist (bulbed: Biology +
  Refrigeration at once) and the research boost. A Great Artist extended the Golden Age to 15 turns. **A Booster
  bought in Nineveh** (2260): the city had to be emptied (the Musketeer and the Worker stepped out) and switched to
  Research first, since a city holding any unit, or the item in its queue, refuses the purchase. A Great Engineer
  cannot hurry a spaceship part (`MISSION_HURRY` not legal in Nimrud with the Booster queued).
- **t258 UN.** 18 Yea Embargo Siam, 16 Nay Embargo Zulus: both failed (Portugal with Siam). Two Boosters into the ship.
- **t259-t264.** Re-proposed Embargo Siam; caravans to Monaco, Zurich, Ormus, Bratislava (Treaty Organization);
  a third Great Scientist bulbed Ecology; the third Booster built in Assur (t264). Ship 5 of 6.
- **t265 UN.** 38 delegates: Embargo Siam passed 24-12; Siam's repeal of Sciences Funding failed. Siam's tourism on me
  fell from 114 to 66 a turn (23%, falling) by t274.
- **t266-t276.** Fur for Dye with Shaka renewed; Scholars in Residence proposed and passed (t272); a Great Writer's
  treatise (+1839 culture) and a Great Musician's work; Shaka's RA (301 gold + Marble + Iron) refused, his Marble
  deal and open-borders renewal accepted, his joint war on Portugal declined (he declared alone at t277).
- **t277-t278.** Particle Physics. **The Engine bought in Assur** (2260 of 2453 gold): the Crossbowman garrison
  embarked onto the lake plot and the Worker stepped out, Assur switched to Wealth, then the purchase ran; the
  purchased unit had no moves, `MISSION_SPACESHIP` queued as HOLD, and at t278 it ran: `ship_complete: true,
  game_over: true, victory: "science"`. `turn(action="status")` carries the `game_over` gate.

## What the session met

- **A purchase needs an empty city and a free queue.** The engine refuses `purchase` while any unit stands in the
  city ("Cannot purchase while another unit is stationed in this City") and while the same item is queued there;
  the reply's `reason` says only "wonders/projects, or not buildable in this city". Worth a sharper refusal.
- **The Booster cap** ("0 built + 3 in production of max 3") counts built-not-delivered parts.
- **Automated Workers in a city keep reappearing in `todo.units`** (65540 in Assur every turn); sleeping it ended that.
- **A Great Engineer cannot hurry a spaceship part**; the refusal lists the legal missions, no reason line.
- **`notebook(action="give_order")` refuses a step whose target plot holds a foreign unit** and names it; a
  neighbouring plot worked, and the trade mission was offered from the plot beside the city-state.
