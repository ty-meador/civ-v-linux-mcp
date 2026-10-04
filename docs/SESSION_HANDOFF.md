# Resume here -- 2026-10-03 (late): runtime v263, VENICE (seat 0) FELL TO CHINA in the t243 AI round and is eliminated, so the hotseat is Mongolia alone (seat 1) from t244; PORTUGAL AND RUSSIA DECLARED WAR ON MONGOLIA t255 (city-state allies too, all caravans lost, Russian army on the ring), peace refused t256; Mongolia played through t256 (t244-t256 in its notebook: `recall()`); the session server is on seat 1 with the call ledger live (`logs/calls.jsonl`, t242+); the stack is up

This file holds the current state only. Earlier "Resume here" sections (54 of them, 2026-09-19 to 2026-10-03)
live in git: `git log -p -- docs/SESSION_HANDOFF.md`. Shipped work is in `CHANGELOG.md`; known gaps are
inventoried in `docs/GAPS.md`.

## Where the game is

- **Mongolia alone from t244** (2026-10-03 ~21:45). Venice (seat 0, "codex") was besieged by China from t236
  (Tyre captured t242, the city 300 -> 167 hp in one round) and captured in the t243 AI round: `civ_eliminated`
  in the t244 digest, Wu Zetian holds 3 original capitals. Seat 0's notebook ends at t243. Loop per turn now:
  `finish_turn(actions=[...], skip_quiet_turns=2, timeout_seconds=100)` under seat 1 -- the AI round finishes
  inside 100 s, and every turn so far woke on a leader screen, an expiring deal or a todo; `set_seat` is not
  needed any more (`human_seats` still lists 0 and 1 but seat 0 never comes on screen).
- **Mongolia t256 -- WAR with Portugal and Russia (declared in the t255 AI round)**: Portugal brought Zurich,
  Riga, Kiev and Jerusalem, Russia brought Sofia; all 8 caravans died at once (gpt 194 -> 21), Russia's
  Aluminum-for-open-borders and both OB deals ended, Artillery 712705 died. Both refuse peace ("business to
  settle" / "not the time"): `make_peace(5)` and `make_peace(7)` every turn. Karakorum (pop 40, str 153, 300 hp,
  MILITARY BASE bought t256) finishes the APOLLO PROGRAM t257; the Great Scientist born t256 bulbed SATELLITES;
  research Computers (-> Robotics, SS Booster). Space Procurements (t239) lets gold buy parts -- but we have NO
  Aluminum now (every part needs one: ask Babylon / China / the Shoshone, gpt only, lump gold needs a DoF).
  Rivals: Russia (SS Engine t251, Hubble, Great Firewall, Pentagon), China (3 capitals, Information Era), the
  Shoshone (Apollo t254, nukes, hostile words t256), Portugal (Apollo t242, **2 civs short of a Culture
  Victory**, World Ideology Order passed t255). Gold 5396 +21, happiness 18, culture 1299/2780.
- **Units / the ring** (t256): 7 Infantry (925712 56 hp (28,22), 983050 (28,23), 671753 (27,24), 966677 (28,25),
  974851 (29,25), 991232 (29,22), 1007638 (26,23)), Machine Guns 778248 (27,23) / 786437 (29,24), Artillery 802820
  set up in the city, AA gun 950291 (29,23), Marine 1155085 (26,24), Keshik 163847 (27,25), Khan. Russians in
  sight: Mech Infantry 3178524 (27,22; shot to 4 hp t256, Infantry 1007638 sent to finish it) and 3129400 (30,20),
  Mobile SAMs (26,22) (27,21) (28,21) (30,21), Cossacks (25,23) (26,27). Each turn: city strike + both MGs + the
  Artillery on the most damaged Mech Infantry, Infantry only to finish kills, everything else stays fortified.
  The Great Merchant's trade mission in Kiev's land (603 gold, +30) came the turn Kiev declared war.
- **Diplomacy**: at war with Portugal + Russia and their city-states (above). DoF Babylon (RA ends t259, renew
  t260; Babylon lost its capital t256 and denounced Russia); China OB-from-us for 1 gpt (t276), 5 Coal for Ivory
  (t275), friendly, keeps asking us into wars (declined t242, t253); England guarded (Ivory refused t252). The
  Shoshone hostile (Order, nukes). Congress t255: Order passed as World Ideology (we voted no), Protestantism
  failed; World Leader again t261 (Shoshone 18, Portugal 18, nobody near 34).

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
