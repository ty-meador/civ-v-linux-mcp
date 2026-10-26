"""The affordance audit (GitLab #44): which replies hand back `{tool, args}` rows and which hand back a tool
name in prose, by file and key.

Three things the new surface builds on already exist: the harness computes affordances from the engine's
own answers (`todo_actions`, every `available_*` and `*_options` read, `city_state_actions`, `trade_catalog`),
`harness/gate.py` names the read to make and the call that clears every blocking state, and `do(actions)` /
`finish_turn(actions)` take orders as `{tool, args}` rows. What is missing is that the affordances come back
as words: `harness/briefing.py` writes a todo row's tool as a sentence, the gate's rows are bare names. This
module finds those sites statically (the AST of every harness source file, no game needed) so stage 1 can
close the seam and the survey can say when it is closed.
"""
from __future__ import annotations

import ast
import inspect as _inspect
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from harness.surface import retirement as R

ROOT = Path(__file__).resolve().parents[2]
#: The dict keys a reply or a refusal uses to say what can be done next.
KEYS = ("tool", "hint", "clear_with", "read_first", "also")
ROW_KEY = "{tool, args}"
WORD = re.compile(r"[a-z_][a-z0-9_]*")


@dataclass(frozen=True)
class Site:
    file: str      # relative to the repo root
    line: int
    key: str       # one of KEYS, or ROW_KEY for a `{tool, args}` row literal
    kind: str      # rows | name | names | prose | text | dynamic
    text: str      # the literal, or a short description of a non-literal


def source_files() -> list[Path]:
    """Every harness source file the audit reads: the core, the tool modules and the game mixins."""
    pats = ("harness/*.py", "harness/mcp_tools/*.py", "harness/game_parts/*.py")
    return sorted(p for pat in pats for p in ROOT.glob(pat))


def _literal_text(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{...}" for v in node.values)
    return None


def _is_row_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Dict) and {"tool", "args"} <= {k.value for k in node.keys
                                                              if isinstance(k, ast.Constant)}


def classify(key: str, value: ast.AST, names: set[str]) -> tuple[str, str]:
    """(kind, text) of one `key: value` pair: `name` is exactly one tool name, `names` a list of them, `prose`
    a sentence naming at least one tool, `text` a sentence naming none, `dynamic` not a literal at all."""
    if isinstance(value, (ast.List, ast.Tuple)):
        items = [_literal_text(e) for e in value.elts]
        if items and all(i in names for i in items):
            return "names", ", ".join(items)  # type: ignore[arg-type]
    text = _literal_text(value)
    if text is None:
        return "dynamic", ast.unparse(value)[:80]
    if text.strip() in names:
        return "name", text.strip()
    named = sorted(set(WORD.findall(text)) & names)
    return ("prose" if named else "text"), text


def scan(names: Iterable[str], files: Iterable[Path] | None = None) -> list[Site]:
    """Every site in the harness source that names what can be done next, classified."""
    names = set(names)
    out: list[Site] = []
    for path in (files if files is not None else source_files()):
        rel = str(path.relative_to(ROOT))
        for node in ast.walk(ast.parse(path.read_text(), filename=rel)):
            if not isinstance(node, ast.Dict):
                continue
            if _is_row_literal(node):
                out.append(Site(rel, node.lineno, ROW_KEY, "rows", ast.unparse(node)[:80]))
                continue  # its own `tool` key is the row, not a name
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value in KEYS:
                    kind, text = classify(k.value, v, names)
                    out.append(Site(rel, v.lineno, k.value, kind, text))
    return out


def summary(sites: list[Site]) -> list[dict]:
    """Counts per kind, by file and key."""
    per: dict[tuple[str, str], Counter] = {}
    for s in sites:
        per.setdefault((s.file, s.key), Counter())[s.kind] += 1
    return [{"file": f, "key": k, **c} for (f, k), c in sorted(per.items())]


def seam(sites: list[Site]) -> list[Site]:
    """The sites stage 1 turns into rows: a tool name, a list of them, or a sentence naming one."""
    return [s for s in sites if s.kind in ("name", "names", "prose")]


# --- the replies that list what can be done -----------------------------------------------------------
#: `(what, view)` keys of the reads that list choices (besides every `question` row and the todo rows).
CHOICE_VIEWS = frozenset({("inspect:units", "actions"), ("inspect:unit", "actions"), ("inspect:unit", "targets"),
                          ("inspect:unit", "home"), ("inspect:city", "production"), ("inspect:city", "strikes"),
                          ("inspect:civ", "trade_catalog"), ("inspect:city_state", "summary"),
                          ("inspect:city_state", "full")})
TODO_READS = ("turn_status", "briefing", "finish_turn")


def is_affordance_read(name: str) -> bool:
    row = R.RETIRED.get(name)
    if row is None:
        return False
    return (name in TODO_READS or row.tool == "question" or row.key in CHOICE_VIEWS
            or row.key[0] == "inspect:options")


CALL = re.compile(r"\.([a-z_][a-z0-9_]*)\(")


def _handler_sources(tool) -> list[str]:
    """The handler's own source, plus the functions it calls by name in its domain's game mixin
    (harness/game_parts/<module>.py), where the reply is composed; the todo reads add harness/briefing.py."""
    srcs = []
    try:
        srcs.append(_dedent(_inspect.getsource(tool.fn)))
    except (OSError, TypeError):
        pass
    called = set(CALL.findall(srcs[0])) if srcs else set()
    module = (getattr(tool.fn, "__module__", "") or "").rsplit(".", 1)[-1]
    twin = ROOT / "harness" / "game_parts" / f"{module}.py"
    if twin.exists():
        for node in ast.parse(twin.read_text()).body:
            if isinstance(node, ast.ClassDef):
                srcs.extend(ast.unparse(fn) for fn in node.body
                            if isinstance(fn, ast.FunctionDef) and fn.name in called)
    if tool.name in TODO_READS:
        srcs.append((ROOT / "harness" / "briefing.py").read_text())
    return srcs


def replies(tools: Iterable) -> list[dict]:
    """For every reply that lists what can be done: whether its handler (or the mixin composing it) emits
    `{tool, args}` rows, or hands the choices back by name only."""
    out = []
    for t in tools:
        if not is_affordance_read(t.name):
            continue
        rows = any(_is_row_literal(n) for src in _handler_sources(t) for n in ast.walk(ast.parse(src)))
        out.append({"reply": t.name, "module": (getattr(t.fn, "__module__", "") or "").rsplit(".", 1)[-1],
                    "key": " / ".join(R.RETIRED[t.name].key), "carries": "rows" if rows else "names only"})
    return out


def _dedent(src: str) -> str:
    import textwrap
    return textwrap.dedent(src)
