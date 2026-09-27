"""Game._settle: the one poll-until-it-changed loop behind every tool that reads back an asynchronous order
(minor_gold_gift, accept_deal, _with_target_result, _confirm_policy, choose_ideology, establish_trade_route,
stage_coup). Each used to carry its own copy of the loop."""
import unittest
from unittest.mock import patch

from harness.game import Game


class SettleTests(unittest.TestCase):
    def setUp(self):
        self.g = Game.__new__(Game)

    def test_returns_the_first_reading_that_satisfies_done(self):
        readings = iter([1, 2, 3])
        with patch("harness.game.time.sleep") as sleep, \
                patch("harness.game.time.monotonic", side_effect=[0, 0.1, 0.2, 0.3]):
            value, settled = self.g._settle(lambda: next(readings), lambda v: v == 2)
        self.assertEqual((value, settled), (2, True))
        self.assertEqual(sleep.call_count, 2, "one sleep before every read: a read at t=0 shows the pre-order state")

    def test_reports_the_last_reading_unsettled_after_the_timeout(self):
        readings = iter([1, 1])
        with patch("harness.game.time.sleep"), patch("harness.game.time.monotonic", side_effect=[0, 0.1, 0.2, 5.0]):
            value, settled = self.g._settle(lambda: next(readings), lambda v: v == 2, timeout=3.0)
        self.assertEqual((value, settled), (1, False), "the last reading is reported as-is, never guessed at")

    def test_initial_stands_in_when_no_reading_happened(self):
        with patch("harness.game.time.monotonic", side_effect=[0, 10.0]):
            value, settled = self.g._settle(lambda: self.fail("no read"), lambda v: True, timeout=3.0, initial="before")
        self.assertEqual((value, settled), ("before", False))
