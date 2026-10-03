# Resume here -- 2026-10-03: runtime v262, both seats played through t187, Venice's t188 hand-off next; the stack is up

This file holds the current state only. Earlier "Resume here" sections (52 of them, 2026-09-19 to 2026-10-03)
live in git: `git log -p -- docs/SESSION_HANDOFF.md`. Shipped work is in `CHANGELOG.md`; known gaps are
inventoried in `docs/GAPS.md`.

## Where the game is

- **t187 ended for both seats** (2026-10-03 ~13:15): the AI round runs, then Venice's (seat 0) t188 hand-off screen;
  hotseat Venice (seat 0) vs Mongolia (seat 1), one session plays both seats from the Claude Code server with
  `set_seat` between turns. `finish_turn(timeout_seconds=30)` for the seat that hands over to the other human seat
  (it ends the turn and times out at once, since the other seat is on screen); `finish_turn(timeout_seconds=180)`
  for the seat whose end starts the AI round (it becomes a background task and reports when the next hand-off is
  up). Mongolia's t187 autosave is the quick-save slot (`QuickSave.Civ5Save`), overwritten by every end of turn:
  copy before loading anything else.
- Venice (Industrial, one city pop ~25, ~3900 gold +160, happiness 27, Golden Age t184 to ~t190): Architecture
  lands t188 (pick the next tech), Research process in the city, Zoo bought t184, Great Works: writing 4/5 (Oxford slot free), art 1/1, music
  1/1; 8 trade routes (new this session: Guangzhou, Shanghai, Beijing), the 2 extra Banking slots stay untrainable
  (no free destination -- a caravan purchase is refused the moment the last land destination is taken). DoFs:
  Russia (renewed t183), Portugal; England declined t183 (ask again ~t193). China's open-borders swap and the
  Shoshone's open-borders-for-1gpt were renewed t186 (to t211); Russia's research agreement lands t193, England's
  t195, Portugal's t199. Worker 180230 has nothing to build and wakes each turn:
  asleep at (69,39) off the city tile (it blocked end turn stacked with a returned caravan in the city; the
  city-state gift list only takes combat units).
- Mongolia (Modern, Karakorum 31 / Beshbalik 13, ~2570 gold +140, happiness 19): Freedom with Avant Garde + Civil
  Society + Universal Healthcare (t182, happiness 7 -> 15); Gems bought from Portugal t185 (9 gpt + 5 Iron to
  t210, happiness 15 -> 19); Railroad (6, the extra route); Karakorum builds the Eiffel Tower (7 turns, tourism
  against the Order pressure; Broadway after), Beshbalik a Police Station after its Hotel, a bought Broadcast
  Tower and a faith-bought Pagoda (t187); Great Works: music in Karakorum's Broadcast Tower (t182), The Night
  Watch in the Museum (t186); Russia research agreement signed t186 (lands t211). DoFs: Babylon (renewed t182), Russia; China's
  expired t181 and is not re-offered (spy Ssima: Wu Zetian plots against us). Portugal: no research agreement
  possible (no DoF). Renewed: Portugal's open-borders swap t186 (to t211), England's Ivory-for-open-borders+4gpt
  t187 (to t212), a new Russia open-borders swap t187 (to t212); England's Copper-for-Marble ends t188 (re-offer
  t189).
- Both: the Third Congress of Beijing (t181) kept China as host. Both notebooks (`recall`) carry the plan.

## Where the code is

- main at runtime v262, package v1.11.0 (+ unreleased), `scripts/check.sh` green (1374 tests, 63 s). Shipped this
  session (2026-10-03, t180-t187): `purchase_production` carries `engine_reason` on a refusal (c89bf97),
  `propose_friendship` waits for the reply screen before closing it (66543b0), runtime v261 `tactical_view` sized
  to the unit's own sight with `unit.sight` / `unit.fire_los` / `in_sight` / `in_fire_los` (4db4588, the user's
  suggestion; checked live t185: the hill Crossbowman 31 plots out to 3, the flat one 24), runtime v262
  `H.ranged_strength` (6b9f217: `Unit:GetRangedCombatStrength` does not exist in this engine's Lua, so every
  ranged unit had read as melee -- `units()` ranged 0, no `ranged_strength` anywhere, melee previews for a
  Crossbowman), and `accept_deal` names the deal it made even when another leader is queued behind it (8eb4f9c:
  `current_deals` refuses while the next offer holds the trade table, so the first of two renewals at a turn
  start had no `new_deal`; it is now inferred as this turn plus the rows' duration, which matched the engine's
  row for China's t186 renewal). Earlier this session (t173-t179): notebook key per seat, runtime v260 free tenets,
  `dismiss_discussion` queued leader, `plain_text` icon spacing, purchase under a process. Ten unreleased
  entries: the next release is 1.12.0 (cut it: version bump, tag, README release row / test count / feature
  bullets, AGENT_INSTALL line 8).
- **v262 is not yet seen live**: the game runs v261 (injected t185 by a `scripts/mcp_session.py` probe). The
  Claude Code session server (pid 74686, started 09:04) keeps `_runtime_ok` once it has checked the runtime
  and never re-injects, and its Python predates every fix above (so its `purchase_production` refusal has no
  `engine_reason`, its `tactical_view` passes radius 2, its `propose_friendship` does not wait). A fresh
  process (`scripts/mcp_session.py --seat N ...` with `CIV5_TUNERD_SOCK=/run/user/1000/civ5-tuner.sock` in the
  sandbox) injects the source on disk on its first call (~70 s): use it to see v262's `fire_los` on a
  Crossbowman, then the session server's calls keep working on the new Lua (nothing re-injects v261: the digest
  check runs once per process, `Game.ensure_runtime`).

## Still open

- Spectator page: no scrubber.
- The rest: `docs/GAPS.md`.
