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
from harness import gate as G
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
    "Read the game as my seat sees it: the empire, units, cities, civs and city-states, the map, the league, spies, the "
    "screens, and the choices open to me (research, policies, beliefs, trade routes). Read-only, no side effect, usable "
    "while it is not my turn. Use it before an order (its rows ARE the orders) and after one to verify; use reference for "
    "what things do, question for what a popup asks, turn for the turn's own state.\n"
    "How to call: `what` names the object, `view` the part of it (left out: the default view), `id` the one object. "
    "Objects and their views:\n"
    + "\n".join(f"  {what}: {', '.join(views)}" for what, views in V.VIEWS.items())
    + "\nSelectors, by view: x, y, radius for map/window and unit/tactical; mission for unit/targets; kind for "
    "options/beliefs and compare; detail ('summary' / 'full') where a view has both; since and limit for lists; item "
    "and yield_type for city/production to price one item; `args` for the rest by the old call's name.\n"
    "Returns: the object as JSON (a list for units, cities, civs; one dict otherwise), with `actions` or `call` rows "
    "wherever something can be done: each row is a complete order() call to copy. A wrong `what` or `view` is refused "
    "with `choices`, and for an object that takes an id, a `hint` saying where the ids come from (unit ids from units, "
    "city-state ids from the `minor: true` rows of civs). Replies are the 1.x reads' replies unchanged."
)

# --- order ---------------------------------------------------------------------------------------------
def order(to: Annotated[str, _f("the target kind, something I own")],
          action: Annotated[str, _f("the verb; its words depend on `to`")],
          id: Annotated[int | None, _f("which unit, city, civ, city-state or spy; empire and league take none")] = None,
          args: Annotated[dict | None, _f("the action's arguments by name, as the copied row has them; a refusal shows the shape with an example")] = None,
          action_id: Annotated[str | None, _f("a token of my choosing: a retry with the same action_id replays the stored result instead of acting twice")] = None) -> str:
    return _run(D.resolve("order", {"to": to, "action": action}, _given(id=id, args=args)), action_id=action_id)


order.__doc__ = (
    "An order to something I own: `to` the target kind, `id` which one, `action` the verb, `args` its arguments by name. "
    "It changes the game, and most of it cannot be undone (a disbanded unit, a declared war, a purchase). Not a read: "
    "inspect shows the state and hands back the rows, question / answer settle what a popup asks, turn(action='finish') "
    "ends the turn. to: actions --\n"
    + "\n".join(f"  {to}: {', '.join(a for a in acts if a != V.SCREEN_BUTTON)}"
                + (f" (or a city-state screen button by its name: {', '.join(V.SCREEN_BUTTONS)})"
                   if V.SCREEN_BUTTON in acts else "")
                for to, acts in V.ACTIONS.items())
    + "\nHow: copy the rows a read hands back (`actions`, `call`) as they are; `id` is a unit, city, civ, city-state or spy "
    "id (empire and league take none); `args` holds what the row holds (a plot's x and y, an item's name, a deal's items, "
    "an amount). An order runs whole or not at all. `action_id`: a token of mine; a retry with the same one replays the "
    "stored reply instead of acting twice.\n"
    "Returns {ok: true, ...} with what changed (a unit's new plot and moves left, a city's queue, a deal's answer), or "
    "{ok: false, err, choices / accepts, example}: the verb is not one of the target's (choices lists them), an argument "
    "is missing (accepts names the shape, example a complete call), or the game refuses it (err names the rule, e.g. the "
    "unit has no moves, the city is not mine, another client of my seat holds this turn's claim). Nothing is acted on "
    "when ok is false."
)

# --- question / answer -----------------------------------------------------------------------------------
def question() -> str:
    ts, gate = _gate_now()
    blocker = G.blocker_question(ts) if gate is None else None
    read = D.question_read(gate, blocker)
    if read is not None:
        try:
            reply = json.loads(_run_tool_here(read.tool, read.args, renamed=False))
        except ValueError:
            reply = {"ok": False, "err": "not JSON"}
        if isinstance(reply, dict):
            reply["gate"] = gate
            if blocker:
                # The engine raised the blocker without its popup (#95): the question is pending all the same,
                # and `answers` rows are answer(choice=...) calls that dispatch on the blocker.
                reply["pending"] = True
                reply["blocker"] = blocker
            return J(reply)
        return J({"ok": True, "question": reply, "gate": gate})
    if gate is not None:
        return J({"ok": True, "pending": True, "gate": gate})
    return J({"ok": True, "pending": False, "decisions": B.decisions(ts, []),
              "note": "nothing is asked; the decisions are the turn's todo (turn(action='briefing') has them in full)"})


question.__doc__ = (
    "What the game is asking right now, so answer() can settle it. Read-only; takes nothing. Use it whenever a reply's "
    "`gate` is not null or turn(action='status') says discussion_pending; use inspect for the board and reference for the "
    "rules. It shows one of: a decision popup (a tech, a production item, a policy, a promotion, a belief, a ruins reward, "
    "a captured city's fate, a Great Person's use, a dig), the leader on screen with their words and the deal on the "
    "table, or nothing pending.\n"
    "Returns the popup's own read -- the question in words plus `answers` rows, each a complete answer() call to copy "
    "(the item's name or button number, and the args the popup needs) -- with `gate` on the reply; a leader screen "
    "returns the leader, the speech, the buttons and the deal's items; when nothing is asked, {pending: false, "
    "decisions: [...]} lists the turn's open decisions instead. Several leaders can queue at a turn start: answering one "
    "returns the next under `next`."
)


def answer(choice: Annotated[str | int, _f("the `answers` row's choice: an item name, a button number, or accept / refuse / leave / accept_friendship")],
           args: Annotated[dict | None, _f("what the popup needs beyond the choice: unit_id, x and y, player_id, beliefs, city")] = None,
           action_id: Annotated[str | None, _f("a token of my choosing: a retry with the same action_id replays the stored result")] = None) -> str:
    gate = blocker = None
    if not (isinstance(choice, str) and choice in D.fixed_answers()):
        ts, gate = _gate_now()
        blocker = G.blocker_question(ts) if gate is None else None
    return _run(D.resolve("answer", {"choice": choice}, _given(args=args), gate, blocker), action_id=action_id)


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
    "Saves, loads and the seat of this game session: keep a state before a risky turn, open another save, leave a "
    "finished game, say which hotseat seat this server plays. It never plays a turn; use turn for that. Side effects: "
    "a load replaces the game on screen for everyone on it, and a hotseat game loads paused until turn(action='wait'); "
    "the notebook is per game and seat, so it follows a save of the same game and is not touched by a load. "
    "action -- save: a quick save of the game on screen into the one quick-save slot (each finished turn's autosave "
    "overwrites that slot, so copy a save you want kept); load {filename}: open that save (a name as the game lists it, "
    "without the single/ prefix; the refusal lists the legal ones), replacing the unsaved state, so save first; "
    "load_latest: open the newest save, whichever game it is; main_menu: leave the game for the main menu (the "
    "game_over gate's way out); seat {seat}: which human seat (0 or 1) this server plays in a hotseat game -- a server "
    "pinned with --seat refuses a change onto the other human seat, and never move onto the seat on screen.\n"
    "Returns {ok: true, saved / loaded, turn, seat, screen} or {ok: false, err} naming why (an unknown filename with the "
    "list, a seat that is someone else's, a game operation already running). In a game with other people ask the human "
    "before loading."
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


# --- the listing (#49): order's schema, one shape for every client -----------------------------------------
_order_tool = mcp._tool_manager.get_tool("order")
_order_tool.parameters = L.order_schema(_order_tool.parameters)   # `to` its enum, `action` the verbs by target
del _order_tool
