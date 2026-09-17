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
from .action_lock import action_lock
from .client import DEFAULT_SOCK

mcp = FastMCP("civ5", instructions=(
    "You are playing Sid Meier's Civilization V as one player in a multiplayer game (hotseat or LAN) with humans and AI. "
    "Use wait_for_my_turn first, then known_world for everything this seat can see or has discovered "
    "(fogged tiles are included but marked vis=false and omit live occupants), act with the action tools, "
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


MENU_TOOLS = {"turn_status", "load_save", "load_latest"}


def guarded(fn):
    @functools.wraps(fn)
    def wrapper(*a, **k):
        try:
            with action_lock(os.environ.get("CIV5_TUNERD_SOCK") or DEFAULT_SOCK):
                g = game()
                # Front-end tools: usable from the main menu, where there is no InGame state at all.
                if fn.__name__ in MENU_TOOLS:
                    if g.has_state("InGame") and fn.__name__ != "turn_status":
                        return J({"ok": False, "err": "a game is already loaded; these tools only work from the main menu",
                                  "turn": g.turn_state().get("turn")})
                    return fn(*a, **k)
                if fn.__name__ != "wait_for_my_turn":
                    ts = g.turn_state()
                    if ts["active_player"] != g.seat:
                        return J({"ok": False, "err": "this seat is not active", "active_player": ts["active_player"]})
                    reads = {"overview", "turn_digest", "discussion", "relationship", "units", "cities", "map_window", "known_world", "diplomacy", "players",
                             "purchase_cost", "available_trade_routes", "available_research", "available_production",
                             "available_unit_actions", "spies", "available_spy_cities", "league_status",
                             "incoming_deal", "available_city_strikes", "trade_catalog", "city_state_gifts"}
                    responses = {"dismiss_discussion", "accept_friendship", "diplo_event", "make_peace",
                                 "accept_deal", "refuse_deal", "respond_discussion"}
                    if fn.__name__ not in reads | responses:
                        if ts["paused"] or ts["processing"] or not ts["my_turn"]:
                            return J({"ok": False, "err": "game is paused, processing, or waiting; use wait_for_my_turn"})
                        if g.discussion_pending():
                            return J({"ok": False, "err": "diplomatic decision pending"})
                        required = {"found_pantheon": "ENDTURN_BLOCKING_FOUND_PANTHEON",
                                    "found_religion": "ENDTURN_BLOCKING_FOUND_RELIGION",
                                    "enhance_religion": "ENDTURN_BLOCKING_ENHANCE_RELIGION"}
                        if fn.__name__ in required and ts["blocking_name"] != required[fn.__name__]:
                            return J({"ok": False, "err": "this religious choice is not pending"})
                        if ts.get("pending_popups"):
                            g.dismiss_pending_popups()
                            pending = g.turn_state().get("pending_popups", [])
                            resolutions = {
                                "set_research": {"BUTTONPOPUP_CHOOSETECH", "BUTTONPOPUP_TECH_TREE"},
                                "set_production": {"BUTTONPOPUP_CHOOSEPRODUCTION"},
                                "choose_policy": {"BUTTONPOPUP_CHOOSEPOLICY"},
                                "unlock_policy_branch": {"BUTTONPOPUP_CHOOSEPOLICY"},
                                "choose_promotion": {"BUTTONPOPUP_CHOOSEUNITPROMOTION"},
                                "found_pantheon": {"BUTTONPOPUP_FOUND_PANTHEON"},
                                "found_religion": {"BUTTONPOPUP_FOUND_RELIGION"},
                                "enhance_religion": {"BUTTONPOPUP_ENHANCE_RELIGION"},
                            }
                            allowed = resolutions.get(fn.__name__, set())
                            unresolved = [p for p in pending if p["name"] not in allowed]
                            if unresolved:
                                return J({"ok": False, "err": "popup needs a decision", "pending_popups": unresolved})
                return fn(*a, **k)
        except (TunerdError, TimeoutError, OSError, ValueError) as e:
            return J({"ok": False, "err": str(e)})
    return wrapper


# ------------------------------------------------------------------ observation
@mcp.tool()
@guarded
def turn_status() -> str:
    """Whose turn it is, current turn number, whether it is my turn, what blocks ending it,
    and whether a greeting/discussion/tech/great-person screen is up (those are not in pending_popups).
    From the main menu (no game loaded) reports {"ingame": false, "screen": ...} instead: use load_latest
    / load_save to get back into a game."""
    g = game()
    if not g.has_state("InGame"):
        return J({"ok": True, "ingame": False, "screen": g.front_end_screen()})
    return J(g.turn_state())


@mcp.tool()
@guarded
def wait_for_my_turn(timeout_seconds: int = 90) -> str:
    """Wait (up to timeout_seconds) until it is my turn (hotseat: dismisses the hand-off screen; LAN: waits for the new turn), return turn_status. Call again if it times out.

    Returns early with discussion_pending=true if an AI leader has opened a negotiation/demand/trade-offer
    screen -- call incoming_deal() to read terms, accept_deal()/refuse_deal() to resolve a trade table,
    or dismiss_discussion() to leave without agreeing, then call this again.
    Returns early with tech_popup_pending=true when a technology must be chosen (research still unset)."""
    return J(game().wait_for_my_turn(timeout=timeout_seconds))


@mcp.tool()
@guarded
def dismiss_discussion() -> str:
    """Leave an AI leader's negotiation/demand/trade-offer screen (see wait_for_my_turn's discussion_pending)
    without agreeing to anything. For a trade already on the table, prefer incoming_deal + refuse_deal."""
    return J(game().dismiss_discussion())


@mcp.tool()
@guarded
def discussion() -> str:
    """What the open leader screen says: the leader, their mood, their speech, the response buttons
    (id + text) and, on a trade screen, the deal on the table. Call this whenever turn_status or
    wait_for_my_turn reports discussion_pending, then answer with respond_discussion(button_id),
    accept_deal / refuse_deal (trade screen), or dismiss_discussion (plain acknowledgement, no buttons)."""
    return J(game().discussion())


@mcp.tool()
@guarded
def respond_discussion(button_id: int) -> str:
    """Press one of the response buttons listed by discussion() (1-4). Use this for AI demands,
    warnings, requests and post-deal remarks that offer choices such as apologise / dismiss / threaten."""
    return J(game().respond_discussion(button_id))


@mcp.tool()
@guarded
def incoming_deal() -> str:
    """Read the current trade table (scratch deal): items already offered, who they are from.
    Empty items means no deal is on the table. Does not mutate the deal or open the trade screen."""
    return J(game().incoming_deal())


@mcp.tool()
@guarded
def accept_deal() -> str:
    """Accept an incoming trade already on the table (see incoming_deal). Does not construct a new deal.
    propose_deal is intentionally not exposed -- building deals with Add* has crashed the game."""
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
    resources). Read-only: does not construct or send a deal. City-states: use city_state_gifts."""
    return J(game().trade_catalog(player_id))


@mcp.tool()
@guarded
def city_state_gifts(player_id: int) -> str:
    """Gold gift tiers and friendship for a met city-state. See minor_gold_gift to actually gift."""
    return J(game().city_state_gifts(player_id))


@mcp.tool()
@guarded
def minor_gold_gift(player_id: int, amount: int) -> str:
    """Gift gold to a city-state. `amount` must be city_state_gifts' small, medium, or large tier."""
    return J(game().minor_gold_gift(player_id, amount))


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
    """Revealed plots within `radius` of (x, y). vis=true is in sight now; vis=false is discovered but fogged (no live units/owners). Prefer known_world for the full discovered map."""
    return J(game().plots_around(x, y, radius))


@mcp.tool()
@guarded
def known_world() -> str:
    """Everything this seat knows: empire, own units/cities, met civs and city-states, notifications, and every revealed plot. Fogged plots have vis=false and omit live occupants; unrevealed tiles are absent."""
    return J(game().known_world())


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
    denouncements, city-state alliances) and the recent messages they sent us. discussion() includes
    this for the leader on screen; call it directly before proposing or answering anything."""
    return J(game().relationship(player_id))


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
def available_research() -> str:
    """Techs I can research right now (prereqs met). `current` marks the one already selected."""
    return J(game().available_research())


@mcp.tool()
@guarded
def available_production(city_id: int) -> str:
    """What this city can produce right now: units, buildings, projects, processes, with turns."""
    return J(game().available_production(city_id))


@mcp.tool()
@guarded
def available_unit_actions(unit_id: int) -> str:
    """Legal unit-panel actions for this unit right now (missions, tile builds, commands, promotions).
    Call this before unit_mission. Move-to is a separate tool (move_unit). Does not select the unit
    or pan the camera."""
    return J(game().available_unit_actions(unit_id))


@mcp.tool()
@guarded
def available_trade_routes(unit_id: int) -> str:
    """Valid trade-route destinations for a specific trade unit (caravan/cargo ship) right now, with the
    trade_type to pass into establish_trade_route."""
    return J(game().available_trade_routes(unit_id))


@mcp.tool()
@guarded
def establish_trade_route(unit_id: int, dest_x: int, dest_y: int, trade_type: int) -> str:
    """Send a caravan/cargo ship to establish a trade route (see available_trade_routes(unit_id) for valid dest_x/dest_y/trade_type)."""
    return J(game().establish_trade_route(unit_id, dest_x, dest_y, trade_type))


@mcp.tool()
@guarded
def plunder_trade_route(unit_id: int) -> str:
    """Order a military unit standing on an enemy trade route to plunder it."""
    return J(game().plunder_trade_route(unit_id))


@mcp.tool()
@guarded
def spies() -> str:
    """My spies: agent_id, name, rank, state, where stationed, and can_stage_coup. See
    available_spy_cities/move_spy/stage_coup for actions."""
    return J(game().spies())


@mcp.tool()
@guarded
def available_spy_cities(agent_id: int) -> str:
    """Cities a given spy (agent_id, from spies()) could be sent to right now, with success `potential` --
    my own cities (counter-intel) and others' (steal tech / set up a future coup). Feeds move_spy."""
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
    there (spies()'s can_stage_coup)."""
    return J(game().stage_coup(agent_id))


@mcp.tool()
@guarded
def league_status() -> str:
    """Read-only: World Congress state -- resolutions I can propose (between sessions) or vote on (during a
    session). See league_propose_enact/league_propose_repeal/league_cast_votes."""
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
    Leftover votes are automatically cast as abstain."""
    return J(game().league_cast_votes(votes))


# propose_deal is intentionally NOT exposed as a tool: Game.propose_deal() (harness/game.py) crashed the
# game process THREE separate times across a day of live testing -- see docs/NOTES.md "Phase 3a" and its
# two follow-up entries. A missing deal:IsPossibleToTradeItem(...) validation gate and a PvP-only item
# (DECLARATION_OF_FRIENDSHIP) were found and fixed (runtime.lua v11), but a third live crash proved the
# deeper problem: deal:AddPeaceTreaty() crashed the game outright even with a fully valid, correctly-built
# deal, suggesting the native deal-mutation API needs real trade-screen UI state that a bare tuner exec
# doesn't have. Do not re-add this tool -- this needs a different approach (a lower-level Network.Send*
# equivalent, if one exists), not another patch to this call pattern.


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


@mcp.tool()
@guarded
def choose_promotion(unit_id: int, promotion: str) -> str:
    """Choose an earned promotion, using its PROMOTION_ name."""
    return J(game().choose_promotion(unit_id, promotion))


# ------------------------------------------------------------------ actions
@mcp.tool()
@guarded
def move_unit(unit_id: int, x: int, y: int) -> str:
    """Order one of my units to move to plot (x, y) (multi-turn paths allowed, like a right-click).
    Does not select the unit or pan/flip the camera."""
    return J(game().move_unit(unit_id, x, y))


@mcp.tool()
@guarded
def unit_mission(unit_id: int, mission: str, x: int = -1, y: int = -1, build: str = "") -> str:
    """Give a unit a mission: MISSION_FOUND (settle here), MISSION_FORTIFY, MISSION_SLEEP, MISSION_SKIP, MISSION_HEAL,
    MISSION_ALERT, MISSION_RANGE_ATTACK (x,y), MISSION_PILLAGE, MISSION_EMBARK/DISEMBARK...
    MISSION_BUILD: pass the improvement in `build`, e.g. build="BUILD_FARM" (do NOT put it in x/y --
    those are for movement-shaped missions). Builds on the unit's own tile.
    Does not select the unit or pan/flip the camera."""
    return J(game().unit_mission(unit_id, mission, x, y, build=(build or None)))


@mcp.tool()
@guarded
def set_production(city_id: int, item: str) -> str:
    """Set a city's production. item like UNIT_WARRIOR, UNIT_SETTLER, BUILDING_MONUMENT, PROJECT_..., PROCESS_WEALTH."""
    order = {"UNIT": "ORDER_TRAIN", "BUILDING": "ORDER_CONSTRUCT", "PROJECT": "ORDER_CREATE", "PROCESS": "ORDER_MAINTAIN"}[item.split("_", 1)[0]]
    return J(game().set_production(city_id, order, item))


@mcp.tool()
@guarded
def purchase_cost(city_id: int, item: str, yield_type: str = "GOLD") -> str:
    """Read-only: cost to rush-buy item (UNIT_.../BUILDING_...) with gold or faith right now, and whether
    it's actually purchasable. Wonders (built via a BUILDING_* item too) are never purchasable in vanilla
    BNW -- can_purchase will read false. Check this before purchase_production."""
    order = {"UNIT": "ORDER_TRAIN", "BUILDING": "ORDER_CONSTRUCT"}[item.split("_", 1)[0]]
    return J(game().purchase_cost(city_id, order, item, yield_type))


@mcp.tool()
@guarded
def purchase_production(city_id: int, item: str, yield_type: str = "GOLD") -> str:
    """Rush-buy a unit or building (item like UNIT_WARRIOR, BUILDING_MARKET) with gold or faith. See
    purchase_cost for price/affordability first. Wonders can never be purchased this way."""
    order = {"UNIT": "ORDER_TRAIN", "BUILDING": "ORDER_CONSTRUCT"}[item.split("_", 1)[0]]
    return J(game().purchase_production(city_id, order, item, yield_type))


@mcp.tool()
@guarded
def set_research(tech: str) -> str:
    """Choose current research, e.g. TECH_POTTERY, TECH_MINING, TECH_BRONZE_WORKING."""
    return J(game().set_research(tech))


@mcp.tool()
@guarded
def quick_save() -> str:
    """Save the game right now (same as the in-game Quick Save / F5). Cheap -- call it after anything
    costly (founding a city, a policy/research choice, before combat), not just periodically, since a
    crash loses everything back to the engine's last autosave otherwise."""
    return J(game().quick_save())


@mcp.tool()
@guarded
def load_save(filename: str) -> str:
    """Load a save from the main menu by its bare name, no path or .Civ5Save extension (e.g. "QuickSave",
    or "Sejong_0180 AD-1200" for a manual save). Only works from a fresh main-menu state, not mid-game."""
    return J(game().load_save(filename))


@mcp.tool()
@guarded
def load_latest() -> str:
    """Crash-recovery: load whichever save (quicksave OR autosave) has the newest filesystem mtime,
    regardless of name. Prefer this over load_save("QuickSave") when resuming after a crash -- an
    autosave made during play can be newer than the last explicit quicksave, and load_save only checks
    quick/manual saves before ever considering autosaves. Only works from a fresh main-menu state."""
    return J(game().load_latest())


@mcp.tool()
@guarded
def end_turn(autosave: bool = True) -> str:
    """End my turn. If something blocks it (unit needs orders, research/production choice), turn_status shows it.
    Auto-quicksaves first by default (single-player only) -- cheap insurance against this game's frequent
    ambient crashes; pass autosave=False to skip."""
    return J(game().end_turn(autosave))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seat", default=os.environ.get("CIV5_SEAT", "auto"), help="player id, or 'auto' (network games: the local player)")
    a = ap.parse_args(argv)
    os.environ["CIV5_SEAT"] = str(a.seat)
    mcp.run()


if __name__ == "__main__":
    main()
