"""Stage 0 of milestone 2.0.0 "The tool surface" (GitLab #44): the catalog by module, the listing's size,
every old name's row in the retirement map, and the affordance audit, as the Markdown checked in under
docs/measurements/tool_survey.md.

Run from the repo root:  .venv/bin/python scripts/tool_survey.py [--write] [--json]

Everything is computed from the registered server and harness/surface/ (no game): `--write` refreshes the
measurement file, `--json` prints the raw tables. tests/test_tool_survey.py holds the baseline the tables
must reproduce (145 tools, 35 zero-argument reads, the eight shapes).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.surface import audit, retirement, survey  # noqa: E402

OUT = ROOT / "docs" / "measurements" / "tool_survey.md"


def table(headers: list[str], rows: list[dict], keys: list[str] | None = None) -> str:
    keys = keys or headers
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(k, "")) for k in keys) + " |")
    return "\n".join(lines)


def collect() -> dict:
    names = [t.name for t in survey.tools()]
    sites = audit.scan(names)
    return {"by_module": survey.by_module(), "shapes": survey.shapes(names), "listing_sizes": survey.listing_sizes(),
            "longest_description": survey.longest_description(),
            "by_new_tool": survey.by_new_tool(), "mapping": survey.mapping(), "check": retirement.check(names),
            "audit_summary": audit.summary(sites),
            "seam": [s.__dict__ for s in audit.seam(sites)],
            "replies": audit.replies(survey.tools())}


def render(d: dict) -> str:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                cwd=ROOT, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "?"
    total = d["by_module"][-1]
    ok = not any(d["check"].values())
    out = ["# The tool surface, measured (stage 0, GitLab #44)",
           "",
           f"Written by `scripts/tool_survey.py --write` at {commit} on {dt.date.today()}: {total['tools']} tools, "
           f"{total['zero_argument_reads']} zero-argument reads. The mapping check "
           + ("passed" if ok else f"FAILED: {json.dumps(d['check'])}")
           + " (every catalog name maps to exactly one row of `harness/surface/retirement.py`, none is left over, "
             "every row speaks `harness/surface/vocabulary.py`). Re-run after any tool, docstring or map change.",
           "",
           "## The catalog by module",
           "",
           "A zero-argument read is a tool in the call ledger's `READ_TOOLS` whose schema has no property.",
           "",
           table(["Module", "Tools", "Of which zero-argument reads"], d["by_module"],
                 ["module", "tools", "zero_argument_reads"]),
           "",
           "## Where the tools come from",
           "",
           "The eight shapes of #44, each old name counted under the first shape it fits (`harness/surface/survey.py`, `SHAPES`).",
           "",
           table(["Shape", "Count", "Names"], [{**r, "names": ", ".join(f"`{n}`" for n in r["names"])} for r in d["shapes"]],
                 ["shape", "count", "names"]),
           "",
           "## The listing's size",
           "",
           f"The `tools/list` reply as a client receives it (name, description, inputSchema; compact JSON). Tokens are "
           f"bytes / {survey.BYTES_PER_TOKEN}, the estimate the server's own comment uses (no tokenizer in the venv). "
           f"The longest description is `{d['longest_description']['tool']}` at {d['longest_description']['chars']} "
           f"characters, under the {d['longest_description']['clip']} at which Claude Code cuts one, so a client "
           "that clips sees the full listing.",
           "",
           table(["Listing", "Tools", "Bytes", "Approx. tokens"], d["listing_sizes"],
                 ["listing", "tools", "bytes", "approx_tokens"]),
           "",
           "## What each of the nine tools replaces",
           "",
           table(["Tool", "Replaces"], d["by_new_tool"], ["tool", "replaces"]),
           "",
           "## Every old name and its row",
           "",
           "The `renamed` string is what a reply to the old name will carry once the map is wired in (#50). "
           "`known_world` follows #50's table to `turn(\"briefing\", since=\"turn\")`, which is why `turn` replaces "
           "one more and `inspect` one fewer than the counts on #59 (8 and 46 against 7 and 47).",
           "",
           table(["Old", "Module", "(tool, action) / (what, view)", "Renamed", "Note"],
                 [{**r, "old": f"`{r['old']}`", "new": f"`{r['new']}`" if r["new"] else ""} for r in d["mapping"]],
                 ["old", "module", "key", "new", "note"]),
           "",
           "## The affordance audit",
           "",
           "Which replies that list what can be done carry `actions: [{tool, args}]` rows, and which hand the choices "
           "back by name only (the write left to the caller). `rows` means the handler or the game mixin composing "
           "the reply emits a `{tool, args}` literal.",
           "",
           table(["Reply", "Module", "Row", "Carries"], d["replies"], ["reply", "module", "key", "carries"]),
           "",
           "### By file and key",
           "",
           "Every dict literal in `harness/` whose key says what to do next (`tool`, `hint`, `clear_with`, "
           "`read_first`, `also`), by what the value is: `name` exactly one tool name, `names` a list of them, "
           "`prose` a sentence naming a tool, `text` a sentence naming none, `dynamic` not a literal; `{tool, args}` "
           "counts row literals.",
           "",
           table(["File", "Key", "rows", "name", "names", "prose", "text", "dynamic"], d["audit_summary"],
                 ["file", "key", "rows", "name", "names", "prose", "text", "dynamic"]),
           "",
           "### The seam",
           "",
           "The sites stage 1 (#45-#47) turns into rows: a tool named in a reply or a refusal as a word, not a row.",
           "",
           table(["Site", "Key", "Kind", "Text"],
                 [{"site": f"`{s['file']}:{s['line']}`", "key": s["key"], "kind": s["kind"],
                   "text": s["text"].replace("|", "\\|").replace("\n", " ")} for s in d["seam"]],
                 ["site", "key", "kind", "text"]),
           ""]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write", action="store_true", help=f"write {OUT.relative_to(ROOT)}")
    ap.add_argument("--json", action="store_true", help="print the raw tables as JSON")
    args = ap.parse_args(argv)
    d = collect()
    if args.json:
        print(json.dumps(d, indent=1, default=str))
    elif args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(render(d))
        print(f"wrote {OUT.relative_to(ROOT)}")
    else:
        print(render(d))
    return 0 if not any(d["check"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
