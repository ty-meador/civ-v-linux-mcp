"""Third-party war / peace on the trade table (GitLab #6).

tradelogic.lua's Other Players pocket lists every living player both sides have met; a leader passes
IsPossibleToTradeItem(from, to, type, TEAM) or is greyed with a reason. LeaderSelected then calls
AddThirdPartyWar/Peace(who, otherTeam) unconditionally, so the gate lives in _check_deal_items.
"""
import unittest

import test_mcp_safety as support


class ThirdPartyLegalityTests(unittest.TestCase):
    CATALOG = {"ok": True, "gold": {"us": True, "them": True, "us_available": 500, "them_available": 40},
               "gold_per_turn": {"us": True, "them": True, "us_available": 20, "them_available": 3},
               "resources": [], "cities": {"us": [], "them": []},
               "third_party": {
                   "war": {"us": [{"player": 23, "team": 23, "name": "Hong Kong", "minor": True, "ok": True},
                                  {"player": 24, "team": 24, "name": "Budapest", "minor": True, "ok": False, "note": "Locked into peace"}],
                           "them": [{"player": 23, "team": 23, "name": "Hong Kong", "minor": True, "ok": True}]},
                   "peace": {"us": [{"player": 23, "team": 23, "name": "Hong Kong", "minor": True, "ok": False, "note": "Not at war"}],
                             "them": []}}}

    def game(self):
        from harness.game import Game
        g = Game.__new__(Game)
        g.seat = 0
        g.trade_catalog = lambda other, pid=None: dict(self.CATALOG)
        return g

    def check(self, *items):
        return self.game()._check_deal_items(1, list(items), 0)

    def test_enabled_leader_buttons_pass(self):
        self.assertTrue(self.check({"type": "THIRD_PARTY_WAR", "from_us": True, "other": 23})["ok"])
        self.assertTrue(self.check({"type": "THIRD_PARTY_WAR", "from_us": False, "other": 23})["ok"])

    def test_greyed_leader_carries_the_screen_reason(self):
        r = self.check({"type": "THIRD_PARTY_WAR", "from_us": True, "other": 24})
        self.assertFalse(r["ok"]); self.assertIn("Locked into peace", r["err"]); self.assertIn("Budapest", r["err"])
        r = self.check({"type": "THIRD_PARTY_PEACE", "from_us": True, "other": 23})
        self.assertFalse(r["ok"]); self.assertIn("Not at war", r["err"])

    def test_unknown_or_unlisted_player_is_refused(self):
        r = self.check({"type": "THIRD_PARTY_PEACE", "from_us": False, "other": 23})
        self.assertFalse(r["ok"]); self.assertEqual(r["third_party"], [])
        self.assertFalse(self.check({"type": "THIRD_PARTY_WAR", "from_us": True, "other": 99})["ok"])
        r = self.check({"type": "THIRD_PARTY_WAR", "from_us": True})
        self.assertFalse(r["ok"]); self.assertIn("other", r["err"])
        self.assertFalse(self.check({"type": "THIRD_PARTY_WAR", "from_us": True, "other": "23"})["ok"])


class ThirdPartyReadTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    WORLD = r"""
    TradeableItems = { TRADE_ITEM_THIRD_PARTY_WAR = 12, TRADE_ITEM_THIRD_PARTY_PEACE = 11 }
    GameDefines = { MAX_CIV_PLAYERS = 6 }
    H.enum_name = function(_, _, v) return v == 12 and 'TRADE_ITEM_THIRD_PARTY_WAR' or 'TRADE_ITEM_THIRD_PARTY_PEACE' end
    local function player(id, team, name, minor, alive)
      return { GetID = function() return id end, GetTeam = function() return team end, GetName = function() return name end,
               IsMinorCiv = function() return minor end, IsAlive = function() return alive ~= false end,
               GetAlly = function() return -1 end, IsMinorPermanentWar = function() return false end,
               IsWillAcceptPeaceWithPlayer = function() return true end }
    end
    -- team ids differ from player ids on purpose: Bravo is player 1 on team 5, Hong Kong player 3 on team 4
    Players = { [0] = player(0, 0, 'Alpha', false), [1] = player(1, 5, 'Bravo', false), [2] = player(2, 2, 'Dead', false, false),
                [3] = player(3, 4, 'Hong Kong', true), [4] = player(4, 3, 'Unmet', true), [5] = player(5, 1, 'Prague', true) }
    MET = { [0] = { [4] = true, [1] = true, [5] = true }, [5] = { [4] = true, [0] = true, [1] = true } }
    WAR = {}   -- "a:b" -> true
    Teams = {}
    for t = 0, 5 do
      Teams[t] = { IsHasMet = function(_, o) return MET[t] and MET[t][o] == true end,
                   IsAtWar = function(_, o) return WAR[t .. ':' .. o] == true end,
                   IsForcePeace = function(_, o) return t == 5 and o == 1 end }
    end
    Locale = { ConvertTextKey = function(k) return ({ TXT_KEY_DIPLO_NOT_AT_WAR = 'Not at war', TXT_KEY_DIPLO_FORCE_PEACE = '[COLOR_WARNING_TEXT]Locked into peace[ENDCOLOR]' })[k] or k end }
    """

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(self.WORLD)

    def test_deal_rows_name_the_teams_leader_not_the_team_id(self):
        self.run_lua("""
        local i = 0
        local deal = { ResetIterator = function() i = 0 end, GetNextItem = function()
          i = i + 1
          if i == 1 then return 12, 0, 0, 4, 0, 0, 0, 1 end      -- Bravo declares war on team 4 (Hong Kong, player 3)
          if i == 2 then return 11, 10, 240, 1, 0, 0, 0, 0 end   -- Alpha makes peace with team 1 (Prague, player 5)
        end }
        local r = H.deal_items(deal, 0)
        assert(#r == 2, H.json(r))
        assert(r[1].type == 'THIRD_PARTY_WAR' and r[1].from_us == false and r[1].team == 4 and r[1].other == 3, H.json(r[1]))
        assert(r[1].other_name == 'Hong Kong' and r[1].minor == true)
        assert(r[2].type == 'THIRD_PARTY_PEACE' and r[2].from_us == true and r[2].team == 1 and r[2].other == 5 and r[2].other_name == 'Prague', H.json(r[2]))
        """)

    def test_catalog_mirrors_the_other_players_pocket(self):
        self.run_lua("""
        local asked = {}
        local deal = { IsPossibleToTradeItem = function(_, from, to, typ, team)
          asked[#asked + 1] = { from, to, typ, team }
          if typ == 12 then return not (from == 1 and team == 1) end   -- Bravo is force-peaced with Prague's team
          return false                                                 -- nobody is at war: no peace items
        end }
        local c = H.third_party_catalog(deal, 0, 1)
        -- Hong Kong (team 4) and Prague (team 1) are met by both; Unmet (team 3) is not; Dead is dead; Bravo/Alpha excluded
        local function names(rows) local o = {} for _, r in ipairs(rows) do o[#o + 1] = r.name .. ':' .. tostring(r.ok) end return table.concat(o, ',') end
        assert(names(c.war.us) == 'Hong Kong:true,Prague:true', names(c.war.us))
        assert(names(c.war.them) == 'Hong Kong:true,Prague:false', names(c.war.them))
        local prague_them = c.war.them[2]
        assert(prague_them.player == 5 and prague_them.team == 1 and prague_them.minor == true, H.json(prague_them))
        assert(prague_them.note == 'Locked into peace', tostring(prague_them.note))
        assert(c.peace.us[1].ok == false and c.peace.us[1].note == 'Not at war', H.json(c.peace.us[1]))
        for _, q in ipairs(asked) do assert(q[4] == 4 or q[4] == 1, 'asked about a team the pocket never shows: ' .. q[4]) end
        """)


if __name__ == "__main__":
    unittest.main()
