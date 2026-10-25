"""Stage 3 of "A seat bound to its channel" (docs/ROADMAP.md): tunerd writes the Lua of a named runtime call with
the connection's own seat, and a seat-bound client sends nothing else to InGame.

The pieces, each on its own: the wire text (harness/lua_wire.py), the slot table generated at build
(harness/runtime_source.py), the dispatcher in the game (harness/lua/runtime/dispatch.lua, under Lua 5.1), the
client's rendering and routing (Game.h / Game.hs / Game.q), the daemon's `call` and `runtime` ops and its free-Lua
policy (harness/tunerd.py Bridge), the socket round trip, and a whole turn played through `call` only.
"""
import ast
import json
import pathlib
import re
import unittest
from unittest import mock

from harness import lua_wire, runtime_source
from harness.client import Civ5, TunerdError
from harness.game import Game, LuaCall
from harness.game_parts.support import SEAT_SLOTS
from harness.tuner import ExecResult, LuaError
from harness.tunerd import Bridge, SeatTable, gate
from test_runtime_source import FAKE_GAME, lua_5_1
from test_tunerd_seats import _Daemon


class WireTests(unittest.TestCase):
    def test_a_call_is_the_dispatcher_with_the_seat_and_the_argument_count(self):
        self.assertEqual(lua_wire.call_lua("tactical_view", 1, [5, None, "full"]),
                         'return H._call("tactical_view", 1, {5, nil, "full"}, 3)')
        self.assertEqual(lua_wire.call_lua("H.turn_state", 0), 'return H._call("turn_state", 0, {}, 0)')
        self.assertEqual(lua_wire.calls_lua(2, [["unit_pos", [5]], {"fn": "automate_check", "args": [7]}]),
                         'return {H._call("unit_pos", 2, {5}, 1), H._call("automate_check", 2, {7}, 1)}')

    def test_a_name_that_is_not_an_entry_or_arguments_that_are_not_json_are_refused(self):
        for bad in ("H.turn_state(0)", "_call", "H._seat_slot", "turn; state", 7, None, "H.x.y"):
            with self.assertRaises(lua_wire.CallError, msg=repr(bad)):
                lua_wire.call_lua(bad, 0)
        with self.assertRaises(lua_wire.CallError):
            lua_wire.call_lua("turn_state", 0, {"not": "a list"})
        with self.assertRaises(lua_wire.CallError):
            lua_wire.calls_lua(0, [])
        with self.assertRaises(lua_wire.CallError):
            lua_wire.calls_lua(0, [("unit_pos", [1], "extra")])

    def test_strings_travel_as_lua_literals_whatever_they_hold(self):
        body = lua_wire.call_lua("remember", 0, ['a "quoted" note\nwith a newline', {"k": [1, True, None]}])
        self.assertIn('"a \\"quoted\\" note\\nwith a newline"', body)
        self.assertIn('{["k"]={1, true, nil}}', body)

    def test_the_chunk_helpers_keep_their_contract_under_their_new_home(self):
        self.assertIs(Game.string_chunks, lua_wire.string_chunks)
        self.assertEqual(Game.command_budget(), lua_wire.command_budget())
        self.assertTrue(lua_wire.query_fits_inline("return 1"))
        self.assertFalse(lua_wire.query_fits_inline("x" * 5000))


class SlotTableTests(unittest.TestCase):
    def setUp(self):
        self.src = runtime_source.snapshot()

    def test_every_pid_entry_has_its_slot_and_nothing_else_does(self):
        names = runtime_source.entry_names(self.src.fragments)
        self.assertEqual(self.src.slots["turn_state"], 1)
        self.assertEqual(self.src.slots["move_unit"], 4)
        self.assertEqual(self.src.slots["tactical_view"], 2)
        self.assertNotIn("vote_gate", self.src.slots)
        self.assertNotIn("reference", self.src.slots)
        self.assertTrue(set(self.src.slots) <= names)
        self.assertGreater(len(self.src.slots), 190)

    def test_the_seat_free_list_names_real_entries_with_no_seat(self):
        names = runtime_source.entry_names(self.src.fragments)
        for name in runtime_source.SEAT_FREE:
            self.assertIn(name, names, name)
            self.assertNotIn(name, self.src.slots, f"{name} takes a seat: not seat-free")

    def test_the_installer_ships_the_tables_before_the_hash(self):
        lua = self.src.install_lua("__SRC")
        self.assertIn('H._seat_slot = {["accept_deal"]=1', lua)
        self.assertIn('H._seat_free = {["reference"]=true', lua)
        self.assertLess(lua.index("H._seat_slot"), lua.index("H.source_hash"))

    def test_the_three_former_exceptions_take_the_seat_now(self):
        for name in ("diplo_event", "plot_units", "plots_around"):
            self.assertIn(name, self.src.slots, name)
        self.assertEqual(self.src.slots["diplo_event"], 1)


class PythonNamesOnlyEntriesTests(unittest.TestCase):
    """What the Python side sends: every `Game.h("<name>", ...)` names an entry with a slot or on the seat-free
    list, and no Lua text goes to InGame from anywhere but the transport itself."""

    FILES = sorted(pathlib.Path("harness/game_parts").glob("*.py")) + [pathlib.Path("harness/game.py"),
                                                                     pathlib.Path("harness/compare.py")]

    def test_every_named_call_is_a_runtime_entry_the_dispatcher_admits(self):
        names = set()
        for path in self.FILES:
            for m in re.finditer(r"""self\.h\(\s*['"](\w+)['"]""", path.read_text()):
                names.add(m.group(1))
            for m in re.finditer(r"""\(['"](\w+)['"],\s*int\(""", path.read_text()):   # compare.call_spec
                names.add(m.group(1))
        self.assertGreater(len(names), 150)
        bad = sorted(n for n in names if n not in SEAT_SLOTS and n not in runtime_source.SEAT_FREE)
        self.assertEqual(bad, [], "named from Python but neither a pid entry nor seat-free")

    def test_no_lua_text_reaches_ingame_from_a_game_part(self):
        offenders = []
        for path in self.FILES:
            src = path.read_text()
            for node in ast.walk(ast.parse(src)):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                attr = node.func.attr
                if attr in ("q", "_order") and node.args and isinstance(node.args[0], (ast.Constant, ast.JoinedStr, ast.BinOp)):
                    offenders.append(f"{path}:{node.lineno} {attr}(<text>)")
                if attr in ("query", "exec", "lua") and node.args and isinstance(node.args[0], ast.Constant) \
                        and node.args[0].value == "InGame" and path.name != "game.py":
                    offenders.append(f"{path}:{node.lineno} {attr}('InGame', ...)")
        self.assertEqual(offenders, [])


class DispatcherTests(unittest.TestCase):
    """dispatch.lua under the game's own Lua (5.1): the seat lands in the slot, nothing of the caller's does."""

    def setUp(self):
        self.lua = lua_5_1()
        if self.lua is None:
            self.skipTest("this lupa build has no Lua 5.1 / LuaJIT runtime")
        self.lua.execute(FAKE_GAME)
        src = runtime_source.snapshot()
        self.lua.globals()["__H_SRC"] = src.text
        self.lua.execute(src.install_lua("__H_SRC"))
        self.lua.execute("""
            H.probe = function(a, pid, b) return { a = a, pid = pid, b = b, n = select('#', a, pid, b) } end
            H._seat_slot.probe = 2
            H.first = function(pid, x) return { pid = pid, x = x } end
            H._seat_slot.first = 1
            H.free_probe = function(x) return { x = x } end
            H._seat_free.free_probe = true
        """)

    def call(self, body):
        return self.lua.execute("return H.json((function() " + body + " end)())")

    def test_the_seat_is_inserted_at_the_slot(self):
        r = json.loads(self.call('return H._call("probe", 9, {1, "x"}, 2)'))
        self.assertEqual(r, {"a": 1, "pid": 9, "b": "x", "n": 3})
        r = json.loads(self.call('return H._call("first", 4, {"y"}, 1)'))
        self.assertEqual(r, {"pid": 4, "x": "y"})

    def test_a_nil_argument_keeps_its_place(self):
        r = json.loads(self.call('return H._call("probe", 9, {1, nil}, 2)'))
        self.assertEqual(r["a"], 1)
        self.assertEqual(r["pid"], 9)
        self.assertNotIn("b", r)
        self.assertEqual(r["n"], 3)
        r = json.loads(self.call('return H._call("probe", 9, {nil, "x"}, 2)'))
        self.assertEqual(r["b"], "x")
        self.assertNotIn("a", r)

    def test_a_caller_cannot_put_anything_in_the_seat_slot(self):
        r = json.loads(self.call('return H._call("first", 4, {7, "y"}, 2)'))
        self.assertEqual(r["pid"], 4, "the first argument of the caller's is shifted behind the seat")
        self.assertEqual(r["x"], 7)

    def test_refusals_name_the_entry(self):
        for body, needle in (('return H._call("no_such", 0, {}, 0)', "no runtime entry H.no_such"),
                             ('return H._call("vote_gate", 0, {1, 2}, 2)', "not callable from outside"),
                             ('return H._call("probe", 0, {}, 0)', "takes 1 argument(s) before the seat")):
            r = json.loads(self.call(body))
            self.assertFalse(r["ok"])
            self.assertIn(needle, r["err"])

    def test_a_seat_free_entry_gets_no_seat(self):
        self.assertEqual(json.loads(self.call('return H._call("free_probe", 3, {"q"}, 1)')), {"x": "q"})
        r = json.loads(self.call('return H._call("reference", 3, {"nothing"}, 1)'))
        self.assertIsInstance(r, dict)

    def test_the_shipped_tables_match_the_source(self):
        src = runtime_source.snapshot()
        got = json.loads(self.lua.execute("return H.json(H._seat_slot)"))
        got.pop("probe"); got.pop("first")
        self.assertEqual(got, src.slots)


class _RecordingClient:
    """The real client's surface as a seat-bound daemon would show it: call_fn/calls/runtime recorded, Lua text
    to InGame refused like tunerd refuses it."""

    def __init__(self, seat=0, answers=None):
        self.seat = seat
        self.requests = []
        self.answers = answers or {}
        self.trips = 0

    def call_fn(self, fn, args=None, seat=None, timeout=None):
        self.requests.append({"op": "call", "fn": fn, "args": list(args or []), "seat": seat})
        a = self.answers.get(fn, {"ok": True})
        return a(args) if callable(a) else a

    def calls(self, calls, seat=None, timeout=None):
        out = [self.call_fn(fn, args, seat) for fn, args in calls]
        self.requests.append({"op": "call", "calls": calls, "seat": seat})
        return out

    def runtime(self, force=False):
        self.requests.append({"op": "runtime", "force": force})
        return {"ok": True, "version": 1, "installed": False}

    def query(self, state, lua, timeout=None):
        self.requests.append({"op": "query", "state": state})
        if state == "InGame":
            raise TunerdError("free Lua to InGame on a bound connection")
        return None

    def exec(self, state, lua, timeout=None, check=True):
        self.requests.append({"op": "exec", "state": state})
        if state == "InGame":
            raise TunerdError("free Lua to InGame on a bound connection")
        return []

    def states(self):
        return {1: "InGame"}


class GameRenderingTests(unittest.TestCase):
    def game(self, seat=0, client=None):
        g = Game.__new__(Game)
        g.seat = seat
        g.c = client if client is not None else _RecordingClient(seat)
        g._runtime_ok = True
        return g

    def test_h_renders_the_lua_the_daemon_will_run_and_carries_the_call(self):
        g = self.game(3)
        c = g.h("tactical_view", 5, 2, "full")
        self.assertIsInstance(c, LuaCall)
        self.assertEqual(str(c), 'return H.tactical_view(5, 3, 2, "full")')
        self.assertEqual((c.fn, c.args, c.calls), ("tactical_view", [5, 2, "full"], None))
        self.assertEqual(str(g.h("move_unit", 7, 1, 2, pid=1)), "return H.move_unit(7, 1, 2, 1)")
        self.assertEqual(str(g.h("reference", "units")), 'return H.reference("units")')
        b = g.hs([("unit_pos", 5), ("automate_check", 6)])
        self.assertEqual(str(b), "return {H.unit_pos(5, 3), H.automate_check(6, 3)}")
        self.assertEqual(b.calls, [["unit_pos", [5]], ["automate_check", [6]]])

    def test_a_name_without_a_slot_or_too_few_arguments_is_a_programming_error(self):
        g = self.game()
        with self.assertRaises(ValueError):
            g.h("vote_gate", 1, 2)
        with self.assertRaises(ValueError):
            g.h("no_such_entry")
        with self.assertRaises(ValueError):
            g.h("move_unit", 7)   # the seat is the 4th parameter: three of the caller's come first

    def test_q_sends_a_named_call_and_refuses_text_on_a_bound_connection(self):
        c = _RecordingClient(seat=2, answers={"turn_state": {"turn": 5}})
        g = self.game(2, c)
        self.assertEqual(g.q(g.h("turn_state")), {"turn": 5})
        self.assertEqual(c.requests[-1], {"op": "call", "fn": "turn_state", "args": [], "seat": 2})
        g.q(g.hs([("unit_pos", 5)]))
        self.assertEqual(c.requests[-1]["calls"], [["unit_pos", [5]]])
        with self.assertRaises(TunerdError):
            g.q("return Players[0]:GetGold()")
        self.assertEqual(c.requests[-1]["op"], "call", "the refusal happened before any trip")

    def test_a_bound_game_takes_its_seat_from_the_daemon_and_installs_nothing(self):
        c = _RecordingClient(seat=1)
        g = self.game(0, c)
        g._runtime_ok = False
        g.ensure_runtime()
        self.assertEqual(c.requests, [{"op": "runtime", "force": False}])
        self.assertTrue(g._runtime_ok and g._popup_shim_ok)
        g3 = Game.__new__(Game); g3.sock_path = None; g3.seat = 0
        with mock.patch("harness.game.Civ5", lambda *a, **k: c):
            Game.__post_init__(g3)
        self.assertEqual(g3.seat, 1, "the binding is the seat")

    def test_a_double_without_call_fn_gets_the_rendered_text(self):
        seen = []

        class Old:
            def query(self, state, lua, timeout=None):
                seen.append((state, lua)); return 1
        g = self.game(0, Old())
        g.q(g.h("gold_now"))
        self.assertEqual(seen, [("InGame", "return H.gold_now(0)")])


class _StubTuner:
    """TunerClient as the bridge sees it: states, execute, query -- recording every command."""

    def __init__(self, states=None, installed=False, active=0):
        self.states = states if states is not None else {1: "InGame", 2: "GenericPopup", 3: "LeaderHeadRoot"}
        self.sent = []
        self.installed = installed
        self.shim = False
        self.active = active
        self.fail_once = None

    def find_state(self, name, refresh=False, last=True):
        ids = [i for i, n in self.states.items() if n == name]
        if not ids:
            raise KeyError(f"no Lua state named {name!r}")
        return max(ids)

    def refresh_states(self):
        return self.states

    def execute(self, state, lua, timeout=None, raise_on_error=True):
        self.sent.append(("exec", state, lua))
        if lua.startswith("print(type(H) == 'table'"):
            return ExecResult(["true" if self.installed else "false"])
        if "harness_runtime_install" in lua:
            self.installed = True
        if "harness_popup_shim" in lua:
            self.shim = True
        return ExecResult([])

    def query(self, state, body, timeout=None):
        self.sent.append(("query", state, body))
        if body.startswith("return __H_BTN_SHIM"):
            return self.shim
        if body == "return Game.GetActivePlayer()":
            return self.active
        if self.fail_once:
            err, self.fail_once = self.fail_once, None
            raise LuaError(err)
        return {"ran": body}

    def ops(self):
        return [s[0] for s in self.sent]


class BridgeCallTests(unittest.TestCase):
    def bridge(self, tuner):
        b = Bridge("127.0.0.1", 0)
        b.client, b.states_ok = tuner, True
        return b

    def test_a_call_installs_the_runtime_once_then_runs_the_dispatcher_with_the_binding(self):
        t = _StubTuner()
        b = self.bridge(t)
        r = b.handle({"op": "call", "fn": "turn_state", "args": []}, seat=1)
        self.assertTrue(r["ok"])
        self.assertEqual(r["value"]["ran"], 'return H._call("turn_state", 1, {}, 0)')
        self.assertEqual(r["seat"], 1)
        self.assertTrue(t.installed and t.shim, "the daemon installed the runtime and the popup shim itself")
        n = len(t.sent)
        b.handle({"op": "call", "fn": "units", "args": [], "seat": 1}, seat=1)
        self.assertEqual([s for s in t.sent[n:]], [("query", "InGame", 'return H._call("units", 1, {}, 0)')],
                         "the second call is one trip: no check, no install")

    def test_an_installed_runtime_is_checked_once_and_a_changed_state_id_rechecked(self):
        t = _StubTuner(installed=True)
        b = self.bridge(t)
        probes = lambda: sum(1 for s in t.sent if s[0] == "exec" and s[2].startswith("print(type(H)"))
        b.handle({"op": "call", "fn": "turn_state"}, seat=0)
        self.assertEqual(probes(), 1, "one probe, no chunks")
        self.assertFalse(any("harness_runtime_install" in s[2] for s in t.sent))
        t.states = {5: "InGame"}
        b.handle({"op": "call", "fn": "turn_state"}, seat=0)
        self.assertEqual(probes(), 2, "a new InGame state id: probed again")

    def test_a_runtime_gone_from_a_kept_state_id_is_reinstalled_and_the_call_rerun(self):
        t = _StubTuner(installed=True)
        b = self.bridge(t)
        b.handle({"op": "call", "fn": "turn_state"}, seat=0)
        t.installed = False
        t.fail_once = "ERR:[string \"q\"]:1: attempt to index global 'H' (a nil value)"
        r = b.handle({"op": "call", "fn": "turn_state"}, seat=0)
        self.assertTrue(r["ok"], r)
        self.assertTrue(t.installed)
        self.assertEqual(t.ops().count("query"), 4, "the shim probe, the first run, the failed run, the rerun")

    def test_the_seat_rules(self):
        b = self.bridge(_StubTuner(installed=True))
        r = b.handle({"op": "call", "fn": "turn_state"}, seat=None)
        self.assertFalse(r["ok"]); self.assertIn("no seat", r["error"])
        r = b.handle({"op": "call", "fn": "turn_state", "seat": 1}, seat=None)
        self.assertTrue(r["ok"]); self.assertEqual(r["seat"], 1)
        r = b.handle({"op": "call", "fn": "turn_state", "seat": 1}, seat=0)
        self.assertFalse(r["ok"]); self.assertIn("bound to seat 0", r["error"]); self.assertEqual(r["seat"], 0)
        r = b.handle({"op": "call", "fn": "turn_state", "seat": "1"}, seat=None)
        self.assertFalse(r["ok"])
        r = b.handle({"op": "call", "fn": "H.turn_state(0)"}, seat=0)
        self.assertFalse(r["ok"]); self.assertIn("not the name of a runtime entry", r["error"])

    def test_a_batch_and_a_long_call_are_shipped_whole(self):
        t = _StubTuner(installed=True)
        b = self.bridge(t)
        r = b.handle({"op": "call", "calls": [["unit_pos", [5]], ["unit_pos", [7]]]}, seat=0)
        self.assertEqual(r["value"]["ran"], 'return {H._call("unit_pos", 0, {5}, 1), H._call("unit_pos", 0, {7}, 1)}')
        r = b.handle({"op": "call", "fn": "remember", "args": ["x" * 4000]}, seat=0)
        self.assertTrue(r["ok"])
        last = t.sent[-1]
        self.assertEqual(last[0], "query")
        self.assertIn("loadstring(src, 'q')", last[2], "shipped in chunks and compiled in the game")
        self.assertTrue(all(len(s[2].encode()) <= lua_wire.command_budget() for s in t.sent if s[0] == "exec"))

    def test_the_runtime_op(self):
        t = _StubTuner()
        b = self.bridge(t)
        r = b.handle({"op": "runtime"}, seat=0)
        self.assertTrue(r["ok"] and r["installed"] and r["popup_shim"])
        self.assertEqual(r["version"], runtime_source.snapshot().version)
        r = b.handle({"op": "runtime"}, seat=0)
        self.assertFalse(r["installed"])
        r = b.handle({"op": "runtime", "force": True}, seat=0)
        self.assertTrue(r["installed"])

    def test_free_lua_on_a_bound_connection(self):
        t = _StubTuner(installed=True, active=1)
        b = self.bridge(t)
        r = b.handle({"op": "query", "state": "InGame", "lua": "return 1"}, seat=1)
        self.assertFalse(r["ok"]); self.assertIn("named runtime calls", r["error"])
        r = b.handle({"op": "exec", "state": 1, "lua": "print(1)"}, seat=1)
        self.assertFalse(r["ok"], "InGame by id is InGame")
        r = b.handle({"op": "query", "state": "GenericPopup", "lua": "return __H_popup_state()"}, seat=1)
        self.assertTrue(r["ok"], "the active seat may read its own screen")
        r = b.handle({"op": "query", "state": "GenericPopup", "lua": "return __H_popup_state()"}, seat=0)
        self.assertFalse(r["ok"]); self.assertIn("not the active player", r["error"]); self.assertEqual(r["active_player"], 1)
        r = b.handle({"op": "exec", "state": "LeaderHeadRoot", "lua": "OnPropose()"}, seat=0)
        self.assertFalse(r["ok"])
        r = b.handle({"op": "query", "state": "InGame", "lua": "return 1"}, seat=None)
        self.assertTrue(r["ok"], "a daemon without a binding forwards as before")

    def test_the_front_end_stays_open_to_a_bound_connection(self):
        t = _StubTuner(states={7: "MainMenu", 8: "StagingRoom"}, installed=True)
        b = self.bridge(t)
        r = b.handle({"op": "exec", "state": "StagingRoom", "lua": "PreGame.SetGameName('x')"}, seat=0)
        self.assertTrue(r["ok"])
        r = b.handle({"op": "call", "fn": "turn_state"}, seat=0)
        self.assertFalse(r["ok"]); self.assertIn("InGame", r["error"])


class GateCallTests(unittest.TestCase):
    def test_call_and_runtime_need_a_binding_on_a_daemon_with_a_table(self):
        table = SeatTable([{"seat": 0, "token": "x" * 16}])
        for op in ("call", "runtime"):
            self.assertTrue(gate({"op": op}, table, None, False)[0]["unbound"], op)
            self.assertIsNone(gate({"op": op}, table, 0, False)[0], op)
            self.assertIsNone(gate({"op": op}, None, None, True)[0], op)


class SocketCallTests(unittest.TestCase):
    def test_the_harness_client_sends_a_call_and_the_bridge_sees_its_seat(self):
        import os
        import tempfile
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        path = os.path.join(d.name, "t.sock")
        daemon = _Daemon(path, SeatTable([{"seat": 1, "token": "t" * 20}]))
        daemon.start(); self.addCleanup(daemon.stop)
        c = Civ5(path, token="t" * 20)
        self.assertEqual(c.seat, 1)
        self.assertTrue(c.bound)
        c.call_fn("turn_state", [], seat=1)
        c.calls([("unit_pos", [5])], seat=1)
        c.runtime()
        ops = [(req["op"], seat) for req, seat in daemon.bridge.seen]
        self.assertEqual(ops, [("call", 1), ("call", 1), ("runtime", 1)])
        self.assertEqual(daemon.bridge.seen[0][0]["args"], [])
        self.assertEqual(daemon.bridge.seen[1][0]["calls"], [["unit_pos", [5]]])


class TurnThroughCallsOnlyTests(unittest.TestCase):
    """A turn's worth of Game methods against a seat-bound client that refuses any Lua text to InGame: every
    trip the loop makes is a named call. The answers are the shapes the runtime gives; what is checked is the
    wire, not the game."""

    def setUp(self):
        status = {"turn": 40, "active_player": 0, "my_turn": True, "processing": False, "paused": False, "mode": "single",
                  "hotseat": False, "blocking": -1, "blocking_name": "NO_ENDTURN_BLOCKING_TYPE", "pending_popups": [],
                  "todo": {"units": [], "cities": [], "promotions": [], "research_unset": False},
                  "leader_greeting_pending": False, "city_state_greeting_pending": False, "discussion_pending": False,
                  "great_person_reward_pending": False, "tech_popup_pending": False, "alerts": [], "screens": {}}
        self.status = status
        self.ended = []
        self.pos = {"x": 1, "y": 1}    # the unit moves when move_unit lands, as the engine's would
        answers = {
            "turn_state": lambda a: dict(status),
            "modal_flags": {"screens": {}},
            "units": [{"id": 7, "type": "WARRIOR", "x": 1, "y": 1, "moves": 2}],
            "cities": [{"id": 3, "name": "Assur", "population": 4}],
            "todo_actions": {"ok": True, "units": [], "n": 0},
            "move_unit": lambda a: self._move(a),
            "unit_pos": lambda a: {"ok": True, "moves": 1, "activity": 0, **self.pos},
            "reveal_mark": {"ok": True}, "reveal_diff": {"ok": True, "revealed": []},
            "note_unit_by_id": True,
            "research_check": {"ok": True, "id": 9, "has_tech": False, "can": True, "current": -1, "free": 0},
            "send_research": {"ok": True},
            "research_after": {"ok": True, "current": 9, "research": "TECH_POTTERY", "has_tech": False, "free": 0, "queue": ["TECH_POTTERY"]},
            "production_check": {"ok": True, "id": 4}, "city_push_order": {"ok": True},
            "city_queue": {"ok": True, "production": "Warrior", "turns": 5, "queue": ["UNIT_WARRIOR"]},
            "pending_popups": [], "end_turn_send": lambda a: self._end_turn(a),
            "events_since": [], "take_events": [], "hp_snapshot": True, "note_units": True, "resume_moves": [],
            "expiring_city_states": [], "alerts_since": [], "current_research": 9,
        }
        self.c = _RecordingClient(seat=0, answers=answers)
        self.g = Game.__new__(Game)
        self.g.seat = 0
        self.g.c = self.c
        self.g._runtime_ok = False
        self.g.lock = __import__("contextlib").nullcontext
        self.g.claim = None

    def _move(self, args):
        """The engine's shape: the order answers with the unit where it stands; the move lands afterwards."""
        was = dict(self.pos)
        self.pos.update(x=args[1], y=args[2])
        return {"ok": True, "moves": 1, "activity": 0, **was}

    def _end_turn(self, args):
        self.ended.append(args)
        self.status["turn"] += 1
        return {"ok": True, "blocking_before": -1}

    def test_reads_orders_and_the_end_of_the_turn_are_named_calls(self):
        g, c = self.g, self.c
        sleep = mock.patch("harness.game.time.sleep")
        with sleep, mock.patch("harness.game_parts.units.time.sleep"), mock.patch("harness.game_parts.turn.time.sleep"), \
                mock.patch("harness.game_parts.cities.time.sleep"), mock.patch("harness.game_parts.policies.time.sleep"):
            self.assertEqual(g.turn_state()["turn"], 40)
            self.assertEqual(g.units()[0]["id"], 7)
            self.assertEqual(g.cities()[0]["name"], "Assur")
            self.assertTrue(g.todo_actions()["ok"])
            self.assertTrue(g.move_unit(7, 2, 1)["ok"])
            self.assertTrue(g.set_research("TECH_POTTERY")["ok"])
            self.assertTrue(g.set_production(3, "ORDER_TRAIN", "UNIT_WARRIOR")["ok"])
            r = g.end_turn(autosave=False)
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(self.ended, [[False]], "the end-turn order went out once, through the entry")
        ops = {req["op"] for req in c.requests}
        self.assertEqual(ops, {"runtime", "call"}, c.requests)
        self.assertTrue(all(req.get("seat") == 0 for req in c.requests if req["op"] == "call"))
        self.assertEqual(c.requests[0], {"op": "runtime", "force": False}, "the daemon installs, the client ships nothing")
        names = [req.get("fn") for req in c.requests if req["op"] == "call"]
        for must in ("turn_state", "units", "cities", "todo_actions", "move_unit", "research_check", "send_research",
                     "production_check", "city_push_order", "end_turn_send"):
            self.assertIn(must, names)


if __name__ == "__main__":
    unittest.main()
