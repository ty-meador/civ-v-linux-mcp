"""One InGame query through the raw client, shipped in chunks when the body would not fit one tuner command.

`Game.q` does the same (harness/game.py: the tuner truncates a command at COMMAND_MAX and the game answers a bare
"Syntax Error" quoting the cut-off source; live 2026-09-29, the map dump) but calls ensure_runtime first, which a
spectator must never do (see the package docstring). This borrows Game's chunking classmethods and nothing else.
The global name is the spectator's own so it never interleaves with a seat server's `__H_Q...` shipments.
"""
from __future__ import annotations

from typing import Any

from ..game import Game

VAR = "__H_SPECTATOR_Q"
LOADER = (f"local src = {VAR}; {VAR} = nil; local f, err = loadstring(src, 'spectator'); "
          "if not f then error(err, 0) end; return f()")


def query(client: Any, code: str, timeout: float | None = None):
    if Game.q_fits_inline(code):
        return client.query("InGame", code, timeout=timeout)
    client.exec("InGame", f"{VAR} = ''")
    for cmd in Game.append_commands(VAR, code):
        client.exec("InGame", cmd)
    return client.query("InGame", LOADER, timeout=timeout)
