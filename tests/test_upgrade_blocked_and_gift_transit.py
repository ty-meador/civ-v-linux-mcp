"""Runtime v254, two things a human reads off a greyed button and a seat did not (live t153, Venice):

- `units` rows: `upgrade_blocked`, the unit panel's red lines under a disabled Upgrade button
  (unitpanel.lua COMMAND_UPGRADE): outside my territory, an air unit outside a city, not enough gold, a
  strategic resource short, a second unit of the kind on the plot -- plus `moved` when none of those holds.
- `gift_unit_options` / `gift_unit`: the city-state screen's own figures (influence the gift earns, the
  travel turns) and its one gate -- while a gifted unit is still on its way the button is greyed and no
  unit can be gifted; the refusal says so instead of "move adjacent first".
"""
import unittest

import test_mcp_safety as support


UPGRADE_WORLD = r"""
local function iter(rows)
  local i = 0
  return function() i = i + 1; return rows[i] end
end
GameInfo = GameInfo or {}
GameInfo.Resources = function() return iter({
  { ID = 1, Type = "RESOURCE_IRON", Description = "TXT_KEY_RESOURCE_IRON" },
  { ID = 2, Type = "RESOURCE_HORSE", Description = "TXT_KEY_RESOURCE_HORSE" },
}) end
DomainTypes = { DOMAIN_LAND = 0, DOMAIN_AIR = 2 }
World = { gold = 2500, available = { [1] = 0, [2] = 3 } }
Players = { [0] = {
  GetGold = function() return World.gold end,
  GetNumResourceAvailable = function(_, id) return World.available[id] or 0 end,
} }
function make_unit(o)
  local plot = {
    GetOwner = function() return o.plot_owner == nil and 0 or o.plot_owner end,
    IsCity = function() return o.in_city == true end,
    GetNumFriendlyUnitsOfType = function() return o.stacked or 1 end,
  }
  return {
    GetPlot = function() return plot end,
    GetOwner = function() return 0 end,
    GetDomainType = function() return o.domain or 0 end,
    GetNumResourceNeededToUpgrade = function(_, id) return (o.needs or {})[id] or 0 end,
    HasMoved = function() return o.moved == true end,
  }
end
"""


class UpgradeBlockedTests(support.LuaRuntimeTests):
    def test_the_warrior_without_iron(self):
        self.run_lua(UPGRADE_WORLD)
        self.run_lua(r"""
local rows = H.upgrade_blocked(make_unit({ in_city = true, needs = { [1] = 1 } }), 0, 55)
assert(#rows == 1 and rows[1].reason == "resources", H.json(rows))
local r = rows[1].resources
assert(#r == 1 and r[1].resource == "IRON" and r[1].needed == 1 and r[1].available == 0, H.json(rows))
assert(rows[1].text == nil or type(rows[1].text) == "string")
""")

    def test_territory_gold_city_and_stacking_each_have_a_row(self):
        self.run_lua(UPGRADE_WORLD)
        self.run_lua(r"""
World.gold = 40
local rows = H.upgrade_blocked(make_unit({ plot_owner = 3 }), 0, 55)
assert(#rows == 2 and rows[1].reason == "territory" and rows[1].owner == 3, H.json(rows))
assert(rows[2].reason == "gold" and rows[2].price == 55 and rows[2].gold == 40, H.json(rows))
World.gold = 2500
rows = H.upgrade_blocked(make_unit({ domain = 2 }), 0, 300)
assert(#rows == 1 and rows[1].reason == "city", "an air unit outside a city: " .. H.json(rows))
rows = H.upgrade_blocked(make_unit({ domain = 2, in_city = true, stacked = 2 }), 0, 300)
assert(#rows == 1 and rows[1].reason == "stacking" and rows[1].units_on_plot == 2, H.json(rows))
-- Unowned plot (owner -1) is outside my territory too, as the panel reads it.
rows = H.upgrade_blocked(make_unit({ plot_owner = -1 }), 0, 55)
assert(#rows == 1 and rows[1].reason == "territory" and rows[1].owner == -1, H.json(rows))
""")

    def test_a_target_the_player_cannot_train_yet_names_its_tech_and_nothing_else(self):
        self.run_lua(UPGRADE_WORLD)
        self.run_lua(r"""
GameInfo.Units = { [9] = { Type = "UNIT_GATLINGGUN", Description = "TXT_KEY_UNIT_GATLINGGUN", PrereqTech = "TECH_INDUSTRIALIZATION" } }
GameInfo.Technologies = { TECH_INDUSTRIALIZATION = { Description = "TXT_KEY_TECH_INDUSTRIALIZATION" } }
GameInfoTypes = { TECH_INDUSTRIALIZATION = 70 }
local known = {}
Teams = { [0] = { GetTeamTechs = function() return { HasTech = function(_, id) return known[id] == true end } end } }
Players[0].GetTeam = function() return 0 end
World.cantrain = false
-- bTestVisible true: the panel's visibility test, which lets a missing resource through (the red line says it).
Players[0].CanTrain = function(_, t, cont, vis, nocost, noupg) assert(t == 9 and vis == true and nocost and noupg); return World.cantrain end
-- Live t153: a Crossbowman outside a city with 2500 gold and no Iron trouble; before Industrialization the
-- only reason is the target itself, and the territory / resource lines are not added on top.
local rows = H.upgrade_blocked(make_unit({ plot_owner = -1, needs = { [1] = 1 } }), 0, 150, 9)
assert(#rows == 1 and rows[1].reason == "unavailable" and rows[1].unit == "UNIT_GATLINGGUN", H.json(rows))
assert(rows[1].prereq_tech == "TECH_INDUSTRIALIZATION" and rows[1].text:find("cannot be trained yet"), H.json(rows))
known[70] = true
rows = H.upgrade_blocked(make_unit({ in_city = true }), 0, 150, 9)
assert(#rows == 1 and rows[1].reason == "unavailable" and rows[1].prereq_tech == nil, "tech known, some other gate: " .. H.json(rows))
World.cantrain = true
assert(#H.upgrade_blocked(make_unit({ in_city = true }), 0, 150, 9) == 0, "trainable: the panel's own checks decide")
""")

    def test_a_unit_that_moved_and_nothing_else_says_so_and_a_free_one_says_nothing(self):
        self.run_lua(UPGRADE_WORLD)
        self.run_lua(r"""
local rows = H.upgrade_blocked(make_unit({ in_city = true, moved = true }), 0, 55)
assert(#rows == 1 and rows[1].reason == "moved" and rows[1].text:find("full moves"), H.json(rows))
assert(#H.upgrade_blocked(make_unit({ in_city = true }), 0, 55) == 0, "nothing in the way: empty list")
-- The panel's reasons come first; `moved` is only for when the panel would show no red line at all.
rows = H.upgrade_blocked(make_unit({ moved = true, needs = { [1] = 1 } }), 0, 55)
assert(#rows == 1 and rows[1].reason == "resources", H.json(rows))
""")


GIFT_WORLD = r"""
GameInfo = GameInfo or {}
GameInfo.Units = { [1] = { Type = "UNIT_WARRIOR" }, [2] = { Type = "UNIT_SCOUT" } }
GameDefines = GameDefines or {}
GameDefines.MINOR_UNIT_GIFT_TRAVEL_TURNS = 3
World = { countdown = -1, can = { [7] = true, [8] = true }, sent = {} }
local function unit(id, t) return {
  GetID = function() return id end, GetUnitType = function() return t end,
  GetX = function() return id end, GetY = function() return 1 end,
  CanDistanceGift = function() return World.can[id] == true and World.countdown < 0 end,
} end
local mine = { unit(7, 1), unit(8, 2) }
Players = {
  [0] = { GetTeam = function() return 0 end, Units = function() local i = 0; return function() i = i + 1; return mine[i] end end },
  [22] = { GetTeam = function() return 5 end, IsMinorCiv = function() return true end, IsAlive = function() return true end,
           GetName = function() return "Yerevan" end,
           GetMinorCivFriendshipWithMajor = function() return 0 end,
           GetFriendshipFromUnitGift = function(_, pid, great, distance) assert(pid == 0 and great == false and distance == true); return 5 end,
           GetIncomingUnitCountdown = function() return World.countdown end },
}
Teams = { [0] = { IsHasMet = function() return true end, IsAtWar = function() return false end } }
Game = Game or {}
Game.GetActivePlayer = function() return 0 end
Network = Network or {}
Network.SendGiftUnit = function(minor, uid) World.sent[#World.sent + 1] = uid end
"""


class GiftUnitTransitTests(support.LuaRuntimeTests):
    def test_the_options_carry_the_buttons_figures(self):
        self.run_lua(GIFT_WORLD)
        self.run_lua(r"""
local o = H.gift_unit_options(22, 0)
assert(o.ok and #o.units == 2 and o.influence_gain == 5 and o.travel_turns == 3, H.json(o))
assert(o.in_transit == nil and o.why_empty == nil)
local r = H.gift_unit(22, 7, 0)
assert(r.ok and r.influence_gain == 5 and r.travel_turns == 3 and #World.sent == 1 and World.sent[1] == 7, H.json(r))
""")

    def test_a_gift_on_its_way_empties_the_list_and_names_itself_in_the_refusal(self):
        self.run_lua(GIFT_WORLD)
        self.run_lua(r"""
World.countdown = 2
local o = H.gift_unit_options(22, 0)
assert(o.ok and #o.units == 0 and o.in_transit.arrives_in == 2, H.json(o))
assert(o.why_empty:find("on its way to Yerevan") and o.why_empty:find("2 turn"), o.why_empty)
local r = H.gift_unit(22, 8, 0)
assert(not r.ok and r.err:find("on its way") and not r.err:find("adjacent"), r.err)
assert(#World.sent == 0, "nothing sent")
-- A unit the engine will not take, with nothing in transit: the refusal names the engine's gate, not a guess.
World.countdown = -1
World.can[8] = false
r = H.gift_unit(22, 8, 0)
assert(not r.ok and r.err:find("CanDistanceGift") and not r.err:find("adjacent"), r.err)
""")


if __name__ == "__main__":
    unittest.main()
