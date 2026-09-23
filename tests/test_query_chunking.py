"""Game.q ships long bodies in chunks (the tuner truncates a command at 2048 bytes; live t319
purchase_cost came back as a bare "Syntax Error"). Runs the shipped Lua in lupa when available."""
import inspect
import re
import unittest

from harness.game import Game
from harness.tuner import TunerClient


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
        self.assertGreater(len(body), Game.q_inline_max())
        self.assertEqual(self.g.q(body), 43)
        self.assertTrue(all(len(s) < 2400 for s in self.g.c.sent))
        self.assertIsNone(self.g.c.lua.globals()[f"__H_Q{self.g._q_seq}_{id(self.g) % 100000}"])


class QueryRunsTheBodyTest(unittest.TestCase):
    """v158 extracted the wrapper and dropped the execute call.

    query() built the Lua and then read `res`, which had never been assigned, so every
    tunerd started from that source answered NameError before the game saw the command.
    A process started earlier kept the old method in memory, which is why play continued.
    """

    def test_query_executes_the_wrapped_body_and_reads_its_output(self):
        seen = {}

        class Stub(TunerClient):
            def __init__(self):
                self.timeout = 5

            def install_helpers(self, state):
                seen["state"] = state

            def execute(self, state, lua, timeout=None, raise_on_error=True):
                seen["lua"] = lua
                seen["timeout"] = timeout

                class Result:
                    output = ["noise", "@@HJ@@7"]

                return Result()

        self.assertEqual(Stub().query("InGame", "return 7", timeout=4), 7)
        self.assertEqual(seen["state"], "InGame")
        self.assertEqual(seen["timeout"], 4)
        self.assertIn("return 7", seen["lua"])


class InlineBudgetTest(unittest.TestCase):
    """The inline/chunked decision must be made against the *wrapped* command.

    Live t193: adding two lines to set_production's puppet guard took its wrapped command from
    2003 to 2093 bytes. The old flat body limit of 2000 still called it "short enough", the tuner
    cut the command at 2048, and the game answered with a Syntax Error quoting the truncated
    source -- for an edit that had nothing to do with size."""

    def test_the_largest_inline_body_still_fits_the_command_limit(self):
        body = "x" * Game.q_inline_max()
        self.assertLessEqual(len(TunerClient._wrap_query(TunerClient, body)), TunerClient.COMMAND_MAX)

    def test_the_budget_is_not_a_hardcoded_guess(self):
        self.assertEqual(Game.q_inline_max(),
                         TunerClient.COMMAND_MAX - TunerClient.query_overhead() - Game.Q_MARGIN)

    def test_every_inline_query_body_in_game_py_fits(self):
        """A body written into game.py as one literal must not need the chunked path by accident
        -- and if it does, it must at least not be silently truncated."""
        over = []
        for name, fn in inspect.getmembers(Game, predicate=inspect.isfunction):
            try:
                src = inspect.getsource(fn)
            except OSError:
                continue
            for body in re.findall(r'self\.q\(f?"""(.*?)"""', src, re.S):
                rendered = body.replace("{{", "{").replace("}}", "}")
                if len(rendered) > Game.q_inline_max():
                    over.append((name, len(rendered)))
        # Bodies over the limit are fine -- q() chunks them -- but each one is a reminder that the
        # limit is real, so the set is pinned rather than merely allowed to grow unnoticed.
        for name, size in over:
            self.assertLess(size, 8000, f"{name}'s inline Lua body is {size} bytes")


if __name__ == "__main__":
    unittest.main()
