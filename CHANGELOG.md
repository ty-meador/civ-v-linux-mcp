# Changelog

Two counters, on purpose (GitLab #26):

- **Package version** (`pyproject.toml`, git tag `vX.Y.Z`) follows the milestones in `docs/ROADMAP.md`:
  0.2.0 information boundary, 0.3.0 trade table, 0.4.0 screens before the decision, 0.5.0 live
  verification, 1.0.0 release.
- **`RUNTIME_VERSION`** (`harness/lua/runtime.lua`, read back by `harness/game.py`) counts injections of
  the Lua runtime. It goes up whenever `runtime.lua` changes, because the game keeps the old `H` table
  alive until a newer number arrives; a stale MCP server re-injects the version it started with.
  Commit subjects carry it as `runtime vNNN`, so `git log --grep 'runtime v'` is the full map.

Dates are the day the change was committed; "live tNNN" is the game turn it was checked on.

## Unreleased

- **Conditional unit orders and runtime v226 (#32).** `give_order(unit_id, steps, interrupt, purpose,
  replace_id, start)` (and `POST /give_order`) stores a short sequence for one unit -- `move` (x, y), `build`
  (on the plot the move ends on), `heal` (to a percent), `hold` (fortify / sleep / alert) -- on the seat's
  notebook, runs it at once and then at the start of each of the seat's turns, one step at a time through the
  ordinary `move_unit` / `unit_mission` path, each step at most once per turn. Before every step it re-reads the
  unit (`H.order_facts`: fingerprint, moves, activity, build in progress, every visible hostile within the
  radius, the destination's `move_refusal` and whether an enemy stands on it, whether the build's plot already
  has it and whether the unit could start it) and pauses -- unit back in the model's hands with `pause.reason`
  and `hint`, and its standing move dropped -- on a newly visible hostile within `interrupt.hostile_within`
  (default 2), damage, `hp_below`, an enemy on the destination (an order never attacks), an illegal
  destination, a refused step, a build plot the unit is not on, no progress for a turn, a loaded save, a step
  whose answer the harness never saw (written ahead as `inflight`, never replayed blind), or a direct
  `move_unit` / `unit_mission` to that unit (`order_paused` on that answer). A lost or reused unit fails the
  order. One open order per unit; `H.resume_moves(pid, skip)` leaves units an order owns to the order, which
  runs after it in the turn-start window, under the seat's turn claim (#41). `orders`, `resume_order`
  (acknowledges what paused it and re-checks every step) and `cancel_order` complete the set; `status.orders`,
  a `finish_turn` wake reason `order:<id>:<status>`, the briefing's `orders` section and `order` on todo and
  decision rows show them. Hotseat seats never see each other's orders (per-seat notebook, per-seat window).

## 1.4.0 -- plans that survive a context reset (2026-09-27)

Milestone 1.4.0 (#33, #34): structured assignments on the notebook and compact comparisons. Tag `v1.4.0` =
runtime v225. The two were used together on one live hotseat turn (2026-09-27, Venice/Mongolia t42, seat 0):
`compare(kind="improvements")` on Worker 49155 sorted by production put the Cow pasture at (69,36) first (the
only row with an `empire_change`, the tile being worked); `assign` gave the worker that job with `done_when`
improvement PASTURE; `briefing(since="turn")` listed it `on_track` with the worker and target plot;
`compare(kind="production")` gave Worker 2 turns / 220 gold, Library 10 turns / +2.5 science, Granary 8 turns
/ +3 food. The test assignment was closed as cancelled; no unit was ordered. 931 tests.

- **Compact comparisons and runtime v225 (#34).** `compare(kind, city_id, unit_id, candidates, plots, sort,
  limit, detail)` (and `GET /compare`) puts a few caller-chosen candidates side by side from one read, with
  `context` (seat, turn, city or unit), `sources` (the getter or table behind each field) and `assumptions`
  (behind each estimate). `production`: up to 8 items in one city with `can_produce` or `why` not (a missing
  tech or building in the city, a resource short, already built, a wonder taken, the civ's own replacement,
  Venice's no-founding trait; `why_unknown` when no rule was found), cost, stored, turns, gold/faith price only
  where the buy button exists with `*_can_buy` and `*_short`, table `effects`, `conditional` per-tile yields
  counted over the city's tiles, `estimated_change` of the city's yields, maintenance (a unit's is "unknown":
  upkeep is empire-wide), `unique_replaces`; a Venice puppet is `purchase_only`, anyone else's refused.
  `research`: status, cost, progress, turns, `missing_prereqs` with `path_beakers` / `path_turns_estimate`,
  unlocks. `improvements`: per plot and build the tile's yields now and after, `empire_change` only while a city
  works the tile, removed feature and chop production, a luxury or strategic `connects`, maintenance, `why` a
  named build is refused; fogged plots are not read. `trade`: the chooser's yields per destination with
  distance and `hazard` (visible hostiles and camps near each end, the not-visible plot count, `danger` never
  "safe"). `limit` cuts rows and `omitted` carries the arguments for the rest. `purchase_cost` no longer calls
  an item with no buy button a gold shortfall (Venice's Settler read "not enough gold (189 of 370)"). Live
  Venice t42, S5 t215 and S1 t266: see `docs/NOTES.md`. 931 tests.
- **Structured assignments and runtime v224 (#33).** `assign(role, purpose, unit_ids, city_ids, target,
  done_when, review, replace_id)`, `assignments(status)`, `amend_assignment`, `close_assignment` (and `POST
  /assign`, `GET /assignments`, `POST /amend_assignment`, `POST /close_assignment`) keep what each unit or
  city is for in the seat's notebook file, beside the prose notes. Units and cities are fingerprinted (type
  and creation turn; name, plot and founding turn), so a reused id reads as the assigned one gone. Targets are
  a plot, a foreign unit or a player. `done_when` is manual, unit_at, city_at, improvement, building or tech.
  `review` is a turn, a hostile within N plots, or hp below a percentage. Every read reconciles against one
  fog-safe `H.assignment_facts` read into `condition_met` (with `evidence`), `needs_review` (with `reasons`:
  unit missing with an upgrade on its last plot named, id reused, city lost, target plot owner changed,
  improvement pillaged, a city within `MIN_CITY_RANGE` of a site, a target unit not where last seen, war or
  elimination, review turn, hostile, low hp) or `on_track`; out-of-sight targets are `stale` / `unknown` with
  the last sighting. `replace_id` closes the old one as `replaced`, so the two never compete. The briefing adds an
  `assignments` section (needing-a-look first, capped at `limit`) and tags an assigned unit's decision row.
  `close_assignment` works off-turn. Live Venice t42 (read-only): see `docs/NOTES.md`. 913 tests.

## 1.3.0 -- compact briefing and tactical view (2026-09-26)

Milestone 1.3.0 (#35, #30, #31): the compact read levels, the one-call turn briefing and the one-unit tactical
view, plus the v223 grid fix found while checking them together. Tag `v1.3.0` = runtime v223. The three reads
were used together on one live hotseat turn (2026-09-26, Venice/Mongolia t42, seat 0): `briefing` gave one
decision (Warrior 40962) with `todo_actions(detail='summary')` as its tool and three barbarian threats with
distance-only assessments; the summary row came back at 1 unit; `tactical_view` on that Warrior and on the
wounded Warrior 16385 beside the barbarian camp showed the coast refusals (needs Optics), the camp's
barbarian as `enemy` with "no moves left", and the three threats as occupants. Seat 1 on the same turn got
only the `other_seat_active` gate. 886 tests.

- **Runtime v223: the tactical grid stops at `radius`.** The grid is a (2r+1)-square box, but hex distance
  makes its corners farther than `radius`; they were drawn from the live map although `occupants` and `fog`
  never counted them, so a hostile could appear as `X` with no occupant row (live Venice t42: (73,41), three
  steps from a Warrior, drawn `__` while `fog.unrevealed` was 0). Cells beyond `radius` are now blank like
  off-map ones and the legend says so. Live t42 after the change: the radius-2 grid has 19 drawn cells = 18
  visible + 1 fogged, radius 3 has 37 = 27 + 9 + 1. 886 tests.

- **`tactical_view` and runtime v222: one unit's surroundings in one read (#31).** A new read (and
  `GET /tactical_view`) around one unit: the six `neighbors` by direction and coordinate from the engine's
  `Map.PlotDirection` (so the wrap seam and the edge rows are the engine's answer; an edge neighbour is
  `off_map`), each with terrain, remembered feature under fog, `river_crossing`, last-seen or live owner,
  visible units and `move`: `attack` (a melee target; its preview is in `targets`), `open` (move_unit would
  send the order: no cost or turns, which the engine cannot give safely), `refused` with `why`, or `enemy`
  with why it is not an attack. `refused` is move_unit's own pre-send checks, moved into `H.move_refusal` and
  shared (fog-safe for the view: a fogged plot's owner is the last-seen one and a city founded in the fog is
  not named). `targets` are `H.melee_targets` / `H.ranged_targets` rows, the same previews
  `available_unit_actions` gives (modifier rows only with `detail="full"`). `occupants` (visible units, hostile
  first, with range for a ranged one) and `cities` (a fogged one is `last_seen`, without hp) cover `radius`
  (1-5, default 2); `fog` counts visible, fogged and unrevealed plots and `unseen_within_2`; `grid` is the
  area as two-letter cells with a `legend`, and `players` names every owner id. `detail="full"` adds every
  revealed plot as `map_window` reads it. Live Venice t42 (80 x 52, wraps): 2,434 PlotDirection neighbours all
  at distance 1 including the seam and edge rows; the river-edge mapping agrees with `IsRiver()` on all 4,160
  plots; for all five units the neighbours agree with `map_window` and the targets and previews with
  `available_unit_actions`; the Scout's water neighbour gave the same refusal text as `move_unit`. 2.1-2.8 KB a
  unit, one call where `map_window` + `available_unit_actions` were two of about the same size. 885 tests.

- **`briefing` and runtime v221: the turn in one compact read (#30).** A new tool (and `GET /briefing`, and
  `finish_turn(briefing=true)`, which returns it in place of `status` and `digest`) answers with the seat,
  turn and gate; a `baseline` saying what it compares against (the seat's previous briefing, kept beside the
  notebook; `comparable=false` with the reason on a first read or after a reload to an earlier turn);
  `decisions` (every unit to order, promotion, empty city, research, incoming deal, stolen tech, popup, and the
  blocker when it is none of those; never cut, one `tools` entry per kind); `warnings` (status alerts,
  expiring deals, friendships and city-state allies, non-blocking stacked tiles); `opportunities` (idle
  caravans and spies, free trade slots); `changes` (empire totals, city pop and production, units new and
  gone, events by kind with the consequential ones listed); the empire totals; notable cities only; units by
  type with damaged and attention rows; visible `threats` (hostile combat units within 4 plots of a city or 2
  of a unit, with a distance-only `assessment`) and nearby barbarian camps; the leader trait text when there is
  no comparable baseline or with since="turn"; and the latest notes. Every list but `decisions` stops at
  `limit` with `omitted` and the tool that shows the rest. Events are read from the runtime's log with the
  briefing's own cursor (`H.briefing_board`), so the briefing and the digest never take events from each
  other. Behind a gate only the gate is returned. Live 2026-09-26: Venice t42 3.4 KB / 9 trips vs the six-call
  recovery's 7.2 KB / 15 trips; S1 t266 2.5 KB vs 29.9 KB; S1 t266 -> t267 through `finish_turn(briefing=true)`
  showed Goshute's finished Walls as a new decision. Details and the table in `docs/NOTES.md`.

- **`todo_actions(detail, limit)` and runtime v220: compact rows with drill-down (#35).** `detail` is
  `summary`, `normal` (the default, unchanged) or `full` (what `full=true` gave). All three are cut in
  `Game.todo_actions` from the same single Lua read, so the tuner cost and the facts do not change with the
  level. A summary row: id, type, x, y, moves, hp / max_hp when damaged, `promotion_ready`, `actions` as bare
  type strings without the everyday orders (listed once in `routine_actions`, counted per unit in
  `routine`), `promotions` (enums), `attack` / `ranged` targets (x, y, unit or city, owner, hp; previews stay
  in normal) and `build_plots` (x, y, builds, resource); `drill_down` names the exact args for the normal
  rows. `limit=N` returns the first N units in todo order and lists the rest in `omitted` (count, ids, args).
  Every reply now carries `detail`, `n` and `returned`; an unknown level, `full=true` with another level, or
  `limit < 1` is refused before any game call. v220 puts `hp` / `max_hp` on a damaged unit's row at every
  level. Live 2026-09-26: S1 t266, all 38 units, 5.7 KB summary vs 26.6 KB normal and 29.1 KB full at 3 trips
  each; Venice t42 hotseat 1.3 vs 3.8 KB. `scripts/measure_reads.py` records bytes, rows, trips and seconds
  per read (the baseline table is in `docs/NOTES.md`). MCP and HTTP (`/todo_actions?detail=&limit=`).

## 1.2.0 -- turn status tells the whole turn (2026-09-26)

The five fixes from the 2026-09-26 hotseat play review (milestone 1.2.0: #37-#41), plus the `gate`, the
rule book, `todo_actions` and the one-query screen reads that landed after 1.1.0. Tag `v1.2.0` = runtime
v219. The new status fields were read together on one live hotseat turn (2026-09-26, Venice/Mongolia t42:
seat 0 on its own turn with `gate: null`, `alerts: []`, `happiness: 8` and a standing-move Warrior in
`todo.ongoing`; seat 1 off-turn with the `other_seat_active` gate and a `happiness` alert at 1); each row
below says where it was checked. 840 tests.

- **Runtime v219: `expiring_deals` and `expiring_friendships` (#38).** City-state alliances already warned
  before they lapsed; deals and declarations of friendship with majors did not (2026-09-26, Mongolia
  t21-42: two embassy-for-gold deals lapsed and the seat learned it from the "expired" notice afterwards;
  a DoF with Catherine had no remaining-turns line on the turn it reads). On this seat's own turn,
  `turn_status` now carries `expiring_deals` -- current deals with `turns_left` <= 3, `{player_id, civ,
  turns_left, ends_on, items}`, items as short "we give / they give" lines -- and
  `expiring_friendships` -- DoFs with met majors ending within 5 turns (`DOF_EXPIRATION_TIME -
  GetDoFCounter`), with `ask_too_soon` when `IsDoFMessageTooSoon` would grey out the renewal. Either one
  wakes `finish_turn(skip_quiet_turns)`. The deal snapshot uses `current_deals`, so it is skipped (field
  left off) whenever the scratch trade table holds items or another seat's proposal is waiting: an offer
  or draft is never cleared or loaded. Unmet civs are not named. `relationship` now reports
  `dof_turns_left` too. Checked live 2026-09-26 on the t42 hotseat (helpers run inline, the v218 runtime left
  in place): seat 1 (Mongolia) listed the Portugal embassy-for-1-gpt deal ending t43 (`turns_left` 1, as
  `current_deals` says) and the Russia DoF at 38 turns (as `war_consequences`); seat 0 listed none of
  seat 1's; the scratch table was empty before and after.

- **Runtime v218: `todo.ongoing` and `going_to` (#37).** A unit the game is already moving used to vanish
  from the turn: `todo` listed a unit only when it needed orders or its standing move had stalled, and
  neither `units()` nor the next status repeated where a queued `move_unit` was taking it (2026-09-26,
  Mongolia t42: the auto-explore scout drifting toward a camp near x=16 was on no list; earlier, Arabia's
  0-move `queued: true` order was never restated). `turn_status.todo.ongoing` now lists every automated
  unit and every unit walking a standing move: `{id, type, x, y, moves, hp, automated, mission_name,
  going_to: {x, y}, attention, note}`. `going_to` is also on `units()` rows and on the `queued: true`
  reply of `move_unit`. These rows never set a blocker and never wake `finish_turn(skip_quiet_turns)` on
  their own; a row's `attention` does (`woke_because` `ongoing:<id>:camp` / `hostile` /
  `destination_unrevealed` / `destination_impassable` / `destination_gone`): a visible barbarian camp on
  or beside the unit, a visible hostile combat unit beside it, or a destination the seat can no longer
  path to. Only plots this seat can see are read; a fogged neighbour is unknown here as on the map. A
  stalled standing move stays in `todo.units` with its re-issue note (now with `going_to`). Orders go
  out as manual missions, which clear the automate type, so a new `move_unit` / `unit_mission` takes an
  automated unit back and no cancel tool was added. Also fixed: a refused `move_unit` cleared the standing
  record under the pre-hotseat key (bare unit id), so the refused destination survived to `going_to` and
  the next turn's resume; it now clears `H.pm_key(unit, seat)`. `H.going_to`, `H.ongoing_attention`;
  tests/test_ongoing_units.py. Checked live 2026-09-26 (hotseat quicksave, t42, seat 0): a Warrior
  ordered at 0 moves came back `queued: true, going_to: {72,36}` and the next status listed it under
  `ongoing` with `attention` = the camp at (74,33) and the 10 hp Barbarian Warrior on it; a Worker
  mid-path carried `going_to` on `units()` and no attention; seat 1's auto-explore Scout at (16,19)
  read `automated` with no attention (nearest revealed camp 3 plots off, fogged). `AUTOMATE_EXPLORE`
  was refused as not legal for seat 0's units (the engine's `CanAutomate`; seat 1's Scout and Spearman
  answered true), an engine rule, not a harness one.

- **Runtime v217: `turn_status.alerts` (#39).** Every status now carries `alerts`, a short list of facts about
  the seat's own empire that `overview` already showed and the loop never read: `{kind: "happiness",
  happiness, unhappy}` when the total is 2 or below or an unhappy tier is set, and `{kind:
  "strategic_deficit", resource, available, deficit, total, used}` for each revealed strategic resource
  with a negative `available` (an unrevealed one stays unknown, as on the top bar). The bare `happiness`
  total and `unhappy` tier ride on every status too. Alerts never add a `blocking_name` and never enter
  `todo`; the figures come from the same reads as `overview` (`H.status_alerts` shares `H.unhappy_tier`
  and `H.strategic_resources`) in the same trip as the rest of the status. `finish_turn(skip_quiet_turns)`
  wakes on an alert only when it worsens against the previous turn this process saw -- `happiness_drop:3->1`,
  `unhappy:unhappy`, `strategic_deficit:IRON:-2` in `woke_because` -- so a steady happiness of 1 through a
  five-turn Circus lets the run continue; the first status after a server start has no baseline and is
  never a drop, and a turn number going backwards (a reloaded save) clears the baseline. Motivated by
  2026-09-26 (Mongolia, seat 1, t41): happiness 1, a Circus queued, `todo` empty, the turn treated as quiet.

- **One client owns a seat's turn (#41).** The action lock made one operation exclusive and said nothing
  about the gaps between operations: two servers pinned to the same `--seat` could both end the turn, and
  on 2026-09-26 (Mongolia, seat 1, t37-42) a second client of the seat ended turns whose `todo` was empty
  while the first still meant to retarget its scout. Now the turn's first mutating command (an order, a
  diplomatic answer, `end_turn`, the end inside `finish_turn`) records its process in a claim file beside
  the lock, one per tuner socket and seat (`harness/turn_claim.py`). `end_turn`, `finish_turn` and every
  order from another process of the same seat answer `ok: false` with `turn_claim` (holder pid, how long
  it has held the turn, seconds since its latest order, when the claim expires) and the `gate`; reads, the
  waits and the notebook still answer, and `turn_status` shows `turn_claim` while a claim is live. The
  claim is for one game turn, so the holder's `skip_quiet_turns` run claims each turn it ends; if a second
  client acts on one of those turns first, the run stops and hands that turn back
  (`woke_because: ["other_client_holds_turn"]`) instead of ending it under them. It expires after 180 s
  without an order from the holder and at once when the holder's process is gone; `force: true` on
  `end_turn`, `finish_turn` or `do` takes it over. A server pinned to the other seat is refused as before
  (`this seat is not active`), claim or not. The CLI and the HTTP server keep their own `Game` with no
  claim (uncontested). `tests/test_turn_claim.py`: the file, two real processes, a crashed holder, the Game
  layer and the MCP layer.
- **`remember(replace_id)` refuses a different tag and returns the previous text (#40).** A replace used to
  match on the id alone and reply with the new note: `remember(replace_id=2)` from a scout stored its text
  over the plan, reported success, and the plan had to be written again (Arabia, seat 1, 2026-09-26). Now a
  non-empty `tag` that differs from the stored tag writes nothing and answers `ok: false` with the `id`,
  `stored_tag` and the tag that was passed; `retag: true` allows the change (`retagged: true` in the reply).
  Every successful replace carries `previous` (id, text, tag, turn) so a mistaken overwrite can be undone by
  writing it back. An empty tag still keeps the stored tag; a bad id still writes nothing and lists the ids.
  MCP `remember` and HTTP `POST /remember` take `retag`. Four tests in `tests/test_notes.py`.
- **The rule book: static help printed once, not on every row (runtime v216).** Every chooser row used
  to carry its hover text: the same Library blurb in every city's `available_production` every turn, the
  Salt hover (`resource_happiness`, `resource_improved_yields`, `resource_help`) on every Salt tile of every
  `map_window`, the tech sentence on every `available_research` row, the promotion effect under every
  button, the belief description, the policy help, the building help on `city_screen`, the standing
  sentence under every unit action. None of it changes during a game. `reference(section)` (MCP tool,
  usable between turns; MCP resources `civ5://reference` and `civ5://reference/{section}`; HTTP
  `GET /reference?section=`) is all of it in one Markdown document, read once from the game's own
  database (`H.reference`, so mods and DLC are honoured), cached per process and written beside the
  notebooks for the human. Sections: terrain, resources, improvements, units, buildings, projects,
  processes, promotions, policies, techs, beliefs, specialists, actions. The rows now carry enums, names
  and live numbers only (cost at this city's rate, turns, purchase price, upgrade target and price, scrap
  gold: the lines the panel computes per unit stay, in `help`). The server `instructions`, the playbook
  and every affected docstring point at the book. The choice was tokens, not bytes: a single-character
  terrain code saves bytes but not tokens ("GRASS" is one token; a glyph is two to four), while the
  repeated hover paragraph was tens of tokens per tile and per row. `revealed_map` remains the
  one-character-per-plot view.
- **Your own Continue screen is pressed for you by whatever you call first.** With `gate` in place the
  hand-off screen was still a chore: an agent that (re)started on it read `hand_off_screen`, and had to
  call `wait_for_my_turn` to press a button a human at that seat would press before anything else.
  `Game.clear_hand_off` presses it (our seat on screen, `hand_off_pending` true; never another seat's) and
  hands back the turn as the wait does, standing orders resumed, marked `hand_off_cleared: true`; every
  guarded tool, `turn_status` and the HTTP `/turn_status` run it before looking at the state. Two presses;
  a screen that stays up is left to the gate, whose `why` now says the press did not take. `finish_turn`
  called while our own hand-off is up waits instead of ending: `my_turn` already reads true under that
  screen, so a `finish_turn` retried after a client timeout that landed on the next turn's Continue screen
  would have ended it blind. `tests/test_gate.py` (`AnyCallPressesOurContinueScreen`).
- **`gate`: every status and every refusal names the one thing that must happen first, and the tool that
  does it** (runtime v215, `harness/gate.py`). Live 2026-09-26, Codex on seat 0 of the two-agent hotseat
  game, after a context reset: `turn_status` read `my_turn=true, paused=true, popup_up=true`, an empty todo
  and no blocker while its own hand-off screen was up -- nothing named the screen or the call that clears it.
  It read the board for four minutes, was refused with `game is paused, processing, or waiting`, replayed
  that refusal through its own `action_id`, and only then called `wait_for_my_turn`, which cleared it at
  once. Earlier the same hour, with the other seat on screen, the status note `set_seat(player_id) changes
  the seat` read as advice: it called `set_seat(1)` and pressed the other player's Continue button through
  raw Lua. Now `turn_status`, `wait_for_my_turn`, `finish_turn`, the HTTP `/turn_status` and every guard
  refusal carry `gate`: `null` when the seat may act, else `{name, why, clear_with, args?, read_first?}`
  computed once, in the order the engine and the guard enforce (no game, game over, other seat active,
  hand-off screen, processing, paused, turn not active, leader screen, discussion, tech choice, decision
  popup, announcement screen). The hand-off screen is a flag of its own now (`hand_off_pending`, read by
  `H.hand_off_up` in the same trip: the PlayerChange context answers `IsHidden() == true` while it is modal
  with its container visible, which is why `screens.PlayerChange` never saw it), and the wait loop uses it
  instead of two more trips. The seat notes and hints no longer offer `set_seat` from a pinned server; an
  auto-seat server hears it only as "if nobody else plays that seat". A refusal at a gate is never
  remembered under an `action_id`, so a retry after the gate clears runs. `tests/test_gate.py`.
- **The wait tools no longer hold the operation lock while they sleep.** Two agents in one hotseat game
  (Codex seat 0, Grok seat 1, 2026-09-26) stalled for most of two turns on `another game operation is
  running; retry`: `mcp_server.guarded` wrapped the whole call, so an inactive seat's `finish_turn(300)`
  held the per-socket flock for five minutes and the active seat could not even read `turn_status`, nor
  clear its own hand-off screen. An orphaned `scripts/mcp_call.py wait_for_my_turn` (a one-shot server the
  caller's shell had stopped watching) did the same for 180 s, and a first call's runtime injection for
  75 s. Now `Game.wait_for_my_turn` / `finish_turn` take `Game.lock` (the server's `action_lock`; a
  no-op for the CLI and HTTP server) around each poll, the end-turn and the digest, and sleep unlocked;
  `guarded` locks a wait tool only for the connect. The holder writes its seat, tool and pid into the
  lock file, and the refusal says what a human at the hand-off screen would know: for another seat's
  call, `it is not your turn while another seat acts` and nothing else (the other player's tool names and
  timings are their cursor, not the game's UI); for your own seat's earlier call, `your own finish_turn,
  pid 198237, has held it for 212 s`. `tests/test_lock_liveness.py` proves it at the Game, lock and MCP
  layers (a contender gets in between polls; each poll is still locked; a second process's refusal names
  your own call and not another seat's). Holders identified from both agents' transcripts
  in `docs/NOTES.md`. Verified live the same morning, Codex (seat 0) vs Grok (seat 1) on the same
  socket: three alternating hand-offs (turns 0-2) with both agents sitting in `finish_turn` at once, the
  waiting seat's `wait_for_my_turn` / `finish_turn` returning 7-8 s after the other's `finish_turn` began,
  and the only refusals the first call's runtime injection, which Grok read and waited out (the message
  then still named the other seat's tool; it no longer does).
- **`set_seat` refuses the other player's seat on a pinned server.** A server started with an explicit
  `--seat N` plays only seat N; `set_seat(other)` answers `this server was started with --seat N and plays
  only that seat; seat M is another player's`. `--seat auto` keeps its freedom (a hotseat save loaded on
  the wrong seat still needs it). Before this the playbook's "never take the other human's seat" was the
  only guard between two agents' information sets.

- **v214** every popup / leader screen's up-or-down in one InGame query, and the loop timed. The open
  ROADMAP row asked where a late `scripts/play_loop.py` turn spends its time; `--profile` (new) attributes
  every tuner round-trip to the loop phase and the `Game` method on the stack. Live S1 t270: 97 s, 278
  trips of ~0.35 s each (the floor: the game services one tuner command per frame or so), and 250 of
  them were screen reads -- `turn_state` was 8 trips (3.1 s: one per popup context through the tuner),
  the popup sweep ~20, and `wait_for_my_turn` did both on every poll (157 trips over a 50 s AI round),
  `end_turn` 93 trips (33 s). The engine's control tree is one tree, so `H.modal_flags()` now reads
  every context's `IsHidden()` from InGame by full path (`H.CONTEXT_PATHS`, 28 screens) and
  `H.turn_state` carries the five flags; `dismiss_pending_popups(ts)` reuses the caller's read. After:
  `turn_state` 1 trip (0.37 s), sweep-with-nothing-up 1, an idle wait poll 2, `end_turn` 8 trips (3.2 s).
  Live t271 (three blockers, a leader approach, 12 idle units): 90 s, with `unit_mission` (~7 trips an
  order: selection retries and confirmation polls) and the bot's candidate walks on top. Paths found the
  hard way: `BulkUI` is transparent (`/InGame/<ID>`; a `/InGame/BulkUI/<x>` path answers with BulkUI
  itself, visible), `LeaderHeadRoot` hangs off the root, and an ID can differ from its file
  (`GreatWorkSplash`, `ChooseIdeology`). Verified live: a `BUTTONPOPUP_TEXT` raised by Lua read as
  `screens.TextPopup = true` and the sweep closed it in its own state. Also fixed: `popup_up` read nil
  instead of false (an `a and b or nil` since v207). `tests/test_screens_one_read.py` (10). 592 tests.

- **v213** `todo_actions` (MCP + HTTP): legal actions for many units in one read. With no `unit_ids` it
  covers every unit in `turn_status.todo.units` plus every promotion-ready unit; with ids, exactly those.
  Each row is `available_unit_actions`' answer plus `id`, `type`, `promotion_ready`; action rows drop their
  `help` unless `full=true` (promotion rows keep name + help). Usable inside `do`. Live S1 t270: 38 units in
  one 0.5 s query, 30 KB compact / 59 KB full, against 0.37 s and ~1.6 KB per unit one at a time; two woken
  units (Paratrooper, Trebuchet) came back as `source: todo, n: 2` with the same rows as the single read.
  Found on the way: the per-unit read is cheap (0.37 s), so the handoff's "~15 min of
  `available_unit_actions` per unit" was a misattribution -- the loop's time goes elsewhere (unmeasured).
  The win is 1 tool call instead of 38 for the model, not minutes. `tests/test_todo_actions.py` (7). 582 tests.

## 1.1.0 -- the LLM-first loop (2026-09-25)

The turn boundary as one call, safe retries, a notebook, batching, and the seat named in every answer.
Tag `v1.1.0` = runtime v212 (v208-v212 landed after 1.0.0: revealed_map and trade-route paths). Every row
below was checked live on 2026-09-25 (S1 t269-t271, the Alpha/Bravo hotseat for set_seat and
exit_to_main_menu). 575 tests. `pytest` now finds `harness` from any invocation (`pythonpath` in
pyproject; before, only `python -m pytest` did).

- **set_seat** (MCP): change the player this server plays, or re-detect it, without a restart. Live
  2026-09-25: a hotseat save loaded under `--seat auto` left the server on its default seat 1 while seat 0
  sat on the hand-off screen; every tool refused with only `active_player: 0`, a 420 s `wait_for_my_turn`
  ran out, and nothing said which seat the server was on. Now `turn_status` carries `seat` (and a
  `seat_note` in hotseat when the seat on screen differs), the "this seat is not active" refusal carries
  `seat` and a `hint` naming set_seat, wait/finish timeouts carry `seat` + `active_player`, and progress
  messages name the seat. Only a seat the engine considers human can be chosen; `set_seat()` with no
  argument re-runs detection (hotseat: the seat on screen when it is human). Refused inside `do`.
- **exit_to_main_menu** (MCP): leave the loaded game for the main menu so load_save / load_latest can open
  another save (they only work from the menu, and nothing on the MCP surface got there before); quick-saves
  first when it is our turn in a solo game. A load now detects an auto seat afresh (the previous game's
  seat may be wrong for this one) and answers with `seat`. Both refused inside `do`.
- **finish_turn default timeout 600** (MCP + HTTP, was 270): verified in Claude Code 2026-09-25 that a
  420 s wait with progress every 5 s returns the server's own timeout, not a client cutoff; the client moves
  a call past 120 s to a background task and reports its result when it lands.
- **finish_turn** (MCP + HTTP): the turn boundary as one call -- end_turn, wait_for_my_turn and turn_digest,
  returning status, digest, turn and the latest notebook notes. Idempotent: when it is already not our turn it
  only waits, so a call retried after a client timeout never ends two turns. `skip_quiet_turns=N` ends up to N
  further turns while nothing needs the player (empty todo, no blocker/popup/expiring ally, nothing eventful
  in the digest: `Game.WAKE_KINDS` / `WAKE_WORDS`, plus the caller's `wake_on` words); the skipped turns'
  digests are merged and `woke_because` names the reason. Live t269-271: one call, 64 s, woke on
  todo.units + a leader message + a lost unit. `scripts/et.sh` is now one finish_turn call.
- **Progress notifications** while waiting: `wait_for_my_turn` and `finish_turn` report MCP progress every
  5 s (and at "ending turn N" / "turn N was quiet"), so a client's idle timeout no longer cuts a long wait
  short; the SDK runs tools in a worker thread, the reporter hops back to the loop with anyio. Verified
  in-process over the memory transport and live over stdio.
- **Notebook** `remember` / `recall` / `forget` (MCP + HTTP, `harness/notes.py`): per-game, per-seat notes
  stored under `$XDG_DATA_HOME/civ5-harness/notes/` (or `$CIV5_NOTES_DIR`), keyed by leader, civ, map
  script, capital and its founding turn (`Game.game_key`; the engine exposes no seed). `replace_id` keeps one
  living plan; the last 8 notes ride along in every finish_turn result. Usable while it is not our turn.
- **do** (MCP): a list of `{tool, args}` orders carried out in sequence with the SDK's own argument
  validation, each result returned; stops at the first `ok: false` and lists the rest as `skipped`
  (`stop_on_refusal=false` runs them all). Waiting, loading, end_turn, lua and do itself are refused inside.
- **action_id** on any tool call (and any `do` order): the call wrapper pops it before validation, keeps the
  raw result in a bounded per-process cache, and answers a repeat with the earlier result plus
  `replayed: true`, so a retry after a transport timeout never acts twice. Live t271: two skips batched,
  the same batch replayed, a direct call replayed. The wrapper now installs at import, once per process.
- **MCP resource + prompt**: `civ5://playbook` serves `docs/PLAYBOOK.md`; the `play_turn` prompt is the loop
  in one paragraph. The server `instructions` now describe the finish_turn loop.
- **docs** PLAYBOOK, README and AGENT_INSTALL describe the one-call loop and the notebook.

- **LICENSE** MIT, with the README noting that the game, its assets and the quoted stock UI Lua stay Firaxis/Take-Two's.
- **docs** `docs/GROK_PLAYBOOK.md` is `docs/PLAYBOOK.md`: mode-neutral, and its blocker table now matches
  `BLOCKING_HINTS` in the runtime (ideology, free great person, Maya, archaeology, reformation, steal-tech
  and league votes all have tools; proposing deals is no longer described as disabled).
- **docs** README rewritten for people (what to expect, ways to play, honest limits) and a new
  `docs/AGENT_INSTALL.md`: the complete install brief an agent follows to get the game, the shim, tunerd
  and the MCP server running on a fresh machine, with a check per step and a report-back script.
- **v212** `revealed_map`: the whole revealed map as character grids, one byte per plot per layer (vis,
  terrain, elevation, river, owner, feature, improvement, resource, route), legends built per reply,
  `layers` and an x0/y0/x1/y1 window for large maps (a Huge map after Satellites is ~10 KB a layer, where
  `known_world` is ~140 B a plot). The `vis` layer is the point: '#' in sight, '~' revealed but fogged,
  whose contents are what was last seen and may be stale. Fog rules are describe_plot's (remembered
  feature or '?', Revealed* improvement/route/owner, no live units or pillage marks under fog). Live S1
  t269: 66x42, 559 revealed / 355 visible, 28 KB for all nine layers.
- **v212** `trade_routes` rows carry the route line: `path` from the origin (fogged plots marked,
  `path_gaps` for unrevealed stretches), read from the plot hover's route list
  (`Player:GetInternationalTradeRoutePlotToolTip`, which plothelptext.lua calls on any revealed plot);
  `unit` is the caravan on the line (ours always; a foreign one only in sight) with `escorted` /
  `escorted_by` (own combat units on its plot, which an enemy must defeat before plundering) and
  `enemies_near_path` (visible enemy combat units within one hex, with their distance to the caravan).
  Caravans that fit only one route are placed first, since routes share plots (live t269: two Addis
  Ababa routes ran the same eleven plots). Found on the way: `Plot:IsTradeRoute()` is the city-connection
  flag, not a caravan line, so it is no longer the gate and `map_window`'s `trade_route` says so.
  Regression: `tests/test_revealed_map.py` (8). 528 tests.
- `docs/LIMITATIONS.md` "Still to be seen live" no longer waits for states already reached (#13 S4 t239,
  #22 S2b t237-238, #15 S5 t215, #23 S6 t215-t216); it now names what actually has regression coverage
  only: war on a city-state syncing over LAN (COVERAGE_AUDIT G-D3), LAN mode since 0.5.0, and the stale
  PRODUCTION blocker after game over (`turn_status.game_over` first). `docs/GAPS.md` section 0 header
  reads v207.
- `tests/test_supervisor.py`: `harness/supervisor.py` had no tests. 25 cases pin every path that must not
  relaunch the game (grace window open, process still up, pid unknown, no `--launch-cmd`, restart cap),
  the one that must, the grace-window reset after a relaunch and after a self-reconnect, `rejoin`'s replay
  per saved lobby kind, and `wait_for_main_menu`'s cold-boot retry. 520 tests.

## 1.0.0 -- release (2026-09-25)

Every row on the 0.5.0 and 1.0.0 tables in `docs/ROADMAP.md` is closed or declared (GitLab #29). Tag
`v1.0.0` = runtime v207. Cut after an unattended `scripts/play_loop.py` pass on a clean S1 load (solo
Shoshone, t266-t268, 38 units, World Congress): three turns ended without a stall, through
ENDTURN_BLOCKING_UNITS and PRODUCTION, one declined leader approach (Haile Selassie), a Caravan route and
three Worker automations; no stale blocker and no orphaned popup appeared. Each late-game turn took the
loop about 15 minutes (it reads `available_unit_actions` per unit), which is the loop's cost, not the
harness's.

- **v207** GitLab #23 closed: `ENDTURN_BLOCKING_UNITS` with an empty todo is a stale reading. The engine does
  not re-evaluate `GetEndTurnBlockingType` while a popup is up (`UI.IsPopupUp()`), so the last ready unit's
  order plus any announcement popup raised on the way -- a city-state met by the unit itself (which is why
  three `Teams:Meet` attempts never reproduced it), a natural wonder, a plain text box -- leaves UNITS on the
  books with `HasReadyUnit()` false (live S6 line t215-t216: Infantry 32771 toward Melbourne past a natural
  wonder, then a `UI.AddPopup` text box with Infantry 73736; both held UNITS until the popup closed). Now
  `turn_status` carries `blocking_stale` and `popup_up` and the hint names the popup instead of "every unit
  in todo.units" over an empty list; `end_turn` refuses on the popup ("popup needs attention (... stale ...)")
  rather than the blocker; and `dismiss_pending_popups` processes an announcement popup the engine waits on
  that nothing draws (record present, context hidden, `UI.IsPopupUp()` true, no screen up) the way its own
  close button would -- guarded, unit-tested, not yet seen live. 495 tests.

## 0.5.0 -- live verification (2026-09-25)

The reads that had only regression coverage, each closed by a live reproduction (GitLab #20-#22), plus the 0.4.0
screens that landed after the 0.3.0 cut (#13 live switch, #15 Venice). Tag `v0.5.0` = runtime v206. #23 (the
CityStateGreeting empty-todo turn-loop defect) stays open until a game state reproduces it: three attempts with the
greeting pending (S2b t237, Doge t215, S6 t214) all ended the turn normally.

- #21 closed live (no runtime change): the golden-age combat modifier row seen on a Persian seat in a golden age
  (S6 `Shah_0214 golden-age`, t214): `available_unit_actions` previews carried "Golden Age Bonus +10" and 70 -> 77
  strength, gone again with the golden age removed. Found on the way: `Players[63]:InitUnit` crashes the game in a
  fresh hotseat where the barbarian player is not alive yet (`docs/GAPS.md`, `saves/README.md`).
- **v206** Policy screen: `available_policies` branch rows say `can_unlock: false` once a branch is open (the
  engine's CanUnlockPolicyBranch stays true) and `unlock_policy_branch` refuses an open branch instead of
  re-sending it. `scripts/play_loop.py` adopts what the screen offers (an Atomic start's free policies were
  none of its static candidates, and re-unlocking Tradition counted as progress five times, live Doge t215)
  and handles ENDTURN_BLOCKING_CHOOSE_IDEOLOGY through `choose_ideology` (Freedom chosen, t215 ended).
- **v205** Venice's puppets live (#15 closed): a one-human hotseat hosted as Venice (S5
  `Doge_0215 venice-puppet`); the Merchant of Venice's `MISSION_BUY_CITY_STATE` bought Wittenberg,
  `available_production` opened the puppet in purchase mode (22 priced rows) and `purchase_production` bought a
  Monument there while `set_production` refused. Fixed on sight: `producing` was the raw TXT_KEY in the puppet
  list and in the refusal (now the printed name; `H.L` survives a missing Locale), and the refusal told Venice to
  annex, which it cannot (now it points at purchase_production).
- **v204** Ideology switch live (#13 closed): eight Great Musician concert tours by Bravo (`unit_mission
  MISSION_ONE_SHOT_TOURISM`, 67 tourism each at Quick speed, legal at war) put Alpha at Popular influence
  under Order; Alpha's t239 read Civil Resistance, 6 unhappiness, `can_switch` with the 2-turn anarchy cost,
  and `change_ideology` moved Autocracy -> Order on the spot (anarchy 2, opinion back to Content). The gold
  hover now carries `anarchy_turns` like the science/culture/faith ones (stock GoldTipHandler). New save S4
  `Alpha-Bravo_0239 ideology-pressure`.
- Release hygiene: `docs/LIMITATIONS.md` (declared engine rules and refused calls, #24), README and
  ARCHITECTURE rewritten for the current tool set (#27), `saves/` library of the reproduction states (#28).
- **v203** Captured civilians: the notice is linked from the destroy side too (the destroy event can arrive
  after the notice), and `move_unit` refreshes the loss roster on arrival. Live S1 t267: one
  `unit_captured` row with the barbarian captor on the tile, and S2b t237-238 the same with Bravo's Infantry as
  captor (#22 closed).
- #20 closed as a declared limitation: stock BNW ships `FIRE_SUPPORT_DISABLED = 1`, so melee fire support
  never fires and the preview's 0 is faithful. #21 rough/open-terrain and flanking rows seen live (S1 t266);
  the golden-age row needs Persia. New save S3 `Pocatello_0266 combat-lab`.

## 0.3.0 -- trade table (2026-09-25)

Everything a human can put on, read from, or answer on the trade table (GitLab #4-#8), each live on the
Alpha/Bravo hotseat or the solo Shoshone save. Tag `v0.3.0` = runtime v202.

- **v202** The leader screen's Demand button: `demand(other, items)` through OnDemand / UI.OnHumanDemand /
  UI.DoDemand, their items only, refused at war or toward a human seat (#6; live t266, Darius refused).
  `trade_catalog.gold.note` explains the Brave New World rule that lump-sum gold needs a Declaration of
  Friendship (gold per turn is not gated).
- **v201** Venice buys in its puppets: `available_production` opens in purchase mode for a puppet when
  the player `MayNotAnnex()`, as the stock production popup does (#15; regression-tested, live check
  needs a Venice seat).
- **v200** Peace with terms through the real screens: `make_peace(other, items)` is `propose_deal` with
  the treaty on both sides; `trade_catalog().peace` is the Negotiate Peace gate with the locked-into-war
  reason (#5; live t237: Silk + Salzburg accepted by the other human seat).
- **v199** Third-party war and peace on the trade table, with the Other Players pocket as
  `trade_catalog.third_party` (#6; live t234). The AI-only Demand button stays open.
- **v198** World Congress vote commitments on the trade table, with the Diplomat requirement (#7; live
  t233).
- **v197** Switch Ideology: the unhappiness hover, the switch cost and the switch itself (#13; the
  enabled button is not yet seen live).
- **v196** Remembered terrain features under fog, a last-seen cache like the stock map's (#19).
- **v195** The Culture Overview swap tab (#12; live t270).
- **v194** Coup odds and grey reasons, the spy potential hover, the faith purchase pull-down (#9, #10, #11).
- **v193** The hovers behind the city screen meters, specialist yields, help on owned buildings, stored
  beakers on every tech (#14, #16, #17, #18).
- The regression suite has a locked `dev` dependency group and a one-line runner, `scripts/check.sh`,
  meant to run before every push; GitLab pipelines are not used (no shared runner minutes) (#25).
- Deals between human seats: `propose_deal`, `incoming_deal`, `accept_deal`, `refuse_deal` on the
  `SimpleDiploTrade` table; `load_save` finds hotseat and network saves (#4; live t227/t228).

## 0.2.0 -- information boundary (2026-09-24)

Nothing new may leak and no read may truncate.

- **v192** No rival tech list behind an embassy; deal city rows are reveal-gated and carry population
  (#1, #2, #8).
- Query chunking budgets escaped bytes, not characters: the tuner truncates at 2048 bytes (#3).
- **v185–v191** The first two-human hotseat: a standing move belongs to one seat, the stacked tile's
  units, the swap a move causes, deals between humans and the leader scene a proposal leaves behind,
  intercepted strikes, clamped previews, captured civilians named.

## 0.1.x -- the solo Shoshone game (2026-09-15 to 2026-09-23)

`RUNTIME_VERSION` v125–v184: the information-parity reads and writes built against a solo Emperor game
(Pocatello, t1–t266), each one opened because it was blocking a real decision and verified live the
same turn. `docs/GAPS.md` and `docs/SESSION_HANDOFF.md` hold the turn-by-turn notes.

## Runtime version map

Recent runtime versions and the commit that introduced each:

| Runtime | Date | Commit | Change |
|---|---|---|---|
| v226 | 2026-09-27 | `3c0aec0` | `H.order_facts`, `H.resume_moves(pid, skip)`: conditional unit orders (#32) |
| v225 | 2026-09-27 | `61cb931` | `H.compare_production` / `_research` / `_improvements` / `_trade_routes` (#34) |
| v224 | 2026-09-26 | `3e9a7fa` | `H.assignment_facts`, `H.is_upgrade_of`: structured assignments (#33) |
| v223 | 2026-09-26 | `be1eb1b` | tactical grid cells beyond `radius` are blank |
| v222 | 2026-09-26 | `9e64b1d` | `H.tactical_view`, `H.move_refusal` shared with `move_unit` (#31) |
| v221 | 2026-09-26 | `9778f81` | `H.briefing_board`: threats, camps, leader trait, event log with its own cursor (#30) |
| v220 | 2026-09-26 | `7914f48` | `hp` / `max_hp` on damaged `todo_actions` rows; `detail` levels (#35) |
| v219 | 2026-09-26 | `4534fda` | `expiring_deals` / `expiring_friendships` on turn_status (#38) |
| v218 | 2026-09-26 | `38a6608` | `todo.ongoing`: automated units and standing-move destinations (#37) |
| v217 | 2026-09-26 | `1559c74` | `turn_status.alerts`: low happiness, unhappy tier, strategic deficits (#39) |
| v216 | 2026-09-26 | `926bd54` | the rule book: static help once in `reference()`, not on every row |
| v215 | 2026-09-26 | `3bf4f93` | `gate` on every status and refusal |
| v214 | 2026-09-25 | `d0af586` | every popup screen in one query; `play_loop --profile` |
| v213 | 2026-09-25 | `d981a76` | `todo_actions`: legal actions of every unit needing an order in one read |
| v212 | 2026-09-25 | `2910df8` | `revealed_map` grids and trade-route paths |
| v207 | 2026-09-25 | `8ebe0ad` | a stale UNITS blocker is named (#23) |
| v206 | 2026-09-25 | `0ecec22` | open policy branches offer no unlock; play loop reads the policy screen, picks an ideology |
| v205 | 2026-09-25 | `78cb3ff` | Venice's puppets live: localized `producing`, refusal points at purchase_production (#15) |
| v204 | 2026-09-25 | `c410c45` | ideology switch live, gold hover's anarchy line (#13) |
| v203 | 2026-09-25 | `579f8d4` | capture notices linked from the destroy side (#22) |
| v201 | 2026-09-24 | `a6be7be` | Venice buys in its puppets (#15) |
| v200 | 2026-09-24 | `2d1d857` | peace with terms through the real screens (#5) |
| v199 | 2026-09-24 | `e0fef85` | third-party war/peace on the trade table (#6) |
| v198 | 2026-09-24 | `c3dd709` | World Congress vote commitments on the trade table (#7) |
| v197 | 2026-09-24 | `cfaa529` | the Switch Ideology button, its hover and the switch (#13) |
| v196 | 2026-09-24 | `da91929` | remembered terrain features under fog (#19) |
| v195 | 2026-09-24 | `e70930a` | the Culture Overview swap tab (#12) |
| v194 | 2026-09-24 | `6ca1580` | coup odds and grey reasons, the spy potential hover, and the faith purchase pull-down (#9, #10, #11) |
| v193 | 2026-09-24 | `153d0c0` | the hovers behind the city screen and stored beakers on every tech (#14, #16, #17, #18) |
| v192 | 2026-09-24 | `a8b2ce6` | no rival tech list behind an embassy, deal city rows reveal-gated and carry pop (#1, #2, #8) |
| v191 | 2026-09-24 | `8b07491` | intercepted strikes, clamped previews, captured civilians named |
| v187 | 2026-09-24 | `7190cf9` | deals between humans, and the leader scene a proposal leaves behind |
| v185 | 2026-09-24 | `3a5c6f0` | a standing move belongs to one seat |

<details><summary>v125–v184</summary>

| Runtime | Date | Commit | Change |
|---|---|---|---|
| v183–v184 | 2026-09-24 | `e33a166` | the stacked tile's units, and the swap a move causes |
| v182 | 2026-09-23 | `371e10c` | the greyed Gift Improvement button says why |
| v181 | 2026-09-22 | `2de406e` | the trade route screen's religion columns and gold hover |
| v180 | 2026-09-22 | `ce8887a` | World Congress names drop the choice's icon tag |
| v179 | 2026-09-22 | `bc33a3c` | the resource list's bonus stack, and the tile hover |
| v178 | 2026-09-22 | `48945fa` | the Happiness screen's rows, not just the totals |
| v177 | 2026-09-22 | `0b34980` | the tech tree's buttons, not just the paragraph |
| v176 | 2026-09-22 | `47e2603` | the World Congress screen's tooltips, not just the names |
| v175 | 2026-09-22 | `76318e4` | World's Fair progress on the league screen and the production row |
| v174 | 2026-09-22 | `f786ccd` | the city screen's meters, including a tile you cannot afford |
| v173 | 2026-09-21 | `d7c772f` | the Notification Log, not just the panel |
| v172 | 2026-09-21 | `2167b2a` | a finished build says what it changed, including the borders it moved |
| v171 | 2026-09-21 | `c2389d0` | the Change Home City chooser, for caravans and Great Admirals |
| v170 | 2026-09-21 | `81c9dc3` | a gift tier says whether it actually buys the alliance |
| v169 | 2026-09-21 | `dead011` | the production chooser says Zoo, not BUILDING_THEATRE |
| v168 | 2026-09-21 | `1b247f9` | an idle caravan says why it has nowhere to go |
| v167 | 2026-09-21 | `11d7c96` | what the unit-action button says it does |
| v165 | 2026-09-21 | `06b0ec6` | the Gift Improvement button, and the hexes it lights up |
| v164 | 2026-09-21 | `953b724` | say which great work a Great Person became, and where it went |
| v163 | 2026-09-21 | `c6a55e7` | refuse a move onto another player's city instead of letting it rot |
| v162 | 2026-09-21 | `27add30` | an idle spy is as invisible as an idle caravan used to be |
| v161 | 2026-09-21 | `406c756` | a missionary says which faith it carries, and a no-op spread says so |
| v160 | 2026-09-21 | `0c0ebcb` | a negative TurnsLeft is a blank column, not an overdue route |
| v159 | 2026-09-21 | `409367b` | buy_city_plot had the same puppet hole, and now a lint says so |
| v158 | 2026-09-21 | `ca9884b` | a puppet is not ours to run, and the inline-query budget was a guess |
| v157 | 2026-09-20 | `1ef40ec` | a captured-city row pointed at the wrong city |
| v156 | 2026-09-20 | `b57c0d0` | say why the turn will not end, in the engine's words |
| v155 | 2026-09-20 | `093cf6e` | turn_status and unit_mission agreed about stalled units |
| v154 | 2026-09-20 | `f1a4198` | steal_tech takes player_id like every other civ-targeting tool |
| v153 | 2026-09-20 | `bbaf461` | refuse an air strike the engine would ignore |
| v152 | 2026-09-20 | `c4de752` | the promotion chooser as a human reads it |
| v151 | 2026-09-20 | `d98b0b1` | itemised combat modifier rows on every preview |
| v150 | 2026-09-20 | `ac2dcd7` | include melee fire support and cap preview damage |
| v149 | 2026-09-20 | `4a40b14` | air-strike retaliation and ranged combat previews |
| v148 | 2026-09-19 | `79e2670` | tech/production help, nearby build turns, public opinion |
| v147 | 2026-09-19 | `8acb5c2` | incoming trade routes, score breakdown, WLTKD/blockade |
| v146 | 2026-09-19 | `f93bc4e` | worker job turns, CS quest list, plot construction tooltip |
| v145 | 2026-09-19 | `ee5ea13` | Military Overview unit supply and Economic Overview gold rows |
| v144 | 2026-09-19 | `c561ad5` | gold deficit flag and city-screen sell building |
| v143 | 2026-09-19 | `c477c08` | pending steal-tech in todo and on the notice |
| v142 | 2026-09-19 | `5a8943c` | conversion banner, empty-queue vs process, Discuss flags |
| v141 | 2026-09-19 | `436e356` | top-bar science/culture/tourism/faith; combat result holes |
| v140 | 2026-09-19 | `e5ec3dd` | map index, named deal cities, CS unit gift |
| v139 | 2026-09-19 | `53fda00` | remaining information-parity reads |
| v136 | 2026-09-19 | `7325f84` | docs: notes + handoff through t150 |
| v136 | 2026-09-19 | `30e6363` | attack_targets / move_unit: a garrisoned enemy city is fought as the city; result says city_captured |
| v135 | 2026-09-19 | `7846f17` | move_unit: a captured civilian reports captured + the new unit id, not defender_killed |
| v134 | 2026-09-19 | `cad1951` | docs: notes + handoff through t100 |
| v134 | 2026-09-19 | `5e7b5c8` | free_great_person_options / choose: only this civ's own great people |
| v133 | 2026-09-19 | `b1bae90` | unit_mission builds: name the build in progress and its turns left; say when a feature removal runs first |
| v132 | 2026-09-19 | `2192fe0` | disband_unit: say when the refusal is 'no moves left this turn' |
| v131 | 2026-09-19 | `1907dcb` | move_unit / resume_moves: refuse a destination held by a civ we are at peace with |
| v130 | 2026-09-19 | `4ff285a` | available_city_strikes: target hp + expected damage (UpdateCombatOddsCityVsUnit) |
| v129 | 2026-09-19 | `f752d7a` | docs: notes + handoff through t33 |
| v129 | 2026-09-19 | `c47e282` | unit_mission: a refused order keeps the unit's standing move |
| v128 | 2026-09-19 | `9dfbbbe` | docs: notes + handoff through t19 |
| v128 | 2026-09-19 | `6f5d2fc` | religion_overview: rival pantheons as the Beliefs tab lists them |
| v127 | 2026-09-19 | `2959d92` | city_capture_options / choose_city_capture: BUTTONPOPUP_CITY_CAPTURED with unhappiness deltas + warmonger preview |
| v126 | 2026-09-19 | `77a1078` | war_consequences: the declare-war confirmation's warnings as a read |
| v125 | 2026-09-19 | `7d49e36` | docs: notes + handoff through t11 |
| v125 | 2026-09-19 | `8739bcd` | city_state_actions / city_state_action: quests, pledge, tribute, war and peace as the city-state screen does them |
| v124 | 2026-09-19 | `4ff475d` | trade_catalog: a tradeable city's x,y only once its plot is revealed |
| v123 | 2026-09-19 | `2fc3250` | religion_overview: the Religion Overview screen's three tabs, unmet founders masked |
| v121 | 2026-09-19 | `67b3f8e` | attack previews for city assault and ranged shots; enemy-city melee listed and never stored as a standing move |
| v119 | 2026-09-19 | `5345a35` | available_beliefs + add_reformation_belief; found/enhance validate each belief against its slot's available list |
| v118 | 2026-09-19 | `fcf3cb6` | goody_hut_options / choose_goody_hut: Shoshone Pathfinder ruins choice via Network.SendGoodyChoice |
| v117 | 2026-09-19 | `a7ced23` | league_status votable: yes_no flag; luxury bans name the resource and our count |
| v116 | 2026-09-19 | `c1814d7` | incoming_deal: say whether a luxury we would receive is new to us |
| v115 | 2026-09-19 | `979328c` | culture_overview tool; civ_eliminated digest event |
| v87 | 2026-09-18 | `ad98816` | Combat provenance in turn_digest: named attacker/defender, plots, hp; hp-diff fallback across the AI phase |
| v83 | 2026-09-17 | `4ea6311` | unit_mission: refuse MISSION_SKIP on a unit mid multi-turn move |
| v82 | 2026-09-17 | `ba6e6a1` | city_state_gifts: rivals influence list |
| v81 | 2026-09-17 | `9c8d4a5` | incoming_deal: us_owned undoes export-net totals; renewals are not last copies |
| v80 | 2026-09-17 | `499b7b3` | incoming_deal: resource items we would give carry copies/import/export and last_copy |
| v79 | 2026-09-17 | `87804b3` | available_production: faith rows listed before they are affordable, faith_can_buy |
| v78 | 2026-09-17 | `38987ea` | available_production: faith purchase costs and faith-only rows |
| v77 | 2026-09-17 | `e3f469c` | cities: majority religion name |
| v76 | 2026-09-17 | `bd95025` | explore_frontier: reachability respects borders |
| v75 | 2026-09-17 | `892efb2` | generic_popup / answer_popup: drive the game's yes/no confirmations |
| v72 | 2026-09-17 | `455d983` | explore_frontier: reachable flag via flood fill over the revealed map |
| v71 | 2026-09-17 | `469290f` | disband_unit: COMMAND_DELETE with polled confirmation and measured effects |
| v69 | 2026-09-17 | `7f72ec1` | overview: strategic_resources with available/total for revealed resources |
| v67 | 2026-09-17 | `7ff0363` | trade_catalog: per-resource copy counts and last_copy luxury warning |
| v65 | 2026-09-17 | `1621921` | explore_frontier: flag polar map_edge plots |
| v63 | 2026-09-17 | `aa7ccd2` | unit_mission: measured effects for MISSION_SPREAD_RELIGION / REMOVE_HERESY |

</details>
