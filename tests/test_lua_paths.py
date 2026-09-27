"""The shipped Lua is found from where the package actually keeps it (harness/lua), not from the module that
names it: the mixin split moved support.py into game_parts/ and its relative path with it (2026-09-27, live:
load_latest failed on generic_popup_shim.lua)."""
import unittest

from harness import runtime_source
from harness.game_parts import support


class LuaPathTests(unittest.TestCase):
    def test_lua_dir_is_the_package_lua_folder(self):
        self.assertEqual(support.LUA_DIR.name, "lua")
        self.assertEqual(support.LUA_DIR.parent.name, "harness")
        self.assertTrue((support.LUA_DIR / "generic_popup_shim.lua").is_file())
        self.assertTrue((support.LUA_DIR / "audit.lua").is_file())

    def test_runtime_dir_is_under_the_same_folder(self):
        self.assertEqual(runtime_source.RUNTIME_DIR.parent, support.LUA_DIR)
        self.assertTrue(any(runtime_source.RUNTIME_DIR.glob("*.lua")))
