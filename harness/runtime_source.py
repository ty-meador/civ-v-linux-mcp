"""The Lua runtime's source: ordered fragments under harness/lua/runtime/, assembled into the one chunk that
Game.ensure_runtime injects (GitLab #42).

The runtime used to be one 11.5k-line runtime.lua. It is now a file per game domain, but the fragments are
still *one* Lua chunk when they run: some 130 top-level locals (L, short, info_type, own_active_unit, the
network-command helpers, ...) are upvalues shared across domains, and a fragment compiled on its own would
silently read them as nil globals. So MANIFEST is a load ORDER as well as a file list: a local is visible only
to the fragments after the one that declares it. Nothing here wraps a fragment in `do ... end` or in its own
loadstring(), for the same reason.

Fragments are joined with a comment line naming the file (`-- @@ events.lua`), so the assembled text is valid
Lua and RuntimeSource.locate() maps an assembled-chunk line back to a fragment and its own line. The digest is
the SHA-256 of that exact assembled text; game.py compares it with H.source_hash inside the game, so editing
any fragment (or renaming one, or reordering MANIFEST) re-injects the runtime whether or not RUNTIME_VERSION
was bumped. RUNTIME_VERSION itself lives in bootstrap.lua and still goes up with every runtime change
(CHANGELOG.md, #26): a stale MCP server re-injects the version it started with, and the number is what a live
session can read back.

Production and tests both load through snapshot(): there is no second, hand-maintained monolith. One snapshot
is one read of every file, and its digest and its text agree by construction.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
from dataclasses import dataclass

RUNTIME_DIR = pathlib.Path(__file__).with_name("lua") / "runtime"

# Load order. A fragment may use the H.* functions of any other (looked up at call time) but only the top-level
# locals of the fragments ABOVE it. The comments name the shared locals a fragment declares for later ones.
MANIFEST: tuple[str, ...] = (
    "bootstrap.lua",          # RUNTIME_VERSION; replaces H, carrying over the allowlist of accumulated state
    "json.lua",               # H.json / H.emit; local esc
    "helpers.lua",            # shared locals: L (also H.L), info_type, short, own_active_unit, info_id, move_denom,
                              #   require_revealed_plot, selected_is, net_unit_message, push_mission, do_command
    "events.lua",             # event recorder: H.record, cursors, capture attribution, rosters, hp snapshots,
                              #   H.install_hooks (called from install.lua)
    "empire.lua",             # player summary, resources, happiness, gold/science/culture/tourism/faith breakdowns,
                              #   ideology switch; shared locals: plain_text, plain_key
    "units.lua",              # unit list, unit supply, idle trade units and spies, promotions
    "city_views.lua",         # city list and city screen: yields, meters, specialists, hovers
    "city_actions.lua",       # citizen management, plot purchase, annex/raze, sell building; the puppet guards;
                              #   shared local: own_city
    "map.lua",                # plots, the fog cache of remembered features, revealed map and its index, known world
    "diplomacy.lua",          # relationship view
    "policies.lua",           # social policy screen
    "notifications.lua",      # pending notifications
    "diplomacy_actions.lua",  # met-civ list with war/peace facts, enum-name cache (H.enum_name), discussion events
    "city_strikes.lua",       # city ranged attacks, units on a plot
    "unit_orders.lua",        # promotion, upgrade, disband
    "choices.lua",            # popup choosers: steal tech, policy, free great person, goody hut, ideology, Maya, archaeology
    "religion.lua",           # religion overview, faith purchases, beliefs, pantheon and religion founding
    "deals.lua",              # deal items and catalogs, incoming/current deals, peace and third-party catalogs, vote gate
    "war.lua",                # city-capture popup and the consequences of a war declaration
    "city_states.lua",        # quests, gifts, influence actions, tile-improvement gifts, tribute
    "trade_routes.lua",       # route options, yields, paths, establishment and plunder
    "league.lua",             # World Congress: proposals, votes, projects
    "overviews.lua",          # victory progress, global relations, wonders, intrigue, demographics, great works
    "espionage.lua",          # spies, potential and catch modifiers, coups
    "research.lua",           # tech tree, tech unlocks, research choice
    "production.lua",         # production choices
    "unit_actions.lua",       # legal actions and missions per unit, action help, todo_actions
    "combat.lua",             # melee defender and peaceful-occupant facts, combat modifier rows (cm_*), city strike modifiers
    "combat_previews.lua",    # melee and ranged previews and targets, air strikes, interception, attack before/after
    "tactical.lua",           # activity names, unit_pos, explore frontier, tactical view
    "movement.lua",           # move_unit / move_refusal, standing moves, unit missions, automate and build checks
    "turn.lua",               # popups, blockers, todo, turn_state, expiring deals, notification log, net players
    "victory.lua",            # culture overview, spaceship status
    "reference.lua",          # the rule book: static database reads
    "briefing.lua",           # briefing board
    "assignments.lua",        # assignment facts
    "comparisons.lua",        # compare_* reads (#34)
    "install.lua",            # runs last: H.install_hooks()
)

MARKER = "-- @@ "                        # boundary line in the assembled text: "-- @@ events.lua"
CHUNK_NAME = "harness_runtime"           # the loadstring() chunk name game.py gives the assembled text
PRELUDE = "if H then H.version = -1 end\n"   # a changed source reloads even without a version bump
_VERSION_RE = re.compile(r"^local RUNTIME_VERSION = (\d+)$", re.M)
_CHUNK_LINE_RE = re.compile(r'\[string "' + re.escape(CHUNK_NAME) + r'"\]:(\d+):')


class RuntimeSourceError(RuntimeError):
    """The runtime source cannot be assembled (a manifest entry is missing, or bootstrap has no version)."""


@dataclass(frozen=True)
class Fragment:
    name: str
    path: pathlib.Path
    text: str      # the file as read (UTF-8), normalised to end with exactly one newline

    @property
    def lines(self) -> int:
        return self.text.count("\n")


@dataclass(frozen=True)
class RuntimeSource:
    """One read of every fragment: the assembled text, its digest and version, and the line map."""
    fragments: tuple[Fragment, ...]
    text: str        # the assembled chunk: what is hashed, and what runs (inside install_chunk())
    digest: str      # sha256 of text
    version: int     # RUNTIME_VERSION from bootstrap.lua

    def fragment(self, name: str) -> Fragment:
        for f in self.fragments:
            if f.name == name:
                return f
        raise KeyError(name)

    def install_chunk(self) -> str:
        """What Game.ensure_runtime injects: force a reload, run the source, mark it current last."""
        return PRELUDE + self.text + f"\nH.source_hash = '{self.digest}'\n"

    def locate(self, line: int, *, installed: bool = False) -> tuple[str, int] | None:
        """(fragment, line in that fragment) for a line of `text`, or of install_chunk() when `installed`.
        Line 0 of a fragment is its boundary marker; one past its last line is the blank separator."""
        if installed:
            line -= PRELUDE.count("\n")
        start = 1
        for f in self.fragments:
            span = f.lines + 2   # marker + body + separator
            if line < start + span:
                return (f.name, line - start) if line >= start else None
            start += span
        return None

    def locate_error(self, message: str) -> str | None:
        """'events.lua:57' for a Lua error raised by the installed chunk, or None when it names no line."""
        m = _CHUNK_LINE_RE.search(message)
        if not m:
            return None
        where = self.locate(int(m.group(1)), installed=True)
        return f"{where[0]}:{where[1]}" if where else None


def read_fragments(directory: pathlib.Path | None = None, manifest: tuple[str, ...] | None = None) -> tuple[Fragment, ...]:
    """Every manifest entry, in order. Fails before anything is read when one is missing."""
    directory = RUNTIME_DIR if directory is None else directory
    manifest = MANIFEST if manifest is None else manifest
    missing = [name for name in manifest if not (directory / name).is_file()]
    if missing:
        raise RuntimeSourceError(
            f"runtime source incomplete: {', '.join(missing)} missing under {directory} "
            f"(harness/runtime_source.py MANIFEST lists {len(manifest)} fragments)")
    out = []
    for name in manifest:
        text = (directory / name).read_text(encoding="utf-8")
        out.append(Fragment(name, directory / name, text.rstrip("\n") + "\n"))
    return tuple(out)


def assemble(fragments: tuple[Fragment, ...]) -> str:
    return "\n".join(f"{MARKER}{f.name}\n{f.text}" for f in fragments)


def snapshot(directory: pathlib.Path | None = None, manifest: tuple[str, ...] | None = None) -> RuntimeSource:
    """One read of the runtime source (RUNTIME_DIR and MANIFEST unless given: tests point at a copy)."""
    fragments = read_fragments(directory, manifest)
    text = assemble(fragments)
    m = _VERSION_RE.search(fragments[0].text)
    if not m:
        raise RuntimeSourceError(f"{fragments[0].name} declares no `local RUNTIME_VERSION = N`")
    return RuntimeSource(fragments, text, hashlib.sha256(text.encode("utf-8")).hexdigest(), int(m.group(1)))
