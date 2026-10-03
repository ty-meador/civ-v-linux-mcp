"""Peace with terms on the trade table (GitLab #5).

Neither stock screen has a Peace Treaty pocket button: tradelogic.lua OnOpenPlayerDealScreen seeds
TRADE_ITEM_PEACE_TREATY on both sides itself when two humans at war open a table, and after
HUMAN_NEGOTIATE_PEACE the engine opens the AI's table with the same pair already on it. The gate a human
sees is the leader screen's Negotiate Peace button (leaderheadroot.lua OnShowHide): hidden without
CanChangeWarPeace, greyed with the locked-into-war tooltip. trade_catalog().peace is that gate and
_check_deal_items applies it to every deal proposed while at war.
"""
import unittest

import test_mcp_safety as support


class PeaceLegalityTests(unittest.TestCase):
    BASE = {"ok": True, "gold": {"us": True, "them": True, "us_available": 500, "them_available": 40},
            "gold_per_turn": {"us": True, "them": True, "us_available": 20, "them_available": 3},
            "resources": [], "cities": {"us": [], "them": []}}

    def game(self, peace):
        from harness.game import Game
        g = Game.__new__(Game)
        g.seat = 0
        g.trade_catalog = lambda other, pid=None: dict(self.BASE, at_war=peace.get("at_war", False), peace=peace)
        return g

    def check(self, peace, *items):
        return self.game(peace)._check_deal_items(1, list(items), 0)

    def test_peace_treaty_is_a_known_item_type(self):
        from harness.game import Game
        self.assertIn("PEACE_TREATY", Game._DEAL_ITEM_TYPES)

    def test_a_treaty_at_peace_is_refused(self):
        r = self.check({"at_war": False, "ok": False, "note": "not at war"}, {"type": "PEACE_TREATY"})
        self.assertFalse(r["ok"])
        self.assertIn("not at war", r["err"])

    def test_any_deal_while_locked_into_war_carries_the_screen_reason(self):
        peace = {"at_war": True, "ok": False, "locked_turns": 7, "note": "You cannot negotiate peace for 7 more turns."}
        r = self.check(peace, {"type": "GOLD_PER_TURN", "from_us": True, "amount": 2})
        self.assertFalse(r["ok"])
        self.assertIn("7 more turns", r["err"])
        self.assertEqual(r["peace"], peace)
        r = self.check(peace, {"type": "PEACE_TREATY"})
        self.assertFalse(r["ok"])

    def test_an_open_gate_passes_the_treaty_and_its_terms(self):
        peace = {"at_war": True, "ok": True, "locked_turns": 0, "us": True, "them": True}
        r = self.check(peace, {"type": "PEACE_TREATY"}, {"type": "GOLD_PER_TURN", "from_us": True, "amount": 2})
        self.assertTrue(r["ok"], r)
        self.assertTrue(self.check(peace, {"type": "GOLD_PER_TURN", "from_us": False, "amount": 3})["ok"])

    def test_at_peace_ordinary_deals_are_untouched(self):
        self.assertTrue(self.check({"at_war": False, "ok": False, "note": "not at war"},
                                   {"type": "GOLD_PER_TURN", "from_us": True, "amount": 2})["ok"])

    def test_make_peace_puts_the_treaty_first(self):
        from harness.game import Game
        g = Game.__new__(Game)
        g.seat = 0
        seen = {}
        g.propose_deal = lambda other, items, ask_counter=False, pid=None: seen.update(other=other, items=items) or {"ok": True}
        g.make_peace(1, [{"type": "GOLD_PER_TURN", "from_us": True, "amount": 2}])
        self.assertEqual(seen["other"], 1)
        self.assertEqual(seen["items"][0], {"type": "PEACE_TREATY"})
        self.assertEqual(len(seen["items"]), 2)
        g.make_peace(1)
        self.assertEqual(seen["items"], [{"type": "PEACE_TREATY"}])


class PeaceCatalogTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    WORLD = r"""
    TradeableItems = { TRADE_ITEM_PEACE_TREATY = 9 }
    GameDefines = { PEACE_TREATY_LENGTH = 10 }
    GameOptionTypes = { GAMEOPTION_ALWAYS_WAR = 1, GAMEOPTION_NO_CHANGING_WAR_PEACE = 2 }
    OPTIONS = {}
    Game = Game or {}
    Game.IsOption = function(o) return OPTIONS[o] == true end
    Game.GetPeaceDuration = function() return 10 end
    WAR, LOCK, CAN, POSSIBLE = {}, {}, {}, {}
    local function player(id, team) return { GetID = function() return id end, GetTeam = function() return team end } end
    Players = { [0] = player(0, 0), [1] = player(1, 5) }
    Teams = {}
    for t = 0, 5 do
      Teams[t] = { IsAtWar = function(_, o) return WAR[t .. ':' .. o] == true end,
                   CanChangeWarPeace = function(_, o) return CAN[t .. ':' .. o] ~= false end,
                   GetNumTurnsLockedIntoWar = function(_, o) return LOCK[t .. ':' .. o] or 0 end }
    end
    Locale = { ConvertTextKey = function(k, n)
      if k == 'TXT_KEY_DIPLO_NEGOTIATE_PEACE_BLOCKED_TT' then return 'You cannot negotiate peace for ' .. n .. ' more turns.' end
      return k
    end }
    deal = { IsPossibleToTradeItem = function(_, from, to, typ, a)
      assert(typ == 9 and a == 10, 'peace treaty asked with its length')
      return POSSIBLE[from .. ':' .. to] ~= false
    end }
    """

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(self.WORLD)

    def test_at_peace(self):
        self.run_lua("""
        local c = H.peace_catalog(deal, 0, 1)
        assert(c.at_war == false and c.ok == false and c.note == 'not at war', H.json(c))
        assert(c.locked_turns == nil and c.us == nil, H.json(c))
        """)

    def test_locked_into_war_reads_like_the_button_tooltip(self):
        self.run_lua("""
        WAR['0:5'], WAR['5:0'], LOCK['0:5'] = true, true, 7
        local c = H.peace_catalog(deal, 0, 1)
        assert(c.at_war == true and c.ok == false and c.locked_turns == 7, H.json(c))
        assert(c.note == 'You cannot negotiate peace for 7 more turns.', H.json(c))
        assert(c.us == true and c.them == true, H.json(c))
        """)

    def test_open_gate(self):
        self.run_lua("""
        WAR['0:5'], WAR['5:0'] = true, true
        local c = H.peace_catalog(deal, 0, 1)
        assert(c.ok == true and c.note == nil and c.locked_turns == 0, H.json(c))
        assert(c.can_change_war_peace == true and c.duration == 10, H.json(c))
        """)

    def test_engine_refusal_and_fixed_options(self):
        self.run_lua("""
        WAR['0:5'], WAR['5:0'] = true, true
        POSSIBLE['1:0'] = false
        local c = H.peace_catalog(deal, 0, 1)
        assert(c.ok == false and c.us == true and c.them == false and c.note:find('engine'), H.json(c))
        POSSIBLE['1:0'] = nil
        CAN['0:5'] = false
        c = H.peace_catalog(deal, 0, 1)
        assert(c.ok == false and c.can_change_war_peace == false and c.note:find('cannot be changed'), H.json(c))
        CAN['0:5'] = nil
        OPTIONS[2] = true
        c = H.peace_catalog(deal, 0, 1)
        assert(c.ok == false and c.note:find('game options'), H.json(c))
        """)


if __name__ == "__main__":
    unittest.main()


class SeededPeaceTableTests(unittest.TestCase):
    """Live t206: the first turn Russia's and Portugal's Negotiate Peace buttons were lit, the tables they opened
    carried the treaty pair plus THIRD_PARTY_PEACE rows for their allied city-states (Almaty; Zurich, Riga, Kiev,
    Jerusalem), and make_peace refused both as 'already holds a deal'."""

    PAIR = [{"duration": 10, "type": "PEACE_TREATY", "from_us": False, "from": 7},
            {"duration": 10, "type": "PEACE_TREATY", "from_us": True, "from": 1}]

    def test_the_pair_alone_is_the_seeded_table(self):
        from harness.game_parts.deals import _seeded_peace_table, _allied_minors
        self.assertTrue(_seeded_peace_table(self.PAIR))
        self.assertEqual(_allied_minors(self.PAIR), [])

    def test_the_pair_with_allied_city_states_is_the_seeded_table_and_names_them(self):
        from harness.game_parts.deals import _seeded_peace_table, _allied_minors
        rows = self.PAIR + [{"other": 28, "from_us": True, "other_name": "Almaty", "from": 1, "team": 28,
                             "duration": 10, "minor": True, "type": "THIRD_PARTY_PEACE"}]
        self.assertTrue(_seeded_peace_table(rows))
        self.assertEqual(_allied_minors(rows), [{"player_id": 28, "name": "Almaty"}])

    def test_anything_else_on_the_table_is_a_loaded_deal(self):
        from harness.game_parts.deals import _seeded_peace_table
        self.assertFalse(_seeded_peace_table([]))
        self.assertFalse(_seeded_peace_table(self.PAIR + [{"type": "GOLD", "from_us": False, "amount": 100}]))
        # peace with a major civ is a term someone put there, not the seeding
        self.assertFalse(_seeded_peace_table(self.PAIR + [{"type": "THIRD_PARTY_PEACE", "other": 2, "minor": False}]))
        # allied minors without the treaty itself is not a peace table
        self.assertFalse(_seeded_peace_table([{"type": "THIRD_PARTY_PEACE", "other": 28, "minor": True}]))
