"""A Great Merchant's trade mission has a target read (GitLab #87) and a route refusal names the rule and the routes
open (GitLab #73)."""
import unittest

import test_mcp_safety as support
from harness import affordances as A
from harness.game import Game


class TradeMissionTargetsLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua("""
        GameDefines = { MAX_CIV_PLAYERS = 4 }
        PLOTS = {}
        local function plot(x, y, owner, revealed)
          local k = x .. ',' .. y
          PLOTS[k] = PLOTS[k] or { GetX = function() return x end, GetY = function() return y end,
                                   GetOwner = function() return owner end, IsRevealed = function() return revealed ~= false end }
          return PLOTS[k]
        end
        -- Belgrade at (20,20) owns its ring; Ur at (30,30) owns its ring (one plot unrevealed)
        for dx = -1, 1 do for dy = -1, 1 do plot(20 + dx, 20 + dy, 2, true); plot(30 + dx, 30 + dy, 3, not (dx == -1 and dy == -1)) end end
        Map = { PlotXYWithRangeCheck = function(cx, cy, dx, dy, r) if math.abs(dx) > r or math.abs(dy) > r then return nil end return PLOTS[(cx + dx) .. ',' .. (cy + dy)] or plot(cx + dx, cy + dy, -1, true) end,
                PlotDistance = function(x1, y1, x2, y2) return math.max(math.abs(x1 - x2), math.abs(y1 - y2)) end }
        local function cap(name, x, y) return { GetName = function() return name end, GetX = function() return x end, GetY = function() return y end } end
        local unit = { GetX = function() return 17 end, GetY = function() return 21 end,
                       GetTradeGold = function(_, pl) return pl:GetOwner() == 2 and 350 or 300 end,
                       GetTradeInfluence = function() return 30 end }
        Players = { [0] = { GetUnitByID = function() return unit end, GetTeam = function() return 0 end },
                    [1] = { IsAlive = function() return true end, IsMinorCiv = function() return false end, GetTeam = function() return 1 end },
                    [2] = { IsAlive = function() return true end, IsMinorCiv = function() return true end, GetTeam = function() return 2 end, GetCapitalCity = function() return cap('Belgrade', 20, 20) end },
                    [3] = { IsAlive = function() return true end, IsMinorCiv = function() return true end, GetTeam = function() return 3 end, GetCapitalCity = function() return cap('Ur', 30, 30) end } }
        Teams = { [0] = { IsHasMet = function(_, t) return t ~= 1 or true end, IsAtWar = function(_, t) return t == 3 end } }
        GameInfo = GameInfo or {}
        GameInfo.InterfaceModes = {}
        H.targeted_missions = function() return {} end
        """)

    def test_city_states_by_distance_with_the_plot_to_stand_on_and_the_engines_gold(self):
        self.run_lua("""
        local r = H.unit_mission_targets(1, 'MISSION_TRADE', 0, 0, 100)
        assert(r.ok and r.mission == 'MISSION_TRADE' and #r.targets == 2, H.json(r))
        local b, u = r.targets[1], r.targets[2]
        assert(b.city_state == 'Belgrade' and b.x == 19 and b.distance == 2 and b.gold == 350 and b.influence == 30, H.json(b))   -- (19,19) and (19,21) tie at 2
        assert(u.city_state == 'Ur' and u.distance == 12 and u.at_war == true and u.gold == 300, H.json(u))
        assert(r.note:find('move onto the plot', 1, true))
        """)


class TradeRowsTests(unittest.TestCase):
    def test_a_trade_target_carries_the_move_then_the_mission(self):
        r = A.mission_target_rows({"ok": True, "unit_id": 9, "mission": "MISSION_TRADE",
                                   "targets": [{"city_state": "Belgrade", "x": 19, "y": 21, "gold": 350}]})
        calls = r["targets"][0]["calls"]
        self.assertEqual(calls[0]["args"], {"to": "unit", "action": "move", "id": 9, "args": {"x": 19, "y": 21}})
        self.assertEqual(calls[1]["args"]["args"], {"mission": "MISSION_TRADE"})
        plain = A.mission_target_rows({"ok": True, "unit_id": 9, "mission": "MISSION_REBASE", "targets": [{"x": 1, "y": 2}]})
        self.assertEqual(plain["targets"][0]["call"]["args"]["args"], {"mission": "MISSION_REBASE", "x": 1, "y": 2})


class RouteRefusalTests(unittest.TestCase):
    def test_the_refusal_names_the_rule_and_the_routes_open(self):
        g = Game.__new__(Game)
        g.seat = 0
        g._pid = lambda pid=None: 0
        g.h = Game.h.__get__(g)
        g._order = lambda call: {"ok": False, "err": "no route to that destination is open to this unit", "dest_x": 24, "dest_y": 29}
        g.trade_routes = lambda pid=None: {"outgoing": []}
        g.available_trade_routes = lambda uid, pid=None: [{"x": 20, "y": 28, "city_name": "Nineveh", "kind": "food", "call": {"tool": "order"}},
                                                           {"x": 12, "y": 26, "city_name": "Kar-Tukulti-Ninurta", "kind": "international"}]
        r = g.establish_trade_route(1400869, 24, 29, 0)
        self.assertFalse(r["ok"])
        self.assertIn("one route per origin-destination pair", r["reason"])
        self.assertEqual([a["city_name"] for a in r["available"]], ["Nineveh", "Kar-Tukulti-Ninurta"])


if __name__ == "__main__":
    unittest.main()
