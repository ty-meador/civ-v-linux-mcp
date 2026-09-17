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

**Camera rule:** do not flip 2D/3D. Do not call `select_unit` / `move_unit` /
`unit_mission` until those use `PushMission` without `UI.SelectUnit`. Do not
call `ToggleStrategicView` or `SetGameViewRenderType`. Ask before any camera
or view change.

**FOW rule:** `known_world` is the observation tool. Revealed tiles are
included; currently fogged tiles have `vis=false` and must not carry live
units/owners/improvements/cities/features. Unrevealed tiles are omitted.
Do not read dynamic plot state on fogged tiles.

## Exact campaign state

- Game is running: hotseat, nick **Codex** = seat **0**, Korea/Sejong,
  **turn 6, our turn, units still have 2 moves, orders NOT issued.**
- Seoul **8192** at **(16,27)**, pop 2, Worker **8 turns**.
- Research: **Calendar, 8 turns** (auto-queued after Pottery). Intended pick
  is still **Writing** — confirm before `set_research('TECH_WRITING')`.
- Scout **24576** at **(13,25)**, 2 moves. Egypt warrior **visible** at
  **(13,27)** (owner 1, vis=true). Peek; do not walk onto them; no war.
- Warrior **16385** at **(18,33)**, 2 moves. Marble at (19,33).
- Met: Egypt (id 1, score 34, not at war); **Zanzibar** (id 26, minor,
  allied=false, friends=false). Gold **57**.
- Barb camp last seen **(20,29)**: plot is in `known_world` as
  `{x:20,y:29,vis:false,t:GRASS}` — discovered, fogged, no camp/unit leaked.
  Do not assume it is gone.
- `known_world` live: **118** revealed plots (**60** vis, **58** fogged,
  **0** fog leaks). View still `GAMEVIEW_STANDARD` (3D).
- blocking=ENDTURN_BLOCKING_UNITS. Modal flags empty.

## How to control the game

```sh
.venv/bin/python scripts/mcp_call.py --seat 0 known_world '{}'
.venv/bin/python scripts/mcp_call.py --seat 0 turn_status '{}'
.venv/bin/python scripts/mcp_call.py --seat 0 available_unit_actions '{"unit_id":16385}'
```

Seat **must** be `--seat 0`. Socket `$XDG_RUNTIME_DIR/civ5-tuner.sock`.
Sandbox cannot reach it. **Do not launch a duplicate Civ5.**

## Changes this session (committed)

`known_world` (runtime.lua v23): one read of empire, own units/cities, met
civs **and city-states**, notifications, and **every revealed plot**. Each
plot has `vis=true` (in sight) or `vis=false` (discovered, fogged). Fogged
plots omit live occupants. Unrevealed tiles are absent. `map_window` uses
the same encoder. Diplomacy no longer drops met minors.

Live-verified on this campaign: 118 plots, 60/58 vis/fog, (20,29) fogged
grass only, Egypt warrior only on a vis tile, Zanzibar in `met`, camera
unchanged. Tests cover fog-cheat and unmet city-states.

## Immediate next work

1. Confirm with user: keep 3D view? Switch research to Writing?
2. Silent unit orders via `PushMission` (no SelectUnit). Until then do not
   move units.
3. Then play turn 6: scout peeks without eating Egypt's warrior; warrior
   stays north of fogged (20,29).
4. Trade read/accept still missing. Do not re-expose `propose_deal`.

## Open risks

Same as before: one human hotseat seat; PushMission untested; tunerd
reconnect; no claim of full action coverage.
