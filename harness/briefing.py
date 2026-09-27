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
"""
from __future__ import annotations

from typing import Any

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


def snapshot(turn: int | None, summary: dict, cities: list, units: list, event_seq: int | None) -> dict:
    """What the next briefing compares against."""
    return {
        "turn": turn,
        "event_seq": event_seq,
        "empire": {k: summary.get(k) for k in EMPIRE_KEYS if _num(summary.get(k)) is not None},
        "cities": {str(c.get("id")): {"name": c.get("name"), "pop": c.get("pop"), "production": c.get("production")}
                   for c in cities if isinstance(c, dict) and c.get("id") is not None},
        "units": {str(u.get("id")): u.get("type") for u in units if isinstance(u, dict) and u.get("id") is not None},
    }


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
    if added:
        units["new"] = added
    if lost:
        units["gone"] = lost
        units["gone_note"] = ("not on the unit list any more: killed, captured, disbanded, upgraded (new id), "
                              "consumed (settler, great person, a caravan whose route started); the events say which")
    if units:
        out["units"] = units
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
        out["more"] = "briefing(since='turn', limit=N) repeats this turn's events; notification_log() has every notice"
    return out


def decisions(ts: dict, cities: list) -> list[dict]:
    """Every mandatory item of the turn, each with the entity id and the tool that clears it. Never capped."""
    out: list[dict] = []
    todo = ts.get("todo") if isinstance(ts.get("todo"), dict) else {}
    names = {c.get("id"): c.get("name") for c in cities if isinstance(c, dict)}
    for u in todo.get("units") or []:
        if not isinstance(u, dict):
            continue
        row = {"kind": "unit_orders", "id": u.get("id"), "type": u.get("type"), "x": u.get("x"), "y": u.get("y"),
               "moves": u.get("moves"), "tool": "todo_actions(detail='summary') then move_unit / unit_mission"}
        if u.get("stalled_mission"):
            row["note"] = u.get("note")
        out.append(row)
    for uid in todo.get("promotions") or []:
        out.append({"kind": "promotion", "id": uid, "tool": "choose_promotion (todo_actions lists the choices)"})
    for c in todo.get("cities") or []:
        cid = c.get("id") if isinstance(c, dict) else c
        out.append({"kind": "city_production", "id": cid, "name": (c.get("name") if isinstance(c, dict) else None) or names.get(cid),
                    "tool": "available_production + set_production"})
    if todo.get("research_unset"):
        out.append({"kind": "research", "tool": "available_research + set_research"})
    if todo.get("incoming_deal"):
        d = todo["incoming_deal"]
        out.append({"kind": "incoming_deal", "from": d.get("from") if isinstance(d, dict) else None,
                    "tool": "incoming_deal then accept_deal / refuse_deal"})
    if todo.get("steal_tech"):
        out.append({"kind": "steal_tech", "detail": todo.get("steal_tech"), "tool": "steal_tech_options + steal_tech"})
    if todo.get("stacked") and ts.get("blocking_name") == "ENDTURN_BLOCKING_STACKED_UNITS":
        # The runtime lists every shared tile; only the engine's own blocker makes one a decision (a
        # warning otherwise: a worker beside a caravan is legal).
        out.append({"kind": "stacked", "tiles": todo["stacked"], "tool": "move_unit one unit with moves off each tile"})
    for k, v in todo.items():
        if k in ("units", "promotions", "cities", "research_unset", "incoming_deal", "steal_tech", "ongoing",
                 "steal_tech_hint", "stacked"):
            continue
        if v:
            out.append({"kind": k, "detail": v})
    for p in ts.get("pending_popups") or []:
        out.append({"kind": "popup", "detail": p, "tool": "generic_popup / answer_popup"})
    name = ts.get("blocking_name")
    covered = {"ENDTURN_BLOCKING_UNITS": "unit_orders", "ENDTURN_BLOCKING_PRODUCTION": "city_production",
               "ENDTURN_BLOCKING_RESEARCH": "research", "ENDTURN_BLOCKING_UNIT_PROMOTION": "promotion",
               "ENDTURN_BLOCKING_STACKED_UNITS": "stacked"}
    if name and name != "NO_ENDTURN_BLOCKING_TYPE" and not any(r["kind"] == covered.get(name) for r in out):
        out.append({"kind": "blocker", "name": name, "hint": ts.get("blocking_hint")})
    return out


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


def threat_rows(board: dict) -> list[dict]:
    rows = [dict(t) for t in board.get("threats") or [] if isinstance(t, dict)]
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
    return sorted(rows, key=lambda r: min((r.get("near_city") or {}).get("distance", 99),
                                          (r.get("near_unit") or {}).get("distance", 99)))


def opportunities(summary: dict, ts: dict) -> list[dict]:
    """Optional, not blocking: idle trade units and spies, free trade-route slots."""
    out = []
    for u in summary.get("idle_trade_units") or []:
        if isinstance(u, dict):
            # The hint names the arguments: live 2026-09-27 (Codex, t73) called available_trade_routes({}) and
            # establish_trade_route with target_x/target_y, and read two validation errors first.
            out.append({"kind": "idle_trade_unit", "id": u.get("id"), "type": u.get("type"),
                        "tool": f"available_trade_routes(unit_id={u.get('id')}) then establish_trade_route(unit_id, "
                                "dest_x, dest_y) or establish_trade_route(unit_id, city_name, kind)"})
    for s in summary.get("idle_spies") or []:
        out.append({"kind": "idle_spy", "detail": s, "tool": "available_spy_cities(agent_id) then move_spy(agent_id, target_player_id, target_city_id)"})
    if summary.get("trade_note"):
        out.append({"kind": "free_trade_route_slots", "count": summary.get("free_trade_route_slots"),
                    "detail": summary.get("trade_note")})
    return out


def warnings(ts: dict) -> list[dict]:
    """Facts that do not block the turn: status alerts, expiring deals, friendships and city-state allies."""
    out = [dict(a) for a in ts.get("alerts") or [] if isinstance(a, dict)]
    todo = ts.get("todo") if isinstance(ts.get("todo"), dict) else {}
    if todo.get("stacked") and ts.get("blocking_name") != "ENDTURN_BLOCKING_STACKED_UNITS":
        out.append({"kind": "stacked", "tiles": todo["stacked"], "note": "units sharing a tile; the engine does not block on it now"})
    for k in ("expiring_deals", "expiring_friendships", "expiring_city_states"):
        for row in ts.get(k) or []:
            out.append({"kind": k, **row} if isinstance(row, dict) else {"kind": k, "detail": row})
    return out


def build(ts: dict, summary: dict, cities: list, units: list, board: dict, baseline: dict, prev: dict | None,
          events: list | None, limit: int, include_rules: bool) -> tuple[dict, dict]:
    """(briefing, snapshot): the briefing dict (seat, gate and notes are added by the caller) and the baseline
    the next briefing compares against."""
    snap = snapshot(ts.get("turn"), summary, cities, units, board.get("event_seq"))
    todo = ts.get("todo") if isinstance(ts.get("todo"), dict) else {}
    dec = decisions(ts, cities)
    opp = opportunities(summary, ts)
    # The tool is the same for every row of a kind (twelve idle units, one sentence): said once, in `tools`.
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
    changes: dict = {}
    if baseline.get("comparable") and isinstance(prev, dict):
        changes.update(compare(prev, snap))
    if events is not None:
        changes["events"] = summarize_events(events, limit)
    if changes:
        out["changes"] = changes
    empire = {k: summary.get(k) for k in EMPIRE_KEYS + EMPIRE_EXTRA if summary.get(k) is not None}
    out["empire"] = empire
    cr = city_rows(cities)
    out["cities"] = {"total": len(cities), **_cap(cr, limit, "cities() for every city, city_screen(city_id) for one")}
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
                    "attention": _cap(attention, limit, "turn_status todo.ongoing")["rows"],
                    "damaged": _cap(damaged, limit, "units()")}
    tr = threat_rows(board)
    out["threats"] = {"total": len(tr), **_cap(tr, limit, "units() / map_window around the city for the rest"),
                      "basis": "visible hostile combat units within 4 plots of a city or 2 of a unit; "
                               "`assessment` is distance only, no combat estimate"}
    camps = board.get("camps") or []
    if camps:
        out["threats"]["camps"] = camps[:limit]
    if include_rules and board.get("traits"):
        out["civ_rules"] = board["traits"]
    return out, snap
