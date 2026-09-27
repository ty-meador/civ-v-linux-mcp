"""The rule book, the playbook, the MCP resources and prompt, and the opt-in raw Lua tool.

One of the civ5 MCP server's tool modules: every tool here registers on the server in
harness/mcp_server.py, which keeps the game handle, the guard and the tool sets (see its docstring).
"""
from __future__ import annotations

from pathlib import Path

from harness import guide

from harness import mcp_server as core
from harness.mcp_server import mcp, J, guarded, lua_allowed


@guarded
def lua(code: str) -> str:
    """Escape hatch: run Lua in the InGame context and return printed output. Use the Civ V modding API
    (Players[i], Game, Map...). CAUTION: an unfamiliar or unvalidated engine call here can crash the whole
    game process outright, not just error -- this has happened before. Check the dedicated tools above
    first (there are more than it looks like: city_ranged_attack, choose_policy, found_pantheon/religion,
    trade routes, diplo_event...) and docs/lua_command_patterns.md / docs/lua_api_surface.md before writing
    a new raw call, and prefer a validated read (does the object have the method? does a Can*() check pass?)
    before a write. Disabled unless the server was started with CIV5_ALLOW_LUA=1 / --allow-lua."""
    if not lua_allowed():
        return J({"ok": False, "err": "raw lua is disabled for this server (start it with CIV5_ALLOW_LUA=1 or --allow-lua); "
                                      "use the dedicated tools instead"})
    return J(core.game().lua("InGame", code, timeout=20))


def register_lua_if_allowed() -> bool:
    """`lua` is deliberately NOT decorated with @mcp.tool(): it only appears in the tool list when the
    operator opts in. The in-body lua_allowed() check is the second fence for anyone calling the function directly."""
    if lua_allowed() and "lua" not in {t.name for t in mcp._tool_manager.list_tools()}:
        mcp.tool()(lua)
        return True
    return False


@mcp.tool()
def how_to_play(topic: str = "") -> str:
    """How to play through these tools, from the playbook shipped with this server; needs no game and works at
    any time. With no topic: the index of topics and the introduction (what you are, what you see, `gate`,
    seats, loading a game). Playbook topics: start, turn_loop (every turn in order; two agents or two clients on
    one game), quiet_turns (skip_quiet_turns and what wakes a run), batches (do and action_id), verify,
    blockers (the end-turn blocker table and what clears each), diplomacy (leader screens, discussions, the
    trade table), rules (what the harness refuses on purpose), first_turn; "all" is the whole playbook. A tool
    name -- finish_turn, briefing, turn_status, overview, compare, propose_deal, give_order -- is that reply's
    full key-by-key reference, the part its own description leaves out. Read a topic once, when you first
    need it; the answer is Markdown."""
    return guide.how_to_play(topic)


@mcp.tool()
@guarded
def reference(section: str | None = None) -> str:
    """The rule book, as Markdown: what every unit, building, wonder, project, process, promotion, social
    policy and ideology tenet, technology, belief, resource, terrain, feature, improvement, specialist and
    unit action does, read once from this game's own database (mods and DLC included) and cached. No other
    answer repeats this text (since runtime v216): chooser rows carry the enum, the name and live numbers,
    and a resource tile carries its resource name. Sections, one per call with `section`: terrain,
    resources, improvements, units, buildings, projects, processes, promotions, policies, techs, beliefs,
    specialists, actions. The whole book is long (tens of thousands of tokens): read it once at the start of
    a game if you can hold it, otherwise the section a choice needs. Also served as the MCP resources
    civ5://reference and civ5://reference/{section}. Usable while it is not
    my turn."""
    out = core.game().reference_markdown(section)
    return out if isinstance(out, str) else J(out)


@mcp.resource("civ5://reference", name="reference", description="The rule book: what every unit, building, tech, policy, promotion, belief, resource, terrain, improvement and unit action does, from this game's database. Markdown.", mime_type="text/markdown")
def reference_resource() -> str:
    out = core.game().reference_markdown()
    return out if isinstance(out, str) else J(out)


@mcp.resource("civ5://reference/{section}", name="reference_section", description="One section of the rule book: terrain, resources, improvements, units, buildings, projects, processes, promotions, policies, techs, beliefs, specialists or actions. Markdown.", mime_type="text/markdown")
def reference_section_resource(section: str) -> str:
    out = core.game().reference_markdown(section)
    return out if isinstance(out, str) else J(out)


@mcp.resource("civ5://playbook", name="playbook", description="How to play through this harness: the turn loop, the blocker table, verification habits.")
def playbook_resource() -> str:
    path = Path(__file__).resolve().parent.parent / "docs" / "PLAYBOOK.md"
    try:
        return path.read_text()
    except OSError:
        return "PLAYBOOK.md is not installed alongside this server."


@mcp.prompt(name="play_turn", description="Play one turn of Civilization V through the civ5 tools.")
def play_turn_prompt() -> str:
    return ("Play my current turn of Civilization V through the civ5 tools. Start with briefing(since=\"turn\") "
            "(or the finish_turn result that brought you here) and read its gate first; how_to_play() explains "
            "the loop if you are new to it. Clear every item in decisions: todo_actions for the units, "
            "available_production then set_production for empty cities, available_research then set_research, "
            "answer any popup or leader screen. Give a repeating plan as one give_order. Then remember() what "
            "future-you must know and finish_turn. Never guess a plot or an id you have not read this turn.")
