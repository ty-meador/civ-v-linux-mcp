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

NO_BLOCK = "NO_ENDTURN_BLOCKING_TYPE"
WAIT = {"clear_with": "wait_for_my_turn", "args": {"timeout_seconds": 600}}

# Decision popups (SerialEventGameMessagePopup) and what resolves them. The guard lets only these tools
# through while the popup is up (resolutions_by_tool); the gate names them (popup_resolution).
POPUP_RESOLUTIONS: dict[str, dict[str, Any]] = {
    "BUTTONPOPUP_CHOOSETECH": {"clear_with": "set_research", "read_first": "available_research"},
    "BUTTONPOPUP_TECH_TREE": {"clear_with": "set_research", "read_first": "available_research"},
    "BUTTONPOPUP_CHOOSEPRODUCTION": {"clear_with": "set_production", "read_first": "available_production"},
    "BUTTONPOPUP_CHOOSEPOLICY": {"clear_with": "choose_policy", "also": ["unlock_policy_branch"],
                                 "read_first": "available_policies"},
    "BUTTONPOPUP_CHOOSE_IDEOLOGY": {"clear_with": "choose_ideology"},
    "BUTTONPOPUP_CHOOSEUNITPROMOTION": {"clear_with": "choose_promotion", "read_first": "available_unit_actions"},
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


def resolutions_by_tool() -> dict[str, set[str]]:
    """tool name -> the popups it may be called under (the guard's allow-list)."""
    out: dict[str, set[str]] = {}
    for popup, r in POPUP_RESOLUTIONS.items():
        for tool in [r["clear_with"], *r.get("also", [])]:
            out.setdefault(tool, set()).add(popup)
    return out


def popup_resolution(name: str) -> dict[str, Any]:
    r = dict(POPUP_RESOLUTIONS.get(name) or GENERIC_POPUP)
    r.pop("also", None)
    return r


def popup_gate(popup: dict | str) -> dict[str, Any]:
    """The gate for one unresolved decision popup (a pending_popups entry or its name)."""
    name = popup.get("name") if isinstance(popup, dict) else popup
    r = popup_resolution(str(name))
    why = (f"the {name} popup asks for a decision and nothing else runs until it is answered: "
           + (f"{r['read_first']}() lists the choices, " if r.get("read_first") else "")
           + f"{r['clear_with']}() makes one")
    return {"name": "decision_popup", "popup": name, **r, "why": why}


def compute_gate(ts: dict | None, seat: int | None, *, may_change_seat: bool = False) -> dict[str, Any] | None:
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
                       "load_latest resumes the newest save, load_save a named one; in a game with other "
                       "people ask the human first"}
    if ts.get("game_over"):
        return {"name": "game_over", "clear_with": None,
                "why": "the game is over; nothing more happens in it (exit_to_main_menu leaves it)"}
    active = ts.get("active_player")
    hotseat = bool(ts.get("hotseat"))
    if seat is not None and active is not None and active != seat:
        if hotseat:
            why = (f"it is not seat {seat}'s turn: seat {active} is on screen. wait_for_my_turn blocks until it "
                   "is your turn (finish_turn does the same after ending a turn); you see nothing of the other "
                   "player's turn meanwhile")
            if may_change_seat:
                why += (f". Only if this server is on the wrong seat (nobody else plays seat {active}), "
                        f"set_seat({active}) moves it; never take a seat another player is playing")
            return {"name": "other_seat_active", **WAIT, "why": why}
        return {"name": "waiting_for_turn", **WAIT,
                "why": f"player {active} holds the turn (the AIs, or another human): wait_for_my_turn / "
                       "finish_turn block until it is yours"}
    if hotseat and ts.get("hand_off_pending"):
        return {"name": "hand_off_screen", **WAIT,
                "why": "the hotseat hand-off screen (\"Continue\") is up for this seat: the game is paused behind "
                       "it and every action is refused until it is dismissed. wait_for_my_turn presses Continue "
                       "and returns the turn; do not read the board first, nothing has changed since the hand-off"}
    if ts.get("processing"):
        return {"name": "processing", **WAIT,
                "why": "the engine is still processing the turn change: wait_for_my_turn returns when it is done"}
    if ts.get("paused"):
        why = "the game is paused"
        if hotseat and ts.get("hand_off_pending") is None:
            why += " (in hotseat that is the hand-off screen, which pauses the game until Continue is pressed)"
        return {"name": "paused", **WAIT, "why": why + ": wait_for_my_turn clears what pauses it and returns the turn"}
    if ts.get("my_turn") is False:
        return {"name": "turn_not_active", **WAIT,
                "why": "the seat is on screen but its turn is not active yet (or turn-complete was already sent): "
                       "wait_for_my_turn returns when it is"}
    if ts.get("leader_greeting_pending"):
        return {"name": "leader_screen", "clear_with": "dismiss_discussion", "read_first": "discussion",
                "why": "a leader screen is up (a greeting, or the echo of a war or peace) and the game is frozen "
                       "behind it: discussion() reads it, dismiss_discussion() closes it. blocking_name and todo "
                       "are frozen too and may already be resolved"}
    if ts.get("discussion_pending"):
        return {"name": "discussion", "clear_with": "respond_discussion", "read_first": "discussion",
                "alternatives": ["accept_deal", "refuse_deal", "dismiss_discussion"],
                "why": "a leader is asking you something: discussion() shows what they said and the buttons, "
                       "respond_discussion(button_id) answers; for a deal on the table incoming_deal() reads the "
                       "terms and accept_deal() / refuse_deal() settle it; dismiss_discussion() leaves without "
                       "agreeing"}
    todo = ts.get("todo") if isinstance(ts.get("todo"), dict) else {}
    if ts.get("tech_popup_pending") and todo.get("research_unset"):
        return {"name": "tech_choice", "clear_with": "set_research", "read_first": "available_research",
                "why": "the technology chooser is up and research is unset: available_research() lists the "
                       "options, set_research(tech) picks one"}
    pending = ts.get("pending_popups") or []
    decisions = [p for p in pending if isinstance(p, dict) and p.get("name") in POPUP_RESOLUTIONS]
    if decisions:
        return popup_gate(decisions[0])
    if ts.get("city_state_greeting_pending") or ts.get("great_person_reward_pending"):
        which = "city-state greeting" if ts.get("city_state_greeting_pending") else "Great Person announcement"
        return {"name": "announcement_screen", **WAIT,
                "why": f"a {which} screen is up; it needs no decision but end_turn silently does nothing while "
                       "it shows: wait_for_my_turn closes it (any action would too)"}
    return None
