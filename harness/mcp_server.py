"""MCP server: lets an LLM play Civilization V through the harness.

Run (stdio):  .venv/bin/python -m harness.mcp_server --seat 1
Requires: the game running with the shim (scripts/launch_civ5.sh) and tunerd (python -m harness.tunerd).

Tool design notes
- Everything returns compact JSON text; the LLM sees exactly what the game's Lua reports.
- `turn_digest` is the "what happened since my last turn" feed (recorded Events + notifications).
- Actions never block on animations; call `turn_status` to observe results.
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import sys
from typing import Any

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP

from .client import TunerdError
from .game import Game

mcp = FastMCP("civ5", instructions=(
    "You are playing Sid Meier's Civilization V as one player in a hotseat game with humans and AI. "
    "Use wait_for_my_turn first, then read turn_digest/overview/units/cities, act with the action tools, "
    "and finish with end_turn. Coordinates are hex plot (x, y). Player ids: yours is given by overview."))

_game: Game | None = None


def game() -> Game:
    global _game
    if _game is None:
        _game = Game(os.environ.get("CIV5_TUNERD_SOCK"))
        _game.seat = int(os.environ.get("CIV5_SEAT", "1"))
    return _game


def J(v: Any) -> str:
    return json.dumps(v, separators=(",", ":"), ensure_ascii=False)


def guarded(fn):
    @functools.wraps(fn)
    def wrapper(*a, **k):
        try:
            return fn(*a, **k)
        except (TunerdError, TimeoutError, ConnectionError) as e:
            return J({"error": str(e)})
    return wrapper


# ------------------------------------------------------------------ observation
@mcp.tool()
@guarded
def turn_status() -> str:
    """Whose turn it is, current turn number, whether it is my turn, and what blocks ending it."""
    return J(game().turn_state())


@mcp.tool()
@guarded
def wait_for_my_turn(timeout_seconds: int = 90) -> str:
    """Wait (up to timeout_seconds) until it is my turn, dismiss the hotseat hand-off screen, return turn_status. Call again if it times out."""
    return J(game().wait_for_my_turn(timeout=timeout_seconds))


@mcp.tool()
@guarded
def overview() -> str:
    """My empire at a glance: gold, science, culture, happiness, research, era, counts, turn/year."""
    return J(game().summary())


@mcp.tool()
@guarded
def turn_digest() -> str:
    """Everything recorded since my last call: combats, cities founded/lost, wars, chat, notifications, alerts."""
    g = game()
    return J({"events": g.events_since_last(), "notifications": g.notifications()})


@mcp.tool()
@guarded
def units() -> str:
    """My units with position, moves left, hp, strength, and whether they still need orders."""
    return J(game().units())


@mcp.tool()
@guarded
def cities() -> str:
    """My cities: population, yields, current production and turns left, growth, happiness."""
    return J(game().cities())


@mcp.tool()
@guarded
def map_window(x: int, y: int, radius: int = 3) -> str:
    """Revealed plots within `radius` of (x, y): terrain, hills/river, feature, resource, improvement, owner, city, visible units."""
    return J(game().plots_around(x, y, radius))


@mcp.tool()
@guarded
def diplomacy() -> str:
    """Known major civs: met, at war, their approach toward me, score, cities."""
    return J(game().diplomacy())


@mcp.tool()
@guarded
def lua(code: str) -> str:
    """Escape hatch: run Lua in the InGame context and return printed output. Use the Civ V modding API (Players[i], Game, Map...)."""
    return J(game().lua("InGame", code, timeout=20))


# ------------------------------------------------------------------ actions
@mcp.tool()
@guarded
def move_unit(unit_id: int, x: int, y: int) -> str:
    """Order one of my units to move to plot (x, y) (multi-turn paths allowed, like a right-click)."""
    return J(game().move_unit(unit_id, x, y))


@mcp.tool()
@guarded
def unit_mission(unit_id: int, mission: str, x: int = -1, y: int = -1) -> str:
    """Give a unit a mission: MISSION_FOUND (settle here), MISSION_FORTIFY, MISSION_SLEEP, MISSION_SKIP, MISSION_HEAL,
    MISSION_ALERT, MISSION_BUILD (needs data), MISSION_RANGE_ATTACK (x,y), MISSION_PILLAGE, MISSION_EMBARK/DISEMBARK..."""
    return J(game().unit_mission(unit_id, mission, x, y))


@mcp.tool()
@guarded
def set_production(city_id: int, item: str) -> str:
    """Set a city's production. item like UNIT_WARRIOR, UNIT_SETTLER, BUILDING_MONUMENT, PROJECT_..., PROCESS_WEALTH."""
    order = {"UNIT": "ORDER_TRAIN", "BUILDING": "ORDER_CONSTRUCT", "PROJECT": "ORDER_CREATE", "PROCESS": "ORDER_MAINTAIN"}[item.split("_", 1)[0]]
    return J(game().set_production(city_id, order, item))


@mcp.tool()
@guarded
def set_research(tech: str) -> str:
    """Choose current research, e.g. TECH_POTTERY, TECH_MINING, TECH_BRONZE_WORKING."""
    return J(game().set_research(tech))


@mcp.tool()
@guarded
def end_turn() -> str:
    """End my turn. If something blocks it (unit needs orders, research/production choice), turn_status shows it."""
    return J(game().end_turn())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seat", type=int, default=int(os.environ.get("CIV5_SEAT", "1")))
    a = ap.parse_args(argv)
    os.environ["CIV5_SEAT"] = str(a.seat)
    mcp.run()


if __name__ == "__main__":
    main()
