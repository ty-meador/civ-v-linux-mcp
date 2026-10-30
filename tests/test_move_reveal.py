"""A move's result says what the move showed (runtime v263).

"Move the scout and see what is there" used to be move_unit, then tactical_view or units: two or three calls
for one intent. H.move_unit now snapshots what the team can see within 12 plots of the unit as it sends the
order (same tuner trip), and the poll that reads the unit back asks H.unit_pos for the difference: `revealed`
{count, plots (as map_window describes them), more, sighted (fogged plots now in sight with foreign units or a
city on them)}; count 0 means nothing new. A move still queued (no moves left) carries nothing: it has not
moved. Only IsRevealed / IsVisible are read per plot; new plots go through H.describe_plot, which never reads
an unrevealed plot or anything live about a fogged one.
"""
import itertools
import unittest
from unittest import mock

import test_mcp_safety as support
from tests.test_after_reads import _game


class MoveRevealReadBackTests(unittest.TestCase):
    def setUp(self):
        self.sleep = mock.patch("harness.game_parts.units.time.sleep")
        self.sleep.start()
        self.clock = mock.patch("harness.game_parts.units.time.monotonic", side_effect=itertools.count(0, 0.6))
        self.clock.start()

    def tearDown(self):
        self.sleep.stop()
        self.clock.stop()

    def test_a_move_that_happened_carries_what_it_revealed(self):
        shown = {"count": 3, "water": 1, "notable": [{"x": 7, "y": 5, "what": "ruins"}],
                 "sighted": [{"x": 4, "y": 5, "units": [{"owner": 1, "id": 77, "type": "UNIT_WARRIOR", "hp": 100}]}]}
        g = _game([("H.attack_before", {"attack": False}),
                   ("H.move_unit", {"ok": True, "x": 4, "y": 5, "moves": 2}),
                   ("H.unit_pos", {"ok": True, "x": 5, "y": 5, "moves": 1, "activity": 0, "revealed": shown}),
                   ("H.note_unit", True)])
        r = g.move_unit(9, 5, 5)
        self.assertTrue(r["ok"] and r["arrived"])
        # GitLab #153: the new ground is a map-window read on the row, never a plot dump
        self.assertEqual(r["revealed"], {**shown, "map": {"tool": "state", "args": {"what": "map", "view": "window", "x": 5, "y": 5, "radius": 3}}})
        self.assertTrue(any("H.unit_pos(9, 0, true)" in q for q in g.queries), g.queries)

    def test_nothing_revealed_offers_no_map_read(self):
        g = _game([("H.attack_before", {"attack": False}),
                   ("H.move_unit", {"ok": True, "x": 4, "y": 5, "moves": 2}),
                   ("H.unit_pos", {"ok": True, "x": 5, "y": 5, "moves": 1, "activity": 0, "revealed": {"count": 0}}),
                   ("H.note_unit", True)])
        self.assertEqual(g.move_unit(9, 5, 5)["revealed"], {"count": 0})

    def test_a_move_still_queued_says_nothing_about_the_map(self):
        g = _game([("H.attack_before", {"attack": False}),
                   ("H.move_unit", {"ok": True, "x": 4, "y": 5, "moves": 0}),
                   ("H.unit_pos", {"ok": True, "x": 4, "y": 5, "moves": 0, "activity": 6, "revealed": {"count": 0}})])
        r = g.move_unit(9, 5, 5)
        self.assertTrue(r["ok"] and r["queued"])
        self.assertNotIn("revealed", r)


class RevealDiffLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua
    load_runtime = support.LuaRuntimeTests.load_runtime

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        # A 3x3 world around the unit: WORLD['x:y'] = {rev, vis, units, city, owner}. describe_plot is stubbed to
        # what the test needs (its own reads are covered by test_mcp_safety), so only IsRevealed / IsVisible are
        # ever asked of a plot here -- a read of anything else on an unrevealed plot errors.
        self.run_lua("""
        WORLD = {}
        local function plot(x, y)
          local key = x .. ':' .. y
          local p = { GetX = function() return x end, GetY = function() return y end,
            IsRevealed = function(self, team, dbg) assert(team == 0 and dbg == false); return (WORLD[key] or {}).rev or false end,
            IsVisible = function(self, team, dbg) assert(team == 0 and dbg == false); return (WORLD[key] or {}).vis or false end }
          return setmetatable(p, { __index = function(_, k) error('read of ' .. k .. ' on plot ' .. key) end })
        end
        PLOTS = setmetatable({}, { __index = function(t, k)
          local x, y = k:match('(-?%d+):(-?%d+)'); local p = plot(tonumber(x), tonumber(y)); rawset(t, k, p); return p end })
        Map = { PlotXYWithRangeCheck = function(x, y, dx, dy, r)
          if math.abs(dx) > 1 or math.abs(dy) > 1 then return nil end
          return PLOTS[(x + dx) .. ':' .. (y + dy)] end }
        UNIT = { x = 5, y = 5 }
        local unit = { GetID = function() return 9 end, GetX = function() return UNIT.x end, GetY = function() return UNIT.y end,
                       MovesLeft = function() return 60 end }
        GameDefines = GameDefines or {}; GameDefines.MOVE_DENOMINATOR = 60
        Players = { [0] = { GetTeam = function() return 0 end, GetUnitByID = function(self, id) return id == 9 and unit or nil end } }
        H.describe_plot = function(p, team)
          assert(p:IsRevealed(team, false), 'describe_plot on an unrevealed plot')
          local w = WORLD[p:GetX() .. ':' .. p:GetY()] or {}
          return { x = p:GetX(), y = p:GetY(), vis = p:IsVisible(team, false), units = w.units, city = w.city, owner = w.owner,
                   t = w.t, improvement = w.improvement, resource = w.resource, feature = w.feature }
        end
        """)

    def test_notable_new_ground_is_ruins_camps_resources_wonders_and_cities(self):
        """GitLab #153: a one-tile move onto a map reward listed 49 plots. The reply counts them, says how many are
        water, and lists only what a human would walk toward -- bonus resources and bare ground are the map's."""
        self.run_lua("""
        GameInfo = { Resources = { RESOURCE_WHEAT = { ResourceClassType = 'RESOURCECLASS_BONUS' },
                                   RESOURCE_SILK = { ResourceClassType = 'RESOURCECLASS_LUXURY' },
                                   RESOURCE_IRON = { ResourceClassType = 'RESOURCECLASS_RUSH' } },
                     Features = { FEATURE_FOREST = {}, FEATURE_CRATER = { NaturalWonder = true } } }
        WORLD['5:5'] = { rev = true, vis = true }
        local u = Players[0]:GetUnitByID(9)
        H.reveal_mark(u, 0)
        WORLD['4:4'] = { rev = true, vis = true, t = 'GRASS', resource = 'WHEAT' }
        WORLD['5:4'] = { rev = true, vis = true, t = 'OCEAN' }
        WORLD['6:4'] = { rev = true, vis = false, t = 'COAST' }
        WORLD['4:5'] = { rev = true, vis = true, t = 'PLAINS', improvement = 'GOODY_HUT' }
        WORLD['6:5'] = { rev = true, vis = true, t = 'HILL', resource = 'IRON', feature = 'FOREST' }
        WORLD['4:6'] = { rev = true, vis = false, t = 'GRASS', improvement = 'BARBARIAN_CAMP' }
        WORLD['5:6'] = { rev = true, vis = true, t = 'DESERT', resource = 'SILK', feature = 'CRATER', owner = 2 }
        WORLD['6:6'] = { rev = true, vis = true, t = 'GRASS', improvement = 'FARM' }
        local d = H.reveal_diff(9, 0)
        assert(d.count == 8 and d.water == 2, H.json(d))
        local what = {}
        for _, r in ipairs(d.notable) do what[r.x .. ':' .. r.y] = r end
        assert(#d.notable == 4, H.json(d.notable))
        assert(what['4:5'].what == 'ruins' and what['4:5'].fogged == nil)
        assert(what['6:5'].what == 'IRON')
        assert(what['4:6'].what == 'barbarian camp' and what['4:6'].fogged == true, 'a fogged camp is last seen, said so')
        assert(what['5:6'].what == 'SILK, natural wonder CRATER' and what['5:6'].owner == 2)
        assert(what['4:4'] == nil and what['6:6'] == nil, 'wheat and a farm are not news')
        """)

    def test_the_diff_is_new_plots_and_what_came_into_sight(self):
        self.run_lua("""
        WORLD['5:5'] = { rev = true, vis = true }
        WORLD['6:5'] = { rev = true, vis = true }
        WORLD['4:5'] = { rev = true, vis = false, units = { { owner = 1, id = 77, type = 'UNIT_WARRIOR' } } }
        WORLD['6:4'] = { rev = true, vis = false, units = { { owner = 0, id = 5, type = 'UNIT_WORKER' } } }
        local u = Players[0]:GetUnitByID(9)
        H.reveal_mark(u, 0)
        local mark = H.reveal_marks[H.pm_key(9, 0)]
        assert(mark.seen['5:5'] == 2 and mark.seen['4:5'] == 1 and mark.seen['6:6'] == 0, 'the snapshot grades each plot')
        -- the move: two plots uncovered, the fogged warrior's plot and our own worker's plot come into sight
        WORLD['6:6'] = { rev = true, vis = true, city = { name = 'Ur', owner = 1 }, owner = 1 }
        WORLD['4:4'] = { rev = true, vis = false }
        WORLD['4:5'].vis = true
        WORLD['6:4'].vis = true
        UNIT.x = 6
        local d = H.reveal_diff(9, 0)
        assert(d.count == 2, 'count ' .. tostring(d.count))
        -- GitLab #153: the new plots are not listed; what is worth a look on them is
        assert(d.plots == nil and d.more == nil and d.more_notable == nil)
        assert(#d.notable == 1 and d.notable[1].x == 6 and d.notable[1].y == 6 and d.notable[1].what == 'city Ur'
               and d.notable[1].owner == 1, H.json(d.notable))
        assert(#d.sighted == 1, 'only the foreign unit is news, not our own worker: ' .. #d.sighted)
        assert(d.sighted[1].x == 4 and d.sighted[1].y == 5 and d.sighted[1].units[1].owner == 1)
        -- the same reading through the unit's read-back
        local pos = H.unit_pos(9, 0, true)
        assert(pos.ok and pos.x == 6 and pos.revealed.count == 2)
        assert(H.unit_pos(9, 0).revealed == nil, 'without the flag unit_pos is what it was')
        assert(H.reveal_diff(8, 0) == nil, 'no mark, no diff')
        """)

    def test_nothing_new_is_count_zero(self):
        self.run_lua("""
        WORLD['5:5'] = { rev = true, vis = true }
        local u = Players[0]:GetUnitByID(9)
        H.reveal_mark(u, 0)
        local d = H.reveal_diff(9, 0)
        assert(d.count == 0 and d.notable == nil and d.sighted == nil and d.water == nil)
        """)


if __name__ == "__main__":
    unittest.main()
