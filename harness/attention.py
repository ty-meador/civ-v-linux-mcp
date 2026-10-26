"""Where one tool call's attention was: the plots its reply described (`seen`), the plots its arguments pointed at
(`intent`), the units and cities it named (`refs`) and how bright the visualization should paint it (`scope`).

Computed from the arguments and the parsed reply the ledger already has, so it costs no trips; the spectator
(harness/spectator) and the page (web/viz) draw it. docs/VISUALIZATION.md says what each field means on screen.

A batch's rows (`actions` of do / finish_turn, the `{tool, args}` rows every affordance reply hands back) are
read as rows: the tool and its arguments, never a sentence naming a tool.

Plots are `[x, y]` pairs, never wrapped: a tactical_view disk near the seam may name x = -1 or x = width, and the
page wraps them, because only the page knows the map width. `seen` is cut at SEEN_MAX with `seen_more` counting
the rest (a known_world reply after Satellites names every plot of the map).
"""
from __future__ import annotations

import json
from typing import Any

from . import hexgrid
from .surface.classes import Key, Keys

# Targeted reads: the model chose one object or spot and looked at it. Full-brightness pulse. Every other read
# is a broad scan (dim pulse); every write is an act (stays painted). Keyed by `(tool, action)`
# (harness/surface/classes.py), so a call by an old name counts as the new call it means.
FOCUS = Keys({("inspect", "unit/tactical"), ("inspect", "map/window"), ("inspect", "city/screen"),
              ("inspect", "unit/targets"), ("inspect", "map/frontier"), ("inspect", "compare"),
              ("inspect", "unit/actions"), ("inspect", "unit/home"), ("inspect", "city/production"),
              ("inspect", "city/strikes")})

SEEN_MAX = 4096
ARGS_CHARS = 1200
EXCERPT_CHARS = 240
#: The reads whose reply is a disk around a centre: the radius when the call named none.
DEFAULT_RADIUS: dict[Key, int] = {("inspect", "unit/tactical"): 2, ("inspect", "map/window"): 3}
GRID = ("inspect", "map/grid")    # revealed_map: a character grid placed by its window
ID_KEYS = ("unit_id", "city_id", "unit_ids", "city_ids", "spy_id", "assignment_id", "order_id")


def scope(key: Key, kind: str) -> str:
    if kind == "write":
        return "act"
    if kind == "wait":
        return "wait"
    return "focus" if key in FOCUS else "broad"


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def plots_in(value: Any, out: list[list[int]], budget: int = 64 * SEEN_MAX) -> None:
    """Collect every object with integer x and y anywhere inside `value` (lists and dicts, any depth). The budget
    only bounds pathological replies; `fields` cuts the list and counts the rest."""
    stack = [value]
    while stack and len(out) < budget:
        v = stack.pop()
        if isinstance(v, dict):
            if _is_int(v.get("x")) and _is_int(v.get("y")):
                out.append([v["x"], v["y"]])
            stack.extend(v.values())
        elif isinstance(v, list):
            stack.extend(v)


def _grid_plots(reply: dict) -> list[list[int]]:
    """revealed_map: the plots whose character is not blank, placed by the reply's window (north row first)."""
    layers = reply.get("layers")
    window = reply.get("window")
    if not isinstance(layers, dict) or not isinstance(window, dict):
        return []
    grid = layers.get("vis") or next((g for g in layers.values() if isinstance(g, list)), None)
    if not isinstance(grid, list):
        return []
    x0, y1 = window.get("x0", 0), window.get("y1")
    if not _is_int(y1):
        return []
    out = []
    for i, line in enumerate(grid):
        if not isinstance(line, str):
            continue
        y = y1 - i
        out.extend([x0 + j, y] for j, ch in enumerate(line) if ch != " ")
    return out


def _dedupe(pairs: list[list[int]]) -> list[list[int]]:
    seen: set[tuple[int, int]] = set()
    out = []
    for p in pairs:
        k = (p[0], p[1])
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def seen_plots(key: Key, args: dict | None, reply: Any) -> list[list[int]]:
    """The plots a reply handed the model. Special shapes first, the generic x/y walk for everything else."""
    args = args or {}
    if isinstance(reply, list):                       # units / cities answer with a bare list of rows
        out: list[list[int]] = []
        plots_in(reply, out)
        return _dedupe(out)
    if not isinstance(reply, dict) or reply.get("ok") is False:
        return []
    if key == GRID:
        return _dedupe(_grid_plots(reply))
    if key in DEFAULT_RADIUS:
        centre = None
        if key[1] == "unit/tactical":
            u = reply.get("unit")
            if isinstance(u, dict) and _is_int(u.get("x")) and _is_int(u.get("y")):
                centre = (u["x"], u["y"])
        elif _is_int(args.get("x")) and _is_int(args.get("y")):
            centre = (args["x"], args["y"])
        radius = args.get("radius", DEFAULT_RADIUS[key])
        if centre is not None and _is_int(radius) and 0 <= radius <= 8:
            out = hexgrid.disk(centre[0], centre[1], radius)
            plots_in(reply, out)
            return _dedupe(out)
    out: list[list[int]] = []
    plots_in(reply, out)
    return _dedupe(out)


def action_rows(args: dict | None) -> list[tuple[str, dict]]:
    """The `(tool, args)` of every well-formed row under `actions` (do, finish_turn)."""
    if not isinstance(args, dict):
        return []
    return [(a["tool"], a["args"]) for a in args.get("actions") or []
            if isinstance(a, dict) and isinstance(a.get("tool"), str) and isinstance(a.get("args"), dict)]


def intent_plots(args: dict | None) -> list[list[int]]:
    """The plots the arguments named: x/y, dest_x/dest_y, order steps, compare's plots, the rows of a batch."""
    if not isinstance(args, dict):
        return []
    out: list[list[int]] = []
    if _is_int(args.get("x")) and _is_int(args.get("y")):
        out.append([args["x"], args["y"]])
    if _is_int(args.get("dest_x")) and _is_int(args.get("dest_y")):
        out.append([args["dest_x"], args["dest_y"]])
    for p in args.get("plots") or []:
        if isinstance(p, list) and len(p) == 2 and _is_int(p[0]) and _is_int(p[1]):
            out.append([p[0], p[1]])
    for key in ("steps", "target", "done_when", "interrupt"):
        if key in args:
            plots_in(args[key], out)
    for _name, a in action_rows(args):
        out.extend(intent_plots(a))
    return _dedupe(out)


def refs(args: dict | None) -> dict:
    """The unit / city ids the arguments named (a batch's actions included), for the spectator to place."""
    if not isinstance(args, dict):
        return {}
    out: dict[str, list[int]] = {}

    def take(k: str, v: Any) -> None:
        if k.endswith("s") and isinstance(v, list):
            vals = [i for i in v if _is_int(i)]
            k = k[:-1]
        elif _is_int(v):
            vals = [v]
        else:
            return
        if vals:
            out.setdefault(k, []).extend(i for i in vals if i not in out.get(k, []))

    for k in ID_KEYS:
        if k in args:
            take(k, args[k])
    for _name, a in action_rows(args):
        for k in ID_KEYS:
            if k in a:
                take(k, a[k])
    return out


def compact_args(args: dict | None) -> str | None:
    if not args:
        return None
    s = json.dumps(args, separators=(",", ":"), ensure_ascii=False, default=str)
    return s if len(s) <= ARGS_CHARS else s[:ARGS_CHARS - 1] + "…"


def excerpt(kind: str, ok: bool, text: str) -> str | None:
    """A write's or a refusal's reply, cut short. Reads are large and their content is what `seen` describes."""
    if kind == "read" and ok:
        return None
    t = text.strip()
    if not t:
        return None
    return t if len(t) <= EXCERPT_CHARS else t[:EXCERPT_CHARS - 1] + "…"


def fields(key: Key, kind: str, args: dict | None, parsed: Any, ok: bool, text: str) -> dict:
    """Everything this module adds to a ledger row, from the call's key and the old handler's arguments (the
    ledger resolves a new call to them first: ids and plots sit under their old names there)."""
    r: dict[str, Any] = {"scope": scope(key, kind)}
    e = excerpt(kind, ok, text)
    if e:
        r["excerpt"] = e
    seen = seen_plots(key, args, parsed)
    if seen:
        r["seen"] = seen[:SEEN_MAX]
        if len(seen) > SEEN_MAX:
            r["seen_more"] = len(seen) - SEEN_MAX
    intent = intent_plots(args)
    if intent:
        r["intent"] = intent
    rf = refs(args)
    if rf:
        r["refs"] = rf
    return r
