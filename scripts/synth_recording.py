#!/usr/bin/env python3
"""Write a synthetic spectator recording for any map size, to measure the page against (CANVAS_MIGRATION phase 0).

    python scripts/synth_recording.py --size 200x120 --out logs/synth_200x120.jsonl
    python -m harness.spectator --replay logs/synth_200x120.jsonl --port 8771

The file is what `--record` would have written: a `hello` with a generated map of the requested shape (continents,
latitude bands, hills, mountains, forests, resources, rivers, every legend the page reads), then `--snapshots`
snapshots 8 s apart (players: `--seats` humans and `--ai` AI civs plus the barbarians; `--cities` cities with
borders around them; `--units` units that drift a plot per snapshot; a fog grid per human seat around its own
pieces) with ledger `call` rows between them -- a briefing, tactical views (`seen` rings, `refs`), moves
(`intent`), a finish_turn `wait` -- and a leader_message event now and then. Nothing in it comes from a game;
the shapes match the 2026-09-30 recording's rows so the page draws it the same way.
"""
from __future__ import annotations

import argparse
import json
import random
import time

TERRAIN = {"O": "Ocean", "C": "Coast", "L": "Lake", "G": "Grassland", "P": "Plains", "D": "Desert", "T": "Tundra", "S": "Snow"}
ELEV = {"M": "mountain", "^": "hills", ".": "flat"}
FEATURE = {"a": "ICE", "b": "FOREST", "c": "FLOOD_PLAINS", "f": "OASIS", "g": "MARSH", "h": "JUNGLE", "e": "ATOLL"}
RESOURCE = {"a": "FISH", "b": "IRON", "d": "DEER", "e": "GOLD", "f": "SHEEP", "h": "HORSE", "l": "BISON",
            "o": "WHEAT", "r": "COW", "u": "STONE", "w": "MARBLE", "x": "COPPER", "E": "WINE", "G": "SPICES"}
UNIT_TYPES = ["WARRIOR", "ARCHER", "SCOUT", "WORKER", "SPEARMAN", "SWORDSMAN", "CHARIOT_ARCHER", "CATAPULT", "SETTLER", "CARAVAN"]
SEA_TYPES = ["TRIREME", "GALLEASS", "CARGO_SHIP"]
CITY_NAMES = ["Alba", "Brae", "Cairn", "Dun", "Esk", "Firth", "Glen", "Holm", "Inch", "Kyle", "Loch", "Moss", "Ness", "Orme",
              "Pen", "Quay", "Rath", "Strath", "Tarn", "Ure", "Vale", "Wick", "Yare", "Zeal"]


def cube(x: int, y: int) -> tuple[int, int, int]:
    q = x - (y - (y & 1)) // 2
    return q, y, -q - y


def dist(x0: int, y0: int, x1: int, y1: int, w: int) -> int:
    def plain(ax, ay, bx, by):
        a, b = cube(ax, ay), cube(bx, by)
        return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))
    return min(plain(x0, y0, x1 - w, y1), plain(x0, y0, x1, y1), plain(x0, y0, x1 + w, y1))


def noise(w: int, h: int, cell: int, rng: random.Random) -> list[list[float]]:
    """Value noise: a coarse random lattice, bilinear between its points (x wraps)."""
    gw, gh = w // cell + 2, h // cell + 2
    lat = [[rng.random() for _ in range(gw)] for _ in range(gh)]
    out = []
    for y in range(h):
        gy, fy = divmod(y / cell, 1)
        gy = int(gy)
        row = []
        for x in range(w):
            gx, fx = divmod(x / cell, 1)
            gx = int(gx)
            a = lat[gy][gx % gw] * (1 - fx) + lat[gy][(gx + 1) % gw] * fx
            b = lat[gy + 1][gx % gw] * (1 - fx) + lat[gy + 1][(gx + 1) % gw] * fx
            row.append(a * (1 - fy) + b * fy)
        out.append(row)
    return out


def make_map(w: int, h: int, rng: random.Random) -> dict:
    """Layers as the page reads them: row 0 is the north edge (y = h-1); x along the row."""
    big, small = noise(w, h, max(8, w // 12), rng), noise(w, h, 4, rng)
    terrain = [["O"] * w for _ in range(h)]
    land = [[False] * w for _ in range(h)]
    for ry in range(h):
        lat = abs((ry / (h - 1)) * 2 - 1)                       # 0 at the equator, 1 at the poles
        for x in range(w):
            v = 0.7 * big[ry][x] + 0.3 * small[ry][x] - 0.25 * max(0.0, lat - 0.8) * 5
            land[ry][x] = v > 0.52
    for ry in range(h):
        lat = abs((ry / (h - 1)) * 2 - 1)
        for x in range(w):
            if not land[ry][x]:
                continue
            m = small[ry][x]
            if lat > 0.92: t = "S"
            elif lat > 0.78: t = "T" if m > 0.3 else "S"
            elif lat < 0.3 and m > 0.72: t = "D"
            elif m > 0.5: t = "P"
            else: t = "G"
            terrain[ry][x] = t
    for ry in range(h):
        for x in range(w):
            if land[ry][x]:
                continue
            near = any(land[ry + dy][(x + dx) % w] for dy in (-1, 0, 1) for dx in (-1, 0, 1) if 0 <= ry + dy < h)
            terrain[ry][x] = "C" if near else "O"
    elev = [["."] * w for _ in range(h)]
    feature = [["."] * w for _ in range(h)]
    resource = [["."] * w for _ in range(h)]
    river = [["."] * w for _ in range(h)]
    for ry in range(h):
        lat = abs((ry / (h - 1)) * 2 - 1)
        for x in range(w):
            t = terrain[ry][x]
            if t == "O" and lat > 0.95: feature[ry][x] = "a"
            if t == "C" and rng.random() < 0.02: feature[ry][x] = "e"
            if not land[ry][x]:
                if t == "C" and rng.random() < 0.06: resource[ry][x] = "a"
                continue
            r = rng.random()
            if r < 0.05: elev[ry][x] = "M"
            elif r < 0.18: elev[ry][x] = "^"
            if elev[ry][x] != "M":
                f = rng.random()
                if t in "GP" and f < 0.22: feature[ry][x] = "b"
                elif t == "G" and lat < 0.25 and f < 0.4: feature[ry][x] = "h"
                elif t == "G" and f < 0.26: feature[ry][x] = "g"
                elif t == "D" and f < 0.08: feature[ry][x] = "f"
                if rng.random() < 0.09: resource[ry][x] = rng.choice(list(RESOURCE))
            if elev[ry][x] == "^" and rng.random() < 0.3:         # a short river run downhill of some hills
                cx, cy = x, ry
                for _ in range(rng.randint(2, 6)):
                    if not (0 <= cy < h) or not land[cy][cx % w]: break
                    river[cy][cx % w] = "r"
                    cx, cy = cx + rng.choice((-1, 0, 1)), cy + rng.choice((0, 1))
    rows = lambda g: ["".join(r) for r in g]
    return {"ok": True, "w": w, "h": h, "wrap": True,
            "legend": {"terrain": TERRAIN, "elev": ELEV, "feature": FEATURE, "resource": RESOURCE},
            "layers": {"terrain": rows(terrain), "elev": rows(elev), "feature": rows(feature), "resource": rows(resource), "river": rows(river)}}, land


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--size", default="200x120", help="WxH plots")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seats", type=int, default=2)
    ap.add_argument("--ai", type=int, default=6)
    ap.add_argument("--units", type=int, default=600)
    ap.add_argument("--cities", type=int, default=80)
    ap.add_argument("--snapshots", type=int, default=6)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    w, h = (int(v) for v in a.size.lower().split("x"))
    rng = random.Random(a.seed)
    game_map, land = make_map(w, h, rng)
    land_plots = [(x, h - 1 - ry) for ry in range(h) for x in range(w) if land[ry][x]]      # (x, y) with y north-up
    sea_plots = [(x, h - 1 - ry) for ry in range(h) for x in range(w) if not land[ry][x] and game_map["layers"]["terrain"][ry][x] == "C"]
    rng.shuffle(land_plots)

    n_players = a.seats + a.ai
    players = []
    for pid in range(n_players):
        col = [rng.randint(40, 230) for _ in range(3)]
        players.append({"id": pid, "name": f"seat{pid}" if pid < a.seats else f"ai{pid}", "civ": f"Civ{pid}", "team": pid,
                        "human": pid < a.seats, "alive": True, "minor": False, "barb": False, "score": rng.randint(50, 400),
                        "gold": rng.randint(0, 900), "color": col, "color2": [255 - c for c in col]})
    players.append({"id": 63, "name": "Barbarians", "civ": "Barbarians", "team": 63, "human": False, "alive": True, "minor": False,
                    "barb": True, "score": 0, "gold": 0, "color": [120, 20, 20], "color2": [0, 0, 0]})

    cities, taken = [], set()
    for i in range(min(a.cities, len(land_plots))):
        x, y = land_plots[i]
        if any(dist(x, y, cx, cy, w) < 4 for cx, cy in taken): continue
        taken.add((x, y))
        o = i % n_players
        cities.append({"id": 8192 + i, "o": o, "x": x, "y": y, "n": f"{CITY_NAMES[i % len(CITY_NAMES)]} {i // len(CITY_NAMES) + 1}".strip(" 1") if i >= len(CITY_NAMES) else CITY_NAMES[i],
                       "pop": rng.randint(1, 14), "hp": 200, "cap": i < n_players, "puppet": False})
    units = []
    for i in range(a.units):
        at_sea = sea_plots and rng.random() < 0.12
        x, y = rng.choice(sea_plots) if at_sea else land_plots[(len(taken) + i) % len(land_plots)]
        o = 63 if rng.random() < 0.08 else i % n_players
        units.append({"id": 4096 + i, "o": o, "x": x, "y": y, "t": rng.choice(SEA_TYPES if at_sea else UNIT_TYPES),
                      "d": "S" if at_sea else "L", "hp": rng.randint(30, 100), "mhp": 100})

    def owners_rows() -> dict:
        legend = {chr(65 + i): i for i in range(n_players)}
        letter = {v: k for k, v in legend.items()}
        grid = [["."] * w for _ in range(h)]
        for c in cities:
            for dy in range(-2, 3):
                for dx in range(-3, 4):
                    x, y = (c["x"] + dx) % w, c["y"] + dy
                    if 0 <= y < h and dist(c["x"], c["y"], x, y, w) <= 2 and land[h - 1 - y][x]:
                        grid[h - 1 - y][x] = letter[c["o"]]
        return {"legend": legend, "rows": ["".join(r) for r in grid]}

    def fog_rows(seat: int, grow: int) -> list[str]:
        grid = [["."] * w for _ in range(h)]
        mine = [(p["x"], p["y"]) for p in cities + units if p["o"] == seat]
        for px, py in mine:
            for dy in range(-6 - grow, 7 + grow):
                for dx in range(-7 - grow, 8 + grow):
                    x, y = (px + dx) % w, py + dy
                    if not (0 <= y < h): continue
                    d = dist(px, py, x, y, w)
                    if d <= 3: grid[h - 1 - y][x] = "v"
                    elif d <= 6 + grow and grid[h - 1 - y][x] != "v": grid[h - 1 - y][x] = "f"
        return ["".join(r) for r in grid]

    seq = 0
    t0 = time.time() - 3600.0
    rows: list[dict] = []

    def push(type_: str, data: dict, t: float) -> None:
        nonlocal seq
        seq += 1
        rows.append({"seq": seq, "t": round(t, 3), "type": type_, "data": data})

    push("hello", {"map": game_map}, t0)
    t = t0 + 0.5
    turn = 100
    for i in range(a.snapshots):
        active = i % a.seats
        push("snapshot", {"ok": True, "over": False, "turn": turn, "active": active, "players": players, "cities": cities, "units": units,
                          "owners": owners_rows(), "fog": {str(s): fog_rows(s, i) for s in range(a.seats)}}, t)
        t += 0.4
        own = [u for u in units if u["o"] == active][:6]
        push("call", {"t": t, "seat": active, "tool": "briefing", "kind": "read", "bytes": 4000, "seconds": 0.5, "trips": 9, "ok": True,
                      "turn": turn, "scope": "broad", "args": '{"since":"turn"}'}, t)
        for u in own:
            t += 0.7
            ring = [[(u["x"] + dx) % w, u["y"] + dy] for dy in range(-2, 3) for dx in range(-2, 3)
                    if 0 <= u["y"] + dy < h and dist(u["x"], u["y"], (u["x"] + dx) % w, u["y"] + dy, w) <= 2]
            push("call", {"t": t, "seat": active, "tool": "tactical_view", "kind": "read", "bytes": 3000, "seconds": 0.13, "trips": 2, "ok": True,
                          "turn": turn, "scope": "focus", "args": json.dumps({"unit_id": u["id"], "radius": 2}), "seen": ring,
                          "refs": {"unit_id": [u["id"]]}}, t)
            t += 0.5
            nx, ny = (u["x"] + rng.choice((-1, 1))) % w, min(h - 1, max(0, u["y"] + rng.choice((-1, 0, 1))))
            push("call", {"t": t, "seat": active, "tool": "move_unit", "kind": "write", "bytes": 300, "seconds": 0.4, "trips": 3, "ok": True,
                          "turn": turn, "scope": "act", "args": json.dumps({"unit_id": u["id"], "x": nx, "y": ny}), "intent": [[nx, ny]],
                          "refs": {"unit_id": [u["id"]]}}, t)
            u["x"], u["y"] = nx, ny
        if i % 2 == 1:
            push("event", {"seq": i, "turn": turn, "kind": "leader_message", "audience": active,
                           "data": {"player": a.seats + (i % a.ai), "state": "DIPLO_UI_STATE_DEFAULT", "text": "A word with you, if you please."}}, t)
        t += 1.0
        push("call", {"t": t, "seat": active, "tool": "finish_turn", "kind": "wait", "bytes": 2500, "seconds": 6.0, "trips": 40, "ok": True,
                      "turn": turn, "scope": "broad", "args": "{}"}, t)
        t += 8.0
        if active == a.seats - 1: turn += 1
        for u in units:                                              # the world moves between snapshots
            if u["o"] != active and rng.random() < 0.5:
                u["x"] = (u["x"] + rng.choice((-1, 1))) % w
    with open(a.out, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, separators=(",", ":")) + "\n" for r in rows)
    land_n = len(land_plots)
    print(f"{a.out}: {w}x{h} ({w * h} plots, {land_n} land), {len(cities)} cities, {len(units)} units, {len(rows)} rows, "
          f"{sum(1 for r in rows if r['type'] == 'snapshot')} snapshots")


if __name__ == "__main__":
    main()
