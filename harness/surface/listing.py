"""What the listing shows for `order` (GitLab #49, stage 2b): `to` an enum, `action` a string whose
description lists the verbs by target -- one shape for every client.

The action tables of `harness.surface.vocabulary` are the one place the actions live; this module writes the
listed `inputSchema` from them. Stage 2b first offered the per-target enums as a `oneOf` on `to` (one branch per
target, `to` fixed with `const`, `action` its enum) with this flat shape as a fallback chosen per client. The
measurement on the three clients (the table in `docs/ARCHITECTURE.md`, 2026-10-25 to 2026-10-27) ended that:
Codex rendered the `oneOf` as a union of the branches alone and lost `id` and `args`; Claude Code rendered it
as one wrong sentence ("exactly one of: to, action") and lost the enums; Grok passed it through verbatim and
validated nothing. No client validated the pair before the server saw it, and the words the branches carried
were already in `action`'s description, so the `oneOf` bought nothing anywhere and cost something everywhere:
TDQS counts each `oneOf` branch as invocation cost (14 against `answer`'s 3) and flagged `order` as shadowed
by its cheaper sibling. One flat shape, and the server's own refusal (`harness.surface.dispatch`) names the
legal verbs either way.
"""
from __future__ import annotations

import copy

from harness.surface import vocabulary as V


def actions_of(to: str) -> list[str]:
    """The named actions of a target (the screen-button placeholder left out)."""
    return [a for a in V.ACTIONS[to] if a != V.SCREEN_BUTTON]


def _action_prose(to: str) -> str:
    words = ", ".join(actions_of(to))
    if V.SCREEN_BUTTON in V.ACTIONS[to]:
        words += f", or a city-state screen button by its name ({', '.join(V.SCREEN_BUTTONS)})"
    return words


def order_schema(base: dict) -> dict:
    """The `order` tool's listed input schema, grown from the schema the SDK generated for the function (its
    argument titles, descriptions, defaults and `required` are kept): `to` gains its enum, `action` the verbs by
    target in its description."""
    sch = copy.deepcopy(base)
    props = sch.setdefault("properties", {})
    props.setdefault("to", {"type": "string"})["enum"] = list(V.ACTIONS)
    action = props.setdefault("action", {"type": "string"})
    action["description"] = "the verb, by target -- " + "; ".join(f"{to}: {_action_prose(to)}" for to in V.ACTIONS)
    sch.pop("oneOf", None)
    return sch
