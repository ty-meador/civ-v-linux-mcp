"""One unit's orders as rows (GitLab #45, #47): from its todo_actions / available_unit_actions row.

The engine's action row says what the unit may do (`type`, `kind`, `mission`, `target_view`); these functions
say how: `action_rows` turns one action into its call (two rows when the action opens a chooser: the read of
its targets, then the order), `unit_actions` lists a unit's orders for the summary level, and `annotate_unit`
puts `call` (and `read`) on every action, target and promotion of a normal or full row.
"""
from __future__ import annotations

from ..rows import act, pick

#: A unit command and the tool that presses it, with the arguments left to choose. Any other COMMAND_ (promotion:
#: the promotion rows; hotkey, cancel, wake: routine or not an order) makes no row -- unit_mission takes none of
#: them (live Assyria t238: an Infantry's COMMAND_GIFT came out as a unit_mission row the engine would refuse).
COMMAND_TOOLS: dict[str, tuple[str, list[str]]] = {
    "COMMAND_UPGRADE": ("upgrade_unit", []), "COMMAND_DELETE": ("disband_unit", []),
    "COMMAND_GIFT": ("gift_unit", ["minor_id"]),
}
RANGE_ATTACK = "MISSION_RANGE_ATTACK"
#: The read that lists a targeted mission's choices, by the view the engine's row names in `target_view` (a
#: rebase's, an air strike's or a nuke's plots; a trade unit's or Great Admiral's home cities).
TARGET_READS: dict[str, str] = {"targets": "unit_mission_targets", "home": "unit_home_options"}


def action_rows(uid, a: dict) -> list[dict]:
    """The rows for one engine action row: a mission by its engine name, a build through MISSION_BUILD, a command
    through its own tool, a targeted mission (rebase, air strike, paradrop, nuke, a trade unit's new home) as the
    read of its targets then the order with the plot to choose; anything else the engine names (AUTOMATE_*) goes
    through unit_mission as is. Empty when the action is not an order."""
    if not isinstance(a, dict):
        return []
    kind, typ = a.get("kind"), a.get("type")
    if kind == "build":
        return [act("unit_mission", unit_id=uid, mission="MISSION_BUILD", build=typ)]
    if kind == "command":
        if str(typ) not in COMMAND_TOOLS:
            return []
        tool, choose = COMMAND_TOOLS[str(typ)]
        return [pick(tool, choose, unit_id=uid) if choose else act(tool, unit_id=uid)]
    mission = a.get("mission") or typ
    if kind == "interface":
        return [act(TARGET_READS.get(a.get("target_view"), "unit_mission_targets"), unit_id=uid, mission=mission),
                pick("unit_mission", ["x", "y"], unit_id=uid, mission=mission)]
    if a.get("target_view") in TARGET_READS:   # a mission that opens a chooser (a trade unit's new home)
        return [act(TARGET_READS[a["target_view"]], unit_id=uid), pick("unit_mission", ["x", "y"], unit_id=uid, mission=mission)]
    if mission == "MISSION_MOVE_TO":
        # GitLab #135 (Denmark t20): the move row carried no plot and no way to find one. The tactical view's six
        # neighbours say where a step is open; the order takes the plot to choose.
        return [act("tactical_view", unit_id=uid), pick("move_unit", ["x", "y"], unit_id=uid)]
    if mission == "MISSION_ROUTE_TO":
        return [act("tactical_view", unit_id=uid), pick("unit_mission", ["x", "y"], unit_id=uid, mission=mission)]
    if isinstance(mission, str):
        return [act("unit_mission", unit_id=uid, mission=mission)]
    return []


def build_plot_calls(uid, plot: dict) -> list[dict]:
    """One complete order per build a plot offers (GitLab #102): MISSION_BUILD with the plot, which the harness runs
    as walk-then-build when the unit is not standing there."""
    if not isinstance(plot, dict) or plot.get("x") is None or plot.get("y") is None:
        return []
    return [act("unit_mission", unit_id=uid, mission="MISSION_BUILD", build=b, x=plot["x"], y=plot["y"])
            for b in plot.get("builds") or [] if isinstance(b, str)]


def _target_rows(u: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """(melee, ranged, promotion) rows of a unit row, one per target or promotion offered."""
    uid = u.get("id")
    melee = [act("move_unit", unit_id=uid, x=t["x"], y=t["y"])
             for t in u.get("attack_targets") or [] if isinstance(t, dict) and t.get("x") is not None]
    ranged = [act("unit_mission", unit_id=uid, mission=RANGE_ATTACK, x=t["x"], y=t["y"])
              for t in u.get("ranged_targets") or [] if isinstance(t, dict) and t.get("x") is not None]
    promos = []
    for p in u.get("promotions") or []:
        name = p.get("promotion") if isinstance(p, dict) else p
        if name:
            promos.append(act("choose_promotion", unit_id=uid, promotion=name))
    return melee, ranged, promos


def unit_actions(u: dict, actions: list[dict] | None = None) -> list[dict]:
    """Every order a unit's row allows, complete where the reply knows the target (the summary level's `actions`):
    the action rows, one `move_unit` per melee target, one MISSION_RANGE_ATTACK per ranged target, one
    `choose_promotion` per promotion. `actions` is the action list to read when it is not `u["actions"]` (the
    summary row is built from the normal row's, minus the routine ones)."""
    uid = u.get("id")
    out: list[dict] = []
    for a in (actions if actions is not None else u.get("actions")) or []:
        out.extend(action_rows(uid, a))
    for rows in _target_rows(u):
        out.extend(rows)
    return out


def annotate_unit(u: dict, unit_id=None) -> dict:
    """A normal / full unit row with `call` beside every choice (#47): each engine action carries the row that
    takes it (`read` too when it opens a chooser), each melee and ranged target its attack, each promotion its
    promotion order. The row's own keys stay as they were. `unit_id` is the unit when the row does not carry
    its own `id` (a single unit's read answers for the unit asked about; live Assyria t238 the rows came back
    without one)."""
    if not isinstance(u, dict) or u.get("ok") is False:
        return u
    uid = u.get("id") if u.get("id") is not None else unit_id
    for a in u.get("actions") or []:
        rows = action_rows(uid, a)
        if rows:
            a["call"] = rows[-1]
        if len(rows) == 2:
            a["read"] = rows[0]
    for t in u.get("attack_targets") or []:
        if isinstance(t, dict) and t.get("x") is not None:
            t["call"] = act("move_unit", unit_id=uid, x=t["x"], y=t["y"])
    for t in u.get("ranged_targets") or []:
        if isinstance(t, dict) and t.get("x") is not None:
            t["call"] = act("unit_mission", unit_id=uid, mission=RANGE_ATTACK, x=t["x"], y=t["y"])
    for plot in u.get("nearby_builds") or []:
        calls = build_plot_calls(uid, plot)
        if calls:
            plot["calls"] = calls
    for p in u.get("promotions") or []:
        if isinstance(p, dict) and p.get("promotion"):
            p["call"] = act("choose_promotion", unit_id=uid, promotion=p["promotion"])
    return u
