// The scrubber bar under the map: start, play/pause, speed, the slider with the turn boundaries ticked on it,
// where the clock is (turn, elapsed), and a "live" button back to the tail. Space plays/pauses, ← → jump a
// turn boundary, Home/End go to the start and the end.
import { esc } from "./panels.js";

const SPEEDS = [0.5, 1, 2, 4, 8, 16, 64];
const STEPS = 2000;                  // slider resolution

export class Scrubber {
  constructor(player, timeline, world, root) {
    this.player = player; this.tl = timeline; this.world = world; this.root = root;
    root.innerHTML = `<button id="sc-start" title="start (Home)">⏮</button>`
      + `<button id="sc-play" title="play / pause (space)">▶</button>`
      + `<select id="sc-speed" title="speed">${SPEEDS.map((s) => `<option value="${s}"${s === 1 ? " selected" : ""}>${s}×</option>`).join("")}</select>`
      + `<div id="sc-track"><div id="sc-ticks"></div><input id="sc-pos" type="range" min="0" max="${STEPS}" value="0" step="1"></div>`
      + `<span id="sc-label">—</span>`
      + `<button id="sc-live" title="follow the live feed (End)">live</button>`;
    this.el = Object.fromEntries(["start", "play", "speed", "ticks", "pos", "label", "live"].map((k) => [k, root.querySelector(`#sc-${k}`)]));
    this.el.start.addEventListener("click", () => player.toStart());
    this.el.play.addEventListener("click", () => player.toggle());
    this.el.speed.addEventListener("change", () => player.setSpeed(parseFloat(this.el.speed.value)));
    this.el.live.addEventListener("click", () => player.live());
    this.el.pos.addEventListener("input", () => { const { t0, t1 } = this.tl; player.seek(t0 + (t1 - t0) * (this.el.pos.value / STEPS)); });
    document.addEventListener("keydown", (e) => this.key(e));
    this.tickCount = -1;
    this.pending = false;
  }

  show() { this.root.hidden = false; this.render(); }

  key(e) {
    if (this.root.hidden || /^(INPUT|SELECT|TEXTAREA|BUTTON)$/.test(e.target.tagName) || e.altKey || e.ctrlKey || e.metaKey) return;
    const p = this.player;
    let b;
    switch (e.key) {
      case " ": p.toggle(); break;
      case "Home": p.toStart(); break;
      case "End": p.live(); break;
      case "ArrowLeft": b = p.turnBefore(); if (b) p.seek(b.t); else p.toStart(); break;
      case "ArrowRight": b = p.turnAfter(); if (b) p.seek(b.t); else p.live(); break;
      default: return;
    }
    e.preventDefault();
  }

  // Called on every player change; the DOM is touched once a frame.
  render() {
    if (this.pending) return;
    this.pending = true;
    requestAnimationFrame(() => { this.pending = false; this.paint(); });
  }

  paint() {
    const s = this.player.state();
    const span = s.t1 - s.t0;
    this.el.pos.value = span > 0 ? Math.round((s.clock - s.t0) / span * STEPS) : 0;
    this.el.play.textContent = s.playing ? "⏸" : "▶";
    this.el.play.classList.toggle("on", s.playing);
    this.el.live.hidden = s.mode !== "live";
    this.el.live.classList.toggle("on", s.following);
    const snap = this.world.snapshot;
    const where = snap ? `t${snap.turn}${snap.active >= 0 ? " · " + this.world.playerName(snap.active) : ""}` : "—";
    this.el.label.textContent = `${where} · ${clock(s.clock - s.t0)} / ${clock(span)}${s.following ? " · live" : ""}`;
    this.el.label.title = `${s.cursor} of ${s.length} events`;
    if (this.tl.length !== this.tickCount) { this.tickCount = this.tl.length; this.ticks(); }
  }

  // One tick per turn boundary, in the hue of the seat whose turn begins (grey for an AI round).
  ticks() {
    const { t0, t1 } = this.tl, span = t1 - t0;
    const parts = [];
    if (span > 0) {
      for (const b of this.tl.turns()) {
        const seat = this.world.seats.includes(b.active) ? b.active : null;
        const hue = seat === null ? "var(--dim)" : this.world.hue(seat);
        const name = Number.isInteger(b.active) ? this.world.playerName(b.active) : "?";
        parts.push(`<i class="tick" style="left:${((b.t - t0) / span * 100).toFixed(3)}%;--seat:${hue}" data-t="${b.t}" title="t${esc(b.turn)} · ${esc(name)}"></i>`);
      }
    }
    this.el.ticks.innerHTML = parts.join("");
    for (const i of this.el.ticks.querySelectorAll("i.tick")) i.addEventListener("click", () => this.player.seek(parseFloat(i.dataset.t)));
  }
}

// m:ss or h:mm:ss of recording time
export function clock(seconds) {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return (h ? `${h}:${String(m).padStart(2, "0")}` : String(m)) + ":" + String(r).padStart(2, "0");
}
