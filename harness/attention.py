"""Where one tool call's attention was: the plots its reply described (`seen`), the plots its arguments pointed at
(`intent`), the units and cities it named (`refs`) and how bright the visualization should paint it (`scope`).

Computed from the arguments and the parsed reply the ledger already has, so it costs no trips; the spectator
(harness/spectator) and the page (web/viz) draw it. docs/VISUALIZATION.md says what each field means on screen.

Plots are `[x, y]` pairs, never wrapped: a tactical_view disk near the seam may name x = -1 or x = width, and the
page wraps them, because only the page knows the map width. `seen` is cut at SEEN_MAX with `seen_more` counting
the rest (a known_world reply after Satellites names every plot of the map).
"""
from __future__ import annotations

import json
from typing import Any

from . import hexgrid

# Targeted reads: the model chose a spot and looked at it. Full-brightness pulse.
FOCUS_TOOLS = frozenset({
    "tactical_view", "map_window", "city_screen", "unit_mission_targets", "explore_frontier", "compare",
    "available_unit_actions", "purchase_cost", "city_capture_options", "available_city_strikes",
    "gift_tile_improvement_options", "archaeology_options", "unit_home_options",
})
# Every other read is a broad scan (dim pulse); every write is an act (stays painted).

SEEN_MAX = 4096
ARGS_CHARS = 1200
EXCERPT_CHARS = 240
DEFAULT_RADIUS = {"tactical_view": 2, "map_window": 3}
ID_KEYS = ("unit_id", "city_id", "unit_ids", "city_ids", "spy_id", "assignment_id", "order_id")


def scope(tool: str, kind: str) -> str:
    if kind == "write":
        return "act"
    if kind == "wait":
        return "wait"
    return "focus" if tool in FOCUS_TOOLS else "broad"


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


def seen_plots(tool: str, args: dict | None, reply: Any) -> list[list[int]]:
    """The plots a reply handed the model. Special shapes first, the generic x/y walk for everything else."""
    args = args or {}
    if isinstance(reply, list):                       # units / cities answer with a bare list of rows
        out: list[list[int]] = []
        plots_in(reply, out)
        return _dedupe(out)
    if not isinstance(reply, dict) or reply.get("ok") is False:
        return []
    if tool == "revealed_map":
        return _dedupe(_grid_plots(reply))
    if tool in DEFAULT_RADIUS:
        centre = None
        if tool == "tactical_view":
            u = reply.get("unit")
            if isinstance(u, dict) and _is_int(u.get("x")) and _is_int(u.get("y")):
                centre = (u["x"], u["y"])
        elif _is_int(args.get("x")) and _is_int(args.get("y")):
            centre = (args["x"], args["y"])
        radius = args.get("radius", DEFAULT_RADIUS[tool])
        if centre is not None and _is_int(radius) and 0 <= radius <= 8:
            out = hexgrid.disk(centre[0], centre[1], radius)
            plots_in(reply, out)
            return _dedupe(out)
    out: list[list[int]] = []
    plots_in(reply, out)
    return _dedupe(out)


def intent_plots(tool: str, args: dict | None) -> list[list[int]]:
    """The plots the arguments named: x/y, dest_x/dest_y, order steps, compare's plots, the actions of a batch."""
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
    if tool == "do":
        for action in args.get("actions") or []:
            if isinstance(action, dict):
                out.extend(intent_plots(str(action.get("tool", "")), action.get("args")))
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
    for action in args.get("actions") or []:
        if isinstance(action, dict) and isinstance(action.get("args"), dict):
            for k in ID_KEYS:
                if k in action["args"]:
                    take(k, action["args"][k])
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


def fields(tool: str, kind: str, args: dict | None, parsed: Any, ok: bool, text: str) -> dict:
    """Everything this module adds to a ledger row."""
    r: dict[str, Any] = {"scope": scope(tool, kind)}
    a = compact_args(args)
    if a:
        r["args"] = a
    e = excerpt(kind, ok, text)
    if e:
        r["excerpt"] = e
    seen = seen_plots(tool, args, parsed)
    if seen:
        r["seen"] = seen[:SEEN_MAX]
        if len(seen) > SEEN_MAX:
            r["seen_more"] = len(seen) - SEEN_MAX
    intent = intent_plots(tool, args)
    if intent:
        r["intent"] = intent
    rf = refs(args)
    if rf:
        r["refs"] = rf
    return r
