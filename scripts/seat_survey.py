"""Where does each runtime entry learn the acting seat? -- the stage-2 survey of "A seat bound to its channel".

Reads harness/lua/runtime/*.lua and the Python that composes Lua (harness/game.py, harness/game_parts/*.py,
scripts/*.py) and prints, for docs/GAPS.md:

  1. every `function H.<name>(params)` with the position of its seat parameter (first / last / middle / none)
     and whether Python ever names it (a tool entry) or only other Lua does (internal);
  2. the entries with no seat parameter that Python reaches, and those that read a caller-chosen team or
     viewer in the acting role -- the exceptions stage 3 has to give an explicit seat;
  3. the Python call sites that send Lua: those naming an `H.*` entry against those composing engine Lua
     ad hoc (`Players[...]`, `UI.`, `PreGame.`), which stage 3 moves into named runtime entries.

Run from the repo root:  python -I scripts/seat_survey.py [--sites]
"""

from __future__ import annotations

import ast
import glob
import re
import sys
from pathlib import Path
from collections import Counter

SEAT_NAMES = {"pid", "player_id", "player", "p", "seat", "me", "my_pid", "owner"}
TEAM_NAMES = {"team", "viewer", "us", "them", "owner_id"}
FN_RE = re.compile(r"^function H\.([A-Za-z0-9_]+)\s*\(([^)]*)\)", re.M)
SENDERS = {"q", "lua", "exec", "query"}
STATE_FIRST = {"exec", "query", "lua"}


def lua_entries() -> list[dict]:
    rows = []
    for path in sorted(glob.glob("harness/lua/runtime/*.lua")):
        src = Path(path).read_text()
        for m in FN_RE.finditer(src):
            params = [p.strip() for p in m.group(2).split(",") if p.strip()]
            pos = next((k for k, p in enumerate(params) if p in SEAT_NAMES), None)
            if pos is None:
                where = "none"
            elif pos == 0:
                where = "first"
            elif pos == len(params) - 1:
                where = "last"
            else:
                where = "middle"
            rows.append(
                dict(
                    file=path.rsplit("/", 1)[1],
                    line=src[: m.start()].count("\n") + 1,
                    name=m.group(1),
                    params=params,
                    seat=where,
                    team_arg=[p for p in params if p in TEAM_NAMES],
                )
            )
    return rows


def python_sources() -> dict[str, str]:
    files = sorted(glob.glob("harness/*.py") + glob.glob("harness/game_parts/*.py") + glob.glob("scripts/*.py"))
    return {f: Path(f).read_text() for f in files if not f.endswith("seat_survey.py")}


def literal_text(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(literal_text(v) or "{…}" for v in node.values if not isinstance(v, ast.FormattedValue))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return (literal_text(node.left) or "{…}") + (literal_text(node.right) or "{…}")
    return None


def lua_sites(sources: dict[str, str]) -> tuple[Counter, list[tuple[str, int, str]]]:
    """Count Lua-sending calls per file: named H.* entry / ad hoc engine Lua / non-literal body."""
    per: Counter = Counter()
    adhoc: list[tuple[str, int, str]] = []
    for path, src in sources.items():
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            name = node.func.attr
            if name not in SENDERS:
                continue
            args = node.args[1:] if name in STATE_FIRST and len(node.args) >= 2 else node.args
            body = next((literal_text(a) for a in args if literal_text(a) is not None), None)
            for kw in node.keywords:
                if kw.arg == "lua":
                    body = literal_text(kw.value)
            if body is None:
                per[(path, "variable")] += 1
            elif "H." in body:
                per[(path, "H")] += 1
            else:
                per[(path, "adhoc")] += 1
                adhoc.append((path, node.lineno, " ".join(body.split())[:100]))
    return per, adhoc


def main() -> None:
    rows = lua_entries()
    sources = python_sources()
    py_all = "\n".join(sources.values())
    for r in rows:
        r["from_python"] = re.search(r"\bH\." + re.escape(r["name"]) + r"\b", py_all) is not None

    print(f"{len(rows)} H.* entries in {len({r['file'] for r in rows})} runtime files\n")
    print("seat parameter   tool entries (named from Python)   Lua-internal only")
    for where in ("first", "last", "middle", "none"):
        a = sum(1 for r in rows if r["seat"] == where and r["from_python"])
        b = sum(1 for r in rows if r["seat"] == where and not r["from_python"])
        print(f"  {where:8}       {a:4}                               {b:4}")

    print("\nseat in the middle (a positional rule cannot place it):")
    for r in rows:
        if r["seat"] == "middle":
            print(f"  {r['file']}:{r['line']} H.{r['name']}({', '.join(r['params'])})")

    print("\nno seat parameter, reached from Python:")
    for r in rows:
        if r["seat"] == "none" and r["from_python"]:
            print(f"  {r['file']}:{r['line']} H.{r['name']}({', '.join(r['params'])})")

    print("\na caller-chosen team / viewer in the acting role (no seat parameter):")
    for r in rows:
        if r["seat"] == "none" and r["team_arg"]:
            print(f"  {r['file']}:{r['line']} H.{r['name']}({', '.join(r['params'])})")

    per, adhoc = lua_sites(sources)
    print("\nLua-sending calls in Python (H = names an H.* entry, adhoc = engine Lua composed in Python):")
    files = sorted({p for p, _ in per})
    tot = Counter()
    for f in files:
        h, a, v = per[(f, "H")], per[(f, "adhoc")], per[(f, "variable")]
        tot.update(H=h, adhoc=a, variable=v)
        print(f"  {f:40} H={h:3}  adhoc={a:3}  non-literal={v}")
    print(f"  {'total':40} H={tot['H']:3}  adhoc={tot['adhoc']:3}  non-literal={tot['variable']}")
    if "--sites" in sys.argv:
        print("\nad-hoc sites:")
        for path, line, body in adhoc:
            print(f"  {path}:{line}  {body}")


if __name__ == "__main__":
    main()
