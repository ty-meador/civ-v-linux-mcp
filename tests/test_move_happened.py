"""A move's reply says what the move made happen (GitLab #122) and names a leader met on the way (GitLab #125).

Siam t7 / t12 (Grok): a scout's ruin reward and a warrior's camp gold arrived only on the next finish, stamped the
previous turn; t16: Egypt's first-contact greeting opened under a scout's move, the move said nothing, and the next
status was gated on it.
"""
import unittest

from harness.game import Game


class MoveHappenedTests(unittest.TestCase):
    def _game(self, events, screens=None):
        g = Game.__new__(Game)
        g.seat = 0
        g._pid = lambda pid=None: 0
        g.h = Game.h.__get__(g)
        log = []

        def q(call, timeout=None):
            log.append(call.fn)
            if call.fn == "events_since":
                assert call.args[0] == 40, call.args
                return events
            if call.fn == "attack_before":
                return {"attack": False, "seq": 40}   # the log's head rides on the pre-read (runtime v300)
            return {"ok": True}
        g.q = q
        g._screens = lambda: screens or {}
        g.dismiss_leader_greeting = lambda: log.append("dismissed")
        return g, log

    def test_the_ruin_and_the_camp_are_on_the_move_reply(self):
        g, log = self._game([
            {"seq": 41, "kind": "popup_shown", "audience": 0, "data": {"type": 7, "name": "BUTTONPOPUP_GOODY_HUT_REWARD", "reward": "GOODY_POPULATION"}},
            {"seq": 42, "kind": "popup_shown", "audience": 0, "data": {"type": 9, "name": "BUTTONPOPUP_BARBARIAN_CAMP_REWARD", "gold": 16}},
            {"seq": 43, "kind": "alert", "audience": 0, "data": {"text": "You have discovered an Ancient Ruin: survivors join your city!"}},
            {"seq": 44, "kind": "unit_graphics_reset", "audience": 0, "data": {}},
        ])
        r = g._with_attack_result(7, 3, 4, lambda: {"ok": True, "x": 3, "y": 4, "moves": 1})
        self.assertEqual(r["happened"], [{"kind": "ruins", "reward": "GOODY_POPULATION"}, {"kind": "camp_cleared", "gold": 16},
                                         {"kind": "alert", "text": "You have discovered an Ancient Ruin: survivors join your city!"}])
        self.assertEqual(log.count("events_since"), 1)
        self.assertNotIn("dismissed", log)

    def test_a_leader_met_on_the_way_is_named_and_the_greeting_closed(self):
        g, log = self._game([{"seq": 41, "kind": "leader_message", "audience": 0,
                              "data": {"player": 4, "state": "DIPLO_UI_STATE_DEFAULT_ROOT", "text": "Greetings, I am Ramesses."}}],
                            screens={"leader_greeting_pending": True, "discussion_pending": False})
        r = g._with_attack_result(7, 59, 50, lambda: {"ok": True, "x": 59, "y": 50, "moves": 0})
        self.assertEqual(r["happened"][0]["kind"], "met_leader")
        self.assertEqual(r["happened"][0]["player"], 4)
        self.assertIn("closed for you", r["happened"][0]["screen"])
        self.assertIn("dismissed", log)

    def test_a_real_discussion_is_never_closed(self):
        g, log = self._game([{"seq": 41, "kind": "leader_message", "audience": 0, "data": {"player": 4, "text": "Give me your gold."}}],
                            screens={"leader_greeting_pending": True, "discussion_pending": True})
        r = g._with_attack_result(7, 59, 50, lambda: {"ok": True, "x": 59, "y": 50, "moves": 0})
        self.assertEqual(r["happened"][0]["kind"], "met_leader")
        self.assertNotIn("screen", r["happened"][0])
        self.assertNotIn("dismissed", log)

    def test_a_quiet_move_adds_nothing(self):
        g, _log = self._game([])
        r = g._with_attack_result(7, 3, 4, lambda: {"ok": True, "x": 3, "y": 4, "moves": 1})
        self.assertNotIn("happened", r)
        r = g._with_attack_result(7, 3, 4, lambda: {"ok": False, "err": "no path"})
        self.assertNotIn("happened", r)


if __name__ == "__main__":
    unittest.main()
