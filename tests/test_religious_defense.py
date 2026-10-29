"""Religious defense is a row, not a digest line (GitLab #112); a negotiation signs nothing and says so (GitLab #69)."""
import unittest

import test_mcp_safety as support
from harness.briefing import religion_warnings
from harness.game import Game


class ReligionBoardLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua("""
        Game.GetReligionName = function(id) return ({ [5] = 'Taoism', [2] = 'Catholicism' })[id] end
        GameInfo = GameInfo or {}
        GameInfo.Units = { [7] = { Type = 'UNIT_MISSIONARY', ReligionSpreads = 2 }, [1] = { Type = 'UNIT_WARRIOR', ReligionSpreads = 0 } }
        local function city(id, name, maj, holy, mine_n, maj_n)
          return { GetID = function() return id end, GetName = function() return name end,
                   GetReligiousMajority = function() return maj end,
                   GetNumFollowers = function(_, r) return r == maj and maj_n or mine_n end,
                   IsHolyCityForReligion = function(_, r) return holy and r == 5 end }
        end
        local cities = { city(8192, 'Palenque', 2, true, 3, 5), city(16385, 'Tikal', 5, false, 6, 6) }
        local myplot = { GetOwner = function() return 0 end, IsVisible = function() return true end,
                         GetWorkingCity = function() return cities[2] end }
        local missionary = { GetPlot = function() return myplot end, GetUnitType = function() return 7 end, GetID = function() return 99 end,
                             IsDelayedDeath = function() return false end, GetX = function() return 20 end, GetY = function() return 29 end,
                             GetReligion = function() return 2 end }
        local warrior = { GetPlot = function() return myplot end, GetUnitType = function() return 1 end, IsDelayedDeath = function() return false end }
        local function iter(list) local i = 0; return function() i = i + 1; return list[i] end end
        Players = { [0] = { HasCreatedReligion = function() return true end, GetReligionCreatedByPlayer = function() return 5 end,
                            GetTeam = function() return 0 end, Cities = function() return iter(cities) end,
                            GetCivilizationShortDescription = function() return 'Maya' end },
                    [1] = { IsAlive = function() return true end, IsMinorCiv = function() return false end, GetTeam = function() return 1 end,
                            IsBarbarian = function() return false end, Units = function() return iter({ missionary, warrior }) end,
                            GetCivilizationShortDescription = function() return 'Venice' end } }
        Teams = { [0] = { IsHasMet = function() return true end } }
        """)

    def test_the_board_names_the_lost_holy_city_and_the_missionary_in_my_land(self):
        self.run_lua("""
        local r = H.religion_board(0)
        assert(r.mine == 'Taoism' and #r.cities == 2, H.json(r))
        local pal = r.cities[1]
        assert(pal.name == 'Palenque' and pal.majority == 'Catholicism' and pal.mine_majority == false and pal.holy_city == true, H.json(pal))
        assert(pal.followers_mine == 3 and pal.followers_majority == 5, H.json(pal))
        assert(r.cities[2].mine_majority == true, H.json(r.cities[2]))
        assert(#r.foreign_religious_units == 1 and r.foreign_religious_units[1].unit == 'MISSIONARY' and r.foreign_religious_units[1].religion == 'Catholicism', H.json(r.foreign_religious_units))
        assert(r.foreign_religious_units[1].near_city == 'Tikal')
        Players[0].HasCreatedReligion = function() return false end
        assert(H.religion_board(0) == nil, 'no religion of mine: nothing to defend')
        """)


class ReligionWarningRowsTests(unittest.TestCase):
    def test_the_holy_city_comes_first_with_its_rows(self):
        board = {"religion": {"mine": "Taoism", "cities": [
            {"id": 16385, "name": "Tikal", "majority": "Catholicism", "mine_majority": False, "followers_mine": 2, "followers_majority": 4},
            {"id": 8192, "name": "Palenque", "majority": "Catholicism", "mine_majority": False, "holy_city": True},
            {"id": 24578, "name": "Uxmal", "majority": "Taoism", "mine_majority": True}],
            "foreign_religious_units": [{"id": 99, "unit": "MISSIONARY", "owner": "Venice", "x": 20, "y": 29, "religion": "Catholicism"}]}}
        rows = religion_warnings(board)
        self.assertEqual([r["kind"] for r in rows], ["religion_lost", "religion_lost", "religious_unit_in_my_land"])
        self.assertEqual(rows[0]["name"], "Palenque")
        self.assertTrue(rows[0]["holy_city"])
        self.assertIn("cannot enhance", rows[0]["note"])
        self.assertEqual(rows[1]["actions"][0]["args"], {"what": "city", "view": "production", "id": 16385})
        self.assertIn("conversion is coming", rows[2]["note"])
        self.assertEqual(religion_warnings({}), [])


class SpreadTargetLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)

    def test_a_spread_row_names_the_city_it_would_hit(self):
        self.run_lua("""
        Game.GetReligionName = function(id) return ({ [5] = 'Taoism', [2] = 'Catholicism' })[id] end
        local city = { GetName = function() return 'Tikal' end, GetOwner = function() return 0 end,
                       GetReligiousMajority = function() return 5 end, GetNumFollowers = function(_, r) return r == 5 and 6 or 0 end }
        local here = { GetPlotCity = function() return nil end, GetX = function() return 1 end, GetY = function() return 1 end }
        local beside = { IsCity = function() return true end, GetPlotCity = function() return city end }
        Map = { PlotDirection = function(x, y, d) if d == 2 then return beside end return nil end }
        Players = { [0] = { GetCivilizationShortDescription = function() return 'Maya' end } }
        local u = { GetSpreadsLeft = function() return 2 end, GetReligion = function() return 5 end, GetPlot = function() return here end }
        local y = H.great_person_yield(u, 'MISSION_SPREAD_RELIGION', 0)
        assert(y.spreads_left == 2 and y.religion == 'Taoism', H.json(y))
        assert(y.target and y.target.city == 'Tikal' and y.target.already_majority == true and y.target.followers_mine == 6, H.json(y))
        assert(y.target.note:find('already follows', 1, true), y.target.note)
        """)


class NegotiateSignsNothingTests(unittest.TestCase):
    def test_the_reply_says_signed_false_and_hands_back_the_proposal(self):
        g = Game.__new__(Game)
        g.seat = 0
        g._pid = lambda pid=None: 0
        g.h = Game.h.__get__(g)
        g._check_deal_items = lambda other, items, pid, demand=False: {"ok": True}
        g.q = lambda call, timeout=None: False
        g._open_trade_screen = lambda other, pid, demand=False: {"ok": True}
        g._add_deal_items = lambda other, items, pid: {"ok": True, "table": {"items": items}}
        table_items = [{"type": "RESOURCES", "resource": "RESOURCE_FUR", "from_us": True, "amount": 1},
                       {"type": "RESOURCES", "resource": "RESOURCE_DYE", "from_us": False, "amount": 1}]
        g._ask_ai = lambda pid, call, table: {"reply": "This deal will work as it stands on the table.", "items": table_items, "changed": False}
        g.close_trade_screens = lambda: {"closed": True}
        r = g.negotiate_deal(3, table_items[:1], mode="equalize")
        self.assertTrue(r["ok"])
        self.assertFalse(r["signed"])
        self.assertEqual(r["next"]["args"], {"to": "civ", "action": "propose_deal", "id": 3, "args": {"items": table_items}})
        self.assertIn("nothing was signed", r["note"])


if __name__ == "__main__":
    unittest.main()
