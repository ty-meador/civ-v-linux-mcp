"""The main menu: loading and leaving games.

One of the civ5 MCP server's tool modules: every tool here registers on the server in
harness/mcp_server.py, which keeps the game handle, the guard and the tool sets (see its docstring).
"""
from __future__ import annotations

import os
import time

from harness.client import TunerdError

from harness import mcp_server as core
from harness.mcp_server import mcp, J, _resolve_seat, guarded


def _loaded_new_game(r: dict) -> dict:
    """After a load: the seat gets detected afresh (an auto seat from the previous game may be wrong for
    this one) and the answer says which seat the server is on."""
    g = core.game()
    if r.get("ok") and os.environ.get("CIV5_SEAT", "auto") == "auto":
        g._mode = None
        core._seat_rechecked = False
        core._seat_unresolved = not _resolve_seat(g)
    r["seat"] = g.seat
    return r


@mcp.tool()
@guarded
def load_save(filename: str) -> str:
    """Load a save from the main menu by its bare name, no path or .Civ5Save extension (e.g. "QuickSave",
    or "Sejong_0180 AD-1200" for a manual save). Only works from a fresh main-menu state, not mid-game:
    exit_to_main_menu first. The answer carries `seat`, the player this server will play in the loaded
    game (auto seats are detected afresh; hotseat keeps the default, set_seat changes it)."""
    return J(_loaded_new_game(core.game().load_save(filename)))


@mcp.tool()
@guarded
def load_latest() -> str:
    """Crash-recovery: load whichever save (quicksave OR autosave) has the newest filesystem mtime,
    regardless of name. Prefer this over load_save("QuickSave") when resuming after a crash -- an
    autosave made during play can be newer than the last explicit quicksave, and load_save only checks
    quick/manual saves before ever considering autosaves. Only works from a fresh main-menu state:
    exit_to_main_menu first. The answer carries `seat` like load_save."""
    return J(_loaded_new_game(core.game().load_latest()))


@mcp.tool()
@guarded
def exit_to_main_menu(save: bool = True) -> str:
    """Leave the loaded game for the main menu, so load_save / load_latest can open another save. Quick-saves
    first when it is my turn in a solo game (save=false skips that); in a game with other people ask the
    human before leaving, as it ends the game for them too. Waits until the main menu is on screen.
    Usable while it is not my turn."""
    g = core.game()
    if not g.has_state("InGame"):
        return J({"ok": True, "already": True, "screen": g.front_end_screen(), "seat": g.seat})
    saved = False
    if save:
        try:
            ts = g.turn_state()
            if ts.get("mode") == "single" and ts.get("my_turn") and not ts.get("processing"):
                g.quick_save()
                saved = True
        except (TunerdError, TimeoutError, OSError, ValueError, KeyError):
            saved = False
    g.leave_to_main_menu()
    deadline = time.monotonic() + 45
    screen = "?"
    while time.monotonic() < deadline:
        try:
            screen = g.front_end_screen()
        except (TunerdError, TimeoutError, OSError):
            screen = "?"
        if screen == "MainMenu":
            break
        time.sleep(1.0)
    return J({"ok": screen == "MainMenu", "screen": screen, "saved": saved, "seat": g.seat,
              "hint": "load_save(filename) or load_latest opens a game" if screen == "MainMenu"
              else "the main menu has not appeared yet; turn_status reports the screen"})
