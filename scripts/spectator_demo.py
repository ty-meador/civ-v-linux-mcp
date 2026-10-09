#!/usr/bin/env python3
"""Write a synthetic spectator recording so the visualization page can be developed and shown with no game running:

    python3 scripts/spectator_demo.py logs/demo.jsonl
    python -m harness.spectator --replay logs/demo.jsonl --speed 2

Two human seats on a small wrapped map take turns: broad scans, tactical views around their units, moves and orders,
notes and assignments, a few runtime events. Every row has the shape the real feed produces (harness/spectator/feed.py,
harness/attention.py), so what the page shows here is what it will show live. Deterministic (seeded).
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harness import call_ledger, hexgrid

W, H = 44, 26
SEATS = {0: {"name": "Wu Zetian", "civ": "China", "color": [0, 148, 82], "cx": 10, "cy": 12},
         1: {"name": "Genghis Khan", "civ": "Mongolia", "color": [81, 0, 122], "cx": 30, "cy": 13}}


def terrain(rng: random.Random) -> dict:
    layers = {k: [] for k in ("terrain", "elev", "feature", "river", "resource")}
    feats, res = {"a": "FOREST", "b": "JUNGLE", "c": "MARSH", "d": "ICE"}, {"a": "IRON", "b": "WHEAT", "c": "HORSE"}
    for y in range(H - 1, -1, -1):
        t, e, f, r, s = [], [], [], [], []
        for x in range(W):
            land = 6 <= y <= H - 7 and (4 <= x <= 18 or 24 <= x <= 40) and rng.random() > 0.08
            if y in (0, H - 1):
                t.append("O"); e.append("."); f.append("d"); r.append("."); s.append(".")
                continue
            if not land:
                coast = any(6 <= y + dy <= H - 7 and (4 <= x + dx <= 18 or 24 <= x + dx <= 40) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
                t.append("C" if coast else "O"); e.append("."); f.append("."); r.append("."); s.append(".")
                continue
            t.append(rng.choice("GGGPPDT"))
            e.append(rng.choice("......^^M"))
            f.append(rng.choice("......aab") if t[-1] in "GP" else ".")
            r.append("r" if rng.random() < 0.15 else ".")
            s.append(rng.choice(".........abc"))
        for k, v in (("terrain", t), ("elev", e), ("feature", f), ("river", r), ("resource", s)):
            layers[k].append("".join(v))
    return {"ok": True, "w": W, "h": H, "wrap": True, "layers": layers,
            "legend": {"feature": feats, "resource": res}}


REVEALED: dict[int, set] = {s: set() for s in SEATS}   # what each seat has ever seen, grown by every snapshot


def fog(seat: int, units: dict, cities: list) -> list[str]:
    """The seat's own fog, as the real snapshot's `fog` grid: sight 2 around its pieces, everything seen stays revealed."""
    visible = set()
    for piece in [*units.values(), *cities]:
        if piece["o"] == seat:
            visible.update((x % W, y) for x, y in hexgrid.disk(piece["x"], piece["y"], 2) if 0 <= y < H)
    REVEALED[seat] |= visible
    return ["".join("v" if (x, y) in visible else "f" if (x, y) in REVEALED[seat] else "." for x in range(W))
            for y in range(H - 1, -1, -1)]


def snapshot(turn: int, active: int, units: dict, cities: list, owners: dict) -> dict:
    rows = []
    for y in range(H - 1, -1, -1):
        rows.append("".join("AB"[owners[(x, y)]] if (x, y) in owners else "." for x in range(W)))
    return {"ok": True, "turn": turn, "active": active, "over": False,
            "players": [{"id": s, "name": v["name"], "civ": v["civ"], "human": True, "alive": True, "minor": False,
                         "barb": False, "team": s, "score": 100 + turn * (s + 1), "color": v["color"]} for s, v in SEATS.items()],
            "cities": cities, "units": list(units.values()),
            "owners": {"rows": rows, "legend": {"A": 0, "B": 1}},
            "fog": {str(s): fog(s, units, cities) for s in SEATS}}


def main(out: str) -> None:
    rng = random.Random(7)
    t0 = time.time() - 600
    t = t0
    evs: list[dict] = []
    seq = 0

    def push(type_: str, data: dict, dt: float = 0.0) -> None:
        nonlocal t, seq
        t += dt
        seq += 1
        evs.append({"seq": seq, "t": round(t, 3), "type": type_, "data": data})

    def call(seat: int, tool: str, args: dict, reply: dict, seconds: float, dt: float = 1.2, turn: int | None = None) -> dict:
        if turn is not None:
            reply = {**reply, "turn": turn}
        row = call_ledger.row(tool, seat, json.dumps(reply), seconds, 3, now=t + dt, args=args)
        push("call", row, dt)
        return row

    push("hello", {"map": terrain(rng)})
    units, cities, owners = {}, [], {}
    uid = 100
    for s, v in SEATS.items():
        cities.append({"id": s + 1, "o": s, "x": v["cx"], "y": v["cy"], "n": "Beijing" if s == 0 else "Karakorum", "pop": 4, "cap": True, "hp": 200})
        for p in hexgrid.disk(v["cx"], v["cy"], 2):
            owners[(p[0] % W, p[1])] = s
        for t_, dx, dy in (("WARRIOR", 2, 1), ("ARCHER", -2, 0), ("SETTLER", 1, -2), ("WORKER", 0, 1)):
            uid += 1
            units[uid] = {"id": uid, "o": s, "x": v["cx"] + dx, "y": v["cy"] + dy, "t": t_, "hp": 100, "mhp": 100,
                          "d": "L", **({"civ": True} if t_ in ("SETTLER", "WORKER") else {})}
    turn = 40
    pending: dict[int, tuple[int, float]] = {}
    push("snapshot", snapshot(turn, 0, units, cities, owners), 0.5)
    for s in SEATS:
        push("notebook", {"seat": s, "game": "demo", "notes": [{"id": 1, "turn": 38, "tag": "plan", "text": "Tradition, then a second city on the river."}],
                          "assignments": [{"id": 1, "role": "explore", "purpose": "map the coast west of the capital", "status": "active"}],
                          "orders": []}, 0.2)

    for rnd in range(4):
        for seat in (0, 1):
            v = SEATS[seat]
            mine = [u for u in units.values() if u["o"] == seat]
            if seat in pending:
                new_turn, ended = pending.pop(seat)
                push("call", call_ledger.row("finish_turn", seat, json.dumps({"ok": True, "status": {"turn": new_turn}}),
                                             t - ended, 40, now=t, args={}), 0.0)
            call(seat, "turn_status", {}, {"ok": True, "turn": turn, "todo": {}}, 0.4, dt=1.0, turn=turn)
            grid = ["#" * 12 + "~" * 6 + " " * (W - 18)] * 8 + [" " * W] * (H - 8)
            call(seat, "revealed_map", {"layers": ["vis"]}, {"ok": True, "w": W, "h": H, "window": {"x0": 0, "y0": 0, "x1": W - 1, "y1": H - 1},
                                                              "layers": {"vis": [(" " * (v["cx"] - 6) + g[:16])[:W].ljust(W) if i < 8 else g for i, g in
                                                                                 enumerate([grid[0]] * (H - v["cy"] - 5) + grid[:10] + [grid[-1]] * 40)][:H]}},
                 1.1, dt=1.5, turn=turn)
            for u in mine:
                if u["t"] in ("SETTLER", "WORKER"):
                    continue
                call(seat, "tactical_view", {"unit_id": u["id"], "radius": 2},
                     {"ok": True, "unit": {"id": u["id"], "x": u["x"], "y": u["y"], "type": u["t"]}, "neighbors": [], "units": []}, 0.9, dt=2.0, turn=turn)
                dx, dy = rng.choice([(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1)])
                nx, ny = (u["x"] + dx) % W, min(max(u["y"] + dy, 2), H - 3)
                call(seat, "move_unit", {"unit_id": u["id"], "x": nx, "y": ny},
                     {"ok": True, "moved": True, "at": {"x": nx, "y": ny}, "moves_left": 1}, 0.7, dt=1.6, turn=turn)
                u["x"], u["y"] = nx, ny
                push("snapshot", snapshot(turn, seat, units, cities, owners), 0.6)
            worker = next(u for u in mine if u["t"] == "WORKER")
            wx, wy = worker["x"] + 1, worker["y"]
            call(seat, "give_order", {"unit_id": worker["id"], "steps": [{"move": {"x": wx, "y": wy}}, {"build": "FARM", "x": wx, "y": wy}],
                                      "purpose": "farm the river tile by the capital"},
                 {"ok": True, "order_id": 3, "steps": 2}, 0.8, dt=1.4, turn=turn)
            call(seat, "city_screen", {"city_id": seat + 1},
                 {"ok": True, "name": cities[seat]["n"], "plots": [{"x": p[0] % W, "y": p[1], "worked": True} for p in hexgrid.disk(v["cx"], v["cy"], 1)]},
                 0.6, dt=1.3, turn=turn)
            call(seat, "set_production", {"city_id": seat + 1, "item": "BUILDING_MONUMENT"}, {"ok": True, "queued": "Monument", "turns": 6}, 0.5, dt=1.0, turn=turn)
            call(seat, "remember", {"text": f"t{turn}: the {'east' if seat else 'west'} coast is clear, push the settler north next turn.", "tag": "plan"},
                 {"ok": True, "id": 2 + rnd}, 0.1, dt=1.1, turn=turn)
            push("notebook", {"seat": seat, "game": "demo",
                              "notes": [{"id": 1, "turn": 38, "tag": "plan", "text": "Tradition, then a second city on the river."},
                                        {"id": 2 + rnd, "turn": turn, "tag": "plan", "text": f"t{turn}: the coast is clear, push the settler north next turn."}],
                              "assignments": [{"id": 1, "role": "explore", "purpose": "map the coast west of the capital", "status": "active"},
                                              {"id": 2, "role": "improve", "purpose": "farm the river tile by the capital", "status": "active"}],
                              "orders": []}, 0.2)
            if rnd == 2 and seat == 1:
                push("event", {"seq": 10 + rnd, "turn": turn, "audience": 0, "kind": "leader_message",
                               "data": {"from": 1, "text": "Your borders are too close to mine, Wu Zetian."}}, 0.3)
            push("event", {"seq": 20 + rnd * 2 + seat, "turn": turn, "audience": seat, "kind": "combat",
                           "data": {"attacker_type": "WARRIOR", "defender_type": "BRUTE", "damage": 27, "x": v["cx"] + 3, "y": v["cy"] - 1}}, 0.4)
            # the seat ends its turn now, but its finish_turn row only lands when the turn comes back, after the
            # other seat has played: it is pushed at the start of this seat's next turn
            pending[seat] = (turn + (1 if seat == 1 else 0), t)
            t += 4.0
            if seat == 1:
                turn += 1
                push("snapshot", snapshot(turn, 0, units, cities, owners), 0.5)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(e, separators=(",", ":")) + "\n" for e in evs)
    print(f"{out}: {len(evs)} events over {evs[-1]['t'] - evs[0]['t']:.0f} s of game time")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "logs/spectator_demo.jsonl")
