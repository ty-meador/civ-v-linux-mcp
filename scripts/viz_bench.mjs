#!/usr/bin/env node
// Measure the spectator page in a real Chrome through the DevTools protocol (docs/CANVAS_MIGRATION.md).
//
//   google-chrome --user-data-dir=/tmp/viz-bench-profile --no-first-run --remote-debugging-port=9222 \
//                 --remote-allow-origins='*' about:blank &
//   node scripts/viz_bench.mjs measure http://127.0.0.1:8765/ [more urls]   # one JSON line per page
//   node scripts/viz_bench.mjs heap    http://127.0.0.1:8765/ [more urls]   # JS heap after a forced GC, a fresh tab each
//   node scripts/viz_bench.mjs shots   http://127.0.0.1:8765/ out-prefix    # seat view at the fit and after ten
//                                                                           # wheel ticks: <prefix>-fit.png, -zoom.png
//
// Why not the browser extension: its scripts time out at 45 s and a tab it opens can sit hidden (no animation
// frames) behind another window; here the page is in Chrome's own front window, sized 1920x1080 (a 1540x898 map
// pane), and the measurement runs to the end. Chrome needs a non-default profile for the debugging port.
//
// `measure`: End (the whole recording applied) and pause; a view switch timed from the click to the second
// animation frame after it (js = the handler, paint = until that frame); Home and End seeks the same way; 20
// wheel ticks in, a 30-move drag at that zoom, 20 ticks out, a drag at the fit, one event per frame with the
// frame gaps recorded (avg / p90 / max); the player at its top speed from 97 % of the recording for 180 frames
// (the live pass); 30 idle frames. Numbers are milliseconds; 16.7 is the frame.
import { writeFileSync } from "node:fs";

const [mode, ...rest] = process.argv.slice(2);
const PORT = process.env.CDP_PORT || "9222";

async function connect(wsUrl) {
  const ws = new WebSocket(wsUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  let id = 0; const pending = new Map(); const listeners = [];
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.id && pending.has(d.id)) { const { res, rej } = pending.get(d.id); pending.delete(d.id); d.error ? rej(new Error(JSON.stringify(d.error))) : res(d.result); }
    else if (d.method) for (const l of listeners) l(d);
  };
  const send = (method, params = {}) => new Promise((res, rej) => { pending.set(++id, { res, rej }); ws.send(JSON.stringify({ id, method, params })); });
  const once = (method) => new Promise((res) => { const l = (d) => { if (d.method === method) { listeners.splice(listeners.indexOf(l), 1); res(d.params); } }; listeners.push(l); });
  const evaluate = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true, timeout: 600000 });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + " " + ((r.exceptionDetails.exception || {}).description || ""));
    return r.result.value;
  };
  const close = () => ws.close();
  const onEvent = (l) => listeners.push(l);
  return { send, once, evaluate, close, onEvent };
}

const json = async (path) => (await fetch(`http://127.0.0.1:${PORT}/json${path}`)).json();

// A page target in its own tab, 1920x1080, in front; closed by the caller.
async function openTab(browser, url) {
  const { targetId } = await browser.send("Target.createTarget", { url: "about:blank" });
  const info = (await json("")).find((t) => t.id === targetId);
  const p = await connect(info.webSocketDebuggerUrl);
  await p.send("Page.enable"); await p.send("Runtime.enable"); await p.send("HeapProfiler.enable"); await p.send("Page.bringToFront");
  await p.send("Log.enable");
  p.onEvent((d) => {   // page errors to stderr: a clean run prints none
    if (d.method === "Runtime.exceptionThrown") console.error("page exception:", d.params.exceptionDetails.text, (d.params.exceptionDetails.exception || {}).description || "");
    if (d.method === "Log.entryAdded" && d.params.entry.level === "error") console.error("page error:", d.params.entry.text);
    if (d.method === "Runtime.consoleAPICalled" && d.params.type === "error") console.error("console.error:", d.params.args.map((a) => a.value || a.description).join(" "));
  });
  const { windowId } = await p.send("Browser.getWindowForTarget", { targetId });
  await p.send("Browser.setWindowBounds", { windowId, bounds: { windowState: "normal" } });
  await p.send("Browser.setWindowBounds", { windowId, bounds: { left: 0, top: 0, width: 1920, height: 1080 } });
  const loaded = p.once("Page.loadEventFired");
  await p.send("Page.navigate", { url });
  await loaded;
  const close = async () => { p.close(); await browser.send("Target.closeTarget", { targetId }); };
  return { p, close };
}

// In the page: wait for the map (the view buttons follow hello), End, pause.
const SETTLE = `(async () => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms)); const raf = () => new Promise(r => requestAnimationFrame(r));
  for (let i = 0; i < 1800 && !document.querySelector('#views button'); i++) await sleep(100);
  await sleep(1500);
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true })); await sleep(500);
  const p = document.getElementById('sc-play'); if (p && /⏸/.test(p.textContent)) p.click();
  await raf(); await raf(); await sleep(500);
  return document.visibilityState;
})()`;

const MEASURE = `(async () => {
  const raf = () => new Promise(r => requestAnimationFrame(r));
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const now = () => performance.now();
  const el = [...document.querySelectorAll('#mapwrap > svg, #mapwrap > canvas')].find(e => !e.classList.contains('off'));
  const renderer = el.tagName.toLowerCase();
  const wrap = document.getElementById('mapwrap');
  const out = { url: location.href, renderer, pane: [wrap.clientWidth, wrap.clientHeight], dpr: devicePixelRatio };
  const key = (k) => document.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true }));
  const timed = async (fn) => { const t0 = now(); fn(); const t1 = now(); await raf(); await raf(); return [Math.round(t1 - t0), Math.round(now() - t0)]; };
  const stats = (gaps) => { const s = [...gaps].sort((a, b) => a - b); const avg = s.reduce((a, b) => a + b, 0) / s.length; return [avg, s[Math.floor(s.length * 0.9)], s[s.length - 1]].map(v => Math.round(v * 10) / 10); };
  const centre = () => { const r = el.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; };
  const perFrame = async (n, fire) => { const gaps = []; await raf(); let last = now(); for (let i = 0; i < n; i++) { fire(i); await raf(); const t = now(); gaps.push(t - last); last = t; } await raf(); const t = now(); gaps.push(t - last); return stats(gaps); };
  const wheel = (dy) => { const [x, y] = centre(); el.dispatchEvent(new WheelEvent('wheel', { clientX: x, clientY: y, deltaY: dy, deltaMode: 0, bubbles: true, cancelable: true })); };
  const mouse = (type, x, y, target) => (target || el).dispatchEvent(new MouseEvent(type, { clientX: x, clientY: y, button: 0, buttons: type === 'mouseup' ? 0 : 1, bubbles: true, cancelable: true, view: window }));
  const drag = async () => { const [x, y] = centre(); mouse('mousedown', x, y); const s = await perFrame(30, (i) => mouse('mousemove', x + 6 * (i + 1), y + 3 * (i + 1), window)); mouse('mouseup', x + 180, y + 90, window); return s; };
  const fit = () => window.dispatchEvent(new Event('resize'));
  const svgNodes = () => renderer === 'svg' ? document.querySelectorAll('#map *').length : null;
  const playing = document.getElementById('sc-play');
  const pause = () => { if (playing && /⏸/.test(playing.textContent)) playing.click(); };
  out.turn = (document.getElementById('turn') || {}).textContent;
  out.nodesObserver = svgNodes();
  const views = [...document.querySelectorAll('#views button')];
  out.views = views.map(b => b.textContent);
  if (views.length > 1) {
    out.toSeat = await timed(() => views[1].click());
    out.nodesSeat = svgNodes();
    await timed(() => views[0].click());
    out.toSeatAgain = await timed(() => views[1].click());
    out.toObserver = await timed(() => views[0].click());
  }
  const heat = document.getElementById('tg-heat'); if (heat && !heat.checked) heat.click();
  await raf(); await raf();
  out.seekHome = await timed(() => key('Home')); pause(); await raf(); await raf();
  out.seekEnd = await timed(() => key('End')); pause(); await raf(); await raf();
  fit(); await raf(); await raf();
  out.zoomIn = await perFrame(20, () => wheel(-100));
  out.dragAt8x = await drag();
  out.zoomOut = await perFrame(20, () => wheel(100));
  fit(); await raf(); await raf();
  out.dragAtFit = await drag();
  fit(); await raf(); await raf();
  const pos = document.getElementById('sc-pos'), speed = document.getElementById('sc-speed');
  if (pos && speed) {
    pos.value = Math.round(pos.max * 0.97); pos.dispatchEvent(new Event('input', { bubbles: true }));
    await sleep(600); await raf();
    const opt = [...speed.options].map(o => parseFloat(o.value)); speed.value = String(Math.max(...opt)); speed.dispatchEvent(new Event('change', { bubbles: true }));
    if (playing && /▶/.test(playing.textContent)) playing.click();
    out.live = await perFrame(180, () => {});
    pause();
  }
  await sleep(500);
  out.idle = await perFrame(30, () => {});
  return JSON.stringify(out);
})()`;

const SEAT_VIEW = `(async () => {
  const raf = () => new Promise(r => requestAnimationFrame(r));
  const b = document.querySelectorAll('#views button'); if (b.length > 1) b[1].click();
  await raf(); await raf(); window.dispatchEvent(new Event('resize')); await raf(); await raf();
  return b.length;
})()`;
const TEN_TICKS = `(async () => {
  const raf = () => new Promise(r => requestAnimationFrame(r));
  const el = [...document.querySelectorAll('#mapwrap > svg, #mapwrap > canvas')].find(e => !e.classList.contains('off'));
  const r = el.getBoundingClientRect(); const x = r.left + r.width / 2, y = r.top + r.height / 2;
  for (let i = 0; i < 10; i++) { el.dispatchEvent(new WheelEvent('wheel', { clientX: x, clientY: y, deltaY: -100, deltaMode: 0, bubbles: true, cancelable: true })); await raf(); }
  await new Promise(r => setTimeout(r, 400)); await raf(); await raf();
  return [x, y];
})()`;

const browser = await connect((await json("/version")).webSocketDebuggerUrl);
if (mode === "measure") {
  for (const url of rest) {
    const { p, close } = await openTab(browser, url);
    const vis = await p.evaluate(SETTLE);
    if (vis !== "visible") console.error(`${url}: the tab is ${vis}, animation frames will not fire`);
    console.log(await p.evaluate(MEASURE));
    await close();
  }
} else if (mode === "heap") {
  for (const url of rest) {
    const { p, close } = await openTab(browser, url);
    await p.evaluate(SETTLE);
    await p.send("HeapProfiler.collectGarbage"); await new Promise((r) => setTimeout(r, 1500)); await p.send("HeapProfiler.collectGarbage");
    console.log(url, await p.evaluate("Math.round(performance.memory.usedJSHeapSize / 1048576)"), "MB");
    await close();
  }
} else if (mode === "shots") {
  const [url, prefix] = rest;
  const { p, close } = await openTab(browser, url);
  await p.evaluate(SETTLE); await p.evaluate(SEAT_VIEW);
  const shot = async (file) => writeFileSync(file, Buffer.from((await p.send("Page.captureScreenshot", { format: "png" })).data, "base64"));
  await shot(`${prefix}-fit.png`); await p.evaluate(TEN_TICKS); await shot(`${prefix}-zoom.png`);
  console.log(`${prefix}-fit.png ${prefix}-zoom.png`);
  await close();
} else {
  console.error("usage: viz_bench.mjs measure|heap <url>... | shots <url> <prefix>");
  process.exit(2);
}
browser.close();
