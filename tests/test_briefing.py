"""The turn briefing (#30): one compact read of the seat's decisions, changes since its previous briefing,
board and visible threats.

Lua half: H.briefing_board against a mocked world (threat range, fog, war state, camps, the leader trait, the
event log read with its own cursor and never another seat's rows). Python half: the pure composer in
harness/briefing.py, Game.briefing's baseline handling on a scripted game (fresh session, context recovery,
reload, production completion, seat isolation), and the MCP tool / finish_turn wiring.
"""
import asyncio
import contextlib
import json
import os
import tempfile
import unittest
from unittest import mock

import test_mcp_safety as support
from harness import briefing as B
from harness.game import Game


# Seat 0 (team 0) owns the city Venice at (10,10) and a warrior at (20,20). Seat 1 is the other human (peace),
# player 2 an AI at war, 63 the barbarians. Every plot is visible unless in World.fogged.
WORLD = r"""
local function iter(rows)
  local i = 0
  return function() i = i + 1; return rows[i] end
end
Locale = { ConvertTextKey = function(k) return "text:" .. k end }
GameInfo = GameInfo or {}
GameInfo.Units = { [1] = { Type = "UNIT_WARRIOR" }, [2] = { Type = "UNIT_BRUTE" }, [3] = { Type = "UNIT_WORKER" },
                   [4] = { Type = "UNIT_ARCHER" } }
GameInfo.Leaders = { [5] = { Type = "LEADER_ENRICO_DANDOLO" } }
GameInfo.Traits = { TRAIT_SUPER_CITY_STATE = { Type = "TRAIT_SUPER_CITY_STATE", ShortDescription = "TXT_KEY_TRAIT_SUPER_CITY_STATE_SHORT",
                                               Description = "TXT_KEY_TRAIT_SUPER_CITY_STATE" } }
GameInfo.Leader_Traits = setmetatable({}, { __call = function(_, f)
  local rows = {}
  if f.LeaderType == "LEADER_ENRICO_DANDOLO" then rows[1] = { LeaderType = f.LeaderType, TraitType = "TRAIT_SUPER_CITY_STATE" } end
  return iter(rows)
end })
GameInfoTypes = { IMPROVEMENT_BARBARIAN_CAMP = 3 }
World = { fogged = {}, camp = nil, at_war = { [2] = true } }
local function key(x, y) return x .. "," .. y end

All = {}
function make_unit(o)
  local u = {}
  u.GetID = function() return o.id end
  u.GetUnitType = function() return o.type end
  u.GetX = function() return o.x end
  u.GetY = function() return o.y end
  u.GetOwner = function() return o.owner end
  u.GetPlot = function() return Map.GetPlot(o.x, o.y) end
  u.IsCombatUnit = function() return o.combat ~= false end
  u.IsDelayedDeath = function() return false end
  u.IsInvisible = function() return false end
  u.GetCurrHitPoints = function() return o.hp or 100 end
  u.GetBaseCombatStrength = function() return o.strength or 8 end
  u.GetRangedCombatStrength = function() return o.ranged or 0 end
  All[#All + 1] = u
  return u
end
local function units_of(owner) local out = {}; for _, u in ipairs(All) do if u.GetOwner() == owner then out[#out + 1] = u end end; return out end

Map = Map or {}
function Map.GetPlot(x, y)
  local pl = {}
  pl.GetX = function() return x end
  pl.GetY = function() return y end
  pl.IsVisible = function() return not World.fogged[key(x, y)] end
  pl.IsRevealed = function() return true end
  pl.GetRevealedImprovementType = function() return (World.camp and World.camp.x == x and World.camp.y == y) and 3 or -1 end
  return pl
end
Map.PlotDistance = function(x1, y1, x2, y2) return math.max(math.abs(x1 - x2), math.abs(y1 - y2)) end
Map.PlotXYWithRangeCheck = function(x, y, dx, dy, r)
  if math.max(math.abs(dx), math.abs(dy)) > r then return nil end
  return Map.GetPlot(x + dx, y + dy)
end

local city = { GetID = function() return 8192 end, GetName = function() return "Venice" end,
               GetX = function() return 10 end, GetY = function() return 10 end }
local function player(pid, team, o)
  local p = { GetTeam = function() return team end, IsAlive = function() return true end,
              IsBarbarian = function() return pid == 63 end,
              Units = function() return iter(units_of(pid)) end,
              GetCivilizationShortDescription = function() return o and o.civ or "?" end }
  p.Cities = function() return iter(pid == 0 and { city } or {}) end
  p.GetLeaderType = function() return 5 end
  return p
end
Players = { [0] = player(0, 0), [1] = player(1, 1, { civ = "Mongolia" }), [2] = player(2, 2, { civ = "Russia" }),
            [63] = player(63, 63) }
Teams = { [0] = { IsAtWar = function(_, t) return World.at_war[t] == true end, IsHasMet = function() return true end } }

make_unit{ id = 1, type = 1, x = 20, y = 20, owner = 0 }                    -- my warrior
make_unit{ id = 50, type = 1, x = 11, y = 10, owner = 1 }                   -- the other human, beside Venice, at peace
make_unit{ id = 60, type = 4, x = 13, y = 10, owner = 2, ranged = 7 }       -- Russian archer 3 from Venice
make_unit{ id = 61, type = 1, x = 17, y = 17, owner = 2 }                   -- 7 from Venice, 3 from my warrior: not a threat
make_unit{ id = 62, type = 1, x = 9, y = 10, owner = 2 }                    -- beside Venice but fogged
make_unit{ id = 63, type = 3, x = 10, y = 11, owner = 2, combat = false }   -- a Russian worker beside Venice
make_unit{ id = 70, type = 2, x = 21, y = 21, owner = 63, hp = 55 }         -- a brute beside my warrior
World.fogged["9,10"] = true

H.event_seq = 6
H.events = {
  { seq = 1, turn = 40, audience = 0, kind = "combat", data = { narration = "old fight" } },
  { seq = 2, turn = 41, audience = 0, kind = "turn_end", data = { player = 0 } },
  { seq = 3, turn = 41, audience = 1, kind = "notification", data = { summary = "seat 1 private", player = 1 } },
  { seq = 4, turn = 41, audience = 0, kind = "notification", data = { summary = "Venice has completed Worker", player = 0 } },
  { seq = 5, turn = 42, audience = 0, kind = "turn_start", data = { player = 0 } },
  { seq = 6, turn = 42, audience = 1, kind = "turn_end", data = { player = 1 } },
}
"""


class BoardLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_threats_are_visible_hostile_combat_units_near_a_city_or_unit(self):
        self.run_lua(r"""
local b = H.briefing_board(0, nil)
assert(b.events == nil, "no cursor, no events")
assert(b.event_seq == 6, H.json(b))
local ids = {}
for _, t in ipairs(b.threats) do ids[t.id] = t end
assert(ids[60] and ids[70], "the archer near Venice and the brute beside my warrior: " .. H.json(b.threats))
assert(not ids[50], "a unit of a player at peace is not a threat (the other human seat)")
assert(not ids[61], "seven plots from the city and three from the unit is out of range")
assert(not ids[62], "a unit on a fogged plot is not read")
assert(not ids[63], "a civilian is not a threat")
local a = ids[60]
assert(a.owner == "Russia" and a.unit == "ARCHER" and a.ranged_strength == 7 and a.x == 13 and a.y == 10, H.json(a))
assert(a.near_city.id == 8192 and a.near_city.name == "Venice" and a.near_city.distance == 3, H.json(a))
local br = ids[70]
assert(br.owner == "Barbarians" and br.hp == 55 and br.near_unit.id == 1 and br.near_unit.distance == 1, H.json(br))
""")

    def test_a_peace_turns_into_a_threat_only_at_war(self):
        self.run_lua(r"""
World.at_war[1] = true
local b = H.briefing_board(0, nil)
local found = false
for _, t in ipairs(b.threats) do if t.id == 50 then found = true; assert(t.owner == "Mongolia") end end
assert(found, "at war, the same unit beside Venice is a threat")
""")

    def test_events_are_read_with_their_own_cursor_and_only_for_the_seat(self):
        self.run_lua(r"""
local b = H.briefing_board(0, 3)
assert(#b.events == 2 and b.events[1].seq == 4 and b.events[2].seq == 5, H.json(b.events))
assert(b.since_seq == 3)
-- the digest cursor did not move: take_events still returns everything
local t = H.take_events(0)
assert(#t == 4, "briefing_board never consumes the digest's events: " .. H.json(t))
-- -1: after this seat's last turn_end (seq 2), never seat 1's (seq 6) and never seat 1's rows
b = H.briefing_board(0, -1)
assert(b.since_seq == 2, H.json(b.since_seq))
for _, e in ipairs(b.events) do assert(e.audience == 0, "another seat's event: " .. H.json(e)) end
assert(#b.events == 2, H.json(b.events))
""")

    def test_camps_near_a_city_and_the_leader_trait(self):
        self.run_lua(r"""
World.camp = { x = 13, y = 13 }
local b = H.briefing_board(0, nil)
assert(#b.camps == 1 and b.camps[1].x == 13 and b.camps[1].near_city.distance == 3 and b.camps[1].visible == true, H.json(b.camps))
World.camp = { x = 15, y = 10 }
b = H.briefing_board(0, nil)
assert(#b.camps == 0, "five plots out is beyond the ring")
assert(b.traits and #b.traits == 1 and b.traits[1].trait == "TRAIT_SUPER_CITY_STATE", H.json(b.traits))
assert(b.traits[1].text == "text:TXT_KEY_TRAIT_SUPER_CITY_STATE", H.json(b.traits))
""")


def status(turn=42, todo=None, **extra):
    ts = {"turn": turn, "my_turn": True, "active_player": 0, "processing": False, "paused": False,
          "blocking_name": "NO_ENDTURN_BLOCKING_TYPE", "pending_popups": [], "alive": True, "hotseat": True,
          "todo": todo if todo is not None else {"units": [], "cities": [], "promotions": [], "research_unset": False},
          "alerts": []}
    ts.update(extra)
    return ts


SUMMARY = {"gold": 189, "gold_per_turn": -1, "science": 8, "culture_per_turn": 6, "faith": 0, "happiness": 8,
           "num_cities": 1, "num_units": 2, "score": 89, "research": "OPTICS", "research_turns_left": 4,
           "era": "ANCIENT", "idle_trade_units": [], "idle_spies": []}
CITY = {"id": 8192, "name": "Venice", "pop": 5, "production": "Worker", "production_turns": 2, "growth": "growing",
        "growth_turns": 4, "hp": 200, "max_hp": 200, "needs_production": False}


class ComposerTests(unittest.TestCase):
    def test_baseline_states(self):
        self.assertFalse(B.baseline_state(None, 42, 10)["comparable"])
        r = B.baseline_state({"turn": 50, "event_seq": 3}, 42, 10)
        self.assertFalse(r["comparable"])
        self.assertIn("save was loaded", r["reason"])
        r = B.baseline_state({"turn": 41, "event_seq": 3}, 42, 10)
        self.assertEqual((r["comparable"], r["turn"], r["turns_ago"]), (True, 41, 1))
        self.assertTrue(B.baseline_state({"turn": 42, "event_seq": 30}, 42, 10)["events_restarted"])

    def test_production_completion_and_unit_changes(self):
        prev = B.snapshot(41, SUMMARY, [CITY], [{"id": 1, "type": "WARRIOR"}, {"id": 2, "type": "SETTLER"}], 5)
        now = B.snapshot(42, {**SUMMARY, "gold": 200}, [{**CITY, "production": "Monument", "pop": 6},
                                                         {"id": 9, "name": "Treviso"}],
                         [{"id": 1, "type": "WARRIOR"}, {"id": 3, "type": "WORKER"}], 9)
        c = B.compare(prev, now)
        self.assertEqual(c["empire"], {"gold": {"was": 189, "now": 200}})
        self.assertEqual(c["cities"]["production"], [{"id": 8192, "name": "Venice", "was": "Worker", "now": "Monument"}])
        self.assertEqual(c["cities"]["pop"][0]["pop"], {"was": 5, "now": 6})
        self.assertEqual(c["cities"]["new"], [{"id": 9, "name": "Treviso"}])
        self.assertEqual(c["units"]["new"], [{"id": 3, "type": "WORKER"}])
        self.assertEqual(c["units"]["gone"], [{"id": 2, "type": "SETTLER"}])

    def test_a_trade_unit_gone_is_named_as_a_route_not_a_loss(self):
        # Codex c41 (2026-09-27): a caravan that left on its route showed under units.gone with the generic
        # note, and the report called it an ambiguous unit loss.
        prev = B.snapshot(41, SUMMARY, [CITY], [{"id": 1, "type": "WARRIOR"}, {"id": 2, "type": "CARAVAN"}], 5)
        now = B.snapshot(42, SUMMARY, [CITY], [{"id": 1, "type": "WARRIOR"}, {"id": 7, "type": "CARAVAN"}], 9)
        c = B.compare(prev, now)
        gone = c["units"]["gone"]
        self.assertEqual((gone[0]["id"], gone[0]["type"]), (2, "CARAVAN"))
        self.assertIn("trade route started or ended", gone[0]["likely"])
        self.assertIn("new id", gone[0]["likely"])
        prev = B.snapshot(41, SUMMARY, [CITY], [{"id": 2, "type": "SETTLER"}], 5)
        now = B.snapshot(42, SUMMARY, [CITY], [], 9)
        self.assertNotIn("likely", B.compare(prev, now)["units"]["gone"][0])

    def test_an_announcement_popup_is_not_a_decision(self):
        """Live 2026-09-27 (Grok, t53): BUTTONPOPUP_TECH_AWARD sat in decisions with tool generic_popup, and
        generic_popup({}) then said no confirmation is open: the harness sweeps announcement screens itself.
        A popup with a real choice (city captured) stays."""
        ts = {"turn": 42, "todo": {}, "blocking_name": "NO_ENDTURN_BLOCKING_TYPE",
              "pending_popups": [{"name": "BUTTONPOPUP_TECH_AWARD", "type": 68},
                                 {"name": "BUTTONPOPUP_WONDER_COMPLETED"},
                                 {"name": "BUTTONPOPUP_CITY_CAPTURED", "data1": 3}]}
        rows = [r for r in B.decisions(ts, []) if r["kind"] == "popup"]
        self.assertEqual([r["detail"]["name"] for r in rows], ["BUTTONPOPUP_CITY_CAPTURED"])

    def test_decisions_are_never_capped_and_name_their_tool(self):
        todo = {"units": [{"id": i, "type": "WARRIOR", "x": 1, "y": 1, "moves": 2} for i in range(12)],
                "cities": [{"id": 8192, "name": "Venice"}], "promotions": [7], "research_unset": True,
                "incoming_deal": {"from": 1, "items": 2}}
        ts = status(todo=todo, blocking_name="ENDTURN_BLOCKING_POLICY", blocking_hint="choose a policy")
        out, _ = B.build(ts, SUMMARY, [CITY], [], {}, {"comparable": False}, None, [], limit=0, include_rules=False)
        kinds = [d["kind"] for d in out["decisions"]]
        self.assertEqual(kinds.count("unit_orders"), 12)
        self.assertEqual(out["decisions_total"], 17)
        for k in ("promotion", "city_production", "research", "incoming_deal", "blocker"):
            self.assertIn(k, kinds)
        self.assertTrue(all(out["tools"].get(d["kind"]) or d["kind"] == "blocker" for d in out["decisions"]),
                        "every decision kind names its tool, once")
        self.assertFalse(any("tool" in d for d in out["decisions"]))
        # a blocker the rows already cover is not repeated
        ts = status(todo=todo, blocking_name="ENDTURN_BLOCKING_UNITS")
        out, _ = B.build(ts, SUMMARY, [CITY], [], {}, {"comparable": False}, None, [], limit=8, include_rules=False)
        self.assertNotIn("blocker", [d["kind"] for d in out["decisions"]])

    def test_stacked_units_are_a_decision_only_when_the_engine_blocks_on_them(self):
        tiles = [{"x": 49, "y": 15, "class": "civilian", "units": [{"id": 1, "type": "WORKER", "moves": 2}]}]
        todo = {"units": [], "cities": [], "promotions": [], "research_unset": False, "stacked": tiles}
        out, _ = B.build(status(todo=todo), SUMMARY, [CITY], [], {}, {"comparable": False}, None, None, 8, False)
        self.assertEqual(out["decisions"], [])
        self.assertEqual(out["warnings"][0]["kind"], "stacked")
        out, _ = B.build(status(todo=todo, blocking_name="ENDTURN_BLOCKING_STACKED_UNITS"), SUMMARY, [CITY], [], {},
                         {"comparable": False}, None, None, 8, False)
        self.assertEqual([d["kind"] for d in out["decisions"]], ["stacked"])
        self.assertNotIn("warnings", out)

    def test_a_notification_restating_its_headline_is_one_line(self):
        s = B.summarize_events([{"seq": 6, "turn": 267, "kind": "notification",
                                 "data": {"summary": "ENACT: Historical Landmarks Passes",
                                          "text": "ENACT: Historical Landmarks Passes. Its effects are..."}},
                                {"seq": 7, "turn": 267, "kind": "notification",
                                 "data": {"summary": "No longer Ally of Sidon!", "text": "Influence over Sidon has decreased"}}], 8)
        self.assertEqual(s["items"][0]["text"], "ENACT: Historical Landmarks Passes. Its effects are...")
        self.assertEqual(s["items"][1]["text"], "No longer Ally of Sidon!: Influence over Sidon has decreased")

    def test_lists_are_capped_with_counts_and_a_drill_down(self):
        events = [{"seq": i, "turn": 42, "kind": "combat", "data": {"narration": f"fight {i}"}} for i in range(20)]
        events.append({"seq": 99, "turn": 42, "kind": "turn_start", "data": {}})
        s = B.summarize_events(events, 5)
        self.assertEqual(s["total"], 21)
        self.assertEqual(s["by_kind"], {"combat": 20, "turn_start": 1})
        self.assertEqual(len(s["items"]), 5)
        self.assertEqual(s["omitted"], 15)
        self.assertEqual(s["items"][-1]["text"], "fight 19", "the newest are kept")
        self.assertIn("since='turn'", s["more"])
        board = {"threats": [{"id": i, "near_city": {"name": "Venice", "distance": 4}} for i in range(10)]}
        out, _ = B.build(status(), SUMMARY, [CITY], [], board, {"comparable": False}, None, None, 3, False)
        self.assertEqual(out["threats"]["total"], 10)
        self.assertEqual(len(out["threats"]["rows"]), 3)
        self.assertEqual(out["threats"]["omitted"], 7)
        self.assertTrue(out["threats"]["more"])

    def test_a_visible_threat_carries_a_labelled_assessment(self):
        board = {"threats": [{"id": 60, "near_city": {"id": 8192, "name": "Venice", "distance": 1}},
                             {"id": 70, "near_unit": {"id": 1, "type": "WARRIOR", "distance": 1}},
                             {"id": 71, "near_city": {"id": 8192, "name": "Venice", "distance": 4}}]}
        out, _ = B.build(status(), SUMMARY, [CITY], [], board, {"comparable": False}, None, None, 8, False)
        rows = out["threats"]["rows"]
        self.assertEqual(rows[0]["assessment"], "adjacent to Venice")
        self.assertEqual(rows[1]["assessment"], "adjacent to my WARRIOR 1")
        self.assertEqual(rows[2]["assessment"], "in sight, not adjacent")
        self.assertIn("distances only", out["threats"]["basis"])

    def test_compact_threat_rows_and_seen_marks(self):
        brute = {"id": 60, "owner": "Barbarians", "player_id": 63, "unit": "BARBARIAN_WARRIOR", "x": 10, "y": 11,
                 "hp": 70, "strength": 8, "near_city": {"id": 8192, "name": "Venice", "distance": 3},
                 "near_unit": {"id": 1, "type": "WARRIOR", "distance": 1}}
        horse = {**brute, "id": 61, "owner": "Mongolia", "player_id": 1, "unit": "KESHIK", "x": 20, "y": 21,
                 "near_city": {"id": 8192, "name": "Venice", "distance": 4}, "near_unit": None}
        board = {"threats": [horse, brute]}
        out, snap = B.build(status(), SUMMARY, [CITY], [], board, {"comparable": False}, None, None, 8, False)
        rows = out["threats"]["rows"]
        self.assertEqual(rows[0], {"id": 60, "unit": "BARBARIAN_WARRIOR", "hp": 70, "x": 10, "y": 11,
                                   "near": {"unit": 1, "unit_d": 1, "city": "Venice", "city_d": 3},
                                   "assessment": "adjacent to my WARRIOR 1"}, "nearest first, no owner for a brute")
        self.assertEqual(rows[1]["owner"], "Mongolia")
        self.assertNotIn("strength", rows[1])
        self.assertNotIn("player_id", rows[1])
        self.assertEqual(snap["threats"], {"60": [10, 11], "61": [20, 21]}, "what was listed, for the next briefing")
        # Next turn: the brute sits still, the keshik moved; the snapshot says which were shown already.
        board2 = {"threats": [brute, {**horse, "x": 19, "y": 21, "near_unit": {"id": 1, "type": "WARRIOR", "distance": 2}}]}
        out2, snap2 = B.build(status(), SUMMARY, [CITY], [], board2, {"comparable": True}, snap, None, 8, False)
        rows = out2["threats"]["rows"]
        self.assertEqual(rows[0], {"id": 60, "unit": "BARBARIAN_WARRIOR", "hp": 70, "x": 10, "y": 11, "seen": True, "d": 1})
        self.assertEqual(rows[1]["seen"], True)
        self.assertEqual(rows[1]["moved_from"], [20, 21])
        self.assertEqual(rows[1]["near"], {"unit": 1, "unit_d": 2, "city": "Venice", "city_d": 4}, "moved: whereabouts again")
        self.assertIn("seen", out2["threats"]["basis"])
        # Without a comparable baseline nothing is seen; detail="full" keeps every field and still marks seen.
        out3, _ = B.build(status(), SUMMARY, [CITY], [], board2, {"comparable": False}, snap, None, 8, False)
        self.assertNotIn("seen", out3["threats"]["rows"][0])
        out4, _ = B.build(status(), SUMMARY, [CITY], [], board2, {"comparable": True}, snap, None, 8, False, detail="full")
        full = out4["threats"]["rows"][0]
        self.assertEqual((full["strength"], full["player_id"], full["seen"], full["near_unit"]["id"]), (8, 63, True, 1))
        self.assertEqual(full["assessment"], "adjacent to my WARRIOR 1")
        # Only listed rows are remembered: a capped list does not mark the rest seen next time.
        many = {"threats": [{**brute, "id": 100 + i, "near_unit": None,
                             "near_city": {"id": 8192, "name": "Venice", "distance": 4}} for i in range(6)]}
        _, snap5 = B.build(status(), SUMMARY, [CITY], [], many, {"comparable": False}, None, None, 2, False)
        self.assertEqual(len(snap5["threats"]), 2)

    def test_notable_cities_only(self):
        rows = B.city_rows([CITY, {**CITY, "id": 2, "production_turns": 1},
                            {**CITY, "id": 3, "production": None, "needs_production": True},
                            {**CITY, "id": 4, "growth": "starving"}, {**CITY, "id": 5, "hp": 150}])
        self.assertEqual([(r["id"], r["why"]) for r in rows],
                         [(2, ["completes_next_turn"]), (3, ["no_production"]), (4, ["starving"]), (5, ["damaged"])])


class ScriptedBoardGame(Game):
    """Game.briefing's reads, scripted: q() answers H.briefing_board and records the cursor it was given."""

    def __init__(self, seat=0, event_seq=6):
        self.seat = seat
        self.event_seq = event_seq
        self.cursors = []
        self.ts = status()
        self.city = dict(CITY)
        self.unit_rows = [{"id": 1, "type": "WARRIOR", "hp": 100, "max_hp": 100}]
        self._game_key = "test-game"
        self.long_markup = False
        self.threats = []

    def q(self, code, *a, **k):
        assert code.startswith(f"return H.briefing_board({self.seat}, "), code
        cursor = int(code.split(",")[1].strip(" )"))
        self.cursors.append(cursor)
        events = [{"seq": self.event_seq, "turn": self.ts["turn"], "audience": self.seat, "kind": "notification",
                   "data": {"summary": "Venice has completed Worker"}}] if cursor < self.event_seq else []
        if self.long_markup and events:
            events[0]["data"]["summary"] = "[COLOR_POSITIVE_TEXT]" + "x" * 150 + "[ENDCOLOR] [ICON_GOLD] Gold"
        return {"event_seq": self.event_seq, "since_seq": cursor, "events": events, "threats": list(self.threats),
                "camps": [],
                "traits": [{"trait": "TRAIT_SUPER_CITY_STATE", "text": "Cannot found cities"}]}

    def turn_state(self, pid=None):
        return dict(self.ts)

    def summary(self, pid=None):
        return dict(SUMMARY)

    def cities(self, pid=None):
        return [dict(self.city)]

    def units(self, pid=None):
        return [dict(u) for u in self.unit_rows]


class GameBriefingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"CIV5_NOTES_DIR": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_fresh_session_then_changes_since_the_previous_briefing(self):
        g = ScriptedBoardGame()
        first = g.briefing()
        self.assertTrue(first["ok"])
        self.assertFalse(first["baseline"]["comparable"])
        self.assertIn("no earlier briefing", first["baseline"]["reason"])
        self.assertEqual(first["baseline"]["events_since"], "this seat's last turn end")
        self.assertEqual(g.cursors, [-1])
        self.assertEqual(first["civ_rules"][0]["trait"], "TRAIT_SUPER_CITY_STATE", "no baseline: the civ's rules come along")
        self.assertEqual(first["changes"]["events"]["items"][0]["text"], "Venice has completed Worker")
        # next turn: the worker is out, a Monument went in, one new event
        g.ts = status(turn=43)
        g.city["production"] = "Monument"
        g.unit_rows.append({"id": 2, "type": "WORKER", "hp": 100, "max_hp": 100})
        g.event_seq = 9
        second = g.briefing()
        self.assertEqual(g.cursors, [-1, 6], "the second read continues from the first briefing's log head")
        self.assertEqual(second["baseline"], {"comparable": True, "turn": 42, "turns_ago": 1, "events_since": "previous briefing"})
        self.assertNotIn("civ_rules", second)
        self.assertEqual(second["changes"]["cities"]["production"][0]["was"], "Worker")
        self.assertEqual(second["changes"]["units"]["new"], [{"id": 2, "type": "WORKER"}])
        # nothing new: the same turn read again has no events and no changes
        third = g.briefing()
        self.assertEqual(third["changes"]["events"]["total"], 0)
        self.assertNotIn("cities", third["changes"])

    def test_context_recovery_in_a_new_process_compares_against_the_stored_baseline(self):
        ScriptedBoardGame().briefing()
        g = ScriptedBoardGame()   # a new server process for the same game and seat
        g.ts = status(turn=43)
        r = g.briefing()
        self.assertTrue(r["baseline"]["comparable"])
        self.assertEqual(g.cursors, [6])
        g2 = ScriptedBoardGame()
        g2.ts = status(turn=43)
        r = g2.briefing(since="turn")
        self.assertEqual(g2.cursors, [-1], "since='turn' re-reads the whole turn")
        self.assertIn("civ_rules", r)

    def test_a_reload_to_an_earlier_turn_has_no_comparable_baseline(self):
        g = ScriptedBoardGame()
        g.ts = status(turn=50)
        g.briefing()
        g.ts = status(turn=42)
        g.city["production"] = "Monument"
        r = g.briefing()
        self.assertFalse(r["baseline"]["comparable"])
        self.assertIn("turn 50", r["baseline"]["reason"])
        self.assertNotIn("cities", r.get("changes", {}), "nothing is diffed against a later turn")
        self.assertEqual(g.cursors[-1], -1)

    def test_a_restarted_event_log_is_reread_from_the_turn(self):
        g = ScriptedBoardGame(event_seq=40)
        g.briefing()
        g.event_seq = 3   # same turn, fresh runtime log after a load
        r = g.briefing()
        self.assertEqual(g.cursors, [-1, 40, -1])
        self.assertTrue(r["baseline"]["events_restarted"])
        self.assertEqual(r["baseline"]["events_since"], "this seat's last turn end")

    def test_seats_keep_separate_baselines_and_read_only_their_own_board(self):
        a = ScriptedBoardGame(seat=0)
        a.briefing()
        b = ScriptedBoardGame(seat=1)
        r = b.briefing()
        self.assertFalse(r["baseline"]["comparable"], "seat 0's briefing is not seat 1's baseline")
        self.assertEqual(b.cursors, [-1])
        self.assertNotEqual(a.notebook().path, b.notebook().path)

    def test_markup_is_stripped_before_a_line_is_shortened(self):
        g = ScriptedBoardGame()
        g.long_markup = True
        text = g.briefing()["changes"]["events"]["items"][0]["text"]
        self.assertNotIn("[", text, "a cut tag would survive the strip: " + text)

    def test_bad_since_is_refused(self):
        self.assertFalse(ScriptedBoardGame().briefing(since="yesterday")["ok"])
        self.assertFalse(ScriptedBoardGame().briefing(detail="huge")["ok"])
        self.assertFalse(ScriptedBoardGame().briefing(notes="some")["ok"])

    def test_notes_ride_once_and_since_turn_brings_them_all(self):
        g = ScriptedBoardGame()
        g.notebook().remember("Tradition first", turn=40, tag="plan")
        g.notebook().remember("brute NE", turn=41, tag="threat")
        first = g.briefing()
        self.assertEqual([n["text"] for n in first["notes"]], ["Tradition first", "brute NE"])
        self.assertNotIn("notes_unshown", first)
        second = g.briefing()
        self.assertNotIn("notes", second, "nothing new since the last hand-off")
        self.assertEqual(second["notes_unshown"]["count"], 2)
        g.notebook().remember("Library in 2", turn=42)
        third = g.briefing()
        self.assertEqual([n["text"] for n in third["notes"]], ["Library in 2"])
        self.assertEqual(third["notes_unshown"]["count"], 2)
        recovery = g.briefing(since="turn")
        self.assertEqual(len(recovery["notes"]), 3, "the recovery read carries every note (notes=auto -> all)")
        self.assertEqual(len(g.briefing(notes="all")["notes"]), 3)
        self.assertNotIn("notes", g.briefing(notes="new"))

    def test_a_threat_listed_last_time_comes_back_marked_seen(self):
        g = ScriptedBoardGame()
        g.threats = [{"id": 60, "owner": "Barbarians", "player_id": 63, "unit": "BARBARIAN_WARRIOR", "x": 10, "y": 11,
                      "hp": 70, "strength": 8, "near_unit": {"id": 1, "type": "WARRIOR", "distance": 2}}]
        first = g.briefing()
        self.assertEqual(first["threats"]["rows"][0]["near"], {"unit": 1, "unit_d": 2})
        self.assertNotIn("seen", first["threats"]["rows"][0])
        second = g.briefing()
        self.assertEqual(second["threats"]["rows"][0], {"id": 60, "unit": "BARBARIAN_WARRIOR", "hp": 70, "x": 10, "y": 11,
                                                          "seen": True, "d": 2})
        full = g.briefing(detail="full")["threats"]["rows"][0]
        self.assertEqual((full["seen"], full["strength"], full["near_unit"]["distance"]), (True, 8, 2))
        g.threats = []
        gone = g.briefing()
        self.assertEqual(gone["threats"]["total"], 0)
        g.threats = [{"id": 60, "unit": "BARBARIAN_WARRIOR", "x": 10, "y": 11, "hp": 70}]
        self.assertNotIn("seen", g.briefing()["threats"]["rows"][0], "out of sight for a briefing: listed in full again")


class McpBriefingTests(unittest.TestCase):
    def setUp(self):
        from harness import mcp_server
        self.m = mcp_server
        self._saved = mcp_server._game
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"CIV5_NOTES_DIR": self.tmp.name, "CIV5_SEAT": "0"})
        patcher.start()
        self.addCleanup(patcher.stop)
        g = ScriptedBoardGame()
        g.has_state = lambda name: True
        g.expiring_city_states = lambda: []
        g.discussion_pending = lambda: False
        g.lock = contextlib.nullcontext
        g.claim = None
        self.g = g
        mcp_server._game = g

    def tearDown(self):
        self.m._game = self._saved

    def _call(self, tool, args):
        result = asyncio.run(self.m.mcp.call_tool(tool, args))
        text = result[0].text if isinstance(result, (list, tuple)) else result.content[0].text
        return json.loads(text)

    def test_the_tool_answers_with_seat_gate_and_notes(self):
        self.g.notebook().remember("keep two archers in Venice", turn=41, tag="plan")
        r = self._call("briefing", {})
        self.assertTrue(r["ok"])
        self.assertEqual((r["seat"], r["gate"], r["turn"]), (0, None, 42))
        self.assertEqual(r["notes"][0]["text"], "keep two archers in Venice")

    def test_another_seats_turn_is_refused_before_the_board_is_read(self):
        self.g.ts = status(active_player=1, my_turn=False)
        r = self._call("briefing", {})
        self.assertFalse(r["ok"])
        self.assertEqual(self.g.cursors, [], "nothing of the board was read")

    def test_a_gate_withholds_the_board(self):
        self.g.ts = status(leader_greeting_pending=True)
        r = self._call("briefing", {})
        self.assertIsNotNone(r["gate"])
        self.assertIn("withheld", r)
        self.assertNotIn("decisions", r)
        self.assertEqual(self.g.cursors, [])

    def test_finish_turn_briefing_replaces_status_and_digest(self):
        g = self.g
        digest = {"events": [{"seq": 6, "kind": "notification", "data": {"summary": "Venice has completed Worker"}}],
                  "notifications": []}
        g.finish_turn = lambda **k: {"ok": True, "ended": True, "turn": 43, "status": status(turn=43),
                                     "digest": digest, "turns_skipped": 0, "woke_because": ["turn_started"]}
        g.ts = status(turn=43)
        r = self._call("finish_turn", {"briefing": True})
        self.assertNotIn("status", r)
        self.assertNotIn("digest", r)
        self.assertEqual(r["briefing"]["turn"], 43)
        self.assertEqual(r["briefing"]["changes"]["events"]["total"], 1, "the digest's event is in the briefing too")
        r = self._call("finish_turn", {})
        self.assertIn("status", r)
        self.assertIn("digest", r)
        self.assertNotIn("briefing", r)

    def test_finish_turn_notes_ride_once_and_inside_the_briefing(self):
        g = self.g
        g.notebook().remember("hold the pass", turn=41)
        g.finish_turn = lambda **k: {"ok": True, "ended": True, "turn": 43, "status": status(turn=43), "digest": {}}
        r = self._call("finish_turn", {})
        self.assertEqual([n["text"] for n in r["notes"]], ["hold the pass"])
        r = self._call("finish_turn", {})
        self.assertNotIn("notes", r)
        self.assertEqual(r["notes_unshown"]["count"], 1)
        r = self._call("finish_turn", {"notes": "all"})
        self.assertEqual([n["text"] for n in r["notes"]], ["hold the pass"])
        self.assertFalse(self._call("finish_turn", {"notes": "some"})["ok"])
        g.notebook().remember("Library next", turn=43)
        r = self._call("finish_turn", {"briefing": True})
        self.assertNotIn("notes", r, "with a briefing the notes are inside it, once")
        self.assertEqual([n["text"] for n in r["briefing"]["notes"]], ["Library next"])
        self.assertEqual(r["briefing"]["notes_unshown"]["count"], 1)
        r = self._call("finish_turn", {"briefing": True, "notes": "all"})
        self.assertEqual(len(r["briefing"]["notes"]), 2)

    def test_finish_turn_with_a_briefing_keeps_only_what_each_order_did(self):
        row = {"id": 11, "unit": {"id": 16385, "type": "WARRIOR"}, "status": "paused", "step": 1, "of": 2,
               "now": "heal to 100%", "steps": ["heal to 100%", "hold (fortify)"], "state": "paused",
               "pause": {"kind": "hostile", "reason": "a hostile GALLEY is in sight", "hint": "decide with tactical_view"},
               "did": ["paused: a hostile GALLEY is in sight"]}
        self.g.finish_turn = lambda **k: {"ok": True, "ended": True, "turn": 43, "digest": {},
                                          "status": {**status(turn=43), "orders": {"open": 1, "paused": 1, "rows": [row]}}}
        r = self._call("finish_turn", {"briefing": True})
        self.assertEqual(r["orders"]["rows"], [{"id": 11, "unit": {"id": 16385, "type": "WARRIOR"}, "status": "paused",
                                                "did": ["paused: a hostile GALLEY is in sight"]}])
        self.assertEqual((r["orders"]["open"], r["orders"]["paused"], r["orders"]["state"]), (1, 1, "briefing.orders"))
        r = self._call("finish_turn", {})
        self.assertEqual(r["status"]["orders"]["rows"][0]["pause"]["kind"], "hostile", "without a briefing the rows are whole")

    def test_finish_turn_behind_a_gate_keeps_status(self):
        self.g.finish_turn = lambda **k: {"ok": True, "ended": True, "turn": 43, "discussion_pending": True,
                                          "status": status(turn=43, discussion_pending=True), "digest": {"events": []}}
        r = self._call("finish_turn", {"briefing": True})
        self.assertIn("status", r)
        self.assertNotIn("briefing", r)


if __name__ == "__main__":
    unittest.main()


class IdleTradeUnitRowTest(unittest.TestCase):
    def test_the_row_carries_the_runtime_unit_id_and_the_field_hint(self):
        from harness.briefing import opportunities
        rows = opportunities({"idle_trade_units": [{"unit_id": 335888, "type": "CARAVAN", "in_city": "Beshbalik"},
                                                   {"unit_id": 7, "type": "CARGO_SHIP", "in_city": False,
                                                    "hint": "walk it to a city first"}]}, {})
        self.assertEqual(rows[0]["id"], 335888)
        self.assertIn("unit_id=335888", rows[0]["tool"])
        self.assertNotIn("hint", rows[0])
        self.assertEqual(rows[1]["hint"], "walk it to a city first")
