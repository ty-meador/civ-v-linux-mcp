"""The Lua side of the affordance audit (GitLab #57): which runtime strings name a retired tool.

`harness.surface.audit` reads the Python sources as an AST and finds every reply key whose literal names an
old tool. The Lua runtime (`harness/lua/runtime/*.lua`) names tools too, only inside the strings it hands up:
a blocker's hint, a refusal's `why`, a `how` row. Those strings reach the model as they are, so once the
listing is the nine tools they must say the new call as well. This module finds them with the same rule the
Python audit applies (`audit.named_in`: a call form, or a bare word that is not also a word of a sentence),
over the string literals of every fragment, comments left out. The survey prints its count by file and the
suite asserts it is zero.
"""
from __future__ import annotations

import pathlib
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from harness import runtime_source
from harness.surface import audit
from harness.surface import retirement as R
from harness.surface import vocabulary as V

#: A Lua string literal on one line (`'...'` or `"..."`, backslash escapes), or the start of a comment.
_TOKEN = re.compile(r"""'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|--""")
#: A literal that is exactly a word of the vocabulary (an action, a view, a choice) is that value -- the
#: city-state screen's `declare_war` button, compared or listed by name -- not the tool that shares its name.
VALUE_WORDS = frozenset(w for table in (V.ACTIONS, V.VIEWS) for words in table.values() for w in words) | frozenset(
    V.SCREEN_BUTTONS + V.TURN_ACTIONS + V.ANSWER_CHOICES + V.NOTEBOOK_ACTIONS + V.SESSION_ACTIONS + V.BOOKS)


@dataclass(frozen=True)
class Site:
    file: str       # the fragment's file name
    line: int       # 1-based
    names: tuple[str, ...]   # the retired names the literal names, sorted
    text: str       # the literal, quotes stripped


def string_literals(line: str) -> list[str]:
    """The string literals of one Lua line, quotes stripped, up to the first `--` outside a string."""
    out = []
    for m in _TOKEN.finditer(line):
        tok = m.group(0)
        if tok == "--":
            break
        out.append(tok[1:-1])
    return out


def names() -> set[str]:
    """The names a runtime string may not carry: every retired name but `reference`, the one that stays listed."""
    return set(R.RETIRED) - {"reference"}


def scan(retired: Iterable[str] | None = None, directory: pathlib.Path | None = None) -> list[Site]:
    """Every string literal of every runtime fragment that names a retired tool, in manifest order."""
    wanted = set(retired) if retired is not None else names()
    out: list[Site] = []
    for fragment in runtime_source.read_fragments(directory):
        for n, line in enumerate(fragment.text.splitlines(), 1):
            for text in string_literals(line):
                if text in VALUE_WORDS:
                    continue
                hit = audit.named_in(text, wanted)
                if hit:
                    out.append(Site(fragment.name, n, tuple(hit), text))
    return out


def summary(sites: list[Site]) -> list[dict]:
    """Rows of `{file, strings, names}`: the literals per fragment and the distinct names they carry."""
    per_file: dict[str, list[Site]] = {}
    for s in sites:
        per_file.setdefault(s.file, []).append(s)
    return [{"file": f, "strings": len(ss), "names": ", ".join(sorted(Counter(n for s in ss for n in s.names)))}
            for f, ss in sorted(per_file.items())]
