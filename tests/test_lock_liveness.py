"""The wait tools hold the per-socket operation lock per poll, never across a sleep.

Two MCP servers (one per seat) share one tuner socket in a two-agent hotseat game; each takes the same
flock for every operation. Until 2026-09-26 `wait_for_my_turn` and `finish_turn` held it for their whole
wait, so the inactive seat's 300 s finish_turn starved the active seat's every call (docs/NOTES.md, the
Codex/Grok game). These tests pin the liveness property at three layers:

- Game: while a wait polls, a contender acquires the lock between polls; each poll itself runs locked.
- action_lock: a contender's refusal across processes says only what a human at the hand-off screen
  would know: another seat is acting (no tool, no timing), or which of its own earlier calls holds it.
- MCP: through the real server over the memory transport, the lock is free during a wait tool's wait
  and held during an ordinary tool.
"""
import fcntl
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

import anyio
from mcp import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from harness import mcp_server as m
from harness.action_lock import action_lock, lock_path
from harness.game import Game

SOCK = "/tmp/civ5-test-lock-liveness.sock"


def _held(sock: str) -> bool:
    """Is the flock for `sock` held right now (by anyone, this process included)?"""
    with lock_path(sock).open("a+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(f, fcntl.LOCK_UN)
        return False


class _Client:
    def ping(self):
        return {"connected": True}


def _waiting_game(sock: str, polls_until_mine: int, seen: list) -> Game:
    """A Game whose seat becomes active after `polls_until_mine` turn_state reads. Every read records
    whether the lock was held at that moment."""
    g = Game.__new__(Game)
    g.c = _Client()
    g.seat = 1
    g.lock = lambda: action_lock(sock, timeout=2, seat=1, tool="wait poll")
    n = {"reads": 0}

    def turn_state(pid=None):
        n["reads"] += 1
        seen.append(_held(sock))
        mine = n["reads"] > polls_until_mine
        return {"turn": 3, "active_player": 1 if mine else 0, "my_turn": mine, "processing": False,
                "paused": False, "hotseat": False, "blocking_name": "NO_ENDTURN_BLOCKING_TYPE",
                "todo": {}, "pending_popups": [], "discussion_pending": False, "tech_popup_pending": False}

    g.turn_state = turn_state
    g.dismiss_pending_popups = lambda ts=None: False
    g.q = lambda code, timeout=None: []
    g.expiring_city_states = lambda: []
    g.end_turn = lambda autosave=True: {"ok": True}
    g.turn_digest = lambda: {"events": [], "notifications": []}
    return g


def _contend(sock: str, after: float, result: dict, tool: str = "turn_status") -> threading.Thread:
    """Another seat's server: `after` seconds in, take the lock for one operation and record how long
    the acquire took (or the refusal)."""
    def run():
        time.sleep(after)
        t0 = time.monotonic()
        try:
            with action_lock(sock, timeout=1.5, seat=0, tool=tool):
                result["acquired_after"] = time.monotonic() - t0
        except TimeoutError as e:
            result["refused"] = str(e)
    t = threading.Thread(target=run)
    t.start()
    return t


class GameWaitReleasesBetweenPolls(unittest.TestCase):
    def setUp(self):
        lock_path(SOCK).unlink(missing_ok=True)

    def test_wait_for_my_turn_lets_a_contender_in_and_locks_each_poll(self):
        seen: list = []
        g = _waiting_game(SOCK, polls_until_mine=6, seen=seen)
        got: dict = {}
        c = _contend(SOCK, after=0.35, result=got)
        r = g.wait_for_my_turn(timeout=10, poll=0.25)
        c.join()
        self.assertTrue(r["my_turn"])
        self.assertIn("acquired_after", got, got)
        self.assertLess(got["acquired_after"], 1.0, "the contender should get in between polls")
        self.assertTrue(seen and all(seen), "every turn_state read must happen under the lock")
        self.assertFalse(_held(SOCK), "nothing holds the lock once the wait returns")

    def test_finish_turn_releases_between_end_turn_and_polls(self):
        seen: list = []
        g = _waiting_game(SOCK, polls_until_mine=0, seen=seen)
        # first read: mine -> end_turn; then not mine for a few polls; then mine again
        reads = {"n": 0}
        base = g.turn_state

        def turn_state(pid=None):
            reads["n"] += 1
            ts = base(pid)
            mine = reads["n"] == 1 or reads["n"] > 3
            ts.update({"active_player": 1 if mine else 0, "my_turn": mine})
            return ts

        g.turn_state = turn_state
        got: dict = {}
        c = _contend(SOCK, after=0.35, result=got, tool="units")
        r = g.finish_turn(timeout=10)
        c.join()
        self.assertTrue(r["ok"] and r["ended"], r)
        self.assertIn("acquired_after", got, got)
        self.assertLess(got["acquired_after"], 1.0)
        self.assertTrue(all(seen))

    def test_a_poll_is_serialized_against_an_action_in_flight(self):
        """The other direction: while an action holds the lock, the wait's poll waits for it; an action that
        outlasts the whole wait ends it at its own deadline, naming the busy lock the way a refusal would."""
        seen: list = []
        g = _waiting_game(SOCK, polls_until_mine=0, seen=seen)
        with action_lock(SOCK, seat=0, tool="move_unit"):
            with self.assertRaises(TimeoutError) as cm:
                g.wait_for_my_turn(timeout=5, poll=0.1)
        self.assertIn("timed out waiting for our turn", str(cm.exception))
        self.assertIn("not your turn while another seat acts", str(cm.exception))
        self.assertNotIn("move_unit", str(cm.exception))
        self.assertEqual(seen, [], "no read happens while another operation holds the lock")


    def test_a_long_action_skips_polls_not_the_wait(self):
        """Another seat's operation that outlasts one poll's acquire timeout (2 s here, 10 s live) costs that
        poll, not the wait: live, seat 1's end_turn held the lock past 10 s and a 600 s finish_turn came back
        timed_out after 24 s (Venice/Mongolia t50, 2026-09-27)."""
        seen: list = []
        g = _waiting_game(SOCK, polls_until_mine=0, seen=seen)
        held = threading.Event()

        def long_action():
            with action_lock(SOCK, seat=0, tool="end_turn"):
                held.set()
                time.sleep(3.0)
        t = threading.Thread(target=long_action)
        t.start()
        held.wait()
        r = g.wait_for_my_turn(timeout=10, poll=0.1)
        t.join()
        self.assertTrue(r["my_turn"])
        self.assertTrue(seen and all(seen))


class RefusalSaysOnlyWhatTheHandoffScreenWould(unittest.TestCase):
    def test_another_seats_call_is_just_not_your_turn_and_your_own_is_named(self):
        lock_path(SOCK).unlink(missing_ok=True)
        child = subprocess.Popen(
            [sys.executable, "-c",
             "import sys, time; sys.path.insert(0, %r)\n"
             "from harness.action_lock import action_lock\n"
             "with action_lock(%r, seat=1, tool='finish_turn'):\n"
             "    print('held', flush=True); time.sleep(3)" % (os.path.dirname(os.path.dirname(__file__)), SOCK)],
            stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "held")
            time.sleep(1.1)
            # seat 0 asking: another seat holds it -> no tool name, no pid, no timing
            with self.assertRaises(TimeoutError) as cm:
                with action_lock(SOCK, timeout=0.3, seat=0, tool="turn_status"):
                    pass
            msg = str(cm.exception)
            self.assertIn("another game operation is running", msg)
            self.assertIn("not your turn while another seat acts", msg)
            for leak in ("your own", "held it", str(child.pid), " s)"):
                self.assertNotIn(leak, msg)
            # seat 1 asking: its own earlier call -> named, with pid and age
            with self.assertRaises(TimeoutError) as cm:
                with action_lock(SOCK, timeout=0.3, seat=1, tool="turn_status"):
                    pass
            msg = str(cm.exception)
            self.assertIn(f"your own finish_turn, pid {child.pid}, has held it for ", msg)
            age = int(msg.rsplit("for ", 1)[1].split(" ")[0])
            self.assertGreaterEqual(age, 1)
        finally:
            child.wait(timeout=10)
        # released: the next acquire is immediate and rewrites the record
        with action_lock(SOCK, timeout=0.3, seat=0, tool="units"):
            rec = json.loads(lock_path(SOCK).read_text())
            self.assertEqual((rec["seat"], rec["tool"]), (0, "units"))


class FakeGame:
    seat = 1

    def __init__(self, sock):
        self.sock = sock
        self.probe: dict = {}
        self.lock = lambda: action_lock(sock, timeout=2, seat=1, tool="wait poll")

    def has_state(self, name):
        return True

    def turn_state(self, pid=None):
        self.probe["turn_status_saw_lock_held"] = _held(self.sock)
        return {"turn": 7, "active_player": 1, "my_turn": True, "processing": False, "paused": False,
                "blocking_name": "NO_ENDTURN_BLOCKING_TYPE", "todo": {}, "pending_popups": []}

    def expiring_city_states(self):
        return []

    def wait_for_my_turn(self, timeout=90, poll=1.0, on_wait=None):
        # the real loop sleeps here with the lock released; a contender must be able to take it
        self.probe["wait_saw_lock_held"] = _held(self.sock)
        try:
            with action_lock(self.sock, timeout=0.3, seat=0, tool="turn_status"):
                self.probe["contender_got_in"] = True
        except TimeoutError as e:
            self.probe["contender_got_in"] = str(e)
        with self.lock():
            self.probe["poll_holds_lock"] = _held(self.sock)
        return self.turn_state()

    def finish_turn(self, autosave=True, timeout=600, on_wait=None, skip_quiet_turns=0, wake_on=None, force=False):
        self.probe["finish_saw_lock_held"] = _held(self.sock)
        return {"ok": True, "turn": 8, "status": {}, "digest": {}, "turns_skipped": 0, "woke_because": ["turn_started"]}

    def notebook(self):
        class NB:
            def latest(self, limit=8):
                return []
        return NB()


async def _call(tool, args):
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        async with anyio.create_task_group() as tg:
            srv = m.mcp._lowlevel_server

            async def run_server():
                await srv.run(server_streams[0], server_streams[1], srv.create_initialization_options())

            tg.start_soon(run_server)
            async with ClientSession(client_streams[0], client_streams[1]) as s:
                await s.initialize()
                res = await s.call_tool(tool, args)
                out = json.loads(res.content[0].text)
            tg.cancel_scope.cancel()
    return out


class McpWaitToolsDoNotHoldTheLock(unittest.TestCase):
    def setUp(self):
        lock_path(SOCK).unlink(missing_ok=True)
        self.fake = FakeGame(SOCK)
        self.patches = [mock.patch.object(m, "game", lambda: self.fake),
                        mock.patch.dict(os.environ, {"CIV5_TUNERD_SOCK": SOCK})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_wait_for_my_turn_runs_unlocked_and_polls_locked(self):
        out = anyio.run(_call, "wait_for_my_turn", {"timeout_seconds": 30})
        self.assertTrue(out["my_turn"])
        self.assertFalse(self.fake.probe["wait_saw_lock_held"])
        self.assertIs(self.fake.probe["contender_got_in"], True, self.fake.probe)
        self.assertTrue(self.fake.probe["poll_holds_lock"])

    def test_finish_turn_runs_unlocked(self):
        out = anyio.run(_call, "finish_turn", {})
        self.assertTrue(out["ok"])
        self.assertFalse(self.fake.probe["finish_saw_lock_held"])

    def test_an_ordinary_tool_still_runs_under_the_lock(self):
        out = anyio.run(_call, "turn_status", {})
        self.assertEqual(out["turn"], 7)
        self.assertTrue(self.fake.probe["turn_status_saw_lock_held"])


if __name__ == "__main__":
    unittest.main()
