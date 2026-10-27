"""The nine tools of milestone 2.0.0 (GitLab #48, stage 2a): the game as a clock, a world of objects, the
questions it asks, my notebook and the session.

One of the civ5 MCP server's tool modules (registered last by harness/mcp_server.py). Each tool routes its
call through `harness.surface.dispatch` onto the old handler and runs it with the server's own runner (by the
handler's exact name, so no `renamed` rides on it), so the old guard, ledger row and reply are exactly what
they were: `inspect(what="screen", view="league")` returns
`league_status()` byte for byte. `reference(book, section)` is the old `reference` tool grown a `book`
(harness/mcp_tools/reference.py). The 145 old handlers are registered and retired at once (`@retired`, #52): the
listing is these nine, and an old name answers through the retirement map with `renamed` on its reply.
"""
from __future__ import annotations

import json
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from harness.mcp_server import Context

from harness import briefing as B
from harness import mcp_server as core
from harness.mcp_server import J, _remember_result, _replayed, _run_tool_here, mcp
from harness.mcp_tools.batch import run_batch
from harness.surface import dispatch as D
from harness.surface import listing as L
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
def _f(description: str):
    """A parameter's `description` in the listed schema (TDQS and the clients read it)."""
    return Field(description=description)


def turn(action: Annotated[str, _f("status | briefing | finish | end | wait")],
         actions: Annotated[list[dict] | None, _f("finish only: order rows to run before the turn ends, [{tool, args}] as the reads hand them back")] = None,
         since: Annotated[str, _f("briefing: 'previous' (default) compares with my last briefing, 'turn' with the last turn end (after a context reset)")] = "",
         limit: Annotated[int | None, _f("briefing: rows per list of changes and notes (default 8)")] = None,
         detail: Annotated[str, _f("briefing: 'compact' (default) or 'digest' (the event digest alone)")] = "",
         notes: Annotated[str, _f("finish: which notebook notes ride on the reply, 'new' (default) or 'all'")] = "",
         timeout_seconds: Annotated[int | None, _f("finish / wait: seconds to wait for my turn before answering with the state so far (default 600)")] = None,
         args: Annotated[dict | None, _f("other arguments of the old call by name: skip_quiet_turns, wake_on, autosave, briefing")] = None,
         ctx: Context = None) -> str:
    return _run(D.resolve("turn", {"action": action},
                          _given(actions=actions, since=since, limit=limit, detail=detail, notes=notes,
                                 timeout_seconds=timeout_seconds, args=args)), ctx=ctx)


turn.__doc__ = (
    "The clock. action: status (whose turn, the gate, what blocks ending it; today's turn_status), briefing (my turn in "
    "one read: decisions with their `actions` rows, changes, board, threats, notes; since='turn' after a context reset, "
    "detail='digest' for the event digest alone), finish (run `actions` rows, end the turn, wait until it is mine again "
    "and return the new turn; notes='new' / 'all' picks which notebook notes ride on the reply; `timeout_seconds`), "
    "end (end the turn only), wait (block until it is my turn). "
    "Other arguments of the old call by name in `args` (finish_turn's skip_quiet_turns, wake_on, autosave, briefing). "
    "Returns the turn: turn, my_turn, `gate` (null, or what must be answered first), todo / decisions, digest, notes; "
    "finish and wait return once it is my turn again or the timeout passes (then with my_turn false, nothing lost)."
)

# --- inspect --------------------------------------------------------------------------------------------
def inspect(what: Annotated[str, _f("the object: " + ", ".join(V.VIEWS))],
            id: Annotated[int | list[int] | None, _f("the one object's id (unit, city, civ, city-state or spy); a list of unit ids for units/actions")] = None,
            view: Annotated[str, _f("the part of the object, from the list below; the default view when left out")] = "",
            x: Annotated[int | None, _f("map/window centre or unit/tactical origin, with y")] = None,
            y: Annotated[int | None, _f("with x")] = None,
            radius: Annotated[int | None, _f("map/window, unit/tactical: tiles around x, y")] = None,
            mission: Annotated[str, _f("unit/targets: the mission whose legal targets to list")] = "",
            kind: Annotated[str, _f("options/beliefs: the belief kind; compare: what to compare")] = "",
            detail: Annotated[str, _f("'summary' or 'full' where a view offers both")] = "",
            since: Annotated[str, _f("notifications: only those after this turn")] = "",
            limit: Annotated[int | None, _f("how many rows a list returns")] = None,
            item: Annotated[str, _f("city/production: price this one item")] = "",
            yield_type: Annotated[str, _f("city/production with item: the yield to price it in")] = "",
            args: Annotated[dict | None, _f("the rest by the old call's name (compare's fields)")] = None) -> str:
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
def order(to: Annotated[str, _f("the target kind, something I own")],
          action: Annotated[str, _f("the verb; its words depend on `to`")],
          id: Annotated[int | None, _f("which unit, city, civ, city-state or spy; empire and league take none")] = None,
          args: Annotated[dict | None, _f("the action's arguments by name, as the copied row has them; a refusal shows the shape with an example")] = None,
          action_id: Annotated[str | None, _f("a token of my choosing: a retry with the same action_id replays the stored result instead of acting twice")] = None) -> str:
    return _run(D.resolve("order", {"to": to, "action": action}, _given(id=id, args=args)), action_id=action_id)


order.__doc__ = (
    "An order to something I own: `to` the target kind, `id` which one, `action` the verb, `args` its arguments by name "
    "(a refusal names the shape with an example). to: actions --\n"
    + "\n".join(f"  {to}: {', '.join(a for a in acts if a != V.SCREEN_BUTTON)}"
                + (f" (or a city-state screen button by its name: {', '.join(V.SCREEN_BUTTONS)})"
                   if V.SCREEN_BUTTON in acts else "")
                for to, acts in V.ACTIONS.items())
    + "\nCopy the rows a read hands back (`actions`, `call`) as they are; `action_id` replays a retried order. Returns "
    "{ok: true, ...} with what changed (a unit's new plot, a city's queue, a deal's answer), or {ok: false, err, choices / "
    "accepts, example} naming why and the legal shape; nothing is acted on when ok is false. Orders change the game and "
    "most cannot be undone (disband, declare_war, a purchase)."
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


def answer(choice: Annotated[str | int, _f("the `answers` row's choice: an item name, a button number, or accept / refuse / leave / accept_friendship")],
           args: Annotated[dict | None, _f("what the popup needs beyond the choice: unit_id, x and y, player_id, beliefs, city")] = None,
           action_id: Annotated[str | None, _f("a token of my choosing: a retry with the same action_id replays the stored result")] = None) -> str:
    gate = None
    if not (isinstance(choice, str) and choice in D.fixed_answers()):
        _ts, gate = _gate_now()
    return _run(D.resolve("answer", {"choice": choice}, _given(args=args), gate), action_id=action_id)


answer.__doc__ = (
    "Answer what the game is asking: `choice` is the item's name (a TECH_, UNIT_, BUILDING_, POLICY_, PROMOTION_, BELIEF_ "
    "or goody name; liberate / annex / puppet / raze; a dig's choice number), a popup's or leader screen's button number, "
    "or on a leader screen accept / refuse (a deal on the table), leave (close it), accept_friendship. `args` carries the "
    "rest the popup needs (a promotion's unit_id, a dig's x and y, a stolen tech's player_id, a religion's beliefs and city). "
    "Dispatches on the gate: question() shows which question is up. Returns {ok, ...} with the popup's outcome and the "
    "gate that follows (still_pending and `next` when another leader waits), or {ok: false, err, choices}."
)

# --- notebook / session / batch ------------------------------------------------------------------------
def notebook(action: Annotated[str, _f(" | ".join(V.NOTEBOOK_ACTIONS))],
             args: Annotated[dict | None, _f("the action's arguments by name: text / tag / replace_id, note_id, role and purpose with unit_ids / city_ids, assignment_id, unit_id and steps, order_id")] = None,
             action_id: Annotated[str | None, _f("a token of my choosing: a retry with the same action_id replays the stored result")] = None) -> str:
    return _run(D.resolve("notebook", {"action": action}, _given(args=args)), action_id=action_id)


notebook.__doc__ = (
    "My memory, kept beside the game per seat and surviving a context reset: free-text notes, assignments (what a unit or "
    "city is for) and multi-turn orders for units. Use it for what future-me must know; the game itself holds no plan. "
    "action, with its args -- remember {text, tag?, replace_id?}: write a note (returns the note with its id; new notes "
    "ride on the next briefing / finish); recall {tag?, limit?}: list notes; forget {note_id}: delete a note for good. "
    "assign {role, purpose, unit_ids? / city_ids?}: give units or cities a purpose that shows in their rows; assignments: list "
    "them; amend {assignment_id, purpose? / role?}; close {assignment_id}. give_order {unit_id, steps}: a plan of steps "
    "run one per turn at each finish; orders: the plans with their status; cancel_order / resume_order {order_id}. "
    "Returns {ok: true, ...} with the row written or the rows listed, or {ok: false, err, accepts, example}. A note "
    "written on a turn later than the one on screen (a save was loaded) comes back marked later_timeline."
)


def session(action: Annotated[str, _f(" | ".join(V.SESSION_ACTIONS))],
            args: Annotated[dict | None, _f("load: {filename} (a save's name without the single/ prefix); seat: {seat} (0 or 1)")] = None) -> str:
    return _run(D.resolve("session", {"action": action}, _given(args=args)))


session.__doc__ = (
    "Saves, loads and the seat of this game session: keep a state before a risky turn, open another save, leave a finished "
    "game. It never plays a turn. action -- save: a quick save of the game on screen (returns the save written); load "
    "{filename}: open that save in the live game, replacing the unsaved state on screen (save first); load_latest: open the "
    "newest save, whichever game it is; main_menu: leave the game for the main menu (the game_over gate's way out); seat "
    "{seat}: which human seat this server plays in a hotseat game (a server pinned with --seat refuses a change onto the "
    "other human seat; never move onto the seat on screen). Returns {ok: true, turn, seat, ...} or {ok: false, err} with "
    "the legal filenames or seats. In a game with other people ask the human before loading."
)


def batch(actions: Annotated[list[dict], _f("the rows to run in order, [{tool, args}], as every read hands them back")],
          stop_on_refusal: Annotated[bool, _f("stop at the first refused row (default true); false runs them all")] = True,
          force: Annotated[bool, _f("take over this turn's claim held by another client of my seat")] = False) -> str:
    return J(run_batch(actions, stop_on_refusal=stop_on_refusal, force=force))


batch.__doc__ = (
    "Many orders in one call, in order: actions is a list of {tool, args} rows -- the rows every read hands back, old or "
    "new names alike -- each answered under `results`; the first refusal stops the rest (stop_on_refusal=false runs them "
    "all). Not inside: the turn's wait / finish / end, a load, the seat, the exit, a batch. turn(action='finish', "
    "actions=[...]) runs a batch and ends the turn in one call. Returns {ok, results: [one reply per row], stopped_at?}; "
    "the rows act on the game as the orders they carry."
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


#: What each tool does to the world, as MCP annotations on the listing (TDQS lint, 2026-10-27): the reads are
#: read-only and idempotent; an order, a batch, a load and a forgotten note cannot be taken back; nothing here
#: reaches beyond the game on this machine.
ANNOTATIONS: dict[str, ToolAnnotations] = {
    "turn": ToolAnnotations(title="The clock", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    "inspect": ToolAnnotations(title="Read the world", readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    "order": ToolAnnotations(title="Order what I own", readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False),
    "question": ToolAnnotations(title="What the game asks", readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    "answer": ToolAnnotations(title="Answer the game", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    "notebook": ToolAnnotations(title="My notebook", readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False),
    "batch": ToolAnnotations(title="Many orders", readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False),
    "session": ToolAnnotations(title="Saves, loads, the seat", readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False),
    "reference": ToolAnnotations(title="The rule book and the playbook", readOnlyHint=True, idempotentHint=True, openWorldHint=False),
}

for _name in V.TOOLS:
    if _name != "reference":          # the old `reference` tool, grown a `book`, is the ninth (mcp_tools/reference.py)
        mcp.tool(annotations=ANNOTATIONS[_name])(_safe(globals()[_name]))
del _name


# --- the listing (#49): order's schema, oneOf or flat, per connected client -------------------------------
def _order_tool():
    return mcp._tool_manager.get_tool("order")


#: The schema the SDK generated for `order` (titles, defaults, `required`), before any variant grew on it.
BASE_ORDER_SCHEMA: dict = dict(_order_tool().parameters)


def show_order_schema(variant: str) -> str:
    """Put one variant of the `order` schema on the listing (`harness.surface.listing`); returns the variant."""
    tool = _order_tool()
    if tool is not None:
        tool.parameters = L.order_schema(BASE_ORDER_SCHEMA, variant)
    return variant


def order_schema_shown() -> str:
    tool = _order_tool()
    return L.variant_of(tool.parameters) if tool is not None else L.ONEOF


def _client_name(ctx) -> str | None:
    params = getattr(getattr(ctx, "session", None), "client_params", None)
    info = getattr(params, "client_info", None) or getattr(params, "clientInfo", None)
    return getattr(info, "name", None)


async def _listing_middleware(ctx, call_next):
    """Before each `tools/list`: the `order` schema variant for the client that asked (its `clientInfo` name
    from the handshake; `CIV5_ORDER_SCHEMA` overrides). A stdio server has one client, so this settles once."""
    if getattr(ctx, "method", None) == "tools/list":
        show_order_schema(L.variant_for(_client_name(ctx)))
    return await call_next(ctx)


show_order_schema(L.variant_for(None))
if hasattr(mcp, "middleware"):            # mcp 2.x; a 1.x server shows the environment's variant, or oneOf
    mcp.middleware.append(_listing_middleware)
