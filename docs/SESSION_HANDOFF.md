# Resume here — 2026-09-16 (evening checkpoint)

## User directive

Play the game yourself and try to win. Do not automate turns to manufacture a
test state. Harden MCP while playing, including impossible actions, popups,
diplomacy, and eventual war. Respect fog of war. HTTP/WebSocket attention
pings and spoken turn commentary are later work. Hotseat is the target mode.
Restart/new games/saves are authorized. Ask the user about screen appearance
when necessary. Commit incrementally; do not push.

Workflow: 2–3 features per session, or stop when context is getting large.
Reach a stopping point, commit, rewrite this handoff, then wait for a context
reset. Do not mention assistant product names in commit messages.

## Exact campaign state

- Game is running: hotseat, player nick **Codex** = seat **0**, Korea/Sejong,
  **turn 5, mid-turn, orders already issued, turn has NOT been ended.**
- One human seat; AI opponents. Inherited lobby settings (not Poland/Prince/Quick).
  Original lobby: our handicap 3, AI slots 8.
- Seoul: city ID **8192**, **(16,27)**, coastal river capital, **pop 2** (grew
  this turn). Worker in production, **9 turns**. Nearby: cotton, stone, gold, cows.
  Settler is now legal (11 turns) but keep the Worker.
- Research: **Pottery, 1 turn left.** Completes on the next turn. Do not switch.
  After Pottery, intended pick is **Writing** (libraries / Korea science). Calendar
  can wait — the Worker is not out yet. **Do not blindly dismiss the tech
  discovery or the research-choice screens; verify them with the user.**
- Scout ID **24576**, at **(13,25)** hills, **0 moves**. Explored west of Seoul.
- Warrior ID **16385**, at **(18,33)** grass, **0 moves**. Path this
  session: (20,31) → forest (20,32) → marble-adjacent (18,33). Marble luxury is
  at **(19,33)** tundra.
- **Egypt / Ramesses II met** (player id **1**, score 34, not at war). Their
  warrior was visible at **(12,26)** from the scout. Digest event:
  `DIPLO_UI_STATE_DEFAULT_ROOT` greeting text from Ramesses.
- **Zanzibar met** (city-state, owner **26**) at **(16,34)** hills tundra:
  porcelain, sheep, fish, road, pop 1. Gold jumped 23 → **53** (typical 30-gold
  first-meet gift; mercantile). Notification: "You have met Zanzibar".
- Barb camp last seen at **(20,29)** with a barb warrior. After the warrior
  moved north that tile is revealed-but-fogged: FOW correctly omitted the camp
  and unit. Do not assume it is gone.
- turn_status at checkpoint: active_player=0, my_turn=true, paused=false,
  pending_popups=[], blocking_name=NO_ENDTURN_BLOCKING_TYPE.
- User reported the **game is in 2D map mode** and they did **not** switch it.
  Likely `UI.LookAt` inside `select_unit` (used by `available_unit_actions` and
  `unit_mission`) or first-contact. Ask before forcing a camera/view change.
- `quick_save` returned `{ok:true, turn:5}` at this checkpoint.
  File: `/home/ty/.local/share/Aspyr/Sid Meier's Civilization 5/Saves/single/quick/QuickSave.Civ5Save`
  (573048 bytes). Hotseat quicksaves still land under `single/quick`. Reloading
  that hotseat quicksave is still untested. Preserve the running game.

## How to control the game

No Civ V tools are injected into this session. Use the stdio client:

```sh
.venv/bin/python scripts/mcp_call.py --seat 0 turn_status '{}'
.venv/bin/python scripts/mcp_call.py --seat 0 available_research '{}'
.venv/bin/python scripts/mcp_call.py --seat 0 available_production '{"city_id":8192}'
.venv/bin/python scripts/mcp_call.py --seat 0 available_unit_actions '{"unit_id":16385}'
.venv/bin/python scripts/mcp_call.py --list
```

Seat **must** be `--seat 0` (MCP server defaults to seat 1 in hotseat).
Unix socket: `$XDG_RUNTIME_DIR/civ5-tuner.sock`. Sandbox cannot reach it.

Live processes at checkpoint:

- Civ5XP PID **366109**, reaper **366026**, launch `CIV5_WAIT=1 scripts/launch_civ5.sh codex`.
  Logs `logs/codex.{out,err}`. **Do not launch a duplicate.**
- tunerd PID **372967** (restarted this session — previous daemon 323452 was
  listening but every connect returned ECONNREFUSED). Log:
  `logs/tunerd_session5.log`. Shim is loaded; restarting tunerd is safe.
- `.venv` is Python 3.14 / MCP v2. System python3 is 3.12 (unit tests use it
  for liblua5.4).

## Changes this session (committed)

Three MCP features, all live-verified on this campaign:

1. **Read-only catalogs** (runtime.lua v21):
   - `available_research` — techs where `CanResearch` is true.
     Live: Pottery (current, 3 then 1 turn), Animal Husbandry, Archery, Mining.
   - `available_production(city_id)` — CanTrain/CanConstruct/CanCreate/CanMaintain.
     Live turn 4 Seoul: Worker/Scout/Warrior/Monument. No Settler (pop 1), no
     Caravan (pre-Pottery). After growth: Settler appeared (11 turns).
   - `available_unit_actions(unit_id)` — selects the unit first, then
     `Game.CanHandleAction` only if that unit is head-selected. Filters out
     `CONTROL_*`, `COMMAND_HOTKEY`, and `INTERFACEMODE_*`.
     Live warrior: SKIP/ALERT/FORTIFY/AUTOMATE_EXPLORE/MOVE_TO/ROUTE_TO/
     SWAP_UNITS/COMMAND_DELETE. No FOUND, no BUILD_FARM.

2. **`set_research` now checks `CanResearch`** before `SendResearch`. Live:
   `TECH_EDUCATION` → `cannot research this yet (missing prerequisites or disabled)`
   instead of the misleading free-tech-mismatch postcondition.

3. **Illegal-action queue still refuses cleanly** (game stayed responsive):
   trade route on warrior; FOUND/BUILD_FARM on warrior; UNIT_CARAVAN;
   UNIT_SETTLER (pop 1); bad city/unit ids.

HTTP GET routes were mirrored 1:1. Tests added in `tests/test_mcp_safety.py`.
`python3 -m unittest tests.test_mcp_safety tests.test_liveness` was green.

## Immediate next work

1. Inspect state; if still turn 5 with 0 moves, `end_turn` then
   `wait_for_my_turn`. Next turn is **Pottery completion** — handle both the
   discovery splash and the choose-tech screen with the user. Prefer Writing.
2. **Popup gap (do this next):** `turn_status.pending_popups` only tracks
   `SerialEventGameMessagePopup` from injection time. LeaderHeadRoot /
   CityStateGreetingPopup / GreatPersonRewardPopup are **not** in that list.
   They can sit on screen while `pending_popups=[]` and `end_turn` silently
   no-ops. `dismiss_pending_popups()` already knows them, and `end_turn`
   already calls it, but `turn_status` does not report
   `leader_greeting_pending` / `city_state_greeting_pending` /
   `discussion_pending` / `tech_popup_pending`. Surface those flags.
   Mid-turn first contact this session may still have a greeting up; ask the
   user what they see (they reported 2D map, not a leader screen).
3. Egypt is adjacent. Do not declare war. Scout next: peek without eating
   their warrior. Warrior: keep north of the fogged barb camp; marble/Zanzibar
   coast is the scout-military job.
4. `UI.LookAt` on every select may be what flipped 2D mode — confirm, then
   stop doing that for catalog reads.
5. Trade proposal **read/accept** is still missing. Do not re-expose
   `propose_deal` (known crash). HTTP/WebSocket attention pings still later.

## Open risks (unchanged)

- One human hotseat seat only; two-human handoff untested live.
- No claim of full action coverage or crash-proof queueing.
- Modal allowlist fails closed for unknown popup enum names.
- tunerd timeout/reconnect, multi-client event cursors, delayed
  postconditions still to harden.
- CPU affinity mitigation still in the launcher. This session: one wedged
  tunerd (not a game crash). Multi-hour stability not established.
