"""What crosses the wire as Lua, written by the trusted side: literals, the command budget, and the one call
shape a seat-bound client may send (docs/ROADMAP.md "A seat bound to its channel", stage 3).

A client of tunerd names a runtime entry and its arguments as JSON (`{"op": "call", "fn": "tactical_view",
"args": [5, 2, "full"]}`); the daemon writes the Lua here, with the connection's seat, and ships it. Nothing in
this module touches a socket or the game: it is imported by harness/tunerd.py (which writes the Lua) and by
harness/game.py (which renders the same text for its test doubles and the call ledger), and tested on its
own. The encoders used to live in harness/game_parts/support.py, which re-exports them.
"""
from __future__ import annotations

from .tuner import TunerClient

Q_MARGIN = 64   # headroom under the tuner's command limit for the `CMD:<state>:` framing and the trailing NUL


def lua_str(s: str) -> str:
    """Encode a Python str as a Lua double-quoted literal (safe for any bytes, incl. NUL and control chars)."""
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch == '"': out.append('\\"')
        elif ch == "\\": out.append("\\\\")
        elif ch == "\n": out.append("\\n")
        elif ch == "\r": out.append("\\r")
        elif ch == "\t": out.append("\\t")
        elif o < 32 or o == 127: out.append("\\%03d" % o)
        else: out.append(ch)
    out.append('"')
    return "".join(out)


def lua_str_len(ch: str) -> int:
    """UTF-8 bytes `lua_str` emits for one character -- the unit the tuner's command limit counts in.

    Kept next to `lua_str` so the two cannot drift: `tests/test_query_chunking.py` checks that summing
    this over a string plus the two quotes equals the encoded length of `lua_str`."""
    o = ord(ch)
    if ch in '"\\\n\r\t':
        return 2
    if o < 32 or o == 127:
        return 4
    return len(ch.encode("utf-8"))


def lua_table(v) -> str:
    """Encode a JSON-shaped Python value (dict/list/str/number/bool/None) as a Lua literal."""
    if v is None:
        return "nil"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return lua_str(v)
    if isinstance(v, dict):
        return "{" + ", ".join(f"[{lua_str(str(k))}]={lua_table(x)}" for k, x in v.items()) + "}"
    if isinstance(v, (list, tuple)):
        return "{" + ", ".join(lua_table(x) for x in v) + "}"
    raise TypeError(f"cannot encode {type(v).__name__} as Lua")


# ------------------------------------------------------------------ the command budget and chunking
def command_budget() -> int:
    """Bytes one tuner command may carry after framing, under COMMAND_MAX with Q_MARGIN to spare."""
    return TunerClient.COMMAND_MAX - Q_MARGIN


def query_fits_inline(code: str) -> bool:
    """Whether the *encoded* wrapped query stays under the tuner's limit.

    `len(code)` counts characters; the tuner counts bytes after UTF-8 encoding. A body of 1000 CJK characters
    is 3000 bytes and used to go inline on the strength of its character count, so the tuner cut it and the
    game answered a bare "Syntax Error" (GAPS §0 / GitLab #3)."""
    wrapped = TunerClient._wrap_query(TunerClient, code)
    return len(wrapped.encode("utf-8")) <= command_budget()


def string_chunks(src: str, prefix: str) -> list[str]:
    """Cut `src` so that `prefix .. lua_str(piece)` fits one tuner command *after* escaping.

    Escaping is what used to break the fixed 1500-character cut: 1500 backslashes escape to 3000 bytes, and
    1500 CJK characters encode to 4500. The cut is made on the escaped byte count of each character
    (`lua_str_len`), never on characters."""
    room = command_budget() - len(prefix.encode("utf-8")) - 2   # the two quotes
    if room < 4:
        raise ValueError(f"no room for a string chunk under prefix {prefix!r}")
    pieces, start, used = [], 0, 0
    for i, ch in enumerate(src):
        n = lua_str_len(ch)
        if used + n > room:
            pieces.append(src[start:i])
            start, used = i, 0
        used += n
    if start < len(src) or not pieces:
        pieces.append(src[start:])
    return pieces


def append_commands(var: str, src: str) -> list[str]:
    """The `{var} = {var} .. "..."` commands that ship `src` into the Lua global `var`, each one under
    `command_budget()` bytes once encoded."""
    prefix = f"{var} = {var} .. "
    return [prefix + lua_str(piece) for piece in string_chunks(src, prefix)]


def shipped_query(var: str) -> str:
    """The query body that compiles and runs a source shipped into the global `var` (and clears it)."""
    return (f"local src = {var}; {var} = nil; "
            f"local f, err = loadstring(src, 'q'); if not f then error(err, 0) end; return f()")


# ------------------------------------------------------------------ the call shape
class CallError(ValueError):
    """A `call` request that cannot be written as Lua (a bad name, non-JSON arguments)."""


def check_fn(fn) -> str:
    """The bare entry name of a `call`: `H.` is stripped, anything but an identifier is refused."""
    if not isinstance(fn, str):
        raise CallError("call: fn must be the name of a runtime entry")
    name = fn[2:] if fn.startswith("H.") else fn
    if not name.isidentifier() or name.startswith("_"):
        raise CallError(f"call: {fn!r} is not the name of a runtime entry")
    return name


def check_args(args) -> list:
    if args is None:
        return []
    if not isinstance(args, (list, tuple)):
        raise CallError("call: args must be a JSON array")
    return list(args)


def call_expr(name: str, seat: int, args: list) -> str:
    """`H._call("name", seat, {args}, n)`: the dispatcher in harness/lua/runtime/dispatch.lua inserts `seat` at
    the entry's own seat slot. `n` travels because a nil argument leaves a hole `#` cannot count."""
    return f"H._call({lua_str(name)}, {int(seat)}, {lua_table(list(args))}, {len(args)})"


def call_lua(fn, seat: int, args=None) -> str:
    """The whole query body for one call."""
    return "return " + call_expr(check_fn(fn), seat, check_args(args))


def calls_lua(seat: int, calls) -> str:
    """Several calls in one trip, answered as a Lua array (so as a JSON list) in the order given. A nil result
    leaves a hole, exactly as the composed `return {H.a(...), H.b(...)}` bodies this replaces did."""
    if not isinstance(calls, (list, tuple)) or not calls:
        raise CallError("calls: a non-empty JSON array of [fn, args]")
    parts = []
    for item in calls:
        if isinstance(item, dict):
            fn, args = item.get("fn"), item.get("args")
        elif isinstance(item, (list, tuple)) and 1 <= len(item) <= 2:
            fn, args = item[0], (item[1] if len(item) == 2 else None)
        else:
            raise CallError("calls: each item is [fn, args] or {fn, args}")
        parts.append(call_expr(check_fn(fn), seat, check_args(args)))
    return "return {" + ", ".join(parts) + "}"
