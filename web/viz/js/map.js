// The hex map in d3/SVG: a static greyscale terrain layer drawn once, then borders, heat, attention, units, cities
// and floating captions redrawn from state. Zoom and pan on the whole thing.
import * as H from "./hex.js";
import { TERRAIN_GREY, MOUNTAIN, HILLS, featureGlyph, unitGlyph, rgb } from "./palette.js";

export class HexMap {
  constructor(svgEl, captionsEl, world) {
    this.world = world;
    this.svg = d3.select(svgEl);
    this.captions = d3.select(captionsEl);
    this.root = this.svg.append("g").attr("class", "root");
    this.layers = {};
    for (const name of ["terrain", "borders", "heat", "attention", "intent", "cities", "units", "labels"]) {
      this.layers[name] = this.root.append("g").attr("class", `layer-${name}`);
    }
    this.transform = d3.zoomIdentity;
    this.zoom = d3.zoom().scaleExtent([0.25, 8]).on("zoom", (e) => {
      this.transform = e.transform;
      this.root.attr("transform", e.transform);
      this.placeCaptions();
    });
    this.svg.call(this.zoom);
    this.built = false;
    this.captionList = [];
    this.show = { borders: true, labels: true };
  }

  // ------------------------------------------------------------ static terrain, once per map
  build() {
    const w = this.world.w, h = this.world.h;
    if (!w || !h) return;
    const g = this.layers.terrain;
    g.selectAll("*").remove();
    const cells = [];
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) cells.push({ x, y, ...this.world.plot(x, y) });
    const poly = g.selectAll("polygon").data(cells).join("polygon")
      .attr("points", (d) => { const [cx, cy] = H.centre(d.x, d.y, h); return H.polygon(cx, cy, 0.985); })
      .attr("fill", (d) => d.elev === "M" ? MOUNTAIN : d.elev === "^" ? HILLS : (TERRAIN_GREY[d.terrain] || TERRAIN_GREY["?"]))
      .attr("stroke", (d) => d.river ? "#8fa3b8" : "#0b0c0f")
      .attr("stroke-width", (d) => d.river ? 0.9 : 0.5)
      .attr("stroke-opacity", (d) => d.river ? 0.7 : 1);
    poly.append("title").text((d) => `(${d.x},${d.y}) ${d.terrain}${d.elev !== "." ? " " + d.elev : ""}${d.feature ? " " + d.feature : ""}${d.resource ? " · " + d.resource : ""}`);
    g.selectAll("text.feat").data(cells.filter((d) => d.feature && featureGlyph(d.feature))).join("text")
      .attr("class", "feat").attr("x", (d) => H.centre(d.x, d.y, h)[0]).attr("y", (d) => H.centre(d.x, d.y, h)[1] + 3)
      .attr("text-anchor", "middle").attr("font-size", 8).attr("fill", "#9aa0aa").attr("fill-opacity", 0.75)
      .text((d) => featureGlyph(d.feature));
    g.selectAll("circle.res").data(cells.filter((d) => d.resource)).join("circle")
      .attr("class", "res").attr("cx", (d) => H.centre(d.x, d.y, h)[0] + H.R * 0.45).attr("cy", (d) => H.centre(d.x, d.y, h)[1] - H.R * 0.45)
      .attr("r", 1.4).attr("fill", "#cfd3da").attr("fill-opacity", 0.7);
    this.built = true;
    this.fit();
  }

  fit() {
    const node = this.svg.node();
    const W = node.clientWidth || 800, Hh = node.clientHeight || 600;
    const mapW = (this.world.w + 0.5) * H.HW, mapH = (this.world.h - 1) * H.VS + 2 * H.R;
    const k = Math.min(W / mapW, Hh / mapH) * 0.96;
    const t = d3.zoomIdentity.translate((W - mapW * k) / 2, (Hh - mapH * k) / 2).scale(k);
    this.svg.call(this.zoom.transform, t);
  }

  // ------------------------------------------------------------ dynamic layers
  colorOfOwner(pid) {
    const p = this.world.players.get(pid);
    return p ? rgb(p.color, "#888") : "#888";
  }

  drawBorders() {
    const g = this.layers.borders, s = this.world.snapshot, h = this.world.h, w = this.world.w;
    if (!s || !s.owners || !this.show.borders) { g.selectAll("*").remove(); return; }
    const owned = [];
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { const o = this.world.ownerAt(x, y); if (o >= 0) owned.push({ x, y, o }); }
    g.selectAll("polygon").data(owned, (d) => d.y * w + d.x).join("polygon")
      .attr("points", (d) => { const [cx, cy] = H.centre(d.x, d.y, h); return H.polygon(cx, cy, 0.985); })
      .attr("fill", (d) => this.colorOfOwner(d.o)).attr("fill-opacity", 0.16)
      .attr("stroke", (d) => this.colorOfOwner(d.o)).attr("stroke-opacity", 0.35).attr("stroke-width", 0.6);
  }

  // rows: [{key, seat, alpha, kind}] — pulse/hold/ghost fill, intent outline
  drawAttention(rows, hueOf) {
    const w = this.world.w, h = this.world.h;
    const fills = rows.filter((r) => r.kind !== "intent"), outlines = rows.filter((r) => r.kind === "intent");
    this.layers.attention.selectAll("polygon").data(fills, (d) => `${d.seat}:${d.key}:${d.kind}`).join("polygon")
      .attr("points", (d) => { const [x, y] = H.unkey(d.key, w); const [cx, cy] = H.centre(x, y, h); return H.polygon(cx, cy, 0.985); })
      .attr("fill", (d) => hueOf(d.seat)).attr("fill-opacity", (d) => d.alpha)
      .style("mix-blend-mode", "screen");
    this.layers.intent.selectAll("polygon").data(outlines, (d) => `${d.seat}:${d.key}`).join("polygon")
      .attr("points", (d) => { const [x, y] = H.unkey(d.key, w); const [cx, cy] = H.centre(x, y, h); return H.polygon(cx, cy, 0.8); })
      .attr("fill", "none").attr("stroke", (d) => hueOf(d.seat)).attr("stroke-width", 1.6).attr("stroke-dasharray", "3 2")
      .attr("stroke-opacity", (d) => d.alpha);
  }

  drawHeat(rows, hueOf) {
    const w = this.world.w, h = this.world.h;
    this.layers.heat.selectAll("polygon").data(rows, (d) => `${d.seat}:${d.key}`).join("polygon")
      .attr("points", (d) => { const [x, y] = H.unkey(d.key, w); const [cx, cy] = H.centre(x, y, h); return H.polygon(cx, cy, 0.985); })
      .attr("fill", (d) => hueOf(d.seat)).attr("fill-opacity", (d) => d.alpha * 0.6).style("mix-blend-mode", "screen");
  }

  // Units and cities. `colourKeys`: Set of plot keys that are in colour in the current view (null = everything).
  drawPieces(colourKeys) {
    const s = this.world.snapshot, h = this.world.h, w = this.world.w;
    if (!s) return;
    const inColour = (x, y) => !colourKeys || colourKeys.has(H.key(x, y, w));
    const cities = this.layers.cities.selectAll("g.city").data(s.cities, (d) => `${d.o}:${d.id}`).join((enter) => {
      const g = enter.append("g").attr("class", "city");
      g.append("rect").attr("width", H.R * 1.1).attr("height", H.R * 1.1).attr("x", -H.R * 0.55).attr("y", -H.R * 0.55).attr("rx", 1.5);
      g.append("text").attr("class", "pop").attr("text-anchor", "middle").attr("y", 3).attr("font-size", 7).attr("fill", "#fff");
      return g;
    });
    cities.attr("transform", (d) => { const [cx, cy] = H.centre(d.x, d.y, h); return `translate(${cx},${cy})`; })
      .attr("opacity", (d) => inColour(d.x, d.y) ? 1 : 0.55);
    cities.select("rect").attr("fill", (d) => inColour(d.x, d.y) ? this.colorOfOwner(d.o) : "#777")
      .attr("stroke", (d) => d.cap ? "#fff" : "#000").attr("stroke-width", (d) => d.cap ? 1.2 : 0.6);
    cities.select("text.pop").text((d) => d.pop);
    const units = this.layers.units.selectAll("g.unit").data(s.units, (d) => `${d.o}:${d.id}`).join((enter) => {
      const g = enter.append("g").attr("class", "unit");
      g.append("circle").attr("r", H.R * 0.42).attr("stroke", "#000").attr("stroke-width", 0.5);
      g.append("text").attr("text-anchor", "middle").attr("y", 2.6).attr("font-size", 6.5).attr("fill", "#fff").attr("font-weight", 700);
      g.append("title");
      return g;
    });
    units.attr("transform", (d) => { const [cx, cy] = H.centre(d.x, d.y, h); const off = (d.id % 3 - 1) * 2.2; return `translate(${cx + off},${cy - H.R * 0.35})`; })
      .attr("opacity", (d) => inColour(d.x, d.y) ? 1 : 0.5);
    units.select("circle").attr("fill", (d) => inColour(d.x, d.y) ? this.colorOfOwner(d.o) : "#666")
      .attr("stroke-dasharray", (d) => d.civ ? "1.5 1" : null);
    units.select("text").text((d) => unitGlyph(d));
    units.select("title").text((d) => `${d.t} #${d.id} (${d.x},${d.y}) hp ${d.hp}${d.mhp ? "/" + d.mhp : ""} — ${this.world.playerName(d.o)}`);
    const labels = this.layers.labels.selectAll("text.cname").data(this.show.labels ? s.cities : [], (d) => `${d.o}:${d.id}`).join("text")
      .attr("class", "cname").attr("text-anchor", "middle").attr("font-size", 7.5).attr("fill", "#e6e8ec").attr("stroke", "#000").attr("stroke-width", 2).attr("paint-order", "stroke");
    labels.attr("x", (d) => H.centre(d.x, d.y, h)[0]).attr("y", (d) => H.centre(d.x, d.y, h)[1] + H.R * 1.35).text((d) => d.n || "");
  }

  // ------------------------------------------------------------ captions: HTML floating over a plot, then fading
  caption(x, y, html, hue, ttl = 4500) {
    const el = this.captions.append("div").attr("class", "caption").style("--seat", hue).html(html);
    // captions on the same spot stack upwards instead of covering each other
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
