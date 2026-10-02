"""turn_status.expiring_deals / expiring_friendships (#38): deals and declarations of friendship with majors
about to lapse, the same warning city-state alliances already get, and the quiet-turn wake behind it.

Mongolia t21-42: two embassy-for-gold deals lapsed and the seat learned it from the "expired" notice after
the fact; a DoF with Catherine had no remaining-turns line on the turn the seat reads.
"""
import unittest

import test_mcp_safety as support
from test_finish_turn import QUIET, ScriptedGame, status


WORLD = r"""
Game.GetGameTurn = function() return 40 end
GameDefines = { MAX_MAJOR_CIVS = 4, DOF_EXPIRATION_TIME = 50 }
TradeableItems = { TRADE_ITEM_GOLD_PER_TURN = 2, TRADE_ITEM_ALLOW_EMBASSY = 7, TRADE_ITEM_RESOURCES = 3 }
GameInfo = GameInfo or {}
GameInfo.Resources = { [5] = { ID = 5, Type = "RESOURCE_SILK", ResourceClassType = "RESOURCECLASS_LUXURY" } }
local met = { [0] = true, [1] = true, [2] = true, [3] = false }
Teams = {}
for t = 0, 3 do Teams[t] = { IsHasMet = function(_, o) return t == 0 and met[o] == true or t == o end } end
local names = { [1] = "Russia", [2] = "Portugal", [3] = "Siam" }
W = { dof = { [1] = 45, [2] = 44 }, too_soon = {}, proposal_from = nil, scratch = {}, loaded = nil, cleared = 0,
      deals = {
        -- Russia: we pay 1 gpt for their embassy, started t13 for 30 turns: ends t43, 3 turns left
        { other = 1, start = 13, dur = 30, items = {
            { 2, 30, 43, 1, nil, nil, nil, 0 }, { 7, 30, 43, nil, nil, nil, nil, 1 } } },
        -- Portugal: 4 turns left, outside the window
        { other = 2, start = 14, dur = 30, items = { { 2, 30, 44, 1, nil, nil, nil, 0 } } },
        -- Siam (never met): 1 turn left, must not be named
        { other = 3, start = 11, dur = 30, items = { { 3, 30, 41, 5, 1, nil, nil, 3 } } },
      } }
Players = {}
for i = 0, 3 do
  Players[i] = {
    IsAlive = function() return true end, IsMinorCiv = function() return false end,
    GetTeam = function() return i end,
    GetCivilizationShortDescription = function() return names[i] or "Mongolia" end,
    IsDoF = function(_, o) return i == 0 and W.dof[o] ~= nil end,
    GetDoFCounter = function(_, o) return W.dof[o] or 0 end,
    IsDoFMessageTooSoon = function(_, o) return W.too_soon[i] == true end,
    GetNumResourceAvailable = function() return 0 end,
  }
end
local function rows()
  local k = 0
  return function()
    k = k + 1
    local r = W.scratch[k]
    if r then return table.unpack(r) end
  end
end
local it
deal = {
  ResetIterator = function() it = rows() end,
  GetNextItem = function() return it() end,
  GetOtherPlayer = function() return W.loaded and W.loaded.other end,
  GetStartTurn = function() return W.loaded and W.loaded.start end,
  GetDuration = function() return W.loaded and W.loaded.dur end,
  GetFromPlayer = function() return 0 end, GetToPlayer = function() return 1 end,
  ClearItems = function() W.cleared = W.cleared + 1; W.scratch = {}; W.loaded = nil end,
  AddGoldTrade = function() error("must not Add*") end,
}
UI = {
  GetScratchDeal = function() return deal end,
  GetNumCurrentDeals = function(pid) return pid == 0 and #W.deals or 0 end,
  LoadCurrentDeal = function(pid, i) W.loaded = W.deals[i + 1]; W.scratch = W.loaded.items end,
  ProposedDealExists = function(from, to) return from == W.proposal_from and to == 0 end,
  LoadProposedDeal = function() error("the snapshot must not load another seat's proposal") end,
  DoProposeDeal = function() error("must not propose") end,
  DoFinalizePlayerDeal = function() error("must not accept or refuse") end,
}
"""


class ExpiringDealsLuaTests(support.LuaRuntimeTests):
    def test_three_turns_is_in_four_is_not_and_unmet_is_not_named(self):
        self.run_lua(WORLD)
        self.run_lua(r"""
local rows = H.expiring_deals(0)
assert(#rows == 2, "Russia (3) and the unmet civ (1), not Portugal (4): " .. H.json(rows))
local ru, siam = rows[1], rows[2]
assert(ru.player_id == 1 and ru.civ == "Russia" and ru.turns_left == 3 and ru.ends_on == 43, H.json(ru))
assert(ru.items[1] == "we give GOLD_PER_TURN 1" and ru.items[2] == "they give ALLOW_EMBASSY", H.json(ru.items))
assert(ru.hint:find("stays committed until then", 1, true), "the hint says when a committed item can be re-offered: " .. tostring(ru.hint))
-- v256 (live t159): open borders are committed like a resource; the row names the turn a renewal is legal
assert(ru.hint:find("open borders", 1, true) and ru.hint:find("gold per turn can be re-offered now", 1, true), ru.hint)
assert(ru.reoffer_on == 44, "reoffer_on is the turn after ends_on: " .. tostring(ru.reoffer_on))
assert(siam.player_id == 3 and siam.civ == nil and siam.turns_left == 1, "an unmet civ is not named")
-- the same numbers current_deals prints
local cd = H.current_deals(0)
assert(cd.deals[1].turns_left == ru.turns_left and cd.deals[2].turns_left == 4)
assert(W.cleared == 2, "each snapshot empties the table it loaded")
""")

    def test_a_renewed_deal_names_the_new_end_and_nothing_to_reoffer(self):
        # live t161 Venice: China's open-borders swap (ends t161) renewed at the turn's start; current_deals
        # holds both until the turn ends, and the old row said "re-offer on t162"
        self.run_lua(WORLD)
        self.run_lua(r"""
TradeableItems.TRADE_ITEM_OPEN_BORDERS = 4
W.deals = {
  { other = 1, start = 10, dur = 30, items = { { 4, 30, 40, nil, nil, nil, nil, 0 }, { 4, 30, 40, nil, nil, nil, nil, 1 } } },
  { other = 1, start = 40, dur = 30, items = { { 4, 30, 70, nil, nil, nil, nil, 0 }, { 4, 30, 70, nil, nil, nil, nil, 1 } } },
  -- Portugal's gold per turn also ends now, with no newer deal behind it: the plain row
  { other = 2, start = 10, dur = 30, items = { { 2, 30, 40, 1, nil, nil, nil, 0 } } },
}
local rows = H.expiring_deals(0)
assert(#rows == 2, H.json(rows))
local ru, por = rows[1], rows[2]
assert(ru.renewed == true and ru.renewed_until == 70 and ru.reoffer_on == nil, H.json(ru))
assert(ru.hint:find("already renewed", 1, true) and ru.hint:find("turn 70", 1, true), ru.hint)
assert(ru.turns_left == 0 and ru.ends_on == 40, "the old deal's own numbers stay: " .. H.json(ru))
assert(por.renewed == nil and por.reoffer_on == 41, "a deal with no newer twin keeps the re-offer hint: " .. H.json(por))
-- a newer deal with a different item is no renewal
W.deals[2].items = { { 2, 30, 70, 5, nil, nil, nil, 1 } }
rows = H.expiring_deals(0)
assert(rows[1].renewed == nil and rows[1].reoffer_on == 41, H.json(rows[1]))
""")

    def test_an_items_giver_is_the_deals_other_player_not_the_engines_stray_id(self):
        # live t162 Mongolia: Catherine's renewal offer (deal 1 -> 7) carried England's id on her two items
        self.run_lua(WORLD)
        self.run_lua(r"""
TradeableItems.TRADE_ITEM_OPEN_BORDERS = 4
W.loaded = { other = 1 }
W.scratch = { { 3, 25, -1, 5, 1, nil, nil, 0 }, { 4, 25, -1, nil, nil, nil, nil, 2 }, { 2, 25, -1, 4, nil, nil, nil, 2 } }
local items = H.deal_items(deal, 0)
assert(#items == 3, H.json(items))
assert(items[1].from == 0 and items[1].from_us == true and items[1].from_engine == nil, H.json(items[1]))
assert(items[2].from == 1 and items[2].from_us == false and items[2].from_engine == 2, "the giver is the other player: " .. H.json(items[2]))
assert(items[3].from == 1 and items[3].from_engine == 2, H.json(items[3]))
-- an ordinary row (the engine's id is the other player) carries no from_engine
W.scratch = { { 4, 25, -1, nil, nil, nil, nil, 1 } }
items = H.deal_items(deal, 0)
assert(items[1].from == 1 and items[1].from_engine == nil, H.json(items[1]))
""")

    def test_a_permanent_deal_never_expires(self):
        # live t145 (Mongolia): Babylon's embassy swap, duration 0, read as ending the turn it was signed
        self.run_lua(WORLD)
        self.run_lua(r"""
W.deals[#W.deals + 1] = { other = 1, start = 40, dur = 0, items = { { 7, 0, 40, nil, nil, nil, nil, 1 }, { 7, 0, 40, nil, nil, nil, nil, 0 } } }
local rows = H.expiring_deals(0)
assert(#rows == 2, "the embassy swap is not about to lapse: " .. H.json(rows))
for _, r in ipairs(rows) do assert(r.turns_left > 0 or r.items[1]:find("GOLD_PER_TURN"), H.json(r)) end
""")

    def test_occupied_table_or_waiting_proposal_is_left_alone(self):
        self.run_lua(WORLD)
        self.run_lua(r"""
W.scratch = { { 2, 30, 0, 5, nil, nil, nil, 1 } }   -- an AI offer sits on the table
assert(H.expiring_deals(0) == nil, "occupied: field left off")
assert(W.cleared == 0 and #W.scratch == 1, "the offer is not cleared")
W.scratch = {}
W.proposal_from = 2                                  -- a human seat's proposal waits (not yet loaded)
assert(H.expiring_deals(0) == nil and W.cleared == 0, "a waiting proposal is not loaded or cleared")
W.proposal_from = nil
W.deals = {}
local none = H.expiring_deals(0)
assert(type(none) == "table" and #none == 0 and W.cleared == 0, "no deals: empty, table untouched")
""")

    def test_other_seats_deals_are_not_read(self):
        self.run_lua(WORLD)
        self.run_lua(r"""
local rows = H.expiring_deals(1)
assert(type(rows) == "table" and #rows == 0, "seat 1 has no deals of its own here: " .. H.json(rows))
""")

    def test_friendship_five_turns_is_in_six_is_not(self):
        self.run_lua(WORLD)
        self.run_lua(r"""
local rows = H.expiring_friendships(0)
assert(#rows == 1 and rows[1].player_id == 1 and rows[1].turns_left == 5 and rows[1].civ == "Russia", H.json(rows))
assert(rows[1].ask_too_soon == nil)
W.dof[2] = 45; W.too_soon[2] = true
rows = H.expiring_friendships(0)
assert(#rows == 2 and rows[2].player_id == 2 and rows[2].ask_too_soon == true, "greyed-out renewal is flagged")
W.dof[3] = 49                                        -- unmet: never listed
assert(#H.expiring_friendships(0) == 2)
assert(#H.expiring_friendships(1) == 0, "another seat's friendships are its own")
""")

    def test_relationship_reports_the_dof_counter(self):
        self.run_lua(WORLD)
        self.run_lua(r"""
-- relationship reads far more than this fixture models; every other method answers nil
local stub = { __index = function() return function() return nil end end }
for i = 0, 3 do setmetatable(Players[i], stub); setmetatable(Teams[i], stub) end
Game.GetActivePlayer = function() return 0 end
local r = H.relationship(0, 1)
assert(r.ok and r.declaration_of_friendship == true and r.dof_turns_left == 5, H.json(r))
""")

    def test_turn_state_carries_them_on_this_seats_own_turn_only(self):
        self.run_lua(WORLD)
        self.run_lua(r"""
local stub = { __index = function() return function() return nil end end }
for i = 0, 3 do setmetatable(Players[i], stub) end
Game.IsNetworkMultiPlayer = function() return false end
Game.GetGameState = function() return 0 end
Game.IsProcessingMessages = function() return false end
Game.IsPaused = function() return false end
GameplayGameStateTypes = { GAMESTATE_OVER = 2 }
PreGame = { IsHotSeatGame = function() return false end }
UI.IsPopupUp = function() return false end
H.modal_flags = function() return {} end
H.status_alerts = function() return {} end
H.pending_popups = function() return {} end
H.stale_units_blocker = function() return nil end
local ours = true
H.todo = function() return ours and { units = {} } or nil end
local t = H.turn_state(0)
assert(#t.expiring_deals == 2 and #t.expiring_friendships == 1, H.json(t))
ours = false
t = H.turn_state(0)
assert(t.expiring_deals == nil and t.expiring_friendships == nil, "not our turn: nothing read")
ours, W.deals, W.dof = true, {}, {}
t = H.turn_state(0)
assert(t.expiring_deals == nil and t.expiring_friendships == nil, "empty lists stay off the status")
""")


class ExpiringDealsWakeTests(unittest.TestCase):
    def test_a_lapsing_deal_or_friendship_wakes_a_quiet_run(self):
        for extra in ({"expiring_deals": [{"player_id": 1, "turns_left": 3}]},
                      {"expiring_friendships": [{"player_id": 1, "turns_left": 5}]}):
            g = ScriptedGame([(status(2, **extra), QUIET), (status(3), QUIET)])
            r = g.finish_turn(skip_quiet_turns=5)
            self.assertEqual(r["turn"], 2, extra)
            self.assertIn(next(iter(extra)), r["woke_because"])
        g = ScriptedGame([(status(2), QUIET), (status(3), QUIET)])
        self.assertEqual(g.finish_turn(skip_quiet_turns=1)["turn"], 3, "without them the turn is quiet")
        renewed = {"expiring_deals": [{"player_id": 1, "turns_left": 0, "renewed": True, "renewed_until": 70}]}
        g = ScriptedGame([(status(2, **renewed), QUIET), (status(3), QUIET)])
        self.assertEqual(g.finish_turn(skip_quiet_turns=1)["turn"], 3, "v258: a deal already renewed wakes nothing")

    def test_briefing_warnings_skip_a_renewed_deal(self):
        from harness.briefing import warnings
        ts = {"expiring_deals": [{"player_id": 1, "turns_left": 0, "renewed": True, "renewed_until": 70},
                                 {"player_id": 2, "turns_left": 1, "reoffer_on": 42}]}
        self.assertEqual([w["player_id"] for w in warnings(ts)], [2])


if __name__ == "__main__":
    unittest.main()
