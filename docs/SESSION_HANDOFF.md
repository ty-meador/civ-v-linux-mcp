# Resume here — 2026-09-16 (turn 6, units unmoved)

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

**Camera rule (user, this session):** do not flip 2D/3D. `UI.SelectUnit` and
`UI.LookAt` both change `GetGameViewRenderType` / strategic view. Catalog
reads are now selection-free. **Do not call `select_unit` / `move_unit` /
`unit_mission` until those are rewritten onto `unit:PushMission` (untested).**
Do not call `ToggleStrategicView` or `SetGameViewRenderType`. Ask before any
camera or view change.

## Exact campaign state

- Game is running: hotseat, player nick **Codex** = seat **0**, Korea/Sejong,
  **turn 6, our turn, units still have 2 moves, orders NOT issued.**
- One human seat; AI opponents. Inherited lobby settings (not Poland/Prince/Quick).
- Seoul: city ID **8192**, **(16,27)**, coastal river capital, **pop 2**.
  Worker in production, **8 turns**. Nearby: cotton, stone, gold, cows.
  Settler is legal but keep the Worker.
- Research: **Calendar, 8 turns left.** This was auto-queued when Pottery
  completed; the intended pick is still **Writing**. Confirm with the user
  before `set_research('TECH_WRITING')`. Do not blindly dismiss tech screens.
- Scout ID **24576**, at **(13,25)**, **2 moves**. Egypt warrior is visible at
  **(13,27)** (owner 1). Peek without walking onto them. Do not declare war.
- Warrior ID **16385**, at **(18,33)** grass, **2 moves**. Marble at **(19,33)**.
  Sheep **(16,33)**, fish **(17,34)** (Zanzibar coast). Keep north of the
  fogged barb camp.
- **Egypt / Ramesses II met** (player id **1**, not at war).
- **Zanzibar met** (city-state, owner **26**). Gold now **57** (+4/turn).
- Barb camp last seen at **(20,29)**. Tile is revealed-but-fogged: no camp or
  unit in `plots_around`. Do not assume it is gone.
- Score 32, happiness 4, era Ancient.
- View at checkpoint: `GetGameViewRenderType() == 1` (`GAMEVIEW_STANDARD`, 3D),
  `InStrategicView() == false`. Leave it there unless the user asks.
- `quick_save` on turn 5 before ending that turn.
  File: `/home/ty/.local/share/Aspyr/Sid Meier's Civilization 5/Saves/single/quick/QuickSave.Civ5Save`
  Reloading that hotseat quicksave is still untested. Preserve the running game.
- turn_status: active_player=0, my_turn=true, blocking=ENDTURN_BLOCKING_UNITS,
  all modal flags false, pending_popups=[].

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

Live processes at checkpoint (PIDs from the previous session; re-check):

- Civ5XP launched via `CIV5_WAIT=1 scripts/launch_civ5.sh codex`.
  Logs `logs/codex.{out,err}`. **Do not launch a duplicate.**
- tunerd: `python3 -m harness.tunerd`. Shim is loaded; restarting tunerd is safe.
- `.venv` is Python 3.14 / MCP v2. System python3 is 3.12 (unit tests use it
  for liblua5.4).

## Changes this session (committed)

1. **`turn_status` modal flags.** `pending_popups` still only tracks
   `SerialEventGameMessagePopup`. `turn_state()` now also reports
   `leader_greeting_pending`, `city_state_greeting_pending`,
   `great_person_reward_pending`, `tech_popup_pending`, `discussion_pending`
   by querying those Lua contexts (cheap `states()` first, no 1s wait).
   Live turn 5: `pending_popups=[]` but `leader_greeting_pending=true`.
   `dismiss_pending_popups()` then closed **LeaderHeadRoot and a stacked
   CityStateGreetingPopup**. Flags went false. That greeting stack is why
   `end_turn` used to silently no-op.

2. **Catalog reads no longer change the map view (runtime.lua v22).**
   `UI.LookAt` is opt-in on `select_unit`. That was not enough: **`UI.SelectUnit`
   itself flips 2D/3D.** `available_unit_actions` no longer selects; it uses
   `unit:CanStartMission(id, -1, -1, false)` / `CanBuild` / `CanDoCommand` /
   `CanAutomate`. One-arg `CanStartMission(id)` is too loose (great-person
   missions returned true on a warrior). Live turn 6: view stayed
   `GAMEVIEW_STANDARD` through catalog + `plots_around`. Warrior/scout actions
   match the old panel list (SKIP/ALERT/FORTIFY/AUTOMATE_EXPLORE/MOVE_TO/
   ROUTE_TO/SWAP_UNITS/COMMAND_DELETE).

3. **`wait_for_my_turn` returns immediately when a tech must be chosen**
   (`tech_popup_pending` and `GetCurrentResearch() == -1`) instead of polling
   to timeout.

HTTP GET `/status` still mirrors `turn_state()`. Tests in
`tests/test_mcp_safety.py`. `python3 -m unittest tests.test_mcp_safety tests.test_liveness`
was green.

Played: ended turn 5 after dismissing the stacked greetings. Turn 6 is ours.
Did **not** move units (that still calls `SelectUnit`).

## Immediate next work

1. Ask the user: keep the current 3D view? Switch research Pottery→Writing
   (Calendar is 8 turns and was not the plan)?
2. Rewrite `select_unit` / `move_unit` / `unit_mission` to `unit:PushMission`
   (and equivalent) so orders do not `UI.SelectUnit`. Live-verify
   `GetGameViewRenderType` is unchanged across a move. Until then, **do not
   issue unit orders** — the user cannot follow the game if the view flips.
3. Then play turn 6: scout peeks without walking onto Egypt's warrior at
   (13,27); warrior stays north of fogged (20,29), marble/Zanzibar coast.
4. Trade proposal **read/accept** is still missing. Do not re-expose
   `propose_deal` (known crash). HTTP/WebSocket attention pings still later.

## Open risks (unchanged)

- One human hotseat seat only; two-human handoff untested live.
- No claim of full action coverage or crash-proof queueing.
- Modal allowlist fails closed for unknown popup enum names.
- tunerd timeout/reconnect, multi-client event cursors, delayed
  postconditions still to harden.
- CPU affinity mitigation still in the launcher. Multi-hour stability not
  established.
- `PushMission` without selection is **not** live-verified.
