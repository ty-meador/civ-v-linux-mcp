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

    def refresh_states(self) -> dict[int, str]:
        self.send(TAG_HANDSHAKE, "LSQ:")
        m = self.recv()
        parts = [p for p in (m.payload.split("\x00") if m else [])]
        states: dict[int, str] = {}
        for i in range(0, len(parts) - 1, 2):
            try:
                states[int(parts[i])] = parts[i + 1]
            except ValueError:
                pass
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
    local isarr = n > 0
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

    def query(self, state: int | str, lua_body: str, timeout: float | None = None):
        """Run `lua_body` (which must `return` a value) and get it back as JSON.

        Output is fenced with a sentinel so unrelated print() chatter from the game
        can be discarded."""
        self.install_helpers(state)
        src = ("local __f = function() " + lua_body + " end; "
               "local __ok, __r = pcall(__f); "
               "if __ok then print('@@HJ@@' .. __hjson(__r) .. '@@HJ@@') "
               "else error(__r, 0) end")
        res = self.execute(state, src, timeout=timeout)
        blob = "".join(res.output)
        start, end = blob.find("@@HJ@@"), blob.rfind("@@HJ@@")
        if start < 0 or end <= start:
            raise TunerError(f"no JSON sentinel in output: {res.output[:5]}")
        return json.loads(blob[start + 6:end])


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
