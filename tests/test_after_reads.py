"""The read-back after a unit order: one trip on its own, one trip for a whole batch.

Every mission is a net message applied on the next game frame, so a tool reads the unit back instead of
trusting the send. On its own that read is one tuner trip after the push (live t151: MISSION_SKIP and
AUTOMATE_BUILD each showed on the first read, 43-60 ms after the push, six pushes). Inside a `do` batch the
orders used to pay that trip each; now they answer an `after_pending` marker and the batch reads every unit
in one query at its end, then folds each reading into its order's result.
"""
import os
import unittest
from unittest import mock

import anyio

from harness import mcp_server as m
from harness.game import Game
from harness.game_parts import units as units_mod
from tests.test_do_batch import session


def _game(answers):
    """A Game whose q() answers from `answers` (substring of the query -> reply), recording every query."""
    g = Game.__new__(Game)
    g.seat = 0
    g.queries = []

    def q(body):
        g.queries.append(body)
        for key, reply in answers:
            if key in body:
                return reply(body) if callable(reply) else reply
        raise AssertionError("unexpected query: " + body)

    g.q = q
    g._order = lambda body: g.q(body)
    return g


class LoneOrderTests(unittest.TestCase):
    def setUp(self):
        units_mod.defer_after_reads(False)
        self.sleep = mock.patch("harness.game_parts.units.time.sleep")
        self.sleep.start()

    def tearDown(self):
        self.sleep.stop()

    def test_a_plain_mission_reads_the_unit_back_once(self):
        g = _game([("H.unit_mission", {"ok": True}),
                   ("H.unit_pos", {"ok": True, "x": 4, "y": 5, "moves": 0, "activity": 1, "activity_name": "HOLD"})])
        r = g.unit_mission(7, "MISSION_SKIP")
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["x"], r["y"], r["activity_name"]), (4, 5, "HOLD"))
        self.assertNotIn("after_pending", r)
        self.assertEqual(sum("H.unit_pos" in q for q in g.queries), 1)

    def test_an_automate_order_is_confirmed_by_its_first_read(self):
        g = _game([("H.unit_mission", {"ok": True, "automate_pending": 0}),
                   ("H.automate_check", {"ok": True, "automated": True, "x": 4, "y": 5, "moves": 0})])
        r = g.unit_mission(7, "AUTOMATE_BUILD")
        self.assertEqual(r, {"ok": True, "automated": True, "x": 4, "y": 5, "moves": 0})
        self.assertEqual(sum("H.automate_check" in q for q in g.queries), 1, "no fixed wait, no second read")

    def test_an_automate_order_keeps_polling_until_it_lands(self):
        reads = iter([{"ok": True, "automated": False}, {"ok": True, "automated": False},
                      {"ok": True, "automated": True, "x": 1, "y": 1, "moves": 2}])
        g = _game([("H.unit_mission", {"ok": True, "automate_pending": 0}),
                   ("H.automate_check", lambda body: next(reads))])
        r = g.unit_mission(7, "AUTOMATE_EXPLORE")
        self.assertTrue(r["ok"] and r["automated"], r)
        self.assertEqual(sum("H.automate_check" in q for q in g.queries), 3)

    def test_an_automate_order_that_never_lands_is_a_refusal(self):
        g = _game([("H.unit_mission", {"ok": True, "automate_pending": 0}),
                   ("H.automate_check", {"ok": True, "automated": False})])
        with mock.patch("harness.game.time.monotonic", side_effect=[0, 0, 0, 10, 10, 10, 10]):
            r = g.unit_mission(7, "AUTOMATE_BUILD")
        self.assertFalse(r["ok"])
        self.assertIn("not automated after 3 s", r["err"])


class DeferredReadTests(unittest.TestCase):
    def setUp(self):
        units_mod.defer_after_reads(True)
        self.sleep = mock.patch("harness.game_parts.units.time.sleep")
        self.sleep.start()

    def tearDown(self):
        units_mod.defer_after_reads(False)
        self.sleep.stop()

    def test_a_deferred_order_answers_a_marker_and_reads_nothing_back(self):
        g = _game([("H.unit_mission", {"ok": True})])
        r = g.unit_mission(7, "MISSION_FORTIFY")
        self.assertEqual(r, {"ok": True, "after_pending": {"unit_id": 7, "mission": "MISSION_FORTIFY", "kind": "pos"}})
        g2 = _game([("H.unit_mission", {"ok": True, "automate_pending": 0})])
        r2 = g2.unit_mission(9, "AUTOMATE_BUILD")
        self.assertEqual(r2["after_pending"], {"unit_id": 9, "mission": "AUTOMATE_BUILD", "kind": "automate"})
        self.assertFalse(any("H.unit_pos" in q or "H.automate_check" in q for q in g.queries + g2.queries))

    def test_a_refusal_carries_no_marker(self):
        g = _game([("H.unit_mission", {"ok": False, "err": "action is not currently legal"}),
                   ("available_unit_actions", {"ok": True, "actions": []}), ("H.units", {"units": []})])
        g.available_unit_actions = lambda uid, pid=None: {"actions": []}
        g._unit_rows = lambda pid=None: []
        r = g.unit_mission(7, "MISSION_FORTIFY")
        self.assertFalse(r["ok"])
        self.assertNotIn("after_pending", r)

    def test_read_after_batch_is_one_query_in_marker_order(self):
        g = _game([("return {", [{"ok": True, "x": 1, "y": 2, "moves": 0, "activity_name": "HOLD"},
                                 {"ok": True, "automated": True, "x": 3, "y": 4, "moves": 1},
                                 {"ok": False, "err": "no such unit"}])])
        markers = [{"unit_id": 7, "mission": "MISSION_SKIP", "kind": "pos"},
                   {"unit_id": 9, "mission": "AUTOMATE_BUILD", "kind": "automate"},
                   {"unit_id": 11, "mission": "MISSION_BUILD_ACADEMY", "kind": "pos"}]
        rows = g.read_after_batch(markers)
        self.assertEqual(len(g.queries), 1)
        self.assertEqual(g.queries[0], "return {H.unit_pos(7, 0), H.automate_check(9, 0), H.unit_pos(11, 0)}")
        a = g.apply_after({"ok": True, "after_pending": markers[0]}, markers[0], rows[0])
        self.assertEqual(a, {"ok": True, "x": 1, "y": 2, "moves": 0, "activity_name": "HOLD"})
        b = g.apply_after({"ok": True, "after_pending": markers[1]}, markers[1], rows[1])
        self.assertEqual(b, {"ok": True, "automated": True, "x": 3, "y": 4, "moves": 1})
        c = g.apply_after({"ok": True, "consumed_note": 1, "after_pending": markers[2]}, markers[2], rows[2])
        self.assertEqual(c, {"ok": True, "consumed_note": 1, "consumed": True}, "a unit gone after its mission was consumed")

    def test_a_dropped_route_is_still_a_refusal_when_read_late(self):
        g = _game([])
        marker = {"unit_id": 7, "mission": "MISSION_ROUTE_TO", "kind": "pos"}
        r = g.apply_after({"ok": True, "after_pending": marker}, marker,
                          {"ok": True, "x": 1, "y": 1, "moves": 2, "activity_name": "AWAKE", "buildtype": -1})
        self.assertFalse(r["ok"])
        self.assertIn("dropped the route", r["err"])

    def test_an_automate_not_landed_by_the_batch_read_is_re_read_alone(self):
        reads = iter([{"ok": True, "automated": False}, {"ok": True, "automated": True, "x": 3, "y": 4, "moves": 0}])
        g = _game([("return {", [{"ok": True, "x": 1, "y": 2, "moves": 0}, {"ok": True, "automated": False}]),
                   ("H.automate_check(9, 0)", lambda body: next(reads))])
        rows = g.read_after_batch([{"unit_id": 7, "mission": "MISSION_SKIP", "kind": "pos"},
                                   {"unit_id": 9, "mission": "AUTOMATE_BUILD", "kind": "automate"}])
        self.assertTrue(rows[1]["automated"])
        self.assertEqual(len(g.queries), 3, "the batch read, then the one automate re-read twice")

    def test_a_short_or_missing_batch_reading_never_crashes(self):
        g = _game([("return {", None)])
        markers = [{"unit_id": 7, "mission": "MISSION_SKIP", "kind": "pos"}]
        rows = g.read_after_batch(markers)
        r = g.apply_after({"ok": True, "after_pending": markers[0]}, markers[0], rows[0])
        self.assertEqual(r, {"ok": True, "consumed": True})
        self.assertEqual(g.read_after_batch([]), [])


class BatchGame:
    """A Game whose unit orders behave like the real ones under `do`: a marker while deferring, a read-back
    otherwise. Records every 'trip'."""
    seat = 0

    def __init__(self):
        self.calls, self.trips = [], []

    def has_state(self, name):
        return True

    def turn_state(self, pid=None):
        return {"turn": 7, "active_player": 0, "my_turn": True, "processing": False, "paused": False,
                "blocking_name": "NO_ENDTURN_BLOCKING_TYPE", "todo": {}, "pending_popups": []}

    def discussion_pending(self):
        return False

    def unit_mission(self, unit_id, mission, x=-1, y=-1, build=None):
        self.calls.append(("unit_mission", unit_id, mission))
        self.trips.append("push")
        if unit_id == 13:
            return {"ok": False, "err": "no such unit"}
        kind = "automate" if mission.startswith("AUTOMATE_") else "pos"
        if units_mod.deferring_after_reads():
            return {"ok": True, "after_pending": {"unit_id": unit_id, "mission": mission, "kind": kind}}
        self.trips.append("read")
        return {"ok": True, "x": 1, "y": 1}

    def set_production(self, city_id, order, item, append=False):
        self.calls.append(("set_production", city_id, item))
        return {"ok": True}

    read_after_batch = Game.read_after_batch
    apply_after = Game.apply_after
    _apply_unit_after = Game._apply_unit_after
    _apply_automate_after = staticmethod(Game._apply_automate_after)
    _settle = Game._settle

    def _pid(self, pid=None):
        return 0

    def q(self, body):
        self.trips.append("batch-read:" + body)
        return [{"ok": True, "x": 5, "y": 6, "moves": 0, "activity_name": "HOLD"},
                {"ok": True, "automated": True, "x": 7, "y": 8, "moves": 0}]


class DoBatchReadsOnceTests(unittest.TestCase):
    def setUp(self):
        self.fake = BatchGame()
        self.patches = [mock.patch.object(m, "game", lambda: self.fake),
                        mock.patch.dict(os.environ, {"CIV5_TUNERD_SOCK": "/tmp/civ5-test-after.sock"}),
                        mock.patch.dict(m._RECENT, {}, clear=True),
                        mock.patch("harness.game_parts.units.time.sleep")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        units_mod.defer_after_reads(False)

    def test_a_batch_reads_its_units_back_in_one_trip_and_each_result_is_complete(self):
        (out,) = anyio.run(session, [("do", {"actions": [
            {"tool": "unit_mission", "args": {"unit_id": 7, "mission": "MISSION_FORTIFY"}, "action_id": "f7"},
            {"tool": "set_production", "args": {"city_id": 1, "item": "UNIT_ARCHER"}},
            {"tool": "unit_mission", "args": {"unit_id": 9, "mission": "AUTOMATE_BUILD"}},
        ]})])
        self.assertTrue(out["ok"], out)
        r7, r9 = out["results"][0]["result"], out["results"][2]["result"]
        self.assertEqual(r7, {"ok": True, "x": 5, "y": 6, "moves": 0, "activity_name": "HOLD"})
        self.assertEqual(r9, {"ok": True, "automated": True, "x": 7, "y": 8, "moves": 0})
        self.assertEqual(self.fake.trips, ["push", "push", "batch-read:return {H.unit_pos(7, 0), H.automate_check(9, 0)}"])
        self.assertFalse(units_mod.deferring_after_reads(), "the switch is off again after the batch")
        # The remembered result is the complete one: a replay never shows the marker.
        (again,) = anyio.run(session, [("do", {"actions": [
            {"tool": "unit_mission", "args": {"unit_id": 7, "mission": "MISSION_FORTIFY"}, "action_id": "f7"}]})])
        self.assertTrue(again["results"][0]["result"]["replayed"])
        self.assertEqual(again["results"][0]["result"]["x"], 5)
        self.assertNotIn("after_pending", again["results"][0]["result"])

    def test_a_lone_order_outside_a_batch_still_reads_itself_back(self):
        (r,) = anyio.run(session, [("unit_mission", {"unit_id": 7, "mission": "MISSION_FORTIFY"})])
        self.assertEqual(self.fake.trips, ["push", "read"])
        self.assertNotIn("after_pending", r)

    def test_a_refusal_mid_batch_still_reads_back_the_orders_that_went_out(self):
        (out,) = anyio.run(session, [("do", {"actions": [
            {"tool": "unit_mission", "args": {"unit_id": 7, "mission": "MISSION_FORTIFY"}},
            {"tool": "unit_mission", "args": {"unit_id": 13, "mission": "MISSION_SKIP"}},
            {"tool": "unit_mission", "args": {"unit_id": 9, "mission": "AUTOMATE_BUILD"}},
        ]})])
        self.assertFalse(out["ok"])
        self.assertEqual(out["results"][0]["result"]["x"], 5)
        self.assertEqual(out["skipped"], [{"index": 2, "tool": "unit_mission"}])
        self.assertEqual(sum(t.startswith("batch-read") for t in self.fake.trips), 1)

    def test_a_failed_batch_read_leaves_every_order_answered_without_the_marker(self):
        def boom(body):
            raise OSError("tuner gone")
        self.fake.q = boom
        (out,) = anyio.run(session, [("do", {"actions": [
            {"tool": "unit_mission", "args": {"unit_id": 7, "mission": "MISSION_FORTIFY"}}]})])
        r = out["results"][0]["result"]
        self.assertNotIn("after_pending", r)
        self.assertTrue(r["ok"], "the order went out; only its read-back failed")
        self.assertNotIn("consumed", r, "a reading that never happened must not pass for a unit that is gone")
        self.assertIn("not read back", r["note"])
        self.assertIn("units()", r["note"])


if __name__ == "__main__":
    unittest.main()


class GateReadsTheStatusTests(unittest.TestCase):
    """The gate's discussion check was a second tuner trip on every mutating call; turn_state carries the flag."""

    def _fake(self, flag):
        fake = BatchGame()
        ts = fake.turn_state()
        if flag is not None:
            ts["discussion_pending"] = flag
        fake.turn_state = lambda pid=None: ts

        def asked():
            fake.asked = True
            return True
        fake.asked = False
        fake.discussion_pending = asked
        return fake

    def _run(self, fake):
        with mock.patch.object(m, "game", lambda: fake), \
                mock.patch.dict(os.environ, {"CIV5_TUNERD_SOCK": "/tmp/civ5-test-after.sock"}), \
                mock.patch.dict(m._RECENT, {}, clear=True), \
                mock.patch("harness.game_parts.units.time.sleep"):
            (r,) = anyio.run(session, [("unit_mission", {"unit_id": 7, "mission": "MISSION_FORTIFY"})])
        return r

    def test_a_status_that_says_no_discussion_is_believed_without_a_second_read(self):
        fake = self._fake(False)
        r = self._run(fake)
        self.assertTrue(r["ok"], r)
        self.assertFalse(fake.asked, "no separate discussion_pending() trip")

    def test_a_status_that_says_discussion_refuses(self):
        fake = self._fake(True)
        fake.discussion_pending = lambda: False
        r = self._run(fake)
        self.assertFalse(r["ok"])
        self.assertIn("diplomatic decision pending", r["err"])

    def test_a_status_without_the_flag_still_asks(self):
        fake = self._fake(None)
        r = self._run(fake)
        self.assertFalse(r["ok"])
        self.assertTrue(fake.asked)
