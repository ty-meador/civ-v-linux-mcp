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
from .game import Game, plain_text
from .action_lock import action_lock
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

mcp = FastMCP("civ5", instructions=(
    "You are playing Sid Meier's Civilization V as one player (solo against the game's AI, or hotseat/LAN with humans). "
    "The turn loop: wait_for_my_turn (blocks until it is your turn OR an AI needs an answer mid-turn -- check "
    "discussion_pending / pending_popups in its result) -> turn_digest (what happened since last time) -> "
    "turn_status (todo: units needing orders, empty cities, promotions; blocking_name + blocking_hint say what "
    "still stops the turn from ending and which tool clears it) -> act -> end_turn. A refused action never "
    "crashes anything: its err says why and, where possible, what to do instead (e.g. nearest_revealed plots "
    "for a move into the unknown, target hp for attacks, the todo list for a blocked end_turn). "
    "Reads: overview (yields, gold, happiness, research), cities, units, map_window(x, y, radius) for terrain "
    "(fogged tiles are marked vis=false and omit live occupants), diplomacy for the civs you have met and "
    "their player_ids, relationship(player_id) for one civ in depth. Before acting on a unit call "
    "available_unit_actions (workers: nearby_builds), on a city available_production, for research "
    "available_research. Coordinates are hex plot (x, y). Your own player id is overview().id. "
    "Trade: trade_catalog -> negotiate_deal (ask, no commitment) -> propose_deal. "
    "turn_digest carries leader_message events when an AI approaches you (a demand, an offer, a war "
    "declaration); discussion() shows the buttons and respond_discussion answers. "
    "Save often: end_turn quick-saves by default; quick_save is also a tool."))

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
    v = plain_text(v)  # "[COLOR_POSITIVE_TEXT]Free Thought[ENDCOLOR][NEWLINE]+1 [ICON_RESEARCH] Science" -> readable
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
                    reads = {"overview", "turn_digest", "discussion", "relationship", "available_policies", "units", "cities", "map_window", "known_world", "diplomacy", "players",
                             "purchase_cost", "available_trade_routes", "available_research", "available_production",
                             "available_unit_actions", "spies", "available_spy_cities", "league_status",
                             "incoming_deal", "generic_popup", "spaceship_status", "culture_overview", "available_city_strikes", "trade_catalog", "city_state_gifts", "trade_routes", "explore_frontier", "goody_hut_options"}
                    responses = {"dismiss_discussion", "accept_friendship", "diplo_event", "make_peace",
                                 "accept_deal", "refuse_deal", "respond_discussion", "answer_popup"}
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
                                "choose_ideology": {"BUTTONPOPUP_CHOOSE_IDEOLOGY"},
                                "choose_promotion": {"BUTTONPOPUP_CHOOSEUNITPROMOTION"},
                                "found_pantheon": {"BUTTONPOPUP_FOUND_PANTHEON"},
                                "found_religion": {"BUTTONPOPUP_FOUND_RELIGION"},
                                "enhance_religion": {"BUTTONPOPUP_ENHANCE_RELIGION"},
                                "choose_goody_hut": {"BUTTONPOPUP_CHOOSE_GOODY_HUT_REWARD"},
                            }
                            allowed = resolutions.get(fn.__name__, set())
                            unresolved = [p for p in pending if p["name"] not in allowed]
                            if unresolved:
                                return J({"ok": False, "err": "popup needs a decision", "pending_popups": unresolved,
                                          "hint": "goody_hut_options() then choose_goody_hut(goody)"
                                          if unresolved[0]["name"] == "BUTTONPOPUP_CHOOSE_GOODY_HUT_REWARD" else
                                          "generic_popup() shows the question and buttons; answer_popup(button) presses one"})
                return fn(*a, **k)
        except (TunerdError, TimeoutError, OSError, ValueError) as e:
            return J({"ok": False, "err": str(e)})
        except Exception as e:  # noqa: BLE001 -- a harness bug must still come back as a readable JSON error,
            # not the MCP layer's bare "Error executing tool" (which hides the cause and, for the trade flow,
            # can leave a leader screen open that every later action then refuses on).
            return J({"ok": False, "err": f"harness error: {type(e).__name__}: {e}", "tool": fn.__name__})
    return wrapper


def lua_allowed() -> bool:
    """The raw `lua` tool is opt-in (env CIV5_ALLOW_LUA / --allow-lua), mirroring the HTTP server's per-seat allow_lua."""
    return os.environ.get("CIV5_ALLOW_LUA", "").strip().lower() in {"1", "true", "yes", "on"}


# ------------------------------------------------------------------ observation
@mcp.tool()
@guarded
def turn_status() -> str:
    """Whose turn it is, current turn number, whether it is my turn, what blocks ending it,
    and whether a greeting/discussion/tech/great-person screen is up (those are not in pending_popups).
    While a leader screen is up (leader_greeting_pending / discussion_pending) the game freezes blocking_name
    and todo: read it with discussion(), close a plain greeting with dismiss_discussion(), then look again.
    From the main menu (no game loaded) reports {"ingame": false, "screen": ...} instead: use load_latest
    / load_save to get back into a game."""
    g = game()
    if not g.has_state("InGame"):
        return J({"ok": True, "ingame": False, "screen": g.front_end_screen()})
    ts = g.turn_state()
    expiring = g.expiring_city_states()
    if expiring:
        ts["expiring_city_states"] = expiring  # ally/friend status lapsing within 3 turns
    return J(ts)


@mcp.tool()
@guarded
def wait_for_my_turn(timeout_seconds: int = 90) -> str:
    """Block until it is my turn (hotseat: dismisses the hand-off screen; LAN/solo: waits for the AIs to finish),
    then return turn_status. On timeout it returns the current status with my_turn=false -- call it again;
    keep timeout_seconds under your client's tool-call limit. Also sweeps informational popups.

    Returns early with discussion_pending=true when an AI leader wants an answer mid-turn: discussion()
    shows what they said and the buttons, respond_discussion(button_id) answers; for a trade offer on the
    table incoming_deal() reads the terms and accept_deal()/refuse_deal() resolve it; dismiss_discussion()
    leaves without agreeing. Then call this again.
    Returns early with tech_popup_pending=true when a technology must be chosen (research still unset)."""
    return J(game().wait_for_my_turn(timeout=timeout_seconds))


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
    """Read the current trade table (scratch deal): items already offered, who they are from.
    Empty items means no deal is on the table. Does not mutate the deal or open the trade screen."""
    return J(game().incoming_deal())


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
    resources). Each resource carries `class`, `us_available`/`them_available` (spare copies each side holds)
    and `last_copy: true` when exporting it would give away our only copy of a luxury (costs happiness).
    Read-only: does not construct or send a deal. City-states: use city_state_gifts."""
    return J(game().trade_catalog(player_id))


@mcp.tool()
@guarded
def city_state_gifts(player_id: int) -> str:
    """Gold gift tiers and friendship for a met city-state. See minor_gold_gift to actually gift.
    `ally` is what the city-state screen's ally tooltip shows: {us: true}, {none: true, to_become_ally},
    or the current ally (named only if met) with `to_become_ally` = influence we still need to pass it.
    Other majors' influence is not visible to a player and is not returned."""
    return J(game().city_state_gifts(player_id))


@mcp.tool()
@guarded
def minor_gold_gift(player_id: int, amount: int) -> str:
    """Gift gold to a city-state. `amount` must be city_state_gifts' small, medium, or large tier."""
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
    """My empire at a glance: gold, science, culture, happiness, research, era, counts, turn/year, and
    `strategic_resources` (revealed ones only) with `available` spare copies -- negative means a deficit:
    units/buildings consume more than the empire owns and they fight/produce at a penalty.
    trade_routes_used counts caravans/cargo ships, not running routes: `idle_trade_units` lists the ones sitting
    without a route (give them one with available_trade_routes + establish_trade_route)."""
    return J(game().summary())


@mcp.tool()
@guarded
def turn_digest() -> str:
    """Everything recorded since my last call: combats, cities founded/lost, wars, chat, notifications, alerts.
    Notes: a caravan / cargo ship shows up as `unit_destroyed` the turn its trade route starts -- the route
    IS the unit now (it comes back as a new unit when the route ends); `unit_graphics_reset` means the engine
    only rebuilt a model (era change, upgrade), the unit is fine. Leader lines you provoked yourself via
    negotiate_deal/propose_deal are not included; unsolicited AI approaches are."""
    return J(game().turn_digest())


@mcp.tool()
@guarded
def units() -> str:
    """My units with position, moves left, hp, strength, and whether they still need orders."""
    return J(game().units())


@mcp.tool()
@guarded
def cities() -> str:
    """My cities: population, yields, current production and turns left, growth, happiness.
    `growth` is "growing" (then `growth_turns` is present), "stagnant" (food_surplus 0 -- typical while
    empire happiness is negative, which throttles growth) or "starving" (negative surplus, will lose pop)."""
    return J(game().cities())


@mcp.tool()
@guarded
def map_window(x: int, y: int, radius: int = 3) -> str:
    """Revealed plots within `radius` of (x, y). vis=true is in sight now; vis=false is discovered but fogged (no live units/owners). Prefer known_world for the full discovered map."""
    return J(game().plots_around(x, y, radius))


@mcp.tool()
@guarded
def explore_frontier(unit_id: int, limit: int = 12) -> str:
    """Where the known map ends for this unit: revealed, passable plots of its domain (sea for a ship, land otherwise) that border unrevealed plots, nearest first. Each has unrevealed_neighbors (how much stepping there reveals), distance (hex distance, not path length), reachable (true when a route exists through the already-revealed map; false = behind land or an unknown strait, listed last), terrain t (a Trireme cannot enter OCEAN), and map_edge=true on the polar rows (mostly ice beyond). move_unit refuses unrevealed targets, so an explorer picks its next stop from here. frontier_total / unrevealed_plots say how much is left; note explains an empty list."""
    return J(game().explore_frontier(unit_id, limit=limit))


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
    """Social policies: what is adopted, what can be adopted right now (with help text), which branches
    are unlocked / unlockable, culture vs next cost. Use before choose_policy / unlock_policy_branch."""
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
    """What this city can produce right now: units, buildings, projects, processes, with `turns` at the
    current production rate, and for units/buildings the gold rush-buy price (`gold`; absent when the item
    can never be bought, e.g. national wonders) plus `can_buy` (affordable AND purchasable right now ->
    purchase_production). Use set_production(city_id, item) to queue one.
    Each row carries `gold` (rush-buy cost, `can_buy`) and, when the faith tab offers it, `faith` + `faith_can_buy`;
    `faith_only` rows (Missionaries, Great People, belief buildings) cannot be produced, only bought
    with purchase_production(yield_type="FAITH")."""
    return J(game().available_production(city_id))


@mcp.tool()
@guarded
def available_unit_actions(unit_id: int) -> str:
    """Legal unit-panel actions for this unit right now (missions, tile builds on ITS plot, commands,
    promotions). Call this before unit_mission. Move-to is a separate tool (move_unit). Does not select
    the unit or pan the camera. For Workers/Work Boats also returns `nearby_builds`: plots within 2 tiles
    that still need work (unimproved, or pillaged) with the builds legal there -- move_unit onto one, then
    unit_mission(MISSION_BUILD, build=...). A build issued with 0 moves left starts next turn."""
    return J(game().available_unit_actions(unit_id))


@mcp.tool()
@guarded
def available_trade_routes(unit_id: int) -> str:
    """Valid trade-route destinations for a specific trade unit (caravan/cargo ship) right now, with the
    trade_type to pass into establish_trade_route. Yields are PER TURN: gold/science/food/production are
    what my end receives, *_them what the destination receives (an internal food/production route delivers
    to the destination city, so read food_them/production_them for those). kind = international|food|production."""
    return J(game().available_trade_routes(unit_id))


@mcp.tool()
@guarded
def trade_routes() -> str:
    """My ACTIVE trade routes (the Trade Route Overview): from/to city, turns_left until the caravan or cargo
    ship returns home and needs a new order, per-turn yields for my end (gold/science) and theirs
    (gold_them / food_them / production_them for internal routes). overview().trade_routes_used vs
    trade_routes_available says whether a slot is free for a new caravan."""
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
    """My spies: agent_id, name, rank, state, where stationed, and can_stage_coup. See
    available_spy_cities/move_spy/stage_coup for actions."""
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
    For a plain yes/no proposal (every repeal; enacts with no `choices` listed) `choice` is required:
    "yes"/"no" or 1/0 (leagueoverview.lua's kChoiceYes/kChoiceNo). For proposals with
    `choices` (e.g. World Leader, host city) pass the listed choice id. Leftover votes are cast as abstain."""
    return J(game().league_cast_votes(votes))


@mcp.tool()
@guarded
def propose_deal(player_id: int, items: list[dict], ask_counter: bool = False) -> str:
    """Offer a trade to an AI civ and get the answer in the same call. Drives the game's real leader/trade
    screens (the only crash-free path; headless deal building crashes the engine), proposes, reads the
    reply, closes the screens and reports measured `effects` (gold, gold/turn, happiness, deal count,
    per-resource import/export before vs after) -- so there is nothing to poll afterwards.
    items: [{"type":"RESOURCES","resource":"RESOURCE_DYE","from_us":true,"amount":1},
            {"type":"RESOURCES","resource":"RESOURCE_SPICES","from_us":false,"amount":1}]
    Types: GOLD / GOLD_PER_TURN (amount), RESOURCES (resource, amount), OPEN_BORDERS, ALLOW_EMBASSY,
    DEFENSIVE_PACT, RESEARCH_AGREEMENT, TRADE_AGREEMENT (from_us picks the direction), CITIES (city_id).
    Use trade_catalog(player_id) first to see what is legal, how much gold / gold-per-turn each side can put
    up, and which cities (`cities.us` / `cities.them`) the game allows trading -- capitals never are.
    Refuses -- without opening any screen -- an amount that is not a positive whole number or exceeds what
    that side has, and a city_id outside trade_catalog().cities; refuses -- without proposing -- if any item
    does not land on the table at the requested amount (e.g. they own none of that resource).
    ask_counter=true: on rejection also returns the AI's own counter-offer (`counter.items`) which can be
    passed straight back into propose_deal. Duration of timed items is the game's deal length (30 turns)."""
    return J(game().propose_deal(player_id, items, ask_counter=ask_counter))


@mcp.tool()
@guarded
def negotiate_deal(player_id: int, items: list[dict], mode: str = "equalize") -> str:
    """Ask an AI civ about a deal without committing to it (the trade screen's helper buttons), then close
    the screen. mode="equalize": put a draft on the table and ask what would make it acceptable;
    "what_will_ai_give": list only my items (from_us=true) and see what the AI offers for them;
    "what_does_ai_want": list only their items (from_us=false) and see what the AI asks in return.
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
    Selects the unit like the unit panel does (orders go through the game's network path)."""
    return J(game().move_unit(unit_id, x, y))


@mcp.tool()
@guarded
def unit_mission(unit_id: int, mission: str, x: int = -1, y: int = -1, build: str = "") -> str:
    """Give a unit a mission: MISSION_FOUND (settle here), MISSION_FORTIFY, MISSION_SLEEP, MISSION_SKIP, MISSION_HEAL,
    MISSION_ALERT, MISSION_RANGE_ATTACK (x,y), MISSION_PILLAGE, MISSION_EMBARK/DISEMBARK...
    MISSION_BUILD: pass the improvement in `build`, e.g. build="BUILD_FARM" (do NOT put it in x/y --
    those are for movement-shaped missions). Builds on the unit's own tile.
    MISSION_SPREAD_RELIGION / MISSION_REMOVE_HERESY: the unit must be inside or adjacent to the target city;
    the result's `effects` reports that city's followers/majority before and after, spreads_left, and (for a
    city-state) influence before/after, so no follow-up read is needed to know whether the spread worked.
    AUTOMATE_EXPLORE / AUTOMATE_BUILD (the unit panel's automation buttons, when available_unit_actions lists
    them) hand the unit to the game's own automation; it then never blocks end_turn. The reply has automated=true.
    Selects the unit like the unit panel does (orders go through the game's network path)."""
    return J(game().unit_mission(unit_id, mission, x, y, build=(build or None)))


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
    it's actually purchasable. Wonders (built via a BUILDING_* item too) are never purchasable in vanilla
    BNW -- can_purchase will read false. Check this before purchase_production."""
    order = _purchase_order(item)
    if order is None:
        return J({"ok": False, "err": f"{item!r}: purchasable items are UNIT_*, BUILDING_* or PROJECT_*"})
    return J(game().purchase_cost(city_id, order, item, yield_type))


@mcp.tool()
@guarded
def purchase_production(city_id: int, item: str, yield_type: str = "GOLD") -> str:
    """Rush-buy a unit or building (item like UNIT_WARRIOR, BUILDING_MARKET) with gold or faith. See
    purchase_cost for price/affordability first. Wonders can never be purchased this way."""
    order = _purchase_order(item)
    if order is None:
        return J({"ok": False, "err": f"{item!r}: purchasable items are UNIT_*, BUILDING_* or PROJECT_*"})
    return J(game().purchase_production(city_id, order, item, yield_type))


@mcp.tool()
@guarded
def steal_tech_options() -> str:
    """When blocking_name is ENDTURN_BLOCKING_STEAL_TECH (a spy finished stealing): which civs I can take
    a tech from and the techs available from each. Then call steal_tech."""
    return J(game().steal_tech_options())


@mcp.tool()
@guarded
def steal_tech(tech: str, victim: int) -> str:
    """Take a stolen tech (TECH_...) from player `victim` (see steal_tech_options). Clears
    ENDTURN_BLOCKING_STEAL_TECH."""
    return J(game().steal_tech(tech, victim))


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
    import sys
    tm = mcp._tool_manager
    orig = tm.call_tool
    tool_error = sys.modules[type(tm).__module__].ToolError  # mcp 1.x and 2.x keep it in different packages

    async def call_tool(name, arguments, *a, **kw):
        tool = tm.get_tool(name)
        if tool is None:
            raise tool_error(unknown_tool_hint(name, sorted(t.name for t in tm.list_tools())))
        arguments = alias_arguments(arguments, tool.parameters)
        try:
            return await orig(name, arguments, *a, **kw)
        except tool_error as e:
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
