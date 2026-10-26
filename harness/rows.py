"""The shape of a row: one call the model copies (GitLab #45, #46, #55).

A row is `{tool, args}`, exactly what `batch(actions=[...])` and `turn(action="finish", actions=[...])` take; a
row whose arguments the model still has to pick carries `choose`, the names of the arguments the read before it
lists the values for. Every row is written in the nine-tool vocabulary: the makers (`harness/gate.py`,
`harness/affordances/`) name the old handler and its arguments, and this module renders the new call through the
retirement map (`harness.surface.forward.new_call`), so a reply never hands back a name the listing does not
carry. A chosen name in the tool's `TOP_LEVEL` arguments (`id`, a plot's `x` / `y` on `inspect`) goes at the
top of the row, any other under its `args`.
"""
from __future__ import annotations

from typing import Any

from harness.surface import forward
from harness.surface import retirement as R

#: The key of a row whose arguments the model fills from the read before it.
CHOOSE = "choose"


def act(tool: str, **args: Any) -> dict:
    """One complete call: `{tool, args}`. An old handler's name and arguments come back as the new call."""
    if tool in R.RETIRED:
        return forward.new_call(tool, args)
    return {"tool": tool, "args": args}


def pick(tool: str, choose: list[str], **args: Any) -> dict:
    """A call with arguments still to choose from the read before it: `{tool, args, choose}`."""
    names = forward.choose_names(tool, list(choose)) if tool in R.RETIRED else list(choose)
    return {**act(tool, **args), CHOOSE: names}


def is_row(v: Any) -> bool:
    """A `{tool, args}` row as batch() / turn(action="finish") take it."""
    return isinstance(v, dict) and isinstance(v.get("tool"), str) and isinstance(v.get("args"), dict)


#: Where a reply keeps rows: lists of them (what can be done, what answers a question) and single ones on a
#: choice row (the write that takes it, its purchase, the read of its targets).
LIST_KEYS = ("actions", "answers")
ROW_KEYS = ("call", "buy", "read")


def rows_in(reply: Any) -> list[dict]:
    """Every row anywhere in a reply (the LIST_KEYS lists and the ROW_KEYS rows, any depth), in reading order."""
    out: list[dict] = []
    stack = [reply]
    while stack:
        v = stack.pop(0)
        if isinstance(v, dict):
            for k in LIST_KEYS:
                rows = v.get(k)
                if isinstance(rows, list) and rows and all(is_row(r) for r in rows):
                    out.extend(rows)
            out.extend(v[k] for k in ROW_KEYS if is_row(v.get(k)))
            stack.extend(x for k, x in v.items() if k not in LIST_KEYS and k not in ROW_KEYS)
        elif isinstance(v, list):
            stack.extend(v)
    return out
