"""The word a bare game icon stands for.

The engine's text normally writes an icon before its word ("[ICON_GOLD] Gold") and plain_text drops the icon.
Some strings carry the icon alone -- the God-King pantheon reads "Palace provides +1 to these yields:
[ICON_CULTURE] , [ICON_PEACE] , [ICON_GOLD], [ICON_PRODUCTION], [ICON_RESEARCH]" -- and there the icon's
name is the only word left. Most names read as their yield once title-cased (Gold, Culture, Tourism); the
ones below do not: the faith icon is named after the dove, science after the flask, and a happiness face
carries a number (GitLab #103, hotseat Maya t3: "Culture, Peace, Gold, Production, Research").

The Lua runtime keeps the same table in empire.lua (plain_text's icon_word); tests/test_plain_text_icons.py
holds both sides to it.
"""
from __future__ import annotations

#: Icon name (without the ICON_ prefix) -> the word it stands for, where the name itself misleads.
ICON_WORDS: dict[str, str] = {
    "PEACE": "Faith",
    "RESEARCH": "Science",
    "HAPPINESS_1": "Happiness",
    "HAPPINESS_3": "Unhappiness",
    "HAPPINESS_4": "Unhappiness",
    "GREATPEOPLE": "Great People",
    "RANGE_STRENGTH": "Ranged Strength",
    "TURNS_REMAINING": "Turns",
    "INTERNATIONAL_TRADE": "Trade Route",
}


def icon_word(name: str) -> str:
    """The word for a bare [ICON_<name>]: the table's entry, a resource icon's resource (RES_HORSE -> Horse), or
    the name title-cased with its underscores as spaces (IDEOLOGY_ORDER -> Ideology Order)."""
    hit = ICON_WORDS.get(name)
    if hit is not None:
        return hit
    if name.startswith("RES_"):
        name = name[4:]
    return name.replace("_", " ").title()
