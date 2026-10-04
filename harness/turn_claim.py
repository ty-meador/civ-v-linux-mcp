"""One client owns a seat's turn between calls (GitLab #41).

The action lock (`action_lock.py`) makes one game operation exclusive; it says nothing about who owns the
turn in the gaps between operations. Two MCP servers pinned to the same `--seat` were both allowed to end
it: on 2026-09-26 (Mongolia, seat 1, turns 37-42) a second client of the seat ended turns whose `todo`
was empty while the first still meant to retarget its scout, and every order of the first then found the
other seat active.

The claim is a small JSON file beside the lock, one per tuner socket and seat, holding the pid that
issued the turn's first mutating command, the game turn, when that first command was and when the
latest one was. Rules:

- A mutating command (an order, a diplomatic answer, `end_turn`, the end inside `finish_turn`) from
  the holding pid refreshes the claim and proceeds; the same from another pid is refused with the
  holder's pid and how long it has held the turn.
- The claim is for one game turn: a new turn number frees it, so the client that ends turn N and
  keeps going with `skip_quiet_turns` simply claims N+1, N+2, ... as it ends them.
- It expires after IDLE_SECONDS with no mutating command from the holder (long enough for a model to
  think, short enough that an abandoned client does not freeze the seat), and at once when the
  holder's process is gone. `force=True` takes it over regardless.
- Reads, the waits and the notebook never touch it: a second client can look, and can resume after
  the idle interval, without moving anything in between.
- The claim also records the holder's client label (call_ledger.client(): CIV5_CLIENT, else the MCP
  clientInfo). A refusal whose holder carries the caller's own label says so (`same_client`): on
  2026-10-03 Codex's second and fourth sessions each waited out their own earlier session's server,
  which the Codex app had kept alive after a context reset, for up to 180 s. Two agents at one table
  carry different labels, so the hint never points at another model's session; the caller still decides
  (force) -- nothing is taken over by itself.

The file is only ever read for the caller's own seat, so everything in a refusal is about a client of
the same seat (docs/PLAYBOOK.md: nothing a seat receives describes another player's activity).
"""
import hashlib
import json
import os
from pathlib import Path
import time

IDLE_SECONDS = 180


class ClaimRefused(Exception):
    """Another client of this seat holds the turn. `info` is the structured refusal (turn_claim)."""

    def __init__(self, message: str, info: dict):
        super().__init__(message)
        self.info = info


def claim_path(socket_path: str, seat) -> Path:
    key = hashlib.sha256(socket_path.encode()).hexdigest()[:24]
    return Path('/tmp') / f'civ5-turn-{key}-seat{seat}.json'


def read_claim(socket_path: str, seat) -> dict:
    try:
        v = json.loads(claim_path(socket_path, seat).read_text() or "{}")
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError, TypeError, OverflowError):
        return False
    except PermissionError:
        return True
    return True


def claim_status(socket_path: str, seat, turn, pid: int | None = None, now: float | None = None,
                 client: str | None = None) -> dict | None:
    """The live claim on `seat`'s turn `turn` as seen by `pid`, or None when nobody holds it (no file,
    another turn, the holder's process gone, or idle past IDLE_SECONDS). `holder_client` is the label the
    holder's server carried (None for a claim written without one); `same_client` is true when it equals
    `client`, the caller's own label -- another process of the same agent on this seat."""
    c = read_claim(socket_path, seat)
    if not c or c.get("turn") != turn:
        return None
    now = time.time() if now is None else now
    pid = os.getpid() if pid is None else pid
    try:
        holder, since, last = int(c["pid"]), float(c["since"]), float(c.get("last", c["since"]))
    except (KeyError, TypeError, ValueError):
        return None
    idle = max(0, int(now - last))
    if idle >= IDLE_SECONDS or not _pid_alive(holder):
        return None
    holder_client = c.get("client") or None
    return {"holder_pid": holder, "mine": holder == pid, "tool": c.get("tool") or "",
            "held_for_s": max(0, int(now - since)), "idle_for_s": idle, "expires_in_s": IDLE_SECONDS - idle,
            "idle_limit_s": IDLE_SECONDS, "holder_client": holder_client,
            "same_client": bool(holder_client and client and holder_client == client)}


def claim_turn(socket_path: str, seat, turn, tool: str, force: bool = False,
               pid: int | None = None, now: float | None = None, client: str | None = None) -> dict:
    """Record `pid` (carrying `client`, its label) as the owner of `seat`'s turn `turn` for `tool`, or raise
    ClaimRefused when another live, non-idle client of the seat owns it (unless `force`). Returns the claim
    as written, with `taken_over: True` when force displaced a holder."""
    now = time.time() if now is None else now
    pid = os.getpid() if pid is None else pid
    live = claim_status(socket_path, seat, turn, pid=pid, now=now, client=client)
    taken_over = False
    if live and not live["mine"]:
        if not force:
            same = (f" That holder carries this client's own label ({live['holder_client']}): most likely an earlier "
                    f"session of the same agent on this seat, still alive after a context reset -- force=true takes "
                    f"the turn over at once." if live["same_client"] else "")
            raise ClaimRefused(
                f"another client of seat {seat} holds turn {turn} (pid {live['holder_pid']}, first order "
                f"{live['held_for_s']} s ago, latest {live['idle_for_s']} s ago); the turn frees "
                f"{live['expires_in_s']} s after that client's latest order or when its process exits; "
                f"force=true on end_turn / finish_turn / do takes it over now. Reads, the waits and the "
                f"notebook still work meanwhile.{same}",
                {**live, "seat": seat, "turn": turn, "refused_tool": tool})
        taken_over = True
    since = now if not live or not live["mine"] else now - live["held_for_s"]
    c = {"seat": seat, "turn": turn, "pid": pid, "tool": tool, "since": since, "last": now}
    if client:
        c["client"] = client
    p = claim_path(socket_path, seat)
    try:
        tmp = p.with_suffix(f".{pid}.tmp")
        tmp.write_text(json.dumps(c))
        os.replace(tmp, p)
    except OSError:
        pass
    out = dict(c)
    if taken_over:
        out["taken_over"] = True
    return out
