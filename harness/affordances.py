"""What can be done next, as rows the model copies (GitLab #45, stage 1a of "The tool surface").

A reply that lists what can be done used to say it in words ("available_production + set_production") and the
model had to turn the sentence into a call. Now the reply writes the call: a row `{tool, args}` is exactly what
`do(actions=[...])` and `finish_turn(actions=[...])` take, so a decision's rows go back into the game unchanged.
A row whose argument the model still has to pick carries `choose`: the names of the arguments the read before it
lists the values for (`set_production(city_id=7, item=<a row of available_production>)`).

This module is the one place that writes such a row in today's vocabulary, so stage 2 (#48) swaps the words
here and nowhere else: `harness/briefing.py` asks it for every decision and opportunity, the todo_actions summary
(`harness/game_parts/support.py`) for every unit, and the gate (`harness/gate.py`) supplies the popup rows. The
audit (`harness/surface/audit.py`) counts a reply as carrying rows when it calls into this module.
"""
from __future__ import annotations

from typing import Any

from . import gate

#: The key of a row whose arguments the model fills from the read before it.
CHOOSE = "choose"


def act(tool: str, **args: Any) -> dict:
    """One complete call: `{tool, args}`."""
    return {"tool": tool, "args": args}


def pick(tool: str, choose: list[str], **args: Any) -> dict:
    """A call with arguments still to choose from the read before it: `{tool, args, choose}`."""
    return {**act(tool, **args), CHOOSE: list(choose)}


# --- the briefing's decisions (harness/briefing.py decisions / opportunities) ------------------------
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
    """A decision popup: the gate's read, then the call that answers it (the arguments from gate.POPUP_CHOICE_ARGS)."""
    r = gate.popup_resolution(str(name))
    out: list[dict] = []
    if r.get("read_first"):
        out.append(act(r["read_first"]))
    chosen = gate.POPUP_CHOICE_ARGS.get(str(name), "button" if r["clear_with"] == "answer_popup" else "")
    out.append(pick(r["clear_with"], [a.strip() for a in chosen.split(",") if a.strip()]))
    return out


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


# --- one unit's orders, from its todo_actions / available_unit_actions row ----------------------------
#: A unit command and the tool that presses it, with the arguments left to choose. Any other COMMAND_ (promotion:
#: the promotion rows; hotkey, cancel, wake: routine or not an order) makes no row -- unit_mission takes none of
#: them (live Assyria t238: an Infantry's COMMAND_GIFT came out as a unit_mission row the engine would refuse).
COMMAND_TOOLS: dict[str, tuple[str, list[str]]] = {
    "COMMAND_UPGRADE": ("upgrade_unit", []), "COMMAND_DELETE": ("disband_unit", []),
    "COMMAND_GIFT": ("gift_unit", ["minor_id"]),
}


def unit_actions(u: dict, actions: list[dict] | None = None) -> list[dict]:
    """Every order a unit's action row allows, complete where the reply knows the target: a mission by its
    engine name, a build through MISSION_BUILD, a command through its own tool, a targeted mission (rebase,
    air strike, paradrop, nuke) as the read of its targets then the order to choose among them, one
    `move_unit` per melee target and one MISSION_RANGE_ATTACK per ranged target, one `choose_promotion` per
    promotion offered. `actions` is the action list to read when it is not `u["actions"]` (the summary row
    is built from the normal row's)."""
    uid = u.get("id")
    out: list[dict] = []
    for a in (actions if actions is not None else u.get("actions")) or []:
        if not isinstance(a, dict):
            continue
        kind, typ = a.get("kind"), a.get("type")
        if kind == "build":
            out.append(act("unit_mission", unit_id=uid, mission="MISSION_BUILD", build=typ))
        elif kind == "command":
            if str(typ) in COMMAND_TOOLS:
                tool, choose = COMMAND_TOOLS[str(typ)]
                out.append(pick(tool, choose, unit_id=uid) if choose else act(tool, unit_id=uid))
        elif kind == "interface":
            mission = a.get("mission") or typ
            out.append(act(a.get("target_tool") or "unit_mission_targets", unit_id=uid, mission=mission))
            out.append(pick("unit_mission", ["x", "y"], unit_id=uid, mission=mission))
        elif a.get("target_tool"):           # a mission that opens a chooser (a trade unit's new home)
            out.append(act(a["target_tool"], unit_id=uid))
            out.append(pick("unit_mission", ["x", "y"], unit_id=uid, mission=a.get("mission") or typ))
        elif isinstance(a.get("mission") or typ, str):   # a mission, or anything else the engine names (AUTOMATE_*)
            out.append(act("unit_mission", unit_id=uid, mission=a.get("mission") or typ))
    for t in u.get("attack_targets") or []:
        if isinstance(t, dict) and t.get("x") is not None:
            out.append(act("move_unit", unit_id=uid, x=t["x"], y=t["y"]))
    for t in u.get("ranged_targets") or []:
        if isinstance(t, dict) and t.get("x") is not None:
            out.append(act("unit_mission", unit_id=uid, mission="MISSION_RANGE_ATTACK", x=t["x"], y=t["y"]))
    for p in u.get("promotions") or []:
        name = p.get("promotion") if isinstance(p, dict) else p
        if name:
            out.append(act("choose_promotion", unit_id=uid, promotion=name))
    return out


def is_row(v: Any) -> bool:
    """A `{tool, args}` row as do() / finish_turn() take it."""
    return isinstance(v, dict) and isinstance(v.get("tool"), str) and isinstance(v.get("args"), dict)


def rows_in(reply: Any) -> list[dict]:
    """Every action row anywhere in a reply (`actions` lists at any depth), in reading order."""
    out: list[dict] = []
    stack = [reply]
    while stack:
        v = stack.pop(0)
        if isinstance(v, dict):
            acts = v.get("actions")
            if isinstance(acts, list) and all(is_row(r) for r in acts):
                out.extend(acts)
            stack.extend(x for k, x in v.items() if k != "actions")
        elif isinstance(v, list):
            stack.extend(v)
    return out
