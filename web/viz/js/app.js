// Wiring: feed -> timeline/player -> world / attention -> map + panels. Observer view draws every seat; a seat
// view draws that seat only. With a recording behind the server the player owns the clock (the scrubber);
// without one the stream applies as it arrives.
import * as H from "./hex.js";
import { state as fetchState, recording as fetchRecording, stream } from "./feed.js";
import { World } from "./world.js";
import { Attention } from "./attention.js";
import { HexMap } from "./map.js";
import { CanvasMap } from "./map_canvas.js";
import { Panels, summarize } from "./panels.js";
import { Timeline, Player } from "./timeline.js";
import { Scrubber } from "./scrub.js";

const world = new World();
const attention = new Attention();
// ?renderer=canvas draws the map on a canvas (docs/CANVAS_MIGRATION.md); the SVG renderer is the default until parity
const RENDERER = new URLSearchParams(location.search).get("renderer") === "canvas" ? "canvas" : "svg";
const map = (() => {
  const svg = document.getElementById("map"), cv = document.getElementById("map-canvas"), caps = document.getElementById("captions");
  if (RENDERER === "canvas") { svg.classList.add("off"); return new CanvasMap(cv, caps, world); }
  cv.classList.add("off");
  return new HexMap(svg, caps, world);
})();
let view = "observer";
let toggles = { heat: false, ghost: true, borders: true, labels: true };
let rafPending = false;

const history = { calls: [], events: [] };    // what the side panels re-render from on a view switch or a seek
const HISTORY = 200;

const panels = new Panels(world, {
  onView: (v) => {
    view = v;
    repaint();
  },
  onToggle: (id, on) => { toggles[id] = on; map.show.borders = toggles.borders; map.show.labels = toggles.labels; redraw(true); },
});
toggles = panels.toggles();

function seatsInView() { return view === "observer" ? world.seats : [view]; }

// Plots a ledger row touched, wrapped onto the map, as keys.
function keysOf(pairs) {
  const out = [];
  for (const p of pairs || []) { const q = H.onMap(p, world.w, world.h); if (q) out.push(H.key(q[0], q[1], world.w)); }
  return out;
}

// `quiet`: history and attention only -- no caption, no panel row (a seek or the bootstrap; the panels are rebuilt after)
function handleCall(row, arrived, quiet = false) {
  world.noteSeat(row.seat);
  const seen = keysOf(row.seen), intent = keysOf(row.intent);
  const refPos = world.positionsOf(row.refs, row.seat);
  const refKeys = keysOf(refPos);
  attention.call(row.seat, row, seen.length ? seen : (row.kind === "read" ? refKeys : []), intent.length ? intent : (row.kind === "write" ? refKeys : []), arrived);
  history.calls.push(row); if (history.calls.length > HISTORY) history.calls.shift();
  if (quiet) return;
  panels.call(row, summarize(row, world));
  if (!world.map || (view !== "observer" && view !== row.seat) || row.kind === "wait" || row.scope === "broad") return;
  // where the caption floats: the argument's plot, else the unit/city named, else the centre of what was seen
  const anchor = (row.intent && row.intent[0] && H.onMap(row.intent[0], world.w, world.h))
    || (refPos[0] && H.onMap(refPos[0], world.w, world.h))
    || (row.seen && row.seen[0] && H.onMap(row.seen[0], world.w, world.h));
  if (anchor) {
    const text = summarize(row, world);
    map.caption(anchor[0], anchor[1], `<span class="tool">${row.tool}</span>${text ? "\n" + text.replace(/[<>&]/g, "") : ""}`, world.hue(row.seat));
  }
}

function colourKeys(now) {
  // In a seat view only plots that seat has thought about this turn are in colour; the observer sees everything.
  if (view === "observer") return null;
  const s = new Set();
  for (const r of attention.layers(now, [view], { ghost: false })) s.add(r.key);
  return s;
}

// What a seat view's screen holds, from the seat's own fog in the snapshot: its team's pieces always, other cities
// and borders where it has ever looked, other units only where it can see now and the game does not hide them
// from it (an undetected submarine). null: the observer sees everything (also a seat whose snapshot carries no
// fog grid, e.g. a recording made before the grids existed).
function seatScreen() {
  if (view === "observer" || !world.hasFog(view)) return null;
  return {
    plot: (x, y) => world.fogAt(view, x, y) !== ".",
    city: (c) => world.sameTeam(view, c.o) || world.fogAt(view, c.x, c.y) !== ".",
    unit: (u) => world.sameTeam(view, u.o) || (world.fogAt(view, u.x, u.y) === "v" && !world.hiddenFrom(view, u)),
  };
}

function redraw(full = false) {
  if (!world.map) return;
  const now = performance.now();
  const seats = seatsInView();
  const screen = seatScreen();
  map.drawAttention(attention.layers(now, seats, { ghost: toggles.ghost && view === "observer" }), (s) => world.hue(s));
  map.drawHeat(toggles.heat ? attention.heatLayers(seats) : [], (s) => world.hue(s));
  if (full) { map.drawFog(screen ? view : null); map.drawBorders(screen && screen.plot); panels.renderViews(); panels.turn(); }
  map.drawPieces(colourKeys(now), screen);
  if (attention.live(now) && !rafPending) {
    rafPending = true;
    requestAnimationFrame(() => { rafPending = false; redraw(false); });
  }
}

// One event onto the page. `jump`: part of a seek or the bootstrap -- state only, the page is repainted after.
function apply(ev, arrived, jump = false) {
  switch (ev.type) {
    case "hello":
      world.setMap(ev.data.map);
      map.build();
      if (!jump) redraw(true);
      break;
    case "snapshot":
      world.setSnapshot(ev.data);
      if (!jump) redraw(true);
      break;
    case "call":
      handleCall(ev.data, arrived, jump);
      if (!jump) redraw(false);
      break;
    case "event":
      history.events.push(ev.data); if (history.events.length > HISTORY) history.events.shift();
      if (!jump) panels.event(ev.data);
      break;
    case "notebook":
      world.setNotebook(ev.data);
      if (!jump) { panels.notebook(); panels.renderViews(); }
      break;
    case "status":
      panels.status(true, `${ev.data.source}: ${ev.data.err || "ok"}`);
      break;
  }
}

// The side panels from history, the map from state: after a view switch, a seek, the bootstrap.
function repaint() {
  panels.clearLists();
  for (const row of history.calls) panels.call(row, summarize(row, world));
  for (const ev of history.events) panels.event(ev);
  panels.notebook();
  redraw(true);
  scrubber.render();
}

// Everything the page knows, gone: a seek backwards rebuilds from the recording's first row (every call in order,
// the latest hello / snapshot / notebook before the target; Timeline.plan).
function reset() {
  world.reset();
  attention.reset();
  history.calls = []; history.events = [];
  map.clear();
  panels.clearLists();
}

const timeline = new Timeline();
const player = new Player(timeline, { apply, reset, settled: repaint, changed: () => scrubber.render() }, { now: () => performance.now() });
const scrubber = new Scrubber(player, timeline, world, document.getElementById("scrub"));
setInterval(() => player.step(performance.now()), 80);

async function start() {
  let st;
  try { st = await fetchState(); } catch (e) { panels.status(false, `state: ${e.message}`); setTimeout(start, 3000); return; }
  const onStatus = (ok, text) => panels.status(ok, text);
  if (st.recording) {
    // the recording into the timeline row by row as it streams in; the SSE stream carries on from its last row
    // (duplicates are dropped by seq)
    await fetchRecording(0, (ev) => timeline.add(ev));
    player.mode = st.mode === "replay" ? "replay" : "live";
    scrubber.show();
    if (player.mode === "replay") { player.toStart(); player.play(); } else { player.toEnd(); }
    stream(timeline.last, { onEvent: (ev) => player.push(ev), onStatus });
    return;
  }
  // no recording: the bootstrap state, then the stream as it comes (history paints as holds/ghost, never as fresh pulses)
  const arrived = performance.now() - 60000;
  if (st.hello) apply({ type: "hello", data: st.hello }, arrived, true);
  if (st.snapshot) apply({ type: "snapshot", data: st.snapshot }, arrived, true);
  for (const nb of Object.values(st.notebooks || {})) apply({ type: "notebook", data: nb }, arrived, true);
  for (const c of st.calls || []) apply(c, arrived, true);
  for (const e of st.events || []) apply(e, arrived, true);
  repaint();
  stream(st.seq || 0, { onEvent: (ev) => apply(ev, performance.now(), false), onStatus });
}
start();

window.addEventListener("resize", () => { if (world.map) map.fit(); });
