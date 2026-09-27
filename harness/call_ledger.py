"""An opt-in ledger of MCP tool calls: what a model spent per turn (GitLab #36, "how to judge progress").

With `CIV5_CALL_LOG=/path/calls.jsonl` in the server's environment, every tool call appends one JSON row: time,
seat, tool, `kind` (read / write / wait), the reply's bytes, tuner trips, seconds, whether the answer was a refusal
(`ok: false`) with its `err` cut short, and the `turn` when the answer names one. The file is the operator's, on
the operator's disk; nothing here is returned to any seat. `scripts/ledger_report.py` groups the rows into turns
and keeps waiting (the AIs' turns, the bridge) apart from inspection.

Pure apart from `append`; no game reads of its own, so logging costs no trips.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

# The calls that sleep until the seat's turn comes back: their seconds are AI-turn and bridge time, not the
# model's inspection overhead, and each one closes a turn in the report.
WAIT_TOOLS = frozenset({"end_turn", "finish_turn", "wait_for_my_turn"})

# Reads: they change nothing in the game or the notebook. Everything else (orders, answers to screens, notes,
# assignments, orders) is a write. `do` is a write: it batches orders.
READ_TOOLS = frozenset({
    "turn_status", "briefing", "turn_digest", "todo_actions", "recall", "assignments", "orders", "reference",
    "notification_log", "overview", "units", "cities", "city_screen", "map_window", "known_world", "map_index",
    "revealed_map", "explore_frontier", "tactical_view", "compare", "diplomacy", "relationship", "players",
    "discussion", "purchase_cost", "available_trade_routes", "trade_routes", "available_research", "tech_tree",
    "available_production", "available_unit_actions", "unit_mission_targets", "available_policies",
    "available_beliefs", "available_city_strikes", "available_spy_cities", "great_person_progress",
    "demographics", "culture_works", "culture_overview", "maya_options", "archaeology_options",
    "domination_progress", "wonder_overview", "espionage_intrigue", "city_state_bonuses", "city_state_actions",
    "city_state_gifts", "gift_unit_options", "gift_tile_improvement_options", "unit_home_options", "spies",
    "league_status", "incoming_deal", "current_deals", "trade_catalog", "generic_popup", "spaceship_status",
    "goody_hut_options", "faith_great_person_options", "free_great_person_options", "religion_overview",
    "war_consequences", "city_capture_options", "steal_tech_options",
})

ERR_CHARS = 120


def path() -> str | None:
    p = os.environ.get("CIV5_CALL_LOG", "").strip()
    return p or None


def kind(tool: str) -> str:
    if tool in WAIT_TOOLS:
        return "wait"
    return "read" if tool in READ_TOOLS else "write"


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


def row(tool: str, seat: Any, text: str, seconds: float, trips: int | None, now: float | None = None) -> dict:
    """One ledger row from a finished call. `ok` is False only for a reply that says so (`{"ok": false}`)."""
    r: dict[str, Any] = {"t": round(now if now is not None else time.time(), 3), "seat": seat, "tool": tool,
                         "kind": kind(tool), "bytes": len(text.encode("utf-8")), "seconds": round(seconds, 3),
                         "trips": trips, "ok": True}
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        if parsed.get("ok") is False:
            r["ok"] = False
            err = parsed.get("err") or parsed.get("error") or ""
            r["err"] = str(err)[:ERR_CHARS]
        turn = parsed.get("turn")
        if not isinstance(turn, int):
            status = parsed.get("status")
            turn = status.get("turn") if isinstance(status, dict) else None
        if isinstance(turn, int):
            r["turn"] = turn
    return r


def append(p: str, r: dict) -> None:
    """Best effort: a ledger that cannot be written never breaks the call it describes."""
    try:
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    except OSError:
        pass
