# Resume here -- 2026-10-03: runtime v260, the game sits at t175, Mongolia's turn; the stack is up

This file holds the current state only. Earlier "Resume here" sections (51 of them, 2026-09-19 to 2026-10-01)
live in git: `git log -p -- docs/SESSION_HANDOFF.md`. Shipped work is in `CHANGELOG.md`; known gaps are
inventoried in `docs/GAPS.md`.

## Where the game is

- **t175, Mongolia's turn** (seat 1), hotseat Venice (seat 0) vs Mongolia (seat 1); one session plays both
  seats from the Claude Code server with `set_seat` between turns. Venice's t175 autosave is the quick-save
  slot (`QuickSave.Civ5Save`), overwritten by every `end_turn`/`finish_turn`: copy before loading anything else.
- **The stack is up** (checked 2026-10-03 00:40): Civ5XP (pid 24888), tunerd on `/run/user/1000/civ5-tuner.sock`
  (pid 26198, 48 Lua states), the session server `harness.mcp_server --seat auto` (pid 15128, started 22:31 on
  2026-10-02 -- its Python predates every commit after b99e69e, see below). Cold start if it is gone: Steam silent
  start with the desktop env vars, `scripts/launch_civ5.sh`, then tunerd once the Lua states exist, then
  `load_latest` / `load_save`.
- Venice (Industrial, pop 16, 2943 gold +153): Banking t179 (Bank + 2 route slots -> buy caravans), Shrine then
  a process; 8 routes; spy 1 Giosafat to London (steal), spy 2 stole Fertilizer from China t174. DoFs: Russia,
  England, Portugal; research agreements Portugal (t199), England (t195). Portugal open-borders renewal (ours,
  free) accepted t175 to t200.
- Mongolia (Modern, Karakorum 29 / Beshbalik 11, 2230 gold +138, happiness 9 after Freedom): Freedom with Avant
  Garde + Civil Society (t174); Broadcast Tower (6), Constabulary (5); Refrigeration 5; spy Ssima diplomat in
  Beijing; China open-borders-for-1gpt ends t175, re-offer t176. DoFs: China, Babylon, Russia.
- Both: the Second Congress of Beijing convenes t178 (ENACT Embargo England, REPEAL Arts Funding) -- decide votes.
  Both notebooks (`recall`) carry the plan.

## Where the code is

- main at runtime v260, package v1.11.0 (+ unreleased), `scripts/check.sh` green (1355 tests, 63 s). Shipped this
  session (2026-10-02/03): the notebook key follows the seat (6a3f797: `game_key` cached per seat, dropped on
  load; a `set_seat` server used to read an empty notebook under the old seat's key), runtime v260 free tenets
  on the policy screen / `todo.policy` (b1d648d), `dismiss_discussion` waits for the leader queued behind a plain
  remark (9710852). The accept_deal renewal stamping (dd5316b) was seen live t171 on both seats.
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
