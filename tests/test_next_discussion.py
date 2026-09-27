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
