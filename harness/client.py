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
    def __init__(self, sock_path: str | None = None):
        sock_path = sock_path or DEFAULT_SOCK
        self.path = sock_path
        self._lock = threading.RLock()
        self._open()

    def _open(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.path)
        self.f = self.sock.makefile("rwb")

    def close(self):
        self.f.close(); self.sock.close()

    def call(self, **req: Any) -> dict:
        # MCP sync tools run on worker threads. A request and its reply must stay
        # together or concurrent callers can consume each other's response.
        with self._lock:
            try:
                line = self._exchange(req)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as e:
                # tunerd was restarted under us (routine: it is the thing you restart when the
                # game's tuner connection needs re-arming). The request never reached it, so
                # reconnecting and sending once more cannot duplicate a side effect. Without
                # this, a long-lived MCP/http server answers "[Errno 32] Broken pipe" to every
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
                except OSError:
                    raise TunerdError("tunerd closed the connection")
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

    def eval(self, state: int | str, expr: str) -> str:
        return "\n".join(self.exec(state, f"print({expr})"))

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
