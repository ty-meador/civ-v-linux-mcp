# Resume here -- 2026-10-02: runtime v259, the game sits at t164, Venice's turn; the stack is down

This file holds the current state only. Earlier "Resume here" sections (51 of them, 2026-09-19 to 2026-10-01)
live in git: `git log -p -- docs/SESSION_HANDOFF.md`. Shipped work is in `CHANGELOG.md`; known gaps are
inventoried in `docs/GAPS.md`.

## Where the game is

- **t164, Venice's turn**, hotseat Venice (seat 0) vs Mongolia (seat 1), hand-off screen up when the save is
  loaded (`wait_for_my_turn` on seat 0 dismisses it). Mongolia's t163 autosave is copied to
  `Saves/hotseat/Venice-Mongolia_0163 fertilizer`; the quick-save slot is the autosave and gets overwritten by
  `finish_turn`, so copy before loading anything else.
- **The stack is not running** (checked 2026-10-02 22:30): no Civ5 process, no tunerd, the old session server
  (pid 63232) is gone. Only a fresh `harness.mcp_server --seat auto` is up (pid 15128). Cold start: Steam
  silent start with the desktop env vars, `scripts/launch_civ5.sh`, then tunerd once the Lua states exist,
  then `load_latest` / `load_save`. Until tunerd is back every civ5 tool says "No such file or directory".
- Venice: Chivalry (3), Seaport (4) then Opera House; golden age to ~t167; 7 routes, 1 slot with no
  destination; Worker 180230 automated out of the city. Mongolia: Fertilizer (3), Karakorum Hospital (4),
  6 routes all used, Free Thought adopted, Riga friend 51 after a 250 gift. Both notebooks (`recall`) carry
  the plan; AI renewal offers arrive at turn start most rounds (China, Shoshone, Portugal, Russia).

## Where the code is

- main at runtime v259, package v1.11.0, `scripts/check.sh` green (1347 tests, 62 s). Last shipped:
  `accept_deal.new_deal` / `final_turn_offered` on a renewal (unit-tested, not yet seen live);
  v257 strips `[LINK=...]` from build names (c24c157); v258 marks an expiring deal already renewed
  (`renewed` / `renewed_until`, 932720f); v259 names a deal item's giver from the deal's other player,
  `from_engine` when the raw id differs (d025eb8); the spectator seat view hides undetected submarines (f08f8fe).
- A server started before a runtime edit keeps its old Python; its Lua digest is read per call. Edits to
  `harness/lua/runtime/` re-inject on the next call (~70 s, use a long first timeout).

## Still open

- Spectator page: no scrubber.
- The rest: `docs/GAPS.md`.
