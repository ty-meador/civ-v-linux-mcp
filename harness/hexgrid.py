"""Civ V's hex grid in Python: odd-r offset coordinates ("odd rows sit half a hex to the east"), y growing north.

Shared by the attention extractor (a tactical_view lights the disk around its unit) and the spectator. The engine
is the authority on adjacency in play (H.tactical_view uses Map.PlotDirection); this is only for drawing and for
naming which plots a reply covered. `web/viz/js/hex.js` mirrors it.
"""
from __future__ import annotations


def to_cube(x: int, y: int) -> tuple[int, int, int]:
    q = x - (y - (y & 1)) // 2
    r = y
    return q, r, -q - r


def distance(x0: int, y0: int, x1: int, y1: int, width: int | None = None) -> int:
    """Hex distance; with `width`, the shorter way round an east-west wrapping map."""
    def plain(ax: int, ay: int, bx: int, by: int) -> int:
        aq, ar, as_ = to_cube(ax, ay)
        bq, br, bs = to_cube(bx, by)
        return max(abs(aq - bq), abs(ar - br), abs(as_ - bs))
    if not width:
        return plain(x0, y0, x1, y1)
    return min(plain(x0, y0, x1 + k * width, y1) for k in (-1, 0, 1))


def disk(x: int, y: int, radius: int) -> list[list[int]]:
    """Every plot within `radius` of (x, y), centre first, as [x, y] pairs. Not wrapped and not clipped: the
    caller (the page) knows the map size; here we only know the reply."""
    out = [[x, y]]
    for dy in range(-radius, radius + 1):
        for dx in range(-radius - 1, radius + 2):
            px, py = x + dx, y + dy
            if (px, py) != (x, y) and distance(x, y, px, py) <= radius:
                out.append([px, py])
    return out
