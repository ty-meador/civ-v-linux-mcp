"""The itemised combat-modifier rows EnemyUnitPanel shows beside the damage numbers.

Each fake here defines only the engine methods whose rows the case is about: a modifier the runtime
cannot read must drop its own row, so a row that does appear proves the runtime called the method the
stock panel calls, by that name, with those arguments.
"""
import unittest

import test_mcp_safety as support


WORLD = """
DomainTypes={DOMAIN_LAND=0,DOMAIN_SEA=1,DOMAIN_AIR=2}
GameDefines={MAX_HIT_POINTS=100,BONUS_PER_ADJACENT_FRIEND=10,RIVER_ATTACK_MODIFIER=-20,
  AMPHIB_ATTACK_MODIFIER=-50,POLICY_ATTACK_BONUS_MOD=20,SAPPED_CITY_ATTACK_MODIFIER=50}
Locale={ConvertTextKey=function(key,arg)
  if arg~=nil then return key..'['..tostring(arg)..']' end
  return key
end}
Map={PlotDistance=function(x1,y1,x2,y2) return math.abs(x1-x2)+math.abs(y1-y2) end}
Game.GetHandicapType=function() return 3 end
GameInfo={
  Terrains=setmetatable({TERRAIN_HILL={ID=7,Description='HILL'}},
    {__index=function(t,k) if k==7 then return {Description='HILL'} end
       return {Description='TERRAIN'..tostring(k)} end}),
  Features=setmetatable({},{__index=function(_,k) return {Description='FEATURE'..tostring(k)} end}),
  UnitClasses=setmetatable({},{__index=function(_,k) return {Description='CLASS'..tostring(k)} end}),
  UnitCombatInfos=setmetatable({},{__index=function(_,k) return {Description='COMBAT'..tostring(k)} end}),
  Units=setmetatable({},{__index=function(_,k) return {Type='UNIT_'..tostring(k)} end}),
  HandicapInfos=setmetatable({},{__index=function(_,k) return {BarbarianBonus=25} end}),
}

-- A plot with every terrain question answered "no" unless a case overrides it.
function bare_plot(x,y)
  return {GetX=function() return x end,GetY=function() return y end,
    IsWater=function() return false end,IsHills=function() return false end,
    IsOpenGround=function() return false end,IsRoughGround=function() return false end,
    IsRiverCrossingToPlot=function() return false end,
    IsFriendlyTerritory=function() return false end,
    GetOwner=function() return -1 end,
    GetFeatureType=function() return -1 end,GetTerrainType=function() return 2 end}
end

function player(id)
  return {IsGoldenAge=function() return false end,IsEmpireVeryUnhappy=function() return false end,
    IsMinorCiv=function() return false end}
end
Players={[0]=player(0),[1]=player(1)}

-- Only the methods the previews themselves need; modifier methods are added per case.
function bare_unit(owner,plot)
  return {GetOwner=function() return owner end,GetPlot=function() return plot end,
    GetDamage=function() return 0 end,IsCombatUnit=function() return true end,
    IsBarbarian=function() return false end}
end
"""


class CombatModifierRowTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)
        self.run_lua("""
        target_plot=bare_plot(4,5)
        source_plot=bare_plot(3,5)
        attacker=bare_unit(0,source_plot)
        defender=bare_unit(1,target_plot)
        city_plot=bare_plot(9,9)
        city={Plot=function() return city_plot end,GetOwner=function() return 1 end}
        function keys(rows)
          local out={}
          for i,r in ipairs(rows) do out[i]=r.key end
          return table.concat(out,',')
        end
        function row(rows,key)
          for _,r in ipairs(rows) do if r.key==key then return r end end
          return nil
        end
        """)

    def test_attacker_rows_carry_localized_text_value_and_percent_flag(self):
        self.run_lua("""
        attacker.GetExtraCombatPercent=function() return 15 end
        local m=H.combat_modifiers(attacker,defender,nil,false,0)
        local r=row(m.mine,'TXT_KEY_EUPANEL_EXTRA_PERCENT')
        assert(r and r.value==15 and r.percent==true)
        assert(r.text=='TXT_KEY_EUPANEL_EXTRA_PERCENT')
        """)

    def test_zero_and_unreadable_modifiers_drop_only_their_own_row(self):
        self.run_lua("""
        attacker.GetExtraCombatPercent=function() return 0 end
        attacker.GetAttackModifier=function() error('unreadable') end
        attacker.HillsAttackModifier=function() return 30 end
        target_plot.IsHills=function() return true end
        local m=H.combat_modifiers(attacker,defender,nil,false,0)
        assert(row(m.mine,'TXT_KEY_EUPANEL_EXTRA_PERCENT')==nil)
        assert(row(m.mine,'TXT_KEY_EUPANEL_ATTACK_MOD_BONUS')==nil)
        assert(row(m.mine,'TXT_KEY_EUPANEL_HILL_ATTACK_BONUS').value==30)
        """)

    def test_melee_terrain_and_flanking_rows_match_the_panel_formula(self):
        self.run_lua("""
        source_plot.IsRiverCrossingToPlot=function(_,to) assert(to==target_plot); return true end
        attacker.IsRiverCrossingNoPenalty=function() return false end
        attacker.FlankAttackModifier=function() return 50 end
        defender.GetNumEnemyUnitsAdjacent=function(_,other) assert(other==attacker); return 2 end
        target_plot.IsRoughGround=function() return true end
        attacker.RoughAttackModifier=function() return 25 end
        local m=H.combat_modifiers(attacker,defender,nil,false,0)
        assert(row(m.mine,'TXT_KEY_EUPANEL_ATTACK_OVER_RIVER').value==-20)
        -- 2 adjacent friends x 10, scaled by the unit's +50% flank promotion
        assert(row(m.mine,'TXT_KEY_EUPANEL_FLANKING_BONUS').value==30)
        assert(row(m.mine,'TXT_KEY_EUPANEL_ROUGH_TERRAIN_BONUS').value==25)
        """)

    def test_ranged_attack_omits_the_melee_only_rows(self):
        self.run_lua("""
        source_plot.IsRiverCrossingToPlot=function() return true end
        attacker.IsRiverCrossingNoPenalty=function() return false end
        defender.GetNumEnemyUnitsAdjacent=function() return 2 end
        attacker.GetRangedAttackModifier=function() return 40 end
        local m=H.combat_modifiers(attacker,defender,nil,true,0)
        assert(row(m.mine,'TXT_KEY_EUPANEL_ATTACK_OVER_RIVER')==nil)
        assert(row(m.mine,'TXT_KEY_EUPANEL_FLANKING_BONUS')==nil)
        assert(row(m.mine,'TXT_KEY_EUPANEL_RANGED_ATTACK_MODIFIER').value==40)
        assert(row(m.theirs,'TXT_KEY_EUPANEL_FLANKING_BONUS')==nil)
        """)

    def test_defender_rows_name_the_attacking_class_and_terrain(self):
        self.run_lua("""
        attacker.GetUnitClassType=function() return 4 end
        attacker.GetUnitCombatType=function() return 1 end
        defender.UnitClassDefenseModifier=function(_,cls) assert(cls==4); return 33 end
        defender.UnitCombatModifier=function(_,ct) assert(ct==1); return 10 end
        defender.FortifyModifier=function() return 25 end
        defender.TerrainDefenseModifier=function(_,t) assert(t==2); return 20 end
        local m=H.combat_modifiers(attacker,defender,nil,false,0)
        assert(row(m.theirs,'TXT_KEY_EUPANEL_FORTIFICATION_BONUS').value==25)
        assert(row(m.theirs,'TXT_KEY_EUPANEL_BONUS_DEFENSE_TERRAIN').text=='TXT_KEY_EUPANEL_BONUS_DEFENSE_TERRAIN[TERRAIN2]')
        local class_rows={}
        for _,r in ipairs(m.theirs) do
          if r.key=='TXT_KEY_EUPANEL_BONUS_VS_CLASS' then class_rows[#class_rows+1]=r.text end
        end
        assert(#class_rows==2)
        assert(class_rows[1]=='TXT_KEY_EUPANEL_BONUS_VS_CLASS[CLASS4]')
        assert(class_rows[2]=='TXT_KEY_EUPANEL_BONUS_VS_CLASS[COMBAT1]')
        """)

    def test_a_feature_replaces_the_terrain_row_and_hills_adds_its_own(self):
        self.run_lua("""
        defender.FeatureDefenseModifier=function(_,f) assert(f==5); return 50 end
        defender.TerrainDefenseModifier=function() return 20 end
        target_plot.GetFeatureType=function() return 5 end
        local m=H.combat_modifiers(attacker,defender,nil,false,0)
        local rows={}
        for _,r in ipairs(m.theirs) do
          if r.key=='TXT_KEY_EUPANEL_BONUS_DEFENSE_TERRAIN' then rows[#rows+1]=r.text end
        end
        assert(#rows==1 and rows[1]=='TXT_KEY_EUPANEL_BONUS_DEFENSE_TERRAIN[FEATURE5]')

        target_plot.GetFeatureType=function() return -1 end
        target_plot.IsHills=function() return true end
        m=H.combat_modifiers(attacker,defender,nil,false,0)
        rows={}
        for _,r in ipairs(m.theirs) do
          if r.key=='TXT_KEY_EUPANEL_BONUS_DEFENSE_TERRAIN' then rows[#rows+1]=r.text end
        end
        assert(#rows==2 and rows[2]=='TXT_KEY_EUPANEL_BONUS_DEFENSE_TERRAIN[HILL]')
        """)

    def test_a_non_combat_defender_has_no_defender_rows(self):
        self.run_lua("""
        defender.FortifyModifier=function() return 25 end
        defender.IsCombatUnit=function() return false end
        local m=H.combat_modifiers(attacker,defender,nil,false,0)
        assert(#m.theirs==0)
        """)

    def test_great_general_block_adds_the_ignore_row_as_the_negated_bonus(self):
        self.run_lua("""
        Players[0].GetGreatGeneralCombatBonus=function() return 15 end
        Players[0].GetTraitGreatGeneralExtraBonus=function() return 10 end
        attacker.IsNearGreatGeneral=function() return true end
        attacker.GetDomainType=function() return DomainTypes.DOMAIN_SEA end
        attacker.IsIgnoreGreatGeneralBenefit=function() return true end
        local m=H.combat_modifiers(attacker,defender,nil,false,0)
        assert(row(m.mine,'TXT_KEY_EUPANEL_GA_NEAR').value==25)
        assert(row(m.mine,'TXT_KEY_EUPANEL_GG_NEAR')==nil)
        assert(row(m.mine,'TXT_KEY_EUPANEL_IGG').value==-25)
        """)

    def test_capital_defense_falls_off_with_distance_and_drops_at_zero(self):
        self.run_lua("""
        local capital={GetX=function() return 1 end,GetY=function() return 1 end}
        Players[1].GetCapitalCity=function() return capital end
        defender.GetX=function() return 4 end
        defender.GetY=function() return 5 end
        defender.CapitalDefenseModifier=function() return 25 end
        defender.CapitalDefenseFalloff=function() return -5 end
        -- distance 3+4=7, so 25 + 7*-5 = -10: the panel prints nothing
        local m=H.combat_modifiers(attacker,defender,nil,false,0)
        assert(row(m.theirs,'TXT_KEY_EUPANEL_CAPITAL_DEFENSE_BONUS')==nil)
        defender.CapitalDefenseFalloff=function() return -2 end
        m=H.combat_modifiers(attacker,defender,nil,false,0)
        assert(row(m.theirs,'TXT_KEY_EUPANEL_CAPITAL_DEFENSE_BONUS').value==11)
        """)

    def test_barbarian_bonus_sums_handicap_and_player_bonus(self):
        self.run_lua("""
        defender.IsBarbarian=function() return true end
        Players[0].GetBarbarianCombatBonus=function() return 33 end
        local m=H.combat_modifiers(attacker,defender,nil,false,0)
        assert(row(m.mine,'TXT_KEY_EUPANEL_VS_BARBARIANS_BONUS').value==58)
        """)

    def test_fire_support_row_is_a_flat_damage_not_a_percentage(self):
        self.run_lua("""
        local m=H.combat_modifiers(attacker,defender,nil,false,17)
        local r=row(m.mine,'TXT_KEY_EUPANEL_SUPPORT_DMG')
        assert(r.value==17 and r.percent==false)
        assert(H.combat_modifiers(attacker,defender,nil,false,0).mine[1]==nil
          or row(H.combat_modifiers(attacker,defender,nil,false,0).mine,'TXT_KEY_EUPANEL_SUPPORT_DMG')==nil)
        """)

    def test_air_strike_notes_carry_no_value_and_capture_chance_is_melee_only(self):
        self.run_lua("""
        attacker.GetCaptureChance=function(_,other) assert(other==defender); return 67 end
        local air=H.combat_modifiers(attacker,defender,nil,true,0,true,2)
        assert(keys(air.theirs)=='TXT_KEY_EUPANEL_AIR_INTERCEPT_WARNING1,'..
          'TXT_KEY_EUPANEL_AIR_INTERCEPT_WARNING2,TXT_KEY_EUPANEL_VISIBLE_AA_UNITS')
        for _,r in ipairs(air.theirs) do assert(r.value==nil and r.percent==nil) end
        assert(row(air.theirs,'TXT_KEY_EUPANEL_VISIBLE_AA_UNITS').text=='TXT_KEY_EUPANEL_VISIBLE_AA_UNITS[2]')

        local melee=H.combat_modifiers(attacker,defender,nil,false,0)
        assert(row(melee.theirs,'TXT_KEY_EUPANEL_CAPTURE_CHANCE').text=='TXT_KEY_EUPANEL_CAPTURE_CHANCE[67]')
        local ranged=H.combat_modifiers(attacker,defender,nil,true,0)
        assert(row(ranged.theirs,'TXT_KEY_EUPANEL_CAPTURE_CHANCE')==nil)
        """)

    def test_a_city_target_gets_city_rows_and_no_defender_column(self):
        self.run_lua("""
        attacker.CityAttackModifier=function() return 33 end
        attacker.IsNearSapper=function(_,target) assert(target==city); return true end
        Players[0].GetAttackBonusTurns=function() return 4 end
        local m=H.combat_modifiers(attacker,nil,city,false,0)
        assert(row(m.mine,'TXT_KEY_EUPANEL_ATTACK_CITIES').value==33)
        assert(row(m.mine,'TXT_KEY_EUPANEL_ATTACK_CITIES_PENALTY')==nil)
        assert(row(m.mine,'TXT_KEY_EUPANEL_CITY_SAPPED').value==50)
        assert(row(m.mine,'TXT_KEY_EUPANEL_POLICY_ATTACK_BONUS').text=='TXT_KEY_EUPANEL_POLICY_ATTACK_BONUS[4]')
        assert(#m.theirs==0)
        attacker.CityAttackModifier=function() return -33 end
        m=H.combat_modifiers(attacker,nil,city,false,0)
        assert(row(m.mine,'TXT_KEY_EUPANEL_ATTACK_CITIES')==nil)
        assert(row(m.mine,'TXT_KEY_EUPANEL_ATTACK_CITIES_PENALTY').value==-33)
        """)

    def test_city_strike_lists_the_city_strike_modifiers_and_the_short_defender_list(self):
        self.run_lua("""
        local garrison={}
        local striker={GetOwner=function() return 0 end,
          GetGarrisonedUnit=function() return garrison end,
          GetReligionCityRangeStrikeModifier=function() return 10 end}
        Players[0].GetGarrisonedCityRangeStrikeModifier=function() return 15 end
        defender.FortifyModifier=function() return 25 end
        defender.GetNearbyImprovementModifier=function() return 40 end
        defender.GetReverseGreatGeneralModifier=function() return 20 end
        defender.GetDefenseModifier=function() return 5 end
        defender.IsNearSapper=function(_,target) assert(target==striker); return true end
        local m=H.city_strike_modifiers(striker,defender)
        assert(row(m.mine,'TXT_KEY_EUPANEL_GARRISONED_CITY_RANGE_BONUS').value==15)
        assert(row(m.mine,'TXT_KEY_EUPANEL_BONUS_RELIGIOUS_BELIEF').value==10)
        assert(row(m.theirs,'TXT_KEY_EUPANEL_FORTIFICATION_BONUS').value==25)
        assert(row(m.theirs,'TXT_KEY_EUPANEL_DEFENSE_BONUS').value==5)
        assert(row(m.theirs,'TXT_KEY_EUPANEL_CITY_SAPPED').value==50)
        -- the city-vs-unit panel has no reverse-general or nearby-improvement row
        assert(row(m.theirs,'TXT_KEY_EUPANEL_REVERSE_GG_NEAR')==nil)
        assert(row(m.theirs,'TXT_KEY_EUPANEL_IMPROVEMENT_NEAR')==nil)
        """)

    def test_city_strike_without_a_garrison_omits_the_garrison_row(self):
        self.run_lua("""
        local striker={GetOwner=function() return 0 end,
          GetGarrisonedUnit=function() return nil end,
          GetReligionCityRangeStrikeModifier=function() return 0 end}
        Players[0].GetGarrisonedCityRangeStrikeModifier=function() return 15 end
        local m=H.city_strike_modifiers(striker,defender)
        assert(#m.mine==0)
        """)

    def test_melee_preview_attaches_the_modifier_columns(self):
        self.run_lua("""
        attacker.GetMaxAttackStrength=function() return 3000 end
        attacker.GetFireSupportUnit=function() return nil end
        attacker.GetCombatDamage=function() return 40 end
        attacker.AttackWoundedModifier=function() return 33 end
        defender.GetMaxDefenseStrength=function() return 2400 end
        defender.GetCombatDamage=function() return 20 end
        defender.GetDamage=function() return 10 end
        local p=H.melee_preview(attacker,defender)
        assert(p.expected_damage_dealt==40 and p.expected_damage_taken==20)
        assert(row(p.modifiers.mine,'TXT_KEY_EUPANEL_BONUS_VS_WOUND_UNITS').value==33)
        """)


class CityStrikePreviewCapTests(unittest.TestCase):
    """available_city_strikes caps at the panel's maximum hit points, not the hp the unit has left."""

    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(WORLD)
        self.run_lua("""
        UI={SelectCity=function() error('SelectCity') end}
        GameDefines.MAX_CITY_ATTACK_RANGE=1
        their_plot=bare_plot(6,5)
        their_unit=bare_unit(1,their_plot)
        their_unit.GetID=function() return 77 end
        their_unit.GetCurrHitPoints=function() return 30 end
        their_unit.GetUnitType=function() return 1 end
        their_unit.FortifyModifier=function() return 25 end
        their_plot.IsVisible=function() return true end
        their_plot.GetNumUnits=function() return 1 end
        their_plot.GetUnit=function() return their_unit end
        their_plot.IsCity=function() return false end
        striker={GetX=function() return 5 end,GetY=function() return 5 end,
          GetOwner=function() return 0 end,GetID=function() return 1 end,
          CanRangeStrike=function() return true end,
          CanRangeStrikeAt=function(_,x,y) return x==6 and y==5 end,
          RangeCombatDamage=function() return 240 end,
          GetStrengthValue=function() return 4500 end,
          RangeCombatUnitDefense=function(_,u) assert(u==their_unit); return 2600 end,
          GetGarrisonedUnit=function() return nil end,
          GetReligionCityRangeStrikeModifier=function() return 0 end}
        Players[0].GetCityByID=function() return striker end
        Players[0].GetTeam=function() return 0 end
        Map.PlotXYWithRangeCheck=function(x,y,dx,dy,r)
          if dx==1 and dy==0 then return their_plot end
          local p=bare_plot(x+dx,y+dy); p.IsVisible=function() return false end; return p
        end
        """)

    def test_estimate_is_capped_at_max_hit_points_not_remaining_hit_points(self):
        self.run_lua("""
        local t=H.available_city_strikes(1,0).targets[1]
        assert(t.preview.expected_damage_dealt==100)
        assert(t.preview.expected_damage_taken==0)
        """)

    def test_both_strengths_and_the_modifier_columns_are_reported(self):
        self.run_lua("""
        local t=H.available_city_strikes(1,0).targets[1]
        assert(t.preview.my_strength==45 and t.preview.their_strength==26)
        local found=false
        for _,r in ipairs(t.preview.modifiers.theirs) do
          if r.key=='TXT_KEY_EUPANEL_FORTIFICATION_BONUS' and r.value==25 then found=true end
        end
        assert(found)
        """)


if __name__ == "__main__":
    unittest.main()
