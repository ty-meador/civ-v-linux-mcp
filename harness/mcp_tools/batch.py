"""Many orders in one call.

One of the civ5 MCP server's tool modules: every tool here registers on the server in
harness/mcp_server.py, which keeps the game handle, the guard and the tool sets (see its docstring).
"""
from __future__ import annotations

import json

from harness import mcp_server as core
from harness.game_parts.units import defer_after_reads
from harness.surface import classes, forward
from harness.mcp_server import J, MAX_BATCH, _claim_for, _op, _remember_result, _replayed, _run_tool_here, retired


@retired
def do(actions: list[dict], stop_on_refusal: bool = True, force: bool = False) -> str:
    """Carry out a list of orders in one call, in order: [{"tool": "unit_mission", "args": {"unit_id": 7,
    "mission": "MISSION_FORTIFY"}}, {"tool": "set_production", "args": {...}}, ...]. Each order is the named
    tool with its own arguments and comes back with its own result under `results` (index, tool, result).
    The first refusal (ok=false) stops the batch by default: the orders after it are listed under `skipped`,
    since the state they were reasoned about is no longer certain; stop_on_refusal=false runs them all.
    Not allowed inside: the waits and the turn's end, a load, the seat, the exit, lua, a batch. At most 40 orders.
    An order may carry "action_id": a retried batch after a transport timeout then replays the results of
    orders already carried out instead of repeating them (see the server instructions on action_id).
    force=true takes the turn over from another client of this seat that still holds it (see end_turn).
    When the batch is the last thing before ending the turn, finish_turn(actions=[...]) runs it and ends the
    turn in the same call."""
    return J(run_batch(actions, stop_on_refusal=stop_on_refusal, force=force))


def run_batch(actions, stop_on_refusal: bool = True, force: bool = False) -> dict:
    """The body of `do`, as a dict: finish_turn(actions=...) runs its orders through here before ending the turn."""
    if not isinstance(actions, list) or not actions:
        return {"ok": False, "err": "actions must be a non-empty list of {tool, args}"}
    if len(actions) > MAX_BATCH:
        return {"ok": False, "err": f"at most {MAX_BATCH} orders per batch"}
    if force:
        # Take the turn over from another client of this seat before the orders run (each order then finds
        # the claim ours). Without force each order claims for itself and the first is refused if held.
        g = core.game()
        with _op(g):
            ts = g.turn_state()
            if ts.get("active_player") == g.seat:
                _claim_for(g, ts, "do", force=True)
    results, skipped = [], []
    # Every unit order reads the unit back after its mission (one tuner trip each); a batch reads them all in one
    # trip at its end instead. The switch is thread-local and cleared however the loop ends.
    deferred: list[tuple[int, str, object]] = []   # (result index, tool, action_id) of orders with a marker
    defer_after_reads(True)
    try:
        _run_orders(actions, results, skipped, deferred, stop_on_refusal)
    finally:
        defer_after_reads(False)
    _finish_deferred(core.game(), results, deferred)
    stopped = bool(skipped)
    # a refusal is an object saying ok=false; a list reply (units, cities in a batch of reads) is an answer
    all_ok = all(not (isinstance(r["result"], dict) and r["result"].get("ok") is False) for r in results)
    out = {"ok": all_ok and not stopped, "done": len(results), "results": results}
    if skipped:
        out["skipped"] = skipped
        out["hint"] = "re-read the state (turn(action='status') / inspect(what='units')) before re-issuing the skipped orders"
    return out


@retired
def call(tool: str = "", args: dict | None = None, describe: bool = False, action_id: str | None = None) -> str:
    """Retired (stage 2d, #51): any tool of this server by name, which is what a batch row is --
    batch(actions=[{tool, args}]) runs one and returns its answer under `results`. Still answers: call(tool, args)
    runs the tool and returns its reply unchanged (with `renamed`, the new call, when the name is an old one);
    call() lists every tool, one line each, by domain; describe=true returns one tool's description and arguments
    and runs nothing. action_id replays like any other order."""
    if not tool:
        return J({"ok": True, "tools": core.tool_catalog()})
    found = core.find_tool(tool)
    if found is None:
        return J({"ok": False, "err": core.unknown_tool_hint(tool, core.known_tool_names())})
    if describe:
        name, target, forwarded = found
        out = {"ok": True, "tool": name, "accepts": f"{name}{core.tool_signature(target.parameters)}",
               "description": target.description or ""}
        if forwarded:
            out["renamed"] = forward.renamed(forwarded)
        return J(out)
    if classes.of_call(tool, args) in classes.BATCH_EXCLUDED:
        return J({"ok": False, "err": f"{tool} is not run through call: it is not a batch row; call it on its own"})
    r = _replayed(tool, action_id)
    if r is None:
        r = _run_tool_here(tool, args if isinstance(args, dict) else {})
        _remember_result(tool, action_id, r)
    return r



def _run_orders(actions, results, skipped, deferred, stop_on_refusal) -> None:
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
        if classes.of_call(name, args if isinstance(args, dict) else {}) in classes.BATCH_EXCLUDED:
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
        if isinstance(rv, dict) and isinstance(rv.get("after_pending"), dict):
            deferred.append((len(results) - 1, name, action_id))
        if stop_on_refusal and isinstance(rv, dict) and rv.get("ok") is False:
            stopped = True


def _finish_deferred(g, results, deferred) -> None:
    """One read for every order that deferred its read-back, folded into each result; a result remembered for
    its action_id is remembered again complete, so a replay never shows the marker."""
    if not deferred:
        return
    markers = [results[i]["result"]["after_pending"] for i, _, _ in deferred]
    try:
        rows = g.read_after_batch(markers)
    except Exception as e:  # the orders went out; only their read-back failed: say so, never
        # let a reading that did not happen pass for a unit that is gone
        rows = [None] * len(markers)
        failure = f"the unit was not read back after the order ({e}); inspect(what='units') shows its state"
    else:
        failure = None
    for (i, name, action_id), marker, row in zip(deferred, markers, rows):
        rv = results[i]["result"]
        rv.pop("after_pending", None)
        if row is None:
            rv["note"] = failure
        else:
            try:
                g.apply_after(rv, marker, row)
            except Exception as e:
                rv["note"] = f"the unit was not read back after the order ({e}); inspect(what='units') shows its state"
        _remember_result(name, action_id, J(rv))
