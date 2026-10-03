"""turn_digest keeps the newest DIGEST_MAX_EVENTS events and says what it cut (live t192: 350 rows / 75 KB)."""
import unittest

from harness.game import Game
from harness.game_parts.events import DIGEST_MAX_EVENTS


def game_with_events(events):
    g = Game.__new__(Game)
    g.seat = 0
    g._pid = lambda pid=None: 0
    g.q = lambda body, timeout=None: list(events) if "take_events" in body else []
    return g


class DigestCapTests(unittest.TestCase):
    def test_under_the_cap_nothing_is_cut(self):
        ev = [{"kind": "notification", "turn": 10, "seq": i, "audience": 0, "data": {"text": f"n{i}"}} for i in range(5)]
        out = game_with_events(ev).turn_digest()
        self.assertEqual(len(out["events"]), 5)
        self.assertNotIn("omitted", out)

    def test_over_the_cap_keeps_the_newest_and_counts_the_rest(self):
        n = DIGEST_MAX_EVENTS + 30
        ev = [{"kind": "notification" if i % 2 else "turn_start", "turn": 163 + i // 12, "seq": i + 1, "audience": 0,
               "data": {"text": f"n{i}"}} for i in range(n)]
        out = game_with_events(ev).turn_digest()
        self.assertEqual(len(out["events"]), DIGEST_MAX_EVENTS)
        self.assertEqual(out["events"][-1]["seq"], n, "the newest rows are the ones kept")
        om = out["omitted"]
        self.assertEqual(om["count"], 30)
        self.assertEqual(om["turns"], [163, 163 + 29 // 12])
        self.assertEqual(sum(om["by_kind"].values()), 30)
        self.assertIn("notification_log", om["hint"])


if __name__ == "__main__":
    unittest.main()
