"""Structured assignments on the notebook (#33).

Lua half: H.assignment_facts on the tactical-view test world (an 8 x 5 wrapping hex map whose fogged plots raise
on every live getter): my own units and cities read live, an upgrade found on a missing unit's last plot, a reused
id, fogged target plots answering with revealed values only, a city site's founding-range check, a foreign unit
only while in sight, hostiles within the asked radius, players and techs.
Python half: harness/assignments.py (normalizing, the read's spec, reconcile, the briefing section), the notebook
storage (replace, amend, close, prune, restart, per-seat files) and the Game / MCP layer over a scripted read.
"""
import asyncio
import contextlib
import json
import os
import tempfile
import unittest
from unittest import mock

import test_mcp_safety as support
import test_tactical_view as tv
from harness import assignments as A
from harness.game import Game
from harness.notes import Notebook

WORLD = tv.WORLD + r"""
Game = Game or {}
Game.GetGameTurn = function() return 50 end
GameInfo.Units[1].Class = 'UNITCLASS_WARRIOR'
GameInfo.Units[4].Class = 'UNITCLASS_WORKER'
GameInfo.Units[5] = { Type = 'UNIT_SWORDSMAN', Class = 'UNITCLASS_SWORDSMAN' }
for _, r in pairs({ GameInfo.Units[1], GameInfo.Units[2], GameInfo.Units[3], GameInfo.Units[4], GameInfo.Units[5] }) do
  GameInfo.Units[r.Type] = r
end
GameInfo.Unit_ClassUpgrades = function(f)
  local rows = (f.UnitType == 'UNIT_WARRIOR') and { { UnitType = 'UNIT_WARRIOR', UnitClassType = 'UNITCLASS_SWORDSMAN' } } or {}
  local i = 0
  return function() i = i + 1; return rows[i] end
end
GameInfo.Improvements = { [0] = { Type = 'IMPROVEMENT_FARM' } }
GameDefines.MIN_CITY_RANGE = 2
GameInfoTypes.TECH_OPTICS = 7; GameInfoTypes.TECH_BRONZE_WORKING = 8; GameInfoTypes.BUILDING_WALLS = 3
Teams[0].IsHasTech = function(_, t) return t == 7 end
Teams[0].IsAtWar = function(_, t) return t == 63 end

ALL = { [0] = {}, [3] = {}, [63] = {} }
local base_unit = unit
function unit(id, owner, typ, x, y, o)
  o = o or {}
  local u = base_unit(id, owner, typ, x, y, o)
  u.GetGameTurnCreated = function() return o.created or 1 end
  ALL[owner][id] = u
  return u
end
for pid, pl in pairs(Players) do
  pl.GetUnitByID = function(_, id) return ALL[pid][id] end
  pl.Units = function() local t = {}; for _, u in pairs(ALL[pid]) do t[#t + 1] = u end
                        local i = 0; return function() i = i + 1; return t[i] end end
end
CITIES = {}
function city(id, owner, name, x, y, o)
  o = o or {}
  local c = { GetID = function() return id end, GetName = function() return name end,
              GetOwner = function() return owner end, GetX = function() return x end, GetY = function() return y end,
              GetPopulation = function() return o.pop or 3 end, GetGameTurnFounded = function() return o.founded or 1 end,
              GetMaxHitPoints = function() return 200 end, GetDamage = function() return o.damage or 0 end,
              IsRevealed = function() return o.revealed ~= false end,
              IsHasBuilding = function(_, b) return (o.buildings or {})[b] == true end }
  if owner == 0 then CITIES[id] = c end
  P[x .. ',' .. y].o.city = c
  return c
end
Players[0].GetCityByID = function(_, id) return CITIES[id] end
"""


class AssignmentFactsLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_my_units_live_a_missing_one_and_its_upgrade_on_the_last_plot(self):
        self.run_lua("""
        unit(1, 0, 1, 2, 2, { created = 5, hp = 60 })
        unit(9, 0, 5, 4, 2, { created = 50 })          -- a Swordsman where Warrior 2 was last seen
        unit(10, 0, 4, 4, 2, { created = 30 })         -- a Worker there too: not an upgrade
        local f = H.assignment_facts(0, { units = { { id = 1, type = 'WARRIOR', created = 5, x = 2, y = 2 },
                                                    { id = 2, type = 'WARRIOR', created = 3, x = 4, y = 2 } } })
        local a, b = f.units['1'], f.units['2']
        assert(f.turn == 50)
        assert(a.type == 'WARRIOR' and a.x == 2 and a.hp == 60 and a.created == 5 and not a.missing and not a.on_last_plot)
        assert(b.missing and #b.on_last_plot == 2, 'my units on its last plot')
        local up = {}; for _, c in ipairs(b.on_last_plot) do up[c.id] = c.upgrade_of end
        assert(up[9] == 'WARRIOR' and up[10] == nil, 'only the Swordsman is a Warrior upgrade')
        """)

    def test_a_reused_id_is_read_as_what_it_is_now(self):
        self.run_lua("""
        unit(1, 0, 4, 2, 2, { created = 40 })           -- id 1 is now a Worker
        local f = H.assignment_facts(0, { units = { { id = 1, type = 'WARRIOR', created = 5, x = 2, y = 2 } } })
        assert(f.units['1'].type == 'WORKER' and f.units['1'].created == 40, 'facts, not the stored fingerprint')
        """)

    def test_a_fogged_target_plot_answers_with_revealed_values_only(self):
        self.run_lua("""
        local p = P['5,3']
        p.o.fog = true; p.o.rowner = 3
        p.GetRevealedImprovementType = function() return 0 end
        p.GetPlotCity = function() error('live city read under fog') end
        local f = H.assignment_facts(0, { plots = { { x = 5, y = 3 } } })
        local r = f.plots['5,3']
        assert(r.vis == 'fogged' and r.owner == 3 and r.owner_name == 'Persia' and r.improvement == 'FARM')
        assert(r.units == nil and r.city == nil and r.pillaged == nil, 'nothing live under fog')
        P['6,3'].o.revealed = false
        f = H.assignment_facts(0, { plots = { { x = 6, y = 3 } } })
        assert(f.plots['6,3'].vis == 'unrevealed' and f.plots['6,3'].owner == nil)
        """)

    def test_a_visible_target_plot_shows_its_city_and_units(self):
        self.run_lua("""
        city(8192, 0, 'Venice', 3, 3)
        unit(1, 0, 1, 3, 3)
        local r = H.assignment_facts(0, { plots = { { x = 3, y = 3 } } }).plots['3,3']
        assert(r.vis == 'visible' and r.city.name == 'Venice' and r.city.owner == 0 and #r.units == 1)
        """)

    def test_a_site_reports_the_nearest_known_city_within_founding_range(self):
        self.run_lua("""
        P['3,2'].o.fog = true; P['3,2'].o.rowner = 3
        city(77, 3, 'Pasargadae', 3, 2)                 -- fogged, banner seen, next door
        city(78, 3, 'Hidden', 2, 4, { revealed = false }) -- visible plot: a city in sight is known
        P['1,2'].o.fog = true
        city(79, 3, 'Unseen', 1, 2, { revealed = false }) -- fogged and never seen: not reported
        local r = H.assignment_facts(0, { plots = { { x = 2, y = 2, site = true } } }).plots['2,2']
        assert(r.found_range == 2)
        local c = r.city_within_range
        assert(c and c.name == 'Pasargadae' and c.distance == 1 and c.owner == 3 and c.owner_name == 'Persia',
               'nearest known, never the unseen one at the same distance: ' .. tostring(c and c.name))
        P['3,2'].o.city = nil
        c = H.assignment_facts(0, { plots = { { x = 2, y = 2, site = true } } }).plots['2,2'].city_within_range
        assert(c and c.name == 'Hidden' and c.distance == 2, 'a city in sight counts: ' .. tostring(c and c.name))
        """)

    def test_a_foreign_unit_only_while_in_sight(self):
        self.run_lua("""
        unit(7, 3, 1, 5, 2)
        local f = H.assignment_facts(0, { foreign_units = { { owner = 3, id = 7 } } })
        assert(f.foreign_units['3:7'].in_sight and f.foreign_units['3:7'].x == 5 and f.foreign_units['3:7'].type == 'WARRIOR')
        P['5,2'].o.fog = true
        f = H.assignment_facts(0, { foreign_units = { { owner = 3, id = 7, x = 6, y = 2 } } })
        local r = f.foreign_units['3:7']
        assert(not r.in_sight and r.x == nil and r.type == nil and r.last_plot_visible == true)
        f = H.assignment_facts(0, { foreign_units = { { owner = 3, id = 99, x = 6, y = 2 } } })
        assert(not f.foreign_units['3:99'].in_sight, 'a unit that does not exist reads the same as one out of sight')
        """)

    def test_hostiles_within_the_radius_and_visible_only(self):
        self.run_lua("""
        unit(1, 0, 1, 2, 2)
        unit(20, 63, 2, 3, 2)                            -- barbarian beside it
        unit(21, 63, 2, 0, 2); P['0,2'].o.fog = true     -- another two away, in fog: never seen
        local f = H.assignment_facts(0, { units = { { id = 1 } }, radius = 2 })
        assert(f.units['1'].hostile and f.units['1'].hostile.id == 20 and f.units['1'].hostile.distance == 1)
        f = H.assignment_facts(0, { units = { { id = 1 } } })
        assert(f.units['1'].hostile == nil, 'no radius asked, no scan')
        """)

    def test_cities_buildings_players_and_techs(self):
        self.run_lua("""
        city(8192, 0, 'Venice', 3, 3, { founded = 1, damage = 20, buildings = { [3] = true } })
        local f = H.assignment_facts(0, { cities = { { id = 8192, buildings = { 'BUILDING_WALLS', 'BUILDING_NOPE' } },
                                                     { id = 5 } },
                                          players = { 3, 63 }, techs = { 'TECH_OPTICS', 'TECH_BRONZE_WORKING' } })
        local c = f.cities['8192']
        assert(c.name == 'Venice' and c.hp == 180 and c.founded == 1 and c.has.BUILDING_WALLS and c.has.BUILDING_NOPE == false)
        assert(f.cities['5'].missing)
        assert(f.players['3'].met and f.players['3'].name == 'Persia' and f.players['3'].at_war == false)
        assert(f.techs.TECH_OPTICS == true and f.techs.TECH_BRONZE_WORKING == false)
        """)


# ------------------------------------------------------------------ pure Python
def escort(**kw):
    a = {"id": 1, "role": "escort", "purpose": "Escort the settler to the hill site by the river", "status": "active",
         "created_turn": 40,
         "units": [{"id": 10, "type": "WARRIOR", "created": 5, "x": 2, "y": 2},
                   {"id": 11, "type": "SETTLER", "created": 38, "x": 2, "y": 2}],
         "cities": [], "target": {"kind": "plot", "x": 5, "y": 2}, "done_when": {"kind": "city_at", "x": 5, "y": 2},
         "review": {}, "seen": {"turn": 40, "owner_name": None}}
    a.update(kw)
    return a


def facts(**kw):
    f = {"turn": 42,
         "units": {"10": {"id": 10, "type": "WARRIOR", "created": 5, "x": 3, "y": 2, "hp": 100, "max_hp": 100, "moves": 2},
                   "11": {"id": 11, "type": "SETTLER", "created": 38, "x": 3, "y": 2, "hp": 100, "max_hp": 100, "moves": 2}},
         "cities": {}, "plots": {"5,2": {"vis": "visible", "found_range": 2}}, "foreign_units": {}, "players": {},
         "techs": {}}
    for k, v in kw.items():
        f[k] = {**f.get(k, {}), **v} if isinstance(v, dict) else v
    return f


class NormalizeTests(unittest.TestCase):
    def test_targets(self):
        self.assertEqual(A.normalize_target({"x": 5, "y": 2}), {"kind": "plot", "x": 5, "y": 2})
        self.assertEqual(A.normalize_target({"unit_id": 7, "owner": 3}), {"kind": "unit", "id": 7, "owner": 3})
        self.assertEqual(A.normalize_target({"player": 3}), {"kind": "player", "id": 3})
        self.assertIsNone(A.normalize_target({}))
        with self.assertRaisesRegex(A.AssignmentError, "owner"):
            A.normalize_target({"unit_id": 7})
        with self.assertRaisesRegex(A.AssignmentError, "x and y"):
            A.normalize_target({"x": 5})

    def test_done_when_defaults_to_the_target_plot_and_full_type_names(self):
        t = {"kind": "plot", "x": 5, "y": 2}
        self.assertEqual(A.normalize_done("city_at", t), {"kind": "city_at", "x": 5, "y": 2})
        self.assertEqual(A.normalize_done({"kind": "improvement", "improvement": "farm"}, t),
                         {"kind": "improvement", "x": 5, "y": 2, "improvement": "IMPROVEMENT_FARM"})
        self.assertEqual(A.normalize_done({"kind": "tech", "tech": "optics"}, None), {"kind": "tech", "tech": "TECH_OPTICS"})
        self.assertEqual(A.normalize_done(None, None), {"kind": "manual"})
        with self.assertRaisesRegex(A.AssignmentError, "needs x and y"):
            A.normalize_done("unit_at", None)
        with self.assertRaisesRegex(A.AssignmentError, "one of"):
            A.normalize_done({"kind": "win"}, None)

    def test_review_and_text(self):
        self.assertEqual(A.normalize_review({"turn": 50, "hostile_within": 9, "hp_below": 50}),
                         {"turn": 50, "hostile_within": 6, "hp_below": 50})
        with self.assertRaisesRegex(A.AssignmentError, "unknown review"):
            A.normalize_review({"when": 3})
        with self.assertRaisesRegex(A.AssignmentError, "required"):
            A.clean_text("  ", 40, "purpose", required=True)
        with self.assertRaisesRegex(A.AssignmentError, "integer"):
            A.normalize_ids(["seven"], "unit_ids")

    def test_spec_lists_every_reference_once(self):
        b = escort(id=2, units=[{"id": 10, "type": "WARRIOR", "x": 3, "y": 2}], target={"kind": "unit", "id": 7, "owner": 3},
                   done_when={"kind": "tech", "tech": "TECH_OPTICS"}, review={"hostile_within": 3},
                   seen={"turn": 41, "x": 6, "y": 2})
        c = escort(id=3, units=[], cities=[{"id": 8192, "x": 3, "y": 3}], target={"kind": "player", "id": 3},
                   done_when={"kind": "building", "city_id": 8192, "building": "BUILDING_WALLS"})
        s = A.spec([escort(), b, c])
        self.assertEqual(sorted(u["id"] for u in s["units"]), [10, 11])
        self.assertEqual(s["units"][0]["x"], 3, "the later record's last plot wins")
        self.assertIn({"x": 5, "y": 2, "site": True}, s["plots"])
        self.assertEqual(s["foreign_units"], [{"owner": 3, "id": 7, "x": 6, "y": 2}])
        self.assertEqual(s["cities"], [{"id": 8192, "buildings": ["BUILDING_WALLS"]}])
        self.assertEqual((s["players"], s["techs"], s["radius"]), ([3], ["TECH_OPTICS"], 3))


class ReconcileTests(unittest.TestCase):
    def test_on_track_then_condition_met_with_the_settler_consumed(self):
        row, upd = A.reconcile(escort(), facts(), 42, 0)
        self.assertEqual(row["state"], "on_track")
        self.assertEqual([u["x"] for u in row["units"]], [3, 3])
        self.assertEqual(upd["unit_plots"], [(10, 3, 2), (11, 3, 2)], "the last plots move with the units")
        done = facts(units={"11": {"missing": True}},
                     plots={"5,2": {"vis": "visible", "city": {"name": "Aquileia", "owner": 0, "owner_name": "you"}}})
        row, _ = A.reconcile(escort(), done, 45, 0)
        self.assertEqual(row["state"], "condition_met")
        self.assertIn("Aquileia", row["evidence"])
        self.assertTrue(any("consumed" in r for r in row["reasons"]), "the settler's absence is still explained")

    def test_a_lost_unit_and_an_upgrade_on_its_last_plot(self):
        f = facts(units={"10": {"missing": True, "on_last_plot": [{"id": 33, "type": "SWORDSMAN", "upgrade_of": "WARRIOR"}]}})
        row, upd = A.reconcile(escort(units=[{"id": 10, "type": "WARRIOR", "created": 5, "x": 3, "y": 2}]), f, 43, 0)
        self.assertEqual(row["state"], "needs_review")
        self.assertTrue(row["units"][0]["gone"])
        self.assertIn("not among my units", row["reasons"][0])
        self.assertIn("SWORDSMAN (33)", row["reasons"][1])
        self.assertIn("amend_assignment", row["reasons"][1])
        self.assertNotIn("unit_plots", upd, "a gone unit's last plot is kept")

    def test_a_reused_id_is_never_attached(self):
        f = facts(units={"10": {"id": 10, "type": "WORKER", "created": 41, "x": 1, "y": 1}})
        row, upd = A.reconcile(escort(), f, 43, 0)
        self.assertTrue(row["units"][0]["gone"])
        self.assertEqual(row["units"][0]["type"], "WARRIOR", "the assigned unit, not the new owner of the id")
        self.assertIn("now belongs to a WORKER", row["reasons"][0])
        self.assertNotIn((10, 1, 1), upd.get("unit_plots", []))

    def test_a_site_taken_or_crowded_is_an_invalid_prerequisite(self):
        f = facts(plots={"5,2": {"vis": "visible", "found_range": 2, "owner": 3, "owner_name": "Persia"}})
        row, _ = A.reconcile(escort(), f, 43, 0)
        self.assertTrue(any("inside Persia's borders" in r for r in row["reasons"]))
        self.assertTrue(any("owner changed: none -> Persia" in r for r in row["reasons"]))
        f = facts(plots={"5,2": {"vis": "fogged", "found_range": 2,
                                 "city_within_range": {"name": "Pasargadae", "owner": 3, "owner_name": "Persia", "distance": 2}}})
        row, upd = A.reconcile(escort(), f, 43, 0)
        self.assertTrue(any("Pasargadae (Persia) stands 2" in r for r in row["reasons"]))
        self.assertEqual(row["target"]["known"], "stale")
        self.assertEqual(row["target"]["last_seen_turn"], 40)
        self.assertNotIn("seen", upd, "a fogged read never overwrites the last sighting")
        f = facts(plots={"5,2": {"vis": "visible", "found_range": 2,
                                 "city_within_range": {"name": "Venice", "owner": 0, "owner_name": "you", "distance": 2}}})
        row, _ = A.reconcile(escort(), f, 43, 0)
        self.assertTrue(any("Venice (you) stands 2" in r for r in row["reasons"]), "my own cities count for the range")
        f = facts(plots={"5,2": {"vis": "visible", "found_range": 2, "owner": 0, "owner_name": "you",
                                 "city": {"name": "Aquileia", "owner": 0, "owner_name": "you"},
                                 "city_within_range": {"name": "Aquileia", "owner": 0, "owner_name": "you", "distance": 0}}})
        row, _ = A.reconcile(escort(), f, 43, 0)
        self.assertEqual(row["state"], "condition_met")
        self.assertFalse(any("stands 0" in r for r in row.get("reasons", [])), "the founded city is the goal, not a blocker")

    def test_an_unobserved_foreign_unit_is_stale_not_dead(self):
        a = escort(target={"kind": "unit", "id": 7, "owner": 3}, done_when={"kind": "manual"},
                   seen={"turn": 41, "type": "BRUTE", "x": 6, "y": 2, "hp": 100})
        row, upd = A.reconcile(a, facts(foreign_units={"3:7": {"in_sight": False, "last_plot_visible": False}}), 43, 0)
        self.assertEqual(row["state"], "on_track", "out of sight is not a change")
        self.assertEqual(row["target"]["known"], "stale")
        self.assertEqual(row["target"]["last_seen"]["turn"], 41)
        self.assertNotIn("seen", upd)
        row, _ = A.reconcile(a, facts(foreign_units={"3:7": {"in_sight": False, "last_plot_visible": True}}), 43, 0)
        self.assertIn("not on the plot it was last seen on", row["reasons"][0])
        self.assertIn("not in sight", row["reasons"][0])
        row, upd = A.reconcile(a, facts(foreign_units={"3:7": {"in_sight": True, "type": "BRUTE", "x": 7, "y": 2, "hp": 60}}), 43, 0)
        self.assertEqual((row["target"]["x"], upd["seen"]["turn"], upd["seen"]["hp"]), (7, 43, 60))

    def test_review_triggers(self):
        a = escort(review={"turn": 43, "hostile_within": 2, "hp_below": 50})
        f = facts(units={"10": {"id": 10, "type": "WARRIOR", "created": 5, "x": 3, "y": 2, "hp": 40, "max_hp": 100,
                                "hostile": {"unit": "BRUTE", "owner": "Barbarians", "distance": 2, "id": 20}}})
        row, _ = A.reconcile(a, f, 43, 0)
        text = " | ".join(row["reasons"])
        self.assertIn("review turn 43 reached", text)
        self.assertIn("hostile BRUTE (Barbarians) 2 plot(s) from WARRIOR 10", text)
        self.assertIn("40/100 hp, below 50%", text)
        self.assertNotIn("hostile", row["units"][0], "the entity row stays short")
        a = escort(review={"hostile_within": 1})
        row, _ = A.reconcile(a, f, 42, 0)
        self.assertFalse(any("hostile" in r for r in row.get("reasons", [])), "another assignment's wider radius does not apply")

    def test_player_target_war_and_elimination(self):
        a = escort(units=[], target={"kind": "player", "id": 3}, done_when={"kind": "manual"},
                   seen={"turn": 40, "name": "Persia", "at_war": False})
        row, upd = A.reconcile(a, facts(players={"3": {"id": 3, "name": "Persia", "met": True, "alive": True, "at_war": True}}), 43, 0)
        self.assertIn("now at war with Persia (was at peace)", row["reasons"])
        self.assertTrue(upd["seen"]["at_war"])
        row, _ = A.reconcile(a, facts(players={"3": {"id": 3, "name": "Persia", "met": True, "alive": False, "at_war": False}}), 43, 0)
        self.assertIn("Persia has been eliminated", row["reasons"])

    def test_improvement_building_tech_and_a_lost_city(self):
        a = escort(units=[{"id": 12, "type": "WORKER", "created": 20, "x": 4, "y": 4}], target={"kind": "plot", "x": 4, "y": 4},
                   done_when={"kind": "improvement", "x": 4, "y": 4, "improvement": "IMPROVEMENT_FARM"}, seen={})
        f = facts(units={"12": {"id": 12, "type": "WORKER", "created": 20, "x": 4, "y": 4}},
                  plots={"4,4": {"vis": "visible", "improvement": "FARM", "owner": 0, "owner_name": "you"}})
        self.assertEqual(A.reconcile(a, f, 43, 0)[0]["evidence"], "FARM on (4,4)")
        f["plots"]["4,4"]["pillaged"] = True
        row, _ = A.reconcile(a, f, 43, 0)
        self.assertEqual(row["state"], "needs_review", "a pillaged farm is not done")
        b = escort(units=[], cities=[{"id": 8192, "name": "Venice", "x": 3, "y": 3, "founded": 1}], target=None,
                   done_when={"kind": "building", "city_id": 8192, "building": "BUILDING_WALLS"})
        f = facts(cities={"8192": {"id": 8192, "name": "Venice", "x": 3, "y": 3, "founded": 1, "has": {"BUILDING_WALLS": True}}})
        self.assertEqual(A.reconcile(b, f, 43, 0)[0]["evidence"], "Venice has WALLS")
        f = facts(cities={"8192": {"missing": True}},
                  plots={"3,3": {"vis": "visible", "city": {"name": "Venice", "owner": 3, "owner_name": "Persia"}}})
        row, _ = A.reconcile(b, f, 43, 0)
        self.assertEqual(row["reasons"][:2], ["Venice (8192) is no longer my city",
                                              "its plot (3,3) is in sight: Venice held by Persia"])
        c = escort(units=[], target={"kind": "player", "id": 3}, done_when={"kind": "tech", "tech": "TECH_OPTICS"})
        self.assertEqual(A.reconcile(c, facts(techs={"TECH_OPTICS": True}), 43, 0)[0]["evidence"], "OPTICS researched")

    def test_briefing_section_puts_the_ones_needing_a_look_first(self):
        rows = [{"id": 1, "role": "explore", "state": "on_track", "purpose": "x" * 300},
                {"id": 2, "role": "escort", "state": "needs_review", "purpose": "p", "reasons": ["r"],
                 "units": [{"id": 10, "type": "WARRIOR", "x": 1, "y": 1, "hp": 50, "moves": 2}]},
                {"id": 3, "role": "settle", "state": "condition_met", "purpose": "q", "evidence": "e"}]
        s = A.briefing_section(rows, 2)
        self.assertEqual([r["id"] for r in s["rows"]], [3, 2])
        self.assertEqual((s["active"], s["omitted"]), (3, 1))
        self.assertEqual(s["by_state"], {"condition_met": 1, "needs_review": 1, "on_track": 1})
        self.assertNotIn("moves", s["rows"][1]["units"][0])
        self.assertEqual(len(A.briefing_section(rows, 8)["rows"][2]["purpose"]), 160)


class NotebookAssignmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"CIV5_NOTES_DIR": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)

    def test_replace_amend_close_and_restart(self):
        nb = Notebook("g", 0)
        nb.remember("Tradition then Rationalism", turn=40, tag="plan")
        a = nb.add_assignment({"role": "escort", "purpose": "p", "units": [{"id": 10}]}, turn=40)["assignment"]
        b = nb.add_assignment({"role": "escort", "purpose": "p2", "units": [{"id": 10}]}, turn=41, replace_id=a["id"])
        self.assertTrue(b["ok"])
        self.assertEqual([x["id"] for x in nb.assignments("active")], [b["assignment"]["id"]], "the old one never competes")
        old = nb.assignments("closed")[0]
        self.assertEqual((old["status"], old["replaced_by"]), ("replaced", b["assignment"]["id"]))
        r = nb.update_assignment(a["id"], {"purpose": "x"}, 42, "amend")
        self.assertFalse(r["ok"])
        self.assertEqual(r["replaced_by"], b["assignment"]["id"])
        r = nb.update_assignment(b["assignment"]["id"], {"purpose": "p3"}, 42, "amended purpose")
        self.assertEqual(r["previous"], {"purpose": "p2"})
        nb.store_observations({b["assignment"]["id"]: {"seen": {"turn": 42}, "unit_plots": [(10, 4, 4)]}})
        again = Notebook("g", 0)   # a new process
        cur = again.assignments("active")[0]
        self.assertEqual((cur["purpose"], cur["seen"], cur["units"][0]["x"]), ("p3", {"turn": 42}, 4))
        self.assertEqual(again.recall()["notes"][0]["text"], "Tradition then Rationalism", "prose notes untouched")
        again.update_assignment(cur["id"], {}, 43, "completed", close="completed")
        self.assertEqual(again.assignments("active"), [])
        self.assertEqual(Notebook("g", 1).assignments("all"), [], "the other seat's notebook is its own")
        self.assertEqual(Notebook("other-game", 0).assignments("all"), [], "and another game's")

    def test_limits(self):
        nb = Notebook("g", 0)
        for _ in range(A.MAX_ACTIVE):
            nb.add_assignment({"role": "r", "purpose": "p"}, turn=1)
        self.assertIn("already", nb.add_assignment({"role": "r", "purpose": "p"}, turn=1)["err"])
        self.assertFalse(nb.add_assignment({"role": "r", "purpose": "p"}, turn=1, replace_id=999)["ok"])
        for a in nb.assignments("active"):
            nb.update_assignment(a["id"], {}, 2, "cancelled", close="cancelled")
        for _ in range(A.MAX_CLOSED):
            aid = nb.add_assignment({"role": "r", "purpose": "p"}, turn=3)["assignment"]["id"]
            nb.update_assignment(aid, {}, 3, "completed", close="completed")
        closed = nb.assignments("closed")
        self.assertEqual(len(closed), A.MAX_CLOSED, "the oldest closed ones are pruned")
        self.assertEqual({a["status"] for a in closed}, {"completed"})


# ------------------------------------------------------------------ Game and MCP over a scripted read
class ScriptedFactsGame(Game):
    """q() answers H.assignment_facts from `world` (the spec is parsed back out of the Lua literal)."""

    def __init__(self, seat=0):
        self.seat = seat
        self._game_key = "test-game"
        self.turn = 42
        self.world = {"units": {10: {"type": "WARRIOR", "created": 5, "x": 2, "y": 2, "hp": 100, "max_hp": 100},
                                11: {"type": "SETTLER", "created": 38, "x": 2, "y": 2, "hp": 100, "max_hp": 100}},
                      "cities": {8192: {"name": "Venice", "x": 3, "y": 3, "founded": 1, "pop": 4}},
                      "plots": {}}
        self.reads = 0

    def q(self, code, *a, **k):
        assert code.startswith(f"return H.assignment_facts({self.seat}, "), code
        self.reads += 1
        units = {str(i): ({"id": i, **self.world["units"][i]} if i in self.world["units"] else {"id": i, "missing": True})
                 for i in self._ids(code, "units")}
        cities = {str(i): ({"id": i, **self.world["cities"][i]} if i in self.world["cities"] else {"id": i, "missing": True})
                  for i in self._ids(code, "cities")}
        return {"turn": self.turn, "units": units, "cities": cities, "plots": dict(self.world["plots"]),
                "foreign_units": {}, "players": {}, "techs": {}}

    @staticmethod
    def _ids(code, key):
        import re
        m = re.search(r'\["' + key + r'"\]=\{(.*?)\}\}', code) or re.search(r'\["' + key + r'"\]=\{\}', code)
        return [int(x) for x in re.findall(r'\["id"\]=(\d+)', m.group(1))] if m and m.groups() else []

    def turn_state(self, pid=None):
        return {"turn": self.turn}


class GameAssignmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"CIV5_NOTES_DIR": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)

    def test_assign_fingerprints_and_refuses_what_is_not_mine(self):
        g = ScriptedFactsGame()
        r = g.assign("escort", "Escort the settler to the hill site", unit_ids=[10, 11], target={"x": 5, "y": 2},
                     done_when="city_at", review={"turn": 50})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["assignment"]["state"], "on_track")
        self.assertEqual(g.reads, 1, "one read for the fingerprints and the first reconcile")
        stored = g.notebook().assignments("active")[0]
        self.assertEqual(stored["units"][0], {"id": 10, "type": "WARRIOR", "created": 5, "x": 2, "y": 2})
        self.assertEqual(stored["done_when"], {"kind": "city_at", "x": 5, "y": 2})
        r = g.assign("defend", "Hold the pass", unit_ids=[99])
        self.assertFalse(r["ok"])
        self.assertIn("not mine now: unit 99", r["err"])
        self.assertIn("is a note", g.assign("plan", "go wide")["err"])
        self.assertIn("done_when.kind", g.assign("x", "y", unit_ids=[10], done_when={"kind": "win"})["err"])

    def test_an_upgrade_is_surfaced_and_taken_over_with_amend(self):
        g = ScriptedFactsGame()
        aid = g.assign("defend", "Hold Venice's river crossing", unit_ids=[10], review={"hp_below": 50})["assignment"]["id"]
        g.turn = 45
        del g.world["units"][10]
        g.world["units"][30] = {"type": "SWORDSMAN", "created": 45, "x": 2, "y": 2, "hp": 100, "max_hp": 100}
        row = g.assignments()["active"][0]
        self.assertEqual(row["state"], "needs_review")
        self.assertTrue(row["units"][0]["gone"])
        r = g.amend_assignment(aid, {"unit_ids": [30]}, note="upgraded")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["assignment"]["state"], "on_track")
        self.assertEqual(r["previous"]["units"][0]["type"], "WARRIOR", "what was replaced, as stored")
        stored = g.notebook().assignments("active")[0]
        self.assertEqual(stored["units"][0]["type"], "SWORDSMAN")
        self.assertEqual(stored["history"][-1]["what"], "amended unit_ids: upgraded")
        self.assertFalse(g.amend_assignment(aid, {"colour": "red"})["ok"])
        self.assertFalse(g.amend_assignment(aid, {"unit_ids": [], "target": {}})["ok"], "nothing left to track")
        r = g.close_assignment(aid, "completed", note="the pass held")
        self.assertEqual((r["status"], r["active"]), ("completed", 0))
        self.assertFalse(g.close_assignment(aid)["ok"])
        self.assertEqual(g.assignments("closed")["closed"][0]["outcome_note"], "the pass held")
        self.assertFalse(g.close_assignment(aid, "won")["ok"])

    def test_briefing_carries_the_section_and_tags_decision_rows(self):
        import test_briefing as tb

        class G(tb.ScriptedBoardGame, ScriptedFactsGame):
            def __init__(self):
                tb.ScriptedBoardGame.__init__(self)
                w = ScriptedFactsGame()
                self.world, self.turn, self.reads = w.world, 42, 0

            def q(self, code, *a, **k):
                if code.startswith("return H.assignment_facts"):
                    return ScriptedFactsGame.q(self, code)
                return tb.ScriptedBoardGame.q(self, code)

        g = G()
        g.ts = tb.status(todo={"units": [{"id": 10, "type": "WARRIOR", "x": 2, "y": 2, "moves": 2}]})
        self.assertNotIn("assignments", g.briefing(), "no assignments, no section and no extra read")
        self.assertEqual(g.reads, 0)
        g.assign("escort", "Escort the settler north", unit_ids=[10, 11], target={"x": 5, "y": 2}, done_when="city_at")
        b = g.briefing()
        self.assertEqual(b["assignments"]["active"], 1)
        self.assertEqual(b["assignments"]["rows"][0]["purpose"], "Escort the settler north")
        row = next(d for d in b["decisions"] if d["kind"] == "unit_orders")
        self.assertEqual(row["assignment"], {"id": 1, "role": "escort"})


class McpAssignmentTests(unittest.TestCase):
    def setUp(self):
        from harness import mcp_server
        self.m = mcp_server
        self._saved = mcp_server._game
        self.addCleanup(setattr, mcp_server, "_game", self._saved)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"CIV5_NOTES_DIR": self.tmp.name, "CIV5_SEAT": "0"})
        p.start()
        self.addCleanup(p.stop)
        g = ScriptedFactsGame()
        g.ts = {"turn": 42, "active_player": 0, "my_turn": True, "paused": False, "processing": False}
        g.turn_state = lambda pid=None: dict(g.ts)
        g.has_state = lambda name: True
        g.discussion_pending = lambda: False
        g.lock = contextlib.nullcontext
        g.claim = None
        self.g = g
        mcp_server._game = g

    def _call(self, tool, args):
        result = asyncio.run(self.m.mcp.call_tool(tool, args))
        text = result[0].text if isinstance(result, (list, tuple)) else result.content[0].text
        return json.loads(text)

    def test_the_four_tools(self):
        r = self._call("assign", {"role": "escort", "purpose": "Escort the settler", "unit_ids": [10, 11],
                                  "target": {"x": 5, "y": 2}, "done_when": "city_at"})
        self.assertTrue(r["ok"], r)
        aid = r["assignment"]["id"]
        self.assertEqual(self._call("assignments", {})["active"][0]["id"], aid)
        r = self._call("amend_assignment", {"assignment_id": aid, "review": {"turn": 44}})
        self.assertEqual(r["assignment"]["review"], {"turn": 44})
        self.g.ts = {**self.g.ts, "active_player": 1, "my_turn": False}
        self.assertFalse(self._call("assignments", {})["ok"], "the board is not read on another seat's turn")
        r = self._call("close_assignment", {"assignment_id": aid, "outcome": "cancelled"})
        self.assertTrue(r["ok"], "closing is notebook-only: usable off-turn")


if __name__ == "__main__":
    unittest.main()
