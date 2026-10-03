"""purchase_production while the city runs a process: the city keeps converting production, it never
"completes", and the engine answers 2^31-1 turns. Live t179 (Venice): a Bank bought under the Research process
read `city_now_building_turns: 2147483647`; set_production already nulls that number with a note.
"""
import unittest
from unittest import mock

from harness.game import Game


class ScriptedGame(Game):
    def __init__(self, after):
        self.seat = 0
        self.answers = [{"ok": True, "id": 7}, {"ok": True}, after]
        self.asked = []

    def q(self, code, *a, **k):
        self.asked.append(code)
        return self.answers.pop(0)


class PurchaseUnderAProcess(unittest.TestCase):
    def buy(self, after):
        g = ScriptedGame(after)
        with mock.patch("time.sleep"):
            return g.purchase_production(8192, "ORDER_CONSTRUCT", "BUILDING_BANK")

    def test_a_process_has_no_turns_and_says_so(self):
        r = self.buy({"ok": True, "production": "Research", "turns": 2147483647, "balance": 3093})
        self.assertEqual((r["bought"], r["city_now_building"], r["city_now_building_turns"]),
                         ("BUILDING_BANK", "Research", None))
        self.assertIn("never completes", r["note"])
        self.assertEqual(r["balance"], 3093)

    def test_a_real_build_keeps_its_turns(self):
        r = self.buy({"ok": True, "production": "Opera House", "turns": 4, "balance": 10})
        self.assertEqual((r["city_now_building"], r["city_now_building_turns"]), ("Opera House", 4))
        self.assertNotIn("note", r)

    def test_an_emptied_queue_still_warns(self):
        r = self.buy({"ok": True, "production": "", "turns": 2147483647, "balance": 10})
        self.assertIsNone(r["city_now_building"])
        self.assertIn("queue is now empty", r["note"])


if __name__ == "__main__":
    unittest.main()
