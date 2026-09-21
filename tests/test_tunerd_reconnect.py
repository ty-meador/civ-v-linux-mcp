"""Reconnect behaviour around tunerd, both directions.

Two failures cost a whole session start on 2026-09-20 and neither self-heals:

1. `launch_civ5.sh` opens the tuner port long before the front end creates its Lua contexts.
   A tunerd started in that gap handshakes fine, logs "0 lua states", and answers every later
   LSQ on that connection with an empty list -- so every tool fails with
   "Lua state 'LoadMenu' did not appear" until a human restarts the daemon.
2. Restarting the daemon (the documented fix for a wedged game connection) leaves every
   long-lived client -- the MCP server, the http server -- writing to a dead socket and
   returning "[Errno 32] Broken pipe" for the rest of its life.
"""
import json
import os
import socket
import tempfile
import threading
import unittest

from harness.client import Civ5, TunerdError
from harness.tunerd import Bridge


class FakeTunerClient:
    """Stands in for TunerClient: hands out whatever state list the script says."""

    def __init__(self, states):
        self._states = states
        self.app = "Civ5 | fake"
        self.closed = False

    def handshake(self):
        return self._states

    def close(self):
        self.closed = True


class ConnectWithStatesTest(unittest.TestCase):
    def _run(self, scripted_states, attempts=4):
        """Drive _connect_with_states against a scripted sequence of handshake results.

        Returns (client, connections_made, sleeps).
        """
        import harness.tunerd as tunerd

        made: list[FakeTunerClient] = []
        slept: list[float] = []

        class Stub:
            def __init__(self, *a, **kw):
                pass

            def connect(self, *a, **kw):
                c = FakeTunerClient(scripted_states[len(made)])
                made.append(c)
                return c

        original, original_sleep = tunerd.TunerClient, tunerd.time.sleep
        tunerd.TunerClient = Stub
        tunerd.time.sleep = slept.append
        try:
            client = Bridge("127.0.0.1", 4318)._connect_with_states(attempts=attempts, delay=0.01)
        finally:
            tunerd.TunerClient = original
            tunerd.time.sleep = original_sleep
        return client, made, slept

    def test_empty_state_list_is_retried_until_the_front_end_is_up(self):
        """0 states means "connected too early", not "this game has no Lua"."""
        client, made, slept = self._run([{}, {}, {1: "MainMenu", 2: "LoadMenu"}, {}])

        self.assertEqual(client.handshake(), {1: "MainMenu", 2: "LoadMenu"})
        self.assertEqual(len(made), 3, "should have reconnected twice before states appeared")
        self.assertTrue(made[0].closed and made[1].closed, "dead-early connections must be closed")
        self.assertEqual(slept, [0.01, 0.01])

    def test_first_nonempty_handshake_connects_once(self):
        client, made, slept = self._run([{1: "MainMenu"}])

        self.assertEqual(len(made), 1)
        self.assertFalse(made[0].closed)
        self.assertEqual(slept, [])

    def test_gives_up_after_the_last_attempt_rather_than_looping_forever(self):
        client, made, slept = self._run([{}, {}, {}, {}])

        self.assertEqual(len(made), 4)
        self.assertFalse(made[-1].closed, "the last connection is kept, not thrown away")


class _FakeDaemon:
    """A minimal newline-JSON server on a unix socket that can be stopped and restarted."""

    def __init__(self, path):
        self.path = path
        self.requests: list[dict] = []
        self._srv = None
        self._thread = None
        self._conns: list[socket.socket] = []

    def start(self):
        if os.path.exists(self.path):
            os.unlink(self.path)
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(self.path)
        self._srv.listen(4)
        self._stop = False
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return
            self._conns.append(conn)
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        try:
            with conn, conn.makefile("rwb") as f:
                while True:
                    line = f.readline()
                    if not line:
                        return
                    req = json.loads(line)
                    self.requests.append(req)
                    f.write((json.dumps({"ok": True, "echo": req}) + "\n").encode())
                    f.flush()
        except OSError:
            return

    def stop(self):
        """Kill the whole daemon, open connections included -- a restarted tunerd does not
        keep serving its predecessor's clients."""
        self._stop = True
        if self._srv:
            self._srv.close()
        for c in self._conns:
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                c.close()
            except OSError:
                pass
        self._conns.clear()
        if os.path.exists(self.path):
            os.unlink(self.path)


class ClientReconnectTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "t.sock")
        self.daemon = _FakeDaemon(self.path)
        self.daemon.start()
        self.addCleanup(self.dir.cleanup)
        self.addCleanup(self.daemon.stop)

    def test_survives_a_daemon_restart(self):
        """The documented fix for a wedged game connection is "restart tunerd"; a long-lived
        MCP server must not need restarting too."""
        c = Civ5(self.path)
        self.assertTrue(c.call(op="ping")["ok"])

        self.daemon.stop()
        fresh = _FakeDaemon(self.path)
        fresh.start()
        self.addCleanup(fresh.stop)

        # The first call after the restart may surface the clean EOF; either way the client
        # must end up usable again rather than raising Broken pipe forever.
        try:
            c.call(op="ping")
        except TunerdError as e:
            self.assertIn("retry", str(e))
        self.assertTrue(c.call(op="states")["ok"])
        self.assertEqual(fresh.requests[-1]["op"], "states")

    def test_a_clean_eof_does_not_silently_resend_the_request(self):
        """A resend could repeat a move or an end_turn the daemon had already acted on."""
        c = Civ5(self.path)
        c.call(op="ping")
        self.daemon.stop()
        fresh = _FakeDaemon(self.path)
        fresh.start()
        self.addCleanup(fresh.stop)

        sent_twice = 0
        for _ in range(2):
            try:
                c.call(op="end_turn")
            except TunerdError:
                pass
        sent_twice = sum(1 for r in fresh.requests if r["op"] == "end_turn")
        self.assertLessEqual(sent_twice, 2, "one end_turn per call, never an automatic replay")


if __name__ == "__main__":
    unittest.main()
