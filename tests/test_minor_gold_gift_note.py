"""minor_gold_gift's note after a gift that did not make us ally.

Grok (Venice/Mongolia 2026-09-27): a gift landing under the threshold answered `still_short` although
city_state_gifts said `ally.none` -- nobody held the alliance, so nothing was missed. The two cases now
read differently: a rival above us is `still_short`, an empty alliance is `to_become_ally`.
"""
import unittest

from harness.game import Game


class G(Game):
    def __init__(self, ally):
        self.seat = 0
        self.n = 0
        self.ally = ally

    def q(self, code, *a, **k):
        return {"ok": True, "amount": 250}

    def city_state_gifts(self, minor_id, pid=None):
        self.n += 1
        return {"friendship": 5 if self.n == 1 else 40, "gold": 700 if self.n == 1 else 450,
                "allied": False, "friends": True, "ally": self.ally}


class GiftNoteTests(unittest.TestCase):
    def test_no_ally_at_all_is_a_threshold_not_a_lost_race(self):
        r = G({"none": True, "to_become_ally": 20}).minor_gold_gift(26, 250)
        self.assertTrue(r["ok"])
        self.assertEqual(r["to_become_ally"], 20)
        self.assertNotIn("still_short", r)
        self.assertIn("no civ holds the alliance yet", r["note"])
        self.assertIn("20 more Influence makes us ally", r["note"])

    def test_a_rival_above_us_is_still_short(self):
        r = G({"civ": "Ethiopia", "player": 4, "to_become_ally": 43}).minor_gold_gift(26, 250)
        self.assertEqual(r["still_short"], 43)
        self.assertIn("Ethiopia still holds the alliance", r["note"])


if __name__ == "__main__":
    unittest.main()
