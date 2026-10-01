// What the page knows about the game: the static map, the latest snapshot, the notebooks, and who the seats are.
import { SEAT_HUES } from "./palette.js";

export class World {
  constructor() {
    this.map = null;             // hello.map: w, h, wrap, layers{terrain,elev,feature,river,resource}, legend
    this.snapshot = null;        // players, cities, units, owners, fog, turn, active, over
    this.players = new Map();    // id -> player row
    this.units = new Map();      // "owner:id" -> unit row (Civ V unit and city ids are per player)
    this.cities = new Map();     // "owner:id" -> city row
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

  // A seat's own fog at a plot, as its screen draws it: "v" visible now, "f" seen before (fogged), "." never seen.
  // null when the snapshot holds no grid for that seat (not a human player, or a recording from before the grids).
  fogAt(seat, x, y) {
    const rows = this.snapshot && this.snapshot.fog && this.snapshot.fog[String(seat)];
    if (!Array.isArray(rows)) return null;
    const line = rows[this.h - 1 - y];
    return line ? (line[x] || ".") : ".";
  }
  hasFog(seat) { return this.fogAt(seat, 0, 0) !== null; }

  // A piece the seat's team owns is always on its screen, fog or not.
  sameTeam(seat, owner) {
    if (seat === owner) return true;
    const a = this.players.get(seat), b = this.players.get(owner);
    return !!a && !!b && Number.isInteger(a.team) && a.team === b.team;
  }

  setMap(map) { this.map = map; }

  setSnapshot(s) {
    this.snapshot = s;
    this.players = new Map(s.players.map((p) => [p.id, p]));
    this.units = new Map(s.units.map((u) => [`${u.o}:${u.id}`, u]));
    this.cities = new Map(s.cities.map((c) => [`${c.o}:${c.id}`, c]));
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

  // Where a seat's ledger row's ids point right now: its own unit ids first, then its city ids.
  positionsOf(refs, seat) {
    const out = [];
    for (const id of (refs && refs.unit_id) || []) { const u = this.units.get(`${seat}:${id}`); if (u) out.push([u.x, u.y]); }
    for (const id of (refs && refs.city_id) || []) { const c = this.cities.get(`${seat}:${id}`); if (c) out.push([c.x, c.y]); }
    return out;
  }

  unitLabel(id, seat) {
    const u = this.units.get(`${seat}:${id}`);
    return u ? `${titleCase(u.t)} #${id}` : `unit #${id}`;
  }
  cityLabel(id, seat) {
    const c = this.cities.get(`${seat}:${id}`);
    return c ? c.n || `city #${id}` : `city #${id}`;
  }
}

export function titleCase(s) {
  return (s || "").toLowerCase().replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
