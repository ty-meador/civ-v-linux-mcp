"""The `attack` block of a move or mission reply: what one blow did, read from the two sides before and after.

Pure functions over the runtime's two reads (`H.attack_before`, `H.attack_after` / `H.city_attack_after`), so the
block is one shape wherever a move turns out to be an attack (move_unit, a move-shaped mission, an air strike).
GitLab #156: `defender.hp` used to be the pre-read's health -- the preview's `defender` row copied as it was --
while `def_hp` and the alert said the health after the blow; the row now reads the after state, and the blow's
own numbers (`damage_dealt`, `damage_taken`) stand beside the before/after pairs.
"""
from __future__ import annotations

#: Why a blow misses the preview by a few points: the stock enemy-unit panel previews with the engine's own
#: CvUnit::getCombatDamage(..., bIncludeRand=false), and the blow itself is rolled.
ROLL_NOTE = ("each blow is the engine's roll around the preview's expected_damage_dealt / expected_damage_taken "
             "(the stock panel previews without the random part); a few points either way is the roll, not a stale preview")


def attack_block(pre: dict, post: dict | None) -> dict:
    """The `attack` block: the defender as it stands after the blow, both sides' hp before and after, who died,
    and the blow's own numbers. `pre` is attack_before's reply, `post` attack_after's (or city_attack_after's)."""
    post = dict(post) if isinstance(post, dict) else {}
    a = {"defender": _defender_after(pre, post), "defender_hp_before": pre.get("def_hp"),
         "my_hp_before": pre.get("my_hp"), **post}
    dealt = _loss(a.get("defender_hp_before"), a.get("def_hp"), bool(a.get("defender_killed")))
    taken = _loss(a.get("my_hp_before"), a.get("my_hp"), bool(a.get("my_unit_killed")))
    if dealt is not None:
        a["damage_dealt"] = dealt
    if taken is not None:
        a["damage_taken"] = taken
    if dealt or taken:
        a["roll_note"] = ROLL_NOTE
    return a


def nothing_happened(a: dict) -> bool:
    """Both sides stand as before: the moves ran out on the way and nobody fought (live t327)."""
    return a.get("def_hp") == a.get("defender_hp_before") and a.get("my_hp") == a.get("my_hp_before")


def no_combat_block(a: dict) -> dict:
    return {"happened": False, "defender": a.get("defender"),
            "note": "moves ran out before reaching the target: no combat this turn. The standing order is dropped "
                    "at turn start (an enemy is on the destination); order(to='unit', action='move') onto it again "
                    "next turn to attack"}


def mark_captured(a: dict, new_unit_id: int) -> None:
    """A civilian "defender" that vanished was taken, not killed: the unit of its type now ours on the plot."""
    a.pop("defender_killed", None)
    a.pop("damage_dealt", None)
    if not a.get("damage_taken"):
        a.pop("roll_note", None)
    a["captured"] = True
    a["captured_unit_id"] = new_unit_id
    d = a.get("defender")
    if isinstance(d, dict):
        d.pop("killed", None)
        d.pop("hp", None)
        d["captured"] = True


def _defender_after(pre: dict, post: dict) -> dict | None:
    d = pre.get("defender")
    if not isinstance(d, dict):
        return d
    d = dict(d)
    if post.get("defender_killed"):
        d["hp"], d["killed"] = 0, True
    elif isinstance(post.get("def_hp"), int):
        d["hp"] = post["def_hp"]
    return d


def _loss(before, after, killed: bool) -> int | None:
    if not isinstance(before, int):
        return None
    if killed:
        return before
    if isinstance(after, int):
        return max(0, before - after)
    return None
