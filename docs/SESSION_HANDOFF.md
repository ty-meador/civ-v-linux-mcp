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
table with `accept_deal` / `refuse_deal`. Do **not** re-expose `propose_deal`
(Add* on the scratch deal has crashed the process).

## Exact campaign state

- Game is running: hotseat, nick **Codex** = seat **0**, Korea/Sejong,
  **turn 7, our turn, units still have 2 moves, orders NOT issued.**
- Seoul **8192** at **(16,27)**, pop 2, Worker **7 turns**, growth **6 turns**.
- Research: **Calendar, 7 turns**. Intended pick is still **Writing** —
  confirm before `set_research('TECH_WRITING')`.
- Scout **24576** at **(12,27)** (cows), 2 moves. Egypt warrior last seen
  leaving **(13,27)**.
- Warrior **16385** at **(19,32)**, 2 moves. Stay north of fogged (20,29).
- Met: Egypt (id 1), Zanzibar (id 26). Gold **61**.
- Barb camp last seen **(20,29)** still fogged grass only.
- `incoming_deal` live: empty (`n=0`, from/to=-1).
- `available_city_strikes(8192)`: `can=true`, no targets (peace, nothing in range).
- `InStrategicView()` **false** (3D). Units not moved this session.
- blocking=ENDTURN_BLOCKING_UNITS. Modal flags empty.

## How to control the game

```sh
.venv/bin/python scripts/mcp_call.py --seat 0 incoming_deal '{}'
.venv/bin/python scripts/mcp_call.py --seat 0 available_city_strikes '{"city_id":8192}'
.venv/bin/python scripts/mcp_call.py --seat 0 known_world '{}'
```

Seat **must** be `--seat 0`. Socket `$XDG_RUNTIME_DIR/civ5-tuner.sock`.
Sandbox cannot reach it. **Do not launch a duplicate Civ5.**

## Changes this session (committed)

Runtime.lua v25:

1. `incoming_deal` — read scratch deal via ResetIterator/GetNextItem. No Add*.
2. `accept_deal` / `refuse_deal` — if DiploTrade is open, click the stock
   Accept/Refuse buttons; otherwise `UI.DoFinalizePlayerDeal` on a non-empty
   scratch deal. Empty deal is `{ok:false, err:"no incoming deal"}`.
3. `available_city_strikes` + `city_ranged_attack` via `Network.SendDoTask`
   (no `UI.SelectCity`).

Live-verified read-only on this campaign (turn 7, units unmoved, 3D). Accept
and bombard were not issued (nothing on the table; no strike targets).

## Immediate next work

1. Play turn 7 (user skipped play this session to focus on features).
2. Confirm Writing vs Calendar; keep 3D.
3. When an AI offer actually appears: `incoming_deal` then accept/refuse.
   That is the first live accept. Do not re-expose `propose_deal`.
4. Optional: `trade_catalog(other_player)` via IsPossibleToTradeItem only
   (never Add*).

## Open risks

One human hotseat seat; tunerd reconnect; accept_deal's DiploTrade.OnPropose
path is unit-tested, not live (no offer this turn). SendDoTask bombard is
unit-tested, not live-fired. `select_unit` still flips the view if called.
