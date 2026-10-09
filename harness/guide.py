"""The `how_to_play` tool: the playbook and the long reply references, served by topic.

Two Markdown files ship with the package's docs: `docs/PLAYBOOK.md` (how to play through the tools) and
`docs/TOOL_REPLIES.md` (every key of the replies whose full description outgrew a tool docstring). A client
shows a tool's description whole only up to a couple of thousand characters -- Claude Code cuts it there --
and the server instructions the same, so the docstrings and instructions carry what a turn needs and point
here for the rest. No game is needed to read any of it.
"""
from __future__ import annotations

import re
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
PLAYBOOK = DOCS / "PLAYBOOK.md"
TOOL_REPLIES = DOCS / "TOOL_REPLIES.md"

# topic -> (the heading it starts at in PLAYBOOK.md, one line for the index). "" is the text before the first
# heading. A topic runs to the next heading of its own level or higher, so a ## topic keeps its ### parts.
PLAYBOOK_TOPICS: dict[str, tuple[str, str]] = {
    "start": ("", "what you are, what you see, `gate`, seats, loading a game"),
    "turn_loop": ("## The turn loop", "every turn in order: finish_turn, decisions, notes; two agents or two clients on one game"),
    "quiet_turns": ("### Letting quiet turns pass", "skip_quiet_turns, wake_on, what wakes a run"),
    "batches": ("## Many orders, one call", "do(actions), action_id replay"),
    "verify": ("## Verify, do not assume", "read back what an order did; ids and plots"),
    "blockers": ("## What `blocking_name` means", "the end-turn blocker table and the tool that clears each"),
    "diplomacy": ("## Leader screens and diplomacy", "leader screens, discussions, deals, the trade table"),
    "rules": ("## Rules of the house", "what the harness refuses on purpose"),
    "first_turn": ("## Minimal first turn", "the shortest correct first turn"),
}
_HEADING = re.compile(r"^(#{1,6}) ", re.MULTILINE)


def _read(path: Path) -> str:
    try:
        return path.read_text()
    except OSError:
        return ""


def _sections(text: str) -> list[tuple[int, str, str]]:
    """(level, heading line, body including the heading) for every heading; level 0 is the preamble."""
    out: list[tuple[int, str, str]] = []
    starts = [(m.start(), len(m.group(1))) for m in _HEADING.finditer(text)]
    if not starts or starts[0][0] > 0:
        end = starts[0][0] if starts else len(text)
        out.append((0, "", text[:end]))
    for i, (pos, level) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        line = text[pos:text.find("\n", pos) if "\n" in text[pos:] else len(text)]
        out.append((level, line, text[pos:end]))
    return out


def playbook_topic(topic: str) -> str | None:
    heading, _ = PLAYBOOK_TOPICS[topic]
    secs = _sections(_read(PLAYBOOK))
    if heading == "":
        # the introduction: the text under the document title (or before it), up to the first section
        return secs[0][2] if secs and secs[0][0] <= 1 else None
    for i, (level, line, body) in enumerate(secs):
        if line.startswith(heading):
            parts = [body]
            for lvl, _, more in secs[i + 1:]:
                if lvl <= level:
                    break
                parts.append(more)
            return "".join(parts)
    return None


def reply_topics() -> list[str]:
    """The tools with a reply reference: the `## <tool>` headings of TOOL_REPLIES.md, in file order."""
    return [line[3:].strip() for level, line, _ in _sections(_read(TOOL_REPLIES)) if level == 2]


def reply_topic(tool: str) -> str | None:
    for level, line, body in _sections(_read(TOOL_REPLIES)):
        if level == 2 and line[3:].strip() == tool:
            return body
    return None


def index() -> str:
    lines = ["# how_to_play: topics", "",
             "One topic per call: `how_to_play(topic)`. `how_to_play(\"all\")` is the whole playbook.", "",
             "Playbook:"]
    for key, (_, blurb) in PLAYBOOK_TOPICS.items():
        lines.append(f"- `{key}`: {blurb}")
    replies = reply_topics()
    if replies:
        lines += ["", "Reply references (every key of the tool's answer, beyond what its description holds):"]
        lines += [f"- `{name}`" for name in replies]
    return "\n".join(lines) + "\n"


def how_to_play(topic: str | None = None) -> str:
    """The text for `topic`: a playbook topic, a tool with a reply reference, "all", or the index."""
    topic = (topic or "").strip()
    if not topic or topic == "index":
        return index() + "\n" + (playbook_topic("start") or "")
    if topic == "all":
        return _read(PLAYBOOK) or "PLAYBOOK.md is not installed alongside this server."
    if topic in PLAYBOOK_TOPICS:
        body = playbook_topic(topic)
        return body if body is not None else f"PLAYBOOK.md has no section for {topic!r} (is docs/ installed?)."
    body = reply_topic(topic)
    if body is not None:
        return body
    known = ", ".join(list(PLAYBOOK_TOPICS) + ["all"] + reply_topics())
    return f"unknown topic {topic!r}; topics: {known}"
