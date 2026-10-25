# The tool surface: from 145 tools to a catalog an agent can choose from

Written 2026-10-25 after the Glama listing (https://glama.ai/mcp/servers/ty-meador/civ-v-linux-mcp) scored the
server: completeness 5/5, naming consistency 4/5, disambiguation 3/5, tool count 1/5. The count is the one
they call extreme (their rubric wants 3-15 and flags 50+), and the other two marks are its symptoms: with
145 names the reviewer found six map reads, four status reads and four "what can this unit do" reads and
could not say from the names which to use. This document is the plan to fix all three at once. It is a
Python-and-docs change: the Lua runtime (`harness/lua/runtime/*.lua`, `H.*`) does not move, so there is no
runtime bump, no re-injection window and no live-game risk from the plan itself (`docs/ROADMAP.md`, "The
tool surface", has the stage table; this file holds the reasoning and the merge list).

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

Three things the plan builds on already exist:

- `--tools compact` (`CIV5_TOOLS=compact`) lists 24 `CORE_TOOLS` plus `call`; every hidden tool still runs
  through `call(tool, args)`, inside `do` / `finish_turn(actions)`, or by name from a client that sends it
  anyway. Measured 2026-10-03: the full listing is ~100 KB (~25k tokens) on every request of a client that
  does not defer schemas; compact is a quarter of that.
- `TOOL_ALIASES` and `unknown_tool_hint` (`harness/mcp_server.py`): a wrong name gets "Did you mean".
  `alias_arguments` does the same for argument names. Neither runs the aliased tool; the plan makes them.
- `harness/gate.py` already pairs every blocking popup with its read (`read_first`) and its answer
  (`clear_with`). That table is the dispatch a merged `popup()` / `answer_popup()` needs.

Where the 145 come from, counted by hand from the catalog:

| Shape | Count | Example |
|---|---|---|
| a popup's read + its answer, one pair per popup kind | 16 | `goody_hut_options` / `choose_goody_hut` |
| one zero-argument read per overview screen | 13 | `culture_overview`, `spaceship_status`, `wonder_overview` |
| reads of the same map at different grains | 6 | `known_world`, `map_window`, `revealed_map`, `map_index`, `explore_frontier`, `tactical_view` |
| reads of "what can this unit do" | 4 | `available_unit_actions`, `todo_actions`, `unit_mission_targets`, `unit_home_options` |
| city-state screen, one tool per button and per tooltip | 9 | `city_state_gifts`, `gift_unit_options`, `gift_unit`, `minor_gold_gift` |
| the trade table's buttons, one tool each | 6 | `incoming_deal`, `accept_deal`, `refuse_deal`, `dismiss_discussion` |
| status reads that overlap | 4 | `turn_status`, `briefing`, `turn_digest`, `players` |
| city-screen toggles, one tool per checkbox | 3 | `set_city_focus`, `set_avoid_growth`, `set_auto_specialists` |

Each row was a reasonable decision on its own day: a tool per screen button keeps the engine rule behind
that button in one place (`docs/GAPS.md` records why each exists). The cost shows up only in the aggregate,
which is what the listing is.

## The three rules the new catalog follows

**Naming.** A read is a noun (`units`, `cities`, `map`, `screen`, `diplomacy`, `spies`); a write is a verb
phrase (`move_unit`, `set_production`, `declare_war`). `available_<noun>` is kept only where a verb tool
consumes it (`available_production` feeds `set_production`, `available_research` feeds `set_research`,
`available_policies` feeds `choose_policy`, `available_beliefs` feeds `found_pantheon` and the religion
tools, `available_trade_routes` feeds `establish_trade_route`). `*_options` goes away entirely: the popup
ones become `popup()`, the city-state ones become `city_state(player_id)`, the unit one becomes a
`unit_actions(mission=...)` read. `choose_*` is kept only for a choice that clears a blocking
(`choose_policy`, `choose_ideology`, `choose_promotion`). The domain prefixes stay where the domain is the
thing a model scans for (`city_state_*`, `league_*`): that is the "predictable prefixes" the reviewer
credited and a verb-first rename would spread them across the alphabet. The bare names the reviewer
flagged get a verb: `do` -> `do_actions`, `city_task` -> `set_city_status`, `demand` -> `demand_tribute`,
`diplo_event` -> `diplomacy_action`. `compare`, `assign`, `remember`, `recall`, `forget`, `call` are verbs
already and stay.

**One tool per decision, not per button.** Where several tools read the same screen or answer the same
popup, one tool with a `kind` / `name` / `view` enum replaces them, and the enum's description carries one
line per value. The enum is what a model reads well: fifteen values in one schema beat fifteen names in a
list of 145. The merge never adds a tuner trip: a merged read dispatches to the same `H.*` entry its
predecessor called, with the same arguments, so the trip count memory (`play_loop --profile`) stays as
measured.

**A description says when to use the sibling.** Every description's first sentence says what the tool
returns or does, under 160 characters, and where a sibling exists the second sentence names it: "for one
unit's move or attack, `tactical_view`; for where the known map ends, `map(view="frontier")`". A test
enforces the length and the cross-reference for each family named below. `how_to_play("tools")` serves the
family table (the same one as below, one line per tool) so a model that is unsure reads one topic instead
of twenty descriptions.

## The merge list

Before -> after, by family. "Absorbed" names stay callable forever through the retirement map (next
section) and are never listed again. Counts are listed tools.

| Family | Before (count) | After (count) | How |
|---|---|---|---|
| overview screens | `tech_tree`, `religion_overview`, `culture_overview`, `culture_works`, `great_person_progress`, `demographics`, `domination_progress`, `spaceship_status`, `wonder_overview`, `espionage_intrigue`, `trade_routes`, `current_deals`, `league_status` (13) | `screen(name)` (1) | all thirteen take no argument and each is one `H.*` read; `name` is an enum with one line per value; the reply is unchanged per screen |
| blocking popups | `generic_popup`, `answer_popup`, `goody_hut_options`, `choose_goody_hut`, `maya_options`, `choose_maya_bonus`, `archaeology_options`, `choose_archaeology`, `city_capture_options`, `choose_city_capture`, `faith_great_person_options`, `choose_faith_great_person`, `free_great_person_options`, `choose_free_great_person`, `steal_tech_options`, `steal_tech` (16) | `popup()`, `answer_popup(choice, x=, y=, player_id=)` (2) | `popup()` reads whichever popup `turn_status.pending_popups` / the gate names (the gate's `read_first` table is the dispatch) and its reply states the exact `answer_popup` call; `answer_popup` routes on the open popup: `choice` is the button number, the UNIT_ / TECH_ / goody name or liberate/annex/puppet/raze, `x`,`y` for a dig, `player_id` for a stolen tech; the per-popup `H.*` writes stay |
| map reads | `known_world`, `map_window`, `revealed_map`, `map_index`, `explore_frontier`, `tactical_view` (6) | `map(view, x=, y=, radius=, layers=, box=, unit_id=, limit=)`, `tactical_view` (2) | `view` is `window` (the old `map_window`), `grid` (`revealed_map`), `index` (`map_index`), `frontier` (`explore_frontier`, needs `unit_id`); `known_world` is retired outright, its parts are `overview` + `units` + `cities` + `diplomacy` + `notification_log` + `map(view="grid")` and `briefing(since="turn")` is the context-reset read the instructions already point at; `tactical_view` stays its own tool because it is the one named in the server instructions before every move |
| what a unit can do | `available_unit_actions`, `todo_actions`, `unit_mission_targets`, `unit_home_options` (4) | `unit_actions(unit_ids=, full=, detail=, limit=, mission=)` (1) | `todo_actions` already generalises `available_unit_actions` (`unit_ids=[id], full=true`); with `mission=` the reply is that mission's legal targets (air strike, rebase, paradrop, change home / port), which is what the two `*_targets` / `*_options` tools returned |
| city-state screen | `city_state_actions`, `city_state_bonuses`, `city_state_gifts`, `gift_unit_options`, `gift_tile_improvement_options`, `city_state_action`, `minor_gold_gift`, `gift_unit`, `gift_tile_improvement` (9) | `city_state(player_id, detail=)`, `city_state_action(player_id, action, amount=, unit_id=, x=, y=)` (2) | `detail="summary"` is the old `city_state_actions` + `city_state_gifts` (two trips as before); `detail="full"` adds bonuses and both gift lists; `action` gains `gift_gold`, `gift_unit`, `gift_improvement` next to the existing screen buttons, each still running its own `H.*` write and the one-gift-at-a-time rule |
| the trade table | `discussion`, `incoming_deal`, `respond_discussion`, `accept_deal`, `refuse_deal`, `accept_friendship`, `dismiss_discussion` (7) | `discussion()`, `respond_discussion(button_id=, answer=, expect=)` (2) | `discussion()` already shows the deal on a trade screen, so `incoming_deal` is its `deal` key; `answer` is `accept` / `refuse` / `leave` / `accept_friendship` for the screens that have no numbered buttons, `button_id` stays for the ones that do; the gate's `clear_with` rows point at the two names |
| status | `turn_status`, `briefing`, `turn_digest`, `players`, `overview`, `notification_log`, `end_turn`, `finish_turn` (8) | `turn_status`, `briefing`, `overview`, `notification_log`, `finish_turn` (5) | `players` becomes `turn_status.players` (hotseat only, it is the same read); `turn_digest` becomes `briefing(detail="digest")`, since `briefing` already carries "what changed" and `finish_turn` returns the digest; `end_turn` becomes `finish_turn(wait=false)` (`end_turn` ends the turn and returns; `finish_turn` is that followed by `wait_for_my_turn` and the new turn's read, with the same `turn_claim` and autosave rules) |
| who I stand with | `diplomacy`, `relationship`, `war_consequences` (3) | `diplomacy(player_id=, detail=)` (1) | no id: the old table of everyone met; an id: the old `relationship`; `detail="war"` adds the declare-war confirmation text the old `war_consequences` read, still to be read before `declare_war` (the PLAYBOOK sentence moves with it) |
| city governor | `set_city_focus`, `set_avoid_growth`, `set_auto_specialists` (3) | `set_city_governor(city_id, focus=, avoid_growth=, auto_specialists=)` (1) | each given argument runs its old write; the puppet rule stays one refusal |
| production cost | `available_production`, `purchase_cost` (2) | `available_production(city_id, yield_type=)` (1) | the list already carries the gold price; `yield_type="FAITH"` lists the faith price and purchasability, which is what `purchase_cost` added |
| great works swap | `set_swappable_great_work`, `swap_great_works` (2) | `swap_great_works(action, work_class=, work_id=, their_work_id=)` (1) | `action` is `offer` / `clear` / `swap` |
| policy branch | `choose_policy`, `unlock_policy_branch` (2) | `choose_policy(policy)` (1) | a `POLICY_BRANCH_*` name unlocks the branch, a `POLICY_*` name adopts (the gate's `also` row already lists both for one popup) |
| spies | `spies`, `available_spy_cities` (2) | `spies(agent_id=)` (1) | with an id the reply adds that spy's legal destinations |
| World Congress proposals | `league_propose_enact`, `league_propose_repeal` (2) | `league_propose(resolution_type=, choice=, repeal_id=)` (1) | one of `resolution_type` or `repeal_id` |
| assignments | `assign`, `amend_assignment` (2) | `assign(..., replace_id=)` (1) | `assign` already has `replace_id`; `amend_assignment` is `assign` with the unchanged fields copied, which the merged tool does when only some fields are given |
| renamed, not merged | `do`, `city_task`, `demand`, `diplo_event` (4) | `do_actions`, `set_city_status`, `demand_tribute`, `diplomacy_action` (4) | the four bare names the reviewer flagged |

Unchanged: `how_to_play`, `reference`, `wait_for_my_turn`, `quick_save`, `set_seat`, `call`, the notebook
(`remember`, `recall`, `forget`, `assignments`, `close_assignment`, `give_order`, `orders`, `cancel_order`,
`resume_order`), the unit orders (`units`, `move_unit`, `unit_mission`, `choose_promotion`, `upgrade_unit`,
`disband_unit`), the city writes (`cities`, `city_screen`, `set_production`, `purchase_production`,
`remove_from_queue`, `sell_building`, `buy_city_plot`, `change_specialist`, `change_working_plot`,
`available_city_strikes` with `city_ranged_attack`, `compare`), research and policy (`available_policies`, `choose_ideology`,
`change_ideology`, `available_research`, `set_research`, `available_beliefs`, `found_pantheon`,
`found_religion`, `enhance_religion`, `add_reformation_belief`, `set_faith_purchase`), the rest of
diplomacy (`trade_catalog`, `negotiate_deal`, `propose_deal`, `make_peace`, `propose_friendship`,
`declare_war`, `denounce`), trade and espionage (`available_trade_routes`, `establish_trade_route`,
`plunder_trade_route`, `move_spy`, `stage_coup`, `league_cast_votes`) and the front end (`load_save`,
`load_latest`, `exit_to_main_menu`).

Result: **87 tools**: 145 names, 66 absorbed, 8 merged tools added (`screen`, `popup`, `answer_popup`
keeping its name, `map`, `unit_actions`, `city_state`, `set_city_governor`, `league_propose`). By module:
turn 8, batch 2, notebook 10, units 11, cities 16, policies 12, screens 1, diplomacy 14, trade 8, front
end 3, reference 2. (Checked by script against the live catalog on 2026-10-25, not by hand.)

Merges considered and not taken, so nobody re-opens them:

- `move_unit` into `unit_mission(mission="MISSION_MOVE_TO")`: `move_unit` is the most-called order and the
  one every doc example starts with; the saving is one name.
- `choose_ideology` and `change_ideology` into one: a switch costs anarchy turns and the Lua path differs; a
  model should not reach a switch by omitting an argument.
- `found_religion` and `enhance_religion`: different blockings, different belief kinds, one tool would need
  the popup to say which arguments apply. The popup rule above covers choosers, not these.
- `cancel_order` / `resume_order` into one `order_control`: two verbs, both rare, both clear.
- `declare_war(confirm=false)` as the dry run instead of `diplomacy(detail="war")`: a write tool that
  sometimes reads is the one shape the house rule (reads are nouns) exists to prevent.
- the notebook into one `notebook(action)`: `remember` / `recall` / `forget` are the three names most agents
  use without reading a description; they are the model of a good small verb.

## What a client is shown: three listings

The count a reviewer scores is `tools/list` on a default start. Consolidation brings the real catalog to 87,
which their rubric still calls 50+; the second lever is which of the 87 are listed by default, and the
machinery for that (`apply_toolset`, `_HIDDEN`, `call`) is already in production as `--tools compact`.

| `--tools` | Lists | For |
|---|---|---|
| `compact` | the 24 `CORE_TOOLS` + `call` (today's set, names updated) | clients that resend every schema on every request |
| `standard` (**the new default**) | about 40: `compact` plus every tool a gate's `clear_with` / `read_first` names, every `available_*`, `popup` / `answer_popup`, `map`, `screen`, `diplomacy`, `city_state`, `trade_catalog` / `negotiate_deal` / `propose_deal`, `spies`, `quick_save`, `set_seat`, the notebook | the turn loop with nothing hidden that a gate or a todo hands out |
| `full` | all 87 | the old default; `scripts/mcp_call.py --list` and the tests use it |

The rule for `standard`: a listed tool is one the loop, a gate, `unit_actions` or a `briefing` todo can name
in a reply. Anything a model reaches only after reading a screen (great-works swap, league proposals,
espionage, city-state gifts, archaeology, the front end) is one `call(tool, args)` away, and the reply that
leads there says so by name, as `COMPACT_NOTE` does today. `call(describe=true)` on any hidden name returns
its schema; `how_to_play("tools")` lists all 87 by family with one line each. The standard list is tested
to be a superset of every name `harness/gate.py` can emit, so a model is never pointed at a tool it cannot
see.

Why `standard` is the default and not `compact`: in compact mode a model's first `set_production` after a
gate is a `call()` with a hand-typed argument object, which is a worse experience than one more listed
name; standard lists what the loop hands out and hides only what a screen hands out. Why not `full`: 87
listed names is still the listing the reviewer read, and the ~100 KB per request on a non-deferring client
is real money per turn.

## Retirement, not removal

Every absorbed and renamed name stays callable, forever, through one map in `harness/mcp_server.py`:

```
RETIRED = {"turn_digest": ("briefing", lambda a: {**a, "detail": "digest"}),
           "map_window":  ("map",      lambda a: {**a, "view": "window"}),
           "do":          ("do_actions", None), ...}
```

The call wrapper (`_hint_unknown_tools`) runs the target with the mapped arguments and appends
`"renamed": "map(view=\"window\")"` to the reply. The retired name is never in a listing, `call(describe=true)`
on it returns the replacement's schema, `unknown_tool_hint` folds `TOOL_ALIASES` into the same map, and the
call ledger records the call under the new name (so `READ_TOOLS` and the spectator see one vocabulary). A
test asserts every retired name maps to a listed-or-full tool with a schema that accepts the mapped
arguments. The cost of keeping them is a dict; the cost of dropping them is every agent prompt, Codex
config and transcript analysis script in the wild that names the old tool.

Old call-ledger rows keep their old names; the spectator reads names as labels and needs no change.

## Where the names live (the touch list)

A rename touches more than the tool function. Counted at 7c30a8f with `grep -rlw`, per name:

| Place | What refers to tool names |
|---|---|
| `harness/mcp_server.py` | `CORE_TOOLS`, `MENU_TOOLS`, `ANYTIME_TOOLS`, `WAIT_TOOLS`, `RESPONSE_TOOLS`, `SAVE_TOOLS`, `BATCH_EXCLUDED`, `TOOL_ALIASES`, the server instructions (kept under the ~2000 characters Claude Code shows) |
| `harness/gate.py` | every `clear_with`, `read_first`, `also` row and the `POPUP_CHOICE_ARGS` hints |
| `harness/call_ledger.py` | `READ_TOOLS` (the read/write classification the ledger and spectator use) |
| `harness/mcp_tools/*.py` | the functions themselves and the cross-references inside descriptions and refusal texts (`err` strings name the tool to use instead) |
| `harness/briefing.py`, `harness/attention.py`, `harness/orders.py` | todo rows and refusals that name a tool |
| `docs/PLAYBOOK.md`, `docs/TOOL_REPLIES.md` | served live as `how_to_play`; the `## <tool>` headings of TOOL_REPLIES are topic names |
| `docs/AGENT_INSTALL.md`, `README.md`, `docs/ARCHITECTURE.md`, `docs/LIMITATIONS.md`, `docs/GAPS.md` | prose and the two "145 tools" counts |
| `tests/` (119 files) | between 1 and 27 files per name (`turn_status` 27, `overview` 19, `briefing` 16, `available_unit_actions` 14; the popup pairs 2 each) |
| `scripts/mcp_session.py`, `scripts/play_loop.py`, `scripts/seat_survey.py` | call tools by name |

The Lua runtime references tool names only inside notification and refusal strings (1 to 8 files per name);
those strings are updated in the same commits, which is a runtime text change and so a `RUNTIME_VERSION`
bump after all, but one, at the end, with no `H.*` signature change: it re-injects under the digest rule
and needs the usual quiet window (`docs/ROADMAP.md`, live loop deploys). Until then the old string names a
retired tool, which still works.

## Stages

Each stage is one or more commits on `main`, `scripts/check.sh` green, pushed; a stage that changes a reply
shape is checked live on the S10 save (Assyria t238) with reads only.

| Stage | Work | Done when |
|---|---|---|
| 0 | `scripts/tool_survey.py`: the catalog by module, the listing's byte and token size per `--tools` mode, every name classified by shape (noun read / `available_` / `_options` / `choose_` / verb write / bare), every description's first-sentence length, and which names each description, gate row and `err` string refers to | the three tables above are its output, checked in under `docs/measurements/` |
| 1 | the rules as tests: `tests/test_tool_surface.py` asserts name shapes against the allow-list, first sentences under 160 characters, the sibling cross-reference for each family in the merge list, every gate / `err` / todo name resolves to a listed-or-retired tool, and the standard listing is a superset of what the gate emits | the test fails on `main` today for the names the plan retires, and nothing else |
| 2 | the retirement map: `RETIRED` with argument mappers, the wrapper runs the target and adds `renamed`, `call(describe=true)` on a retired name, the ledger records the new name, `TOOL_ALIASES` folded in; the four plain renames (`do_actions`, `set_city_status`, `demand_tribute`, `diplomacy_action`) ride on it | `call("turn_state")` runs `turn_status` with `renamed` in the reply; `do` and `do_actions` are one function |
| 3 | the merges, one commit each, cheapest in test count first: screens (13 -> 1), popups (16 -> 2), map (6 -> 2), unit actions (4 -> 1), city-state (9 -> 2), the trade table (7 -> 2), status (8 -> 5), diplomacy (3 -> 1), governor (3 -> 1), the five small ones; each commit moves the gate rows, `READ_TOOLS`, the tool sets, PLAYBOOK / TOOL_REPLIES / AGENT_INSTALL prose and the tests, and retires the old names | `scripts/mcp_call.py --list` prints 87; one full turn of the Assyria game played through the loop with the new names only (`scripts/mcp_session.py`), and the fake-bridge turn tests pass with `RETIRED` emptied in a fixture (nothing left depends on an old name) |
| 4 | the listings: `--tools standard` as the default, `compact` and `full` kept; the superset test from stage 1 turned on; `COMPACT_NOTE` generalised to say which listing is up; `how_to_play("tools")` serves the family table; AGENT_INSTALL and README counts | a fresh Claude Code session sees ~40 tools, plays a turn, and reaches `swap_great_works` through `call` from the reply that named it |
| 5 | the runtime strings that name retired tools, one `RUNTIME_VERSION` bump in a quiet window; release 1.17.0 (README release row, feature bullets, test counts, AGENT_INSTALL line 8); re-submit the Glama listing and record its four marks here | the four marks are in this file next to today's |

What stays out of scope: the Lua `H.*` signatures (that is the seat-binding route's stage 3, a different
plan), the reply shapes of tools that merely moved under a new name (a `screen("league")` reply is today's
`league_status` reply byte for byte, so `docs/TOOL_REPLIES.md` keeps its keys), and the spectator.

## Risks, and the answer to each

- **A merged read costs more trips.** It does not: `screen`, `map`, `popup`, `unit_actions` dispatch on
  their enum to the same `H.*` entry with the same arguments. `city_state(detail="full")` is the one
  read that makes more trips than any of its parts, and `summary` is the default. Stage 3 runs
  `play_loop --profile` before and after.
- **A model types `screen("culture")` for a name that is `culture_overview` in its training.** The enum
  value list is in the schema; a wrong value gets the valid list back in `err`, as every enum refusal
  does today; and `call("culture_overview")` still works through `RETIRED`.
- **Hidden tools in `standard` cost a round trip through `call`.** Only for tools a screen hands out, and
  the reply that hands them out names them; measured in compact mode since 2026-10-03 with no stuck turns.
- **Prompts in the wild name the old tools.** They keep working; the `renamed` key in each reply is the
  only sign. The README's examples change in stage 3; `docs/AGENT_INSTALL.md` says once that the old
  names are retired, not removed.
- **The runtime bump.** One, last, text only; under the digest rule it re-injects on the first runtime
  check of a process started after the edit, so the live Assyria game is left alone until a quiet window.
