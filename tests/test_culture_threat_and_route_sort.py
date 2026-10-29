"""The culture row's estimate is always said (GitLab #88); trade routes come sorted, measured and limited (GitLab #74)."""
import unittest

import test_mcp_safety as support
from harness.briefing import build
from harness.game import Game


class CultureEstimateLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua("""
        GameDefines = { MAX_CIV_PLAYERS = 2 }
        InfluenceLevelTrend = { INFLUENCE_TREND_FALLING = 0, INFLUENCE_TREND_STATIC = 1, INFLUENCE_TREND_RISING = 2 }
        InfluenceLevelTypes = { NO_INFLUENCE_LEVEL = -1 }
        Locale = { Lookup = function(k) return k end }
        TURNS, TREND, LEVEL = 999, 2, 1
        local function civ(i, name, inf, needed)
          return { IsAlive = function() return true end, IsMinorCiv = function() return false end, GetTeam = function() return i end,
                   GetCivilizationShortDescriptionKey = function() return name end,
                   GetNumCivsInfluentialOn = function() return inf end, GetNumCivsToBeInfluentialOn = function() return needed end,
                   GetTourism = function() return 110 end, GetInfluenceLevel = function() return LEVEL end,
                   GetJONSCultureEverGenerated = function() return 50000 end, GetInfluenceOn = function() return 11000 end,
                   GetInfluencePerTurn = function() return 110 end, GetInfluenceTrend = function() return TREND end,
                   GetTurnsToInfluential = function() return TURNS end }
        end
        Players = { [0] = civ(0, 'Assyria', 0, 2), [1] = civ(1, 'Siam', 1, 2) }
        Teams = { [0] = { IsHasMet = function() return true end } }
        """)

    def test_never_at_current_rates_is_said_and_the_threat_row_names_it(self):
        self.run_lua("""
        local cv = H.culture_overview(0)
        local siam = cv.civs[2]
        assert(siam.civ == 'Siam' and siam.on[1].player == 0, H.json(siam))
        assert(tostring(siam.on[1].turns_to_influential):find('never at current rates', 1, true), H.json(siam.on[1]))
        TURNS = 40
        assert(H.culture_overview(0).civs[2].on[1].turns_to_influential == 40)
        TREND = 0
        assert(H.culture_overview(0).civs[2].on[1].turns_to_influential == 'never (not rising)')
        local th = H.culture_threats(0)
        assert(#th == 1 and th[1].civ == 'Siam' and th[1].influential_on == 1 and th[1].needed == 2, H.json(th))
        assert(th[1].on_me and th[1].on_me.level == 'familiar', H.json(th[1]))
        """)


class CultureWarningRowTests(unittest.TestCase):
    def test_the_briefing_warns(self):
        board = {"event_seq": 1, "threats": [], "camps": [],
                 "culture_threats": [{"player": 2, "civ": "Siam", "influential_on": 1, "needed": 2, "tourism": 110,
                                      "on_me": {"level": "familiar", "percent": 22, "trend": "rising", "turns_to_influential": "never at current rates"}}]}
        ts = {"turn": 256, "todo": {"units": [], "cities": []}, "blocking_name": "NO_ENDTURN_BLOCKING_TYPE", "pending_popups": []}
        out, _snap = build(ts, {}, [], [], board, {"comparable": False}, None, [], limit=8, include_rules=False)
        rows = [w for w in out.get("warnings", []) if w["kind"] == "culture_victory_threat"]
        self.assertEqual(len(rows), 1)
        self.assertIn("one more wins it the game", rows[0]["note"])
        self.assertIn("never at current rates", rows[0]["note"])


class RouteSortTests(unittest.TestCase):
    def _game(self, rows):
        g = Game.__new__(Game)
        g.seat = 0
        g._pid = lambda pid=None: 0
        g.h = Game.h.__get__(g)
        g.q = lambda call, timeout=None: [dict(r) for r in rows]
        return g

    def test_best_first_by_the_yield_and_a_limit_that_says_what_follows(self):
        rows = [{"x": 1, "y": 1, "city_name": "A", "gold": 3, "distance": 9, "trade_connection_type": 0},
                {"x": 2, "y": 2, "city_name": "B", "gold": 7, "distance": 4, "trade_connection_type": 0},
                {"x": 3, "y": 3, "city_name": "C", "gold": 5, "distance": 2, "trade_connection_type": 0}]
        g = self._game(rows)
        out = g.available_trade_routes(9)
        self.assertEqual([r["city_name"] for r in out], ["B", "C", "A"])
        out = g.available_trade_routes(9, sort="distance", limit=2)
        self.assertEqual([r["city_name"] for r in out], ["C", "B"])
        self.assertEqual(out[-1]["omitted_after"], 1)
        self.assertIn("1 more routes", out[-1]["more"])
        self.assertIn("sort must be one of", g.available_trade_routes(9, sort="luck")["err"])


if __name__ == "__main__":
    unittest.main()
