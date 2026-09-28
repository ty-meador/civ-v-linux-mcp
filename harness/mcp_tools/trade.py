"""Trade routes, espionage and the World Congress.

One of the civ5 MCP server's tool modules: every tool here registers on the server in
harness/mcp_server.py, which keeps the game handle, the guard and the tool sets (see its docstring).
"""
from __future__ import annotations

from harness import mcp_server as core
from harness.mcp_server import mcp, J, guarded


@mcp.tool()
@guarded
def espionage_intrigue() -> str:
    """The Espionage Overview intrigue log: turn, spy, discoverer and the player-visible message."""
    return J(core.game().espionage_intrigue())


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
    return J(core.game().available_trade_routes(unit_id, detail=detail))


@mcp.tool()
@guarded
def trade_routes() -> str:
    """Trade Route Overview: `outgoing` is Your TR (my caravans/cargo ships), `incoming` is With You
    (other civs' routes into my cities). Each row: from/to city and player, turns_left, per-turn yields
    for the origin (`gold`/`science`) and destination (`gold_them` / food_them / production_them).
    The religion columns are `from_religion`/`from_pressure` (left arrow) and `to_religion`/`to_pressure`
    (right arrow), omitted when that cell is blank. `details` is the gold and science hover.
    overview().free_trade_route_slots (available - used - queued) says whether a new caravan can be trained.
    `path` is the route line the map draws, plot by plot from the origin (vis=false where fogged), as
    the plot hover names it on any revealed plot. `unit` is the caravan/cargo ship on that line (ours
    always; a foreign one only while in sight) with `escorted` / `escorted_by`: our combat units on its
    plot, which an enemy must defeat before it can plunder; `unit.matched` is `recorded` (this caravan was
    seen alone on this route before), `line` or `line_ambiguous` (routes share the plot and no earlier read
    told them apart: it may be the other row's caravan). `enemies_near_path` lists visible enemy
    combat units within one hex of the line with their distance to the caravan."""
    return J(core.game().trade_routes())


@mcp.tool()
@guarded
def establish_trade_route(unit_id: int, dest_x: int = -1, dest_y: int = -1, trade_type: int = -1,
                          city_name: str = "", kind: str = "") -> str:
    """Send a caravan/cargo ship to establish a trade route. Either pass dest_x/dest_y/trade_type from
    available_trade_routes(unit_id), or just `city_name` (e.g. "Antwerp") with `kind` =
    international/food/production when that city offers more than one route type."""
    return J(core.game().establish_trade_route(unit_id, dest_x, dest_y, trade_type, city_name=city_name, kind=kind))


@mcp.tool()
@guarded
def plunder_trade_route(unit_id: int) -> str:
    """Order a military unit standing on an enemy trade route to plunder it."""
    return J(core.game().plunder_trade_route(unit_id))


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
    return J(core.game().spies())


@mcp.tool()
@guarded
def available_spy_cities(agent_id: int) -> str:
    """Cities a given spy (agent_id, from spies()) could be sent to right now -- my own cities (counter-intel)
    and others' (steal tech / set up a future coup). Feeds move_spy. `potential` is the espionage screen's
    base potential: for a foreign city, how much there is to steal; for my own, how exposed it is to theft;
    "unknown" until a spy has had that city under surveillance."""
    return J(core.game().available_spy_cities(agent_id))


@mcp.tool()
@guarded
def move_spy(agent_id: int, target_player_id: int, target_city_id: int, as_diplomat: bool = False) -> str:
    """Assign/relocate a spy (see available_spy_cities). Recall home instead with target_player_id=-1,
    target_city_id=-1. as_diplomat only applies when the target is another major civ's capital at peace."""
    return J(core.game().move_spy(agent_id, target_player_id, target_city_id, as_diplomat))


@mcp.tool()
@guarded
def stage_coup(agent_id: int) -> str:
    """Attempt a coup against a city-state's current ally with a spy that has established surveillance
    there (spies()'s can_stage_coup). Returns the `chance` the confirm printed, the `outcome`
    notification and `succeeded` (the city-state's ally is now us); a refusal says `why_not`."""
    return J(core.game().stage_coup(agent_id))


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
    return J(core.game().league_status())


@mcp.tool()
@guarded
def league_propose_enact(resolution_type: str, choice: int = -1) -> str:
    """Propose enacting a World Congress resolution, e.g. RESOLUTION_SCIENCES_FUNDING (see league_status()
    for what's currently proposable and any required `choice`). Needed to clear
    ENDTURN_BLOCKING_LEAGUE_CALL_FOR_PROPOSALS -- closing the popup without proposing does NOT clear it."""
    return J(core.game().league_propose_enact(resolution_type, choice))


@mcp.tool()
@guarded
def league_propose_repeal(resolution_id: int) -> str:
    """Propose repealing an active World Congress resolution (see league_status()'s proposable_repeal)."""
    return J(core.game().league_propose_repeal(resolution_id))


@mcp.tool()
@guarded
def league_cast_votes(votes: list[dict]) -> str:
    """Vote on this session's World Congress proposals (see league_status()'s votable while in_session).
    votes: [{"resolution_id": id, "direction": "enact"|"repeal", "num_votes": n, "choice": id (optional)}].
    For a plain yes/no proposal (every repeal; enacts with no `choices` listed) `choice` is required:
    "yes"/"no" or 1/0 (leagueoverview.lua's kChoiceYes/kChoiceNo). For proposals with
    `choices` (e.g. World Leader, host city) pass the listed choice id. Leftover votes are cast as abstain."""
    return J(core.game().league_cast_votes(votes))
