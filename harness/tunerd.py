"""tunerd: owns the single FireTuner connection to Civ V and multiplexes it.

Civ V accepts exactly ONE tuner client per arming of the listener (it is re-armed only
on ExitToMainMenu / leaving the MP staging room).  Any client that drops the TCP
connection wedges the port until then.  So one long-lived process holds the
connection and everyone else talks to this daemon over a local Unix socket with
newline-delimited JSON:

    -> {"op": "states"}
    -> {"op": "exec",  "state": "InGame" | 12, "lua": "print(1)", "timeout": 10}
    -> {"op": "query", "state": "InGame", "lua": "return {a=1}", "timeout": 10}
    -> {"op": "wait_state", "name": "InGame", "timeout": 120}
    -> {"op": "events", "since": 0}      # unsolicited output the game printed on its own
    -> {"op": "ping"}
    -> {"op": "hello", "token": "..."}   # first message on a connection: bind it to a seat (see below)
    -> {"op": "call", "fn": "tactical_view", "args": [5, 2, "full"], "timeout": 10}   # one runtime entry, see below
    -> {"op": "call", "calls": [["unit_pos", [5]], ["unit_pos", [7]]]}               # several in one trip, a list back
    -> {"op": "runtime", "force": false}  # make sure the Lua runtime (harness/lua/runtime) is installed in the game
    <- {"ok": true, ...} | {"ok": false, "error": "..."}

Run:  python -m harness.tunerd [--sock PATH] [--host 127.0.0.1] [--port 4318] [--seats FILE]
      (defaults from env: CIV5_TUNERD_SOCK, CIV5_TUNER_HOST, CIV5_TUNER_PORT, CIV5_TUNERD_SEATS -- one daemon
      per game instance)

Seats (fair play by mechanism; docs/ROADMAP.md "A seat bound to its channel", stage 1).  Without `--seats`
the daemon is what it always was: any client, any Lua.  With a seat table every connection is bound to one
seat or to none, and `exec` / `query` work only on a bound connection; `ping`, `events`, `states` and
`wait_state` stay open.  A connection binds in one of two ways: the peer's uid is in the table
(`SO_PEERCRED`, one OS user per agent), or its FIRST message is `hello` with a token from the table (one
token per sandbox, handed to the agent as CIV5_TUNERD_TOKEN; harness/client.py sends it by itself).  A
`hello` later than first, an unknown token, or a token for another seat than the uid's is refused and the
connection closed.  The table is JSON: {"seats": [{"seat": 0, "token": "..."}, {"seat": 1, "uid": 1001}]};
several entries may name one seat (two clients of one seat), a token belongs to one seat.  No token is ever
logged or echoed; the one secret the harness holds is in that file and in each agent's own environment.

Calls (stage 3).  `call` names a runtime entry (`H.<fn>` in harness/lua/runtime) and its arguments as JSON;
the daemon writes the Lua itself -- `return H._call("fn", <seat>, {args}, n)` -- and the runtime's dispatcher
inserts the seat at the entry's own seat slot (dispatch.lua), so no argument of the caller's can take the
seat's place.  On a bound connection the seat is the binding, and a "seat" in the request that names another
one is refused; on a daemon without a table the request's "seat" is used (the solo game, today's client).
The daemon installs the runtime on first use (`runtime`, and before any `call`), from the source on disk at
that moment, so no client ships Lua for it.  A bound connection may not send free Lua (`exec` / `query`) to
InGame at all, and to any other state (a popup, a leader screen, the front end) only while its seat is the
active player, since those act on whatever is on the shared screen.
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import pathlib
import socket
import socketserver
import stat
import struct
import sys
import threading
import time
import traceback

from . import runtime_source
from .lua_wire import CallError, append_commands, call_lua, calls_lua, query_fits_inline, shipped_query
from .tuner import TunerClient, TunerError, LuaError, TAG_OUTPUT

DEFAULT_SOCK = os.environ.get("CIV5_TUNERD_SOCK") or os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "civ5-tuner.sock")
DEFAULT_SEATS = os.environ.get("CIV5_TUNERD_SEATS") or None

OPEN_OPS = frozenset({"ping", "events", "states", "wait_state"})   # no binding needed, even on a daemon with a table
BOUND_OPS = frozenset({"exec", "query", "call", "runtime"})        # the game's Lua: only through a bound connection
UNBOUND_HINT = ('this tunerd binds connections to seats: send {"op": "hello", "token": ...} as the first message '
                "(the harness client does when CIV5_TUNERD_TOKEN is set), or connect as a listed user")
FREE_LUA_HINT = ('a seat-bound connection sends named runtime calls ({"op": "call", "fn": ..., "args": [...]}) to '
                 "InGame, never Lua text")
POPUP_SHIM = pathlib.Path(__file__).with_name("lua") / "generic_popup_shim.lua"
_RUNTIME_GONE = ("attempt to index global 'H'", "attempt to call field '_call'", "attempt to index field '_seat_slot'")


class SeatTable:
    """Who may hold which seat: tokens (presented in a first `hello`) and peer uids (verified by the kernel).

    Loaded once at start from a JSON file. An empty table (no file) means the daemon binds nothing and
    refuses nothing, which is every solo game. Lookups never log or return the token itself."""

    def __init__(self, entries: list[dict] | None = None, path: str | None = None):
        self.path = path
        self._tokens: list[tuple[str, int]] = []
        self._uids: dict[int, int] = {}
        for i, e in enumerate(entries or []):
            if not isinstance(e, dict) or not isinstance(e.get("seat"), int) or isinstance(e.get("seat"), bool):
                raise ValueError(f"seat table entry {i}: needs an integer \"seat\"")
            seat = e["seat"]
            tok, uid = e.get("token"), e.get("uid")
            if tok is None and uid is None:
                raise ValueError(f"seat table entry {i} (seat {seat}): needs a \"token\" or a \"uid\"")
            if tok is not None:
                if not isinstance(tok, str) or len(tok) < 16:
                    raise ValueError(f"seat table entry {i} (seat {seat}): a token is a string of 16+ characters")
                if any(hmac.compare_digest(tok, t) for t, _ in self._tokens):
                    raise ValueError(f"seat table entry {i} (seat {seat}): the same token appears twice")
                self._tokens.append((tok, seat))
            if uid is not None:
                if not isinstance(uid, int) or isinstance(uid, bool):
                    raise ValueError(f"seat table entry {i} (seat {seat}): a uid is an integer")
                if uid in self._uids and self._uids[uid] != seat:
                    raise ValueError(f"seat table entry {i} (seat {seat}): uid {uid} is already seat {self._uids[uid]}")
                self._uids[uid] = seat

    @classmethod
    def load(cls, path: str) -> "SeatTable":
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("seats"), list) or not data["seats"]:
            raise ValueError(f"{path}: expected {{\"seats\": [{{\"seat\": 0, \"token\": ...}}, ...]}} with at least one entry")
        t = cls(data["seats"], path=path)
        mode = stat.S_IMODE(os.stat(path).st_mode)
        if mode & (stat.S_IRGRP | stat.S_IROTH):
            log(f"warning: {path} is readable by other users (mode {mode:03o}); a token every agent can read binds "
                f"nothing -- chmod 600 it and hand each agent only its own token")
        return t

    def __bool__(self) -> bool:
        return bool(self._tokens or self._uids)

    def seats(self) -> list[int]:
        return sorted({s for _, s in self._tokens} | set(self._uids.values()))

    def seat_for_token(self, token) -> int | None:
        if not isinstance(token, str):
            return None
        found = None
        for t, seat in self._tokens:       # every token compared: a constant-time scan, no early return
            if hmac.compare_digest(t, token):
                found = seat
        return found

    def seat_for_uid(self, uid: int | None) -> int | None:
        return None if uid is None else self._uids.get(uid)


def peer_uid(sock) -> int | None:
    """The connecting process's uid as the kernel reports it (Linux SO_PEERCRED); None when unavailable."""
    try:
        _pid, uid, _gid = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
        return uid
    except (OSError, AttributeError, struct.error):
        return None


class Bridge:
    def __init__(self, host: str, port: int):
        self.host, self.port = host, port
        self.lock = threading.RLock()
        self.client: TunerClient | None = None
        self.events: list[dict] = []      # unsolicited game output
        self.connected_at = 0.0
        self.states_ok = False            # did the live connection's handshake list any Lua states?
        self.last_retry = 0.0
        self._runtime: tuple[int, str] | None = None   # (InGame state id, digest) last seen installed
        self._shim_in: set[int] = set()                 # GenericPopup state ids holding the popup shim
        self._ship_seq = 0

    # -- game side --------------------------------------------------------
    def ensure(self) -> TunerClient:
        """Hand out the live connection, never a stateless one.

        `_connect_with_states` can run out of attempts while the front end is still loading (on a
        slow machine it needs well over the retry budget), and a connection that handshook with 0
        states answers every later LSQ with an empty list too. Caching that one is what wedged the
        daemon until someone restarted it by hand. So a stateless connection is kept only as a
        fallback: the next call retries from scratch, rate-limited so a genuinely still-loading game
        is not hammered, and the first tool call after the main menu appears simply works."""
        with self.lock:
            if self.client is not None and self.states_ok:
                return self.client
            if self.client is not None and time.time() - self.last_retry < 5.0:
                return self.client        # still loading; do not reconnect on every request
            self.last_retry = time.time()
            stale = self.client
            c = self._connect_with_states(attempts=2, delay=2.0) if stale else self._connect_with_states()
            if stale is not None and c is not stale:
                try:
                    stale.close()
                except OSError:
                    pass
            self.client, self.connected_at = c, time.time()
            return self.client

    def _connect_with_states(self, attempts: int = 6, delay: float = 5.0) -> TunerClient:
        """Connect and handshake, insisting on a non-empty Lua state list.

        The game's tuner port starts listening well before the front end creates its Lua
        contexts, so `launch_civ5.sh && python -m harness.tunerd` (what the README says to
        do) reliably lands in the gap: the handshake succeeds, reports `0 lua states`, and
        that connection then answers every later LSQ with an empty list too -- every tool
        fails with "Lua state 'X' did not appear" until someone restarts the daemon by hand.
        A game that has reached the main menu always has states (~48), so an empty list means
        "too early", and the only fix is a fresh connection. Safe to reconnect here because
        the LD_PRELOAD shim lets the game re-accept; without it the retries simply fail and
        we keep the last connection rather than wedging the port."""
        last = None
        for i in range(attempts):
            c = TunerClient(self.host, self.port, timeout=15).connect(retries=2, delay=0.5)
            states = c.handshake()
            self.states_ok = bool(states)
            if states or i == attempts - 1:
                log(f"connected to game tuner; {len(states)} lua states; app={c.app[:60]!r}"
                    + ("" if states else " -- still no states; will retry on the next request"))
                return c
            log(f"game tuner has 0 lua states (front end still loading); reconnecting in {delay}s")
            last = c
            try:
                c.close()
            except OSError:
                pass
            time.sleep(delay)
        return last  # unreachable: the loop returns on its last iteration

    def drop(self):
        with self.lock:
            if self.client:
                try:
                    self.client.close()
                finally:
                    self.client = None
                    self.states_ok = False
                    self._runtime = None
                    self._shim_in.clear()
            log("game connection dropped; will reconnect (game must re-arm its listener)")

    # -- the runtime and the call op ----------------------------------------
    def _ship(self, c: TunerClient, state: int | str, src: str) -> str:
        """Put `src` into a fresh global of `state` in byte-budgeted pieces; returns the global's name."""
        self._ship_seq += 1
        var = f"__H_SRC_tunerd_{os.getpid()}_{self._ship_seq}"
        c.execute(state, f"{var} = ''")
        for cmd in append_commands(var, src):
            c.execute(state, cmd)
        return var

    def _load(self, c: TunerClient, state: int | str, src: str, name: str, timeout: float = 30) -> None:
        var = self._ship(c, state, src)
        c.execute(state, f"local f, err = loadstring({var}, '{name}'); {var} = nil; if not f then error(err, 0) end; f()",
                  timeout=timeout)

    def ensure_runtime(self, c: TunerClient, force: bool = False) -> dict:
        """The Lua runtime in InGame, from the source on disk now (an edit deploys at the next call, one installer
        instead of one per client process), plus the popup shim in GenericPopup when that state exists. Cached per
        (InGame state id, digest): a loaded save rebuilds the state under a new id, a changed fragment changes
        the digest, and a call that finds H gone (`_RUNTIME_GONE`) clears the cache and installs again."""
        src = runtime_source.snapshot()
        sid = c.find_state("InGame", refresh=False)
        installed = False
        if force or self._runtime != (sid, src.digest):
            out = [] if force else c.execute(
                "InGame", f"print(type(H) == 'table' and H.source_hash == '{src.digest}' and type(H._call) == 'function')").output
            if not (out and out[-1] == "true"):
                var = self._ship(c, "InGame", src.text)
                self._load(c, "InGame", src.install_lua(var), "harness_runtime_install")
                installed = True
                log(f"runtime v{src.version} ({src.digest[:12]}) installed in InGame state {sid}")
            self._runtime = (sid, src.digest)
        shim = self._ensure_popup_shim(c)
        return {"ok": True, "version": src.version, "digest": src.digest, "installed": installed, "popup_shim": shim}

    def _ensure_popup_shim(self, c: TunerClient) -> bool:
        """The button shim in GenericPopup (harness/lua/generic_popup_shim.lua), once per state id."""
        try:
            sid = c.find_state("GenericPopup", refresh=False)
        except (TunerError, KeyError):
            return False
        if sid in self._shim_in:
            return True
        ok = c.query(sid, "return __H_BTN_SHIM == true and type(__H_answer_popup) == 'function'")
        if not ok:
            self._load(c, sid, POPUP_SHIM.read_text(), "harness_popup_shim")
        self._shim_in.add(sid)
        return True

    def _query_body(self, c: TunerClient, body: str, timeout):
        """A query whose body the daemon wrote: inline when it fits, shipped in chunks when it does not."""
        if query_fits_inline(body):
            return c.query("InGame", body, timeout=timeout)
        var = self._ship(c, "InGame", body)
        return c.query("InGame", shipped_query(var), timeout=timeout)

    def call(self, c: TunerClient, req: dict, binding: int | None) -> dict:
        """`call`: the seat is the connection's binding, or the request's on a daemon that binds nothing."""
        want = req.get("seat")
        if want is not None and (not isinstance(want, int) or isinstance(want, bool)):
            return {"ok": False, "error": "call: seat is an integer"}
        if binding is None and want is None:
            return {"ok": False, "error": "call: no seat -- bind this connection (a seat table) or send \"seat\""}
        if binding is not None and want is not None and want != binding:
            return {"ok": False, "error": f"this connection is bound to seat {binding}", "seat": binding}
        seat = binding if binding is not None else want
        try:
            body = calls_lua(seat, req["calls"]) if "calls" in req else call_lua(req.get("fn"), seat, req.get("args"))
        except CallError as e:
            return {"ok": False, "error": str(e)}
        self.ensure_runtime(c)
        try:
            return {"ok": True, "value": self._query_body(c, body, req.get("timeout")), "seat": seat}
        except LuaError as e:
            if not any(s in str(e) for s in _RUNTIME_GONE):
                raise
            self._runtime = None          # H is gone from a state that kept its id: install and run once more
            self.ensure_runtime(c)
            return {"ok": True, "value": self._query_body(c, body, req.get("timeout")), "seat": seat}

    def _is_ingame(self, c: TunerClient, state) -> bool:
        return state == "InGame" or (isinstance(state, int) and c.states.get(state) == "InGame")

    def free_lua_refusal(self, c: TunerClient, req: dict, seat: int) -> dict | None:
        """Why a bound connection's `exec` / `query` is not forwarded: Lua text never reaches InGame, and a
        screen state (a popup, the leader screen) only while this seat is the active player, since it acts on
        whatever the shared screen shows. The front end (no InGame state) has no player and stays open."""
        state = req.get("state")
        if self._is_ingame(c, state):
            return {"ok": False, "error": FREE_LUA_HINT, "bound": seat}
        if "InGame" not in c.states.values():
            return None
        try:
            active = c.query("InGame", "return Game.GetActivePlayer()")
        except (TunerError, LuaError):
            return None
        if active is not None and active != seat:
            return {"ok": False, "error": f"seat {seat} is not the active player: the screen is not this seat's to read or press",
                    "bound": seat, "active_player": active}
        return None

    def pump_unsolicited(self):
        """Background: while idle, collect anything the game prints on its own."""
        while True:
            time.sleep(0.25)
            with self.lock:
                c = self.client
                if c is None:
                    try:
                        self.ensure()
                    except (OSError, ConnectionError):
                        pass
                    continue
                try:
                    for m in c.drain(0.05):
                        if m.tag == TAG_OUTPUT:
                            text = m.payload.removeprefix("O\x00")
                            self.events.append({"t": time.time(), "text": text})
                            if len(self.events) > 5000:
                                del self.events[:1000]
                except ConnectionError:
                    self.drop()

    # -- request handling -------------------------------------------------
    def handle(self, req: dict, seat: int | None = None) -> dict:
        """One request. `seat` is the connection's binding (None on a daemon without a table, or unbound);
        the Handler has already refused what an unbound connection may not do. Here the binding decides
        two things: the seat a `call` is written with, and whether Lua text is forwarded at all."""
        op = req.get("op")
        if op == "ping":
            return {"ok": True, "connected": self.client is not None, "since": self.connected_at}
        if op == "events":
            since = int(req.get("since", 0))
            return {"ok": True, "events": self.events[since:], "next": len(self.events)}
        with self.lock:
            c = self.ensure()
            try:
                if op == "states":
                    st = c.refresh_states()
                    return {"ok": True, "states": {str(k): v for k, v in st.items()}}
                if op == "wait_state":
                    sid = c.wait_for_state(req["name"], timeout=float(req.get("timeout", 120)))
                    return {"ok": True, "id": sid}
                if op == "call":
                    return self.call(c, req, seat)
                if op == "runtime":
                    return self.ensure_runtime(c, force=bool(req.get("force")))
                if op in ("exec", "query") and seat is not None:
                    refusal = self.free_lua_refusal(c, req, seat)
                    if refusal is not None:
                        return refusal
                if op == "exec":
                    r = c.execute(req["state"], req["lua"], timeout=req.get("timeout"), raise_on_error=False)
                    return {"ok": r.error is None, "output": r.output, "error": r.error}
                if op == "query":
                    v = c.query(req["state"], req["lua"], timeout=req.get("timeout"))
                    return {"ok": True, "value": v}
                return {"ok": False, "error": f"unknown op {op!r}"}
            except LuaError as e:
                return {"ok": False, "error": str(e)}
            except (ConnectionError, BrokenPipeError) as e:
                self.drop()
                return {"ok": False, "error": f"game connection lost: {e}"}
            except (TunerError, KeyError, TimeoutError, runtime_source.RuntimeSourceError) as e:
                return {"ok": False, "error": str(e)}
            except OSError as e:  # ConnectionError is an OSError and was caught above
                return {"ok": False, "error": f"game tuner not reachable: {e}"}


def log(msg: str):
    print(f"[tunerd {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def gate(req: dict, table: SeatTable | None, seat: int | None, first: bool) -> tuple[dict | None, int | None, bool]:
    """The per-connection seat rule, pure so a test can read it without a socket.

    Returns (reply, seat, close): a reply means the request is answered here and never reaches the
    bridge; `seat` is the connection's binding after this message; `close` ends the connection.
    `first` is whether this is the connection's first message."""
    op = req.get("op")
    if op == "hello":
        if table is None or not table:
            return {"ok": True, "bound": False, "seat": None}, seat, False   # no table: a hello is a no-op
        if not first:
            return {"ok": False, "error": "hello must be the first message on a connection"}, seat, False
        found = table.seat_for_token(req.get("token"))
        if found is None:
            return {"ok": False, "error": "unknown seat token"}, seat, True
        if seat is not None and seat != found:
            return {"ok": False, "error": "the token names another seat than this user's"}, seat, True
        return {"ok": True, "bound": True, "seat": found}, found, False
    if table and seat is None and op in BOUND_OPS:
        return {"ok": False, "error": UNBOUND_HINT, "unbound": True}, seat, False
    if table and op not in OPEN_OPS and op not in BOUND_OPS and op is not None:
        return {"ok": False, "error": f"unknown op {op!r}"}, seat, False
    return None, seat, False


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        table: SeatTable | None = getattr(self.server, "seats", None)
        seat: int | None = None
        if table:
            uid = peer_uid(self.request)
            seat = table.seat_for_uid(uid)
            if seat is not None:
                log(f"connection from uid {uid} bound to seat {seat}")
        first = True
        for line in self.rfile:
            line = line.strip()
            if not line:
                continue
            close = False
            try:
                req = json.loads(line)
                resp, seat, close = gate(req, table, seat, first)
                if resp is None:
                    resp = self.server.bridge.handle(req, seat=seat)
                elif req.get("op") == "hello" and resp.get("bound"):
                    log(f"connection bound to seat {seat} by token")
            except Exception as e:
                resp = {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]}
            first = False
            try:
                self.wfile.write((json.dumps(resp) + "\n").encode())
            except BrokenPipeError:
                # the client gave up (timed out / was killed) before the reply: not our problem, no traceback
                return
            self.wfile.flush()
            if close:
                return


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sock", default=DEFAULT_SOCK)
    ap.add_argument("--host", default=os.environ.get("CIV5_TUNER_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("CIV5_TUNER_PORT", "4318")))
    ap.add_argument("--seats", default=DEFAULT_SEATS, metavar="FILE",
                    help="seat table (JSON); with it, exec/query need a connection bound by token or uid")
    a = ap.parse_args(argv)
    seats = None
    if a.seats:
        try:
            seats = SeatTable.load(a.seats)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            sys.exit(f"tunerd: cannot use the seat table: {e}")
    if os.path.exists(a.sock):
        os.unlink(a.sock)
    bridge = Bridge(a.host, a.port)
    srv = Server(a.sock, Handler)
    srv.bridge = bridge
    srv.seats = seats
    threading.Thread(target=bridge.pump_unsolicited, daemon=True).start()
    threading.Thread(target=bridge.ensure, daemon=True).start()
    log(f"listening on {a.sock}; game tuner at {a.host}:{a.port}"
        + (f"; seats bound from {a.seats} (seats {seats.seats()}): exec/query need a bound connection" if seats
           else "; no seat table: any client, any Lua"))
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
        if os.path.exists(a.sock):
            os.unlink(a.sock)


if __name__ == "__main__":
    main()
