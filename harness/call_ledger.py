"""An opt-in ledger of MCP tool calls: what a model spent per turn (GitLab #36, "how to judge progress").

With `CIV5_CALL_LOG=/path/calls.jsonl` in the server's environment, every tool call appends one JSON row: time,
seat, `tool` and `action` (the call in the nine-tool vocabulary, `harness.surface.classes`; `called` keeps the old
name or alias a client used), `kind` (read / write / wait), the reply's bytes, tuner trips, seconds, whether the answer was a refusal
(`ok: false`) with its `err` cut short, the `turn` when the answer names one, and -- for the live visualization
(docs/VISUALIZATION.md, harness/attention.py) -- the arguments, a short excerpt of a write's reply and the plots the
call saw or pointed at. The file is the operator's, on the operator's disk; nothing here is returned to any seat. `scripts/ledger_report.py` groups the rows into turns
and keeps waiting (the AIs' turns, the bridge) apart from inspection.

Pure apart from `append`; no game reads of its own, so logging costs no trips.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from . import attention
from .surface import classes
from .surface import dispatch

ERR_CHARS = 120

# The game turn the latest row of each seat named: a read or an order whose reply names none (`units`,
# `tactical_view`, `move_unit`...) is stamped with it as `turn` plus `turn_inferred: true`, so a row can be
# grouped without replaying the file (the Codex rows of 2026-10-03: 368 of 443 carried no turn). Per process.
_LAST_TURN: dict[Any, int] = {}

# Who made the call: `CIV5_CLIENT` in the server's environment (the seat loops set it to "<agent>/<model>",
# scripts/llm_seat_loop.py) wins; otherwise the MCP initialize handshake's clientInfo ("claude-code/2.1.0",
# "codex-mcp-client/0.42"). Without either the row carries no `client` and the seat is the only key.
CLIENT_ENV = "CIV5_CLIENT"
CLIENT_CHARS = 80


def path() -> str | None:
    p = os.environ.get("CIV5_CALL_LOG", "").strip()
    return p or None


def client(client_info: Any = None) -> str | None:
    """The label a row carries as `client`: the CIV5_CLIENT env, else clientInfo's name[/version]."""
    label = os.environ.get(CLIENT_ENV, "").strip()
    if not label and client_info is not None:
        name = getattr(client_info, "name", None)
        if name is None and isinstance(client_info, dict):
            name, version = client_info.get("name"), client_info.get("version")
        else:
            version = getattr(client_info, "version", None)
        if name:
            label = f"{name}/{version}" if version else str(name)
    return label[:CLIENT_CHARS] or None


def kind(tool: str, args: dict | None = None) -> str:
    """read / write / wait, by the call's `(tool, action)` key (an old name or alias by the row it means)."""
    return classes.kind(classes.of_call(tool, args))


def reply_text(result: Any) -> str:
    """The text a client receives: a tool's own string, or the text parts of converted content."""
    if isinstance(result, str):
        return result
    if isinstance(result, tuple) and result:          # (content, structured) from some SDK versions
        return reply_text(result[0])
    if isinstance(result, (list, tuple)):
        return "".join(getattr(c, "text", "") or "" for c in result)
    text = getattr(result, "text", None)
    return text if isinstance(text, str) else ""


def refusal_reason(parsed: dict) -> str:
    """Why a reply says ok=false: its own `err`, else the nested one -- finish_turn's `end_turn.err` ("the turn
    did not end: every unit in todo.units still has moves"), a batch's first refused result, a `hint`."""
    for key in ("err", "error"):
        if parsed.get(key):
            return str(parsed[key])
    inner = parsed.get("end_turn")
    if isinstance(inner, dict) and inner.get("err"):
        return str(inner["err"])
    batch = parsed.get("batch")
    if isinstance(batch, dict):
        for res in batch.get("results") or []:
            inner = res.get("result") if isinstance(res, dict) else None
            if isinstance(inner, dict) and inner.get("ok") is False and inner.get("err"):
                return f"{res.get('tool')}: {inner['err']}"
    return str(parsed.get("hint") or "")


def row(tool: str, seat: Any, text: str, seconds: float, trips: int | None, now: float | None = None,
        args: dict | None = None, client_label: str | None = None) -> dict:
    """One ledger row from a finished call. `ok` is False only for a reply that says so (`{"ok": false}`).

    With `args` the row also carries the arguments as sent and the call's attention (harness/attention.py:
    `excerpt`, `scope`, `seen`, `intent`, `refs`), what the live visualization draws (docs/VISUALIZATION.md). `client_label`
    (see client()) names who made the call; absent, no `client` key is written."""
    r: dict[str, Any] = {"t": round(now if now is not None else time.time(), 3), "seat": seat,
                         **classes.called_as(tool, args), "kind": kind(tool, args),
                         "bytes": len(text.encode("utf-8")), "seconds": round(seconds, 3), "trips": trips, "ok": True}
    if client_label:
        r["client"] = client_label
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        if parsed.get("ok") is False:
            r["ok"] = False
            r["err"] = refusal_reason(parsed)[:ERR_CHARS]
        turn = parsed.get("turn")
        if not isinstance(turn, int):
            status = parsed.get("status")
            turn = status.get("turn") if isinstance(status, dict) else None
        if isinstance(turn, int):
            r["turn"] = turn
            _LAST_TURN[seat] = turn
    if "turn" not in r and seat in _LAST_TURN:
        r["turn"] = _LAST_TURN[seat]
        r["turn_inferred"] = True
    if args is not None:
        # The attention is read off the old handler's arguments (ids, plots, steps by their old names), whichever
        # name the call came by; `args` on the row stays what the client sent.
        old, old_args = dispatch.old_call(tool, args)
        r.update(attention.fields(classes.of_call(old, old_args), r["kind"], old_args, parsed, r["ok"], text))
        if a := attention.compact_args(args):
            r["args"] = a
    return r


def append(p: str, r: dict) -> None:
    """Best effort: a ledger that cannot be written never breaks the call it describes."""
    try:
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    except OSError:
        pass
