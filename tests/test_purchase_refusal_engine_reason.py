"""A refused purchase_production carries the engine's own sentence, as purchase_cost already does.

Live t182 (Venice): a Caravan bought the moment the last land destination was taken answered only
"this city cannot train or build it, so there is no buy button" -- while purchase_cost, asked right after,
had `engine_reason: "You cannot construct this trade unit because there are no available land trade
routes."` The refusal copied reason / cost / balance / blocking_units from purchase_cost and dropped the one
field that named the rule.
"""
import unittest
from unittest import mock

from harness.game import Game


class RefusingGame(Game):
    def __init__(self):
        self.seat = 0

    def q(self, code, *a, **k):
        return {"ok": False, "err": "cannot purchase this right now (not enough currency, already queued, or not purchasable this way)"}


class PurchaseRefusalEngineReason(unittest.TestCase):
    def refuse(self, why):
        g = RefusingGame()
        with mock.patch.object(Game, "purchase_cost", return_value=why):
            return g.purchase_production(8192, "ORDER_TRAIN", "UNIT_CARAVAN")

    def test_the_engines_sentence_rides_on_the_refusal(self):
        r = self.refuse({"ok": True, "cost": 210, "balance": 3625, "can_purchase": False,
                         "reason": "this city cannot train or build it, so there is no buy button (compare(kind='production') names the rule)",
                         "engine_reason": "You cannot construct this trade unit because there are no available land trade routes."})
        self.assertFalse(r["ok"])
        self.assertEqual(r["engine_reason"], "You cannot construct this trade unit because there are no available land trade routes.")
        self.assertEqual((r["cost"], r["balance"]), (210, 3625))
        self.assertIn("cannot train or build it", r["reason"])

    def test_no_sentence_means_no_field(self):
        r = self.refuse({"ok": True, "cost": 210, "balance": 100, "can_purchase": False,
                         "reason": "not enough gold (100 of 210)"})
        self.assertFalse(r["ok"])
        self.assertNotIn("engine_reason", r)
        self.assertEqual(r["reason"], "not enough gold (100 of 210)")


if __name__ == "__main__":
    unittest.main()
