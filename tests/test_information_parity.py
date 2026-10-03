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

    def test_trade_route_turns_are_blank_when_the_engine_has_no_answer(self):
        """Stock TradeRouteOverview prints the turns column only `if v.TurnsLeft >= 0`.

        Live t205: the four Ethiopian routes into our cities carried TurnsLeft -9/-11/-17/-28,
        which passed through as a countdown that had run out rather than as "not applicable".
        """
        self.run_lua("""
        local mine = {{FromID=0, ToID=4, FromCityName='Moson Kahni', ToCityName='Addis Ababa',
                       Domain=2, TurnsLeft=6, FromGPT=1717}}
        local theirs = {{FromID=4, ToID=0, FromCityName='Addis Ababa', ToCityName='Moson Kahni',
                         Domain=2, TurnsLeft=-17, FromGPT=774}}
        Players={[0]={GetTradeRoutes=function() return mine end,
                      GetTradeRoutesToYou=function() return theirs end,
                      GetTeam=function() return 0 end},
                 [4]={GetTeam=function() return 4 end}}
        Teams={[0]={IsHasMet=function() return true end}}
        local r = H.trade_routes(0)
        assert(r.outgoing[1].turns_left == 6, 'a real countdown is still reported')
        assert(r.outgoing[1].gold == 17.17)
        assert(r.incoming[1].turns_left == nil, 'a negative TurnsLeft is blank, not overdue')
        assert(r.incoming[1].from_city == 'Addis Ababa', 'the rest of the row survives')
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
        H.ranged_target_info=function(_,plot) assert(plot:GetX()==2); return {} end
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

    DEAL_CITY_FIXTURE = """
        local i=0
        local deal={ResetIterator=function() i=0 end, GetNextItem=function()
          i=i+1
          if i==1 then return 8, 0, 0, 12, 7, 0, 0, 2 end
        end}
        TradeableItems={TRADE_ITEM_CITIES=8}
        Players={[0]={GetTeam=function() return 0 end},
                 [2]={Cities=function() local done=false; return function()
          if not done then done=true; return {GetX=function() return 12 end, GetY=function() return 7 end,
            GetName=function() return 'Cusco' end, GetID=function() return 9 end,
            GetPopulation=function() return 11 end} end end end}}
        local asked={}
        Map={GetPlot=function(x,y) asked[#asked+1]={x,y}
          return {IsRevealed=function(self,team,debug) assert(team==0 and debug==false); return REVEALED end} end}
    """

    def test_deal_city_items_name_pop_and_coordinates_once_revealed(self):
        """A city on the table is named with its population (tradelogic.lua DisplayDeal); its plot
        shows only once we have revealed it (GitLab #2)."""
        self.run_lua(self.DEAL_CITY_FIXTURE + """
        REVEALED=true
        local r=H.deal_items(deal,0)
        assert(#r==1 and r[1].type=='CITIES' and r[1].x==12 and r[1].y==7)
        assert(r[1].name=='Cusco' and r[1].city_id==9 and r[1].pop==11)
        assert(#asked==1 and asked[1][1]==12 and asked[1][2]==7)
        """)

    def test_deal_city_items_withhold_coordinates_of_unrevealed_plot(self):
        self.run_lua(self.DEAL_CITY_FIXTURE + """
        REVEALED=false
        local r=H.deal_items(deal,0)
        assert(#r==1 and r[1].type=='CITIES')
        assert(r[1].name=='Cusco' and r[1].city_id==9 and r[1].pop==11)
        assert(r[1].x==nil and r[1].y==nil, 'coordinates of a city we have never seen leaked')
        assert(not H.json(r):find('12', 1, true), 'x leaked through another field')
        """)

    def test_deal_city_items_without_map_api_withhold_coordinates(self):
        """If the plot cannot be checked, the row stays name-only rather than guessing revealed."""
        self.run_lua(self.DEAL_CITY_FIXTURE + """
        Map=nil
        local r=H.deal_items(deal,0)
        assert(r[1].name=='Cusco' and r[1].x==nil and r[1].y==nil)
        """)

    def test_topbar_science_culture_tourism_faith_and_gold_itr(self):
        self.run_lua("""
        Game.GetNumCitiesTechCostMod=function() return 5 end
        Game.GetNumCitiesPolicyCostMod=function() return 10 end
        GameInfo={Victories={VICTORY_CULTURAL={ID=2}}}
        PreGame={IsVictory=function(id) assert(id==2); return true end}
        local p={
          GetGold=function() return 100 end, CalculateGoldRate=function() return -18 end,
          GetGoldPerTurnFromDiplomacy=function() return 13 end,
          GetGoldFromCitiesTimes100=function() return 5372 end,
          GetGoldFromCitiesMinusTradeRoutesTimes100=function() return 4972 end,
          GetCityConnectionGoldTimes100=function() return 1170 end,
          GetGoldPerTurnFromTraits=function() return 0 end,
          GetGoldPerTurnFromReligion=function() return 2 end,
          CalculateUnitCost=function() return 50 end, CalculateUnitSupply=function() return 0 end,
          GetBuildingGoldMaintenance=function() return 48 end,
          GetImprovementGoldMaintenance=function() return 15 end,
          GetScience=function() return 57 end,
          GetScienceFromBudgetDeficitTimes100=function() return -300 end,
          GetScienceFromCitiesTimes100=function(self, exclude)
            return exclude and 5400 or 5700
          end,
          GetScienceFromOtherPlayersTimes100=function() return 0 end,
          GetScienceFromHappinessTimes100=function() return 0 end,
          GetScienceFromResearchAgreementsTimes100=function() return 0 end,
          IsAnarchy=function() return false end,
          GetTotalJONSCulturePerTurn=function() return 35 end,
          GetJONSCulture=function() return 822 end, GetNextPolicyCost=function() return 960 end,
          GetJONSCulturePerTurnForFree=function() return 0 end,
          GetJONSCulturePerTurnFromCities=function() return 30 end,
          GetJONSCulturePerTurnFromExcessHappiness=function() return 2 end,
          GetJONSCulturePerTurnFromTraits=function() return 0 end,
          GetCulturePerTurnFromMinorCivs=function() return 3 end,
          GetCulturePerTurnFromReligion=function() return 0 end,
          GetCulturePerTurnFromBonusTurns=function() return 0 end,
          GetTourism=function() return 4 end, GetNumGreatWorks=function() return 1 end,
          GetNumGreatWorkSlots=function() return 3 end,
          GetNumCivsInfluentialOn=function() return 0 end,
          GetNumCivsToBeInfluentialOn=function() return 3 end,
          GetTotalFaithPerTurn=function() return 45 end, GetFaith=function() return 132 end,
          GetFaithPerTurnFromCities=function() return 29 end,
          GetFaithPerTurnFromMinorCivs=function() return 16 end,
          GetFaithPerTurnFromReligion=function() return 0 end,
          GetMinimumFaithNextGreatProphet=function() return 500 end,
        }
        Players={[0]=p}
        local gold=H.gold_breakdown(0)
        assert(gold.income.cities==49.72 and gold.income.trade_routes==4)
        assert(gold.income.deals==13 and gold.income.religion==2 and gold.income.traits==nil)
        assert(gold.losing_science_from_deficit==nil and gold.is_strike==nil)
        local sci=H.science_breakdown(0)
        assert(sci.total==57 and sci.cities==54 and sci.trade_routes==3 and sci.budget_deficit==-3)
        assert(sci.tech_city_cost_mod==5)
        local cul=H.culture_breakdown(0)
        assert(cul.total==35 and cul.cities==30 and cul.happiness==2 and cul.city_states==3)
        assert(cul.turns==4 and cul.golden_age==nil)
        local tour=H.tourism_breakdown(0)
        assert(tour.tourism==4 and tour.great_works==1 and tour.empty_slots==2)
        assert(tour.influential_on==0 and tour.needed==3)
        local faith=H.faith_breakdown(0)
        assert(faith.total==45 and faith.cities==29 and faith.city_states==16 and faith.next_great_person==500)
        """)

    def test_anarchy_shows_on_the_gold_hover_too(self):
        """toppanel.lua GoldTipHandler prints TXT_KEY_TP_ANARCHY first; live t239 (ideology switch,
        GitLab #13) the science/culture/faith hovers carried anarchy_turns and the gold one did not."""
        self.run_lua("""
        local p={GetGold=function() return 1163 end, CalculateGoldRate=function() return 0 end,
          IsAnarchy=function() return true end, GetAnarchyNumTurns=function() return 2 end}
        Players={[0]=p}
        local gold=H.gold_breakdown(0)
        assert(gold.anarchy_turns==2, 'gold hover lacks the anarchy line')
        p.IsAnarchy=function() return false end
        assert(H.gold_breakdown(0).anarchy_turns==nil)
        """)

    def test_an_unlocked_branch_offers_no_unlock(self):
        """Live Doge t215: CanUnlockPolicyBranch stays true for Tradition after it is unlocked, so the
        row said can_unlock and unlock_policy_branch re-sent it (the play loop counted that as progress
        five times). The screen shows no unlock button on an open branch."""
        self.run_lua("""
        local branches = { { ID = 1, Type = 'POLICY_BRANCH_TRADITION' }, { ID = 2, Type = 'POLICY_BRANCH_LIBERTY' } }
        GameInfo = { PolicyBranchTypes = function() local i = 0; return function() i = i + 1; return branches[i] end end,
                     Policies = function() return function() end end }
        GameInfoTypes = { POLICY_BRANCH_TRADITION = 1, POLICY_BRANCH_LIBERTY = 2 }
        local sent = nil
        Network = { SendUpdatePolicies = function(id) sent = id end }
        Players = { [0] = { GetJONSCulture = function() return 264 end, GetNextPolicyCost = function() return 70 end,
          GetNumFreePolicies = function() return 0 end, IsPolicyBranchUnlocked = function(_, id) return id == 1 end,
          CanUnlockPolicyBranch = function() return true end } }
        local r = H.available_policies(0)
        assert(r.branches[1].unlocked == true and r.branches[1].can_unlock == false, 'open branch offers no unlock')
        assert(r.branches[2].unlocked == false and r.branches[2].can_unlock == true)
        local u = H.unlock_policy_branch('POLICY_BRANCH_TRADITION', 0)
        assert(u.ok == false and u.unlocked == true and u.err:find('already'), tostring(u.err))
        assert(sent == nil, 'nothing sent for an open branch')
        assert(H.unlock_policy_branch('POLICY_BRANCH_LIBERTY', 0).ok == true and sent == 2)
        """)

    def test_map_index_skips_unmet_and_fog_feature(self):
        self.run_lua("""
        local function no() return false end
        local fog={IsRevealed=function() return true end, IsVisible=no, GetX=function() return 1 end,
          GetY=function() return 2 end, GetResourceType=function() return 3 end,
          GetRevealedImprovementType=function() return 1 end, GetPlotCity=function() error('fog city') end,
          GetNumResource=function() error('fog qty') end, GetFeatureType=function() error('fog feature') end,
          GetImprovementType=function() error('live imp') end}
        local vis={IsRevealed=function() return true end, IsVisible=function() return true end,
          GetX=function() return 4 end, GetY=function() return 5 end, GetResourceType=function() return -1 end,
          GetImprovementType=function() return -1 end, GetFeatureType=function() return 9 end,
          GetRevealedImprovementType=function() error('visible should use live imp') end}
        Map={GetNumPlots=function() return 2 end, GetPlotByIndex=function(i) return i==0 and fog or vis end}
        GameInfo={Resources={[3]={Type='RESOURCE_SILK', ResourceClassType='RESOURCECLASS_LUXURY'}},
          Improvements={[1]={Type='IMPROVEMENT_BARBARIAN_CAMP'}},
          Features={[9]={Type='FEATURE_CRATER', NaturalWonder=true}}, Buildings=function() return function() end end}
        Players={[0]={GetTeam=function() return 0 end, IsAlive=function() return true end, IsEverAlive=function() return true end,
          GetCivilizationShortDescription=function() return 'Us' end, IsHasLostCapital=function() return false end,
          Cities=function() return function() end end},
          [1]=setmetatable({GetTeam=function() return 1 end, IsAlive=function() return true end},{__index=function(_,k) error('unmet '..k) end})}
        Teams={[0]={IsHasMet=function() return false end}}
        GameDefines={MAX_MAJOR_CIVS=2, MAX_CIV_PLAYERS=2}
        local r=H.map_index(0)
        assert(r.ok and #r.foreign_cities==0)
        assert(#r.resources==1 and r.resources[1].resource=='RESOURCE_SILK' and r.resources[1].qty==nil)
        assert(#r.camps==1 and r.camps[1].x==1 and r.camps[1].vis==false)
        assert(#r.natural_wonders==1 and r.natural_wonders[1].feature=='FEATURE_CRATER')
        """)

    def test_gift_unit_requires_distance_gift_and_met_minor(self):
        self.run_lua("""
        local sent=0
        Network={SendGiftUnit=function(mid,uid) sent=sent+1; assert(mid==22 and uid==7) end}
        GameInfo={Units={[1]={Type='UNIT_WARRIOR'}}}
        local u={CanDistanceGift=function(_,mid) return mid==22 end, GetID=function() return 7 end,
          GetUnitType=function() return 1 end, GetX=function() return 3 end, GetY=function() return 4 end}
        Players={[0]={GetTeam=function() return 0 end, Units=function() local done=false; return function()
            if not done then done=true; return u end end end},
          [22]={GetTeam=function() return 22 end, IsMinorCiv=function() return true end, IsAlive=function() return true end,
            GetName=function() return 'Sidon' end, GetMinorCivFriendshipWithMajor=function() return 5 end}}
        Teams={[0]={IsHasMet=function(_,t) return t==22 end, IsAtWar=function() return false end}}
        assert(not H.gift_unit_options(1,0).ok)
        local r=H.gift_unit_options(22,0)
        assert(r.ok and #r.units==1 and r.units[1].id==7)
        assert(not H.gift_unit(22,99,0).ok and sent==0)
        assert(H.gift_unit(22,7,0).ok and sent==1)
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

    def test_todo_names_the_stacked_tile_and_its_units(self):
        """Live t245: a Caravan finished in Goshute on top of a Worker; the blocker names nothing.
        Two civilians on one tile is the stack; a combat unit beside them is not, and aircraft
        share a city freely."""
        self.run_lua("""
        local function unit(id, x, y, combat, domain, moves, ready)
          return {IsReadyToMove=function() return ready or false end,IsAutomated=function() return false end,
            IsDelayedDeath=function() return false end,GetActivityType=function() return 0 end,
            MovesLeft=function() return moves end,MaxMoves=function() return 120 end,GetBuildType=function() return -1 end,
            GetUnitType=function() return id end,GetID=function() return id end,GetX=function() return x end,GetY=function() return y end,
            IsCombatUnit=function() return combat end,GetDomainType=function() return domain end}
        end
        local us={unit(1,46,29,false,0,120,true), unit(2,46,29,false,0,60), unit(3,46,29,true,0,120),
                  unit(4,50,24,false,2,120), unit(5,50,24,false,2,120)}
        Players={[0]={IsTurnActive=function() return true end,GetCurrentResearch=function() return 1 end,
          Cities=function() return function() end end,
          Units=function() local i=0;return function() i=i+1;return us[i] end end}}
        GameInfo={Units={[1]={Type='UNIT_WORKER'},[2]={Type='UNIT_CARAVAN'},[3]={Type='UNIT_MUSKETMAN'},
                         [4]={Type='UNIT_FIGHTER'},[5]={Type='UNIT_FIGHTER'}}}
        GameDefines={MOVE_DENOMINATOR=60}; DomainTypes={DOMAIN_LAND=0,DOMAIN_SEA=1,DOMAIN_AIR=2}
        local r=H.todo(0)
        assert(r.stacked and #r.stacked==1, 'one stacked tile, got '..tostring(r.stacked and #r.stacked))
        local s=r.stacked[1]
        assert(s.x==46 and s.y==29 and s.class=='civilian', s.class)
        assert(#s.units==2 and s.units[1].type=='WORKER' and s.units[1].moves==2 and s.units[2].type=='CARAVAN' and s.units[2].moves==1)
        -- the readiness list is unchanged by the stack list
        assert(#r.units==1 and r.units[1].id==1)
        """)

    def test_a_caravan_on_its_route_is_not_part_of_a_stack(self):
        """Mongolia t117 (2026-09-27): two caravans crossing the capital on their routes were listed as a
        civilian stack (and woke a quiet run). A trade unit walking its route is automated and passes
        through; an idle one home in the city still counts, like any civilian."""
        self.run_lua("""
        local function unit(id, x, y, combat, trade, automated)
          return {IsReadyToMove=function() return false end,IsAutomated=function() return automated or false end,
            IsDelayedDeath=function() return false end,GetActivityType=function() return 0 end,
            MovesLeft=function() return 0 end,MaxMoves=function() return 120 end,GetBuildType=function() return -1 end,
            GetUnitType=function() return id end,GetID=function() return id end,GetX=function() return x end,GetY=function() return y end,
            IsCombatUnit=function() return combat end,GetDomainType=function() return 0 end,
            IsTrade=function() return trade or false end,
            GetCurrHitPoints=function() return 100 end,GetMaxHitPoints=function() return 100 end,
            GetMissionType=function() return -1 end,GetPlot=function() return nil end}
        end
        local us={unit(1,28,24,false,false), unit(2,28,24,false,true,true), unit(3,28,24,false,true,true)}
        Players={[0]={IsTurnActive=function() return true end,GetCurrentResearch=function() return 1 end,
          Cities=function() return function() end end,
          Units=function() local i=0;return function() i=i+1;return us[i] end end}}
        GameInfo={Units={[1]={Type='UNIT_WORKER'},[2]={Type='UNIT_CARAVAN'},[3]={Type='UNIT_CARAVAN'}}}
        GameDefines={MOVE_DENOMINATOR=60}; DomainTypes={DOMAIN_LAND=0,DOMAIN_SEA=1,DOMAIN_AIR=2}
        H.ongoing_attention=function() return nil end   -- the ongoing rows' map look-around is not under test
        local r=H.todo(0)
        assert(r.stacked==nil, 'two caravans on their routes beside a worker are no stack')
        -- v254: an idle caravan home in the city holds no slot either (Venice t153: the engine sold a Caravan
        -- into a city already holding a Worker and a caravan, while a second Worker could not be bought there).
        us[3]=unit(3,28,24,false,true,false)
        r=H.todo(0)
        assert(r.stacked==nil, 'an idle caravan beside a worker is no stack: '..H.json(r.stacked))
        us[3]=unit(3,28,24,false,false,false)  -- a second worker is
        r=H.todo(0)
        assert(r.stacked and #r.stacked==1 and #r.stacked[1].units==2, 'two workers stack')
        """)

    def test_todo_lists_pending_steal_tech_behind_another_block(self):
        self.run_lua("""
        local techs={{ID=1,Type='TECH_SAILING',Description='Sailing'}}
        GameInfo={Units={},Technologies=setmetatable({[1]=techs[1]},
          {__call=function() local i=0; return function() i=i+1; return techs[i] end end})}
        GameDefines={MOVE_DENOMINATOR=60,MAX_MAJOR_CIVS=3}
        Players={[0]={IsTurnActive=function() return true end,GetCurrentResearch=function() return 1 end,
          GetTeam=function() return 0 end,GetNumTechsToSteal=function(_,other) return other==2 and 1 or 0 end,
          CanResearch=function() return true end,GetResearchCost=function() return 65 end,
          Cities=function() return function() end end,Units=function() return function() end end},
          [2]={IsAlive=function() return true end,GetTeam=function() return 2 end,
            GetCivilizationShortDescriptionKey=function() return 'The Inca' end}}
        Teams={[0]={IsHasTech=function() return false end},[2]={IsHasTech=function() return true end}}
        Locale={ConvertTextKey=function(s) return s end}
        local r=H.todo(0)
        assert(r.steal_tech and #r.steal_tech==1 and r.steal_tech[1].player==2)
        assert(r.steal_tech[1].techs[1].tech=='TECH_SAILING')
        assert(r.steal_tech_hint:find('steal_tech', 1, true))
        """)

    def test_steal_tech_notice_attaches_chooser(self):
        self.run_lua("""
        local techs={{ID=1,Type='TECH_SAILING',Description='Sailing'}}
        GameInfo={Technologies=setmetatable({[1]=techs[1]},
          {__call=function() local i=0; return function() i=i+1; return techs[i] end end})}
        GameDefines={MAX_MAJOR_CIVS=3}
        Players={[0]={GetTeam=function() return 0 end,GetNumTechsToSteal=function(_,other) return other==2 and 1 or 0 end,
          CanResearch=function() return true end,GetResearchCost=function() return 65 end},
          [2]={IsAlive=function() return true end,GetTeam=function() return 2 end,
            GetCivilizationShortDescriptionKey=function() return 'The Inca' end}}
        Teams={[0]={IsHasTech=function() return false end},[2]={IsHasTech=function() return true end}}
        Locale={ConvertTextKey=function(s) return s end}
        NotificationTypes={}
        local d={player=0, ntype=99, summary='Steal Technology',
          text='Recruit Tetoharsky gathered enough intelligence in Cusco to steal a technology from The Inca!'}
        H.locate_notification(d)
        assert(d.hint:find('steal_tech', 1, true))
        assert(#d.steal_tech==1 and d.steal_tech[1].player==2 and d.steal_tech[1].techs[1].tech=='TECH_SAILING')
        """)

    def test_gold_breakdown_flags_science_taken_from_deficit(self):
        self.run_lua("""
        local p={
          GetGold=function() return 0 end, CalculateGoldRate=function() return -23 end,
          GetGoldPerTurnFromDiplomacy=function() return 13 end,
          GetGoldFromCitiesTimes100=function() return 3100 end,
          GetGoldFromCitiesMinusTradeRoutesTimes100=function() return 3100 end,
          GetCityConnectionGoldTimes100=function() return 1170 end,
          GetGoldPerTurnFromTraits=function() return 0 end,
          GetGoldPerTurnFromReligion=function() return 14 end,
          CalculateUnitCost=function() return 52 end, CalculateUnitSupply=function() return 0 end,
          GetBuildingGoldMaintenance=function() return 49 end,
          GetImprovementGoldMaintenance=function() return 19 end,
          IsStrike=function() return false end, GetStrikeTurns=function() return 0 end,
        }
        Players={[0]=p}
        local gold=H.gold_breakdown(0)
        assert(gold.gold==0 and gold.gold_per_turn==-23 and gold.losing_science_from_deficit==true)
        assert(gold.is_strike==nil and gold.strike_turns==nil)
        assert(gold.note:find('science_breakdown', 1, true))
        """)

    def test_unit_supply_remaining_vs_deficit(self):
        self.run_lua("""
        local p={GetNumUnitsSupplied=function() return 20 end, GetNumUnits=function() return 16 end,
          GetNumUnitsSuppliedByHandicap=function() return 5 end,
          GetNumUnitsSuppliedByCities=function() return 8 end,
          GetNumUnitsSuppliedByPopulation=function() return 7 end,
          GetNumUnitsOutOfSupply=function() return 0 end,
          GetUnitProductionMaintenanceMod=function() return 0 end}
        Players={[0]=p}
        local s=H.unit_supply(0)
        assert(s.cap==20 and s.used==16 and s.remaining==4 and s.deficit==nil)
        assert(s.from_handicap==5 and s.from_cities==8 and s.from_population==7)
        p.GetNumUnits=function() return 24 end
        p.GetNumUnitsOutOfSupply=function() return 4 end
        p.GetUnitProductionMaintenanceMod=function() return -10 end
        s=H.unit_supply(0)
        assert(s.used==24 and s.deficit==4 and s.remaining==nil and s.production_penalty==-10)
        """)

    def test_gold_breakdown_unit_cost_per_paid_unit(self):
        self.run_lua("""
        DomainTypes={NO_DOMAIN=-1}
        local p={
          GetGold=function() return 10 end, CalculateGoldRate=function() return -6 end,
          GetGoldPerTurnFromDiplomacy=function() return 0 end,
          GetGoldFromCitiesTimes100=function() return 3100 end,
          GetGoldFromCitiesMinusTradeRoutesTimes100=function() return 3100 end,
          GetCityConnectionGoldTimes100=function() return 0 end,
          GetGoldPerTurnFromTraits=function() return 0 end,
          GetGoldPerTurnFromReligion=function() return 0 end,
          CalculateUnitCost=function() return 52 end, CalculateUnitSupply=function() return 0 end,
          GetBuildingGoldMaintenance=function() return 37 end,
          GetImprovementGoldMaintenance=function() return 20 end,
          GetNumUnits=function() return 24 end,
          GetNumMaintenanceFreeUnits=function() return 4 end,
        }
        Players={[0]=p}
        local gold=H.gold_breakdown(0)
        assert(gold.expenses.unit_maintenance==52 and gold.expenses.unit_paid==20)
        assert(gold.expenses.unit_free==4 and gold.expenses.unit_cost_per==2.6)
        """)

    def test_cities_building_maintenance_and_connection_gold(self):
        self.run_lua("""
        YieldTypes={YIELD_FOOD=0,YIELD_PRODUCTION=1,YIELD_GOLD=2,YIELD_SCIENCE=3}
        local cap={GetID=function() return 1 end, GetName=function() return 'Cap' end,
          GetX=function() return 1 end, GetY=function() return 1 end, GetPopulation=function() return 5 end,
          IsCapital=function() return true end, IsPuppet=function() return false end,
          IsOccupied=function() return false end, IsRazing=function() return false end,
          GetMaxHitPoints=function() return 200 end, GetDamage=function() return 0 end,
          GetStrengthValue=function() return 1000 end, GetProductionNameKey=function() return '' end,
          GetOrderQueueLength=function() return 0 end, GetYieldRate=function() return 1 end,
          GetJONSCulturePerTurn=function() return 1 end, GetFaithPerTurn=function() return 1 end,
          GetFood=function() return 0 end, GetLocalHappiness=function() return 1 end,
          FoodDifference=function() return 0 end, GetGarrisonedUnit=function() return nil end,
          IsCoastal=function() return false end, GetProductionTurnsLeft=function() return 1 end,
          GetTotalBaseBuildingMaintenance=function() return 12 end}
        local other={GetID=function() return 2 end, GetName=function() return 'Other' end,
          GetX=function() return 2 end, GetY=function() return 2 end, GetPopulation=function() return 3 end,
          IsCapital=function() return false end, IsPuppet=function() return false end,
          IsOccupied=function() return false end, IsRazing=function() return false end,
          GetMaxHitPoints=function() return 200 end, GetDamage=function() return 0 end,
          GetStrengthValue=function() return 800 end, GetProductionNameKey=function() return '' end,
          GetOrderQueueLength=function() return 0 end, GetYieldRate=function() return 1 end,
          GetJONSCulturePerTurn=function() return 1 end, GetFaithPerTurn=function() return 1 end,
          GetFood=function() return 0 end, GetLocalHappiness=function() return 1 end,
          FoodDifference=function() return 0 end, GetGarrisonedUnit=function() return nil end,
          IsCoastal=function() return false end, GetProductionTurnsLeft=function() return 1 end,
          GetTotalBaseBuildingMaintenance=function() return 0 end}
        local cut={GetID=function() return 3 end, GetName=function() return 'Cut' end,
          GetX=function() return 3 end, GetY=function() return 3 end, GetPopulation=function() return 2 end,
          IsCapital=function() return false end, IsPuppet=function() return false end,
          IsOccupied=function() return false end, IsRazing=function() return false end,
          GetMaxHitPoints=function() return 200 end, GetDamage=function() return 0 end,
          GetStrengthValue=function() return 800 end, GetProductionNameKey=function() return '' end,
          GetOrderQueueLength=function() return 0 end, GetYieldRate=function() return 1 end,
          GetJONSCulturePerTurn=function() return 1 end, GetFaithPerTurn=function() return 1 end,
          GetFood=function() return 0 end, GetLocalHappiness=function() return 1 end,
          FoodDifference=function() return 0 end, GetGarrisonedUnit=function() return nil end,
          IsCoastal=function() return false end, GetProductionTurnsLeft=function() return 1 end,
          GetTotalBaseBuildingMaintenance=function() return 0 end}
        local cities={cap, other, cut}
        local i=0
        Players={[0]={Cities=function() i=0; return function() i=i+1; return cities[i] end end,
          IsCapitalConnectedToCity=function(_,c) return c==other end,
          GetCityConnectionRouteGoldTimes100=function(_,c) return (c==other or c==cut) and 370 or 0 end}}
        local rows=H.cities(0)
        assert(rows[1].building_maintenance==12 and rows[1].connection_gold==nil)
        assert(rows[2].building_maintenance==nil and rows[2].connection_gold==3.7)
        assert(rows[3].connected_to_capital==false and rows[3].connection_gold==nil)
        """)

    def test_losing_gold_notice_attaches_unit_supply_when_over_cap(self):
        self.run_lua("""
        NotificationTypes={}
        local p={GetGold=function() return 0 end, CalculateGoldRate=function() return -6 end,
          IsStrike=function() return false end, GetStrikeTurns=function() return 0 end,
          GetNumUnitsSupplied=function() return 20 end, GetNumUnits=function() return 24 end,
          GetNumUnitsSuppliedByHandicap=function() return 5 end,
          GetNumUnitsSuppliedByCities=function() return 8 end,
          GetNumUnitsSuppliedByPopulation=function() return 7 end,
          GetNumUnitsOutOfSupply=function() return 4 end,
          GetUnitProductionMaintenanceMod=function() return -10 end}
        Players={[0]=p}
        local d={player=0, ntype=99, summary='Losing Gold!',
          text='Your treasury is empty and your economy is now producing 0 Gold per turn or less!'}
        H.locate_notification(d)
        assert(d.unit_supply and d.unit_supply.deficit==4 and d.unit_supply.production_penalty==-10)
        assert(d.hint:find('unit_supply', 1, true))
        """)

    def test_losing_gold_notice_attaches_gpt(self):
        self.run_lua("""
        NotificationTypes={}
        local p={GetGold=function() return 0 end, CalculateGoldRate=function() return -23 end,
          IsStrike=function() return false end, GetStrikeTurns=function() return 0 end}
        Players={[0]=p}
        local d={player=0, ntype=99, summary='Losing Gold!',
          text='Your treasury is empty and your economy is now producing 0 Gold per turn or less! If the empire reaches -5 GPT some of your units will be forced to disband!'}
        H.locate_notification(d)
        assert(d.gold==0 and d.gold_per_turn==-23 and d.is_strike==false)
        assert(d.hint:find('sell_building', 1, true))
        """)

    def test_sell_building_refuses_puppet_and_unsellable(self):
        self.run_lua("""
        local sent=0
        Network={SendSellBuilding=function() sent=sent+1 end}
        GameInfoTypes={BUILDING_AIRPORT=11, BUILDING_GRANARY=4}
        Game.GetActivePlayer=function() return 0 end
        local puppet={IsPuppet=function() return true end, GetID=function() return 1 end,
          IsBuildingSellable=function() return true end, GetSellBuildingRefund=function() return 10 end}
        local city={IsPuppet=function() return false end, GetID=function() return 2 end,
          IsBuildingSellable=function(self,id) return id==11 end, GetSellBuildingRefund=function() return 100 end}
        Players={[0]={GetCityByID=function(self,id) return id==1 and puppet or city end, GetGold=function() return 0 end}}
        assert(not H.sell_building(1,'BUILDING_AIRPORT',0).ok and sent==0)
        assert(not H.sell_building(2,'BUILDING_GRANARY',0).ok and sent==0)
        local r=H.sell_building(2,'BUILDING_AIRPORT',0)
        assert(r.ok and r.refund==100 and sent==1)
        """)

    def test_conversion_notice_attaches_banner_even_on_a_tie(self):
        self.run_lua("""
        local rows={{ID=1,Type='RELIGION_TENGRIISM'},{ID=2,Type='RELIGION_ORTHODOXY'}}
        GameInfo={Religions=setmetatable({[1]=rows[1],[2]=rows[2]},
          {__call=function() local i=0; return function() i=i+1; return rows[i] end end})}
        GameDefines={RELIGION_MISSIONARY_PRESSURE_MULTIPLIER=10}
        Game.GetReligionName=function(id) return id==1 and 'Tengriism' or 'Eastern Orthodoxy' end
        local c={GetID=function() return 49157 end, GetName=function() return 'Machu' end,
          GetX=function() return 47 end, GetY=function() return 10 end,
          GetReligiousMajority=function() return -1 end,
          GetNumFollowers=function(_,id) return ({[1]=2,[2]=2})[id] end,
          GetPressurePerTurn=function(_,id) return ({[1]=225,[2]=360})[id], 0 end,
          IsHolyCityForReligion=function() return false end}
        Players={[0]={Cities=function() local done=false; return function()
          if not done then done=true; return c end end end}}
        local d={player=0, text='Machu has been converted to another religion!', ntype=1}
        NotificationTypes={}
        H.locate_notification(d)
        assert(d.city_id==49157 and d.x==47 and d.y==10)
        assert(d.religion==nil and d.majority==nil)
        assert(d.note=='no religion holds a majority in this city now')
        assert(#d.religions==2 and d.religions[1].followers==2)
        assert(d.religions[2].pressure_per_turn==36 and not d.religions[2].majority)
        """)

    def test_empty_queue_is_not_labelled_a_process(self):
        self.run_lua("""
        local empty={GetProductionNameKey=function() return '' end, GetProductionTurnsLeft=function() return 2147483647 end,
          IsProductionProcess=function() return false end, GetID=function() return 1 end, GetName=function() return 'Goshute' end,
          GetX=function() return 46 end, GetY=function() return 29 end, GetPopulation=function() return 4 end,
          IsCapital=function() return false end, IsPuppet=function() return false end, IsOccupied=function() return false end,
          IsRazing=function() return false end, GetMaxHitPoints=function() return 200 end, GetDamage=function() return 0 end,
          GetStrengthValue=function() return 1990 end, GetOrderQueueLength=function() return 0 end,
          GetYieldRate=function() return 1 end, GetJONSCulturePerTurn=function() return 5 end, GetFaithPerTurn=function() return 6 end,
          GetFood=function() return 10 end, GetLocalHappiness=function() return 4 end, FoodDifference=function() return 5 end,
          GetFoodTurnsLeft=function() return 7 end, GetGarrisonedUnit=function() return nil end, IsCoastal=function() return true end,
          GetReligiousMajority=function() return 1 end, IsCapitalConnectedToCity=function() return false end}
        local wealth={GetProductionNameKey=function() return 'TXT_KEY_PROCESS_WEALTH' end,
          GetProductionTurnsLeft=function() return 2147483647 end, IsProductionProcess=function() return true end,
          GetID=function() return 2 end, GetName=function() return 'Te-Moak' end,
          GetX=function() return 50 end, GetY=function() return 24 end, GetPopulation=function() return 5 end,
          IsCapital=function() return false end, IsPuppet=function() return false end, IsOccupied=function() return false end,
          IsRazing=function() return false end, GetMaxHitPoints=function() return 200 end, GetDamage=function() return 0 end,
          GetStrengthValue=function() return 2170 end, GetOrderQueueLength=function() return 1 end,
          GetYieldRate=function() return 1 end, GetJONSCulturePerTurn=function() return 5 end, GetFaithPerTurn=function() return 6 end,
          GetFood=function() return 10 end, GetLocalHappiness=function() return 4 end, FoodDifference=function() return 3 end,
          GetFoodTurnsLeft=function() return 12 end, GetGarrisonedUnit=function() return nil end, IsCoastal=function() return true end,
          GetReligiousMajority=function() return 1 end, IsCapitalConnectedToCity=function() return true end}
        local cities={empty, wealth}
        Players={[0]={Cities=function() local i=0; return function() i=i+1; return cities[i] end end,
          IsCapitalConnectedToCity=function(_,c) return c:GetID()==2 end}}
        YieldTypes={YIELD_FOOD=0,YIELD_PRODUCTION=1,YIELD_GOLD=2,YIELD_SCIENCE=3}
        Game.GetReligionName=function() return 'Tengriism' end
        local r=H.cities(0)
        assert(r[1].needs_production and r[1].production_turns==nil and r[1].production_note==nil)
        assert(r[2].production_note~=nil and r[2].production_turns==nil)
        """)

    def test_religion_overview_pressure_uses_banner_units(self):
        self.run_lua("""
        local rows={{ID=1,Type='RELIGION_TENGRIISM'},{ID=2,Type='RELIGION_ORTHODOXY'}}
        GameInfo={Religions=setmetatable({[1]=rows[1],[2]=rows[2]},
          {__call=function() local i=0; return function() i=i+1; return rows[i] end end}),
          Beliefs={}}
        GameDefines={RELIGION_MISSIONARY_PRESSURE_MULTIPLIER=10, MAX_MAJOR_CIVS=1, MAX_CIV_PLAYERS=1}
        Game.GetReligionName=function(id) return 'R'..id end
        Game.GetNumReligionsStillToFound=function() return 0 end
        Game.GetNumCitiesFollowing=function() return 1 end
        Game.GetBeliefsInReligion=function() return {} end
        Game.GetHolyCityForReligion=function() return nil end
        local c={GetID=function() return 7 end, GetName=function() return 'Machu' end, GetPopulation=function() return 5 end,
          GetReligiousMajority=function() return -1 end,
          GetNumFollowers=function(_,id) return ({[1]=2,[2]=2})[id] end,
          GetPressurePerTurn=function(_,id) return ({[1]=225,[2]=360})[id], 0 end,
          IsHolyCityForReligion=function() return false end}
        local p={GetFaith=function() return 0 end, GetTotalFaithPerTurn=function() return 0 end,
          GetMinimumFaithNextGreatProphet=function() return 500 end, HasCreatedPantheon=function() return true end,
          HasCreatedReligion=function() return true end, GetReligionCreatedByPlayer=function() return 1 end,
          GetBeliefInPantheon=function() return -1 end, Cities=function() local done=false; return function()
            if not done then done=true; return c end end end, GetTeam=function() return 0 end,
          IsAlive=function() return true end, IsEverAlive=function() return true end, IsMinorCiv=function() return false end,
          GetCivilizationShortDescription=function() return 'Us' end}
        Players={[0]=p}; Teams={[0]={IsHasMet=function() return true end}}
        local r=H.religion_overview(0)
        assert(r.cities[1].majority==nil)
        assert(r.cities[1].religions[1].pressure_per_turn==22)
        assert(r.cities[1].religions[2].pressure_per_turn==36)
        assert(r.cities[1].religions[2].pressure_raw==360)
        """)

    def test_relationship_discuss_matches_discuss_screen_gates(self):
        self.run_lua("""
        local p={GetTeam=function() return 0 end, GetApproachTowardsUsGuess=function() return 0 end,
          IsDoF=function() return false end, IsDenouncedPlayer=function() return false end,
          GetNumWarsFought=function() return 0 end,
          GetNegativeReligiousConversionPoints=function() return 4 end,
          GetNegativeArchaeologyPoints=function() return 0 end,
          HasRecentIntrigueAbout=function() return true end}
        local o={IsAlive=function() return true end, IsMinorCiv=function() return false end,
          GetCivilizationShortDescription=function() return 'Ethiopia' end, GetName=function() return 'Haile' end,
          GetTeam=function() return 4 end, IsDenouncedPlayer=function() return false end,
          GetOpinionTable=function() return {} end, GetEspionageSpies=function() return {{}} end,
          IsAskedToStopConverting=function() return false end, IsStopSpyingMessageTooSoon=function() return true end,
          IsDontSettleMessageTooSoon=function() return false end, IsAskedToStopDigging=function() return false end,
          IsDoFMessageTooSoon=function() return false end, IsDoF=function() return false end}
        Players={[0]=p,[4]=o}
        Teams={[0]={IsHasMet=function() return true end, IsAtWar=function() return false end,
          HasEmbassyAtTeam=function() return false end, IsAllowsOpenBordersToTeam=function() return false end,
          IsHasResearchAgreement=function() return false end, IsHasDefensivePact=function() return false end},
          [4]={HasEmbassyAtTeam=function() return false end, IsAllowsOpenBordersToTeam=function() return false end,
            IsAtWar=function() return false end, IsHasMet=function() return true end}}
        GameDefines={MAX_CIV_PLAYERS=5, MAX_MAJOR_CIVS=5}
        H.approach_name=function() return 'NEUTRAL' end
        local r=H.relationship(0,4)
        assert(r.ok and r.discuss.stop_spreading_religion)
        assert(not r.discuss.stop_spying)
        assert(r.discuss.dont_settle and r.discuss.declare_friendship)
        assert(not r.discuss.stop_digging)
        assert(r.discuss.share_intrigue)
        """)

    def test_units_report_worker_job_and_mission_name(self):
        self.run_lua("""
        MissionTypes={MISSION_ROUTE_TO=22, MISSION_BUILD=15}
        GameInfo={Units={[1]={Type='UNIT_WORKER'}}, Domains={[0]={Type='DOMAIN_LAND'}},
          Builds={[8]={Type='BUILD_TRADING_POST'}}}
        GameDefines={MOVE_DENOMINATOR=60}
        local plot={IsCity=function() return false end,
          GetBuildTurnsLeft=function(self, bt, pid) assert(bt==8 and pid==0); return 5 end}
        local u={GetID=function() return 114694 end, GetUnitType=function() return 1 end,
          GetName=function() return 'Worker' end, GetX=function() return 50 end, GetY=function() return 29 end,
          MovesLeft=function() return 0 end, MaxMoves=function() return 120 end,
          GetCurrHitPoints=function() return 100 end, GetMaxHitPoints=function() return 100 end,
          GetBaseCombatStrength=function() return 0 end, GetRangedCombatStrength=function() return 0 end,
          Range=function() return 0 end, IsEmbarked=function() return false end,
          GetFortifyTurns=function() return 0 end, IsAutomated=function() return false end,
          IsReadyToMove=function() return false end, IsGarrisoned=function() return false end,
          GetMissionType=function() return 22 end, GetDomainType=function() return 0 end,
          GetLevel=function() return 1 end, GetExperience=function() return 0 end,
          GetPlot=function() return plot end, GetBuildType=function() return 8 end,
          CanFound=function() return false end}
        Players={[0]={Units=function() local done=false; return function()
          if not done then done=true; return u end end end}}
        local rows=H.units(0)
        assert(#rows==1 and rows[1].id==114694)
        assert(rows[1].mission_name=='MISSION_ROUTE_TO')
        assert(rows[1].build=='BUILD_TRADING_POST' and rows[1].build_turns_left==6)
        """)

    def test_plot_construction_and_unusable_resource_are_visible_only(self):
        self.run_lua("""
        local builds={{ID=3,Type='BUILD_FARM'}}
        GameInfo={Terrains={[0]={Type='TERRAIN_GRASS'}}, Resources={[4]={Type='RESOURCE_OIL', TechCityTrade='TECH_BIOLOGY'}},
          Builds=function() local i=0; return function() i=i+1; return builds[i] end end}
        GameInfoTypes={TECH_BIOLOGY=90}
        Teams={[0]={GetTeamTechs=function() return {HasTech=function() return false end} end}}
        local vis={IsRevealed=function() return true end, IsVisible=function() return true end,
          GetX=function() return 4 end, GetY=function() return 5 end, GetTerrainType=function() return 0 end,
          IsHills=function() return false end, IsMountain=function() return false end, IsRiver=function() return false end,
          IsLake=function() return false end, GetResourceType=function() return 4 end, GetNumResource=function() return 1 end,
          GetFeatureType=function() return -1 end, GetImprovementType=function() return -1 end,
          GetRouteType=function() return -1 end, GetOwner=function() return 0 end, IsCity=function() return false end,
          GetNumUnits=function() return 0 end, CalculateYield=function() return 0 end,
          IsFreshWater=function() return false end, IsBeingWorked=function() return false end,
          IsRoutePillaged=function() return false end, IsTradeRoute=function() return true end,
          GetBuildProgress=function(self,id) return id==3 and 2 or 0 end,
          GetBuildTurnsLeft=function() return 3 end}
        local e=H.describe_plot(vis, 0)
        assert(e.vis==true and e.resource=='OIL' and e.resource_usable==false)
        assert(e.resource_requires_tech=='TECH_BIOLOGY' and e.trade_route==true)
        assert(e.under_construction.build=='BUILD_FARM' and e.under_construction.turns_left==4)
        """)

    def test_kill_camp_quest_coords_only_when_revealed(self):
        self.run_lua("""
        MinorCivQuestTypes={MINOR_CIV_QUEST_KILL_CAMP=5, MINOR_CIV_QUEST_CONTEST_FAITH=2}
        GameDefines={MAX_MAJOR_CIVS=22, MAX_CIV_PLAYERS=24}
        Game.GetActivePlayer=function() return 0 end
        Game.GetGameTurn=function() return 183 end
        GameInfo={Resources={}, Buildings={}, Units={}, Religions={}}
        local camp={IsRevealed=function() return true end}
        Map={GetPlot=function(x,y) return (x==51 and y==7) and camp or nil end}
        local cs={IsMinorCiv=function() return true end, IsAlive=function() return true end,
          GetTeam=function() return 22 end, GetName=function() return 'Sidon' end,
          IsMinorCivDisplayedQuestForPlayer=function(_,pid,q)
            return pid==0 and (q==5 or q==2) end,
          GetQuestData1=function(_,pid,q) return q==5 and 51 or 0 end,
          GetQuestData2=function(_,pid,q) return q==5 and 7 or 0 end,
          GetQuestTurnsRemaining=function(_,pid,q) return q==5 and 12 or 30 end,
          GetMinorCivContestValueForPlayer=function() return 4 end,
          GetMinorCivContestValueForLeader=function() return 9 end,
          IsMinorCivContestLeader=function() return false end,
          IsThreateningBarbariansEventActiveForPlayer=function() return false end,
          IsProxyWarActiveForMajor=function() return false end}
        Players={[0]={GetTeam=function() return 0 end}, [22]=cs}
        Teams={[0]={IsHasMet=function(_,t) return t==22 end}}
        local quests=H.city_state_quests(22,0)
        assert(#quests==2)
        local camp_q, faith
        for _,q in ipairs(quests) do
          if q.type=='KILL_CAMP' then camp_q=q elseif q.type=='CONTEST_FAITH' then faith=q end
        end
        assert(camp_q.x==51 and camp_q.y==7 and camp_q.turns_left==12)
        assert(faith.our_score==4 and faith.leader_score==9 and faith.winning==false and faith.turns_left==30)
        local overlay=H.kill_camp_quest_minors(51,7,0)
        assert(#overlay==1 and overlay[1].name=='Sidon')
        camp.IsRevealed=function() return false end
        local hidden=H.city_state_quests(22,0)
        for _,q in ipairs(hidden) do
          if q.type=='KILL_CAMP' then assert(q.x==nil and q.y==nil) end
        end
        """)

    def test_trade_routes_split_outgoing_and_incoming_and_hide_unmet(self):
        self.run_lua("""
        local outgoing={{FromCityName='Moson Kahni', ToCityName='Addis Ababa', FromID=0, ToID=4, Domain=2,
          TurnsLeft=26, FromGPT=984, FromScience=200, ToGPT=0, ToScience=0, ToFood=0, ToProduction=0}}
        local incoming={{FromCityName='Cusco', ToCityName='Moson Kahni', FromID=2, ToID=0, Domain=2,
          TurnsLeft=10, FromGPT=500, FromScience=0, ToGPT=300, ToScience=0, ToFood=0, ToProduction=0},
          {FromCityName='Unmet', ToCityName='Moson Kahni', FromID=9, ToID=0, Domain=2,
          TurnsLeft=4, FromGPT=100, FromScience=0, ToGPT=100, ToScience=0, ToFood=0, ToProduction=0}}
        Players={[0]={GetTeam=function() return 0 end, GetTradeRoutes=function() return outgoing end,
          GetTradeRoutesToYou=function() return incoming end},
          [2]={GetTeam=function() return 2 end}, [4]={GetTeam=function() return 4 end},
          [9]={GetTeam=function() return 9 end}}
        Teams={[0]={IsHasMet=function(_,t) return t==2 or t==4 end}}
        local r=H.trade_routes(0)
        assert(r.ok and #r.outgoing==1 and r.outgoing[1].to_city=='Addis Ababa' and r.outgoing[1].gold==9.84)
        assert(#r.incoming==1 and r.incoming[1].from_city=='Cusco' and r.incoming[1].from_player_id==2)
        """)

    def test_score_breakdown_omits_zero_buckets(self):
        self.run_lua("""
        GameOptionTypes={GAMEOPTION_NO_SCIENCE=1, GAMEOPTION_NO_POLICIES=2, GAMEOPTION_NO_RELIGION=3}
        Game.IsOption=function() return false end
        local p={GetScore=function() return 412 end, GetScoreFromCities=function() return 80 end,
          GetScoreFromPopulation=function() return 90 end, GetScoreFromLand=function() return 40 end,
          GetScoreFromWonders=function() return 0 end, GetScoreFromGreatWorks=function() return 8 end,
          GetScoreFromTechs=function() return 70 end, GetScoreFromFutureTech=function() return 0 end,
          GetScoreFromPolicies=function() return 50 end, GetScoreFromReligion=function() return 20 end}
        Players={[0]=p}
        local s=H.score_breakdown(0)
        assert(s.total==412 and s.cities==80 and s.population==90 and s.land==40)
        assert(s.wonders==nil and s.future_tech==nil and s.great_works==8 and s.religion==20)
        """)

    def test_cities_wltkd_and_blockade_flags(self):
        self.run_lua("""
        YieldTypes={YIELD_FOOD=0,YIELD_PRODUCTION=1,YIELD_GOLD=2,YIELD_SCIENCE=3}
        local c={GetID=function() return 1 end, GetName=function() return 'Cap' end,
          GetX=function() return 1 end, GetY=function() return 1 end, GetPopulation=function() return 5 end,
          IsCapital=function() return true end, IsPuppet=function() return false end,
          IsOccupied=function() return false end, IsRazing=function() return false end,
          GetMaxHitPoints=function() return 200 end, GetDamage=function() return 0 end,
          GetStrengthValue=function() return 1000 end, GetProductionNameKey=function() return '' end,
          GetOrderQueueLength=function() return 0 end, GetYieldRate=function() return 1 end,
          GetJONSCulturePerTurn=function() return 1 end, GetFaithPerTurn=function() return 1 end,
          GetFood=function() return 0 end, GetLocalHappiness=function() return 1 end,
          FoodDifference=function() return 0 end, GetGarrisonedUnit=function() return nil end,
          IsCoastal=function() return true end, GetProductionTurnsLeft=function() return 1 end,
          GetTotalBaseBuildingMaintenance=function() return 0 end,
          IsBlockaded=function() return true end, GetWeLoveTheKingDayCounter=function() return 12 end}
        Players={[0]={Cities=function() local done=false; return function()
          if not done then done=true; return c end end end}}
        local rows=H.cities(0)
        assert(rows[1].blockaded==true and rows[1].wltkd_turns==12)
        """)

    def test_public_opinion_preferred_ideology_and_tooltip(self):
        self.run_lua("""
        PublicOpinionTypes={PUBLIC_OPINION_DISSIDENTS=1}
        GameInfo={PolicyBranchTypes={[3]={Type='POLICY_BRANCH_ORDER'}}}
        local p={GetPublicOpinionType=function() return 1 end,
          GetPublicOpinionUnhappiness=function() return 8 end,
          GetPublicOpinionPreferredIdeology=function() return 3 end,
          GetPublicOpinionTooltip=function() return 'They prefer Order' end}
        Players={[0]=p}
        local r=H.public_opinion(0)
        assert(r.type=='PUBLIC_OPINION_DISSIDENTS' and r.unhappiness==8)
        assert(r.preferred_ideology=='POLICY_BRANCH_ORDER' and r.tooltip=='They prefer Order')
        """)

    def test_available_research_includes_help_text(self):
        self.run_lua("""
        GameInfo={Technologies=function() local i=0; local rows={{ID=1,Type='TECH_STEEL',Help='TXT_KEY_TECH_STEEL_HELP'}}
          return function() i=i+1; return rows[i] end end}
        local p={GetCurrentResearch=function() return 1 end, CanResearch=function() return true end,
          GetResearchTurnsLeft=function() return 8 end, GetResearchCost=function() return 780 end}
        Players={[0]=p}
        local r=H.available_research(0)
        assert(#r==1 and r[1].tech=='TECH_STEEL' and r[1].help==nil and r[1].current)  -- v216: help is in reference('techs')
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
            g = SimpleNamespace(seat=0, turn_state=lambda state=state: state, discussion_pending=lambda: False,
                                dismiss_pending_popups=lambda: [])
            def action():
                return '{"ok":true}'
            action.__name__ = tool
            with patch.object(mcp_server, "game", return_value=g), patch.object(
                    mcp_server, "action_lock", return_value=contextlib.nullcontext()):
                self.assertTrue(json.loads(mcp_server.guarded(action)())["ok"])
                action.__name__ = "change_specialist"
                self.assertFalse(json.loads(mcp_server.guarded(action)())["ok"])

    def test_city_strike_kill_reports_damage_dealt(self):
        g = Game.__new__(Game)
        g.seat = 0
        g._pid = lambda pid=None: 0
        readings = iter([
            {"visible": True, "units": [{"id": 9, "owner": 63, "type": "UNIT_BRUTE", "hp": 17}]},
            {"visible": True, "units": []},
        ])
        g.plot_units = lambda *a, **k: next(readings)
        with patch("harness.game.time.sleep"), patch("harness.game.time.monotonic", side_effect=[0, 0.1]):
            r = g._with_target_result(4, 5, lambda: {"ok": True})
        self.assertEqual(r["killed"], ["UNIT_BRUTE"])
        self.assertEqual(r["damage_dealt"], 17)

    def test_python_empty_queue_is_not_labelled_a_process(self):
        empty = Game._normalize_production_turns(
            {"production": "", "needs_production": True, "production_turns": 2**31 - 1})
        self.assertIsNone(empty["production_turns"])
        self.assertNotIn("production_note", empty)
        wealth = Game._normalize_production_turns(
            {"production": "Wealth", "needs_production": False, "production_turns": 2**31 - 1})
        self.assertIsNone(wealth["production_turns"])
        self.assertIn("process", wealth["production_note"])

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
