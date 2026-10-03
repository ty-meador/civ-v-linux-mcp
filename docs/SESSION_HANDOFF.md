# Resume here -- 2026-10-03: runtime v260, both seats played through t179, Venice's t180 hand-off next; the stack is up

This file holds the current state only. Earlier "Resume here" sections (51 of them, 2026-09-19 to 2026-10-01)
live in git: `git log -p -- docs/SESSION_HANDOFF.md`. Shipped work is in `CHANGELOG.md`; known gaps are
inventoried in `docs/GAPS.md`.

## Where the game is

- **t179 ended for both seats** (2026-10-03 01:20): the AI round runs, then Venice's (seat 0) t180 hand-off screen;
  hotseat Venice (seat 0) vs Mongolia (seat 1), one session plays both seats from the Claude Code server with
  `set_seat` between turns (`end_turn`, never `finish_turn`, which would wait for a seat the other seat must
  first release). Mongolia's t179 autosave is the quick-save slot (`QuickSave.Civ5Save`), overwritten by every
  `end_turn`: copy before loading anything else.
- **The stack is up** (checked 2026-10-03 00:40): Civ5XP (pid 24888), tunerd on `/run/user/1000/civ5-tuner.sock`
  (pid 26198, 48 Lua states), the session server `harness.mcp_server --seat auto` (pid 15128, started 22:31 on
  2026-10-02 -- its Python predates every commit after b99e69e, see below). Cold start if it is gone: Steam silent
  start with the desktop env vars, `scripts/launch_civ5.sh`, then tunerd once the Lua states exist, then
  `load_latest` / `load_save`.
- Venice (Industrial, pop 16, 3093 gold +147): Bank bought t179, Research process running; Printing Press (4)
  then Architecture; 8 routes, 2 slots free but no destination in range (the engine refuses a new trade unit
  until a route ends or a city comes in range); spy Giosafat in London (steal), spy 2 stole Fertilizer t174.
  DoFs: Russia, England, Portugal; research agreements Portugal (t199), England (t195); England's Gold-for-open
  borders+4gpt renewed t179 to t204, Portugal open borders (ours, free) to t200. Worker 180230 keeps dropping
  off automation (nothing left to build).
- Mongolia (Modern, Karakorum 30 / Beshbalik 12, ~2500 gold +144, happiness 8): Freedom with Avant Garde + Civil
  Society (t174), public opinion Civil Resistance (8 unhappiness, Order pressure from Portugal and Russia) --
  Hotels queued in both cities (4 / 9) for tourism, switching to Order stays an option if happiness goes
  negative; Steam Power (2) then Dynamite; spy Ssima diplomat in Beijing; China open-borders-for-1gpt renewed
  t175 to t200; Russia's research agreement landed t178; Riga friend (63 after a 250 gift t175). DoFs: China,
  Babylon, Russia.
- Both: the Second Congress of Beijing (t178) failed both proposals (Embargo England, repeal Arts Funding).
  Both notebooks (`recall`) carry the plan.

## Where the code is

- main at runtime v260, package v1.11.0 (+ unreleased), `scripts/check.sh` green (1362 tests, 63 s). Shipped this
  session (2026-10-02/03): the notebook key follows the seat (6a3f797: `game_key` cached per seat, dropped on
  load; a `set_seat` server used to read an empty notebook under the old seat's key), runtime v260 free tenets
  on the policy screen / `todo.policy` (b1d648d), `dismiss_discussion` waits for the leader queued behind a plain
  remark (9710852), bare icons spaced in `plain_text` (e1393f6), a purchase under a process reports no turns
  (3f118d3). The accept_deal renewal stamping (dd5316b) was seen live t171 on both seats and again t175
  (China's renewal to Mongolia through a fresh server). Five unreleased entries: the next release is 1.12.0.
- **The session server (pid 15128) runs Python from before dd5316b**: its `accept_deal` has no `new_deal`
  (seen t175: Portugal's renewal rows kept final_turn 175 / 0 left) and its `game_key` is still cached per
  process, so on seat 0 its `recall` / `remember` / briefing baseline go to the wrong file -- do those for
  Venice through `scripts/mcp_session.py --seat 0 ...` (fresh code; set `CIV5_TUNERD_SOCK` in the sandbox).
  Game reads and orders from it are fine. Its Lua digest is read per call, so runtime v260 is injected already.
- A server started before a runtime edit keeps its old Python; its Lua digest is read per call. Edits to
  `harness/lua/runtime/` re-inject on the next call (~70 s): make that call a `scripts/mcp_session.py ... turn_status`
  with a long timeout, never a default-timeout tool call.

## Still open

- Spectator page: no scrubber.
- The rest: `docs/GAPS.md`.
