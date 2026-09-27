"""MCP server: lets an LLM play Civilization V through the harness.

Run (stdio):  .venv/bin/python -m harness.mcp_server [--seat 1 | --seat auto]
Requires: the game running with the shim (scripts/launch_civ5.sh) and tunerd (python -m harness.tunerd).
Env: CIV5_TUNERD_SOCK selects the game instance (LAN mode: the LLM's own instance); CIV5_SEAT=auto (default) takes
the seat of that instance's local player in network games and seat 1 in hotseat. CIV5_ALLOW_LUA=1 (or --allow-lua)
enables the raw `lua` escape hatch, which is refused by default: an unvalidated engine call can crash the game process.

Tool design notes
- Everything returns compact JSON text; the LLM sees exactly what the game's Lua reports.
- `turn_digest` is the "what happened since my last turn" feed (recorded Events + notifications).
- Actions never block on animations; call `turn_status` to observe results.
"""
from __future__ import annotations

import argparse
import contextlib
import functools
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as FastMCP
    from mcp.server.mcpserver import Context
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP, Context

from . import call_ledger, guide
from .client import TunerdError
from .game import Game, plain_text
from .action_lock import action_lock
from .turn_claim import ClaimRefused, claim_status, claim_turn
from .client import DEFAULT_SOCK

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

from harness.gate import compute_gate, popup_gate, popup_hint, resolutions_by_tool  # noqa: E402


def _may_change_seat() -> bool:
    """Only a server whose seat was guessed (--seat auto) is ever told about set_seat: a pinned server refuses
    it onto the other seat, and offering it there read as advice to take the other player's seat (live 2026-09-26)."""
    return os.environ.get("CIV5_SEAT", "auto") == "auto"


def _gate(ts: dict | None, seat) -> dict | None:
    return compute_gate(ts, seat, may_change_seat=_may_change_seat())


mcp = FastMCP("civ5", instructions=(
    # Under 2000 characters on purpose: Claude Code shows the model only that much of a server's instructions
    # (measured 2026-09-27; the old 5000-character text lost everything after `compare`). The vital loop first;
    # the rest is how_to_play(topic), a tool, so it survives any client's cut.
    "You play Sid Meier's Civilization V as one seat (solo against the AI, or hotseat/LAN with others). "
    "The loop: finish_turn ends your turn, waits until it is yours again and returns the new turn (status, "
    "digest, notes; briefing=true for the compact briefing) -> read `gate` first: null means act, otherwise "
    "nothing works until you call its `clear_with` tool -> act on status.todo (units needing orders, empty "
    "cities, promotions) with todo_actions / available_production / available_research, glance at "
    "status.alerts -> remember() what future-you must know, assign() what a unit or city is for -> "
    "finish_turn. A multi-turn plan for one unit is one give_order(unit_id, steps). Before moving or "
    "attacking: tactical_view(unit_id). Weighing options: compare(kind, ...). Many orders at once: "
    "do(actions=[{tool, args}]). Retrying after a timeout: repeat the call with the same action_id and it "
    "replays instead of running twice. A refusal never crashes anything: err says why and what to do instead. "
    "What things DO is reference(section) (units, buildings, techs, policies, promotions, beliefs, ...), read "
    "once. Diplomacy: turn_digest carries leader_message events; discussion() shows the buttons, "
    "respond_discussion answers; trade_catalog -> negotiate_deal -> propose_deal. Hotseat: a different "
    "active_player is the other player's turn (wait_for_my_turn); never set_seat onto the seat on screen; "
    "`turn_claim` in a refusal means another client of your seat is playing this turn. After a context "
    "reset: briefing(since=\"turn\"). Everything else -- the full turn loop, the blocker table, quiet turns, "
    "verification habits, every reply key of finish_turn / briefing / turn_status / overview / compare / "
    "propose_deal / give_order -- is how_to_play(topic); how_to_play() is the index."))

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
    if mode == "hotseat":
        out["hint"] = (f"hotseat: this server plays seat {g.seat} and seat {ts.get('active_player')} is on screen: "
                       "it is not your turn. wait_for_my_turn waits for this seat's turn")
        if _may_change_seat():
            out["hint"] += (f"; only if nobody else plays seat {ts.get('active_player')} (the --seat auto default "
                            f"is 1 and may be wrong), set_seat({ts.get('active_player')}) moves this server there")
    elif mode == "single":
        out["hint"] = ("solo game: the AIs are moving; wait_for_my_turn / finish_turn wait for our turn. "
                       "If the human seat never becomes active, set_seat() re-detects it")
    else:
        out["hint"] = "another player holds the turn: wait_for_my_turn / finish_turn wait for ours"
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
        g.claim = lambda turn, tool, force=False: claim_turn(_sock(), g.seat, turn, tool, force=force)
        seat = os.environ.get("CIV5_SEAT", "auto")
        if seat == "auto":
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


MENU_TOOLS = {"turn_status", "load_save", "load_latest"}
# Usable while it is not our turn: the two that wait for it, and the notebook (a human jots a plan
# while the AIs move; so may we).
ANYTIME_TOOLS = {"wait_for_my_turn", "finish_turn", "remember", "recall", "forget", "close_assignment", "set_seat",
                 "exit_to_main_menu", "orders", "cancel_order",
                 "reference"}  # the rule book is the civilopedia: static, readable between turns
# The two that sleep: they lock per poll inside Game (game().lock) instead of for the whole call, so an
# inactive seat waiting in one process never starves the active seat in another (NOTES.md 2026-09-26).
WAIT_TOOLS = {"wait_for_my_turn", "finish_turn"}
# Reads: allowed while a popup, a leader remark or another client's turn claim is pending -- looking never
# changes the game -- and never claim the turn for this process. The list is the call ledger's (one source:
# a read that fell off a hand-kept copy here claimed the turn and was refused under popups -- seven had by
# 2026-09-27) plus the notebook writes that touch nothing in the game.
READ_TOOLS = frozenset(call_ledger.READ_TOOLS) | {"assign", "amend_assignment"}
# Responses: the tools whose input IS the pending thing (a leader remark, an offer on the table, a popup).
RESPONSE_TOOLS = {"dismiss_discussion", "accept_friendship", "diplo_event",
                  "accept_deal", "refuse_deal", "respond_discussion", "answer_popup"}
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
        except Exception as e:  # noqa: BLE001 -- progress is best effort; never let it break the wait
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


def _refusal_for(g, ts: dict, tool: str) -> dict | None:
    """Why `tool` may not run on this turn_state -- the refusal to return -- or None when it may. The order is
    the gate's (harness/gate.py): the first precondition that stops the seat wins, because clearing it is what
    makes the next one visible. Reads and responses skip every check: looking never changes the game, and a
    response's input IS the pending thing."""
    if tool in READ_TOOLS or tool in RESPONSE_TOOLS:
        return None
    # Every refusal below carries `gate`, the same object turn_status shows: the one thing that must happen
    # first and the tool that does it.
    gate = _gate(ts, g.seat)
    if ts["paused"] or ts["processing"] or not ts["my_turn"]:
        if gate and gate["name"] == "hand_off_screen":
            return {"ok": False, "err": "the hotseat hand-off screen is still up for this seat after Continue "
                                        "was pressed for you; wait_for_my_turn presses it again", "gate": gate}
        return {"ok": False, "err": "game is paused, processing, or waiting; use wait_for_my_turn", "gate": gate}
    if g.discussion_pending():
        return {"ok": False, "err": "diplomatic decision pending",
                "gate": gate if gate and gate["name"] == "discussion" else _gate({**ts, "discussion_pending": True}, g.seat)}
    if ts.get("leader_greeting_pending"):
        # A leader screen (a greeting, or the echo of a war just declared) freezes the engine's update loop:
        # orders pushed underneath it half-apply -- the unit moves, but its mission timer never runs, so it
        # stays "busy" and every later order is refused as not legal (live 2026-09-24 t218, two-human hotseat:
        # two Artillery set up under Bravo's war-declared screen could not fire until it was closed). A human
        # cannot click the map with that screen up either.
        return {"ok": False, "err": "a leader screen is up and the game is frozen behind it; "
                                    "discussion() reads it, dismiss_discussion() closes it", "gate": gate}
    # found_pantheon is not here: the engine reports one blocker at a time, so a pending pantheon can sit
    # behind e.g. PRODUCTION (live t22); H.found_pantheon checks CanCreatePantheon itself.
    required = {"found_religion": "ENDTURN_BLOCKING_FOUND_RELIGION",
                "enhance_religion": "ENDTURN_BLOCKING_ENHANCE_RELIGION"}
    if tool in required and ts["blocking_name"] != required[tool]:
        return {"ok": False, "err": "this religious choice is not pending"}
    if ts.get("pending_popups"):
        # tool -> the decision popups it may run under (harness/gate.py, one table for this allow-list, for
        # the gate that names the popup's resolver and for the hint).
        allowed = resolutions_by_tool().get(tool, set())
        pending = ts["pending_popups"]
        if any(p["name"] not in allowed for p in pending):
            g.dismiss_pending_popups()
            pending = g.turn_state().get("pending_popups", [])
        unresolved = [p for p in pending if p["name"] not in allowed]
        if unresolved:
            return {"ok": False, "err": "popup needs a decision", "pending_popups": unresolved,
                    "gate": popup_gate(unresolved[0]), "hint": popup_hint(unresolved[0]["name"])}
    return None


def guarded(fn):
    """Every tool but `do` runs through here: one action at a time per socket (action_lock), the seat check,
    the hotseat hand-off, then _refusal_for (what the turn state forbids) and the turn claim (one client
    owns a seat's turn between calls). Any failure comes back as a readable JSON error, never the MCP
    layer's bare "Error executing tool"."""
    @functools.wraps(fn)
    def wrapper(*a, **k):
        try:
            seat = getattr(_game, "seat", None)
            if seat is None and os.environ.get("CIV5_SEAT", "auto") != "auto":
                seat = int(os.environ["CIV5_SEAT"])
            if fn.__name__ in WAIT_TOOLS:
                with action_lock(_sock(), seat=seat, tool=fn.__name__):
                    game()   # connect (and inject the runtime on a first call) as one operation
                return fn(*a, **k)   # then each poll is its own operation; nothing is held while sleeping
            with action_lock(_sock(), seat=seat, tool=fn.__name__):
                g = game()
                # Front-end tools: usable from the main menu, where there is no InGame state at all.
                if fn.__name__ in MENU_TOOLS:
                    if g.has_state("InGame") and fn.__name__ != "turn_status":
                        return J({"ok": False, "err": "a game is already loaded; these tools only work from the main menu",
                                  "turn": g.turn_state().get("turn")})
                    return fn(*a, **k)
                if fn.__name__ not in ANYTIME_TOOLS:
                    ts = g.turn_state()
                    if ts["active_player"] != g.seat:
                        ts = _recheck_seat(g, ts)
                    if ts["active_player"] != g.seat:
                        return J(_seat_refusal(g, ts))
                    if ts.get("hotseat") and ts.get("hand_off_pending"):
                        # Our own Continue screen: press it here, as the seat's human would before anything
                        # else, so the first call after a (re)start meets a game state and not a UI gate.
                        ts = g.clear_hand_off(ts)
                    refused = _refusal_for(g, ts, fn.__name__)
                    if refused is not None:
                        return J(refused)
                    if fn.__name__ not in READ_TOOLS and fn.__name__ != "end_turn":
                        # A mutating command: own the turn for this process, or learn who does. end_turn claims
                        # inside Game (so its `force` applies there); `do` (not guarded) takes over with force=true.
                        refused = _claim_for(g, ts, fn.__name__)
                        if refused is not None:
                            return J(refused)
                return fn(*a, **k)
        except (TunerdError, TimeoutError, OSError, ValueError) as e:
            return J({"ok": False, "err": str(e)})
        except Exception as e:  # noqa: BLE001 -- a harness bug must still come back as a readable JSON error,
            # not the MCP layer's bare "Error executing tool" (which hides the cause and, for the trade flow,
            # can leave a leader screen open that every later action then refuses on).
            return J({"ok": False, "err": f"harness error: {type(e).__name__}: {e}", "tool": fn.__name__})
    return wrapper


def lua_allowed() -> bool:
    """The raw `lua` tool is opt-in (env CIV5_ALLOW_LUA / --allow-lua)."""
    return os.environ.get("CIV5_ALLOW_LUA", "").strip().lower() in {"1", "true", "yes", "on"}


# ------------------------------------------------------------------ observation
@mcp.tool()
@guarded
def turn_status() -> str:
    """Whose turn it is, current turn number, whether it is my turn, what blocks ending it, and whether a
    greeting / discussion / tech / great-person screen is up (those are not in pending_popups).
    `gate` is the one thing to read first: null means act freely; otherwise it names what must happen before
    any action works and `clear_with` the tool that does it (every refusal carries the same object). `seat` is
    the player this server plays. `todo` lists the decisions the turn still needs: units (need orders), cities
    (empty production), promotions, steal_tech (a pending spy chooser, even when blocking_name says something
    else: the engine reports one blocker at a time), and `todo.ongoing` -- units the game is already moving
    (automated or on a multi-turn move; `attention` names a camp, hostile or lost destination beside one),
    which never block the turn. `blocking_name` / `blocking_hint` say what stops end_turn and which tool clears
    it. `alerts` are facts about my own empire that block nothing: low happiness or an unhappy tier, a strategic
    resource in deficit; `happiness` rides on every status. `expiring_deals` (within 3 turns) and
    `expiring_friendships` (within 5) list what is about to lapse. While a leader screen is up
    (leader_greeting_pending / discussion_pending) the engine freezes blocking_name and todo: discussion()
    reads it, dismiss_discussion() closes a plain greeting. From the main menu it reports {"ingame": false,
    "screen": ...}: load_latest / load_save get back into a game. Every key in detail: how_to_play("turn_status")."""
    g = game()
    if not g.has_state("InGame"):
        out = {"ok": True, "ingame": False, "screen": g.front_end_screen(), "seat": g.seat}
        out["gate"] = _gate(out, g.seat)
        return J(out)
    ts = g.turn_state()
    if ts.get("hotseat") and ts.get("hand_off_pending"):
        ts = g.clear_hand_off(ts)   # our own Continue screen is pressed, never reported as a chore
    ts["seat"] = g.seat
    if "expiring_city_states" not in ts:
        expiring = g.expiring_city_states()
        if expiring:
            ts["expiring_city_states"] = expiring  # ally/friend status lapsing within 3 turns
    ts["gate"] = _gate(ts, g.seat)
    if getattr(g, "claim", None) is not None and ts.get("active_player") == g.seat:
        c = claim_status(_sock(), g.seat, ts.get("turn"))
        if c:   # another client of this seat (or this process) has already acted this turn (#41)
            ts["turn_claim"] = c
    if ts.get("hotseat") and ts.get("active_player") != g.seat:
        ts["seat_note"] = (f"this server plays seat {g.seat}; seat {ts.get('active_player')} is on screen, so it is "
                           "not your turn: wait_for_my_turn blocks until it is")
        if _may_change_seat():
            ts["seat_note"] += (f". Only if nobody else plays seat {ts.get('active_player')} (this server's seat "
                                f"was guessed), set_seat({ts.get('active_player')}) moves it there")
    return J(ts)


def _briefing_for(g, ts: dict, since: str = "previous", limit: int = 8, notes: str = "auto",
                  detail: str = "compact") -> dict:
    """The briefing of the turn `ts` describes, or only its gate when one is up: the board is not read while
    something else must happen first (and never while another seat is on screen)."""
    gate = _gate(ts, g.seat)
    if gate is not None:
        return {"ok": True, "seat": g.seat, "turn": ts.get("turn"), "gate": gate,
                "withheld": "the board is not read while a gate is up: clear it with gate.clear_with, then briefing()"}
    if "expiring_city_states" not in ts:
        expiring = g.expiring_city_states()
        if expiring:
            ts = {**ts, "expiring_city_states": expiring}
    out = g.briefing(since=since, limit=limit, ts=ts, notes=notes, detail=detail)
    out["seat"] = g.seat
    out["gate"] = None
    return out


@mcp.tool()
@guarded
def briefing(since: str = "previous", limit: int = 8, notes: str = "auto", detail: str = "compact") -> str:
    """My turn in one compact read, for deciding and for recovering after a context reset: what I must do, what
    changed, and what the board looks like. `decisions` is every mandatory item, never cut -- units needing
    orders, promotions, cities with nothing to build, research unset, an incoming deal, a stolen tech, decision
    popups, or the blocker -- each with the tool that clears it. `warnings` are facts that do not block (alerts,
    expiring deals / friendships / allies); `opportunities` idle caravans and spies, free route slots.
    `changes` since the `baseline` (my previous briefing of this game and seat, kept beside my notebook):
    empire totals {was, now}, cities and units new / gone, `events` from the game's log (its own cursor:
    turn_digest keeps its own). `empire`; `cities` (only those worth a look, with `why`); `units` (totals,
    ongoing, attention, damaged); `threats` (visible hostiles within 4 plots of a city or 2 of a unit, nearest
    first; distance only, no odds; ones already briefed are marked `seen`); `camps`; `civ_rules` (my leader's
    trait text, on a first briefing or since="turn"); `notes` (new since my last briefing or finish_turn;
    notes="all" the latest `limit`); `assignments` and `orders` when I have any. While a gate is up only `gate`
    comes back (`withheld`).
    Every list but `decisions` stops at `limit` (default 8, max 50) with `omitted` and `more` naming the tool
    that shows the rest. since="turn" lists every event after my previous turn ended: use it after a context
    reset. detail="full" gives every field of every row. Five game reads; nothing another seat can see is
    read. Every key in detail: how_to_play("briefing")."""
    g = game()
    ts = g.turn_state()
    ts["seat"] = g.seat
    return J(_briefing_for(g, ts, since=since, limit=limit, notes=notes, detail=detail))


@mcp.tool()
@guarded
def set_seat(player_id: int | None = None) -> str:
    """Change which player this server plays, or re-detect it (player_id omitted). Needed when every tool
    answers "this seat is not active" although the game is waiting for a human: the server was started
    with --seat auto before the game was up, or a hotseat save was loaded and auto's default (seat 1) is not
    the seat on screen. Only a seat the engine considers human can be chosen; the answer lists `human_seats`.
    With no player_id: solo and network games re-run detection; hotseat takes the seat on screen when it is
    human. The notebook follows the seat (one notebook per game and seat). Usable while it is not my turn."""
    global _seat_rechecked, _seat_unresolved
    g = game()
    if not g.has_state("InGame"):
        return J({"ok": False, "err": "no game is loaded; load_latest / load_save first", "seat": g.seat})
    g._mode = None  # a save may have been loaded since the mode was cached
    mode = g.mode()
    humans = g.human_seats()
    ts = g.turn_state(0)
    before = g.seat
    if player_id is None:
        if mode == "hotseat":
            if ts.get("active_player") not in humans:
                return J({"ok": False, "err": "the seat on screen is not human; give player_id", "seat": g.seat,
                          "active_player": ts.get("active_player"), "human_seats": humans})
            g.seat = int(ts["active_player"])
        else:
            g.detect_seat()
    else:
        player_id = int(player_id)
        if player_id not in humans:
            return J({"ok": False, "err": f"player {player_id} is not a human seat in this game", "seat": g.seat,
                      "human_seats": humans, "mode": mode})
        pinned = os.environ.get("CIV5_SEAT", "auto")
        if pinned != "auto" and player_id != int(pinned):
            # Two agents in one hotseat game each get a server started with their own --seat. The other
            # human seat is the other player's: taking it on its turn would read their map and units.
            return J({"ok": False, "err": f"this server was started with --seat {pinned} and plays only that seat; "
                                          f"seat {player_id} is another player's", "seat": g.seat,
                      "human_seats": humans, "mode": mode})
        g.seat = player_id
    _seat_rechecked, _seat_unresolved = False, False
    ts = g.turn_state()
    return J({"ok": True, "seat": g.seat, "seat_before": before, "mode": mode, "human_seats": humans,
              "active_player": ts.get("active_player"), "my_turn": ts.get("my_turn"), "turn": ts.get("turn"),
              "hint": None if ts.get("active_player") == g.seat else
              "not this seat's turn yet: wait_for_my_turn / finish_turn wait for it"})


@mcp.tool()
@guarded
def wait_for_my_turn(timeout_seconds: int = 90, ctx: Context = None) -> str:
    """Block until it is my turn (hotseat: dismisses the hand-off screen; LAN/solo: waits for the AIs to finish),
    then return turn_status. On timeout it returns the current status with my_turn=false -- call it again.
    A progress notification goes out every few seconds while waiting, so with a client that honours progress
    timeout_seconds can be as long as an AI round needs (600-1800); otherwise keep it under the client's
    tool-call limit. Also sweeps informational popups. finish_turn does end_turn + this + turn_digest in one call.

    Returns early with discussion_pending=true when an AI leader wants an answer mid-turn: discussion()
    shows what they said and the buttons, respond_discussion(button_id) answers; for a trade offer on the
    table incoming_deal() reads the terms and accept_deal()/refuse_deal() resolve it; dismiss_discussion()
    leaves without agreeing. Then call this again.
    Returns early with tech_popup_pending=true when a technology must be chosen (research still unset).
    Every answer carries `gate` (as turn_status): null when you may act, else what still stands in the way
    and the tool that clears it. A timeout answer carries `seat` (the player this server waits for) and
    `active_player`; in hotseat a different active_player is the other player's turn -- call again."""
    g = game()
    try:
        r = g.wait_for_my_turn(timeout=timeout_seconds, on_wait=progress_reporter(ctx, g.seat))
    except TimeoutError as e:
        return J(_wait_timeout(g, str(e)))
    r["seat"] = g.seat
    r["gate"] = _gate(r, g.seat)
    return J(r)


def _wait_timeout(g: Game, err: str) -> dict:
    """A wait that ran out: say which seat was waited for and who holds the turn, so a wrong seat is visible
    (live 2026-09-25: 420 s of waiting for seat 1 in a hotseat game where seat 0 sat on the hand-off screen)."""
    out = {"ok": False, "err": err, "seat": g.seat, "timed_out": True}
    try:
        with _op(g):
            ts = g.turn_state(g.seat)
        out["active_player"], out["turn"] = ts.get("active_player"), ts.get("turn")
        out["gate"] = _gate(ts, g.seat)
        if ts.get("hotseat") and ts.get("active_player") != g.seat:
            out["hint"] = (f"hotseat: seat {ts.get('active_player')} is on screen and this server plays seat "
                           f"{g.seat}: still the other player's turn; call again")
            if _may_change_seat():
                out["hint"] += f". Only if nobody else plays seat {ts.get('active_player')}, set_seat({ts.get('active_player')})"
        else:
            out["hint"] = "still not my turn; call again"
    except (TunerdError, TimeoutError, OSError, ValueError, KeyError):
        pass
    return out


@mcp.tool()
@guarded
def dismiss_discussion() -> str:
    """Leave an AI leader's negotiation/demand/trade-offer screen (see wait_for_my_turn's discussion_pending)
    without agreeing to anything. For a trade already on the table, prefer incoming_deal + refuse_deal.
    Also closes a plain leader greeting (first meeting, echo of a war/peace just made)."""
    return J(game().dismiss_discussion())


@mcp.tool()
@guarded
def discussion() -> str:
    """What the open leader screen says: the leader, their mood, their speech, the response buttons
    (id + text) and, on a trade screen, the deal on the table; screen="greeting" is a plain
    first-meeting / war / peace message with nothing to decide. Call this whenever turn_status or
    wait_for_my_turn reports discussion_pending, then answer with respond_discussion(button_id),
    accept_deal / refuse_deal (trade screen), or dismiss_discussion (plain acknowledgement, no buttons)."""
    return J(game().discussion())


@mcp.tool()
@guarded
def respond_discussion(button_id: int, expect: str = "") -> str:
    """Press one of the response buttons listed by discussion() (1-4). Use this for AI demands,
    warnings, requests and post-deal remarks that offer choices such as apologise / dismiss / threaten.
    expect: optional words the button's text must contain (e.g. "no interest"); if it does not, nothing is
    pressed and the real buttons come back -- guards against pressing a remembered id on a different screen."""
    return J(game().respond_discussion(button_id, expect))


@mcp.tool()
@guarded
def incoming_deal() -> str:
    """Read the current trade table (scratch deal): items already offered, who they are from. A
    VOTE_COMMITMENT row names the resolution, the pledged choice and the number of votes (`votes`); a
    THIRD_PARTY_WAR / THIRD_PARTY_PEACE row names the third party (`other` player id, `other_name`, `minor`).
    Empty items means no deal is on the table. Does not mutate the deal or open the trade screen."""
    return J(game().incoming_deal())


@mcp.tool()
@guarded
def current_deals() -> str:
    """Diplomacy Overview current deals: who, items, turns remaining until each expires.
    Refuses if a trade is already on the scratch table (answer incoming_deal first). Does not
    construct or propose anything."""
    return J(game().current_deals())


@mcp.tool()
@guarded
def accept_deal() -> str:
    """Accept an incoming trade already on the table (see incoming_deal). Does not construct a new deal.
    To make an offer of my own use propose_deal."""
    return J(game().accept_deal())


@mcp.tool()
@guarded
def refuse_deal() -> str:
    """Refuse an incoming trade already on the table (see incoming_deal). Does not construct a new deal."""
    return J(game().refuse_deal())


@mcp.tool()
@guarded
def trade_catalog(player_id: int) -> str:
    """What can currently go on a trade table with this major civ (gold, GPT, embassy, open borders, pacts,
    resources, cities as name + `pop`, with x/y only once the plot is revealed, `third_party.war/peace.us/them`
    (the Other Players pocket: every third civ both sides know, `ok` or greyed with the screen's reason), World Congress `vote_commitments`:
    one row per pending proposal + choice either side may pledge, with `votes_us`/`votes_them`), `peace` (at war: the Negotiate
    Peace gate -- `ok`, `locked_turns`, the screen's `note`; the treaty itself is seeded on both sides of any table by the screens). Each resource carries `class`, `us_available`/`them_available` (spare copies each side holds)
    and `last_copy: true` when exporting it would give away our only copy of a luxury (costs happiness).
    Read-only: does not construct or send a deal. City-states: use city_state_gifts."""
    return J(game().trade_catalog(player_id))


@mcp.tool()
@guarded
def city_state_gifts(player_id: int) -> str:
    """Gold gift tiers and friendship for a met city-state. See minor_gold_gift to actually gift.
    `ally` is what the city-state screen's ally tooltip shows: {us: true}, {none: true, to_become_ally},
    or the current ally (named only if met) with `to_become_ally` = influence we still need to pass it.
    Other majors' influence is not visible to a player and is not returned.
    Each tier carries `influence_after` and `makes_ally` -- whether that gift actually takes the alliance,
    or `short_by` how much it would miss the civ currently holding it."""
    return J(game().city_state_gifts(player_id))


@mcp.tool()
@guarded
def city_capture_options() -> str:
    """When pending_popups shows BUTTONPOPUP_CITY_CAPTURED: the plunder, and each choice the popup offers (liberate /
    annex / puppet / raze) with its unhappiness change and the warmonger warning from the button tooltip."""
    return J(game().city_capture_options())


@mcp.tool()
@guarded
def choose_city_capture(choice: str) -> str:
    """Decide a captured city: choice = liberate | annex | puppet | raze (only those city_capture_options lists)."""
    return J(game().choose_city_capture(choice))


@mcp.tool()
@guarded
def war_consequences(player_id: int) -> str:
    """Read before declare_war (or city_state_action declare_war): what the game's confirmation screen warns about --
    a Declaration of Friendship being broken, denouncements, city-states allied to the target that join the war,
    majors protecting a targeted city-state, and trade routes that would be cancelled."""
    return J(game().war_consequences(player_id))


@mcp.tool()
@guarded
def city_state_actions(player_id: int) -> str:
    """The city-state screen beyond gifts: influence, `quest_list` (structured: type, turns_left, kill-camp
    x/y when that camp is revealed, contest scores), plus the same quest tooltip text as `quests`. Whether I
    can pledge / revoke protection, demand tribute (gold amount, or a Worker; `details` explains the strength
    check), declare war, or make peace."""
    return J(game().city_state_actions(player_id))


@mcp.tool()
@guarded
def city_state_action(player_id: int, action: str) -> str:
    """Press one city-state screen button. action: pledge | revoke_pledge | bully_gold | bully_unit |
    declare_war | make_peace. Refused with the current state when the screen would not offer it."""
    return J(game().city_state_action(player_id, action))


@mcp.tool()
@guarded
def unit_home_options(unit_id: int) -> str:
    """Where a trade unit or a Great Admiral could re-home (the Change Home City / Change Port
    chooser). Both need the unit to be standing in one of my cities; outside one there is no button,
    and the answer says so. `cities` is the engine's own candidate list -- apply one with
    unit_mission(unit_id, mission, x, y) using the `mission` in the reply. Re-homing a caravan nearer a
    richer partner is how a 6-gold route becomes a 12-gold one; see available_trade_routes after."""
    return J(game().unit_home_options(unit_id))


@mcp.tool()
@guarded
def gift_tile_improvement_options(player_id: int) -> str:
    """The city-state screen's "Gift Improvement" button, and the hexes it would highlight. `can` /
    `cost` / `why_not` are the button (allies only, and the gold has to be there); `plots` is every
    tile within `search_radius` of that city-state's capital where the gift is legal -- the same
    magenta hexes the stock interface mode lights up. A tile I have not revealed is listed as bare
    coordinates. Empty `plots` with `can` true means the ally has nothing left worth improving."""
    return J(game().gift_tile_improvement_options(player_id))


@mcp.tool()
@guarded
def gift_tile_improvement(player_id: int, x: int, y: int) -> str:
    """Buy a city-state an improvement on one of its tiles (clicking a highlighted hex). `x`/`y` must
    be a plot from `gift_tile_improvement_options`. Reports the gold spent, the improvement that
    appeared, and influence before/after."""
    return J(game().gift_tile_improvement(player_id, x, y))


@mcp.tool()
@guarded
def minor_gold_gift(player_id: int, amount: int) -> str:
    """Gift gold to a city-state. `amount` must be city_state_gifts' small, medium, or large tier.
    Check that tier's `makes_ally` first: influence bought is not the alliance bought when another major
    is sitting above me. The reply says `still_short` when the gift lands under the current ally."""
    return J(game().minor_gold_gift(player_id, amount))


@mcp.tool()
@guarded
def players() -> str:
    """HUMAN seats only (network/hotseat games): whether each is connected, has an active turn, and has ended
    their turn. Like the in-game player list, a seat I have not met shows its name but not its civ. In a solo game this is just me. For the AI civs and city-states I have met -- their ids,
    scores, war state -- use `diplomacy`; that is where `player_id`s for trade/diplomacy tools come from."""
    return J(game().net_players())


@mcp.tool()
@guarded
def overview() -> str:
    """My empire at a glance: gold, science, culture, happiness, research, era, counts, turn/year.
    `strategic_resources` (revealed only) with `available` spare copies -- negative is a deficit: units and
    buildings fight and produce at a penalty. `luxuries` with owned / imported / exported copies (`last_copy`
    when selling one would drop the happiness bonus); `bonus_resources` the resource list's bonus stack.
    The top-bar tooltips ride along: `happiness_breakdown` (with the Happiness screen's rows: by_luxury,
    cities, unhappiness tooltips, the `unhappy` tier, `penalties`), `gold_breakdown` (income vs expenses, unit
    maintenance), `science_breakdown`, `culture_breakdown`, `tourism_breakdown`, `faith_breakdown`;
    `unit_supply` (Military Overview cap and deficit), `score_breakdown`, `golden_age_progress` /
    `golden_age_threshold`. `idle_trade_units` lists caravans and cargo ships without a route (with `in_city`
    and the nearest city to walk to: only one standing in my city can be given a route) and `idle_spies`
    unassigned spies. Every key in detail: how_to_play("overview")."""
    return J(game().summary())


@mcp.tool()
@guarded
def notification_log(limit: int = 40, include_dismissed: bool = True) -> str:
    """The Notification Log: every notification the game still holds for me, newest first, including
    ones already dismissed -- which is what the screen is for. `turn_digest` carries only what the
    panel is currently showing, so something read once and dismissed is otherwise gone. Each row has
    the `turn` it arrived on. `limit` is the newest N (default 40); include_dismissed=false keeps only the
    ones still showing."""
    return J(game().notification_log(limit, include_dismissed))


@mcp.tool()
@guarded
def turn_digest() -> str:
    """Everything recorded since my last call: combats, cities founded/lost, wars, chat, notifications, alerts.
    Notes: a caravan / cargo ship shows up as `unit_destroyed` the turn its trade route starts -- the route
    IS the unit now (it comes back as a new unit when the route ends); `unit_graphics_reset` means the engine
    only rebuilt a model (era change, upgrade), the unit is fine. `unit_captured` is a civilian taken, not killed:
    the row carries the unit, its tile, the captor when in sight and (barbarians) the nearest revealed camp. Leader lines you provoked yourself via
    negotiate_deal/propose_deal are not included; unsolicited AI approaches are."""
    return J(game().turn_digest())


@mcp.tool()
@guarded
def units() -> str:
    """My units with position, moves left, hp, strength, current promotions, XP toward the next
    promotion (`xp` / `xp_needed`), and whether they still need orders. `garrisoned` is the Military
    Overview status. `upgrade_to` / `upgrade_gold` / `can_upgrade` are the unit-panel upgrade preview
    when a path exists. A religious unit carries `religion` (the faith it spreads, which is the one of
    the city it was bought in -- not necessarily yours) and `spreads_left`, as the unit panel names it. A Worker mid-job carries `build` (BUILD_*) and `build_turns_left` as the unit
    panel's "Trading Post (6)" line; `mission_name` names a standing MISSION_* (e.g. ROUTE_TO)."""
    return J(game().units())


@mcp.tool()
@guarded
def cities() -> str:
    """My cities: population, yields, current production and turns left, growth, happiness.
    `growth` is "growing" (then `growth_turns` is present), "stagnant" (food_surplus 0 -- typical while
    empire happiness is negative, which throttles growth) or "starving" (negative surplus, will lose pop).
    `building_maintenance` / `connection_gold` are the Economic Overview per-city expense/income rows
    (omit when 0). `blockaded` / `wltkd_turns` are the city-banner blockade and We Love the King timer.
    Open one city with city_screen(city_id) for buildings, specialists, worked tiles,
    queue, and focus."""
    return J(game().cities())


@mcp.tool()
@guarded
def city_screen(city_id: int) -> str:
    """The city screen for one of my cities: buildings, specialists and their Great Person meters,
    which tiles are being worked, the full production queue, citizen focus, avoid-growth, and plots
    that can be bought (`buyable` + `buy_gold`). A tile the screen still prices in red (not enough
    gold) has `buy_gold` and `can_afford: false` instead of `buyable`. `meters` is the corner of
    the city screen: food stored/needed and the growth label (a settler counts as stagnant),
    production stored/needed/per-turn, culture stored/needed and turns until the next border tile,
    and the fractional gold/science plus faith and tourism per turn; `meters.breakdown` is the hover
    behind each of those (sources, food eaten, modifier lines, total). Specialist rows and slots
    carry `yields`; built buildings carry their enum and name (what each does: reference("buildings")). An owned tile another of our
    cities is working names that city (`worked_by`); a blockaded water tile or a visible enemy
    unit is marked. Buildings a human can click-to-sell carry `can_sell` / `sell_gold` /
    `gold_maintenance`. Writes from the same screen: set_city_focus, set_avoid_growth,
    change_working_plot, buy_city_plot, city_task (annex / raze / unraze), sell_building."""
    return J(game().city_screen(city_id))


@mcp.tool()
@guarded
def great_person_progress() -> str:
    """Great Person overview: each city's specialist progress, class-specific threshold and rate;
    national General/Admiral XP meters and next Prophet faith threshold."""
    return J(game().great_person_progress())


@mcp.tool()
@guarded
def demographics() -> str:
    """Demographics: our value/rank and public best, average and worst for population, food,
    production, gold, land, soldiers, approval and literacy. Unmet best/worst identities are masked."""
    return J(game().demographics())


@mcp.tool()
@guarded
def culture_works() -> str:
    """Culture Overview works tab: own buildings' occupied/empty Great Work slots, work tooltips,
    theming rules/bonuses, city tourism breakdowns and tourism modifiers toward met rivals. `swap` is
    the swap tab: `ours` per class (the work we put up and the pull-down's candidates) and `theirs`
    (every met civ's offered writing/art/artifact). Writes: set_swappable_great_work, swap_great_works."""
    return J(game().culture_works())


@mcp.tool()
@guarded
def set_swappable_great_work(work_class: str, work_id: int = -1) -> str:
    """Swap tab pull-down: put one of our works of `work_class` (writing / art / artifact) up for
    swapping, or pass -1 to clear that spot. Candidates are culture_works().swap.ours[class].candidates."""
    return J(game().set_swappable_great_work(work_class, work_id))


@mcp.tool()
@guarded
def swap_great_works(their_work_id: int) -> str:
    """Swap tab's Swap button: exchange the work we have put up for one another civ offers
    (`their_work_id` from culture_works().swap.theirs, same class). Refused unless we have a work of
    that class put up."""
    return J(game().swap_great_works(their_work_id))


@mcp.tool()
@guarded
def domination_progress() -> str:
    """Original capitals of met civilizations and their current holders; unrevealed coordinates
    and unmet holders are masked. Includes whether our team controls each capital."""
    return J(game().domination_progress())


@mcp.tool()
@guarded
def wonder_overview() -> str:
    """World wonders held by met civilizations (Global Relations). Locations and captured/builder
    details only for cities in sight."""
    return J(game().wonder_overview())


@mcp.tool()
@guarded
def espionage_intrigue() -> str:
    """The Espionage Overview intrigue log: turn, spy, discoverer and the player-visible message."""
    return J(game().espionage_intrigue())


@mcp.tool()
@guarded
def city_state_bonuses(minor_id: int) -> str:
    """Met city-state's trait/bonus and personality tooltips, current food/culture/faith/happiness/
    science benefits, unit gift estimate, unique military unit and exported resources."""
    return J(game().city_state_bonuses(minor_id))


@mcp.tool()
@guarded
def gift_unit_options(minor_id: int) -> str:
    """Units that can currently be gifted to this met city-state (the Gift Unit button).
    Typically the unit must be adjacent to their territory. gift_unit sends one."""
    return J(game().gift_unit_options(minor_id))


@mcp.tool()
@guarded
def gift_unit(minor_id: int, unit_id: int) -> str:
    """Gift one of my units to a met city-state (Network.SendGiftUnit). Verifies the unit left
    our army. Use gift_unit_options to see who is in range."""
    return J(game().gift_unit(minor_id, unit_id))


@mcp.tool()
@guarded
def maya_options() -> str:
    """Pending Maya Long Count rewards, including unavailable types and the baktun when chosen."""
    return J(game().maya_options())


@mcp.tool()
@guarded
def choose_maya_bonus(unit: str) -> str:
    """Choose an available UNIT_* from maya_options (unit="UNIT_PROPHET", ...) and verify the reward was
    consumed."""
    return J(game().choose_maya_bonus(unit))


@mcp.tool()
@guarded
def archaeology_options() -> str:
    """Completed dig: artifact origins/era, available art/writing slots, artifact vs landmark
    or writing vs culture choices. Unmet artifact origins are masked."""
    return J(game().archaeology_options())


@mcp.tool()
@guarded
def choose_archaeology(choice: int, x: int, y: int) -> str:
    """Confirm a choice ID at the completed dig's x,y from archaeology_options. Verifies resolution."""
    return J(game().choose_archaeology(choice, x, y))


@mcp.tool()
@guarded
def unit_mission_targets(unit_id: int, mission: str, offset: int = 0, limit: int = 100) -> str:
    """Legal visible targets for an air strike/sweep, nuke, paradrop, rebase or airlift mission
    listed in available_unit_actions. Paginated: `offset` / `limit` (at most 100 per page; `total` says how
    many exist); use unit_mission to issue the order.
    Air strikes include target details and a combat preview with retaliation, strength and visible
    interceptors. Expected damage taken excludes interception; unseen interceptors may still exist.
    Fogged destinations are excluded because legality could expose hidden occupants."""
    return J(game().unit_mission_targets(unit_id, mission, offset, limit))


@mcp.tool()
@guarded
def change_specialist(city_id: int, building: str, add: bool) -> str:
    """Add (add=true) or remove (false) one specialist in a BUILDING_* from city_screen.
    Disables automatic specialist assignment, like clicking a slot. Verifies the resulting count."""
    return J(game().change_specialist(city_id, building, add))


@mcp.tool()
@guarded
def set_auto_specialists(city_id: int, automatic: bool) -> str:
    """Enable or disable automatic specialist assignment in an owned, non-puppet city."""
    return J(game().set_auto_specialists(city_id, automatic))


@mcp.tool()
@guarded
def set_city_focus(city_id: int, focus: str) -> str:
    """Set citizen focus on one of my (non-puppet) cities. focus is one of: balanced, food, production,
    gold, science, culture, great_people, faith. Same as the city-screen focus buttons."""
    return J(game().set_city_focus(city_id, focus))


@mcp.tool()
@guarded
def set_avoid_growth(city_id: int, avoid: bool) -> str:
    """Toggle avoid-growth on one of my (non-puppet) cities (the city-screen checkbox)."""
    return J(game().set_avoid_growth(city_id, avoid))


@mcp.tool()
@guarded
def change_working_plot(city_id: int, x: int, y: int) -> str:
    """Toggle whether this city works plot (x, y). Same as clicking the tile in the city screen.
    Forced-worked tiles stay locked until clicked again. Puppets refuse."""
    return J(game().change_working_plot(city_id, x, y))


@mcp.tool()
@guarded
def buy_city_plot(city_id: int, x: int, y: int) -> str:
    """Buy plot (x, y) for this city for gold. city_screen lists buyable plots with buy_gold."""
    return J(game().buy_city_plot(city_id, x, y))


@mcp.tool()
@guarded
def city_task(city_id: int, action: str) -> str:
    """City-screen tasks: annex (a puppet), raze, or unraze. Annexed cities get resistance;
    raze burns one population per turn. cities()/city_screen already flag puppet/razing state."""
    return J(game().city_task(city_id, action))


@mcp.tool()
@guarded
def sell_building(city_id: int, building: str) -> str:
    """Sell one building in one of my non-puppet cities (the city-screen click-to-sell).
    city_screen lists `can_sell` / `sell_gold` / `gold_maintenance`. Usually one sell per city per turn."""
    return J(game().sell_building(city_id, building))


@mcp.tool()
@guarded
def map_window(x: int, y: int, radius: int = 3) -> str:
    """Revealed plots within `radius` of (x, y). vis=true is in sight now and includes yields
    (food/production/gold/science/culture/faith), fresh_water, worked, under_construction, trade_route
    (the plot hover's "Trade Route": a city connection to the capital, not a caravan line; those are
    trade_routes().path), and live units/cities (units have strength/promotions; a city banner has strength, garrison,
    puppet/razing, religion). A resource tile carries `resource` (and `resource_qty`); what a
    resource gives when improved, its happiness and its blurb are in reference("resources"), once, not
    on every tile. A revealed Oil/Aluminum/Coal tile that we cannot yet hook has
    `resource_requires_tech`. A barbarian camp with a city-state kill-camp quest has `cs_quest`.
    vis=false is discovered but fogged (no live units/owners/features/yields). Prefer known_world
    for the full discovered map."""
    return J(game().plots_around(x, y, radius))


@mcp.tool()
@guarded
def explore_frontier(unit_id: int, limit: int = 12) -> str:
    """Where the known map ends for this unit: revealed, passable plots of its domain (sea for a ship, land otherwise) that border unrevealed plots, nearest first. Each has unrevealed_neighbors (how much stepping there reveals), distance (hex distance, not path length), reachable (true when a route exists through the already-revealed map; false = behind land or an unknown strait, listed last), terrain t (a Trireme cannot enter OCEAN), and map_edge=true on the polar rows (mostly ice beyond). move_unit refuses unrevealed targets, so an explorer picks its next stop from here. frontier_total / unrevealed_plots say how much is left; note explains an empty list. `limit` is how many plots to list (default 12)."""
    return J(game().explore_frontier(unit_id, limit=limit))


@mcp.tool()
@guarded
def tactical_view(unit_id: int, radius: int = 2, detail: str = "summary") -> str:
    """One unit's surroundings in one read, for choosing its move or attack. `neighbors` are the six adjacent plots
    by coordinate and direction (NE, E, SE, SW, W, NW; the engine's own adjacency, so map wrap and the edge rows
    need no hex arithmetic), each with terrain, river_crossing, owner, visible units and `move`: attack (a melee
    attack; its preview is in targets), open (move_unit would send the order), refused (move_unit would refuse it,
    `why` says why) or enemy (a visible enemy this unit cannot melee). `open` is not a path cost: turns-to-reach and
    movement cost are not available. `targets` are the unit's melee and ranged targets with the combat previews
    available_unit_actions gives. `occupants` (visible units, hostile first) and `cities` (a fogged one is
    last_seen) cover `radius` (1-5, default 2); `fog` counts visible, fogged and unrevealed plots there, and
    unseen_within_2 is how many plots within two cannot be seen: fog can hide units, so nothing is called safe.
    `grid` is a lettered picture of the same area with its `legend`; `players` names every owner id in the reply.
    detail="full" adds `plots` (every revealed plot in radius, as map_window reads it) and the previews' modifier rows."""
    return J(game().tactical_view(unit_id, radius=radius, detail=detail))


@mcp.tool()
@guarded
def compare(kind: str, city_id: int | None = None, unit_id: int | None = None, candidates: list[str] | None = None,
            plots: list[list[int]] | None = None, sort: str | None = None, limit: int | None = None,
            detail: str = "summary") -> str:
    """Your candidates side by side in one read, for a decision you are weighing; the facts, never a pick.
    kind="production": city_id + candidates (up to 8 UNIT_/BUILDING_/PROJECT_/PROCESS_ types): can_produce or
    `why` not, cost, stored, turns, gold / faith price with *_can_buy, effects, conditional per-tile yields with
    how many of this city's tiles qualify, estimated_change (formula in assumptions), maintenance, unique_replaces.
    kind="research": up to 8 TECH_ types: status, cost, progress, turns, missing_prereqs, path_beakers and
    path_turns_estimate for a locked one, unlocks.
    kind="improvements": unit_id (a worker) + optional plots ([[x, y], ...]; default: plots within 2 that are
    owned or hold a resource) + optional candidates (BUILD_ types): per plot yields_now, worked, city; per build
    legal (or why), turns (work only), tile_change, empire_change when a city works the tile, removes /
    chop_production, connects, maintenance. Fogged plots are not read. sort= a yield or "turns".
    kind="trade": unit_id (a caravan or cargo ship in a city): every destination with what each end receives,
    distance and hazard (visible hostiles and camps near it; never "safe"). sort= gold, science, food,
    production, *_them or distance.
    Every answer has context, sources, assumptions, n / returned and `omitted` with the arguments that fetch
    the rest (`limit`, 1-20). detail="full" adds help text and the chooser's hover breakdown. Field by field:
    how_to_play("compare")."""
    return J(game().compare(kind, city_id=city_id, unit_id=unit_id, candidates=candidates, plots=plots, sort=sort,
                            limit=limit, detail=detail))


@mcp.tool()
@guarded
def known_world() -> str:
    """Everything this seat knows: empire, own units/cities, met civs and city-states, notifications, and every revealed plot. Fogged plots have vis=false and omit live occupants; unrevealed tiles are absent."""
    return J(game().known_world())


@mcp.tool()
@guarded
def map_index() -> str:
    """Compact map scan: revealed luxuries/strategics, barb camps, ruins, met foreign cities,
    visible natural wonders, and in-sight world wonders. A camp with a city-state kill-camp quest
    carries `cs_quest` (met CS only). Prefer this over known_world unless you need every plot."""
    return J(game().map_index())


@mcp.tool()
@guarded
def revealed_map(layers: list[str] | None = None, x0: int | None = None, y0: int | None = None,
                 x1: int | None = None, y1: int | None = None) -> str:
    """The whole revealed map at a glance, as character grids: one string per row (north first), one
    character per plot, one grid per layer. Layers: vis ('#' in sight now, '~' revealed but fogged:
    what you see there is what was last seen and may be stale until a unit gets eyes back on it, ' '
    unrevealed), terrain, elevation (hills/mountain), river, owner (borders), feature, improvement,
    resource, route. Each reply carries its own legend (letters are assigned per reply). Fog rules are
    the human's: a fogged plot shows remembered feature/improvement/route/owner, never live units or
    pillage. Pass `layers` to fetch a subset and x0/y0/x1/y1 to window a large map (a Huge map after
    Satellites is about 10 KB per layer). map_window(x, y, r) reads one area in full; map_index lists
    cities, camps and resources with coordinates."""
    return J(game().revealed_map(layers=layers, x0=x0, y0=y0, x1=x1, y1=y1))


@mcp.tool()
@guarded
def diplomacy() -> str:
    """Civs and city-states I have met: at war, score (majors), ally/friends (city-states). Unmet players are omitted."""
    return J(game().diplomacy())


@mcp.tool()
@guarded
def relationship(player_id: int) -> str:
    """Our standing with one civ or city-state: their visible approach toward us, friendship /
    denouncements / embassies / open borders / research agreement / defensive pact, the opinion lines
    the game shows, their public relations with every civ we have met (wars, friendships,
    denouncements, city-state alliances) and the recent messages they sent us. `discuss` lists the
    Discuss-screen buttons a human would see (share intrigue, stop spreading religion, stop spying,
    don't settle, stop digging, declare friendship). discussion() includes this for the leader on screen; call it
    directly before proposing or answering anything."""
    return J(game().relationship(player_id))


@mcp.tool()
@guarded
def declare_war(player_id: int) -> str:
    """Declare war on a civ I have met. Irreversible for a while (can't make peace again immediately). Bypasses the leader-head screen entirely."""
    return J(game().declare_war(player_id))


@mcp.tool()
@guarded
def make_peace(player_id: int, items: list[dict] | None = None) -> str:
    """Offer peace to a civ I'm at war with, through the real trade screen: the treaty goes on both sides and
    `items` (same shapes as propose_deal: GOLD, GOLD_PER_TURN, RESOURCES, CITIES, THIRD_PARTY_WAR/PEACE...) are
    the terms, from_us picking who gives what. An AI answers on the spot (`accepted`, `reply`, `at_war` afterwards;
    it can refuse for a while after a declaration even when nothing locks it). A human seat gets it as a pending
    proposal (`pending: true`) to accept_deal / refuse_deal on its turn. Refused with the leader screen's reason
    while locked into war (see trade_catalog(player_id).peace). Any propose_deal while at war is the same peace deal."""
    return J(game().make_peace(player_id, items))


@mcp.tool()
@guarded
def denounce(player_id: int) -> str:
    """Publicly denounce another civ. Worsens relations with them and their friends; cannot be undone."""
    return J(game().denounce(player_id))


@mcp.tool()
@guarded
def spaceship_status() -> str:
    """Science-victory progress: whether the Apollo Program is done, for each spaceship part how many are needed,
    already in the ship, built but not yet delivered to the capital, and which tech unlocks it; plus met rivals
    that finished Apollo and how many parts they have (the Victory Progress screen's space race)."""
    return J(game().spaceship_status())


@mcp.tool()
@guarded
def culture_overview() -> str:
    """Culture-victory race (the Culture Overview screen): for each met major civ, how many civs it is Influential
    on out of how many it needs, its tourism, and its influence on every other major civ -- level (exotic ..
    dominant), percent, tourism per turn, trend, and turns_to_influential while rising. A civ you have not met
    appears as "unknown". Use it when a "Culture Victory Contender" alert names a rival."""
    return J(game().culture_overview())


@mcp.tool()
@guarded
def propose_friendship(player_id: int) -> str:
    """Ask an AI civ for a Declaration of Friendship (the leader screen's "work together"). Refused when already
    friends, asked too recently, at war or unmet. The reply says whether they accepted. Declarations expire after
    their term (a "Declaration of Friendship Has Expired" notification) -- this is how to renew one."""
    return J(game().propose_friendship(player_id))


@mcp.tool()
@guarded
def accept_friendship(player_id: int) -> str:
    """Accept a pending Declaration of Friendship proposal (turn_digest's leader_message with state
    DISCUSS_WORK_WITH_US). Works even if the discussion dialog was already dismissed/declined -- the
    request stays acceptable server-side. Check diplomacy() or `IsDoF` via diplo_event's underlying call
    if you need to confirm it actually took."""
    return J(game().accept_friendship(player_id))


@mcp.tool()
@guarded
def diplo_event(event: str, player_id: int, data1: int = 0, data2: int = 0) -> str:
    """Escape hatch for any other diplomatic action not covered above (accept/decline a coop-war offer,
    respond to a denounce request, agree to work with someone, etc). `event` is a FromUIDiploEventTypes
    name, with or without its FROM_UI_DIPLO_EVENT_ prefix -- see docs/NOTES.md for the list. Read a
    pending leader_message in turn_digest first to know what's being asked and what data1/data2 should be."""
    return J(game().diplo_event(event, player_id, data1, data2))


@mcp.tool()
@guarded
def generic_popup() -> str:
    """Read the open yes/no confirmation (the game's generic popup): its text and numbered buttons.
    These are BUTTONPOPUP_RETURN_CIVILIAN (keep a captured civilian or return it: returning to a city-state
    gives +30 influence, to an AI a diplomatic bonus), ANNEX_CITY / PUPPET_CITY after a conquest,
    BARBARIAN_RANSOM, MINOR_CIV_ENTER_TERRITORY, CONFIRM_COMMAND and the like. Nothing else moves while one
    is open ("popup needs a decision"). Answer with answer_popup(button)."""
    return J(game().generic_popup())


@mcp.tool()
@guarded
def answer_popup(button: int) -> str:
    """Press one button (1-based id from generic_popup) of the open generic confirmation. Runs the button's
    real handler (e.g. Network.SendReturnCivilian) and closes the window. Returns `discussion_pending`
    because some answers make an AI leader speak next (dismiss_discussion)."""
    return J(game().answer_popup(button))


@mcp.tool()
@guarded
def city_ranged_attack(city_id: int, x: int, y: int) -> str:
    """Ranged attack from a city onto plot (x, y). See available_city_strikes first.
    Does not select the city or pan/flip the camera."""
    return J(game().city_ranged_attack(city_id, x, y))


@mcp.tool()
@guarded
def available_city_strikes(city_id: int) -> str:
    """Plots this city can bombard right now. Empty if it has no ranged strike this turn."""
    return J(game().available_city_strikes(city_id))


@mcp.tool()
@guarded
def available_policies() -> str:
    """Social policies: what is adopted, what can be adopted right now (enum + name; the effect text is
    in reference("policies")), which branches are unlocked / unlockable, culture vs next cost. Use before
    choose_policy / unlock_policy_branch."""
    return J(game().available_policies())


@mcp.tool()
@guarded
def choose_policy(policy: str) -> str:
    """Adopt a social policy, e.g. POLICY_TRADITION, within an already-unlocked branch."""
    return J(game().choose_policy(policy))


@mcp.tool()
@guarded
def unlock_policy_branch(branch: str) -> str:
    """Unlock a policy branch/tree, e.g. POLICY_BRANCH_TRADITION, spending a culture policy slot."""
    return J(game().unlock_policy_branch(branch))


@mcp.tool()
@guarded
def choose_ideology(branch: str) -> str:
    """Choose the empire's ideology when ENDTURN_BLOCKING_CHOOSE_IDEOLOGY is up (3 Factories or the Modern
    era): branch is POLICY_BRANCH_FREEDOM, POLICY_BRANCH_ORDER or POLICY_BRANCH_AUTOCRACY. Irreversible
    short of a revolution. Other civs' ideologies are public (their choice matters for ideological
    pressure/unhappiness). Returns `ideology` (confirmed) and `free_tenets` to spend via choose_policy."""
    return J(game().choose_ideology(branch))


@mcp.tool()
@guarded
def free_great_person_options() -> str:
    """When turn_status shows ENDTURN_BLOCKING_FREE_ITEMS: how many free Great People are owed and which unit
    types (UNIT_SCIENTIST, UNIT_ENGINEER, UNIT_MERCHANT, UNIT_ARTIST, UNIT_WRITER, UNIT_MUSICIAN, ...) qualify."""
    return J(game().free_great_person_options())


@mcp.tool()
@guarded
def choose_free_great_person(unit: str) -> str:
    """Claim a free Great Person, e.g. unit="UNIT_SCIENTIST". Only valid while turn_status shows
    ENDTURN_BLOCKING_FREE_ITEMS (e.g. right after completing the Liberty policy tree)."""
    return J(game().choose_free_great_person(unit))


@mcp.tool()
@guarded
def goody_hut_options() -> str:
    """When turn_status.pending_popups shows BUTTONPOPUP_CHOOSE_GOODY_HUT_REWARD (a Shoshone Pathfinder entered
    ancient ruins): the rewards on offer, each with the popup's own description."""
    return J(game().goody_hut_options())


@mcp.tool()
@guarded
def choose_goody_hut(goody: str) -> str:
    """Take one ruins reward from goody_hut_options, e.g. goody="GOODY_CULTURE"."""
    return J(game().choose_goody_hut(goody))


@mcp.tool()
@guarded
def religion_overview() -> str:
    """Religion Overview screen: faith, next Great Prophet threshold, my pantheon/religion and beliefs, all founded
    religions with their beliefs and city counts, per own city the followers and pressure of each religion, and
    `auto_purchase`: the automatic faith purchase pull-down (current selection and every option it lists with
    its faith cost; change it with set_faith_purchase)."""
    return J(game().religion_overview())


@mcp.tool()
@guarded
def set_faith_purchase(kind: str, index: int = 0) -> str:
    """The Religion Overview's automatic faith purchase pull-down. `kind` is nothing, save_prophet,
    unit or building; `index` is the unit/building id from religion_overview().auto_purchase.options
    (each option lists its faith cost). Refused for anything the pull-down does not currently list."""
    return J(game().set_faith_purchase(kind, index))


@mcp.tool()
@guarded
def change_ideology() -> str:
    """The policy screen's Switch Ideology button: adopt the preferred ideology public opinion pushes
    toward, at the cost overview().public_opinion.switch_cost shows (anarchy turns, tenets kept).
    Refused while the button is grey (no public-opinion unhappiness)."""
    return J(game().change_ideology())


@mcp.tool()
@guarded
def faith_great_person_options() -> str:
    """When turn_status shows ENDTURN_BLOCKING_FAITH_GREAT_PERSON: the Great People the faith can buy now."""
    return J(game().faith_great_person_options())


@mcp.tool()
@guarded
def choose_faith_great_person(unit: str) -> str:
    """Take one unit type from faith_great_person_options (it appears in the capital or holy city)."""
    return J(game().choose_faith_great_person(unit))


@mcp.tool()
@guarded
def available_beliefs(kind: str) -> str:
    """Beliefs still available for one slot (enum + name; what each does is in reference("beliefs")). kind: pantheon | founder | follower | enhancer |
    bonus | reformation. Founding a religion takes pantheon(if none yet)/founder/follower(/bonus for Byzantium);
    enhancing takes follower + enhancer. kind=founder also lists the religions nobody has founded."""
    return J(game().available_beliefs(kind))


@mcp.tool()
@guarded
def add_reformation_belief(belief: str) -> str:
    """When turn_status shows ENDTURN_BLOCKING_ADD_REFORMATION_BELIEF (Piety's Reformation policy): pick one
    from available_beliefs(kind="reformation")."""
    return J(game().add_reformation_belief(belief))


@mcp.tool()
@guarded
def found_pantheon(belief: str) -> str:
    """Found a pantheon with the given belief, e.g. BELIEF_GOD_OF_THE_SEA. Check turn_status first: only
    valid when blocking_name is ENDTURN_BLOCKING_FOUND_PANTHEON."""
    return J(game().found_pantheon(belief))


@mcp.tool()
@guarded
def found_religion(religion: str, beliefs: list[str], city_x: int, city_y: int, custom_name: str = "") -> str:
    """Found a religion (RELIGION_..., see available_beliefs(kind="founder").religions) in the city at
    (city_x, city_y) = data1, data2 of the pending BUTTONPOPUP_FOUND_RELIGION. `beliefs` in order: a pantheon
    belief (only if I have no pantheon yet), a founder belief, a follower belief (+ a bonus belief for Byzantium).
    Only valid when blocking_name is ENDTURN_BLOCKING_FOUND_RELIGION. custom_name renames the religion
    (empty keeps the stock name)."""
    return J(game().found_religion(religion, beliefs, city_x, city_y, custom_name))


@mcp.tool()
@guarded
def enhance_religion(religion: str, belief4: str, belief5: str, city_x: int, city_y: int, custom_name: str = "") -> str:
    """Enhance my founded religion: belief4 = a follower belief, belief5 = an enhancer belief (available_beliefs),
    in the city at (city_x, city_y) = data1, data2 of the pending BUTTONPOPUP_FOUND_RELIGION (the holy city, where
    the Great Prophet stands); custom_name is ignored unless the game asks for one. Only valid when
    blocking_name is ENDTURN_BLOCKING_ENHANCE_RELIGION."""
    return J(game().enhance_religion(religion, belief4, belief5, city_x, city_y, custom_name))


@mcp.tool()
@guarded
def available_research() -> str:
    """Techs I can research right now (prereqs met). `current` marks the one already selected;
    `progress` is the science already stored in a tech (shown whenever it is nonzero).
    `unlocks` is the tech-tree button row for this seat: our units and buildings (not another
    civ's uniques), revealed resources, and the ability the button names (embark, ocean, embassy)."""
    return J(game().available_research())


@mcp.tool()
@guarded
def tech_tree() -> str:
    """The tech tree: `have` (already researched), `techs` (current / available / unavailable with
    prereqs and missing steps, turns-if-researchable, and `unlocks` — the buttons on that tech for
    this seat). No rival column: an embassy shows a capital, not a tech list (the steal-tech chooser
    is the only stock screen that names a rival's techs). available_research is the leaf list only."""
    return J(game().tech_tree())


@mcp.tool()
@guarded
def available_production(city_id: int) -> str:
    """What this city can produce right now: units, buildings, projects, processes, with `turns` at the
    current production rate, and for units/buildings the gold rush-buy price (`gold`; absent when the item
    can never be bought, e.g. national wonders) plus `can_buy` (affordable AND purchasable right now ->
    purchase_production). Use set_production(city_id, item) to queue one.
    Each row carries `gold` (rush-buy cost, `can_buy`) and, when the faith tab offers it, `faith` + `faith_can_buy`;
    `faith_only` rows (Missionaries, Great People, belief buildings) cannot be produced, only bought
    with purchase_production(yield_type="FAITH").
    Each row carries the enum in `item` and, when it differs, the `name` the chooser button shows:
    BNW renamed several (BUILDING_THEATRE is "Zoo"), and `cities()` prints that name, not the enum.
    A puppet is refused (its AI picks production; `producing` says what) -- except for Venice, whose
    puppets answer `purchase_only: true` with just the gold/faith rows the purchase screen offers."""
    return J(game().available_production(city_id))


@mcp.tool()
@guarded
def available_unit_actions(unit_id: int) -> str:
    """Legal unit-panel actions for this unit right now (missions, tile builds on ITS plot, commands,
    promotions). Call this before unit_mission. Move-to is a separate tool (move_unit). Does not select
    the unit or pan the camera. For Workers/Work Boats also returns `nearby_builds`: plots within 2 tiles
    that still need work (unimproved, or pillaged) with the builds legal there -- move_unit onto one, then
    unit_mission(MISSION_BUILD, build=...). `build_info` adds the unit-panel turns and yield_delta for each
    build. A build issued with 0 moves left starts next turn. `ranged_targets` includes combat strength
    and expected damage; air previews include retaliation and a warning about interception.
    Melee previews include `fire_support_damage` in damage taken and its effect on damage dealt.
    `promotions` are the chooser's own rows -- `promotion` (pass this to choose_promotion) and `name`;
    what each does is in reference("promotions"). An action row's `help` is only the line the panel
    computes for this unit (upgrade target and price, scrap gold, golden age length, paradrop range);
    the standing sentence for every action is in reference("actions")."""
    return J(game().available_unit_actions(unit_id))


@mcp.tool()
@guarded
def todo_actions(unit_ids: list[int] | None = None, full: bool = False, detail: str = "",
                 limit: int | None = None) -> str:
    """Legal actions for many units in one call. With no `unit_ids`: every unit in `turn_status.todo.units`
    (still needs an order) plus every unit with a promotion waiting; with `unit_ids`: exactly those.
    Each row is what `available_unit_actions` returns for that unit (actions, promotions, nearby_builds,
    attack_targets, ranged_targets, moves, x, y) plus `id`, `type` and `promotion_ready`. Action rows
    drop the computed `help` line (upgrade price, scrap gold) unless `full=true`; the standing text
    for every action and promotion is in reference("actions") / reference("promotions"). One query instead of one per unit: the
    read for a whole turn's units in one call. Refused while it is not our turn unless unit_ids is given.
    `detail`: "normal" (default, the rows above), "full" (same as full=true) or "summary": per unit only id,
    type, x, y, moves, promotion_ready, `actions` as bare type strings minus the everyday ones (move, route,
    swap, skip, sleep, fortify, alert, wake, cancel, delete, automate/stop, remove route -- listed once in
    `routine_actions`, counted per unit in `routine`), `promotions` (enums for choose_promotion), `attack` /
    `ranged` targets (x, y, unit or city, owner, hp; no preview) and `build_plots` (x, y, builds, resource).
    `drill_down` gives the exact todo_actions arguments for the normal rows. Same single read at every level;
    a summary of 38 units is a fraction of the normal size. `limit` returns the first N units in todo order
    and lists the rest in `omitted` (count, ids, the args that fetch them). Every reply has `detail`, `n`
    (total units) and `returned`."""
    return J(game().todo_actions(unit_ids or None, full, detail=detail or None, limit=limit))


@mcp.tool()
@guarded
def available_trade_routes(unit_id: int, detail: str = "summary") -> str:
    """Valid trade-route destinations for a specific trade unit (caravan/cargo ship) right now, with the
    trade_type to pass into establish_trade_route. Yields are PER TURN: gold/science/food/production are
    what my end receives, *_them what the destination receives (an internal food/production route delivers
    to the destination city, so read food_them/production_them for those). Religious pressure, when the
    chooser would print it, is `from_religion`/`from_pressure` and `to_religion`/`to_pressure`.
    kind = international|food|production. detail="full" adds `details`, the gold and science hover behind
    each row (the same numbers, itemised: base, buildings, resources, river; a paragraph per destination).
    A list means there are destinations; when there are none it is an object instead, saying why -- a route
    starts inside one of my own cities, so a unit in the field gets the nearest one to walk to."""
    return J(game().available_trade_routes(unit_id, detail=detail))


@mcp.tool()
@guarded
def trade_routes() -> str:
    """Trade Route Overview: `outgoing` is Your TR (my caravans/cargo ships), `incoming` is With You
    (other civs' routes into my cities). Each row: from/to city and player, turns_left, per-turn yields
    for the origin (`gold`/`science`) and destination (`gold_them` / food_them / production_them).
    The religion columns are `from_religion`/`from_pressure` (left arrow) and `to_religion`/`to_pressure`
    (right arrow), omitted when that cell is blank. `details` is the gold and science hover.
    overview().trade_routes_used vs trade_routes_available says whether a slot is free for a new caravan.
    `path` is the route line the map draws, plot by plot from the origin (vis=false where fogged), as
    the plot hover names it on any revealed plot. `unit` is the caravan/cargo ship on that line (ours
    always; a foreign one only while in sight) with `escorted` / `escorted_by`: our combat units on its
    plot, which an enemy must defeat before it can plunder. `enemies_near_path` lists visible enemy
    combat units within one hex of the line with their distance to the caravan."""
    return J(game().trade_routes())


@mcp.tool()
@guarded
def establish_trade_route(unit_id: int, dest_x: int = -1, dest_y: int = -1, trade_type: int = -1,
                          city_name: str = "", kind: str = "") -> str:
    """Send a caravan/cargo ship to establish a trade route. Either pass dest_x/dest_y/trade_type from
    available_trade_routes(unit_id), or just `city_name` (e.g. "Antwerp") with `kind` =
    international/food/production when that city offers more than one route type."""
    return J(game().establish_trade_route(unit_id, dest_x, dest_y, trade_type, city_name=city_name, kind=kind))


@mcp.tool()
@guarded
def plunder_trade_route(unit_id: int) -> str:
    """Order a military unit standing on an enemy trade route to plunder it."""
    return J(game().plunder_trade_route(unit_id))


@mcp.tool()
@guarded
def spies() -> str:
    """My spies: agent_id, name, rank, state, where stationed, and can_stage_coup. In a city-state the
    row carries the coup button's hover: `coup_chance` (percent) when it is enabled, otherwise
    `coup_why_not` (spy_dead / surveillance_pending / no_ally / we_are_ally) and `coup_ally`. In a
    foreign major city the row carries `city_potential`, the potential meter's hover: `state`
    potential (effective `potential`, `base_potential`, building/wonder/policy `modifiers`,
    `catch_spies` lines), cannot_steal, once_known or unknown. See available_spy_cities/move_spy/
    stage_coup for actions."""
    return J(game().spies())


@mcp.tool()
@guarded
def available_spy_cities(agent_id: int) -> str:
    """Cities a given spy (agent_id, from spies()) could be sent to right now -- my own cities (counter-intel)
    and others' (steal tech / set up a future coup). Feeds move_spy. `potential` is the espionage screen's
    base potential: for a foreign city, how much there is to steal; for my own, how exposed it is to theft;
    "unknown" until a spy has had that city under surveillance."""
    return J(game().available_spy_cities(agent_id))


@mcp.tool()
@guarded
def move_spy(agent_id: int, target_player_id: int, target_city_id: int, as_diplomat: bool = False) -> str:
    """Assign/relocate a spy (see available_spy_cities). Recall home instead with target_player_id=-1,
    target_city_id=-1. as_diplomat only applies when the target is another major civ's capital at peace."""
    return J(game().move_spy(agent_id, target_player_id, target_city_id, as_diplomat))


@mcp.tool()
@guarded
def stage_coup(agent_id: int) -> str:
    """Attempt a coup against a city-state's current ally with a spy that has established surveillance
    there (spies()'s can_stage_coup). Returns the `chance` the confirm printed, the `outcome`
    notification and `succeeded` (the city-state's ally is now us); a refusal says `why_not`."""
    return J(game().stage_coup(agent_id))


@mcp.tool()
@guarded
def league_status() -> str:
    """Read-only: World Congress state -- resolutions I can propose (between sessions) or vote on (during a
    session), each with the tooltip the League Overview shows (`details`). `name` is the button text
    with the choice's icon tag removed (the screen draws that icon): "World Religion: Tengriism",
    not "[ICON_RELIGION_TENGRIISM]". Greyed resolutions are `unavailable_enact`. Already in effect:
    `active_resolutions` and `active_effects`. Also
    `projects` (World's Fair / International Games / ISS: percent complete, our production, the hammers
    each reward tier needs). See league_propose_enact/league_propose_repeal/league_cast_votes.
    The same project paragraph is on a league process in available_production (`league_project`)."""
    return J(game().league_status())


@mcp.tool()
@guarded
def league_propose_enact(resolution_type: str, choice: int = -1) -> str:
    """Propose enacting a World Congress resolution, e.g. RESOLUTION_SCIENCES_FUNDING (see league_status()
    for what's currently proposable and any required `choice`). Needed to clear
    ENDTURN_BLOCKING_LEAGUE_CALL_FOR_PROPOSALS -- closing the popup without proposing does NOT clear it."""
    return J(game().league_propose_enact(resolution_type, choice))


@mcp.tool()
@guarded
def league_propose_repeal(resolution_id: int) -> str:
    """Propose repealing an active World Congress resolution (see league_status()'s proposable_repeal)."""
    return J(game().league_propose_repeal(resolution_id))


@mcp.tool()
@guarded
def league_cast_votes(votes: list[dict]) -> str:
    """Vote on this session's World Congress proposals (see league_status()'s votable while in_session).
    votes: [{"resolution_id": id, "direction": "enact"|"repeal", "num_votes": n, "choice": id (optional)}].
    For a plain yes/no proposal (every repeal; enacts with no `choices` listed) `choice` is required:
    "yes"/"no" or 1/0 (leagueoverview.lua's kChoiceYes/kChoiceNo). For proposals with
    `choices` (e.g. World Leader, host city) pass the listed choice id. Leftover votes are cast as abstain."""
    return J(game().league_cast_votes(votes))


@mcp.tool()
@guarded
def propose_deal(player_id: int, items: list[dict], ask_counter: bool = False) -> str:
    """Offer a trade to another civ. With an AI: drives the game's real leader / trade screens, proposes, reads
    the reply, closes them and reports measured `effects` (gold, gold/turn, happiness, per-resource
    import/export before vs after): nothing to poll afterwards. With another human seat: puts the same table
    on the PvP deal screen (`pvp: true`, `pending: true`); that seat answers with accept_deal / refuse_deal.
    items: [{"type":"RESOURCES","resource":"RESOURCE_DYE","from_us":true,"amount":1},
            {"type":"GOLD_PER_TURN","from_us":false,"amount":5}]
    Types: GOLD / GOLD_PER_TURN (amount), RESOURCES (resource, amount), OPEN_BORDERS, ALLOW_EMBASSY,
    DEFENSIVE_PACT, RESEARCH_AGREEMENT, TRADE_AGREEMENT (from_us picks the direction), CITIES (city_id),
    VOTE_COMMITMENT (resolution_id, choice_id, repeal), THIRD_PARTY_WAR / THIRD_PARTY_PEACE (other: player
    id), PEACE_TREATY (implied while at war: any deal then is peace with terms; or make_peace).
    Read trade_catalog(player_id) first: what is legal, how much gold each side can put up, which cities may
    be traded (capitals never), the vote and third-party rows. Lump-sum gold needs a Declaration of Friendship
    (a Brave New World rule; trade_catalog's gold.note says so); gold per turn is not gated. Refuses without
    opening a screen an amount that is not a positive whole number or beyond what that side has, a city
    outside the catalog, or an item that does not land on the table at the requested amount. ask_counter=true
    also returns the AI's counter-offer (`counter.items`), which can go straight back in. Timed items last the
    game's deal length (30 turns). Item rules in full: how_to_play("propose_deal")."""
    return J(game().propose_deal(player_id, items, ask_counter=ask_counter))


@mcp.tool()
@guarded
def demand(player_id: int, items: list[dict]) -> str:
    """The leader screen's Demand button: tell an AI leader to hand over `items` for nothing, through the
    game's real screens (Demand -> table with only THEIR pocket -> DEMAND -> the leader's answer), then
    close up and report `accepted`, `reply` and measured `effects` like propose_deal. items take
    propose_deal's shapes and are all from_us:false (GOLD, GOLD_PER_TURN, RESOURCES, CITIES, OPEN_BORDERS,
    ALLOW_EMBASSY...); pick from trade_catalog(player_id)'s `them` side. AI leaders only (a human seat has no
    leader screen: propose_deal sends them a table), and the button is greyed at war (make_peace instead).
    As in the stock game a refused demand is remembered against you by that leader; use it deliberately."""
    return J(game().demand(player_id, items))


@mcp.tool()
@guarded
def negotiate_deal(player_id: int, items: list[dict], mode: str = "equalize") -> str:
    """Ask an AI civ about a deal without committing to it (the trade screen's helper buttons), then close
    the screen. mode="equalize": put a draft on the table and ask what would make it acceptable;
    "what_will_ai_give": list only my items (from_us=true) and see what the AI offers for them;
    "what_does_ai_want": list only their items (from_us=false) and see what the AI asks in return.
    `items` takes propose_deal's rows, from_us saying who gives each one -- there is no offer/give/receive shape:
    [{"type":"RESOURCES","resource":"RESOURCE_GOLD","from_us":true,"amount":1}, {"type":"GOLD_PER_TURN","from_us":false,"amount":5}]
    Returns the AI's reply and the resulting table `items`, which can be passed to propose_deal as-is."""
    return J(game().negotiate_deal(player_id, items, mode=mode))



@guarded
def lua(code: str) -> str:
    """Escape hatch: run Lua in the InGame context and return printed output. Use the Civ V modding API
    (Players[i], Game, Map...). CAUTION: an unfamiliar or unvalidated engine call here can crash the whole
    game process outright, not just error -- this has happened before. Check the dedicated tools above
    first (there are more than it looks like: city_ranged_attack, choose_policy, found_pantheon/religion,
    trade routes, diplo_event...) and docs/lua_command_patterns.md / docs/lua_api_surface.md before writing
    a new raw call, and prefer a validated read (does the object have the method? does a Can*() check pass?)
    before a write. Disabled unless the server was started with CIV5_ALLOW_LUA=1 / --allow-lua."""
    if not lua_allowed():
        return J({"ok": False, "err": "raw lua is disabled for this server (start it with CIV5_ALLOW_LUA=1 or --allow-lua); "
                                      "use the dedicated tools instead"})
    return J(game().lua("InGame", code, timeout=20))


def register_lua_if_allowed() -> bool:
    """`lua` is deliberately NOT decorated with @mcp.tool(): it only appears in the tool list when the
    operator opts in. The in-body lua_allowed() check is the second fence for anyone calling the function directly."""
    if lua_allowed() and "lua" not in {t.name for t in mcp._tool_manager.list_tools()}:
        mcp.tool()(lua)
        return True
    return False


@mcp.tool()
@guarded
def choose_promotion(unit_id: int, promotion: str) -> str:
    """Choose an earned promotion, using its PROMOTION_ name."""
    return J(game().choose_promotion(unit_id, promotion))


@mcp.tool()
@guarded
def upgrade_unit(unit_id: int) -> str:
    """Upgrade a unit for gold along its upgrade path (e.g. Warrior -> Swordsman). Needs full moves,
    own/allied territory, the gold and any strategic resource. The engine replaces the unit: use the
    returned `unit_id` (new) from now on, not the one passed in. available_unit_actions lists
    COMMAND_UPGRADE when possible."""
    return J(game().upgrade_unit(unit_id))


@mcp.tool()
@guarded
def disband_unit(unit_id: int) -> str:
    """Disband (delete) one of my units -- the unit panel's Disband button. Irreversible. Frees its gold
    maintenance and any strategic resource it consumes (e.g. an obsolete Swordsman holding Iron). Returns
    `effects.before/after` with unit count and strategic_resources so the freed resource is measured."""
    return J(game().disband_unit(unit_id))


# ------------------------------------------------------------------ actions
@mcp.tool()
@guarded
def move_unit(unit_id: int, x: int, y: int) -> str:
    """Order one of my units to move to plot (x, y) (multi-turn paths allowed, like a right-click).
    Selects the unit like the unit panel does (orders go through the game's network path).
    A unit on a conditional order (give_order) is taken back: the order pauses (`order_paused`)."""
    g = game()
    return J(_took_back(g, unit_id, "move_unit", g.move_unit(unit_id, x, y)))


def _took_back(g, unit_id: int, tool: str, r: dict) -> dict:
    """A direct command to a unit an active order owns pauses the order (#32): one owner at a time."""
    note = getattr(g, "note_manual_order", None)
    if isinstance(r, dict) and r.get("ok") and note is not None:
        paused = note(unit_id, tool)
        if paused:
            r["order_paused"] = paused
    return r


@mcp.tool()
@guarded
def unit_mission(unit_id: int, mission: str, x: int = -1, y: int = -1, build: str = "") -> str:
    """Give a unit a mission: MISSION_FOUND (settle here), MISSION_FORTIFY, MISSION_SLEEP, MISSION_SKIP, MISSION_HEAL,
    MISSION_ALERT, MISSION_RANGE_ATTACK (x,y), MISSION_PILLAGE (result includes gold_gained), MISSION_EMBARK/DISEMBARK...
    An **air strike is MISSION_MOVE_TO onto the target plot** (that is how the game issues it); like a
    melee move onto an enemy, the result then carries `attack` with both sides' hp before/after and who died.
    An intercepted strike says so: `attack.intercepted`, `interceptor`, `shot_down` (from the game's own banner).
    MISSION_BUILD: pass the improvement in `build`, e.g. build="BUILD_FARM" (do NOT put it in x/y --
    those are for movement-shaped missions). Builds on the unit's own tile.
    MISSION_SPREAD_RELIGION / MISSION_REMOVE_HERESY: the unit must be inside or adjacent to the target city;
    the result's `effects` reports that city's followers/majority before and after, spreads_left, and (for a
    city-state) influence before/after, so no follow-up read is needed to know whether the spread worked.
    MISSION_CREATE_GREAT_WORK: the reply's `great_work` names the work and the city/building slot it filled.
    AUTOMATE_EXPLORE / AUTOMATE_BUILD (the unit panel's automation buttons, when available_unit_actions lists
    them) hand the unit to the game's own automation; it then never blocks end_turn. The reply has automated=true,
    and the unit is listed under turn_status.todo.ongoing until a new move_unit / unit_mission takes it back.
    Selects the unit like the unit panel does (orders go through the game's network path).
    A unit on a conditional order (give_order) is taken back: the order pauses (`order_paused`)."""
    if mission.startswith("BUILD_") and not build:
        # available_unit_actions lists builds by their BUILD_* type; take that name as given
        mission, build = "MISSION_BUILD", mission
    g = game()
    return J(_took_back(g, unit_id, "unit_mission", g.unit_mission(unit_id, mission, x, y, build=(build or None))))


@mcp.tool()
@guarded
def set_production(city_id: int, item: str, append: bool = False) -> str:
    """Set a city's production. item like UNIT_WARRIOR, UNIT_SETTLER, BUILDING_MONUMENT, PROJECT_..., PROCESS_WEALTH.
    append=true queues it behind the current build (the production screen's shift-click) instead of replacing
    it; the reply lists the whole `queue`."""
    order = {"UNIT": "ORDER_TRAIN", "BUILDING": "ORDER_CONSTRUCT", "PROJECT": "ORDER_CREATE", "PROCESS": "ORDER_MAINTAIN"}[item.split("_", 1)[0]]
    return J(game().set_production(city_id, order, item, append=append))


def _purchase_order(item: str) -> str | None:
    # PROJECT_* was missing: live t391 purchase_cost(PROJECT_APOLLO_PROGRAM) died with KeyError 'PROJECT'.
    return {"UNIT": "ORDER_TRAIN", "BUILDING": "ORDER_CONSTRUCT", "PROJECT": "ORDER_CREATE"}.get(item.split("_", 1)[0].upper())


@mcp.tool()
@guarded
def purchase_cost(city_id: int, item: str, yield_type: str = "GOLD") -> str:
    """Read-only: cost to rush-buy item (UNIT_.../BUILDING_...) with gold or faith right now, and whether
    it's actually purchasable. yield_type is "GOLD" (default) or "FAITH". Wonders (built via a BUILDING_* item
    too) are never purchasable in vanilla BNW -- can_purchase will read false. Check this before purchase_production.
    A refusal carries `reason` and, when the engine has one, `engine_reason`: the same sentence the
    production popup puts under a greyed-out purchase button."""
    order = _purchase_order(item)
    if order is None:
        return J({"ok": False, "err": f"{item!r}: purchasable items are UNIT_*, BUILDING_* or PROJECT_*"})
    return J(game().purchase_cost(city_id, order, item, yield_type))


@mcp.tool()
@guarded
def purchase_production(city_id: int, item: str, yield_type: str = "GOLD") -> str:
    """Rush-buy a unit or building (item like UNIT_WARRIOR, BUILDING_MARKET) with gold or faith (yield_type
    "GOLD", the default, or "FAITH"). See purchase_cost for price/affordability first. Wonders can never be purchased this way."""
    order = _purchase_order(item)
    if order is None:
        return J({"ok": False, "err": f"{item!r}: purchasable items are UNIT_*, BUILDING_* or PROJECT_*"})
    return J(game().purchase_production(city_id, order, item, yield_type))


@mcp.tool()
@guarded
def steal_tech_options() -> str:
    """When a spy finished stealing: which civs I can take a tech from and the techs available from each.
    Each victim carries `player_id` -- pass that to steal_tech. Also listed on turn_status.todo.steal_tech even if blocking_name is still
    POLICY/PRODUCTION/etc. (the engine reports one blocker at a time)."""
    return J(game().steal_tech_options())


@mcp.tool()
@guarded
def steal_tech(tech: str, player_id: int) -> str:
    """Take a stolen tech (TECH_...) from `player_id` (steal_tech_options lists each victim and the
    techs available from it). Clears ENDTURN_BLOCKING_STEAL_TECH."""
    return J(game().steal_tech(tech, player_id))


@mcp.tool()
@guarded
def set_research(tech: str) -> str:
    """Choose current research, e.g. TECH_POTTERY, TECH_MINING, TECH_BRONZE_WORKING. Also the way to claim a
    free technology (blocking_name ENDTURN_BLOCKING_FREE_TECH, e.g. Oxford University): the named tech is
    granted outright (`granted`), current research is left as it was. A tech whose prerequisites are
    missing works like clicking it in the tech tree: the game researches the first missing step now and
    queues the rest (`goal`, `queue` in the reply)."""
    return J(game().set_research(tech))


@mcp.tool()
@guarded
def quick_save() -> str:
    """Save the game right now (same as the in-game Quick Save / F5). Cheap -- call it after anything
    costly (founding a city, a policy/research choice, before combat), not just periodically, since a
    crash loses everything back to the engine's last autosave otherwise."""
    return J(game().quick_save())


def _loaded_new_game(r: dict) -> dict:
    """After a load: the seat gets detected afresh (an auto seat from the previous game may be wrong for
    this one) and the answer says which seat the server is on."""
    global _seat_rechecked, _seat_unresolved
    g = game()
    if r.get("ok") and os.environ.get("CIV5_SEAT", "auto") == "auto":
        g._mode = None
        _seat_rechecked = False
        _seat_unresolved = not _resolve_seat(g)
    r["seat"] = g.seat
    return r


@mcp.tool()
@guarded
def load_save(filename: str) -> str:
    """Load a save from the main menu by its bare name, no path or .Civ5Save extension (e.g. "QuickSave",
    or "Sejong_0180 AD-1200" for a manual save). Only works from a fresh main-menu state, not mid-game:
    exit_to_main_menu first. The answer carries `seat`, the player this server will play in the loaded
    game (auto seats are detected afresh; hotseat keeps the default, set_seat changes it)."""
    return J(_loaded_new_game(game().load_save(filename)))


@mcp.tool()
@guarded
def load_latest() -> str:
    """Crash-recovery: load whichever save (quicksave OR autosave) has the newest filesystem mtime,
    regardless of name. Prefer this over load_save("QuickSave") when resuming after a crash -- an
    autosave made during play can be newer than the last explicit quicksave, and load_save only checks
    quick/manual saves before ever considering autosaves. Only works from a fresh main-menu state:
    exit_to_main_menu first. The answer carries `seat` like load_save."""
    return J(_loaded_new_game(game().load_latest()))


@mcp.tool()
@guarded
def exit_to_main_menu(save: bool = True) -> str:
    """Leave the loaded game for the main menu, so load_save / load_latest can open another save. Quick-saves
    first when it is my turn in a solo game (save=false skips that); in a game with other people ask the
    human before leaving, as it ends the game for them too. Waits until the main menu is on screen.
    Usable while it is not my turn."""
    g = game()
    if not g.has_state("InGame"):
        return J({"ok": True, "already": True, "screen": g.front_end_screen(), "seat": g.seat})
    saved = False
    if save:
        try:
            ts = g.turn_state()
            if ts.get("mode") == "single" and ts.get("my_turn") and not ts.get("processing"):
                g.quick_save()
                saved = True
        except (TunerdError, TimeoutError, OSError, ValueError, KeyError):
            saved = False
    g.leave_to_main_menu()
    deadline = time.monotonic() + 45
    screen = "?"
    while time.monotonic() < deadline:
        try:
            screen = g.front_end_screen()
        except (TunerdError, TimeoutError, OSError):
            screen = "?"
        if screen == "MainMenu":
            break
        time.sleep(1.0)
    return J({"ok": screen == "MainMenu", "screen": screen, "saved": saved, "seat": g.seat,
              "hint": "load_save(filename) or load_latest opens a game" if screen == "MainMenu"
              else "the main menu has not appeared yet; turn_status reports the screen"})


@mcp.tool()
@guarded
def end_turn(autosave: bool = True, force: bool = False) -> str:
    """End my turn. If something blocks it (unit needs orders, research/production choice), turn_status shows it.
    Auto-quicksaves first by default (single-player only) -- cheap insurance against this game's frequent
    ambient crashes; pass autosave=False to skip. Refused with `turn_claim` when another client of this seat
    gave this turn's first order and is still at it (its pid and timings are in the answer): that client owns
    the turn until 180 s pass without an order from it or its process exits; force=true takes it over."""
    return J(game().end_turn(autosave, force=force))


@mcp.tool()
@guarded
def finish_turn(autosave: bool = True, timeout_seconds: int = 600, skip_quiet_turns: int = 0,
                wake_on: list[str] | None = None, force: bool = False, briefing: bool = False,
                notes: str = "new", ctx: Context = None) -> str:
    """The turn boundary as one call: end my turn, wait until it is my turn again, and return the new turn --
    `status` (as turn_status), `digest` (as turn_digest: what happened while I was away), `turn` and `notes`
    (notebook entries since my last finish_turn or briefing; notes="all" brings the latest eight). briefing=true
    returns `briefing` (see the briefing tool) in place of status and digest. If the turn will not end, ok=false
    and `end_turn` carries the refusal with the todo that blocks it: nothing is waited on.
    Safe to repeat: when it is already not my turn it only waits, never ends a second turn. Returns early with
    discussion_pending=true (an AI wants an answer: discussion() then respond_discussion / accept_deal /
    refuse_deal / dismiss_discussion, then call again) or tech_popup_pending=true (set_research). timed_out=true
    means the AIs are still moving after timeout_seconds: call again (the default 600 is safe in Claude Code,
    which moves a long call to a background task; under a client with a hard per-call limit stay below it).
    Progress notifications go out every few seconds.
    skip_quiet_turns=N keeps ending turns, up to N more, while nothing needs me (no unit awaiting orders, empty
    city, promotion, popup, blocker, expiring ally, worsening alert, paused order or eventful digest); wake_on
    adds my own words (event kinds or notification text, e.g. ["Machinery"]). The skipped turns' digests are
    merged and `turns_skipped` / `woke_because` say what happened; the harness never issues an order for me.
    One client owns the turn: another client of this seat gets ok=false with `turn_claim` instead of ending a
    turn under it; force=true takes it over. autosave=false skips the quick-save before ending.
    Every key of the reply, what wakes a quiet run, and the claim rules: how_to_play("finish_turn")."""
    g = game()
    if notes not in ("new", "all"):
        return J({"ok": False, "err": f"notes must be 'new' or 'all', not {notes!r}"})
    r = g.finish_turn(autosave=autosave, timeout=timeout_seconds, on_wait=progress_reporter(ctx, g.seat),
                      skip_quiet_turns=max(0, int(skip_quiet_turns)), wake_on=wake_on, force=force)
    r["seat"] = g.seat
    # The gate of the turn handed back: from `status` on a normal boundary, from the answer itself when it
    # returned early (a discussion, a tech choice, a timeout carry the turn_state at top level).
    st = r.get("status") if isinstance(r.get("status"), dict) else r
    r["gate"] = _gate(st, g.seat)
    if r.get("timed_out") and r.get("hotseat") and r.get("active_player") != g.seat:
        r["hint"] = (f"hotseat: seat {r.get('active_player')} is on screen and this server plays seat {g.seat}: "
                     "still the other player's turn; call again")
        if _may_change_seat():
            r["hint"] += f". Only if nobody else plays seat {r.get('active_player')}, set_seat({r.get('active_player')})"
    if briefing and r.get("ok") and isinstance(r.get("status"), dict) and r["gate"] is None:
        try:
            with _op(g):
                b = _briefing_for(g, {**r["status"], "seat": g.seat}, notes=notes)
        except Exception as e:  # noqa: BLE001 -- the turn has already ended: status and digest must still arrive
            b = {"ok": False}
            r["briefing_error"] = f"{type(e).__name__}: {e}"
        if b.get("ok") and b.get("gate") is None:
            r["briefing"] = b
            if r["status"].get("orders"):
                # What the orders did at this turn start; their state (now, pause, steps) is in the briefing's own
                # `orders`, so the full rows are not repeated here (#43: ~1.1 KB a turn with two open orders).
                so = r["status"]["orders"]
                r["orders"] = {k: v for k, v in so.items() if k != "rows"}
                r["orders"]["rows"] = [{k: v for k, v in row.items() if k in ("id", "unit", "status", "did")}
                                       for row in so.get("rows") or [] if isinstance(row, dict)]
                r["orders"]["state"] = "briefing.orders"
            r.pop("status", None)
            r.pop("digest", None)
    if "briefing" not in r:   # the briefing carries the notes itself (and moved the hand-off cursor once)
        try:
            with _op(g):   # game_key() reads the game once per process
                r.update(g.notebook().hand_off_section(notes))
        except Exception:  # noqa: BLE001 -- the notebook is a convenience; the turn result must still arrive
            pass
    return J(r)


# ------------------------------------------------------------------ many orders, one call
# Tools that never belong inside a batch: the ones that wait, load, or run raw Lua, and the batch itself.
BATCH_EXCLUDED = {"do", "wait_for_my_turn", "finish_turn", "lua", "load_save", "load_latest", "end_turn", "set_seat", "exit_to_main_menu"}
MAX_BATCH = 40
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


def _run_tool_here(name: str, args: dict) -> str:
    """Call one registered tool synchronously with the SDK's own argument validation (a batch runs in the
    worker thread already, so no event-loop hop). Returns the tool's JSON string, or a JSON error."""
    tm = mcp._tool_manager
    tool = tm.get_tool(name)
    if tool is None:
        return J({"ok": False, "err": unknown_tool_hint(name, sorted(t.name for t in tm.list_tools()))})
    args = alias_arguments(dict(args or {}), tool.parameters)
    try:
        meta = tool.fn_metadata
        if hasattr(meta, "validate_arguments"):
            validated = meta.validate_arguments(args)
        else:  # mcp 1.x
            validated = meta.arg_model.model_validate(meta.pre_parse_json(args)).model_dump_one_level()
    except Exception as e:  # noqa: BLE001 -- a validation error is the caller's to read
        return J({"ok": False, "err": f"{type(e).__name__}: {e}", "accepts": f"{name}{tool_signature(tool.parameters)}"})
    ctx_kwarg = getattr(tool, "context_kwarg", None)
    if ctx_kwarg:
        validated[ctx_kwarg] = None
    r = tool.fn(**validated)
    return r if isinstance(r, str) else J(r)


@mcp.tool()
def do(actions: list[dict], stop_on_refusal: bool = True, force: bool = False) -> str:
    """Carry out a list of orders in one call, in order: [{"tool": "unit_mission", "args": {"unit_id": 7,
    "mission": "MISSION_FORTIFY"}}, {"tool": "set_production", "args": {...}}, ...]. Each order is the named
    tool with its own arguments and comes back with its own result under `results` (index, tool, result).
    The first refusal (ok=false) stops the batch by default: the orders after it are listed under `skipped`,
    since the state they were reasoned about is no longer certain; stop_on_refusal=false runs them all.
    Not allowed inside: wait_for_my_turn, finish_turn, end_turn, load_*, lua, do. At most 40 orders.
    An order may carry "action_id": a retried batch after a transport timeout then replays the results of
    orders already carried out instead of repeating them (see the server instructions on action_id).
    force=true takes the turn over from another client of this seat that still holds it (see end_turn)."""
    if not isinstance(actions, list) or not actions:
        return J({"ok": False, "err": "actions must be a non-empty list of {tool, args}"})
    if len(actions) > MAX_BATCH:
        return J({"ok": False, "err": f"at most {MAX_BATCH} orders per batch"})
    if force:
        # Take the turn over from another client of this seat before the orders run (each order then finds
        # the claim ours). Without force each order claims for itself and the first is refused if held.
        g = game()
        with _op(g):
            ts = g.turn_state()
            if ts.get("active_player") == g.seat:
                _claim_for(g, ts, "do", force=True)
    results, skipped = [], []
    stopped = False
    for i, a in enumerate(actions):
        if stopped:
            skipped.append({"index": i, "tool": a.get("tool") if isinstance(a, dict) else None})
            continue
        if not isinstance(a, dict) or not isinstance(a.get("tool"), str):
            results.append({"index": i, "tool": None, "result": {"ok": False, "err": "each order is {tool: str, args: object}"}})
            stopped = stop_on_refusal
            continue
        name, args, action_id = a["tool"], a.get("args") or {}, a.get("action_id")
        if isinstance(args, dict) and "action_id" in args and action_id is None:
            # the id belongs beside `args`, but inside them is the natural place to put it (Codex, t54:
            # set_research refused the extra field and the rest of the batch was skipped)
            args = dict(args)
            action_id = args.pop("action_id")
        if name in BATCH_EXCLUDED:
            r = J({"ok": False, "err": f"{name} cannot run inside a batch; call it on its own"})
        else:
            r = _replayed(name, action_id)
            if r is None:
                r = _run_tool_here(name, args if isinstance(args, dict) else {})
                _remember_result(name, action_id, r)
        try:
            rv = json.loads(r)
        except ValueError:
            rv = {"raw": r}
        results.append({"index": i, "tool": name, "result": rv})
        if stop_on_refusal and isinstance(rv, dict) and rv.get("ok") is False:
            stopped = True
    all_ok = all(isinstance(r["result"], dict) and r["result"].get("ok") is not False for r in results)
    out = {"ok": all_ok and not stopped, "done": len(results), "results": results}
    if skipped:
        out["skipped"] = skipped
        out["hint"] = "re-read the state (turn_status / units) before re-issuing the skipped orders"
    return J(out)


# ------------------------------------------------------------------ notebook: what a human keeps in their head
@mcp.tool()
@guarded
def remember(text: str, tag: str = "", replace_id: int | None = None, retag: bool = False) -> str:
    """Write a note to my notebook for this game: the plan, a promise, a threat, why I did something
    ("Tradition then Rationalism", "Askia denounced me t140: expect a DoW", "keep 2 archers in Moson Kahni").
    Notes survive session restarts and context loss: they live beside the game (one notebook per game and
    seat, keyed by leader/civ/map/capital), and the latest ones ride along in every finish_turn result.
    tag groups notes (plan, threat, diplomacy, todo...). replace_id rewrites an existing note in place, so a
    living plan stays one note instead of a trail of superseded ones; the result carries `previous` (the
    text, tag and turn it overwrote). A replace whose tag differs from the stored tag is refused with
    `stored_tag` and writes nothing (the id was probably wrong); an empty tag keeps the stored tag, and
    retag=true allows the change. Usable while it is not my turn."""
    g = game()
    return J(g.notebook().remember(text, turn=g.turn_state().get("turn", -1), tag=tag, replace_id=replace_id,
                                   retag=retag))


@mcp.tool()
@guarded
def recall(tag: str = "", limit: int = 50) -> str:
    """Read my notebook for this game (see remember): every note with its id, the turn it was written on
    and its tag; tag filters, `limit` is the newest N (default 50). The last few also arrive with each
    finish_turn result. Usable while it is not my turn."""
    return J(game().notebook().recall(tag=tag, limit=limit))


@mcp.tool()
@guarded
def forget(note_id: int) -> str:
    """Delete one note from my notebook by id (recall lists them)."""
    return J(game().notebook().forget(note_id))


@mcp.tool()
@guarded
def assign(role: str, purpose: str, unit_ids: list[int] | None = None, city_ids: list[int] | None = None,
           target: dict | None = None, done_when: dict | str | None = None, review: dict | None = None,
           replace_id: int | None = None) -> str:
    """Give units or cities a structured assignment in my notebook: what they are for, where, when it is done
    and when to look again. A prose note (remember) says why; an assignment lets a later me -- after a context
    reset, in a new session -- see at once what each unit is doing and whether that still holds.
    role: a short word (escort, settle, improve, defend, explore, diplomacy...). purpose: one sentence.
    unit_ids / city_ids: mine, now; each is fingerprinted (type and creation turn; name and founding turn), so
    if an id later names a different unit the assignment says the assigned one is gone instead of following it.
    target: {x, y} a plot (a city site, a tile to improve, a city to take or hold), {unit_id, owner} a foreign
    unit, or {player} a civ or city-state. done_when (checked on every read; default "manual"): {kind:
    "unit_at"|"city_at"|"improvement", x, y} (x, y default to the target plot; unit_at takes unit_id,
    improvement takes improvement e.g. "FARM"), {kind: "building", city_id, building}, {kind: "tech", tech}.
    review (optional): {turn: N, hostile_within: plots, hp_below: percent} -- look again at turn N, when a
    visible hostile comes that close to an assigned unit or city, when an assigned unit's hp drops below.
    replace_id: this replaces that assignment, which is closed as replaced (the two never compete).
    The answer is the stored assignment reconciled right away (see assignments). One game read."""
    g = game()
    return J(g.assign(role, purpose, unit_ids=unit_ids, city_ids=city_ids, target=target, done_when=done_when,
                      review=review, replace_id=replace_id))


@mcp.tool()
@guarded
def assignments(status: str = "active") -> str:
    """My assignments (see assign), each reconciled against what I can see now, in one game read. An active row:
    id, role, purpose, since_turn, `state` -- condition_met (its done_when holds: `evidence` says how;
    close_assignment it), needs_review (`reasons` lists each observation: an assigned unit missing or gone -- an
    upgrade on its last plot is named --, a city no longer mine, the target plot's owner changed or a city now
    too close to a site, a target unit not where last seen, a war or elimination, the review turn, a hostile
    within range, low hp) or on_track --, `units` / `cities` as they are now, `target` as observed (a fogged
    plot or an out-of-sight unit is `known`: stale / unknown with when it was last seen; never assumed gone or
    still there), done_when and review. Nothing is closed, re-targeted or ordered for me.
    status: "active" (default), "closed" (completed, cancelled, replaced), or "all". briefing() carries the
    active ones compactly, needing-a-look first."""
    return J(game().assignments(status=status))


@mcp.tool()
@guarded
def amend_assignment(assignment_id: int, role: str | None = None, purpose: str | None = None,
                     unit_ids: list[int] | None = None, city_ids: list[int] | None = None,
                     target: dict | None = None, done_when: dict | str | None = None, review: dict | None = None,
                     note: str = "") -> str:
    """Change an active assignment in place: only the fields given change (role, purpose, done_when and review
    as in assign; unit_ids / city_ids replace the list; target={} clears the target; review={} clears the triggers). Use it when a unit was upgraded (new id), a
    site moved, or the review turn passed and the plan still holds. note is kept in the assignment's history.
    The answer is the amended assignment reconciled now, with `previous` values. One game read."""
    changes = {k: v for k, v in (("role", role), ("purpose", purpose), ("unit_ids", unit_ids), ("city_ids", city_ids),
                                 ("target", target), ("done_when", done_when), ("review", review)) if v is not None}
    return J(game().amend_assignment(assignment_id, changes, note=note))


@mcp.tool()
@guarded
def close_assignment(assignment_id: int, outcome: str = "completed", note: str = "") -> str:
    """Close an active assignment: outcome "completed" or "cancelled", with an optional note (why). Closed ones
    leave the briefing and stay readable with assignments(status="closed"). Usable while it is not my turn."""
    return J(game().close_assignment(assignment_id, outcome=outcome, note=note))


# ------------------------------------------------------------------ conditional orders (#32)
@mcp.tool()
@guarded
def give_order(unit_id: int, steps: list[dict | str], interrupt: dict | None = None, purpose: str = "",
               replace_id: int | None = None, start: bool = True) -> str:
    """Give one of my units a short sequence of steps the harness carries out over the coming turns, so a plan
    already chosen does not cost a call every turn. steps (at most 6, in order): {kind: "move", x, y} walk
    there (multi-turn); {kind: "build", build: "FARM"} build it where the previous move ends (x, y name
    another plot); {kind: "heal", hp: 80} heal to at least that percent (default 100); {kind: "hold", mission:
    "fortify"|"sleep"|"alert"} as the last step. Example: move to (12,8) then build FARM; or heal to 80, move
    to (30,14), hold. purpose is a free-text label for the order.
    It runs now (start=true) as far as it can, then at the start of each of my turns (finish_turn /
    wait_for_my_turn carry `orders`), one step per turn at most, through move_unit / unit_mission. It pauses
    and hands the unit back with `pause.reason` and `hint` when a hostile comes into sight within
    interrupt.hostile_within plots (default 2; 0 off), the unit was damaged (interrupt.damaged, default true)
    or is below interrupt.hp_below, an enemy stands on the destination (an order never attacks), a step is
    refused or makes no progress, a save was loaded, or I give the unit a direct order. An order never declares
    war, attacks, ends the turn or touches another unit; a unit on automation leaves it as soon as the order
    is stored. One open order per unit (replace_id replaces it); a first step that cannot run now refuses the
    order. Stored in my notebook: orders survive a restart, briefing() lists them, resume_order / cancel_order
    finish a paused one. Every interrupt and state: how_to_play("give_order")."""
    return J(game().give_order(unit_id, steps, interrupt=interrupt, purpose=purpose, replace_id=replace_id,
                               start=start))


@mcp.tool()
@guarded
def orders(status: str = "open") -> str:
    """My conditional orders (see give_order) as stored, without reading the game: id, unit, status (active /
    paused; completed, cancelled, replaced, failed once closed), step N of M and `now` (the current step),
    `steps`, `state` (moving, building, healing, no_moves...), `pause` (kind, reason, hint, turn) when it waits
    for me, `last` (the last step issued: turn, what, ok, err / note), `issued_count` (calls it made for me),
    `purpose`. status: "open" (default), "closed" or "all". Usable while it is not my turn."""
    return J(game().orders(status=status))


@mcp.tool()
@guarded
def resume_order(order_id: int) -> str:
    """Hand a paused order its unit back and run it now (an active one just runs now). What paused it -- the
    hostiles in sight, the hp now -- is taken as seen, so only something new pauses it again. Every step is
    re-checked against the board first: a step completed meanwhile is not issued again. To change the plan
    instead, give_order with replace_id."""
    return J(game().resume_order(order_id))


@mcp.tool()
@guarded
def cancel_order(order_id: int, note: str = "") -> str:
    """Close an open order as cancelled (note: why). The standing move it had issued is dropped, so the unit
    stops where it is; a build or fortify already under way is left alone. Usable while it is not my turn."""
    return J(game().cancel_order(order_id, note=note))


@mcp.tool()
@guarded
def reference(section: str | None = None) -> str:
    """The rule book, as Markdown: what every unit, building, wonder, project, process, promotion, social
    policy and ideology tenet, technology, belief, resource, terrain, feature, improvement, specialist and
    unit action does, read once from this game's own database (mods and DLC included) and cached. No other
    answer repeats this text (since runtime v216): chooser rows carry the enum, the name and live numbers,
    and a resource tile carries its resource name. Sections, one per call with `section`: terrain,
    resources, improvements, units, buildings, projects, processes, promotions, policies, techs, beliefs,
    specialists, actions. The whole book is long (tens of thousands of tokens): read it once at the start of
    a game if you can hold it, otherwise the section a choice needs. Also served as the MCP resources
    civ5://reference and civ5://reference/{section}. Usable while it is not
    my turn."""
    out = game().reference_markdown(section)
    return out if isinstance(out, str) else J(out)


@mcp.tool()
def how_to_play(topic: str = "") -> str:
    """How to play through these tools, from the playbook shipped with this server; needs no game and works at
    any time. With no topic: the index of topics and the introduction (what you are, what you see, `gate`,
    seats, loading a game). Playbook topics: start, turn_loop (every turn in order; two agents or two clients on
    one game), quiet_turns (skip_quiet_turns and what wakes a run), batches (do and action_id), verify,
    blockers (the end-turn blocker table and what clears each), diplomacy (leader screens, discussions, the
    trade table), rules (what the harness refuses on purpose), first_turn; "all" is the whole playbook. A tool
    name -- finish_turn, briefing, turn_status, overview, compare, propose_deal, give_order -- is that reply's
    full key-by-key reference, the part its own description leaves out. Read a topic once, when you first
    need it; the answer is Markdown."""
    return guide.how_to_play(topic)


@mcp.resource("civ5://reference", name="reference", description="The rule book: what every unit, building, tech, policy, promotion, belief, resource, terrain, improvement and unit action does, from this game's database. Markdown.", mime_type="text/markdown")
def reference_resource() -> str:
    out = game().reference_markdown()
    return out if isinstance(out, str) else J(out)


@mcp.resource("civ5://reference/{section}", name="reference_section", description="One section of the rule book: terrain, resources, improvements, units, buildings, projects, processes, promotions, policies, techs, beliefs, specialists or actions. Markdown.", mime_type="text/markdown")
def reference_section_resource(section: str) -> str:
    out = game().reference_markdown(section)
    return out if isinstance(out, str) else J(out)


@mcp.resource("civ5://playbook", name="playbook", description="How to play through this harness: the turn loop, the blocker table, verification habits.")
def playbook_resource() -> str:
    path = Path(__file__).resolve().parent.parent / "docs" / "PLAYBOOK.md"
    try:
        return path.read_text()
    except OSError:
        return "PLAYBOOK.md is not installed alongside this server."


@mcp.prompt(name="play_turn", description="Play one turn of Civilization V through the civ5 tools.")
def play_turn_prompt() -> str:
    return ("Play my current turn of Civilization V through the civ5 tools. Start with briefing(since=\"turn\") "
            "(or the finish_turn result that brought you here) and read its gate first; how_to_play() explains "
            "the loop if you are new to it. Clear every item in decisions: todo_actions for the units, "
            "available_production then set_production for empty cities, available_research then set_research, "
            "answer any popup or leader screen. Give a repeating plan as one give_order. Then remember() what "
            "future-you must know and finish_turn. Never guess a plot or an id you have not read this turn.")


# Names a caller plausibly reaches for (they exist in the Game API, older docs, or other harnesses) mapped to
# the tool that answers it. The SDK's bare "Unknown tool: X" leaves the caller to list and guess.
TOOL_ALIASES = {"summary": "overview", "plots_around": "map_window", "turn_state": "turn_status",
                "state": "turn_status", "status": "turn_status", "digest": "turn_digest", "research": "set_research"}


def unknown_tool_hint(name: str, known: list[str]) -> str:
    import difflib
    hints = [TOOL_ALIASES[name]] if TOOL_ALIASES.get(name) in known else []
    hints += [n for n in difflib.get_close_matches(name, known, n=4, cutoff=0.5) if n not in hints]
    hints += [n for n in known if name in n and n not in hints][:4]
    return f"Unknown tool: {name}" + (f". Did you mean: {', '.join(hints[:5])}?" if hints else
                                      ". List the tools your client was given (tools/list).")


def _hint_unknown_tools() -> None:
    """Install the call wrapper (unknown-tool hints, argument aliases, action_id replay) once per process."""
    import sys
    tm = mcp._tool_manager
    if getattr(tm, "_civ5_wrapped", False):
        return
    tm._civ5_wrapped = True
    orig = tm.call_tool
    tool_error = sys.modules[type(tm).__module__].ToolError  # mcp 1.x and 2.x keep it in different packages

    import inspect
    converts_here = "convert_result" in inspect.signature(orig).parameters  # mcp 2.x: the manager converts

    def convert(tool, raw, want):
        if want and hasattr(tool.fn_metadata, "convert_result"):
            return tool.fn_metadata.convert_result(raw)
        return raw

    async def call_tool(name, arguments, *a, **kw):
        tool = tm.get_tool(name)
        if tool is None:
            raise tool_error(unknown_tool_hint(name, sorted(t.name for t in tm.list_tools())))
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
        if log:
            c = getattr(_game, "c", None)
            trips0, t0 = getattr(c, "trips", None), time.perf_counter()
        try:
            if converts_here:
                result = await orig(name, arguments, *a, convert_result=False, **kw)
            else:
                result = await orig(name, arguments, *a, **kw)
            _remember_result(name, action_id, result)
            if log:
                c = getattr(_game, "c", None)
                trips1 = getattr(c, "trips", None)
                trips = trips1 - (trips0 or 0) if isinstance(trips1, int) else None
                call_ledger.append(log, call_ledger.row(name, getattr(_game, "seat", None),
                                                        call_ledger.reply_text(result),
                                                        time.perf_counter() - t0, trips))
            return convert(tool, result, want_convert)
        except tool_error as e:
            if log:
                call_ledger.append(log, {**call_ledger.row(name, getattr(_game, "seat", None), "",
                                                           time.perf_counter() - t0, None),
                                         "ok": False, "err": str(e)[:call_ledger.ERR_CHARS]})
            # A pydantic rejection names the bad keys but not the good ones (live t324: x/y passed to
            # establish_trade_route, whose parameters are dest_x/dest_y). Append the signature.
            if type(e.__cause__).__name__ != "ValidationError":
                raise
            raise tool_error(f"{e}\n{name} accepts: {tool_signature(tool.parameters)}") from e.__cause__
    tm.call_tool = call_tool


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


_hint_unknown_tools()  # also for embeddings that never call main() (tests, other hosts)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seat", default=os.environ.get("CIV5_SEAT", "auto"), help="player id, or 'auto' (network games: the local player)")
    ap.add_argument("--allow-lua", action="store_true", help="enable the raw `lua` escape hatch (env CIV5_ALLOW_LUA=1)")
    a = ap.parse_args(argv)
    os.environ["CIV5_SEAT"] = str(a.seat)
    if a.allow_lua:
        os.environ["CIV5_ALLOW_LUA"] = "1"
    register_lua_if_allowed()
    _hint_unknown_tools()
    mcp.run()


if __name__ == "__main__":
    main()
