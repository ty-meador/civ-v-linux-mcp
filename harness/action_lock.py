"""Serialize complete MCP operations, including selection and postcondition reads."""
from contextlib import contextmanager
import fcntl
import hashlib
from pathlib import Path
import threading
import time

_thread_lock = threading.RLock()


@contextmanager
def action_lock(socket_path: str, timeout: float = 10):
    deadline = time.monotonic() + timeout
    if not _thread_lock.acquire(timeout=timeout):
        raise TimeoutError("another game operation is running; retry")
    try:
        key = hashlib.sha256(socket_path.encode()).hexdigest()[:24]
        with (Path('/tmp') / f'civ5-actions-{key}.lock').open('a') as lock:
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("another game operation is running; retry")
                    time.sleep(0.05)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    finally:
        _thread_lock.release()
