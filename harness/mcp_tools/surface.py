"""The nine tools of milestone 2.0.0 (GitLab #48, stage 2a): the game as a clock, a world of objects, the
questions it asks, my notebook and the session.

One of the civ5 MCP server's tool modules (registered last by harness/mcp_server.py). Each tool routes its
call through `harness.surface.dispatch` onto the old handler and runs it with the server's own runner (by the
handler's exact name, so no `renamed` rides on it), so the old guard, ledger row and reply are exactly what
they were: `inspect(what="screen", view="league")` returns
`league_status()` byte for byte. `reference(book, section)` is the old `reference` tool grown a `book`
(harness/mcp_tools/reference.py). The 145 old names stay registered beside these until #52.
"""
from __future__ import annotations

import json
from typing import Any

from harness.mcp_server import Context

from harness import briefing as B
from harness import mcp_server as core
from harness.mcp_server import J, _remember_result, _replayed, _run_tool_here, mcp
from harness.mcp_tools.batch import run_batch
from harness.surface import dispatch as D
from harness.surface import vocabulary as V


def _run(target: D.Call | D.Composite | D.Refusal, action_id: str | None = None, ctx: Context | None = None) -> str:
    """Run what dispatch resolved: a refusal as is, a composite part by part, a call through the runner (with
    the replay of a retried action_id, as a batch row has it)."""
    if isinstance(target, D.Refusal):
        return J(target.reply())
    if isinstance(target, D.Composite):
        parts = {}
        for key, call in target.parts.items():
            try:
                parts[key] = json.loads(_run_tool_here(call.tool, call.args, renamed=False))
            except ValueError:
                parts[key] = {"ok": False, "err": "not JSON"}
        ok = all(isinstance(p, dict) and p.get("ok") is not False for p in parts.values())
        return J({"ok": ok, **parts})
    r = _replayed(target.tool, action_id) if action_id else None
    if r is None:
        r = _run_tool_here(target.tool, target.args, ctx=ctx, renamed=False)
        if action_id:
            _remember_result(target.tool, action_id, r)
    return r


def _given(**kw: Any) -> dict:
    """The arguments actually passed: empty strings and None are "not given"."""
    out = {}
    for k, v in kw.items():
        if k == "args" and isinstance(v, dict):
            out.update({kk: vv for kk, vv in v.items() if vv is not None})
        elif v is not None and v != "":
            out[k] = v
    return out


def _gate_now() -> tuple[dict, dict | None]:
    """The live turn state and its gate (what `question` shows and `answer` dispatches on)."""
    g = core.game()
    with core.action_lock(core._sock(), seat=g.seat, tool="question"):
        ts = g.turn_state()
    return ts, core._gate(ts, g.seat)


# --- turn ---------------------------------------------------------------------------------------------
def turn(action: str, actions: list[dict] | None = None, since: str = "", limit: int | None = None,
         detail: str = "", notes: str = "", timeout_seconds: int | None = None, args: dict | None = None,
         ctx: Context = None) -> str:
    return _run(D.resolve("turn", {"action": action},
                          _given(actions=actions, since=since, limit=limit, detail=detail, notes=notes,
                                 timeout_seconds=timeout_seconds, args=args)), ctx=ctx)


turn.__doc__ = (
    "The clock. action: status (whose turn, the gate, what blocks ending it; today's turn_status), briefing (my turn in "
    "one read: decisions with their `actions` rows, changes, board, threats, notes; since='turn' after a context reset, "
    "detail='digest' for the event digest alone), finish (run `actions` rows, end the turn, wait until it is mine again "
    "and return the new turn; `notes`, `timeout_seconds`), end (end the turn only), wait (block until it is my turn). "
    "Other arguments of the old call by name in `args` (finish_turn's skip_quiet_turns, wake_on, autosave, briefing)."
)

# --- inspect --------------------------------------------------------------------------------------------
def inspect(what: str, id: int | list[int] | None = None, view: str = "", x: int | None = None, y: int | None = None,
            radius: int | None = None, mission: str = "", kind: str = "", detail: str = "", since: str = "",
            limit: int | None = None, item: str = "", yield_type: str = "", args: dict | None = None) -> str:
    return _run(D.resolve("inspect", {"what": what, "view": view},
                          _given(id=id, x=x, y=y, radius=radius, mission=mission, kind=kind, detail=detail,
                                 since=since, limit=limit, item=item, yield_type=yield_type, args=args)))


inspect.__doc__ = (
    "A read of the world: `what` names the object, `view` the part of it (the default view when left out); `id` the "
    "one object (a unit, city, civ, city-state or spy id; a list for units/actions). Every reply that lists what can be "
    "done carries `actions` / `call` rows for order. what: views --\n"
    + "\n".join(f"  {what}: {', '.join(views)}" for what, views in V.VIEWS.items())
    + "\nSelectors: x, y, radius (map/window, unit/tactical), mission (unit/targets), kind (options/beliefs, compare), "
    "detail, since, limit, item + yield_type (city/production prices one item), `args` for the rest by the old name "
    "(compare's fields). Replies are the old reads' replies unchanged."
)

# --- order ---------------------------------------------------------------------------------------------
def order(to: str, action: str, id: int | None = None, args: dict | None = None, action_id: str | None = None) -> str:
    return _run(D.resolve("order", {"to": to, "action": action}, _given(id=id, args=args)), action_id=action_id)


order.__doc__ = (
    "An order to something I own: `to` the target kind, `id` which one, `action` the verb, `args` its arguments by name "
    "(a refusal names the shape with an example). to: actions --\n"
    + "\n".join(f"  {to}: {', '.join(a for a in acts if a != V.SCREEN_BUTTON)}"
                + (" (or a city-state screen button by its name: pledge, revoke_pledge, bully_gold, bully_unit, declare_war, make_peace)"
                   if V.SCREEN_BUTTON in acts else "")
                for to, acts in V.ACTIONS.items())
    + "\nCopy the rows a read hands back (`actions`, `call`) as they are; `action_id` replays a retried order."
)

# --- question / answer -----------------------------------------------------------------------------------
def question() -> str:
    ts, gate = _gate_now()
    read = D.question_read(gate)
    if read is not None:
        try:
            reply = json.loads(_run_tool_here(read.tool, read.args, renamed=False))
        except ValueError:
            reply = {"ok": False, "err": "not JSON"}
        if isinstance(reply, dict):
            reply["gate"] = gate
            return J(reply)
        return J({"ok": True, "question": reply, "gate": gate})
    if gate is not None:
        return J({"ok": True, "pending": True, "gate": gate})
    return J({"ok": True, "pending": False, "decisions": B.decisions(ts, []),
              "note": "nothing is asked; the decisions are the turn's todo (turn(action='briefing') has them in full)"})


question.__doc__ = (
    "What the game is asking right now, with its `answers` rows: the decision popup's choices (a tech, a production item, "
    "a policy, a promotion, a belief, a ruins reward, a captured city's fate, a Great Person, a dig), the leader on screen "
    "and the deal on the table (the buttons), or nothing pending (then the turn's open decisions). `gate` rides on the "
    "reply. answer() takes the choice."
)


def answer(choice: str | int, args: dict | None = None, action_id: str | None = None) -> str:
    gate = None
    if not (isinstance(choice, str) and choice in D.fixed_answers()):
        _ts, gate = _gate_now()
    return _run(D.resolve("answer", {"choice": choice}, _given(args=args), gate), action_id=action_id)


answer.__doc__ = (
    "Answer what the game is asking: `choice` is the item's name (a TECH_, UNIT_, BUILDING_, POLICY_, PROMOTION_, BELIEF_ "
    "or goody name; liberate / annex / puppet / raze; a dig's choice number), a popup's or leader screen's button number, "
    "or on a leader screen accept / refuse (a deal on the table), leave (close it), accept_friendship. `args` carries the "
    "rest the popup needs (a promotion's unit_id, a dig's x and y, a stolen tech's player_id, a religion's beliefs and city). "
    "Dispatches on the gate: question() shows which question is up."
)

# --- notebook / session / batch ------------------------------------------------------------------------
def notebook(action: str, args: dict | None = None, action_id: str | None = None) -> str:
    return _run(D.resolve("notebook", {"action": action}, _given(args=args)), action_id=action_id)


notebook.__doc__ = (
    "My own memory, kept beside the game: action one of " + ", ".join(V.NOTEBOOK_ACTIONS) + " (today's remember / recall / "
    "forget, assign / assignments / amend_assignment / close_assignment, give_order / orders / cancel_order / resume_order), "
    "`args` the old call's arguments by name."
)


def session(action: str, args: dict | None = None) -> str:
    return _run(D.resolve("session", {"action": action}, _given(args=args)))


session.__doc__ = (
    "Saves, loads and the seat: action one of " + ", ".join(V.SESSION_ACTIONS) + " (today's quick_save, load_save with "
    "`filename` in args, load_latest, exit_to_main_menu, set_seat with `seat`). In a game with other people ask the human "
    "before loading."
)


def batch(actions: list[dict], stop_on_refusal: bool = True, force: bool = False) -> str:
    return J(run_batch(actions, stop_on_refusal=stop_on_refusal, force=force))


batch.__doc__ = (
    "Many orders in one call, in order: actions is a list of {tool, args} rows -- the rows every read hands back, old or "
    "new names alike -- each answered under `results`; the first refusal stops the rest (stop_on_refusal=false runs them "
    "all). Not inside: turn, session, batch, wait_for_my_turn, finish_turn, end_turn, load_*. turn(action='finish', "
    "actions=[...]) runs a batch and ends the turn in one call."
)


def _safe(fn):
    """A harness bug comes back as a readable JSON error, as `guarded` does for the old tools (the nine run the
    old handlers through the runner, which guards them; this covers the routing itself)."""
    import functools

    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as e:
            return J({"ok": False, "err": f"harness error: {type(e).__name__}: {e}", "tool": fn.__name__})
    return wrapper


for _name in V.TOOLS:
    if _name != "reference":          # the old `reference` tool, grown a `book`, is the ninth (mcp_tools/reference.py)
        mcp.tool()(_safe(globals()[_name]))
del _name
