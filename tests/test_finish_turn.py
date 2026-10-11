"""finish_turn: the turn boundary as one call, and the quiet-turn skipping behind it.

No game: a scripted Game whose end_turn / wait_for_my_turn / turn_digest replay a sequence of turns.
"""
import unittest

from harness.game import Game


def status(turn, my_turn=True, todo=None, blocking="NO_ENDTURN_BLOCKING_TYPE", **extra):
    ts = {"turn": turn, "my_turn": my_turn, "active_player": 0, "processing": False, "paused": False,
          "blocking_name": blocking, "pending_popups": [], "alive": True, "hotseat": False,
          "todo": todo if todo is not None else {"units": [], "cities": [], "promotions": [], "research_unset": False}}
    ts.update(extra)
    return ts


class ScriptedGame(Game):
    """Each `turns` entry is (status_when_my_turn_returns, digest). end_turn advances the script."""

    def __init__(self, turns, first_status=None, end_turn_ok=True, wait_raises=None):
        self.seat = 0
        self.turns = list(turns)
        self.i = 0
        self.first_status = first_status or status(1)
        self.end_turn_ok = end_turn_ok
        self.wait_raises = wait_raises
        self.log = []

    def turn_state(self, pid=None):
        if self.i == 0 and not self.log:
            return self.first_status
        # After end_turn the AIs move: not my turn until wait returns.
        return status(self.turns[min(self.i, len(self.turns)) - 1][0]["turn"], my_turn=False) if self.log and self.log[-1] == "end" else self.turns[self.i - 1][0]

    def end_turn(self, autosave=True):
        self.log.append("end")
        if not self.end_turn_ok:
            return {"ok": False, "err": "a unit needs orders"}
        return {"ok": True}

    def wait_for_my_turn(self, timeout=3600, poll=1.0, on_wait=None):
        self.log.append("wait")
        if self.wait_raises:
            raise self.wait_raises
        if on_wait:
            on_wait(1.0, {"turn": 0, "active_player": 3})
        self.i += 1
        return dict(self.turns[self.i - 1][0])

    def turn_digest(self):
        self.log.append("digest")
        return dict(self.turns[self.i - 1][1])


QUIET = {"events": [{"kind": "turn_start", "data": {}}], "notifications": []}


class FinishTurnTests(unittest.TestCase):
    def test_one_call_is_end_wait_digest(self):
        g = ScriptedGame([(status(2), {"events": [{"kind": "city_created", "data": {}}], "notifications": []})])
        r = g.finish_turn()
        self.assertEqual(g.log, ["end", "wait", "digest"])
        self.assertTrue(r["ok"] and r["ended"])
        self.assertEqual(r["turn"], 2)
        self.assertEqual(r["digest"]["events"][0]["kind"], "city_created")
        self.assertEqual(r["turns_skipped"], 0)
        self.assertEqual(r["woke_because"], ["event:city_created"])
        g = ScriptedGame([(status(2), QUIET)])
        self.assertEqual(g.finish_turn()["woke_because"], ["turn_started"])

    def test_refused_end_turn_waits_on_nothing(self):
        g = ScriptedGame([(status(2), QUIET)], end_turn_ok=False)
        r = g.finish_turn()
        self.assertFalse(r["ok"])
        self.assertEqual(g.log, ["end"])
        self.assertIn("unit needs orders", r["end_turn"]["err"])
        self.assertIn("status", r)

    def test_when_it_is_not_my_turn_it_only_waits(self):
        # A retried call after a client timeout must never end a second turn.
        g = ScriptedGame([(status(2), QUIET)], first_status=status(1, my_turn=False))
        r = g.finish_turn()
        self.assertEqual(g.log, ["wait", "digest"])
        self.assertTrue(r["ok"])
        self.assertFalse(r["ended"])

    def test_timeout_returns_status_with_hint(self):
        g = ScriptedGame([(status(2), QUIET)], wait_raises=TimeoutError("timed out"))
        r = g.finish_turn(timeout=1)
        self.assertTrue(r["timed_out"])
        self.assertTrue(r["ended"])
        self.assertIn("finish_turn again", r["hint"])
        # Solo / LAN: the AIs are still moving, the boundary has not passed -- no digest yet, the cursor stays.
        self.assertEqual(g.log, ["end", "wait"])
        self.assertNotIn("digest", r)

    def test_hotseat_hand_off_timeout_takes_the_digest(self):
        # Live t192 (2026-10-03): one session played both hotseat seats; each seat's finish_turn ended its turn
        # and timed out at once with the other seat on screen, which skipped the digest every time -- seat 1's
        # event cursor never moved and its first completed digest carried 350 events from 29 turns (75 KB).
        # With my turn ended and the other human seat on screen the boundary has passed: take the digest then.
        class HotseatGame(ScriptedGame):
            def turn_state(self, pid=None):
                if self.log and self.log[-1] in ("end", "wait"):
                    return status(2, my_turn=False, hotseat=True, active_player=1)
                return status(1, hotseat=True)

        digest = {"events": [{"kind": "leader_message", "data": {"text": "war"}}], "notifications": []}
        g = HotseatGame([(status(2), digest)], wait_raises=TimeoutError("timed out"))
        r = g.finish_turn(timeout=1)
        self.assertEqual(g.log, ["end", "wait", "digest"])
        self.assertTrue(r["timed_out"] and r["ended"])
        self.assertEqual(r["digest"]["events"][0]["kind"], "leader_message")
        # Only a turn this call ended: a retried call that only waited takes nothing on a timeout.
        g = HotseatGame([(status(2), digest)], wait_raises=TimeoutError("timed out"))
        g.log.append("wait")   # a previous call already ended the turn
        g.i = 0
        g.first_status = None
        r = g.finish_turn(timeout=1)
        self.assertEqual(g.log, ["wait", "wait"])
        self.assertNotIn("digest", r)

    def test_events_older_than_the_turn_before_the_ended_one_are_dropped(self):
        # Live 2026-10-03 (Venice t208, hotseat): the seat's event cursor had not moved since t198, so the
        # finish_turn digest carried the 120-event cap (~10 KB) of which only t207-t208 mattered. Events that
        # predate the turn before the one just ended were in that seat's own briefings already.
        ev = [{"kind": "notification", "turn": 3, "data": {"text": "old"}},
              {"kind": "leader_message", "turn": 6, "data": {"text": "old too"}},
              {"kind": "notification", "turn": 7, "data": {"text": "AI round before my t8"}},
              {"kind": "turn_start", "turn": 8, "data": {}},
              {"kind": "notification", "turn": 9, "data": {"text": "new"}}]
        g = ScriptedGame([(status(9), {"events": ev, "notifications": []})], first_status=status(8))
        r = g.finish_turn()
        self.assertEqual([e["turn"] for e in r["digest"]["events"]], [7, 8, 9])
        self.assertEqual(r["digest"]["stale"]["count"], 2)
        self.assertEqual(r["digest"]["stale"]["turns"], [3, 6])
        self.assertEqual(r["digest"]["stale"]["by_kind"], {"notification": 1, "leader_message": 1})
        self.assertIn("turn 7", r["digest"]["stale"]["hint"])

    def test_no_stale_key_when_nothing_is_old(self):
        g = ScriptedGame([(status(9), {"events": [{"kind": "turn_start", "turn": 9, "data": {}}], "notifications": []})],
                         first_status=status(8))
        r = g.finish_turn()
        self.assertNotIn("stale", r["digest"])

    def test_hotseat_hand_off_timeout_digest_is_trimmed_too(self):
        # The hand-off timeout path (my turn ended, the other human seat is on screen) takes the digest at
        # once; it is the path the live flood came through.
        class G(ScriptedGame):
            def turn_state(self, pid=None):
                if self.log and self.log[-1] == "wait":
                    return status(8, my_turn=False, active_player=1, hotseat=True)
                return self.first_status
        ev = [{"kind": "notification", "turn": 2, "data": {"text": "old"}},
              {"kind": "notification", "turn": 8, "data": {"text": "this turn"}}]
        g = G([(status(8), {"events": ev, "notifications": []})], first_status=status(8, hotseat=True),
              wait_raises=TimeoutError())
        g.i = 1
        r = g.finish_turn(timeout=1)
        self.assertTrue(r["timed_out"] and r["ended"])
        self.assertEqual([e["turn"] for e in r["digest"]["events"]], [8])
        self.assertEqual(r["digest"]["stale"]["count"], 1)

    def test_merged_digest_adds_up_omitted(self):
        merged = {"events": [], "notifications": []}
        Game._merge_digest(merged, {"events": [1], "notifications": [], "omitted": {"count": 3, "turns": [5, 7]}})
        Game._merge_digest(merged, {"events": [2], "notifications": []})
        Game._merge_digest(merged, {"events": [3], "notifications": [], "omitted": {"count": 2, "turns": [8, 8]}})
        self.assertEqual(merged["events"], [1, 2, 3])
        self.assertEqual(merged["omitted"]["count"], 5)
        self.assertEqual(merged["omitted"]["turns"], [5, 8])

    def test_quiet_turns_are_skipped_up_to_the_budget(self):
        g = ScriptedGame([(status(2), QUIET), (status(3), QUIET), (status(4), QUIET), (status(5), QUIET)])
        r = g.finish_turn(skip_quiet_turns=2)
        self.assertEqual(r["turn"], 4)
        self.assertEqual(r["turns_skipped"], 2)
        self.assertEqual(r["woke_because"], ["quiet_turn_budget_used"])
        self.assertEqual(g.log.count("end"), 3)
        self.assertEqual(len(r["digest"]["events"]), 3, "the skipped turns' digests are merged")

    def test_a_stack_warning_alone_does_not_wake(self):
        # Codex c41 (2026-09-27): a quiet run woke on "todo.stacked" for a stack its own note called
        # non-blocking. The unit that needs orders is in todo.units; the stack is only a warning.
        stacked = {"units": [], "cities": [], "promotions": [], "research_unset": False,
                   "stacked": [{"x": 3, "y": 4, "class": "combat", "units": [{"id": 1}, {"id": 2}]}]}
        g = ScriptedGame([(status(2, todo=stacked), QUIET),
                          (status(3, todo={**stacked, "units": [{"id": 1}]}), QUIET)])
        r = g.finish_turn(skip_quiet_turns=3)
        self.assertEqual((r["turn"], r["turns_skipped"]), (3, 1))
        self.assertEqual(r["woke_because"], ["todo.units"])

    def test_a_unit_needing_orders_wakes(self):
        busy = status(3, todo={"units": [{"id": 7}], "cities": [], "promotions": [], "research_unset": False})
        g = ScriptedGame([(status(2), QUIET), (busy, QUIET), (status(4), QUIET)])
        r = g.finish_turn(skip_quiet_turns=5)
        self.assertEqual(r["turn"], 3)
        self.assertEqual(r["turns_skipped"], 1)
        self.assertEqual(r["woke_because"], ["todo.units"])

    def test_combat_and_leaders_wake(self):
        fight = {"events": [{"kind": "combat", "data": {}}], "notifications": []}
        g = ScriptedGame([(status(2), fight), (status(3), QUIET)])
        r = g.finish_turn(skip_quiet_turns=5)
        self.assertEqual(r["turn"], 2)
        self.assertEqual(r["woke_because"], ["event:combat"])
        talk = {"events": [{"kind": "leader_message", "data": {}}], "notifications": []}
        g = ScriptedGame([(status(2), talk), (status(3), QUIET)])
        self.assertEqual(g.finish_turn(skip_quiet_turns=5)["woke_because"], ["event:leader_message"])

    def test_a_banner_wakes_only_when_it_reads_like_trouble(self):
        """Live 2026-09-27 (Grok): "Work has now begun on a Colosseum." and "You have discovered Trapping!"
        (GameplayAlertMessage banners, event kind alert) ended 15 of 50 quiet runs. A banner naming the enemy,
        or carrying the hostiles the runtime found beside the named city, still wakes."""
        dull = {"events": [{"kind": "alert", "data": {"text": "Work has now begun on a Colosseum."}},
                           {"kind": "alert", "data": {"text": "You have discovered Trapping!"}}], "notifications": []}
        g = ScriptedGame([(status(2), dull), (status(3), QUIET)])
        self.assertEqual(g.finish_turn(skip_quiet_turns=1)["turn"], 3, "a dull banner is quiet")
        seen = {"events": [{"kind": "alert", "data": {"text": "The enemy has been spotted near Karakorum!"}}],
                "notifications": []}
        g = ScriptedGame([(status(2), seen), (status(3), QUIET)])
        r = g.finish_turn(skip_quiet_turns=5)
        self.assertEqual(r["turn"], 2)
        self.assertEqual(r["woke_because"], ["alert:The enemy has been spotted near Karakorum!"])
        located = {"events": [{"kind": "alert", "data": {"text": "Something is afoot.", "hostiles": [{"id": 9}]}}],
                   "notifications": []}
        g = ScriptedGame([(status(2), located), (status(3), QUIET)])
        self.assertEqual(g.finish_turn(skip_quiet_turns=5)["turn"], 2)

    def test_notification_words_wake_including_my_own(self):
        n = {"events": [], "notifications": [{"summary": "Machinery researched", "text": "You have discovered Machinery"}]}
        g = ScriptedGame([(status(2), n), (status(3), QUIET)])
        self.assertEqual(g.finish_turn(skip_quiet_turns=1)["turn"], 3, "a plain tech notice is quiet")
        g = ScriptedGame([(status(2), n), (status(3), QUIET)])
        r = g.finish_turn(skip_quiet_turns=5, wake_on=["machinery"])
        self.assertEqual(r["turn"], 2)
        self.assertTrue(r["woke_because"][0].startswith("notification:Machinery"))
        war = {"events": [{"kind": "notification", "data": {"summary": "War!", "text": "Askia has declared war on you!"}}],
               "notifications": []}
        g = ScriptedGame([(status(2), war), (status(3), QUIET)])
        self.assertEqual(g.finish_turn(skip_quiet_turns=5)["turn"], 2)

    def test_blockers_popups_and_expiring_allies_wake(self):
        for extra in ({"blocking": "ENDTURN_BLOCKING_PRODUCTION"}, {"pending_popups": [{"name": "X"}]},
                      {"expiring_city_states": [{"name": "Geneva"}]}, {"game_over": True}):
            ts = status(2, **extra)
            g = ScriptedGame([(ts, QUIET), (status(3), QUIET)])
            self.assertEqual(g.finish_turn(skip_quiet_turns=5)["turn"], 2, extra)

    def test_discussion_pending_returns_at_once(self):
        ts = status(2, discussion_pending=True, discussion={"buttons": [1]})
        g = ScriptedGame([(ts, QUIET), (status(3), QUIET)])
        r = g.finish_turn(skip_quiet_turns=5)
        self.assertTrue(r["discussion_pending"])
        self.assertEqual(r["turn"], 2)
        self.assertEqual(r["woke_because"], ["discussion_pending"])

    def test_on_wait_is_forwarded(self):
        seen = []
        g = ScriptedGame([(status(2), QUIET), (status(3), QUIET)])
        g.finish_turn(skip_quiet_turns=1, on_wait=lambda e, ts: seen.append(ts))
        self.assertTrue(any("skipping_quiet_turn" in ts for ts in seen))
        self.assertTrue(any(ts.get("active_player") == 3 for ts in seen))


class GameOverTests(unittest.TestCase):
    """Live 2026-10-04 t253 (the Mongolia replay): Russia won a Science Victory in the AI round. The game went to
    GAMESTATE_OVER, my_turn never came back, the wait ran to its timeout and finish_turn answered timed_out with
    "call finish_turn again". The over state is the answer, with the winner from the game's own notification."""

    WON = {"text": "Catherine has won the game through a Science Victory!", "summary": "Catherine has Won!", "turn": 253}

    def test_finish_turn_names_the_win_and_stops(self):
        over = status(253, my_turn=False, game_over=True)
        digest = {"events": [{"kind": "alert", "data": {"text": "Catherine has completed SS Stasis Chamber!"}}],
                  "notifications": [self.WON]}
        g = ScriptedGame([(over, digest)])
        g.notification_log = lambda limit=40, include_dismissed=True, pid=None: {"notifications": [self.WON]}
        r = g.finish_turn(skip_quiet_turns=3)
        self.assertEqual(g.log, ["end", "wait", "digest"])
        self.assertTrue(r["ok"] and r["ended"] and r["game_over"])
        self.assertNotIn("timed_out", r)
        self.assertEqual(r["woke_because"], ["game_over"])
        self.assertEqual(r["turns_skipped"], 0)
        self.assertEqual(r["victory"], {"winner": "Catherine", "type": "science", "text": self.WON["text"], "turn": 253})
        self.assertIn("exit_to_main_menu", r["hint"])
        self.assertTrue(r["hint"].startswith("Catherine has won"))

    def test_without_the_notification_only_the_state_says_so(self):
        g = ScriptedGame([(status(253, my_turn=False, game_over=True), QUIET)])
        g.notification_log = lambda limit=40, include_dismissed=True, pid=None: {"notifications": []}
        r = g.finish_turn()
        self.assertTrue(r["game_over"])
        self.assertNotIn("victory", r)
        self.assertIn("the game is over", r["hint"])

    def test_a_dead_seat_without_a_winner_is_told_its_defeat(self):
        """Live England t226: London, the last city, fell to the Ottomans; the reply said only game_over."""
        over = status(226, my_turn=False, game_over=True, alive=False)
        digest = {"events": [{"kind": "city_captured", "seq": 122, "turn": 226,
                              "data": {"name": "London", "x": 60, "y": 40, "by": 7, "owner": 7, "former_city_id": 8192}}],
                  "notifications": []}
        g = ScriptedGame([(over, digest)])
        g.notification_log = lambda limit=40, include_dismissed=True, pid=None: {"notifications": []}
        r = g.finish_turn()
        self.assertTrue(r["game_over"])
        self.assertNotIn("victory", r)
        self.assertEqual(r["defeat"]["last_city"], {"name": "London", "x": 60, "y": 40, "by": 7})
        self.assertIn("London, your last city, was captured", r["hint"])
        self.assertIn("exit_to_main_menu", r["hint"])
        g = ScriptedGame([(status(253, my_turn=False, game_over=True, alive=True), QUIET)])
        g.notification_log = lambda limit=40, include_dismissed=True, pid=None: {"notifications": []}
        self.assertNotIn("defeat", g.finish_turn(), "alive and no winner read: nothing is claimed")

    def test_the_wait_returns_at_once_on_the_over_state(self):
        class G(Game):
            def __init__(self):
                self.seat = 0
                self.n = 0

                class C:
                    def ping(_):
                        return {"connected": True}
                self.c = C()

            def turn_state(self, pid=None):
                self.n += 1
                return status(253, my_turn=False, active_player=1, game_over=True)

        g = G()
        ts = g.wait_for_my_turn(timeout=5, poll=0.01)
        self.assertTrue(ts["game_over"])
        self.assertFalse(ts["my_turn"])
        self.assertEqual(g.n, 1)


class WaitProgressTests(unittest.TestCase):
    def test_wait_loop_calls_on_wait_while_waiting(self):
        class G(Game):
            def __init__(self):
                self.seat = 0
                self.n = 0

                class C:
                    def ping(_):
                        return {"connected": True}
                self.c = C()

            def turn_state(self, pid=None):
                self.n += 1
                return status(5, my_turn=self.n > 3, active_player=0 if self.n > 3 else 2)

            def dismiss_pending_popups(self, ts=None):
                return False

            def q(self, code, timeout=None):
                return []

            def expiring_city_states(self):
                return []

        seen = []
        g = G()
        ts = g.wait_for_my_turn(timeout=5, poll=0.01, on_wait=lambda e, ts: seen.append(e))
        self.assertTrue(ts["my_turn"])
        self.assertGreaterEqual(len(seen), 3)
        self.assertTrue(all(isinstance(e, float) for e in seen))

    def test_the_hand_off_is_pressed_before_a_leader_discussion_stops_the_wait(self):
        # Live 2026-09-27 (Codex, t55): an AI trade offer came up together with the seat's own Continue
        # screen. The poll returned on the discussion before the press, the gate named hand_off_screen and
        # its clear_with (this wait) did the same again: nothing an agent could call moved the game.
        class G(Game):
            def __init__(self):
                self.seat = 0
                self.log = []
                self.hand_off = True

                class C:
                    def ping(_):
                        return {"connected": True}
                self.c = C()

            def turn_state(self, pid=None):
                return status(55, hotseat=True, paused=self.hand_off, hand_off_pending=self.hand_off,
                              discussion_pending=True)

            def dismiss_pending_popups(self, ts=None):
                return False

            def dismiss_player_change(self):
                self.log.append("press")
                self.hand_off = False
                return {"ok": True}

            def discussion(self, pid=None):
                self.log.append("discussion")
                return {"pending": True, "screen": "trade", "buttons": [], "player": 3}

        g = G()
        ts = g.wait_for_my_turn(timeout=5, poll=0.01)
        self.assertEqual(g.log, ["press", "discussion"], "Continue is pressed before the leader screen is read")
        self.assertTrue(ts["discussion_pending"])
        self.assertFalse(ts["hand_off_pending"])
        self.assertFalse(ts["paused"])

    def test_a_busy_game_is_polled_on_and_a_lost_game_is_not(self):
        # Live 2026-09-27: "no Lua state named 'InGame'; have []" ended three Codex cycles, each in the
        # finish_turn that waited across the AI turns; the next call found the game fine.
        from harness.client import TunerConnectionLost, TunerdError

        class G(Game):
            def __init__(self, errors):
                self.seat = 0
                self.n = 0
                self.errors = list(errors)

                class C:
                    def ping(_):
                        return {"connected": True}
                self.c = C()

            def turn_state(self, pid=None):
                self.n += 1
                if self.errors:
                    raise self.errors.pop(0)
                return status(7)

            def dismiss_pending_popups(self, ts=None):
                return False

            def q(self, code, timeout=None):
                return []

            def expiring_city_states(self):
                return []

        g = G([TunerdError("\"no Lua state named 'InGame'; have []\""),
               TunerdError("timeout waiting for completion of command in state 5: 'return H.turn_state()'")])
        ts = g.wait_for_my_turn(timeout=5, poll=0.01)
        self.assertTrue(ts["my_turn"])
        self.assertEqual(g.n, 4, "two busy answers, then the turn, then the look for a late leader")
        with self.assertRaises(TunerConnectionLost):
            G([TunerConnectionLost("tunerd lost its connection")]).wait_for_my_turn(timeout=5, poll=0.01)
        with self.assertRaises(TunerdError):
            G([TunerdError("game tuner not reachable: [Errno 2] No such file or directory")]).wait_for_my_turn(timeout=5, poll=0.01)
        with self.assertRaises(TimeoutError):
            G([TunerdError("have []")] * 50).wait_for_my_turn(timeout=0.2, poll=0.01)


class LateLeaderTests(unittest.TestCase):
    """Mongolia t126/t127 (2026-09-27): wait_for_my_turn answered discussion_pending=false and the caller's
    next order was refused "diplomatic decision pending" -- the AI's approach landed a moment after the turn
    became ours. The wait takes one more look before handing the turn back."""

    class G(Game):
        _LATE_DISCUSSION_SETTLE = 0.0

        def __init__(self, late, buttons):
            self.seat = 0
            self.n = 0
            self.late = late
            self.buttons = buttons
            self.log = []

            class C:
                def ping(_):
                    return {"connected": True}
            self.c = C()

        def turn_state(self, pid=None):
            self.n += 1
            return status(9, discussion_pending=self.late and self.n >= 2)

        def dismiss_pending_popups(self, ts=None):
            return False

        def q(self, code, timeout=None):
            return []

        def expiring_city_states(self):
            return [{"civ": "Jerusalem", "turns_left": 1}]

        def discussion(self, pid=None):
            self.log.append("discussion")
            return {"pending": True, "screen": "discussion", "buttons": self.buttons, "can_go_back": not self.buttons,
                    "player": 7}

        def dismiss_discussion(self):
            self.log.append("dismiss")
            self.late = False
            return {"ok": True}

    def test_a_late_offer_comes_back_as_the_waits_answer(self):
        g = self.G(late=True, buttons=[{"id": 1, "text": "Yes"}])
        ts = g.wait_for_my_turn(timeout=5, poll=0.01)
        self.assertTrue(ts["discussion_pending"])
        self.assertEqual(ts["discussion"]["player"], 7)
        self.assertEqual(ts["expiring_city_states"][0]["civ"], "Jerusalem", "what the arrival read rides along")
        self.assertEqual(g.log, ["discussion"])

    def test_a_late_remark_is_dismissed_and_the_turn_is_mine(self):
        g = self.G(late=True, buttons=[])
        ts = g.wait_for_my_turn(timeout=5, poll=0.01)
        self.assertFalse(ts.get("discussion_pending"))
        self.assertTrue(ts["my_turn"])
        self.assertEqual(g.log, ["discussion", "dismiss"])

    def test_no_late_leader_costs_one_read(self):
        g = self.G(late=False, buttons=[])
        ts = g.wait_for_my_turn(timeout=5, poll=0.01)
        self.assertTrue(ts["my_turn"])
        self.assertEqual((g.n, g.log), (2, []))


class ProgressReporterTests(unittest.TestCase):
    def test_reporter_throttles_and_survives_a_dead_context(self):
        from harness import mcp_server as m
        self.assertIsNone(m.progress_reporter(None))
        calls = []

        class Ctx:
            async def report_progress(self, progress, total=None, message=None):
                calls.append((progress, message))

        import anyio

        async def run():
            def work():
                on_wait = m.progress_reporter(Ctx())
                for t in (0.0, 1.0, 2.0, 5.5, 6.0, 11.0):
                    on_wait(t, {"turn": 9, "active_player": 2})
                on_wait(0.0, {"skipping_quiet_turn": 9})
            await anyio.to_thread.run_sync(work)
        anyio.run(run)
        self.assertEqual([c[0] for c in calls], [1.0, 2.0, 3.0, 4.0])
        self.assertIn("waiting for my turn", calls[0][1])
        self.assertIn("quiet", calls[-1][1])


if __name__ == "__main__":
    unittest.main()
