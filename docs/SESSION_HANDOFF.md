# Resume here — 2026-09-17 (fourteenth session, solo China game)

## User directive for the next session

The user will set up a **fresh game for Claude to play alone** (single LLM seat, in-game AI opponents)
and sleep. Play it to win, manually, turn by turn, and fix/catalog harness bugs as they come up.
Standing rules: [[feedback-civ5-play-manually]] (no heuristic play loops), quick_save every turn,
human-visible information only, don't flip 2D/3D, commit incrementally, don't push.

Victory conditions the user prefers: domination, science or culture. Diplomatic victory OFF (too easy on
a small map). Difficulty "hard" = HANDICAP_EMPEROR on the human slot(s).

## How to control the game (no MCP client attached in the last session)

```sh
.venv/bin/python scripts/mcp_call.py --seat 0 turn_status '{}'      # goes through the real MCP tool layer
.venv/bin/python scripts/mcp_call.py --seat 0 wait_for_my_turn '{"timeout": 360}'
```

Seat: `--seat 0` for a game hosted from this desktop (LAN host or single human). The desktop instance is
launched by `scripts/launch_civ5.sh` (shim + 8-CPU taskset), bridge by `python -m harness.tunerd`
(socket `$XDG_RUNTIME_DIR/civ5-tuner.sock`). If the user hosts through the game UI, `cli.py status`
shows `StagingRoom`; ready up with the Lua in the "Ready up" snippet below, then `launch_game()`.

Ready up + launch from a user-made lobby:
```python
from harness.game import Game; g=Game(); c=g.c; stg=c.wait_state("StagingRoom",5)
c.exec(stg,"local me=Matchmaking.GetLocalID(); PreGame.SetNickName(me,'Claude'); PreGame.SetReady(me,true); Network.BroadcastPlayerInfo()")
g.launch_game(); g.wait_ingame(); g.detect_seat(); g.quick_save()
```
`cli.py host-lan` now takes `--map continents.lua --size WORLDSIZE_SMALL --close 3 --handicap HANDICAP_EMPEROR`.

## What happened this session (2026-09-17, ~00:00-01:00)

- Steam Deck (`deck@10.10.10.171`) set up as a second LLM seat for Grok: switched Civ V from Proton to
  the native Linux build, harness + venv installed, user systemd units `steam-harness`, `civ5-game`,
  `civ5-tunerd`. Full how-to: `docs/DECK_HOWTO.md`; LLM-player playbook: `docs/GROK_PLAYBOOK.md`.
- Two 3-seat LAN games were started (Claude host on desktop, Grok/Siam on the Deck, 1 AI). The user is
  parking the Deck idea for now: the Deck crashed once (new signature, gamecore DLL null-deref, see
  NOTES.md) and driving both seats by hand was clumsy. The current LAN game (turn 2, Claude = Indonesia,
  Jakarta at (38,29), Pottery researching, Scout in production) is effectively abandoned.
- Harness fixes committed this session:
  - `dismiss_pending_popups` now closes `TextPopup` (BUTTONPOPUP_TEXT message boxes, e.g. "player
    disconnected") and cancels `DeclareWarPopup` confirmations (BUTTONPOPUP_DECLAREWARMOVE "entering that
    territory would trigger war") via `HideWindow()`, then clears the stale H.popups record because
    HideWindow does not fire PopupProcessed. **Neither has been re-verified live after the final edit**
    -- the Deck seat's stuck DECLAREWARMOVE was cleared by hand with the same calls, which is the evidence.
  - `host_lan` gained map_script / world_size / closed_seats / handicap.
  - `launch_civ5.sh` gained CIV5_STEAM_LIB / CIV5_SLR_LIB overrides; `scripts/launch_deck.sh` preset.

## Known gotchas fresh in mind

- `move_unit` into an unrevealed plot is refused ("plot is not revealed") -- use `map_window` first.
- `move_unit` toward a city-state/rival border silently pops the war-move confirmation; the unit does not
  move and `MISSION_SKIP` does not clear ENDTURN_BLOCKING_UNITS until that popup is dismissed.
- The game rewrites config.ini on exit; a relaunch by the user through Steam's UI (no shim) leaves the
  tuner disabled in MP. Always relaunch through the harness launcher.
- The mcp guard blocks every action tool with "popup needs a decision" while any recorded popup remains;
  `wait_for_my_turn` runs the sweep.

## Current game state (2026-09-17, fourteenth session, ~17:40)

Solo China game (Wu Zetian, Emperor), **turn 278 ending** (et.sh may be running in the background;
check `logs/et_last.log` / `python3 scripts/turn_brief.py` first). Runtime v72. Game + tunerd running
since 00:17. Drive it with `XDG_RUNTIME_DIR=/run/user/1000 .venv/bin/python scripts/mcp_call.py --seat 0
<tool> '<json>'`, end turns with `scripts/et.sh > logs/et_last.log` **as a background job**, and
`scripts/et.sh --wait-only` after answering an AI mid-turn. et.sh exits on an end-turn block (e.g. World
Congress votes): clear the block, re-run it.

- Happiness **5** (Gems sold to America t273 -- our only copy, see NOTES fourteenth session), science
  247, gold 639 at +58/turn, culture 658/1355, faith 111. Iron 0 spare after disbanding two level-1
  Swordsmen t277 (`overview.strategic_resources`); 16 units, 2 Swordsmen (lvl 3) + 2 Chu-Ko-Nu remain.
- Research Metallurgy (done t279 -> choose next: Fertilizer / Archaeology / Radio were the others).
  Production: Beijing Opera House (~5t), Shanghai Public School (~11t; Seaport available), Guangzhou
  Public School (19t, Machu Picchu done t278), Nanjing Opera House (~2t). No happiness building is buildable anywhere (all built); the fifth city will push
  happiness to ~2, so consider a policy or luxury import (America has Spices and Salt spare).
- Settler 638976 standing order to **(43,12)** (coastal plains hill on the eastern strip: Wheat, 2 Fish,
  Horse, Aluminum, Silver in range); embarked t277, at (31,16) t279, ~3 plots/turn. Worker 49155 follows
  (embarked, (33,20)). Monaco (city-state at (40,8)) owns the plots to its west. On arrival: `MISSION_FOUND`
  only with moves left; expect edge cases. `map_window` shows
  `owner` only on currently visible plots.
- Caravel 540678 at (37,24) exploring south (`explore_frontier` now has `reachable`). (52,6) unreachable from the
  north; the unexplored east coast must be reached around the south.
- Deals: Gems -> America 5 GPT (t273-303); Dye deal with America expired t272 (Dye no longer in the
  catalog -- America has its own now); Copper -> Venice 5 GPT+OB; Copper -> Sweden 4 GPT+OB (to ~t292).
- World Congress t275: our Sciences Funding failed, Venice's Arts Funding passed. Spies Liu (Zanzibar)
  and Wu (Antwerp) rigging elections, 10 turns left. "Industrialization stolen!" notification t275.
- City-states: Antwerp Friends, Zanzibar friend, Ur 17. 5/5 trade routes (slot frees t282 earliest).

## Thirteenth session (2026-09-17, ~14:00-14:30)

- New `explore_frontier(unit_id, limit)` tool/route (runtime v64-v66): fog-edge plots of the unit's
  domain, nearest first, `unrevealed_neighbors`, terrain, `map_edge` on polar rows. Caveat: `distance`
  is hex distance, not path length (see NOTES thirteenth session).
- `mcp_call.py` tool errors exit 1 cleanly (no ExceptionGroup traceback).
- Tests 34/34: `uv run --with pytest pytest -q tests`.

## Tenth session (2026-09-17, ~09:30-): propose_deal works (real trade screen)

`propose_deal(player_id, items, ask_counter)` and `negotiate_deal(player_id, items, mode)` are live MCP tools
now (see NOTES.md tenth session). They drive LeaderHeadRoot.OnTrade -> DiploTrade pocket handlers ->
OnPropose and close everything themselves; results carry measured `effects`. Venice holds one of my Copper
for free until t261 (dev accident, see NOTES). Game still at **turn 231** when this was written.

## Immediate next work

1. Read `logs/et_last.log` (turn_brief.py): act on `todo`, `blocking_hint`, any discussion.
2. Nanjing Settler -> eastern strip (see route above). This is the first live embark + cross-sea settle;
   expect move_unit / MISSION_FOUND edge cases and fix them.
3. Navigation -> Seaport in Shanghai; then a Cargo Ship once a trade-route slot frees (t282 earliest,
   `trade_routes` shows turns_left) to test sea trade routes.
4. Untested still: CHOOSE_IDEOLOGY (3 factories or Modern era), ADD_REFORMATION_BELIEF, CHOOSE_ARCHAEOLOGY.
5. Harness idea: `explore_frontier` cannot report path length (Unit:GeneratePath NYI); consider marking
   plots on the far side of land as `same_water_body=false` via a flood fill over revealed water.
