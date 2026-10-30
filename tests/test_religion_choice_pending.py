"""A religion to found or enhance stays visible and orderable whatever blocker the engine names (GitLab #109).

Live Maya t105: MISSION_ENHANCE_RELIGION answered a bare consumed:true; the engine named PRODUCTION as the blocker,
so the choice was invisible and order(empire, enhance_religion) was refused "not pending" until both cities had
production. The runtime remembers the Prophet's mission itself, the todo and the briefing carry the choice, and the
guard no longer compares blocker names.
"""
import unittest

import test_mcp_safety as support
from harness.briefing import decisions
from harness.surface import classes as C


class ReligionChoiceLuaTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)

    def test_the_prophets_mission_opens_the_choice_and_the_order_closes_it(self):
        self.run_lua("""
        local pushed={}
        local selected=nil
        UI={SelectUnit=function(u) selected=u end, GetHeadSelectedUnit=function() return selected end}
        Game={GetActivePlayer=function() return 0 end,
              SelectionListGameNetMessage=function(msg, m, d1, d2) pushed[#pushed+1]={m=m} end}
        GameMessageTypes={GAMEMESSAGE_PUSH_MISSION=41, GAMEMESSAGE_DO_COMMAND=42}
        GameDefines={MOVE_DENOMINATOR=60}
        MissionTypes={MISSION_ENHANCE_RELIGION=36, MISSION_FOUND_RELIGION=35}
        GameInfoTypes={MISSION_ENHANCE_RELIGION=36, MISSION_FOUND_RELIGION=35, RELIGION_TAOISM=5,
                       BELIEF_DIVINE_INSPIRATION=70, BELIEF_RELIGIOUS_TEXTS=71}
        local blocker = 'ENDTURN_BLOCKING_PRODUCTION'
        local unit={
          GetID=function() return 1 end, GetOwner=function() return 0 end,
          GetX=function() return 34 end, GetY=function() return 62 end, MovesLeft=function() return 120 end,
          IsCombatUnit=function() return false end, CanStartMission=function() return true end,
          GetBuildType=function() return -1 end, GetLengthMissionQueue=function() return 0 end,
          GetActivityType=function() return 1 end,
        }
        Players={[0]={GetUnitByID=function() return unit end, GetTeam=function() return 0 end,
                      GetEndTurnBlockingType=function() return 3 end}}
        H.blocking_name=function() return blocker end
        H.religion_pending = {}
        assert(H.religion_choice(0) == nil, 'nothing pending')
        local r=H.unit_mission(1, 'MISSION_ENHANCE_RELIGION', -1, -1, nil, 0)
        assert(r.ok==true and #pushed==1, H.json(r))
        assert(H.religion_choice(0) == 'enhance', 'the choice is open behind the PRODUCTION blocker')
        -- the choice is made: the memory clears
        H.belief_available=function() return true end
        local sent
        Network={SendEnhanceReligion=function(...) sent={...} end}
        r=H.enhance_religion('RELIGION_TAOISM', 'BELIEF_DIVINE_INSPIRATION', 'BELIEF_RELIGIOUS_TEXTS', 34, 62, nil, 0)
        assert(r.ok==true and r.beliefs.follower=='BELIEF_DIVINE_INSPIRATION' and r.religion=='RELIGION_TAOISM', H.json(r))
        assert(sent and sent[2]==5 and sent[4]==70 and sent[5]==71, H.json(sent))
        assert(H.religion_choice(0) == nil, 'made')
        -- the blocker alone also says so
        blocker = 'ENDTURN_BLOCKING_FOUND_RELIGION'
        assert(H.religion_choice(0) == 'found', 'the blocker names it when the runtime did not see the Prophet')
        """)


class ReligionDecisionTests(unittest.TestCase):
    def test_todo_religion_is_a_decision_with_the_popups_rows_and_the_blocker_is_not_repeated(self):
        ts = {"todo": {"units": [], "cities": [{"id": 1, "name": "Tikal"}], "religion": "enhance"},
              "blocking_name": "ENDTURN_BLOCKING_PRODUCTION", "blocking_hint": "x", "pending_popups": []}
        rows = decisions(ts, [])
        rel = [r for r in rows if r["kind"] == "religion"]
        self.assertEqual(len(rel), 1)
        self.assertEqual(rel[0]["detail"], {"choice": "enhance"})
        tools = [a["tool"] for a in rel[0]["actions"]]
        self.assertEqual(tools[0], "state")
        self.assertIn("order", tools)
        ts["blocking_name"] = "ENDTURN_BLOCKING_ENHANCE_RELIGION"
        kinds = [r["kind"] for r in decisions(ts, [])]
        self.assertEqual(kinds.count("religion"), 1)
        self.assertNotIn("blocker", kinds)

    def test_the_guard_compares_no_blocker_name(self):
        self.assertEqual(C.REQUIRED_BLOCKER, {})


if __name__ == "__main__":
    unittest.main()
