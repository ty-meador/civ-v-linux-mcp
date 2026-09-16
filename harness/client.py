"""Thin client for tunerd's Unix socket (see harness/tunerd.py)."""
from __future__ import annotations

import json
import os
import socket
from typing import Any

DEFAULT_SOCK = os.environ.get("CIV5_TUNERD_SOCK") or os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "civ5-tuner.sock")


class TunerdError(RuntimeError):
    pass


class Civ5:
    def __init__(self, sock_path: str | None = None):
        sock_path = sock_path or DEFAULT_SOCK
        self.path = sock_path
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(sock_path)
        self.f = self.sock.makefile("rwb")

    def close(self):
        self.f.close(); self.sock.close()

    def call(self, **req: Any) -> dict:
        self.f.write((json.dumps(req) + "\n").encode()); self.f.flush()
        line = self.f.readline()
        if not line:
            raise TunerdError("tunerd closed the connection")
        return json.loads(line)

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
