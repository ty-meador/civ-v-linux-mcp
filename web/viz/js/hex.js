// Odd-r offset hexes, y growing north (mirrors harness/hexgrid.py). Pointy-top.
export const R = 9;                       // hex circumradius in map units before zoom
export const HW = Math.sqrt(3) * R;       // hex width
export const VS = 1.5 * R;                // vertical spacing between rows

export function wrapX(x, w) { return ((x % w) + w) % w; }
export function key(x, y, w) { return y * w + x; }
export function unkey(k, w) { return [k % w, Math.floor(k / w)]; }

// Screen centre of plot (x, y) on a map h rows tall (north row on top).
export function centre(x, y, h) {
  return [(x + (y & 1) * 0.5 + 0.5) * HW, (h - 1 - y) * VS + R];
}

const CORNERS = Array.from({ length: 6 }, (_, i) => {
  const a = Math.PI / 180 * (60 * i - 30);
  return [R * Math.cos(a), R * Math.sin(a)];
});
export function polygon(cx, cy, scale = 1) {
  return CORNERS.map(([dx, dy]) => `${(cx + dx * scale).toFixed(2)},${(cy + dy * scale).toFixed(2)}`).join(" ");
}

export function toCube(x, y) { const q = x - (y - (y & 1)) / 2; return [q, y, -q - y]; }
export function distance(x0, y0, x1, y1, w) {
  const plain = (ax, ay, bx, by) => {
    const [aq, ar, as] = toCube(ax, ay), [bq, br, bs] = toCube(bx, by);
    return Math.max(Math.abs(aq - bq), Math.abs(ar - br), Math.abs(as - bs));
  };
  if (!w) return plain(x0, y0, x1, y1);
  return Math.min(plain(x0, y0, x1 - w, y1), plain(x0, y0, x1, y1), plain(x0, y0, x1 + w, y1));
}

// Normalise a [x, y] pair from a ledger row onto the map (wrap x, drop rows off the map).
export function onMap([x, y], w, h) {
  if (!Number.isInteger(x) || !Number.isInteger(y) || y < 0 || y >= h) return null;
  return [wrapX(x, w), y];
}

// ---------------------------------------------------------------- canvas helpers (CANVAS_MIGRATION phase 1)
// The plot under a point in map units (the inverse of `centre`): the nearest hex centre is the containing hex.
// Returns [x, y] with x wrapped when `wrap`, else null for a point past the map's edge.
export function plotAt(px, py, w, h, wrap = true) {
  if (!w || !h) return null;
  const ry = Math.round((py - R) / VS);
  let best = null, bestD = Infinity;
  for (let r = ry - 1; r <= ry + 1; r++) {
    const y = h - 1 - r;
    if (y < 0 || y >= h) continue;
    const xf = px / HW - (y & 1) * 0.5 - 0.5;
    for (let x = Math.floor(xf); x <= Math.ceil(xf); x++) {
      const [cx, cy] = centre(x, y, h);
      const d = (cx - px) ** 2 + (cy - py) ** 2;
      if (d < bestD) { bestD = d; best = [x, y]; }
    }
  }
  if (!best) return null;
  if (best[0] < 0 || best[0] >= w) { if (!wrap) return null; best[0] = wrapX(best[0], w); }
  return best;
}

// The plot range a viewport shows under a zoom transform {x, y, k} (screen = map * k + [x, y]) on a W x H
// pixel canvas: {x0, x1, y0, y1} inclusive, clipped to the map, with a one-plot margin; null when nothing shows.
export function visibleRange(t, W, H, w, h) {
  if (!w || !h || !(t.k > 0)) return null;
  const mx0 = (0 - t.x) / t.k, mx1 = (W - t.x) / t.k, my0 = (0 - t.y) / t.k, my1 = (H - t.y) / t.k;
  const x0 = Math.max(0, Math.floor(mx0 / HW) - 1), x1 = Math.min(w - 1, Math.ceil(mx1 / HW) + 1);
  const yTop = h - 1 - Math.floor((my0 - R) / VS) + 1, yBot = h - 1 - Math.ceil((my1 - R) / VS) - 1;
  const y0 = Math.max(0, yBot), y1 = Math.min(h - 1, yTop);
  if (x0 > x1 || y0 > y1) return null;
  return { x0, x1, y0, y1 };
}

// Trace a hex at (cx, cy) onto anything with moveTo / lineTo / closePath (a 2D context, a Path2D, a test stub).
export function tracePath(ctx, cx, cy, scale = 1) {
  for (let i = 0; i < 6; i++) {
    const [dx, dy] = CORNERS[i];
    if (i === 0) ctx.moveTo(cx + dx * scale, cy + dy * scale); else ctx.lineTo(cx + dx * scale, cy + dy * scale);
  }
  ctx.closePath();
}
