// Wiring: feed -> world / attention -> map + panels. Observer view draws every seat; a seat view draws that seat only.
import * as H from "./hex.js";
import { connect } from "./feed.js";
import { World } from "./world.js";
import { Attention } from "./attention.js";
import { HexMap } from "./map.js";
import { Panels, summarize } from "./panels.js";

const world = new World();
const attention = new Attention();
const map = new HexMap(document.getElementById("map"), document.getElementById("captions"), world);
let view = "observer";
let toggles = { heat: false, ghost: true, borders: true, labels: true };
let rafPending = false;

const history = { calls: [], events: [] };    // what the side panels re-render from on a view switch
const HISTORY = 200;

const panels = new Panels(world, {
  onView: (v) => {
    view = v;
    panels.clearLists();
    for (const row of history.calls) panels.call(row, summarize(row, world));
    for (const ev of history.events) panels.event(ev);
    panels.notebook();
    redraw(true);
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

function handleCall(row, arrived, quiet = false) {
  world.noteSeat(row.seat);
  const seen = keysOf(row.seen), intent = keysOf(row.intent);
  const refPos = world.positionsOf(row.refs, row.seat);
  const refKeys = keysOf(refPos);
  attention.call(row.seat, row, seen.length ? seen : (row.kind === "read" ? refKeys : []), intent.length ? intent : (row.kind === "write" ? refKeys : []), arrived);
  history.calls.push(row); if (history.calls.length > HISTORY) history.calls.shift();
  panels.call(row, summarize(row, world));
  if (quiet || !world.map || (view !== "observer" && view !== row.seat) || row.kind === "wait" || row.scope === "broad") return;
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

function redraw(full = false) {
  if (!world.map) return;
  const now = performance.now();
  const seats = seatsInView();
  map.drawAttention(attention.layers(now, seats, { ghost: toggles.ghost && view === "observer" }), (s) => world.hue(s));
  map.drawHeat(toggles.heat ? attention.heatLayers(seats) : [], (s) => world.hue(s));
  if (full) { map.drawBorders(); panels.renderViews(); panels.turn(); }
  map.drawPieces(colourKeys(now));
  if (attention.live(now) && !rafPending) {
    rafPending = true;
    requestAnimationFrame(() => { rafPending = false; redraw(false); });
  }
}

function onEvent(ev, fromState = false) {
  const arrived = performance.now();
  switch (ev.type) {
    case "hello":
      world.setMap(ev.data.map);
      map.build();
      redraw(true);
      break;
    case "snapshot":
      world.setSnapshot(ev.data);
      redraw(true);
      break;
    case "call":
      handleCall(ev.data, fromState ? arrived - 60000 : arrived, fromState);   // history paints as holds/ghost, never as fresh pulses
      redraw(false);
      break;
    case "event":
      history.events.push(ev.data); if (history.events.length > HISTORY) history.events.shift();
      panels.event(ev.data);
      break;
    case "notebook":
      world.setNotebook(ev.data);
      panels.notebook();
      panels.renderViews();
      break;
    case "status":
      panels.status(true, `${ev.data.source}: ${ev.data.err || "ok"}`);
      break;
  }
}

connect({
  onState: (st) => {
    if (st.hello) onEvent({ type: "hello", data: st.hello }, true);
    if (st.snapshot) onEvent({ type: "snapshot", data: st.snapshot }, true);
    for (const nb of Object.values(st.notebooks || {})) onEvent({ type: "notebook", data: nb }, true);
    for (const c of st.calls || []) onEvent(c, true);
    for (const e of st.events || []) onEvent(e, true);
    redraw(true);
  },
  onEvent: (ev) => onEvent(ev, false),
  onStatus: (ok, text) => panels.status(ok, text),
});

window.addEventListener("resize", () => { if (world.map) map.fit(); });
