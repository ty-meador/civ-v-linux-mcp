# Resume here — 2026-09-16 (turn 8, scout needs orders)

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

**Camera rule:** do not flip 2D/3D. Do not call `select_unit`,
`ToggleStrategicView`, or `SetGameViewRenderType`. `InStrategicView()` false = 3D.

**FOW rule:** `known_world` is the observation tool. Fogged tiles `vis=false`
must not carry live occupants. Unrevealed tiles omitted.

**Deals:** `trade_catalog(player_id)` is the read of what *could* go on a
table. `incoming_deal` / `accept_deal` / `refuse_deal` for an offer already
on it. City-states: `city_state_gifts` / `minor_gold_gift` (tiers 250/500/1000).
Do **not** re-expose full `propose_deal` (PEACE_TREATY Add* crashed). Lump GOLD
is currently illegal (no Currency); GPT *is* legal. A 1 GPT offer to Egypt
was sent via `Game.propose_deal` (not MCP) and accepted live.

## Exact campaign state

- Hotseat, nick **Codex** = seat **0**, Korea/Sejong, **turn 8, our turn**.
- Seoul **8192** (16,27), pop 2, Worker in queue. Calendar still researching.
- Scout **24576** at **(11,29)**, 2 moves, ready=true. Blocking UNITS.
- Warrior **16385** at **(18,32)**, 2 moves, **ready=false** — ALERT from turn 7
  persisted; wake (COMMAND_WAKE / MISSION) before moving.
- Egypt accepted **1 GPT for 25 turns**. Gold **64**, GPT **3** (was 4).
  Ramesses "I must accept." (`DIPLO_UI_STATE_BLANK_DISCUSSION`) — dismissed.
- Zanzibar friendship 0; small gift is 250 gold (not affordable).
- Egypt warrior last **(13,29)** turn 7. Barb camp last **(20,29)** fogged.
- `incoming_deal` empty. `InStrategicView()` false. No discussion pending.

## How to control the game

```sh
.venv/bin/python scripts/mcp_call.py --seat 0 trade_catalog '{"player_id":1}'
.venv/bin/python scripts/mcp_call.py --seat 0 city_state_gifts '{"player_id":26}'
.venv/bin/python scripts/mcp_call.py --seat 0 incoming_deal '{}'
```

Seat **must** be `--seat 0`. Socket `$XDG_RUNTIME_DIR/civ5-tuner.sock`.
**Do not launch a duplicate Civ5.**

## Changes this session (committed)

`trade_catalog` (IsPossibleToTradeItem only) and `city_state_gifts` /
`minor_gold_gift` (`Game.DoMinorGoldGift`, stock tiers). Live: catalog said
GPT yes / lump gold no; CS small gift unaffordable; 1 GPT to Egypt accepted
and GPT dropped 4→3; 3D view held.

## Immediate next work

1. Play turn 8: scout from (11,29); wake warrior if you want it to move.
2. Optional MCP: a GPT/gold-only `offer_deal` that still refuses peace/DoF.
3. Writing vs Calendar. Keep 3D.
4. First `accept_deal` still needs an *incoming* AI offer.

## Open risks

Full `propose_deal` still unsafe for PEACE_TREATY/DoF. GPT/gold-per-turn
Add* worked this once; do not treat that as a blank check for every Add*.
