"""purchase_cost / purchase_production take yield_type as the tool documents it ("GOLD" or "FAITH"), in any
case and with or without the YIELD_ prefix; anything else is a plain refusal, not a KeyError."""
import unittest

from harness.game import Game


class YieldTypeTests(unittest.TestCase):
    def game(self):
        g = Game.__new__(Game)
        g.seat = 0
        g.queries = []
        g.q = lambda code, **kw: g.queries.append(code) or {"ok": True, "cost": 1}
        return g

    def test_case_and_prefix_are_forgiven(self):
        g = self.game()
        for yt in ("gold", "Faith", "YIELD_FAITH", None):
            self.assertTrue(g.purchase_cost(1, "ORDER_TRAIN", "UNIT_WARRIOR", yt)["ok"], yt)
        self.assertIn("YIELD_FAITH", g.queries[1])
        self.assertIn("YIELD_GOLD", g.queries[3])

    def test_anything_else_is_refused_before_any_query(self):
        g = self.game()
        with self.assertRaises(ValueError) as cm:
            g.purchase_cost(1, "ORDER_TRAIN", "UNIT_WARRIOR", "beakers")
        self.assertIn("GOLD", str(cm.exception))
        self.assertEqual(g.queries, [])
