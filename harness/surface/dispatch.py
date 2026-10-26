"""The nine tools' routing onto today's handlers (GitLab #48, stage 2a).

`harness.surface.retirement.RETIRED` maps each old name onto its row in the new surface; read the other way it
says which old handler a new call runs: `inspect(what="screen", view="league")` is `league_status()`,
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


@dataclass(frozen=True)
class Call:
    """One old call to run: the registered tool's name and its arguments."""
    tool: str
    args: dict


@dataclass(frozen=True)
class Composite:
    """Several old calls whose replies merge into one (`inspect("city_state", view="full")`)."""
    parts: dict[str, Call]


@dataclass(frozen=True)
class Refusal:
    """Why a new call cannot be routed, with the shape it should have had."""
    err: str
    accepts: Any = None
    example: dict | None = None
    choices: list | None = None

    def reply(self) -> dict:
        out: dict[str, Any] = {"ok": False, "err": self.err}
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
    ("inspect:empire", V.DEFAULT): lambda a: "overview",
    ("inspect:city", "production"): lambda a: "purchase_cost" if a.get("item") else "available_production",
    ("order:city", "governor"): lambda a: ("set_city_focus" if "focus" in a else "set_avoid_growth" if "avoid" in a
                                           else "set_auto_specialists" if "automatic" in a else None),
    ("order:city", "great_work"): lambda a: "swap_great_works" if "their_work_id" in a else "set_swappable_great_work",
    ("order:empire", "policy"): lambda a: ("unlock_policy_branch"
                                           if str(a.get("policy") or a.get("branch") or "").startswith("POLICY_BRANCH_")
                                           else "choose_policy"),
}
#: `inspect("city_state", view="full")`: the one read that makes more trips than any of its parts, merged
#: under these keys (the summary first).
CITY_STATE_FULL = {"summary": "city_state_actions", "gifts": "city_state_gifts", "bonuses": "city_state_bonuses",
                   "gift_units": "gift_unit_options", "gift_tiles": "gift_tile_improvement_options"}

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


# --- the schemas of the old handlers (lazy: the server module imports this package's tool module) ----------
def schema(old: str) -> dict:
    from harness import mcp_server as core
    tool = core.mcp._tool_manager.get_tool(old) or core.hidden_tools().get(old)
    return dict(tool.parameters) if tool is not None else {}


def signature(old: str) -> str:
    from harness import mcp_server as core
    return f"{old}{core.tool_signature(schema(old))}"


def required(old: str) -> set[str]:
    return set(schema(old).get("required") or [])


def properties(old: str) -> set[str]:
    return set((schema(old).get("properties") or {}).keys())


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


def pick(key: tuple[str, str], args: dict) -> str | Refusal:
    """The old name a key and the arguments mean."""
    names = INDEX.get(key)
    if not names:
        tool, _, what = key[0].partition(":")
        heads = {k[0] for k in INDEX}
        if key[0] not in heads:    # no such object / target at all: list them
            return Refusal(f"{tool} has no {'object' if tool == 'inspect' else 'target'} {what!r}",
                           choices=sorted({k[0].partition(":")[2] for k in INDEX if k[0].startswith(tool + ":")}))
        return Refusal(f"{key[0]} has no {key[1]!r}", choices=sorted(k[1] for k in INDEX if k[0] == key[0]))
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
def resolve(tool: str, fixed: dict, args: dict | None = None, gate: dict | None = None) -> Call | Composite | Refusal:
    """The old call a new call means. `fixed` are the new call's fixed fields (what / view, to / action, action,
    book, choice); `args` its arguments by the new names; `gate` the live gate, which `answer` dispatches on."""
    args = dict(args or {})
    if tool == "answer":
        return answer(fixed.get("choice"), args, gate)
    if tool == "order" and fixed.get("to") == "city_state" and fixed.get("action") not in V.ACTIONS["city_state"]:
        # the screen's own buttons (pledge, bully_gold, make_peace, ...): one old tool, the button as its argument
        return _call("city_state_action", {**args, "action": fixed.get("action")})
    if tool == "inspect" and fixed.get("what") == "city_state" and fixed.get("view") == "full":
        return Composite({k: Call(n, old_args(n, args)) for k, n in CITY_STATE_FULL.items()})
    if tool == "reference":
        fixed = {"book": fixed.get("book") or "rules"}
    if tool == "inspect":
        fixed = {"what": fixed.get("what"), **({"view": fixed["view"]} if fixed.get("view") else {})}
    try:
        key = _key(tool, fixed)
    except KeyError as e:
        return Refusal(f"{tool} needs {e.args[0]}")
    old = pick(key, args)
    if isinstance(old, Refusal):
        return old
    return _call(old, args)


def _call(old: str, args: dict) -> Call | Refusal:
    oargs = old_args(old, args)
    props = schema(old).get("properties") or {}
    for k, v in list(oargs.items()):
        # one id where the old handler takes a list of them (inspect("units", id=7, view="actions") -> todo_actions(unit_ids=[7]))
        p = props.get(k) or {}
        types = {p.get("type")} | {x.get("type") for x in p.get("anyOf", [])}
        if "array" in types and not isinstance(v, list) and "integer" not in types and "string" not in types:
            oargs[k] = [v]
    unknown = sorted(set(oargs) - properties(old))
    missing = sorted(required(old) - set(oargs))
    if unknown or missing:
        return shape_refusal(old, unknown, missing)
    return Call(old, oargs)


def shape_refusal(old: str, unknown: list[str], missing: list[str]) -> Refusal:
    row = R.RETIRED[old]
    parts = []
    if missing:
        parts.append("needs " + ", ".join(_new_name(row, m) for m in missing))
    if unknown:
        parts.append("does not take " + ", ".join(unknown))
    return Refusal(f"{row.render()} {'; '.join(parts)}", accepts=signature(old), example=example(old))


def _new_name(row: R.Row, old_arg: str) -> str:
    return row.renames.get(old_arg, old_arg)


def example(old: str) -> dict:
    """One example of the new call for an old handler: the required arguments with a placeholder by type."""
    row = R.RETIRED[old]
    sch = schema(old)
    props = sch.get("properties") or {}
    args = {}
    for name in sch.get("required") or []:
        p = props.get(name) or {}
        t = p.get("type") or next((x.get("type") for x in p.get("anyOf", []) if x.get("type") != "null"), "string")
        args[_new_name(row, name)] = {"integer": 1, "number": 1, "boolean": True, "array": [], "object": {}}.get(t, f"<{name}>")
    fixed = {k: (f"<{v.name}>" if isinstance(v, R.FromArg) else v) for k, v in row.fixed.items()}
    for v in row.fixed.values():            # the choice itself is the answer's `choice`, not an argument
        if isinstance(v, R.FromArg):
            args.pop(v.name, None)
    top = {"id": args.pop("id")} if "id" in args and row.tool in ("inspect", "order") else {}
    nested = row.tool not in ("inspect", "turn")
    return {"tool": row.tool, "args": {**fixed, **top, **({"args": args} if args and nested else args)}}


def answer(choice: Any, args: dict, gate: dict | None) -> Call | Refusal:
    """`answer(choice, args)`: a fixed word (accept, refuse, leave, accept_friendship) names its call; anything
    else answers the question the gate shows -- the popup's resolver with the choice in its own argument, a
    leader's button, the tech chooser."""
    if isinstance(choice, str) and choice in fixed_answers():
        return _call(fixed_answers()[choice], args)
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


def question_read(gate: dict | None) -> Call | None:
    """The read that shows the question a gate asks, when the gate names one the call can make as is."""
    if not gate:
        return None
    for row in gate.get("actions") or []:
        if row["tool"] == gate.get("read_first") and "choose" not in row:
            return Call(row["tool"], dict(row["args"]))
    return None


def words() -> dict[str, Any]:
    """The vocabulary as the tool descriptions print it: every value with the old call it runs."""
    out: dict[str, Any] = {"turn": {}, "inspect": {}, "order": {}, "notebook": {}, "session": {}, "reference": {}}
    for key, names in INDEX.items():
        head, tail = key
        tool, _, what = head.partition(":")
        if tool == "inspect":
            out["inspect"].setdefault(what, {})[tail] = names
        elif tool == "order":
            out["order"].setdefault(what, {})[tail] = names
        elif tool in out:
            out[tool][tail] = names
    return out

