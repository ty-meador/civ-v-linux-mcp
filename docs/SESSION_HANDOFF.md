# Resume here — 2026-09-16 (turn 7, orders issued, turn not ended)

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

**Camera rule:** do not flip 2D/3D. `move_unit` / `unit_mission` use
`Unit:PushMission`. `city_ranged_attack` uses `Network.SendDoTask` (no
`UI.SelectCity`). Do not call `select_unit`, `ToggleStrategicView`, or
`SetGameViewRenderType`. Ask before any camera or view change.
`InStrategicView()` is the live 3D check (false = 3D).

**FOW rule:** `known_world` is the observation tool. Revealed tiles are
included; currently fogged tiles have `vis=false` and must not carry live
units/owners/improvements/cities/features. Unrevealed tiles are omitted.
Do not read dynamic plot state on fogged tiles.

**Deals:** read with `incoming_deal`. Accept/refuse an offer already on the
table with `accept_deal` / `refuse_deal`. Do **not** re-expose `propose_deal`.

## Exact campaign state

- Game is running: hotseat, nick **Codex** = seat **0**, Korea/Sejong,
  **turn 7, our turn, unit orders issued, end_turn NOT called.**
- Seoul **8192** at **(16,27)**, pop 2, Worker **7 turns**.
- Research: **Calendar, 7 turns**. Intended pick is still **Writing**.
- Scout **24576** at **(11,29)**, 0 moves, ready=false.
  Path this turn: (12,27) cows → (12,28) cotton → (11,29).
- Warrior **16385** at **(18,32)**, activity=4 (alert), ready=false,
  1 move left (ALERT does not spend leftover MP). Path: (19,32) → (18,32)
  then `unit_mission(MISSION_ALERT)`.
- Egypt warrior last seen **(13,29)** (owner 1, vis=true). Do not walk onto
  them. Barb camp last **(20,29)** still fogged grass.
- Met: Egypt, Zanzibar. Gold **61**.
- blocking=**NO_ENDTURN_BLOCKING_TYPE**. `InStrategicView()` false.
- `incoming_deal` still empty. No AI offer this turn.

## How to control the game

```sh
.venv/bin/python scripts/mcp_call.py --seat 0 turn_status '{}'
.venv/bin/python scripts/mcp_call.py --seat 0 end_turn '{}'
.venv/bin/python scripts/mcp_call.py --seat 0 incoming_deal '{}'
```

Seat **must** be `--seat 0`. Socket `$XDG_RUNTIME_DIR/civ5-tuner.sock`.
Sandbox cannot reach it. **Do not launch a duplicate Civ5.**

## Changes this session (committed)

`available_city_strikes` / `city_ranged_attack` now key off
`CanRangeStrikeNow()` (runtime.lua v26). Live: `CanRangeStrike()` was true
on the ungarrisoned capital while `CanRangeStrikeNow()` was false; the
catalog had reported `can=true` with zero targets. Lua `and/or` must not
be used for that gate (`false Now()` is falsy and would fall through).

Live-tested this slice: illegal accept/refuse/strike/move/settle all
rejected cleanly; scout two peeks; warrior move + **MISSION_ALERT**
(`{ok:true}`, activity 4, ready=false, view stayed 3D). Did not end the turn.

## Immediate next work

1. `end_turn` to start turn 8 (or keep playing from here).
2. Confirm Writing vs Calendar; keep 3D.
3. First live `accept_deal` still needs an actual AI offer.
4. Optional: `trade_catalog(other_player)` via IsPossibleToTradeItem only.

## Open risks

Same as before. ALERT leaving leftover moves is engine behavior, not a
harness no-op (ready flipped false and blocking cleared).
