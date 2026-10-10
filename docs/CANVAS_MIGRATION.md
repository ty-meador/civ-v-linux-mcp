# Moving the spectator map from SVG to canvas

Status: done. Phases 0 to 4 on 2026-10-08 (the baseline and the phase 4 numbers are at the end of this document;
`hex.plotAt`, `hex.visibleRange` and `hex.tracePath` are in `web/viz/js/hex.js` with a node test;
`web/viz/js/map_canvas.js` is the renderer; its `tipAt` hit test and pointer handler fill the tooltip div with the
text the SVG `<title>` gave, checked word for word against the SVG renderer at 1x and at a 4.6x zoom), the
side-by-side on two real recordings on 2026-10-09 (the England game at t133 and the 2026-09-30 hotseat; the
section before last), and phase 5 the same day: the canvas is the only renderer, `map.js` and the `?renderer=`
switch are gone. See [VISUALIZATION.md](VISUALIZATION.md) for the page as it is; `scripts/viz_bench.mjs` is the
measurement driver (the last section).

## Why

The map is drawn as SVG: one `<polygon>` per plot in the terrain layer (plus a `<title>`, a feature glyph and a
resource dot where there is one), another polygon per non-visible plot in a seat view's fog, another per owned
plot in the borders layer, and a `<g>` per unit and city. On the 104x64 maps played so far that is roughly
20,000 DOM nodes at rest, and it has been fine: 70-72 MB of heap through three seeks, no jank anyone noticed.

It stops being fine as maps grow, for three reasons that are structural to SVG rather than to d3:

- **Zoom and pan re-rasterise the whole tree.** `d3.zoom` sets one `transform` on the root `<g>`; the browser
  then repaints every node under it on every wheel tick and drag frame. Cost is proportional to the map, not
  to the screen.
- **The fog and borders layers re-run a full keyed join per snapshot.** On a seat view that is one data join
  over every plot the seat cannot see (most of the map, early on), and the DOM diff of it, every 8 s while the
  world moves and after every write-kind call.
- **Per-frame layers are DOM mutations.** While attention is live the page redraws on `requestAnimationFrame`:
  units, cities, pulses and heat each go through a join and attribute updates. That is hundreds of attribute
  writes per frame on a busy turn, before the browser's own style and layout pass.

Civ V's stock sizes run from Duel (40x24) through Standard (80x52) and Large (104x64, the maps played so far)
to Huge (128x80, 10,240 plots); custom scripts go to 180x94 and beyond (17,000+). At Huge the SVG tree passes
30,000 nodes at rest; at a giant custom map it passes 50,000, and zooming starts to drop frames on an ordinary
laptop.

Canvas inverts every one of those costs: drawing is proportional to what is on screen (cull to the viewport),
a static layer is one bitmap blit per frame however many plots it holds, and per-frame layers are plain fills
with no retained tree to diff.

## What stays the same

The migration is contained. These do not change:

- `world.js`, `attention.js`, `timeline.js`, `feed.js`, `scrub.js`, `panels.js`: no rendering in them.
- The snapshot, hello, call and event formats; the spectator server and its Lua.
- `HexMap`'s public surface as `app.js` uses it: `build()`, `clear()`, `fit()`, `drawFog(seat)`,
  `drawBorders(known)`, `drawAttention(rows, hueOf)`, `drawHeat(rows, hueOf)`, `drawPieces(colourKeys, shows)`,
  `caption(x, y, html, hue, ttl)`, `placeCaptions()`, the `show` flags and `transform`. `app.js` changes only
  in which element it hands the constructor.
- Captions stay HTML `<div>`s positioned through `transform.apply`, exactly as now.
- `d3.zoom` stays for pan, wheel, touch and the fit transform; it works on any element. The panels module's
  one data join stays. Whether to drop the d3 CDN tag afterwards is a separate decision (d3-zoom alone is a
  small module and could be vendored).

## Design

### One visible canvas, two cached bitmaps

`#mapwrap` holds one `<canvas id="map">` sized to the wrapper at `devicePixelRatio`, with the captions div and
a new `#tip` tooltip div over it. Each frame composes three things:

| Layer | Holds | Redrawn when |
|---|---|---|
| terrain cache (offscreen canvas) | greyscale hexes, river strokes, feature glyphs, resource dots | a hello (new map), the zoom gesture ends, a resize |
| world cache (offscreen canvas) | fog over the terrain, borders | a `full` redraw: snapshot, view switch, border toggle, and whenever the terrain cache is redrawn |
| live pass (straight onto the visible canvas) | heat, attention fills, intent outlines, units, cities, city labels | every `redraw()` call, as now |

Both caches are rendered **in screen space at the current transform**, not in map units, so they are crisp at
rest. During a drag or wheel gesture the frame blits the stale caches through the delta between the cached
transform and the live one (slightly soft while moving) and the live pass draws at the true transform; on
`zoom.end` both caches re-render. This is the standard canvas pattern and is why the zoom handler gets a
`start`/`zoom`/`end` split instead of one callback.

Drawing the whole terrain of a 128x80 map is roughly 10,000 path fills; at canvas speeds that is a few
milliseconds, well under a frame, so the caches exist to make the common frame (nothing changed, blit twice,
draw pieces) nearly free rather than to make the rare full render possible.

### Cull to the viewport

Every pass starts by inverting the transform on the canvas corners to a plot range (`hex.visibleRange`), then
loops only those rows and columns. A giant map scrolled in at 8x zoom costs the same as a Duel map. Fog and
borders iterate the range, not the map; pieces are filtered by range before drawing.

### Hit testing replaces `<title>`

SVG gave hover titles on plots and units for free. Canvas needs:

- `hex.plotAt(px, py, w, h)`: screen point (after the inverse transform) to the odd-r offset plot under it,
  or null. Pure function in `hex.js` next to `centre`, round-trip tested under node.
- A per-frame index `Map<plotKey, {cities:[], units:[]}>` built in `drawPieces` from the shown pieces.
- One `pointermove` handler on the canvas (throttled to a frame) that looks up the plot, fills `#tip` with the
  same text the titles carried today (terrain, elevation, feature, resource; unit type, id, hp, owner) and places
  it like a caption; `pointerleave` hides it.

### Mapping SVG attributes to 2D-context calls

| SVG today | Canvas |
|---|---|
| `points` string per hex via `H.polygon` | `H.tracePath(ctx, cx, cy, scale)` (moveTo/lineTo the six corners; a `Path2D` per scale cached and translated) |
| `fill-opacity` / `stroke-opacity` | `globalAlpha` around the fill or stroke |
| `mix-blend-mode: screen` on attention and heat | `globalCompositeOperation = "screen"` for those passes |
| `stroke-dasharray` on intent outlines and civilian unit rings | `setLineDash` |
| `paint-order: stroke` on city labels | `strokeText` then `fillText` |
| `opacity` 0.55 / 0.5 on pieces out of colour | `globalAlpha` for that piece |
| `<title>` | hit testing, above |
| `role="img" aria-label` on the svg | the same attributes on the canvas |

Fonts: SVG text and canvas text rasterise differently. Set `ctx.font` from the page's `--mono`/`--ui` variables
once and compare the glyphs at the fit zoom and at 4x before calling parity done; the unit glyphs are 6.5 px
at 1x and are the most sensitive.

### Device pixels and resize

The backing store is `clientWidth * dpr` by `clientHeight * dpr`; `ctx.setTransform(dpr, 0, 0, dpr, 0, 0)` is
composed under the zoom transform. `resize` re-sizes the store, re-renders both caches and calls `fit()` as now.

## Phases

Each phase is a commit on main that leaves the page working. The SVG renderer is kept, selectable, until phase 5.

**0. Baseline.** A script `scripts/synth_recording.py` writes a synthetic spectator recording for any map size
(hello with a generated terrain of the right shape, a few snapshots with a few hundred units and cities, per-seat
fog grids, a handful of calls with plot refs). Serve it with `--replay` and measure the current SVG page in
Chrome at 104x64, 128x80 and 200x120: time to first paint after hello, `drawFog` time per snapshot, frame time
during a wheel zoom, heap at rest. Record the numbers in this document. These are what phase 4 beats.

**1. Pure helpers.** `hex.plotAt`, `hex.visibleRange(transform, W, H, w, h)`, and a `Path2D`-free
`hex.tracePath` that takes any object with `moveTo`/`lineTo`/`closePath`. Node tests: `plotAt(centre(x,y))`
round-trips every plot of a 10x7 map including the wrap column, `visibleRange` at the fit transform returns the
whole map and at 8x returns a window. No page change.

**2. The canvas renderer behind a flag.** `web/viz/js/map_canvas.js` implementing the `HexMap` surface over a
2D context with the two caches, the zoom split and viewport culling. `index.html` gains the canvas and tooltip
elements; `app.js` picks the renderer from `?renderer=canvas|svg` (default stays svg in this phase). Node test:
a stub context that records `fill`/`stroke`/`fillText` counts shows `build()` on a 20x12 map traces 240 hexes,
`drawFog` at a transform showing a 5x5 window traces at most 25, and `drawPieces` draws the pieces inside the
range only.

**3. Hit testing and tooltips.** The pointer handler, the per-frame piece index, `#tip` styling matching the
captions. Verified in Chrome against the 2026-09-30 replay: hover a plot and a unit at 1x and 4x and read the
same text the SVG title gave.

**4. Parity and performance in Chrome.** With the phase 0 recordings and the live England game: side by side
`?renderer=svg` and `?renderer=canvas` at the three sizes, both views (observer and a seat with fog), heat and
ghost on, a seek backwards (rebuild), a seek forwards, a wheel zoom to 8x and back, a resize. Check the fog
levels, border tints, pulse/hold/intent alphas, dashed civilian rings, the capital's white ring, label strokes.
Record frame and pass times beside the baseline. Fix what differs.

**5. Switch and remove.** Default to canvas, delete `map.js` and the flag, drop `svg#map` from the CSS,
update VISUALIZATION.md's file table and the fog paragraph, CHANGELOG, SESSION_HANDOFF, and cut a release.
If d3 is to go, replace the CDN tag with a vendored `d3-zoom` build in the same commit or the next. (Done
2026-10-09, after the real-recording section below; d3 stays, the panels and the zoom still use it.)

## Risks and what to watch

- **Soft frames during a zoom gesture.** The stale-cache blit is a deliberate trade; if it reads as blurry on a
  HiDPI screen, re-render the caches on a short debounce (120 ms) during the gesture rather than only at `end`.
- **Memory of the caches.** Two full-window RGBA bitmaps at dpr 2 on a 2560x1440 window are about 60 MB
  together. That is the budget; a third cache is not free.
- **`drawPieces` ordering.** SVG layers stacked cities under units under labels implicitly; the live pass must
  draw in that order explicitly, and heat under attention under intent.
- **The attention `screen` blend.** Composite operations apply per draw call, so set and reset around the pass;
  a leaked `screen` mode will wash every unit out, which is easy to miss on a dark map.
- **Text under `screen` / `globalAlpha`.** Population and glyph text are drawn after resetting both.
- **Tests under node have no canvas.** The stub context in phase 2 is the test surface; keep the renderer free
  of DOM calls outside the constructor and the pointer handler so it can run against the stub.
- **A hello mid-gesture.** `build()` during a drag must invalidate both caches and let the gesture finish.

## Size

`map.js` is 185 lines; the canvas renderer should land near 300 with the caches, culling and tooltip, `hex.js`
grows by about 30, tests by two cases, `synth_recording.py` is about 80 lines. Phases 1 to 3 are a day each
with verification; phase 4 is the one that takes as long as it takes.

## Baseline: the SVG page, Chrome, 2026-10-08

`scripts/synth_recording.py --size WxH` wrote three recordings (6 snapshots, 600 units, 57-72 cities, 2 human
seats with fog grids, 94 rows); each was served with `python -m harness.spectator --replay ... --port 877N`
and measured in Chrome on a 1560x908 map pane at device pixel ratio 1, one page at a time, through a
script run on the page (`javascript_tool`): a view switch is timed from the click to the second animation
frame after it (`js` is the handler alone, `paint` includes the browser's style, layout and paint), a gesture
is 20 wheel ticks or 30 drag moves fired one per frame with the gaps between frames recorded, a seek is the
scrubber's End / Home key. Numbers are milliseconds. The machine was otherwise idle; one run each, so read
them to the nearest 20 % and the shape of the growth, not the digits.

| | 104x64 (Large) | 128x80 (Huge) | 200x120 |
|---|---|---|---|
| plots | 6,656 | 10,240 | 24,000 |
| SVG nodes at rest, observer | 18,057 | 26,137 | 56,421 |
| of which terrain | 14,550 | 22,380 | 52,540 |
| fog polygons in a seat view | 4,733 | 7,840 | 21,355 |
| first long task at load (parse, hello, build) | 89 | 143 | 302 |
| switch to a seat view: js / paint | 48 / 110 | 48 / 147 | 115 / 316 |
| the same switch a second time | 43 / 126 | 57 / 313 | 137 / 723 |
| back to the observer: js / paint | 14 / 100 | 22 / 272 | 31 / 538 |
| seek End (6 snapshots forward) | 12 / 67 | 14 / 84 | 14 / 131 |
| seek Home (rebuild: hello, build) | 61 / 233 | 85 / 334 | 191 / 686 |
| frame while pulses are live, the page's own redraw: avg / p90 / max | 21 / 38 / 68 | 57 / 177 / 217 | 104 / 338 / 344 |
| wheel zoom in, 20 ticks: avg / p90 / max frame | 36 / 68 / 91 | 63 / 86 / 186 | 113 / 191 / 409 |
| wheel zoom out: avg / p90 / max | 35 / 68 / 73 | 47 / 61 / 75 | 100 / 226 / 253 |
| drag at 4x zoom: avg / max frame | 16 / 17 | 17 / 17 | 16 / 20 |
| drag at the fit zoom: avg / max | 18 / 54 | 24 / 161 | 24 / 256 |
| JS heap at rest (MB) | 7 | 8 | 29 |
| frame at rest, nothing live | 16.7 | 16.7 | 16.7 |

What it says:

- **The page is already past 60 fps on Large during a zoom**: 36 ms a frame on average, 91 at worst. At Huge
  a wheel zoom averages 63 ms and at 200x120 it is 113 with 400 ms stalls. That is the whole-tree repaint.
- **The per-frame live pass costs more than the gesture**: while pulses are live the page's own redraw runs
  57 ms a frame at Huge and 104 at 200x120, before anyone touches the mouse. That is `drawPieces` and the
  attention joins as DOM mutations. On the 104x64 game played so far it is 21 ms, which is why it has not shown.
- **A seat view switch is a fog join**: the handler alone is 115 ms at 200x120 and the paint after it 300-700,
  and it gets slower the second time (the join is diffing against the previous fog, not building fresh).
- **A drag while zoomed in is fine at every size** (16 ms: the browser only repaints what moved into view), a
  drag at the fit zoom stalls at the larger sizes, and the heap stays small: memory is not the problem, the
  node count is.
- **The rebuild on a seek backwards** (hello, `build()`, repaint) is 0.7 s at 200x120.

Targets for phase 4 on the same recordings and pane: a wheel zoom and the live pass under 16 ms a frame at
every size (the live pass draws pieces straight to the canvas, the gesture blits two cached bitmaps), a seat
view switch under 50 ms to paint at 200x120 (fog over the visible range only, into the world cache), the
rebuild under 100 ms, heap within 2x of the SVG page (the two caches).

A note for whoever re-measures: a Chrome tab in the background never fires animation frames, so a script that
awaits one hangs there until the tab is in front. Keep the page in the only tab of the automation group and
run one size at a time; or skip the extension and use `scripts/viz_bench.mjs` (the last section), which drives
Chrome's own front window through the DevTools protocol and has no 45 s limit on a script.

## Phase 4: canvas beside SVG, Chrome, 2026-10-08

The same three recordings on ports 8771-8773, the same 1560x908 pane at dpr 1, one script run on both pages in
turn (`?renderer=svg`, `?renderer=canvas`), so the SVG column here is a re-run under that script rather than the
baseline above (it reads a little heavier than the baseline: heat is on for the seeks and drags, and the
view-switch paint is taken at the second animation frame after the click, which on the canvas page is simply
two 16.7 ms frames). Milliseconds; one run each. Where a number is the frame cadence (16.7, or 33 for two
frames) the work finished inside it.

| | 104x64 svg / canvas | 128x80 svg / canvas | 200x120 svg / canvas |
|---|---|---|---|
| switch to a seat view: js / paint | 33 / 244 · 7 / 33 | 51 / 157 · 8 / 33 | 116 / 347 · 16 / 32 |
| back to the observer: js / paint | 16 / 167 · 5 / 33 | 19 / 156 · 7 / 33 | 39 / 371 · 6 / 35 |
| seek End from the start (6 snapshots): js / paint | 17 / 187 · 10 / 34 | 16 / 217 · 11 / 34 | 19 / 276 · 12 / 36 |
| seek Home (rebuild: hello, build): js / paint | 58 / 128 · 11 / 33 | 96 / 283 · 14 / 33 | 211 / 767 · 43 / 50 |
| wheel zoom in to 8x, 20 ticks: avg / max frame | 51 / 103 · 16.6 / 16.7 | 87 / 225 · 16.6 / 17 | 148 / 355 · 16.5 / 16.8 |
| wheel zoom out: avg / max | 57 / 109 · 16.6 / 16.8 | 63 / 140 · 16.6 / 16.8 | 98 / 330 · 16.6 / 16.9 |
| drag at 8x: avg / max | 19 / 22 · 16.7 / 16.9 | 20 / 25 · 16.7 / 16.8 | 26 / 32 · 16.7 / 16.8 |
| drag at the fit zoom: avg / max | 70 / 134 · 16.7 / 16.8 | 110 / 215 · 16.7 / 16.8 | 232 / 444 · 16.7 / 16.8 |
| frame while pulses are live: avg / p90 / max | 31 / 75 / 115 · 16.7 / 16.8 / 19.6 | 35 / 105 / 224 · 16.7 / 16.8 / 17.9 | 87 / 304 / 363 · 16.7 / 16.8 / 17 |
| JS heap at the end (MB) | 18 · 7 | 10 · 11 | 15 · 8 |

The canvas passes themselves, 200x120 at the fit zoom (every plot in the window), after the chunking below:
the terrain cache renders in 23-31 ms (it was 42-49), a seat's fog and the borders in 8-12 (it was 27), the live
pass in 2-6. The terrain render happens on a rebuild, a resize and at the end of a zoom gesture that shows the
whole map; at a close zoom the window is a few hundred plots and both caches render in under a millisecond.

Every target is met on the synthetic recordings: the zoom and the live pass are at the frame at every size,
the seat view paints in 32 ms at 200x120, the rebuild in 50, the heap is below the SVG page's. The live England
game was not running during this pass; the side-by-side on its recording, and on the 2026-09-30 one, is the
section after the profile notes.

**Parity.** The seat view at a 3.7x zoom on 104x64 (the same ten wheel ticks from the fit on each page) captured
on both renderers: the two fog levels, the border tints and edges, the dashed civilian ring, the grey
out-of-colour cities and units, the capital's white ring, the stroked city labels and the feature glyphs read the
same; the observer view at the fit zoom with heat and ghost on likewise. A window resize refits the canvas (the
backing store follows the pane, the fit transform recomputes). No console errors on any page.

**What the profile taught.** A `fill()` per hex is the cost of a full-map pass (0.9 us each, 22 ms for the
24,000 fills of 200x120, and the same again for the strokes); one path for all the hexes of a colour is not the
answer, it is 50x slower (2 s for the terrain, 0.7 s for the fog: Chrome's fill cost grows faster than the subpath
count). Eight hexes a path is the sweet spot (28 / 10 / 11 / 14 ms for the fog pass at 1 / 8 / 32 / 128 a path),
so `paintHexes` traces hexes eight at a time and fills each path; distinct plots never overlap, so the union
paints as the hexes would one by one. Translucent strokes (rivers at 0.7, borders at 0.35) stay one per hex: in
one path a shared seam composites once, as separate polygons (the SVG) it composites twice, and a chunk boundary
would make the seams uneven. The plain hex edges are opaque, so they chunk too.

## Real recordings: canvas beside SVG, Chrome, 2026-10-09

The live game was not up, so two real recordings stood in for it, each served with `--replay`: the England
game's spectator recording of 2026-10-08 (`logs/spectate_england_2026-10-08.jsonl`: the 104x64 map, the t133
snapshot with 752 units and 77 cities, England's fog grid, no call rows) and the 2026-09-30 hotseat recording
(80x52, 1,386 snapshots and two seats' calls, 72 MB). Measured through `scripts/viz_bench.mjs` (below): a real
Chrome window at 1920x1080, a 1540x898 map pane at dpr 1, the phase 4 gestures under one script on
`?renderer=svg` and `?renderer=canvas` in turn, one run each. Milliseconds; 16.7 is the frame.

| | England t133, 104x64: svg / canvas | 2026-09-30 t152, 80x52: svg / canvas |
|---|---|---|
| SVG nodes, observer / seat view | 19,789 / 22,377 | 12,338 / 13,927 |
| switch to a seat view: js / paint | 43 / 135 · 11 / 33 | 28 / 84 · 6 / 33 |
| the same switch a second time | 40 / 134 · 10 / 34 | 22 / 83 · 6 / 33 |
| back to the observer | 25 / 133 · 16 / 36 | 15 / 67 · 8 / 33 |
| seek Home (rebuild) | 69 / 195 · 9 / 30 | 41 / 83 · 7 / 33 |
| seek End | 20 / 101 · 10 / 34 | 45 / 129 · 18 / 34 |
| wheel zoom in, 20 ticks: avg / p90 / max frame | 44 / 56 / 75 · 16.7 / 16.8 / 16.9 | 29 / 40 / 56 · 16.7 / 16.8 / 17 |
| wheel zoom out | 47 / 77 / 82 · 16.7 / 16.7 / 16.9 | 31 / 52 / 57 · 16.7 / 16.9 / 17.1 |
| drag at 8x: avg / max | 16.7 / 17 · 16.7 / 17 | 16.7 / 17.2 · 16.7 / 17.1 |
| drag at the fit: avg / p90 / max | 68 / 76 / 132 · 16.7 / 16.8 / 18.1 | 44 / 46 / 84 · 16.7 / 16.8 / 16.8 |
| the player at its top speed, 180 frames: avg / p90 / max | 17 / 17 / 60 · 16.7 / 16.8 / 19.7 | 18 / 30 / 50 · 16.7 / 16.8 / 20 |
| JS heap, a fresh tab, after a forced GC (MB) | 3 · 2 | 68 · 68 |

The same shape as the synthetic sizes: the SVG page spends 44 ms a frame in a wheel zoom and 68 in a drag at
the fit on the real Large map (its worst frames 75 and 132), the canvas page sits on the frame through every
gesture, a seat view paints in 33 ms against 135, the rebuild in 30 against 195. The England "player" row is
the player ticking over a recording with no calls (a snapshot re-applied; the SVG's 60 ms worst frame is that),
the 2026-09-30 row has calls arriving and pulses live. The heap on the 72 MB recording is the recording itself
(the page holds every parsed row, SESSION_HANDOFF) and the renderers differ by nothing there; read it in a
fresh tab, as the script does: measured across navigations in one tab it grew by about 67 MB a page, the
back/forward cache keeping each previous document alive.

**Parity** on the England recording: the seat view at the fit and after ten wheel ticks (4x) captured on both
pages read the same to the eye (the two fog levels, border tints, city labels and population, unit glyphs, the
capital's ring). The canvas tip at three screen points gave `(52,32) P · CITRUS`, `(43,28) O`, `(60,34) P JUNGLE`
at the fit and `(49,31) G ^ FOREST` among the zoomed points, the text the SVG `<title>` gave under the same points
wherever an `elementFromPoint` walk reached a title on the SVG page (the centre point there landed on an element
without one). No page errors on either renderer.

## The driver: scripts/viz_bench.mjs

Start a Chrome on a scratch profile with `--remote-debugging-port=9222 --remote-allow-origins='*'` (the default
profile refuses the port), serve a recording with `--replay`, then `node scripts/viz_bench.mjs measure <url>...`
prints one JSON line a page with the rows above, `heap <url>...` the JS heap after a forced GC with each page in a
fresh tab, `shots <url> <prefix>` two PNGs of the seat view (the fit, ten wheel ticks in). Each page opens in its
own tab in a 1920x1080 window in front, so animation frames fire; page exceptions and console errors go to
stderr. The extension's tab was the reason for the script: on 2026-10-09 the window it opened came up 500x37 and
hidden under COSMIC, and its scripts stop at 45 s in any case.
