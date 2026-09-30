"""The runtime's event ring, unfiltered.

The seat servers read `H.events_since(seq, pid)`, which returns only the rows whose audience is that seat. The
spectator reads the ring itself and keeps every row's `audience`, so the page can colour it by seat. `H` is nil
until a seat server has installed the runtime: the read then answers empty and the cursor stays put.
"""
from __future__ import annotations

from typing import Any

LUA = """
if not H or not H.events then return { events = {}, seq = 0 } end
local since = %d
local out = {}
for _, e in ipairs(H.events) do
  if e.seq > since then out[#out + 1] = e end
end
return { events = out, seq = H.event_seq or 0 }
"""


def read(client: Any, since: int, timeout: float = 30) -> tuple[list[dict], int]:
    """Events with seq > since and the ring's current seq. A ring that was reset (a reload, a new game) reports a
    smaller seq than the cursor; the caller starts over from 0 then."""
    r = client.query("InGame", LUA % int(since), timeout=timeout)
    if not isinstance(r, dict):
        return [], since
    events = r.get("events") if isinstance(r.get("events"), list) else []
    seq = r.get("seq") if isinstance(r.get("seq"), int) else since
    return [e for e in events if isinstance(e, dict)], seq
