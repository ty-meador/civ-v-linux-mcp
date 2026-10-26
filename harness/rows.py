"""The shape of a row: one call the model copies (GitLab #45, #46).

A row is `{tool, args}`, exactly what `do(actions=[...])` and `finish_turn(actions=[...])` take; a row whose
arguments the model still has to pick carries `choose`, the names of the arguments the read before it lists the
values for. This module is a leaf (no harness imports): `harness/gate.py` builds a gate's rows with it,
`harness/affordances.py` the briefing's, a unit's and a question's. Nothing here knows a tool name.
"""
from __future__ import annotations

from typing import Any

#: The key of a row whose arguments the model fills from the read before it.
CHOOSE = "choose"


def act(tool: str, **args: Any) -> dict:
    """One complete call: `{tool, args}`."""
    return {"tool": tool, "args": args}


def pick(tool: str, choose: list[str], **args: Any) -> dict:
    """A call with arguments still to choose from the read before it: `{tool, args, choose}`."""
    return {**act(tool, **args), CHOOSE: list(choose)}


def is_row(v: Any) -> bool:
    """A `{tool, args}` row as do() / finish_turn() take it."""
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
