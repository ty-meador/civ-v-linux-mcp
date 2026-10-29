"""What can be done next, as rows the model copies (GitLab #45-#47, stage 1 of "The tool surface").

A reply that lists what can be done used to say it in words ("available_production + set_production") and the
model had to turn the sentence into a call. Now the reply writes the call: a row `{tool, args}` is exactly what
`do(actions=[...])` and `finish_turn(actions=[...])` take, so a decision's rows go back into the game unchanged.
A row whose argument the model still has to pick carries `choose`: the names of the arguments the read before it
lists the values for (`set_production(city_id=7, item=<a row of available_production>)`). The shape itself is
`harness/rows.py` (a leaf); the gate's own rows are `harness/gate.py`.

This package is the one place a row is written in today's vocabulary, so stage 2 (#48) swaps the words here and
nowhere else. One module per concern:

- `decisions`: the briefing's decisions and opportunities (`harness/briefing.py`): the read, then the order;
- `units`: one unit's orders from its action row (the todo_actions summary, `available_unit_actions`);
- `questions`: a question's `answers` (a popup, a leader on screen, a deal on the table; #46);
- `choices`: every `available_*` reply, each choice row carrying `call`, the write that takes it (#47);
- `objects`: the object reads (`units`, `cities`, a city-state, a trade catalog, the league) and an order's pause (#47).

Keys a reply uses: `actions` -- a list of rows, what can be done with the object or the decision; `answers` -- the
rows that answer a question; `call` -- on one choice row, the write that takes that choice; `buy` -- a choice's
purchase; `read` -- on a choice that opens a chooser, the read of its targets. `rows_in(reply)` finds them all.
The audit (`harness/surface/audit.py`) counts a reply as carrying rows when it calls into this package or `rows`.
"""
from __future__ import annotations

from ..rows import CHOOSE, act, is_row, pick, rows_in  # noqa: F401
from .choices import (belief_rows, city_state_gift_rows, gift_tile_rows, gift_unit_rows, home_rows,  # noqa: F401
                      mission_target_rows, policy_rows, production_rows, research_rows, spy_city_rows,
                      strike_rows, trade_route_rows)
from .decisions import (great_people_in, city_production, idle_spy, idle_trade_unit, incoming_deal, policy, popup,  # noqa: F401
                        promotion, research, stacked, steal_tech, unit_orders)
from .objects import (city_rows, city_state_rows, league_rows, order_pause_rows, trade_catalog_rows,  # noqa: F401
                      unit_rows, with_object_rows)
from .questions import (FRIENDSHIP_STATE, answered, archaeology_answers, city_capture_answers,  # noqa: F401
                        discussion_answers, faith_great_person_answers, free_great_person_answers,
                        generic_popup_answers, goody_hut_answers, incoming_deal_answers, maya_answers,
                        steal_tech_answers)
from .units import build_plot_calls, COMMAND_TOOLS, action_rows, annotate_unit, unit_actions  # noqa: F401
