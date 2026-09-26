"""revealed_map (the map as character grids) and trade-route paths.

Both reads answer a question the stock UI answers visually: which revealed plots are stale (fogged since
last seen), and where a trade route's line runs so a caravan can be escorted or plundered on purpose.
The fog rules are describe_plot's, so the same forbidden live getters are asserted here: under fog the
feature is the remembered one or '?', improvement / route / owner are the engine's Revealed* values,
and units are never read. Runs the shipped Lua body in a bare Lua state (test_mcp_safety's loader).
"""
import unittest

import test_mcp_safety as support
from harness.game import Game


PLOTS = """
local function no() return false end
local function yes() return true end
-- a live getter a fogged plot must never see
local function forbidden(name) return function() error('live ' .. name .. ' read under fog') end end
P = {}
function plot(x, y, o)
  local p = {
    GetX = function() return x end, GetY = function() return y end,
    IsRevealed = function() return o.revealed ~= false end,
    IsVisible = function() return o.vis == true end,
    GetTerrainType = function() return o.terrain or 0 end,
    IsHills = function() return o.hills == true end, IsMountain = function() return o.mountain == true end,
    IsRiver = function() return o.river == true end,
    GetResourceType = function(_, team) assert(team == 0, 'resource read is team-gated'); return o.resource or -1 end,
    GetRevealedImprovementType = function() return o.rimp or -1 end,
    GetRevealedRouteType = function() return o.rroute or -1 end,
    GetRevealedOwner = function() return o.rowner or -1 end,
    GetNumUnits = function() return 0 end,
  }
  if o.vis then
    p.GetFeatureType = function() return o.feature or -1 end
    p.GetImprovementType = function() return o.imp or -1 end
    p.IsImprovementPillaged = function() return o.pillaged == true end
    p.GetRouteType = function() return o.route or -1 end
    p.IsRoutePillaged = function() return o.route_pillaged == true end
    p.GetOwner = function() return o.owner or -1 end
  else
    p.GetFeatureType = forbidden('GetFeatureType'); p.GetImprovementType = forbidden('GetImprovementType')
    p.GetRouteType = forbidden('GetRouteType'); p.GetOwner = forbidden('GetOwner')
    p.IsImprovementPillaged = forbidden('IsImprovementPillaged')
  end
  P[x .. ',' .. y] = p
  return p
end
GameInfo = {Terrains = {[0] = {Type = 'TERRAIN_GRASS'}, [1] = {Type = 'TERRAIN_COAST'}},
            Features = {[0] = {Type = 'FEATURE_FOREST'}},
            Improvements = {[0] = {Type = 'IMPROVEMENT_FARM'}, [1] = {Type = 'IMPROVEMENT_MINE'}},
            Routes = {[0] = {Type = 'ROUTE_ROAD'}},
            Resources = {[0] = {Type = 'RESOURCE_IRON'}}}
Locale = {ConvertTextKey = function(s) return s end}
Players = {[0] = {GetTeam = function() return 0 end, GetCivilizationShortDescription = function() return 'Shoshone' end},
           [3] = {GetTeam = function() return 3 end, GetCivilizationShortDescription = function() return 'Persia' end},
           [9] = {GetTeam = function() return 9 end, GetCivilizationShortDescription = function() error('unmet identity read') end}}
Teams = {[0] = {IsHasMet = function(_, t) return t == 3 end}}
-- 3 x 2 map, y = 1 is the north row
plot(0, 1, {vis = true, terrain = 0, feature = 0, imp = 0, owner = 0, hills = true, river = true, resource = 0})
plot(1, 1, {vis = false, terrain = 0, rimp = 1, rowner = 3, rroute = 0})      -- fogged, never seen since load
plot(2, 1, {revealed = false})
plot(0, 0, {vis = true, terrain = 1})
plot(1, 0, {vis = false, terrain = 0})                                     -- fogged, seen earlier with no feature
plot(2, 0, {vis = true, terrain = 0, imp = 0, pillaged = true, route = 0, route_pillaged = true, owner = 9, mountain = true})
local order = {'0,0', '1,0', '2,0', '0,1', '1,1', '2,1'}
Map = {GetGridSize = function() return 3, 2 end, GetPlot = function(x, y) return P[x .. ',' .. y] end,
       GetNumPlots = function() return 6 end, GetPlotByIndex = function(i) return P[order[i + 1]] end}
H.seen_features = {}
H.remember_feature(P['1,0'], 0, -1)   -- (1,0) was in sight once: no feature there
"""


class RevealedMapTests(unittest.TestCase):
    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(PLOTS)
    run_lua = support.LuaRuntimeTests.run_lua

    def test_grids_are_north_first_and_fog_shows_only_remembered_values(self):
        self.run_lua("""
        local m = H.revealed_map(0)
        assert(m.ok and m.w == 3 and m.h == 2, 'grid size')
        assert(m.revealed == 5 and m.visible == 3 and m.fogged == 2, 'counts')
        assert(m.layers.vis[1] == '#~ ' and m.layers.vis[2] == '#~#', 'row 1 is y=1; # in sight, ~ fogged, space unrevealed: ' .. m.layers.vis[1] .. '/' .. m.layers.vis[2])
        assert(m.layers.terrain[1] == 'GG ' and m.layers.terrain[2] == 'CGG', m.layers.terrain[1])
        assert(m.layers.elevation[1] == '^. ' and m.layers.elevation[2] == '..M', m.layers.elevation[2])
        assert(m.layers.river[1] == 'r. ', m.layers.river[1])
        -- feature: visible forest gets a letter; fogged-never-seen is '?'; fogged-seen-empty is '.'
        local f = m.layers.feature
        assert(f[1]:sub(1, 1) ~= '.' and m.legend.feature[f[1]:sub(1, 1)] == 'FOREST', 'forest lettered: ' .. f[1])
        assert(f[1]:sub(2, 2) == '?', 'never-seen fog is ?: ' .. f[1])
        assert(f[2] == '...', 'seen-empty fog is .: ' .. f[2])
        -- improvement: fogged plot shows the *revealed* mine; pillaged visible farm is !
        local i = m.layers.improvement
        assert(m.legend.improvement[i[1]:sub(1, 1)] == 'FARM' and m.legend.improvement[i[1]:sub(2, 2)] == 'MINE', i[1])
        assert(i[2] == '..!', 'pillaged mark on the visible plot only: ' .. i[2])
        assert(m.layers.route[1]:sub(2, 2) ~= '.' and m.legend.route[m.layers.route[1]:sub(2, 2)] == 'ROAD', 'revealed road under fog')
        assert(m.layers.route[2] == '..!', 'pillaged route mark')
        assert(m.legend.resource[m.layers.resource[1]:sub(1, 1)] == 'IRON')
        """)

    def test_owner_legend_names_met_players_and_masks_unmet(self):
        self.run_lua("""
        local m = H.revealed_map(0, {'owner'})
        assert(m.layers.owner and not m.layers.terrain, 'only the asked layer')
        local o = m.layers.owner
        local mine, theirs, unmet = o[1]:sub(1, 1), o[1]:sub(2, 2), o[2]:sub(3, 3)
        assert(mine ~= '.' and theirs ~= '.' and unmet ~= '.' and mine ~= theirs and theirs ~= unmet, o[1] .. '/' .. o[2])
        assert(m.legend.owner[mine].player_id == 0 and m.legend.owner[mine].name == 'Shoshone')
        assert(m.legend.owner[theirs].player_id == 3 and m.legend.owner[theirs].name == 'Persia', 'revealed owner under fog')
        assert(m.legend.owner[unmet].player_id == 9 and m.legend.owner[unmet].name == 'unmet', 'no identity for an unmet owner')
        """)

    def test_window_and_unknown_layer(self):
        self.run_lua("""
        local m = H.revealed_map(0, {'vis'}, 1, 0, 2, 0)
        assert(#m.layers.vis == 1 and m.layers.vis[1] == '~#', 'window rows/cols: ' .. m.layers.vis[1])
        assert(m.window.x0 == 1 and m.window.y1 == 0)
        assert(m.revealed == 2, 'counts cover the window only')
        local bad = H.revealed_map(0, {'units'})
        assert(bad.ok == false and bad.err:match('unknown layer') and #bad.layers == 9)
        local empty = H.revealed_map(0, nil, 2, 1, 1, 1)
        assert(empty.ok == false and empty.err == 'empty window')
        """)

    def test_python_side_validates_layers_and_builds_the_call(self):
        g = Game.__new__(Game)
        g.seat = 0
        sent = []
        g.q = lambda code, timeout=None: sent.append(code) or {"ok": True}
        g._pid = lambda pid: 0
        self.assertEqual(g.revealed_map(layers=["vis", "bogus"])["err"], "unknown layer(s) ['bogus']")
        self.assertEqual(sent, [])
        g.revealed_map(layers=["vis", "owner"], x0=3, y0=4, x1=10, y1=12)
        self.assertEqual(sent[-1], 'return H.revealed_map(0, {"vis", "owner"}, 3, 4, 10, 12)')
        g.revealed_map()
        self.assertEqual(sent[-1], "return H.revealed_map(0, nil, nil, nil, nil, nil)")


ROUTES = """
Locale = {ConvertTextKey = function(s) return s end}
GameInfo = {Units = {[0] = {Type = 'UNIT_CARAVAN'}, [1] = {Type = 'UNIT_MUSKETMAN'}, [2] = {Type = 'UNIT_BARBARIAN_BRUTE'}}}
GameDefines = {MAX_CIV_PLAYERS = 64}
local function dist(ax, ay, bx, by) return math.max(math.abs(ax - bx), math.abs(ay - by)) end
Map = {PlotDistance = dist}
P = {}
UNITS_ON = {}
local function plot(x, y, o)
  local p = {GetX = function() return x end, GetY = function() return y end,
    IsRevealed = function() return o.revealed ~= false end, IsVisible = function() return o.vis ~= false end,
    GetNumUnits = function() return #(UNITS_ON[x .. ',' .. y] or {}) end,
    GetUnit = function(_, i) return (UNITS_ON[x .. ',' .. y] or {})[i + 1] end}
  P[#P + 1] = p; P[x .. ',' .. y] = p
end
-- route A: Moson Kahni (0,5) -> Adwa (6,5) along y=5; (4,5) unrevealed, (6,5) fogged
-- route B: Moson Kahni (0,5) -> Addis Ababa (3,3): shares (0..3,5) then (3,4),(3,3)
-- incoming C: Adwa (6,5) -> Tiwanaku (0,5) drawn on (3..6,5) only (the rest is how the engine would draw it)
for x = 0, 6 do plot(x, 5, {revealed = x ~= 4, vis = x ~= 6}) end
plot(3, 4, {}); plot(3, 3, {}); plot(6, 4, {})
Map.GetNumPlots = function() return #P end
Map.GetPlotByIndex = function(i) return P[i + 1] end
Map.GetPlot = function(x, y) return P[x .. ',' .. y] end
local A = 'Moson Kahni (The Shoshone) [ICON_TURNS_REMAINING] Adwa (Ethiopia)'
local B = 'Moson Kahni (The Shoshone) [ICON_TURNS_REMAINING] Addis Ababa (Ethiopia)'
local C = 'Adwa (Ethiopia) [ICON_TURNS_REMAINING] Tiwanaku (The Shoshone)'
TT = {}
for x = 0, 6 do TT[x .. ',5'] = {} end
for x = 0, 6 do if x ~= 4 then table.insert(TT[x .. ',5'], {String = A}) end end
for x = 0, 3 do table.insert(TT[x .. ',5'], {String = B}) end
TT['3,4'] = {{String = B}}; TT['3,3'] = {{String = B}}
for x = 3, 6 do table.insert(TT[x .. ',5'], {String = C}) end
TT_CALLS = 0
local function unit(id, owner, x, y, kind, o)
  local u = {GetID = function() return id end, GetOwner = function() return owner end,
    GetX = function() return x end, GetY = function() return y end, GetUnitType = function() return kind end,
    IsTrade = function() return kind == 0 end, IsAutomated = function() return kind == 0 end,
    IsCombatUnit = function() return kind ~= 0 end, GetCurrHitPoints = function() return o.hp or 100 end,
    IsInvisible = function() return false end, GetPlot = function() return P[x .. ',' .. y] end}
  UNITS_ON[x .. ',' .. y] = UNITS_ON[x .. ',' .. y] or {}
  table.insert(UNITS_ON[x .. ',' .. y], u)
  return u
end
local caravan_a = unit(11, 0, 5, 5, 0, {})            -- only route A passes (5,5)
local caravan_b = unit(12, 0, 2, 5, 0, {})            -- (2,5) is on A and B
local escort = unit(13, 0, 2, 5, 1, {hp = 80})        -- stacked with caravan_b
local theirs_caravan = unit(41, 4, 3, 5, 0, {})       -- Ethiopia's caravan, in sight
local brute = unit(63001, 63, 6, 4, 2, {hp = 55})     -- barbarian beside (6,5)
local function iter(list) return function() local i = 0; return function() i = i + 1; return list[i] end end end
local city = function(x, y) return {GetX = function() return x end, GetY = function() return y end} end
local mine = {
  {FromID = 0, ToID = 4, FromCityName = 'Moson Kahni', ToCityName = 'Adwa', Domain = 2, TurnsLeft = 5, FromGPT = 100,
   FromCity = city(0, 5), ToCity = city(6, 5)},
  {FromID = 0, ToID = 4, FromCityName = 'Moson Kahni', ToCityName = 'Addis Ababa', Domain = 2, TurnsLeft = 2, FromGPT = 100,
   FromCity = city(0, 5), ToCity = city(3, 3)},
}
local theirs = {{FromID = 4, ToID = 0, FromCityName = 'Adwa', ToCityName = 'Tiwanaku', Domain = 2, TurnsLeft = -3, FromGPT = 50,
                 FromCity = city(6, 5), ToCity = city(0, 5)}}
Players = {
  [0] = {GetTeam = function() return 0 end, GetTradeRoutes = function() return mine end,
         GetTradeRoutesToYou = function() return theirs end, Units = iter({caravan_a, caravan_b, escort}),
         GetInternationalTradeRoutePlotToolTip = function(_, p) TT_CALLS = TT_CALLS + 1; return TT[p:GetX() .. ',' .. p:GetY()] or {} end,
         IsAlive = function() return true end, IsBarbarian = function() return false end},
  [4] = {GetTeam = function() return 4 end, IsAlive = function() return true end, IsBarbarian = function() return false end,
         Units = iter({theirs_caravan})},
  [63] = {GetTeam = function() return 63 end, IsAlive = function() return true end, IsBarbarian = function() return true end,
          Units = iter({brute})},
}
Teams = {[0] = {IsHasMet = function() return true end, IsAtWar = function() return false end}}
"""


class TradeRoutePathTests(unittest.TestCase):
    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(ROUTES)
    run_lua = support.LuaRuntimeTests.run_lua

    def test_path_is_the_hover_line_ordered_from_the_origin_with_fog_and_gaps(self):
        self.run_lua("""
        local r = H.trade_routes(0)
        local a = r.outgoing[1]
        assert(a.path_plots == 6 and a.path_gaps == 1 and a.path_fogged == 1, 'A: ' .. tostring(a.path_plots) .. '/' .. tostring(a.path_gaps) .. '/' .. tostring(a.path_fogged))
        local xs = {}
        for i, e in ipairs(a.path) do xs[i] = e.x; assert(e.y == 5) end
        assert(table.concat(xs, ',') == '0,1,2,3,5,6', 'ordered from the origin across the unrevealed gap: ' .. table.concat(xs, ','))
        assert(a.path[6].vis == false and a.path[5].vis == nil, 'only the fogged plot is marked')
        local b = r.outgoing[2]
        local bs = {}
        for i, e in ipairs(b.path) do bs[i] = e.x .. ':' .. e.y end
        assert(table.concat(bs, ' ') == '0:5 1:5 2:5 3:5 3:4 3:3', 'B turns north at (3,5): ' .. table.concat(bs, ' '))
        assert(b.path_gaps == nil and b.path_fogged == nil)
        assert(TT_CALLS == 9, 'every revealed plot is asked once, unrevealed never: ' .. TT_CALLS)
        assert(r.note:match('route line'), 'the note explains the fields')
        """)

    def test_caravans_are_placed_on_their_route_with_escort_and_nearby_enemies(self):
        self.run_lua("""
        local r = H.trade_routes(0)
        local a, b = r.outgoing[1], r.outgoing[2]
        assert(a.unit and a.unit.id == 11 and a.unit.type == 'CARAVAN' and a.unit.x == 5, 'the caravan only A fits goes to A')
        assert(a.unit.escorted == false and a.unit.escorted_by == nil)
        assert(b.unit and b.unit.id == 12, 'the shared-plot caravan goes to the route left over')
        assert(b.unit.escorted == true and #b.unit.escorted_by == 1 and b.unit.escorted_by[1].id == 13
               and b.unit.escorted_by[1].type == 'MUSKETMAN' and b.unit.escorted_by[1].hp == 80, 'the stacked combat unit is the escort')
        assert(a.enemies_near_path and #a.enemies_near_path == 1, 'the brute beside (6,5) is one hex from A')
        local e = a.enemies_near_path[1]
        assert(e.id == 63001 and e.owner == 63 and e.type == 'BARBARIAN_BRUTE' and e.hp == 55 and e.dist_to_route == 1 and e.dist_to_caravan == 1)
        assert(b.enemies_near_path == nil, 'the brute is two hexes from B')
        """)

    def test_incoming_route_shows_the_foreign_caravan_only_where_in_sight(self):
        self.run_lua("""
        local r = H.trade_routes(0)
        local c = r.incoming[1]
        -- drawn on (3..6,5); (4,5) is unrevealed, so three plots in two runs, walked from Adwa
        local cs = {}
        for i, e in ipairs(c.path) do cs[i] = e.x end
        assert(c.path_plots == 3 and c.path_gaps == 1 and table.concat(cs, ',') == '6,5,3', 'ordered from Adwa toward us: ' .. table.concat(cs, ','))
        assert(c.unit and c.unit.id == 41 and c.unit.type == 'CARAVAN' and c.unit.x == 3, 'their caravan on a visible plot')
        assert(c.unit.escorted == nil, 'no escort read for a foreign unit')
        -- hide the plot it stands on: the unit must vanish from the read
        P['3,5'].IsVisible = function() return false end
        local r2 = H.trade_routes(0)
        assert(r2.incoming[1].unit == nil, 'fogged plot: no foreign unit is read')
        """)

    def test_rows_survive_without_the_hover_api(self):
        self.run_lua("""
        Players[0].GetInternationalTradeRoutePlotToolTip = nil
        local r = H.trade_routes(0)
        assert(#r.outgoing == 2 and r.outgoing[1].path == nil and r.outgoing[1].unit == nil and r.note == nil)
        """)


if __name__ == "__main__":
    unittest.main()
