"""A spread report must say what the charge bought, including "nothing".

Live t205: a Missionary carrying Catholicism (not our Tengriism -- nothing in `units` or
`available_unit_actions` said which religion it held) spent its last charge on Cusco, a puppet that
was already Catholic with 4 of its 5 citizens. The reply read `converted: true`, followers 4 -> 4.
Both halves are fixed: the unit now carries its religion in every read, and `converted` means this
spread changed the majority.
"""
import unittest

from harness.game import spread_effects


def before(**kw):
    base = {"ok": True, "city": "Cusco", "city_owner": 0, "population": 5,
            "unit_religion": 2, "unit_religion_name": "Catholicism",
            "followers": 4, "majority_name": "Catholicism", "spreads_left": 1}
    base.update(kw)
    return base


def after(**kw):
    base = {"ok": True, "followers": 4, "majority_name": "Catholicism", "spreads_left": 0}
    base.update(kw)
    return base


class SpreadEffectsTest(unittest.TestCase):
    def test_a_city_that_already_followed_it_is_not_a_conversion(self):
        eff = spread_effects(before(), after())
        self.assertFalse(eff["converted"])
        self.assertTrue(eff["already_majority"])
        self.assertFalse(eff["gained_followers"])
        self.assertIn("bought nothing", eff["note"])

    def test_flipping_the_majority_is_a_conversion(self):
        eff = spread_effects(before(followers=1, majority_name="Tengriism"),
                             after(followers=4, majority_name="Catholicism"))
        self.assertTrue(eff["converted"])
        self.assertFalse(eff["already_majority"])
        self.assertTrue(eff["gained_followers"])
        self.assertNotIn("note", eff)

    def test_followers_without_a_majority_are_not_a_conversion(self):
        """The t333 regression: 2 -> 3 of 10 with nobody in the majority read as converted."""
        eff = spread_effects(before(followers=2, majority_name=-1),
                             after(followers=3, majority_name=-1))
        self.assertFalse(eff["converted"])
        self.assertTrue(eff["gained_followers"])
        self.assertIsNone(eff["majority_after"])
        self.assertIn("another spread can tip it", eff["note"])

    def test_topping_up_followers_in_a_city_that_is_already_ours_still_counts_as_progress(self):
        eff = spread_effects(before(followers=3), after(followers=5))
        self.assertFalse(eff["converted"], "the majority did not change hands")
        self.assertTrue(eff["already_majority"])
        self.assertTrue(eff["gained_followers"])
        self.assertNotIn("note", eff, "followers were gained, so the charge was not wasted")

    def test_a_city_that_could_not_be_re_read_reports_unknown_not_false(self):
        eff = spread_effects(before(), {"ok": False})
        self.assertIsNone(eff["converted"])
        self.assertIsNone(eff["gained_followers"])
        self.assertEqual(eff["religion"], "Catholicism")

    def test_a_city_state_spread_keeps_the_influence_it_bought(self):
        eff = spread_effects(before(influence=30, majority_name="Tengriism", followers=0),
                             after(influence=45, followers=3))
        self.assertEqual((eff["influence_before"], eff["influence_after"]), (30, 45))
        self.assertTrue(eff["converted"])


if __name__ == "__main__":
    unittest.main()
