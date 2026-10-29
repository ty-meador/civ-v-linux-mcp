"""Which MCP servers of one seat are attached to a game, and whether this one runs code older than main
(GitLab #61).

Two servers of seat 0 of a solo game were attached to one tunerd on 2026-10-27 (the earlier session's, idle,
and the new one): nothing in status said so; `ps` did. And a server started before a release cut keeps its
import-time tool listing and Python: the client saw "(oneOf below)" in a description that no code on disk
still carried. Both are facts about the caller's own seat and own process, so a status row may carry them
(nothing here is about another seat).

A small JSON file beside the action lock, one per tuner socket and seat, holds a row per server process
(pid -> client label, when it first called, when it last called, the code stamp it imported). Every guarded
call refreshes the caller's row and drops rows of dead pids; `others` lists the live rows of other pids;
`outdated` says whether the harness's Python on disk changed after this process imported it. The Lua runtime
is not the question: it re-installs itself at the next call.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time

HARNESS_DIR = Path(__file__).resolve().parent


def code_stamp(root: Path | None = None) -> float:
    """The newest mtime of the harness's own Python (what a running server imported once)."""
    root = root or HARNESS_DIR
    newest = 0.0
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for f in filenames:
                if f.endswith(".py"):
                    try:
                        newest = max(newest, os.stat(os.path.join(dirpath, f)).st_mtime)
                    except OSError:
                        pass
    except OSError:
        pass
    return newest


STAMP_AT_IMPORT = code_stamp()
STARTED = time.time()


def changed_files(since: float, root: Path | None = None) -> list[str]:
    """The harness's Python files written after `since`, relative to the package, newest first."""
    root = root or HARNESS_DIR
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for f in filenames:
            if f.endswith(".py"):
                p = os.path.join(dirpath, f)
                try:
                    m = os.stat(p).st_mtime
                except OSError:
                    continue
                if m > since:
                    out.append((m, os.path.relpath(p, root)))
    return [p for _, p in sorted(out, reverse=True)]


def outdated(now: float | None = None, stamp_at_import: float | None = None, root: Path | None = None) -> dict | None:
    """None while this process runs the code on disk; otherwise what changed and what to do about it."""
    stamp = STAMP_AT_IMPORT if stamp_at_import is None else stamp_at_import
    files = changed_files(stamp, root)
    if not files:
        return None
    now = time.time() if now is None else now
    return {"files_changed": len(files), "newest": files[0], "running_for_s": max(0, int(now - STARTED)),
            "note": ("the harness's Python on disk changed after this server started; its tool listing and behaviour "
                     "are those of the older code until the client restarts its MCP server (Claude Code: /mcp "
                     "reconnect, or a new session)")}


def presence_path(socket_path: str, seat) -> Path:
    key = hashlib.sha256(socket_path.encode()).hexdigest()[:24]
    return Path("/tmp") / f"civ5-clients-{key}-seat{seat}.json"


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError, TypeError, OverflowError):
        return False
    except PermissionError:
        return True
    return True


def _read(path: Path) -> dict:
    try:
        v = json.loads(path.read_text() or "{}")
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def touch(socket_path: str, seat, client: str | None = None, pid: int | None = None, now: float | None = None,
          stamp: float | None = None) -> dict:
    """Refresh this process's row (and drop the rows of dead processes); returns the file's rows."""
    pid = os.getpid() if pid is None else int(pid)
    now = time.time() if now is None else now
    path = presence_path(socket_path, seat)
    rows = {k: v for k, v in _read(path).items() if isinstance(v, dict) and _pid_alive(k)}
    mine = rows.get(str(pid)) or {"since": now}
    mine.update({"last": now, "client": client or mine.get("client"),
                 "stamp": STAMP_AT_IMPORT if stamp is None else stamp})
    rows[str(pid)] = mine
    try:
        tmp = path.with_suffix(".tmp%d" % pid)
        tmp.write_text(json.dumps(rows))
        os.replace(tmp, path)
    except OSError:
        pass
    return rows


def others(socket_path: str, seat, pid: int | None = None, now: float | None = None,
           disk_stamp: float | None = None) -> list[dict]:
    """The other live servers of this seat: {pid, client, attached_for_s, last_call_s, code_behind}; `code_behind`
    is true when that server imported Python older than what is on disk now."""
    pid = os.getpid() if pid is None else int(pid)
    now = time.time() if now is None else now
    disk = code_stamp() if disk_stamp is None else disk_stamp
    out = []
    for k, v in sorted(_read(presence_path(socket_path, seat)).items(), key=lambda kv: kv[0]):
        if not isinstance(v, dict) or int(k) == pid or not _pid_alive(k):
            continue
        try:
            since, last = float(v.get("since", now)), float(v.get("last", now))
        except (TypeError, ValueError):
            since = last = now
        out.append({"pid": int(k), "client": v.get("client"), "attached_for_s": max(0, int(now - since)),
                    "last_call_s": max(0, int(now - last)),
                    "code_behind": bool(v.get("stamp") is not None and float(v["stamp"]) < disk)})
    return out
