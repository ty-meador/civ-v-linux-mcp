"""The retirement map read forward (GitLab #50, stage 2c): an old name called by a client still runs, and the
reply says the new call.

Every old name stays callable forever -- agent prompts, Codex configs and transcript scripts in the wild name
them -- and so do the handful of names callers reach for that never were tools (`summary`, `status`,
`research`). The server's call wrapper asks this module two things about a name it does not list:
`old_name()`, which catalog name it means, and `renamed()`, the new call for the arguments given, rendered
the way a model can copy it: `state(what="map", view="window", x=3, y=4)`. The reply of the old handler is
unchanged but for that one key (`marked()`), so a script in the wild keeps the reply it knows while its model
learns the vocabulary. `new_call()` is the one place the shape of a new call is written -- which arguments
ride at the top level and which under `args` is the vocabulary's `TOP_LEVEL` table (the registered schemas
agree with it), so `example()` (the refusals' example row), every `{tool, args}` row a reply hands back
(`harness.rows`) and the round-trip test speak with the same voice as the tools.
"""
from __future__ import annotations

import json
from typing import Any

from harness.surface import retirement as R
from harness.surface import schemas as S
from harness.surface import vocabulary as V

#: Names a caller plausibly reaches for (they exist in the Game API, older docs, or other harnesses) and the
#: old name each means; through it, the row. Folded here from the server's former TOOL_ALIASES.
ALIASES: dict[str, str] = {"summary": "overview", "plots_around": "map_window", "turn_state": "turn_status",
                           "state": "turn_status", "status": "turn_status", "digest": "turn_digest",
                           "research": "set_research"}


def old_name(name: str) -> str | None:
    """The catalog name a called name means: itself when it is in the retirement map, the alias's target, else
    None (a name the map does not know is the server's to refuse)."""
    if name in R.RETIRED:
        return name
    if name in R.RENAMED_TOOLS:                # a listed tool's old name (`inspect`): the listed tool it is now
        return R.RENAMED_TOOLS[name]
    target = ALIASES.get(name)
    return target if target in R.RETIRED else None


def new_call(old: str, old_args: dict | None = None) -> dict:
    """The `{tool, args}` row of the new call an old call means. The row's fixed fields come first (`what` /
    `view`, `to` / `action`, a FromArg filled from the old argument it names), then the arguments the new tool
    takes at its top level (`id`, `x`, `since`, ...), then everything else under `args` when the tool has one."""
    if old == "call":                       # the retired call(tool, args) means the call it wraps
        inner, inner_args = (old_args or {}).get("tool"), (old_args or {}).get("args") or {}
        if inner in V.TOOLS:
            return {"tool": inner, "args": dict(inner_args)}
        target = old_name(inner) if isinstance(inner, str) else None
        if target is not None:
            return new_call(target, inner_args)
        return {"tool": "batch", "args": {"actions": [{"tool": inner, "args": inner_args}]}}
    old = R.RENAMED_TOOLS.get(old, old)      # `inspect` means `state`
    if old in V.TOOLS:                        # a renamed listed tool: the same call under its name now
        return {"tool": old, "args": {k: v for k, v in (old_args or {}).items() if v is not None}}
    row = R.RETIRED[old]
    rest = {row.renames.get(k, k): v for k, v in (old_args or {}).items() if v is not None}
    fixed = row.fill(rest)
    for v in row.fixed.values():                   # the argument a FromArg took is spent
        if isinstance(v, R.FromArg):
            rest.pop(v.name, None)
    for k in [k for k in rest if k in fixed]:      # a selector the row itself fixes (detail="digest")
        rest.pop(k)
    top = {k: rest.pop(k) for k in list(rest) if k in V.TOP_LEVEL.get(row.tool, ())}
    args = {**fixed, **top}
    if rest:
        if row.tool in V.TAKES_ARGS:
            args["args"] = rest
        else:
            args.update(rest)
    return {"tool": row.tool, "args": args}


def choose_names(old: str, choose: list[str]) -> list[str]:
    """The names a `choose` list carries under the new call: the old argument names renamed (`unit_id` -> `id`),
    and an argument a fixed field takes (a popup's `button`, a goody) as that field (`choice`). A chosen name in
    `TOP_LEVEL` or a fixed field goes at the top of the row, any other under its `args`."""
    row = R.RETIRED[old]
    taken = {v.name: k for k, v in row.fixed.items() if isinstance(v, R.FromArg)}
    return [taken.get(c) or row.renames.get(c, c) for c in choose]


def render(call: dict) -> str:
    """One call as a line: state(what="map", view="window", x=3)."""
    return f"{call['tool']}({', '.join(f'{k}={json.dumps(v, ensure_ascii=False)}' for k, v in call['args'].items())})"


def renamed(old: str, old_args: dict | None = None) -> str:
    """The `renamed` string a forwarded reply carries."""
    return render(new_call(old, old_args))


#: Where a placeholder by type says nothing (`items: []`), one real value (GitLab #118: propose_deal's shape had to
#: be guessed from the deal reads).
EXAMPLE_VALUES = {"propose_deal": {"items": [{"type": "GOLD_PER_TURN", "from_us": True, "amount": 2},
                                             {"type": "RESOURCES", "resource": "RESOURCE_DYE", "from_us": False, "amount": 1}]}}


def new_signature(old: str) -> str:
    """The new call's signature for an old handler, the way a refusal prints what it accepts (GitLab #146: the
    refusals named the retired call's signature, `explore_frontier(unit_id, limit=12)`, beside a right example):
    `state(what="map", view="frontier", id: integer, limit: integer = 12)` -- the row's fixed fields, then the
    old handler's arguments under their new names, the ones that ride under `args` as `args={...}`."""
    row = R.RETIRED[old]
    schema = S.schema(old)
    props, req = schema.get("properties") or {}, set(schema.get("required") or [])
    taken = {v.name for v in row.fixed.values() if isinstance(v, R.FromArg)}
    parts = [f"{k}={R.show(v, quote=True)}" for k, v in row.fixed.items()]
    top, nested = [], []
    for k, p in props.items():
        new = row.renames.get(k, k)
        if k in taken or new in row.fixed:
            continue
        text = f"{new}: {S.type_text(p)}" + ("" if k in req else f" = {p.get('default')!r}")
        at_top = new in V.TOP_LEVEL.get(row.tool, ()) or row.tool not in V.TAKES_ARGS
        (top if at_top else nested).append(text)
    if nested:
        top.append("args={" + ", ".join(nested) + "}")
    return f"{row.tool}(" + ", ".join(parts + top) + ")"


def example(old: str) -> dict:
    """One example of the new call for an old handler: its required arguments with a placeholder by type."""
    values = {name: S.placeholder(old, name) for name in sorted(S.required(old))}
    values.update({k: v for k, v in EXAMPLE_VALUES.get(old, {}).items() if k in values})
    return new_call(old, values)


def marked(reply: Any, renamed_call: str) -> Any:
    """The old handler's reply with `renamed` on it. A JSON object (the string every tool returns) gains the
    key and keeps its formatting; anything else -- plain text, a list -- is returned as it was. A reply that
    already carries one keeps it: `call(tool=<old name>)` is itself retired, and the inner call's new name is
    the one worth copying."""
    if not isinstance(reply, str):
        return reply
    try:
        obj = json.loads(reply)
    except ValueError:
        return reply
    if not isinstance(obj, dict) or "renamed" in obj:
        return reply
    obj["renamed"] = renamed_call
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
