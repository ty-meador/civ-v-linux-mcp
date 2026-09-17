# Resume here — 2026-09-16

## User directive

Play the game yourself and try to win. Do not automate turns to manufacture a test
state. Harden MCP while playing, including impossible actions, popups, diplomacy,
and eventual war. Respect fog of war. HTTP/WebSocket attention notifications and
spoken turn commentary are later work. Hotseat is the target mode. Restart/new
games/saves are authorized. Ask the user about screen appearance when necessary.
Commit incrementally. The user requested an immediate checkpoint/context reset;
the campaign is deliberately left mid-turn. Do not restart or advance blindly.

## Exact campaign state

- Game is running: hotseat, Codex = seat **0**, Korea/Sejong, turn **4**.
- One human-controlled seat with AI opponents; other humans were not added.
- Our attempted prelaunch Poland/Prince/Quick configuration failed because
  `GameInfoTypes` is unavailable in StagingRoom. The game launched with inherited
  settings instead. Do not describe it as Poland/Prince/Quick. Original lobby
  showed our handicap 3 and AI slots 8; difficulty/speed were not changed.
- Seoul: city ID **8192**, at **(16,27)**, coastal river capital, population 1 on
  turn 4, due to grow next turn. Nearby cotton, stone, and gold. Scout completed;
  **Worker** is now in production (12 turns reported before growth).
- Research: **Pottery**, last observed 4 turns remaining on turn 3, thus likely
  3 remaining now. Plan: science-oriented Korea, with worker/luxury techs as needed.
- Scout ID **24576**, at **(15,26)**, zero moves. Ordered toward (14,25), but only
  moved partway; it may retain that destination. Inspect before issuing more orders.
- Warrior ID **16385**, at **(20,31)**, still has **2 moves** on turn 4. Its last
  action was taking ruins on turn 3. Reward was a map, not a free technology.
- A barbarian warrior guards a camp at **(20,29)**. Do not attack it casually with
  our lone warrior. Southern visible terrain includes marble at (19,33), deer at
  (22,32), tundra/coast, and cotton eastward. Scout is exploring northwest.
- Final turn status: active_player=0, my_turn=true, paused=false,
  pending_popups=[], ENDTURN_BLOCKING_UNITS. **Turn has not ended.**
- MCP `quick_save` returned `{ok:true, turn:4}` immediately before this handoff.
  Newest file verified: `/home/ty/.local/share/Aspyr/Sid Meier's Civilization 5/Saves/single/quick/QuickSave.Civ5Save`
  (571507 bytes). Despite hotseat mode, UI.QuickSave wrote under `single/quick`.
  Reloading this particular hotseat quicksave has NOT been tested. Preserve the
  running game if possible; an initial hotseat autosave also exists.

## How this session controls the game

No Civ V or context-mode MCP tools are exposed directly in this Codex session.
Use the actual stdio MCP client added at `scripts/mcp_call.py`, from repo root:

```sh
.venv/bin/python scripts/mcp_call.py --seat 0 turn_status '{}'
.venv/bin/python scripts/mcp_call.py --seat 0 units '{}'
.venv/bin/python scripts/mcp_call.py --seat 0 map_window '{"x":20,"y":31,"radius":3}'
.venv/bin/python scripts/mcp_call.py --list
```

Each invocation opens a real MCP session and calls one tool. It has no strategy
or turn automation. Seat defaults to 0; the MCP server itself defaults to seat 1
in hotseat, so explicitly configure CIV5_SEAT=0 for other clients.
Use escalation for local game/socket access: sandbox blocks it. Approved command
prefixes include the client above, `python3 -m harness.cli`,
`python3 -m harness.tunerd`, and `python3 -m unittest`.
CLI `lua` remains a developer/debug path; never use it to inspect hidden players.

Live processes at checkpoint:

- Game launch session 78068, launched with `CIV5_WAIT=1 scripts/launch_civ5.sh codex`.
  Last seen Civ5XP PID 366109, reaper PID 366026. Logs `logs/codex.{out,err}`.
- Tunerd session 77230, default `/run/user/1000/civ5-tuner.sock`, port 4318.
- A detached launcher invocation exited immediately; attached CIV5_WAIT mode
  worked. Do not launch a duplicate while the current game remains alive.
- If tool sessions disappear across context reset, inspect CLI status first.
- `.venv` uses Python 3.14 and MCP v2 (`CallToolResult.is_error`); system python3
  is 3.12. The script supports both spellings for MCP v1/v2.

## Changes and verification this session

- Bridge client request/reply pairs are protected by a thread lock. Complete MCP
  operations also share a per-socket process/thread lock, including selection,
  action and verification. Contention returns a retryable timeout after 10 sec.
- MCP enforces assigned active seat. Wrong-seat `end_turn` was rejected live.
  Wait polling no longer dismisses another seat's popups. End-turn checks seat,
  pause, engine blockers and tracked unresolved popups.
- Map reads use assigned seat's team; fogged tiles omit current features, owners,
  improvements, routes, city internals and units. Invisible units are filtered.
  Diplomacy omits unmet civ identities and hidden true AI approach/city counts.
- Event recording captures a seat audience and filters private world events at
  capture time. Event cursors are per-seat. Old events without audience are not
  exposed. This is conservative and drops some potentially public events.
- Removed unrestricted Lua from the MCP tool registry (debug CLI still exists).
  Exposed missing `choose_promotion` MCP tool.
- Non-trade units are rejected before the native trade-destination API. A turn-0
  warrior route returned a clean refusal after the fix; game remained responsive.
  Unavailable caravan production was rejected live before Pottery, then a Worker
  queued correctly. Invalid unit ID was rejected without affecting selected unit.
- Generic unit missions validate selection and the real unit-panel
  `Game.CanHandleAction` entry. This intentionally rejects unsupported mission
  shapes; coverage must be expanded with verified dedicated paths.
- Runtime injection uses a source hash. A live test initially hit stale Lua
  despite edited source; this fix prevents forgotten version bumps masking edits.
- Replaced `dismiss_pending_popups` child-control hiding with real per-popup
  callbacks, including **TechAwardPopup**, separate from **TechPopup** research
  choice. Added popup shown/processed tracking to turn_status. Decisions remain
  pending rather than being silently dismissed. Unknown modals block progression.
- **Live verified:** GoodyHutPopup/map reward was recorded, closed through its real
  callback, pending list cleared, and turn 4 began. User explicitly confirmed the
  normal map with no lingering full-screen popup.
- **Not yet live verified:** first technology completion and its stacked screens.
  Prior notes' claims about unreliable IsHidden may confuse child-local hidden
  flags with parent visibility. We stopped directly hiding children. Earlier
  calls in this game did run the old sweep, so watch for residual hidden child
  controls when a previously touched popup next opens; reload may reset UI if needed.
- Final checks: `python3 -m unittest discover -s tests -q`: **9 tests passed**;
  `git diff --check`: clean. Tests include real Lua helper execution using
  liblua5.4, fog privacy, unmet identities, invalid trade unit, seat event cursors,
  popup lifecycle, concurrent request pairing, operation contention and liveness.
  Actual game uses Lua 5.1, so live verification remains necessary.

## Immediate next work and open risks

1. Inspect current state; choose warrior's remaining move. Continue actual play
   toward Pottery completion (~turn 7), verify both discovery and research-choice
   screens visually with user if needed. Do not blindly dismiss decisions.
2. Add read-only catalogs of legal research/builds/unit actions so gameplay needs
   fewer developer queries. Test newly guarded missions live: founding happened
   before the generic unit-panel guard was added, so that guard needs coverage.
3. Test more than one human hotseat seat. Current live campaign only tests one;
   alternate-seat ownership and event privacy have synthetic/wrong-seat coverage,
   not a full two-human turn transition.
4. Trade proposal reading/acceptance is still missing. Existing propose_deal is
   known to crash; do not re-expose it. Real AI decisions must be read and handled,
   not automatically declined. Discussion dialogs aren't yet fully represented by
   generic popup event tracking. Full attention/push service remains unfinished.
5. Unit mission arguments, religion, espionage, congress and diplomacy escape
   hatches still need broader legality and privacy audits. No claim of full action
   coverage, complete fog audit, or crash-proof queueing is warranted yet.
6. `turn_status` exposes tracked popups but not every possible fullscreen UI.
   Modal resolution allowlist may need additional actual enum names; unknowns fail
   closed. Popup tracking starts at injection, so already-open dialogs need checks.
7. Timeout/reconnect recovery in tunerd, whole-operation serialization for direct
   Game/HTTP callers, event cursor sharing between multiple clients of one seat,
   and delayed action postconditions all remain to be hardened.
8. The CPU affinity mitigation from prior sessions remains in the launcher.
   No crash observed this session; multi-hour stability is not established.

## Repository checkpoint provenance

The repository was already dirty on arrival: `.mcp.json` deletion; modifications
to NOTES, cli, game, http_server, runtime.lua, mcp_server, tuner, launch script;
and new watch_game.py. Preserve that prior-session work. Commit c7b0367 contains
this session's client lock and stdio client. The stopping-point checkpoint also
records the inherited working files alongside the new core fixes, so a fresh
checkout has the same playable baseline. The HTTP wrapper was not developed in
this session. See docs/NOTES.md for the much longer prior-session history.
