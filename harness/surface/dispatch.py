"""The nine tools' routing onto today's handlers (GitLab #48, stage 2a).

`harness.surface.retirement.RETIRED` maps each old name onto its row in the new surface; read the other way it
says which old handler a new call runs: `state(what="screen", view="league")` is `league_status()`,
`order(to="city", id=3, action="produce", args={"item": ...})` is `set_production(city_id=3, item=...)`. This
module does that inversion once (the index), renames the arguments back (`id` -> `city_id`), picks among the
old names that share a row (a city's `governor` is three old tools, told apart by the argument given), and
hands back a `Call` the tool module runs through the server's own runner -- so the old handler, its guard,
its ledger row and its reply are exactly what they were. Nothing here touches the game.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from harness import gate as G
from harness.surface import retirement as R
from harness.surface import vocabulary as V
from harness.surface.forward import example, old_name
from harness.surface.schemas import properties, required, schema, signature

__all__ = ["Call", "Composite", "Refusal", "merge_parts", "GIFT_UNITS_SHOWN", "INDEX", "DISAMBIGUATE", "resolve", "old_call", "pick", "old_args", "answer",
           "question_read", "choice_arg", "fixed_answers", "shape_refusal", "words",
           "example", "schema", "signature", "required", "properties"]


@dataclass(frozen=True)
class Call:
    """One old call to run: the registered tool's name and its arguments."""
    tool: str
    args: dict


@dataclass(frozen=True)
class Composite:
    """Several old calls whose replies merge into one (`state("city_state", view="full")`); `merge_parts` makes
    the one reply. `all_units`: list every giftable unit instead of the first few (GitLab #65)."""
    parts: dict[str, Call]
    all_units: bool = False


@dataclass(frozen=True)
class Refusal:
    """Why a new call cannot be routed, with the shape it should have had."""
    err: str
    accepts: Any = None
    example: dict | None = None
    choices: list | None = None
    hint: str | None = None

    def reply(self) -> dict:
        out: dict[str, Any] = {"ok": False, "err": self.err}
        if self.hint is not None:
            out["hint"] = self.hint
        if self.accepts is not None:
            out["accepts"] = self.accepts
        if self.example is not None:
            out["example"] = self.example
        if self.choices is not None:
            out["choices"] = self.choices
        return out


# --- the index -------------------------------------------------------------------------------------------
def _key(tool: str, fixed: dict) -> tuple[str, str]:
    """The `(tool, action)` / `(what, view)` label of a new call, as `Row.key` labels the rows."""
    return R.Row(tool, fixed).key


def by_key() -> dict[tuple[str, str], list[str]]:
    """Row key -> the old names that share it, in catalog order."""
    out: dict[tuple[str, str], list[str]] = {}
    for name, row in R.RETIRED.items():
        out.setdefault(row.key, []).append(name)
    return out


INDEX = by_key()

#: The one old name a shared key means when the arguments do not say (`players` is a key of the status reply;
#: `known_world` retired to the briefing), or how the arguments tell the old names apart.
Choose = Callable[[dict], str | None]
DISAMBIGUATE: dict[tuple[str, str], Choose] = {
    ("turn", "status"): lambda a: "turn_status",
    ("turn", "briefing"): lambda a: "turn_digest" if a.get("detail") == "digest" else "briefing",
    ("state:empire", V.DEFAULT): lambda a: "overview",
    ("state:city", "production"): lambda a: "purchase_cost" if a.get("item") else "available_production",
    ("order:city", "governor"): lambda a: ("set_city_focus" if "focus" in a else "set_avoid_growth" if "avoid" in a
                                           else "set_auto_specialists" if "automatic" in a else None),
    ("order:city", "great_work"): lambda a: "swap_great_works" if "their_work_id" in a else "set_swappable_great_work",
    ("order:empire", "policy"): lambda a: ("unlock_policy_branch"
                                           if str(a.get("policy") or a.get("branch") or "").startswith("POLICY_BRANCH_")
                                           else "choose_policy"),
}
#: `state("city_state", view="full")`: the one read that makes more trips than any of its parts, merged
#: under these keys (the summary first).
CITY_STATE_FULL = {"summary": "city_state_actions", "gifts": "city_state_gifts", "bonuses": "city_state_bonuses",
                   "gift_units": "gift_unit_options", "gift_tiles": "gift_tile_improvement_options"}

#: How many giftable units the full city-state view lists (the runtime orders them: an upgrade passed by first,
#: then the weakest); the rest is a count and the drill-down (GitLab #65: 39 units, each a full call row, ~4 KB).
GIFT_UNITS_SHOWN = 6


def merge_parts(parts: dict, all_units: bool = False) -> dict:
    """The one reply of `state("city_state", view="full")` from its parts' replies (GitLab #65: the parts said
    the same things twice). The resource tiles stay under `gift_tiles` only (the summary's gift_tile_improvement
    status keeps its `why_not` and says where the tiles are); `gift_units.units` is the first GIFT_UNITS_SHOWN
    unless `all_units`, with `units_total` and the drill-down."""
    parts = dict(parts)
    summary, tiles, units = parts.get("summary"), parts.get("gift_tiles"), parts.get("gift_units")
    if isinstance(summary, dict) and isinstance(summary.get("gift_tile_improvement"), dict) \
            and isinstance(tiles, dict) and tiles.get("resource_tiles") is not None:
        status = dict(summary["gift_tile_improvement"])
        if status.pop("resource_tiles", None) is not None:
            status.pop("search_radius", None)
            status["resource_tiles_in"] = "gift_tiles"
            parts["summary"] = {**summary, "gift_tile_improvement": status}
    if isinstance(units, dict) and isinstance(units.get("units"), list):
        rows = units["units"]
        if len(rows) > GIFT_UNITS_SHOWN and not all_units:
            parts["gift_units"] = {**units, "units": rows[:GIFT_UNITS_SHOWN], "units_total": len(rows),
                                   "units_omitted": len(rows) - GIFT_UNITS_SHOWN,
                                   "more": "the first are the ones to gift (an upgrade passed by, then the weakest); "
                                           "every unit: the same read with args={'all_units': true}"}
    ok = all(isinstance(p, dict) and p.get("ok") is not False for p in parts.values())
    return {"ok": ok, **parts}


#: The argument that carries the choice when a popup's resolver is an order tool (an `answer` row's FromArg
#: says it for the answer tools: choose_goody_hut(goody), choose_archaeology(choice), ...).
ORDER_CHOICE_ARG = {"set_production": "item", "set_research": "tech", "choose_policy": "policy",
                    "unlock_policy_branch": "branch", "choose_ideology": "branch", "choose_promotion": "promotion",
                    "found_pantheon": "belief", "found_religion": "religion", "enhance_religion": "religion",
                    "add_reformation_belief": "belief"}


def choice_arg(old: str) -> str | None:
    row = R.RETIRED.get(old)
    if row is not None and row.tool == "answer" and isinstance(row.fixed.get("choice"), R.FromArg):
        return row.fixed["choice"].name
    return ORDER_CHOICE_ARG.get(old)


def fixed_answers() -> dict[str, str]:
    """choice word -> the old tool it always means (accept, refuse, leave, accept_friendship)."""
    return {row.fixed["choice"]: name for name, row in R.RETIRED.items()
            if row.tool == "answer" and isinstance(row.fixed.get("choice"), str)}


# --- renaming and picking ---------------------------------------------------------------------------------
def old_args(old: str, args: dict) -> dict:
    """The new call's arguments under the old handler's names (`id` -> `city_id`), None values dropped."""
    row = R.RETIRED[old]
    back = {new: o for o, new in row.renames.items()}
    out = {}
    for k, v in (args or {}).items():
        if v is None or (k in row.fixed and row.fixed[k] == v):   # a selector the row itself fixes (detail="digest")
            continue
        out[back.get(k, k)] = v
    return out


def _fits(old: str, args: dict) -> bool:
    given = set(old_args(old, args))
    return required(old) <= given and given <= properties(old)


#: Where an `state` object's ids come from (a Grok session spent four calls finding the city-state one, 2026-10-27).
ID_HINTS: dict[str, str] = {
    "city_state": "city-state ids are the `minor: true` rows of state(what='civs')",
    "civ": "civ ids are the rows of state(what='civs')",
    "unit": "unit ids are the rows of state(what='units')",
    "city": "city ids are the rows of state(what='cities')",
}


def pick(key: tuple[str, str], args: dict) -> str | Refusal:
    """The old name a key and the arguments mean."""
    names = INDEX.get(key)
    if not names:
        tool, _, what = key[0].partition(":")
        heads = {k[0] for k in INDEX}
        if key[0] not in heads:    # no such object / target at all: list them
            hint = None
            singular = what[:-1] if what.endswith("s") else None
            if tool == "state" and singular in ID_HINTS:   # a plural miss: name the object meant and its ids
                views = sorted(k[1] for k in INDEX if k[0] == f"state:{singular}")
                hint = (f"one is state(what='{singular}', id=<id>, view=<{' / '.join(views)}>); "
                        f"{ID_HINTS[singular]}")
            return Refusal(f"{tool} has no {'object' if tool == 'state' else 'target'} {what!r}",
                           choices=sorted({k[0].partition(":")[2] for k in INDEX if k[0].startswith(tool + ":")}),
                           hint=hint)
        hint = None
        if tool == "state" and what in ID_HINTS:
            hint = f"`id` is needed too; {ID_HINTS[what]}"
        return Refusal(f"{key[0]} has no {key[1]!r}", choices=sorted(k[1] for k in INDEX if k[0] == key[0]), hint=hint)
    if len(names) == 1:
        return names[0]
    chosen = DISAMBIGUATE.get(key)
    if chosen is not None:
        name = chosen(args)
        if name is not None:
            return name
    fitting = [n for n in names if _fits(n, args)]
    if len(fitting) == 1:
        return fitting[0]
    return Refusal(f"{key[0]} {key[1]!r} is one of {len(names)} calls and the arguments do not say which",
                   accepts=[signature(n) for n in names])


# --- resolution per new tool -------------------------------------------------------------------------------
def resolve(tool: str, fixed: dict, args: dict | None = None, gate: dict | None = None,
            blocker: str | None = None) -> Call | Composite | Refusal:
    """The old call a new call means. `fixed` are the new call's fixed fields (what / view, to / action, action,
    book, choice); `args` its arguments by the new names; `gate` the live gate, which `answer` dispatches on, and
    `blocker` the end-turn blocker it falls back to when no gate is up (harness.gate.BLOCKER_QUESTIONS)."""
    args = dict(args or {})
    if tool == "answer":
        return answer(fixed.get("choice"), args, gate, blocker)
    if tool == "order" and fixed.get("to") == "city_state" and fixed.get("action") not in V.ACTIONS["city_state"]:
        # the screen's own buttons (pledge, bully_gold, make_peace, ...): one old tool, the button as its argument
        return _call("city_state_action", {**args, "action": fixed.get("action")})
    if tool == "state" and fixed.get("what") == "city_state" and fixed.get("view") == "full":
        all_units = bool(args.pop("all_units", False))
        return Composite({k: Call(n, old_args(n, args)) for k, n in CITY_STATE_FULL.items()}, all_units)
    if tool == "reference":
        fixed = {"book": fixed.get("book") or "rules"}
    if tool == "state":
        view = fixed.get("view") or V.DEFAULT_VIEW.get(fixed.get("what"))
        fixed = {"what": fixed.get("what"), **({"view": view} if view else {})}
    try:
        key = _key(tool, fixed)
    except KeyError as e:
        return Refusal(f"{tool} needs {e.args[0]}")
    old = pick(key, args)
    if isinstance(old, Refusal):
        return old
    return _call(old, args)


#: The fixed fields of each new tool, as its own arguments carry them.
FIXED_FIELDS = {"turn": ("action",), "state": ("what", "view"), "order": ("to", "action"), "answer": ("choice",),
                "notebook": ("action",), "session": ("action",), "reference": ("book",)}


def old_call(name: str, args: dict | None = None) -> tuple[str, dict]:
    """The old handler and its arguments that a call by any name means, without the game: an old name or alias
    as it is (the alias by its target), a new tool through `resolve` -- or, when that needs the gate (an
    `answer` to the question on screen) or refuses, the call as it came. The ledger reads a call's attention
    off this, so a unit's id and a plot sit under the names attention knows whichever name the client used."""
    args = dict(args or {})
    if name not in V.TOOLS:
        old = old_name(name)
        if old in V.TOOLS:                    # a renamed listed tool (`inspect`): resolve as the tool it is now
            return old_call(old, args)
        return (old if old is not None else name), args
    if name in ("question", "batch"):
        return name, args
    fixed = {k: args.pop(k) for k in FIXED_FIELDS.get(name, ()) if args.get(k) not in (None, "")}
    if isinstance(args.get("args"), dict):          # the rest of the old call rides under `args`
        args = {**args.pop("args"), **args}
    target = resolve(name, fixed, args)
    if isinstance(target, Call):
        return target.tool, target.args
    if isinstance(target, Composite):
        first = next(iter(target.parts.values()))
        return first.tool, first.args
    return name, {**fixed, **args}


#: state(what="map", view="grid") centre + radius -> the old handler's box (GitLab #107: x, y, radius are state's
#: own parameters and were refused "does not take").
GRID_RADIUS = 5


def _call(old: str, args: dict) -> Call | Refusal:
    oargs = old_args(old, args)
    if old == "revealed_map" and "x" in oargs and "y" in oargs:
        try:
            x, y, r = int(oargs.pop("x")), int(oargs.pop("y")), int(oargs.pop("radius", GRID_RADIUS))
        except (TypeError, ValueError):
            return Refusal("state(what='map', view='grid') takes integer x, y and radius")
        oargs.update({"x0": x - r, "y0": y - r, "x1": x + r, "y1": y + r})
    props = schema(old).get("properties") or {}
    for k, v in list(oargs.items()):
        # one id where the old handler takes a list of them (state("units", id=7, view="actions") -> todo_actions(unit_ids=[7]))
        p = props.get(k) or {}
        types = {p.get("type")} | {x.get("type") for x in p.get("anyOf", [])}
        if "array" in types and not isinstance(v, list) and "integer" not in types and "string" not in types:
            oargs[k] = [v]
    unknown = sorted(set(oargs) - properties(old))
    missing = sorted(required(old) - set(oargs))
    if unknown or missing:
        return shape_refusal(old, unknown, missing)
    return Call(old, oargs)


#: The legal values of a missing argument the refusal can name (GitLab #113: `<mission>` / `<kind>` placeholders).
MISSING_CHOICES = {
    "mission": ["MISSION_MOVE_TO", "MISSION_ROUTE_TO", "MISSION_FOUND", "MISSION_TRADE", "MISSION_PARADROP", "MISSION_REBASE",
                "MISSION_AIRLIFT", "MISSION_NUKE"],
    "kind": ["pantheon", "founder", "follower", "enhancer", "bonus", "reformation"],
}


def shape_refusal(old: str, unknown: list[str], missing: list[str]) -> Refusal:
    row = R.RETIRED[old]
    parts = []
    if missing:
        parts.append("needs " + ", ".join(_new_name(row, m) for m in missing))
    if unknown:
        parts.append("does not take " + ", ".join(unknown))
    msg = f"{row.render()} {'; '.join(parts)}"
    if row.note:
        msg += f"; {row.note}"
    choices = next((MISSING_CHOICES[_new_name(row, m)] for m in missing if _new_name(row, m) in MISSING_CHOICES), None)
    return Refusal(msg, accepts=signature(old), example=example(old), choices=choices)


def _new_name(row: R.Row, old_arg: str) -> str:
    return row.renames.get(old_arg, old_arg)


def answer(choice: Any, args: dict, gate: dict | None, blocker: str | None = None) -> Call | Refusal:
    """`answer(choice, args)`: a fixed word (accept, refuse, leave, accept_friendship) names its call; anything
    else answers the question the gate shows -- the popup's resolver with the choice in its own argument, a
    leader's button, the tech chooser -- or, with no gate up, the end-turn blocker that is a question the
    engine never opened as a popup (`blocker`, one of harness.gate.BLOCKER_QUESTIONS; GitLab #95)."""
    if isinstance(choice, str) and choice in fixed_answers():
        return _call(fixed_answers()[choice], args)
    if gate is None and blocker in G.BLOCKER_QUESTIONS:
        old = G.BLOCKER_QUESTIONS[blocker]["clear_with"]
        arg = choice_arg(old)
        return _call(old, {**args, **({arg: choice} if arg else {})})
    if gate is None:
        return Refusal("nothing is asked right now: question() shows the question when there is one, "
                       "turn(action='briefing') the turn's decisions")
    name = gate.get("name")
    if name == "decision_popup":
        r = G.POPUP_RESOLUTIONS.get(str(gate.get("popup"))) or G.GENERIC_POPUP
        old = r["clear_with"]
        if old == "choose_policy" and str(choice).startswith("POLICY_BRANCH_"):
            old = "unlock_policy_branch"
        arg = choice_arg(old)
        return _call(old, {**args, **({arg: choice} if arg else {})})
    if name == "tech_choice":
        return _call("set_research", {**args, "tech": choice})
    if name == "leader_screen":
        return _call("dismiss_discussion", args)
    if name == "discussion":
        if isinstance(choice, bool) or not isinstance(choice, int):
            return Refusal("a leader is asking: answer with a button number (question() lists the buttons), or "
                           "'accept' / 'refuse' for a deal on the table, 'leave' to close the screen",
                           choices=[r["tool"] for r in gate.get("actions") or []])
        return _call("respond_discussion", {**args, "button_id": choice})
    return Refusal(f"the gate is {name}: {gate.get('why')}", choices=[r["tool"] for r in gate.get("actions") or []])


def question_read(gate: dict | None, blocker: str | None = None) -> Call | None:
    """The read that shows the question a gate asks: a decision popup's own read (`harness.gate`'s table), the
    leader's screen or the deal on the table, the tech chooser's options -- the old handler behind the gate's
    first `question()` / `state(...)` row. With no gate, the read of a blocker question (#95)."""
    if not gate:
        if blocker in G.BLOCKER_QUESTIONS:
            return Call(G.BLOCKER_QUESTIONS[blocker]["read_first"], {})
        return None
    name = gate.get("name")
    if name == "decision_popup":
        r = G.POPUP_RESOLUTIONS.get(str(gate.get("popup"))) or G.GENERIC_POPUP
        return Call(r["read_first"], {}) if r.get("read_first") else None
    for row in gate.get("actions") or []:
        if "choose" in row:
            continue
        if row["tool"] == "question":
            return Call("incoming_deal" if name == "discussion" and gate.get("deal") else "discussion", {})
        if row["tool"] == "state":
            old, args = old_call(row["tool"], row["args"])
            return Call(old, args)
    return None


def words() -> dict[str, Any]:
    """The vocabulary as the tool descriptions print it: every value with the old call it runs."""
    out: dict[str, Any] = {"turn": {}, "state": {}, "order": {}, "notebook": {}, "session": {}, "reference": {}}
    for key, names in INDEX.items():
        head, tail = key
        tool, _, what = head.partition(":")
        if tool == "state":
            out["state"].setdefault(what, {})[tail] = names
        elif tool == "order":
            out["order"].setdefault(what, {})[tail] = names
        elif tool in out:
            out[tool][tail] = names
    return out

