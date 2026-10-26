"""The retirement map read forward (GitLab #50, stage 2c): an old name called by a client still runs, and the
reply says the new call.

Every old name stays callable forever -- agent prompts, Codex configs and transcript scripts in the wild name
them -- and so do the handful of names callers reach for that never were tools (`summary`, `status`,
`research`). The server's call wrapper asks this module two things about a name it does not list:
`old_name()`, which catalog name it means, and `renamed()`, the new call for the arguments given, rendered
the way a model can copy it: `inspect(what="map", view="window", x=3, y=4)`. The reply of the old handler is
unchanged but for that one key (`marked()`), so a script in the wild keeps the reply it knows while its model
learns the vocabulary. `new_call()` is the one place the shape of a new call is written -- which arguments
ride at the top level and which under `args` is read from the new tool's own schema, so `example()` (the
refusals' example row) and the round-trip test speak with the same voice as the tools.
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
    row = R.RETIRED[old]
    rest = {row.renames.get(k, k): v for k, v in (old_args or {}).items() if v is not None}
    fixed = row.fill(rest)
    for v in row.fixed.values():                   # the argument a FromArg took is spent
        if isinstance(v, R.FromArg):
            rest.pop(v.name, None)
    for k in [k for k in rest if k in fixed]:      # a selector the row itself fixes (detail="digest")
        rest.pop(k)
    props = S.properties(row.tool)
    top = {k: rest.pop(k) for k in list(rest) if k in props and k != "args"}
    args = {**fixed, **top}
    if rest:
        if "args" in props:
            args["args"] = rest
        else:
            args.update(rest)
    return {"tool": row.tool, "args": args}


def render(call: dict) -> str:
    """One call as a line: inspect(what="map", view="window", x=3)."""
    return f"{call['tool']}({', '.join(f'{k}={json.dumps(v, ensure_ascii=False)}' for k, v in call['args'].items())})"


def renamed(old: str, old_args: dict | None = None) -> str:
    """The `renamed` string a forwarded reply carries."""
    return render(new_call(old, old_args))


def example(old: str) -> dict:
    """One example of the new call for an old handler: its required arguments with a placeholder by type."""
    return new_call(old, {name: S.placeholder(old, name) for name in sorted(S.required(old))})


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
