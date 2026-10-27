"""The object reads and the standing orders as rows (GitLab #47).

`units()` and `cities()` list what I own; each row gains `actions`, what can be done with that object (the read
that lists a unit's orders, a city's production pair) -- what stage 2's `inspect(what, id)` returns under
`actions`. A city-state's screen, a civ's trade catalog and the league carry their buttons the same way, and an order
that pauses names the two calls that settle it.
"""
from __future__ import annotations

from typing import Any, Callable

from ..rows import act, pick


def unit_rows(unit_id: int) -> list[dict]:
    """A unit I own: the one read whose rows carry every order it takes right now."""
    return [act("todo_actions", unit_ids=[unit_id], detail="summary")]


def city_rows(city_id: int) -> list[dict]:
    """A city I own: its production choices and the order that queues one."""
    return [act("available_production", city_id=city_id), pick("set_production", ["item"], city_id=city_id)]


def with_object_rows(rows: Any, make: Callable[[int], list[dict]]) -> Any:
    """`actions` on every row of an object list that has an `id`."""
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and r.get("id") is not None:
            r["actions"] = make(r["id"])
    return rows


#: The city-state screen's buttons in reply-key order, and the `action` name city_state_action takes for each.
CITY_STATE_BUTTONS = (("pledge", "pledge"), ("revoke_pledge", "revoke_pledge"), ("bully_gold", "bully_gold"),
                      ("bully_unit", "bully_unit"), ("declare_war", "declare_war"), ("peace", "make_peace"))


def city_state_rows(reply: Any, player_id: int) -> Any:
    """city_state_actions: `actions`, one `city_state_action` row per button the screen offers now (`can` true)."""
    if not isinstance(reply, dict) or reply.get("ok") is False:
        return reply
    reply["actions"] = [act("city_state_action", player_id=player_id, action=action)
                        for key, action in CITY_STATE_BUTTONS
                        if isinstance(reply.get(key), dict) and reply[key].get("can")]
    return reply


def _resource_item(resource: str, from_us: bool) -> dict:
    return {"type": "RESOURCES", "resource": resource, "from_us": from_us, "amount": 1}


def trade_catalog_rows(reply: Any, player_id: int) -> Any:
    """trade_catalog: `actions` (the two deal calls with the items to compose), and on each tradeable resource
    `call`: a one-item `negotiate_deal` that asks their copy (or offers ours) and lets the AI price it."""
    if not isinstance(reply, dict) or reply.get("ok") is False:
        return reply
    reply["actions"] = [pick("negotiate_deal", ["items"], player_id=player_id),
                        pick("propose_deal", ["items"], player_id=player_id)]
    for r in reply.get("resources") or []:
        if not isinstance(r, dict) or not r.get("resource"):
            continue
        if (r.get("them") or 0) > 0:
            r["call"] = act("negotiate_deal", player_id=player_id, items=[_resource_item(r["resource"], False)])
        elif (r.get("us") or 0) > 0:
            r["call"] = act("negotiate_deal", player_id=player_id, items=[_resource_item(r["resource"], True)])
    return reply


def league_rows(reply: Any) -> Any:
    """league_status: in a session every `votable` row carries `actions` -- a yes and a no vote with every
    remaining delegate (num_votes is the number to edit when splitting them; a resolution with voter `choices`
    carries one row with the choice left to pick) and the reply's `actions` is the vote call itself; between
    sessions every `proposable_enact` / `proposable_repeal` row carries `call`. Found at Assyria t244 (the UN
    session of #56): the votable rows named nothing to copy."""
    if not isinstance(reply, dict) or reply.get("ok") is False:
        return reply
    if reply.get("in_session"):
        n = reply.get("remaining_votes") or 0
        for v in reply.get("votable") or []:
            if not isinstance(v, dict) or v.get("resolution_id") is None:
                continue
            base = {"resolution_id": v["resolution_id"], "direction": v.get("direction") or "enact", "num_votes": n}
            if v.get("yes_no"):
                v["actions"] = [act("league_cast_votes", votes=[{**base, "choice": "yes"}]),
                                act("league_cast_votes", votes=[{**base, "choice": "no"}])]
            else:
                v["actions"] = [pick("league_cast_votes", ["votes"], votes=[{**base, "choice": None}])]
        reply["actions"] = [pick("league_cast_votes", ["votes"])]
        return reply
    for r in reply.get("proposable_enact") or []:
        if isinstance(r, dict) and r.get("resolution_type"):
            r["call"] = (pick("league_propose_enact", ["choice"], resolution_type=r["resolution_type"]) if r.get("choices")
                         else act("league_propose_enact", resolution_type=r["resolution_type"]))
    for r in reply.get("proposable_repeal") or []:
        if isinstance(r, dict) and r.get("resolution_id") is not None:
            r["call"] = act("league_propose_repeal", resolution_id=r["resolution_id"])
    return reply


def order_pause_rows(order_id: int) -> list[dict]:
    """A paused conditional order: hand the unit back to it, or drop it."""
    return [act("resume_order", order_id=order_id), act("cancel_order", order_id=order_id)]
