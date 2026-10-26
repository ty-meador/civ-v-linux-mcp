"""Stage 0 measurements of the tool surface (GitLab #44): the catalog by module, the zero-argument reads,
the eight shapes the count comes from, the listing's size, and each old name's row in the retirement map.

Everything is computed from the registered server (`harness.mcp_server`) and the retirement map, so the
baseline on #44 (145 tools, 35 zero-argument reads, the shape table) is reproducible rather than counted by
hand. `scripts/tool_survey.py` prints these as Markdown for `docs/measurements/`.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Callable

from harness import mcp_server as core
from harness.mcp_tools import MODULE_NAMES, SURFACE_MODULE
from harness.surface import classes
from harness.surface import retirement as R

#: Where Claude Code cuts a tool description (docs/LIMITATIONS.md, "Client cuts descriptions").
DESCRIPTION_CLIP = 2000
#: No tokenizer ships with the harness: bytes / 4 is the estimate the server's own comment uses.
BYTES_PER_TOKEN = 4


def tools() -> list:
    """Every tool of the old catalog, listed or retired, in the order a client lists them (the nine of stage 2a are
    `new_tools()` until #52 retires the old names)."""
    return [t for t in all_tools() if module_of(t) != SURFACE_MODULE]


def new_tools() -> list:
    """The nine tools of milestone 2.0.0 as registered (stage 2a, #48); `reference` is the old tool grown a `book`."""
    return [t for t in all_tools() if module_of(t) == SURFACE_MODULE or t.name == "reference"]


def all_tools() -> list:
    return list(core.mcp._tool_manager.list_tools()) + list(core.retired_tools().values())


def module_of(tool) -> str:
    return (getattr(tool.fn, "__module__", "") or "").rsplit(".", 1)[-1] or "other"


def is_zero_argument_read(tool) -> bool:
    """A read (the ledger's classification) that takes no argument at all."""
    return classes.of_handler(tool.name) in classes.READ and not tool.parameters.get("properties")


def by_module() -> list[dict]:
    """The baseline table of #44: tools and zero-argument reads per module, in listing order, plus a total."""
    per: dict[str, Counter] = {m: Counter() for m in MODULE_NAMES}
    for t in tools():
        c = per.setdefault(module_of(t), Counter())
        c["tools"] += 1
        c["zero_argument_reads"] += is_zero_argument_read(t)
    rows = [{"module": m, **c} for m, c in per.items() if c["tools"]]
    rows.append({"module": "total", "tools": sum(r["tools"] for r in rows),
                 "zero_argument_reads": sum(r["zero_argument_reads"] for r in rows)})
    return rows


# --- the eight shapes of #44, as predicates over (old name, its row) -----------------------------------
LEADER_SCREEN = frozenset({"discussion", "incoming_deal", "respond_discussion", "accept_deal", "refuse_deal",
                           "dismiss_discussion"})


def _popup_pair(name: str, row: R.Row) -> bool:
    return row.tool in ("question", "answer") and name not in LEADER_SCREEN and name != "accept_friendship"


def _overview_screen(name: str, row: R.Row) -> bool:
    return row.tool == "inspect" and row.fixed["what"] in ("screen", "league", "spies")


def _map_grain(name: str, row: R.Row) -> bool:
    return (row.tool == "inspect" and row.fixed["what"] == "map") or name in ("known_world", "tactical_view")


def _unit_can_do(name: str, row: R.Row) -> bool:
    return row.key in (("inspect:units", "actions"), ("inspect:unit", "actions"), ("inspect:unit", "targets"),
                       ("inspect:unit", "home"))


def _city_state(name: str, row: R.Row) -> bool:
    return row.fixed.get("what") == "city_state" or row.fixed.get("to") == "city_state"


def _trade_table(name: str, row: R.Row) -> bool:
    return name in LEADER_SCREEN


def _city_write(name: str, row: R.Row) -> bool:
    return row.fixed.get("to") == "city"


def _empire_decision(name: str, row: R.Row) -> bool:
    return row.fixed.get("to") == "empire"


SHAPES: tuple[tuple[str, Callable[[str, R.Row], bool]], ...] = (
    ("a popup's read + its answer, one pair per popup kind", _popup_pair),
    ("one zero-argument read per overview screen", _overview_screen),
    ("reads of the same map at different grains", _map_grain),
    ('reads of "what can this unit do"', _unit_can_do),
    ("city-state screen, one tool per button and per tooltip", _city_state),
    ("the trade table's buttons, one tool each", _trade_table),
    ("one write per city-screen control", _city_write),
    ("one write per empire-level decision", _empire_decision),
)


def shapes(names: list[str] | None = None) -> list[dict]:
    """The shape table: label, count, the names behind it. A name belongs to its first matching shape."""
    names = names if names is not None else [t.name for t in tools()]
    taken: set[str] = set()
    out = []
    for label, pred in SHAPES:
        hit = [n for n in names if n in R.RETIRED and n not in taken and pred(n, R.RETIRED[n])]
        taken.update(hit)
        out.append({"shape": label, "count": len(hit), "names": hit})
    out.append({"shape": "the rest (the loop, the notebook, the session, single reads and writes)",
                "count": len([n for n in names if n not in taken]), "names": [n for n in names if n not in taken]})
    return out


# --- the mapping and the count by new tool -------------------------------------------------------------
def mapping() -> list[dict]:
    """Every old name in listing order with its module, its `(tool, action)` / `(what, view)` key and the
    `renamed` string it will carry."""
    out = []
    for t in tools():
        row = R.RETIRED.get(t.name)
        out.append({"old": t.name, "module": module_of(t),
                    "key": " / ".join(row.key) if row else "(unmapped)",
                    "new": row.render() if row else "", "note": row.note if row else ""})
    return out


def by_new_tool() -> list[dict]:
    """How many old names each of the nine tools replaces (the "Replaces" column of #59)."""
    c = Counter(R.RETIRED[t.name].tool for t in tools() if t.name in R.RETIRED)
    return [{"tool": name, "replaces": c.get(name, 0)} for name in ("turn", "inspect", "order", "question",
                                                                     "answer", "notebook", "batch", "session",
                                                                     "reference")]


# --- the listing's size --------------------------------------------------------------------------------
def wire_listing(names: set[str] | None = None, clip: int | None = None) -> str:
    """The `tools/list` reply as a client receives it (name, description, inputSchema; compact JSON),
    optionally only the named tools and with each description cut at `clip` characters."""
    rows = [{"name": t.name, "description": (t.description or "")[:clip] if clip else (t.description or ""),
             "inputSchema": t.parameters}
            for t in tools() if names is None or t.name in names]
    return json.dumps({"tools": rows}, separators=(",", ":"))


def listing_sizes() -> list[dict]:
    """The full listing: every tool a client is shown. A client that cuts descriptions at DESCRIPTION_CLIP sees
    the same bytes while `longest_description()` stays under it. (The `--tools compact` listing measured here
    until stage 2d retired it: 33 KB against the full 110 KB of 2026-10-25.)"""
    text = wire_listing()
    n = len(core.mcp._tool_manager.list_tools())
    return [{"listing": "full", "tools": n, "bytes": len(text.encode()),
             "approx_tokens": len(text.encode()) // BYTES_PER_TOKEN}]


def longest_description() -> dict:
    """The longest tool description against the clip Claude Code applies."""
    t = max(tools(), key=lambda t: len(t.description or ""))
    return {"tool": t.name, "chars": len(t.description or ""), "clip": DESCRIPTION_CLIP}
