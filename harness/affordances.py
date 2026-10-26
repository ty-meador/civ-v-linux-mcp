"""What can be done next, as rows the model copies (GitLab #45, stage 1a of "The tool surface").

A reply that lists what can be done used to say it in words ("available_production + set_production") and the
model had to turn the sentence into a call. Now the reply writes the call: a row `{tool, args}` is exactly what
`do(actions=[...])` and `finish_turn(actions=[...])` take, so a decision's rows go back into the game unchanged.
A row whose argument the model still has to pick carries `choose`: the names of the arguments the read before it
lists the values for (`set_production(city_id=7, item=<a row of available_production>)`).

This module is the one place that writes such a row in today's vocabulary (the shape itself is `harness/rows.py`,
the gate's own rows `harness/gate.py`), so stage 2 (#48) swaps the words here and nowhere else:
`harness/briefing.py` asks it for every decision and opportunity, the todo_actions summary
(`harness/game_parts/support.py`) for every unit, and the question-shaped reads (a popup, a leader on screen, a
deal on the table: `harness/game_parts/popups.py`, `diplomacy.py`, `deals.py`, ...) for their `answers` (#46). The
audit (`harness/surface/audit.py`) counts a reply as carrying rows when it calls into this module or `rows`.
"""
from __future__ import annotations

from typing import Any, Callable

from . import gate
from .rows import CHOOSE, act, is_row, pick, rows_in  # noqa: F401  (re-exported: the briefing and the tests use A.act)


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


# --- a question's answers: the rows that answer a popup, a leader on screen or a deal on the table (#46) -------
def answered(reply: Any, make: Callable[[dict], list[dict]]) -> Any:
    """`reply` with `answers` (the rows `make` builds from it) when it is a reply and not a refusal."""
    if isinstance(reply, dict) and reply.get("ok", True) is not False:
        reply["answers"] = make(reply)
    return reply


def _options(reply: dict, key: str = "options") -> list:
    v = reply.get(key)
    return v if isinstance(v, list) else []


def generic_popup_answers(r: dict) -> list[dict]:
    """One `answer_popup` per numbered button of an open generic confirmation."""
    if not r.get("open"):
        return []
    out = []
    for i, b in enumerate(_options(r, "buttons"), start=1):
        out.append(act("answer_popup", button=b.get("id", i) if isinstance(b, dict) else i))
    return out


def goody_hut_answers(r: dict) -> list[dict]:
    return [act("choose_goody_hut", goody=o["goody"]) for o in _options(r) if isinstance(o, dict) and o.get("goody")]


def maya_answers(r: dict) -> list[dict]:
    """The Long Count's choices still open (a type chosen earlier in the cycle is listed but not offered)."""
    if not r.get("count"):
        return []
    return [act("choose_maya_bonus", unit=o["unit"]) for o in _options(r)
            if isinstance(o, dict) and o.get("unit") and o.get("available", True)]


def city_capture_answers(r: dict) -> list[dict]:
    return [act("choose_city_capture", choice=o["choice"]) for o in _options(r) if isinstance(o, dict) and o.get("choice")]


def steal_tech_answers(r: dict) -> list[dict]:
    """One row per (victim, tech) pair the spy may take."""
    out = []
    for v in _options(r, "victims"):
        if not isinstance(v, dict) or v.get("player_id") is None:
            continue
        for t in _options(v, "techs"):
            if isinstance(t, dict) and t.get("tech"):
                out.append(act("steal_tech", tech=t["tech"], player_id=v["player_id"]))
    return out


def free_great_person_answers(r: dict) -> list[dict]:
    if not r.get("count"):
        return []
    return [act("choose_free_great_person", unit=u) for u in _options(r) if isinstance(u, str)]


def faith_great_person_answers(r: dict) -> list[dict]:
    return [act("choose_faith_great_person", unit=u) for u in _options(r) if isinstance(u, str)]


def archaeology_answers(r: dict) -> list[dict]:
    """One `choose_archaeology` per choice of the completed dig, the dig's plot filled in."""
    if not r.get("pending") or r.get("x") is None or r.get("y") is None:
        return []
    return [act("choose_archaeology", choice=o["choice"], x=r["x"], y=r["y"])
            for o in _options(r) if isinstance(o, dict) and o.get("choice") is not None]


#: The leader's screen state that `accept_friendship` answers (a Declaration of Friendship proposed to us).
FRIENDSHIP_STATE = "DISCUSS_WORK_WITH_US"


def discussion_answers(r: dict) -> list[dict]:
    """The leader screen's buttons as rows: a deal on the table takes accept / refuse, a question its response
    buttons (and `accept_friendship` when the question is a Declaration of Friendship), every screen may be
    left with `dismiss_discussion`."""
    if not r.get("pending"):
        return []
    if r.get("screen") == "trade":
        return [act("accept_deal"), act("refuse_deal"), act("dismiss_discussion")]
    out = [act("respond_discussion", button_id=b["id"]) for b in _options(r, "buttons")
           if isinstance(b, dict) and b.get("id") is not None and not b.get("disabled")]
    rel = r.get("relationship") if isinstance(r.get("relationship"), dict) else {}
    states = [str(h.get("state", "")) for h in rel.get("history") or [] if isinstance(h, dict)]
    if out and isinstance(r.get("player"), int) and r["player"] >= 0 and any(s.endswith(FRIENDSHIP_STATE) for s in states):
        out.append(act("accept_friendship", player_id=r["player"]))
    out.append(act("dismiss_discussion"))
    return out


def incoming_deal_answers(r: dict) -> list[dict]:
    """A deal on the table is taken or declined; nothing on the table makes no row."""
    if not r.get("items") or r.get("pending") is False:
        return []
    return [act("accept_deal"), act("refuse_deal")]
