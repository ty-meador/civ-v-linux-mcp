# Resume here — 2026-09-16 (turn 7, units unmoved)

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

**Camera rule:** do not flip 2D/3D. `move_unit` / `unit_mission` now use
`Unit:PushMission` with no `UI.SelectUnit`. Do not call `select_unit`,
`ToggleStrategicView`, or `SetGameViewRenderType`. Ask before any camera or
view change. `InStrategicView()` is the live 3D check (false = 3D).

**FOW rule:** `known_world` is the observation tool. Revealed tiles are
included; currently fogged tiles have `vis=false` and must not carry live
units/owners/improvements/cities/features. Unrevealed tiles are omitted.
Do not read dynamic plot state on fogged tiles.

## Exact campaign state

- Game is running: hotseat, nick **Codex** = seat **0**, Korea/Sejong,
  **turn 7, our turn, units still have 2 moves, orders NOT issued.**
- Seoul **8192** at **(16,27)**, pop 2, Worker **7 turns**, growth **6 turns**.
- Research: **Calendar, 7 turns**. Intended pick is still **Writing** —
  confirm before `set_research('TECH_WRITING')`.
- Scout **24576** at **(12,27)** (cows), 2 moves. Egypt warrior is **gone**
  from **(13,27)** (vis=true grass, no units). Adjacent peek is fine; do not
  declare war; do not walk onto a foreign unit.
- Warrior **16385** at **(19,32)**, 2 moves. Marble is at (19,33). Stay north
  of fogged (20,29).
- Met: Egypt (id 1, score 35, not at war); **Zanzibar** (id 26, minor,
  allied=false, friends=false). Gold **61** (+4).
- Barb camp last seen **(20,29)**: still `{x:20,y:29,vis:false,t:GRASS}` —
  discovered, fogged, no camp/unit leaked. Do not assume it is gone.
- `known_world` live: **126** revealed plots (**60** vis, **66** fogged,
  **0** fog leaks). `InStrategicView()` **false** (3D).
- blocking=ENDTURN_BLOCKING_UNITS. Modal flags empty.

## How to control the game

```sh
.venv/bin/python scripts/mcp_call.py --seat 0 known_world '{}'
.venv/bin/python scripts/mcp_call.py --seat 0 turn_status '{}'
.venv/bin/python scripts/mcp_call.py --seat 0 move_unit '{"unit_id":24576,"x":11,"y":27}'
.venv/bin/python scripts/mcp_call.py --seat 0 available_unit_actions '{"unit_id":16385}'
```

Seat **must** be `--seat 0`. Socket `$XDG_RUNTIME_DIR/civ5-tuner.sock`.
Sandbox cannot reach it. **Do not launch a duplicate Civ5.**

## Changes this session (committed)

Silent unit orders via `Unit:PushMission` (runtime.lua v24). `move_unit`,
`unit_mission`, `establish_trade_route`, and `plunder_trade_route` no longer
call `UI.SelectUnit` / `SelectionListMove` / `SelectionListGameNetMessage`.
Legality is `CanStartMission` / `CanBuild`; unrevealed plots are rejected;
MISSION_BUILD still puts the build id in iData1. Binder wants integer
`0, 0, 1` for iFlags/bAppend/bManual — booleans failed live.

Live-verified on this campaign: scout (13,25)→(13,26)→(12,27), warrior
(18,33)→(19,33)→(19,32), ended turn 6 → turn 7. `InStrategicView()` stayed
false. Tests cover no-select, unrevealed reject, and the build slot.

## Immediate next work

1. Confirm with user: keep 3D view? Switch research to Writing?
2. Play turn 7: scout on cows; Egypt warrior left (13,27); warrior at (19,32)
   stays north of fogged (20,29).
3. Trade read/accept still missing. Do not re-expose `propose_deal`.
4. `unit_mission` shares PushMission with the live-verified `move_unit` path
   but MISSION_BUILD / FORTIFY were not issued live this session.

## Open risks

Same as before: one human hotseat seat; tunerd reconnect; no claim of full
action coverage. City ranged attack still selects the city. `select_unit`
still exists for opt-in UI and still flips the view if called.
