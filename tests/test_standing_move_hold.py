"""A standing move is held, not resumed, when resuming would walk the unit into harm or waste its purpose (GitLab #98).

Live Maya t34-t38 and t54-t62 (2026-10-27): the resume ran at the turn start, before the seat saw the turn. A
Spearman and then a Scout walked one plot a turn around a barbarian camp, arrived in `ongoing` with 0 moves every
turn, were bombarded every AI turn and died with no turn to react. Settlers and Prophets arrived with 0 moves and
lost the turn their purpose needed. Now the record is kept and the move is not re-issued when a hostile or a camp
is beside the unit, or when a civilian's destination is within this turn's reach; the unit stands in todo.units
with its moves and the reason.
"""
import unittest

import test_mcp_safety as support
from harness.game import Game

WORLD = """
GameDefines = { MOVE_DENOMINATOR = 60 }
GameInfoTypes = { IMPROVEMENT_BARBARIAN_CAMP = 7 }
GameInfo = GameInfo or {}
GameInfo.Units = { [1] = { Type = 'UNIT_WARRIOR' }, [2] = { Type = 'UNIT_SETTLER' } }
PLOTS = {}
function plot(x, y)
  local k = x .. ',' .. y
  PLOTS[k] = PLOTS[k] or { units = {}, imp = -1,
    GetX = function() return x end, GetY = function() return y end,
    IsVisible = function() return true end, IsRevealed = function() return true end,
    IsImpassable = function() return false end,
    GetRevealedImprovementType = function(self) return self.imp end,
    GetNumUnits = function(self) return #self.units end, GetUnit = function(self, i) return self.units[i + 1] end }
  return PLOTS[k]
end
Map = { GetPlot = plot, PlotDistance = function(x1, y1, x2, y2) return math.max(math.abs(x1 - x2), math.abs(y1 - y2)) end }
UNITS = {}
Players = { [0] = { GetTeam = function() return 0 end, IsBarbarian = function() return false end,
                    GetUnitByID = function(_, id) return UNITS[id] end },
            [63] = { GetTeam = function() return 63 end, IsBarbarian = function() return true end } }
Teams = { [0] = { IsAtWar = function() return false end } }
H.melee_defender = function() return nil end
H.enemy_city_at = function() return false end
H.peaceful_occupant = function() return nil end
MOVED = {}
H.move_unit = function(id, x, y, pid) MOVED[#MOVED + 1] = { id, x, y }; return { ok = true } end
function mk(id, utype, x, y, combat)
  return { GetID = function() return id end, GetX = function() return x end, GetY = function() return y end,
           MovesLeft = function() return 120 end, MaxMoves = function() return 120 end,
           IsDelayedDeath = function() return false end, IsCombatUnit = function() return combat end,
           GetBuildType = function() return -1 end, GetUnitType = function() return utype end,
           GetOwner = function() return 0 end }
end
UNITS[1] = mk(1, 1, 22, 48, true)    -- the Spearman beside the camp
UNITS[2] = mk(2, 2, 10, 10, false)   -- a Settler
UNITS[3] = mk(3, 1, 5, 5, true)      -- a Warrior with nothing around
BRUTE = { GetOwner = function() return 63 end, IsCombatUnit = function() return true end,
          IsInvisible = function() return false end, GetUnitType = function() return 1 end,
          GetCurrHitPoints = function() return 100 end }
plot(23, 48).units = { BRUTE }
H.pending_moves = {}
"""


class HeldStandingMoveLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_a_hostile_beside_the_unit_holds_the_move_and_keeps_the_record(self):
        self.run_lua("""
        H.pending_moves[H.pm_key(1, 0)] = { x = 31, y = 60, pid = 0, unit_id = 1 }
        local out = H.resume_moves(0)
        assert(#out == 1 and out[1].held == true and out[1].reason == 'hostile', H.json(out))
        assert(out[1].err:find('standing move held', 1, true) and out[1].err:find('COMMAND_CANCEL', 1, true), out[1].err)
        assert(out[1].attention[1].kind == 'hostile' and out[1].attention[1].x == 23, H.json(out[1].attention))
        assert(#MOVED == 0, 'the move was not re-issued')
        assert(H.pending_moves[H.pm_key(1, 0)] ~= nil, 'the record survives: a move to the same plot resumes it')
        """)

    def test_a_camp_beside_the_unit_holds_it_too(self):
        self.run_lua("""
        plot(23, 48).units = {}
        plot(21, 47).imp = 7
        H.pending_moves[H.pm_key(1, 0)] = { x = 31, y = 60, pid = 0, unit_id = 1 }
        local out = H.resume_moves(0)
        assert(#out == 1 and out[1].held == true and out[1].reason == 'camp', H.json(out))
        assert(out[1].err:find('barbarian camp at (21,47)', 1, true), out[1].err)
        assert(#MOVED == 0)
        """)

    def test_a_civilian_within_reach_is_left_to_the_seat_and_a_far_one_resumes(self):
        self.run_lua("""
        H.pending_moves[H.pm_key(2, 0)] = { x = 11, y = 10, pid = 0, unit_id = 2 }
        local out = H.resume_moves(0)
        assert(#out == 1 and out[1].held == true and out[1].reason == 'within_reach', H.json(out))
        assert(out[1].err:find('act on arrival', 1, true), out[1].err)
        assert(#MOVED == 0 and H.pending_moves[H.pm_key(2, 0)] ~= nil)
        H.pending_moves = {}
        H.pending_moves[H.pm_key(2, 0)] = { x = 20, y = 10, pid = 0, unit_id = 2 }
        out = H.resume_moves(0)
        assert(#out == 1 and out[1].resumed == true, H.json(out))
        assert(#MOVED == 1 and MOVED[1][1] == 2 and MOVED[1][2] == 20, H.json(MOVED))
        """)

    def test_a_combat_unit_with_nothing_around_resumes_as_before(self):
        self.run_lua("""
        H.pending_moves[H.pm_key(3, 0)] = { x = 9, y = 9, pid = 0, unit_id = 3 }
        local out = H.resume_moves(0)
        assert(#out == 1 and out[1].resumed == true, H.json(out))
        assert(#MOVED == 1 and MOVED[1][1] == 3, H.json(MOVED))
        """)

    def test_the_skip_refusal_names_the_cancel_command(self):
        from harness import runtime_source
        src = runtime_source.snapshot().text
        self.assertIn("COMMAND_CANCEL'}) to drop the path on purpose", src)


class HeldMoveIsATodoNote(unittest.TestCase):
    """The arrival puts a held move's reason on the unit's todo row, as it does a dropped one's."""

    def test_the_row_carries_the_reason(self):
        g = Game.__new__(Game)
        g.seat = 0
        g._runtime_ok = True
        g._pid = lambda pid=None: 0
        held = {"unit_id": 24576, "x": 31, "y": 60, "held": True, "reason": "hostile",
                "err": "standing move held: Barbarians WARRIOR at (23,48) is beside the unit, so it keeps its moves this turn"}
        flags = dict.fromkeys(Game.MODAL_FLAGS, False)

        def q(code, timeout=None):
            if "H.resume_moves" in code:
                return [held]
            if "H.turn_state" in code:
                return {"turn": 35, "active_player": 0, "my_turn": True, "processing": False, "hotseat": False,
                        "pending_popups": [], **flags,
                        "todo": {"units": [{"id": 24576, "type": "SPEARMAN", "x": 22, "y": 48, "moves": 2}]}}
            return []
        g.q = q
        g.notebook = lambda: (_ for _ in ()).throw(RuntimeError("no notebook here"))
        g.expiring_city_states = list
        g._unit_rows = lambda pid=None: [{"id": 24576, "x": 22, "y": 48, "moves": 2, "max_moves": 2}]
        from unittest import mock
        with mock.patch("harness.game.time.sleep", lambda s: None):
            ts = g._arrive(g.turn_state())
        self.assertEqual(ts["resumed_moves"], [held])
        self.assertEqual(ts["todo"]["units"][0]["note"], held["err"])

    def test_an_ongoing_row_carries_the_reason_too(self):
        """Live Maya t5: the move was ordered on an automated Warrior at 0 moves; the hold landed and the unit sat in
        `ongoing` with no word of it."""
        g = Game.__new__(Game)
        g.seat = 0
        g._runtime_ok = True
        g._pid = lambda pid=None: 0
        held = {"unit_id": 16385, "x": 31, "y": 25, "held": True, "reason": "camp", "err": "standing move held: a barbarian camp"}
        flags = dict.fromkeys(Game.MODAL_FLAGS, False)
        g.q = lambda code, timeout=None: [held] if "H.resume_moves" in code else (
            {"turn": 5, "active_player": 0, "my_turn": True, "processing": False, "hotseat": False, "pending_popups": [], **flags,
             "todo": {"units": [], "ongoing": [{"id": 16385, "type": "WARRIOR", "automated": True, "x": 31, "y": 24}]}}
            if "H.turn_state" in code else [])
        g.notebook = lambda: (_ for _ in ()).throw(RuntimeError("none"))
        g.expiring_city_states = list
        g._unit_rows = lambda pid=None: [{"id": 16385, "x": 31, "y": 24, "moves": 0, "max_moves": 2}]
        from unittest import mock
        with mock.patch("harness.game.time.sleep", lambda s: None):
            ts = g._arrive(g.turn_state())
        self.assertEqual(ts["todo"]["ongoing"][0]["note"], held["err"])


if __name__ == "__main__":
    unittest.main()
