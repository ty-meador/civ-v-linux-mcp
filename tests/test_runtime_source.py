"""The runtime loader (harness/runtime_source.py) and Game.ensure_runtime's reload semantics (GitLab #42).

The runtime is 38 fragments assembled into one chunk. These tests pin what the split must not change: one
authoritative source that production and the tests share; a digest that moves when any fragment moves; a
source hash set only once every definition ran; a reload that carries the accumulated state, resets the derived
caches and leaves exactly one live handler per hooked event; a failed load that is never accepted as current
and a corrected retry that neither duplicates handlers nor loses state. The game is a lupa state with a fake
Events table that counts handlers, driven through the real Game.ensure_runtime / load_lua chunking.
"""
import pathlib
import re
import shutil
import subprocess
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
        """The commands that compiled and ran a shipped chunk (load_lua's last step): one per injection."""
        return [c for c in self.sent if c.startswith("local f, err = loadstring(")]


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

    def test_the_installer_runs_each_chunk_under_its_name_and_marks_the_source_current_last(self):
        s = runtime_source.snapshot()
        lua = s.install_lua("__SRC")
        self.assertTrue(lua.startswith("local src = __SRC; __SRC = nil\n"), "the shipped global is consumed and cleared")
        self.assertIn(runtime_source.PRELUDE, lua, "a changed source reloads even at the same version")
        self.assertEqual(lua.rstrip("\n").split("\n")[-1], f"H.source_hash = '{s.digest}'")
        self.assertIn("H.install_hooks()", s.fragment("install.lua").text)
        self.assertEqual(s.text.count("\nH.install_hooks()\n"), 1, "hooks are installed from one place")
        # every fragment is its own chunk, and the chunk is exactly the file
        raw = s.text.encode("utf-8")
        chunks = s.chunks()
        self.assertEqual([name for name, _, _ in chunks], list(runtime_source.MANIFEST))
        for name, a, b in chunks:
            self.assertEqual(raw[a - 1:b].decode("utf-8"), s.fragment(name).text, f"{name}: error lines are file lines")
        self.assertEqual(chunks[-1][0], "install.lua")


LUAC = shutil.which("luac5.4") or shutil.which("luac")

# What the runtime may read as a global besides its own H: the game's API in the InGame state and Lua's builtins.
# A new engine table is added here on purpose; a fragment's local that another fragment forgot to import is not.
GAME_API = {
    "ActivityTypes", "ButtonPopupTypes", "CityAIFocusTypes", "CommandTypes", "ContextPtr", "DiploUIStateTypes",
    "DirectionTypes", "DomainTypes", "EndTurnBlockingTypes", "Events", "FaithPurchaseTypes", "FromUIDiploEventTypes",
    "Game", "GameDefines", "GameInfo", "GameInfoActions", "GameInfoTypes", "GameMessageTypes", "GameOptionTypes",
    "GameplayGameStateTypes", "InfluenceLevelTrend", "InfluenceLevelTypes", "Locale", "MajorCivApproachTypes", "Map",
    "MinorCivPersonalityTypes", "MinorCivQuestTypes", "MinorCivTraitTypes", "MissionTypes", "Network",
    "NotificationTypes", "OrderTypes", "Players", "PreGame", "PublicOpinionTypes", "ReligionTypes",
    "ResourceUsageTypes", "TaskTypes", "Teams", "ToGridFromHex", "TradeableItems", "UI", "UIManager", "YieldTypes",
}
LUA_BUILTINS = {"ipairs", "math", "next", "pairs", "pcall", "print", "select", "string", "table", "tonumber", "tostring", "type",
                "error", "setmetatable", "getmetatable", "rawget", "rawset", "unpack", "assert", "loadstring", "load"}
_GLOBAL_OP = re.compile(r'(GETTABUP|SETTABUP)\s.*_ENV "([A-Za-z_]\w*)"')
_FUNC_HEADER = re.compile(r"(\d+)\+? params?, (\d+) slots?, (\d+) upvalues?, (\d+) locals?")
_TOP_LOCAL_FN = re.compile(r"^local function ([A-Za-z_]\w*)", re.M)
_TOP_LOCAL = re.compile(r"^local ([A-Za-z_][\w, ]*?)\s*=", re.M)
_EXPORT = re.compile(r"^H\._ns\.(\w+) = (\w+)$", re.M)


def top_level_locals(text: str) -> set:
    names = set(_TOP_LOCAL_FN.findall(text))
    for group in _TOP_LOCAL.findall(text):
        names.update(n.strip() for n in group.split(","))
    return names


class FragmentLintTests(unittest.TestCase):
    """Each fragment compiles on its own and reads nothing another fragment declared as a local."""

    def setUp(self):
        if not LUAC:
            self.skipTest("luac not installed (apt install lua5.4): the fragment lint compiles each file")
        self.s = runtime_source.snapshot()

    def listing(self, text: str) -> str:
        path = pathlib.Path(tempfile.mkdtemp(prefix="luac-")) / "chunk.lua"
        self.addCleanup(shutil.rmtree, path.parent, ignore_errors=True)
        path.write_text(text, encoding="utf-8")
        return subprocess.run([LUAC, "-l", "-l", "-p", str(path)], capture_output=True, text=True, check=True).stdout

    def globals_of(self, text: str):
        gets, sets = set(), set()
        for op, name in _GLOBAL_OP.findall(self.listing(text)):
            (gets if op == "GETTABUP" else sets).add(name)
        return gets, sets

    def test_a_fragment_reads_only_the_game_api_lua_and_H(self):
        declared = {f.name: top_level_locals(f.text) for f in self.s.fragments}
        for f in self.s.fragments:
            gets, sets = self.globals_of(f.text)
            elsewhere = set().union(*(v for k, v in declared.items() if k != f.name))
            self.assertEqual(sorted(gets & elsewhere), [],
                             f"{f.name} reads another fragment's local as a global: import it from H._ns at the top")
            self.assertEqual(sorted(gets - GAME_API - LUA_BUILTINS - {"H"}), [],
                             f"{f.name} reads a global that is neither the game's API nor H (a typo, or add it to GAME_API)")
            self.assertEqual(sorted(sets - ({"H"} if f.name == "bootstrap.lua" else set())), [], f"{f.name} assigns a global")

    def test_every_import_is_exported_by_an_earlier_fragment_and_every_export_is_imported(self):
        order = [f.name for f in self.s.fragments]
        exports, imports = {}, {}
        for f in self.s.fragments:
            for name, value in _EXPORT.findall(f.text):
                self.assertEqual(name, value, f"{f.name}: H._ns.{name} exports the local of that name")
                self.assertNotIn(name, exports, f"H._ns.{name} exported twice")
                exports[name] = f.name
            code = re.sub(r"--.*$", "", _EXPORT.sub("", f.text), flags=re.M)   # comments describe the mechanism
            imports[f.name] = set(re.findall(r"H\._ns\.(\w+)", code))
        for consumer, needs in imports.items():
            for name in sorted(needs):
                self.assertIn(name, exports, f"{consumer} imports H._ns.{name}, which no fragment exports")
                self.assertLess(order.index(exports[name]), order.index(consumer),
                                f"{consumer} imports H._ns.{name} before {exports[name]} exports it (MANIFEST order)")
        used = set().union(*imports.values())
        self.assertEqual(sorted(set(exports) - used), [], "exports no fragment imports")

    def test_every_chunk_stays_under_the_lua_5_1_compiler_limits(self):
        raw = self.s.text.encode("utf-8")
        for name, a, b in self.s.chunks():
            headers = _FUNC_HEADER.findall(self.listing(raw[a - 1:b].decode("utf-8")))
            self.assertTrue(headers, name)
            main_locals = int(headers[0][3])
            self.assertLessEqual(main_locals, 200, f"{name}: {main_locals} top-level locals (Lua 5.1 allows 200 per chunk)")
            worst = max(int(h[2]) for h in headers)
            self.assertLessEqual(worst, 60, f"{name}: a function captures {worst} upvalues (Lua 5.1 allows 60)")


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
        self.assertIn("map.lua:1:", str(cm.exception), "the chunk is named after the file")
        self.assertFalse(self.g._runtime_ok)
        # the chunks before map.lua ran (H exists), map.lua compiled nothing, and nothing marked the load current
        self.assertTrue(self.lua_eval("H == nil or H.source_hash == nil"), "a failed load is never current")
        self.g.ensure_runtime()           # the corrected source
        self.assertEqual(self.lua_eval("H.source_hash"), runtime_source.snapshot().digest)
        self.assert_one_handler_per_event()

    def test_a_fragments_error_names_the_file_and_its_line(self):
        tmp = self.copy_source()
        (tmp / "install.lua").write_text("\n\nx = = 1\n" + (tmp / "install.lua").read_text(encoding="utf-8"), encoding="utf-8")
        with self.using(tmp):
            with self.assertRaises(TunerdError) as cm:
                self.g.ensure_runtime()
        self.assertIn("install.lua:3:", str(cm.exception))
        self.assertIsNone(self.lua_eval("H.source_hash"), "the definitions ran, nothing marked them current")

    def test_a_failure_midway_is_not_current_and_the_corrected_retry_carries_state(self):
        self.g.ensure_runtime()
        self.lua.execute("H.record('chat', { from = 0, to = 1, text = 'before' })")
        seq = self.lua_eval("H.event_seq")
        tmp = self.copy_source()
        (tmp / "map.lua").write_text('error("map.lua refuses to load")\n' + (tmp / "map.lua").read_text(encoding="utf-8"), encoding="utf-8")
        with self.using(tmp):
            with self.assertRaises(TunerdError) as cm:
                self.g.ensure_runtime(force=True)
        self.assertIn("map.lua:1:", str(cm.exception))
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
