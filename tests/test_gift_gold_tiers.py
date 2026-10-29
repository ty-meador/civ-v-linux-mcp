"""order(to='city_state', action='gift_gold'): the tier by name or amount, the refusal with the tiers (GitLab #113, #118)."""
import unittest

from harness.game import Game


def game(gold=244):
    g = object.__new__(Game)
    tiers = {"small": {"amount": 250, "friendship": 15, "affordable": gold >= 250, "makes_ally": True,
                       "call": {"tool": "order", "args": {"to": "city_state", "action": "gift_gold", "id": 37, "args": {"amount": 250}}}},
             "medium": {"amount": 500, "friendship": 35, "affordable": gold >= 500},
             "large": {"amount": 1000, "friendship": 80, "affordable": gold >= 1000}}
    if gold < 250:
        tiers["small"]["gold_short_by"] = 250 - gold
    g.city_state_gifts = lambda minor_id, pid=None: {"ok": True, "gold": gold, "friendship": 15, **tiers}
    g.sent = []
    g.h = lambda name, *a, **k: (name, a)
    g.q = lambda call: g.sent.append(call) or {"ok": True, "amount": call[1][1]}
    g._settle = lambda read, changed, initial=None: (initial, False)
    return g


class GiftGoldTests(unittest.TestCase):
    def test_a_wrong_amount_lists_the_tiers(self):
        r = game(2000).minor_gold_gift(37, 60)
        self.assertFalse(r["ok"])
        self.assertIn("small 250, medium 500, large 1000", r["err"])
        self.assertEqual(r["tiers"]["medium"]["amount"], 500)
        self.assertEqual(r["example"]["args"]["args"]["amount"], 250)

    def test_a_short_treasury_says_by_how_much(self):
        r = game(244).minor_gold_gift(37, "small")
        self.assertFalse(r["ok"])
        self.assertEqual(r["gold_short_by"], 6)
        self.assertIn("244 of 250", r["err"])
        self.assertEqual(r["affordable_tiers"], [])

    def test_the_tier_name_is_sent_as_its_amount(self):
        g = game(2000)
        r = g.minor_gold_gift(37, "Large")
        self.assertTrue(r["ok"])
        self.assertEqual(g.sent[0], ("minor_gold_gift", (37, 1000)))


if __name__ == "__main__":
    unittest.main()
