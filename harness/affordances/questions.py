"""A question's answers as rows (GitLab #46): a popup, a leader on screen, a deal on the table."""
from __future__ import annotations

from typing import Any, Callable

from ..rows import act


def answered(reply: Any, make: Callable[[dict], list[dict]]) -> Any:
    """`reply` with `answers` (the rows `make` builds from it) when it is a reply and not a refusal."""
    if isinstance(reply, dict) and reply.get("ok", True) is not False:
        reply["answers"] = make(reply)
    return reply


def _options(reply: dict, key: str = "options") -> list:
    v = reply.get(key)
    return v if isinstance(v, list) else []


def generic_popup_answers(r: dict) -> list[dict]:
    """One `answer_popup` per numbered button of an open generic confirmation."""
    if not r.get("open"):
        return []
    out = []
    for i, b in enumerate(_options(r, "buttons"), start=1):
        out.append(act("answer_popup", button=b.get("id", i) if isinstance(b, dict) else i))
    return out


def goody_hut_answers(r: dict) -> list[dict]:
    return [act("choose_goody_hut", goody=o["goody"]) for o in _options(r) if isinstance(o, dict) and o.get("goody")]


def maya_answers(r: dict) -> list[dict]:
    """The Long Count's choices still open (a type chosen earlier in the cycle is listed but not offered)."""
    if not r.get("count"):
        return []
    return [act("choose_maya_bonus", unit=o["unit"]) for o in _options(r)
            if isinstance(o, dict) and o.get("unit") and o.get("available", True)]


def city_capture_answers(r: dict) -> list[dict]:
    return [act("choose_city_capture", choice=o["choice"]) for o in _options(r) if isinstance(o, dict) and o.get("choice")]


def steal_tech_answers(r: dict) -> list[dict]:
    """One row per (victim, tech) pair the spy may take."""
    out = []
    for v in _options(r, "victims"):
        if not isinstance(v, dict) or v.get("player_id") is None:
            continue
        for t in _options(v, "techs"):
            if isinstance(t, dict) and t.get("tech"):
                out.append(act("steal_tech", tech=t["tech"], player_id=v["player_id"]))
    return out


def free_great_person_answers(r: dict) -> list[dict]:
    if not r.get("count"):
        return []
    return [act("choose_free_great_person", unit=u) for u in _options(r) if isinstance(u, str)]


def faith_great_person_answers(r: dict) -> list[dict]:
    return [act("choose_faith_great_person", unit=u) for u in _options(r) if isinstance(u, str)]


def archaeology_answers(r: dict) -> list[dict]:
    """One `choose_archaeology` per choice of the completed dig, the dig's plot filled in."""
    if not r.get("pending") or r.get("x") is None or r.get("y") is None:
        return []
    return [act("choose_archaeology", choice=o["choice"], x=r["x"], y=r["y"])
            for o in _options(r) if isinstance(o, dict) and o.get("choice") is not None]


#: The leader's screen state that `accept_friendship` answers (a Declaration of Friendship proposed to us).
FRIENDSHIP_STATE = "DISCUSS_WORK_WITH_US"


def discussion_answers(r: dict) -> list[dict]:
    """The leader screen's buttons as rows: a deal on the table takes accept / refuse, a question its response
    buttons (and `accept_friendship` when the question is a Declaration of Friendship), every screen may be
    left with `dismiss_discussion`."""
    if not r.get("pending"):
        return []
    if r.get("screen") == "trade":
        return [act("accept_deal"), act("refuse_deal"), act("dismiss_discussion")]
    out = [act("respond_discussion", button_id=b["id"]) for b in _options(r, "buttons")
           if isinstance(b, dict) and b.get("id") is not None and not b.get("disabled")]
    rel = r.get("relationship") if isinstance(r.get("relationship"), dict) else {}
    states = [str(h.get("state", "")) for h in rel.get("history") or [] if isinstance(h, dict)]
    if out and isinstance(r.get("player"), int) and r["player"] >= 0 and any(s.endswith(FRIENDSHIP_STATE) for s in states):
        out.append(act("accept_friendship", player_id=r["player"]))
    out.append(act("dismiss_discussion"))
    return out


def incoming_deal_answers(r: dict) -> list[dict]:
    """A deal on the table is taken or declined; nothing on the table makes no row. A proposal whose items did
    not load (#161, `unread`) can only be declined."""
    if r.get("pending") is False:
        return []
    if not r.get("items"):
        return [act("refuse_deal")] if r.get("unread") else []
    return [act("accept_deal"), act("refuse_deal")]
