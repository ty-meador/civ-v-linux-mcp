"""state(what='city_state', view='full') says each thing once and lists a few giftable units (GitLab #65)."""
import unittest

import test_mcp_safety as support
from harness.surface import dispatch as D


def unit(i):
    return {"id": i, "type": "WARRIOR", "call": {"tool": "order", "args": {"to": "city_state", "action": "gift_unit", "id": 37, "args": {"unit_id": i}}}}


class MergeTests(unittest.TestCase):
    def parts(self, n_units):
        tiles = [{"x": 1, "y": 1, "resource": "WHALE", "improvement": "FISHING_BOATS"}]
        return {"summary": {"ok": True, "name": "Sidon",
                            "gift_tile_improvement": {"can": False, "cost": 200, "why_not": "no tile left", "resource_tiles": tiles, "search_radius": 5}},
                "gifts": {"ok": True, "small": {"amount": 250}},
                "bonuses": {"ok": True},
                "gift_units": {"ok": True, "influence_gain": 5, "units": [unit(i) for i in range(n_units)]},
                "gift_tiles": {"ok": True, "can": False, "why_not": "no tile left", "resource_tiles": tiles, "search_radius": 5}}

    def test_resource_tiles_once_and_a_few_units(self):
        out = D.merge_parts(self.parts(19))
        self.assertTrue(out["ok"])
        status = out["summary"]["gift_tile_improvement"]
        self.assertNotIn("resource_tiles", status)
        self.assertEqual(status["resource_tiles_in"], "gift_tiles")
        self.assertEqual(status["why_not"], "no tile left", "the summary keeps the reason")
        self.assertEqual(len(out["gift_tiles"]["resource_tiles"]), 1)
        gu = out["gift_units"]
        self.assertEqual(len(gu["units"]), D.GIFT_UNITS_SHOWN)
        self.assertEqual((gu["units_total"], gu["units_omitted"]), (19, 19 - D.GIFT_UNITS_SHOWN))
        self.assertIn("all_units", gu["more"])

    def test_the_drill_down_lists_every_unit_and_a_few_are_left_alone(self):
        self.assertEqual(len(D.merge_parts(self.parts(19), all_units=True)["gift_units"]["units"]), 19)
        few = D.merge_parts(self.parts(3))["gift_units"]
        self.assertEqual(len(few["units"]), 3)
        self.assertNotIn("units_total", few)

    def test_resolve_takes_all_units_off_the_parts(self):
        full = D.resolve("state", {"what": "city_state", "view": "full"}, {"id": 20, "all_units": True})
        self.assertIsInstance(full, D.Composite)
        self.assertTrue(full.all_units)
        for call in full.parts.values():
            self.assertNotIn("all_units", call.args)
        self.assertFalse(D.resolve("state", {"what": "city_state", "view": "full"}, {"id": 20}).all_units)


class GiftUnitsOrderLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)

    def test_an_upgradable_unit_comes_first_then_the_weakest(self):
        self.run_lua("""
        GameInfo = GameInfo or {}
        GameInfo.Units = { [4] = { Type = 'UNIT_WARRIOR' }, [5] = { Type = 'UNIT_PIKEMAN' } }
        GameDefines = GameDefines or {}; GameDefines.MINOR_UNIT_GIFT_TRAVEL_TURNS = 3
        local function mk(id, ut, str, upg)
          return { GetID = function() return id end, GetUnitType = function() return ut end, GetX = function() return 1 end,
                   GetY = function() return 2 end, CanDistanceGift = function() return true end,
                   CanUpgradeRightNow = function() return upg end, GetBaseCombatStrength = function() return str end }
        end
        local units = { mk(30, 5, 16, false), mk(10, 4, 8, false), mk(20, 5, 16, true) }
        Teams = { [0] = { IsHasMet = function() return true end, IsAtWar = function() return false end } }
        Players = { [0] = { GetTeam = function() return 0 end, Units = function() local i = 0; return function() i = i + 1; return units[i] end end },
                    [22] = { IsMinorCiv = function() return true end, IsAlive = function() return true end, GetTeam = function() return 0 end,
                             GetName = function() return 'Sidon' end, GetMinorCivFriendshipWithMajor = function() return 15 end,
                             GetFriendshipFromUnitGift = function() return 5 end, GetIncomingUnitCountdown = function() return -1 end } }
        local o = H.gift_unit_options(22, 0)
        assert(o.ok, H.json(o))
        local ids = {}
        for i, u in ipairs(o.units) do ids[i] = u.id end
        assert(ids[1] == 20 and ids[2] == 10 and ids[3] == 30, H.json(ids))
        assert(o.units[1].upgradable == true and o.units[2].upgradable == nil and o.units[2].strength == 8, H.json(o.units))
        """)


if __name__ == "__main__":
    unittest.main()
