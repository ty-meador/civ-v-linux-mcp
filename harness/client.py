"""Thin client for tunerd's Unix socket (see harness/tunerd.py)."""
from __future__ import annotations

import json
import os
import socket
import threading
from typing import Any

DEFAULT_SOCK = os.environ.get("CIV5_TUNERD_SOCK") or os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "civ5-tuner.sock")


class TunerdError(RuntimeError):
    pass


class TunerConnectionLost(TunerdError):
    """tunerd's connection to the game dropped mid-poll (game listener only re-arms on
    ExitToMainMenu / leaving the MP staging room, so this will not self-heal -- see the
    tuner-drop bug writeup in docs/NOTES.md). Subclasses TunerdError so existing
    `except TunerdError` call sites (cli/mcp/http/supervisor) handle it without changes."""


class Civ5:
    def __init__(self, sock_path: str | None = None, token: str | None = None):
        sock_path = sock_path or DEFAULT_SOCK
        self.path = sock_path
        # The seat token (CIV5_TUNERD_TOKEN): sent as the first message of every connection so a tunerd
        # with a seat table binds this client to its seat (harness/tunerd.py). A daemon without a table
        # ignores it, an older daemon answers "unknown op" and is used as before. It is never logged,
        # never in an error, never in a reply: the one copy is here and in the daemon's table.
        self._token = token if token is not None else (os.environ.get("CIV5_TUNERD_TOKEN") or None)
        self.seat: int | None = None   # the seat the daemon bound this connection to, when it has a table
        self._lock = threading.RLock()
        self.trips = 0   # requests sent; the call ledger (harness/call_ledger.py) reads the difference per tool
        self._open()

    def _open(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.path)
        self.f = self.sock.makefile("rwb")
        if self._token:
            self._hello()

    def _hello(self) -> None:
        """Bind the fresh connection to our seat. Not a trip: transport, not a read of the game."""
        line = self._exchange({"op": "hello", "token": self._token})
        if not line:
            raise TunerdError("tunerd closed the connection on the seat token")
        r = json.loads(line)
        if r.get("ok"):
            self.seat = r.get("seat")
            return
        err = str(r.get("error", ""))
        if err.startswith("unknown op"):
            return   # a tunerd from before seat binding: nothing to bind, carry on as before
        raise TunerdError(f"tunerd refused this client's seat token: {err}")

    def close(self):
        self.f.close(); self.sock.close()

    def call(self, **req: Any) -> dict:
        # MCP sync tools run on worker threads. A request and its reply must stay
        # together or concurrent callers can consume each other's response.
        with self._lock:
            self.trips = getattr(self, "trips", 0) + 1   # a test double built without __init__ has none
            try:
                line = self._exchange(req)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as e:
                # tunerd was restarted under us (routine: it is the thing you restart when the
                # game's tuner connection needs re-arming). The request never reached it, so
                # reconnecting and sending once more cannot duplicate a side effect. Without
                # this, a long-lived MCP server answers "[Errno 32] Broken pipe" to every
                # tool for the rest of its life and only a client restart clears it.
                try:
                    self.close()
                except OSError:
                    pass
                try:
                    self._open()
                except OSError:
                    raise TunerdError(f"tunerd socket {self.path} is not reachable: {e}") from e
                line = self._exchange(req)
            if not line:
                # Clean EOF: tunerd went away, possibly after acting on this request. Re-open
                # so the *next* call works, but do not resend -- a silently repeated move_unit
                # or end_turn is worse than one visible error.
                try:
                    self.close()
                except OSError:
                    pass
                try:
                    self._open()
                except OSError as e:
                    raise TunerdError("tunerd closed the connection") from e
                raise TunerdError("tunerd closed the connection; reconnected -- retry the call")
        return json.loads(line)

    def _exchange(self, req: dict) -> bytes:
        self.f.write((json.dumps(req) + "\n").encode()); self.f.flush()
        return self.f.readline()

    def states(self) -> dict[int, str]:
        r = self.call(op="states")
        if not r["ok"]:
            raise TunerdError(r["error"])
        return {int(k): v for k, v in r["states"].items()}

    def wait_state(self, name: str, timeout: float = 120) -> int:
        r = self.call(op="wait_state", name=name, timeout=timeout)
        if not r["ok"]:
            raise TunerdError(r["error"])
        return r["id"]

    def exec(self, state: int | str, lua: str, timeout: float | None = None, check: bool = True) -> list[str]:
        r = self.call(op="exec", state=state, lua=lua, timeout=timeout)
        if not r["ok"] and check:
            raise TunerdError(r["error"])
        return r.get("output", [])

    def query(self, state: int | str, lua_body: str, timeout: float | None = None):
        r = self.call(op="query", state=state, lua=lua_body, timeout=timeout)
        if not r["ok"]:
            raise TunerdError(r["error"])
        return r["value"]

    def events(self, since: int = 0) -> tuple[list[dict], int]:
        r = self.call(op="events", since=since)
        return r["events"], r["next"]

    def ping(self) -> dict:
        """Cheap liveness probe -- doesn't touch the game connection lock or trigger a reconnect
        attempt, just reports tunerd's current view: {"ok": true, "connected": bool, "since": float}."""
        return self.call(op="ping")
