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

## Current game state (2026-09-17, eleventh session, ~13:10)

Solo China game (Wu Zetian, Emperor), **turn 263**, runtime v60. Game + tunerd running since 00:17.
Drive it with `XDG_RUNTIME_DIR=/run/user/1000 .venv/bin/python scripts/mcp_call.py --seat 0 <tool> '<json>'`,
or end a turn with `scripts/et.sh > logs/et_last.log` **as a background job** (saves, ends the turn, waits
until my turn or an AI question, prints discussion/deal/digest/overview; `python3 scripts/turn_brief.py`
summarises the log; `scripts/et.sh --wait-only` resumes after answering an AI mid-turn).

- Happiness 12, science 208, gold 101 at +21/turn, culture 175/1355 (Secularism adopted t258).
- Deals (30 turns from t262): Dye -> America for 5 GPT + OB; Copper -> Venice for 5 GPT + OB; Copper ->
  Sweden for 4 GPT + OB (accepted their offer). Copper mine at (26,26) done t263 so one copy is home.
  Refused: Venice's renewal (Copper for nothing), America's Copper-for-Horses.
- City-states: Antwerp + Zanzibar mercantile friends (influence 50 each); Ur 17; Florence, Genoa, Monaco
  met. Spy Wu rigging Antwerp (10t), Liu sent to Zanzibar t260.
- Research Electricity (10t). Production: Beijing Bank, Shanghai Bank, Guangzhou Machu Picchu (19t),
  Nanjing Public School (8t). All four cities growing, all connected to the capital.
- 5/5 trade routes (Beijing->Antwerp/Ur/Shanghai-production, Nanjing->Ur/Antwerp); `trade_routes` shows
  turns_left. Workers: 49155 farming (26,25); others asleep.
- Caravel 540678 at (36,9) circling north to reach (46,10) / the unclaimed strip at (41-45, 9-13); its
  multi-turn move must be re-issued every turn (todo flags it as stalled_mission).
- World Congress: voted China as host t251 (Venice stayed host). Sweden warred Poland t254, peace t261.

## Tenth session (2026-09-17, ~09:30-): propose_deal works (real trade screen)

`propose_deal(player_id, items, ask_counter)` and `negotiate_deal(player_id, items, mode)` are live MCP tools
now (see NOTES.md tenth session). They drive LeaderHeadRoot.OnTrade -> DiploTrade pocket handlers ->
OnPropose and close everything themselves; results carry measured `effects`. Venice holds one of my Copper
for free until t261 (dev accident, see NOTES). Game still at **turn 231** when this was written.

## Immediate next work

1. Keep playing: `scripts/et.sh > logs/et_last.log` in the background, `python3 scripts/turn_brief.py` on
   wake, then act on `todo` (stalled_mission units need move_unit re-issued each turn) and `blocking_hint`.
2. Scientific Theory (t260) -> Public Schools; Beijing Bank (t266), Nanjing Bank (t262), Zoos in
   Shanghai/Guangzhou. Copper mine at (26,26) finishing -> a tradeable luxury for propose_deal.
3. Happiness +5: Antwerp AND Zanzibar are mercantile friends now (t250, t258). Florence met t257 (also
   "seeks investors"); Ur influence 17. Sweden is allying every city-state -- watch for ally flips.
4. Caravel at (46,17) heading north along the eastern continent (India + a city-state, owner 22).
5. Untested still: CHOOSE_IDEOLOGY (3 factories or Modern era), ADD_REFORMATION_BELIEF, CHOOSE_ARCHAEOLOGY,
   sea trade routes (Cargo Ship), propose_deal for a luxury once Copper is improved.
6. Harness: tunerd.py's BrokenPipe fix only applies after the next tunerd restart. The multi-turn move
   non-resume (NOTES eleventh session) is characterised, not root-caused.
