"""Compact comparisons (#34): a few caller-chosen candidates side by side, from one runtime read.

The runtime (H.compare_production / compare_research / compare_improvements / compare_trade_routes) returns
engine answers and table rows; this module validates the arguments, adds the context (seat, turn, city or unit),
the source of every compared field and the assumption behind every estimate, and cuts the answer to `limit` rows
with the exact arguments that fetch the rest. It never ranks candidates or calls one best: the caller chooses
the objective (`sort` only orders by a field the caller names). Pure: no game access here.
"""
from __future__ import annotations

import copy
import math

KINDS = ("production", "research", "improvements", "trade")
DETAILS = ("summary", "full")
MAX_CANDIDATES = 8
MAX_PLOTS = 12
MAX_LIMIT = 20
MISSING_SHOWN = 6  # research summary: the first missing prerequisites; missing_prereqs_count has them all
DEFAULT_LIMIT = {"production": MAX_CANDIDATES, "research": MAX_CANDIDATES, "improvements": 10, "trade": 6}
YIELDS = ("food", "production", "gold", "science", "culture", "faith")
IMPROVEMENT_SORTS = YIELDS + ("turns",)
TRADE_SORTS = ("gold", "science", "food", "production", "gold_them", "science_them", "food_them",
               "production_them", "distance")

SOURCES = {
    "production": {
        "can_produce": "CvCity:CanTrain / CanConstruct / CanCreate (the production chooser's list); `why` names the rule "
                       "this read found, why_unknown=true when it found none",
        "cost / stored": "CvCity:GetUnitProductionNeeded / GetBuildingProductionNeeded / GetProjectProductionNeeded and "
                         "Get*Production (the chooser's cost and the hammers already put in)",
        "turns": "CvCity:Get*ProductionTurnsLeft",
        "gold / faith": "CvCity:Get*PurchaseCost / Get*FaithPurchaseCost with IsCanPurchase (the city screen's buy buttons)",
        "effects": "GameInfo Units / Buildings / Building_YieldChanges / Building_YieldChangesPerPop / "
                   "Building_YieldModifiers / Building_DomainFreeExperiences: table columns only; other abilities "
                   "are in the help text (on the row when it has no table effect, on every row with detail='full')",
        "conditional": "GameInfo Building_*YieldChanges (resource, feature, terrain, sea, lake, river) counted over the "
                       "tiles this city owns now",
        "maintenance": "Buildings.GoldMaintenance (base; policy or trait discounts are not applied); unit upkeep is "
                       "CvPlayer:CalculateUnitCost for the whole empire",
        "help": 'reference("units") / reference("buildings") / reference("projects"); detail="full" adds the game help '
                "text on each row",
    },
    "research": {
        "cost / progress": "CvPlayer:GetResearchCost / GetResearchProgress (the tech tree's numbers)",
        "turns": "CvPlayer:GetResearchTurnsLeft (available techs only)",
        "missing_prereqs": "GameInfo Technology_PrereqTechs: every unresearched ancestor, each once",
        "unlocks": "the tech tree's buttons for this civilization (tech_tree / available_research)",
        "help": 'reference("techs")',
    },
    "improvements": {
        "legal": "CvUnit:CanBuild for this unit on that plot now; `why` names the rule this read found",
        "turns": "CvPlot:GetBuildTurnsLeft with this unit's work rate, from the moment work starts",
        "yields_now / tile_yields_after": "CvPlot:CalculateYield (the tile hover) and CvPlot:GetYieldWithBuild",
        "removes / chop_production": "GameInfo BuildFeatures.Remove and CvPlot:GetFeatureProduction",
        "connects": "GameInfo Improvement_ResourceTypes and CvPlayer:GetNumResourceAvailable",
        "maintenance": "Improvements.GoldMaintenance / Routes.GoldMaintenance",
        "help": 'reference("improvements"); available_unit_actions(unit_id) lists every legal build',
    },
    "trade": {
        "yields": "the trade-route chooser (available_trade_routes): gold/science/food/production are what your end "
                  "receives, *_them what the destination receives",
        "distance": "hex distance from the caravan to the destination (not the route's path length)",
        "hazard": "visible hostile units (at war or barbarian) and revealed barbarian camps within `radius` of each "
                  "end; not_visible counts the plots there that cannot be seen",
        "details": 'detail="full" adds the chooser\'s hover text (the per-line breakdown)',
    },
}

ASSUMPTIONS = {
    "production": [
        "turns: at this turn's production with this item's modifiers, including hammers already stored; it changes "
        "when tiles, population or buildings change",
        "estimated_change: (base + added) x (city modifier% + building%) / 100 - now, per city yield, where added = flat "
        "+ per-pop x population + conditional x tiles worked now; empire-level modifiers, policies, beliefs and "
        "happiness effects are not applied, and tiles the city does not work add nothing",
    ],
    "research": [
        "turns: the engine's answer at this turn's science, for techs that can be researched now",
        "path_turns_estimate: ceil(path_beakers / science_per_turn) at this turn's science, with no overflow, "
        "boosts or cost changes",
    ],
    "improvements": [
        "turns: work starting now on that plot; the walk there is not included (distance is hex distance, not a path)",
        "tile_change is the plot's own yield change; it reaches the empire (empire_change) only while a city works "
        "the plot",
    ],
    "trade": [
        "the caravan's path is not known before the route is set: hazards are checked only around both ends",
        "danger='none_visible' is not safety: fogged plots (not_visible) can hide units",
    ],
}


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def validate(kind: str, city_id=None, unit_id=None, candidates=None, plots=None, sort=None, limit=None,
             detail: str = "summary") -> str | None:
    """None when the arguments make one comparison; else what is wrong and what to pass."""
    if kind not in KINDS:
        return f"kind must be one of {', '.join(KINDS)}, not {kind!r}"
    if detail not in DETAILS:
        return f"detail must be one of {', '.join(DETAILS)}, not {detail!r}"
    if limit is not None and (not _is_int(limit) or not 1 <= limit <= MAX_LIMIT):
        return f"limit must be a whole number from 1 to {MAX_LIMIT}"
    cands = list(candidates or [])
    if any(not isinstance(c, str) or not c for c in cands):
        return "candidates must be type names such as UNIT_WORKER, BUILDING_LIBRARY, TECH_WRITING or BUILD_FARM"
    if len(cands) > MAX_CANDIDATES:
        return f"at most {MAX_CANDIDATES} candidates per comparison ({len(cands)} given): split them over two calls"
    if len(set(cands)) != len(cands):
        return "candidates repeat a name"
    if kind == "production":
        if not _is_int(city_id):
            return "production needs city_id (cities() lists them)"
        if not cands:
            return "production needs candidates: the items to compare (available_production(city_id) lists the choices)"
    if kind == "research" and not cands:
        return "research needs candidates: the techs to compare (available_research / tech_tree list them)"
    if kind in ("improvements", "trade") and not _is_int(unit_id):
        return f"{kind} needs unit_id ({'a worker or work boat' if kind == 'improvements' else 'a caravan or cargo ship'})"
    if kind == "trade" and cands:
        return "trade takes no candidates: every destination the chooser offers is compared (use sort and limit)"
    if plots is not None and kind != "improvements":
        return "plots is for kind='improvements' only"
    if plots:
        if len(plots) > MAX_PLOTS:
            return f"at most {MAX_PLOTS} plots per comparison"
        for xy in plots:
            if not (isinstance(xy, (list, tuple)) and len(xy) == 2 and all(_is_int(v) for v in xy)):
                return "plots must be [x, y] pairs of whole numbers"
    if sort is not None:
        allowed = {"improvements": IMPROVEMENT_SORTS, "trade": TRADE_SORTS}.get(kind)
        if not allowed:
            return f"sort is for improvements and trade; {kind} rows keep the order of candidates"
        if sort not in allowed:
            return f"sort must be one of {', '.join(allowed)}"
    return None


def _lua_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def lua_call(kind: str, pid: int, city_id=None, unit_id=None, candidates=None, plots=None, detail="summary",
             radius: int = 2) -> str:
    """The one runtime call for this comparison (arguments already validated)."""
    names = "{" + ",".join(_lua_str(c) for c in (candidates or [])) + "}"
    if kind == "production":
        return f"return H.compare_production({int(city_id)}, {names}, {int(pid)}, {'true' if detail == 'full' else 'false'})"
    if kind == "research":
        return f"return H.compare_research({names}, {int(pid)})"
    if kind == "improvements":
        xy = "{" + ",".join(f"{{{int(x)},{int(y)}}}" for x, y in (plots or [])) + "}"
        return f"return H.compare_improvements({int(unit_id)}, {xy}, {names}, {int(pid)})"
    return f"return H.compare_trade_routes({int(unit_id)}, {int(pid)}, {int(radius)})"


def _cut(rows: list, limit: int) -> tuple[list, list]:
    return rows[:limit], rows[limit:]


def _unlock_names(unlocks: list[dict]) -> list[str]:
    out = []
    for u in unlocks or []:
        label = u.get("name") or u.get("type") or "?"
        out.append(f"{label} ({u.get('kind')})" if u.get("kind") else label)
    return out


def _production(raw: dict, args: dict, detail: str, limit: int) -> dict:
    rows, rest = _cut(raw.get("rows") or [], limit)
    for r in rows:
        if r.get("maintenance", {}).get("gold") is None and r.get("kind") == "unit":
            r["maintenance"]["gold"] = "unknown"
        if detail == "summary" and r.get("conditional"):
            # a row that no tile of this city meets changes nothing here; the count says so
            kept = [c for c in r["conditional"] if c.get("worked_now") or c.get("owned_unworked")]
            dropped = len(r["conditional"]) - len(kept)
            r["conditional"] = kept
            if dropped:
                r["conditional_not_here"] = dropped
            if not kept:
                del r["conditional"]
    out = {"context": {"seat": args["pid"], "turn": raw.get("turn"), "city": raw.get("city")}, "rows": rows}
    for k in ("treasury", "unit_upkeep", "restrictions", "purchase_only", "producing"):
        if raw.get(k) is not None:
            out[k] = raw[k]
    if rest:
        out["omitted"] = {"count": len(rest), "candidates": [r.get("item") for r in rest],
                          "args": {"kind": "production", "city_id": args["city_id"],
                                   "candidates": [r.get("item") for r in rest]}}
    return out


def _research(raw: dict, args: dict, detail: str, limit: int) -> dict:
    science = raw.get("science_per_turn")
    rows, rest = _cut(raw.get("rows") or [], limit)
    for r in rows:
        beakers = r.get("path_beakers")
        if beakers is not None:
            r["path_turns_estimate"] = math.ceil(beakers / science) if science and science > 0 else "unknown"
        missing = r.get("missing_prereqs")
        if missing:
            r["missing_prereqs_count"] = len(missing)
            if detail == "summary" and len(missing) > MISSING_SHOWN:
                # ancestors first: the head of the list is what can be researched soonest
                r["missing_prereqs"] = missing[:MISSING_SHOWN]
        if detail == "summary" and r.get("unlocks"):
            r["unlocks"] = _unlock_names(r["unlocks"])
    out = {"context": {"seat": args["pid"], "turn": raw.get("turn")}, "science_per_turn": science,
           "current": raw.get("current"), "rows": rows}
    if rest:
        out["omitted"] = {"count": len(rest), "candidates": [r.get("tech") for r in rest],
                          "args": {"kind": "research", "candidates": [r.get("tech") for r in rest]}}
    return out


def _sort_key_improvement(sort: str):
    if sort == "turns":
        return lambda r: (r.get("turns") is None, r.get("turns") or 0)
    return lambda r: (not r.get("legal"), -((r.get("tile_change") or {}).get(sort) or 0))


def _improvements(raw: dict, args: dict, detail: str, limit: int, sort: str | None) -> dict:
    rows = list(raw.get("rows") or [])
    if sort:
        rows.sort(key=_sort_key_improvement(sort))
    rows, rest = _cut(rows, limit)
    plots = raw.get("plots") or []
    if detail == "summary":
        used = {(r["x"], r["y"]) for r in rows}
        plots = [p for p in plots if (p.get("x"), p.get("y")) in used or p.get("err") or p.get("note")]
    out = {"context": {"seat": args["pid"], "turn": raw.get("turn"), "unit": raw.get("unit")}, "plots": plots,
           "rows": rows}
    if not rows and not rest:
        out["note"] = ("no legal build on these plots" if not args.get("candidates")
                       else "none of these builds on these plots")
    if rest:
        more = sorted({(r["x"], r["y"]) for r in rest})
        out["omitted"] = {"count": len(rest), "rows": [[r["x"], r["y"], r.get("build")] for r in rest],
                          "plots": [list(p) for p in more],
                          "note": "the args re-read those plots, which may repeat rows already returned",
                          "args": {"kind": "improvements", "unit_id": args["unit_id"], "plots": [list(p) for p in more],
                                   **({"candidates": args["candidates"]} if args.get("candidates") else {})}}
    return out


def _trade(raw: dict, args: dict, detail: str, limit: int, sort: str | None) -> dict:
    rows = list(raw.get("rows") or [])
    if sort == "distance":
        rows.sort(key=lambda r: r.get("distance", 10 ** 6))
    elif sort:
        rows.sort(key=lambda r: -(r.get(sort) or 0))
    rows, rest = _cut(rows, limit)
    for r in rows:
        h = r.get("hazard") or {}
        if detail == "summary":
            r.pop("details", None)
            if len(h.get("hostile_units") or []) > 3:
                h["hostile_units_more"] = len(h["hostile_units"]) - 3
                h["hostile_units"] = h["hostile_units"][:3]
        if h.get("danger") == "none_visible" and h.get("not_visible"):
            h["note"] = f"{h['not_visible']} of {h.get('plots')} plots within {raw.get('radius')} are not visible"
    out = {"context": {"seat": args["pid"], "turn": raw.get("turn"), "unit": raw.get("unit"),
                       "origin": raw.get("origin")},
           "origin_area": raw.get("origin_area"), "rows": rows}
    if rest:
        out["omitted"] = {"count": len(rest), "args": {"kind": "trade", "unit_id": args["unit_id"],
                                                       "sort": sort, "limit": MAX_LIMIT}}
    return out


def shape(kind: str, raw, args: dict, detail: str = "summary", limit: int | None = None, sort: str | None = None) -> dict:
    """The comparison answer: context, rows (cut to `limit`), omitted with its arguments, sources, assumptions."""
    if not isinstance(raw, dict):
        return {"ok": False, "err": f"unexpected runtime answer: {raw!r}"[:300]}
    if raw.get("ok") is False:
        return raw
    raw = copy.deepcopy(raw)
    limit = limit or DEFAULT_LIMIT[kind]
    if kind == "production":
        out = _production(raw, args, detail, limit)
    elif kind == "research":
        out = _research(raw, args, detail, limit)
    elif kind == "improvements":
        out = _improvements(raw, args, detail, limit, sort)
    else:
        out = _trade(raw, args, detail, limit, sort)
    n = len(raw.get("rows") or [])
    head = {"ok": True, "kind": kind, "detail": detail, "n": n, "returned": len(out["rows"])}
    if sort:
        head["sort"] = sort
    return {**head, **out, "sources": SOURCES[kind], "assumptions": ASSUMPTIONS[kind]}
