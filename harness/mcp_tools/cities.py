"""Cities: the city screen, production, purchases, citizens, strikes and comparisons.

One of the civ5 MCP server's tool modules: every tool here registers on the server in
harness/mcp_server.py, which keeps the game handle, the guard and the tool sets (see its docstring).
"""
from __future__ import annotations

from harness import mcp_server as core
from harness.mcp_server import mcp, J, guarded


@mcp.tool()
@guarded
def cities() -> str:
    """My cities: population, yields, current production and turns left, growth, happiness.
    `growth` is "growing" (then `growth_turns` is present), "stagnant" (food_surplus 0 -- typical while
    empire happiness is negative, which throttles growth) or "starving" (negative surplus, will lose pop).
    `building_maintenance` / `connection_gold` are the Economic Overview per-city expense/income rows
    (omit when 0). `blockaded` / `wltkd_turns` are the city-banner blockade and We Love the King timer.
    Open one city with city_screen(city_id) for buildings, specialists, worked tiles,
    queue, and focus."""
    return J(core.game().cities())


@mcp.tool()
@guarded
def city_screen(city_id: int) -> str:
    """The city screen for one of my cities: buildings, specialists and their Great Person meters,
    which tiles are being worked, the full production queue, citizen focus, avoid-growth, and plots
    that can be bought (`buyable` + `buy_gold`). A tile the screen still prices in red (not enough
    gold) has `buy_gold` and `can_afford: false` instead of `buyable`. `meters` is the corner of
    the city screen: food stored/needed and the growth label (a settler counts as stagnant),
    production stored/needed/per-turn, culture stored/needed and turns until the next border tile,
    and the fractional gold/science plus faith and tourism per turn; `meters.breakdown` is the hover
    behind each of those (sources, food eaten, modifier lines, total). Specialist rows and slots
    carry `yields`; built buildings carry their enum and name (what each does: reference("buildings")). An owned tile another of our
    cities is working names that city (`worked_by`); a blockaded water tile or a visible enemy
    unit is marked. Buildings a human can click-to-sell carry `can_sell` / `sell_gold` /
    `gold_maintenance`. Writes from the same screen: set_city_focus, set_avoid_growth,
    change_working_plot, buy_city_plot, city_task (annex / raze / unraze), sell_building."""
    return J(core.game().city_screen(city_id))


@mcp.tool()
@guarded
def great_person_progress() -> str:
    """Great Person overview: each city's specialist progress, class-specific threshold and rate;
    national General/Admiral XP meters and next Prophet faith threshold."""
    return J(core.game().great_person_progress())


@mcp.tool()
@guarded
def culture_works() -> str:
    """Culture Overview works tab: own buildings' occupied/empty Great Work slots, work tooltips,
    theming rules/bonuses, city tourism breakdowns and tourism modifiers toward met rivals. `swap` is
    the swap tab: `ours` per class (the work we put up and the pull-down's candidates) and `theirs`
    (every met civ's offered writing/art/artifact). Writes: set_swappable_great_work, swap_great_works."""
    return J(core.game().culture_works())


@mcp.tool()
@guarded
def set_swappable_great_work(work_class: str, work_id: int = -1) -> str:
    """Swap tab pull-down: put one of our works of `work_class` (writing / art / artifact) up for
    swapping, or pass -1 to clear that spot. Candidates are culture_works().swap.ours[class].candidates."""
    return J(core.game().set_swappable_great_work(work_class, work_id))


@mcp.tool()
@guarded
def swap_great_works(their_work_id: int) -> str:
    """Swap tab's Swap button: exchange the work we have put up for one another civ offers
    (`their_work_id` from culture_works().swap.theirs, same class). Refused unless we have a work of
    that class put up."""
    return J(core.game().swap_great_works(their_work_id))


@mcp.tool()
@guarded
def change_specialist(city_id: int, building: str, add: bool) -> str:
    """Add (add=true) or remove (false) one specialist in a BUILDING_* from city_screen.
    Disables automatic specialist assignment, like clicking a slot. Verifies the resulting count."""
    return J(core.game().change_specialist(city_id, building, add))


@mcp.tool()
@guarded
def set_auto_specialists(city_id: int, automatic: bool) -> str:
    """Enable or disable automatic specialist assignment in an owned, non-puppet city."""
    return J(core.game().set_auto_specialists(city_id, automatic))


@mcp.tool()
@guarded
def set_city_focus(city_id: int, focus: str) -> str:
    """Set citizen focus on one of my (non-puppet) cities. focus is one of: balanced, food, production,
    gold, science, culture, great_people, faith. Same as the city-screen focus buttons."""
    return J(core.game().set_city_focus(city_id, focus))


@mcp.tool()
@guarded
def set_avoid_growth(city_id: int, avoid: bool) -> str:
    """Toggle avoid-growth on one of my (non-puppet) cities (the city-screen checkbox)."""
    return J(core.game().set_avoid_growth(city_id, avoid))


@mcp.tool()
@guarded
def change_working_plot(city_id: int, x: int, y: int) -> str:
    """Toggle whether this city works plot (x, y). Same as clicking the tile in the city screen.
    Forced-worked tiles stay locked until clicked again. Puppets refuse."""
    return J(core.game().change_working_plot(city_id, x, y))


@mcp.tool()
@guarded
def buy_city_plot(city_id: int, x: int, y: int) -> str:
    """Buy plot (x, y) for this city for gold. city_screen lists buyable plots with buy_gold."""
    return J(core.game().buy_city_plot(city_id, x, y))


@mcp.tool()
@guarded
def city_task(city_id: int, action: str) -> str:
    """City-screen tasks: annex (a puppet), raze, or unraze. Annexed cities get resistance;
    raze burns one population per turn. cities()/city_screen already flag puppet/razing state."""
    return J(core.game().city_task(city_id, action))


@mcp.tool()
@guarded
def sell_building(city_id: int, building: str) -> str:
    """Sell one building in one of my non-puppet cities (the city-screen click-to-sell).
    city_screen lists `can_sell` / `sell_gold` / `gold_maintenance`. Usually one sell per city per turn."""
    return J(core.game().sell_building(city_id, building))


@mcp.tool()
@guarded
def compare(kind: str, city_id: int | None = None, unit_id: int | None = None, candidates: list[str] | None = None,
            plots: list[list[int]] | None = None, sort: str | None = None, limit: int | None = None,
            detail: str = "summary") -> str:
    """Your candidates side by side in one read, for a decision you are weighing; the facts, never a pick.
    kind="production": city_id + candidates (up to 8 UNIT_/BUILDING_/PROJECT_/PROCESS_ types): can_produce or
    `why` not, cost, stored, turns, gold / faith price with *_can_buy, effects, conditional per-tile yields with
    how many of this city's tiles qualify, estimated_change (formula in assumptions), maintenance, unique_replaces.
    kind="research": up to 8 TECH_ types: status, cost, progress, turns, missing_prereqs, path_beakers and
    path_turns_estimate for a locked one, unlocks.
    kind="improvements": unit_id (a worker) + optional plots ([[x, y], ...]; default: plots within 2 that are
    owned or hold a resource) + optional candidates (BUILD_ types): per plot yields_now, worked, city; per build
    legal (or why), turns (work only), tile_change, empire_change when a city works the tile, removes /
    chop_production, connects, maintenance. Fogged plots are not read. sort= a yield or "turns".
    kind="trade": unit_id (a caravan or cargo ship in a city): every destination with what each end receives,
    distance and hazard (visible hostiles and camps near it; never "safe"). sort= gold, science, food,
    production, *_them or distance.
    Every answer has context, sources, assumptions, n / returned and `omitted` with the arguments that fetch
    the rest (`limit`, 1-20). detail="full" adds help text and the chooser's hover breakdown. Field by field:
    how_to_play("compare")."""
    return J(core.game().compare(kind, city_id=city_id, unit_id=unit_id, candidates=candidates, plots=plots, sort=sort,
                            limit=limit, detail=detail))


@mcp.tool()
@guarded
def city_ranged_attack(city_id: int, x: int, y: int) -> str:
    """Ranged attack from a city onto plot (x, y). See available_city_strikes first.
    Does not select the city or pan/flip the camera."""
    return J(core.game().city_ranged_attack(city_id, x, y))


@mcp.tool()
@guarded
def available_city_strikes(city_id: int) -> str:
    """Plots this city can bombard right now. Empty if it has no ranged strike this turn."""
    return J(core.game().available_city_strikes(city_id))


@mcp.tool()
@guarded
def available_production(city_id: int) -> str:
    """What this city can produce right now: units, buildings, projects, processes, with `turns` at the
    current production rate, and for units/buildings the gold rush-buy price (`gold`; absent when the item
    can never be bought, e.g. national wonders) plus `can_buy` (affordable AND purchasable right now ->
    purchase_production). Use set_production(city_id, item) to queue one.
    Each row carries `gold` (rush-buy cost, `can_buy`) and, when the faith tab offers it, `faith` + `faith_can_buy`;
    `faith_only` rows (Missionaries, Great People, belief buildings) cannot be produced, only bought
    with purchase_production(yield_type="FAITH").
    Each row carries the enum in `item` and, when it differs, the `name` the chooser button shows:
    BNW renamed several (BUILDING_THEATRE is "Zoo"), and `cities()` prints that name, not the enum.
    A puppet is refused (its AI picks production; `producing` says what) -- except for Venice, whose
    puppets answer `purchase_only: true` with just the gold/faith rows the purchase screen offers."""
    return J(core.game().available_production(city_id))


@mcp.tool()
@guarded
def set_production(city_id: int, item: str, append: bool = False) -> str:
    """Set a city's production. item like UNIT_WARRIOR, UNIT_SETTLER, BUILDING_MONUMENT, PROJECT_..., PROCESS_WEALTH.
    append=true queues it behind the current build (the production screen's shift-click) instead of replacing
    it; the reply lists the whole `queue`."""
    order = _production_order(item)
    resolved = None
    if order is None:
        # live 2026-09-27: set_production(item="BOGUS_THING") came back as a bare KeyError
        resolved = _resolve_production_name(core.game(), city_id, item)
        if resolved is None:
            return J({"ok": False, "err": f"item must start with UNIT_, BUILDING_, PROJECT_ or PROCESS_, not {item!r}",
                      "hint": "available_production(city_id) lists what this city can build, by enum"})
    r = core.game().set_production(city_id, order or _production_order(resolved), resolved or item, append=append)
    if isinstance(r, dict) and not r.get("ok") and str(r.get("err", "")).startswith("unknown item") and resolved is None:
        resolved = _resolve_production_name(core.game(), city_id, item)
        if resolved is not None:
            r = core.game().set_production(city_id, _production_order(resolved), resolved, append=append)
    if resolved is not None and isinstance(r, dict):
        r = dict(r, resolved={"asked": item, "item": resolved})
    return J(r)


def _resolve_production_name(game, city_id: int, item: str) -> str | None:
    """The enum in this city's available_production list whose chooser-button name is `item`, or None. BNW renamed
    several items without renaming their types (BUILDING_THEATRE is "Zoo"), so a seat that reads the name off
    `cities()` and asks for "Zoo" or guesses BUILDING_ZOO used to be refused (live t151, Beshbalik); the guess's
    tail ("ZOO") is matched as the name too. One match resolves; none or several do not."""
    r = game.available_production(city_id)
    rows = r.get("items") if isinstance(r, dict) else None
    if not rows:
        return None
    asked = str(item).strip().lower()
    wanted = {asked}
    if _production_order(item) and "_" in asked:
        wanted.add(asked.split("_", 1)[1].replace("_", " "))
    hits = {row["item"] for row in rows if isinstance(row, dict) and row.get("item")
            and str(row.get("name") or "").strip().lower() in wanted}
    return hits.pop() if len(hits) == 1 else None


@mcp.tool()
@guarded
def remove_from_queue(city_id: int, position: int) -> str:
    """Drop one item from a city's production queue (the city screen's click on a queued item). position is
    1-based as set_production's `queue` and city_screen list it: 1 is what the city is building now, 2 the item
    behind it. The reply names `removed` and the `queue` left; when nothing is left the city needs
    set_production before the turn can end. Re-setting an item already queued is refused ("already in this
    city's production queue (position N)"): remove it here first, or set_production another item."""
    return J(core.game().remove_from_queue(city_id, position))


def _production_order(item: str) -> str | None:
    """The engine order for an item enum by its prefix, or None: UNIT_ trains, BUILDING_ constructs, PROJECT_
    creates, PROCESS_ maintains."""
    return {"UNIT": "ORDER_TRAIN", "BUILDING": "ORDER_CONSTRUCT", "PROJECT": "ORDER_CREATE",
            "PROCESS": "ORDER_MAINTAIN"}.get(str(item).split("_", 1)[0].upper())


def _purchase_order(item: str) -> str | None:
    # PROJECT_* was missing: live t391 purchase_cost(PROJECT_APOLLO_PROGRAM) died with KeyError 'PROJECT'.
    order = _production_order(item)
    return None if order == "ORDER_MAINTAIN" else order   # a process is never bought


@mcp.tool()
@guarded
def purchase_cost(city_id: int, item: str, yield_type: str = "GOLD") -> str:
    """Read-only: cost to rush-buy item (UNIT_.../BUILDING_...) with gold or faith right now, and whether
    it's actually purchasable. yield_type is "GOLD" (default) or "FAITH". Wonders (built via a BUILDING_* item
    too) are never purchasable in vanilla BNW -- can_purchase will read false. Check this before purchase_production.
    A refusal carries `reason` and, when the engine has one, `engine_reason`: the same sentence the
    production popup puts under a greyed-out purchase button."""
    order = _purchase_order(item)
    if order is None:
        return J({"ok": False, "err": f"{item!r}: purchasable items are UNIT_*, BUILDING_* or PROJECT_*"})
    return J(core.game().purchase_cost(city_id, order, item, yield_type))


@mcp.tool()
@guarded
def purchase_production(city_id: int, item: str, yield_type: str = "GOLD") -> str:
    """Rush-buy a unit or building (item like UNIT_WARRIOR, BUILDING_MARKET) with gold or faith (yield_type
    "GOLD", the default, or "FAITH"). See purchase_cost for price/affordability first. Wonders can never be purchased this way."""
    order = _purchase_order(item)
    if order is None:
        return J({"ok": False, "err": f"{item!r}: purchasable items are UNIT_*, BUILDING_* or PROJECT_*"})
    return J(core.game().purchase_production(city_id, order, item, yield_type))
