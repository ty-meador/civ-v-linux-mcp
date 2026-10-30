"""Classification by `(tool, action)` (GitLab #51, stage 2d): the sets the server and the call ledger sort a call
into, written in the nine-tool vocabulary.

Until this stage every set that decided how a call is treated -- a read that skips the refusals, a wait that
sleeps outside the lock, a menu tool, a response whose input is the pending thing, a save that runs under a
popup, what a batch may not carry -- was a set of bare tool names, one per old tool. With nine tools carrying
the actions, a name says nothing: `turn` is a read as `status` and a wait as `finish`. So the sets here hold
`(tool, action)` keys, and a call's key comes from the arguments it was made with (`of_call`) or, for the old
handler the guard wraps, from its row in the retirement map (`of_handler`). An old name or alias classifies as
the new call it means, so a script in the wild is treated exactly as the new vocabulary would treat it.

The action half of a key is a short label: `state`'s is the object, with its view after a slash when it is
not the default (`league`, `unit/tactical`); `order`'s is the target and the verb (`city/produce`); `answer`'s
is a fixed word (`accept`, `leave`) or, for the old handlers of the decision popups and buttons, the row's
placeholder (`<button>`, `<goody>`); the rest is the action, the book, or nothing. `*` in a set matches every
action of a tool, `city/*` every action on a target. The same label is what a ledger row carries as `action`
and the spectator prints after the tool name.
"""
from __future__ import annotations

from typing import Any, Iterable, Iterator

from harness.surface import forward
from harness.surface import retirement as R
from harness.surface import vocabulary as V

Key = tuple[str, str]


class Keys:
    """A set of `(tool, action)` keys with wildcards: `("state", "*")` is every state, `("order", "city/*")`
    every order to a city. `key in keys` resolves the wildcards; `|` joins two sets."""

    __slots__ = ("_keys",)

    def __init__(self, keys: Iterable[Key] = ()):
        self._keys = frozenset(tuple(k) for k in keys)

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, tuple) or len(key) != 2:
            return False
        tool, action = key
        if (tool, action) in self._keys or (tool, "*") in self._keys:
            return True
        head, slash, _ = str(action).partition("/")
        return bool(slash) and (tool, f"{head}/*") in self._keys

    def __or__(self, other: "Keys") -> "Keys":
        return Keys(self._keys | other._keys)

    def __iter__(self) -> Iterator[Key]:
        return iter(sorted(self._keys))

    def __len__(self) -> int:
        return len(self._keys)

    def __repr__(self) -> str:
        return f"Keys({sorted(self._keys)!r})"


# --- the key of a call ------------------------------------------------------------------------------------
def action(tool: str, fixed: dict) -> str:
    """The action label of a new call from its fixed fields (what / view, to / action, choice, book, action)."""
    if tool == "state":
        what, view = fixed.get("what", ""), fixed.get("view") or V.DEFAULT
        return f"{what}/{view}" if view != V.DEFAULT else str(what)
    if tool == "order":
        return f"{fixed.get('to', '')}/{R.show(fixed.get('action', ''))}"
    if tool == "answer":
        return R.show(fixed.get("choice", ""))
    if tool == "reference":
        return str(fixed.get("book") or V.BOOKS[0])
    if tool in ("turn", "notebook", "session"):
        return str(fixed.get("action", ""))
    return ""


def of_handler(name: str) -> Key:
    """The key of an old handler by its name alone -- what `guarded` wraps, a gate's `clear_with` -- from its
    row, placeholders kept (`("answer", "<button>")` for answer_popup). A name outside the map (`lua`) is its
    own tool with no action."""
    row = R.RETIRED.get(name)
    return (row.tool, action(row.tool, row.fixed)) if row is not None else (name, "")


def of_call(name: str, args: dict | None = None) -> Key:
    """The key of a call as a client or a batch row makes it: a new tool's from its arguments (`turn(action=
    "finish")` is `("turn", "finish")`; an `answer` is its fixed word or `<choice>`), an old name's or an
    alias's from its row (`finish_turn` is the same key). The sets are consulted with this."""
    args = args or {}
    if name in V.TOOLS:
        if name == "answer":
            choice = args.get("choice")
            fixed = {"choice": choice if choice in V.ANSWER_CHOICES else R.FromArg("choice")}
        else:
            fixed = args
        return (name, action(name, fixed))
    old = forward.old_name(name)
    if old in V.TOOLS:                        # a renamed listed tool (`inspect` -> `state`): the new call's key
        return of_call(old, args)
    return of_handler(old if old is not None else name)


def called_as(name: str, args: dict | None = None) -> dict[str, Any]:
    """What a ledger row records of the name a call was made by: `tool` (one of the nine), `action` (the label,
    with an answer's actual choice and a city-state button's name filled in from the arguments) and `called`
    when the name was an old one or an alias."""
    args = args or {}
    old = None if name in V.TOOLS else forward.old_name(name)
    if name in V.TOOLS:
        tool, fixed = name, args
    elif old in V.TOOLS:                      # a renamed listed tool: its own arguments, `called` the old name
        tool, fixed = old, args
    elif old is not None:
        row = R.RETIRED[old]
        tool, fixed = row.tool, row.fill({row.renames.get(k, k): v for k, v in args.items()})
    else:
        tool, fixed = name, {}
    out: dict[str, Any] = {"tool": tool}
    label = action(tool, fixed)
    if label:
        out["action"] = label
    if name != tool:
        out["called"] = name
    return out


# --- the sets -----------------------------------------------------------------------------------------------
#: Usable from the main menu, where there is no InGame state at all.
MENU = Keys({("turn", "status"), ("session", "load"), ("session", "load_latest")})

#: Usable while it is not our turn: the two that wait for it, the notebook (a human jots a plan while the AIs
#: move; so may we), the seat and the exit, and the rule book (the civilopedia is static, readable between turns).
ANYTIME = Keys({("turn", "wait"), ("turn", "finish"), ("notebook", "remember"), ("notebook", "recall"),
                ("notebook", "forget"), ("notebook", "close"), ("notebook", "orders"), ("notebook", "cancel_order"),
                ("session", "seat"), ("session", "main_menu"), ("reference", "*")})

#: The two that sleep: they lock per poll inside Game instead of for the whole call, so an inactive seat
#: waiting in one process never starves the active seat in another (NOTES.md 2026-09-26).
WAIT = Keys({("turn", "wait"), ("turn", "finish")})

#: The ledger's waits: their seconds are AI-turn and bridge time, not inspection, and each closes a turn in the
#: report; the plain end of a turn is one too.
LEDGER_WAIT = WAIT | Keys({("turn", "end")})

#: Reads: they change nothing in the game or the notebook. Everything else (orders, answers, notes,
#: assignments, standing orders, a batch) is a write.
READ = Keys({("state", "*"), ("question", "*"), ("reference", "*"), ("turn", "status"), ("turn", "briefing"),
             ("notebook", "recall"), ("notebook", "assignments"), ("notebook", "orders")})

#: What runs while a popup, a leader remark or another client's turn claim is pending and never claims the
#: turn: the reads (looking never changes the game) and the notebook writes that touch nothing in the game.
HARMLESS = READ | Keys({("notebook", "assign"), ("notebook", "amend")})

#: Responses: the calls whose input IS the pending thing -- a leader's screen (its buttons, a deal on the
#: table, a declaration of friendship), a plain popup's button, a diplomatic event. The answers to a decision
#: popup (a tech, a goody, a captured city's fate) are not here: they run under the popup allow-list of
#: `harness.gate` and the turn checks like any order.
RESPONSE = Keys({("answer", "accept"), ("answer", "refuse"), ("answer", "leave"), ("answer", "accept_friendship"),
                 ("answer", "<button>"), ("answer", "<button_id>"), ("order", "civ/event")})

#: A save changes nothing on the board, so it runs under a decision popup: the rare screens are worth a save
#: before they are answered (live Assyria t97, 2026-10-11). Still refused while paused / not my turn.
SAVE = Keys({("session", "save")})

#: Never inside a batch: the batch itself, the waits and the turn's end, a load, the seat, the exit, and raw
#: Lua. A `turn` read (status, briefing) and a save are batch rows like any other.
BATCH_EXCLUDED = Keys({("batch", "*"), ("turn", "wait"), ("turn", "finish"), ("turn", "end"), ("session", "load"),
                       ("session", "load_latest"), ("session", "main_menu"), ("session", "seat"), ("lua", "*")})

#: An order that is only pending while the engine names its blocker. Empty since GitLab #109: the engine reports
#: one blocker at a time, so a pending pantheon sat behind PRODUCTION (live t22) and a pending enhancement too
#: (Maya t105, refused "not pending" after the Prophet was spent); the runtime checks each choice itself
#: (H.found_pantheon's CanCreatePantheon, H.religion_choice for a founding or enhancement).
REQUIRED_BLOCKER: dict[Key, str] = {}


def kind(key: Key) -> str:
    """The ledger's kind of a call: read, write or wait."""
    if key in LEDGER_WAIT:
        return "wait"
    return "read" if key in READ else "write"
