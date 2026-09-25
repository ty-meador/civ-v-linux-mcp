"""A captured civilian is named, placed and explained, not mourned as an anonymous id.

"A Worker was captured by the Barbarians!" is all the bubble says; a human clicks it and the camera
pans to the tile, where the captor now stands. Live 2026-09-24 t217 (Alpha/Bravo hotseat) Bravo's
Settler arrived in the digest as a bare `unit_destroyed` id, an `unit_lost` fallback and the generic
notice, none of them linked. The runtime now keeps the dying unit's type and plot inside the destroy
hook and ties the notice to it; the digest folds the three rows into one `unit_captured`.
"""
import unittest

import test_mcp_safety as support
from harness.game import Game


WORLD = """
GameDefines = { MAX_HIT_POINTS = 100 }
DomainTypes = { DOMAIN_LAND = 0, DOMAIN_SEA = 1, DOMAIN_AIR = 2 }
PreGame = { IsHotSeatGame = function() return HOTSEAT end }
HOTSEAT = false
Locale = { Lookup = function(k) return ({ TXT_KEY_UNIT_WORKER = 'Worker', TXT_KEY_UNIT_SETTLER = 'Settler' })[k] or k end }
GameInfoTypes = { IMPROVEMENT_BARBARIAN_CAMP = 9 }
GameInfo = { Units = { [3] = { Type = 'UNIT_WORKER', Description = 'TXT_KEY_UNIT_WORKER' },
                       [4] = { Type = 'UNIT_SETTLER', Description = 'TXT_KEY_UNIT_SETTLER' },
                       [7] = { Type = 'UNIT_BRUTE' } } }
GameInfo.Units.UNIT_WORKER = GameInfo.Units[3]
GameInfo.Units.UNIT_SETTLER = GameInfo.Units[4]
Teams = { [0] = { IsHasMet = function() return false end }, [1] = { IsHasMet = function() return false end } }

function unit(owner, id, utype, x, y, combat)
  return { GetOwner = function() return owner end, GetID = function() return id end,
           GetUnitType = function() return utype end, GetX = function() return x end, GetY = function() return y end,
           IsCombatUnit = function() return combat end, IsInvisible = function() return false end,
           GetCurrHitPoints = function() return 80 end, GetMaxHitPoints = function() return 100 end,
           IsDelayedDeath = function() return false end }
end

-- The plot the worker stood on: the brute stands there now; visible unless FOG.
FOG = false
CAPTOR = unit(63, 900, 7, 10, 12, true)
local site = { IsVisible = function() return not FOG end, GetNumUnits = function() return 1 end,
               GetUnit = function(_, i) return CAPTOR end }
local camps = { [5] = { x = 13, y = 12 }, [9] = { x = 30, y = 30 } }
Map = { GetPlot = function(x, y) if x == 10 and y == 12 then return site end return nil end,
        GetNumPlots = function() return 12 end,
        GetPlotByIndex = function(i)
          local c = camps[i]
          return { IsRevealed = function() return c ~= nil end,
                   GetRevealedImprovementType = function() return c and 9 or -1 end,
                   GetX = function() return c and c.x or 0 end, GetY = function() return c and c.y or 0 end }
        end,
        PlotDistance = function(x1, y1, x2, y2) return math.max(math.abs(x1 - x2), math.abs(y1 - y2)) end }

WORKER = unit(0, 4321, 3, 10, 12, false)
Players = { [0] = { GetTeam = function() return 0 end, IsHuman = function() return true end,
                    GetUnitByID = function(_, id) if id == 4321 and not GONE then return WORKER end return nil end,
                    IsBarbarian = function() return false end },
            [1] = { GetTeam = function() return 1 end, IsHuman = function() return true end,
                    GetUnitByID = function() return nil end, IsBarbarian = function() return false end },
            [63] = { GetTeam = function() return 63 end, IsHuman = function() return false end,
                     IsBarbarian = function() return true end } }
GONE = false

-- Install the destroy and turn hooks and keep their closures.
DESTROY, TURN_START, TURN_END = nil, nil, nil
Events = { SerialEventUnitDestroyed = { Add = function(fn) DESTROY = fn end, Remove = function() end },
           ActivePlayerTurnStart = { Add = function(fn) TURN_START = fn end, Remove = function() end },
           ActivePlayerTurnEnd = { Add = function(fn) TURN_END = fn end, Remove = function() end } }
H.check_eliminations = function() end
H.install_hooks()
"""

BARB_TEXT = ("A Worker was captured by the Barbarians! They will take it to their nearest Encampment. "
             "If you wish to recover your unit you will have to track it down!")


class CaptureNoticeLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_destroy_hook_keeps_type_and_plot_while_the_unit_is_readable(self):
        self.run_lua("""
        DESTROY(0, 4321)
        local e = H.events[#H.events]
        assert(e.kind == 'unit_destroyed', e.kind)
        assert(e.data.unit == 4321 and e.data.unit_type == 'WORKER', tostring(e.data.unit_type))
        assert(e.data.x == 10 and e.data.y == 12)
        assert(e.audience == 0)
        """)

    def test_a_unit_already_gone_is_named_from_the_roster(self):
        """Live 2026-09-24: Unit:Kill() fired no event synchronously; inside the hook GetUnitByID was nil."""
        self.run_lua("""
        Players[0].Units = function() return function(_, k) if k == nil then return WORKER end end end
        H.note_units(0)
        GONE = true
        DESTROY(0, 4321)
        local e = H.events[#H.events]
        assert(e.kind == 'unit_destroyed' and e.data.unit_type == 'WORKER' and e.data.x == 10 and e.data.y == 12, H.json(e.data))
        """)

    def test_turn_end_is_filed_for_the_seat_that_ended_not_the_next_one(self):
        """Hotseat: GetActivePlayer() already names the next seat when ActivePlayerTurnEnd fires."""
        self.run_lua("""
        Players[0].Units = function() return function(_, k) if k == nil then return WORKER end end end
        Players[1].Units = function() return function() return nil end end
        Game.GetActivePlayer = function() return 0 end
        TURN_START()
        Game.GetActivePlayer = function() return 1 end   -- the hand-off happened before the end event
        TURN_END()
        local e = H.events[#H.events]
        assert(e.kind == 'turn_end' and e.data.player == 0 and e.audience == 0, H.json(e))
        assert(H.hp_snaps[0] and H.hp_snaps[0].units[4321], 'seat 0 must be the one snapshotted')
        assert(H.hp_snaps[1] == nil, 'seat 1 has not ended a turn')
        """)

    def test_capture_notice_is_tied_to_the_unit_the_tile_the_captor_and_the_nearest_revealed_camp(self):
        self.run_lua(f"""
        DESTROY(0, 4321); GONE = true
        local d = {{ player = 0, text = {support_lua_str(BARB_TEXT)}, summary = 'A civilian was captured by Barbarians!' }}
        H.attach_capture(d, Players[0])
        assert(d.unit_id == 4321 and d.unit == 'WORKER', tostring(d.unit_id))
        assert(d.x == 10 and d.y == 12, tostring(d.x))
        assert(d.captor and d.captor.owner == 'Barbarians' and d.captor.unit == 'BRUTE' and d.captor.hp == 80, tostring(d.captor))
        assert(d.nearest_revealed_camp and d.nearest_revealed_camp.x == 13 and d.nearest_revealed_camp.distance == 3, tostring(d.nearest_revealed_camp))
        assert(d.hint:find('move_unit', 1, true) and d.hint:find('camp', 1, true), d.hint)
        assert(H.events[#H.events].data.captured == true, 'the row must be marked so a second capture links a different unit')
        """)

    def test_under_fog_the_captor_is_not_read(self):
        self.run_lua(f"""
        FOG = true
        DESTROY(0, 4321); GONE = true
        local d = {{ player = 0, text = {support_lua_str(BARB_TEXT)} }}
        H.attach_capture(d, Players[0])
        assert(d.unit_id == 4321 and d.x == 10, 'the last known tile is still ours to know')
        assert(d.captor == nil, 'a unit under fog was read')
        """)

    def test_a_capture_by_a_civ_links_too_and_names_no_camp(self):
        self.run_lua("""
        DESTROY(0, 4321); GONE = true
        local d = { player = 0, text = 'A Worker was captured by Alpha!' }
        H.attach_capture(d, Players[0])
        assert(d.unit_id == 4321)
        assert(d.nearest_revealed_camp == nil)
        assert(not d.hint:find('camp', 1, true), d.hint)
        """)

    def test_a_notice_naming_another_unit_type_does_not_borrow_the_row(self):
        self.run_lua("""
        DESTROY(0, 4321); GONE = true
        local d = { player = 0, text = 'A Settler was captured by the Barbarians!' }
        H.attach_capture(d, Players[0])
        assert(d.unit_id == nil, 'a Worker row must not be handed to a Settler notice')
        """)

    def test_a_still_living_unit_is_not_reported_captured(self):
        """SerialEventUnitDestroyed also fires on a model rebuild; the unit is still there then."""
        self.run_lua("""
        DESTROY(0, 4321)  -- GONE stays false: the Worker still answers GetUnitByID
        local d = { player = 0, text = 'A Worker was captured by the Barbarians!' }
        H.attach_capture(d, Players[0])
        assert(d.unit_id == nil)
        """)

    def test_hotseat_loss_of_another_seat_is_filed_for_that_seat(self):
        self.run_lua("""
        HOTSEAT = true
        Players[1].GetUnitByID = function(_, id) return unit(1, 77, 4, 20, 20, false) end
        DESTROY(1, 77)  -- active player is 0; the Settler belongs to seat 1
        local e = H.events[#H.events]
        assert(e.kind == 'unit_destroyed' and e.data.player == 1 and e.audience == 1, tostring(e.audience))
        assert(e.data.unit_type == 'SETTLER' and e.data.x == 20)
        """)

    def test_solo_loss_of_another_player_is_still_not_ours_to_see(self):
        self.run_lua("""
        HOTSEAT = false
        local before = #H.events
        DESTROY(1, 77)
        assert(#H.events == before, 'another civ losing a unit is not our event')
        """)


class LateCaptureLinkTests(unittest.TestCase):
    """Live S1 t267: the notice (seq 28) arrived BEFORE the delayed destroy event (seq 29), so attach_capture
    found no row and the Worker went out as an anonymous `unit_spent` at its turn-start plot. The destroy
    side now looks back for the bare notice, and a unit's roster plot follows its moves."""
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_a_notice_that_came_first_is_linked_from_the_destroy_side(self):
        self.run_lua(f"""
        H.record('notification', {{ player = 0, text = {support_lua_str(BARB_TEXT)}, summary = 'A civilian was captured by Barbarians!' }})
        local n = H.events[#H.events].data
        assert(n.unit_id == nil, 'nothing to link to yet')
        GONE = true
        Players[0].Units = function() return function() return nil end end
        H.roster = {{ [0] = {{ [4321] = {{ unit = 'WORKER', x = 10, y = 12 }} }} }}
        DESTROY(0, 4321)
        local d = H.events[#H.events].data
        assert(d.captured == true, 'the destroy row is marked as a capture: ' .. H.json(d))
        assert(n.unit_id == 4321 and n.unit == 'WORKER' and n.x == 10 and n.y == 12, H.json(n))
        assert(n.captor and n.captor.owner == 'Barbarians' and n.captor.unit == 'BRUTE', H.json(n.captor))
        assert(n.nearest_revealed_camp and n.nearest_revealed_camp.x == 13, H.json(n.nearest_revealed_camp))
        """)

    def test_a_notice_from_an_earlier_turn_or_another_unit_type_is_left_alone(self):
        self.run_lua(f"""
        H.record('notification', {{ player = 0, text = 'A Settler was captured by the Barbarians!' }})
        local n = H.events[#H.events].data
        GONE = true
        H.roster = {{ [0] = {{ [4321] = {{ unit = 'WORKER', x = 10, y = 12 }} }} }}
        DESTROY(0, 4321)
        assert(n.unit_id == nil, 'a Settler notice does not borrow a Worker')
        assert(H.events[#H.events].data.captured == nil)
        """)



class HpSnapshotPerSeatTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_the_other_seats_turn_start_does_not_discard_our_snapshot(self):
        self.run_lua("""
        Players[0].Units = function() return function(_, k) if k == nil then return WORKER end end end
        Players[1].Units = function() return function() return nil end end
        H.hp_snapshot(0)          -- seat 0 ends its turn
        H.hp_compare(1)           -- seat 1 starts: used to wipe the single slot
        GONE = true
        Game.GetActivePlayer = function() return 0 end
        H.hp_compare(0)           -- seat 0 starts again: the Worker is gone
        local e = H.events[#H.events]
        assert(e.kind == 'unit_lost' and e.data.unit_id == 4321 and e.data.unit == 'WORKER', tostring(e.kind))
        """)


def support_lua_str(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


class FakeGame(Game):
    def __init__(self, events):
        self.seat = 0
        self._events = events

    def q(self, lua, *a, **kw):
        if "H.take_events" in lua:
            return self._events
        if "local p = Players" in lua:
            return []          # none of the destroyed ids is still alive
        if "H.route_starts" in lua:
            return []
        return {}


class CaptureDigestTests(unittest.TestCase):
    def _events(self):
        note = {"id": 9, "player": 0, "text": BARB_TEXT, "summary": "A civilian was captured by Barbarians!",
                "unit_id": 4321, "unit": "WORKER", "x": 10, "y": 12,
                "captor": {"owner": "Barbarians", "unit": "BRUTE", "x": 10, "y": 12, "hp": 80},
                "nearest_revealed_camp": {"x": 13, "y": 12, "distance": 3}, "hint": "move_unit onto the captor"}
        return [
            {"seq": 1, "turn": 217, "audience": 0, "kind": "turn_end", "data": {"player": 0}},
            {"seq": 2, "turn": 217, "audience": 0, "kind": "unit_destroyed",
             "data": {"player": 0, "unit": 4321, "unit_type": "WORKER", "x": 10, "y": 12, "captured": True}},
            {"seq": 3, "turn": 217, "audience": 0, "kind": "notification", "data": note},
            {"seq": 4, "turn": 218, "audience": 0, "kind": "turn_start", "data": {"player": 0}},
            {"seq": 5, "turn": 218, "audience": 0, "kind": "unit_lost",
             "data": {"player": 0, "unit_id": 4321, "unit": "WORKER", "x": 10, "y": 12, "hp_before": 100}},
        ]

    def test_the_three_rows_become_one_capture(self):
        out = Game.events_since_last(FakeGame(self._events()))
        kinds = [e["kind"] for e in out]
        self.assertIn("unit_captured", kinds)
        self.assertNotIn("unit_destroyed", kinds)
        self.assertNotIn("unit_lost", kinds, "the hp-compare fallback is explained by the capture")
        cap = next(e for e in out if e["kind"] == "unit_captured")["data"]
        self.assertEqual(cap["summary"], "your WORKER at (10,12) was captured by the Barbarians")
        self.assertEqual(cap["captor"]["unit"], "BRUTE")
        self.assertEqual(cap["nearest_revealed_camp"]["x"], 13)
        self.assertIn("move_unit", cap["hint"])
        self.assertIn("notification", kinds, "the notice itself still reaches the caller")

    def test_an_unlinked_loss_stays_a_loss(self):
        events = self._events()
        events[2]["data"] = {"id": 9, "player": 0, "text": "Some other notice"}
        out = Game.events_since_last(FakeGame(events))
        kinds = [e["kind"] for e in out]
        self.assertIn("unit_destroyed", kinds)
        self.assertNotIn("unit_captured", kinds)


if __name__ == "__main__":
    unittest.main()
