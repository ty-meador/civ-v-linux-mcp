# Resume here -- 2026-10-04 (afternoon): 1.12.0 TAGGED (runtime v263, 145 tools, 1430 tests); the game was relaunched today and sits at the legal screen with NO SAVE LOADED; Mongolia's newest save is the t250 AUTOSAVE (the t256 quick save was overwritten by Codex's Portugal game), Codex's Portugal is at t73

This file holds the current state only. Earlier "Resume here" sections (55 of them, 2026-09-19 to 2026-10-04)
live in git: `git log -p -- docs/SESSION_HANDOFF.md`. Shipped work is in `CHANGELOG.md`; known gaps are
inventoried in `docs/GAPS.md`.

## Where the game is

- **Two games, one engine.** (1) The Venice/Mongolia hotseat: Venice (seat 0) fell to China t243, Mongolia
  (seat 1) alone since t244, played by Claude from the session server (`--seat auto`). (2) Codex's single-player
  game as Portugal (gpt-6.1-sol, CIV5_CLIENT `codex/gpt-6.1-sol`), 73 turns over 2026-10-03, saved as
  `single/Codex_as_Portugal.Civ5Save` (t73, after all orders, before the end) and in `single/quick/QuickSave`.
  Its ledger rows (443) are in `logs/calls.jsonl`; `scripts/ledger_report.py --client codex logs/calls.jsonl`.
- **The stack right now** (2026-10-04 15:06): Civ5XP relaunched (pid 42611) and parked on `LegalScreen`; tunerd
  from 11:08 on `/run/user/1000/civ5-tuner.sock` still answers (`harness.cli status`); the session's MCP server
  (pid 42822, started 15:06:49) runs the current main, every 1.12.0 fix included. Nothing is loaded: `load_save`
  the hotseat autosave for Mongolia or `load_latest` for Codex's Portugal (newest file overall).
- **Mongolia's newest save is `hotseat/auto/AutoSave_0250 AD-1960.Civ5Save` (t250, 2026-10-03 21:43).** The
  t256 state below was in the quick-save slot, and Codex's game overwrote it at 23:21 (the lesson in
  `project_quicksave_overwritten_by_finish_turn`: copy QuickSave to a named file before loading another save).
  Resuming from t250 replays t251-t256: Portugal and Russia declared war in the t255 AI round last time; the
  bullets below are what the ring, the war and the diplomacy looked like at t256 and will differ this time.
  Loop per turn: `finish_turn(actions=[...], skip_quiet_turns=2, timeout_seconds=100)` under seat 1;
  `set_seat` is not needed (`human_seats` lists 0 and 1 but seat 0 never comes on screen).
- **Mongolia t256 -- WAR with Portugal and Russia (declared in the t255 AI round)**: Portugal brought Zurich,
  Riga, Kiev and Jerusalem, Russia brought Sofia; all 8 caravans died at once (gpt 194 -> 21), Russia's
  Aluminum-for-open-borders and both OB deals ended, Artillery 712705 died. Both refuse peace ("business to
  settle" / "not the time"): `make_peace(5)` and `make_peace(7)` every turn. Karakorum (pop 40, str 153, 300 hp,
  MILITARY BASE bought t256) finishes the APOLLO PROGRAM t257; the Great Scientist born t256 bulbed SATELLITES;
  research Computers (-> Robotics, SS Booster). Space Procurements (t239) lets gold buy parts -- but we have NO
  Aluminum now (every part needs one: ask Babylon / China / the Shoshone, gpt only, lump gold needs a DoF).
  Rivals: Russia (SS Engine t251, Hubble, Great Firewall, Pentagon), China (3 capitals, Information Era), the
  Shoshone (Apollo t254, nukes, hostile words t256), Portugal (Apollo t242, **2 civs short of a Culture
  Victory**, World Ideology Order passed t255). Gold 5396 +21, happiness 18, culture 1299/2780.
- **Units / the ring** (t256): 7 Infantry (925712 56 hp (28,22), 983050 (28,23), 671753 (27,24), 966677 (28,25),
  974851 (29,25), 991232 (29,22), 1007638 (26,23)), Machine Guns 778248 (27,23) / 786437 (29,24), Artillery 802820
  set up in the city, AA gun 950291 (29,23), Marine 1155085 (26,24), Keshik 163847 (27,25), Khan. Russians in
  sight: Mech Infantry 3178524 (27,22; shot to 4 hp t256, Infantry 1007638 sent to finish it) and 3129400 (30,20),
  Mobile SAMs (26,22) (27,21) (28,21) (30,21), Cossacks (25,23) (26,27). Each turn: city strike + both MGs + the
  Artillery on the most damaged Mech Infantry, Infantry only to finish kills, everything else stays fortified.
  The Great Merchant's trade mission in Kiev's land (603 gold, +30) came the turn Kiev declared war.
- **Diplomacy**: at war with Portugal + Russia and their city-states (above). DoF Babylon (RA ends t259, renew
  t260; Babylon lost its capital t256 and denounced Russia); China OB-from-us for 1 gpt (t276), 5 Coal for Ivory
  (t275), friendly, keeps asking us into wars (declined t242, t253); England guarded (Ivory refused t252). The
  Shoshone hostile (Order, nukes). Congress t255: Order passed as World Ideology (we voted no), Protestantism
  failed; World Leader again t261 (Shoshone 18, Portugal 18, nobody near 34).


## Where the code is

- **main at c690dbf = tag `v1.12.0`** (2026-10-04): package 1.12.0, runtime v263, 145 tools (24 + `call` in
  `--tools compact`), `scripts/check.sh` green (1430 tests, 72 s). The release folds 37 entries since 1.11.0:
  a turn's closing orders and its end in one call (`finish_turn(actions=[...])`, a move's `revealed`), the call
  ledger's `client` label and the turn claim's `same_client`, refusals that say what to do instead
  (`did_you_mean` + `legal_missions`, the sleep/fortify equivalent, `skip_actions`, `_nothing_blocks` re-send,
  the engine's sentence on greyed buttons / purchases / peace / ranged attacks), runtime v254-v263. README has
  a new "A refusal says what to do instead" bullet; ROADMAP carries the release paragraph.
- **Not yet checked live** (this morning's three refusal fixes, 4e4c11e): `unit_mission` with a made-up
  mission name (`did_you_mean`), `MISSION_SLEEP` on a fortify-capable unit (`reason`), and an end refused with
  `NO_ENDTURN_BLOCKING_TYPE` over an empty todo (one re-send, `resent` on the reply). The session server has
  the code; the first call of the next game injects nothing new (runtime unchanged since v263).
- **Memory-rule reminders**: the ctx sandbox lacks XDG_RUNTIME_DIR, export `CIV5_TUNERD_SOCK=/run/user/1000/civ5-tuner.sock`
  before any `harness.cli` call there; `pkill -f` in a compound Bash call kills the shell; disband is denied
  to the auto-mode classifier.

## Still open

- Spectator page: no scrubber.
- Codex's second game (if any) should start from `single/Codex_as_Portugal.Civ5Save`; the Codex app's
  config.toml needs `CIV5_CALL_LOG` set or its rows never reach the ledger (set on 2026-10-03, keep it).
- The rest: `docs/GAPS.md`.
