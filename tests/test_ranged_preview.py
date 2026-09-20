"""EnemyUnitPanel parity for ranged strength, air retaliation and visible targets."""
import unittest

import test_mcp_safety as support


class RangedPreviewTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua("""
        DomainTypes={DOMAIN_LAND=0,DOMAIN_SEA=1,DOMAIN_AIR=2}
        target_plot={}
        attacker={GetDomainType=function() return DomainTypes.DOMAIN_AIR end,
          GetRangeCombatDamage=function(_,unit,city,random)
            assert((unit~=nil)~=(city~=nil)); assert(random==false); return 41 end,
          GetMaxRangedCombatStrength=function(_,unit,city,attack,for_ranged)
            assert((unit~=nil)~=(city~=nil)); assert(attack and for_ranged); return 3250 end,
          GetInterceptorCount=function(_,plot,unit,land_only,visible_only)
            assert(plot==target_plot and land_only==true and visible_only==true)
            assert(unit==defender); return 2 end}
        defender={GetPlot=function() return target_plot end,
          GetDomainType=function() return DomainTypes.DOMAIN_LAND end,
          IsEmbarked=function() return false end, IsRangedSupportFire=function() return false end,
          GetMaxRangedCombatStrength=function(_,unit,city,attack,for_ranged)
            assert(unit==attacker and city==nil and attack==false and for_ranged==true); return 1800 end,
          GetMaxDefenseStrength=function(_,plot,unit,ranged)
            assert(plot==target_plot and unit==attacker and ranged==true); return 2400 end,
          GetAirStrikeDefenseDamage=function(_,unit,random)
            assert(unit==attacker and random==false); return 17 end}
        """)

    def test_air_vs_unit_reports_retaliation_strength_and_visible_interceptors(self):
        self.run_lua("""
        local r=H.ranged_preview(attacker,defender,nil)
        assert(r.expected_damage_dealt==41 and r.expected_damage_taken==17)
        assert(r.my_strength==32.5 and r.their_strength==18)
        assert(r.visible_interceptors==2 and r.interception_possible)
        assert(r.interception_warning:find('excludes interception',1,true))
        """)

    def test_air_vs_city_uses_city_retaliation_and_warns_even_without_visible_aa(self):
        self.run_lua("""
        local city={Plot=function() return target_plot end,GetStrengthValue=function() return 4075 end,
          GetAirStrikeDefenseDamage=function(_,unit,random)
            assert(unit==attacker and random==false); return 23 end}
        attacker.GetInterceptorCount=function(_,plot,unit,land_only,visible_only)
          assert(plot==target_plot and unit==nil and land_only and visible_only); return 0 end
        local r=H.ranged_preview(attacker,nil,city)
        assert(r.expected_damage_dealt==41 and r.expected_damage_taken==23)
        assert(r.my_strength==32.5 and r.their_strength==40.75)
        assert(r.visible_interceptors==0 and r.interception_possible and r.interception_warning)
        """)

    def test_ground_ranged_has_no_retaliation_or_interceptor_read(self):
        self.run_lua("""
        local air_reads=0
        attacker.GetDomainType=function() return DomainTypes.DOMAIN_LAND end
        attacker.GetInterceptorCount=function() air_reads=air_reads+1; return 2 end
        defender.GetAirStrikeDefenseDamage=function() air_reads=air_reads+1; return 17 end
        local r=H.ranged_preview(attacker,defender,nil)
        assert(r.expected_damage_taken==0 and r.expected_damage_dealt==41 and r.their_strength==18)
        assert(r.interception_possible==nil and r.visible_interceptors==nil and r.interception_warning==nil)
        assert(air_reads==0)
        """)

    def test_ranged_defense_matches_embarked_naval_support_and_melee_branches(self):
        self.run_lua("""
        defender.IsEmbarked=function() return true end
        defender.GetEmbarkedUnitDefense=function() return 700 end
        assert(H.ranged_preview(attacker,defender,nil).their_strength==7)
        defender.IsEmbarked=function() return false end
        defender.GetDomainType=function() return DomainTypes.DOMAIN_SEA end
        assert(H.ranged_preview(attacker,defender,nil).their_strength==24)
        defender.GetDomainType=function() return DomainTypes.DOMAIN_LAND end
        defender.IsRangedSupportFire=function() return true end
        assert(H.ranged_preview(attacker,defender,nil).their_strength==24)
        defender.IsRangedSupportFire=function() return false end
        defender.GetMaxRangedCombatStrength=function() return 0 end
        assert(H.ranged_preview(attacker,defender,nil).their_strength==24)
        """)

    def test_failed_air_retaliation_stays_unknown_not_zero(self):
        self.run_lua("""
        defender.GetAirStrikeDefenseDamage=function() error('unavailable') end
        local r=H.ranged_preview(attacker,defender,nil)
        assert(r.expected_damage_taken==nil and r.expected_damage_dealt==41)
        assert(r.interception_possible and r.visible_interceptors==2 and r.their_strength==18)
        """)

    def test_target_details_skip_fog_invisible_and_peaceful_units(self):
        self.run_lua("""
        Players={[0]={GetTeam=function() return 0 end},[1]={GetTeam=function() return 1 end},
          [2]={GetTeam=function() return 2 end}}
        Teams={[0]={IsAtWar=function(_,team) return team==1 end}}
        local fog=setmetatable({IsVisible=function() return false end},
          {__index=function(_,key) error('fog read: '..key) end})
        assert(next(H.ranged_target_info(attacker,fog,0))==nil)
        local hidden=setmetatable({IsInvisible=function() return true end},
          {__index=function(_,key) error('invisible unit read: '..key) end})
        local neutral={IsInvisible=function() return false end,GetOwner=function() return 2 end}
        defender.IsInvisible=function() return false end
        defender.GetOwner=function() return 1 end; defender.GetID=function() return 7 end
        target_plot.IsVisible=function() return true end; target_plot.GetPlotCity=function() end
        target_plot.GetNumUnits=function() return 3 end
        target_plot.GetUnit=function(_,i) return ({hidden,neutral,defender})[i+1] end
        H.combat_side=function(pid,uid,viewer)
          assert(pid==1 and uid==7 and viewer==0); return {unit='INFANTRY',hp=80} end
        local r=H.ranged_target_info(attacker,target_plot,0)
        assert(r.unit=='INFANTRY' and r.hp==80 and r.preview.expected_damage_taken==17)
        """)

    def test_airstrike_target_page_has_city_preview_and_never_reads_garrison_or_fog(self):
        self.run_lua("""
        Players={[0]={GetTeam=function() return 0 end,GetUnitByID=function() return attacker end},
          [1]={GetTeam=function() return 1 end}}
        Teams={[0]={IsAtWar=function(_,team) return team==1 end}}
        H.targeted_missions=function() return {{type='INTERFACEMODE_AIRSTRIKE',mission='MISSION_MOVE_TO'}} end
        local city={GetOwner=function() return 1 end,GetName=function() return 'City' end,
          GetMaxHitPoints=function() return 200 end,GetDamage=function() return 30 end,
          GetStrengthValue=function() return 4075 end,Plot=function() return target_plot end,
          GetAirStrikeDefenseDamage=function() return 23 end}
        attacker.GetPlot=function() return {} end; attacker.MovesLeft=function() return 60 end
        attacker.CanRangeStrikeAt=function(_,x,y,war,visible)
          assert(x~=1 and war and visible); return true end
        attacker.GetInterceptorCount=function(_,plot,unit,land_only,visible_only)
          assert(plot==target_plot and unit==nil and land_only and visible_only); return 0 end
        Map={GetNumPlots=function() return 3 end,GetPlotByIndex=function(i)
          local plot={IsVisible=function() return i~=1 end,GetX=function() return i end,GetY=function() return 0 end,
            GetPlotCity=function() assert(i==2,'off-page preview read'); return city end}
          return setmetatable(plot,{__index=function(_,key) error('unexpected plot read: '..key) end}) end}
        local r=H.unit_mission_targets(7,'MISSION_MOVE_TO',0,1,1)
        assert(r.total==2 and #r.targets==1 and r.next_offset==nil)
        local t=r.targets[1]
        assert(t.x==2 and t.city=='City' and t.owner==1 and t.hp==170)
        assert(t.preview.expected_damage_taken==23 and t.preview.visible_interceptors==0)
        """)


if __name__ == '__main__':
    unittest.main()
