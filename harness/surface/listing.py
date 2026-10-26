"""What the listing shows for `order` (GitLab #49, stage 2b): the per-target action enums as a `oneOf`, or a
plain string with the same words in prose for a client that does not render `oneOf`.

The MCP `inputSchema` is the one place a client can validate a call before the server sees it, and the
action tables of `harness.surface.vocabulary` are the one place the actions live; this module writes the
former from the latter. `oneOf` on `to` is JSON Schema's way to say "the actions of `unit` are these, of
`city` those": each branch fixes `to` with `const` and lists its `action` enum. Which client renders that is
a measurement, not a guess (the table is in `docs/ARCHITECTURE.md`); a client that does not gets the flat
variant -- `to` still an enum, `action` a string whose description carries the per-target lists -- and the
server's own refusal (`harness.surface.dispatch`) still names the shape either way. The variant is chosen per
connected client by the `clientInfo` name of the MCP handshake (`FLAT_CLIENTS`), or forced with
`CIV5_ORDER_SCHEMA` / `--order-schema`.
"""
from __future__ import annotations

import copy
import os
from typing import Mapping

from harness.surface import vocabulary as V

ONEOF, FLAT = "oneof", "flat"
VARIANTS = (ONEOF, FLAT)
ENV = "CIV5_ORDER_SCHEMA"

#: Lower-case prefixes of `clientInfo.name` for the clients measured not to render `oneOf` (#49's table).
#: Empty until a client is measured; Claude Code renders it (2026-10-25).
FLAT_CLIENTS: tuple[str, ...] = ()



def variant_for(client_name: str | None, env: Mapping[str, str] | None = None) -> str:
    """The variant a client is shown: the environment's word when set, else `FLAT_CLIENTS` by name, else oneOf."""
    forced = (env if env is not None else os.environ).get(ENV, "").strip().lower()
    if forced in VARIANTS:
        return forced
    name = (client_name or "").strip().lower()
    if name and any(name.startswith(prefix) for prefix in FLAT_CLIENTS):
        return FLAT
    return ONEOF


def actions_of(to: str) -> list[str]:
    """The named actions of a target (the screen-button placeholder left out)."""
    return [a for a in V.ACTIONS[to] if a != V.SCREEN_BUTTON]


def _action_prose(to: str) -> str:
    words = ", ".join(actions_of(to))
    if V.SCREEN_BUTTON in V.ACTIONS[to]:
        words += f", or a city-state screen button by its name ({', '.join(V.SCREEN_BUTTONS)})"
    return words


def branches() -> list[dict]:
    """One `oneOf` branch per target: `to` fixed, `action` its enum (a string where the list is open)."""
    out = []
    for to, acts in V.ACTIONS.items():
        if V.SCREEN_BUTTON in acts:
            action: dict = {"type": "string", "description": _action_prose(to)}
        else:
            action = {"enum": list(acts)}
        out.append({"properties": {"to": {"const": to}, "action": action}})
    return out


def order_schema(base: dict, variant: str = ONEOF) -> dict:
    """The `order` tool's input schema in one variant, grown from the schema the SDK generated for the function
    (its argument titles, defaults and `required` are kept): `to` gains its enum; oneOf adds the branches, flat
    puts the same words into `action`'s description."""
    if variant not in VARIANTS:
        raise ValueError(f"order schema variant must be one of {VARIANTS}, not {variant!r}")
    sch = copy.deepcopy(base)
    props = sch.setdefault("properties", {})
    props.setdefault("to", {"type": "string"})["enum"] = list(V.ACTIONS)
    action = props.setdefault("action", {"type": "string"})
    if variant == ONEOF:
        action["description"] = "the verb; its words depend on `to` (oneOf below)"
        sch["oneOf"] = branches()
    else:
        action["description"] = "the verb, by target -- " + "; ".join(f"{to}: {_action_prose(to)}" for to in V.ACTIONS)
        sch.pop("oneOf", None)
    return sch


def variant_of(schema: dict) -> str:
    """Which variant a schema is (the tests and the measurements read it back)."""
    return ONEOF if "oneOf" in schema else FLAT
