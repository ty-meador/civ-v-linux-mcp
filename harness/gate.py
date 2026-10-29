"""The gate: one answer to "what must happen before anything else works".

A turn_state is some twenty-five flags, and which of them matters first is a set of precedence rules that
used to live in three places: mcp_server.guarded's refusal chain, Game.wait_for_my_turn's early returns,
and docs/NOTES.md. A reader had to know them all. Live 2026-09-26 (Codex, seat 0 of a two-agent hotseat
game, after a context reset): turn_status said my_turn=true, paused=true, popup_up=true, an empty todo and
no blocker while its own hand-off screen was up; nothing named the screen or the call that clears it. The
agent read the board for four minutes, was refused with "game is paused, processing, or waiting", replayed
that refusal through its own action_id, and only then called wait_for_my_turn -- which cleared it at once.
Earlier the same hour, with the other seat on screen, the status note "set_seat(player_id) changes the
seat" read as advice: it called set_seat onto the other seat and pressed that seat's Continue button.

So every status and every refusal now carries `gate`: None when the seat is free to act, else one object
naming the precondition (`name`), the tool that clears it (`clear_with`, with `args` and `read_first` when
they help) and why (`why`). The order below is the order the engine and the guard enforce; the first match
wins, because clearing it is what makes the next one visible. The end-turn blocker is not a gate: it stops
end_turn, not acting, and blocking_name / blocking_hint / todo already say what clears it.
"""
from __future__ import annotations

from typing import Any

from . import rows
from .surface import classes

NO_BLOCK = "NO_ENDTURN_BLOCKING_TYPE"
WAIT = {"clear_with": "wait_for_my_turn", "args": {"timeout_seconds": 600}}

# Decision popups (SerialEventGameMessagePopup) and what resolves them. The guard lets only these tools
# through while the popup is up (resolutions_by_key); the gate names them (popup_resolution).
POPUP_RESOLUTIONS: dict[str, dict[str, Any]] = {
    "BUTTONPOPUP_CHOOSETECH": {"clear_with": "set_research", "read_first": "available_research"},
    "BUTTONPOPUP_TECH_TREE": {"clear_with": "set_research", "read_first": "available_research"},
    "BUTTONPOPUP_CHOOSEPRODUCTION": {"clear_with": "set_production", "read_first": "available_production"},
    "BUTTONPOPUP_CHOOSEPOLICY": {"clear_with": "choose_policy", "also": ["unlock_policy_branch"],
                                 "read_first": "available_policies"},
    "BUTTONPOPUP_CHOOSE_IDEOLOGY": {"clear_with": "choose_ideology"},
    # todo_actions (not available_unit_actions, which needs a unit_id the popup does not name): every promotion-ready
    # unit with its choose_promotion rows, in one read (#46)
    "BUTTONPOPUP_CHOOSEUNITPROMOTION": {"clear_with": "choose_promotion", "read_first": "todo_actions"},
    "BUTTONPOPUP_FOUND_PANTHEON": {"clear_with": "found_pantheon", "also": ["add_reformation_belief"],
                                   "read_first": "available_beliefs"},
    "BUTTONPOPUP_FOUND_RELIGION": {"clear_with": "found_religion", "read_first": "available_beliefs"},
    "BUTTONPOPUP_ENHANCE_RELIGION": {"clear_with": "enhance_religion", "read_first": "available_beliefs"},
    "BUTTONPOPUP_CHOOSE_GOODY_HUT_REWARD": {"clear_with": "choose_goody_hut", "read_first": "goody_hut_options"},
    "BUTTONPOPUP_CITY_CAPTURED": {"clear_with": "choose_city_capture", "read_first": "city_capture_options"},
    "BUTTONPOPUP_CHOOSE_FAITH_GREAT_PERSON": {"clear_with": "choose_faith_great_person",
                                              "read_first": "faith_great_person_options"},
    "BUTTONPOPUP_CHOOSE_ARCHAEOLOGY": {"clear_with": "choose_archaeology", "read_first": "archaeology_options"},
    "BUTTONPOPUP_CHOOSE_MAYA_BONUS": {"clear_with": "choose_maya_bonus", "read_first": "maya_options"},
}
GENERIC_POPUP = {"clear_with": "answer_popup", "read_first": "generic_popup"}

# End-turn blockers that are a question the engine never opens as a popup until its notification is clicked
# (GitLab #95; live Maya t77 / t88: ENDTURN_BLOCKING_MAYA_LONG_COUNT with no BUTTONPOPUP_CHOOSE_MAYA_BONUS, and
# the same shape for a spy's stolen tech). `question()` serves the read and `answer(choice)` the resolver on the
# blocker alone; the choice lands through the same net message the popup would send. Not gates: an open Long
# Count does not stop a unit from moving, only the turn from ending.
BLOCKER_QUESTIONS: dict[str, dict[str, str]] = {
    "ENDTURN_BLOCKING_MAYA_LONG_COUNT": {"clear_with": "choose_maya_bonus", "read_first": "maya_options"},
    "ENDTURN_BLOCKING_STEAL_TECH": {"clear_with": "steal_tech", "read_first": "steal_tech_options"},
    "ENDTURN_BLOCKING_FREE_ITEMS": {"clear_with": "choose_free_great_person", "read_first": "free_great_person_options"},
    "ENDTURN_BLOCKING_FAITH_GREAT_PERSON": {"clear_with": "choose_faith_great_person",
                                            "read_first": "faith_great_person_options"},
    "ENDTURN_BLOCKING_CHOOSE_ARCHAEOLOGY": {"clear_with": "choose_archaeology", "read_first": "archaeology_options"},
}


def blocker_question(ts: dict | None) -> str | None:
    """The end-turn blocker of this status when it is one of BLOCKER_QUESTIONS, else None."""
    name = ts.get("blocking_name") if isinstance(ts, dict) else None
    return name if name in BLOCKER_QUESTIONS else None


#: What each blocker question's answer leaves to choose (the choice, plus the arguments the read fixes per row).
BLOCKER_CHOICE: dict[str, list[str]] = {
    "choose_maya_bonus": ["unit"], "steal_tech": ["tech", "player_id"], "choose_free_great_person": ["unit"],
    "choose_faith_great_person": ["unit"], "choose_archaeology": ["choice", "x", "y"],
}


def blocker_rows(name: str) -> list[dict]:
    """A blocker question's rows: the read, then the answer with its choice left to pick (#46's shape)."""
    r = BLOCKER_QUESTIONS[name]
    return [_call(r["read_first"]), _call(r["clear_with"], BLOCKER_CHOICE[r["clear_with"]])]



def resolutions_by_key() -> dict[tuple[str, str], set[str]]:
    """The `(tool, action)` of each resolver -> the popups it may be called under (the guard's allow-list;
    harness/surface/classes.py keys a call the same way, so an old name and its new call read as one)."""
    out: dict[tuple[str, str], set[str]] = {}
    for popup, r in POPUP_RESOLUTIONS.items():
        for tool in [r["clear_with"], *r.get("also", [])]:
            out.setdefault(classes.of_handler(tool), set()).add(popup)
    return out


def popup_resolution(name: str) -> dict[str, Any]:
    r = dict(POPUP_RESOLUTIONS.get(name) or GENERIC_POPUP)
    r.pop("also", None)
    return r


# The arguments the resolver takes, for the one-line recipe a refusal carries (popup_hint).
POPUP_CHOICE_ARGS: dict[str, str] = {
    "BUTTONPOPUP_CHOOSETECH": "tech", "BUTTONPOPUP_TECH_TREE": "tech",
    "BUTTONPOPUP_CHOOSEPRODUCTION": "city_id, item",
    "BUTTONPOPUP_CHOOSEPOLICY": "policy", "BUTTONPOPUP_CHOOSE_IDEOLOGY": "branch",
    "BUTTONPOPUP_CHOOSEUNITPROMOTION": "unit_id, promotion",
    "BUTTONPOPUP_FOUND_PANTHEON": "belief",
    "BUTTONPOPUP_FOUND_RELIGION": "religion, beliefs, city_x, city_y",
    "BUTTONPOPUP_ENHANCE_RELIGION": "religion, belief4, belief5, city_x, city_y",
    "BUTTONPOPUP_CHOOSE_GOODY_HUT_REWARD": "goody", "BUTTONPOPUP_CITY_CAPTURED": "choice",
    "BUTTONPOPUP_CHOOSE_FAITH_GREAT_PERSON": "unit", "BUTTONPOPUP_CHOOSE_ARCHAEOLOGY": "choice, x, y",
    "BUTTONPOPUP_CHOOSE_MAYA_BONUS": "unit",
}


#: The read's own arguments when the popup fixes them (available_beliefs takes the slot kind); one row per entry.
POPUP_READ_ARGS: dict[str, list[dict]] = {
    "BUTTONPOPUP_FOUND_PANTHEON": [{"kind": "pantheon"}],
    "BUTTONPOPUP_FOUND_RELIGION": [{"kind": "founder"}, {"kind": "follower"}],
    "BUTTONPOPUP_ENHANCE_RELIGION": [{"kind": "follower"}, {"kind": "enhancer"}],
}
#: A read the gate cannot complete itself: the argument the model supplies (the production popup's city is in
#: turn_status.todo.cities).
READ_CHOICE: dict[str, list[str]] = {"available_production": ["city_id"]}
#: What the `also` resolvers and the non-popup resolvers leave to choose.
CLEAR_CHOICE: dict[str, list[str]] = {
    "unlock_policy_branch": ["branch"], "add_reformation_belief": ["belief"],
    "respond_discussion": ["button_id"], "set_research": ["tech"], "answer_popup": ["button"],
}


def _call(tool: str, choose: list[str] | None = None, **args: Any) -> dict:
    return rows.pick(tool, choose, **args) if choose else rows.act(tool, **args)


def popup_rows(name: str) -> list[dict]:
    """A decision popup's rows (#46): the read (as is, or with the arguments the model supplies), the call that
    answers it with the arguments left to choose, then the other resolvers (`also`)."""
    r = POPUP_RESOLUTIONS.get(name) or GENERIC_POPUP
    out: list[dict] = []
    read = r.get("read_first")
    if read:
        for args in POPUP_READ_ARGS.get(name) or [{}]:
            out.append(_call(read, READ_CHOICE.get(read), **args))
    chosen = POPUP_CHOICE_ARGS.get(name, "button" if r["clear_with"] == "answer_popup" else "")
    out.append(_call(r["clear_with"], [a.strip() for a in chosen.split(",") if a.strip()]))
    for also in r.get("also", []):
        out.append(_call(also, CLEAR_CHOICE.get(also)))
    return out


def rows_for(g: dict[str, Any] | None) -> dict[str, Any] | None:
    """`g` with `actions` (#46): the gate's read first, the call that clears it (its `args`, the arguments left to
    choose), then the alternatives. A gate that already carries rows (a popup's) is returned as is."""
    if g is None or "actions" in g:
        return g
    out: list[dict] = []
    if g.get("read_first"):
        out.append(rows.act(g["read_first"]))
    tool = g.get("clear_with")
    if tool:
        out.append(_call(tool, CLEAR_CHOICE.get(tool), **(g.get("args") or {})))
    elif g.get("name") == "game_over":
        out.append(rows.act("exit_to_main_menu"))
    for alt in g.get("alternatives") or []:
        out.append(_call(alt, CLEAR_CHOICE.get(alt)))
    return {**g, "actions": out}


def popup_hint(name: str) -> str:
    """The recipe for one unresolved popup, as a refusal's `hint`: the read, then the choice. (It used to be a
    chain of four special cases in mcp_server.guarded; a pending tech or production popup got the generic
    answer_popup line, which does not clear those.)"""
    r = POPUP_RESOLUTIONS.get(name)
    if r is None:
        return "question() shows the question and buttons; answer(choice=<button>) presses one"
    read = f"{call_of(r['read_first'])} then " if r.get("read_first") else ""
    return f"{read}{call_of(r['clear_with'])}"


def popup_gate(popup: dict | str) -> dict[str, Any]:
    """The gate for one unresolved decision popup (a pending_popups entry or its name)."""
    name = popup.get("name") if isinstance(popup, dict) else popup
    r = popup_resolution(str(name))
    why = (f"the {name} popup asks for a decision and nothing else runs until it is answered: "
           + (f"{call_of(r['read_first'])} lists the choices, " if r.get("read_first") else "")
           + f"{call_of(r['clear_with'])} makes one")
    return worded({"name": "decision_popup", "popup": name, **r, "why": why, "actions": popup_rows(str(name))})


def compute_gate(ts: dict | None, seat: int | None, *, may_change_seat: bool = False) -> dict[str, Any] | None:
    """The first precondition that stops this seat from acting, or None when it may act now; with its rows and
    its words in the nine-tool vocabulary."""
    return worded(rows_for(_first_gate(ts, seat, may_change_seat=may_change_seat)))


def call_of(name: str | None) -> str | None:
    """An old handler's name as the call it is in the nine-tool vocabulary (`turn(action="wait")`)."""
    from harness.surface import forward, retirement
    return forward.renamed(name) if name in retirement.RETIRED else name


def worded(g: dict[str, Any] | None) -> dict[str, Any] | None:
    """The gate's `clear_with`, `read_first`, `alternatives` and `also` as the new calls (the tables above name
    the old handlers, which is what the server dispatches on); the rows already are."""
    if g is None:
        return g
    out = dict(g)
    for k in ("clear_with", "read_first"):
        if out.get(k):
            out[k] = call_of(out[k])
    for k in ("alternatives", "also"):
        if out.get(k):
            out[k] = [call_of(n) for n in out[k]]
    return out


def _first_gate(ts: dict | None, seat: int | None, *, may_change_seat: bool = False) -> dict[str, Any] | None:
    """The first precondition that stops this seat from acting, or None when it may act now.

    `ts` is a turn_state (or a turn_status answer: `ingame` False means no game is loaded). `seat` is the
    player this server plays. `may_change_seat` adds the set_seat escape to the not-your-turn gate; it is
    for a server whose seat was guessed (--seat auto), never for one pinned to a seat -- a pinned server
    refuses set_seat onto the other seat, and offering it is what sent an agent onto the other player's
    Continue button (live 2026-09-26)."""
    if not isinstance(ts, dict):
        return None
    if ts.get("ingame") is False:
        return {"name": "no_game", "clear_with": "load_latest",
                "why": f"no game is loaded (the game is on its {ts.get('screen') or 'front-end'} screen): "
                       "session(action='load_latest') resumes the newest save, session(action='load', "
                       "args={filename}) a named one; in a game with other people ask the human first"}
    if ts.get("game_over"):
        return {"name": "game_over", "clear_with": None,
                "why": "the game is over; nothing more happens in it (session(action='main_menu') leaves it)"}
    active = ts.get("active_player")
    hotseat = bool(ts.get("hotseat"))
    if seat is not None and active is not None and active != seat:
        if hotseat:
            if ts.get("active_turn_active") is False:
                # the last human seat ended its turn and the AIs are moving before the next human's begins
                why = (f"seat {active} has ended its turn and the AIs are moving before seat {seat}'s begins. "
                       "turn(action='wait') blocks until it is your turn (turn(action='finish') does the same after "
                       "ending a turn); an AI round can take minutes")
            else:
                why = (f"it is not seat {seat}'s turn: seat {active} is on screen. turn(action='wait') blocks until "
                       "it is your turn (turn(action='finish') does the same after ending a turn); you see nothing "
                       "of the other player's turn meanwhile")
            if may_change_seat:
                why += (f". Only if this server is on the wrong seat (nobody else plays seat {active}), "
                        f"session(action='seat', args={{'seat': {active}}}) moves it; never take a seat another "
                        "player is playing")
            return {"name": "other_seat_active", **WAIT, "why": why}
        return {"name": "waiting_for_turn", **WAIT,
                "why": f"player {active} holds the turn (the AIs, or another human): turn(action='wait') / "
                       "turn(action='finish') block until it is yours"}
    if hotseat and ts.get("hand_off_pending"):
        return {"name": "hand_off_screen", **WAIT,
                "why": "the hotseat hand-off screen (\"Continue\") is still up for this seat: the game is paused "
                       "behind it and every action is refused until it is dismissed. Every call presses it for you, "
                       "so seeing this means the press did not take; turn(action='wait') presses it again and "
                       "returns the turn. Do not read the board first, nothing has changed since the hand-off"}
    if ts.get("processing"):
        return {"name": "processing", **WAIT,
                "why": "the engine is still processing the turn change: turn(action='wait') returns when it is done"}
    if ts.get("load_screen_pending"):
        return {"name": "load_screen", **WAIT,
                "why": "the Dawn of Man splash (\"Begin your journey\" / \"Continue\") of a game started or loaded by hand "
                       "is up: a single-player game is paused behind it and every order is a no-op until its button "
                       "is pressed. turn(action='wait') presses it and returns the turn"}
    if ts.get("paused"):
        why = "the game is paused"
        if hotseat and ts.get("hand_off_pending") is None:
            why += " (in hotseat that is the hand-off screen, which pauses the game until Continue is pressed)"
        return {"name": "paused", **WAIT, "why": why + ": turn(action='wait') clears what pauses it and returns the turn"}
    # A leader screen outranks "the turn is not active": after end_turn the AIs make their offers while my_turn
    # is still false, and the answering tools work then (live 2026-10-08, England t118-t122: Rome's open-borders
    # offer, Spain's co-operation question). Naming wait_for_my_turn here sent the agent into a wait that
    # returned at once with the same screen.
    if ts.get("leader_greeting_pending"):
        return {"name": "leader_screen", "clear_with": "dismiss_discussion", "read_first": "discussion",
                "why": "a leader screen is up (a greeting, or the echo of a war or peace) and the game is frozen "
                       "behind it: question() reads it, answer(choice='leave') closes it. blocking_name and todo "
                       "are frozen too and may already be resolved"}
    if ts.get("discussion_pending") and ts.get("trade_state"):
        # the trade table is up (an AI's offer, or the "Anything else?" scene): there are no response buttons,
        # so respond_discussion could not clear it (live t136: China's open-borders offer at the hand-off)
        return {"name": "discussion", "deal": True, "clear_with": "accept_deal", "read_first": "incoming_deal",
                "alternatives": ["refuse_deal", "dismiss_discussion"],
                "why": "a deal is on the table: question() shows the items, the leader and their words; "
                       "answer(choice='accept') takes it, answer(choice='refuse') declines it; answer(choice='leave') "
                       "leaves the screen without answering"}
    if ts.get("discussion_pending"):
        return {"name": "discussion", "clear_with": "respond_discussion", "read_first": "discussion",
                "alternatives": ["accept_deal", "refuse_deal", "dismiss_discussion"],
                "why": "a leader is asking you something: question() shows what they said and the buttons, "
                       "answer(choice=<button id>) answers; for a deal on the table question() reads the terms and "
                       "answer(choice='accept' / 'refuse') settles it; answer(choice='leave') leaves without agreeing"}
    if ts.get("my_turn") is False:
        return {"name": "turn_not_active", **WAIT,
                "why": "the seat is on screen but its turn is not active yet (or turn-complete was already sent): "
                       "turn(action='wait') returns when it is"}
    todo = ts.get("todo") if isinstance(ts.get("todo"), dict) else {}
    if ts.get("tech_popup_pending") and todo.get("research_unset"):
        return {"name": "tech_choice", "clear_with": "set_research", "read_first": "available_research",
                "why": "the technology chooser is up and research is unset: inspect(what='options', "
                       "view='research') lists the options, order(to='empire', action='research', args={tech}) "
                       "picks one"}
    pending = ts.get("pending_popups") or []
    decisions = [p for p in pending if isinstance(p, dict) and p.get("name") in POPUP_RESOLUTIONS]
    if decisions:
        return popup_gate(decisions[0])
    if ts.get("city_state_greeting_pending") or ts.get("great_person_reward_pending"):
        which = "city-state greeting" if ts.get("city_state_greeting_pending") else "Great Person announcement"
        return {"name": "announcement_screen", **WAIT,
                "why": f"a {which} screen is up; it needs no decision but the turn's end silently does nothing "
                       "while it shows. Every call closes these screens for you, so seeing this means the close "
                       "did not take: turn(action='wait') tries again"}
    return None
