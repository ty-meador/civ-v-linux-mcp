"""Serialize complete MCP operations, including selection and postcondition reads.

One lock per tuner socket, shared by every process that talks to it (each seat's MCP server, a one-shot
`scripts/mcp_call.py`, ...): a cross-process `flock` on a file under /tmp, plus a process-local RLock so
two worker threads of one server queue the same way. Hold it for one operation -- a read, an order with
its selection and postcondition, one poll of a wait -- never across a sleep. The Codex/Grok hotseat of
2026-09-26 (docs/NOTES.md) stalled for most of two turns because the wait tools held it for their whole
wait: the inactive seat's `finish_turn(300)` starved the active seat's `turn_status` for five minutes.

The holder writes who it is into the lock file, so the refusal a contender gets after `timeout` names
the tool, seat and pid that hold it and for how long, instead of a bare "retry".
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


def busy_message(holder: dict) -> str:
    msg = "another game operation is running; retry"
    if holder.get("label"):
        age = int(time.time() - float(holder.get("since", time.time())))
        msg += f" (held by {holder['label']}, pid {holder.get('pid')}, for {age} s)"
    return msg


@contextmanager
def action_lock(socket_path: str, timeout: float = 10, label: str | None = None):
    """Exclusive access to the game behind `socket_path` for one operation. `label` names the holder in
    the refusal a contender gets ("wait_for_my_turn seat 1")."""
    deadline = time.monotonic() + timeout
    if not _thread_lock.acquire(timeout=timeout):
        raise TimeoutError("another game operation is running; retry")
    try:
        with lock_path(socket_path).open('a+') as lock:
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(busy_message(_holder(lock)))
                    time.sleep(0.05)
            try:
                lock.seek(0)
                lock.truncate()
                lock.write(json.dumps({"label": label or "", "pid": os.getpid(), "since": time.time()}))
                lock.flush()
            except OSError:
                pass
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    finally:
        _thread_lock.release()
