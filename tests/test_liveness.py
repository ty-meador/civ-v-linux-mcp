"""Regression test for the ping-based liveness check in Game.wait_for_my_turn
(harness/game.py, docs/NOTES.md "wait_for_my_turn liveness check added").

Stands up a throwaway Unix-socket server that speaks tunerd's line-delimited JSON
protocol well enough to drive Game.wait_for_my_turn without a real Civ5/tuner instance:
op=exec (satisfies Game.ensure_runtime's version probe), op=query (turn_state), op=ping.

Run directly: python tests/test_liveness.py
"""
from __future__ import annotations

import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.client import TunerConnectionLost
from harness.game import Game


class FakeTunerd:
    """Handles exactly the ops wait_for_my_turn's path needs. `connected_at_query`
    controls when (by 1-indexed query() call count) `ping` starts reporting
    connected=False; None means it never drops."""

    def __init__(self, sock_path: str, connected_at_query: int | None = None):
        self.sock_path = sock_path
        self.connected_at_query = connected_at_query
        self.query_count = 0
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(sock_path)
        self._srv.listen(1)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        conn, _ = self._srv.accept()
        f = conn.makefile("rwb")
        try:
            for line in f:
                req = json.loads(line)
                resp = self._handle(req)
                f.write((json.dumps(resp) + "\n").encode())
                f.flush()
        except (OSError, ValueError):
            pass

    def _handle(self, req: dict) -> dict:
        op = req["op"]
        if op == "ping":
            connected = self.connected_at_query is None or self.query_count < self.connected_at_query
            return {"ok": True, "connected": connected, "since": 0.0}
        if op == "exec":
            # only path this test exercises is Game.ensure_runtime's version probe
            return {"ok": True, "output": ["true"]}
        if op == "query":
            self.query_count += 1
            ready = self.query_count >= 3
            value = {"my_turn": ready, "processing": False, "hotseat": False}
            return {"ok": True, "value": value}
        raise AssertionError(f"unhandled op in fake tunerd: {op!r}")

    def close(self) -> None:
        self._srv.close()


class WaitForMyTurnLivenessTest(unittest.TestCase):
    def _sock_path(self) -> str:
        d = tempfile.mkdtemp()
        path = str(Path(d) / "fake-tunerd.sock")
        self.addCleanup(lambda: Path(path).exists() and Path(path).unlink())
        return path

    def test_normal_turn_ready_returns(self):
        sock_path = self._sock_path()
        fake = FakeTunerd(sock_path, connected_at_query=None)
        self.addCleanup(fake.close)
        g = Game(sock_path=sock_path)
        self.addCleanup(g.c.close)
        ts = g.wait_for_my_turn(timeout=5, poll=0.01)
        self.assertTrue(ts["my_turn"])

    def test_drop_before_turn_ready_raises(self):
        sock_path = self._sock_path()
        # turn only becomes ready on the 3rd query() call; drop the connection on
        # the very first ping so the drop is unambiguously observed before readiness
        fake = FakeTunerd(sock_path, connected_at_query=1)
        self.addCleanup(fake.close)
        g = Game(sock_path=sock_path)
        self.addCleanup(g.c.close)
        with self.assertRaises(TunerConnectionLost):
            g.wait_for_my_turn(timeout=5, poll=0.01)


if __name__ == "__main__":
    unittest.main()
