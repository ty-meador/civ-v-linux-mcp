# Moving the spectator map from SVG to canvas

Status: plan, 2026-10-08. Nothing below is built yet. See [VISUALIZATION.md](VISUALIZATION.md) for the page as it is.

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
If d3 is to go, replace the CDN tag with a vendored `d3-zoom` build in the same commit or the next.

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
