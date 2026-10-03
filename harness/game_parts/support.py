"""What every part of Game shares: the runtime identity (version and digest of harness/lua/runtime), the Lua
text helpers (lua_str, lua_table, plain_text) and the small pure functions the tools call. harness/game.py
re-exports the public names, so `from harness.game import lua_str` still works.
"""
from __future__ import annotations

import pathlib
import re
from typing import Any

from .. import runtime_source


def _game_busy_error(e: BaseException) -> bool:
    """A tuner failure that means the game is busy, not gone: the state list read empty (the LSQ answer did
    not come in time) or a command ran past its timeout. Read by the wait loop, which polls on."""
    s = str(e)
    return "have []" in s or "timeout waiting for completion" in s or "no Lua state named" in s

# harness/lua, beside game.py: this module lives one level down in game_parts/ (the mixin split of 2026-09-27
# first resolved it as game_parts/lua and every load_save / load_latest failed on the popup shim's path).
LUA_DIR = pathlib.Path(__file__).resolve().parent.parent / "lua"

POPUP_SHIM_LUA = LUA_DIR / "generic_popup_shim.lua"

_SOURCE = runtime_source.snapshot()

RUNTIME_VERSION = _SOURCE.version

RUNTIME_DIGEST = _SOURCE.digest

def spread_effects(before: dict, after: dict) -> dict:
    """What a religious spread actually did, from the target city read either side of the mission.

    Both flags have been wrong in a live game before, in opposite directions:
    * t333, Shanghai went 2 -> 3 of 10 Taoists with no majority at all and read `converted: true`,
      so `converted` stopped meaning "gained followers" and started meaning "the majority is ours";
    * t205, a Catholic Missionary spent its last charge on Cusco -- already Catholic, 4 of 5
      followers -- and read `converted: true` with followers 4 -> 4. The majority *was* ours, and
      had been before the unit moved. So it must now be a change: already-ours is its own flag.
    """
    rel = before.get("unit_religion_name") or before.get("unit_religion")
    eff = {"city": before.get("city"), "city_owner": before.get("city_owner"), "religion": rel,
           "population": before.get("population"),
           "followers_before": before.get("followers"),
           "majority_before": before.get("majority_name", before.get("majority")),
           "spreads_before": before.get("spreads_left")}
    if not after.get("ok"):
        eff["converted"] = eff["gained_followers"] = None  # city could not be re-read after the unit was consumed
        return eff
    eff.update({"followers_after": after.get("followers"),
                "majority_after": after.get("majority_name", after.get("majority")),
                "spreads_left": after.get("spreads_left")})
    if "influence" in before or "influence" in after:
        eff["influence_before"] = before.get("influence"); eff["influence_after"] = after.get("influence")
    eff["gained_followers"] = (after.get("followers") or 0) > (before.get("followers") or 0)
    for k in ("majority_before", "majority_after"):
        if eff.get(k) in (-1, None):
            eff[k] = None
    eff["already_majority"] = eff["majority_before"] is not None and eff["majority_before"] == rel
    eff["converted"] = (eff["majority_after"] is not None and eff["majority_after"] == rel
                        and not eff["already_majority"])
    if eff["already_majority"] and not eff["gained_followers"]:
        eff["note"] = "this city already followed that religion and gained no followers: the charge bought nothing"
    if eff["majority_after"] is None:
        eff["note"] = "no religion holds a majority in this city now; another spread can tip it"
    return eff

def _newest_save(candidates: list[str]) -> str:
    """Disambiguate save-file candidates that share a display basename (e.g. the native F5 hotkey's
    `Saves/single/QuickSave.Civ5Save` vs. `quick_save()`'s own `Saves/single/quick/QuickSave.Civ5Save` --
    two genuinely different files that both display as "QuickSave") by real filesystem mtime instead of
    trusting `UI.SaveFileList()`'s return order, which picked the stale one live (see `load_save`'s
    docstring). The raw path is a real Linux path with backslash separators (Windows-port quirk), so this
    swaps them and stats directly. Falls back to the first candidate if none can be stat'd (e.g. a
    permissions issue) rather than hard-failing -- matches the old behavior in that case."""
    if len(candidates) == 1:
        return candidates[0]

    def mtime(p: str) -> float:
        try:
            return pathlib.Path(p.replace("\\", "/")).stat().st_mtime
        except OSError:
            return -1.0

    best = max(candidates, key=mtime)
    return best if mtime(best) >= 0 else candidates[0]

TODO_DETAIL_LEVELS = ("summary", "normal", "full")

ROUTINE_ACTIONS = ("MISSION_MOVE_TO", "MISSION_ROUTE_TO", "MISSION_SWAP_UNITS", "MISSION_SKIP", "MISSION_SLEEP",
                   "MISSION_FORTIFY", "MISSION_ALERT", "COMMAND_WAKE", "COMMAND_CANCEL", "COMMAND_DELETE",
                   "COMMAND_AUTOMATE", "COMMAND_STOP_AUTOMATION", "BUILD_REMOVE_ROUTE")

def _summary_unit_row(u: dict) -> dict:
    """One todo_actions row cut to what a decision starts from: id, type, position, moves, hp when damaged, the non-routine
    action types (bare strings; `kind`/`mission` follow from the prefix, `target_tool` from the normal row),
    how many routine ones, promotion enums, targets in reach (where and what, no preview), and the plots a
    worker could improve (where and which builds, no turns or yield deltas). Keys in a fixed order."""
    if u.get("ok") is False:
        return {"id": u.get("id"), "ok": False, "err": u.get("err")}
    row: dict[str, Any] = {"id": u.get("id"), "type": u.get("type"), "x": u.get("x"), "y": u.get("y"),
                           "moves": u.get("moves")}
    if u.get("hp") is not None:
        row["hp"], row["max_hp"] = u["hp"], u.get("max_hp")
    if u.get("promotion_ready"):
        row["promotion_ready"] = True
    acts = [a.get("type") for a in u.get("actions") or []]
    row["actions"] = [a for a in acts if a not in ROUTINE_ACTIONS]
    row["routine"] = len(acts) - len(row["actions"])
    if u.get("promotions"):
        row["promotions"] = [p.get("promotion") for p in u["promotions"]]
    for key, name in (("attack_targets", "attack"), ("ranged_targets", "ranged")):
        if u.get(key):
            row[name] = [{k: t[k] for k in ("x", "y", "unit", "city", "owner", "hp") if t.get(k) is not None}
                         for t in u[key]]
    if u.get("nearby_builds"):
        row["build_plots"] = [{k: e[k] for k in ("x", "y", "builds", "resource") if e.get(k) is not None}
                              for e in u["nearby_builds"]]
    return row

_ORDER_ITEM_PREFIX = {
    "ORDER_TRAIN": "UNIT_", "ORDER_CONSTRUCT": "BUILDING_",
    "ORDER_CREATE": "PROJECT_", "ORDER_MAINTAIN": "PROCESS_",
}

def _check_order_item(order: str, item: str) -> dict | None:
    """`order` and `item` must belong to the same GameInfo table (Units/Buildings/Projects/Processes) --
    `GameInfoTypes` is a single flat id-space across EVERY table in the game database, so a mismatched pair
    (e.g. order=ORDER_CREATE with a BUILDING_* item) still resolves to a real, valid-looking id -- just in
    the WRONG table. Passing that id into a Projects-table call (GetProjectPurchaseCost, CanCreate, ...)
    when it's actually a Buildings-table id indexes out of bounds natively: confirmed live (2026-09-16),
    `purchase_cost(8192, "ORDER_CREATE", "BUILDING_SISTINE_CHAPEL")` (a real testing mistake -- wonders are
    BUILDING_* items built via ORDER_CONSTRUCT, not ORDER_CREATE) crashed the game process outright. Checked
    by plain string prefix (this game's own UNIT_/BUILDING_/PROJECT_/PROCESS_ naming convention -- the same
    one mcp_server.py's set_production wrapper already uses to *derive* order from item) rather than a live
    GameInfo lookup, so this is a zero-cost check before ever touching the engine. Returns None when the
    pair is consistent, or an {ok:false, err:...} dict ready to return directly otherwise."""
    expected = _ORDER_ITEM_PREFIX.get(order)
    if expected is None:
        return {"ok": False, "err": f"unknown order {order!r}"}
    if not item.startswith(expected):
        return {"ok": False, "err": f"item {item!r} does not match order {order!r} (expected a {expected}* item)"}
    return None

def lua_table(v) -> str:
    """Encode a JSON-shaped Python value (dict/list/str/number/bool/None) as a Lua table literal."""
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

def _lua_value(v: Any) -> str:
    if isinstance(v, bool): return "true" if v else "false"
    if isinstance(v, (int, float)): return repr(v)
    if isinstance(v, str): return lua_str(v)
    if isinstance(v, dict): return _lua_table(v)
    raise TypeError(f"cannot encode {v!r} as a Lua value")

def _lua_table(d: dict) -> str:
    return "{" + ", ".join(f"{k}={_lua_value(v)}" for k, v in d.items()) + "}"

def _lua_items(items: list[dict]) -> str:
    """Encode a list of flat dicts (string keys, str/int/float/bool values) as a Lua array-of-tables
    literal, for calls like H.propose_deal that take a structured item list rather than scalar args."""
    return "{" + ", ".join(_lua_table(item) for item in items) + "}"

_MARKUP = re.compile(r"\[(?:ICON|COLOR)_[A-Z0-9_]*\]|\[ENDCOLOR\]|\[LINK=[^\]]*\]|\[\\LINK\]")

_BARE_ICON = re.compile(r"\[ICON_([A-Z0-9_]+)\](?=\s*(?:[,.;:)]|\[ICON_|$))")

_DISMISS = re.compile(r"\s*\[COLOR_POSITIVE_TEXT\]RIGHT-CLICK\[ENDCOLOR\] to dismiss\.?|\s*RIGHT-CLICK to dismiss\.?")

def plain_text(v: Any) -> Any:
    r"""Strip the game's display markup from every string in `v`: [COLOR_*]/[ENDCOLOR]/[ICON_*] go (the icon
    is normally followed by its word -- "[ICON_GOLD] Gold"; a bare one keeps its name), a Civilopedia link
    [LINK=...]word[\LINK] keeps its word (the build descriptions: "Construct a [LINK=IMPROVEMENT_FARM]Farm[\LINK]"),
    [NEWLINE] becomes a newline, and the panel's "RIGHT-CLICK to dismiss" line is dropped. Brackets that are not
    markup are left alone."""
    if isinstance(v, str):
        s = _DISMISS.sub("", v).replace("[NEWLINE]", "\n").replace("[TAB]", " ").replace("[SPACE]", " ")
        s = _BARE_ICON.sub(lambda m: m.group(1).replace("_", " ").title(), s)
        s = _MARKUP.sub("", s)
        return re.sub(r"[ \t]{2,}", " ", s).strip() if s is not v else v
    if isinstance(v, dict):
        return {k: plain_text(x) for k, x in v.items()}
    if isinstance(v, list):
        return [plain_text(x) for x in v]
    return v
