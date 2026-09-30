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
