"""Conditional unit orders (#32).

Lua half: H.order_facts on the assignments test world (my unit's moves, activity and build in progress, every
visible hostile within the radius, a destination's refusal or enemy, what a build makes and whether its plot has
it) and H.resume_moves leaving the units an order owns to the order.
Python half: harness/orders.py (normalizing, the read's spec, decide), the notebook storage (one open order per
unit, replace, prune) and Game.give_order / run_orders / resume_order / cancel_order over a small simulated world
that answers H.order_facts and carries out move_unit / unit_mission: move-then-build and heal-then-move across
turns, cancellation, a blocked destination, a hostile coming into sight, damage, a step refused, no progress,
arrival without moves, a lost unit, a direct command taking the unit back, a restart after a step completed, a
harness that died mid-step, a loaded save, hotseat isolation, the turn-start window and its wake reasons, and
the MCP tools.
"""
import asyncio
import contextlib
import json
import os
import re
import tempfile
import unittest
from unittest import mock

import test_assignments as ta
import test_mcp_safety as support
from harness import orders as O
from harness.game import Game
from harness.notes import Notebook

WORLD = ta.WORLD + r"""
ActivityTypes = { ACTIVITY_AWAKE = 0, ACTIVITY_HEAL = 3, ACTIVITY_MISSION = 6 }
GameInfoTypes.IMPROVEMENT_FARM = 0; GameInfoTypes.ROUTE_ROAD = 0
GameInfo.Builds = { [0] = { ID = 0, Type = 'BUILD_FARM', ImprovementType = 'IMPROVEMENT_FARM' },
                    [1] = { ID = 1, Type = 'BUILD_ROAD', RouteType = 'ROUTE_ROAD' } }
GameInfo.Builds.BUILD_FARM = GameInfo.Builds[0]; GameInfo.Builds.BUILD_ROAD = GameInfo.Builds[1]
Game.GetActivePlayer = function() return 0 end
local base_unit2 = unit
function unit(id, owner, typ, x, y, o)
  o = o or {}
  local u = base_unit2(id, owner, typ, x, y, o)
  u.GetActivityType = function() return o.activity or 0 end
  u.GetBuildType = function() return o.build or -1 end
  u.MaxMoves = function() return (o.max_moves or 2) * 60 end
  u.CanBuild = function(_, plot, b, extra)   -- the engine's binding takes (plot, build) only (live t43)
    if extra ~= nil then error("bad argument #3 to 'CanBuild' (number expected, got boolean)") end
    return o.can_build ~= false
  end
  return u
end
"""


class OrderFactsLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)

    def test_unit_detail_and_every_hostile_in_the_radius(self):
        self.run_lua("""
        unit(1, 0, 4, 2, 2, { created = 5, hp = 70, moves = 1, activity = 3, build = 0 })
        unit(40, 63, 2, 3, 2)                          -- a Brute next door
        unit(41, 63, 2, 4, 2)                          -- another, two plots away
        unit(42, 63, 2, 7, 2)                          -- out of the radius
        local f = H.order_facts(0, { units = { { id = 1, type = 'WORKER', created = 5, x = 2, y = 2 } }, radius = 2 })
        local u = f.units['1']
        assert(u.type == 'WORKER' and u.hp == 70 and u.moves == 1 and u.max_moves == 2, 'moves')
        assert(u.activity == 'HEAL' and u.build == 'BUILD_FARM', 'activity and build')
        assert(#u.hostiles == 2 and u.hostiles[1].id == 40 and u.hostiles[1].distance == 1 and u.hostiles[2].id == 41,
               'both hostiles, nearest first')
        assert(u.hostiles[1].owner_id == 63 and u.hostile == nil)
        """)

    def test_a_destination_answers_move_units_refusal_and_an_enemy(self):
        self.run_lua("""
        unit(1, 0, 1, 2, 2)
        unit(40, 63, 2, 4, 2)                          -- a Brute on the destination
        P['5,2'].o.mountain = true
        P['6,2'].o.revealed = false
        local f = H.order_facts(0, { units = { { id = 1 } }, dests = { { unit_id = 1, x = 4, y = 2 },
          { unit_id = 1, x = 5, y = 2 }, { unit_id = 1, x = 6, y = 2 }, { unit_id = 1, x = 3, y = 3 } } })
        assert(f.dests['1:4,2'].enemy == true and f.dests['1:4,2'].refusal == nil, 'enemy, never an attack')
        assert(f.dests['1:5,2'].refusal == 'destination plot is a mountain', tostring(f.dests['1:5,2'].refusal))
        assert(f.dests['1:6,2'].refusal ~= nil, 'unrevealed')
        assert(next(f.dests['1:3,3']) == nil, 'a plain plot: nothing to say')
        """)

    def test_a_build_says_what_it_makes_whether_it_is_there_and_whether_the_unit_can(self):
        self.run_lua("""
        unit(1, 0, 4, 2, 2)
        unit(2, 0, 4, 3, 3, { can_build = false })
        P['2,2'].GetImprovementType = function() return 0 end
        local f = H.order_facts(0, { units = { { id = 1 }, { id = 2 } }, builds = {
          { unit_id = 1, build = 'BUILD_FARM', x = 2, y = 2 }, { unit_id = 2, build = 'BUILD_FARM', x = 3, y = 3 },
          { unit_id = 1, build = 'BUILD_ROAD', x = 4, y = 4 }, { unit_id = 1, build = 'BUILD_CASTLE', x = 2, y = 2 } } })
        local a, b = f.builds['1:BUILD_FARM'], f.builds['2:BUILD_FARM']
        assert(a.known and a.improvement == 'IMPROVEMENT_FARM' and a.done == true and a.can_build == true)
        assert(b.done == false and b.can_build == false)
        local r = f.builds['1:BUILD_ROAD']
        assert(r.route == 'ROUTE_ROAD' and r.done == false and r.can_build == nil, 'not on the plot: not asked')
        assert(f.builds['1:BUILD_CASTLE'].known == false)
        """)

    def test_resume_moves_leaves_an_order_owned_unit_alone(self):
        self.run_lua("""
        unit(1, 0, 1, 2, 2); unit(2, 0, 1, 3, 3)
        H.pending_moves[H.pm_key(1, 0)] = { x = 5, y = 2, pid = 0, unit_id = 1 }
        H.pending_moves[H.pm_key(2, 0)] = { x = 5, y = 3, pid = 0, unit_id = 2 }
        local pushed = {}
        H.move_unit = function(id) pushed[#pushed + 1] = id; return { ok = true } end
        H.melee_defender = function() return nil end; H.enemy_city_at = function() return nil end
        H.peaceful_occupant = function() return nil end
        H.resume_moves(0, { 1 })
        assert(#pushed == 1 and pushed[1] == 2, 'only the unit no order owns')
        assert(H.pending_moves[H.pm_key(1, 0)] ~= nil, 'the order-owned record is kept for the order to judge')
        """)


# ------------------------------------------------------------------ pure logic
def order(steps, **kw):
    o = {"id": 1, "unit": {"id": 7, "type": "WORKER", "created": 3}, "steps": O.normalize_steps(steps), "step": 0,
         "interrupt": O.normalize_interrupt(kw.pop("interrupt", None)), "status": "active", "updated_turn": 10}
    o.update(kw)
    return o


def facts(turn=10, **u):
    row = {"id": 7, "type": "WORKER", "created": 3, "x": 2, "y": 2, "hp": 100, "max_hp": 100, "moves": 2,
           "max_moves": 2}
    dests = u.pop("dests", {})
    builds = u.pop("builds", {})
    row.update(u)
    return {"turn": turn, "units": {"7": row}, "dests": dests, "builds": builds}


class NormalizeTests(unittest.TestCase):
    def test_steps(self):
        s = O.normalize_steps([{"kind": "move", "x": 5, "y": 2}, {"kind": "build", "build": "farm"},
                               "heal", {"kind": "hold", "mission": "MISSION_SLEEP"}])
        self.assertEqual(s[1], {"kind": "build", "build": "BUILD_FARM", "x": 5, "y": 2}, "builds where the move ends")
        self.assertEqual(s[2], {"kind": "heal", "hp": 100})
        self.assertEqual(s[3], {"kind": "hold", "mission": "sleep"})
        for bad, msg in (([], "non-empty"), ([{"kind": "attack"}], "never attacks"), ([{"kind": "move", "x": 1}], "x and y"),
                         (["hold", "heal"], "nothing can follow"), ([{"kind": "hold", "mission": "pillage"}], "mission"),
                         ([{"kind": "move", "x": 1, "y": 1}] * 7, "at most")):
            with self.assertRaises(O.OrderError) as e:
                O.normalize_steps(bad)
            self.assertIn(msg, str(e.exception))
        self.assertNotIn("x", O.normalize_steps([{"kind": "build", "build": "ROAD"}])[0], "filled in by the caller")

    def test_interrupt(self):
        self.assertEqual(O.normalize_interrupt(None), {"hostile_within": 2, "damaged": True})
        self.assertEqual(O.normalize_interrupt({"hostile_within": 0, "hp_below": 150, "damaged": False}),
                         {"hostile_within": 0, "hp_below": 100, "damaged": False})
        with self.assertRaises(O.OrderError):
            O.normalize_interrupt({"war": True})
        with self.assertRaises(O.OrderError):
            O.normalize_interrupt({"damaged": "yes"})

    def test_spec_reads_only_the_current_step(self):
        o = order([{"kind": "move", "x": 5, "y": 2}, {"kind": "build", "build": "FARM"}])
        self.assertEqual(O.spec([o]), {"units": [{"id": 7, "type": "WORKER", "created": 3}],
                                       "dests": [{"unit_id": 7, "x": 5, "y": 2}], "radius": 2})
        o["step"] = 1
        self.assertEqual(O.spec([o])["builds"], [{"unit_id": 7, "build": "BUILD_FARM", "x": 5, "y": 2}])


class DecideTests(unittest.TestCase):
    MOVE_BUILD = [{"kind": "move", "x": 5, "y": 2}, {"kind": "build", "build": "FARM"}]

    def test_move_issue_wait_and_arrive(self):
        o = order(self.MOVE_BUILD)
        d = O.decide(o, facts(), 10)
        self.assertEqual((d["do"], d["tool"], d["args"]), ("issue", "move_unit", {"unit_id": 7, "x": 5, "y": 2}))
        o["issued"] = {"turn": 10, "step": 0, "x": 2, "y": 2}
        d = O.decide(o, facts(x=3, moves=0, going_to={"x": 5, "y": 2}), 10)
        self.assertEqual((d["do"], d["state"]), ("wait", "moving"), "never twice in one turn")
        self.assertEqual(O.decide(o, facts(x=5), 11)["do"], "next")

    def test_no_moves_is_an_explicit_wait_not_a_retry(self):
        d = O.decide(order(self.MOVE_BUILD), facts(moves=0), 10)
        self.assertEqual((d["do"], d["state"]), ("wait", "no_moves"))

    def test_no_progress_for_a_turn_pauses(self):
        o = order(self.MOVE_BUILD, issued={"turn": 9, "step": 0, "x": 2, "y": 2})
        d = O.decide(o, facts(), 10)
        self.assertEqual((d["do"], d["kind"]), ("pause", "no_progress"))

    def test_the_destination_is_checked_before_every_move(self):
        o = order(self.MOVE_BUILD)
        d = O.decide(o, facts(dests={"7:5,2": {"enemy": True}}), 10)
        self.assertEqual((d["do"], d["kind"]), ("pause", "enemy_on_destination"))
        self.assertIn("never attacks", d["reason"])
        d = O.decide(o, facts(dests={"7:5,2": {"refusal": "destination plot is a mountain"}}), 10)
        self.assertEqual((d["do"], d["kind"]), ("pause", "destination"))

    def test_hostiles_pause_unless_acknowledged_and_only_within_the_radius(self):
        h = {"id": 40, "owner_id": 63, "owner": "Barbarians", "unit": "BRUTE", "x": 3, "y": 2, "distance": 1}
        o = order(self.MOVE_BUILD)
        d = O.decide(o, facts(hostiles=[h]), 10)
        self.assertEqual((d["do"], d["kind"]), ("pause", "hostile"))
        self.assertEqual(d["hostiles"], [h])
        o["acked"] = ["63:40"]
        self.assertEqual(O.decide(o, facts(hostiles=[h]), 10)["do"], "issue")
        o = order(self.MOVE_BUILD, interrupt={"hostile_within": 0})
        self.assertEqual(O.decide(o, facts(hostiles=[h]), 10)["do"], "issue", "turned off")

    def test_damage_and_low_hp(self):
        o = order(self.MOVE_BUILD, seen={"hp": 100})
        self.assertEqual(O.decide(o, facts(hp=80), 10)["kind"], "damaged")
        o = order(self.MOVE_BUILD, interrupt={"damaged": False, "hp_below": 50}, seen={"hp": 40})
        self.assertEqual(O.decide(o, facts(hp=40), 10)["kind"], "low_hp")
        o = order([{"kind": "heal", "hp": 90}], interrupt={"hp_below": 50}, seen={"hp": 40})
        self.assertEqual(O.decide(o, facts(hp=40), 10)["do"], "issue", "low hp is what a heal step is for")

    def test_build_steps(self):
        o = order(self.MOVE_BUILD, step=1)
        d = O.decide(o, facts(), 10)
        self.assertEqual((d["do"], d["kind"]), ("pause", "prerequisite"), "not on the build plot")
        f = facts(x=5, builds={"7:BUILD_FARM": {"known": True, "done": False, "can_build": True}})
        d = O.decide(o, f, 10)
        self.assertEqual((d["tool"], d["args"]["build"]), ("unit_mission", "BUILD_FARM"))
        f["units"]["7"]["build"] = "BUILD_REMOVE_FOREST"
        d = O.decide(o, f, 10)
        self.assertEqual(d["state"], "building")
        self.assertIn("first", d["note"])
        f["units"]["7"]["build"] = None
        f["builds"]["7:BUILD_FARM"]["done"] = True
        self.assertEqual(O.decide(o, f, 10)["do"], "next")
        f["builds"]["7:BUILD_FARM"] = {"known": True, "done": False, "can_build": False}
        self.assertEqual(O.decide(o, f, 10)["kind"], "prerequisite")

    def test_heal_and_hold(self):
        o = order([{"kind": "heal", "hp": 80}, "hold"])
        d = O.decide(o, facts(hp=50), 10)
        self.assertEqual(d["args"]["mission"], "MISSION_HEAL")
        self.assertEqual(O.decide(o, facts(hp=60, activity="HEAL"), 10)["state"], "healing")
        self.assertEqual(O.decide(o, facts(hp=80), 10)["do"], "next")
        o["step"] = 1
        self.assertEqual(O.decide(o, facts(), 10)["args"]["mission"], "MISSION_FORTIFY")

    def test_a_lost_or_reused_unit_fails_and_an_upgrade_is_named(self):
        o = order(self.MOVE_BUILD)
        f = {"turn": 10, "units": {"7": {"id": 7, "missing": True,
                                         "on_last_plot": [{"id": 9, "type": "SWORDSMAN", "upgrade_of": "WORKER"}]}}}
        d = O.decide(o, f, 10)
        self.assertEqual((d["do"], d["kind"]), ("fail", "unit_gone"))
        self.assertIn("SWORDSMAN (9)", d["reason"])
        self.assertEqual(O.decide(o, facts(type="SETTLER"), 10)["do"], "fail")

    def test_an_unanswered_step_and_a_loaded_save_pause(self):
        o = order(self.MOVE_BUILD, inflight={"turn": 10, "step": 0, "what": "move to (5,2)"})
        self.assertEqual(O.decide(o, facts(), 10)["kind"], "uncertain")
        self.assertEqual(O.decide(o, facts(x=5), 10)["do"], "next", "the board shows it happened")
        o = order(self.MOVE_BUILD, updated_turn=12)
        self.assertEqual(O.decide(o, facts(), 10)["kind"], "turn_went_back")


class NotebookOrderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"CIV5_NOTES_DIR": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)

    def test_one_open_order_per_unit_and_replace(self):
        nb = Notebook("g", 0)
        rec = {"unit": {"id": 7}, "steps": [{"kind": "heal", "hp": 100}]}
        a = nb.add_order(rec, 5)["order"]["id"]
        r = nb.add_order(rec, 5)
        self.assertFalse(r["ok"])
        self.assertIn("replace_id=1", r["err"])
        r = nb.add_order(rec, 6, replace_id=a)
        self.assertTrue(r["ok"], r)
        self.assertEqual([o["status"] for o in nb.orders("all")], ["replaced", "active"])
        self.assertFalse(nb.add_order(rec, 6, replace_id=a)["ok"], "a replaced order is closed")
        self.assertEqual(Notebook("g", 1).orders("all"), [], "per seat")

    def test_closed_ones_are_pruned(self):
        nb = Notebook("g", 0)
        for i in range(O.MAX_CLOSED + 5):
            o = nb.add_order({"unit": {"id": i}, "steps": []}, 1)["order"]
            o["status"] = "completed"
            nb.put_order(o)
        self.assertEqual(len(nb.orders("closed")), O.MAX_CLOSED)


# ------------------------------------------------------------------ Game over a simulated world
class SimGame(Game):
    """Answers H.order_facts from `world` and carries out move_unit / unit_mission on it. A move walks up to
    `moves` plots in a straight line (x first, then y); a build takes `build_turns` turns; heal adds 20 hp a
    turn while HEAL. `end_turn()` advances the world one turn the way the engine would."""

    def __init__(self, seat=0, key="sim"):
        self.seat = seat
        self._game_key = key
        self.turn = 10
        self.claim = None
        self.units = {7: {"type": "WORKER", "created": 3, "x": 2, "y": 2, "hp": 100, "max_hp": 100, "moves": 2,
                          "max_moves": 2}}
        self.hostiles = []          # {id, owner_id, owner, unit, x, y}
        self.blocked = {}           # (x, y) -> refusal
        self.enemy_on = set()
        self.improved = {}          # (x, y) -> BUILD_*
        self.cant_build = set()
        self.pending = {}           # unit id -> (x, y): the standing move
        self.calls = []             # (tool, args) the orders issued
        self.refuse = None          # make the next action refuse with this err
        self.build_turns = 2
        self.lua = []

    # -- the read
    def q(self, code, *a, **k):
        if code.startswith(f"return H.order_facts({self.seat}, "):
            return self._facts(code)
        if "H.pending_moves" in code:
            self.lua.append(code)
            m = re.search(r"H\.pm_key\((\d+),", code)
            uid = int(m.group(1))
            xy = re.search(r"pm\.x == (-?\d+) and pm\.y == (-?\d+)", code)
            if uid in self.pending and self.pending[uid] == (int(xy.group(1)), int(xy.group(2))):
                del self.pending[uid]
                return True
            return False
        if code.startswith("return H.resume_moves"):
            self.lua.append(code)
            return []
        raise AssertionError(code)

    def _facts(self, code):
        ids = [int(i) for i in re.findall(r'\["id"\]=(\d+)', code.split('["units"]=')[1].split("}}")[0] + "}")]
        radius = int((re.search(r'\["radius"\]=(\d+)', code) or [0, 0])[1])
        units = {}
        for i in ids:
            u = self.units.get(i)
            if u is None:
                units[str(i)] = {"id": i, "missing": True}
                continue
            row = {"id": i, **{k: v for k, v in u.items() if k not in ("heal_turns",)}}
            if i in self.pending:
                row["going_to"] = {"x": self.pending[i][0], "y": self.pending[i][1]}
            near = []
            for h in self.hostiles:
                d = max(abs(h["x"] - u["x"]), abs(h["y"] - u["y"]))
                if d <= radius:
                    near.append({**h, "distance": d})
            if near:
                row["hostiles"] = sorted(near, key=lambda h: h["distance"])
            units[str(i)] = row
        dests = {}
        for uid, x, y in re.findall(r'\["unit_id"\]=(\d+), \["x"\]=(-?\d+), \["y"\]=(-?\d+)\}', code):
            key, xy = f"{uid}:{x},{y}", (int(x), int(y))
            dests[key] = {**({"refusal": self.blocked[xy]} if xy in self.blocked else {}),
                          **({"enemy": True} if xy in self.enemy_on else {})}
        builds = {}
        for uid, b, x, y in re.findall(r'\["unit_id"\]=(\d+), \["build"\]="(\w+)", \["x"\]=(-?\d+), \["y"\]=(-?\d+)', code):
            u = self.units.get(int(uid))
            xy = (int(x), int(y)) if int(x) >= 0 or not u else (u["x"], u["y"])
            row = {"known": b in ("BUILD_FARM", "BUILD_ROAD")}
            if row["known"]:
                row["done"] = self.improved.get(xy) == b
                if u and (u["x"], u["y"]) == xy:
                    row["can_build"] = xy not in self.cant_build
            builds[f"{uid}:{b}"] = row
        return {"turn": self.turn, "units": units, "dests": dests, "builds": builds}

    def turn_state(self, pid=None):
        return {"turn": self.turn, "active_player": self.seat, "my_turn": True, "todo": {"units": []}}

    # -- the actions, as the game would carry them out
    def _step(self, u, x, y):
        while u["moves"] > 0 and (u["x"], u["y"]) != (x, y):
            if u["x"] != x:
                u["x"] += 1 if x > u["x"] else -1
            else:
                u["y"] += 1 if y > u["y"] else -1
            u["moves"] -= 1

    def move_unit(self, unit_id, x, y, pid=None, settle_timeout=1.0):
        self.calls.append(("move_unit", unit_id, x, y))
        if self.refuse:
            err, self.refuse = self.refuse, None
            return {"ok": False, "err": err}
        u = self.units[unit_id]
        u["activity"] = "MISSION"
        u.pop("build", None)
        self._step(u, x, y)
        if (u["x"], u["y"]) == (x, y):
            self.pending.pop(unit_id, None)
            u["activity"] = "AWAKE"
            return {"ok": True, "x": x, "y": y, "arrived": True, "moves": u["moves"]}
        self.pending[unit_id] = (x, y)
        return {"ok": True, "x": u["x"], "y": u["y"], "queued": True, "going_to": {"x": x, "y": y}}

    def unit_mission(self, unit_id, mission, x=-1, y=-1, data2=0, build=None, pid=None):
        self.calls.append(("unit_mission", unit_id, mission, build))
        if self.refuse:
            err, self.refuse = self.refuse, None
            return {"ok": False, "err": err}
        u = self.units[unit_id]
        self.pending.pop(unit_id, None)
        if mission == "MISSION_BUILD":
            u["build"], u["build_left"] = build, self.build_turns
            return {"ok": True, "build": build, "turns_left": self.build_turns}
        if mission == "MISSION_HEAL":
            u["activity"] = "HEAL"
        else:
            u["activity"] = "SLEEP_OR_FORTIFY"
        return {"ok": True}

    def end_turn(self):
        """The AIs move, then my next turn begins."""
        self.turn += 1
        for uid, u in self.units.items():
            if u.get("build"):
                u["build_left"] -= 1
                if u["build_left"] <= 0:
                    self.improved[(u["x"], u["y"])] = u.pop("build")
            if u.get("activity") == "HEAL":
                u["hp"] = min(u["max_hp"], u["hp"] + 20)
                if u["hp"] == u["max_hp"]:
                    u["activity"] = "AWAKE"
            u["moves"] = u["max_moves"]


class GameOrderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"CIV5_NOTES_DIR": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)

    def arrive(self, g):
        """The turn-start window as _arrive runs it (without the rest of the hand-off)."""
        g.end_turn()
        return g._turn_start_orders(g.turn_state())

    def test_move_then_build_across_turns(self):
        g = SimGame()
        r = g.give_order(7, [{"kind": "move", "x": 5, "y": 2}, {"kind": "build", "build": "FARM"}],
                         purpose="farm the river plot")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["did"], ["move to (5,2): issued"])
        self.assertEqual((r["order"]["state"], r["order"]["now"]), ("moving", "move to (5,2)"))
        self.assertEqual(g.pending, {7: (5, 2)}, "the order's standing move")
        out = self.arrive(g)
        row = out["rows"][0]
        self.assertEqual(row["did"], ["move to (5,2): issued", "move to (5,2): done", "build FARM at (5,2): issued"],
                         "arrived with a move left: the build starts the same turn")
        self.assertEqual(row["state"], "building")
        self.arrive(g)
        out = self.arrive(g)
        self.assertEqual(out["rows"][0]["status"], "completed")
        self.assertEqual(g.improved, {(5, 2): "BUILD_FARM"})
        self.assertEqual(len(g.calls), 3, "three calls made for me over four turns")
        self.assertEqual(g.orders("closed")["orders"][0]["issued_count"], 3)
        self.assertIsNone(self.arrive(g), "nothing open: no read at all")

    def test_heal_then_move(self):
        g = SimGame()
        g.units[7]["hp"] = 40
        r = g.give_order(7, [{"kind": "heal", "hp": 80}, {"kind": "move", "x": 3, "y": 2}, "hold"])
        self.assertEqual(r["order"]["state"], "healing")
        self.arrive(g)                                   # 60
        out = self.arrive(g)                             # 80: moves on and holds, same turn
        self.assertEqual(out["rows"][0]["status"], "completed", out)
        self.assertEqual([c[0:3] for c in g.calls][-2:], [("move_unit", 7, 3), ("unit_mission", 7, "MISSION_FORTIFY")])

    def test_a_first_step_that_cannot_run_is_refused_and_nothing_stored(self):
        g = SimGame()
        g.blocked[(6, 2)] = "destination plot is a mountain"
        r = g.give_order(7, [{"kind": "move", "x": 6, "y": 2}])
        self.assertFalse(r["ok"])
        self.assertIn("mountain", r["err"])
        g.cant_build.add((2, 2))
        self.assertFalse(g.give_order(7, [{"kind": "build", "build": "FARM"}])["ok"])
        self.assertIn("not a build", g.give_order(7, [{"kind": "build", "build": "CASTLE"}])["err"])
        self.assertIn("not mine", g.give_order(99, ["heal"])["err"])
        self.assertEqual(g.orders("all")["count"], 0)
        self.assertEqual(g.calls, [])

    def test_a_blocked_destination_mid_order_pauses_and_releases_the_move(self):
        g = SimGame()
        g.give_order(7, [{"kind": "move", "x": 6, "y": 2}])
        g.blocked[(6, 2)] = "destination is inside Persia's borders and you have no open-borders agreement"
        row = self.arrive(g)["rows"][0]
        self.assertEqual((row["status"], row["pause"]["kind"]), ("paused", "destination"))
        self.assertEqual(g.pending, {}, "the unit stops: the order's standing move is dropped")
        self.assertEqual(len(g.calls), 1, "no step after the pause")

    def test_a_hostile_in_sight_pauses_before_any_step_and_resume_acknowledges_it(self):
        g = SimGame()
        g.give_order(7, [{"kind": "move", "x": 8, "y": 2}, {"kind": "build", "build": "FARM"}])
        g.hostiles.append({"id": 40, "owner_id": 63, "owner": "Barbarians", "unit": "BRUTE", "x": 6, "y": 3})
        calls = len(g.calls)
        out = self.arrive(g)
        row = out["rows"][0]
        self.assertEqual((row["status"], row["pause"]["kind"]), ("paused", "hostile"))
        self.assertEqual(len(g.calls), calls, "the interrupted sequence took no other step")
        self.assertEqual(g._wake_reasons({"orders": out}, {}), ["order:1:paused"])
        self.assertIsNone(self.arrive(g)["rows"][0].get("did"), "a paused order does not run")
        r = g.resume_order(1)
        self.assertEqual(r["did"], ["move to (8,2): issued"])
        self.assertEqual(r["order"]["status"], "active")
        g.hostiles.append({"id": 41, "owner_id": 63, "owner": "Barbarians", "unit": "ARCHER", "x": 8, "y": 3})
        self.assertEqual(self.arrive(g)["rows"][0]["pause"]["hostiles"][0]["id"], 41, "only a new one pauses it")

    def test_existing_hostiles_are_acknowledged_when_the_order_is_given(self):
        g = SimGame()
        g.hostiles.append({"id": 40, "owner_id": 63, "owner": "Barbarians", "unit": "BRUTE", "x": 3, "y": 3})
        r = g.give_order(7, [{"kind": "move", "x": 8, "y": 2}])
        self.assertEqual(r["acknowledged_hostiles"][0]["id"], 40)
        self.assertEqual(r["order"]["status"], "active")

    def test_damage_pauses(self):
        g = SimGame()
        g.give_order(7, [{"kind": "move", "x": 8, "y": 2}])
        g.units[7]["hp"] = 70
        self.assertEqual(self.arrive(g)["rows"][0]["pause"]["kind"], "damaged")

    def test_a_refused_step_pauses_with_the_refusal(self):
        g = SimGame()
        g.refuse = "unit did not move: the engine found no path"
        r = g.give_order(7, [{"kind": "move", "x": 8, "y": 2}])
        self.assertEqual(r["order"]["status"], "paused")
        self.assertIn("no path", r["order"]["pause"]["reason"])
        self.assertFalse(r["order"]["last"]["ok"])

    def test_no_progress_pauses_instead_of_retrying_forever(self):
        g = SimGame()
        g.give_order(7, [{"kind": "move", "x": 8, "y": 2}])
        g.units[7].update({"x": 2, "y": 2})          # the engine dropped the path: back where it was issued
        g.pending.clear()
        g.units[7]["x"] = 2
        o = g.notebook().orders("open")[0]
        o["issued"]["x"], o["issued"]["y"] = 2, 2
        g.notebook().put_order(o)
        self.assertEqual(self.arrive(g)["rows"][0]["pause"]["kind"], "no_progress")

    def test_arrival_without_moves_waits_explicitly(self):
        g = SimGame()
        g.units[7]["moves"] = 0
        r = g.give_order(7, [{"kind": "move", "x": 3, "y": 2}])
        self.assertEqual((r["order"]["state"], g.calls), ("no_moves", []))
        self.assertEqual(self.arrive(g)["rows"][0]["status"], "completed")

    def test_a_lost_unit_fails_the_order(self):
        g = SimGame()
        g.give_order(7, [{"kind": "move", "x": 8, "y": 2}])
        del g.units[7]
        row = self.arrive(g)["rows"][0]
        self.assertEqual((row["status"], row["pause"]["kind"]), ("failed", "unit_gone"))

    def test_cancel_and_replace(self):
        g = SimGame()
        g.give_order(7, [{"kind": "move", "x": 8, "y": 2}])
        self.assertFalse(g.give_order(7, ["heal"])["ok"], "one owner per unit")
        r = g.cancel_order(1, note="plans changed")
        self.assertEqual(r["standing_move_dropped"], {"x": 8, "y": 2})
        self.assertEqual(g.pending, {})
        self.assertFalse(g.cancel_order(1)["ok"])
        g.give_order(7, [{"kind": "move", "x": 8, "y": 2}])
        r = g.give_order(7, [{"kind": "move", "x": 2, "y": 4}], replace_id=2)
        self.assertEqual(r["replaced"], 2)
        self.assertEqual([o["status"] for o in g.notebook().orders("all")], ["cancelled", "replaced", "active"])

    def test_a_direct_command_takes_the_unit_back(self):
        g = SimGame()
        g.give_order(7, [{"kind": "move", "x": 8, "y": 2}])
        p = g.note_manual_order(7, "unit_mission")
        self.assertEqual((p["id"], p["status"]), (1, "paused"))
        self.assertIsNone(g.note_manual_order(7, "move_unit"), "already paused")
        self.assertIsNone(g.note_manual_order(8, "move_unit"), "no order on that unit")
        calls = len(g.calls)
        self.arrive(g)
        self.assertEqual(len(g.calls), calls, "the order never fights the command")

    def test_a_restart_after_a_step_completed_does_not_replay_it(self):
        g = SimGame()
        g.give_order(7, [{"kind": "move", "x": 6, "y": 2}, {"kind": "build", "build": "FARM"}])
        self.assertEqual((g.units[7]["x"], g.pending), (4, {7: (6, 2)}), "on its way")
        g.units[7]["x"] = 6                           # the engine carried the standing move to its end
        g.pending.clear()
        g2 = SimGame()                                # a new session: same game, same seat, same notebook
        g2.units, g2.turn, g2.pending = g.units, g.turn, g.pending
        out = self.arrive(g2)
        self.assertEqual(out["rows"][0]["did"], ["move to (6,2): done", "build FARM at (6,2): issued"])
        self.assertEqual([c[0] for c in g2.calls], ["unit_mission"], "the move is not issued again")

    def test_a_harness_that_died_mid_step_pauses_instead_of_replaying(self):
        g = SimGame()
        g.give_order(7, [{"kind": "move", "x": 8, "y": 2}], start=False)
        nb = g.notebook()
        o = nb.orders("open")[0]
        o["inflight"] = {"turn": 10, "step": 0, "what": "move to (8,2)"}
        nb.put_order(o)
        row = self.arrive(g)["rows"][0]
        self.assertEqual(row["pause"]["kind"], "uncertain")
        self.assertEqual(g.calls, [])
        self.assertEqual(g.resume_order(1)["did"], ["move to (8,2): issued"])

    def test_a_loaded_save_pauses(self):
        g = SimGame()
        g.give_order(7, [{"kind": "move", "x": 8, "y": 2}])
        g.turn = 5
        self.assertEqual(g.run_orders()[0]["pause"]["kind"], "turn_went_back")
        self.assertEqual(g.resume_order(1)["order"]["status"], "active")

    def test_hotseat_isolation(self):
        a, b = SimGame(seat=0), SimGame(seat=1)
        a.give_order(7, [{"kind": "move", "x": 8, "y": 2}])
        self.assertEqual(b.orders()["count"], 0)
        self.assertIsNone(self.arrive(b), "seat 1's turn start runs nothing of seat 0's")
        self.assertIsNone(b.note_manual_order(7, "move_unit"), "the same unit id on seat 1 is another unit")
        self.assertEqual(a.orders()["orders"][0]["status"], "active")

    def test_the_turn_claim_gates_the_window(self):
        from harness.turn_claim import ClaimRefused
        g = SimGame()
        g.give_order(7, [{"kind": "move", "x": 8, "y": 2}])

        def held(turn, tool, force=False):
            raise ClaimRefused("another client holds the turn", {"pid": 1})
        g.claim = held
        calls = len(g.calls)
        out = self.arrive(g)
        self.assertIn("not_run", out)
        self.assertEqual(len(g.calls), calls)
        self.assertIn("orders_not_run", g._wake_reasons({"orders": out}, {}))

    def test_arrive_skips_owned_units_in_resume_moves_and_tags_todo(self):
        g = SimGame()
        g.give_order(7, [{"kind": "move", "x": 8, "y": 2}])
        g.enemy_on.add((8, 2))
        g.end_turn()
        g.expiring_city_states = lambda: []
        g.turn_state = lambda pid=None: {"turn": g.turn, "active_player": 0, "my_turn": True,
                                         "todo": {"units": [{"id": 7, "type": "WORKER"}]}}
        ts = g._arrive(g.turn_state())
        self.assertIn("return H.resume_moves(0, {7})", g.lua)
        self.assertEqual(ts["orders"]["paused"], 1)
        self.assertEqual(ts["todo"]["units"][0]["order"]["id"], 1)
        self.assertIn("never attacks", ts["todo"]["units"][0]["order"]["reason"])


class McpOrderTests(unittest.TestCase):
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
        g = SimGame()
        g.ts = {"turn": 10, "active_player": 0, "my_turn": True, "paused": False, "processing": False}
        g.turn_state = lambda pid=None: dict(g.ts)
        g.has_state = lambda name: True
        g.discussion_pending = lambda: False
        g.lock = contextlib.nullcontext
        self.g = g
        mcp_server._game = g

    def _call(self, tool, args):
        result = asyncio.run(self.m.mcp.call_tool(tool, args))
        text = result[0].text if isinstance(result, (list, tuple)) else result.content[0].text
        return json.loads(text)

    def test_the_tools_and_a_direct_command(self):
        r = self._call("give_order", {"unit_id": 7, "steps": [{"kind": "move", "x": 8, "y": 2}, "hold"]})
        self.assertTrue(r["ok"], r)
        self.assertEqual(self._call("orders", {})["orders"][0]["now"], "move to (8,2)")
        r = self._call("move_unit", {"unit_id": 7, "x": 3, "y": 3})
        self.assertEqual(r["order_paused"]["id"], 1)
        r = self._call("resume_order", {"order_id": 1})
        self.assertEqual(r["order"]["status"], "active", r)
        self.g.ts = {**self.g.ts, "active_player": 1, "my_turn": False}
        self.assertFalse(self._call("resume_order", {"order_id": 1})["ok"], "runs only on my turn")
        self.assertTrue(self._call("orders", {"status": "all"})["ok"], "the stored orders: any time")
        self.assertTrue(self._call("cancel_order", {"order_id": 1})["ok"], "cancelling: any time")


if __name__ == "__main__":
    unittest.main()
