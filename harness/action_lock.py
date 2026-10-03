"""Serialize complete MCP operations, including selection and postcondition reads.

One lock per tuner socket, shared by every process that talks to it (each seat's MCP server, a one-shot
`scripts/mcp_call.py`, ...): a cross-process `flock` on a file under /tmp, plus a process-local RLock so
two worker threads of one server queue the same way. Hold it for one operation -- a read, an order with
its selection and postcondition, one poll of a wait -- never across a sleep. The Codex/Grok hotseat of
2026-09-26 (docs/NOTES.md) stalled for most of two turns because the wait tools held it for their whole
wait: the inactive seat's `finish_turn(300)` starved the active seat's `turn_status` for five minutes.

The holder writes its seat, tool and pid into the lock file. A contender refused after `timeout` learns
only what a human at the hand-off screen would: when the holder is another seat, "it is not your turn";
when it is its own seat (an earlier call of its own, a one-shot server it forgot), which call and for how
long. Another player's tool names and timings are their cursor, not part of the game's UI.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import threading
import time

_thread_lock = threading.RLock()


def lock_path(socket_path: str) -> Path:
    key = hashlib.sha256(socket_path.encode()).hexdigest()[:24]
    return Path('/tmp') / f'civ5-actions-{key}.lock'


def _holder(lock) -> dict:
    try:
        lock.seek(0)
        v = json.loads(lock.read() or "{}")
        return v if isinstance(v, dict) else {}
    except (ValueError, OSError):
        return {}


def busy_message(holder: dict, seat=None) -> str:
    """What a contender on `seat` may know about who holds the lock."""
    h_seat = holder.get("seat")
    if h_seat is None or seat is None or str(h_seat) != str(seat):
        return ("another game operation is running; retry (it is not your turn while another seat acts: "
                "wait_for_my_turn / finish_turn wait for yours)")
    age = int(time.time() - float(holder.get("since", time.time())))
    return (f"another game operation is running; retry (your own {holder.get('tool') or 'call'}, "
            f"pid {holder.get('pid')}, has held it for {age} s)")


class LockBusy(TimeoutError):
    """The lock was not free within `timeout`: another operation holds it. A TimeoutError, so every caller that
    already reports one keeps doing so; a wait loop catches this one and polls again instead of giving up."""


@contextmanager
def action_lock(socket_path: str, timeout: float = 10, seat=None, tool: str | None = None):
    """Exclusive access to the game behind `socket_path` for one operation, by `seat` running `tool`."""
    deadline = time.monotonic() + timeout
    if not _thread_lock.acquire(timeout=timeout):
        raise LockBusy("another game operation is running; retry (an earlier call of this server is still running)")
    try:
        with lock_path(socket_path).open('a+') as lock:
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise LockBusy(busy_message(_holder(lock), seat)) from None
                    time.sleep(0.05)
            try:
                lock.seek(0)
                lock.truncate()
                lock.write(json.dumps({"seat": seat, "tool": tool or "", "pid": os.getpid(), "since": time.time()}))
                lock.flush()
            except OSError:
                pass
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    finally:
        _thread_lock.release()
