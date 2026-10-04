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

**Read `gate` first.** Every status (`turn_status`, `wait_for_my_turn`, `finish_turn`) and every refusal
carries `gate`. `null` means you may act. Anything else means nothing works until it is cleared, and the
object says what and how: `name` and `why` describe it, `clear_with` is the one tool to call (with `args`
when it needs them, after `read_first` when a read shows the choices). Call `clear_with`; do not work the
situation out from the other flags, and do not read the board while a gate is up -- nothing has changed
since it went up. The gates, in the order they are enforced: `no_game`, `game_over`, `other_seat_active`
(not your turn), `hand_off_screen` (your own Continue screen, in hotseat), `processing`, `paused`,
`turn_not_active`, `leader_screen`, `discussion`, `tech_choice`, `decision_popup`, `announcement_screen`.
The first five and the last are cleared by `wait_for_my_turn`. Your own Continue screen is pressed for
you by whatever you call first (`hand_off_cleared: true` in that answer, and the turn is yours), so
`hand_off_screen` appears only when that press did not take. Announcement screens (a Great Person born, a
city-state met, a wonder, an era: nothing to decide) are closed the same way by whatever you call first,
reads included (`swept_popups` names them), so `announcement_screen` appears only when that close did not
take. The end-turn blocker is not a gate: it stops `end_turn`, not you, and `blocking_name` /
`blocking_hint` / `todo` say what clears it.

`turn_status.seat` is the player you are. In hotseat, a different `active_player` is the other player's
turn, not a reason to change seats. Only when your server's seat was guessed (`--seat auto`) and nobody
else plays the seat on screen, `set_seat(player_id)` moves it there (`set_seat()` re-detects). A server
started with `--seat N` refuses to move. Never take a seat another player is playing.

## The turn loop (every turn, in this order)

**Two agents, one hotseat game.** Each agent runs its own MCP server pinned to its seat (`--seat 0`,
`--seat 1`); both may sit in `finish_turn` at once, the inactive one waits while the active one plays.
Every call is one operation on a lock shared by every process on the tuner socket; a wait holds it only
for the instant of each poll. `another game operation is running` tells you only what the hand-off
screen would: another seat is acting (retry, or wait for your turn), or one of your own earlier calls
still runs (named, with its pid). A refusal that lasts a minute at game start is the first call
injecting the runtime. Keep your seat: a different `active_player` between turns is the other player's turn, not a
reason to `set_seat` onto it (a server started with `--seat N` refuses to). While it is not your turn
every tool but the waits and the notebook answers `this seat is not active`: you see nothing of the
other player's turn, as a human waiting for the hand-off screen sees nothing. Do not run
`scripts/mcp_call.py` for waits from a shell you will stop watching; a one-shot server keeps polling
until its timeout.

**Two clients, one seat.** The turn's first order claims the turn for that process (a file beside the
lock, per socket and seat). A refusal or `turn_status` carrying `turn_claim` means another client of
your own seat is playing this turn: its pid, how long it has held the turn and when the claim lapses are
in the answer. Read, wait, take notes; do not end the turn under it. The claim lapses 180 s after that
client's latest order, or at once when its process is gone; `force: true` on `end_turn`, `finish_turn`
or `do` takes it over (the other client crashed, or you are the one taking over on purpose). The claim
carries the holder's client label; `same_client: true` in the refusal means the holder carries yours --
an earlier session of your own agent, kept alive by your client after a context reset -- and `force: true`
is the right answer at once; without it, a different model on your seat is still playing. A
`skip_quiet_turns` run owns each turn it ends and stops, handing the turn back, if another client acts
on one first (`woke_because: ["other_client_holds_turn"]`).

1. `finish_turn` (it sends progress while it waits; the default timeout_seconds of 600 is verified safe in
   Claude Code, which moves a call past 120 s to a background task and reports its result; with a client
   that has a hard per-call limit, pass a smaller value). It ends your turn, blocks until you may act again, clears informational
   popups, and returns the new turn: `status` (as `turn_status`), `digest` (as `turn_digest`: combat,
   captures, growth, leader messages, notifications), `turn`, and `notes` (what you told `remember` since
   your last `finish_turn` or `briefing`; `notes_unshown` counts the older ones, `recall()` has them all and
   `notes="all"` brings the latest eight back). Read its result:
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
3. `briefing()` is the short way in: every decision of the turn with its tool, warnings, what changed
   since your last briefing (empire, cities, units, events), notable cities, damaged units, visible threats
   near your cities and units (compact rows; a threat your previous briefing listed is only marked `seen`
   unless it moved; `detail="full"` for whole rows), and the notes you wrote since your last briefing or
   `finish_turn`. After a context reset call `briefing(since="turn")`: it re-lists this turn's events, your
   civ's own rules and every recent note. `finish_turn(briefing=true)` hands each new turn
   back this way. For the full picture: `overview` (gold, science, culture, happiness, era, your player id),
   `units`, `cities`, and `known_world` for the map you can see. Prefer `known_world` and `revealed_map` over large `map_window`
   calls; keep `map_window` radius at 3 or below. For one unit's next step or attack, `tactical_view(unit_id)`
   answers in one read: neighbours by coordinate with move_unit's answer, attack previews, occupants and fog.
4. Give every unit an order and every city a production item. Read before you act:
   `todo_actions()` (the legal actions of every unit that still needs an order, and of every unit with a
   promotion waiting, in one call; `available_unit_actions(unit_id)` is the same for one unit with its
   targets and previews; `todo_actions(detail="summary")` is one short row per unit -- position, moves, hp,
   the non-everyday actions, targets in reach, worker plots -- about a fifth of the size, with `drill_down`
   naming the args for the full rows), `available_production(city_id)`, `available_research`,
   `available_policies`. Names are the game's own ids (`UNIT_WARRIOR`, `BUILDING_MONUMENT`, `TECH_POTTERY`,
   `POLICY_TRADITION`, `BUILD_FARM`, `MISSION_FORTIFY`). Those rows carry the id, the name and the live
   numbers (turns, cost, purchase price) -- not what the thing does. That is the rule book,
   `reference(section)`: `units`, `buildings`, `techs`, `policies`, `promotions`, `beliefs`, `resources`,
   `terrain`, `improvements`, `projects`, `processes`, `specialists`, `actions`, read once from this game's
   own database. Read the whole book at the start of a game if your context can hold it (it is long),
   otherwise the section a choice needs; it never changes mid-game, so never re-read it for the same
   question. It is also the MCP resource `civ5://reference` and works while it is not your turn.
   Torn between a few options? `compare` puts them side by side in one read: `kind="production"` with
   `city_id` and up to 8 item ids, `kind="research"` with tech ids, `kind="improvements"` with a worker's
   `unit_id` (and `plots` / `BUILD_` ids if you have some in mind; `sort="food"` etc.), `kind="trade"` with a
   caravan's `unit_id` (`sort="gold"` etc.). Rows keep engine numbers, table effects and estimates apart, and
   `assumptions` says what each estimate leaves out; `empire_change` is empty for a tile no city works, and a
   trade `hazard` of `none_visible` still has fog in it. You choose the objective.
5. `turn_status`: `blocking_name` names what still prevents ending the turn and `blocking_hint` names the
   tool that clears it (table below). Resolve it, call `turn_status` again, repeat until it is clear, or only
   `ENDTURN_BLOCKING_UNITS` remains for units you deliberately left idle (give them `MISSION_SKIP` or
   `MISSION_FORTIFY`).
6. `remember` what future-you must know: the plan (`tag: plan`; use `replace_id` to keep one living plan),
   threats, promises, why you did something. A replace returns `previous` (what it overwrote) and is refused
   when your tag differs from the note's stored tag: the id was probably wrong, so check `recall` before
   passing `retag: true`. `forget` removes a stale note. What a unit or city is *for* goes in an assignment
   instead: `assign(role, purpose, unit_ids, city_ids, target, done_when, review)`, e.g. an escort
   (`unit_ids: [archer, settler]`, `target: {x, y}`, `done_when: "city_at"`), an improvement
   (`done_when: {kind: "improvement", improvement: "FARM"}`), a diplomatic reminder (`target: {player}`,
   `review: {turn: N}`). `briefing` lists them with `state`: close `condition_met` ones with
   `close_assignment`; read each `needs_review` row's `reasons` and `amend_assignment` (an upgraded unit has
   a new id) or close it. Nothing is ever ordered or closed for you.
7. `finish_turn` exactly once (it quick-saves first by default). In hotseat and LAN games a second `end_turn`
   is refused with `turn_complete_sent`; that is not an error. Back to step 1.

### Letting quiet turns pass

`finish_turn(skip_quiet_turns=N)` keeps ending turns, up to N more, while nothing needs you: no unit
awaiting orders, no empty city, no promotion, no popup, no blocker, no expiring city-state ally, deal or declaration of friendship, and nothing
eventful in the digest (combat, losses, cities changing hands, wars, leaders talking, wonders, great people,
religion, espionage, congress, trade routes). `wake_on=["Machinery", "Askia"]` adds your own words, matched
against event kinds and notification text. Cities keep building their queues and research continues; the
harness never gives an order for you. The digests of the skipped turns are merged into the result, and
`turns_skipped` / `woke_because` say what happened. Use it the way a human presses End Turn a few times
while a wonder builds: with a plan in the notebook and units fortified or sleeping, not mid-war.

`status.alerts` is the exception to "quiet means todo is empty": it lists low happiness (2 or below, or an
unhappy tier) and every revealed strategic resource in deficit, on every status, without blocking anything.
A run wakes on it only when the figure worsens against the previous turn this process saw (`woke_because`
`happiness_drop:3->1`, `unhappy:unhappy`, `strategic_deficit:IRON:-2`); a steady happiness of 1 through a
five-turn Circus lets the run continue. The first status after a server start has no baseline and is never
a drop. Read the alert before swapping a build: on 2026-09-26 the Circus that held Mongolia at happiness 1
was the easy thing to swap away while the total sat on `overview`, a tool the loop never called.

`todo.ongoing` is the other exception: units the game is already moving -- on `AUTOMATE_EXPLORE` /
`AUTOMATE_BUILD`, or walking a `move_unit` order that needs more turns (`going_to: {x, y}`, also on
`units()`) -- with their plot, moves and hp. They are yours but not decisions: they never block end-turn and
a run does not wake for an explorer merely exploring. Each row's `attention` lists what would pull a human
back -- a visible barbarian camp on or beside the unit, a visible hostile combat unit beside it, a
destination no longer revealed or passable -- and any of those wakes the run (`woke_because`
`ongoing:<id>:camp`). Only plots you can see are read. A new `move_unit` / `unit_mission` takes an
automated unit back; a standing move is replaced by any new order. On 2026-09-26 (Mongolia, t42) the
auto-explore scout drifting toward a camp was on no list at all.

## Many orders, one call

`do(actions=[{"tool": "unit_mission", "args": {"unit_id": 7, "mission": "MISSION_FORTIFY"}}, ...])` runs a
list of orders in sequence and returns each one's result. It stops at the first refusal and lists the rest
under `skipped`: re-read the state before re-issuing those, since what you reasoned about may have changed.
Reads first, then one batch of orders, is a normal turn. Waiting, loading, `end_turn` and `finish_turn`
never go inside a batch.

The orders that close a turn go in `finish_turn(actions=[...])` with it: they run exactly as `do` would, and
the turn ends only when every one was ok. The reply carries `batch` (the same `results` / `skipped` as `do`)
either way -- with the new turn on success, with the current `status` and `ended: false` on a refusal, so
nothing is ended on a board you misread. A turn that needs no look is then one call. A turn that needs one
first (move the scout, see what is there, then decide) is two: `do` or `move_unit` for the look, then
`finish_turn(actions)` for the rest. A move's result carries `revealed` -- the plots the move uncovered (as
map_window describes them) and the foreign units or cities that came from fog into sight; `count: 0` says
nothing new -- so the look needs no `tactical_view` or `units` after it.

A unit that still has movement after its order keeps the turn open: a one-plot move with two moves, a ranged
attack, a worker sent to the next tile. The engine refuses the end (`ENDTURN_BLOCKING_UNITS`) and the refusal
costs a round trip. Give every unit you touched a closing order in the same batch -- a longer move, `MISSION_FORTIFY`,
`MISSION_SLEEP` or `MISSION_SKIP` -- or, when the refusal comes anyway, pass its `end_turn.skip_actions`
(the MISSION_SKIP orders for exactly those units) as the next `finish_turn(actions=...)`.

A client that cannot afford every tool's description on each request starts the server with `--tools compact`
(env `CIV5_TOOLS=compact`): it then lists the core set only -- the loop, the reads, `do`, `give_order`, the
notebook, the commonest orders -- plus `call(tool, args)`, which runs any other tool by name and returns its
answer unchanged. `call()` lists every tool with one line each, `call(tool, describe=true)` is one tool's full
description. Batches reach every tool in either mode, and so does a `gate.clear_with` or `todo_actions` name
sent as itself.

Any action may carry an extra `action_id` (any string you choose, e.g. `"t42-move-7"`). Calling the same
tool again with the same `action_id` returns the earlier result with `replayed: true` and runs nothing:
use one whenever you retry after a transport error or timeout, so a unit never moves twice.

## Verify, do not assume

Every action tool returns the state it could read back. Check it before moving on:

- `move_unit` returns the unit's new `x`, `y`, `moves`. If they did not change, the path was blocked or the
  unit had no moves; do not re-issue blindly. Read `tactical_view(unit_id)`: each neighbour's `move` says
  whether `move_unit` would refuse it and why.
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

`blocking_stale: true` means the engine froze its blocker while a popup was up and the todo no longer
shows it: `ENDTURN_BLOCKING_UNITS` with no unit needing orders, `ENDTURN_BLOCKING_PRODUCTION` with no empty
city, `ENDTURN_BLOCKING_RESEARCH` with research set; `end_turn` sweeps the popup, lets the engine re-evaluate
and sends once more.

## Leader screens and diplomacy

- When `discussion_pending` is true, `discussion()` gives the leader, their speech, the response `buttons`
  and, on a trade screen, the deal. Answer with exactly one of `respond_discussion(button_id)`,
  `accept_deal`, `refuse_deal`, or `dismiss_discussion` (only when there are no buttons and no deal). The
  gate says which: `clear_with: accept_deal` when a deal is on the table, `respond_discussion` when there
  are buttons. Several leaders can be queued at one turn start (three at once has happened): the answer to
  one then carries `still_pending: true`, `next` (the next leader's screen, words, buttons, the deal) and
  the gate it raises, so answer that one next; no need to read `discussion()` again. Then `wait_for_my_turn`
  (or carry on with the turn if it was already yours). Nothing else works while a leader screen is open.
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
