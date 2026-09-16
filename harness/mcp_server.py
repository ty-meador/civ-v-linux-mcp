"""MCP server: lets an LLM play Civilization V through the harness.

Run (stdio):  .venv/bin/python -m harness.mcp_server [--seat 1 | --seat auto]
Requires: the game running with the shim (scripts/launch_civ5.sh) and tunerd (python -m harness.tunerd).
Env: CIV5_TUNERD_SOCK selects the game instance (LAN mode: the LLM's own instance); CIV5_SEAT=auto (default) takes
the seat of that instance's local player in network games and seat 1 in hotseat.

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
    "You are playing Sid Meier's Civilization V as one player in a multiplayer game (hotseat or LAN) with humans and AI. "
    "Use wait_for_my_turn first, then read turn_digest/overview/units/cities, act with the action tools, "
    "and finish with end_turn. In LAN games the other humans play at the same time; after end_turn the game waits "
    "for them (turn_status shows turn_complete_sent). Coordinates are hex plot (x, y). Player ids: yours is given by overview. "
    "turn_digest includes leader_message events when an AI wants to talk (a demand, an offer, a war declaration); "
    "read diplomacy() for context and respond with declare_war/make_peace/denounce or the diplo_event escape hatch."))

_game: Game | None = None


def game() -> Game:
    global _game
    if _game is None:
        g = Game(os.environ.get("CIV5_TUNERD_SOCK"))
        seat = os.environ.get("CIV5_SEAT", "auto")
        if seat == "auto":
            # network game: this instance's local player; hotseat: seat must be given (defaults to 1)
            g.seat = 1
            try:
                if g.mode() != "hotseat":
                    g.detect_seat()
            except (TunerdError, TimeoutError):
                pass
        else:
            g.seat = int(seat)
        _game = g
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
    """Wait (up to timeout_seconds) until it is my turn (hotseat: dismisses the hand-off screen; LAN: waits for the new turn), return turn_status. Call again if it times out."""
    return J(game().wait_for_my_turn(timeout=timeout_seconds))


@mcp.tool()
@guarded
def players() -> str:
    """Network games: the human players, whether each is connected, has an active turn, and has ended their turn."""
    return J(game().net_players())


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
def declare_war(player_id: int) -> str:
    """Declare war on a civ I have met. Irreversible for a while (can't make peace again immediately). Bypasses the leader-head screen entirely."""
    return J(game().declare_war(player_id))


@mcp.tool()
@guarded
def make_peace(player_id: int) -> str:
    """Offer peace to a civ I'm at war with (they still have to accept; check diplomacy() next turn to see if it took)."""
    return J(game().make_peace(player_id))


@mcp.tool()
@guarded
def denounce(player_id: int) -> str:
    """Publicly denounce another civ. Worsens relations with them and their friends; cannot be undone."""
    return J(game().denounce(player_id))


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
def city_ranged_attack(city_id: int, x: int, y: int) -> str:
    """Ranged attack from a city onto plot (x, y). Only works if the city can currently range-strike (check turn_status/cities first)."""
    return J(game().city_ranged_attack(city_id, x, y))


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
def found_pantheon(belief: str) -> str:
    """Found a pantheon with the given belief, e.g. BELIEF_GOD_OF_THE_SEA. Check turn_status first: only
    valid when blocking_name is ENDTURN_BLOCKING_FOUND_PANTHEON."""
    return J(game().found_pantheon(belief))


@mcp.tool()
@guarded
def found_religion(religion: str, beliefs: list[str], city_x: int, city_y: int, custom_name: str = "") -> str:
    """Found a religion (RELIGION_...) with 1-4 beliefs, in the city at (city_x, city_y). Check turn_status
    first: only valid when blocking_name is ENDTURN_BLOCKING_FOUND_RELIGION."""
    return J(game().found_religion(religion, beliefs, city_x, city_y, custom_name))


@mcp.tool()
@guarded
def enhance_religion(religion: str, belief4: str, belief5: str, city_x: int, city_y: int, custom_name: str = "") -> str:
    """Enhance my founded religion with two more beliefs. Check turn_status first: only valid when
    blocking_name is ENDTURN_BLOCKING_ENHANCE_RELIGION."""
    return J(game().enhance_religion(religion, belief4, belief5, city_x, city_y, custom_name))


@mcp.tool()
@guarded
def available_trade_routes() -> str:
    """Valid trade-route destinations/types for my trade units right now."""
    return J(game().available_trade_routes())


@mcp.tool()
@guarded
def establish_trade_route(unit_id: int, dest_x: int, dest_y: int, trade_type: int) -> str:
    """Send a caravan/cargo ship to establish a trade route (see available_trade_routes for valid dest_x/dest_y/trade_type)."""
    return J(game().establish_trade_route(unit_id, dest_x, dest_y, trade_type))


@mcp.tool()
@guarded
def plunder_trade_route(unit_id: int) -> str:
    """Order a military unit standing on an enemy trade route to plunder it."""
    return J(game().plunder_trade_route(unit_id))


@mcp.tool()
@guarded
def spies() -> str:
    """Read-only: how many spies I have. No spy-action tools yet (unresearched API -- see docs/NOTES.md)."""
    return J(game().spies())


# propose_deal is intentionally NOT exposed as a tool: Game.propose_deal() (harness/game.py) crashed the
# game process outright on first live test (a single ALLOW_EMBASSY item, nothing exotic) -- see
# docs/NOTES.md. Do not re-add this tool until that's root-caused and confirmed fixed.


@mcp.tool()
@guarded
def lua(code: str) -> str:
    """Escape hatch: run Lua in the InGame context and return printed output. Use the Civ V modding API
    (Players[i], Game, Map...). CAUTION: an unfamiliar or unvalidated engine call here can crash the whole
    game process outright, not just error -- this has happened before. Check the dedicated tools above
    first (there are more than it looks like: city_ranged_attack, choose_policy, found_pantheon/religion,
    trade routes, diplo_event...) and docs/lua_command_patterns.md / docs/lua_api_surface.md before writing
    a new raw call, and prefer a validated read (does the object have the method? does a Can*() check pass?)
    before a write."""
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
    ap.add_argument("--seat", default=os.environ.get("CIV5_SEAT", "auto"), help="player id, or 'auto' (network games: the local player)")
    a = ap.parse_args(argv)
    os.environ["CIV5_SEAT"] = str(a.seat)
    mcp.run()


if __name__ == "__main__":
    main()
