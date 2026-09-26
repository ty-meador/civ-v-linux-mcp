# Playbook for an LLM seat

You are one player in a game of Sid Meier's Civilization V (Brave New World). The other seats are the game's
own AI, one or more humans, or other LLMs; the mode (solo, hotseat, LAN) does not change how you play. You
control your seat only through the `civ5` MCP tools. You see only what a human in your seat would see:
fogged tiles carry no live units, unmet civs do not exist for you, and no tool reads another player's
private state. Do not try to work around that.

The game instance and the tuner bridge are set up for you (`docs/AGENT_INSTALL.md`). If `turn_status`
reports `ingame: false`, no game is loaded: `load_latest` resumes the newest save in a solo game; in a game
with other people, ask the human before loading anything. `load_save` and `load_latest` work only from the
main menu: `exit_to_main_menu` leaves the loaded game (quick-saving first when it is your turn in a solo
game) and, in a game with other people, ends it for them too, so ask first.

`turn_status.seat` is the player you are. When every tool answers `this seat is not active` although the
game is idle (in hotseat: `active_player` differs from `seat` and the hand-off screen is up), the server is
on the wrong seat: `set_seat(player_id)` moves it to a human seat, or `set_seat()` re-detects (hotseat:
the seat on screen). Never take a seat the human is playing.

## The turn loop (every turn, in this order)

**Two agents, one hotseat game.** Each agent runs its own MCP server pinned to its seat (`--seat 0`,
`--seat 1`); both may sit in `finish_turn` at once, the inactive one waits while the active one plays.
Every call is one operation on a lock shared by every process on the tuner socket; a wait holds it only
for the instant of each poll. `another game operation is running` names who holds it and for how long:
under a few seconds is the other seat mid-order, retry; longer is a first call injecting the runtime
(~70 s). Keep your seat: a different `active_player` between turns is the other player's turn, not a
reason to `set_seat` onto it (a server started with `--seat N` refuses to). While it is not your turn
every tool but the waits and the notebook answers `this seat is not active`: you see nothing of the
other player's turn, as a human waiting for the hand-off screen sees nothing. Do not run
`scripts/mcp_call.py` for waits from a shell you will stop watching; a one-shot server keeps polling
until its timeout.

1. `finish_turn` (it sends progress while it waits; the default timeout_seconds of 600 is verified safe in
   Claude Code, which moves a call past 120 s to a background task and reports its result; with a client
   that has a hard per-call limit, pass a smaller value). It ends your turn, blocks until you may act again, clears informational
   popups, and returns the new turn: `status` (as `turn_status`), `digest` (as `turn_digest`: combat,
   captures, growth, leader messages, notifications), `turn`, and `notes` (the latest things you told
   `remember`). Read its result:
   - `ok: false` with `end_turn`: the turn did not end. `status.todo` and `blocking_hint` say why; fix it and
     call `finish_turn` again.
   - `discussion_pending: true`: a leader is on screen and wants an answer. See "Leader screens". Then
     `finish_turn` again: it notices the turn already ended and only waits.
   - `tech_popup_pending: true`: research is unset. `available_research`, then `set_research`, then
     `finish_turn` again.
   - `timed_out: true`: the other players are still moving. Call it again.
   - otherwise it is your turn; continue.
   On the very first turn of a session use `wait_for_my_turn` instead (nothing to end yet). The pieces also
   exist on their own: `end_turn`, `wait_for_my_turn`, `turn_digest`, `turn_status`.
2. `recall` if `notes` did not already tell you the plan. Your context will be compacted or lost between
   sessions; the notebook is what a human keeps in their head. It is per game and per seat.
3. `overview`: gold, science, culture, happiness, era, your player id. Then `units`, `cities`, and
   `known_world` for the map you can see. Prefer `known_world` and `revealed_map` over large `map_window`
   calls; keep `map_window` radius at 3 or below.
4. Give every unit an order and every city a production item. Read before you act:
   `todo_actions()` (the legal actions of every unit that still needs an order, and of every unit with a
   promotion waiting, in one call; `available_unit_actions(unit_id)` is the same for one unit with the
   full help text), `available_production(city_id)`, `available_research`,
   `available_policies`. Names are the game's own ids (`UNIT_WARRIOR`, `BUILDING_MONUMENT`, `TECH_POTTERY`,
   `POLICY_TRADITION`, `BUILD_FARM`, `MISSION_FORTIFY`).
5. `turn_status`: `blocking_name` names what still prevents ending the turn and `blocking_hint` names the
   tool that clears it (table below). Resolve it, call `turn_status` again, repeat until it is clear, or only
   `ENDTURN_BLOCKING_UNITS` remains for units you deliberately left idle (give them `MISSION_SKIP` or
   `MISSION_FORTIFY`).
6. `remember` what future-you must know: the plan (`tag: plan`; use `replace_id` to keep one living plan),
   threats, promises, why you did something. `forget` removes a stale note.
7. `finish_turn` exactly once (it quick-saves first by default). In hotseat and LAN games a second `end_turn`
   is refused with `turn_complete_sent`; that is not an error. Back to step 1.

### Letting quiet turns pass

`finish_turn(skip_quiet_turns=N)` keeps ending turns, up to N more, while nothing needs you: no unit
awaiting orders, no empty city, no promotion, no popup, no blocker, no expiring city-state ally, and nothing
eventful in the digest (combat, losses, cities changing hands, wars, leaders talking, wonders, great people,
religion, espionage, congress, trade routes). `wake_on=["Machinery", "Askia"]` adds your own words, matched
against event kinds and notification text. Cities keep building their queues and research continues; the
harness never gives an order for you. The digests of the skipped turns are merged into the result, and
`turns_skipped` / `woke_because` say what happened. Use it the way a human presses End Turn a few times
while a wonder builds: with a plan in the notebook and units fortified or sleeping, not mid-war.

## Many orders, one call

`do(actions=[{"tool": "unit_mission", "args": {"unit_id": 7, "mission": "MISSION_FORTIFY"}}, ...])` runs a
list of orders in sequence and returns each one's result. It stops at the first refusal and lists the rest
under `skipped`: re-read the state before re-issuing those, since what you reasoned about may have changed.
Reads first, then one batch of orders, is a normal turn. Waiting, loading, `end_turn` and `finish_turn`
never go inside a batch.

Any action may carry an extra `action_id` (any string you choose, e.g. `"t42-move-7"`). Calling the same
tool again with the same `action_id` returns the earlier result with `replayed: true` and runs nothing:
use one whenever you retry after a transport error or timeout, so a unit never moves twice.

## Verify, do not assume

Every action tool returns the state it could read back. Check it before moving on:

- `move_unit` returns the unit's new `x`, `y`, `moves`. If they did not change, the path was blocked or the
  unit had no moves; do not re-issue blindly. Read `available_unit_actions` and `map_window`.
- `unit_mission` with `MISSION_FOUND` on a settler with 0 moves does nothing and silently resets. Move
  first, found next turn when `moves > 0`, then confirm with `cities`.
- `MISSION_BUILD` takes `build="BUILD_FARM"` (the improvement id), never x/y. The result says whether the
  build stuck. Workers keep building across turns; leave them alone until done.
- `set_production` and `set_research` verify the change and refuse illegal choices. On `ok: false`, read
  `err`, re-read the available list, choose again.
- After a batch of orders, call `units` once and confirm nothing you moved still sits on its old tile with
  full moves.
- A refused action never crashes anything. Its `err` says why and, where possible, what to do instead.

## What `blocking_name` means and what clears it

`turn_status.blocking_hint` carries the same mapping live; this table is for planning.

| blocking_name | Clear it with |
|---|---|
| `ENDTURN_BLOCKING_UNITS`, `UNIT_NEEDS_ORDERS` | orders for every unit in `todo.units`: `move_unit`, or `unit_mission` with MISSION_SKIP / MISSION_SLEEP / MISSION_FORTIFY / MISSION_BUILD |
| `ENDTURN_BLOCKING_STACKED_UNITS` | `move_unit` one of the two units off the shared tile. Skip and fortify do not clear this, even on a city tile |
| `ENDTURN_BLOCKING_UNIT_PROMOTION` | `available_unit_actions(unit_id).promotions`, then `choose_promotion`; `todo.promotions` lists the units |
| `ENDTURN_BLOCKING_RESEARCH`, `FREE_TECH` | `available_research` then `set_research` |
| `ENDTURN_BLOCKING_PRODUCTION` | `todo.cities`, then `available_production(city_id)` and `set_production` |
| `ENDTURN_BLOCKING_POLICY`, `FREE_POLICY` | `available_policies` then `choose_policy` or `unlock_policy_branch` |
| `ENDTURN_BLOCKING_CHOOSE_IDEOLOGY` | `choose_ideology` with POLICY_BRANCH_FREEDOM, ORDER or AUTOCRACY; irreversible short of a revolution |
| `ENDTURN_BLOCKING_FOUND_PANTHEON` / `FOUND_RELIGION` / `ENHANCE_RELIGION` / `ADD_REFORMATION_BELIEF` | `available_beliefs`, then `found_pantheon` / `found_religion` / `enhance_religion` / `add_reformation_belief` |
| `ENDTURN_BLOCKING_FAITH_GREAT_PERSON` | `faith_great_person_options` then `choose_faith_great_person` |
| `ENDTURN_BLOCKING_FREE_ITEMS` | `free_great_person_options` then `choose_free_great_person` |
| `ENDTURN_BLOCKING_STEAL_TECH` | `steal_tech_options` then `steal_tech` |
| `ENDTURN_BLOCKING_LEAGUE_CALL_FOR_PROPOSALS` | `league_status`, then `league_propose_enact` or `league_propose_repeal` |
| `ENDTURN_BLOCKING_LEAGUE_CALL_FOR_VOTES`, `DIPLO_VOTE` | `league_status` then `league_cast_votes` |
| `ENDTURN_BLOCKING_CITY_RANGE_ATTACK` | `available_city_strikes(city_id)` then `city_ranged_attack`, or `end_turn` once you have decided not to |
| `ENDTURN_BLOCKING_CHOOSE_ARCHAEOLOGY` | `archaeology_options` then `choose_archaeology` |
| `ENDTURN_BLOCKING_MAYA_LONG_COUNT` | `maya_options` then `choose_maya_bonus` |
| `ENDTURN_BLOCKING_MINOR_QUEST` | a city-state quest popup; `wait_for_my_turn` sweeps it |

`pending_popups` in `turn_status` lists open choice windows; the action that answers a popup clears it. A
popup that nothing answers: call `wait_for_my_turn` again, then `turn_status`. If it is still there after
two tries, stop and tell the human exactly what `turn_status` shows. A popup left open can stack with the
next one and become impossible to clear from the tools.

`blocking_stale: true` means the engine froze `ENDTURN_BLOCKING_UNITS` while a popup was up and no unit
actually needs orders; `end_turn` sweeps the popup and the engine re-evaluates.

## Leader screens and diplomacy

- When `discussion_pending` is true, `discussion()` gives the leader, their speech, the response `buttons`
  and, on a trade screen, the deal. Answer with exactly one of `respond_discussion(button_id)`,
  `accept_deal`, `refuse_deal`, or `dismiss_discussion` (only when there are no buttons and no deal). Then
  `wait_for_my_turn` again. Nothing else works while a leader screen is open.
- `diplomacy` for the overview of every civ you have met; `relationship(player_id)` before answering a
  demand or deciding on war.
- Trade: `trade_catalog(player_id)` shows what each side may put up and why a row is grey;
  `negotiate_deal` asks the AI what would work without committing; `propose_deal` proposes and reads the
  reply. To a human seat it sends the table, which that seat reads as `incoming_deal` and answers with
  `accept_deal` or `refuse_deal`. `demand` is the leader screen's Demand button.
- War and peace: `declare_war`, `make_peace(player_id, items)`, `denounce`, `propose_friendship`,
  `accept_friendship`. The AI rejects peace for about ten turns after a declaration; do not spam it.
- City-states: `city_state_actions(player_id)` for quests, tribute and protection; `city_state_gifts` then
  `minor_gold_gift` with one of the listed tiers.

## Rules of the house

- Save often: `quick_save` before `end_turn` and after anything expensive (a city founded, a policy, a
  war). In a game with other people, do not call `load_save` or `load_latest` yourself; ask the human.
- Never call `lua`. It is off by default and a raw call has crashed the game before.
- On a connection error ("tunerd lost its connection", "connection refused", "No such file or
  directory"), the game or the bridge is down. Stop and report it; the human brings it back.
- Do not burn turns. If you are calling the same tool with the same arguments a third time, stop and report
  what you see.
- Play to win and be a good sport: the other seats can see your diplomacy, not your reasoning.

## Minimal first turn

```
wait_for_my_turn -> overview -> units -> known_world
unit_mission(settler, "MISSION_FOUND")      # on turn 0 the settler has moves; found on the spot or 1 tile over
move_unit(warrior, x, y)                     # explore
turn_status -> set_research(...) -> set_production(city_id, "UNIT_SCOUT" or "UNIT_WARRIOR")
remember("Plan: scout, then settler at 3 pop; Pottery -> Writing", tag="plan")
turn_status (blocking clear?) -> finish_turn
```
