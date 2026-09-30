// The side panels and the header: view switcher, toggles, the thinking column, the event ticker, the notebook.
import { titleCase } from "./world.js";

const MAX_ROWS = 120;

export class Panels {
  constructor(world, { onView, onToggle }) {
    this.world = world;
    this.view = "observer";        // "observer" | seat id
    this.onView = onView;
    this.el = {
      views: document.getElementById("views"), calls: document.getElementById("calls"),
      ticker: document.getElementById("ticker"), notes: document.getElementById("notes"),
      turn: document.getElementById("turn"), conn: document.getElementById("conn"),
    };
    for (const id of ["heat", "ghost", "borders", "labels"]) {
      const box = document.getElementById(`tg-${id}`);
      box.addEventListener("change", () => onToggle(id, box.checked));
    }
    this.toggles = () => Object.fromEntries(["heat", "ghost", "borders", "labels"].map((id) => [id, document.getElementById(`tg-${id}`).checked]));
    this.renderViews();
  }

  renderViews() {
    const views = [["observer", "Observer", null], ...this.world.seats.map((s) => [s, `Seat ${s} · ${this.world.playerName(s)}`, this.world.hue(s)])];
    const sel = d3.select(this.el.views).selectAll("button").data(views, (d) => d[0]).join("button")
      .text((d) => d[1]).style("--seat", (d) => d[2]).on("click", (_, d) => { this.view = d[0]; this.renderViews(); this.onView(d[0]); });
    sel.classed("on", (d) => d[0] === this.view);
  }

  status(connected, text) {
    this.el.conn.classList.toggle("off", !connected);
    this.el.conn.title = text || "";
  }

  turn() {
    const s = this.world.snapshot;
    if (!s) { this.el.turn.textContent = "—"; return; }
    const who = s.active >= 0 ? this.world.playerName(s.active) : "?";
    this.el.turn.textContent = `t${s.turn} · ${who}${s.over ? " · game over" : ""}`;
  }

  // ---------------------------------------------------------- thinking column
  visible(seat) { return this.view === "observer" || this.view === seat; }

  call(row, summary) {
    if (!this.visible(row.seat)) return;
    const li = document.createElement("li");
    li.className = `new${row.ok === false ? " err" : ""}`;
    li.style.setProperty("--seat", this.world.hue(row.seat));
    const secs = typeof row.seconds === "number" ? `${row.seconds.toFixed(1)}s` : "";
    const trips = Number.isInteger(row.trips) ? ` · ${row.trips} trip${row.trips === 1 ? "" : "s"}` : "";
    li.innerHTML = `<span class="scope ${row.scope || row.kind}"></span><span class="tool">${esc(row.tool)}</span> `
      + `<span class="meta">seat ${row.seat}${Number.isInteger(row.turn) ? " · t" + row.turn : ""} · ${secs}${trips}</span>`
      + (summary ? `<div class="args">${esc(summary)}</div>` : "")
      + (row.ok === false && row.err ? `<div class="err">${esc(row.err)}</div>` : "")
      + (row.excerpt && row.ok !== false && row.kind === "write" ? `<div class="meta">${esc(row.excerpt.slice(0, 160))}</div>` : "");
    this.el.calls.prepend(li);
    trim(this.el.calls);
  }

  // ---------------------------------------------------------- runtime events
  event(ev) {
    const aud = ev.audience;
    if (this.view !== "observer" && aud !== this.view) return;
    const li = document.createElement("li");
    li.className = "new";
    li.style.setProperty("--seat", Number.isInteger(aud) ? this.world.hue(aud) : "#555");
    li.innerHTML = `<span class="tool">${esc(ev.kind || "?")}</span> <span class="meta">t${ev.turn ?? "?"}</span><div class="args">${esc(describe(ev, this.world))}</div>`;
    this.el.ticker.prepend(li);
    trim(this.el.ticker);
  }

  // ---------------------------------------------------------- notebook
  notebook() {
    const seats = this.view === "observer" ? this.world.seats : [this.view];
    const parts = [];
    for (const seat of seats) {
      const nb = this.world.notebooks.get(seat);
      if (!nb) continue;
      const hue = this.world.hue(seat);
      parts.push(`<h3 style="--seat:${hue}">Seat ${seat} · ${esc(this.world.playerName(seat))}</h3>`);
      for (const a of (nb.assignments || []).filter((a) => !a.status || a.status === "active" || a.status === "open").slice(-12)) {
        parts.push(`<div class="note assign"><span class="role">${esc(a.role || "")}</span>${esc(a.purpose || "")}</div>`);
      }
      for (const n of (nb.notes || []).slice(-10).reverse()) {
        parts.push(`<div class="note"><span class="tag">${esc(n.tag || "")}${Number.isInteger(n.turn) ? " t" + n.turn : ""}</span>${esc(n.text || "")}</div>`);
      }
    }
    this.el.notes.innerHTML = parts.join("") || `<div class="note meta">no notebook yet</div>`;
  }

  clearLists() { this.el.calls.innerHTML = ""; this.el.ticker.innerHTML = ""; }
}

function trim(ol) { while (ol.children.length > MAX_ROWS) ol.removeChild(ol.lastChild); }

export function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

// One line for a runtime event, from the fields the recorder tends to put there.
export function describe(ev, world) {
  const d = ev.data || {};
  const name = (pid) => Number.isInteger(pid) ? world.playerName(pid) : "";
  switch (ev.kind) {
    case "combat": case "damage": case "unit_hurt":
      return `${d.attacker_type || d.attacker || ""} → ${d.defender_type || d.defender || ""}${d.damage != null ? " · " + d.damage + " dmg" : ""}${d.x != null ? ` @(${d.x},${d.y})` : ""}`;
    case "unit_lost": case "unit_destroyed":
      return `${d.type || d.unit_type || "unit"} of ${name(d.player ?? d.owner)} lost${d.by != null ? " to " + name(d.by) : ""}${d.x != null ? ` @(${d.x},${d.y})` : ""}`;
    case "city_captured": return `${d.name || d.city || "city"} taken by ${name(d.new_owner ?? d.captor)}`;
    case "city_created": return `${d.name || "city"} founded by ${name(d.player ?? d.owner)}`;
    case "leader_message": return `${name(d.from ?? d.player)}: ${d.text || d.message || ""}`;   // the ring row says `player` (live t152)
    case "war_state": return `${name(d.a ?? d.team1)} ${d.war ? "declares war on" : "makes peace with"} ${name(d.b ?? d.team2)}`;
    case "notification": case "alert": return d.text || d.summary || d.message || JSON.stringify(d).slice(0, 120);
    case "turn_start": case "turn_end": case "active_player": return `${name(d.player ?? d.pid)}`;
    default: return d.text || d.summary || JSON.stringify(d).slice(0, 140);
  }
}

// A terse caption for a ledger row: the tool and what it named.
export function summarize(row, world) {
  let a = {};
  try { a = row.args ? JSON.parse(row.args) : {}; } catch { return row.args || ""; }
  const parts = [];
  if (a.unit_id != null) parts.push(world.unitLabel(a.unit_id, row.seat));
  if (a.city_id != null) parts.push(world.cityLabel(a.city_id, row.seat));
  if (a.x != null && a.y != null) parts.push(`→ (${a.x},${a.y})`);
  if (a.dest_x != null) parts.push(`→ (${a.dest_x},${a.dest_y})`);
  if (a.radius != null) parts.push(`r${a.radius}`);
  if (a.item) parts.push(titleCase(String(a.item).replace(/^(BUILDING|UNIT|PROJECT)_/, "")));
  if (a.tech) parts.push(titleCase(String(a.tech).replace(/^TECH_/, "")));
  if (a.mission) parts.push(String(a.mission).replace(/^MISSION_/, ""));
  if (a.role) parts.push(`${a.role}${a.purpose ? " — " + a.purpose : ""}`);
  else if (a.purpose) parts.push(a.purpose);
  if (a.text) parts.push(`“${a.text}”`);
  if (a.steps) parts.push(`${a.steps.length} step${a.steps.length === 1 ? "" : "s"}`);
  if (a.actions) parts.push(`${a.actions.length} orders: ${a.actions.map((x) => x.tool).join(", ")}`);
  if (!parts.length) {
    const keys = Object.keys(a);
    if (keys.length) parts.push(keys.map((k) => `${k}=${JSON.stringify(a[k])}`).join(" ").slice(0, 120));
  }
  return parts.join(" · ");
}
