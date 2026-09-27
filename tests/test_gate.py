"""`gate`: one field that says what must happen before anything else works, and which tool does it.

Live 2026-09-26 (Codex, seat 0 of a two-agent hotseat game): its own hand-off screen showed in turn_status only
as paused=true / popup_up=true with an empty todo, so it read the board for four minutes and replayed a cached
"game is paused" refusal before calling wait_for_my_turn; earlier, with the other seat on screen, the note
"set_seat(player_id) changes the seat" sent it onto the other player's Continue button. Now every status and
refusal carries `gate` (harness/gate.py), the hand-off screen is a flag of its own (runtime v215
`hand_off_pending`), a pinned server never hears about set_seat, and a gate refusal is not replayed.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import anyio

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from harness import mcp_server as m  # noqa: E402
from harness.gate import POPUP_RESOLUTIONS, compute_gate, popup_gate, resolutions_by_tool  # noqa: E402
from harness.game import Game  # noqa: E402
import test_set_seat as seat_support  # noqa: E402

FREE = {"turn": 24, "active_player": 0, "my_turn": True, "processing": False, "paused": False, "hotseat": True,
        "mode": "hotseat", "game_over": False, "hand_off_pending": False, "leader_greeting_pending": False,
        "discussion_pending": False, "tech_popup_pending": False, "city_state_greeting_pending": False,
        "great_person_reward_pending": False, "pending_popups": [], "todo": {"units": [], "research_unset": False},
        "blocking_name": "ENDTURN_BLOCKING_UNITS"}


class PrecedenceTests(unittest.TestCase):
    def test_a_free_seat_has_no_gate_even_with_an_end_turn_blocker(self):
        self.assertIsNone(compute_gate(FREE, 0))

    def test_the_hand_off_screen_is_named_and_cleared_by_the_wait(self):
        g = compute_gate({**FREE, "hand_off_pending": True, "paused": True, "popup_up": True}, 0)
        self.assertEqual((g["name"], g["clear_with"]), ("hand_off_screen", "wait_for_my_turn"))
        self.assertIn("Continue", g["why"])

    def test_the_other_seat_on_screen_is_a_wait_and_not_a_set_seat(self):
        ts = {**FREE, "active_player": 1, "my_turn": False}
        g = compute_gate(ts, 0)
        self.assertEqual((g["name"], g["clear_with"]), ("other_seat_active", "wait_for_my_turn"))
        self.assertNotIn("set_seat", g["why"])
        guessed = compute_gate(ts, 0, may_change_seat=True)
        self.assertIn("set_seat(1)", guessed["why"])
        self.assertIn("never take a seat another player is playing", guessed["why"])

    def test_the_ai_round_after_the_other_seat_ended_is_named(self):
        ts = {**FREE, "active_player": 1, "my_turn": False, "active_turn_active": False}
        g = compute_gate(ts, 0)
        self.assertEqual((g["name"], g["clear_with"]), ("other_seat_active", "wait_for_my_turn"))
        self.assertIn("AIs are moving", g["why"])
        self.assertIn("seat 1 has ended its turn", g["why"])
        # the seat on screen still holding its turn reads as before; an unknown flag (older runtime) too
        self.assertIn("seat 1 is on screen", compute_gate({**ts, "active_turn_active": True}, 0)["why"])
        self.assertIn("seat 1 is on screen", compute_gate({**FREE, "active_player": 1, "my_turn": False}, 0)["why"])

    def test_a_deal_on_the_table_is_cleared_by_accept_or_refuse(self):
        ts = {**FREE, "discussion_pending": True, "trade_state": "DiploTrade"}
        g = compute_gate(ts, 0)
        self.assertEqual((g["name"], g["clear_with"], g["read_first"]), ("discussion", "accept_deal", "incoming_deal"))
        self.assertIn("refuse_deal", g["alternatives"])
        self.assertNotIn("respond_discussion", g["why"])
        g = compute_gate({**FREE, "discussion_pending": True, "trade_state": None}, 0)
        self.assertEqual(g["clear_with"], "respond_discussion")

    def test_turn_state_keeps_trade_state_for_the_gate(self):
        from harness.game import Game
        g = Game.__new__(Game)
        g.seat = 0
        flags = {k: False for k in Game.MODAL_FLAGS}
        g.q = lambda code, **kw: {**FREE, **flags, "discussion_pending": True, "trade_state": "DiploTrade"}
        g._note_happiness = lambda ts: None
        ts = g.turn_state()
        self.assertEqual(ts["trade_state"], "DiploTrade")
        self.assertEqual(g._trade_state, "DiploTrade")
        self.assertEqual(compute_gate(ts, 0)["clear_with"], "accept_deal")

    def test_the_order_is_the_engines(self):
        everything = {**FREE, "active_player": 1, "my_turn": False, "hand_off_pending": True, "processing": True,
                      "paused": True, "leader_greeting_pending": True, "discussion_pending": True,
                      "tech_popup_pending": True, "todo": {"research_unset": True},
                      "pending_popups": [{"name": "BUTTONPOPUP_CHOOSEPOLICY"}], "city_state_greeting_pending": True}
        seen = []
        clear = [("active_player", 0), ("hand_off_pending", False), ("processing", False), ("paused", False),
                 ("my_turn", True), ("leader_greeting_pending", False), ("discussion_pending", False),
                 ("tech_popup_pending", False), ("pending_popups", []), ("city_state_greeting_pending", False)]
        ts = dict(everything)
        for key, value in clear:
            seen.append(compute_gate(ts, 0)["name"])
            ts[key] = value
        self.assertIsNone(compute_gate(ts, 0))
        self.assertEqual(seen, ["other_seat_active", "hand_off_screen", "processing", "paused", "turn_not_active",
                                "leader_screen", "discussion", "tech_choice", "decision_popup", "announcement_screen"])

    def test_no_game_and_game_over_come_first(self):
        self.assertEqual(compute_gate({"ok": True, "ingame": False, "screen": "MainMenu"}, 0)["name"], "no_game")
        self.assertEqual(compute_gate({**FREE, "game_over": True, "hand_off_pending": True}, 0)["name"], "game_over")

    def test_a_solo_game_waiting_on_the_ais(self):
        g = compute_gate({**FREE, "hotseat": False, "mode": "single", "active_player": 3, "my_turn": False}, 0)
        self.assertEqual((g["name"], g["clear_with"]), ("waiting_for_turn", "wait_for_my_turn"))

    def test_paused_without_the_flag_still_points_at_the_hand_off(self):
        """An older runtime's turn_state has no hand_off_pending; paused in hotseat is its shadow."""
        ts = {k: v for k, v in FREE.items() if k != "hand_off_pending"}
        g = compute_gate({**ts, "paused": True}, 0)
        self.assertEqual(g["name"], "paused")
        self.assertIn("hand-off screen", g["why"])

    def test_a_decision_popup_names_its_resolver_and_the_read_before_it(self):
        g = compute_gate({**FREE, "pending_popups": [{"name": "BUTTONPOPUP_CHOOSE_GOODY_HUT_REWARD"}]}, 0)
        self.assertEqual((g["name"], g["popup"], g["clear_with"], g["read_first"]),
                         ("decision_popup", "BUTTONPOPUP_CHOOSE_GOODY_HUT_REWARD", "choose_goody_hut", "goody_hut_options"))
        unknown = popup_gate({"name": "BUTTONPOPUP_SOMETHING_NEW"})
        self.assertEqual((unknown["clear_with"], unknown["read_first"]), ("answer_popup", "generic_popup"))

    def test_an_announcement_popup_is_not_a_gate(self):
        """The guard sweeps GOODY_HUT_REWARD and its kin on the next action; only decision popups gate."""
        self.assertIsNone(compute_gate({**FREE, "pending_popups": [{"name": "BUTTONPOPUP_GOODY_HUT_REWARD"}]}, 0))

    def test_the_guards_allow_list_is_derived_from_the_same_table(self):
        by_tool = resolutions_by_tool()
        self.assertEqual(by_tool["set_research"], {"BUTTONPOPUP_CHOOSETECH", "BUTTONPOPUP_TECH_TREE"})
        self.assertEqual(by_tool["unlock_policy_branch"], {"BUTTONPOPUP_CHOOSEPOLICY"})
        self.assertEqual(by_tool["add_reformation_belief"], {"BUTTONPOPUP_FOUND_PANTHEON"})
        for popup, r in POPUP_RESOLUTIONS.items():
            self.assertIn(popup, by_tool[r["clear_with"]])


class HandOffGame(seat_support.FakeGame):
    """Seat 0's own server, its hand-off screen up (the live t22/t24 shape), then cleared by the wait."""

    def __init__(self):
        super().__init__(mode="hotseat", humans=(0, 1), active=0, seat=0)
        self.hand_off = True
        self.sticky = False     # a Continue press that does not take (the screen stays up)
        self.pressed = 0
        self.orders = []

    def turn_state(self, pid=None):
        ts = super().turn_state(pid)
        ts.update({"hand_off_pending": self.hand_off, "paused": self.hand_off, "popup_up": self.hand_off,
                   "game_over": False})
        return ts

    def clear_hand_off(self, ts):
        if not (ts.get("hotseat") and ts.get("active_player") == self.seat and ts.get("hand_off_pending")):
            return ts
        self.pressed += 1
        if self.sticky:
            return ts
        self.hand_off = False
        return {**self.turn_state(), "hand_off_cleared": True}

    def wait_for_my_turn(self, timeout=90, on_wait=None):
        self.hand_off = False
        return self.turn_state()

    def set_research(self, tech):
        self.orders.append(tech)
        return {"ok": True, "research": tech}

    def notebook(self):
        raise RuntimeError("no notebook in this fake")


class McpAnswersCarryTheGate(unittest.TestCase):
    def setUp(self):
        self.fake = HandOffGame()
        self.patches = [mock.patch.object(m, "game", lambda: self.fake),
                        mock.patch.dict(os.environ, {"CIV5_TUNERD_SOCK": "/tmp/civ5-test-gate.sock", "CIV5_SEAT": "0"}),
                        mock.patch.object(m, "_seat_rechecked", True),
                        mock.patch.dict(m._RECENT, {}, clear=True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_turn_status_presses_our_continue_screen_and_answers_with_the_turn(self):
        """The first call after a (re)start meets a game state, not a UI gate to clear first."""
        (out,) = anyio.run(seat_support.session, [("turn_status", {})])
        self.assertIsNone(out["gate"])
        self.assertTrue(out["hand_off_cleared"])
        self.assertTrue(out["my_turn"] and not out["paused"])
        self.assertEqual((self.fake.pressed, self.fake.hand_off), (1, False))

    def test_an_order_under_the_screen_presses_continue_and_runs(self):
        (out,) = anyio.run(seat_support.session, [("set_research", {"tech": "TECH_POTTERY"})])
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.fake.orders, ["TECH_POTTERY"])
        self.assertEqual(self.fake.pressed, 1)

    def test_a_press_that_does_not_take_is_an_honest_gate(self):
        self.fake.sticky = True
        status, refused = anyio.run(seat_support.session, [("turn_status", {}), ("set_research", {"tech": "TECH_POTTERY"})])
        self.assertEqual((status["gate"]["name"], status["gate"]["clear_with"]), ("hand_off_screen", "wait_for_my_turn"))
        self.assertIn("press did not take", status["gate"]["why"])
        self.assertFalse(refused["ok"])
        self.assertIn("still up", refused["err"])
        self.assertEqual(refused["gate"]["name"], "hand_off_screen")
        self.assertEqual(self.fake.orders, [])

    def test_the_other_seats_screen_is_never_pressed(self):
        self.fake.active = 1
        status, refused = anyio.run(seat_support.session, [("turn_status", {}), ("units", {})])
        self.assertEqual((status["gate"]["name"], refused["gate"]["name"]), ("other_seat_active", "other_seat_active"))
        self.assertEqual((self.fake.pressed, self.fake.hand_off), (0, True))

    def test_the_wait_clears_it_and_answers_with_no_gate(self):
        wait, status = anyio.run(seat_support.session, [("wait_for_my_turn", {"timeout_seconds": 5}), ("turn_status", {})])
        self.assertIsNone(wait["gate"])
        self.assertIsNone(status["gate"])

    def test_a_gate_refusal_is_not_replayed_after_the_gate_clears(self):
        self.fake.sticky = True
        (refused,) = anyio.run(seat_support.session, [("set_research", {"tech": "TECH_POTTERY", "action_id": "t24-research"})])
        self.fake.sticky = False
        _, ran = anyio.run(seat_support.session, [
            ("wait_for_my_turn", {"timeout_seconds": 5}),
            ("set_research", {"tech": "TECH_POTTERY", "action_id": "t24-research"})])
        self.assertFalse(refused["ok"])
        self.assertTrue(ran["ok"], ran)
        self.assertNotIn("replayed", ran)
        self.assertEqual(self.fake.orders, ["TECH_POTTERY"])

    def test_a_pinned_server_never_hears_about_set_seat(self):
        self.fake.active = 1
        self.fake.hand_off = False
        status, refused = anyio.run(seat_support.session, [("turn_status", {}), ("units", {})])
        self.assertEqual(status["gate"]["name"], "other_seat_active")
        for text in (status["seat_note"], status["gate"]["why"], refused["hint"], refused["gate"]["why"]):
            self.assertNotIn("set_seat", text)
        self.assertIn("wait_for_my_turn", status["seat_note"])
        self.assertEqual(refused["gate"]["name"], "other_seat_active")

    def test_an_auto_seat_server_hears_it_only_as_a_last_resort(self):
        self.fake.active = 1
        self.fake.hand_off = False
        with mock.patch.dict(os.environ, {"CIV5_SEAT": "auto"}):
            (status,) = anyio.run(seat_support.session, [("turn_status", {})])
        self.assertIn("Only if nobody else plays seat 1", status["seat_note"])
        self.assertIn("never take a seat another player is playing", status["gate"]["why"])


class TheWaitLoopUsesTheCarriedFlag(unittest.TestCase):
    """runtime v215: the hand-off is in turn_state, so a poll spends no trips on the PlayerChange state."""

    def _game(self, hand_off_states):
        g = Game.__new__(Game)
        g.seat = 0
        g._runtime_ok = True
        g._pid = lambda pid=None: 0
        flags = {"leader_greeting_pending": False, "city_state_greeting_pending": False,
                 "great_person_reward_pending": False, "tech_popup_pending": False, "discussion_pending": False}
        state = {"i": 0}

        def q(code, timeout=None):
            if "H.turn_state" in code:
                up = hand_off_states[min(state["i"], len(hand_off_states) - 1)]
                state["i"] += 1
                return {"turn": 24, "active_player": 0, "my_turn": True, "processing": False, "hotseat": True,
                        "pending_popups": [], "todo": {"units": []}, "hand_off_pending": up, **flags}
            return []
        g.q = q
        dismissed = []
        g.dismiss_player_change = lambda: dismissed.append(True)
        g.c = type("C", (), {"ping": staticmethod(lambda: {"connected": True}),
                             "wait_state": staticmethod(lambda *a, **k: (_ for _ in ()).throw(AssertionError("PlayerChange probed")))})()
        g.expiring_city_states = lambda: []
        g._unit_rows = lambda pid=None: []
        g.dismiss_pending_popups = lambda ts=None: []
        return g, dismissed

    def test_the_flag_drives_the_dismissal_without_a_probe(self):
        g, dismissed = self._game([True, False])
        with mock.patch("harness.game.time.sleep", lambda s: None):
            ts = g.wait_for_my_turn(timeout=5, poll=0.01)
        self.assertEqual(dismissed, [True])
        self.assertFalse(ts["hand_off_pending"])

    def test_no_screen_means_no_dismissal(self):
        g, dismissed = self._game([False])
        ts = g.wait_for_my_turn(timeout=5, poll=0.01)
        self.assertEqual(dismissed, [])
        self.assertTrue(ts["my_turn"])


class AnyCallPressesOurContinueScreen(unittest.TestCase):
    """Game.clear_hand_off: what every guarded tool and turn_status run before looking at the state."""

    def _game(self, hand_off_states, active=0):
        g, dismissed = TheWaitLoopUsesTheCarriedFlag()._game(hand_off_states)
        real_q = g.q
        resumed = []

        def q(code, timeout=None):
            if "H.resume_moves" in code:
                resumed.append(code)
                return []
            out = real_q(code, timeout)
            if isinstance(out, dict):
                out["active_player"] = active
            return out
        g.q = q
        return g, dismissed, resumed

    def test_our_screen_is_pressed_and_the_turn_arrives(self):
        g, dismissed, resumed = self._game([True, False])
        with mock.patch("harness.game.time.sleep", lambda s: None):
            ts = g.clear_hand_off(g.turn_state())
        self.assertEqual(dismissed, [True])
        self.assertTrue(ts["hand_off_cleared"])
        self.assertFalse(ts["hand_off_pending"])
        self.assertEqual(len(resumed), 1, "the turn-start routine (standing orders) ran once")

    def test_two_presses_then_the_screen_is_left_to_the_gate(self):
        g, dismissed, resumed = self._game([True, True, True, True])
        with mock.patch("harness.game.time.sleep", lambda s: None):
            ts = g.clear_hand_off(g.turn_state())
        self.assertEqual(dismissed, [True, True])
        self.assertTrue(ts["hand_off_pending"])
        self.assertNotIn("hand_off_cleared", ts)
        self.assertEqual(resumed, [])

    def test_another_seats_screen_is_left_alone(self):
        g, dismissed, resumed = self._game([True], active=1)
        ts = g.clear_hand_off(g.turn_state())
        self.assertEqual(dismissed, [])
        self.assertTrue(ts["hand_off_pending"])
        self.assertNotIn("hand_off_cleared", ts)

    def test_finish_turn_under_our_screen_presses_it_and_never_ends_that_turn(self):
        """A finish_turn retried after a client timeout that lands on the next turn's Continue screen must
        hand that turn back, not end it blind (my_turn already reads true under the screen)."""
        g, dismissed, resumed = self._game([True, True, False, False])
        ended = []
        g.end_turn = lambda autosave=True: ended.append(True) or {"ok": True}
        g.turn_digest = lambda: {"events": [], "notifications": []}
        with mock.patch("harness.game.time.sleep", lambda s: None):
            out = g.finish_turn(timeout=5)
        self.assertEqual(ended, [])
        self.assertEqual(dismissed, [True])
        self.assertFalse(out["ended"])
        self.assertFalse(out["status"]["hand_off_pending"])

    def test_player_change_pending_trusts_the_flag_and_falls_back_without_it(self):
        g = Game.__new__(Game)
        probes = []
        g.c = type("C", (), {"wait_state": staticmethod(lambda *a, **k: probes.append(a) or "PlayerChange"),
                             "exec": staticmethod(lambda *a, **k: ["true"])})()
        self.assertTrue(g.player_change_pending({"hand_off_pending": True}))
        self.assertFalse(g.player_change_pending({"hand_off_pending": False}))
        self.assertEqual(probes, [])
        self.assertTrue(g.player_change_pending({}))
        self.assertEqual(len(probes), 1)


class LuaRuntimeCarriesTheFlag(unittest.TestCase):
    def test_hand_off_up_is_false_where_there_is_no_ui_and_the_key_is_carried(self):
        import test_mcp_safety as support
        case = support.LuaRuntimeTests("test_unmet_civilizations_are_not_returned")
        try:
            case.setUp()
        except unittest.SkipTest as e:
            self.skipTest(str(e))
        case.run_lua("assert(H.hand_off_up() == false, 'no ContextPtr: not up')")
        case.run_lua("local found = false; for _, k in ipairs(H.MODAL_FLAG_KEYS) do if k == 'hand_off_pending' then found = true end end; assert(found, 'hand_off_pending is a turn_state key')")
        case.doCleanups()


if __name__ == "__main__":
    unittest.main()


class PopupHintTests(unittest.TestCase):
    """The `hint` a refusal carries for an unresolved popup comes from the one resolution table."""

    def test_the_read_then_the_choice(self):
        from harness.gate import popup_hint
        self.assertEqual(popup_hint("BUTTONPOPUP_CHOOSE_GOODY_HUT_REWARD"), "goody_hut_options() then choose_goody_hut(goody)")
        self.assertEqual(popup_hint("BUTTONPOPUP_CHOOSE_ARCHAEOLOGY"), "archaeology_options() then choose_archaeology(choice, x, y)")

    def test_a_tech_or_production_popup_names_its_own_resolver_not_answer_popup(self):
        from harness.gate import popup_hint
        self.assertEqual(popup_hint("BUTTONPOPUP_CHOOSETECH"), "available_research() then set_research(tech)")
        self.assertEqual(popup_hint("BUTTONPOPUP_CHOOSEPRODUCTION"), "available_production() then set_production(city_id, item)")

    def test_an_unknown_popup_gets_the_generic_recipe(self):
        from harness.gate import popup_hint
        self.assertIn("answer_popup(button)", popup_hint("BUTTONPOPUP_SOMETHING_ELSE"))
