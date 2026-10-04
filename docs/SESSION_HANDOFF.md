# Resume here -- 2026-10-04 (evening): 1.12.0 TAGGED (runtime v263, 145 tools, 1430 tests) plus two fixes after it; THE VENICE/MONGOLIA HOTSEAT IS OVER -- replayed from the t250 autosave, RUSSIA WON A SCIENCE VICTORY in the t253 AI round; the game sits on that over state; Codex's Portugal is at t73

This file holds the current state only. Earlier "Resume here" sections (56 of them, 2026-09-19 to 2026-10-04)
live in git: `git log -p -- docs/SESSION_HANDOFF.md`. Shipped work is in `CHANGELOG.md`; known gaps are
inventoried in `docs/GAPS.md`.

## Where the game is

- **The Venice/Mongolia hotseat is finished.** Its t256 quick save was overwritten by Codex's Portugal game
  (2026-10-03 23:21), so this afternoon it was replayed from `hotseat/auto/AutoSave_0250 AD-1960` (t251-t253,
  seat 1, Claude from the session server). The replay diverged at once: Catherine (Russia) finished the SS
  Stasis Chamber and won a Science Victory in the t253 AI round (last time she had only the SS Engine at t256).
  Notes 126-128 in seat 1's notebook are the replay; 119-125 the first run of the same turns. The engine is
  parked on GAMESTATE_OVER (the `game_over` gate): `exit_to_main_menu` leaves it. Nothing else to do in it.
- **Codex's single-player game as Portugal** (gpt-6.1-sol, CIV5_CLIENT `codex/gpt-6.1-sol`): 73 turns on
  2026-10-03, saved as `single/Codex_as_Portugal.Civ5Save` (t73, after all orders, before the end) and in
  `single/quick/QuickSave`. Its 443 ledger rows are in `logs/calls.jsonl`
  (`scripts/ledger_report.py --client codex logs/calls.jsonl`). The next game to continue is this one
  (`load_latest` picks it, it is the newest save) or a fresh one.
- **The stack** (2026-10-04): Civ5XP relaunched at 15:06 (pid 42611), tunerd from 11:08 on
  `/run/user/1000/civ5-tuner.sock`, the session's MCP server (pid 42822, started 15:06:49) runs the code as of
  c690dbf (1.12.0) -- NOT the two fixes after it (d33e638, and the game-over one): `/mcp` reconnect picks
  them up. Both were checked live through a fresh stdio server (`scripts/mcp_session.py --seat 1`).

## Where the code is

- **main = tag `v1.12.0` (c690dbf) + two fixes**, `scripts/check.sh` green (1435 tests). 1.12.0 folds the 37
  entries since 1.11.0: a turn's closing orders and its end in one call (`finish_turn(actions=[...])`, a
  move's `revealed`, `--tools compact` with `call`), the call ledger's `client` label and the turn claim's
  `same_client`, refusals that say what to do instead, runtime v254-v263. README has a new "A refusal says
  what to do instead" bullet; ROADMAP carries the release paragraph; AGENT_INSTALL says 145 tools.
- **Checked live on the replay (t251-t253), fixed where it fell short:**
  - `unit_mission` with a made-up name: `did_you_mean` answered `["MISSION_ROUTE_TO"]` for
    MISSION_FORTIFY_HEAL on a fortified Infantry (the `or` between the legal and stock lists) -- d33e638
    scores one pool and keeps the names within 0.15 of the best (FORTIFY, HEAL). A hold sent to a unit already
    holding (legal list has COMMAND_WAKE, no hold) now carries a `reason`.
  - MISSION_FORTIFY on a civilian: `reason` names MISSION_SLEEP (right as shipped).
  - `finish_turn` when the game ends in the AI round: it ran to the wait's timeout and said "call again" under
    a `game_over` gate -- now the poll returns the over state at once, with `game_over`, `woke_because`
    `["game_over"]`, `victory` {winner, type, text, turn} from the notification log and a hint naming
    `exit_to_main_menu` (verified live: the fresh server answered in one poll).
  - Not yet seen live: the NO_ENDTURN_BLOCKING_TYPE re-send over an empty todo (`resent` on the reply).
- **Memory-rule reminders**: the ctx sandbox lacks XDG_RUNTIME_DIR, export
  `CIV5_TUNERD_SOCK=/run/user/1000/civ5-tuner.sock` before any `harness.cli` call there; `pkill -f` in a
  compound Bash call kills the shell; disband is denied to the auto-mode classifier; copy QuickSave to a named
  file before loading another save into a live game.

## Still open

- Spectator page: the scrubber shipped 2026-10-04 (play/pause, speed, slider with turn ticks, keys; `/recording`
  route); still open there: undetected submarines show in a seat view, the whole recording is loaded into memory.
- The next release is 1.13.0 when the unreleased entries warrant it (version bump, tag, README release row /
  test count / feature bullets, AGENT_INSTALL line 8, ROADMAP paragraph).
- The rest: `docs/GAPS.md`.
