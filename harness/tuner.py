"""FireTuner client for Sid Meier's Civilization V (Linux/Aspyr build 1.0.3.279).

With `EnableTuner = 1` in config.ini the game listens on TCP 0.0.0.0:4318 and
speaks the Firaxis "Nexus" tuner protocol, verified live against this build:

    frame     := uint32 LE payload_len | int32 LE tag | payload (NUL terminated)
    tag 4     handshake:  "APP:" -> app identity ("Civ5\0Sid Meier's Civilization V\0<dir>\0...")
                           "LSQ:" -> Lua states as NUL-separated (id, name) pairs
    tag 3     command:    "CMD:<state_id>:<lua source>"
    replies:  tag -1 "O\0<text>"   one per print() line (text is prefixed "<Context>: "
                                    for UI contexts, no prefix for "Main State")
              tag  3 ""            command finished OK
              tag  3 "ERR:..."     syntax / runtime error (with traceback)

`return` values are NOT echoed; everything must go through print().  Each UI
context (FrontEnd, MainMenu, InGame, ...) is its own Lua state; state ids are
stable for the life of a context and are NOT dense (id 1 does not exist).
"""
from __future__ import annotations

import json
import socket
import struct
import time
from dataclasses import dataclass, field

HEADER = struct.Struct("<Ii")
TAG_HELP, TAG_COMMAND, TAG_HANDSHAKE, TAG_OUTPUT = 1, 3, 4, -1
DEFAULT_ADDR = ("127.0.0.1", 4318)


class TunerError(RuntimeError):
    pass


class LuaError(TunerError):
    pass


@dataclass
class Message:
    tag: int
    payload: str


@dataclass
class ExecResult:
    output: list[str]           # print() lines, context prefix stripped
    error: str | None = None    # "ERR:..." text if the command failed

    @property
    def text(self) -> str:
        return "\n".join(self.output)


@dataclass
class TunerClient:
    host: str = DEFAULT_ADDR[0]
    port: int = DEFAULT_ADDR[1]
    timeout: float = 10.0
    sock: socket.socket | None = field(default=None, repr=False)
    _buf: bytes = field(default=b"", repr=False)
    app: str = ""
    states: dict[int, str] = field(default_factory=dict)   # id -> context name

    # -- connection -------------------------------------------------------
    def connect(self, retries: int = 1, delay: float = 1.0) -> "TunerClient":
        last: Exception | None = None
        for _ in range(max(1, retries)):
            try:
                self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
                self.sock.settimeout(self.timeout)
                self._buf = b""
                return self
            except OSError as e:
                last = e
                time.sleep(delay)
        raise ConnectionError(f"tuner port {self.host}:{self.port} not reachable: {last}")

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()

    # -- framing ----------------------------------------------------------
    def send(self, tag: int, payload: str) -> None:
        assert self.sock, "not connected"
        data = payload.encode("utf-8") + b"\x00"
        self.sock.sendall(HEADER.pack(len(data), tag) + data)

    def recv(self, timeout: float | None = None) -> Message | None:
        assert self.sock, "not connected"
        self.sock.settimeout(self.timeout if timeout is None else timeout)
        try:
            while True:
                if len(self._buf) >= HEADER.size:
                    ln, tag = HEADER.unpack_from(self._buf)
                    if len(self._buf) >= HEADER.size + ln:
                        raw = self._buf[HEADER.size:HEADER.size + ln]
                        self._buf = self._buf[HEADER.size + ln:]
                        return Message(tag, raw.rstrip(b"\x00").decode("utf-8", "replace"))
                chunk = self.sock.recv(1 << 16)
                if not chunk:
                    raise ConnectionError("tuner socket closed by game")
                self._buf += chunk
        except socket.timeout:
            return None

    def drain(self, quiet: float = 0.2) -> list[Message]:
        out: list[Message] = []
        while (m := self.recv(timeout=quiet)) is not None:
            out.append(m)
        return out

    # -- protocol ---------------------------------------------------------
    def handshake(self) -> dict[int, str]:
        self.drain(0.2)
        self.send(TAG_HANDSHAKE, "APP:")
        m = self.recv()
        self.app = m.payload.replace("\x00", " | ") if m else ""
        return self.refresh_states()

    def refresh_states(self, retry: bool = True) -> dict[int, str]:
        self.send(TAG_HANDSHAKE, "LSQ:")
        m = self.recv()
        # A frame of another tag can arrive first (a late print from the previous command, tuner chatter):
        # it is not the list. Live 2026-09-27 (Codex, t58): one finish_turn failed with "no Lua state named
        # 'InGame'; have []" in a game that had 48 states before and after.
        for _ in range(8):
            if m is None or m.tag == TAG_HANDSHAKE:
                break
            m = self.recv(timeout=2.0)
        payload = m.payload if m else ""
        # a long state list may be split over several handshake frames: absorb any that follow quickly
        while (extra := self.recv(timeout=0.15)) is not None:
            if extra.tag == TAG_HANDSHAKE:
                payload += ("\x00" if payload and not payload.endswith("\x00") else "") + extra.payload
        parts = [p for p in payload.split("\x00")]
        states: dict[int, str] = {}
        for i in range(0, len(parts) - 1, 2):
            try:
                states[int(parts[i])] = parts[i + 1]
            except ValueError:
                pass
        if not states and self.states and retry:
            # an empty answer where there were states a moment ago is a bad read until asked twice
            return self.refresh_states(retry=False)
        self.states = states
        return states

    def find_state(self, name: str, refresh: bool = True, last: bool = True) -> int:
        """Return the id of the Lua state whose context name == `name`.

        Names are not unique (e.g. several SelectCivilization contexts); by default
        the most recently created (highest id) match wins."""
        if refresh or not self.states:
            self.refresh_states()
        ids = [i for i, n in self.states.items() if n == name]
        if not ids:
            raise KeyError(f"no Lua state named {name!r}; have {sorted(set(self.states.values()))}")
        return max(ids) if last else min(ids)

    def wait_for_state(self, name: str, timeout: float = 120.0, poll: float = 1.0) -> int:
        deadline = time.monotonic() + timeout
        while True:
            try:
                return self.find_state(name)
            except KeyError:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Lua state {name!r} did not appear within {timeout}s")
                time.sleep(poll)

    def execute(self, state: int | str, lua: str, timeout: float | None = None, raise_on_error: bool = True) -> ExecResult:
        """Run `lua` in a state; collect print() output until the completion ack."""
        sid = state if isinstance(state, int) else self.find_state(state)
        prefix = f"{self.states.get(sid, '')}: "
        self.send(TAG_COMMAND, f"CMD:{sid}:{lua}")
        out: list[str] = []
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while True:
            m = self.recv(timeout=max(0.05, deadline - time.monotonic()))
            if m is None:
                raise TunerError(f"timeout waiting for completion of command in state {sid}: {lua[:80]!r}")
            if m.tag == TAG_OUTPUT:
                text = m.payload[2:] if m.payload.startswith("O\x00") else m.payload
                if prefix != ": " and text.startswith(prefix):
                    text = text[len(prefix):]
                out.append(text)
            elif m.tag == TAG_COMMAND:
                if m.payload.startswith("ERR:"):
                    if raise_on_error:
                        raise LuaError(m.payload)
                    return ExecResult(out, m.payload)
                return ExecResult(out)
            # other tags: ignore (tuner UI chatter)

    # -- conveniences -----------------------------------------------------
    def eval(self, state: int | str, expr: str) -> str:
        """print() a Lua expression's value(s) and return the text."""
        return self.execute(state, f"print({expr})").text

    _JSON_HELPER = r'''
if not __hjson then
function __hjson(v, depth)
  depth = depth or 0
  local t = type(v)
  if t == "nil" then return "null"
  elseif t == "boolean" then return v and "true" or "false"
  elseif t == "number" then
    if v ~= v or v == math.huge or v == -math.huge then return "null" end
    if v == math.floor(v) then return string.format("%d", v) end
    return string.format("%.6g", v)
  elseif t == "string" then
    return '"' .. v:gsub('[%c"\\]', function(c)
      if c == '"' then return '\\"' elseif c == '\\' then return '\\\\'
      elseif c == '\n' then return '\\n' elseif c == '\r' then return '\\r' elseif c == '\t' then return '\\t'
      else return string.format('\\u%04x', c:byte()) end end) .. '"'
  elseif t == "table" then
    if depth > 12 then return '"<deep>"' end
    local n = #v
    local isarr = n > 0 or next(v) == nil
    if isarr then
      local parts = {}
      for i = 1, n do parts[i] = __hjson(v[i], depth + 1) end
      return "[" .. table.concat(parts, ",") .. "]"
    end
    local parts = {}
    for k, val in pairs(v) do
      parts[#parts + 1] = '"' .. tostring(k) .. '":' .. __hjson(val, depth + 1)
    end
    return "{" .. table.concat(parts, ",") .. "}"
  else return '"<' .. t .. '>"' end
end
end
'''

    def install_helpers(self, state: int | str) -> None:
        self.execute(state, self._JSON_HELPER)

    # Civ5's own print()->Tuner OUTPUT relay silently truncates any single print() call's payload
    # past ~4085 bytes (confirmed live via binary search: 4071-byte Lua string round-trips intact,
    # 4072 comes back as a single mangled 'O' line with the closing sentinel gone) -- almost
    # certainly a fixed ~4096-byte buffer in the native tuner-output code, not anything on our
    # side of the wire (the length-prefixed socket framing itself has no such cap). This silently
    # corrupted every query() call whose JSON result crossed that size, e.g. plots_around with a
    # wide enough radius (37 plots at r=3 -> 3.1KB, fine; 61 plots at r=4 -> 4.4KB, corrupted) --
    # found live pressure-testing the map API, same "accepted but wrong/broken" shape as every
    # other silent-truncation bug in this harness. Fixed generally, not just for plots_around: the
    # JSON is now split into <4KB print() calls, each tagged with the sentinel, and reassembled
    # here by concatenating every matching line in order (still discarding any unrelated print()
    # chatter that doesn't carry the tag).
    _CHUNK = 3500

    # The tuner truncates an inbound command at 2048 bytes and the game then reports a bare
    # "Syntax Error" quoting the cut-off source. Measured live (t193): a query whose wrapped
    # command came to 2003 bytes ran, and the same one at 2093 did not. Callers that decide
    # whether a body still fits inline must budget for QUERY_OVERHEAD, not just the body --
    # game.py's Q_INLINE_MAX did not, and a two-line edit to set_production's guard silently
    # pushed it over.
    COMMAND_MAX = 2048

    def _wrap_query(self, lua_body: str) -> str:
        return ("local __f = function() " + lua_body + " end; "
                "local __ok, __r = pcall(__f); "
                "if __ok then local __s = __hjson(__r); local __i = 1; local __n = #__s; "
                f"while __i <= __n do local __j = math.min(__i + {self._CHUNK - 1}, __n); "
                "print('@@HJ@@' .. __s:sub(__i, __j)); __i = __j + 1 end "
                "else error(__r, 0) end")

    @classmethod
    def query_overhead(cls) -> int:
        """Bytes `query` adds around a body, so callers can size an inline body against COMMAND_MAX."""
        return len(cls._wrap_query(cls, ""))

    def query(self, state: int | str, lua_body: str, timeout: float | None = None):
        """Run `lua_body` (which must `return` a value) and get it back as JSON.

        Output is fenced with a per-chunk sentinel so unrelated print() chatter from the game
        can be discarded, and split into pieces small enough that the game's own print() relay
        won't truncate any single one (see `_CHUNK` above)."""
        self.install_helpers(state)
        src = self._wrap_query(lua_body)
        res = self.execute(state, src, timeout=timeout)
        chunks = [line[6:] for line in res.output if line.startswith("@@HJ@@")]
        if not chunks:
            raise TunerError(f"no JSON sentinel in output: {res.output[:5]}")
        return json.loads("".join(chunks))


if __name__ == "__main__":  # tiny REPL for manual poking:  python -m harness.tuner [StateName]
    import sys
    c = TunerClient().connect(retries=3)
    states = c.handshake()
    print("APP:", c.app)
    for i in sorted(states):
        print(f"  [{i}] {states[i]}")
    sid = c.find_state(sys.argv[1]) if len(sys.argv) > 1 else 0
    print(f"state {sid} ({states.get(sid)}); type lua, 'use <Name|id>', 'states', or 'quit'")
    for line in sys.stdin:
        line = line.strip()
        if line == "quit":
            break
        if line == "states":
            for i, n in sorted(c.refresh_states().items()):
                print(f"  [{i}] {n}")
            continue
        if line.startswith("use "):
            arg = line[4:].strip()
            sid = int(arg) if arg.isdigit() else c.find_state(arg)
            continue
        try:
            r = c.execute(sid, line, raise_on_error=False)
            print(r.text if not r.error else r.error)
        except TunerError as e:
            print("!!", e)
