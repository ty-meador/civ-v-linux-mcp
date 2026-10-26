# The tool surface: model the game, not its buttons

Written 2026-10-25 after the Glama listing (https://glama.ai/mcp/servers/ty-meador/civ-v-linux-mcp) scored the
server: completeness 5/5, naming consistency 4/5, disambiguation 3/5, tool count 1/5. Their rubric wants 3
to 15 tools and calls 50 or more an extreme mismatch; we list 145. The other two marks are symptoms of the
count: among 145 names the reviewer found six map reads, four status reads and four "what can this unit
do" reads and could not tell from the names which to use.

A first draft of this plan (commit ac28a1b, same day) folded families of tools into enums: the thirteen
overview screens into `screen(name)`, the sixteen popup tools into two, and so on. It reached 87 listed
tools, with a hidden tier behind `call()` to show a client about 40. That was not enough, and the reason
is instructive: it still modelled the *interface*, one tool per screen or per button, only with fewer
buttons. 87 is still "50+", a hidden tier only moves the count out of the reviewer's sight, and every new
game feature would add a tool again. The catalog grew to 145 because the model was "a tool for every
possible thing that can be done". The fix is a different model of the game, not a tidier list.

This is a Python-and-docs change. The Lua runtime (`harness/lua/runtime/*.lua`, `H.*`) does not move; the
MCP functions in `harness/mcp_tools/*.py` keep their bodies and become the dispatch targets of nine tools.
No runtime bump until one text-only one at the end, so no re-injection window and no live-game risk from the
plan itself. `docs/ROADMAP.md`, "The tool surface", has the stage table; this file holds the model and the
mapping.

## What is there today

Measured on `main` at 7c30a8f with `tool_catalog()` (`scripts/mcp_call.py --list` gives the same names):

| Module | Tools | Of which zero-argument reads |
|---|---|---|
| `turn` | 11 | 4 |
| `batch` | 2 | 0 |
| `notebook` | 11 | 0 |
| `units` | 24 | 7 |
| `cities` | 22 | 3 |
| `policies` | 21 | 7 |
| `diplomacy` | 36 | 10 |
| `trade` | 13 | 4 |
| `front_end` | 3 | 0 |
| `reference` | 2 | 0 |
| total | 145 | 35 |

Where the 145 come from, counted from the catalog:

| Shape | Count | Example |
|---|---|---|
| a popup's read + its answer, one pair per popup kind | 16 | `goody_hut_options` / `choose_goody_hut` |
| one zero-argument read per overview screen | 13 | `culture_overview`, `spaceship_status`, `wonder_overview` |
| reads of the same map at different grains | 6 | `known_world`, `map_window`, `revealed_map`, `map_index`, `explore_frontier`, `tactical_view` |
| reads of "what can this unit do" | 4 | `available_unit_actions`, `todo_actions`, `unit_mission_targets`, `unit_home_options` |
| city-state screen, one tool per button and per tooltip | 9 | `city_state_gifts`, `gift_unit_options`, `gift_unit`, `minor_gold_gift` |
| the trade table's buttons, one tool each | 6 | `incoming_deal`, `accept_deal`, `refuse_deal`, `dismiss_discussion` |
| one write per city-screen control | 14 | `set_city_focus`, `set_avoid_growth`, `change_working_plot`, `sell_building` |
| one write per empire-level decision | 10 | `set_research`, `choose_policy`, `found_pantheon`, `set_faith_purchase` |

Each row was a reasonable decision on its own day: a tool per button keeps the engine rule behind that
button in one place, and `docs/GAPS.md` records why each exists. The cost is the aggregate, which is what a
listing is. Three things the new model builds on already exist:

- the harness already computes **affordances**: `todo_actions` returns, per unit, the legal missions,
  builds, commands and promotions right now; `available_production`, `available_research`,
  `available_policies`, `available_beliefs`, `available_trade_routes`, `available_spy_cities`,
  `city_state_actions`, `trade_catalog` and every `*_options` read do the same for their object. They are
  the engine's own answers (`CanDoMission`, `canTrain`, `CanAdoptPolicy`, ...), not the harness's guess.
- `harness/gate.py` already names, for every blocking state, the read to make and the call that clears it.
- `do(actions=[{tool, args}])` and `finish_turn(actions=[...])` already take orders as data, and
  `harness/attention.py` already reads `{tool, args}` rows back out of todo replies.

What is missing is only that the affordances are handed back as prose. `harness/briefing.py` writes a todo
row as `"tool": "available_production + set_production"` and `"tool": "incoming_deal then accept_deal /
refuse_deal"`: a sentence the model must turn into a tool choice. That sentence is the seam.

## The model

A game of Civilization V, from one seat, is:

1. **a clock**: it is my turn or it is not, something blocks ending it or nothing does;
2. **a world of objects** I can look at: my empire, the map, units, cities, civilizations, city-states,
   the World Congress, my spies, and the overview screens the game draws from the same state;
3. **objects I own that take orders**: a unit, a city, the empire (research, policy, religion, faith),
   and my standing toward another civ, a city-state, the Congress, or a spy's posting;
4. **questions the game asks me**: a popup, a leader on screen, a deal on the table, a blocker;
5. **my own memory**: notes, assignments, standing orders;
6. **the session**: saves, loads, which seat I am.

And at any moment every object carries its **legal actions right now**, which the engine computes. So the
surface is three operations over objects, plus the clock, the memory, the session and the rulebook:

| Tool | Is | Replaces |
|---|---|---|
| `turn(action, ...)` | the clock: `status`, `briefing`, `finish` (end and wait, with `actions`), `end`, `wait` | 7 |
| `inspect(what, id=, view=, ...)` | read any object: `empire`, `map`, `unit`, `units`, `city`, `cities`, `civ`, `civs`, `city_state`, `league`, `spies`, `screen`, `notifications`, `options`, `compare`; `view` picks the grain | 47 |
| `order(to, id=, action, args={})` | give any object I own an order: `to` is `unit`, `city`, `empire`, `civ`, `city_state`, `league`, `spy` | 48 |
| `question()` | what the game is asking right now: the popup, the leader screen, the deal on the table, or the blocker, with the answers it accepts as ready-made `answer` / `order` rows | 10 |
| `answer(choice, args={})` | answer it | 13 |
| `notebook(action, ...)` | `remember`, `recall`, `forget`, `assign`, `assignments`, `amend`, `close`, `give_order`, `orders`, `cancel_order`, `resume_order` | 11 |
| `batch(actions)` | many orders in one call, in order (today's `do`); `call` is no longer needed because nothing is hidden | 2 |
| `session(action, ...)` | `save`, `load`, `load_latest`, `main_menu`, `seat` | 5 |
| `reference(book, section=)` | the rule book and the playbook (`how_to_play`) | 2 |

Nine tools. Checked by script on 2026-10-25: each of the 145 names maps to exactly one of the nine and
none is left over. The listing is inside the rubric's band, with no hidden tier and nothing reachable only
by a side door.

**The rule that keeps the count there.** A new game feature is a new `view` of an object or a new `action`
on one, never a new tool. The catalog is closed; the enums are open.

### Why this is a better model, not just a smaller list

- **The engine chooses the vocabulary.** `inspect(what="unit", id=7)` returns the unit and, under
  `actions`, the orders it can take right now, each as a row the model passes straight to `order` (or into
  `batch`). The model's decision is "which object, then which of its listed actions", never "which of 145
  tools". Disambiguation stops being a reading-comprehension task over descriptions.
- **Siblings become views.** `map_window` / `revealed_map` / `map_index` / `explore_frontier` /
  `tactical_view` are `inspect(what="map", view="window" | "grid" | "index" | "frontier")` and
  `inspect(what="unit", id, view="tactical")`. `turn_status` / `briefing` / `turn_digest` / `players` are
  `turn("status")` and `turn("briefing", detail="digest")`. The reviewer's four confusable unit reads are
  `inspect(what="unit", id, view="actions" | "targets")` and `inspect(what="units")`.
- **One shape for every decision the game forces.** Today a Maya bonus, a goody hut, a captured city, a
  stolen tech, a free Great Person and a leader's demand are twelve tools with twelve argument shapes.
  `question()` reads whichever is up (the gate's table is the dispatch) and lists the answers; `answer`
  takes one. The popup kind is in the reply, not in the tool name.
- **Names stop being a problem.** Nine names, each a verb or the thing it acts on; `available_*` versus
  `*_options`, `do`, `city_task`, `demand` and `diplo_event` go away with the names they were attached to.
- **Completeness is kept by construction.** Every old function remains the handler of one `(tool, action)`
  or `(what, view)` row. Nothing is dropped; the 5/5 stands.

### The schemas

`inspect` and `turn` have small, flat schemas: `what` / `action` are enums with one line per value in the
description, and the handful of selectors (`id`, `view`, `x`, `y`, `radius`, `mission`, `kind`, `detail`,
`since`, `limit`, the `compare` fields) are optional top-level arguments. `order`, `answer`, `notebook` and
`session` take `action` plus an `args` object, because their arguments differ per action (a deal's `items`,
a dig's `x`,`y`, a religion's five beliefs) and a flat schema of sixty optional fields would be worse than
none. Three things make the `args` object safe:

1. **The reply writes the call.** Every affordance row is `{"tool": "order", "args": {"to": "city", "id": 3,
   "action": "produce", "args": {"item": "BUILDING_LIBRARY"}}}`, copied as is. `question()` does the same
   for its answers, and `turn("briefing")` for its todo rows. The prose hints in `harness/briefing.py` are
   replaced by these rows (stage 1), in today's vocabulary first so the change is testable on its own.
2. **A refusal names the shape.** An `order` with a missing or unknown argument is refused with the
   action's argument list and one example, the way enum refusals already list the valid values. Validation
   is per action, in one table (`harness/surface.py`), which is also what `reference("playbook",
   "orders")` prints.
3. **The action names are the old verbs.** `order(to="unit", action="move")`, `"mission"`, `"promote"`,
   `"upgrade"`, `"disband"`, `"trade_route"`, `"plunder"`; `to="city"`: `"produce"`, `"purchase"`,
   `"dequeue"`, `"sell_building"`, `"buy_plot"`, `"specialist"`, `"work_plot"`, `"governor"` (focus /
   avoid growth / auto specialists in one), `"status"` (annex / raze / unraze), `"strike"`, `"great_work"`
   (offer / clear / swap); `to="empire"`: `"research"`, `"policy"` (a `POLICY_BRANCH_*` unlocks),
   `"ideology"`, `"switch_ideology"`, `"pantheon"`, `"religion"`, `"enhance_religion"`, `"reformation"`,
   `"faith_purchase"`; `to="civ"`: `"propose_deal"`, `"negotiate"`, `"peace"`, `"demand"`,
   `"friendship"`, `"declare_war"`, `"denounce"`, `"event"` (today's `diplo_event`); `to="city_state"`:
   the screen's buttons by their names plus `"gift_gold"`, `"gift_unit"`, `"gift_improvement"`;
   `to="league"`: `"propose"`, `"repeal"`, `"vote"`; `to="spy"`: `"move"`, `"coup"`. A model that knew the
   old tools knows the words.

The MCP `inputSchema` for `order` can carry the per-target action enums as a `oneOf` on `to`, which
Claude Code renders and validates; stage 2 checks Codex and the Grok client against the same schema and
falls back to a plain string with server-side validation where a client does not render `oneOf`. Either
way the reply-writes-the-call rule carries the model.

### The mapping, by old module

Every old name becomes one row. The retirement map is this table in code; the test that every old name
resolves is mechanical.

| Old | New |
|---|---|
| `finish_turn(...)`, `end_turn`, `wait_for_my_turn` | `turn("finish", ...)`, `turn("end")`, `turn("wait")` |
| `turn_status`, `players` | `turn("status")` (`players` is a key of it in hotseat games) |
| `briefing(...)`, `turn_digest` | `turn("briefing", ...)`, `turn("briefing", detail="digest")` |
| `overview`, `demographics`, `notification_log` | `inspect("empire")`, `inspect("empire", view="demographics")`, `inspect("notifications")` |
| `tech_tree`, `religion_overview`, `culture_overview`, `culture_works`, `great_person_progress`, `domination_progress`, `spaceship_status`, `wonder_overview`, `espionage_intrigue`, `trade_routes`, `current_deals`, `league_status`, `spies` | `inspect("screen", view=<name>)`; `league_status` is `inspect("league")`, `spies` is `inspect("spies")` |
| `units`, `todo_actions`, `available_unit_actions`, `unit_mission_targets`, `unit_home_options`, `tactical_view` | `inspect("units")` (with `view="actions"` the todo list), `inspect("unit", id, view="actions" / "targets" (with `mission`) / "tactical")` |
| `cities`, `city_screen`, `available_production`, `purchase_cost`, `available_city_strikes` | `inspect("cities")`, `inspect("city", id, view="screen" / "production" (with `yield_type`) / "strikes")` |
| `known_world`, `map_window`, `revealed_map`, `map_index`, `explore_frontier` | `inspect("map", view="window" / "grid" / "index" / "frontier")`; `known_world` retires to `turn("briefing", since="turn")` + the parts |
| `diplomacy`, `relationship`, `war_consequences`, `trade_catalog` | `inspect("civs")`, `inspect("civ", id, view="summary" / "war" / "trade_catalog")` |
| `city_state_actions`, `city_state_bonuses`, `city_state_gifts`, `gift_unit_options`, `gift_tile_improvement_options` | `inspect("city_state", id, view="summary" / "full")` |
| `available_research`, `available_policies`, `available_beliefs`, `available_trade_routes`, `available_spy_cities` | `inspect("options", view="research" / "policies" / "beliefs" (with `kind`) / "trade_routes" (with `id`) / "spy_cities" (with `id`))` |
| `compare(...)` | `inspect("compare", kind=..., ...)` |
| `generic_popup`, the seven `*_options` popup reads, `discussion`, `incoming_deal` | `question()` |
| `answer_popup`, the six `choose_*` popup answers, `steal_tech`, `respond_discussion`, `accept_deal`, `refuse_deal`, `accept_friendship`, `dismiss_discussion` | `answer(choice, args)`: a button number, a `UNIT_` / `TECH_` / goody name, `liberate` / `annex` / `puppet` / `raze`, or `accept` / `refuse` / `leave` / `accept_friendship` on a leader screen |
| the 7 unit writes, 14 city writes, 10 empire decisions, 8 civ actions, 4 city-state actions, 3 league actions, 2 spy actions | `order(to, id, action, args)` as listed above |
| `remember`, `recall`, `forget`, `assign`, `assignments`, `amend_assignment`, `close_assignment`, `give_order`, `orders`, `cancel_order`, `resume_order` | `notebook(action=<same word>, ...)` |
| `do`, `call` | `batch(actions)`; `call` retires (every tool is listed) |
| `quick_save`, `load_save`, `load_latest`, `exit_to_main_menu`, `set_seat` | `session("save" / "load" / "load_latest" / "main_menu" / "seat", ...)` |
| `reference(section)`, `how_to_play(topic)` | `reference("rules", section)`, `reference("playbook", topic)` |

Reply shapes do not change: `inspect("screen", view="league")` returns today's `league_status` reply byte
for byte, so `docs/TOOL_REPLIES.md` keeps its keys and only its headings move.

## Retirement, not removal

Every old name stays callable forever. The call wrapper (`_hint_unknown_tools` in `harness/mcp_server.py`)
looks an unlisted name up in the mapping table, runs the new `(tool, args)` and adds
`"renamed": "inspect(what=\"map\", view=\"window\")"` to the reply. The old names are never in a listing;
the call ledger records the new tool and action, so `READ_TOOLS` becomes a classification by `(tool,
action)` and the spectator shows one vocabulary (it gains the action next to the tool name, a small change
in `web/`). `TOOL_ALIASES` folds into the same table. A test asserts every old name maps to a row whose
validation accepts the mapped arguments. The cost of keeping them is a dict; the cost of dropping them is
every agent prompt, Codex config and transcript script in the wild that names an old tool.

Old call-ledger rows keep their old names; the spectator reads names as labels.

## Where the names live (the touch list)

Counted at 7c30a8f with `grep -rlw`, per name:

| Place | What refers to tool names |
|---|---|
| `harness/mcp_server.py` | `CORE_TOOLS` and `--tools compact` (retired: nine tools need no compact tier), `MENU_TOOLS`, `ANYTIME_TOOLS`, `WAIT_TOOLS`, `RESPONSE_TOOLS`, `SAVE_TOOLS`, `BATCH_EXCLUDED`, `TOOL_ALIASES` (all become `(tool, action)` sets), the server instructions (kept under the ~2000 characters Claude Code shows; they get shorter, since the loop is `turn` -> `question` -> `inspect` -> `order` -> `turn`) |
| `harness/gate.py` | every `clear_with`, `read_first`, `also` row and `POPUP_CHOICE_ARGS` become `(tool, args)` rows, which is what `question()` returns |
| `harness/call_ledger.py` | `READ_TOOLS` by `(tool, action)` |
| `harness/mcp_tools/*.py` | the functions stay; registration moves to `harness/surface.py` (nine tools, the action tables, per-action validation); `err` strings that name a tool are rewritten |
| `harness/briefing.py`, `harness/attention.py`, `harness/orders.py` | todo rows and refusals as `{tool, args}` rows instead of prose |
| `docs/PLAYBOOK.md`, `docs/TOOL_REPLIES.md` | served live as `reference("playbook")`; headings move to the new vocabulary |
| `docs/AGENT_INSTALL.md`, `README.md`, `docs/ARCHITECTURE.md`, `docs/LIMITATIONS.md`, `docs/GAPS.md` | prose, examples, and the two "145 tools" counts |
| `tests/` (119 files) | between 1 and 27 files per name; most tests call the handler functions, which do not move, so the bulk of the edits are in the tests of registration, the gate, the ledger and the batch |
| `scripts/mcp_session.py`, `scripts/play_loop.py`, `scripts/seat_survey.py` | call tools by name |

The Lua runtime references tool names only inside notification and refusal strings (1 to 8 files per name).
Those are updated last, in one text-only `RUNTIME_VERSION` bump with no `H.*` signature change, in a quiet
window (`docs/ROADMAP.md`, live loop deploys). Until then an old name in a runtime string names a retired
tool, which still works.

## Stages

Each stage is one or more commits on `main`, `scripts/check.sh` green, pushed; a stage that changes a reply
is checked live on the S10 save (Assyria t238) with reads only. Planned on GitLab 2026-10-25: milestone [2.0.0 The tool surface](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/milestones/11), tracking issue [#59](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/issues/59), one issue per item: stage 0 #44; stage 1 #45 (todo rows), #46 (question-shaped reads and the gate's rows), #47 (`available_*`, object reads, the live turn from rows); stage 2 #48 (`harness/surface.py`), #49 (`oneOf` on three clients), #50 (the retirement map), #51 (gate, ledger, tool sets, spectator), #52 (unregister the 145); stage 3 #53 (instructions and playbook), #54 (the other docs), #55 (`tests/test_tool_surface.py`); stage 4 #56 (the two live sessions); stage 5 #57 (the runtime strings), #58 (release 2.0.0 and the Glama marks). Work proceeds from the issues, in that order; this table is the summary.

| Stage | Work | Done when |
|---|---|---|
| 0 | `scripts/tool_survey.py`: the catalog by module, the listing's byte and token size, every name's row in the mapping table, and the affordance audit: which replies already carry `{tool, args}` rows and which carry prose | its tables are the ones in this file, checked in under `docs/measurements/` |
| 1 | affordances as data, in today's vocabulary: every todo row of `briefing`, every `question`-shaped read (`generic_popup`, the `*_options`, `discussion`) and every `available_*` reply carries `actions: [{tool, args}]`; `do` accepts them unchanged; `attention.py` reads only rows | a fake-bridge turn plays from affordance rows alone, with no tool name typed by the test; one live Assyria turn the same way through `scripts/mcp_session.py` |
| 2 | `harness/surface.py`: the nine tools as dispatchers over the existing functions, the action tables with per-action validation and the refusal that names the shape, the `oneOf` schema for `order` (checked against Claude Code, Codex and the Grok client; string fallback where `oneOf` is not rendered), the retirement map in the call wrapper with `renamed`, the gate and ledger by `(tool, action)`, the tool sets, `--tools compact` and `call` retired, the spectator's action column; the 145 are unregistered | `scripts/mcp_call.py --list` prints 9; the suite passes with the old names reaching their handlers only through the retirement map, and again with the map emptied in a fixture for the tests that use the new vocabulary |
| 3 | the words: server instructions, `docs/PLAYBOOK.md`, `docs/TOOL_REPLIES.md`, `docs/AGENT_INSTALL.md`, README examples, ARCHITECTURE; `reference("playbook", "orders")` prints the action table from the same code the validator uses; `tests/test_tool_surface.py` asserts nine listed names, every description under 2000 characters, every enum value with a line, every gate / `err` / todo row resolving to a listed tool and a valid action | a reader of the README learns the loop in four lines: `turn` -> `question` -> `inspect` -> `order` |
| 4 | live: a full Assyria turn through the nine tools from a fresh Claude Code session and a fresh Codex session; `play_loop --profile` before and after (trip count unchanged, listing size recorded) | both sessions reach a city-state gift and a league vote without a tool name they were not shown |
| 5 | runtime strings that name retired tools, one text-only `RUNTIME_VERSION` bump in a quiet window; release 2.0.0 (the listed surface changes wholesale even though every old name still runs; README release row, feature bullets, test counts, AGENT_INSTALL line 8); re-submit to Glama and record the four marks here | the new marks sit next to today's in this file |

Out of scope: the `H.*` signatures (the seat-binding route's stage 3 is a different plan and touches the
same functions from below; the two routes do not conflict, since this one only moves registration), the
reply shapes, and the spectator beyond the action column.

## Risks, and the answer to each

- **Polymorphic arguments lose client-side validation.** True for `order`'s `args`. The answer is that a
  model rarely composes an order from nothing: `inspect`, `question` and `turn("briefing")` hand it the
  row, and a refusal names the exact shape with an example. `do(actions=[{tool, args}])` has worked this
  way since 2026-09 with no stuck turns from argument shape.
- **Descriptions get long.** The nine descriptions carry the enum values one line each and nothing else;
  the per-action argument table lives in `reference("playbook", "orders")` and in refusals. The 2000
  character cut the client applies is a test.
- **A merged read costs more trips.** It does not: a `(what, view)` row dispatches to the same `H.*` entry
  its old tool called, with the same arguments. `inspect("city_state", view="full")` is the one read
  that makes more trips than any of its parts, and `summary` is the default. Stage 4 measures.
- **Prompts in the wild name the old tools.** They keep working; `renamed` in each reply is the only
  sign. `docs/AGENT_INSTALL.md` says once that the old names are retired, not removed.
- **Nine tools is far from the 145 a model may have seen in this repo's transcripts.** The action words
  are the old verbs, the reply rows are copy-and-paste, and the loop is shorter to explain than before.
  The two live sessions in stage 4 are the check; if a client plays worse, the fallback is to list
  `inspect`'s most-used views as their own tools, which is a listing choice, not a model change.
- **The runtime bump.** One, last, text only; under the digest rule it re-injects on the first runtime
  check of a process started after the edit, so the live Assyria game is left alone until a quiet window.
