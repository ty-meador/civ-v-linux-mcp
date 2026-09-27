"""todo.ongoing (#37): units the game is already moving -- automated, or walking a standing move_unit
order -- on the turn checklist with where they are going, without blocking end-turn, and the quiet-turn
wake rule behind them (a visible camp or hostile beside the unit wakes; ordinary exploration does not).

Lua half: H.todo / H.units / H.going_to / H.ongoing_attention against a mocked seat; Python half:
finish_turn's _wake_reasons on a scripted game.
"""
import unittest

import test_mcp_safety as support
from test_finish_turn import QUIET, ScriptedGame, status


# One seat, three units: an automated scout at (10,10), a chariot archer fortified and healing at (12,12),
# a settler at (5,5) with a standing move to (8,8). A camp and a barbarian brute can be placed on any plot;
# every plot is visible unless listed in World.fogged, revealed unless listed in World.unrevealed.
WORLD = r"""
local function iter(rows)
  local i = 0
  return function() i = i + 1; return rows[i] end
end
GameInfo = GameInfo or {}
GameInfo.Units = { [1] = { Type = "UNIT_SCOUT" }, [2] = { Type = "UNIT_CHARIOT_ARCHER" }, [3] = { Type = "UNIT_SETTLER" },
                   [4] = { Type = "UNIT_BRUTE" }, [5] = { Type = "UNIT_WARRIOR" } }
GameInfo.Domains = { [0] = { Type = "DOMAIN_LAND" } }
GameDefines = { MOVE_DENOMINATOR = 60, MAX_MAJOR_CIVS = 2 }
GameInfoTypes = { IMPROVEMENT_BARBARIAN_CAMP = 3 }
MissionTypes = { MISSION_MOVE_TO = 0, MISSION_FORTIFY = 8 }
ActivityTypes = { ACTIVITY_MISSION = 6, ACTIVITY_AWAKE = 1 }

World = { camp = nil, hostile = nil, fogged = {}, unrevealed = {}, impassable = {}, at_war = {} }
local function key(x, y) return x .. "," .. y end

function make_unit(o)
  local u = {}
  for k, v in pairs(o) do u[k] = v end
  u.GetID = function() return o.id end
  u.GetUnitType = function() return o.type end
  u.GetName = function() return "unit" end
  u.GetX = function() return o.x end
  u.GetY = function() return o.y end
  u.MovesLeft = function() return o.moves or 0 end
  u.MaxMoves = function() return 120 end
  u.GetCurrHitPoints = function() return o.hp or 100 end
  u.GetMaxHitPoints = function() return 100 end
  u.GetBaseCombatStrength = function() return o.strength or 0 end
  u.GetRangedCombatStrength = function() return 0 end
  u.Range = function() return 0 end
  u.IsEmbarked = function() return false end
  u.GetFortifyTurns = function() return o.fortified and 1 or 0 end
  u.IsAutomated = function() return o.automated == true end
  u.IsReadyToMove = function() return o.ready == true end
  u.IsDelayedDeath = function() return false end
  u.IsGarrisoned = function() return false end
  u.IsCombatUnit = function() return (o.strength or 0) > 0 end
  u.IsInvisible = function() return false end
  u.GetMissionType = function() return o.mission or -1 end
  u.GetActivityType = function() return o.activity or 1 end
  u.GetBuildType = function() return -1 end
  u.GetDomainType = function() return 0 end
  u.GetLevel = function() return 1 end
  u.GetExperience = function() return 0 end
  u.GetOwner = function() return o.owner or 0 end
  u.GetPlot = function() return Map.GetPlot(o.x, o.y) end
  u.CanFound = function() return false end
  u.IsPromotionReady = function() return false end
  return u
end

Units = {
  make_unit{ id = 101, type = 1, x = 10, y = 10, moves = 0, automated = true, mission = 0, activity = 6 },
  make_unit{ id = 102, type = 2, x = 12, y = 12, moves = 120, hp = 74, fortified = true, strength = 6, mission = 8 },
  make_unit{ id = 103, type = 3, x = 5, y = 5, moves = 0, mission = 0, activity = 6 },
}

local plots = {}
function Map.GetPlot(x, y)
  if x < 0 or y < 0 or x > 40 or y > 40 then return nil end
  local k = key(x, y)
  if not plots[k] then
    local pl = { x = x, y = y }
    pl.GetX = function() return x end
    pl.GetY = function() return y end
    pl.IsVisible = function() return not World.fogged[k] and not World.unrevealed[k] end
    pl.IsRevealed = function() return not World.unrevealed[k] end
    pl.IsImpassable = function() return World.impassable[k] == true end
    pl.IsCity = function() return false end
    pl.GetRevealedImprovementType = function() return (World.camp and World.camp.x == x and World.camp.y == y) and 3 or -1 end
    local occupants = function()
      local out = {}
      if World.hostile and World.hostile.x == x and World.hostile.y == y then out[#out + 1] = World.hostile.unit end
      for _, u in ipairs(Units) do if u.GetX() == x and u.GetY() == y then out[#out + 1] = u end end
      return out
    end
    pl.GetNumUnits = function() return #occupants() end
    pl.GetUnit = function(_, i) return occupants()[i + 1] end
    plots[k] = pl
  end
  return plots[k]
end
Map.PlotDistance = function(x1, y1, x2, y2)
  -- a plain grid is enough here: the eight neighbours of (x, y) are all at distance 1
  return math.max(math.abs(x1 - x2), math.abs(y1 - y2))
end

Players = {
  [0] = { GetTeam = function() return 0 end, IsTurnActive = function() return true end,
          GetCurrentResearch = function() return 1 end, IsBarbarian = function() return false end,
          Cities = function() return iter({}) end, Units = function() return iter(Units) end,
          GetUnitByID = function(_, id) for _, u in ipairs(Units) do if u.GetID() == id then return u end end end },
  [1] = { GetTeam = function() return 1 end, IsBarbarian = function() return false end,
          GetCivilizationShortDescription = function() return "Russia" end },
  [63] = { GetTeam = function() return 63 end, IsBarbarian = function() return true end },
}
Teams = { [0] = { IsAtWar = function(_, t) return World.at_war[t] == true end, IsHasMet = function() return true end } }
H.pending_moves = {}
H.pending_moves[H.pm_key(103, 0)] = { x = 8, y = 8, pid = 0, unit_id = 103 }
"""


class OngoingLuaTests(support.LuaRuntimeTests):
    def setUp(self):
        super().setUp()
        self.run_lua("Map = Map or {}")
        self.run_lua(WORLD)

    def test_automated_and_standing_move_units_are_ongoing_not_decisions(self):
        self.run_lua(r"""
local t = H.todo(0)
assert(#t.units == 0, "nothing needs orders: an automated scout, a fortified archer and a walking settler, got " .. H.json(t.units))
assert(t.ongoing and #t.ongoing == 2, "the scout and the settler are ongoing, got " .. H.json(t.ongoing))
local scout, settler = t.ongoing[1], t.ongoing[2]
assert(scout.id == 101 and scout.type == "SCOUT" and scout.automated == true and scout.going_to == nil, H.json(scout))
assert(scout.x == 10 and scout.y == 10 and scout.moves == 0 and scout.hp == 100 and scout.mission_name == "MISSION_MOVE_TO")
assert(scout.attention == nil, "an explorer merely exploring is not an alert")
assert(scout.note:find("move_unit"), "the row says how to take the unit back")
assert(settler.id == 103 and settler.automated == nil, "automated is only ever true")
assert(settler.going_to.x == 8 and settler.going_to.y == 8, "the standing destination is on the row: " .. H.json(settler))
assert(settler.attention == nil, "a revealed, passable destination with nothing beside the unit is quiet")
for _, row in ipairs(t.ongoing) do assert(row.id ~= 102, "the fortified archer is nobody's business this turn") end
""")

    def test_units_carry_going_to_only_when_a_destination_is_stored(self):
        self.run_lua(r"""
local rows = H.units(0)
local by = {}
for _, r in ipairs(rows) do by[r.id] = r end
assert(by[103].going_to.x == 8 and by[103].going_to.y == 8, H.json(by[103]))
assert(by[101].going_to == nil and by[102].going_to == nil, "no destination is invented")
-- the record belongs to a seat: seat 1's settler of the same id has no destination
assert(H.going_to(Units[3], 1) == nil, "another seat's record is not this seat's plan")
-- an arrived record is stale bookkeeping, not a plan
H.pending_moves[H.pm_key(103, 0)] = { x = 5, y = 5, pid = 0, unit_id = 103 }
assert(H.going_to(Units[3], 0) == nil, "standing on the destination means no going_to")
""")

    def test_a_visible_camp_or_hostile_beside_the_unit_is_attention(self):
        self.run_lua(r"""
World.camp = { x = 11, y = 10 }
local t = H.todo(0)
local a = t.ongoing[1].attention
assert(a and #a == 1 and a[1].kind == "camp" and a[1].x == 11 and a[1].y == 10, H.json(t.ongoing[1]))
-- the same camp under fog is unknown here, as on the map
World.fogged["11,10"] = true
t = H.todo(0)
assert(t.ongoing[1].attention == nil, "a fogged neighbour is not read: " .. H.json(t.ongoing[1]))
World.fogged["11,10"] = nil
World.camp = { x = 13, y = 12 }
t = H.todo(0)
assert(t.ongoing[1].attention == nil, "a camp two plots away is not beside the scout")
World.camp = nil
-- a barbarian brute next to the scout
World.hostile = { x = 9, y = 11, unit = make_unit{ id = 900, type = 4, x = 9, y = 11, strength = 8, hp = 60, owner = 63 } }
t = H.todo(0)
a = t.ongoing[1].attention
assert(a and #a == 1 and a[1].kind == "hostile", H.json(t.ongoing[1]))
assert(a[1].owner == "Barbarians" and a[1].unit == "BRUTE" and a[1].hp == 60 and a[1].x == 9 and a[1].y == 11, H.json(a))
-- a warrior of a civ we are at peace with is not hostile; at war it is, and it is named as met
World.hostile = { x = 9, y = 11, unit = make_unit{ id = 901, type = 5, x = 9, y = 11, strength = 8, owner = 1 } }
t = H.todo(0)
assert(t.ongoing[1].attention == nil, "a neighbour at peace does not wake anyone")
World.at_war[1] = true
t = H.todo(0)
assert(t.ongoing[1].attention[1].owner == "Russia", H.json(t.ongoing[1].attention))
World.at_war[1] = nil
-- a civilian of an enemy is not a combat unit
World.hostile = { x = 9, y = 11, unit = make_unit{ id = 902, type = 3, x = 9, y = 11, strength = 0, owner = 63 } }
t = H.todo(0)
assert(t.ongoing[1].attention == nil, "an enemy civilian is not a threat")
""")

    def test_a_destination_the_seat_cannot_reach_is_attention(self):
        self.run_lua(r"""
World.unrevealed["8,8"] = true
local t = H.todo(0)
local a = t.ongoing[2].attention
assert(a and a[1].kind == "destination_unrevealed" and a[1].x == 8 and a[1].y == 8, H.json(t.ongoing[2]))
World.unrevealed["8,8"] = nil
World.impassable["8,8"] = true
t = H.todo(0)
assert(t.ongoing[2].attention[1].kind == "destination_impassable", H.json(t.ongoing[2]))
World.impassable["8,8"] = nil
H.pending_moves[H.pm_key(103, 0)] = { x = 99, y = 99, pid = 0, unit_id = 103 }
t = H.todo(0)
assert(t.ongoing[2].attention[1].kind == "destination_gone", H.json(t.ongoing[2]))
""")

    def test_a_stalled_standing_move_still_needs_orders(self):
        """The existing shape: activity MISSION, moves in hand, not automated -- todo.units with the
        re-issue note, now with the destination too, and not doubled under ongoing."""
        self.run_lua(r"""
Units[3] = make_unit{ id = 103, type = 3, x = 5, y = 5, moves = 120, mission = 0, activity = 6 }
local t = H.todo(0)
assert(#t.units == 1 and t.units[1].id == 103 and t.units[1].stalled_mission == true, H.json(t.units))
assert(t.units[1].note:find("re%-issue move_unit") and t.units[1].going_to.x == 8, H.json(t.units[1]))
assert(#t.ongoing == 1 and t.ongoing[1].id == 101, "the stalled settler is a decision, not ongoing")
""")

    def test_ongoing_is_absent_when_nothing_is_moving(self):
        self.run_lua(r"""
H.pending_moves = {}
Units = { make_unit{ id = 102, type = 2, x = 12, y = 12, moves = 120, fortified = true, strength = 6, mission = 8 } }
local t = H.todo(0)
assert(t.ongoing == nil, "no key at all when there is nothing to list: " .. H.json(t))
assert(#t.units == 0)
""")


def ongoing(uid=101, attention=None):
    row = {"id": uid, "type": "SCOUT", "x": 10, "y": 10, "moves": 0, "hp": 100, "automated": True}
    if attention:
        row["attention"] = attention
    return {"units": [], "cities": [], "promotions": [], "research_unset": False, "ongoing": [row]}


class OngoingWakeTests(unittest.TestCase):
    def test_an_explorer_merely_exploring_lets_the_run_continue(self):
        g = ScriptedGame([(status(2, todo=ongoing()), QUIET), (status(3, todo=ongoing()), QUIET),
                          (status(4, todo=ongoing()), QUIET)])
        r = g.finish_turn(skip_quiet_turns=2)
        self.assertEqual(r["turns_skipped"], 2)
        self.assertEqual(r["status"]["turn"], 4)
        self.assertNotIn("ongoing", " ".join(r.get("woke_because") or []))

    def test_a_visible_camp_beside_an_ongoing_unit_wakes(self):
        g = ScriptedGame([(status(2, todo=ongoing(attention=[{"kind": "camp", "x": 11, "y": 10}])), QUIET),
                          (status(3, todo=ongoing()), QUIET)])
        r = g.finish_turn(skip_quiet_turns=2)
        self.assertEqual(r["turns_skipped"], 0)
        self.assertEqual(r["status"]["turn"], 2)
        self.assertIn("ongoing:101:camp", r["woke_because"])

    def test_a_hostile_beside_it_wakes_with_the_unit_named(self):
        g = ScriptedGame([(status(2, todo=ongoing(uid=7, attention=[{"kind": "hostile", "owner": "Barbarians",
                                                                       "unit": "BRUTE", "x": 9, "y": 11}])), QUIET)])
        r = g.finish_turn(skip_quiet_turns=3)
        self.assertEqual(r["woke_because"], ["ongoing:7:hostile"])

    def test_ongoing_never_blocks_end_turn_by_itself(self):
        """todo.ongoing is not a todo key that ends a quiet run (the generic rule is 'any non-empty todo
        list wakes'); only its attention does."""
        g = ScriptedGame([(status(2, todo=ongoing()), QUIET)])
        self.assertEqual(g._wake_reasons(status(2, todo=ongoing()), QUIET), [])
        self.assertEqual(g._wake_reasons(status(2, todo=ongoing(attention=[{"kind": "destination_unrevealed"}])), QUIET),
                         ["ongoing:101:destination_unrevealed"])


if __name__ == "__main__":
    unittest.main()
