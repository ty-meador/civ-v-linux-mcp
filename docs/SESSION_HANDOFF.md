# Resume here — 2026-09-17 (after the Steam Deck / 3-seat LAN session)

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

## Current game state (2026-09-17, eleventh session, in progress)

Solo China game (Wu Zetian, Emperor), **turn 251+**, runtime v54. Game + tunerd running since 00:17.
Drive it with `XDG_RUNTIME_DIR=/run/user/1000 .venv/bin/python scripts/mcp_call.py --seat 0 <tool> '<json>'`,
or end a turn with `scripts/et.sh > logs/et_last.log` **as a background job** (it saves, ends the turn,
blocks until my turn or an AI question, then prints digest + overview; `python3 scripts/turn_brief.py`
summarises that log). That is the no-polling pattern: the session is woken when the job exits.

- Happiness +2 (was -1 since t229): Antwerp (mercantile) friends via a 250g gift at t250. Zoos still
  coming in Beijing (t252), Guangzhou, Shanghai, Nanjing (6t). Science 159-180 depending on happiness.
- Research: Scientific Theory (9t) -> Public Schools. Architecture done t251.
- Gold ~146 at +20/turn (dropped from 27: barbarians pillaged Guangzhou's trading post at (29,24) again,
  and Antwerp gift). Worker 49155 farming (28,24); repair (29,24) when it is free. Worker 98309
  lumbermill (22,24), 204809 lumbermill (24,19), 213003 asleep in Shanghai.
- Barbarian Musketman killed t249 (city + Chu-Ko-Nu). Chu-Ko-Nu 385032 got Accuracy II, fortified (28,23).
- Caravel 540678 exploring east along y=13 (at (36,13)), nothing but ocean so far; move_unit's
  nearest_revealed hint is how to keep pushing into the unknown.
- Spies: Liu gathering intel in Delhi (27t); Wu moved to Antwerp t251 (rig elections -> influence).
- World Congress in session t251: voted 2 for China as host. Sciences Funding proposed earlier.
- Declined Sweden's coop war vs Poland (t248/249). DoF with Venice; RA with Poland.

## Tenth session (2026-09-17, ~09:30-): propose_deal works (real trade screen)

`propose_deal(player_id, items, ask_counter)` and `negotiate_deal(player_id, items, mode)` are live MCP tools
now (see NOTES.md tenth session). They drive LeaderHeadRoot.OnTrade -> DiploTrade pocket handlers ->
OnPropose and close everything themselves; results carry measured `effects`. Venice holds one of my Copper
for free until t261 (dev accident, see NOTES). Game still at **turn 231** when this was written.

## Immediate next work

1. Keep playing turn by turn (`et.sh` pattern: end_turn -> wait_for_my_turn -> turn_digest/overview/cities;
   turn_status now carries `todo`). Buy Shanghai's Zoo once gold > 740; adopt a Rationalism policy at 1125 culture.
2. Architecture -> Scientific Theory -> Public Schools; Factories after (Ideology at 3).
3. Use `propose_deal` / `negotiate_deal` when a luxury or RA is worth it (AIs currently value my spare Dye at
   nothing; RA with Venice/India/America when embassies + gold allow). Human recipients and PEACE_TREATY are
   the unsupported cases (leader screen "negotiate peace" = FROM_UI_DIPLO_EVENT_HUMAN_NEGOTIATE_PEACE, untried).
4. Naval: finish the Caravel's coastal loop; when a route slot frees, Cargo Ship from Shanghai for sea trade.
5. Untested still: CHOOSE_IDEOLOGY, ADD_REFORMATION_BELIEF, CHOOSE_ARCHAEOLOGY.
