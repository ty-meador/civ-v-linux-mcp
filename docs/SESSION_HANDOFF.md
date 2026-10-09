# Resume here -- 2026-10-08 (night): runtime v265, 145 tools; GROK'S ENGLAND GAME is the live game, at t127 after Claude took the seat at t118 and made peace; the Venice/Mongolia hotseat is over (Russia won t253); Codex's Portugal is at t118 in `single/Codex_as_Portugal`

This file holds the current state only. Earlier "Resume here" sections (57 of them, 2026-09-19 to 2026-10-04)
live in git: `git log -p -- docs/SESSION_HANDOFF.md`. Shipped work is in `CHANGELOG.md`; known gaps are
inventoried in `docs/GAPS.md`.

## Where the game is

- **Grok's England game** (grok-shell-civ5/1.0.41, seat 0, solo, `L7-C5-Assets_Maps_continents-London`): Grok
  played t0-t118 on 2026-10-04 23:24 to 2026-10-05 05:24 (2623 ledger rows in `logs/calls.jsonl`) and stopped
  mid-turn with London alone at 68/250 hp inside a ring of twenty Songhai, Spanish and Portuguese units, at war
  with those three and eleven city-states. `load_latest` picks this game (its quick save is the newest). On
  2026-10-08 Claude took the seat from the session server: white peace with all three on the first ask at t118
  (every allied city-state along), food focus against the starvation, DoF with Spain (t119), open borders with
  Rome / Mongolia / Ottomans / Spain, caravans to Madrid (t121) and York (t125), University building, Chivalry
  researching, the Embargo England proposal defeated at the First Council of Lisbon (t126). Grok's t118 state is
  kept as `single/Grok_as_England_0118 siege` and `saves/Elizabeth_0118 grok-siege` (S8). The notebook's plan
  note (id 1) is current as of t126; assignments 42 (longbow in London) and 43 (scout exploring north of Persia).
  The game sits at **t127, my turn, only the scout to order**.
- **Codex's Portugal game** (gpt-6.1-sol) is at t118 in `single/Codex_as_Portugal.Civ5Save` (its own quick save
  was overwritten by Grok's game); the arrival fix (a104091) was found on it at t95.
- **The Venice/Mongolia hotseat is finished** (Russia, Science Victory, t253; notes 119-128 in seat 1's notebook).
- **The stack** (2026-10-08 21:09): Steam, Civ5XP (pid 18367), tunerd (pid 19039) on
  `/run/user/1000/civ5-tuner.sock`. The session's MCP server (pid 20035, started ~21:17) runs the Python as of
  5a606d0 and the Lua source of **v264**; the v265 edit was injected through a fresh stdio server
  (`scripts/mcp_session.py --seat 0`). Memory rule: two servers built from different runtime sources re-inject
  each other into one game -- `/mcp` reconnect the session server before using its civ5 tools again.

## Where the code is

- **main = 5a606d0 + tonight's v265 commit** (see CHANGELOG "Four things a human saw that the seat did not"):
  `turn_state.wars` + the briefing's `at_war` warnings, the leader screen outranking `turn_not_active` in the
  gate, `unit_displaced` events from `H.displaced_compare` at the turn start, `league_status.special_session`.
  `scripts/check.sh` green.
- **Unreleased since 1.12.0**: nine entries (this one, the arrival hook a104091, the tuner stream resync c1f4e8d,
  the headless-deal removal 5a606d0, the scrubber, and four 2026-10-04 fixes). 1.13.0 is due when it is cut:
  version bump, tag, README release row / test count / feature bullets, AGENT_INSTALL line 8, ROADMAP paragraph.
- **Memory-rule reminders**: the ctx sandbox lacks XDG_RUNTIME_DIR, export
  `CIV5_TUNERD_SOCK=/run/user/1000/civ5-tuner.sock` before any `harness.cli` call there; `pkill -f` in a
  compound Bash call kills the shell; disband is denied to the auto-mode classifier; copy QuickSave to a named
  file before loading another save into a live game.

## Still open

- `unit_displaced` has regression coverage and the live rule behind it (the General jumped twice, t121 and t125);
  the row itself has not been read live yet -- a Caravan built or bought into London with the General asleep there
  and one end_turn through a v265 server shows it.
- The `at_war` warning and `wars` status: coded from the t118 catalog reads (peace gate open with all three);
  England is at peace with everyone now, so a live read needs another war.
- Why the engine moves the civilian and not the trade unit, and whether a Worker or Settler is moved the same way:
  not known; the row reports the fact either way.
- Spectator page: undetected submarines show in a seat view; the whole recording is loaded into memory.
- The rest: `docs/GAPS.md`.
