"""Religion rows and replies say what they mean (GitLab #103)."""
import json
import os
import unittest
from unittest import mock


import test_mcp_safety as support
from harness import mcp_server as m
from tests.test_tool_surface import FakeGame, ThroughTheServerTests


class BeliefRowsLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua("""
        Locale = { Lookup = function(k) return ({ TXT_SHORT = 'Religious Idols', TXT_DESC = '+1 Culture and +1 Faith from Gold and Silver' })[k] or k end }
        GameInfo = GameInfo or {}
        GameInfo.Beliefs = { [7] = { ID = 7, Type = 'BELIEF_FORMAL_LITURGY', ShortDescription = 'TXT_SHORT', Description = 'TXT_DESC' } }
        GameInfoTypes = { BELIEF_FORMAL_LITURGY = 7 }
        local getter = H.BELIEF_GETTERS.pantheon
        Game[getter] = function() return { 7 } end
        SENT = nil
        Network = { SendFoundPantheon = function(pid, id) SENT = id end }
        H.belief_available = function() return true end
        Players = { [0] = { CanCreatePantheon = function() return true end } }
        """)

    def test_a_belief_row_carries_its_effect_and_the_pantheon_reply_names_the_belief(self):
        self.run_lua("""
        local r = H.available_beliefs('pantheon', 0)
        assert(r.beliefs[1].belief == 'BELIEF_FORMAL_LITURGY' and r.beliefs[1].name == 'Religious Idols', H.json(r))
        assert(r.beliefs[1].effect:find('+1 Culture', 1, true), H.json(r.beliefs[1]))
        local f = H.found_pantheon('BELIEF_FORMAL_LITURGY', 0)
        assert(f.ok and f.belief == 'BELIEF_FORMAL_LITURGY' and f.name == 'Religious Idols' and f.effect:find('Faith', 1, true), H.json(f))
        assert(SENT == 7)
        """)


class ProphetRefusalLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua("""
        IS_CITY, OWNER, HAS, MAJORITY = true, 0, true, 5
        local city = { GetOwner = function() return OWNER end, GetReligiousMajority = function() return MAJORITY end }
        local plot = { IsCity = function() return IS_CITY end, GetPlotCity = function() return city end }
        local unit = { GetPlot = function() return plot end }
        Players = { [0] = { GetUnitByID = function() return unit end, HasCreatedReligion = function() return HAS end,
                            GetReligionCreatedByPlayer = function() return 5 end } }
        Game.GetNumReligionsStillToFound = function() return 2 end
        """)

    def test_each_condition_is_named(self):
        self.run_lua("""
        IS_CITY = false
        assert(H.religion_mission_why(1, 'MISSION_ENHANCE_RELIGION', 0):find('must stand in one of your cities', 1, true))
        IS_CITY = true; OWNER = 3
        assert(H.religion_mission_why(1, 'MISSION_ENHANCE_RELIGION', 0):find('not yours', 1, true))
        OWNER = 0; MAJORITY = 2
        assert(H.religion_mission_why(1, 'MISSION_ENHANCE_RELIGION', 0):find('must follow your religion', 1, true))
        MAJORITY = 5
        assert(H.religion_mission_why(1, 'MISSION_ENHANCE_RELIGION', 0):find('already enhanced', 1, true))
        HAS = false
        assert(H.religion_mission_why(1, 'MISSION_ENHANCE_RELIGION', 0):find('founded no religion', 1, true))
        assert(H.religion_mission_why(1, 'MISSION_FOUND_RELIGION', 0):find('cannot be founded here now', 1, true))
        HAS = true
        assert(H.religion_mission_why(1, 'MISSION_FOUND_RELIGION', 0):find('founded a religion already', 1, true))
        """)


class ReligionQuestionGame(FakeGame):
    def __init__(self):
        super().__init__()
        self.todo_extra = {}

    def turn_state(self, pid=None):
        ts = super().turn_state(pid)
        ts["todo"] = {**ts["todo"], **self.todo_extra}
        return ts

    def cities(self, pid=None):
        return [{"id": 8192, "name": "Palenque", "x": 34, "y": 62}]


class ReligionQuestionTests(ThroughTheServerTests):
    def setUp(self):
        self.fake = ReligionQuestionGame()
        self.patches = [mock.patch.object(m, "game", lambda: self.fake),
                        mock.patch.dict(os.environ, {"CIV5_TUNERD_SOCK": "/tmp/civ5-test-religion.sock", "CIV5_SEAT": "0"}),
                        mock.patch.object(m, "_seat_rechecked", True),
                        mock.patch.dict(m._RECENT, {}, clear=True)]
        for p in self.patches:
            p.start()

    def test_question_shows_the_religion_to_found_with_its_rows_and_beliefs(self):
        """GitLab #103 (Maya t71): after MISSION_FOUND_RELIGION, question() said "nothing is asked"."""
        self.fake.todo_extra = {"religion": "found"}
        out, = self.run_tools([("question", {})])
        r = json.loads(out)
        self.assertEqual((r["pending"], r["decision"], r["choice"], r["gate"]), (True, "religion", "found", None))
        self.assertEqual(r["actions"][0]["tool"], "state")
        self.assertEqual(sorted(r["beliefs"]), ["follower", "founder"])
        self.assertEqual(r["beliefs"]["founder"]["called"], "available_beliefs")

    def test_the_religion_order_takes_the_city_id(self):
        out, = self.run_tools([("order", {"to": "empire", "action": "religion",
                                          "args": {"religion": "RELIGION_TAOISM", "beliefs": ["B1", "B2"], "city": 8192}})])
        r = json.loads(out)
        self.assertTrue(r["ok"], r)
        self.assertIn(("found_religion", ("RELIGION_TAOISM", ["B1", "B2"], 34, 62, "")), [(c[0], c[1]) for c in self.fake.calls])
        out, = self.run_tools([("order", {"to": "empire", "action": "religion", "args": {"religion": "RELIGION_TAOISM", "beliefs": ["B1"], "city": 99}})])
        self.assertIn("no city of mine with id 99", json.loads(out)["err"])


# the inherited ThroughTheServerTests cases are not re-run here
for _name in [n for n in dir(ThroughTheServerTests) if n.startswith("test_")]:
    setattr(ReligionQuestionTests, _name, None)
del _name


if __name__ == "__main__":
    unittest.main()
