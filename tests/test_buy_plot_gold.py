"""buy_plot's gold_after is the treasury after the purchase (GitLab #129)."""
import unittest
from unittest import mock

from harness.game import Game


class BuyPlotGoldTests(unittest.TestCase):
    def _game(self, golds):
        g = Game.__new__(Game)
        g.seat = 0
        g._pid = lambda pid=None: 0
        g.h = Game.h.__get__(g)
        reads = iter(golds)

        def q(call, timeout=None):
            if call.fn == "buy_city_plot":
                return {"ok": True, "city_id": 8192, "x": 59, "y": 36, "cost": 30, "gold_before": 166}
            if call.fn == "gold_now":
                return next(reads)
            return {"ok": True}
        g.q = q
        g.city_screen = lambda cid, pid=None: {"plots": [{"x": 59, "y": 36, "owned": True}]}
        return g

    def test_the_treasury_is_read_after_the_purchase_landed(self):
        g = self._game([166, 136])
        with mock.patch("harness.game_parts.cities.time.sleep", lambda s: None):
            r = g.buy_city_plot(8192, 59, 36)
        self.assertEqual((r["gold_before"], r["gold_after"], r["cost"]), (166, 136, 30))
        self.assertNotIn("note", r)

    def test_a_purchase_still_pending_says_so(self):
        g = self._game([166] * 6)
        with mock.patch("harness.game_parts.cities.time.sleep", lambda s: None):
            r = g.buy_city_plot(8192, 59, 36)
        self.assertEqual(r["gold_after"], 166)
        self.assertIn("had not moved yet", r["note"])


if __name__ == "__main__":
    unittest.main()
