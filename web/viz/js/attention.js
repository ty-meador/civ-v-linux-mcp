// Per-seat attention over the map: one bright pulse per touched plot that fades back to greyscale, acts that stay
// painted until the seat's turn ends, a low-opacity ghost of the previous seat's turn, and a heatmap that never
// resets. Time is the page's clock at arrival, so live and replay animate the same way.
export const PULSE_MS = 2600;         // a pulse is gone after this
export const BRIGHT = { focus: 1.0, broad: 0.38, act: 0.9 };
export const GHOST_ALPHA = 0.22;
export const HOLD_ALPHA = 0.78;

export class Attention {
  constructor() {
    this.pulses = new Map();   // seat -> Map(key -> {at, scope})
    this.holds = new Map();    // seat -> Map(key -> {intent: bool, at})
    this.ghost = new Map();    // seat -> Set(key)
    this.heat = new Map();     // seat -> Map(key -> count)
    this.current = null;       // the seat whose calls arrived last (whose turn it looks like)
    this.turnOf = new Map();   // seat -> ledger turn last seen
  }

  _m(map, seat) { if (!map.has(seat)) map.set(seat, new Map()); return map.get(seat); }

  // A ledger row arrived. `seen`/`intent` are key lists already wrapped onto the map.
  call(seat, row, seen, intent, now) {
    if (!Number.isInteger(seat)) return;
    // whoever was playing before this seat spoke has finished: their layers become their ghost
    if (this.current !== null && this.current !== seat) this.endTurn(this.current);
    if (row.kind === "wait") {                 // finish_turn returned: the seat's own new turn begins (hard cut)
      this.endTurn(seat);
      this.beginTurn(seat);
      this.current = seat;
      return;
    }
    if (this.current !== seat) { this.beginTurn(seat); this.current = seat; }
    if (Number.isInteger(row.turn)) this.turnOf.set(seat, row.turn);
    const scope = row.scope || (row.kind === "write" ? "act" : "broad");
    const pulses = this._m(this.pulses, seat), heat = this._m(this.heat, seat);
    for (const k of seen) {
      const prev = pulses.get(k);
      if (!prev || BRIGHT[scope] >= BRIGHT[prev.scope] || now - prev.at > PULSE_MS / 3) pulses.set(k, { at: now, scope });
      heat.set(k, (heat.get(k) || 0) + (scope === "focus" ? 2 : 1));
    }
    if (scope === "act") {
      const holds = this._m(this.holds, seat);
      for (const k of intent) { holds.set(k, { intent: true, at: now }); heat.set(k, (heat.get(k) || 0) + 3); }
      for (const k of seen) if (!holds.has(k)) holds.set(k, { intent: false, at: now });
    }
  }

  // The seat's turn is over: what it painted becomes its ghost, its live layers clear.
  endTurn(seat) {
    const g = new Set();
    for (const k of (this.pulses.get(seat) || new Map()).keys()) g.add(k);
    for (const k of (this.holds.get(seat) || new Map()).keys()) g.add(k);
    if (g.size) this.ghost.set(seat, g);
    this.pulses.set(seat, new Map());
    this.holds.set(seat, new Map());
  }

  // The seat's own turn begins: its ghost is gone (hard cut).
  beginTurn(seat) {
    this.ghost.delete(seat);
    this.pulses.set(seat, new Map());
    this.holds.set(seat, new Map());
  }

  // Anything still animating? (the renderer idles otherwise)
  live(now) {
    for (const m of this.pulses.values()) for (const p of m.values()) if (now - p.at < PULSE_MS) return true;
    return false;
  }

  // Layers to draw: [{key, seat, alpha, kind}] with kind pulse | hold | intent | ghost, for the seats in `seats`.
  layers(now, seats, { ghost = true } = {}) {
    const out = [];
    for (const seat of seats) {
      if (ghost) for (const k of this.ghost.get(seat) || []) out.push({ key: k, seat, alpha: GHOST_ALPHA, kind: "ghost" });
      for (const [k, h] of this.holds.get(seat) || []) out.push({ key: k, seat, alpha: HOLD_ALPHA, kind: h.intent ? "intent" : "hold" });
      for (const [k, p] of this.pulses.get(seat) || []) {
        const age = now - p.at;
        if (age >= PULSE_MS) continue;
        const t = age / PULSE_MS;
        const env = t < 0.12 ? t / 0.12 : Math.pow(1 - (t - 0.12) / 0.88, 1.6);   // quick up, slow fade
        out.push({ key: k, seat, alpha: BRIGHT[p.scope] * env, kind: "pulse" });
      }
    }
    return out;
  }

  heatLayers(seats) {
    const out = [];
    let max = 1;
    for (const seat of seats) for (const c of (this.heat.get(seat) || new Map()).values()) max = Math.max(max, c);
    for (const seat of seats) for (const [k, c] of this.heat.get(seat) || []) out.push({ key: k, seat, alpha: 0.15 + 0.7 * Math.sqrt(c / max) });
    return out;
  }
}
