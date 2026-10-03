# Resume here -- 2026-10-03: runtime v262, both seats played through t228; VENICE IS AT WAR with England and the Shoshone (declared t228) and Mongolia at peace with everyone (England's peace t226); Venice's t229 hand-off is on screen; the stack is up

This file holds the current state only. Earlier "Resume here" sections (53 of them, 2026-09-19 to 2026-10-03)
live in git: `git log -p -- docs/SESSION_HANDOFF.md`. Shipped work is in `CHANGELOG.md`; known gaps are
inventoried in `docs/GAPS.md`.

## Where the game is

- **Both seats through t228** (2026-10-03 ~16:15). Loop per turn: Venice (seat 0) is on screen first --
  `set_seat(0)`, `wait_for_my_turn(60)` (presses Continue, surfaces any leader screen), clear the gate, play,
  `finish_turn(timeout_seconds=30)` (ends and times out at once since Mongolia's hand-off is next); then
  `set_seat(1)`, `wait_for_my_turn(60)`, play Mongolia, `finish_turn(timeout_seconds=100)` -- under 120 s it
  stays in the foreground and the AI round (1-2 min now) usually finishes inside it; if it times out, `set_seat(0)`
  + `wait_for_my_turn(300)` waits the rest out under the right seat. (A longer timeout becomes a background task
  that must be TaskStop'd before `set_seat(0)`.) The live session server (started 14:35) runs pre-feaeb32 code:
  no digest trimming, no arrive_if_due, no queued_next wait (6359073) -- `/mcp` reconnect to pick them up.
- **Venice t228 -- WAR**: England declared t228 (its allies Sydney, Vilnius) and the Shoshone t228 (Vatican City,
  Almaty); Tyre (our ally, 152) joined us. Shoshone land is 4 plots west of Venice at (65,35); no enemy in sight
  yet. City str 73 / 300 hp (Castle t224, Arsenal + Armory t225). Garrison Rifleman 901141 (Shock I, Cover I),
  Gatlings 843777 (69,39 forest hill), 851988 (69,38), 860164 (69,40), Rifleman 876554 (68,38), Submarine 892930
  (Wolfpack II) in port. Per turn: step the garrison out, buy one Rifleman / Gatling (410) in the city, fortify
  (purchase needs an empty city tile); from t230 `make_peace(2)` and `make_peace(6)` each turn (both refused the
  turn of the declaration by rule). Gold 4611 +233, happiness 31, Radio (7, then Broadcast Tower / Broadway).
  Freedom adopted t222 (no free tenet; next policy 1070: Avant Garde / Civil Society / Treaty Organization).
  Deals: Russia RA (lands t250) + OB-from-us (t247) + DoF; Portugal RA (t251) + OB swap (t253) + DoF; Babylon DoF
  (t223) -- **Babylon's t228 RA offer was lost** (the blank-table bug, fixed in 6359073): `propose_deal(4,
  RESEARCH_AGREEMENT both ways)` on t229. China HOSTILE (denounced t223, covets our land, Autocracy) -- a second
  front is possible; its OB with us runs to t236. Spies: Niccolo stealing in Beijing, Marino diplomat in Lisbon,
  Cesare counterspy in Venice. 11 routes + Riga (t226); one free slot (a Cargo Ship, 270, when the seas are safer).
  Sciences Funding passed t227 (artists -33%); World Ideology Order repealed t227; World Leader vote t233 (Venice
  6 delegates, Portugal 16).
- **Mongolia t228 -- peace**: England's DP war (t224-t226, Babylon's Defensive Pact) ended with England's own peace
  offer t226 (Sydney, Vilnius included; treaty to t236). The boxed-in Scout 24576 died t224 to Sydney's bombardment.
  Karakorum (37 pop, happiness 26 after the Order repeal) builds Research Lab (4); Penicillin (5, 8th route),
  then Radar. Ring: Infantry 991232 (29,22) Drill I+II, 925712 (28,22), 671753 (27,24), 966677 (28,25), 974851
  (29,25), 983050 (28,23) (the three Legions upgraded t224), Machine Guns (27,23) (29,24), AA gun 950291 (29,23),
  Artillery 802820 in the city + 712705 (27,22), Keshik 163847, Khan 770062. Their Finest Hour adopted t226 (next
  policy 2250). 7 caravans running (174 gpt); Babylon OB bought t224 (3 gpt to t249); Great Musician 917506 on
  order 20 (paused -- `move_unit` it each turn) walking to (46,20) for a concert tour in Babylon's land, 1-3 plots
  a turn via the south (Akkad is 24 plots: reconsider if it keeps heading away). China's OB-for-1gpt renewed to
  t250; Ivory sold to China for 5 Iron (t249); embassies swapped with Russia t225. **Russia plots against us**
  (spy t225; denounced us t213; refused their free OB ask t227) -- keep the ring fortified, 1600+ gold in hand.
  Sofia (49) and Tyre (45) friends; Yerevan lapsed t224 (left to lapse). Public news only in this notebook: China
  denounced Venice, England and the Shoshone declared war on Venice t228.
- Earlier (t192-t206, the war): the section below is kept for the record.

- **WAR (t192 AI round): Russia (Catherine, 7) declared war on Mongolia** despite the DoF; Portugal (5) and its
  city-state allies Zurich, Riga, Kiev, Jerusalem joined. All seven Mongolian caravans died at once, Russia's
  research agreement / open borders and Portugal's Gems deal ended (gpt 125 -> 22-30, happiness 13 -> 9). Both
  leaders refuse peace every turn so far (`make_peace` t193-t195: "business to settle" / "no peace, perhaps
  another day") -- keep retrying each Mongolian turn. Defence so far: Walls bought in both cities (250 hp,
  Karakorum 82 str, Beshbalik 77), a Great War Infantry bought for Karakorum (663560, Drill I+II) and Sofia's
  gifted one (655366, Drill I) fortified inside Beshbalik, the Keshiks shoot from around Karakorum and sleep
  beside it (a Keshik does ~12 to a Cossack, 24-29 to a Lancer; the city strike first, then the Keshiks finish).
  Kills: Lancer t193, Cossack t194, two Lancers + a Cossack t195. Still in sight t195: Infantry (27,22) by
  Karakorum, Artillery (31,22), a Galleass (31,25) that bombards the coast, three Infantry + a Gatling Gun around
  Beshbalik. Plastic landed t196 and both GWIs became Infantry. t196-t198: lost Keshiks 188426 and 237573 and a worker
  (Keshiks do 1-2 damage to full-health Infantry: use them only on Lancers / Cossacks / siege), killed another
  Infantry and a Gatling Gun; a Great Scientist bulbed Ballistics (lands t200, Machine Guns), a Great Musician's
  work went into Beshbalik's Broadcast Tower. **Beshbalik fell in the t198 AI round** (it was at 64/250 after
  Artillery + two Gatling Guns; the Infantry bought into it that turn died with it): Mongolia is Karakorum alone,
  happiness 19, science 283, ~1000 gold +25. Infantry 679944 (76 hp, Drill I) stands fortified on the hill (23,22)
  beside Russian-held Beshbalik (75 hp, an 18-hp Infantry inside); Karakorum has Infantry 671753 (Drill I+II) and
  finishes an Artillery t200; three Keshiks (180226, 196619 74 hp, 163847) sleep beside it. Russian Infantry
  (29,24) at 48 hp after t199's strikes, another at (30,26). Deals lost t199: England's Copper/Horses+4gpt,
  Babylon's Silver (re-offer both), Babylon's DoF expired (re-ask). Sofia gifted 250 t192 and t199 (influence 49). Venice is neutral: it declined
  Russia's war ask t191 and accepted Portugal's DoF t193 (its own seat's interest; it sees nothing of the war
  beyond the game's own notices).
- Venice (Industrial, one city pop ~25, ~3900 gold +160, happiness 27, Golden Age t184 to ~t190): Economics (3,
  then Archaeology), Entrepreneurship adopted t188 (Commerce 4/5), Golden Age over, Research process in the city, Zoo bought t184, Great Works: writing 4/5 (Oxford slot free), art 1/1, music
  1/1; 8 trade routes (new this session: Guangzhou, Shanghai, Beijing), the 2 extra Banking slots stay untrainable
  (no free destination -- a caravan purchase is refused the moment the last land destination is taken). DoFs:
  Russia (renewed t183), Portugal; England declined t183 (ask again ~t193). China's open-borders swap and the
  Shoshone's open-borders-for-1gpt were renewed t186 (to t211); Russia's research agreement lands t193, England's
  t195, Portugal's t199. Worker 180230 has nothing to build and wakes each turn:
  asleep at (69,39) off the city tile, worker 65541 asleep at (69,38) (a sleep given at 0 moves is only a hold and
  the unit wakes next turn; the city-state gift list only takes combat units). Russia asked Venice to join a war
  on Mongolia t191: declined. t192-t195: Russia's 5 Aluminum + 13 gold for 1 Gold (to t217), Russia's research
  agreement renewed t194 (lands t219), Portugal DoF t193, Babylon's Gold-for-open-borders+4gpt renewed t195 (to
  t220), Russia's 930-gold ask refused t195; England's research agreement landed t195 (re-offer it and a DoF
  t196), Russia's open borders ends t196 (re-offer t197). Archaeology (3). Portugal says England plots against
  Venice.
- Mongolia (Modern, Karakorum 31 / Beshbalik 13, ~2700 gold +135, happiness 19): Freedom with Avant Garde + Civil
  Society + Universal Healthcare (t182, happiness 7 -> 15); Gems bought from Portugal t185 (9 gpt + 5 Iron to
  t210, happiness 15 -> 19); Plastic (8, Research Lab); Scientific Revolution adopted t191 (Rationalism finished, a free tech lands);
  Eiffel Tower built (hurried by a Great Engineer t190); Karakorum trains a Caravan for Railroad's extra slot,
  then a Stadium; Beshbalik a Police Station after its Hotel, a bought Broadcast Tower and a faith-bought Pagoda
  (t187); Great Works: music in the Broadcast Tower (t182), The Night Watch in the Museum (t186), The Red Badge
  of Courage in Oxford (t189); Russia research agreement signed t186 (lands t211), China's landed t190, Babylon's
  t191 (re-offer t192). England's Copper-for-Horses+4gpt t189 (to t214); England refuses to sell Marble short
  of Iron + Horses + open borders (t191), happiness 19 without it. Sofia's friendship lapses ~t194 (34 influence). DoFs: Babylon (renewed t182), Russia; China's
  expired t181 and is not re-offered (spy Ssima: Wu Zetian plots against us). Portugal: no research agreement
  possible (no DoF). Renewed: Portugal's open-borders swap t186 (to t211), England's Ivory-for-open-borders+4gpt
  t187 (to t212), a new Russia open-borders swap t187 (to t212); England's Copper-for-Marble ended t188 (re-offer t189 if England asks;
  Marble's happiness is gone otherwise); China's research agreement lands t190, Babylon's t191.
- Both: the Third Congress of Beijing (t181) kept China as host. Both notebooks (`recall`) carry the plan.

## Where the code is

- main at runtime v262, package v1.11.0 (+ unreleased), `scripts/check.sh` green (1382 tests, 64 s). Shipped
  this afternoon (t192-t199): `finish_turn` takes the digest at a hotseat hand-off timeout and `turn_digest`
  keeps the newest 120 events with `omitted` (5d77246: a two-seat session's finish_turn always timed out at the
  other seat's hand-off and skipped the digest, so seat 1's cursor never moved -- the first digest that did
  complete, when Russia's declaration stopped the wait, was 350 events / 75 KB, past the client's limit), and
  `unit_mission` says why a ranged attack was refused (8ffdf47: range, line of fire, no moves, already attacked,
  siege not set up, no enemy -- a Keshik rode three plots for a bare "not legal"), and `propose_deal` places a
  research agreement / defensive pact / trade agreement once (a3f38f4: the pocket handler puts the pair on the
  table per press, so Venice's England agreement held two pairs and cost 468 gold). **The session server still
  runs the pre-5d77246 Python** (its hand-off timeouts carry no digest and its ranged refusals no `reason`):
  `/mcp` reconnect picks both up. Shipped earlier this session (t180-t191): `purchase_production` carries `engine_reason` on a refusal (c89bf97),
  `propose_friendship` waits for the reply screen before closing it (66543b0), runtime v261 `tactical_view` sized
  to the unit's own sight with `unit.sight` / `unit.fire_los` / `in_sight` / `in_fire_los` (4db4588, the user's
  suggestion; checked live t185: the hill Crossbowman 31 plots out to 3, the flat one 24), runtime v262
  `H.ranged_strength` (6b9f217: `Unit:GetRangedCombatStrength` does not exist in this engine's Lua, so every
  ranged unit had read as melee -- `units()` ranged 0, no `ranged_strength` anywhere, melee previews for a
  Crossbowman), and `accept_deal` names the deal it made even when another leader is queued behind it (8eb4f9c:
  `current_deals` refuses while the next offer holds the trade table, so the first of two renewals at a turn
  start had no `new_deal`; it is now inferred as this turn plus the rows' duration, which matched the engine's
  row for China's t186 renewal), and `unit_mission` says when a sleep/fortify given at 0 moves is only a hold
  (feced9b). Earlier this session (t173-t179): notebook key per seat, runtime v260 free tenets,
  `dismiss_discussion` queued leader, `plain_text` icon spacing, purchase under a process. Fourteen unreleased
  entries: the next release is 1.12.0 (cut it: version bump, tag, README release row / test count / feature
  bullets, AGENT_INSTALL line 8).
- **v262 is live and the session server is current.** `/mcp` reconnected the civ5 server at t188 (fresh Python,
  every fix above included); its first call injected v262 and `tactical_view` on the hill Crossbowman answered
  `ranged_strength 18`, `fire_los` 31 plots out to 3, `radius_from: sight`. `Game.ensure_runtime` checks the
  runtime once per process: after any later Lua edit the first call of a FRESH process injects it (~70 s, give
  it 120 s+) while a running server keeps the old Lua.

## Still open

- Spectator page: no scrubber.
- The rest: `docs/GAPS.md`.
