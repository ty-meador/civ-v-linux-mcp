# The tool surface, measured (stage 0, GitLab #44)

Written by `scripts/tool_survey.py --write` at b624810 on 2026-10-25: 145 tools, 35 zero-argument reads. The mapping check passed (every catalog name maps to exactly one row of `harness/surface/retirement.py`, none is left over, every row speaks `harness/surface/vocabulary.py`). Re-run after any tool, docstring or map change.

## The catalog by module

A zero-argument read is a tool in the call ledger's `READ_TOOLS` whose schema has no property.

| Module | Tools | Of which zero-argument reads |
|---|---|---|
| reference | 2 | 0 |
| turn | 11 | 4 |
| batch | 2 | 0 |
| notebook | 11 | 0 |
| units | 24 | 7 |
| cities | 22 | 3 |
| policies | 21 | 7 |
| diplomacy | 36 | 10 |
| trade | 13 | 4 |
| front_end | 3 | 0 |
| total | 145 | 35 |

## Where the tools come from

The eight shapes of #44, each old name counted under the first shape it fits (`harness/surface/survey.py`, `SHAPES`).

| Shape | Count | Names |
|---|---|---|
| a popup's read + its answer, one pair per popup kind | 16 | `maya_options`, `choose_maya_bonus`, `archaeology_options`, `choose_archaeology`, `generic_popup`, `answer_popup`, `goody_hut_options`, `choose_goody_hut`, `free_great_person_options`, `choose_free_great_person`, `faith_great_person_options`, `choose_faith_great_person`, `steal_tech_options`, `steal_tech`, `city_capture_options`, `choose_city_capture` |
| one zero-argument read per overview screen | 13 | `great_person_progress`, `culture_works`, `religion_overview`, `tech_tree`, `current_deals`, `domination_progress`, `wonder_overview`, `spaceship_status`, `culture_overview`, `espionage_intrigue`, `trade_routes`, `spies`, `league_status` |
| reads of the same map at different grains | 6 | `map_window`, `explore_frontier`, `tactical_view`, `known_world`, `map_index`, `revealed_map` |
| reads of "what can this unit do" | 4 | `unit_home_options`, `unit_mission_targets`, `available_unit_actions`, `todo_actions` |
| city-state screen, one tool per button and per tooltip | 9 | `city_state_gifts`, `city_state_actions`, `city_state_action`, `gift_tile_improvement_options`, `gift_tile_improvement`, `minor_gold_gift`, `city_state_bonuses`, `gift_unit_options`, `gift_unit` |
| the trade table's buttons, one tool each | 6 | `dismiss_discussion`, `discussion`, `respond_discussion`, `incoming_deal`, `accept_deal`, `refuse_deal` |
| one write per city-screen control | 14 | `set_swappable_great_work`, `swap_great_works`, `change_specialist`, `set_auto_specialists`, `set_city_focus`, `set_avoid_growth`, `change_working_plot`, `buy_city_plot`, `city_task`, `sell_building`, `city_ranged_attack`, `set_production`, `remove_from_queue`, `purchase_production` |
| one write per empire-level decision | 10 | `choose_policy`, `unlock_policy_branch`, `choose_ideology`, `set_faith_purchase`, `change_ideology`, `add_reformation_belief`, `found_pantheon`, `found_religion`, `enhance_religion`, `set_research` |
| the rest (the loop, the notebook, the session, single reads and writes) | 67 | `how_to_play`, `reference`, `turn_status`, `briefing`, `set_seat`, `wait_for_my_turn`, `players`, `overview`, `notification_log`, `turn_digest`, `quick_save`, `end_turn`, `finish_turn`, `do`, `call`, `remember`, `recall`, `forget`, `assign`, `assignments`, `amend_assignment`, `close_assignment`, `give_order`, `orders`, `resume_order`, `cancel_order`, `units`, `choose_promotion`, `upgrade_unit`, `disband_unit`, `move_unit`, `unit_mission`, `cities`, `city_screen`, `compare`, `available_city_strikes`, `available_production`, `purchase_cost`, `available_policies`, `available_beliefs`, `available_research`, `trade_catalog`, `war_consequences`, `demographics`, `diplomacy`, `relationship`, `declare_war`, `make_peace`, `denounce`, `propose_friendship`, `accept_friendship`, `diplo_event`, `propose_deal`, `demand`, `negotiate_deal`, `available_trade_routes`, `establish_trade_route`, `plunder_trade_route`, `available_spy_cities`, `move_spy`, `stage_coup`, `league_propose_enact`, `league_propose_repeal`, `league_cast_votes`, `load_save`, `load_latest`, `exit_to_main_menu` |

## The listing's size

The `tools/list` reply as a client receives it (name, description, inputSchema; compact JSON). Tokens are bytes / 4, the estimate the server's own comment uses (no tokenizer in the venv). The longest description is `finish_turn` at 1987 characters, under the 2000 at which Claude Code cuts one, so a client that clips sees the full listing.

| Listing | Tools | Bytes | Approx. tokens |
|---|---|---|---|
| full | 145 | 112417 | 28104 |
| compact | 24 | 33341 | 8335 |

## What each of the nine tools replaces

| Tool | Replaces |
|---|---|
| turn | 8 |
| inspect | 46 |
| order | 48 |
| question | 10 |
| answer | 13 |
| notebook | 11 |
| batch | 2 |
| session | 5 |
| reference | 2 |

## Every old name and its row

The `renamed` string is what a reply to the old name will carry once the map is wired in (#50). `known_world` follows #50's table to `turn("briefing", since="turn")`, which is why `turn` replaces one more and `inspect` one fewer than the counts on #59 (8 and 46 against 7 and 47).

| Old | Module | (tool, action) / (what, view) | Renamed | Note |
|---|---|---|---|---|
| `how_to_play` | reference | reference / playbook | `reference(book="playbook")` |  |
| `reference` | reference | reference / rules | `reference(book="rules")` |  |
| `turn_status` | turn | turn / status | `turn(action="status")` |  |
| `briefing` | turn | turn / briefing | `turn(action="briefing")` |  |
| `set_seat` | turn | session / seat | `session(action="seat")` |  |
| `wait_for_my_turn` | turn | turn / wait | `turn(action="wait")` |  |
| `players` | turn | turn / status | `turn(action="status")` | `players` is a key of the status reply in hotseat games |
| `overview` | turn | inspect:empire / default | `inspect(what="empire")` |  |
| `notification_log` | turn | inspect:notifications / default | `inspect(what="notifications")` |  |
| `turn_digest` | turn | turn / briefing | `turn(action="briefing", detail="digest")` |  |
| `quick_save` | turn | session / save | `session(action="save")` |  |
| `end_turn` | turn | turn / end | `turn(action="end")` |  |
| `finish_turn` | turn | turn / finish | `turn(action="finish")` |  |
| `do` | batch | batch /  | `batch()` |  |
| `call` | batch | batch /  | `batch()` | `call(tool, args)` is one batch row; nothing is hidden once every tool is listed |
| `remember` | notebook | notebook / remember | `notebook(action="remember")` |  |
| `recall` | notebook | notebook / recall | `notebook(action="recall")` |  |
| `forget` | notebook | notebook / forget | `notebook(action="forget")` |  |
| `assign` | notebook | notebook / assign | `notebook(action="assign")` |  |
| `assignments` | notebook | notebook / assignments | `notebook(action="assignments")` |  |
| `amend_assignment` | notebook | notebook / amend | `notebook(action="amend")` |  |
| `close_assignment` | notebook | notebook / close | `notebook(action="close")` |  |
| `give_order` | notebook | notebook / give_order | `notebook(action="give_order")` |  |
| `orders` | notebook | notebook / orders | `notebook(action="orders")` |  |
| `resume_order` | notebook | notebook / resume_order | `notebook(action="resume_order")` |  |
| `cancel_order` | notebook | notebook / cancel_order | `notebook(action="cancel_order")` |  |
| `unit_home_options` | units | inspect:unit / home | `inspect(what="unit", view="home")` |  |
| `units` | units | inspect:units / default | `inspect(what="units")` |  |
| `maya_options` | units | question /  | `question()` |  |
| `choose_maya_bonus` | units | answer / <unit> | `answer(choice=<unit>)` |  |
| `archaeology_options` | units | question /  | `question()` |  |
| `choose_archaeology` | units | answer / <choice> | `answer(choice=<choice>)` |  |
| `unit_mission_targets` | units | inspect:unit / targets | `inspect(what="unit", view="targets")` |  |
| `map_window` | units | inspect:map / window | `inspect(what="map", view="window")` |  |
| `explore_frontier` | units | inspect:map / frontier | `inspect(what="map", view="frontier")` |  |
| `tactical_view` | units | inspect:unit / tactical | `inspect(what="unit", view="tactical")` |  |
| `known_world` | units | turn / briefing | `turn(action="briefing", since="turn")` | retires to the briefing plus the parts it joined |
| `map_index` | units | inspect:map / index | `inspect(what="map", view="index")` |  |
| `revealed_map` | units | inspect:map / grid | `inspect(what="map", view="grid")` |  |
| `generic_popup` | units | question /  | `question()` |  |
| `answer_popup` | units | answer / <button> | `answer(choice=<button>)` |  |
| `goody_hut_options` | units | question /  | `question()` |  |
| `choose_goody_hut` | units | answer / <goody> | `answer(choice=<goody>)` |  |
| `available_unit_actions` | units | inspect:unit / actions | `inspect(what="unit", view="actions")` |  |
| `todo_actions` | units | inspect:units / actions | `inspect(what="units", view="actions")` |  |
| `choose_promotion` | units | order:unit / promote | `order(to="unit", action="promote")` |  |
| `upgrade_unit` | units | order:unit / upgrade | `order(to="unit", action="upgrade")` |  |
| `disband_unit` | units | order:unit / disband | `order(to="unit", action="disband")` |  |
| `move_unit` | units | order:unit / move | `order(to="unit", action="move")` |  |
| `unit_mission` | units | order:unit / mission | `order(to="unit", action="mission")` |  |
| `cities` | cities | inspect:cities / default | `inspect(what="cities")` |  |
| `city_screen` | cities | inspect:city / screen | `inspect(what="city", view="screen")` |  |
| `great_person_progress` | cities | inspect:screen / great_people | `inspect(what="screen", view="great_people")` |  |
| `culture_works` | cities | inspect:screen / culture_works | `inspect(what="screen", view="culture_works")` |  |
| `set_swappable_great_work` | cities | order:city / great_work | `order(to="city", action="great_work")` | offer / clear |
| `swap_great_works` | cities | order:city / great_work | `order(to="city", action="great_work")` | swap |
| `change_specialist` | cities | order:city / specialist | `order(to="city", action="specialist")` |  |
| `set_auto_specialists` | cities | order:city / governor | `order(to="city", action="governor")` |  |
| `set_city_focus` | cities | order:city / governor | `order(to="city", action="governor")` |  |
| `set_avoid_growth` | cities | order:city / governor | `order(to="city", action="governor")` |  |
| `change_working_plot` | cities | order:city / work_plot | `order(to="city", action="work_plot")` |  |
| `buy_city_plot` | cities | order:city / buy_plot | `order(to="city", action="buy_plot")` |  |
| `city_task` | cities | order:city / status | `order(to="city", action="status")` | annex / raze / unraze |
| `sell_building` | cities | order:city / sell_building | `order(to="city", action="sell_building")` |  |
| `compare` | cities | inspect:compare / default | `inspect(what="compare")` |  |
| `city_ranged_attack` | cities | order:city / strike | `order(to="city", action="strike")` |  |
| `available_city_strikes` | cities | inspect:city / strikes | `inspect(what="city", view="strikes")` |  |
| `available_production` | cities | inspect:city / production | `inspect(what="city", view="production")` |  |
| `set_production` | cities | order:city / produce | `order(to="city", action="produce")` |  |
| `remove_from_queue` | cities | order:city / dequeue | `order(to="city", action="dequeue")` |  |
| `purchase_cost` | cities | inspect:city / production | `inspect(what="city", view="production")` | with `item` and `yield_type` |
| `purchase_production` | cities | order:city / purchase | `order(to="city", action="purchase")` |  |
| `available_policies` | policies | inspect:options / policies | `inspect(what="options", view="policies")` |  |
| `choose_policy` | policies | order:empire / policy | `order(to="empire", action="policy")` |  |
| `unlock_policy_branch` | policies | order:empire / policy | `order(to="empire", action="policy")` | a POLICY_BRANCH_* unlocks |
| `choose_ideology` | policies | order:empire / ideology | `order(to="empire", action="ideology")` |  |
| `free_great_person_options` | policies | question /  | `question()` |  |
| `choose_free_great_person` | policies | answer / <unit> | `answer(choice=<unit>)` |  |
| `religion_overview` | policies | inspect:screen / religion | `inspect(what="screen", view="religion")` |  |
| `set_faith_purchase` | policies | order:empire / faith_purchase | `order(to="empire", action="faith_purchase")` |  |
| `change_ideology` | policies | order:empire / switch_ideology | `order(to="empire", action="switch_ideology")` |  |
| `faith_great_person_options` | policies | question /  | `question()` |  |
| `choose_faith_great_person` | policies | answer / <unit> | `answer(choice=<unit>)` |  |
| `available_beliefs` | policies | inspect:options / beliefs | `inspect(what="options", view="beliefs")` |  |
| `add_reformation_belief` | policies | order:empire / reformation | `order(to="empire", action="reformation")` |  |
| `found_pantheon` | policies | order:empire / pantheon | `order(to="empire", action="pantheon")` |  |
| `found_religion` | policies | order:empire / religion | `order(to="empire", action="religion")` |  |
| `enhance_religion` | policies | order:empire / enhance_religion | `order(to="empire", action="enhance_religion")` |  |
| `available_research` | policies | inspect:options / research | `inspect(what="options", view="research")` |  |
| `tech_tree` | policies | inspect:screen / tech_tree | `inspect(what="screen", view="tech_tree")` |  |
| `steal_tech_options` | policies | question /  | `question()` |  |
| `steal_tech` | policies | answer / <tech> | `answer(choice=<tech>)` |  |
| `set_research` | policies | order:empire / research | `order(to="empire", action="research")` |  |
| `dismiss_discussion` | diplomacy | answer / leave | `answer(choice="leave")` |  |
| `discussion` | diplomacy | question /  | `question()` |  |
| `respond_discussion` | diplomacy | answer / <button_id> | `answer(choice=<button_id>)` |  |
| `incoming_deal` | diplomacy | question /  | `question()` |  |
| `current_deals` | diplomacy | inspect:screen / deals | `inspect(what="screen", view="deals")` |  |
| `accept_deal` | diplomacy | answer / accept | `answer(choice="accept")` |  |
| `refuse_deal` | diplomacy | answer / refuse | `answer(choice="refuse")` |  |
| `trade_catalog` | diplomacy | inspect:civ / trade_catalog | `inspect(what="civ", view="trade_catalog")` |  |
| `city_state_gifts` | diplomacy | inspect:city_state / full | `inspect(what="city_state", view="full")` |  |
| `city_capture_options` | diplomacy | question /  | `question()` |  |
| `choose_city_capture` | diplomacy | answer / <choice> | `answer(choice=<choice>)` |  |
| `war_consequences` | diplomacy | inspect:civ / war | `inspect(what="civ", view="war")` |  |
| `city_state_actions` | diplomacy | inspect:city_state / summary | `inspect(what="city_state", view="summary")` |  |
| `city_state_action` | diplomacy | order:city_state / <action> | `order(to="city_state", action=<action>)` |  |
| `gift_tile_improvement_options` | diplomacy | inspect:city_state / full | `inspect(what="city_state", view="full")` |  |
| `gift_tile_improvement` | diplomacy | order:city_state / gift_improvement | `order(to="city_state", action="gift_improvement")` |  |
| `minor_gold_gift` | diplomacy | order:city_state / gift_gold | `order(to="city_state", action="gift_gold")` |  |
| `demographics` | diplomacy | inspect:empire / demographics | `inspect(what="empire", view="demographics")` |  |
| `domination_progress` | diplomacy | inspect:screen / domination | `inspect(what="screen", view="domination")` |  |
| `wonder_overview` | diplomacy | inspect:screen / wonders | `inspect(what="screen", view="wonders")` |  |
| `city_state_bonuses` | diplomacy | inspect:city_state / full | `inspect(what="city_state", view="full")` |  |
| `gift_unit_options` | diplomacy | inspect:city_state / full | `inspect(what="city_state", view="full")` |  |
| `gift_unit` | diplomacy | order:city_state / gift_unit | `order(to="city_state", action="gift_unit")` |  |
| `diplomacy` | diplomacy | inspect:civs / default | `inspect(what="civs")` |  |
| `relationship` | diplomacy | inspect:civ / summary | `inspect(what="civ", view="summary")` |  |
| `declare_war` | diplomacy | order:civ / declare_war | `order(to="civ", action="declare_war")` |  |
| `make_peace` | diplomacy | order:civ / peace | `order(to="civ", action="peace")` |  |
| `denounce` | diplomacy | order:civ / denounce | `order(to="civ", action="denounce")` |  |
| `spaceship_status` | diplomacy | inspect:screen / spaceship | `inspect(what="screen", view="spaceship")` |  |
| `culture_overview` | diplomacy | inspect:screen / culture | `inspect(what="screen", view="culture")` |  |
| `propose_friendship` | diplomacy | order:civ / friendship | `order(to="civ", action="friendship")` |  |
| `accept_friendship` | diplomacy | answer / accept_friendship | `answer(choice="accept_friendship")` |  |
| `diplo_event` | diplomacy | order:civ / event | `order(to="civ", action="event")` |  |
| `propose_deal` | diplomacy | order:civ / propose_deal | `order(to="civ", action="propose_deal")` |  |
| `demand` | diplomacy | order:civ / demand | `order(to="civ", action="demand")` |  |
| `negotiate_deal` | diplomacy | order:civ / negotiate | `order(to="civ", action="negotiate")` |  |
| `espionage_intrigue` | trade | inspect:screen / intrigue | `inspect(what="screen", view="intrigue")` |  |
| `available_trade_routes` | trade | inspect:options / trade_routes | `inspect(what="options", view="trade_routes")` |  |
| `trade_routes` | trade | inspect:screen / trade_routes | `inspect(what="screen", view="trade_routes")` |  |
| `establish_trade_route` | trade | order:unit / trade_route | `order(to="unit", action="trade_route")` |  |
| `plunder_trade_route` | trade | order:unit / plunder | `order(to="unit", action="plunder")` |  |
| `spies` | trade | inspect:spies / default | `inspect(what="spies")` |  |
| `available_spy_cities` | trade | inspect:options / spy_cities | `inspect(what="options", view="spy_cities")` |  |
| `move_spy` | trade | order:spy / move | `order(to="spy", action="move")` |  |
| `stage_coup` | trade | order:spy / coup | `order(to="spy", action="coup")` |  |
| `league_status` | trade | inspect:league / default | `inspect(what="league")` |  |
| `league_propose_enact` | trade | order:league / propose | `order(to="league", action="propose")` |  |
| `league_propose_repeal` | trade | order:league / repeal | `order(to="league", action="repeal")` |  |
| `league_cast_votes` | trade | order:league / vote | `order(to="league", action="vote")` |  |
| `load_save` | front_end | session / load | `session(action="load")` |  |
| `load_latest` | front_end | session / load_latest | `session(action="load_latest")` |  |
| `exit_to_main_menu` | front_end | session / main_menu | `session(action="main_menu")` |  |

## The affordance audit

Which replies that list what can be done carry `actions: [{tool, args}]` rows, and which hand the choices back by name only (the write left to the caller). `rows` means the handler or the game mixin composing the reply emits a `{tool, args}` literal.

| Reply | Module | Row | Carries |
|---|---|---|---|
| turn_status | turn | turn / status | names only |
| briefing | turn | turn / briefing | rows |
| finish_turn | turn | turn / finish | rows |
| unit_home_options | units | inspect:unit / home | rows |
| maya_options | units | question /  | rows |
| archaeology_options | units | question /  | rows |
| unit_mission_targets | units | inspect:unit / targets | rows |
| generic_popup | units | question /  | rows |
| goody_hut_options | units | question /  | rows |
| available_unit_actions | units | inspect:unit / actions | rows |
| todo_actions | units | inspect:units / actions | rows |
| available_city_strikes | cities | inspect:city / strikes | rows |
| available_production | cities | inspect:city / production | rows |
| purchase_cost | cities | inspect:city / production | names only |
| available_policies | policies | inspect:options / policies | rows |
| free_great_person_options | policies | question /  | rows |
| faith_great_person_options | policies | question /  | rows |
| available_beliefs | policies | inspect:options / beliefs | rows |
| available_research | policies | inspect:options / research | rows |
| steal_tech_options | policies | question /  | rows |
| discussion | diplomacy | question /  | rows |
| incoming_deal | diplomacy | question /  | rows |
| trade_catalog | diplomacy | inspect:civ / trade_catalog | rows |
| city_state_gifts | diplomacy | inspect:city_state / full | rows |
| city_capture_options | diplomacy | question /  | rows |
| city_state_actions | diplomacy | inspect:city_state / summary | rows |
| gift_tile_improvement_options | diplomacy | inspect:city_state / full | rows |
| city_state_bonuses | diplomacy | inspect:city_state / full | names only |
| gift_unit_options | diplomacy | inspect:city_state / full | rows |
| available_trade_routes | trade | inspect:options / trade_routes | rows |
| available_spy_cities | trade | inspect:options / spy_cities | rows |

### By file and key

Every dict literal in `harness/` whose key says what to do next (`tool`, `hint`, `clear_with`, `read_first`, `also`), by what the value is: `name` exactly one tool name, `names` a list of them, `prose` a sentence naming a tool, `text` a sentence naming none, `dynamic` not a literal; `{tool, args}` counts row literals.

| File | Key | rows | name | names | prose | text | dynamic |
|---|---|---|---|---|---|---|---|
| harness/action_lock.py | tool |  |  |  |  |  | 1 |
| harness/briefing.py | hint |  |  |  | 1 |  | 1 |
| harness/briefing.py | tool |  |  |  | 11 |  |  |
| harness/call_ledger.py | tool |  |  |  |  |  | 1 |
| harness/game_parts/cities.py | hint |  |  |  | 1 |  |  |
| harness/game_parts/diplomacy.py | hint |  |  |  | 1 |  |  |
| harness/game_parts/events.py | hint |  |  |  | 1 |  |  |
| harness/game_parts/turn.py | hint |  |  |  | 4 |  |  |
| harness/game_parts/unit_orders.py | hint |  |  |  | 3 |  | 2 |
| harness/game_parts/units.py | {tool, args} | 1 |  |  |  |  |  |
| harness/gate.py | also |  |  | 2 |  |  |  |
| harness/gate.py | clear_with |  | 21 |  |  |  | 1 |
| harness/gate.py | read_first |  | 18 |  |  |  |  |
| harness/mcp_server.py | hint |  |  |  | 1 |  | 1 |
| harness/mcp_server.py | tool |  |  |  |  |  | 1 |
| harness/mcp_tools/batch.py | tool |  |  |  |  |  | 4 |
| harness/mcp_tools/cities.py | hint |  |  |  | 1 |  |  |
| harness/mcp_tools/front_end.py | hint |  |  |  |  |  | 1 |
| harness/mcp_tools/surface.py | tool |  |  |  |  |  | 1 |
| harness/mcp_tools/turn.py | hint |  |  |  | 1 |  | 1 |
| harness/mcp_tools/turn.py | {tool, args} | 1 |  |  |  |  |  |
| harness/orders.py | hint |  |  |  | 11 | 1 |  |
| harness/orders.py | {tool, args} | 4 |  |  |  |  |  |
| harness/rows.py | {tool, args} | 1 |  |  |  |  |  |
| harness/turn_claim.py | tool |  |  |  |  |  | 2 |

### The seam

The sites stage 1 (#45-#47) turns into rows: a tool named in a reply or a refusal as a word, not a row.

| Site | Key | Kind | Text |
|---|---|---|---|
| `harness/briefing.py:225` | tool | prose | todo_actions(detail='summary') then move_unit / unit_mission |
| `harness/briefing.py:238` | tool | prose | available_research + set_research |
| `harness/briefing.py:231` | tool | prose | choose_promotion (todo_actions lists the choices) |
| `harness/briefing.py:236` | tool | prose | available_production + set_production |
| `harness/briefing.py:245` | tool | prose | incoming_deal then accept_deal / refuse_deal |
| `harness/briefing.py:247` | tool | prose | steal_tech_options + steal_tech |
| `harness/briefing.py:252` | tool | prose | available_policies then choose_policy / unlock_policy_branch |
| `harness/briefing.py:256` | tool | prose | move_unit one unit with moves off each tile |
| `harness/briefing.py:271` | tool | prose | generic_popup / answer_popup |
| `harness/briefing.py:400` | tool | prose | available_trade_routes(unit_id={...}) then establish_trade_route(unit_id, dest_x, dest_y) or establish_trade_route(unit_id, city_name, kind) |
| `harness/briefing.py:408` | tool | prose | available_spy_cities(agent_id) then move_spy(agent_id, target_player_id, target_city_id) |
| `harness/briefing.py:461` | hint | prose | city_state_actions(player_id) says whether make_peace is offered; city_state_action(player_id, "make_peace") presses it; a peace with their ally's civ takes them along |
| `harness/game_parts/cities.py:185` | hint | prose | city_screen(city_id) lists the queue in order |
| `harness/game_parts/diplomacy.py:82` | hint | prose | city_state_gifts / minor_gold_gift to keep it |
| `harness/game_parts/events.py:32` | hint | prose | the oldest {...} events were cut (the digest keeps the newest {...}): notification_log() has every notice; briefing(since='turn') the events of this turn |
| `harness/game_parts/turn.py:599` | hint | prose | {...} events from before turn {...} were dropped: they predate the turn before the one just ended (turn {...}), so this seat's briefings already covered them; notification_log() has every notice |
| `harness/game_parts/turn.py:717` | hint | prose | the game is over: nothing more happens in it; exit_to_main_menu leaves it |
| `harness/game_parts/turn.py:661` | hint | prose | this turn began while a leader screen was being answered and nothing of yours has seen it, so it was not ended: play it (status.todo, digest), then finish_turn |
| `harness/game_parts/turn.py:701` | hint | prose | still not my turn; call finish_turn again (it will only wait, not end another turn) |
| `harness/game_parts/unit_orders.py:204` | hint | prose | resume_order hands the unit back to this order; cancel_order drops the order |
| `harness/game_parts/unit_orders.py:68` | hint | prose | replace that plot (tactical_view shows what move_unit allows) |
| `harness/game_parts/unit_orders.py:344` | hint | prose | fix what the refusal names and resume_order, or replace / cancel the order |
| `harness/gate.py:26` | clear_with | name | wait_for_my_turn |
| `harness/gate.py:51` | clear_with | name | answer_popup |
| `harness/gate.py:51` | read_first | name | generic_popup |
| `harness/gate.py:31` | clear_with | name | set_research |
| `harness/gate.py:31` | read_first | name | available_research |
| `harness/gate.py:32` | clear_with | name | set_research |
| `harness/gate.py:32` | read_first | name | available_research |
| `harness/gate.py:33` | clear_with | name | set_production |
| `harness/gate.py:33` | read_first | name | available_production |
| `harness/gate.py:34` | clear_with | name | choose_policy |
| `harness/gate.py:34` | also | names | unlock_policy_branch |
| `harness/gate.py:35` | read_first | name | available_policies |
| `harness/gate.py:36` | clear_with | name | choose_ideology |
| `harness/gate.py:39` | clear_with | name | choose_promotion |
| `harness/gate.py:39` | read_first | name | todo_actions |
| `harness/gate.py:40` | clear_with | name | found_pantheon |
| `harness/gate.py:40` | also | names | add_reformation_belief |
| `harness/gate.py:41` | read_first | name | available_beliefs |
| `harness/gate.py:42` | clear_with | name | found_religion |
| `harness/gate.py:42` | read_first | name | available_beliefs |
| `harness/gate.py:43` | clear_with | name | enhance_religion |
| `harness/gate.py:43` | read_first | name | available_beliefs |
| `harness/gate.py:44` | clear_with | name | choose_goody_hut |
| `harness/gate.py:44` | read_first | name | goody_hut_options |
| `harness/gate.py:45` | clear_with | name | choose_city_capture |
| `harness/gate.py:45` | read_first | name | city_capture_options |
| `harness/gate.py:46` | clear_with | name | choose_faith_great_person |
| `harness/gate.py:47` | read_first | name | faith_great_person_options |
| `harness/gate.py:48` | clear_with | name | choose_archaeology |
| `harness/gate.py:48` | read_first | name | archaeology_options |
| `harness/gate.py:49` | clear_with | name | choose_maya_bonus |
| `harness/gate.py:49` | read_first | name | maya_options |
| `harness/gate.py:175` | clear_with | name | load_latest |
| `harness/gate.py:221` | clear_with | name | dismiss_discussion |
| `harness/gate.py:221` | read_first | name | discussion |
| `harness/gate.py:228` | clear_with | name | accept_deal |
| `harness/gate.py:228` | read_first | name | incoming_deal |
| `harness/gate.py:234` | clear_with | name | respond_discussion |
| `harness/gate.py:234` | read_first | name | discussion |
| `harness/gate.py:246` | clear_with | name | set_research |
| `harness/gate.py:246` | read_first | name | available_research |
| `harness/mcp_server.py:357` | hint | prose | check `orders` and the units with a standing move; the turn's own orders still run |
| `harness/mcp_tools/cities.py:213` | hint | prose | available_production(city_id) lists what this city can build, by enum |
| `harness/mcp_tools/turn.py:369` | hint | prose | an order was refused, so the turn was not ended: read batch.results, re-check the state, then finish_turn again with the orders still wanted (or none) |
| `harness/orders.py:222` | hint | prose | check the unit, then resume_order (it re-checks every step against the board) or cancel_order |
| `harness/orders.py:232` | hint | prose | look at the unit (units / tactical_view), then resume_order or cancel_order |
| `harness/orders.py:245` | hint | prose | decide with tactical_view; resume_order carries on (and ignores the hostiles seen now), cancel_order drops the order |
| `harness/orders.py:253` | hint | prose | see turn_digest / tactical_view for who hit it; resume_order or replace the order |
| `harness/orders.py:257` | hint | prose | replace the order with a heal step first, or resume_order to carry on anyway |
| `harness/orders.py:330` | hint | prose | attack it yourself with move_unit, or replace the order with another destination |
| `harness/orders.py:347` | hint | prose | replace the order with a reachable plot (tactical_view shows what move_unit allows) |
| `harness/orders.py:267` | hint | prose | resume_order after moving it there, or replace the order with a move step first |
| `harness/orders.py:285` | hint | prose | available_unit_actions(unit_id) lists the builds it can start here |
| `harness/orders.py:288` | hint | prose | available_unit_actions(unit_id) lists what it can build; replace or cancel the order |
| `harness/orders.py:342` | hint | prose | move that unit off the plot and resume_order, or replace the order with another plot |
