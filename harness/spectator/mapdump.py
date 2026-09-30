"""The static map, once: terrain, elevation, features, rivers and resources for every plot, fog ignored.

Character grids in revealed_map's convention (rows[0] is the north row y = h - 1, each string runs x = 0 .. w - 1,
odd rows sit half a hex to the east) with a legend per lettered layer. The Lua runs through the raw client (query.py ships it in
chunks) and depends on nothing the runtime installs. A Huge map is ~10 KB per layer.
"""
from __future__ import annotations

from typing import Any

from . import query as Q

TERRAIN_CHARS = {"TERRAIN_GRASS": "G", "TERRAIN_PLAINS": "P", "TERRAIN_DESERT": "D", "TERRAIN_TUNDRA": "T",
                 "TERRAIN_SNOW": "S", "TERRAIN_COAST": "C", "TERRAIN_OCEAN": "O"}

LUA = r"""
local w, h = Map.GetGridSize()
local TC = { TERRAIN_GRASS = "G", TERRAIN_PLAINS = "P", TERRAIN_DESERT = "D", TERRAIN_TUNDRA = "T",
             TERRAIN_SNOW = "S", TERRAIN_COAST = "C", TERRAIN_OCEAN = "O" }
local POOL = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
local function legend_new() return { by = {}, n = 0, names = {} } end
local function letter(lg, name)
  local c = lg.by[name]
  if c then return c end
  lg.n = lg.n + 1
  if lg.n > #POOL then return "?" end
  c = POOL:sub(lg.n, lg.n)
  lg.by[name] = c
  lg.names[c] = name
  return c
end
local function tname(t) return t and (t:gsub("^FEATURE_", ""):gsub("^RESOURCE_", "")) or "?" end
local feat, res = legend_new(), legend_new()
local out = { ok = true, w = w, h = h, wrap = Map.IsWrapX(), layers = { terrain = {}, elev = {}, feature = {}, river = {}, resource = {} } }
for y = h - 1, 0, -1 do
  local t, e, f, r, s = {}, {}, {}, {}, {}
  for x = 0, w - 1 do
    local p = Map.GetPlot(x, y)
    if not p then
      t[#t + 1] = " "; e[#e + 1] = " "; f[#f + 1] = " "; r[#r + 1] = " "; s[#s + 1] = " "
    else
      local ti = GameInfo.Terrains[p:GetTerrainType()]
      local tc = TC[ti and ti.Type or ""] or "?"
      if p.IsLake and p:IsLake() then tc = "L" end
      t[#t + 1] = tc
      e[#e + 1] = p:IsMountain() and "M" or (p:IsHills() and "^" or ".")
      local ft = p:GetFeatureType()
      if ft and ft >= 0 then
        local fi = GameInfo.Features[ft]
        f[#f + 1] = letter(feat, tname(fi and fi.Type))
      else
        f[#f + 1] = "."
      end
      r[#r + 1] = p:IsRiver() and "r" or "."
      local rt = p:GetResourceType(-1)
      if rt and rt >= 0 then
        local ri = GameInfo.Resources[rt]
        s[#s + 1] = letter(res, tname(ri and ri.Type))
      else
        s[#s + 1] = "."
      end
    end
  end
  local L = out.layers
  L.terrain[#L.terrain + 1] = table.concat(t); L.elev[#L.elev + 1] = table.concat(e)
  L.feature[#L.feature + 1] = table.concat(f); L.river[#L.river + 1] = table.concat(r)
  L.resource[#L.resource + 1] = table.concat(s)
end
out.legend = { feature = feat.names, resource = res.names,
               terrain = { G = "Grassland", P = "Plains", D = "Desert", T = "Tundra", S = "Snow", C = "Coast", O = "Ocean", L = "Lake" },
               elev = { ["."] = "flat", ["^"] = "hills", M = "mountain" } }
return out
"""


def read(client: Any, timeout: float = 120) -> dict:
    """The map dump from a raw client (`Civ5.query`)."""
    return Q.query(client, LUA, timeout=timeout)


def valid(m: Any) -> bool:
    if not isinstance(m, dict) or not m.get("ok"):
        return False
    w, h = m.get("w"), m.get("h")
    layers = m.get("layers")
    if not (isinstance(w, int) and isinstance(h, int) and isinstance(layers, dict)):
        return False
    grid = layers.get("terrain")
    return isinstance(grid, list) and len(grid) == h and all(isinstance(s, str) and len(s) == w for s in grid)
