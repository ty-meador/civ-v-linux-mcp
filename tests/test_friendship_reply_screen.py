"""propose_friendship waits for the leader's reply screen before closing it.

The AI answers our Declaration of Friendship ask on a leader screen that stays up until Back is clicked;
_friendship_result closed it when it was there half a second after the ask. Live t182 (Mongolia): Babylon's
"That will work. May a strong friendship lead to the flourishing of our empires." came up a beat later, so the
call returned accepted=true with no screen_closed, `reply` was Babylon's t171 line, and the following
finish_turn was refused with a discussion gate. The result now polls for the screen (as dismiss_discussion
polls for a queued leader), reads the reply once it is up and closes it.
"""
import unittest
from unittest import mock

from harness.game import Game


class ScriptedGame(Game):
    def __init__(self, pending, histories):
        self.seat = 1
        self.pending = list(pending)
        self.histories = list(histories)
        self.dismissed = 0

    def q(self, code, *a, **k):
        return {"dof": True}

    def discussion_pending(self):
        return self.pending.pop(0) if self.pending else False

    def relationship(self, other, pid=None):
        return {"history": self.histories.pop(0) if self.histories else []}

    def dismiss_discussion(self):
        self.dismissed += 1
        return {"ok": True}


T171 = [{"turn": 171, "text": "That deal will work."}]
T182 = T171 + [{"turn": 182, "text": "That will work. May a strong friendship lead to the flourishing of our empires."}]


class FriendshipReplyScreen(unittest.TestCase):
    def result(self, pending, histories):
        g = ScriptedGame(pending, histories)
        with mock.patch("time.sleep"):
            return g._friendship_result(4, 1, None), g

    def test_a_screen_that_comes_up_a_beat_later_is_still_closed(self):
        out, g = self.result([False, False, True], [T182])
        self.assertTrue(out["accepted"])
        self.assertTrue(out["screen_closed"])
        self.assertEqual(g.dismissed, 1)
        self.assertEqual(out["reply"], T182[-1]["text"])

    def test_no_screen_within_the_wait_closes_nothing(self):
        out, g = self.result([False] * 10, [T171])
        self.assertTrue(out["accepted"])
        self.assertNotIn("screen_closed", out)
        self.assertEqual(g.dismissed, 0)
        self.assertEqual(out["reply"], "That deal will work.")

    def test_the_wait_is_bounded(self):
        g = ScriptedGame([False] * 50, [T171])
        with mock.patch("time.sleep") as slept:
            g._friendship_result(4, 1, None)
        self.assertLessEqual(slept.call_count, Game._NEXT_LEADER_POLLS)


if __name__ == "__main__":
    unittest.main()
