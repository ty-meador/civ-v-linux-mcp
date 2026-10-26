"""The briefing's decisions and opportunities as rows (GitLab #45): the read to make, then the order that resolves it."""
from __future__ import annotations

from .. import gate
from ..rows import act, pick


def unit_orders(unit_id: int) -> list[dict]:
    """A unit still needing orders: the one read whose rows carry every order it takes (`unit_actions`)."""
    return [act("todo_actions", unit_ids=[unit_id], detail="summary")]


def promotion(unit_id: int) -> list[dict]:
    return [act("todo_actions", unit_ids=[unit_id], detail="summary"),
            pick("choose_promotion", ["promotion"], unit_id=unit_id)]


def city_production(city_id: int) -> list[dict]:
    return [act("available_production", city_id=city_id), pick("set_production", ["item"], city_id=city_id)]


def research() -> list[dict]:
    return [act("available_research"), pick("set_research", ["tech"])]


def incoming_deal() -> list[dict]:
    return [act("incoming_deal"), act("accept_deal"), act("refuse_deal")]


def steal_tech() -> list[dict]:
    return [act("steal_tech_options"), pick("steal_tech", ["tech", "player_id"])]


def policy() -> list[dict]:
    return [act("available_policies"), pick("choose_policy", ["policy"]), pick("unlock_policy_branch", ["branch"])]


def stacked(tiles: list) -> list[dict]:
    """Units sharing a tile when the engine blocks on it: for each tile, the unit to look at and move off."""
    out: list[dict] = []
    for tile in tiles if isinstance(tiles, list) else []:
        units = tile.get("units") if isinstance(tile, dict) else None
        if not isinstance(units, list) or not units:
            continue
        movers = [u for u in units if isinstance(u, dict) and (u.get("moves") or 0) > 0] or units
        uid = movers[0].get("id") if isinstance(movers[0], dict) else None
        if uid is None:
            continue
        out.append(act("tactical_view", unit_id=uid))
        out.append(pick("move_unit", ["x", "y"], unit_id=uid))
    return out


def popup(name: str | None) -> list[dict]:
    """A decision popup: the gate's own rows (the read, then the call that answers it)."""
    return gate.popup_rows(str(name))


def idle_trade_unit(unit_id: int) -> list[dict]:
    """The route choices, then either form of the order: by destination plot or by city name and kind."""
    return [act("available_trade_routes", unit_id=unit_id),
            pick("establish_trade_route", ["dest_x", "dest_y"], unit_id=unit_id),
            pick("establish_trade_route", ["city_name", "kind"], unit_id=unit_id)]


def idle_spy(agent_id: int | None) -> list[dict]:
    if agent_id is None:
        return []
    return [act("available_spy_cities", agent_id=agent_id),
            pick("move_spy", ["target_player_id", "target_city_id"], agent_id=agent_id)]


