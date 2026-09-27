"""The runtime loader (harness/runtime_source.py) and Game.ensure_runtime's reload semantics (GitLab #42).

The runtime is 38 fragments assembled into one chunk. These tests pin what the split must not change: one
authoritative source that production and the tests share; a digest that moves when any fragment moves; a
source hash set only once every definition ran; a reload that carries the accumulated state, resets the derived
caches and leaves exactly one live handler per hooked event; a failed load that is never accepted as current
and a corrected retry that neither duplicates handlers nor loses state. The game is a lupa state with a fake
Events table that counts handlers, driven through the real Game.ensure_runtime / load_lua chunking.
"""
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

from harness import runtime_source
from harness.client import TunerdError
from harness.game import Game, RUNTIME_VERSION

FAKE_GAME = """
loadstring = loadstring or load
__OUT = {}
print = function(...)
  local t = {}
  for i = 1, select('#', ...) do t[#t + 1] = tostring(select(i, ...)) end
  __OUT[#__OUT + 1] = table.concat(t, '\\t')
end
-- every Events.<Name> exists and counts its handlers; Remove is by identity, as the engine's is
Events = setmetatable({}, { __index = function(t, name)
  local ev = { handlers = {} }
  function ev.Add(fn) ev.handlers[#ev.handlers + 1] = fn end
  function ev.Remove(fn)
    for i, f in ipairs(ev.handlers) do if f == fn then table.remove(ev.handlers, i); return end end
  end
  rawset(t, name, ev)
  return ev
end })
Game = { GetActivePlayer = function() return 0 end, GetGameTurn = function() return 12 end }
Players = { [0] = { GetTeam = function() return 0 end } }
"""


def lua_5_1():
    """The game runs Lua 5.1. lupa's own 5.1 build (or LuaJIT, also 5.1) is the closest match, and it enforces
    5.1's compiler limits (200 locals and 60 upvalues per function) that a newer Lua would let slide."""
    import importlib
    for module in ("lupa.lua51", "lupa.luajit21", "lupa.luajit20"):
        try:
            return importlib.import_module(module).LuaRuntime()
        except ImportError:
            continue
    return None


class FakeTunerd:
    """exec against one lupa state the way tunerd answers: printed lines back, a Lua error as TunerdError."""

    def __init__(self, lua):
        import importlib
        self.lua = lua
        self.sent = []
        self.LuaError = importlib.import_module(type(lua).__module__).LuaError   # each lupa build has its own

    def exec(self, state, code, timeout=None, check=True):
        self.sent.append(code)
        try:
            self.lua.execute(code)
        except self.LuaError as e:
            raise TunerdError(str(e)) from e
        out = [str(line) for line in self.lua.globals()["__OUT"].values()]
        self.lua.execute("__OUT = {}")
        return out

    def loads(self):
        """The loadstring() commands sent: one per injection."""
        return [c for c in self.sent if "loadstring(" in c]


class SourceCopy(unittest.TestCase):
    def copy_source(self) -> pathlib.Path:
        """An editable copy of every fragment; snapshot(tmp) / patching RUNTIME_DIR point the loader at it."""
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="runtime-src-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for name in runtime_source.MANIFEST:
            shutil.copy(runtime_source.RUNTIME_DIR / name, tmp / name)
        return tmp


class SourceTests(SourceCopy):
    def test_the_manifest_is_the_directory(self):
        on_disk = sorted(p.name for p in runtime_source.RUNTIME_DIR.glob("*.lua"))
        self.assertEqual(sorted(runtime_source.MANIFEST), on_disk, "a fragment on disk is in MANIFEST and vice versa")
        self.assertEqual(len(set(runtime_source.MANIFEST)), len(runtime_source.MANIFEST))
        self.assertEqual(runtime_source.MANIFEST[0], "bootstrap.lua")
        self.assertEqual(runtime_source.MANIFEST[-1], "install.lua", "hooks are installed after every definition")

    def test_a_missing_fragment_is_named_before_anything_is_read(self):
        tmp = self.copy_source()
        (tmp / "map.lua").unlink()
        with self.assertRaises(runtime_source.RuntimeSourceError) as cm:
            runtime_source.snapshot(tmp)
        self.assertIn("map.lua", str(cm.exception))
        self.assertIn(str(tmp), str(cm.exception))

    def test_the_version_comes_from_bootstrap(self):
        s = runtime_source.snapshot()
        self.assertEqual(s.version, RUNTIME_VERSION)
        self.assertIn(f"local RUNTIME_VERSION = {s.version}\n", s.fragment("bootstrap.lua").text)

    def test_every_fragment_moves_the_digest(self):
        base = runtime_source.snapshot()
        seen = {base.digest}
        for name in runtime_source.MANIFEST:
            tmp = self.copy_source()
            with open(tmp / name, "a", encoding="utf-8") as f:
                f.write("\n-- an edit, no version bump\n")
            digest = runtime_source.snapshot(tmp).digest
            self.assertNotIn(digest, seen, f"editing {name} must change the digest")
            seen.add(digest)
        self.assertEqual(runtime_source.snapshot().digest, base.digest, "an unchanged source has a stable digest")

    def test_renaming_or_reordering_moves_the_digest(self):
        base = runtime_source.snapshot()
        swapped = list(runtime_source.MANIFEST)
        i, j = swapped.index("policies.lua"), swapped.index("notifications.lua")
        swapped[i], swapped[j] = swapped[j], swapped[i]
        self.assertNotEqual(runtime_source.snapshot(manifest=tuple(swapped)).digest, base.digest)
        tmp = self.copy_source()
        (tmp / "map.lua").rename(tmp / "plots.lua")
        renamed = tuple("plots.lua" if n == "map.lua" else n for n in runtime_source.MANIFEST)
        self.assertNotEqual(runtime_source.snapshot(tmp, renamed).digest, base.digest)

    def test_the_install_chunk_marks_the_source_current_last(self):
        s = runtime_source.snapshot()
        chunk = s.install_chunk()
        self.assertTrue(chunk.startswith(runtime_source.PRELUDE), "a changed source reloads even at the same version")
        self.assertEqual(chunk.rstrip("\n").split("\n")[-1], f"H.source_hash = '{s.digest}'")
        self.assertIn("H.install_hooks()", s.fragment("install.lua").text)
        self.assertEqual(s.text.count("\nH.install_hooks()\n"), 1, "hooks are installed from one place")

    def test_locate_names_the_fragment_and_its_own_line(self):
        s = runtime_source.snapshot()
        lines = s.text.split("\n")
        i = lines.index("-- @@ events.lua") + 1          # 1-based line of the boundary marker
        n = s.fragment("events.lua").lines
        self.assertEqual(s.locate(i), ("events.lua", 0))
        self.assertEqual(s.locate(i + 1), ("events.lua", 1))
        self.assertEqual(lines[i], s.fragment("events.lua").text.split("\n")[0])
        self.assertEqual(s.locate(i + n), ("events.lua", n))
        self.assertEqual(lines[i + n - 1], s.fragment("events.lua").text.split("\n")[n - 1])
        self.assertEqual(s.locate(i + n + 1), ("events.lua", n + 1), "the blank separator")
        self.assertEqual(s.locate(i + n + 2), ("empire.lua", 0))
        # errors from the installed chunk are one line further down (the prelude)
        self.assertEqual(s.locate_error(f'[string "harness_runtime"]:{i + 2}: attempt to call a nil value'), "events.lua:1")
        self.assertIsNone(s.locate_error("attempt to index a nil value"))
        self.assertIsNone(s.locate(0))


class EnsureRuntimeTests(SourceCopy):
    def setUp(self):
        try:
            import lupa  # noqa: F401
        except ImportError:
            self.skipTest("lupa not installed (uv sync --group dev)")
        self.lua = lua_5_1()
        if self.lua is None:
            self.skipTest("this lupa build has no Lua 5.1 / LuaJIT runtime")
        self.lua.execute(FAKE_GAME)
        self.c = FakeTunerd(self.lua)
        self.g = Game.__new__(Game)
        self.g.c = self.c
        self.g.seat = 0
        self.g._runtime_ok = False
        self.g.ensure_popup_shim = lambda: True   # GenericPopup is another Lua state, not under test here

    def lua_eval(self, expr):
        return self.lua.execute("return " + expr)

    def handlers(self) -> dict:
        return dict(self.lua.execute("local out = {} for name, ev in pairs(Events) do out[name] = #ev.handlers end return out").items())

    def using(self, directory):
        return mock.patch.object(runtime_source, "RUNTIME_DIR", directory)

    def assert_one_handler_per_event(self):
        h = self.handlers()
        self.assertGreaterEqual(len(h), 10, "the runtime hooks a dozen events")
        self.assertEqual({name: n for name, n in h.items() if n != 1}, {}, "exactly one live handler per event")

    def fire_chat(self, text):
        self.lua.execute(f"for _, fn in ipairs(Events.GameMessageChat.handlers) do fn(0, 1, '{text}', 0) end")

    def test_first_installation(self):
        self.g.ensure_runtime()
        s = runtime_source.snapshot()
        self.assertEqual(self.lua_eval("H.source_hash"), s.digest)
        self.assertEqual(self.lua_eval("H.version"), s.version)
        self.assertEqual(len(self.c.loads()), 1)
        self.assertTrue(self.lua_eval("type(H.turn_state) == 'function' and type(H.compare_production) == 'function'"))
        self.assert_one_handler_per_event()
        self.assertTrue(self.g._runtime_ok)
        self.fire_chat("hello")
        self.assertEqual(self.lua_eval("#H.events"), 1)

    def test_an_unchanged_source_is_reused(self):
        self.g.ensure_runtime()
        self.g._runtime_ok = False           # a new Game object, or wait_ingame: the game still has the runtime
        n = len(self.c.sent)
        self.g.ensure_runtime()
        self.assertEqual(len(self.c.sent), n + 1, "one check, no chunks")
        self.assertEqual(len(self.c.loads()), 1)
        self.assertTrue(self.g._runtime_ok)

    def test_a_forced_reload_reinjects(self):
        self.g.ensure_runtime()
        self.g.ensure_runtime(force=True)
        self.assertEqual(len(self.c.loads()), 2)
        self.assert_one_handler_per_event()

    def test_a_changed_fragment_reloads_without_a_version_bump(self):
        self.g.ensure_runtime()
        before = self.lua_eval("H.source_hash")
        tmp = self.copy_source()
        with open(tmp / "map.lua", "a", encoding="utf-8") as f:
            f.write("\n-- a comment, no version bump\n")
        with self.using(tmp):
            self.g._runtime_ok = False
            self.g.ensure_runtime()
            edited = runtime_source.snapshot()
        self.assertEqual(len(self.c.loads()), 2)
        self.assertEqual(self.lua_eval("H.source_hash"), edited.digest)
        self.assertNotEqual(edited.digest, before)
        self.assertEqual(self.lua_eval("H.version"), RUNTIME_VERSION, "same number, new source")
        self.assert_one_handler_per_event()

    def test_a_reload_carries_state_resets_caches_and_keeps_one_handler_per_event(self):
        self.g.ensure_runtime()
        self.lua.execute("""
          H.record('chat', { from = 0, to = 1, text = 'before' })
          H.seen_features[7] = { ['5,5'] = 'FEATURE_FOREST' }
          H.pending_moves['p0:1'] = { x = 1, y = 2 }
          H.hp_snaps[0] = { [1] = 100 }
          H.roster[0] = { [1] = { unit = 'WARRIOR', x = 1, y = 2 } }
          H.known_sites[0] = { [42] = true }
          H.cursors.digest = 3
          H.popups[5] = { type = 5 }
          H.seen_notes['0:9'] = 'text'
          H.popup_rows['12:0:1:2:3'] = true
          H.last_war_key = '0:1:true:12'
          H.turn_seat = 1
          H.alive_majors = { [0] = true }
          H._enum_names.stale = { [1] = 'WRONG' }
        """)
        seq = self.lua_eval("H.event_seq")
        self.g.ensure_runtime(force=True)
        for expr, want in [("H.events[1].data.text", "before"), ("H.event_seq", seq),
                           ("H.seen_features[7]['5,5']", "FEATURE_FOREST"), ("H.pending_moves['p0:1'].y", 2),
                           ("H.hp_snaps[0][1]", 100), ("H.roster[0][1].unit", "WARRIOR"), ("H.known_sites[0][42]", True),
                           ("H.cursors.digest", 3), ("H.popups[5].type", 5), ("H.seen_notes['0:9']", "text"),
                           ("H.popup_rows['12:0:1:2:3']", True), ("H.last_war_key", "0:1:true:12"),
                           ("H.turn_seat", 1), ("H.alive_majors[0]", True)]:
            self.assertEqual(self.lua_eval(expr), want, expr)
        self.assertIsNone(self.lua_eval("next(H._enum_names)"), "a derived cache is rebuilt, never carried")
        self.assert_one_handler_per_event()
        self.fire_chat("after")
        self.assertEqual(self.lua_eval("#H.events"), 2, "one handler recorded the event once")
        self.assertEqual(self.lua_eval("H.events[2].seq"), seq + 1)
        self.assertEqual(self.lua_eval("H.events[2].data.text"), "after")

    def test_a_syntax_error_names_the_fragment_and_installs_nothing(self):
        tmp = self.copy_source()
        (tmp / "map.lua").write_text("x = = 1\n" + (tmp / "map.lua").read_text(encoding="utf-8"), encoding="utf-8")
        with self.using(tmp):
            with self.assertRaises(TunerdError) as cm:
                self.g.ensure_runtime()
        self.assertIn("map.lua:1", str(cm.exception))
        self.assertFalse(self.g._runtime_ok)
        self.assertIsNone(self.lua_eval("H"), "a chunk that does not compile runs nothing")
        self.g.ensure_runtime()           # the corrected source
        self.assertEqual(self.lua_eval("H.source_hash"), runtime_source.snapshot().digest)
        self.assert_one_handler_per_event()

    def test_a_failure_midway_is_not_current_and_the_corrected_retry_carries_state(self):
        self.g.ensure_runtime()
        self.lua.execute("H.record('chat', { from = 0, to = 1, text = 'before' })")
        seq = self.lua_eval("H.event_seq")
        tmp = self.copy_source()
        (tmp / "map.lua").write_text('error("map.lua refuses to load")\n' + (tmp / "map.lua").read_text(encoding="utf-8"), encoding="utf-8")
        with self.using(tmp):
            with self.assertRaises(TunerdError) as cm:
                self.g.ensure_runtime(force=True)
        self.assertIn("map.lua:1", str(cm.exception))
        self.assertFalse(self.g._runtime_ok, "a failed force-reload is not current either")
        # bootstrap ran, so H is the new table carrying the state, but nothing marked it current
        self.assertIsNone(self.lua_eval("H.source_hash"))
        self.assertEqual(self.lua_eval("H.events[1].data.text"), "before")
        self.assert_one_handler_per_event()   # the previous handlers are still the live ones
        self.g.ensure_runtime()                # the corrected source: the check finds no hash and reinjects
        self.assertEqual(len(self.c.loads()), 3)
        self.assertEqual(self.lua_eval("H.source_hash"), runtime_source.snapshot().digest)
        self.assertEqual(self.lua_eval("H.events[1].data.text"), "before")
        self.assertEqual(self.lua_eval("H.event_seq"), seq)
        self.assert_one_handler_per_event()
        self.fire_chat("after")
        self.assertEqual(self.lua_eval("#H.events"), 2)
        self.assertEqual(self.lua_eval("H.events[2].seq"), seq + 1)


if __name__ == "__main__":
    unittest.main()
