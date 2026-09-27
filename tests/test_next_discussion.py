"""accept_deal / refuse_deal / dismiss_discussion hand over the next queued leader (harness/mcp_tools/diplomacy.py
_with_next), as respond_discussion already did: at a turn start several AIs can be waiting in a row (live
t136: China, Portugal, Russia), and the caller's next order would otherwise be refused with a gate it had
no way to expect."""
import json
import unittest
from unittest import mock

from harness import mcp_server as m
from harness.mcp_tools.diplomacy import _with_next


class FakeGame:
    seat = 1

    def __init__(self, queued):
        self.queued = list(queued)

    def discussion_pending(self):
        return bool(self.queued)

    def discussion(self):
        return self.queued[0]

    def incoming_deal(self):
        return {"ok": True, "items": [{"type": "OPEN_BORDERS", "from_us": True}]}

    def accept_deal(self):
        self.queued.pop(0)
        return {"ok": True, "via": "DiploTrade.OnPropose", "accepted_items": []}


class WithNextTests(unittest.TestCase):
    def test_a_queued_trade_offer_rides_along_with_its_gate(self):
        g = FakeGame([{"screen": "trade"}, {"screen": "trade", "player": 7, "leader": "Catherine",
                                             "speech": "Shall we renew?", "buttons": [], "how_to_answer": "accept_deal"}])
        out = _with_next(g, g.accept_deal())
        self.assertTrue(out["still_pending"])
        self.assertEqual(out["next"]["player"], 7)
        self.assertEqual(out["next"]["deal"][0]["type"], "OPEN_BORDERS")
        self.assertEqual((out["gate"]["name"], out["gate"]["clear_with"]), ("discussion", "accept_deal"))

    def test_a_queued_discussion_names_respond_discussion(self):
        g = FakeGame([{"screen": "trade"}, {"screen": "discussion", "player": 3, "buttons": [{"id": 1, "text": "Fine"}]}])
        out = _with_next(g, g.accept_deal())
        self.assertEqual(out["gate"]["clear_with"], "respond_discussion")
        self.assertNotIn("deal", out["next"])

    def test_nothing_queued_leaves_the_reply_alone(self):
        g = FakeGame([{"screen": "trade"}])
        out = _with_next(g, g.accept_deal())
        self.assertNotIn("still_pending", out)
        self.assertNotIn("gate", out)

    def test_a_refusal_is_left_alone_and_a_read_error_is_swallowed(self):
        g = FakeGame([{"screen": "trade"}, {"screen": "trade"}])
        self.assertEqual(_with_next(g, {"ok": False, "err": "x"}), {"ok": False, "err": "x"})
        g.discussion = lambda: (_ for _ in ()).throw(RuntimeError("no screen"))
        out = _with_next(g, g.accept_deal())
        self.assertTrue(out["ok"])
        self.assertNotIn("gate", out)

    def test_the_tools_go_through_it(self):
        g = FakeGame([{"screen": "trade"}, {"screen": "trade", "player": 5, "buttons": []}])
        with mock.patch.object(m, "game", return_value=g):
            r = json.loads(m.accept_deal.__wrapped__())
        self.assertTrue(r["still_pending"])
        self.assertEqual(r["next"]["player"], 5)


class GreetingQueueTests(unittest.TestCase):
    """Live t145 (Venice): three first-meeting greetings queued at one turn start; one Back per call answered
    ok=false with the next greeting up. dismiss_discussion clicks through them, stopping at a real question."""

    class FakeGame(__import__("harness.game", fromlist=["Game"]).Game):
        def __init__(self, greetings, then_discussion=False):
            self.greetings = greetings
            self.then_discussion = then_discussion
            self.clicks = 0

        def discussion_pending(self):
            return self.then_discussion and self.greetings == 0

        def leader_greeting_pending(self):
            return self.greetings > 0

        def dismiss_leader_greeting(self):
            self.clicks += 1
            self.greetings -= 1

    def test_three_greetings_close_in_one_call(self):
        g = self.FakeGame(3)
        with mock.patch("time.sleep"):
            r = g.dismiss_discussion()
        self.assertEqual((r["ok"], r["closed"], r["closed_count"], g.clicks), (True, "greeting", 3, 3))

    def test_a_real_question_behind_them_stops_the_clicking(self):
        # a trade table or buttons after the greetings: stop there, ok (the caller gets it as `next`)
        g = self.FakeGame(2, then_discussion=True)
        with mock.patch("time.sleep"):
            r = type(g).__mro__[1].dismiss_discussion(g)
        self.assertTrue(r["ok"])
        self.assertEqual(g.clicks, 2)

    def test_the_bound_holds(self):
        g = self.FakeGame(20)
        with mock.patch("time.sleep"):
            r = type(g).__mro__[1].dismiss_discussion(g)
        self.assertFalse(r["ok"])
        self.assertEqual(g.clicks, type(g)._GREETING_CLICKS)
