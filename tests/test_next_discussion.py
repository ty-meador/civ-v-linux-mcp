"""accept_deal / refuse_deal / dismiss_discussion hand over the next queued leader (harness/mcp_tools/diplomacy.py
_with_next), as respond_discussion already did: at a turn start several AIs can be waiting in a row (live
t136: China, Portugal, Russia), and the caller's next order would otherwise be refused with a gate it had
no way to expect."""
import json
import unittest
from unittest import mock

from harness import mcp_server as m
from harness.game_parts.diplomacy import DiplomacyMixin
from harness.mcp_tools.diplomacy import _with_next


class FakeGame:
    seat = 1
    queued_next = DiplomacyMixin.queued_next   # the real hand-over read, over this fake's screens
    _TRADE_TABLE_WAIT = (3, 0)

    def __init__(self, queued, tables=None):
        self.queued = list(queued)
        self.tables = list(tables) if tables is not None else None   # incoming_deal answers in order, last one repeats
        self.arrivals = 0

    def discussion_pending(self):
        return bool(self.queued)

    def discussion(self):
        return self.queued[0]

    def incoming_deal(self):
        if self.tables:
            return self.tables.pop(0) if len(self.tables) > 1 else self.tables[0]
        return {"ok": True, "items": [{"type": "OPEN_BORDERS", "from_us": True}]}

    def arrive_if_due(self):
        self.arrivals += 1
        return None

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

    def test_a_queued_trade_screen_is_read_once_its_table_has_filled(self):
        # live t228 (Venice): Babylon's research agreement behind England's war screen read as a trade screen with
        # no leader and no items -- the AI's table lands a beat after its screen opens -- and was dismissed unseen.
        empty = {"screen": "trade", "player": None, "leader": None, "buttons": [], "how_to_answer": "accept_deal"}
        filled = {"screen": "trade", "player": 4, "leader": "Nebuchadnezzar II", "buttons": [], "how_to_answer": "accept_deal"}
        g = FakeGame([{"screen": "trade"}, empty],
                     tables=[{"ok": True, "items": []}, {"ok": True, "items": []},
                             {"ok": True, "items": [{"type": "RESEARCH_AGREEMENT", "from_us": False}]}])
        reads = {"n": 0}
        real = g.discussion

        def discussion():
            reads["n"] += 1
            if reads["n"] >= 3:      # the third look sees the leader
                g.queued[0] = filled
            return real()
        g.discussion = discussion
        with mock.patch("time.sleep"):
            out = _with_next(g, g.accept_deal())
        self.assertTrue(out["still_pending"])
        self.assertEqual(out["next"]["leader"], "Nebuchadnezzar II")
        self.assertEqual(out["next"]["deal"][0]["type"], "RESEARCH_AGREEMENT")
        self.assertNotIn("note", out["next"])

    def test_a_trade_table_that_never_fills_is_reported_as_such(self):
        g = FakeGame([{"screen": "trade"}, {"screen": "trade", "player": None, "leader": None, "buttons": []}],
                     tables=[{"ok": True, "items": []}])
        with mock.patch("time.sleep"):
            out = _with_next(g, g.accept_deal())
        self.assertEqual(out["next"]["deal"], [])
        self.assertIn("still empty", out["next"]["note"])

    def test_a_free_table_runs_the_turns_arrival_once(self):
        # live t225 (Mongolia): the turn opened under China's renewal, wait_for_my_turn returned at that gate before
        # the arrival hook, and the Great Musician's order sat out the turn. Answering the leader now runs it.
        g = FakeGame([{"screen": "trade"}])
        g.arrive_if_due = lambda: {"orders": {"open": 1, "rows": [{"id": 20, "did": ["move to (46,20): issued"]}]}}
        out = _with_next(g, g.accept_deal())
        self.assertEqual(out["orders"]["rows"][0]["id"], 20)
        self.assertNotIn("still_pending", out)

    def test_nothing_due_adds_nothing(self):
        g = FakeGame([{"screen": "trade"}])
        out = _with_next(g, g.accept_deal())
        self.assertEqual(g.arrivals, 1)
        self.assertNotIn("orders", out)


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


class BlankRemarkQueueTests(unittest.TestCase):
    """Live t174 (Mongolia): England's "glad you are friends with Russia" remark (no buttons) was closed with
    dismiss_discussion, which answered a bare ok while Portugal's identical remark came up a beat later: the
    hand-over `next` was empty and the next briefing() was refused with a discussion gate. The Back now waits
    for the dialog to close and for anything that comes straight back up."""

    class FakeGame(__import__("harness.game", fromlist=["Game"]).Game):
        def __init__(self, pending_sequence):
            self.pending_sequence = list(pending_sequence)
            self.polls = 0
            self.backs = []
            self.c = self

        def wait_state(self, name, timeout):
            return 7

        def exec(self, state, code, check=False):
            self.backs.append((state, code))
            return []

        def leader_greeting_pending(self):
            return False

        def discussion(self):
            return {"screen": "discussion", "player": 5, "leader": "Maria I", "speech": "Glad to hear of it.",
                    "buttons": [], "how_to_answer": "dismiss_discussion()"}

        def discussion_pending(self):
            self.polls += 1
            return self.pending_sequence.pop(0) if len(self.pending_sequence) > 1 else self.pending_sequence[0]

    def test_the_leader_behind_a_blank_remark_is_waited_for(self):
        # pending now (the gate check), closed, closed, then Portugal is up
        g = self.FakeGame([True, False, False, True])
        with mock.patch("time.sleep"):
            r = g.dismiss_discussion()
        self.assertEqual((r["ok"], g.backs), (True, [(7, "OnBack(true)")]))
        self.assertEqual(g.polls, 4, "stops as soon as the next leader is up")
        out = _with_next(g, r)
        self.assertTrue(out["still_pending"], "the wrapper now sees the queued leader")

    def test_nothing_behind_it_costs_the_bounded_wait_only(self):
        g = self.FakeGame([True, False])
        with mock.patch("time.sleep"):
            r = g.dismiss_discussion()
        self.assertTrue(r["ok"])
        self.assertEqual(g.polls, 1 + type(g)._NEXT_LEADER_POLLS)

    def test_a_dialog_that_never_closes_is_not_mistaken_for_the_next_one(self):
        g = self.FakeGame([True, True])
        with mock.patch("time.sleep"):
            r = g.dismiss_discussion()
        self.assertTrue(r["ok"])
        self.assertEqual(g.polls, 1 + type(g)._NEXT_LEADER_POLLS, "no early break on the screen still closing")
