"""Melee combat estimates match EnemyUnitPanel, including defensive fire support."""
import unittest

import test_mcp_safety as support


class MeleePreviewTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua("""
        GameDefines={MAX_HIT_POINTS=100}
        support_damage=17
        support_enabled=true
        target_plot={GetX=function() return 4 end,GetY=function() return 5 end}
        source_plot={}
        support_unit=setmetatable({GetRangeCombatDamage=function(_,unit,city,random)
          assert(unit==attacker and city==nil and random==false); return support_damage end},
          {__index=function(_,key) error('support identity/location must not be read: '..key) end})
        attacker={GetPlot=function() return source_plot end,GetDamage=function() return 20 end,
          GetMaxAttackStrength=function(_,from,to,unit)
            assert(from==source_plot and to==target_plot)
            assert(unit==defender or unit==nil); return 3000 end,
          GetFireSupportUnit=function(_,owner,x,y)
            assert(owner==1 and x==4 and y==5)
            if support_enabled then return support_unit end end,
          GetCombatDamage=function(_,mine,theirs,damage,random,attacking_city,defending_city)
            assert(random==false)
            if attacking_city then
              assert(mine==4000 and theirs==3000 and damage==30 and not defending_city)
              return 29
            end
            assert(mine==3000 and theirs==(defending_city and 4000 or 2400))
            return 80-damage
          end}
        defender={GetPlot=function() return target_plot end,GetOwner=function() return 1 end,
          GetDamage=function() return 10 end,
          GetMaxDefenseStrength=function(_,plot,unit)
            assert(plot==target_plot and unit==attacker); return 2400 end,
          GetCombatDamage=function(_,mine,theirs,damage,random,attacking_city,defending_city)
            assert(mine==2400 and theirs==3000 and damage==10)
            assert(not random and not attacking_city and not defending_city); return 23 end}
        city={Plot=function() return target_plot end,GetOwner=function() return 1 end,
          GetStrengthValue=function() return 4000 end,GetDamage=function() return 30 end,
          GetMaxHitPoints=function() return 250 end}
        """)

    def test_unit_fire_support_reduces_outgoing_damage_and_adds_incoming_damage(self):
        self.run_lua("""
        local r=H.melee_preview(attacker,defender)
        assert(r.my_strength==30 and r.their_strength==24)
        assert(r.fire_support_damage==17)
        assert(r.expected_damage_dealt==43 and r.expected_damage_taken==40)
        """)

    def test_city_fire_support_uses_city_flags_and_owner(self):
        self.run_lua("""
        local r=H.melee_city_preview(attacker,city)
        assert(r.my_strength==30 and r.their_strength==40)
        assert(r.fire_support_damage==17)
        assert(r.expected_damage_dealt==43 and r.expected_damage_taken==46)
        """)

    def test_no_support_preserves_normal_damage(self):
        self.run_lua("""
        support_enabled=false
        local unit=H.melee_preview(attacker,defender)
        local town=H.melee_city_preview(attacker,city)
        assert(unit.fire_support_damage==0 and town.fire_support_damage==0)
        assert(unit.expected_damage_dealt==60 and unit.expected_damage_taken==23)
        assert(town.expected_damage_dealt==60 and town.expected_damage_taken==29)
        """)

    def test_damage_caps_match_panel_maximum_hp_not_remaining_hp(self):
        self.run_lua("""
        attacker.GetCombatDamage=function() return 400 end
        defender.GetCombatDamage=function() return 400 end
        local unit=H.melee_preview(attacker,defender)
        local town=H.melee_city_preview(attacker,city)
        assert(unit.expected_damage_dealt==100 and unit.expected_damage_taken==100)
        assert(town.expected_damage_dealt==250 and town.expected_damage_taken==100)
        """)

    def test_failed_support_read_leaves_damage_unknown_but_keeps_strength(self):
        self.run_lua("""
        for _,fail in ipairs({function() error('unavailable') end,
          function() return {GetRangeCombatDamage=function() error('unavailable') end} end}) do
          attacker.GetFireSupportUnit=fail
          for _,r in ipairs({H.melee_preview(attacker,defender),H.melee_city_preview(attacker,city)}) do
            assert(r.my_strength==30 and r.their_strength~=nil)
            assert(r.expected_damage_dealt==nil and r.expected_damage_taken==nil)
            assert(r.fire_support_damage==nil)
          end
        end
        """)


if __name__ == '__main__':
    unittest.main()
