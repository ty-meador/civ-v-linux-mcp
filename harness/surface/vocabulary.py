"""The nine-tool vocabulary (GitLab #48): data only.

A game of Civilization V from one seat is a clock, a world of objects each carrying the actions the engine
allows right now, the questions the game asks, the player's notebook and the session. The surface is nine
tools; this module holds their words. Nothing here dispatches: `harness.surface.retirement` maps the old
names onto these words and stage 2a attaches the handlers. A new game feature is a new view or action in
this file, never a new tool.
"""
from __future__ import annotations

TOOLS = ("turn", "inspect", "order", "question", "answer", "notebook", "batch", "session", "reference")

#: `turn(action)`: the clock.
TURN_ACTIONS = ("status", "briefing", "finish", "end", "wait")

#: The view an `inspect` with no `view` argument returns.
DEFAULT = "default"

#: `inspect(what, id=, view=)`: every object and its views. `home` on `unit` is the one view #48 did not list
#: (today's `unit_home_options`, a trade unit's or Great Admiral's re-homing choices); the survey records it.
VIEWS: dict[str, tuple[str, ...]] = {
    "empire": (DEFAULT, "demographics"),
    "notifications": (DEFAULT,),
    "screen": ("tech_tree", "religion", "culture", "culture_works", "great_people", "domination", "spaceship",
               "wonders", "intrigue", "trade_routes", "deals"),
    "league": (DEFAULT,),
    "spies": (DEFAULT,),
    "units": (DEFAULT, "actions"),
    "unit": ("actions", "targets", "tactical", "home"),   # one unit's own row is in `units`
    "cities": (DEFAULT,),
    "city": ("screen", "production", "strikes"),   # one city's own row is in `cities`
    "map": ("window", "grid", "index", "frontier"),
    "civs": (DEFAULT,),
    "civ": ("summary", "war", "trade_catalog"),
    "city_state": ("summary", "full"),
    "options": ("research", "policies", "beliefs", "trade_routes", "spy_cities"),
    "compare": (DEFAULT,),
}

#: A city-state order named by the screen's own button (today's `city_state_action(player_id, action)`).
SCREEN_BUTTON = "<button>"

#: `order(to, id=, action, args={})`: every target I own and the orders it takes.
ACTIONS: dict[str, tuple[str, ...]] = {
    "unit": ("move", "mission", "promote", "upgrade", "disband", "trade_route", "plunder"),
    "city": ("produce", "purchase", "dequeue", "sell_building", "buy_plot", "specialist", "work_plot",
             "governor", "status", "strike", "great_work"),
    "empire": ("research", "policy", "ideology", "switch_ideology", "pantheon", "religion", "enhance_religion",
               "reformation", "faith_purchase"),
    "civ": ("propose_deal", "negotiate", "peace", "demand", "friendship", "declare_war", "denounce", "event"),
    "city_state": (SCREEN_BUTTON, "gift_gold", "gift_unit", "gift_improvement"),
    "league": ("propose", "repeal", "vote"),
    "spy": ("move", "coup"),
}

#: `answer(choice, args={})` on a leader screen; a popup's answer is its button number or the item's name
#: (a `UNIT_` / `TECH_` / goody name, `liberate` / `annex` / `puppet` / `raze`), taken from the question's rows.
ANSWER_CHOICES = ("accept", "refuse", "leave", "accept_friendship")

#: `notebook(action, ...)`: my own memory.
NOTEBOOK_ACTIONS = ("remember", "recall", "forget", "assign", "assignments", "amend", "close",
                    "give_order", "orders", "cancel_order", "resume_order")

#: `session(action, ...)`: saves, loads, the seat.
SESSION_ACTIONS = ("save", "load", "load_latest", "main_menu", "seat")

#: `reference(book, section=)`: the rule book and the playbook.
BOOKS = ("rules", "playbook")

#: The arguments each tool takes at its top level beside its fixed words (what / view, to / action, action,
#: choice, book); every other argument of the old call rides under `args`. The registered schemas agree with
#: this table (tests/test_tool_surface.py), and every `{tool, args}` row a reply hands back is written from it.
TOP_LEVEL: dict[str, tuple[str, ...]] = {
    "turn": ("actions", "since", "limit", "detail", "notes", "timeout_seconds"),
    "inspect": ("id", "x", "y", "radius", "mission", "kind", "detail", "since", "limit", "item", "yield_type"),
    "order": ("id",),
    "question": (),
    "answer": (),
    "notebook": (),
    "batch": ("actions", "stop_on_refusal", "force"),
    "session": (),
    "reference": ("section",),
}
#: The tools whose old call's remaining arguments nest under `args`.
TAKES_ARGS = ("turn", "inspect", "order", "answer", "notebook", "session")
