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

## Current game state (2026-09-17, ninth session end, ~09:30)

Solo China game (Wu Zetian, Emperor), **turn 229**, start of my turn, no blockers, quick-saved
(`Saves/single/quick/QuickSave.Civ5Save`). Game + tunerd still running (`ps` for `Civ5XP` / `harness.tunerd`).
Drive it with `XDG_RUNTIME_DIR=/run/user/1000 .venv/bin/python scripts/mcp_call.py --seat 0 <tool> '<json>'`.

- Cities: Beijing (East India Company, ~7 turns), Shanghai (Harbor ~5), Guangzhou (Bank 13),
  Nanjing (Caravansary ~2). Research: Printing Press (~3 turns). Rationalism opened t227.
- Army: 4 Swordsmen (Guangzhou, Shanghai, near Nanjing (25,28)->(29,24) area, (25,21)), 2 Chu-Ko-Nu
  ((28,23) and Nanjing), 1 Archer in Beijing. 4 iron (2 own + India + Venice open-borders deals).
- 4/4 trade routes: Beijing->Ur (gold), Beijing->Guangzhou (food), Beijing->Antwerp, Nanjing->Antwerp.
  Gold 94 at +9/turn, science 153. **Happiness -1 again at t229** (cities grew past Circus Maximus; consider Colosseum/Zoo or a luxury trade). Faith 117 (+7/turn).
- Diplomacy: DoF with Poland. Sweden (score leader) and Poland made peace t220. Refused every
  Dye-for-gold offer (only luxury copy, happiness thin) and every open-borders-for-gold offer.
  Spy Liu (Agent) is in Stockholm stealing tech.
- Workers: 5, mostly asleep -- almost every workable tile is improved. Wake them for repairs.
- World Congress (Venice host) first session ~t241; I proposed Scholars in Residence.

## Immediate next work

1. Keep playing turn by turn (see the `endturn.sh` pattern in NOTES.md ninth session: status -> quick_save
   -> end_turn -> wait_for_my_turn -> digest/ready/needs-production). Handle `discussion_pending`
   with `discussion` + `incoming_deal` + `accept_deal`/`refuse_deal`/`respond_discussion`.
2. When Shanghai's Harbor completes: build a Cargo Ship and a Caravel there and exercise the untested
   naval side (MISSION_EMBARK, sea trade routes via available_trade_routes, naval move_unit pathing).
3. Bank in Beijing after East India Company; Printing Press -> Economics/Scientific Theory.
4. Untested harness paths still without tools: CHOOSE_IDEOLOGY, ADD_REFORMATION_BELIEF, DIPLO_VOTE
   (World Congress session ~t241 will hit league_cast_votes -- verify it live), CHOOSE_ARCHAEOLOGY.
