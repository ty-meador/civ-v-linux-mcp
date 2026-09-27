"""Every city write must decide, explicitly, what it does about a puppet.

A puppet's city screen is read-only -- no production picker, no tile purchase, no citizen
management -- but the engine only enforces some of that. `IsCanPurchase` answers false for a
puppet; `CityPushOrder` and `CanBuyPlotAt` happily say yes. So a new city tool that trusts the
engine gets a hole, silently, and the harness hands the LLM a move no human can make:

  - v158, live t192: `set_production` pushed a Worker into captured Cusco and it stuck across the
    turn boundary, displacing the puppet AI's own pick permanently.
  - live t193: `buy_city_plot` had the same hole. All three puppets offered buyable plots at
    65-130 gold.

This is a lint, not a behaviour test: it fails when a city write is added without the guard, so
the next one is a decision someone made rather than one nobody noticed.
"""
import pathlib
import re
import unittest

from harness import runtime_source


# City functions that may legitimately act on (or read) a puppet, with the reason.
PUPPET_IS_FINE = {
    "city_task": "annex/raze IS the puppet tool",
    "puppet_guard": "it is the guard",
    "city_production_guard": "it is the guard",
}


def _h_functions(src: str) -> dict[str, str]:
    return {m.group(1): m.group(2)
            for m in re.finditer(r"function H\.(\w+)\((?:[^)]*)\)(.*?)\nend\n", src, re.S)}


class CityWriteGuardTest(unittest.TestCase):
    def setUp(self):
        # the whole assembled runtime: a city write is a city write whichever fragment it lands in
        self.fns = _h_functions(runtime_source.snapshot().text)
        self.assertIn("city_task", self.fns, "the lint found no H.* functions at all")

    def test_every_city_write_handles_puppets(self):
        unguarded = [
            name for name, body in self.fns.items()
            if "own_city(" in body
            and name not in PUPPET_IS_FINE
            and not re.search(r"IsPuppet|puppet_guard", body)
        ]
        self.assertEqual(unguarded, [],
                         "city write(s) with no puppet decision: add H.puppet_guard(c, ...) "
                         "or list them in PUPPET_IS_FINE with the reason")

    def test_the_guard_is_shared_rather_than_copied(self):
        """Eight hand-written copies of the same IsPuppet check is how one of them went missing."""
        self.assertIn("puppet_guard", self.fns, "H.puppet_guard must exist")
        self.assertIn("annex", self.fns["puppet_guard"], "the refusal names the way out")

    def test_set_production_guards_puppets_from_python(self):
        """set_production builds its precheck in Python rather than going through own_city."""
        import inspect
        from harness.game import Game
        self.assertIn("city_production_guard", inspect.getsource(Game.set_production))


if __name__ == "__main__":
    unittest.main()
