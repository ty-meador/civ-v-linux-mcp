"""Announcement screens are closed for the caller, never handed back as a chore.

Live 2026-09-27 (Codex c42, t116): finish_turn returned with the Great Person announcement up -- `gate`
announcement_screen, `woke_because` pending_popups / great_person_reward_pending -- and the agent's next two
calls (wait_for_my_turn, briefing again) did nothing but close a screen with no decision in it. Now every
call that reads our turn (the guard, turn_status, the arrival inside wait_for_my_turn) runs
Game.settle_announcements first: a sweep only when the status says a screen may be up, the state re-read after
it, `swept_popups` naming what closed. The announcement_screen gate is left for a close that did not take.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / "tests"))

import anyio  # noqa: E402

from harness import mcp_server as m  # noqa: E402
from harness.game import Game  # noqa: E402
import test_set_seat as seat_support  # noqa: E402

FREE = {"turn": 116, "active_player": 0, "my_turn": True, "processing": False, "paused": False, "hotseat": True,
        "hand_off_pending": False, "leader_greeting_pending": False, "discussion_pending": False,
        "tech_popup_pending": False, "city_state_greeting_pending": False, "great_person_reward_pending": False,
        "popup_up": False, "pending_popups": [], "todo": {"units": [], "research_unset": False},
        "blocking_name": "NO_ENDTURN_BLOCKING_TYPE"}


def _game(states, closes=("GreatPersonRewardPopup",)):
    """A detached Game whose turn_state replays `states`; dismiss_pending_popups closes `closes` once."""
    g = Game.__new__(Game)
    g.seat = 0
    g._runtime_ok = True
    reads = {"i": 0}
    log = []

    def turn_state(pid=None):
        ts = dict(states[min(reads["i"], len(states) - 1)])
        reads["i"] += 1
        log.append("read")
        return ts

    def dismiss(ts=None):
        log.append("sweep")
        out = list(closes) if log.count("sweep") == 1 else []
        return out
    g.turn_state = turn_state
    g.dismiss_pending_popups = dismiss
    return g, log


class WhenASweepIsWorthItsTrip(unittest.TestCase):
    def setUp(self):
        self.g = Game.__new__(Game)
        self.g.seat = 0

    def test_a_clean_status_costs_nothing(self):
        self.assertFalse(self.g.announcement_pending(FREE))
        self.assertFalse(self.g.announcement_pending(None))

    def test_the_two_screen_flags(self):
        self.assertTrue(self.g.announcement_pending({**FREE, "great_person_reward_pending": True}))
        self.assertTrue(self.g.announcement_pending({**FREE, "city_state_greeting_pending": True}))

    def test_a_recorded_popup_with_no_decision_in_it(self):
        for name in ("BUTTONPOPUP_WONDER_COMPLETED", "BUTTONPOPUP_NEW_ERA", "BUTTONPOPUP_TEXT",
                     "BUTTONPOPUP_GREAT_WORK_COMPLETED_ACTIVE_PLAYER"):
            self.assertTrue(self.g.announcement_pending({**FREE, "pending_popups": [{"name": name, "type": 1}]}), name)

    def test_a_decision_popup_is_the_agents_and_not_swept(self):
        ts = {**FREE, "popup_up": True, "pending_popups": [{"name": "BUTTONPOPUP_CHOOSETECH", "type": 2}]}
        self.assertFalse(self.g.announcement_pending(ts))
        ts = {**FREE, "popup_up": True, "pending_popups": [{"name": "BUTTONPOPUP_CITY_CAPTURED", "type": 3}]}
        self.assertFalse(self.g.announcement_pending(ts))

    def test_an_unrecorded_popup_the_engine_waits_on(self):
        self.assertTrue(self.g.announcement_pending({**FREE, "popup_up": True}))
        for flag in ("tech_popup_pending", "leader_greeting_pending", "discussion_pending"):
            self.assertFalse(self.g.announcement_pending({**FREE, "popup_up": True, flag: True}), flag)
        self.assertFalse(self.g.announcement_pending({**FREE, "popup_up": True, "hand_off_pending": True}))

    def test_another_seats_screen_is_never_ours(self):
        self.assertFalse(self.g.announcement_pending({**FREE, "active_player": 1, "great_person_reward_pending": True}))


class SettleAnnouncements(unittest.TestCase):
    def test_the_screen_is_closed_and_the_state_re_read(self):
        up = {**FREE, "great_person_reward_pending": True, "popup_up": True,
              "pending_popups": [{"name": "BUTTONPOPUP_GREAT_PERSON_REWARD", "type": 9}]}
        g, log = _game([FREE])
        with mock.patch("harness.game.time.sleep", lambda s: None):
            ts = g.settle_announcements(up)
        self.assertEqual(log, ["sweep", "read"])
        self.assertFalse(ts["great_person_reward_pending"])
        self.assertEqual(ts["pending_popups"], [])
        self.assertEqual(ts["swept_popups"], ["GreatPersonRewardPopup"])

    def test_nothing_up_means_no_sweep_and_the_same_state_back(self):
        g, log = _game([FREE])
        ts = g.settle_announcements(FREE)
        self.assertEqual(log, [])
        self.assertIs(ts, FREE)
        self.assertNotIn("swept_popups", ts)

    def test_a_close_that_does_not_take_is_handed_back_once(self):
        up = {**FREE, "city_state_greeting_pending": True}
        g, log = _game([up], closes=())
        ts = g.settle_announcements(up)
        self.assertEqual(log, ["sweep"], "one sweep, no re-read: nothing closed")
        self.assertTrue(ts["city_state_greeting_pending"])
        self.assertNotIn("swept_popups", ts)

    def test_two_rounds_at_most(self):
        up = {**FREE, "city_state_greeting_pending": True}
        g, log = _game([up, up, up])
        g.dismiss_pending_popups = lambda ts=None: log.append("sweep") or ["CityStateGreetingPopup"]
        with mock.patch("harness.game.time.sleep", lambda s: None):
            ts = g.settle_announcements(up)
        self.assertEqual(log.count("sweep"), 2)
        self.assertEqual(ts["swept_popups"], ["CityStateGreetingPopup", "CityStateGreetingPopup"])


class TheWaitHandsBackAPlayableTurn(unittest.TestCase):
    """wait_for_my_turn's arrival: the late re-read sees the announcement; the turn comes back without it."""

    def _game(self, states):
        g = Game.__new__(Game)
        g.seat = 0
        g._runtime_ok = True
        reads = {"i": 0}
        log = []

        def q(code, timeout=None):
            if "H.turn_state" in code:
                ts = dict(states[min(reads["i"], len(states) - 1)])
                reads["i"] += 1
                log.append("read")
                return ts
            return []
        g.q = q
        g.c = type("C", (), {"ping": staticmethod(lambda: {"connected": True})})()
        g.expiring_city_states = list
        g._unit_rows = lambda pid=None: []
        g.notebook = lambda: (_ for _ in ()).throw(RuntimeError("no notebook"))

        def dismiss(ts=None):
            log.append("sweep")
            return ["GreatPersonRewardPopup"] if (ts or {}).get("great_person_reward_pending") else []
        g.dismiss_pending_popups = dismiss
        return g, log

    def test_an_announcement_seen_by_the_late_read_is_closed(self):
        born = {**FREE, "great_person_reward_pending": True, "popup_up": True,
                "pending_popups": [{"name": "BUTTONPOPUP_GREAT_PERSON_REWARD", "type": 9}]}
        # poll read: clean; late-discussion read: the screen is up; after the sweep: clean again
        g, log = self._game([FREE, born, FREE])
        with mock.patch("harness.game.time.sleep", lambda s: None):
            ts = g.wait_for_my_turn(timeout=5, poll=0.01)
        self.assertTrue(ts["my_turn"])
        self.assertFalse(ts["great_person_reward_pending"])
        self.assertEqual(ts["pending_popups"], [])
        self.assertEqual(ts["swept_popups"], ["GreatPersonRewardPopup"])
        self.assertEqual(log.count("sweep"), 2, "the poll's sweep and the settle's")

    def test_a_clean_arrival_spends_no_extra_trip(self):
        g, log = self._game([FREE])
        with mock.patch("harness.game.time.sleep", lambda s: None):
            ts = g.wait_for_my_turn(timeout=5, poll=0.01)
        self.assertTrue(ts["my_turn"])
        self.assertNotIn("swept_popups", ts)
        self.assertEqual(log.count("read"), 2, "the poll's read and the late-discussion re-read")
        self.assertEqual(log.count("sweep"), 1)


class AnnouncementGame(seat_support.FakeGame):
    """Seat 0's own server with the Great Person screen up (the Codex c42 shape); the sweep closes it."""
    announcement_pending = Game.announcement_pending
    settle_announcements = Game.settle_announcements
    _ANNOUNCEMENT_SETTLE = 0.0

    def __init__(self):
        super().__init__(mode="hotseat", humans=(0, 1), active=0, seat=0)
        self.up = True
        self.sticky = False
        self.sweeps = 0
        self.orders = []

    def turn_state(self, pid=None):
        ts = super().turn_state(pid)
        ts.update({"hand_off_pending": False, "popup_up": self.up, "great_person_reward_pending": self.up,
                   "pending_popups": [{"name": "BUTTONPOPUP_GREAT_PERSON_REWARD", "type": 9}] if self.up else [],
                   "game_over": False, "leader_greeting_pending": False, "discussion_pending": False,
                   "tech_popup_pending": False, "city_state_greeting_pending": False})
        return ts

    def clear_hand_off(self, ts):
        return ts

    def dismiss_pending_popups(self, ts=None):
        self.sweeps += 1
        if self.sticky or not self.up:
            return []
        self.up = False
        return ["GreatPersonRewardPopup"]

    def set_research(self, tech):
        self.orders.append(tech)
        return {"ok": True, "research": tech}

    def notebook(self):
        raise RuntimeError("no notebook in this fake")


class McpCallsCloseTheScreenFirst(unittest.TestCase):
    def setUp(self):
        self.fake = AnnouncementGame()
        self.patches = [mock.patch.object(m, "game", lambda: self.fake),
                        mock.patch.dict(os.environ, {"CIV5_TUNERD_SOCK": "/tmp/civ5-test-announce.sock", "CIV5_SEAT": "0"}),
                        mock.patch.object(m, "_seat_rechecked", True),
                        mock.patch.dict(m._RECENT, {}, clear=True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_turn_status_closes_it_and_answers_with_a_playable_turn(self):
        (out,) = anyio.run(seat_support.session, [("turn_status", {})])
        self.assertIsNone(out["gate"], out)
        self.assertFalse(out["great_person_reward_pending"])
        self.assertEqual(out["swept_popups"], ["GreatPersonRewardPopup"])
        self.assertEqual((self.fake.sweeps, self.fake.up), (1, False))

    def test_an_order_under_the_screen_closes_it_and_runs(self):
        (out,) = anyio.run(seat_support.session, [("set_research", {"tech": "TECH_POTTERY"})])
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.fake.orders, ["TECH_POTTERY"])
        self.assertEqual(self.fake.up, False)

    def test_a_clean_turn_spends_no_sweep(self):
        self.fake.up = False
        (out,) = anyio.run(seat_support.session, [("turn_status", {})])
        self.assertIsNone(out["gate"])
        self.assertEqual(self.fake.sweeps, 0)
        self.assertNotIn("swept_popups", out)

    def test_a_close_that_does_not_take_is_an_honest_gate(self):
        self.fake.sticky = True
        status, refused = anyio.run(seat_support.session, [("turn_status", {}), ("set_research", {"tech": "TECH_POTTERY"})])
        self.assertEqual((status["gate"]["name"], status["gate"]["clear_with"]), ("announcement_screen", "wait_for_my_turn"))
        self.assertIn("close did not take", status["gate"]["why"])
        self.assertEqual(self.fake.orders, [], refused)

    def test_the_other_seats_screen_is_never_touched(self):
        self.fake.active = 1
        status, refused = anyio.run(seat_support.session, [("turn_status", {}), ("units", {})])
        self.assertEqual((status["gate"]["name"], refused["gate"]["name"]), ("other_seat_active", "other_seat_active"))
        self.assertEqual((self.fake.sweeps, self.fake.up), (0, True))


if __name__ == "__main__":
    unittest.main()
