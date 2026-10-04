// The recording as the page holds it, and a player that walks it on the page's own clock.
//
// Timeline: every event the page has seen -- the /recording file, then the SSE tail -- in seq order, deduped by
// seq. Each row gets `tm`, a time that never goes back (a ledger row's `t` is the call's own time, which can be
// earlier than the snapshot pushed before it), so a position on the slider is one count of rows.
// Player: a cursor (rows applied) and a clock (recording time). Playing advances the clock at `speed` and applies
// the rows that fall due; silence longer than MAX_GAP is skipped. A seek applies the rows between (forward) or
// rebuilds from the start (backward). `following` means the cursor sits at the tail of a live stream and new
// rows apply as they arrive, as the page did before it had a scrubber.
// No DOM in here: tests run it under node.
export const MAX_GAP = 20;           // seconds of recorded silence the player jumps over

export class Timeline {
  constructor() { this.rows = []; this.last = 0; }

  // Keep a row the page has not seen (seq beyond the last). Returns whether it was kept.
  add(ev) {
    if (!ev || !Number.isInteger(ev.seq) || ev.seq <= this.last) return false;
    const t = typeof ev.t === "number" ? ev.t : (this.rows.length ? this.rows[this.rows.length - 1].tm : 0);
    ev.tm = this.rows.length ? Math.max(t, this.rows[this.rows.length - 1].tm) : t;
    this.rows.push(ev);
    this.last = ev.seq;
    return true;
  }

  get length() { return this.rows.length; }
  get t0() { return this.rows.length ? this.rows[0].tm : 0; }
  get t1() { return this.rows.length ? this.rows[this.rows.length - 1].tm : 0; }

  // How many rows fall at or before recording time `t`.
  countAt(t) {
    let lo = 0, hi = this.rows.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (this.rows[mid].tm <= t) lo = mid + 1; else hi = mid; }
    return lo;
  }

  // The turn boundaries: every snapshot whose turn or active player differs from the snapshot before it.
  turns() {
    const out = [];
    let prev = null;
    for (const r of this.rows) {
      if (r.type !== "snapshot") continue;
      const d = r.data || {};
      if (!prev || d.turn !== prev.turn || d.active !== prev.active) out.push({ t: r.tm, turn: d.turn, active: d.active, seq: r.seq });
      prev = d;
    }
    return out;
  }
}

export class Player {
  // hooks: apply(row, arrivedMs, jump) paints one row (jump: part of a seek, no captions, panels later);
  //        reset() clears the page's world for a rebuild; settled() repaints after a seek; changed() after any move.
  constructor(timeline, hooks, { mode = "live", now = () => Date.now() } = {}) {
    this.tl = timeline;
    this.hooks = hooks;
    this.mode = mode;                 // "live": the tail grows and can be followed; "replay": the file is all there is
    this.now = now;
    this.cursor = 0;                  // rows applied
    this.clock = timeline.t0;         // recording time the page shows
    this.speed = 1;
    this.playing = false;
    this.following = false;
    this.lastTick = null;
  }

  state() {
    return { cursor: this.cursor, clock: this.clock, t0: this.tl.t0, t1: this.tl.t1, length: this.tl.length,
             playing: this.playing, speed: this.speed, following: this.following, mode: this.mode };
  }

  _changed() { if (this.hooks.changed) this.hooks.changed(this.state()); }

  // Move to recording time `t`: forward applies the rows in between, backward rebuilds from the first row.
  seek(t) {
    const rows = this.tl.rows;
    t = Math.min(Math.max(t, this.tl.t0), this.tl.t1);
    const n = this.tl.countAt(t);
    const nowMs = this.now();
    let from = this.cursor;
    if (n < this.cursor) { this.hooks.reset(); from = 0; }
    for (let i = from; i < n; i++) this.hooks.apply(rows[i], nowMs - (t - rows[i].tm) * 1000, true);
    this.cursor = n;
    this.clock = t;
    this.following = this.mode === "live" && n === rows.length;
    this.lastTick = nowMs;
    if (this.hooks.settled) this.hooks.settled();
    this._changed();
  }

  toStart() { this.seek(this.tl.t0); }
  toEnd() { this.seek(this.tl.t1); }

  play() { if (this.cursor >= this.tl.length && this.mode === "replay") this.toStart(); this.playing = true; this.lastTick = this.now(); this._changed(); }
  pause() { this.playing = false; this._changed(); }
  toggle() { if (this.playing) this.pause(); else this.play(); }
  setSpeed(s) { this.speed = s > 0 ? s : 1; this._changed(); }

  // The clock ticks: apply what fell due. Nothing to do while following (the tail applies itself in push()).
  step(nowMs = this.now()) {
    if (!this.playing || this.following) { this.lastTick = nowMs; return; }
    const rows = this.tl.rows;
    const dt = this.lastTick === null ? 0 : (nowMs - this.lastTick) / 1000 * this.speed;
    this.lastTick = nowMs;
    let clock = this.clock + dt;
    if (this.cursor < rows.length && rows[this.cursor].tm - this.clock > MAX_GAP) clock = rows[this.cursor].tm;   // skip silence
    let applied = 0;
    while (this.cursor < rows.length && rows[this.cursor].tm <= clock) { this.hooks.apply(rows[this.cursor], nowMs, false); this.cursor++; applied++; }
    this.clock = Math.min(clock, this.tl.t1);
    if (this.cursor >= rows.length) {
      if (this.mode === "live") this.following = true;      // caught up with the tail: live again
      else this.playing = false;                            // the file is over
    }
    if (applied || dt) this._changed();
    return applied;
  }

  // A row from the stream. Applied at once while following; otherwise it only lengthens the slider.
  push(ev) {
    if (!this.tl.add(ev)) return false;
    if (this.following) {
      this.hooks.apply(ev, this.now(), false);
      this.cursor = this.tl.length;
      this.clock = ev.tm;
    }
    this._changed();
    return true;
  }

  // Back to the live tail (live mode) or the end of the file.
  live() { this.toEnd(); }

  // The boundary before / after the clock, for the arrow keys.
  turnBefore() { const ts = this.tl.turns().filter((b) => b.t < this.clock - 0.001); return ts.length ? ts[ts.length - 1] : null; }
  turnAfter() { return this.tl.turns().find((b) => b.t > this.clock + 0.001) || null; }
}
