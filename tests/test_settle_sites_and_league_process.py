"""A Settler's sites are a read (GitLab #106); a league project's process says its tiers and turns (GitLab #81)."""
import unittest
from unittest import mock

import test_mcp_safety as support
from harness import affordances as A
from harness.game import Game


class SettleSitesLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua("""
        GameInfo = GameInfo or {}
        GameInfo.Resources = { [3] = { Type = 'RESOURCE_WHEAT' } }
        GameInfo.InterfaceModes = {}
        PLOTS = {}
        local function plot(x, y)
          local k = x .. ',' .. y
          if not PLOTS[k] then
            PLOTS[k] = { x = x, y = y, revealed = true, found = false, value = 0, fresh = false, res = -1,
              GetX = function() return x end, GetY = function() return y end,
              IsRevealed = function(self) return self.revealed end, IsFreshWater = function(self) return self.fresh end,
              IsRiver = function() return false end, IsCoastalLand = function() return false end, IsHills = function() return false end,
              GetResourceType = function(self) return self.res end, GetFoundValue = function(self) return self.value end }
          end
          return PLOTS[k]
        end
        Map = { PlotXYWithRangeCheck = function(cx, cy, dx, dy, r) if math.abs(dx) > r or math.abs(dy) > r then return nil end return plot(cx + dx, cy + dy) end,
                PlotDirection = function(x, y, d) local off = { {1,0}, {0,1}, {-1,1}, {-1,0}, {0,-1}, {1,-1} }; return plot(x + off[d + 1][1], y + off[d + 1][2]) end,
                PlotDistance = function(x1, y1, x2, y2) return math.max(math.abs(x1 - x2), math.abs(y1 - y2)) end }
        -- two sites: (12,12) river-side, value 900, a wheat beside it; (16,10) value 1200 but a fogged neighbour
        plot(12, 12).found = true; plot(12, 12).value = 900; plot(12, 12).fresh = true; plot(13, 12).res = 3
        plot(16, 10).found = true; plot(16, 10).value = 1200; plot(17, 10).revealed = false
        local unit = { GetX = function() return 10 end, GetY = function() return 10 end, CanFound = function(_, q) return q.found end,
                       GetDomainType = function() return 0 end, GetDropRange = function() return 0 end }
        Players = { [0] = { GetUnitByID = function() return unit end, GetTeam = function() return 0 end,
                            Cities = function() local done; return function() if done then return nil end; done = true; return { GetName = function() return 'Palenque' end, GetX = function() return 10 end, GetY = function() return 14 end } end end } }
        H.targeted_missions = function() return {} end
        """)

    def test_sites_come_best_first_with_the_tile_facts_and_the_fog_rule(self):
        self.run_lua("""
        local r = H.unit_mission_targets(1, 'MISSION_FOUND', 0, 0, 100)
        assert(r.ok and r.mission == 'MISSION_FOUND' and r.total == 2, H.json(r))
        local a, b = r.targets[1], r.targets[2]
        assert(a.x == 12 and a.value == 900 and a.fresh_water == true and a.ring_resources[1] == 'WHEAT' and a.distance == 2, H.json(a))
        assert(a.nearest_city.name == 'Palenque' and a.nearest_city.distance == 2, H.json(a))
        assert(b.x == 16 and b.value == nil and b.value_note:find('not fully revealed', 1, true), H.json(b))
        """)


class SettleRowsTests(unittest.TestCase):
    def test_a_site_carries_the_move_then_the_founding(self):
        r = A.mission_target_rows({"ok": True, "unit_id": 5, "mission": "MISSION_FOUND", "targets": [{"x": 12, "y": 12, "value": 900}]})
        calls = r["targets"][0]["calls"]
        self.assertEqual(calls[0]["args"]["args"], {"x": 12, "y": 12})
        self.assertEqual(calls[1]["args"]["args"], {"mission": "MISSION_FOUND"})


class LeagueProcessNoteTests(unittest.TestCase):
    def test_the_process_reply_names_the_tier_and_the_turns(self):
        g = Game.__new__(Game)
        g.seat = 0
        g._pid = lambda pid=None: 0
        g.h = Game.h.__get__(g)

        def q(call, timeout=None):
            if call.fn == "production_check":
                return {"ok": True, "id": 4}
            if call.fn == "city_push_order":
                return {"ok": True, "before": []}
            if call.fn == "city_queue":
                return {"ok": True, "production": "International Space Station", "turns": 2**31 - 1,
                        "queue": ["PROCESS_INTERNATIONAL_SPACE_STATION"], "production_per_turn": 120}
            return {"ok": True}
        g.q = q
        g.league_status = lambda pid=None, detail="full": {"ok": True, "projects": [
            {"project": "LEAGUE_PROJECT_INTERNATIONAL_SPACE_STATION", "name": "International Space Station",
             "process": "PROCESS_INTERNATIONAL_SPACE_STATION", "progress_percent": 40, "our_contribution": 482,
             "our_tier": 1, "cost": 1929, "cost_per_player": 965, "tier_1_at": 290, "tier_2_at": 569}]}
        with mock.patch("harness.game.time.sleep", lambda s: None):
            r = g.set_production(8192, "ORDER_MAINTAIN", "PROCESS_INTERNATIONAL_SPACE_STATION")
        self.assertTrue(r["ok"])
        self.assertIsNone(r["turns"])
        self.assertEqual((r["league_project"]["next_tier"], r["league_project"]["next_tier_at"], r["league_project"]["turns_to_next_tier"]), ("tier 2", 569, 1))
        self.assertIn("pays by tier", r["note"])
        self.assertNotIn("never completes", r["note"])


if __name__ == "__main__":
    unittest.main()
