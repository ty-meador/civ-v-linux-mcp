"""The turn briefing (#30): one compact read of what needs this seat now, what changed since the seat's
previous briefing, and what the board looks like, built from reads the harness already makes.

Everything here is a pure function of those reads, so it is tested without a game:

- `snapshot` keeps what the next briefing compares against (empire totals, cities, unit ids). It is stored
  beside the seat's notebook (`Notebook.briefing_baseline`), so a new server process or a model whose
  context was reset still compares against the seat's last briefing of the same game.
- `baseline_state` says whether that snapshot is comparable: none yet, or one from a later turn than the
  game now shows (a reload), is reported as such and nothing is diffed against it.
- `build` assembles the answer. `decisions` holds every mandatory item and is never cut; every other list
  is capped at `limit` with the count left out and the tool that shows the rest.

Facts are copied from the reads; the one judgement (how close a hostile unit is) is labelled `assessment`.

Size (#43, measured in #36): threat rows are compact by default and a threat the previous briefing listed is
only marked `seen`; the notes a hand-off carries are the ones written since the last hand-off
(`Notebook.hand_off`). `decisions` is never cut.
"""
from __future__ import annotations

from typing import Any

from . import affordances as A
from . import gate
from . import rows as R

# Totals compared turn to turn. Names are overview()'s.
EMPIRE_KEYS = ("gold", "gold_per_turn", "science", "culture_per_turn", "faith", "faith_per_turn", "happiness",
               "num_cities", "num_units", "score")
EMPIRE_EXTRA = ("research", "research_turns_left", "era", "culture", "next_policy_cost", "golden_age_turns")

# Event kinds a briefing lists one by one; everything else is only counted. Chosen from what
# finish_turn already treats as waking (Game.WAKE_KINDS) minus the noise a briefing does not need.
LISTED_KINDS = ("combat", "damage", "unit_lost", "unit_hurt", "unit_destroyed", "unit_captured", "city_captured",
                "city_destroyed", "city_created", "civ_eliminated", "war_state", "leader_message", "chat",
                "notification", "alert", "popup_shown")
QUIET_KINDS = frozenset({"turn_start", "turn_end", "unit_graphics_reset", "active_player", "hook_error"})

TEXT_MAX = 160


def _num(v: Any) -> Any:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def snapshot(turn: int | None, summary: dict, cities: list, units: list, event_seq: int | None,
             territory: list | None = None) -> dict:
    """What the next briefing compares against. `territory` is the board's list of owned plots ("x,y");
    kept only when the board read it (a baseline without it compares no plots)."""
    out = {
        "turn": turn,
        "event_seq": event_seq,
        "empire": {k: summary.get(k) for k in EMPIRE_KEYS if _num(summary.get(k)) is not None},
        "cities": {str(c.get("id")): {"name": c.get("name"), "pop": c.get("pop"), "production": c.get("production")}
                   for c in cities if isinstance(c, dict) and c.get("id") is not None},
        "units": {str(u.get("id")): u.get("type") for u in units if isinstance(u, dict) and u.get("id") is not None},
    }
    if isinstance(territory, list):
        out["territory"] = sorted(str(k) for k in territory)
    return out


def _plot_key(k: str) -> dict | None:
    try:
        x, y = k.split(",")
        return {"x": int(x), "y": int(y)}
    except (ValueError, AttributeError):
        return None


def territory_changes(prev: dict, snap: dict) -> dict:
    """Plots owned at the baseline and not now (`lost`) and the other way round (`gained`), when both
    snapshots carry a territory list. A lost plot is land a neighbour's Citadel took, or a city lost or traded
    with its tiles: the map shows the border move, the notification names only the civ (live England t216).
    The caller fills each lost row in from the game (owner now, improvement, resource)."""
    pt, nt = prev.get("territory"), snap.get("territory")
    if not isinstance(pt, list) or not isinstance(nt, list):
        return {}
    was, now = set(pt), set(nt)
    lost = [r for r in (_plot_key(k) for k in sorted(was - now)) if r]
    gained = [r for r in (_plot_key(k) for k in sorted(now - was)) if r]
    if not lost and not gained:
        return {}
    out: dict = {"plots": {"was": len(was), "now": len(now)}}
    if lost:
        out["lost"] = lost
        out["lost_note"] = ("mine at the baseline, not now: a neighbour's Citadel or a city lost or traded; "
                            "each row says who holds it now and what stood on it; the events say which")
    if gained:
        out["gained"] = gained
    return out


def baseline_state(prev: dict | None, turn: int | None, event_seq: int | None) -> dict:
    """Whether `prev` can be diffed against the game as it is now, and why not when it cannot."""
    if not isinstance(prev, dict) or prev.get("turn") is None:
        return {"comparable": False, "reason": "no earlier briefing of this game for this seat: nothing to compare "
                                               "against; the board below is the whole picture"}
    pt = prev.get("turn")
    if isinstance(turn, int) and isinstance(pt, int) and pt > turn:
        return {"comparable": False, "turn": pt,
                "reason": f"the last briefing was on turn {pt}, later than turn {turn}: a save was loaded; "
                          "nothing is compared and the baseline restarts here"}
    out = {"comparable": True, "turn": pt, "turns_ago": (turn - pt) if isinstance(turn, int) and isinstance(pt, int) else None}
    ps = prev.get("event_seq")
    if isinstance(ps, int) and isinstance(event_seq, int) and ps > event_seq:
        # The game's event log restarted (a load gives the runtime a fresh log): the numbers still compare,
        # the events since the old cursor do not exist here.
        out["events_restarted"] = True
    return out


def _delta(prev: dict, now: dict) -> dict:
    out = {}
    for k in EMPIRE_KEYS:
        a, b = _num(prev.get(k)), _num(now.get(k))
        if a is not None and b is not None and a != b:
            out[k] = {"was": a, "now": b}
    return out


def compare(prev: dict, snap: dict) -> dict:
    """Empire, city and unit changes between two snapshots; empty lists are left out."""
    out: dict = {}
    d = _delta(prev.get("empire") or {}, snap.get("empire") or {})
    if d:
        out["empire"] = d
    pc, nc = prev.get("cities") or {}, snap.get("cities") or {}
    cities: dict = {}
    new = [{"id": int(k), "name": v.get("name")} for k, v in nc.items() if k not in pc]
    gone = [{"id": int(k), "name": v.get("name")} for k, v in pc.items() if k not in nc]
    grew, prod = [], []
    for k, v in nc.items():
        was = pc.get(k)
        if not was:
            continue
        if _num(v.get("pop")) is not None and _num(was.get("pop")) is not None and v["pop"] != was["pop"]:
            grew.append({"id": int(k), "name": v.get("name"), "pop": {"was": was["pop"], "now": v["pop"]}})
        if v.get("production") != was.get("production"):
            # The item a city was building left its queue: completed, bought, or switched by hand.
            prod.append({"id": int(k), "name": v.get("name"), "was": was.get("production"), "now": v.get("production")})
    for key, rows in (("new", new), ("gone", gone), ("pop", grew), ("production", prod)):
        if rows:
            cities[key] = rows
    if cities:
        out["cities"] = cities
    pu, nu = prev.get("units") or {}, snap.get("units") or {}
    units: dict = {}
    added = [{"id": int(k), "type": t} for k, t in nu.items() if k not in pu]
    lost = [{"id": int(k), "type": t} for k, t in pu.items() if k not in nu]
    for row in lost:
        # A trade unit leaves the list the turn its route starts (the engine re-creates it under a new id for
        # the route) and again when the route ends (back home, new id): not a loss, and the events say which
        # (Codex c41, 2026-09-27, read "gone" as an ambiguous unit loss).
        if row["type"] in ("CARAVAN", "CARGO_SHIP"):
            row["likely"] = ("its trade route started or ended: the same unit continues under a new id "
                             "(inspect(what='screen', view='trade_routes') lists one on a route; inspect(what='empire').idle_trade_units one back home)")
    if added:
        units["new"] = added
    if lost:
        units["gone"] = lost
        units["gone_note"] = ("not on the unit list any more: killed, captured, disbanded, upgraded (new id), "
                              "consumed (settler, great person); a trade unit whose route started or ended carries "
                              "`likely`; the events say which")
    if units:
        out["units"] = units
    t = territory_changes(prev, snap)
    if t:
        out["territory"] = t
    return out


def _event_line(e: dict) -> dict | None:
    kind = str(e.get("kind") or "")
    if kind in QUIET_KINDS:
        return None
    d = e.get("data") if isinstance(e.get("data"), dict) else {}
    row: dict = {"seq": e.get("seq"), "turn": e.get("turn"), "kind": kind}
    text = d.get("narration") or d.get("summary") or d.get("text")
    if kind == "notification" and d.get("summary") and d.get("text") and d.get("text") != d.get("summary"):
        # The tooltip usually restates the headline ("ENACT: X Passes" / "ENACT: X was passed..."): keep one.
        text = d["text"] if str(d["text"]).startswith(str(d["summary"])) else f"{d['summary']}: {d['text']}"
    if text:
        s = " ".join(str(text).split())
        row["text"] = s if len(s) <= TEXT_MAX else s[:TEXT_MAX - 3] + "..."
    for k in ("x", "y", "city_id", "unit", "player"):
        if k in d and isinstance(d[k], (int, str)):
            row[k] = d[k]
    return row


def summarize_events(events: list, limit: int) -> dict:
    """Counts by kind for every event, the consequential ones listed newest last, capped at `limit`."""
    counts: dict[str, int] = {}
    listed: list[dict] = []
    for e in events or []:
        if not isinstance(e, dict):
            continue
        kind = str(e.get("kind") or "")
        counts[kind] = counts.get(kind, 0) + 1
        if kind in LISTED_KINDS:
            row = _event_line(e)
            if row is not None:
                listed.append(row)
    out: dict = {"total": sum(counts.values()), "by_kind": counts}
    if len(listed) > limit:
        out["omitted"] = len(listed) - limit
        listed = listed[-limit:] if limit > 0 else []
    out["items"] = listed
    if out.get("omitted"):
        out["more"] = "turn(action='briefing', since='turn', limit=N) repeats this turn's events; inspect(what='notifications') has every notice"
    return out


def decisions(ts: dict, cities: list) -> list[dict]:
    """Every mandatory item of the turn, each with the entity id, the calls that clear it (`actions`, rows for
    do / finish_turn, from harness.affordances) and -- for one more release -- the same as a sentence (`tool`,
    lifted into the briefing's `tools` by build()). Never capped."""
    out: list[dict] = []
    todo = ts.get("todo") if isinstance(ts.get("todo"), dict) else {}
    names = {c.get("id"): c.get("name") for c in cities if isinstance(c, dict)}
    capital = next((c for c in cities if isinstance(c, dict) and c.get("capital") and c.get("x") is not None), None)
    for u in todo.get("units") or []:
        if not isinstance(u, dict):
            continue
        if str(u.get("type") or "").startswith("SS_"):
            # GitLab #93 (Assyria t273): the one order that wins the game was never a row. In the capital the part goes
            # in; elsewhere it walks there first (a part at 0 moves is refused by the runtime, so the row says next turn).
            at_capital = bool(capital and (u.get("x"), u.get("y")) == (capital.get("x"), capital.get("y")))
            row = {"kind": "spaceship_part", "id": u.get("id"), "type": u.get("type"), "x": u.get("x"), "y": u.get("y"),
                   "moves": u.get("moves"), "at_capital": at_capital,
                   "tool": "order(to='unit', action='mission', args={mission: MISSION_SPACESHIP}) in the capital"}
            if at_capital:
                row["actions"] = [R.act("unit_mission", unit_id=u.get("id"), mission="MISSION_SPACESHIP")]
                row["note"] = ("in the capital: MISSION_SPACESHIP adds it to the ship" +
                               ("" if (u.get("moves") or 0) > 0 else " -- next turn, it has no moves left now"))
            elif capital:
                row["actions"] = [R.act("move_unit", unit_id=u.get("id"), x=capital["x"], y=capital["y"]),
                                  R.act("unit_mission", unit_id=u.get("id"), mission="MISSION_SPACESHIP")]
                row["note"] = (f"walk it into {capital.get('name') or 'the capital'} ({capital['x']},{capital['y']}) -- the city tile "
                               "must hold no other civilian -- then MISSION_SPACESHIP there")
            else:
                row["actions"] = A.unit_orders(u.get("id"))
            out.append(row)
            continue
        row = {"kind": "unit_orders", "id": u.get("id"), "type": u.get("type"), "x": u.get("x"), "y": u.get("y"),
               "moves": u.get("moves"), "tool": "inspect(what='units', view='actions', detail='summary') then order(to='unit', action='move' / 'mission')",
               "actions": A.unit_orders(u.get("id"))}
        if u.get("stalled_mission"):
            row["note"] = u.get("note")
        out.append(row)
    for uid in todo.get("promotions") or []:
        out.append({"kind": "promotion", "id": uid, "tool": "order(to='unit', action='promote') (inspect(what='units', view='actions') lists the choices)",
                    "actions": A.promotion(uid)})
    for c in todo.get("cities") or []:
        cid = c.get("id") if isinstance(c, dict) else c
        out.append({"kind": "city_production", "id": cid, "name": (c.get("name") if isinstance(c, dict) else None) or names.get(cid),
                    "tool": "inspect(what='city', view='production') + order(to='city', action='produce')", "actions": A.city_production(cid)})
    for c in todo.get("starving") or []:
        # GitLab #101: a city losing food is a decision (the tile swap or the focus that ends it), not a notification
        if isinstance(c, dict) and c.get("id") is not None:
            out.append({"kind": "starving", "id": c["id"], "name": c.get("name"), "food_surplus": c.get("food_surplus"),
                        "tool": "inspect(what='city', view='screen') then order(to='city', action='governor' / 'work_plot')",
                        "actions": [R.act("city_screen", city_id=c["id"]), R.act("set_city_focus", city_id=c["id"], focus="food"),
                                    R.pick("change_working_plot", ["x", "y"], city_id=c["id"])]})
    for c in todo.get("city_strikes") or []:
        # a city that can fire this turn: the strike is free, and it was never a row (#101, about 40 turns of it)
        if isinstance(c, dict) and c.get("id") is not None:
            out.append({"kind": "city_strike", "id": c["id"], "name": c.get("name"), "targets": c.get("targets"),
                        "tool": "inspect(what='city', view='strikes') then order(to='city', action='strike')",
                        "actions": [R.act("available_city_strikes", city_id=c["id"]), R.pick("city_ranged_attack", ["x", "y"], city_id=c["id"])]})
    if todo.get("research_unset"):
        row = {"kind": "research", "tool": "inspect(what='options', view='research') + order(to='empire', action='research')", "actions": A.research()}
        if not cities:
            row["note"] = "research opens once the capital is founded: settle first"
        out.append(row)
    if todo.get("incoming_deal"):
        d = todo["incoming_deal"]
        out.append({"kind": "incoming_deal", "from": d.get("from") if isinstance(d, dict) else None,
                    "tool": "question() then answer(choice='accept' / 'refuse')", "actions": A.incoming_deal()})
    if todo.get("steal_tech"):
        out.append({"kind": "steal_tech", "detail": todo.get("steal_tech"), "tool": "question() + answer(choice=<tech>, args={player_id})",
                    "actions": A.steal_tech()})
    if todo.get("policy"):
        # the runtime's own check (culture >= cost, or a free policy), whichever blocker the engine reports first
        out.append({"kind": "policy", "detail": todo["policy"],
                    "tool": "inspect(what='options', view='policies') then order(to='empire', action='policy')", "actions": A.policy()})
    if todo.get("stacked") and ts.get("blocking_name") == "ENDTURN_BLOCKING_STACKED_UNITS":
        # The runtime lists every shared tile; only the engine's own blocker makes one a decision (a
        # warning otherwise: a worker beside a caravan is legal).
        row = {"kind": "stacked", "tiles": todo["stacked"], "tool": "order(to='unit', action='move') one unit with moves off each tile",
               "actions": A.stacked(todo["stacked"])}
        gps = [gp for t in todo["stacked"] if isinstance(t, dict) for gp in A.great_people_in(t.get("units") or [])]
        if gps:
            # GitLab #91 (Assyria t268, t270): a Great Person born on the city tile read as a movement chore
            row["note"] = ("a Great Person stands on the tile: its own mission (inspect(what='unit', id, view='actions') "
                           "lists them -- a great work, a bulb, a golden age, a citadel, a trade mission) clears the stack "
                           "as well as a move; the first rows are its choices")
            row["great_people"] = [{"id": gp.get("id"), "type": gp.get("type")} for gp in gps]
        out.append(row)
    for k, v in todo.items():
        if k in ("units", "promotions", "cities", "research_unset", "incoming_deal", "steal_tech", "ongoing",
                 "steal_tech_hint", "stacked", "policy", "religion", "league_proposal", "starving", "city_strikes"):
            continue
        if v:
            out.append({"kind": k, "detail": v})
    for p in ts.get("pending_popups") or []:
        # An announcement screen (tech award, wonder built, new era, golden age...) is swept by the next action
        # and nothing answers it: not a decision. Live 2026-09-27 (Grok, t53): BUTTONPOPUP_TECH_AWARD was listed
        # here and generic_popup({}) then said "no generic confirmation is open".
        name = p.get("name") if isinstance(p, dict) else p
        if name in _announcement_popups():
            continue
        out.append({"kind": "popup", "detail": p, "tool": "question() / answer(choice=<button>)", "actions": A.popup(name)})
    if todo.get("religion") in ("found", "enhance"):
        # A Prophet spent, the beliefs not chosen (#109): the same rows the popup would carry, whatever blocker
        # the engine names first.
        popup = "BUTTONPOPUP_ENHANCE_RELIGION" if todo["religion"] == "enhance" else "BUTTONPOPUP_FOUND_RELIGION"
        out.append({"kind": "religion", "detail": {"choice": todo["religion"]},
                    "tool": "order(to='empire', action='enhance_religion')" if todo["religion"] == "enhance"
                    else "order(to='empire', action='religion')", "actions": A.popup(popup)})
    if todo.get("league_proposal"):
        # The World Congress wants a proposal (#117): a hard block the engine may name only after production.
        out.append({"kind": "league_proposal", "detail": todo["league_proposal"],
                    "tool": "inspect(what='league') then order(to='league', action='propose' / 'repeal')",
                    "actions": [R.act("league_status", detail="compact"),
                                R.pick("league_propose_enact", ["resolution_type", "choice"]),
                                R.pick("league_propose_repeal", ["resolution_id"])]})
    name = ts.get("blocking_name")
    covered = {"ENDTURN_BLOCKING_UNITS": "unit_orders", "ENDTURN_BLOCKING_PRODUCTION": "city_production",
               "ENDTURN_BLOCKING_RESEARCH": "research", "ENDTURN_BLOCKING_UNIT_PROMOTION": "promotion",
               "ENDTURN_BLOCKING_STACKED_UNITS": "stacked", "ENDTURN_BLOCKING_POLICY": "policy",
               "ENDTURN_BLOCKING_FREE_POLICY": "policy", "ENDTURN_BLOCKING_STEAL_TECH": "steal_tech",
               "ENDTURN_BLOCKING_ENHANCE_RELIGION": "religion", "ENDTURN_BLOCKING_FOUND_RELIGION": "religion",
               "ENDTURN_BLOCKING_LEAGUE_CALL_FOR_PROPOSALS": "league_proposal",
               "ENDTURN_BLOCKING_CITY_RANGE_ATTACK": "city_strike"}
    if name and name != "NO_ENDTURN_BLOCKING_TYPE" and not any(r["kind"] == covered.get(name) for r in out):
        row = {"kind": "blocker", "name": name, "hint": ts.get("blocking_hint")}
        if name in gate.BLOCKER_QUESTIONS:
            # A question the engine raised without its popup (#95): question() reads it, answer(choice) takes it.
            row["actions"] = gate.blocker_rows(name)
        out.append(row)
    return out


def _announcement_popups() -> set:
    """The popup names whose screens the harness closes itself (Game._POPUP_CONTEXTS); imported late, game.py
    imports this module."""
    from .game import Game
    return set(Game._POPUP_CONTEXTS)


def _cap(rows: list, limit: int, more: str) -> dict:
    out: dict = {"rows": rows[:limit] if limit > 0 else []}
    if len(rows) > limit:
        out["omitted"] = len(rows) - max(0, limit)
        out["more"] = more
    return out


def city_rows(cities: list) -> list[dict]:
    """Cities worth a look this turn: nothing building, finishing next turn, starving or stalled, hurt."""
    rows = []
    for c in cities:
        if not isinstance(c, dict):
            continue
        why = []
        if c.get("needs_production") or not c.get("production"):
            why.append("no_production")
        elif isinstance(c.get("production_turns"), int) and c["production_turns"] <= 1:
            why.append("completes_next_turn")
        if c.get("growth") == "starving":
            why.append("starving")
        elif c.get("growth") == "growing" and c.get("growth_turns") == 1:
            why.append("grows_next_turn")
        if isinstance(c.get("hp"), int) and isinstance(c.get("max_hp"), int) and c["hp"] < c["max_hp"]:
            why.append("damaged")
        if c.get("razing"):
            why.append("razing")
        if why:
            row = {"id": c.get("id"), "name": c.get("name"), "pop": c.get("pop"), "production": c.get("production"),
                   "production_turns": c.get("production_turns"), "why": why}
            if "damaged" in why:
                row["hp"], row["max_hp"] = c.get("hp"), c.get("max_hp")
            rows.append(row)
    return rows


THREAT_DETAIL = ("compact", "full")
THREAT_BASIS = {
    "compact": "hostile combat units in sight within 4 plots of a city or 2 of a unit, nearest first; distances "
               "only, no combat odds; seen = in my previous briefing too (d: plots to my nearest unit or city, "
               "moved_from when it moved); detail='full' for whole rows",
    "full": "visible hostile combat units within 4 plots of a city or 2 of a unit; `assessment` is distance "
            "only, no combat estimate; seen = listed in my previous briefing too",
}


def _threat_distance(r: dict) -> int:
    return min((r.get("near_city") or {}).get("distance", 99), (r.get("near_unit") or {}).get("distance", 99))


def threat_rows(board: dict, prev: dict | None = None, detail: str = "compact") -> list[dict]:
    """The board's threats nearest first, each with its `assessment`. `prev` is what the previous briefing
    listed ({id: [x, y]}, from the baseline snapshot): a threat in it is marked `seen`. detail="compact"
    (#43) keeps unit, hp, x, y, the nearest own unit and city with their distances and the assessment
    (~110 B a row against ~250), and a seen threat that has not moved only its position, hp and distance."""
    rows = [dict(t) for t in board.get("threats") or [] if isinstance(t, dict)]
    prev = prev if isinstance(prev, dict) else {}
    for r in rows:
        dc = (r.get("near_city") or {}).get("distance")
        du = (r.get("near_unit") or {}).get("distance")
        if dc is not None and dc <= 1:
            r["assessment"] = f"adjacent to {r['near_city'].get('name')}"
        elif du is not None and du <= 1:
            r["assessment"] = f"adjacent to my {r['near_unit'].get('type')} {r['near_unit'].get('id')}"
        elif dc is not None and dc <= 2:
            r["assessment"] = f"can reach {r['near_city'].get('name')} next turn if it has 2+ moves"
        else:
            r["assessment"] = "in sight, not adjacent"
        if str(r.get("id")) in prev:
            r["seen"] = True
    rows.sort(key=_threat_distance)
    if detail == "full":
        return rows
    return [_compact_threat(r, prev.get(str(r.get("id")))) for r in rows]


def _compact_threat(r: dict, was: list | None) -> dict:
    row = {"id": r.get("id"), "unit": r.get("unit"), "hp": r.get("hp"), "x": r.get("x"), "y": r.get("y")}
    if r.get("owner") and r.get("owner") != "Barbarians":
        row["owner"] = r["owner"]   # a civilization's unit in sight is a different matter from a brute
    nc, nu = r.get("near_city") or {}, r.get("near_unit") or {}
    moved = isinstance(was, list) and len(was) >= 2 and [r.get("x"), r.get("y")] != list(was[:2])
    if r.get("seen") and not moved:
        row["seen"] = True
        d = _threat_distance(r)
        if d < 99:
            row["d"] = d
        return row
    near: dict = {}
    if nu:
        near["unit"], near["unit_d"] = nu.get("id"), nu.get("distance")
    if nc:
        near["city"], near["city_d"] = nc.get("name"), nc.get("distance")
    if near:
        row["near"] = near
    row["assessment"] = r.get("assessment")
    if r.get("seen"):
        row["seen"] = True
        row["moved_from"] = list(was[:2])
    return row


def opportunities(summary: dict, ts: dict) -> list[dict]:
    """Optional, not blocking: idle trade units and spies, free trade-route slots."""
    out = []
    for u in summary.get("idle_trade_units") or []:
        if isinstance(u, dict):
            # The hint names the arguments: live 2026-09-27 (Codex, t73) called available_trade_routes({}) and
            # establish_trade_route with target_x/target_y, and read two validation errors first.
            uid = u.get("unit_id", u.get("id"))   # the runtime's rows say unit_id (live t141: id came out null)
            row = {"kind": "idle_trade_unit", "id": uid, "type": u.get("type"),
                   "tool": f"inspect(what='options', view='trade_routes', id={uid}) then order(to='unit', id={uid}, "
                           "action='trade_route', args={dest_x, dest_y}) or args={city_name, kind}",
                   "actions": A.idle_trade_unit(uid)}
            if u.get("in_city") is False and u.get("hint"):
                row["hint"] = u["hint"]   # not in a city: it cannot take a route from where it stands
            out.append(row)
    for s in summary.get("idle_spies") or []:
        out.append({"kind": "idle_spy", "detail": s,
                    "tool": "inspect(what='options', view='spy_cities', id=<spy>) then order(to='spy', id=<spy>, action='move', args={target_player_id, target_city_id})",
                    "actions": A.idle_spy(s.get("agent_id") if isinstance(s, dict) else None)})
    if summary.get("trade_note"):
        row = {"kind": "free_trade_route_slots", "count": summary.get("free_trade_route_slots"),
               "detail": summary.get("trade_note")}
        if summary.get("trade_units_blocked"):
            # live t152: Venice read "4 free slots: build or buy" while the engine refused both kinds
            row["blocked"] = summary["trade_units_blocked"]
        out.append(row)
    return out


def warnings(ts: dict) -> list[dict]:
    """Facts that do not block the turn: status alerts, expiring deals, friendships and city-state allies."""
    out = [dict(a) for a in ts.get("alerts") or [] if isinstance(a, dict)]
    todo = ts.get("todo") if isinstance(ts.get("todo"), dict) else {}
    if todo.get("stacked") and ts.get("blocking_name") != "ENDTURN_BLOCKING_STACKED_UNITS":
        out.append({"kind": "stacked", "tiles": todo["stacked"], "note": "units sharing a tile; the engine does not block on it now"})
    for k in ("expiring_deals", "expiring_friendships", "expiring_city_states"):
        for row in ts.get(k) or []:
            if isinstance(row, dict) and row.get("renewed"):
                continue   # v258: a deal already renewed (turn_status still lists it, renewed_until) warns of nothing
            out.append({"kind": k, **row} if isinstance(row, dict) else {"kind": k, "detail": row})
    out.extend(war_warnings(ts))
    return out


def religion_warnings(board: dict) -> list[dict]:
    """The religion rows a human reads off the city banners (GitLab #112): a city of mine whose majority is not my
    religion (the holy city first -- a Prophet's enhancement and the founder beliefs depend on it), and another
    civ's Missionary or Prophet standing in my land."""
    rel = board.get("religion") if isinstance(board, dict) and isinstance(board.get("religion"), dict) else None
    if not rel:
        return []
    out: list[dict] = []
    for c in rel.get("cities") or []:
        if not isinstance(c, dict) or c.get("mine_majority") or c.get("id") is None:
            continue
        row = {"kind": "religion_lost", "id": c["id"], "name": c.get("name"), "majority": c.get("majority"),
               "mine": rel.get("mine"), "followers_mine": c.get("followers_mine"), "followers_majority": c.get("followers_majority"),
               "actions": [R.act("available_production", city_id=c["id"])]}
        if c.get("holy_city"):
            row["holy_city"] = True
            row["note"] = (f"the holy city of {rel.get('mine')} follows {c.get('majority')}: a Prophet cannot enhance there and the "
                           "founder beliefs weaken; an Inquisitor (faith, order(to='city', action='purchase')) sent in with "
                           "MISSION_REMOVE_HERESY, or a Missionary's MISSION_SPREAD_RELIGION, wins it back")
        else:
            row["note"] = (f"{c.get('name')} follows {c.get('majority')}, not {rel.get('mine')}: an Inquisitor's MISSION_REMOVE_HERESY "
                           "or a Missionary's MISSION_SPREAD_RELIGION wins it back")
        out.append(row)
    out.sort(key=lambda r: not r.get("holy_city"))
    for u in rel.get("foreign_religious_units") or []:
        if isinstance(u, dict):
            out.append({"kind": "religious_unit_in_my_land", **u,
                        "note": "another civ's religious unit stands in my land: a conversion is coming; an Inquisitor "
                                "garrisoned in the city blocks it, open borders can be refused"})
    return out


def war_warnings(ts: dict) -> list[dict]:
    """One `at_war` row per major civ this seat fights, saying whether peace can be asked for now -- what the
    leader screen's Negotiate Peace button shows a human every time they open it. Live 2026-10-08: England sat
    twenty turns in a siege while all three enemies would have taken a white peace on the first ask, and no read
    said so. City-states at war ride on one row (their peace is city_state_action)."""
    wars = ts.get("wars") if isinstance(ts.get("wars"), dict) else {}
    out: list[dict] = []
    for row in wars.get("majors") or []:
        if not isinstance(row, dict):
            continue
        peace = row.get("peace") if isinstance(row.get("peace"), dict) else {}
        pid = row.get("player_id")
        r = {"kind": "at_war", "civ": row.get("civ"), "leader": row.get("leader"), "player_id": pid,
             "peace_possible": peace.get("ok")}
        if peace.get("ok"):
            r["hint"] = (f"order(to='civ', action='peace', id={pid}) offers a white peace through the real leader screen and the AI answers "
                         "at once (items add terms); inspect(what='civ', view='trade_catalog', id=<player>).peace is the full gate")
        else:
            r["peace_note"] = peace.get("note")
            if peace.get("locked_turns"):
                r["locked_turns"] = peace["locked_turns"]
        out.append(r)
    minors = [m for m in wars.get("minors") or [] if isinstance(m, dict)]
    if minors:
        out.append({"kind": "at_war_city_states", "count": len(minors),
                    "civs": [{"civ": m.get("civ"), "player_id": m.get("player_id")} for m in minors],
                    "hint": "inspect(what='city_state', id, view='summary') says whether peace is offered; "
                            "order(to='city_state', id, action='make_peace') presses it; a peace with their ally's civ takes them along"})
    return out


#: The prose `tools` map is on its way out: every row carries its calls.
TOOLS_NOTE = "prose, retired in 2.0.0: each decisions / opportunities row carries `actions` rows for batch(actions=[...])"


def build(ts: dict, summary: dict, cities: list, units: list, board: dict, baseline: dict, prev: dict | None,
          events: list | None, limit: int, include_rules: bool, detail: str = "compact") -> tuple[dict, dict]:
    """(briefing, snapshot): the briefing dict (seat, gate, notes, assignments and orders are added by the
    caller) and the baseline the next briefing compares against. `detail` is the threat row form
    (THREAT_DETAIL)."""
    snap = snapshot(ts.get("turn"), summary, cities, units, board.get("event_seq"),
                    board.get("territory") if isinstance(board.get("territory"), list) else None)
    todo = ts.get("todo") if isinstance(ts.get("todo"), dict) else {}
    dec = decisions(ts, cities)
    opp = opportunities(summary, ts)
    # The sentence is the same for every row of a kind (twelve idle units, one sentence): said once, in `tools`.
    # It stays one release beside the rows (#45): the rows are what a model copies, the sentence what the
    # playbook taught before 2.0.0.
    tools: dict[str, str] = {}
    for row in dec + opp:
        if row.get("tool"):
            tools[row["kind"]] = row.pop("tool")
    out: dict = {
        "turn": ts.get("turn"),
        "baseline": baseline,
        "decisions": dec,
        "decisions_total": len(dec),
    }
    w = warnings(ts)
    if w:
        out["warnings"] = w
    if opp:
        out["opportunities"] = opp
    if tools:
        out["tools"] = tools
        out["tools_note"] = TOOLS_NOTE
    changes: dict = {}
    if baseline.get("comparable") and isinstance(prev, dict):
        changes.update(compare(prev, snap))
        t = changes.get("territory")
        if isinstance(t, dict) and len(t.get("gained") or []) > limit:
            # Every lost plot is listed (a loss is rare and each row matters); border growth is capped.
            gained = t["gained"]
            t["gained"] = gained[:limit]
            t["gained_omitted"] = {"count": len(gained) - limit, "more": "inspect(what='map', view='window', x, y) around the city shows the border"}
    if events is not None:
        changes["events"] = summarize_events(events, limit)
    if changes:
        out["changes"] = changes
    empire = {k: summary.get(k) for k in EMPIRE_KEYS + EMPIRE_EXTRA if summary.get(k) is not None}
    out["empire"] = empire
    cr = city_rows(cities)
    out["cities"] = {"total": len(cities), **_cap(cr, limit, "inspect(what='cities') for every city, inspect(what='city', id, view='screen') for one")}
    by_type: dict[str, int] = {}
    for u in units:
        if isinstance(u, dict):
            by_type[str(u.get("type"))] = by_type.get(str(u.get("type")), 0) + 1
    attention = [{"id": u.get("id"), "type": u.get("type"), "x": u.get("x"), "y": u.get("y"),
                  "attention": u.get("attention")}
                 for u in todo.get("ongoing") or [] if isinstance(u, dict) and u.get("attention")]
    damaged = [{"id": u.get("id"), "type": u.get("type"), "hp": u.get("hp"), "max_hp": u.get("max_hp"),
                "x": u.get("x"), "y": u.get("y")}
               for u in units if isinstance(u, dict) and isinstance(u.get("hp"), int) and isinstance(u.get("max_hp"), int)
               and u["hp"] < u["max_hp"]]
    out["units"] = {"total": len(units), "by_type": by_type,
                    "ongoing": len(todo.get("ongoing") or []),
                    "attention": _cap(attention, limit, "turn(action='status') todo.ongoing")["rows"],
                    "damaged": _cap(damaged, limit, "inspect(what='units')")}
    prev_threats = prev.get("threats") if baseline.get("comparable") and isinstance(prev, dict) else None
    tr = threat_rows(board, prev_threats, detail)
    out["threats"] = {"total": len(tr), **_cap(tr, limit, "inspect(what='units') / inspect(what='map', view='window', x, y) around the city for the rest"),
                      "basis": THREAT_BASIS.get(detail, THREAT_BASIS["compact"])}
    # What this briefing listed, so the next one can mark a threat still in sight as seen (#43).
    snap["threats"] = {str(r.get("id")): [r.get("x"), r.get("y")] for r in out["threats"]["rows"]}
    camps = board.get("camps") or []
    if camps:
        out["threats"]["camps"] = camps[:limit]
    rw = religion_warnings(board)
    if rw:
        out.setdefault("warnings", []).extend(rw)   # #112
    for t in (board.get("culture_threats") if isinstance(board, dict) else None) or []:
        if isinstance(t, dict):
            # #88: a civ one civilization short of a culture victory, and whether this seat is the one it needs
            on_me = t.get("on_me") if isinstance(t.get("on_me"), dict) else {}
            out.setdefault("warnings", []).append({
                "kind": "culture_victory_threat", **t,
                "note": (f"{t.get('civ')} is influential on {t.get('influential_on')} of {t.get('needed')} civilizations: one more "
                         f"wins it the game. On you: {on_me.get('level')}, {on_me.get('trend')}, turns to influential: "
                         f"{on_me.get('turns_to_influential')}. Your own culture per turn is the defence (inspect(what='screen', view='culture'))")})
    if include_rules and board.get("traits"):
        out["civ_rules"] = board["traits"]
    return out, snap
