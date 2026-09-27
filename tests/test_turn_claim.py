"""One client owns a seat's turn between calls (GitLab #41; harness/turn_claim.py).

Three layers, no game:

- turn_claim: the file, the refusal, force, the idle expiry, a dead holder, a new turn; two real processes.
- Game: finish_turn / end_turn refuse under another client's claim, the holder's quiet-turn run claims
  each turn it ends, a second client acting mid-run stops the run, a pinned other seat is still refused.
- MCP guarded(): a mutating tool from the non-holder is refused like finish_turn, reads still answer and
  show the claim, `do(force=true)` takes over.
"""
import json
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

from harness import mcp_server as m
from harness.game import Game
from harness.turn_claim import IDLE_SECONDS, ClaimRefused, claim_path, claim_status, claim_turn

SOCK = "/tmp/civ5-test-turn-claim.sock"
ROOT = os.path.dirname(os.path.dirname(__file__))


def _other_process() -> subprocess.Popen:
    """A live process that is not this one: its pid stands for the other client."""
    return subprocess.Popen(["sleep", "30"])


class ClaimFileTests(unittest.TestCase):
    def setUp(self):
        claim_path(SOCK, 1).unlink(missing_ok=True)
        self.other = _other_process()
        self.addCleanup(self.other.kill)

    def test_first_order_claims_and_another_pid_is_refused_with_holder_and_timings(self):
        t0 = 1_000.0
        claim_turn(SOCK, 1, 12, "unit_mission", pid=self.other.pid, now=t0)
        with self.assertRaises(ClaimRefused) as cm:
            claim_turn(SOCK, 1, 12, "finish_turn", now=t0 + 40)
        info = cm.exception.info
        self.assertEqual(info["holder_pid"], self.other.pid)
        self.assertFalse(info["mine"])
        self.assertEqual((info["held_for_s"], info["idle_for_s"], info["expires_in_s"]), (40, 40, IDLE_SECONDS - 40))
        self.assertEqual((info["seat"], info["turn"], info["refused_tool"]), (1, 12, "finish_turn"))
        msg = str(cm.exception)
        self.assertIn(f"pid {self.other.pid}", msg)
        self.assertIn("force=true", msg)
        self.assertIn(f"{IDLE_SECONDS - 40} s after", msg)
        # the file is the other client's still
        self.assertEqual(json.loads(claim_path(SOCK, 1).read_text())["pid"], self.other.pid)

    def test_force_takes_the_turn_over(self):
        claim_turn(SOCK, 1, 12, "unit_mission", pid=self.other.pid, now=1_000.0)
        c = claim_turn(SOCK, 1, 12, "end_turn", force=True, now=1_010.0)
        self.assertTrue(c["taken_over"])
        self.assertEqual(c["pid"], os.getpid())
        # and the displaced client is now the one refused
        with self.assertRaises(ClaimRefused):
            claim_turn(SOCK, 1, 12, "unit_mission", pid=self.other.pid, now=1_011.0)

    def test_claim_expires_after_the_idle_interval_without_an_order(self):
        claim_turn(SOCK, 1, 12, "unit_mission", pid=self.other.pid, now=1_000.0)
        claim_turn(SOCK, 1, 12, "move_unit", pid=self.other.pid, now=1_100.0)   # keeps it alive
        with self.assertRaises(ClaimRefused):
            claim_turn(SOCK, 1, 12, "finish_turn", now=1_100.0 + IDLE_SECONDS - 1)
        c = claim_turn(SOCK, 1, 12, "finish_turn", now=1_100.0 + IDLE_SECONDS)
        self.assertEqual(c["pid"], os.getpid())
        self.assertNotIn("taken_over", c)

    def test_a_dead_holder_frees_the_turn_at_once(self):
        dead = subprocess.Popen(["true"])
        dead.wait(timeout=10)
        claim_turn(SOCK, 1, 12, "unit_mission", pid=dead.pid, now=1_000.0)
        self.assertIsNone(claim_status(SOCK, 1, 12, now=1_001.0))
        c = claim_turn(SOCK, 1, 12, "finish_turn", now=1_001.0)
        self.assertEqual(c["pid"], os.getpid())

    def test_a_new_turn_is_nobodys(self):
        claim_turn(SOCK, 1, 12, "unit_mission", pid=self.other.pid, now=1_000.0)
        self.assertIsNone(claim_status(SOCK, 1, 13, now=1_001.0))
        c = claim_turn(SOCK, 1, 13, "set_production", now=1_001.0)
        self.assertEqual(c["pid"], os.getpid())

    def test_the_holders_own_orders_refresh_last_and_keep_since(self):
        claim_turn(SOCK, 1, 12, "unit_mission", now=1_000.0)
        c = claim_turn(SOCK, 1, 12, "set_research", now=1_050.0)
        self.assertEqual((c["since"], c["last"], c["tool"]), (1_000.0, 1_050.0, "set_research"))
        s = claim_status(SOCK, 1, 12, now=1_060.0)
        self.assertTrue(s["mine"])
        self.assertEqual((s["held_for_s"], s["idle_for_s"]), (60, 10))

    def test_seats_have_separate_claims(self):
        claim_path(SOCK, 0).unlink(missing_ok=True)
        claim_turn(SOCK, 0, 12, "unit_mission", pid=self.other.pid, now=1_000.0)
        c = claim_turn(SOCK, 1, 12, "unit_mission", now=1_000.0)   # seat 1 is untouched by seat 0's claim
        self.assertEqual(c["pid"], os.getpid())

    def test_two_processes_then_the_holder_crashes(self):
        child = subprocess.Popen(
            [sys.executable, "-c",
             "import sys, time; sys.path.insert(0, %r)\n"
             "from harness.turn_claim import claim_turn\n"
             "claim_turn(%r, 1, 12, 'unit_mission')\n"
             "print('claimed', flush=True); time.sleep(30)" % (ROOT, SOCK)],
            stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "claimed")
            with self.assertRaises(ClaimRefused) as cm:
                claim_turn(SOCK, 1, 12, "finish_turn")
            self.assertEqual(cm.exception.info["holder_pid"], child.pid)
        finally:
            child.kill()
            child.wait(timeout=10)
        # the holder is gone: no idle wait, the seat is free
        c = claim_turn(SOCK, 1, 12, "finish_turn")
        self.assertEqual(c["pid"], os.getpid())


# ------------------------------------------------------------------ Game layer
def status(turn, my_turn=True, active_player=1, **extra):
    ts = {"turn": turn, "my_turn": my_turn, "active_player": active_player, "processing": False, "paused": False,
          "blocking_name": "NO_ENDTURN_BLOCKING_TYPE", "pending_popups": [], "alive": True, "hotseat": True,
          "hand_off_pending": False,
          "todo": {"units": [], "cities": [], "promotions": [], "research_unset": False}}
    ts.update(extra)
    return ts


QUIET = {"events": [{"kind": "turn_start", "data": {}}], "notifications": []}


class ScriptedGame(Game):
    """Seat 1 with the real claim. `turns` are the statuses wait_for_my_turn hands back, one per end.
    `on_wait_return(turn)` runs when a new turn arrives: the place a second client acts."""

    def __init__(self, turns, on_wait_return=None):
        self.seat = 1
        self.turns = list(turns)
        self.i = 0
        self.log = []
        self.first = status(1)
        self.on_wait_return = on_wait_return
        self.claim = lambda turn, tool, force=False: claim_turn(SOCK, 1, turn, tool, force=force)

    def turn_state(self, pid=None):
        if self.i == 0 and not self.log:
            return self.first
        if self.log and self.log[-1] == "end":
            return status(self.turns[min(self.i, len(self.turns)) - 1], my_turn=False, active_player=0)
        return status(self.turns[self.i - 1])

    def dismiss_pending_popups(self, ts=None):
        return False

    def _end_turn_send(self, autosave_lua):
        self.log.append("end")
        return {"ok": True}

    def wait_for_my_turn(self, timeout=3600, poll=1.0, on_wait=None):
        self.log.append("wait")
        self.i += 1
        if self.on_wait_return:
            self.on_wait_return(self.turns[self.i - 1])
        return status(self.turns[self.i - 1])

    def turn_digest(self):
        return dict(QUIET)


class GameClaimTests(unittest.TestCase):
    def setUp(self):
        claim_path(SOCK, 1).unlink(missing_ok=True)
        self.other = _other_process()
        self.addCleanup(self.other.kill)

    def test_finish_turn_from_the_non_holder_is_refused_and_names_the_holder(self):
        claim_turn(SOCK, 1, 1, "unit_mission", pid=self.other.pid)
        g = ScriptedGame([2])
        r = g.finish_turn()
        self.assertFalse(r["ok"])
        self.assertFalse(r["ended"])
        self.assertEqual(r["turn_claim"]["holder_pid"], self.other.pid)
        self.assertEqual(r["turn"], 1)
        self.assertNotIn("end", g.log)

    def test_end_turn_from_the_non_holder_is_refused_the_same_way(self):
        claim_turn(SOCK, 1, 1, "unit_mission", pid=self.other.pid)
        g = ScriptedGame([2])
        r = g.end_turn()
        self.assertFalse(r["ok"])
        self.assertEqual(r["turn_claim"]["holder_pid"], self.other.pid)
        self.assertNotIn("end", g.log)

    def test_force_ends_the_turn(self):
        claim_turn(SOCK, 1, 1, "unit_mission", pid=self.other.pid)
        g = ScriptedGame([2])
        r = g.finish_turn(force=True)
        self.assertTrue(r["ok"] and r["ended"])
        self.assertEqual(g.log, ["end", "wait"])
        self.assertEqual(json.loads(claim_path(SOCK, 1).read_text())["pid"], os.getpid())

    def test_after_the_idle_interval_no_force_is_needed(self):
        with mock.patch("harness.turn_claim.time.time", return_value=1_000.0):
            claim_turn(SOCK, 1, 1, "unit_mission", pid=self.other.pid)
        g = ScriptedGame([2])
        with mock.patch("harness.turn_claim.time.time", return_value=1_000.0 + IDLE_SECONDS):
            r = g.finish_turn()
        self.assertTrue(r["ok"] and r["ended"])

    def test_the_holders_quiet_turn_run_claims_each_turn_it_ends(self):
        claim_turn(SOCK, 1, 1, "unit_mission")   # this process gave the turn's first order
        g = ScriptedGame([2, 3, 4])
        r = g.finish_turn(skip_quiet_turns=2)
        self.assertTrue(r["ok"])
        self.assertEqual((r["turn"], r["turns_skipped"], r["woke_because"]), (4, 2, ["quiet_turn_budget_used"]))
        self.assertEqual(g.log.count("end"), 3)
        rec = json.loads(claim_path(SOCK, 1).read_text())
        self.assertEqual((rec["pid"], rec["turn"]), (os.getpid(), 3))   # the last turn it ended is claimed
        self.assertEqual(rec["tool"], "end_turn")                        # finish_turn ends through end_turn

    def test_a_second_client_acting_mid_run_stops_the_run_and_hands_the_turn_back(self):
        other = self.other

        def second_client_moves_a_unit(turn):
            if turn == 3:
                claim_turn(SOCK, 1, 3, "move_unit", pid=other.pid)

        g = ScriptedGame([2, 3, 4], on_wait_return=second_client_moves_a_unit)
        r = g.finish_turn(skip_quiet_turns=5)
        self.assertTrue(r["ok"] and r["ended"])
        self.assertEqual((r["turn"], r["turns_skipped"]), (3, 1))
        self.assertEqual(r["woke_because"], ["other_client_holds_turn"])
        self.assertEqual(r["turn_claim"]["holder_pid"], other.pid)
        self.assertEqual(g.log.count("end"), 2)   # turns 1 and 2, never 3

    def test_a_server_pinned_to_the_other_seat_is_refused_claim_or_not(self):
        g = ScriptedGame([2])
        g.seat = 0                                  # plays seat 0 while seat 1 is on screen
        self.assertEqual(g.end_turn()["err"], "this seat is not active")
        self.assertEqual(g.end_turn(force=True)["err"], "this seat is not active")
        r = g.finish_turn(force=True)               # only waits; never ends seat 1's turn
        self.assertNotIn("end", g.log)

    def test_a_game_without_a_claim_is_uncontested(self):
        claim_turn(SOCK, 1, 1, "unit_mission", pid=self.other.pid)
        g = ScriptedGame([2])
        g.claim = None                              # the CLI / HTTP / tests
        self.assertTrue(g.finish_turn()["ok"])


# ------------------------------------------------------------------ MCP layer
class FakeGame:
    seat = 1

    def __init__(self):
        self.orders = []
        self.claim = lambda turn, tool, force=False: claim_turn(SOCK, 1, turn, tool, force=force)

    def has_state(self, name):
        return True

    _END_TURN_CONFIRM_POLLS = 4   # not a Game subclass: end_turn reads these off the instance
    _END_TURN_CONFIRM_SLEEP = 0.0

    def turn_state(self, pid=None):
        if ("end",) in self.orders:
            return {**status(7), "active_player": 0, "my_turn": False}   # the end took: seat 0 is on screen
        return status(7)

    def expiring_city_states(self):
        return []

    def set_research(self, tech):
        self.orders.append(("set_research", tech))
        return {"ok": True, "tech": tech}

    def end_turn(self, autosave=True, force=False):
        return Game.end_turn(self, autosave, force)   # the real one, with its claim check

    def _claim_turn(self, ts, tool, force=False):
        return Game._claim_turn(self, ts, tool, force)

    def dismiss_pending_popups(self, ts=None):
        return False

    def _end_turn_send(self, autosave_lua):
        self.orders.append(("end",))
        return {"ok": True}

    def discussion_pending(self):
        return False


class McpClaimTests(unittest.TestCase):
    def setUp(self):
        claim_path(SOCK, 1).unlink(missing_ok=True)
        self.other = _other_process()
        self.addCleanup(self.other.kill)
        self.fake = FakeGame()
        self.patches = [mock.patch.object(m, "game", lambda: self.fake),
                        mock.patch.object(m, "_game", self.fake),
                        mock.patch.dict(os.environ, {"CIV5_TUNERD_SOCK": SOCK})]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_an_order_from_the_non_holder_is_refused_like_finish_turn(self):
        claim_turn(SOCK, 1, 7, "unit_mission", pid=self.other.pid)
        r = json.loads(m.set_research("TECH_POTTERY"))
        self.assertFalse(r["ok"])
        self.assertEqual(r["turn_claim"]["holder_pid"], self.other.pid)
        self.assertIn("gate", r)
        self.assertEqual(self.fake.orders, [])
        r = json.loads(m.end_turn())
        self.assertFalse(r["ok"])
        self.assertEqual(r["turn_claim"]["holder_pid"], self.other.pid)
        self.assertEqual(self.fake.orders, [])

    def test_reads_still_answer_and_show_the_claim(self):
        claim_turn(SOCK, 1, 7, "unit_mission", pid=self.other.pid)
        r = json.loads(m.turn_status())
        self.assertEqual(r["turn"], 7)
        self.assertEqual(r["turn_claim"]["holder_pid"], self.other.pid)
        self.assertFalse(r["turn_claim"]["mine"])
        self.assertIsNone(r["gate"])

    def test_the_first_order_claims_for_this_process(self):
        self.assertIsNone(claim_status(SOCK, 1, 7))
        r = json.loads(m.set_research("TECH_POTTERY"))
        self.assertTrue(r["ok"])
        s = claim_status(SOCK, 1, 7)
        self.assertTrue(s["mine"])
        self.assertEqual(s["tool"], "set_research")
        self.assertTrue(json.loads(m.turn_status())["turn_claim"]["mine"])
        self.assertTrue(json.loads(m.end_turn())["ok"])

    def test_end_turn_force_takes_over_and_do_force_takes_over(self):
        claim_turn(SOCK, 1, 7, "unit_mission", pid=self.other.pid)
        r = json.loads(m.do([{"tool": "set_research", "args": {"tech": "TECH_MINING"}}]))
        self.assertFalse(r["ok"])
        self.assertEqual(r["results"][0]["result"]["turn_claim"]["holder_pid"], self.other.pid)
        r = json.loads(m.do([{"tool": "set_research", "args": {"tech": "TECH_MINING"}}], force=True))
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.fake.orders, [("set_research", "TECH_MINING")])
        self.assertTrue(claim_status(SOCK, 1, 7)["mine"])
        claim_turn(SOCK, 1, 7, "unit_mission", pid=self.other.pid, force=True)   # they take it back
        self.assertFalse(json.loads(m.end_turn())["ok"])
        self.assertTrue(json.loads(m.end_turn(force=True))["ok"])
        self.assertEqual(self.fake.orders[-1], ("end",))


if __name__ == "__main__":
    unittest.main()
