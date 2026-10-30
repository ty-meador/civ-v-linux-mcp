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
KEYS = ("tool", "hint", "clear_with", "read_first", "also", "how_to_answer", "leader_screen_note", "drill_down",
        "err", "note")   # a refusal's sentence and a reply's aside name what to do next as well (widened 2026-10-26)
ROW_KEY = "{tool, args}"
#: The key of a sentence found outside those keys: any string literal of the source that is prose (holds a
#: space) and is not a docstring or a Lua snippet. A bare name outside KEYS is a handler reference (the row
#: makers, the dispatch tables) and is not a site; a sentence naming an old tool anywhere is, since a reply
#: may carry it under any key (`more`, `gone_note`, `basis`, a summary) -- widened 2026-10-26 after the live
#: t241 digest said `overview.idle_trade_units` and `recall()`.
LITERAL_KEY = "(literal)"
#: Files whose sentences name old tools on purpose: the nine tools' descriptions teach the old name beside the
#: new call ("today's turn_status"), the runtime's file list is file names.
LITERAL_EXEMPT = frozenset({"harness/mcp_tools/surface.py", "harness/runtime_source.py"})
LUA_MARKS = ("H.", "Game.", "Players[", "function ", "local ")
#: Where every row is made in today's vocabulary (stage 1, #45 / #46): the shape, and the calls; a reply that
#: calls into either carries rows.
ROW_MODULES = (ROOT / "harness" / "rows.py", *sorted((ROOT / "harness" / "affordances").glob("*.py")))
ROW_MODULE_NAMES = frozenset({"rows", "affordances"})
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
    pats = ("harness/*.py", "harness/affordances/*.py", "harness/mcp_tools/*.py", "harness/game_parts/*.py")
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


#: Old names that are also plain words of a sentence (the units with a standing move, replace the order, do
#: not...), a reply key (`end_turn`, `call`) or a gate name (`discussion`): in prose they count only as a call
#: form. Shared with the tests of the words (#53).
WORDS = frozenset({"units", "cities", "orders", "demand", "denounce", "discussion", "players", "spies",
                   "compare", "do", "call", "recall", "remember", "forget", "assign", "assignments",
                   "reference", "diplomacy", "demographics", "overview", "briefing", "end_turn"})
#: A call in the nine-tool vocabulary, with its arguments (one level of nested parentheses), and a quoted value
#: (an action word, an id): neither names an old tool, whatever words they hold.
NEW_CALL = re.compile(r"\b(?:turn|state|order|question|answer|notebook|batch|session|reference)\((?:[^()]|\([^()]*\))*\)")
QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"')


def named_in(text: str, names: Iterable[str]) -> list[str]:
    """The old names a sentence names, once the new calls and the quoted values are taken out: as a call form
    (`units(`), or as a bare or backticked word when the name is not also a word (WORDS). Sorted."""
    rest = QUOTED.sub('""', NEW_CALL.sub(" ", text))
    out = set()
    for n in names:
        if re.search(rf"(?<![\w.]){n}\(", rest):
            out.add(n)
        elif n not in WORDS and re.search(rf"(?<![\w.]){n}(?![\w(]|\.py)", rest):   # a script's file name is not a call
            out.add(n)
    return sorted(out)


def classify(key: str, value: ast.AST, names: set[str]) -> tuple[str, str]:
    """(kind, text) of one `key: value` pair: `name` is exactly one tool name, `names` a list of them, `prose`
    a sentence naming at least one old tool (`named_in`), `text` a sentence naming none, `dynamic` not a
    literal at all."""
    if isinstance(value, (ast.List, ast.Tuple)):
        items = [_literal_text(e) for e in value.elts]
        if items and all(i in names for i in items):
            return "names", ", ".join(items)  # type: ignore[arg-type]
    text = _literal_text(value)
    if text is None:
        return "dynamic", ast.unparse(value)[:80]
    if text.strip() in names:
        return "name", text.strip()
    return ("prose" if named_in(text, names) else "text"), text


def _docstrings(tree: ast.AST) -> set[int]:
    """The ids of the docstring nodes: developer prose, not a reply's."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                out.add(id(first.value))
    return out


def is_prose(text: str) -> bool:
    """A sentence (not a name, a key, a Lua snippet or a path)."""
    return " " in text.strip() and not any(m in text for m in LUA_MARKS)


def scan(names: Iterable[str], files: Iterable[Path] | None = None) -> list[Site]:
    """Every site in the harness source that names what can be done next, classified: the values under KEYS
    (a name, a list of names, a sentence), every `{tool, args}` row literal, and every other sentence of the
    source that names an old tool (LITERAL_KEY)."""
    names = set(names)
    out: list[Site] = []
    for path in (files if files is not None else source_files()):
        rel = str(path.relative_to(ROOT))
        tree = ast.parse(path.read_text(), filename=rel)
        seen: set[int] = _docstrings(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            if _is_row_literal(node):
                out.append(Site(rel, node.lineno, ROW_KEY, "rows", ast.unparse(node)[:80]))
                continue  # its own `tool` key is the row, not a name
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value in KEYS:
                    kind, text = classify(k.value, v, names)
                    out.append(Site(rel, v.lineno, k.value, kind, text))
                    seen.update(id(n) for n in ast.walk(v))
        if rel in LITERAL_EXEMPT:
            continue
        for node in ast.walk(tree):
            if id(node) in seen or not isinstance(node, (ast.Constant, ast.JoinedStr)):
                continue
            if isinstance(node, ast.JoinedStr):
                seen.update(id(n) for n in ast.walk(node))
            text = _literal_text(node)
            if text and is_prose(text) and named_in(text, names):
                out.append(Site(rel, node.lineno, LITERAL_KEY, "prose", text))
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
CHOICE_VIEWS = frozenset({("state:units", "actions"), ("state:unit", "actions"), ("state:unit", "targets"),
                          ("state:unit", "home"), ("state:city", "production"), ("state:city", "strikes"),
                          ("state:civ", "trade_catalog"), ("state:city_state", "summary"),
                          ("state:city_state", "full"), ('state:league', 'default')})
TODO_READS = ("turn_status", "briefing", "finish_turn")
#: The todo reads whose rows harness/briefing.py composes (turn_status hands the runtime's todo back as is).
BRIEFED = ("briefing", "finish_turn")


def is_affordance_read(name: str) -> bool:
    row = R.RETIRED.get(name)
    if row is None:
        return False
    return (name in TODO_READS or row.tool == "question" or row.key in CHOICE_VIEWS
            or row.key[0] == "state:options")


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
    for fn in _mixin_methods(called):
        srcs.append(ast.unparse(fn))
    if tool.name in BRIEFED:
        srcs.append((ROOT / "harness" / "briefing.py").read_text())
    return srcs


def _mixin_methods(names: set[str]) -> list[ast.FunctionDef]:
    """The game-mixin methods (any class under harness/game_parts/) with one of `names`: where a reply is composed.
    A handler's module and its mixin do not always share a name (available_production is a tool of
    mcp_tools/cities.py and a method of game_parts/reads.py)."""
    out = []
    for path in sorted((ROOT / "harness" / "game_parts").glob("*.py")):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.ClassDef):
                out.extend(fn for fn in node.body if isinstance(fn, ast.FunctionDef) and fn.name in names)
    return out


def row_makers() -> set[str]:
    """The public functions of the row modules that return rows (the predicates and walkers excepted)."""
    out: set[str] = set()
    for path in ROW_MODULES:
        tree = ast.parse(path.read_text())
        out |= {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
                and n.name not in ("is_row", "rows_in")}
    return out


def _aliases(src: str) -> set[str]:
    """The names `src` binds a row module to (`from . import affordances as A`, `from . import rows`)."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom):
            out.update(a.asname or a.name for a in node.names if a.name in ROW_MODULE_NAMES)
        elif isinstance(node, ast.Import):
            out.update((a.asname or a.name).split(".")[-1] for a in node.names
                       if a.name.rsplit(".", 1)[-1] in ROW_MODULE_NAMES)
    return out


def makes_rows(src: str, makers: set[str], aliases: set[str] | None = None) -> bool:
    """Whether `src` writes a `{tool, args}` row: a literal, or a call of a row maker on an alias of the module."""
    aliases = _aliases(src) if aliases is None else aliases
    for n in ast.walk(ast.parse(src)):
        if _is_row_literal(n):
            return True
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in makers
                and isinstance(n.func.value, ast.Name) and n.func.value.id in aliases):
            return True
    return False


def replies(tools: Iterable) -> list[dict]:
    """For every reply that lists what can be done: whether its handler (or the mixin composing it) emits
    `{tool, args}` rows, or hands the choices back by name only."""
    out = []
    makers = row_makers()
    for t in tools:
        if not is_affordance_read(t.name):
            continue
        srcs = _handler_sources(t)
        aliases = {a for src in _module_sources(t) + srcs for a in _aliases(src)}
        rows = any(makes_rows(src, makers, aliases) for src in srcs)
        out.append({"reply": t.name, "module": (getattr(t.fn, "__module__", "") or "").rsplit(".", 1)[-1],
                    "key": " / ".join(R.RETIRED[t.name].key), "carries": "rows" if rows else "names only"})
    return out


def _module_sources(tool) -> list[str]:
    """The module a handler lives in and its game-mixin twin, whole: the import aliases their fragments use."""
    out = []
    try:
        out.append(_inspect.getsource(_inspect.getmodule(tool.fn)))
    except (OSError, TypeError):
        pass
    out.extend(p.read_text() for p in sorted((ROOT / "harness" / "game_parts").glob("*.py")))
    return out


def _dedent(src: str) -> str:
    import textwrap
    return textwrap.dedent(src)
