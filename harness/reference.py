"""The rule book: this game's static help, rendered once as Markdown.

Until runtime v215 every chooser row repeated its hover text: the same "+33% Science in this City" under
Library on every `available_production`, in every city, every turn; the same Salt blurb on every Salt tile
of every `map_window`. The words never change during a game, so they now live in one document the model
reads once (or one section at a time when a choice comes up), and the rows carry enums, names and live
numbers only. `H.reference()` (harness/lua/runtime.lua) reads the game's own database, so mods and DLC are
honoured; this module turns that JSON into text. Served by the MCP tool `reference(section)`, the MCP
resources `civ5://reference` and `civ5://reference/{section}`, and HTTP `GET /reference?section=`.
"""
from __future__ import annotations

from typing import Any

SECTIONS = ("terrain", "resources", "improvements", "units", "buildings", "projects", "processes",
            "promotions", "policies", "techs", "beliefs", "specialists", "actions")

TITLES = {
    "terrain": "Terrain and features",
    "resources": "Resources",
    "improvements": "Tile improvements",
    "units": "Units",
    "buildings": "Buildings and wonders",
    "projects": "Projects",
    "processes": "Processes",
    "promotions": "Promotions",
    "policies": "Social policies and ideologies",
    "techs": "Technologies",
    "beliefs": "Beliefs",
    "specialists": "Specialists",
    "actions": "Unit actions",
}

# One line under each heading: which live tool names these enums, so the reader knows what to look up.
USAGE = {
    "terrain": "`map_window` plots carry `t` (terrain), `feature`, `hills`, `mountain`, `river`; `revealed_map` legends use the same names.",
    "resources": "`map_window` plots carry `resource` (and `resource_requires_tech` while it cannot be worked); `map_index` lists them; `trade_catalog` trades them.",
    "improvements": "`available_unit_actions.nearby_builds` and `unit_mission(MISSION_BUILD, build=...)` use the `build` enum; plots carry `improvement`.",
    "units": "`available_production` rows (`kind: unit`), `units`, `tech_tree` unlocks. Live cost, turns and purchase price are on those rows.",
    "buildings": "`available_production` rows (`kind: building`), `city_screen.buildings`, `tech_tree` unlocks.",
    "projects": "`available_production` rows (`kind: project`); `spaceship_status` for the parts.",
    "processes": "`available_production` rows (`kind: process`); league processes carry their live progress there.",
    "promotions": "`available_unit_actions.promotions` / `todo_actions` name the `promotion`; `choose_promotion` takes it.",
    "policies": "`available_policies.adoptable` names the `policy` and `branch`; `choose_policy` / `unlock_policy_branch` take them; `choose_ideology` the ideology.",
    "techs": "`available_research` / `tech_tree` name the `tech`; `set_research` takes it. Turns at your rate are on those rows.",
    "beliefs": "`available_beliefs(kind)` names the `belief`; `found_pantheon` / `found_religion` / `enhance_religion` / `add_reformation_belief` take it.",
    "specialists": "`city_screen` specialist rows and `change_specialist`.",
    "actions": "`available_unit_actions` / `todo_actions` rows name the action `type`; `unit_mission` runs it. The few lines that carry live numbers stay on the row (`help`).",
}

YIELD_ORDER = ("food", "production", "gold", "science", "culture", "faith")


def _yields(y: dict | None) -> str | None:
    if not isinstance(y, dict) or not y:
        return None
    keys = [k for k in YIELD_ORDER if k in y] + sorted(k for k in y if k not in YIELD_ORDER)
    return ", ".join(f"{y[k]:+g} {k}" for k in keys)


def _stats(*pairs: tuple[str, Any]) -> str:
    """'label value' fragments for the values that are set, joined with commas."""
    out = []
    for label, v in pairs:
        if v is None or v is False or v == "" or v == []:
            continue
        if v is True:
            out.append(label)
        elif isinstance(v, list):
            out.append(f"{label} {', '.join(str(x) for x in v)}" if label else ", ".join(str(x) for x in v))
        else:
            out.append(f"{label} {v}".strip())
    return ", ".join(out)


def _text(s: Any) -> str:
    return " ".join(str(s).split()) if s else ""


def _row(name: str | None, enum: str, stats: str = "", help: Any = None, extra: Any = None) -> str:
    head = f"**{name}** `{enum}`" if name and name != enum else f"`{enum}`"
    if stats:
        head += f" — {stats}"
    line = f"- {head}"
    if help:
        line += f". {_text(help)}"
    if extra:
        line += f"\n  _{_text(extra)}_"
    return line


def _rows(rows: Any) -> list[dict]:
    return [r for r in (rows or []) if isinstance(r, dict) and r.get("type")]


def render_terrain(data: dict) -> list[str]:
    out = ["### Terrains", ""]
    for t in _rows((data or {}).get("terrains")):
        out.append(_row(t.get("name"), t["type"], _stats(("", _yields(t.get("yields"))), ("movement", t.get("movement")),
                                                       ("defense", f"{t['defense']:+d}%" if isinstance(t.get("defense"), int) else None),
                                                       ("water", t.get("water")), ("impassable", t.get("impassable")))))
    out += ["", "### Features", ""]
    for f in _rows((data or {}).get("features")):
        out.append(_row(f.get("name"), f["type"], _stats(("", _yields(f.get("yields"))), ("movement", f.get("movement")),
                                                       ("defense", f"{f['defense']:+d}%" if isinstance(f.get("defense"), int) else None),
                                                       ("impassable", f.get("impassable")), ("natural wonder", f.get("natural_wonder")),
                                                       ("no city", f.get("no_city"))), f.get("help")))
    return out


def render_resources(rows: Any) -> list[str]:
    out = []
    for r in sorted(_rows(rows), key=lambda r: (str(r.get("class") or ""), str(r.get("name") or r["type"]))):
        stats = _stats(("", (r.get("class") or "").lower() or None),
                       ("happiness", f"{r['happiness']:+d}" if isinstance(r.get("happiness"), int) else None),
                       ("improved:", _yields(r.get("improved_yields"))),
                       ("improved by", r.get("improvements")),
                       ("revealed by", r.get("tech_reveal")), ("usable with", r.get("tech_use")))
        out.append(_row(r.get("name"), r["type"], stats, r.get("help")))
    return out


def render_improvements(rows: Any) -> list[str]:
    out = []
    for i in _rows(rows):
        stats = _stats(("", _yields(i.get("yields"))), ("build", i.get("build")), ("needs", i.get("tech")),
                       ("on", i.get("resources")), ("defense", f"{i['defense']:+d}%" if isinstance(i.get("defense"), int) else None),
                       ("pillage gold", i.get("pillage_gold")), ("fresh water", i.get("fresh_water")),
                       ("barbarian camp", i.get("barbarian_camp")), ("ruins", i.get("goody_hut")))
        out.append(_row(i.get("name"), i["type"], stats, i.get("help")))
    return out


def render_units(rows: Any) -> list[str]:
    out = []
    for u in _rows(rows):
        stats = _stats(("cost", u.get("cost")), ("faith", u.get("faith_cost")), ("strength", u.get("strength")),
                       ("ranged", u.get("ranged_strength")), ("range", u.get("range")), ("moves", u.get("moves")),
                       ("", (u.get("domain") or "").lower() or None), ("", (u.get("combat_class") or "").lower().replace("_", " ") or None),
                       ("needs", u.get("tech")), ("obsolete at", u.get("obsolete_tech")), ("requires", u.get("requirements")))
        out.append(_row(u.get("name"), u["type"], stats, u.get("help"), u.get("strategy")))
    return out


def render_buildings(rows: Any) -> list[str]:
    out = []
    for b in _rows(rows):
        wonder = {"world": "World Wonder", "national": "National Wonder"}.get(b.get("wonder") or "")
        stats = _stats(("", wonder), ("cost", b.get("cost")), ("faith", b.get("faith_cost")),
                       ("maintenance", b.get("gold_maintenance")), ("", _yields(b.get("yields"))),
                       ("happiness", f"{b['happiness']:+d}" if isinstance(b.get("happiness"), int) else None),
                       ("specialists", f"{b['specialist_slots']} {str(b.get('specialist') or '').lower()}".strip() if b.get("specialist_slots") else None),
                       ("great work slots", b.get("great_work_slots")), ("needs", b.get("tech")))
        out.append(_row(b.get("name"), b["type"], stats, b.get("help"), b.get("strategy")))
    return out


def render_simple(rows: Any) -> list[str]:
    out = []
    for p in _rows(rows):
        out.append(_row(p.get("name"), p["type"], _stats(("cost", p.get("cost")), ("needs", p.get("tech"))), p.get("help")))
    return out


def render_policies(data: dict) -> list[str]:
    data = data or {}
    branches = _rows(data.get("branches"))
    policies = _rows(data.get("policies"))
    out = ["### Branches and ideologies", ""]
    names = {}
    for br in branches:
        names[br["type"]] = br.get("name") or br["type"]
        out.append(_row(br.get("name"), br["type"], _stats(("ideology", br.get("ideology")), ("era", br.get("era"))), br.get("help")))
    by_branch: dict[str, list[dict]] = {}
    for p in policies:
        by_branch.setdefault(p.get("branch") or "", []).append(p)
    for branch in [b["type"] for b in branches] + sorted(k for k in by_branch if k not in names):
        rows = by_branch.get(branch)
        if not rows:
            continue
        out += ["", f"### {names.get(branch, branch or 'Other')}", ""]
        for p in sorted(rows, key=lambda p: (p.get("level") or 0)):
            out.append(_row(p.get("name"), p["type"], _stats(("tenet level", p.get("level"))), p.get("help")))
    return out


def render_techs(rows: Any) -> list[str]:
    out = []
    era = None
    for t in _rows(rows):
        if t.get("era") != era:
            era = t.get("era")
            out += ["", f"### {str(era or 'Other').replace('_', ' ').title()}", ""]
        out.append(_row(t.get("name"), t["type"], _stats(("cost", t.get("cost")), ("after", t.get("prereqs"))), t.get("help")))
    return out[1:] if out and out[0] == "" else out


def render_beliefs(rows: Any) -> list[str]:
    out = []
    order = ("pantheon", "founder", "follower", "enhancer", "reformation")
    rows = _rows(rows)
    kinds = [k for k in order if any(b.get("kind") == k for b in rows)] + sorted({str(b.get("kind") or "other") for b in rows} - set(order))
    for kind in kinds:
        out += ["", f"### {kind.title()}", ""]
        for b in rows:
            if (b.get("kind") or "other") == kind:
                out.append(_row(b.get("name"), b["type"], "", b.get("description")))
    return out[1:] if out and out[0] == "" else out


def render_specialists(rows: Any) -> list[str]:
    out = []
    for s in _rows(rows):
        gp = f"{s['great_person_points']} toward {str(s.get('great_person') or 'a great person').replace('_', ' ').title()}" if s.get("great_person_points") else None
        out.append(_row(s.get("name"), s["type"], _stats(("", _yields(s.get("yields"))), ("", gp))))
    return out


def render_actions(rows: Any) -> list[str]:
    out = []
    for a in _rows(rows):
        stats = _stats(("", a.get("kind")), ("mission", a.get("mission")))
        out.append(_row(a.get("name"), a["type"], stats, a.get("help"), a.get("computed")))
    return out


RENDERERS = {
    "terrain": render_terrain, "resources": render_resources, "improvements": render_improvements,
    "units": render_units, "buildings": render_buildings, "projects": render_simple, "processes": render_simple,
    "promotions": render_simple, "policies": render_policies, "techs": render_techs, "beliefs": render_beliefs,
    "specialists": render_specialists, "actions": render_actions,
}


def render_section(name: str, rows: Any) -> str:
    body = RENDERERS[name](rows)
    if not body:
        body = ["_(nothing in this game's database)_"]
    return "\n".join([f"## {TITLES[name]}", "", USAGE[name], ""] + body)


def render_markdown(data: dict, section: str | None = None) -> str:
    """`data` is H.reference()'s reply (the whole book, or one section's `{section, rows}`); `section`
    narrows the whole book to one part. Unknown sections raise ValueError with the list."""
    if section is not None and section not in SECTIONS:
        raise ValueError(f"unknown reference section {section!r}; sections: {', '.join(SECTIONS)}")
    if "rows" in data and data.get("section"):
        return render_section(data["section"], data["rows"])
    sections = data.get("sections") or {}
    errors = data.get("errors") or {}
    if section is not None:
        if section in errors:
            return f"## {TITLES[section]}\n\n_This section could not be read from the game: {errors[section]}_"
        return render_section(section, sections.get(section))
    head = [
        "# Civilization V reference",
        "",
        f"Read from this game's own database (runtime v{data.get('runtime', '?')}), so mods and DLC are included. "
        "Everything here is static: it never changes during a game, so no tool answer repeats it. Rows in "
        "`available_production`, `available_unit_actions`, `available_policies`, `available_research`, "
        "`available_beliefs`, `city_screen` and `map_window` carry enums, names and live numbers (costs at your rate, "
        "turns, purchase prices, what is legal now); look the enum up here for what it does.",
        "",
        "Sections: " + ", ".join(f"`{s}`" for s in SECTIONS) + ". One at a time: `reference(section=...)`, "
        "`civ5://reference/{section}`, or `GET /reference?section=...`.",
        "",
    ]
    parts = []
    for name in SECTIONS:
        if name in errors:
            parts.append(f"## {TITLES[name]}\n\n_This section could not be read from the game: {errors[name]}_")
        else:
            parts.append(render_section(name, sections.get(name)))
    return "\n".join(head) + "\n\n".join(parts) + "\n"
