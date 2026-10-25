"""tunerd binds a connection to a seat (docs/ROADMAP.md "A seat bound to its channel", stage 1).

A daemon started with a seat table binds each connection by the peer's uid (SO_PEERCRED) or by a token in
the connection's first `hello`, and refuses `exec` / `query` on a connection bound to nothing. A daemon with
no table is the daemon of before: any client, any Lua. The token never appears in a reply or a log line.
"""
import contextlib
import io
import json
import os
import socket
import socketserver
import tempfile
import threading
import unittest

import harness.tunerd as tunerd
from harness.client import Civ5, TunerdError
from harness.tunerd import Handler, SeatTable, Server, gate

TOKEN0 = "seat-zero-secret-0123456789abcdef"
TOKEN1 = "seat-one-secret-fedcba9876543210"


class SeatTableTest(unittest.TestCase):
    def test_tokens_and_uids_bind_their_seats(self):
        t = SeatTable([{"seat": 0, "token": TOKEN0}, {"seat": 1, "token": TOKEN1}, {"seat": 1, "uid": 1001}])
        self.assertTrue(t)
        self.assertEqual(t.seats(), [0, 1])
        self.assertEqual(t.seat_for_token(TOKEN0), 0)
        self.assertEqual(t.seat_for_token(TOKEN1), 1)
        self.assertIsNone(t.seat_for_token("not-a-token-but-long-enough-xx"))
        self.assertIsNone(t.seat_for_token(None))
        self.assertIsNone(t.seat_for_token(12))
        self.assertEqual(t.seat_for_uid(1001), 1)
        self.assertIsNone(t.seat_for_uid(1000))
        self.assertIsNone(t.seat_for_uid(None))

    def test_an_empty_table_binds_nothing(self):
        self.assertFalse(SeatTable([]))
        self.assertFalse(SeatTable(None))

    def test_a_bad_entry_is_refused_at_load(self):
        bad = [
            [{"token": TOKEN0}],                                   # no seat
            [{"seat": True, "token": TOKEN0}],                     # a bool is not a seat
            [{"seat": 0}],                                         # neither token nor uid
            [{"seat": 0, "token": "short"}],                       # a guessable token
            [{"seat": 0, "token": TOKEN0}, {"seat": 1, "token": TOKEN0}],   # one token, two seats
            [{"seat": 0, "uid": 1000}, {"seat": 1, "uid": 1000}],  # one user, two seats
            [{"seat": 0, "uid": "1000"}],                          # a uid is an integer
        ]
        for entries in bad:
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                SeatTable(entries)

    def test_load_reads_the_file_and_warns_when_others_can_read_it(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "seats.json")
            with open(p, "w") as f:
                json.dump({"seats": [{"seat": 0, "token": TOKEN0}]}, f)
            os.chmod(p, 0o644)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                t = SeatTable.load(p)
            self.assertEqual(t.seat_for_token(TOKEN0), 0)
            self.assertIn("readable by other users", err.getvalue())
            self.assertNotIn(TOKEN0, err.getvalue())

            os.chmod(p, 0o600)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                SeatTable.load(p)
            self.assertEqual(err.getvalue(), "")

            with open(p, "w") as f:
                json.dump({"seats": []}, f)
            with self.assertRaises(ValueError):
                SeatTable.load(p)

    def test_main_refuses_to_start_on_a_bad_table(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "seats.json")
            with open(p, "w") as f:
                f.write("{not json")
            with self.assertRaises(SystemExit) as cm:
                tunerd.main(["--seats", p, "--sock", os.path.join(d, "t.sock")])
            self.assertIn("seat table", str(cm.exception))
            with self.assertRaises(SystemExit):
                tunerd.main(["--seats", os.path.join(d, "missing.json"), "--sock", os.path.join(d, "t.sock")])


class GateTest(unittest.TestCase):
    """The rule itself, without a socket."""

    def setUp(self):
        self.table = SeatTable([{"seat": 0, "token": TOKEN0}, {"seat": 1, "token": TOKEN1}])

    def test_without_a_table_nothing_is_gated_and_hello_is_a_no_op(self):
        for table in (None, SeatTable([])):
            r, seat, close = gate({"op": "exec", "state": 5, "lua": "print(1)"}, table, None, True)
            self.assertIsNone(r)
            r, seat, close = gate({"op": "hello", "token": TOKEN0}, table, None, True)
            self.assertEqual(r, {"ok": True, "bound": False, "seat": None})
            self.assertIsNone(seat)
            self.assertFalse(close)

    def test_an_unbound_exec_or_query_is_refused_and_the_open_ops_pass(self):
        for op in ("exec", "query"):
            r, _seat, close = gate({"op": op, "state": 5, "lua": "return 1"}, self.table, None, False)
            self.assertFalse(r["ok"])
            self.assertTrue(r["unbound"])
            self.assertIn("hello", r["error"])
            self.assertFalse(close, "a refused read keeps the connection; the client may still bind nothing and ping")
        for op in ("ping", "events", "states", "wait_state"):
            r, _seat, _close = gate({"op": op, "name": "InGame"}, self.table, None, False)
            self.assertIsNone(r, f"{op} is open on a daemon with a table")

    def test_a_first_hello_with_a_listed_token_binds_the_connection(self):
        r, seat, close = gate({"op": "hello", "token": TOKEN1}, self.table, None, True)
        self.assertEqual(r, {"ok": True, "bound": True, "seat": 1})
        self.assertEqual(seat, 1)
        self.assertFalse(close)
        r, seat, close = gate({"op": "exec", "state": 5, "lua": "print(1)"}, self.table, seat, False)
        self.assertIsNone(r)
        self.assertEqual(seat, 1)

    def test_an_unknown_token_is_refused_and_the_connection_closed(self):
        r, seat, close = gate({"op": "hello", "token": "guess-guess-guess-guess-guess"}, self.table, None, True)
        self.assertFalse(r["ok"])
        self.assertIsNone(seat)
        self.assertTrue(close)
        self.assertNotIn("guess", json.dumps(r), "the refusal does not echo what was sent")
        r, seat, close = gate({"op": "hello"}, self.table, None, True)
        self.assertFalse(r["ok"])
        self.assertTrue(close)

    def test_a_late_hello_is_refused_without_closing(self):
        r, seat, close = gate({"op": "hello", "token": TOKEN0}, self.table, None, False)
        self.assertFalse(r["ok"])
        self.assertIn("first message", r["error"])
        self.assertIsNone(seat)
        self.assertFalse(close)

    def test_a_uid_bound_connection_takes_only_its_own_seats_token(self):
        r, seat, close = gate({"op": "hello", "token": TOKEN0}, self.table, 0, True)
        self.assertEqual((r["ok"], seat, close), (True, 0, False))
        r, seat, close = gate({"op": "hello", "token": TOKEN1}, self.table, 0, True)
        self.assertFalse(r["ok"])
        self.assertIn("another seat", r["error"])
        self.assertEqual(seat, 0)
        self.assertTrue(close)

    def test_a_uid_bound_connection_needs_no_hello(self):
        r, seat, _ = gate({"op": "query", "state": 5, "lua": "return 1"}, self.table, 1, True)
        self.assertIsNone(r)
        self.assertEqual(seat, 1)


class _StubBridge:
    """Records what reaches the bridge and with which seat; never touches a game."""

    def __init__(self):
        self.seen: list[tuple[dict, int | None]] = []

    def handle(self, req, seat=None):
        self.seen.append((req, seat))
        if req.get("op") == "ping":
            return {"ok": True, "connected": False, "since": 0}
        return {"ok": True, "op": req.get("op"), "seat": seat}


class _TrackingHandler(Handler):
    """The real Handler, remembering its connection so a stopped daemon can drop it like a killed process would."""

    def setup(self):
        super().setup()
        self.server.conns.append(self.request)


class _Daemon:
    """The real Handler and Server over a scratch socket, with a stub bridge and a given seat table."""

    def __init__(self, path, table):
        self.path, self.table = path, table
        self.bridge = _StubBridge()

    def start(self):
        self.srv = Server(self.path, _TrackingHandler)
        self.srv.bridge = self.bridge
        self.srv.seats = self.table
        self.srv.conns = []
        threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()
        for c in self.srv.conns:
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if os.path.exists(self.path):
            os.unlink(self.path)


def _raw(path, *reqs):
    """Send requests on one fresh connection, no hello, and return the replies (None where the daemon closed)."""
    out = []
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(path)
        f = s.makefile("rwb")
        for r in reqs:
            f.write((json.dumps(r) + "\n").encode()); f.flush()
            line = f.readline()
            out.append(json.loads(line) if line else None)
    return out


class SocketBindingTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "t.sock")
        os.environ.pop("CIV5_TUNERD_TOKEN", None)

    def _daemon(self, table):
        d = _Daemon(self.path, table)
        d.start()
        self.addCleanup(d.stop)
        return d

    def test_a_raw_client_without_a_token_is_refused_on_a_daemon_with_a_table(self):
        d = self._daemon(SeatTable([{"seat": 0, "token": TOKEN0}]))
        ping, ex, states = _raw(self.path, {"op": "ping"}, {"op": "exec", "state": 5, "lua": "print(1)"}, {"op": "states"})
        self.assertTrue(ping["ok"])
        self.assertFalse(ex["ok"])
        self.assertTrue(ex["unbound"])
        self.assertTrue(states["ok"], "states stays open, and the refusal did not close the connection")
        self.assertEqual([r["op"] for r, _ in d.bridge.seen], ["ping", "states"], "the exec never reached the game")

    def test_the_same_raw_client_works_on_a_daemon_without_a_table(self):
        d = self._daemon(None)
        (ex,) = _raw(self.path, {"op": "exec", "state": 5, "lua": "print(1)"})
        self.assertTrue(ex["ok"])
        self.assertEqual(d.bridge.seen[0][1], None)

    def test_the_harness_client_binds_with_its_token_and_the_bridge_sees_the_seat(self):
        d = self._daemon(SeatTable([{"seat": 0, "token": TOKEN0}, {"seat": 1, "token": TOKEN1}]))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            c = Civ5(self.path, token=TOKEN1)
            self.assertEqual(c.seat, 1)
            r = c.call(op="exec", state=5, lua="print(1)")
        self.assertTrue(r["ok"])
        self.assertEqual(d.bridge.seen[-1], ({"op": "exec", "state": 5, "lua": "print(1)"}, 1))
        self.assertEqual(c.trips, 1, "the hello is transport, not a trip")
        self.assertIn("bound to seat 1 by token", err.getvalue())
        self.assertNotIn(TOKEN1, err.getvalue())
        self.assertNotIn(TOKEN1, json.dumps(d.bridge.seen), "the token never reaches the bridge")

    def test_the_token_comes_from_the_environment_by_default(self):
        self._daemon(SeatTable([{"seat": 0, "token": TOKEN0}]))
        os.environ["CIV5_TUNERD_TOKEN"] = TOKEN0
        self.addCleanup(os.environ.pop, "CIV5_TUNERD_TOKEN", None)
        c = Civ5(self.path)
        self.assertEqual(c.seat, 0)
        self.assertTrue(c.call(op="query", state=5, lua="return 1")["ok"])

    def test_a_wrong_token_is_a_clear_error_that_does_not_name_it(self):
        self._daemon(SeatTable([{"seat": 0, "token": TOKEN0}]))
        with self.assertRaises(TunerdError) as cm:
            Civ5(self.path, token="wrong-wrong-wrong-wrong-wrong")
        self.assertIn("seat token", str(cm.exception))
        self.assertNotIn("wrong-wrong", str(cm.exception))

    def test_a_token_on_a_daemon_without_a_table_is_ignored(self):
        d = self._daemon(None)
        c = Civ5(self.path, token=TOKEN0)
        self.assertIsNone(c.seat)
        self.assertTrue(c.call(op="exec", state=5, lua="print(1)")["ok"])
        self.assertEqual(d.bridge.seen[-1][1], None)

    def test_the_peer_uid_binds_without_a_hello(self):
        d = self._daemon(SeatTable([{"seat": 1, "uid": os.getuid()}, {"seat": 1, "token": TOKEN1},
                                    {"seat": 0, "token": TOKEN0}]))
        (ex,) = _raw(self.path, {"op": "exec", "state": 5, "lua": "print(1)"})
        self.assertTrue(ex["ok"])
        self.assertEqual(d.bridge.seen[-1][1], 1)
        # this user's connection may not take the other seat's token...
        (hello,) = _raw(self.path, {"op": "hello", "token": TOKEN0})
        self.assertFalse(hello["ok"])
        self.assertIn("another seat", hello["error"])
        # ...and its own seat's token agrees with the uid
        c = Civ5(self.path, token=TOKEN1)
        self.addCleanup(c.close)
        self.assertEqual(c.seat, 1)

    def test_the_binding_is_per_connection_and_survives_the_clients_reconnect(self):
        d = self._daemon(SeatTable([{"seat": 0, "token": TOKEN0}]))
        c = Civ5(self.path, token=TOKEN0)
        c.call(op="ping")
        d.stop()
        fresh = _Daemon(self.path, SeatTable([{"seat": 0, "token": TOKEN0}]))
        fresh.start()
        self.addCleanup(fresh.stop)
        try:
            c.call(op="ping")
        except TunerdError as e:
            self.assertIn("retry", str(e))
        r = c.call(op="exec", state=5, lua="print(1)")
        self.assertTrue(r["ok"])
        self.assertEqual(fresh.bridge.seen[-1][1], 0, "the reconnect sent a fresh hello before the request")

    def test_an_old_daemon_that_knows_no_hello_is_used_as_before(self):
        class Old(socketserver.StreamRequestHandler):
            def handle(self):
                for line in self.rfile:
                    req = json.loads(line)
                    resp = {"ok": False, "error": f"unknown op {req['op']!r}"} if req["op"] == "hello" else {"ok": True}
                    self.wfile.write((json.dumps(resp) + "\n").encode()); self.wfile.flush()

        srv = Server(self.path, Old)
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        c = Civ5(self.path, token=TOKEN0)
        self.assertIsNone(c.seat)
        self.assertTrue(c.call(op="ping")["ok"])


if __name__ == "__main__":
    unittest.main()
