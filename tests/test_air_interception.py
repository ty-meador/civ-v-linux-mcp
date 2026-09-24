"""An intercepted air strike says it was intercepted, and the strike preview stays inside the health bar.

Live 2026-09-24 (Alpha/Bravo hotseat): a Bomber sent at an Infantry next to an Anti-Aircraft Gun was
shot down on the way in. The pilot at the screen reads the banner "Your Bomber was shot down by an
enemy Anti-Aircraft Gun!"; the tool result only said my_unit_killed, which reads as if the strike itself
had gone wrong. The same session's air preview put expected_damage_taken above 100, a number the
stock EnemyUnitPanel clamps to MAX_HIT_POINTS before drawing it.
"""
import unittest

import test_mcp_safety as support
from harness.game import Game


BEST = {"player": 63, "id": 98314, "owner": "Barbarians", "unit": "ANTI_AIRCRAFT_GUN", "x": 2, "y": 11}


class FakeGame(Game):
    def __init__(self, after, alerts, before_count=1, after_count=1, best=BEST):
        self.seat = 0
        self._after = after
        self._alerts = alerts
        self._before = {"count": before_count}
        if best:
            self._before["best"] = dict(best)
        self._after_count = after_count
        self.calls: list[str] = []

    def q(self, lua, *a, **kw):
        self.calls.append(lua)
        if "H.attack_before" in lua:
            return {"attack": True, "def_player": 1, "def_unit": 55, "def_hp": 100, "my_hp": 100,
                    "air": {"can_strike": True, "range": 8}, "interception": self._before,
                    "defender": {"unit": "INFANTRY", "owner": "Bravo", "x": 6, "y": 11, "hp": 100, "max_hp": 100}}
        if "return H.event_seq" in lua:
            return 40
        if "H.alerts_since(40, 0)" in lua:
            return self._alerts
        if "H.interception_after(17, 6, 11, 1, 55, 0)" in lua:
            return {"count": self._after_count}
        if "H.attack_after" in lua:
            return dict(self._after)
        if "H.captured_at" in lua:
            return None
        if "H.unit_pos" in lua:
            return {"ok": True, "x": 3, "y": 9, "moves": 0}
        return {"ok": True}

    def _order(self, lua, *a, **kw):
        self.calls.append(lua)
        return {"ok": True, "x": 3, "y": 9, "moves": 0}


def strike(after, alerts, **kw):
    return Game.unit_mission(FakeGame(after, alerts, **kw), unit_id=17, mission="MISSION_MOVE_TO", x=6, y=11)["attack"]


class InterceptionResultTests(unittest.TestCase):
    def test_a_visible_interceptor_that_fired_drops_out_of_the_count(self):
        """Live 2026-09-24: 1 before, 0 after; the banner was only 'Your Bomber bombarded an enemy Infantry! (87 damage)'."""
        a = strike({"my_hp": 13, "def_hp": 91}, ["Your Bomber bombarded an enemy Infantry! (87 damage)"],
                   before_count=1, after_count=0)
        self.assertTrue(a["intercepted"])
        self.assertEqual(a["interceptor"]["unit"], "ANTI_AIRCRAFT_GUN")
        self.assertEqual((a["interceptor"]["x"], a["interceptor"]["y"]), (2, 11))
        self.assertNotIn("player", a["interceptor"], "the raw player id is not what a human sees; owner is")
        self.assertEqual(a["interceptor"]["owner"], "Barbarians")
        self.assertNotIn("shot_down", a)
        self.assertIn("still struck", a["note"])
        self.assertEqual(a["visible_interceptors_before"], 1)

    def test_an_exhausted_gun_does_not_fire_twice(self):
        """The second Bomber of the turn met a gun already out of interceptions: 0 before, 0 after."""
        a = strike({"my_hp": 1, "def_hp": 85}, ["Your Bomber bombarded an enemy Infantry! (24 damage)"],
                   before_count=0, after_count=0, best=None)
        self.assertNotIn("intercepted", a)
        self.assertNotIn("note", a)
        self.assertEqual(a["visible_interceptors_before"], 0)

    def test_dead_aircraft_and_untouched_target_is_a_shoot_down(self):
        a = strike({"my_unit_killed": True, "def_hp": 100}, [], before_count=1, after_count=1)
        self.assertTrue(a["intercepted"])
        self.assertTrue(a["shot_down"])
        self.assertIn("target is unhurt", a["note"])
        self.assertEqual(a["interceptor"]["unit"], "ANTI_AIRCRAFT_GUN", "the gun in sight before the strike is the one that fired")

    def test_dead_aircraft_whose_strike_still_landed(self):
        """Live 2026-09-24: a 40 hp Bomber struck for 1 damage and died; another aircraft read the count 1 -> 0."""
        a = strike({"my_unit_killed": True, "def_hp": 99}, [], before_count=1, after_count=0)
        self.assertTrue(a["intercepted"])
        self.assertTrue(a["shot_down"])
        self.assertIn("still landed", a["note"])
        self.assertEqual((a["interceptor"]["x"], a["interceptor"]["y"]), (2, 11))

    def test_an_unseen_interceptor_is_not_named(self):
        a = strike({"my_unit_killed": True, "def_hp": 100}, [], before_count=0, after_count=0, best=None)
        self.assertTrue(a["intercepted"])
        self.assertNotIn("interceptor", a)

    def test_banner_texts_naming_an_interception_are_honoured(self):
        a = strike({"my_hp": 60, "def_hp": 62},
                   ["Your Bomber was intercepted by an enemy Fighter! (40% Damage)"],
                   before_count=0, after_count=0, best=None)
        self.assertTrue(a["intercepted"])
        self.assertEqual(a["interceptor"], {"unit": "Fighter"})
        self.assertIn("still struck", a["note"])

    def test_a_clean_strike_carries_no_interception(self):
        a = strike({"my_hp": 89, "def_hp": 41}, ["Your Bomber bombarded an enemy Infantry! (11 damage)"],
                   before_count=1, after_count=1)
        self.assertNotIn("intercepted", a)
        self.assertNotIn("note", a)

    def test_banners_are_read_without_moving_the_digest_cursor(self):
        g = FakeGame({"my_hp": 89, "def_hp": 41}, [])
        Game.unit_mission(g, unit_id=17, mission="MISSION_MOVE_TO", x=6, y=11)
        self.assertTrue(any("H.alerts_since(40, 0)" in c for c in g.calls))
        self.assertFalse(any("H.take_events" in c for c in g.calls), "reading the banner must not consume the digest")

    def test_the_count_is_asked_after_a_dead_aircraft_too(self):
        g = FakeGame({"my_unit_killed": True, "def_hp": 99}, [])
        Game.unit_mission(g, unit_id=17, mission="MISSION_MOVE_TO", x=6, y=11)
        self.assertTrue(any("H.interception_after" in c for c in g.calls), "another aircraft of ours can read the count")


PREVIEW_WORLD = """
GameDefines = { MAX_HIT_POINTS = 100 }
DomainTypes = { DOMAIN_LAND = 0, DOMAIN_SEA = 1, DOMAIN_AIR = 2 }
H.combat_modifiers = function() return {} end
local plot = { GetX = function() return 6 end, GetY = function() return 11 end }
bomber = { GetDomainType = function() return 2 end, GetDamage = function() return 30 end,
           GetRangeCombatDamage = function() return 140 end,
           GetMaxRangedCombatStrength = function() return 7000 end,
           GetInterceptorCount = function() return 1 end }
infantry = { GetAirStrikeDefenseDamage = function() return 150 end, GetDamage = function() return 10 end,
             IsEmbarked = function() return false end, GetDomainType = function() return 0 end,
             GetMaxRangedCombatStrength = function() return 0 end, IsRangedSupportFire = function() return false end,
             GetMaxDefenseStrength = function() return 7000 end, GetPlot = function() return plot end }
city = { GetAirStrikeDefenseDamage = function() return 35 end, GetMaxHitPoints = function() return 250 end,
         GetStrengthValue = function() return 6000 end, GetDamage = function() return 0 end, Plot = function() return plot end }
"""


class PreviewClampTests(unittest.TestCase):
    run_lua = support.LuaRuntimeTests.run_lua

    def setUp(self):
        support.LuaRuntimeTests.setUp(self)
        self.run_lua(PREVIEW_WORLD)

    def test_air_preview_is_clamped_to_the_health_bar_and_says_who_dies(self):
        self.run_lua("""
        local p = H.ranged_preview(bomber, infantry, nil)
        assert(p.expected_damage_taken == 100, tostring(p.expected_damage_taken))
        assert(p.expected_damage_dealt == 100, tostring(p.expected_damage_dealt))
        assert(p.my_unit_would_die == true)
        assert(p.target_would_die == true)
        assert(p.interception_possible == true and p.visible_interceptors == 1)
        """)

    def test_city_preview_uses_the_citys_own_maximum_and_never_kills_it(self):
        self.run_lua("""
        bomber.GetRangeCombatDamage = function() return 300 end
        local p = H.ranged_preview(bomber, nil, city)
        assert(p.expected_damage_dealt == 250, tostring(p.expected_damage_dealt))
        assert(p.expected_damage_taken == 35)
        assert(p.my_unit_would_die == nil)
        assert(p.target_would_die == nil, 'a city is not killed by bombardment')
        """)

    def test_a_ground_unit_that_survives_is_not_flagged(self):
        self.run_lua("""
        bomber.GetRangeCombatDamage = function() return 40 end
        bomber.GetDomainType = function() return 0 end
        local p = H.ranged_preview(bomber, infantry, nil)
        assert(p.expected_damage_dealt == 40 and p.expected_damage_taken == 0)
        assert(p.my_unit_would_die == nil and p.target_would_die == nil)
        assert(p.interception_possible == nil)
        """)


if __name__ == "__main__":
    unittest.main()
