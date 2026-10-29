"""A write's arrival block does not warn about the city-state the write just addressed (GitLab #64)."""
import json
import unittest

from harness import mcp_server as m


class ArrivalTargetRowsTests(unittest.TestCase):
    ARRIVAL = {"expiring_city_states": [{"player_id": 33, "civ": "Colombo", "influence": 60, "turns_left": 1},
                                        {"player_id": 35, "civ": "Yerevan", "influence": 61, "turns_left": 2}]}

    def test_the_orders_own_target_is_dropped_with_a_note(self):
        out = json.loads(m._with_arrival(json.dumps({"ok": True, "friendship": 80}), self.ARRIVAL, 33))
        rows = out["arrival"]["expiring_city_states"]
        self.assertEqual([r["player_id"] for r in rows], [35])
        self.assertIn("city-state 33", out["arrival"]["expiring_city_states_note"])
        self.assertEqual(self.ARRIVAL["expiring_city_states"][0]["player_id"], 33, "the arrival dict itself is untouched")

    def test_the_only_row_gone_leaves_the_note(self):
        arrival = {"expiring_city_states": [self.ARRIVAL["expiring_city_states"][0]]}
        out = json.loads(m._with_arrival(json.dumps({"ok": True}), arrival, 33))
        self.assertNotIn("expiring_city_states", out["arrival"])
        self.assertIn("expiring_city_states_note", out["arrival"])

    def test_no_target_or_another_target_keeps_every_row(self):
        out = json.loads(m._with_arrival(json.dumps({"ok": True}), self.ARRIVAL, None))
        self.assertEqual(len(out["arrival"]["expiring_city_states"]), 2)
        out = json.loads(m._with_arrival(json.dumps({"ok": True}), self.ARRIVAL, 7))
        self.assertEqual(len(out["arrival"]["expiring_city_states"]), 2)
        self.assertEqual(m._city_state_target({"minor_id": 33, "amount": 250}), 33)
        self.assertEqual(m._city_state_target({"player_id": 3, "items": []}), 3)
        self.assertIsNone(m._city_state_target({"unit_id": 33, "x": 1}))
        self.assertIsNone(m._city_state_target({"minor_id": True}))


if __name__ == "__main__":
    unittest.main()
