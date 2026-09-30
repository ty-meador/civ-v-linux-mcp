// What the page knows about the game: the static map, the latest snapshot, the notebooks, and who the seats are.
import { SEAT_HUES } from "./palette.js";

export class World {
  constructor() {
    this.map = null;             // hello.map: w, h, wrap, layers{terrain,elev,feature,river,resource}, legend
    this.snapshot = null;        // players, cities, units, owners, turn, active, over
    this.players = new Map();    // id -> player row
    this.units = new Map();      // id -> unit row
    this.cities = new Map();     // id -> city row
    this.notebooks = new Map();  // seat -> {notes, assignments, orders}
    this.seats = [];             // seat ids in the order first seen in the ledger
  }

  get w() { return this.map ? this.map.w : 0; }
  get h() { return this.map ? this.map.h : 0; }

  // A plot's static description from the character grids (north row first).
  plot(x, y) {
    const L = this.map.layers, row = this.h - 1 - y;
    const g = (name) => (L[name] && L[name][row]) ? L[name][row][x] : " ";
    const f = g("feature"), r = g("resource");
    return { terrain: g("terrain"), elev: g("elev"), river: g("river") === "r",
             feature: f === "." || f === " " ? null : (this.map.legend.feature || {})[f] || null,
             resource: r === "." || r === " " ? null : (this.map.legend.resource || {})[r] || null };
  }

  ownerAt(x, y) {
    const o = this.snapshot && this.snapshot.owners;
    if (!o || !o.rows) return -1;
    const ch = o.rows[this.h - 1 - y] ? o.rows[this.h - 1 - y][x] : ".";
    return ch === "." ? -1 : (o.legend[ch] ?? -1);
  }

  setMap(map) { this.map = map; }

  setSnapshot(s) {
    this.snapshot = s;
    this.players = new Map(s.players.map((p) => [p.id, p]));
    this.units = new Map(s.units.map((u) => [u.id, u]));
    this.cities = new Map(s.cities.map((c) => [c.id, c]));
    for (const p of s.players) if (p.human && !p.barb && p.alive) this.noteSeat(p.id);
  }

  setNotebook(rec) { this.notebooks.set(rec.seat, rec); this.noteSeat(rec.seat); }

  noteSeat(seat) {
    if (Number.isInteger(seat) && !this.seats.includes(seat)) this.seats.push(seat);
  }

  hue(seat) { const i = this.seats.indexOf(seat); return SEAT_HUES[(i < 0 ? 0 : i) % SEAT_HUES.length]; }

  playerName(id) {
    const p = this.players.get(id);
    return p ? (p.civ || p.name || `#${id}`) : `#${id}`;
  }

  // Where a ledger row's ids point right now: unit ids first, then city ids.
  positionsOf(refs) {
    const out = [];
    for (const id of (refs && refs.unit_id) || []) { const u = this.units.get(id); if (u) out.push([u.x, u.y]); }
    for (const id of (refs && refs.city_id) || []) { const c = this.cities.get(id); if (c) out.push([c.x, c.y]); }
    return out;
  }

  unitLabel(id) {
    const u = this.units.get(id);
    return u ? `${titleCase(u.t)} #${id}` : `unit #${id}`;
  }
  cityLabel(id) {
    const c = this.cities.get(id);
    return c ? c.n || `city #${id}` : `city #${id}`;
  }
}

export function titleCase(s) {
  return (s || "").toLowerCase().replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
