"""The registered tools' schemas, read lazily (a leaf of `harness.surface`).

Both directions of the retirement map need the schema of a registered tool: `dispatch` (new -> old) checks
the old handler's required and known arguments and prints its signature in a refusal; `forward` (old -> new)
splits an old call's arguments between the new tool's top-level selectors and its `args` object. The server
module imports this package's tool module, so the lookup is deferred to call time; outside a server (a bare
import of the package) every schema is empty.
"""
from __future__ import annotations


def schema(name: str) -> dict:
    """The JSON schema of a registered (or retired, still callable) tool, `{}` for an unknown name."""
    from harness import mcp_server as core
    tool = core.mcp._tool_manager.get_tool(name) or core.retired_tools().get(name)
    return dict(tool.parameters) if tool is not None else {}


def signature(name: str) -> str:
    """`name(arg: type = default, ...)` as the refusals print it."""
    from harness import mcp_server as core
    return f"{name}{core.tool_signature(schema(name))}"


def type_text(prop: dict) -> str:
    """A JSON-schema property's type as the signatures print it: `integer`, `integer/null`, `any`."""
    return prop.get("type") or "/".join(x.get("type", "?") for x in prop.get("anyOf", [])) or "any"


def required(name: str) -> set[str]:
    return set(schema(name).get("required") or [])


def properties(name: str) -> set[str]:
    return set((schema(name).get("properties") or {}).keys())


def placeholder(name: str, arg: str) -> object:
    """One stand-in value for an argument, by its declared type: the examples and the round-trip test use it."""
    p = (schema(name).get("properties") or {}).get(arg) or {}
    t = p.get("type") or next((x.get("type") for x in p.get("anyOf", []) if x.get("type") != "null"), "string")
    return {"integer": 1, "number": 1, "boolean": True, "array": [], "object": {}}.get(t, f"<{arg}>")
