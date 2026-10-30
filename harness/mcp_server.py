"""MCP server: lets an LLM play Civilization V through the harness.

Run (stdio):  .venv/bin/python -m harness.mcp_server [--seat 1 | --seat auto]
Requires: the game running with the shim (scripts/launch_civ5.sh) and tunerd (python -m harness.tunerd).
Env: CIV5_TUNERD_SOCK selects the game instance (LAN mode: the LLM's own instance); CIV5_SEAT=auto (default) takes
the seat of that instance's local player in network games and seat 1 in hotseat. CIV5_ALLOW_LUA=1 (or --allow-lua)
enables the raw `lua` escape hatch, which is refused by default: an unvalidated engine call can crash the game process.

Layout: this module is the core -- the game handle (`game()`), the seat logic, the tool sets, the `guarded`
decorator every tool runs through, the batch / replay helpers and the call wrapper -- and the tools themselves
live in harness/mcp_tools/, one module per domain (turn, batch, notebook, units, cities, policies, diplomacy,
trade, front_end, reference), imported at the bottom in the order a client lists them. Every tool is also an
attribute of this module (`mcp_server.set_research`), so tests and scripts patch and call it here.

Tool design notes
- Everything returns compact JSON text; the LLM sees exactly what the game's Lua reports.
- `turn_digest` is the "what happened since my last turn" feed (recorded Events + notifications).
- Actions never block on animations; call `turn_status` to observe results.
"""
from __future__ import annotations

if __name__ == "__main__":
    # `python -m harness.mcp_server` loads this file as __main__, and the tool modules' `from harness import
    # mcp_server` would then load it a second time as harness.mcp_server -- registering every tool on that
    # copy's `mcp` while the __main__ copy served none (live 2026-09-27, the first stdio client after the split:
    # "Unknown tool: turn_status"). Run the importable module instead and never execute this copy's body.
    from harness.mcp_server import main as _main
    raise SystemExit(_main())
import argparse
import contextlib
import functools
import json
import os
import sys
import time
from typing import Any
try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as FastMCP
    from mcp.server.mcpserver import Context  # re-exported: mcp_tools/turn.py imports it from here
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp import Context  # noqa: F401
from . import call_ledger
from .client import TunerdError
from .game import Game, plain_text
from .action_lock import action_lock
from . import presence
from .turn_claim import ClaimRefused, claim_turn
from .client import DEFAULT_SOCK
from .surface import classes, forward, retirement as R
# The SDK's argument models ignore unknown keys, so a misspelled parameter (timeout vs timeout_seconds,
# city_id vs target_city_id) silently falls back to the default -- the worst kind of failure for a caller
# that cannot see the game. Forbid extras: the call is rejected with the offending field named instead.
def _forbid_unknown_tool_args() -> None:
    for modname in ("mcp.server.mcpserver.utilities.func_metadata", "mcp.server.fastmcp.utilities.func_metadata"):
        try:
            import importlib
            mod = importlib.import_module(modname)
        except ImportError:
            continue
        base = getattr(mod, "ArgModelBase", None)
        if base is not None:
            base.model_config["extra"] = "forbid"
            return
_forbid_unknown_tool_args()
from harness.gate import compute_gate, popup_gate, popup_hint, resolutions_by_key  # noqa: E402


def _may_change_seat() -> bool:
    """Only a server whose seat was guessed (--seat auto) is ever told about set_seat: a pinned server refuses
    it onto the other seat, and offering it there read as advice to take the other player's seat (live 2026-09-26)."""
    return os.environ.get("CIV5_SEAT", "auto") == "auto" and getattr(_game, "bound_seat", None) is None


def _gate(ts: dict | None, seat) -> dict | None:
    return compute_gate(ts, seat, may_change_seat=_may_change_seat())
mcp = FastMCP("civ5", instructions=(
    # Under 2000 characters on purpose: Claude Code shows the model only that much of a server's instructions
    # (measured 2026-09-27; the old 5000-character text lost everything after `compare`). The vital loop first;
    # the rest is reference(book="playbook", section=<topic>), a tool, so it survives any client's cut.
    "You play Sid Meier's Civilization V as one seat through nine tools: turn "
    "(the clock), state (read anything), order (write to anything you own), question / answer (what the game "
    "asks), notebook (your memory), batch (many orders), session (saves, loads, the seat), reference (rule book "
    "and playbook). The loop: turn(action=\"finish\") ends your turn, waits until it is yours again and returns "
    "the new turn (status, digest, notes) -> read `gate` first: null means act, otherwise nothing works until its "
    "`actions` rows are run (question() shows what is asked, answer(choice) answers) -> act on status.todo "
    "(the briefing's `decisions`): "
    "state(what=\"units\", view=\"actions\"), state(what=\"city\", id, view=\"production\"), "
    "state(what=\"options\", view=\"research\") -- every reply listing what can be done hands back `actions` / "
    "`call` rows, complete order() calls to copy -> notebook(action=\"remember\") what future-you must know, "
    "notebook(action=\"assign\") what a unit or city is for -> turn(action=\"finish\"). Before moving or "
    "attacking: state(what=\"unit\", id, view=\"tactical\"). Many orders at once: batch(actions=[{tool, args}]); "
    "the orders that close a turn go in "
    "turn(action=\"finish\", actions=[...]). A retry with the same action_id replays. A refusal never crashes "
    "anything: err says why, the shape, an example. What things DO: "
    "reference(section), read once. Diplomacy: question() shows the leader's buttons or the deal, "
    "answer(choice=<button> / \"accept\" / \"refuse\" / \"leave\"); trade through state(what=\"civ\") views "
    "and order(to=\"civ\") actions. Hotseat: a different active_player is the other player's turn "
    "(turn(action=\"wait\")); never move the seat onto the one on screen; `turn_claim` in a refusal means another "
    "client of your seat plays this turn. After a context reset: turn(action=\"briefing\", since=\"turn\"). "
    "Everything else -- the loop, the action table (section=\"orders\"), blockers, quiet turns, every reply key "
    "-- is reference(book=\"playbook\", section=<topic>); no section: the index."))
# Every tool returns one JSON string. The SDK's default (`structured_output=None`) wraps a str return as
# {"result": "<the same string>"} in structured_content, so each reply crossed the wire twice, and the Grok
# CLI (seen 2026-09-27, t55) shows its model both copies: every read cost that seat double. Text only.
_mcp_tool = mcp.tool


def _text_only_tool(*args, **kwargs):
    kwargs.setdefault("structured_output", False)
    return _mcp_tool(*args, **kwargs)
mcp.tool = _text_only_tool
_game: Game | None = None
_seat_unresolved = False   # 'auto' seat we could not detect yet, because no game was running
_seat_rechecked = False    # an auto seat gets one free re-detection the first time it looks wrong


def _resolve_seat(g: Game) -> bool:
    """Detect the seat this instance plays; False means "could not tell yet, ask again later".

    Detection needs a loaded game, and this server is routinely started before the game is
    (or while it is still on the main menu). Live 2026-09-21: the server came up first, detection
    raised, the seat silently stayed at its hotseat default of 1, and then every tool in a solo
    game where we are player 0 answered "this seat is not active" -- with no way out, because
    restarting the MCP server is what loses the tools for the rest of the session."""
    try:
        if g.mode() == "hotseat":
            return True    # hotseat cannot be detected from the engine; 1 is the documented default
        g.detect_seat()
        return True
    except (TunerdError, TimeoutError, OSError, KeyError, ValueError):
        g._mode = None     # mode() caches; a failed probe must not pin "no game" as the answer
        return False


def _recheck_seat(g: Game, ts: dict) -> dict:
    """One free re-detection the first time an auto seat disagrees with the engine.

    A seat detected at the wrong moment (solo game, AI half of the turn) used to be permanent:
    every tool refused with "this seat is not active" and the only cure -- restarting the server --
    is what loses the tools. Re-detect once, then trust the answer; an AI genuinely holding the
    turn stays a plain refusal and never costs a second probe."""
    global _seat_rechecked
    if _seat_rechecked or os.environ.get("CIV5_SEAT", "auto") != "auto":
        return ts
    _seat_rechecked = True
    before = g.seat
    if not _resolve_seat(g) or g.seat == before:
        return ts
    return g.turn_state()


def _seat_refusal(g: Game, ts: dict) -> dict:
    """The "this seat is not active" refusal with everything the caller needs to get out of it: which seat
    this server plays, whose turn it is, and the tool that changes the seat. Live 2026-09-25: a hotseat save
    loaded under --seat auto put the server on its default seat 1 while seat 0 held the turn; every tool
    refused with only active_player=0, and nothing said which seat the server thought it was."""
    out = {"ok": False, "err": "this seat is not active", "seat": g.seat, "active_player": ts.get("active_player")}
    try:
        mode = g.mode()
    except (TunerdError, TimeoutError, OSError, KeyError, ValueError):
        mode = None
    out["gate"] = _gate({**ts, "hotseat": ts.get("hotseat", mode == "hotseat")}, g.seat)
    if mode == "hotseat" and ts.get("active_turn_active") is False:
        out["hint"] = (f"hotseat: seat {ts.get('active_player')} has ended its turn and the AIs are moving before seat "
                       f"{g.seat}'s begins (an AI round can take minutes). turn(action='wait') waits for this seat's turn")
    elif mode == "hotseat":
        out["hint"] = (f"hotseat: this server plays seat {g.seat} and seat {ts.get('active_player')} is on screen: "
                       "it is not your turn. turn(action='wait') waits for this seat's turn")
        if _may_change_seat():
            out["hint"] += (f"; only if nobody else plays seat {ts.get('active_player')} (the --seat auto default "
                            f"is 1 and may be wrong), session(action='seat', args={{seat: {ts.get('active_player')}}}) moves this server there")
    elif mode == "single":
        out["hint"] = ("solo game: the AIs are moving; turn(action='wait') / turn(action='finish') wait for our turn. "
                       "If the human seat never becomes active, session(action='seat') re-detects it")
    else:
        out["hint"] = "another player holds the turn: turn(action='wait') / turn(action='finish') wait for ours"
    return out


def _sock() -> str:
    return os.environ.get("CIV5_TUNERD_SOCK") or DEFAULT_SOCK


def _op(g) -> Any:
    """One operation on `g` outside a guarded call: the game's own per-poll lock (a no-op on a fake)."""
    return getattr(g, "lock", contextlib.nullcontext)()


def game() -> Game:
    global _game, _seat_unresolved
    if _game is None:
        g = Game(os.environ.get("CIV5_TUNERD_SOCK"))
        # The wait loops take the per-socket operation lock once per poll through this (game.py holds
        # no lock of its own), so that between polls another seat's server can act. See action_lock.py.
        g.lock = lambda: action_lock(_sock(), seat=g.seat, tool="wait poll")
        # The turn's first mutating command claims it for this process; end_turn / finish_turn and every
        # order from another client of the same seat are refused until it idles out. See turn_claim.py (#41).
        g.claim = lambda turn, tool, force=False: claim_turn(_sock(), g.seat, turn, tool, force=force,
                                                             client=call_ledger.client(_client_info()))
        seat = os.environ.get("CIV5_SEAT", "auto")
        bound = g.bound_seat
        if bound is not None:
            # tunerd bound this connection to one seat by its token (or uid): the only seat this process may
            # play. A different --seat (what scripts/mcp_call.py and mcp_session.py pass as CIV5_SEAT) is a
            # misconfiguration, refused here on every tool rather than overridden in silence; the daemon would
            # refuse each call that named the other seat anyway ("A seat bound to its channel", stage 4).
            if seat != "auto" and int(seat) != bound:
                g.c.close()
                raise TunerdError(f"this server was started with --seat {seat} but its tunerd connection is bound "
                                  f"to seat {bound} by its token: seat {seat} is another player's. Start it with "
                                  f"--seat {bound} or --seat auto")
            g.seat = bound
            _seat_unresolved = False
        elif seat == "auto":
            # network game: this instance's local player; hotseat: seat must be given (defaults to 1)
            g.seat = 1
            _seat_unresolved = not _resolve_seat(g)
        else:
            g.seat = int(seat)
        _game = g
    elif _seat_unresolved:
        _seat_unresolved = not _resolve_seat(_game)
    return _game


def J(v: Any) -> str:
    v = plain_text(v)  # "[COLOR_POSITIVE_TEXT]Free Thought[ENDCOLOR][NEWLINE]+1 [ICON_RESEARCH] Science" -> readable
    return json.dumps(v, separators=(",", ":"), ensure_ascii=False)
# How a call is treated -- a menu tool, usable any time, a wait, a read, a response, a save -- is decided by its
# `(tool, action)` key in harness/surface/classes.py (MENU, ANYTIME, WAIT, HARMLESS, RESPONSE, SAVE, ...); an old
# handler's key is its row's in the retirement map (classes.of_handler), so the guard below never looks at a name.
PROGRESS_EVERY = 5.0  # seconds between progress notifications while waiting


def progress_reporter(ctx, seat=None):
    """An `on_wait` callback for Game.wait_for_my_turn / finish_turn: sends an MCP progress notification
    every PROGRESS_EVERY seconds so a client's idle timeout does not cut a long wait short. Tools run in a
    worker thread (the SDK's anyio.to_thread), so the async notify is hopped back onto the event loop.
    Silent when there is no request context (tests, HTTP) or the client did not ask for progress.
    `seat` names the player waited for in each message, so a wait on the wrong seat is visible."""
    if ctx is None:
        return None
    import anyio
    state = {"last": -PROGRESS_EVERY, "n": 0}

    def on_wait(elapsed: float, ts: dict) -> None:
        immediate = "skipping_quiet_turn" in ts or "ending_turn" in ts
        if elapsed - state["last"] < PROGRESS_EVERY and not immediate:
            return
        state["last"], state["n"] = elapsed, state["n"] + 1
        if "skipping_quiet_turn" in ts:
            msg = f"turn {ts.get('skipping_quiet_turn')} was quiet; ending it too"
        elif "ending_turn" in ts:
            msg = f"ending turn {ts.get('ending_turn')}"
        elif ts:
            who = f" (seat {seat})" if seat is not None else ""
            msg = (f"waiting for my turn{who}: {elapsed:.0f}s, turn {ts.get('turn')}, "
                   f"active player {ts.get('active_player')}")
        else:
            msg = f"waiting for my turn: {elapsed:.0f}s"
        try:
            anyio.from_thread.run(ctx.report_progress, float(state["n"]), None, msg)
        except Exception as e:  # progress is best effort; never let it break the wait
            if state["n"] == 1:
                print(f"civ5: progress notification failed: {e!r}", file=sys.stderr, flush=True)
    return on_wait


def _claim_for(g, ts: dict, tool: str, force: bool = False) -> dict | None:
    """Game._claim_turn on a real Game; a fake without the method or claim is nobody's to contest."""
    claim = getattr(g, "claim", None)
    if claim is None:
        return None
    try:
        claim(ts.get("turn"), tool, force)
    except ClaimRefused as e:
        return {"ok": False, "err": str(e), "turn_claim": e.info, "turn": ts.get("turn"), "gate": _gate(ts, g.seat)}
    return None


def _refusal_for(g, ts: dict, key: tuple[str, str]) -> dict | None:
    """Why the call with this `(tool, action)` key may not run on this turn_state -- the refusal to return -- or
    None when it may. The order is the gate's (harness/gate.py): the first precondition that stops the seat
    wins, because clearing it is what makes the next one visible. Reads and responses skip every check: looking
    never changes the game, and a response's input IS the pending thing."""
    if key in classes.HARMLESS or key in classes.RESPONSE:
        return None
    # Every refusal below carries `gate`, the same object turn_status shows: the one thing that must happen
    # first and the tool that does it.
    gate = _gate(ts, g.seat)
    if ts["paused"] or ts["processing"] or not ts["my_turn"]:
        if gate and gate["name"] == "hand_off_screen":
            return {"ok": False, "err": "the hotseat hand-off screen is still up for this seat after Continue "
                                        "was pressed for you; turn(action='wait') presses it again", "gate": gate}
        if gate and gate["name"] == "load_screen":
            return {"ok": False, "err": "the Dawn of Man splash is still up after its button was pressed for you; "
                                        "turn(action='wait') presses it again", "gate": gate}
        return {"ok": False, "err": "game is paused, processing, or waiting; use turn(action='wait')", "gate": gate}
    # H.turn_state carries the modal flags since runtime v214; asking the game again cost every mutating call a
    # second trip (live t151: turn_state + modal_flags before each order). A status without the flag still asks.
    discussion = ts["discussion_pending"] if isinstance(ts.get("discussion_pending"), bool) else g.discussion_pending()
    if discussion:
        return {"ok": False, "err": "diplomatic decision pending",
                "gate": gate if gate and gate["name"] == "discussion" else _gate({**ts, "discussion_pending": True}, g.seat)}
    if ts.get("leader_greeting_pending"):
        # A leader screen (a greeting, or the echo of a war just declared) freezes the engine's update loop:
        # orders pushed underneath it half-apply -- the unit moves, but its mission timer never runs, so it
        # stays "busy" and every later order is refused as not legal (live 2026-09-24 t218, two-human hotseat:
        # two Artillery set up under Bravo's war-declared screen could not fire until it was closed). A human
        # cannot click the map with that screen up either.
        return {"ok": False, "err": "a leader screen is up and the game is frozen behind it; "
                                    "question() reads it, answer(choice='leave') closes it", "gate": gate}
    # found_pantheon is not here: the engine reports one blocker at a time, so a pending pantheon can sit
    # behind e.g. PRODUCTION (live t22); H.found_pantheon checks CanCreatePantheon itself.
    required = classes.REQUIRED_BLOCKER.get(key)
    if required and ts["blocking_name"] != required:
        return {"ok": False, "err": "this religious choice is not pending"}
    if ts.get("pending_popups") and key not in classes.SAVE:
        # key -> the decision popups it may run under (harness/gate.py, one table for this allow-list, for
        # the gate that names the popup's resolver and for the hint). A save runs under any popup and sweeps
        # none of them.
        allowed = resolutions_by_key().get(key, set())
        pending = ts["pending_popups"]
        if any(p["name"] not in allowed for p in pending):
            g.dismiss_pending_popups()
            pending = g.turn_state().get("pending_popups", [])
        unresolved = [p for p in pending if p["name"] not in allowed]
        if unresolved:
            return {"ok": False, "err": "popup needs a decision", "pending_popups": unresolved,
                    "gate": popup_gate(unresolved[0]), "hint": popup_hint(unresolved[0]["name"])}
    return None


def _arrival_before(g, ts) -> dict | None:
    """The turn's arrival work before a mutating order, when it is still due (Game.arrive_if_due). The arrival
    marks itself done as it starts, so a failure here is not retried by the next call: it is reported instead,
    and the order itself still runs."""
    arrive = getattr(g, "arrive_if_due", None)   # a bare fake has none
    if arrive is None:
        return None
    try:
        return arrive(ts)
    except (TunerdError, TimeoutError, OSError, ValueError) as e:
        return {"err": f"the turn's arrival work (standing moves, open orders) failed: {e}",
                "hint": "check notebook(action=\"orders\") and the units with a standing move; the turn's own orders still run"}


def _with_arrival(out: str, arrival: dict, target: int | None = None) -> str:
    """`arrival` added to a tool's JSON reply (an object only; anything else comes back untouched). `target` is
    the city-state the order itself addressed: its expiring-ally row, computed before the order, is dropped
    (GitLab #64, Assyria t239: a 250-gold gift's reply carried "Colombo, influence 60, 1 turn left: gift_gold to
    keep it" about the city-state it had just fixed)."""
    try:
        d = json.loads(out)
    except (TypeError, ValueError):
        return out
    if not isinstance(d, dict):
        return out
    if target is not None and isinstance(arrival, dict) and isinstance(arrival.get("expiring_city_states"), list):
        rows = arrival["expiring_city_states"]
        kept = [r for r in rows if not (isinstance(r, dict) and r.get("player_id") == target)]
        if len(kept) != len(rows):
            arrival = {**arrival, "expiring_city_states": kept,
                       "expiring_city_states_note": f"the row for city-state {target} was read before this order ran: "
                                                    "this reply's own influence is the current one"}
            if not kept:
                arrival.pop("expiring_city_states", None)
    d["arrival"] = arrival
    return J(d)


def _city_state_target(kwargs: dict) -> int | None:
    """The city-state a write addresses, from its own arguments (minor_id / player_id), else None."""
    for key in ("minor_id", "player_id"):
        v = kwargs.get(key)
        if isinstance(v, int) and not isinstance(v, bool):
            return v
    return None


def guarded(fn):
    """Every tool but `do` runs through here: one action at a time per socket (action_lock), the seat check,
    the hotseat hand-off, then _refusal_for (what the turn state forbids) and the turn claim (one client
    owns a seat's turn between calls). Any failure comes back as a readable JSON error, never the MCP
    layer's bare "Error executing tool"."""
    key = classes.of_handler(fn.__name__)   # the handler's (tool, action): what every set below is keyed by

    @functools.wraps(fn)
    def wrapper(*a, **k):
        try:
            seat = getattr(_game, "seat", None)
            if seat is None and os.environ.get("CIV5_SEAT", "auto") != "auto":
                seat = int(os.environ["CIV5_SEAT"])
            if seat is not None:   # this server's row among the seat's clients (GitLab #61); never in the way
                try:
                    presence.touch(_sock(), seat, call_ledger.client(_client_info()))
                except Exception:
                    pass
            if key in classes.WAIT:
                with action_lock(_sock(), seat=seat, tool=fn.__name__):
                    game()   # connect (and inject the runtime on a first call) as one operation
                return fn(*a, **k)   # then each poll is its own operation; nothing is held while sleeping
            with action_lock(_sock(), seat=seat, tool=fn.__name__):
                g = game()
                # Front-end tools: usable from the main menu, where there is no InGame state at all.
                if key in classes.MENU:
                    if g.has_state("InGame") and key != ("turn", "status"):
                        return J({"ok": False, "err": "a game is already loaded; these tools only work from the main menu",
                                  "turn": g.turn_state().get("turn")})
                    return fn(*a, **k)
                if key not in classes.ANYTIME:
                    ts = g.turn_state()
                    if ts["active_player"] != g.seat:
                        ts = _recheck_seat(g, ts)
                    if ts["active_player"] != g.seat:
                        return J(_seat_refusal(g, ts))
                    if (ts.get("hotseat") and ts.get("hand_off_pending")) or ts.get("load_screen_pending"):
                        # Our own Continue screen, or the Dawn of Man splash of a game started by hand (#96):
                        # press it here, as the seat's human would before anything else, so the first call
                        # after a (re)start meets a game state and not a UI gate.
                        ts = g.clear_hand_off(ts)
                    # An announcement screen (a Great Person born, a city-state met, a wonder, an era) is closed
                    # here for every tool, reads included, as the seat's human would click it away before
                    # looking at anything: the gate then never asks the agent to spend a call on it.
                    settle = getattr(g, "settle_announcements", None)   # a bare fake has none
                    ts = settle(ts) if settle else ts
                    refused = _refusal_for(g, ts, key)
                    if refused is not None:
                        return J(refused)
                    if key not in classes.HARMLESS and key != ("turn", "end"):
                        # A mutating command: own the turn for this process, or learn who does. end_turn claims
                        # inside Game (so its `force` applies there); `do` (not guarded) takes over with force=true.
                        refused = _claim_for(g, ts, fn.__name__)
                        if refused is not None:
                            return J(refused)
                        # A turn that no wait of ours opened (the AI round ran on after a leader was answered at
                        # the end of the last one, live t95) has had no arrival: its standing moves and open
                        # orders would sit out the turn. It runs before this first order of the turn, once per
                        # turn, and rides on the order's reply as `arrival` (what the wait would have reported).
                        arrival = _arrival_before(g, ts)
                        if arrival:
                            return _with_arrival(fn(*a, **k), arrival, _city_state_target(k))
                return fn(*a, **k)
        except (TunerdError, TimeoutError, OSError, ValueError) as e:
            return J({"ok": False, "err": str(e)})
        except Exception as e:  # a harness bug must still come back as a readable JSON error,
            # not the MCP layer's bare "Error executing tool" (which hides the cause and, for the trade flow,
            # can leave a leader screen open that every later action then refuses on).
            return J({"ok": False, "err": f"harness error: {type(e).__name__}: {e}", "tool": fn.__name__})
    return wrapper


def lua_allowed() -> bool:
    """The raw `lua` tool is opt-in (env CIV5_ALLOW_LUA / --allow-lua)."""
    return os.environ.get("CIV5_ALLOW_LUA", "").strip().lower() in {"1", "true", "yes", "on"}

MAX_BATCH = 40
# The 145 old handlers, off the listing (stage 2e, #52): each still answers to its name through the retirement
# map (`find_tool`) with `renamed` on the reply, and the nine listed tools run them by name. (Until stage 2d this
# was `--tools compact`, a core set plus `call(tool, args)` for the rest; with nine listed tools nothing needs
# hiding, and since 2e nothing but the nine is listed.)
_RETIRED: dict = {}     # name -> Tool


def retire(name: str) -> None:
    """Take a registered tool off the client's listing; it keeps its guard, ledger row and replay wrappers and
    runs by its name through the retirement map, in a batch row, or through `call`."""
    tm = mcp._tool_manager
    tool = tm.get_tool(name)
    if tool is not None:
        _RETIRED[name] = tool
        tm.remove_tool(name)


def retired_tools() -> dict:
    return _RETIRED


def retired(fn):
    """`@retired` where `@mcp.tool()` stood (stage 2e, #52): the handler is registered for its schema, guard,
    ledger and replay wrappers, then taken off the listing at once. It answers to its old name through the
    retirement map (`find_tool`), with `renamed` on the reply; the nine listed tools run it by that name."""
    mcp.tool()(fn)
    retire(fn.__name__)
    return fn


def retired_names_on() -> bool:
    """Whether an old name still answers (`CIV5_RETIRED_NAMES` / `--retired-names`; on by default). Off, a server
    knows the nine tools alone: what a session that was never shown an old name must be able to play on."""
    return os.environ.get("CIV5_RETIRED_NAMES", "on").strip().lower() not in {"off", "0", "false", "no"}


def tool_catalog() -> dict:
    """Every tool, listed or retired, by domain module: "name(args): first sentence"."""
    tm = mcp._tool_manager
    out: dict[str, list[str]] = {}
    for tool in list(tm.list_tools()) + list(_RETIRED.values()):
        mod = (getattr(tool.fn, "__module__", "") or "").rsplit(".", 1)[-1] or "other"
        desc = " ".join((tool.description or "").split())
        cut = desc.find(". ")
        first = desc if cut < 0 else desc[:cut + 1]
        if len(first) > 200:
            first = first[:197] + "..."
        out.setdefault(mod, []).append(f"{tool.name}{tool_signature(tool.parameters)}: {first}")
    return out
# (tool, action_id) -> result JSON of a call already made. A client that retries after a transport timeout
# gets the first result back (with replayed=true) instead of moving the unit twice. Bounded, per process.
_RECENT: dict = {}
RECENT_MAX = 500


def _remember_result(name: str, action_id, result) -> None:
    if action_id is None or not isinstance(result, str):
        return
    # A refusal at a gate (not your turn, hand-off screen, paused, a popup up) is about the moment, not the
    # order: replaying it would refuse the retry after the gate cleared (live 2026-09-26: a city strike retried
    # with its action_id got the cached "game is paused" back while the game had long since resumed).
    try:
        v = json.loads(result)
    except ValueError:
        v = None
    if isinstance(v, dict) and v.get("ok") is False and v.get("gate"):
        return
    if len(_RECENT) >= RECENT_MAX:
        del _RECENT[next(iter(_RECENT))]
    _RECENT[(name, str(action_id))] = result


def _replayed(name: str, action_id):
    if action_id is None:
        return None
    prior = _RECENT.get((name, str(action_id)))
    if prior is None:
        return None
    try:
        v = json.loads(prior)
    except ValueError:
        return prior
    if isinstance(v, dict):
        v["replayed"] = True
        v["replay_note"] = "this action_id was already carried out; this is the earlier result, nothing ran again"
        return J(v)
    return prior


def find_tool(name: str, exact: bool = False):
    """The handler a called name means: `(name, Tool, forwarded)`, or None. A listed tool is itself. An unlisted
    name goes through the retirement map (`harness.surface.forward`: an old name the listing no longer carries,
    or an alias such as `summary`) to its old handler, listed or retired, and `forwarded` is that old name --
    the reply then carries `renamed`, the new call. With the retired names off, an unlisted name is unknown.
    `exact` is the nine tools' own path to the handler they dispatch to: by its exact name, listed or retired,
    never through the map, so they answer whether or not the old names do."""
    tm = mcp._tool_manager
    tool = tm.get_tool(name)
    if tool is not None:
        return name, tool, None
    if exact:
        tool = _RETIRED.get(name)
        return (name, tool, None) if tool is not None else None
    old = forward.old_name(name) if retired_names_on() else None
    if old is not None:
        tool = tm.get_tool(old) or _RETIRED.get(old)
        if tool is not None:
            return old, tool, old
    return None


def known_tool_names() -> list[str]:
    """The names a caller may use: the listing, plus the retired names while they answer."""
    tm = mcp._tool_manager
    retired = (set(_RETIRED) | set(R.RENAMED_TOOLS)) if retired_names_on() else set()
    return sorted(set(t.name for t in tm.list_tools()) | retired)


def _run_tool_here(name: str, args: dict, ctx=None, renamed: bool = True) -> str:
    """Call one tool by any name it answers to -- listed, retired or an alias (`find_tool`) -- with the
    SDK's own argument validation, synchronously (a batch runs in the worker thread already, so no event-loop
    hop). Returns the tool's JSON string, or a JSON error. A name reached through the retirement map gets
    `renamed` on its reply, unless the caller is the new surface itself running an old handler
    (`renamed=False`: the nine tools' replies are the old replies exactly). `ctx` is handed to a tool that
    takes the request context (the nine pass theirs on, so a wait keeps its progress notifications)."""
    found = find_tool(name, exact=not renamed)
    if found is None:
        return J({"ok": False, "err": unknown_tool_hint(name, known_tool_names())})
    name, tool, forwarded = found
    reply = _run_handler(tool, args, ctx)
    return forward.marked(reply, forward.renamed(forwarded, args)) if forwarded and renamed else reply


def _tool_error_type():
    """The SDK's ToolError (mcp 1.x and 2.x keep it in different packages)."""
    return sys.modules[type(mcp._tool_manager).__module__].ToolError


def _run_handler(tool, args: dict, ctx=None, strict: bool = False) -> str:
    """Run one found Tool with its arguments as the SDK would validate them. A validation failure comes back as
    a JSON error the caller reads (a batch row, `call`), or with `strict` is raised as the SDK's ToolError, the
    way a listed tool's failure reaches a client (the call wrapper runs a retired name that way)."""
    name = tool.name
    args = alias_arguments(dict(args or {}), tool.parameters)
    try:
        meta = tool.fn_metadata
        if hasattr(meta, "validate_arguments"):
            validated = meta.validate_arguments(args)
        else:  # mcp 1.x
            validated = meta.arg_model.model_validate(meta.pre_parse_json(args)).model_dump_one_level()
    except Exception as e:  # a validation error is the caller's to read
        if strict:
            raise _tool_error_type()(f"Error executing tool {name}: {e}") from e
        return J({"ok": False, "err": f"{type(e).__name__}: {e}", "accepts": f"{name}{tool_signature(tool.parameters)}"})
    ctx_kwarg = getattr(tool, "context_kwarg", None)
    if ctx_kwarg:
        validated[ctx_kwarg] = ctx
    r = tool.fn(**validated)
    return r if isinstance(r, str) else J(r)
def unknown_tool_hint(name: str, known: list[str]) -> str:
    """The SDK's bare "Unknown tool: X" leaves the caller to list and guess; name the likely tools instead (the
    aliases a caller plausibly reaches for live in the retirement map, `harness.surface.forward.ALIASES`)."""
    import difflib
    hints = [forward.ALIASES[name]] if forward.ALIASES.get(name) in known else []
    hints += [n for n in difflib.get_close_matches(name, known, n=4, cutoff=0.5) if n not in hints]
    hints += [n for n in known if name in n and n not in hints][:4]
    return f"Unknown tool: {name}" + (f". Did you mean: {', '.join(hints[:5])}?" if hints else
                                      ". List the tools your client was given (tools/list).")


def _hint_unknown_tools() -> None:
    """Install the call wrapper (unknown-tool hints, argument aliases, action_id replay) once per process."""
    tm = mcp._tool_manager
    if getattr(tm, "_civ5_wrapped", False):
        return
    tm._civ5_wrapped = True
    orig = tm.call_tool
    tool_error = _tool_error_type()

    import inspect
    converts_here = "convert_result" in inspect.signature(orig).parameters  # mcp 2.x: the manager converts

    def convert(tool, raw, want):
        if want and hasattr(tool.fn_metadata, "convert_result"):
            return tool.fn_metadata.convert_result(raw)
        return raw

    async def call_tool(name, arguments, *a, **kw):
        found = find_tool(name)
        if found is None:
            raise tool_error(unknown_tool_hint(name, sorted(t.name for t in tm.list_tools())))
        requested = name    # the name the client used: the ledger row's `called` (an alias stays an alias there)
        # An unlisted name (retired from the listing, or an alias) runs its handler here; one reached through
        # the retirement map gets `renamed` on its reply.
        name, tool, forwarded = found
        unlisted = tm.get_tool(name) is None
        want_convert = bool(kw.pop("convert_result", False)) if converts_here else False
        action_id = None
        if isinstance(arguments, dict) and "action_id" in arguments and "action_id" not in tool.parameters.get("properties", {}):
            arguments = dict(arguments)
            action_id = arguments.pop("action_id")
            prior = _replayed(name, action_id)
            if prior is not None:
                return convert(tool, prior, want_convert)
        arguments = alias_arguments(arguments, tool.parameters)
        log = call_ledger.path()
        # The SDK hands the per-request Context to call_tool (keyword `context`, or the first positional):
        # read the client's label through it, and keep it for the claim (written off-request, in a thread).
        context = kw.get("context") if "context" in kw else (a[0] if a else None)   # the SDK's per-request Context
        who = call_ledger.client(_client_info(context))
        if log:
            c = getattr(_game, "c", None)
            trips0, t0 = getattr(c, "trips", None), time.perf_counter()
        try:
            if unlisted:
                # A retired handler runs as a listed one would: in the worker thread, with the request context
                # (a wait keeps its progress notifications), a bad argument raised as the SDK's error.
                import anyio
                result = await anyio.to_thread.run_sync(
                    lambda: _run_handler(tool, arguments if isinstance(arguments, dict) else {}, context, strict=True))
            elif converts_here:
                result = await orig(name, arguments, *a, convert_result=False, **kw)
            else:
                result = await orig(name, arguments, *a, **kw)
            if forwarded:
                result = forward.marked(result, forward.renamed(forwarded, arguments if isinstance(arguments, dict) else {}))
            _remember_result(name, action_id, result)
            if log:
                c = getattr(_game, "c", None)
                trips1 = getattr(c, "trips", None)
                trips = trips1 - (trips0 or 0) if isinstance(trips1, int) else None
                call_ledger.append(log, call_ledger.row(requested, getattr(_game, "seat", None),
                                                        call_ledger.reply_text(result),
                                                        time.perf_counter() - t0, trips,
                                                        args=arguments if isinstance(arguments, dict) else None,
                                                        client_label=who))
            return convert(tool, result, want_convert)
        except tool_error as e:
            if log:
                call_ledger.append(log, {**call_ledger.row(requested, getattr(_game, "seat", None), "",
                                                           time.perf_counter() - t0, None,
                                                           args=arguments if isinstance(arguments, dict) else None,
                                                           client_label=who),
                                         "ok": False, "err": str(e)[:call_ledger.ERR_CHARS]})
            # A pydantic rejection names the bad keys but not the good ones (live t324: x/y passed to
            # establish_trade_route, whose parameters are dest_x/dest_y). Append the signature.
            if type(e.__cause__).__name__ != "ValidationError":
                raise
            raise tool_error(f"{e}\n{name} accepts: {tool_signature(tool.parameters)}") from e.__cause__
    tm.call_tool = call_tool


_CLIENT_INFO = None   # the clientInfo of the first request that carried one: this process has one client


def _client_info(context=None):
    """The connected client's clientInfo (name, version) from the MCP initialize handshake. `context` is the
    SDK's per-request Context, which the tool manager passes to call_tool (mcp 2.x: there is no
    request_context on the server object, so the earlier server-attribute path always answered None and
    every row of a Claude Code / stdio session went unlabelled, 2026-10-04). The first one seen is kept:
    the turn claim is written from a worker thread with no context at hand, and a stdio server has exactly
    one client. None outside a request (tests call the tool manager directly)."""
    global _CLIENT_INFO
    info = None
    try:
        rc = context.request_context if context is not None else None
        params = getattr(getattr(rc, "session", None), "client_params", None)
        # mcp 2.x spells the InitializeRequestParams field client_info; 1.x spelled it clientInfo.
        info = getattr(params, "client_info", None) or getattr(params, "clientInfo", None)
    except Exception:
        info = None
    if info is None:
        try:
            srv = getattr(mcp, "_mcp_server", None) or getattr(mcp, "_lowlevel_server", None)
            params = srv.request_context.session.client_params
            info = getattr(params, "client_info", None) or getattr(params, "clientInfo", None)
        except Exception:
            info = None
    if info is not None:
        _CLIENT_INFO = info
    return info if info is not None else _CLIENT_INFO


def alias_arguments(arguments, schema: dict):
    """Rename a key the tool lacks to the one obvious parameter it means: `k` -> `k_id` or `dest_k` (live t438/443:
    button for respond_discussion's button_id, x/y for establish_trade_route's dest_x/dest_y). Only when exactly one
    such parameter exists and the caller did not also pass it; anything else is left for validation to reject."""
    if not isinstance(arguments, dict):
        return arguments
    props = schema.get("properties", {})
    out = dict(arguments)
    for k in list(arguments):
        if k in props:
            continue
        targets = [t for t in (f"{k}_id", f"dest_{k}") if t in props and t not in arguments]
        if len(targets) == 1:
            out[targets[0]] = out.pop(k)
    return out


def tool_signature(schema: dict) -> str:
    props, required = schema.get("properties", {}), set(schema.get("required", []))
    parts = []
    for k, p in props.items():
        t = p.get("type") or "/".join(x.get("type", "?") for x in p.get("anyOf", [])) or "any"
        parts.append(f"{k}: {t}" + ("" if k in required else f" = {p.get('default')!r}"))
    return "(" + ", ".join(parts) + ")"

# ------------------------------------------------------------------ the tools, one module per domain
# Imported here, after everything they take from this module exists (mcp, guarded, J, the tool sets, the
# batch and replay helpers). Each module registers its tools on `mcp` as it loads; the order is the order
# a client lists them in. Every tool is also an attribute of this module, as before the split.
import importlib  # noqa: E402

from . import mcp_tools  # noqa: E402

for _modname in (*mcp_tools.MODULE_NAMES, mcp_tools.SURFACE_MODULE):
    # imported by name, never bound here: units, cities, diplomacy and reference are tools as well as modules
    _mod = importlib.import_module(f"harness.mcp_tools.{_modname}")
    for _name, _obj in vars(_mod).items():
        if getattr(_obj, "__module__", None) == _mod.__name__ and not _name.startswith("__"):
            if _name in globals():
                raise ImportError(f"tool module {_modname} defines {_name}, which the server core already has")
            globals()[_name] = _obj
del _modname, _mod, _name, _obj
from .mcp_tools.reference import register_lua_if_allowed  # noqa: E402  (the loop bound it too; named for main())


_hint_unknown_tools()  # also for embeddings that never call main() (tests, other hosts)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seat", default=os.environ.get("CIV5_SEAT", "auto"), help="player id, or 'auto' (network games: the local player)")
    ap.add_argument("--allow-lua", action="store_true", help="enable the raw `lua` escape hatch (env CIV5_ALLOW_LUA=1)")
    ap.add_argument("--retired-names", default=os.environ.get("CIV5_RETIRED_NAMES", "on"), choices=("on", "off"),
                    help="on (default): the 145 old tool names and the aliases still answer, with `renamed` on the reply; "
                         "off: the nine tools alone (env CIV5_RETIRED_NAMES)")
    a = ap.parse_args(argv)
    os.environ["CIV5_SEAT"] = str(a.seat)
    os.environ["CIV5_RETIRED_NAMES"] = a.retired_names
    if a.allow_lua:
        os.environ["CIV5_ALLOW_LUA"] = "1"
    register_lua_if_allowed()
    _hint_unknown_tools()
    mcp.run()
