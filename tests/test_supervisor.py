"""harness/supervisor.py: the decisions behind a relaunch, without a game.

The supervisor's one dangerous action is `subprocess.Popen(launch_cmd)`: a second Civ5 instance on top
of a live one wedges Steam. So every path that must NOT relaunch is pinned here (grace window not over,
process still up, pid unknown, no launch command, restart cap reached), along with the one that must,
and what `rejoin` replays for each saved lobby kind.
"""
import os
import subprocess
import unittest
from unittest import mock

import harness.supervisor as sup
from harness.client import TunerdError


class StopLoop(Exception):
    """Raised by the fake clock to leave main()'s infinite loop."""


class FakeClock:
    """Stands in for the `time` module inside harness.supervisor: sleep advances the clock and stops
    the loop once the scripted iterations are used up."""

    def __init__(self, iterations):
        self.now = 1000.0
        self.remaining = iterations
        self.sleeps = []

    def time(self):
        return self.now

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds
        self.remaining -= 1
        if self.remaining <= 0:
            raise StopLoop

    @staticmethod
    def strftime(fmt):
        return "00:00:00"


class FakeCiv5:
    """Scripted `ping` answers; records that close() ran even when ping raised."""

    script = []
    closed = 0

    def __init__(self, sock):
        self.sock = sock

    def call(self, **req):
        assert req == {"op": "ping"}
        answer = type(self).script.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return {"connected": answer}

    def close(self):
        type(self).closed += 1


class PidAliveTest(unittest.TestCase):
    def test_missing_file_is_unknown(self):
        self.assertIsNone(sup.pid_alive(None))
        self.assertIsNone(sup.pid_alive("/nonexistent/dir/civ5.pid"))

    def test_garbage_file_is_unknown(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".pid", delete=False) as f:
            f.write("not a pid\n")
        try:
            self.assertIsNone(sup.pid_alive(f.name))
        finally:
            os.unlink(f.name)

    def test_own_pid_is_alive(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".pid", delete=False) as f:
            f.write(f"{os.getpid()}\n")
        try:
            self.assertIs(sup.pid_alive(f.name), True)
        finally:
            os.unlink(f.name)

    def test_reaped_pid_is_dead(self):
        import tempfile
        proc = subprocess.Popen(["true"])
        proc.wait()  # reaped: os.kill(pid, 0) now raises ProcessLookupError
        with tempfile.NamedTemporaryFile("w", suffix=".pid", delete=False) as f:
            f.write(f"{proc.pid}\n")
        try:
            self.assertIs(sup.pid_alive(f.name), False)
        finally:
            os.unlink(f.name)


class WaitForMainMenuTest(unittest.TestCase):
    def _game(self, answers):
        g = mock.Mock()
        g.c.wait_state.side_effect = answers
        return g

    def test_retries_until_the_port_answers(self):
        clock = FakeClock(iterations=100)
        g = self._game([TunerdError("connect refused"), OSError("no socket"), 7])
        with mock.patch.object(sup, "time", clock):
            sup.wait_for_main_menu(g, timeout=60, poll=3.0)
        self.assertEqual(g.c.wait_state.call_count, 3)
        self.assertEqual(clock.sleeps, [3.0, 3.0])
        for call in g.c.wait_state.call_args_list:
            self.assertEqual(call.args, ("MainMenu", 5))

    def test_gives_up_after_the_deadline_with_the_last_error(self):
        clock = FakeClock(iterations=100)
        g = self._game(TunerdError("still refused"))
        with mock.patch.object(sup, "time", clock):
            with self.assertRaises(TimeoutError) as cm:
                sup.wait_for_main_menu(g, timeout=10, poll=4.0)
        self.assertIn("still refused", str(cm.exception))
        self.assertIn("10s", str(cm.exception))
        self.assertEqual(g.c.wait_state.call_count, 3)  # t=0, 4, 8; 12 is past the deadline

    def test_other_exceptions_propagate(self):
        g = self._game(RuntimeError("bug"))
        with mock.patch.object(sup, "time", FakeClock(iterations=100)):
            with self.assertRaises(RuntimeError):
                sup.wait_for_main_menu(g, timeout=10)


class RejoinTest(unittest.TestCase):
    def _run(self, state):
        game = mock.Mock()
        game.load_rejoin_state.return_value = state
        logs = []
        with mock.patch.object(sup, "Game", return_value=game) as game_cls, \
                mock.patch.object(sup, "wait_for_main_menu") as wait_menu, \
                mock.patch.object(sup, "log", logs.append):
            sup.rejoin("/run/civ5-llm.sock", 180.0)
        game_cls.assert_called_once_with("/run/civ5-llm.sock")
        wait_menu.assert_called_once_with(game, 180.0)
        return game, logs

    def test_no_saved_state_stops_at_the_menu(self):
        game, logs = self._run(None)
        game.join_lan.assert_not_called()
        game.host_lan.assert_not_called()
        game.note_reconnected.assert_not_called()
        self.assertTrue(any("no saved rejoin state" in m for m in logs))

    def test_lan_join_replays_the_join_and_notes_the_reconnect(self):
        game, logs = self._run({"kind": "lan_join", "host": "10.0.0.5", "nickname": "Claude"})
        game.join_lan.assert_called_once_with("10.0.0.5", nickname="Claude", ready=True, timeout=90)
        game.wait_ingame.assert_called_once_with()
        game.note_reconnected.assert_called_once_with()
        self.assertTrue(any("back in game" in m for m in logs))

    def test_lan_host_reopens_the_lobby_but_does_not_launch(self):
        game, logs = self._run({"kind": "lan_host", "game_name": "Night game", "open_seats": [1, 2],
                                "nickname": "Claude"})
        game.host_lan.assert_called_once_with(game_name="Night game", open_seats=[1, 2], nickname="Claude")
        game.wait_ingame.assert_not_called()
        game.note_reconnected.assert_not_called()

    def test_lan_host_defaults(self):
        game, _ = self._run({"kind": "lan_host"})
        game.host_lan.assert_called_once_with(game_name="LLM Harness", open_seats=None, nickname=None)

    def test_hotseat_has_no_lobby_to_rejoin(self):
        game, logs = self._run({"kind": "hotseat", "human_seats": [0, 1]})
        game.join_lan.assert_not_called()
        game.host_lan.assert_not_called()
        game.wait_ingame.assert_not_called()
        self.assertTrue(any("reload the autosave manually" in m for m in logs))

    def test_unknown_kind_is_left_alone(self):
        game, logs = self._run({"kind": "pitboss"})
        game.join_lan.assert_not_called()
        game.host_lan.assert_not_called()
        self.assertTrue(any("unrecognised rejoin state 'pitboss'" in m for m in logs))


class MainLoopTest(unittest.TestCase):
    """Drive main() with scripted pings; the fake clock ends the loop with StopLoop."""

    def _run(self, pings, *, iterations=None, pid_alive=None, launch_cmd="scripts/launch.sh",
             grace=90.0, interval=15.0, max_restarts=5, rejoin=None):
        FakeCiv5.script = list(pings)
        FakeCiv5.closed = 0
        clock = FakeClock(iterations if iterations is not None else len(pings))
        logs = []
        argv = ["--sock", "/run/civ5-llm.sock", "--name", "civ5-llm", "--check-interval", str(interval),
                "--grace-seconds", str(grace), "--max-restarts", str(max_restarts), "--menu-timeout", "42"]
        if pid_alive is not None:
            argv += ["--pid-file", "logs/civ5-llm.pid"]
        if launch_cmd:
            argv += ["--launch-cmd", launch_cmd]
        with mock.patch.object(sup, "time", clock), \
                mock.patch.object(sup, "Civ5", FakeCiv5), \
                mock.patch.object(sup, "log", logs.append), \
                mock.patch.object(sup, "pid_alive", return_value=pid_alive) as pid_check, \
                mock.patch.object(sup, "rejoin", side_effect=rejoin) as rejoin_call, \
                mock.patch.object(sup.subprocess, "Popen") as popen:
            with self.assertRaises(StopLoop):
                sup.main(argv)
        return {"popen": popen, "rejoin": rejoin_call, "pid_check": pid_check, "logs": logs, "clock": clock}

    # three checks at 15s intervals stay inside a 90s grace window; seven cross it
    def test_connected_never_restarts(self):
        r = self._run([True] * 10, pid_alive=False)
        r["popen"].assert_not_called()
        r["pid_check"].assert_not_called()
        self.assertEqual(FakeCiv5.closed, 10)

    def test_disconnect_inside_the_grace_window_waits(self):
        r = self._run([False] * 6, pid_alive=False)  # 0..75s, never reaches 90s
        r["popen"].assert_not_called()
        r["pid_check"].assert_not_called()

    def test_unreachable_tunerd_counts_as_disconnected(self):
        r = self._run([OSError("no such socket")] * 8, pid_alive=True)
        r["popen"].assert_not_called()
        self.assertGreaterEqual(r["pid_check"].call_count, 1)
        self.assertEqual(FakeCiv5.closed, 8)  # close() ran even though ping raised

    def test_process_still_up_is_not_restarted(self):
        r = self._run([False] * 12, pid_alive=True)
        r["popen"].assert_not_called()
        self.assertGreaterEqual(r["pid_check"].call_count, 5)

    def test_unknown_pid_never_restarts(self):
        r = self._run([False] * 8, pid_alive=None)
        r["popen"].assert_not_called()
        self.assertTrue(any("no pid file to confirm" in m for m in r["logs"]))

    def test_no_launch_cmd_only_observes(self):
        r = self._run([False] * 8, pid_alive=False, launch_cmd=None)
        r["popen"].assert_not_called()
        self.assertTrue(any("no --launch-cmd configured" in m for m in r["logs"]))
        self.assertTrue(any("DISABLED (observing only)" in m for m in r["logs"]))

    def test_confirmed_dead_relaunches_once_and_rejoins(self):
        r = self._run([False] * 8, pid_alive=False)
        r["popen"].assert_called_once_with("scripts/launch.sh", shell=True)
        r["rejoin"].assert_called_once_with("/run/civ5-llm.sock", 42.0)
        self.assertTrue(any("attempt 1/5" in m for m in r["logs"]))

    def test_relaunch_resets_the_grace_window(self):
        # 7 checks confirm death at 90s; the 8th starts a new window and must not relaunch again
        r = self._run([False] * 12, pid_alive=False)
        r["popen"].assert_called_once()
        # after the reset, the second window closes at check 7+7=14 -- beyond the 12 scripted checks

    def test_second_death_after_the_window_relaunches_again(self):
        r = self._run([False] * 15, pid_alive=False)
        self.assertEqual(r["popen"].call_count, 2)
        self.assertTrue(any("attempt 2/5" in m for m in r["logs"]))

    def test_restart_cap_gives_up(self):
        r = self._run([False] * 15, pid_alive=False, max_restarts=1)
        r["popen"].assert_called_once()
        self.assertTrue(any("restart cap (1) reached" in m for m in r["logs"]))

    def test_rejoin_failure_keeps_supervising(self):
        r = self._run([False] * 15, pid_alive=False, rejoin=RuntimeError("menu never came"))
        self.assertEqual(r["popen"].call_count, 2)  # the loop went on to a second confirmed death
        self.assertTrue(any("rejoin after relaunch failed: menu never came" in m for m in r["logs"]))

    def test_own_reconnect_clears_the_window(self):
        # 5 bad checks (75s), one good, then 6 bad (75s from the new start): never confirmed dead
        r = self._run([False] * 5 + [True] + [False] * 6, pid_alive=False)
        r["popen"].assert_not_called()
        self.assertTrue(any("reconnected on its own" in m for m in r["logs"]))


if __name__ == "__main__":
    unittest.main()
