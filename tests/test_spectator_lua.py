"""The spectator's two Lua queries (harness/spectator/mapdump.py, snapshot.py) run against a tiny fake engine under
lupa: they must compile as Lua 5.1, read the map and the pieces without fog, ask about fog only for the seats' own
grids, and produce grids the parsers accept."""
from __future__ import annotations

import unittest

from harness.spectator import mapdump, snapshot

try:
    import lupa
except ImportError:  # pragma: no cover
    lupa = None

FAKE = r"""
local W, H = 3, 2
FOG_OK = true
local plots = {}
local function plot(x, y, o)
  return {
    GetTerrainType = function() return o.t end, IsLake = function() return o.lake == true end,
    IsMountain = function() return o.m == true end, IsHills = function() return o.h == true end,
    GetFeatureType = function() return o.f or -1 end, IsRiver = function() return o.r == true end,
    GetResourceType = function(_, team) assert(team == -1, "resource read must ignore reveal"); return o.res or -1 end,
    GetOwner = function() return o.owner or -1 end,
    -- fog is asked only for the snapshot's per-seat grids; o.fog maps team -> "v" (visible) / "f" (revealed)
    IsVisible = function(_, team, debug) assert(FOG_OK and debug == false, "no fog here"); return (o.fog or {})[team] == "v" end,
    IsRevealed = function(_, team, debug) assert(FOG_OK and debug == false, "no fog here"); return (o.fog or {})[team] ~= nil end,
  }
end
plots["0,0"] = plot(0, 0, { t = 0, h = true, f = 0, r = true, res = 1, owner = 0, fog = { [0] = "v" } })
plots["1,0"] = plot(1, 0, { t = 1, fog = { [0] = "v", [1] = "f" } })
plots["2,0"] = plot(2, 0, { t = 2, lake = true })
plots["0,1"] = plot(0, 1, { t = 0, m = true, f = 1, fog = { [0] = "f" } })
plots["1,1"] = plot(1, 1, { t = 0, owner = 1, fog = { [1] = "v" } })
plots["2,1"] = plot(2, 1, { t = 0, owner = 63 })
Map = { GetGridSize = function() return W, H end, IsWrapX = function() return true end,
        GetPlot = function(x, y) return plots[x .. "," .. y] end }
GameInfo = {
  Terrains = { [0] = { Type = "TERRAIN_GRASS" }, [1] = { Type = "TERRAIN_COAST" }, [2] = { Type = "TERRAIN_OCEAN" } },
  Features = { [0] = { Type = "FEATURE_FOREST" }, [1] = { Type = "FEATURE_ICE" } },
  Resources = { [1] = { Type = "RESOURCE_IRON" } },
  Civilizations = { [0] = { ShortDescription = "TXT_CHINA" }, [1] = { ShortDescription = "TXT_MONGOLIA" } },
  Units = { [7] = { Type = "UNIT_ARCHER" } },
  PlayerColors = { [0] = { PrimaryColor = "C_RED", SecondaryColor = "C_WHITE" } },
  Colors = { C_RED = { Red = 1, Green = 0, Blue = 0 }, C_WHITE = { Red = 1, Green = 1, Blue = 1 } },
}
GameDefines = { MAX_CIV_PLAYERS = 64 }
GameplayGameStateTypes = { GAMESTATE_ON = 0 }
DomainTypes = { DOMAIN_LAND = 0, DOMAIN_SEA = 1, DOMAIN_AIR = 2 }
Locale = { ConvertTextKey = function(k) return "L:" .. k end }
Game = { GetGameTurn = function() return 42 end, GetActivePlayer = function() return 1 end, GetGameState = function() return 0 end }
local function unit(id, x, y, civ)
  return { GetID = function() return id end, GetX = function() return x end, GetY = function() return y end,
           GetUnitType = function() return 7 end, GetCurrHitPoints = function() return 90 end,
           GetMaxHitPoints = function() return 100 end, IsCombatUnit = function() return not civ end,
           GetDomainType = function() return 0 end, IsEmbarked = function() return false end }
end
local function city(id, x, y, name)
  return { GetID = function() return id end, GetX = function() return x end, GetY = function() return y end,
           GetPopulation = function() return 5 end, IsCapital = function() return true end,
           GetName = function() return name end, GetMaxHitPoints = function() return 200 end,
           GetDamage = function() return 20 end, IsPuppet = function() return false end }
end
local function iter(list) local i = 0; return function() i = i + 1; return list[i] end end
local function player(pid, opts)
  return {
    IsEverAlive = function() return true end, IsAlive = function() return opts.alive ~= false end,
    IsHuman = function() return opts.human == true end, IsMinorCiv = function() return false end,
    IsBarbarian = function() return pid == 63 end, GetTeam = function() return pid end,
    GetScore = function() return 100 + pid end, GetName = function() return opts.name end,
    GetCivilizationType = function() return pid end, GetGold = function() return 50 end,
    GetPlayerColor = function() return pid end,
    Cities = function() return iter(opts.cities or {}) end, Units = function() return iter(opts.units or {}) end,
  }
end
Players = {
  [0] = player(0, { human = true, name = "Wu", cities = { city(1, 0, 0, "Beijing") }, units = { unit(10, 1, 0) } }),
  [1] = player(1, { human = true, name = "Genghis", units = { unit(11, 1, 1, true) } }),
  [2] = player(2, { alive = false, name = "Dead" }),
  [63] = player(63, { name = "Barbarians", units = { unit(12, 2, 1) } }),
}
"""


@unittest.skipIf(lupa is None, "lupa not installed")
class SpectatorLuaTests(unittest.TestCase):
    def setUp(self):
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(FAKE)

    def run_query(self, body: str):
        fn = self.lua.execute("return function() " + body + " end")
        return _py(fn())

    def test_mapdump_grids_and_legends(self):
        self.lua.execute("FOG_OK = false")                    # the terrain is the spectator's: never fog-gated
        m = self.run_query(mapdump.LUA)
        self.assertTrue(mapdump.valid(m), m)
        self.assertEqual((m["w"], m["h"], m["wrap"]), (3, 2, True))
        L = m["layers"]
        self.assertEqual(L["terrain"], ["GGG", "GCL"])            # north row first; the lake overrides ocean
        self.assertEqual(L["elev"], ["M..", "^.."])
        self.assertEqual(L["river"], ["...", "r.."])
        feat = m["legend"]["feature"]
        self.assertEqual({feat[c] for c in feat}, {"FOREST", "ICE"})
        self.assertEqual(L["feature"][1][0], next(c for c, n in feat.items() if n == "FOREST"))
        res = m["legend"]["resource"]
        self.assertEqual(list(res.values()), ["IRON"])
        self.assertEqual(L["resource"][1], list(res)[0] + "..")

    def test_snapshot_players_cities_units_owners(self):
        s = self.run_query(snapshot.LUA)
        self.assertTrue(snapshot.valid(s), s)
        self.assertEqual((s["turn"], s["active"], s["over"]), (42, 1, False))
        by_id = {p["id"]: p for p in s["players"]}
        self.assertEqual(sorted(by_id), [0, 1, 2, 63])
        self.assertEqual((by_id[0]["civ"], by_id[0]["color"], by_id[0]["human"]), ("L:TXT_CHINA", [255, 0, 0], True))
        self.assertFalse(by_id[2]["alive"])
        self.assertTrue(by_id[63]["barb"])
        self.assertEqual(s["cities"], [{"id": 1, "o": 0, "x": 0, "y": 0, "pop": 5, "cap": True, "n": "Beijing",
                                        "hp": 180, "puppet": False}])
        units = {u["id"]: u for u in s["units"]}
        self.assertEqual(sorted(units), [10, 11, 12], "the dead player's units are skipped, the barbarians' kept")
        self.assertEqual((units[10]["t"], units[10]["hp"], units[10]["d"]), ("ARCHER", 90, "L"))
        self.assertTrue(units[11]["civ"])
        rows, legend = s["owners"]["rows"], s["owners"]["legend"]
        inv = {pid: ch for ch, pid in legend.items()}
        self.assertEqual(rows, ["." + inv[1] + inv[63], inv[0] + ".."])

    def test_snapshot_fog_per_human_seat(self):
        s = self.run_query(snapshot.LUA)
        self.assertEqual(sorted(s["fog"]), ["0", "1"], "only living humans get a grid: not the dead, not barbarians")
        self.assertEqual(s["fog"]["0"], ["f..", "vv."])       # north row first, like the owner grid
        self.assertEqual(s["fog"]["1"], [".v.", ".f."])


def _py(v):
    """Lua tables -> dicts/lists (1..n arrays become lists)."""
    if lupa is not None and lupa.lua_type(v) == "table":
        keys = list(v.keys())
        if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
            return [_py(v[i]) for i in range(1, len(keys) + 1)]
        return {str(k) if not isinstance(k, str) else k: _py(v[k]) for k in keys}
    return v
