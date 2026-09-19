"""Game.q ships long bodies in chunks (the tuner truncates a command at ~2.5 KB; live t319
purchase_cost came back as a bare "Syntax Error"). Runs the shipped Lua in lupa when available."""
import unittest

from harness.game import Game


class LuaClient:
    """Stands in for the tunerd client: exec/query run in one lupa runtime."""

    def __init__(self, lua):
        self.lua = lua
        self.sent = []

    def exec(self, state, lua, timeout=None, check=True):
        self.sent.append(lua)
        self.lua.execute(lua)
        return []

    def query(self, state, lua_body, timeout=None):
        self.sent.append(lua_body)
        return self.lua.execute("local __f = function() " + lua_body + " end; return __f()")


class QueryChunkingTest(unittest.TestCase):
    def setUp(self):
        try:
            import lupa
        except ImportError:
            self.skipTest("lupa not installed (uv run --with lupa)")
        lua = lupa.LuaRuntime()
        lua.execute("loadstring = load")
        self.g = Game.__new__(Game)
        self.g.c = LuaClient(lua)
        self.g.ensure_runtime = lambda: None

    def test_short_body_goes_inline(self):
        self.assertEqual(self.g.q("return 1 + 1"), 2)
        self.assertEqual(len(self.g.c.sent), 1)

    def test_long_body_is_chunked_and_runs(self):
        pad = "\n".join(f'local v{i} = "{"x" * 40}\\"q"' for i in range(120))
        body = pad + "\nreturn #v7 + 1"
        self.assertGreater(len(body), Game.Q_INLINE_MAX)
        self.assertEqual(self.g.q(body), 43)
        self.assertTrue(all(len(s) < 2400 for s in self.g.c.sent))
        self.assertIsNone(self.g.c.lua.globals()[f"__H_Q{self.g._q_seq}_{id(self.g) % 100000}"])


if __name__ == "__main__":
    unittest.main()
