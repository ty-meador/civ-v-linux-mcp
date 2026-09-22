"""An unassigned spy must show up where the seat already looks for idle assets.

Live t212: a Special Agent sat `TXT_KEY_SPY_STATE_UNASSIGNED` for an unknown number of turns while
the empire was behind in science with a tech-steal target available. Nothing surfaced it -- an idle
spy is not an end-turn blocker and the game stops mentioning it after the notification that
announced it. `overview.idle_trade_units` already exists for exactly this hazard; spies join it.
"""
import unittest

import test_mcp_safety as support
from harness.game import Game


SPY_WORLD = """
Map = {GetPlot = function() return nil end}
function make_player(spies)
  return {
    GetEspionageSpies = function() return spies end,
    CanSpyStageCoup = function() return false end,
  }
end
"""


class IdleSpyTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua("Locale={ConvertTextKey=function(s) return s end}")
        self.run_lua(SPY_WORLD)

    def test_only_the_unassigned_spies_are_listed(self):
        self.run_lua("""
        Players = {[0] = make_player({
          {AgentID=0, Name='Tetoharsky', Rank='Special Agent', State='TXT_KEY_SPY_STATE_UNASSIGNED'},
          {AgentID=1, Name='Cameahwait', Rank='Recruit', State='TXT_KEY_SPY_STATE_GATHERING_INTEL'},
          {AgentID=2, Name='Sacajawea', Rank='Agent', State='TXT_KEY_SPY_STATE_TRAVELLING'},
        })}
        local idle = H.idle_spies(0)
        assert(#idle == 1, 'only the unassigned one is idle, got ' .. #idle)
        assert(idle[1].agent_id == 0 and idle[1].name == 'Tetoharsky')
        assert(idle[1].rank == 'Special Agent', 'the rank is what decides where it is worth sending')
        """)

    def test_a_fully_deployed_network_reports_an_empty_list(self):
        self.run_lua("""
        Players = {[0] = make_player({
          {AgentID=0, Name='Tetoharsky', Rank='Special Agent', State='TXT_KEY_SPY_STATE_SURVEILLANCE'},
        })}
        assert(#H.idle_spies(0) == 0)
        """)

    def test_a_game_without_espionage_is_not_an_error(self):
        """Espionage only exists from the Renaissance on, and GetEspionageSpies may be missing."""
        self.run_lua("""
        Players = {[0] = {}}
        assert(#H.idle_spies(0) == 0)
        """)


class SpyNoteTest(unittest.TestCase):
    """The summary carries the same kind of nudge `idle_trade_units` gets."""

    def _summary(self, payload):
        g = Game.__new__(Game)
        g.seat = 0
        g.q = lambda body: payload
        return g.summary()

    def test_an_idle_spy_comes_with_what_to_do_about_it(self):
        out = self._summary({"idle_spies": [{"agent_id": 0, "name": "Tetoharsky", "rank": "Special Agent"}]})
        self.assertIn("move_spy", out["spy_note"])
        self.assertIn("available_spy_cities", out["spy_note"])

    def test_no_idle_spy_means_no_note(self):
        self.assertNotIn("spy_note", self._summary({"idle_spies": []}))
        self.assertNotIn("spy_note", self._summary({}))


if __name__ == "__main__":
    unittest.main()
