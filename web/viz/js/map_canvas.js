// The hex map on a 2D canvas (docs/CANVAS_MIGRATION.md, phase 2): the same surface as map.js's HexMap, drawn as
// one visible canvas composed from two cached bitmaps and a live pass. The terrain cache holds the greyscale
// hexes, river strokes, feature glyphs and resource dots; the world cache holds a seat's fog and the borders over
// it; the live pass draws heat, attention, intent, cities, units and labels straight onto the visible canvas on
// every redraw. Both caches are rendered in screen space at the transform of the moment and only the plots the
// viewport shows (hex.visibleRange); during a zoom gesture the stale caches are blitted through the delta and
// re-rendered when the gesture ends. Hovering (phase 3): the live pass indexes the pieces it drew by plot, `tipAt`
// inverts the transform and hex.plotAt to name the plot and the unit under a point, and the pointer handler puts
// that text (the SVG <title> text) in the tip div. Nothing here touches the DOM outside the constructor, `fit`,
// `resize`, the captions and the tip, so the drawing and the hit test run under node against a stub context
// (tests/test_viz_js.py).
import * as H from "./hex.js";
import { TERRAIN_GREY, MOUNTAIN, HILLS, featureGlyph, unitGlyph, rgb } from "./palette.js";

const D3 = typeof d3 !== "undefined" ? d3 : null;
const SANS = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";   // the page's --sans, what the SVG text inherited
const CHUNK = 8;   // hexes a path in the cached passes (paintHexes): measured in Chrome at 200x120, 1 / 8 / 32 / 128 gave 28 / 10 / 11 / 14 ms

// A plain transform when d3 is not loaded (node): the three numbers d3.zoomIdentity carries and `apply`.
function plainTransform(k, x, y) {
  return { k, x, y, apply: ([px, py]) => [px * k + x, py * k + y] };
}

export class CanvasMap {
  // opts: makeCanvas() for the offscreen caches (default document.createElement), dpr, font, tip (the div that
  // shows the hovered plot or unit; none under node).
  constructor(canvasEl, captionsEl, world, opts = {}) {
    this.world = world;
    this.canvas = canvasEl;
    this.ctx = canvasEl.getContext("2d");
    this.dpr = opts.dpr || (typeof devicePixelRatio === "number" ? devicePixelRatio : 1);
    this.font = opts.font || SANS;
    this.makeCanvas = opts.makeCanvas || (() => document.createElement("canvas"));
    this.tip = opts.tip || null;
    this.pointer = null;                 // the last pointer position over the canvas, in CSS pixels
    this.index = new Map();              // plot key -> { cities, units } drawn by the last live pass
    this.cacheTerrain = this.newCache();
    this.cacheWorld = this.newCache();
    this.captions = D3 && captionsEl ? D3.select(captionsEl) : null;
    this.captionList = [];
    this.show = { borders: true, labels: true };
    this.built = false;
    this.transform = plainTransform(1, 0, 0);
    this.gesture = false;
    // what the last draw* calls asked for, so a zoom frame can repaint without them
    this.fogSeat = null;
    this.known = null;
    this.attn = { rows: [], hueOf: () => "#888" };
    this.heat = { rows: [], hueOf: () => "#888" };
    this.pieces = { colourKeys: null, shows: null };
    this.W = 0; this.Hh = 0;
    this.resize();
    this.zoom = null;
    if (D3) {
      this.zoom = D3.zoom().scaleExtent([0.25, 8])
        .on("start", () => { this.gesture = true; this.hideTip(); })
        .on("zoom", (e) => { this.transform = e.transform; this.placeCaptions(); this.frame(); })
        .on("end", () => { this.gesture = false; this.invalidate(true); this.frame(); });
      D3.select(canvasEl).call(this.zoom);
    }
    if (this.tip && canvasEl.addEventListener) {
      canvasEl.addEventListener("pointermove", (e) => {
        const b = canvasEl.getBoundingClientRect();
        this.pointer = [e.clientX - b.left, e.clientY - b.top];
        this.showTip();
      });
      canvasEl.addEventListener("pointerleave", () => { this.pointer = null; this.hideTip(); });
    }
  }

  // ------------------------------------------------------------ hovering
  // What is under a point of the canvas (CSS pixels): the unit whose disc holds it, else the plot; null off the
  // map. The text is what the SVG renderer's <title> elements say, so both renderers read the same.
  tipAt(sx, sy) {
    const w = this.world.w, h = this.world.h, t = this.transform;
    if (!this.built || !w) return null;
    const mx = (sx - t.x) / t.k, my = (sy - t.y) / t.k;
    const p = H.plotAt(mx, my, w, h, false);
    if (!p) return null;
    const [x, y] = p;
    let best = null, bestD = (H.R * 0.42) ** 2;
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      const yy = y + dy;
      if (yy < 0 || yy >= h) continue;
      const at = this.index.get(H.key(H.wrapX(x + dx, w), yy, w));
      if (!at) continue;
      for (const u of at.units) {
        const [ux, uy] = this.unitPos(u);
        const d = (ux - mx) ** 2 + (uy - my) ** 2;
        if (d < bestD) { bestD = d; best = u; }
      }
    }
    if (best) {
      const u = best;
      return { kind: "unit", x: u.x, y: u.y, unit: u,
               text: `${u.t} #${u.id} (${u.x},${u.y}) hp ${u.hp}${u.mhp ? "/" + u.mhp : ""} — ${this.world.playerName(u.o)}` };
    }
    const d = this.world.plot(x, y);
    return { kind: "plot", x, y,
             text: `(${x},${y}) ${d.terrain}${d.elev !== "." ? " " + d.elev : ""}${d.feature ? " " + d.feature : ""}${d.resource ? " · " + d.resource : ""}` };
  }

  showTip() {
    if (!this.tip || !this.pointer || this.gesture) return;
    const [sx, sy] = this.pointer, hit = this.tipAt(sx, sy);
    if (!hit) { this.hideTip(); return; }
    this.tip.textContent = hit.text;
    this.tip.style.left = `${sx}px`;
    this.tip.style.top = `${sy - 12}px`;
    this.tip.hidden = false;
  }

  hideTip() { if (this.tip) this.tip.hidden = true; }

  newCache() {
    const canvas = this.makeCanvas();
    return { canvas, ctx: canvas.getContext("2d"), t: null, valid: false };
  }

  // The backing stores follow the element's CSS size at the device pixel ratio; everything is stale after.
  resize() {
    const W = this.canvas.clientWidth || 800, Hh = this.canvas.clientHeight || 600;
    this.W = W; this.Hh = Hh;
    for (const c of [this.canvas, this.cacheTerrain.canvas, this.cacheWorld.canvas]) {
      c.width = Math.round(W * this.dpr); c.height = Math.round(Hh * this.dpr);
    }
    this.invalidate(true);
  }

  invalidate(terrain = false) {
    if (terrain) this.cacheTerrain.valid = false;
    this.cacheWorld.valid = false;
  }

  setTransform(t) {
    this.transform = t.apply ? t : plainTransform(t.k, t.x, t.y);
    this.invalidate(true);
    this.placeCaptions();
  }

  // ------------------------------------------------------------ the HexMap surface
  build() {
    if (!this.world.w || !this.world.h) return;
    const first = !this.built;
    this.built = true;
    this.invalidate(true);
    if (first) this.fit(); else this.frame();     // a rebuild (a seek backwards) keeps the viewer's zoom
  }

  clear() {
    this.fogSeat = null; this.known = null;
    this.attn = { rows: [], hueOf: () => "#888" }; this.heat = { rows: [], hueOf: () => "#888" };
    this.pieces = { colourKeys: null, shows: null };
    if (this.captions) this.captions.selectAll("*").remove();
    this.captionList = [];
    this.invalidate(false);
    this.frame();
  }

  fitTransform() {
    const mapW = (this.world.w + 0.5) * H.HW, mapH = (this.world.h - 1) * H.VS + 2 * H.R;
    const k = Math.min(this.W / mapW, this.Hh / mapH) * 0.96;
    return { k, x: (this.W - mapW * k) / 2, y: (this.Hh - mapH * k) / 2 };
  }

  fit() {
    this.resize();
    const t = this.fitTransform();
    // under d3 the programmatic transform runs the start/zoom/end handlers, which re-render and paint
    if (this.zoom) D3.select(this.canvas).call(this.zoom.transform, D3.zoomIdentity.translate(t.x, t.y).scale(t.k));
    else { this.setTransform(t); this.frame(); }
  }

  colorOfOwner(pid) {
    const p = this.world.players.get(pid);
    return p ? rgb(p.color, "#888") : "#888";
  }

  drawFog(seat) { this.fogSeat = seat; this.invalidate(false); }
  drawBorders(known = null) { this.known = known; this.invalidate(false); }
  drawAttention(rows, hueOf) { this.attn = { rows, hueOf }; }
  drawHeat(rows, hueOf) { this.heat = { rows, hueOf }; }
  // The last call of a redraw: the frame is painted here.
  drawPieces(colourKeys, shows = null) { this.pieces = { colourKeys, shows }; this.frame(); }

  // ------------------------------------------------------------ composing a frame
  range() { return H.visibleRange(this.transform, this.W, this.Hh, this.world.w, this.world.h); }

  // Map units under the zoom transform and the device pixel ratio.
  mapSpace(ctx, t = this.transform) {
    ctx.setTransform(this.dpr * t.k, 0, 0, this.dpr * t.k, this.dpr * t.x, this.dpr * t.y);
  }

  screenSpace(ctx) { ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0); }

  frame() {
    if (!this.built || !this.world.w) return;
    const ctx = this.ctx;
    if (!this.cacheTerrain.valid && !this.gesture) this.renderTerrain();
    if (!this.cacheWorld.valid && !this.gesture) this.renderWorld();
    this.screenSpace(ctx);
    ctx.clearRect(0, 0, this.W, this.Hh);
    this.blit(this.cacheTerrain);
    this.blit(this.cacheWorld);
    this.renderLive();
    this.showTip();                      // the pieces under a still pointer may have changed
  }

  // A unit's disc centre in map units: up from the plot's centre, nudged sideways so a stack shows (as the SVG).
  unitPos(d) {
    const [cx, cy] = H.centre(d.x, d.y, this.world.h);
    return [cx + (d.id % 3 - 1) * 2.2, cy - H.R * 0.35];
  }

  // A cache rendered at transform c, shown under the current one: screen = (cached - c) * k/c.k + x.
  blit(cache) {
    if (!cache.t) return;
    const t = this.transform, r = t.k / cache.t.k;
    this.ctx.drawImage(cache.canvas, 0, 0, cache.canvas.width, cache.canvas.height,
                       t.x - cache.t.x * r, t.y - cache.t.y * r, this.W * r, this.Hh * r);
  }

  hexPath(ctx, x, y, scale) {
    const [cx, cy] = H.centre(x, y, this.world.h);
    ctx.beginPath();
    H.tracePath(ctx, cx, cy, scale);
  }

  // Hexes (a flat [x, y, x, y, ...] list) traced CHUNK at a time with `paint` (a fill or an opaque stroke) run on
  // each path: a fill call per hex is what a full-map pass costs (0.9 us each, 22 ms for 24,000 plots at the fit
  // zoom), one call per 8 hexes is 2.5x cheaper, and one path for everything is 50x slower (Chrome's fill cost grows
  // faster than the subpath count). Distinct plots never overlap, so the union paints exactly as the hexes would
  // one by one; a translucent stroke must not come through here (adjacent strokes overlap at the seams and the SVG
  // composites each polygon's stroke on its own).
  paintHexes(ctx, list, scale, paint) {
    const h = this.world.h;
    let n = 0;
    ctx.beginPath();
    for (let i = 0; i < list.length; i += 2) {
      const [cx, cy] = H.centre(list[i], list[i + 1], h);
      H.tracePath(ctx, cx, cy, scale);
      if (++n === CHUNK) { paint(); ctx.beginPath(); n = 0; }
    }
    if (n) paint();
  }

  renderTerrain() {
    const c = this.cacheTerrain, ctx = c.ctx, t = this.transform, h = this.world.h;
    this.screenSpace(ctx);
    ctx.clearRect(0, 0, this.W, this.Hh);
    this.mapSpace(ctx, t);
    const r = this.range();
    if (r) {
      const byFill = new Map(), plain = [], rivers = [];
      for (let y = r.y0; y <= r.y1; y++) for (let x = r.x0; x <= r.x1; x++) {
        const d = this.world.plot(x, y);
        const fill = d.elev === "M" ? MOUNTAIN : d.elev === "^" ? HILLS : (TERRAIN_GREY[d.terrain] || TERRAIN_GREY["?"]);
        let list = byFill.get(fill);
        if (!list) byFill.set(fill, list = []);
        list.push(x, y);
        (d.river ? rivers : plain).push(x, y);
      }
      ctx.globalAlpha = 1;
      for (const [fill, list] of byFill) { ctx.fillStyle = fill; this.paintHexes(ctx, list, 0.985, () => ctx.fill()); }
      ctx.strokeStyle = "#0b0c0f"; ctx.lineWidth = 0.5;
      this.paintHexes(ctx, plain, 0.985, () => ctx.stroke());
      ctx.strokeStyle = "#8fa3b8"; ctx.lineWidth = 0.9; ctx.globalAlpha = 0.7;
      for (let i = 0; i < rivers.length; i += 2) { this.hexPath(ctx, rivers[i], rivers[i + 1], 0.985); ctx.stroke(); }
      ctx.globalAlpha = 1;
      ctx.textAlign = "center";
      ctx.font = `8px ${this.font}`;
      for (let y = r.y0; y <= r.y1; y++) for (let x = r.x0; x <= r.x1; x++) {
        const d = this.world.plot(x, y);
        const glyph = d.feature ? featureGlyph(d.feature) : "";
        if (!glyph && !d.resource) continue;
        const [cx, cy] = H.centre(x, y, h);
        if (glyph) { ctx.fillStyle = "#9aa0aa"; ctx.globalAlpha = 0.75; ctx.fillText(glyph, cx, cy + 3); }
        if (d.resource) {
          ctx.fillStyle = "#cfd3da"; ctx.globalAlpha = 0.7;
          ctx.beginPath(); ctx.arc(cx + H.R * 0.45, cy - H.R * 0.45, 1.4, 0, Math.PI * 2); ctx.fill();
        }
      }
      ctx.globalAlpha = 1;
    }
    c.t = { k: t.k, x: t.x, y: t.y };
    c.valid = true;
  }

  // Fog (never-seen plots nearly black, fogged plots dimmed) and borders, over the terrain cache's window.
  renderWorld() {
    const c = this.cacheWorld, ctx = c.ctx, t = this.transform, s = this.world.snapshot;
    this.screenSpace(ctx);
    ctx.clearRect(0, 0, this.W, this.Hh);
    this.mapSpace(ctx, t);
    const r = this.range();
    if (r && this.fogSeat !== null) {
      const fogged = [], never = [];
      for (let y = r.y0; y <= r.y1; y++) for (let x = r.x0; x <= r.x1; x++) {
        const f = this.world.fogAt(this.fogSeat, x, y);
        if (f !== "v") (f === "f" ? fogged : never).push(x, y);
      }
      ctx.fillStyle = "#04050a";
      ctx.globalAlpha = 0.45; this.paintHexes(ctx, fogged, 1.0, () => ctx.fill());
      ctx.globalAlpha = 0.86; this.paintHexes(ctx, never, 1.0, () => ctx.fill());
      ctx.globalAlpha = 1;
    }
    if (r && s && s.owners && this.show.borders) {
      ctx.lineWidth = 0.6;
      for (let y = r.y0; y <= r.y1; y++) for (let x = r.x0; x <= r.x1; x++) {
        const o = this.world.ownerAt(x, y);
        if (o < 0 || (this.known && !this.known(x, y))) continue;
        const col = this.colorOfOwner(o);
        this.hexPath(ctx, x, y, 0.985);
        ctx.fillStyle = col; ctx.globalAlpha = 0.16; ctx.fill();
        ctx.strokeStyle = col; ctx.globalAlpha = 0.35; ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }
    c.t = { k: t.k, x: t.x, y: t.y };
    c.valid = true;
  }

  // Heat under attention under intent, then cities under units under labels (the SVG layer order).
  renderLive() {
    const ctx = this.ctx, w = this.world.w, h = this.world.h, r = this.range();
    if (!r) return;
    const inRange = (x, y) => x >= r.x0 && x <= r.x1 && y >= r.y0 && y <= r.y1;
    const keyIn = (k) => { const [x, y] = H.unkey(k, w); return inRange(x, y); };
    this.mapSpace(ctx);
    ctx.globalCompositeOperation = "screen";
    for (const d of this.heat.rows) {
      if (!keyIn(d.key)) continue;
      const [x, y] = H.unkey(d.key, w);
      this.hexPath(ctx, x, y, 0.985);
      ctx.fillStyle = this.heat.hueOf(d.seat); ctx.globalAlpha = d.alpha * 0.6; ctx.fill();
    }
    for (const d of this.attn.rows) {
      if (d.kind === "intent" || !keyIn(d.key)) continue;
      const [x, y] = H.unkey(d.key, w);
      this.hexPath(ctx, x, y, 0.985);
      ctx.fillStyle = this.attn.hueOf(d.seat); ctx.globalAlpha = d.alpha; ctx.fill();
    }
    ctx.globalCompositeOperation = "source-over";
    ctx.globalAlpha = 1;
    const intents = this.attn.rows.filter((d) => d.kind === "intent" && keyIn(d.key));
    if (intents.length) {
      ctx.setLineDash([3, 2]); ctx.lineWidth = 1.6;
      for (const d of intents) {
        const [x, y] = H.unkey(d.key, w);
        this.hexPath(ctx, x, y, 0.8);
        ctx.strokeStyle = this.attn.hueOf(d.seat); ctx.globalAlpha = d.alpha; ctx.stroke();
      }
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
    }

    const s = this.world.snapshot;
    this.index = new Map();
    if (!s) return;
    const { colourKeys, shows } = this.pieces;
    const inColour = (x, y) => !colourKeys || colourKeys.has(H.key(x, y, w));
    const cities = (shows ? s.cities.filter(shows.city) : s.cities).filter((c) => inRange(c.x, c.y));
    const units = (shows ? s.units.filter(shows.unit) : s.units).filter((u) => inRange(u.x, u.y));
    const slot = (d) => { const k = H.key(d.x, d.y, w); let at = this.index.get(k); if (!at) this.index.set(k, at = { cities: [], units: [] }); return at; };
    for (const d of cities) slot(d).cities.push(d);
    for (const d of units) slot(d).units.push(d);
    ctx.textAlign = "center";
    const side = H.R * 1.1;
    ctx.font = `7px ${this.font}`;
    for (const d of cities) {
      const [cx, cy] = H.centre(d.x, d.y, h), colour = inColour(d.x, d.y);
      ctx.globalAlpha = colour ? 1 : 0.55;
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(cx - side / 2, cy - side / 2, side, side, 1.5); else ctx.rect(cx - side / 2, cy - side / 2, side, side);
      ctx.fillStyle = colour ? this.colorOfOwner(d.o) : "#777"; ctx.fill();
      ctx.strokeStyle = d.cap ? "#fff" : "#000"; ctx.lineWidth = d.cap ? 1.2 : 0.6; ctx.stroke();
      ctx.fillStyle = "#fff"; ctx.fillText(String(d.pop), cx, cy + 3);
    }
    ctx.font = `700 6.5px ${this.font}`;
    for (const d of units) {
      const [ux, uy] = this.unitPos(d), colour = inColour(d.x, d.y);
      ctx.globalAlpha = colour ? 1 : 0.5;
      ctx.beginPath(); ctx.arc(ux, uy, H.R * 0.42, 0, Math.PI * 2);
      ctx.fillStyle = colour ? this.colorOfOwner(d.o) : "#666"; ctx.fill();
      ctx.strokeStyle = "#000"; ctx.lineWidth = 0.5;
      if (d.civ) ctx.setLineDash([1.5, 1]);
      ctx.stroke();
      if (d.civ) ctx.setLineDash([]);
      ctx.fillStyle = "#fff"; ctx.fillText(unitGlyph(d), ux, uy + 2.6);
    }
    ctx.globalAlpha = 1;
    if (this.show.labels) {
      ctx.font = `7.5px ${this.font}`;
      ctx.lineWidth = 2; ctx.strokeStyle = "#000"; ctx.fillStyle = "#e6e8ec"; ctx.lineJoin = "round";
      for (const d of cities) {
        if (!d.n) continue;
        const [cx, cy] = H.centre(d.x, d.y, h);
        ctx.strokeText(d.n, cx, cy + H.R * 1.35);
        ctx.fillText(d.n, cx, cy + H.R * 1.35);
      }
    }
  }

  // ------------------------------------------------------------ captions: HTML floating over a plot, then fading
  caption(x, y, html, hue, ttl = 4500) {
    if (!this.captions) return;
    const el = this.captions.append("div").attr("class", "caption").style("--seat", hue).html(html);
    const stack = this.captionList.filter((o) => Math.abs(o.x - x) <= 2 && Math.abs(o.y - y) <= 2).length;
    const c = { x, y, el, born: performance.now(), ttl, stack };
    this.captionList.push(c);
    this.placeCaptions();
    setTimeout(() => el.classed("fade", true), ttl);
    setTimeout(() => { el.remove(); this.captionList = this.captionList.filter((o) => o !== c); }, ttl + 700);
    if (this.captionList.length > 8) { const old = this.captionList.shift(); old.el.remove(); }
  }

  placeCaptions() {
    const h = this.world.h;
    for (const c of this.captionList) {
      const [cx, cy] = H.centre(c.x, c.y, h);
      const [sx, sy] = this.transform.apply([cx, cy - H.R]);
      c.el.style("left", `${sx}px`).style("top", `${sy - 4 - c.stack * 40}px`);
    }
  }
}
