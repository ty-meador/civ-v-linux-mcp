"""Screen parity regressions: privacy gates, UI units, choices and confirmed writes."""
import unittest
import contextlib
import json
from types import SimpleNamespace
from unittest.mock import patch

import test_mcp_safety as support
from harness.game import Game


class InformationParityTests(unittest.TestCase):
    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua("Locale={ConvertTextKey=function(s) return s end}")
    run_lua = support.LuaRuntimeTests.run_lua

    def test_foreign_religion_uses_banner_units_and_omits_invisible_pressure(self):
        self.run_lua("""
        local rows={{ID=0,Type='RELIGION_PANTHEON'}, {ID=1,Type='RELIGION_ONE'}, {ID=2,Type='RELIGION_TWO'}}
        GameInfo={Religions=function() local i=0; return function() i=i+1; return rows[i] end end}
        GameDefines={RELIGION_MISSIONARY_PRESSURE_MULTIPLIER=10}
        Game.GetReligionName=function(id) return 'Religion '..id end
        local c={GetReligiousMajority=function() return 1 end,
          GetNumFollowers=function(_,id) return ({[0]=1,[1]=4,[2]=0})[id] end,
          GetPressurePerTurn=function(_,id) assert(id~=2, 'non-banner pressure queried'); return 245,2 end,
          IsHolyCityForReligion=function(_,id) return id==1 end}
        local r=H.city_religions(c)
        assert(#r==2 and r[1].religion=='RELIGION_PANTHEON')
        assert(r[2].followers==4 and r[2].majority and r[2].holy_city)
        assert(r[2].pressure_per_turn==24 and r[2].pressure_raw==245 and r[2].trade_routes==2)
        """)

    def test_gp_threshold_is_specific_to_class_and_rate_includes_buildings(self):
        self.run_lua("""
        GameInfo={UnitClasses={UNITCLASS_WRITER={ID=9,Type='UNITCLASS_WRITER'}},
          Buildings=function() local done=false; return function() if not done then done=true;
            return {ID=4,SpecialistType='SPECIALIST_WRITER',GreatPeopleRateChange=1} end end end}
        local c={GetSpecialistCount=function() return 2 end, GetSpecialistGreatPersonProgress=function() return 28 end,
          IsHasBuilding=function() return true end, GetGreatPeopleRateModifier=function() return 0 end,
          GetSpecialistUpgradeThreshold=function(_,cls) assert(cls==9); return 300 end}
        local p={GetGreatPeopleRateModifier=function() return 10 end, GetGreatWriterRateModifier=function() return 15 end,
          GetGoldenAgeTurns=function() return 1 end, GetGoldenAgeGreatWriterRateModifier=function() return 25 end}
        local r=H.specialist_meter(c,{ID=1,Type='SPECIALIST_WRITER',GreatPeopleUnitClass='UNITCLASS_WRITER',GreatPeopleRateChange=3},p)
        assert(r.gp_progress==28 and r.gp_threshold==300 and r.gp_per_turn==10)
        """)

    def test_specialist_validation_happens_before_automation_or_assignment(self):
        self.run_lua("""
        local sent={}; local assigned=0; local puppet=false; local can=false
        Network={SendDoTask=function(...) sent[#sent+1]={...} end}
        TaskTypes={TASK_ADD_SPECIALIST=1,TASK_REMOVE_SPECIALIST=2,TASK_NO_AUTO_ASSIGN_SPECIALISTS=3}
        GameInfo={Buildings={BUILDING_MARKET={ID=8,Type='BUILDING_MARKET',SpecialistType='SPECIALIST_MERCHANT'}}}
        GameInfoTypes={SPECIALIST_MERCHANT=7}
        local c={GetID=function() return 6 end, IsPuppet=function() return puppet end,
          IsHasBuilding=function() return true end, GetNumSpecialistsInBuilding=function() return assigned end,
          IsCanAddSpecialistToBuilding=function() return can end, IsNoAutoAssignSpecialists=function() return false end}
        Players={[0]={GetCityByID=function(_,id) if id==6 then return c end end}}
        assert(not H.change_specialist(6,'BUILDING_MARKET',true,0).ok and #sent==0)
        assert(not H.change_specialist(6,'BUILDING_MARKET',false,0).ok and #sent==0)
        can=true; puppet=true
        assert(not H.change_specialist(6,'BUILDING_MARKET',true,0).ok and #sent==0)
        puppet=false
        local r=H.change_specialist(6,'BUILDING_MARKET',true,0)
        assert(r.ok and r.expected==1 and #sent==2)
        assert(sent[1][1]==6 and sent[1][2]==3 and sent[1][5]==true)
        assert(sent[2][1]==6 and sent[2][2]==1 and sent[2][3]==7 and sent[2][4]==8)
        """)

    def test_maya_repeated_and_unavailable_choices_are_refused(self):
        self.run_lua("""
        local count=1; local repeat_free=false; local sent=0
        Network={SendMayaBonusChoice=function(pid,id) assert(pid==0 and id==2); sent=sent+1 end}
        GameInfoTypes={UNIT_WRITER=2,UNIT_ARTIST=3}
        GameInfo={Units=function() local i=0; local rows={{ID=2,Type='UNIT_WRITER'}, {ID=3,Type='UNIT_ARTIST'}};
          return function() i=i+1; return rows[i] end end}
        Players={[0]={GetNumMayaBoosts=function() return count end, CanTrain=function() return true end,
          GetUnitBaktun=function(_,id) return id==2 and 5 or 0 end, IsFreeMayaGreatPersonChoice=function() return repeat_free end}}
        local r=H.maya_options(0); assert(#r.options==2 and not r.options[1].available and r.options[2].available)
        assert(not H.choose_maya_bonus('UNIT_WRITER',0).ok and sent==0)
        repeat_free=true; assert(H.choose_maya_bonus('UNIT_WRITER',0).ok and sent==1)
        count=0; assert(not H.choose_maya_bonus('UNIT_WRITER',0).ok and sent==1)
        """)

    def test_archaeology_no_slots_stale_dig_and_unmet_origins(self):
        self.run_lua("""
        local sent=0; local visible=true; local written=false
        Network={SendArchaeologyChoice=function(pid,unit,choice) assert(pid==0 and unit==42 and choice==1); sent=sent+1 end}
        ButtonPopupTypes={BUTTONPOPUP_CHOOSE_ARCHAEOLOGY=9}; H.popups={[9]={player=0,data2=42}}
        GameInfo={GreatWorkSlots={GREAT_WORK_SLOT_ART_ARTIFACT={ID=1},GREAT_WORK_SLOT_LITERATURE={ID=2}},
          GreatWorkArtifactClasses={[3]={Type='ARTIFACT_BARBARIAN_CAMP'}}, Eras={[0]={Type='ERA_ANCIENT'}}}
        Game.GetArtifactName=function() return 'Artifact' end
        local plot={IsVisible=function() return visible end, HasWrittenArtifact=function() return written end,
          GetX=function() return 5 end,GetY=function() return 6 end,
          GetArchaeologyArtifactType=function() return 3 end, GetArchaeologyArtifactPlayer1=function() return 1 end,
          GetArchaeologyArtifactPlayer2=function() return -1 end, GetArchaeologyArtifactEra=function() return 0 end}
        Players={[0]={GetTeam=function() return 0 end,GetNextDigCompletePlot=function() return plot end,
          HasAvailableGreatWorkSlot=function() return false end,GetWrittenArtifactCulture=function() return 450 end},
          [1]={GetTeam=function() return 1 end,GetCivilizationShortDescription=function() error('unmet origin leak') end}}
        Teams={[0]={IsHasMet=function() return false end}}
        local r=H.archaeology_options(0)
        assert(r.pending and #r.options==1 and r.options[1].choice==1 and r.origins[1].civ=='unknown')
        assert(not H.choose_archaeology(2,5,6,0).ok and sent==0)
        assert(not H.choose_archaeology(1,5,7,0).ok and sent==0)
        assert(H.choose_archaeology(1,5,6,0).ok and sent==1)
        written=true; r=H.archaeology_options(0); assert(r.options[1].choice==4 and r.options[1].culture==450)
        visible=false; assert(not H.archaeology_options(0).ok)
        """)

    def test_air_target_pagination_never_tests_fogged_occupants(self):
        self.run_lua("""
        local calls=0
        local unit={GetPlot=function() return {} end, MovesLeft=function() return 60 end,
          CanRebaseAt=function(_,origin,x,y) assert(x~=1, 'fog legality leak'); calls=calls+1; return true end}
        Players={[0]={GetTeam=function() return 0 end,GetUnitByID=function() return unit end}}
        H.targeted_missions=function() return {{mission='MISSION_REBASE'}} end
        Map={GetNumPlots=function() return 4 end,GetPlotByIndex=function(i)
          return {IsVisible=function() return i~=1 end,GetX=function() return i end,GetY=function() return 0 end} end}
        local r=H.unit_mission_targets(7,'MISSION_REBASE',0,0,2)
        assert(r.ok and r.total==3 and #r.targets==2 and r.next_offset==2 and calls==3)
        assert(r.targets[1].x==0 and r.targets[2].x==2)
        r=H.unit_mission_targets(7,'MISSION_REBASE',0,2,2)
        assert(#r.targets==1 and r.targets[1].x==3 and r.next_offset==nil)
        """)

    def test_public_overviews_never_enumerate_unmet_cities(self):
        self.run_lua("""
        local function empty() return function() end end
        Players={[0]={GetTeam=function() return 0 end,IsEverAlive=function() return true end,
          IsAlive=function() return true end,GetCivilizationShortDescription=function() return 'Us' end,
          IsHasLostCapital=function() return false end,Cities=empty,GetIntrigueMessages=function() return {} end},
          [1]=setmetatable({GetTeam=function() return 1 end},{__index=function(_,k) error('unmet read '..k) end})}
        Teams={[0]={IsHasMet=function() return false end}}
        GameDefines={MAX_MAJOR_CIVS=2,MAX_CIV_PLAYERS=2}; GameInfo={Buildings=empty}
        assert(#H.domination_progress(0).capitals==1)
        assert(#H.wonder_overview(0).wonders==0)
        assert(#H.espionage_intrigue(0).messages==0)
        assert(not H.city_state_bonuses(1,0).ok)
        """)

    def test_airstrike_move_mission_uses_attack_cursor_legality(self):
        self.run_lua("""
        H.targeted_missions=function() return {{type='INTERFACEMODE_AIRSTRIKE',mission='MISSION_MOVE_TO'}} end
        local u={GetPlot=function() return {} end,MovesLeft=function() return 60 end,
          CanStartMission=function() error('generic move legality would list every tile') end,
          CanRangeStrikeAt=function(_,x,y,war,visible) assert(war and visible); return x==2 end}
        Players={[0]={GetTeam=function() return 0 end,GetUnitByID=function() return u end}}
        Map={GetNumPlots=function() return 3 end,GetPlotByIndex=function(i)
          return {IsVisible=function() return true end,GetX=function() return i end,GetY=function() return 0 end} end}
        local r=H.unit_mission_targets(7,'MISSION_MOVE_TO',0,0,100)
        assert(r.total==1 and r.targets[1].x==2)
        """)

    def test_demographics_returns_only_public_aggregates_and_masks_unmet_winners(self):
        self.run_lua("""
        local function player(id,value)
          return {GetTeam=function() return id end,IsAlive=function() return true end,IsMinorCiv=function() return false end,
            GetRealPopulation=function() return value end,CalculateTotalYield=function() return value end,
            CalculateGrossGold=function() return value end,GetNumPlots=function() return value end,
            GetMilitaryMight=function() return value end,GetExcessHappiness=function() return 0 end}
        end
        Players={[0]=player(0,100),[1]=player(1,200),[2]=player(2,50)}
        Teams={}; for i=0,2 do Teams[i]={GetTeamTechs=function() return {HasTech=function() return true end} end} end
        Teams[0].IsHasMet=function(_,id) return id~=1 end
        GameDefines={MAX_MAJOR_CIVS=3}; YieldTypes={YIELD_FOOD=0,YIELD_PRODUCTION=1}; GameInfoTypes={TECH_WRITING=0}
        GameInfo={Technologies=setmetatable({{}},{__call=function() local done=false;
          return function() if not done then done=true; return {ID=0} end end end})}
        local r=H.demographics(0)
        assert(r.ok and r.metrics.population.value==100 and r.metrics.population.rank==2)
        assert(r.metrics.population.average==117 and r.metrics.population.best.value==200)
        assert(r.metrics.population.best.player==nil and r.metrics.population.worst.player==2)
        assert(r.players==nil and r.metrics.population.players==nil)
        """)

    def test_partial_move_stall_is_in_turn_todo(self):
        self.run_lua("""
        local u={IsReadyToMove=function() return false end,IsAutomated=function() return false end,
          IsDelayedDeath=function() return false end,GetActivityType=function() return 6 end,
          MovesLeft=function() return 30 end,MaxMoves=function() return 120 end,GetBuildType=function() return -1 end,
          GetUnitType=function() return 0 end,GetID=function() return 7 end,GetX=function() return 2 end,GetY=function() return 3 end}
        Players={[0]={IsTurnActive=function() return true end,GetCurrentResearch=function() return 1 end,
          Cities=function() return function() end end,Units=function() local done=false;return function() if not done then done=true;return u end end end}}
        GameInfo={Units={[0]={Type='UNIT_WARRIOR'}}};GameDefines={MOVE_DENOMINATOR=60}
        local r=H.todo(0)
        assert(#r.units==1 and r.units[1].id==7 and r.units[1].moves==0.5 and r.units[1].stalled_mission)
        """)


class ConfirmationTests(unittest.TestCase):
    def test_archaeology_read_opens_notification_to_capture_network_data(self):
        g = Game.__new__(Game)
        g.seat = 0
        results = iter([{"ok": True, "pending": True}, True,
                        {"ok": True, "pending": True, "unit_id": -1}])
        queries = []
        def query(code):
            queries.append(code)
            return next(results)
        g.q = query
        with patch("harness.game.time.sleep"):
            self.assertEqual(g.archaeology_options()["unit_id"], -1)
        self.assertIn("UI.ActivateNotification", queries[1])

    def test_popup_guard_allows_matching_choice_and_blocks_unrelated_choice(self):
        from harness import mcp_server
        for tool, popup in (("choose_archaeology", "BUTTONPOPUP_CHOOSE_ARCHAEOLOGY"),
                            ("choose_maya_bonus", "BUTTONPOPUP_CHOOSE_MAYA_BONUS")):
            state = {"active_player": 0, "paused": False, "processing": False, "my_turn": True,
                     "pending_popups": [{"name": popup}]}
            g = SimpleNamespace(seat=0, turn_state=lambda: state, discussion_pending=lambda: False,
                                dismiss_pending_popups=lambda: [])
            def action():
                return '{"ok":true}'
            action.__name__ = tool
            with patch.object(mcp_server, "game", return_value=g), patch.object(
                    mcp_server, "action_lock", return_value=contextlib.nullcontext()):
                self.assertTrue(json.loads(mcp_server.guarded(action)())["ok"])
                action.__name__ = "change_specialist"
                self.assertFalse(json.loads(mcp_server.guarded(action)())["ok"])

    def test_silent_specialist_refusal_is_not_success(self):
        g = Game.__new__(Game)
        g.seat = 0
        g.q = lambda _: {"ok": True, "building": "BUILDING_MARKET", "expected": 1}
        g.city_screen = lambda *_: {"auto_specialists": False, "buildings": [
            {"building": "BUILDING_MARKET", "specialist_assigned": 0}]}
        with patch("harness.game.time.sleep"):
            result = g.change_specialist(7, "BUILDING_MARKET", True)
        self.assertFalse(result["ok"])
        self.assertIn("did not match", result["err"])


if __name__ == "__main__":
    unittest.main()
