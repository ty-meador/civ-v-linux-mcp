#!/usr/bin/env python3
"""Autonomous single-player play loop: the harness controls one seat (AI plays every
other seat), and this script plays turns unattended using simple heuristics instead of
an LLM, so the harness/game plumbing can be stress-tested for many turns without a
human (or an LLM) driving every action. This is the same ad hoc pattern used across
several previous live-play sessions (see docs/NOTES.md's "Phase 1"/turn 90+ sections
for the bugs it found: stacked units, promotion picking, pantheon founding, the tuner
liveness gap) -- checked in here instead of being rewritten from scratch each time.

Usage:
    python -m scripts.play_loop [--seat 0] [--max-turns N] [--stall-limit N]

Exits 0 on game over or --max-turns reached, 1 on a lost tuner connection, 2 if stuck
on the same blocker for --stall-limit consecutive attempts (this is a *signal*, not
just a failure: it means either a bug or a genuinely unimplemented action -- check the
log for `blocking_name` and add support in harness/game.py + harness/lua/runtime.lua,
following the pattern of choose_promotion/choose_policy/found_pantheon).
"""
from __future__ import annotations

import argparse
import sys
import time

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])

from harness.client import TunerConnectionLost  # noqa: E402
from harness.game import Game  # noqa: E402

# Candidate lists: harness's choose_promotion/choose_policy/found_pantheon all validate
# with CanAcquirePromotion/CanAdoptPolicy/CanCreatePantheon before doing anything, so
# trying an unavailable candidate is a safe, cheap {ok:false} no-op -- not a guess that
# risks corrupting state.
PROMOTION_CANDIDATES = [
    "PROMOTION_SHOCK_1", "PROMOTION_SHOCK_2", "PROMOTION_SHOCK_3",
    "PROMOTION_DRILL_1", "PROMOTION_DRILL_2", "PROMOTION_DRILL_3",
    "PROMOTION_COVER_1", "PROMOTION_COVER_2",
    "PROMOTION_ACCURACY_1", "PROMOTION_ACCURACY_2", "PROMOTION_ACCURACY_3",
    "PROMOTION_BARRAGE_1", "PROMOTION_BARRAGE_2", "PROMOTION_BARRAGE_3",
    "PROMOTION_RANGE", "PROMOTION_LOGISTICS", "PROMOTION_CHARGE", "PROMOTION_MEDIC",
    "PROMOTION_MEDIC_GENERAL", "PROMOTION_MOBILITY", "PROMOTION_AMBUSH_1",
    "PROMOTION_AMPHIBIOUS", "PROMOTION_SIEGE", "PROMOTION_INTERCEPTION_1",
    "PROMOTION_EVASION", "PROMOTION_EXTENDED_RANGE",
]
POLICY_CANDIDATES = [
    "POLICY_TRADITION", "POLICY_ARISTOCRACY", "POLICY_LEGALISM", "POLICY_LANDED_ELITE",
    "POLICY_MONARCHY", "POLICY_ORACLE",
    "POLICY_LIBERTY", "POLICY_COLLECTIVE_RULE", "POLICY_CITIZENSHIP", "POLICY_REPUBLIC",
    "POLICY_REPRESENTATION", "POLICY_MERITOCRACY",
    "POLICY_HONOR", "POLICY_WARRIOR_CODE", "POLICY_DISCIPLINE", "POLICY_MILITARY_TRADITION",
    "POLICY_MILITARY_CASTE", "POLICY_PROFESSIONAL_ARMY",
    "POLICY_PIETY", "POLICY_ORGANIZED_RELIGION", "POLICY_MANDATE_OF_HEAVEN",
    "POLICY_THEOCRACY", "POLICY_FREE_RELIGION", "POLICY_REFORMATION",
    "POLICY_COMMERCE", "POLICY_TRADE_UNIONS", "POLICY_MERCANTILISM", "POLICY_ENTREPRENEURSHIP",
    "POLICY_PROTECTIONISM", "POLICY_NAVAL_TRADITION",
]
BRANCH_CANDIDATES = [
    "POLICY_BRANCH_TRADITION", "POLICY_BRANCH_LIBERTY", "POLICY_BRANCH_HONOR",
    "POLICY_BRANCH_PIETY", "POLICY_BRANCH_COMMERCE", "POLICY_BRANCH_PATRONAGE",
    "POLICY_BRANCH_AESTHETICS", "POLICY_BRANCH_EXPLORATION",
]
BELIEF_CANDIDATES = [
    "BELIEF_GOD_OF_CRAFTSMEN", "BELIEF_GODDESS_OF_LOVE", "BELIEF_GODDESS_OF_PROTECTION",
    "BELIEF_GOD_OF_THE_SEA", "BELIEF_GOD_OF_WAR", "BELIEF_GODDESS_OF_FESTIVALS",
    "BELIEF_GOD_OF_THE_OPEN_SKY", "BELIEF_GODDESS_OF_THE_HUNT", "BELIEF_GOD_OF_HEALING",
    "BELIEF_ORACLE_OF_THE_DAWN", "BELIEF_SACRED_PATH", "BELIEF_STONE_CIRCLES",
    "BELIEF_DANCE_OF_THE_AURORA", "BELIEF_DESERT_FOLKLORE", "BELIEF_FERTILITY_RITES",
    "BELIEF_ONE_WITH_NATURE",
]
TECH_CANDIDATES = [
    "TECH_POTTERY", "TECH_ANIMAL_HUSBANDRY", "TECH_ARCHERY", "TECH_MINING",
    "TECH_BRONZE_WORKING", "TECH_WRITING", "TECH_TRAPPING", "TECH_THE_WHEEL",
    "TECH_MASONRY", "TECH_CALENDAR", "TECH_PHILOSOPHY", "TECH_CURRENCY",
    "TECH_IRON_WORKING", "TECH_HORSEBACK_RIDING", "TECH_MATHEMATICS",
    "TECH_CONSTRUCTION", "TECH_OPTICS", "TECH_HORSEBACK_RIDING", "TECH_DRAMA_AND_POETRY",
    "TECH_THEOLOGY", "TECH_CIVIL_SERVICE", "TECH_METAL_CASTING", "TECH_COMPASS",
    "TECH_EDUCATION", "TECH_ACOUSTICS", "TECH_CHIVALRY", "TECH_MACHINERY",
]
PRODUCTION_CANDIDATES = [
    ("UNIT_WORKER", "ORDER_TRAIN"),
    ("BUILDING_MONUMENT", "ORDER_CONSTRUCT"),
    ("BUILDING_SHRINE", "ORDER_CONSTRUCT"),
    ("BUILDING_GRANARY", "ORDER_CONSTRUCT"),
    ("UNIT_WARRIOR", "ORDER_TRAIN"),
    ("UNIT_SCOUT", "ORDER_TRAIN"),
    ("BUILDING_LIBRARY", "ORDER_CONSTRUCT"),
    ("BUILDING_TEMPLE", "ORDER_CONSTRUCT"),
    ("BUILDING_WALLS", "ORDER_CONSTRUCT"),
    ("BUILDING_MARKET", "ORDER_CONSTRUCT"),
    ("BUILDING_AQUEDUCT", "ORDER_CONSTRUCT"),
    ("BUILDING_COLOSSEUM", "ORDER_CONSTRUCT"),
    ("UNIT_SETTLER", "ORDER_TRAIN"),
]

MOVE_OFFSETS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)]

# Blockers we know how to resolve with an existing harness tool. Anything else counts
# as a stall -- see module docstring.
HANDLED_BLOCKERS = {
    "ENDTURN_BLOCKING_UNIT_PROMOTION", "ENDTURN_BLOCKING_POLICY", "ENDTURN_BLOCKING_FOUND_PANTHEON",
    "ENDTURN_BLOCKING_STACKED_UNITS", "ENDTURN_BLOCKING_RESEARCH", "ENDTURN_BLOCKING_PRODUCTION",
    "ENDTURN_BLOCKING_UNITS", "ENDTURN_BLOCKING_UNIT_NEEDS_ORDERS",
}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def resolve_promotion(g: Game, seat: int) -> bool:
    """Ask each unit what it can actually take, and only fall back to guessing.

    The candidate list predates `available_unit_actions(unit).promotions` (v153), which is the
    engine's own answer. Walking 26 candidates is one tuner round-trip each: live t195 a single
    promoting unit spent over a minute being told "no" 20-odd times before landing on one.
    """
    for u in g.units(seat):
        if not u.get("promotion_ready"):
            continue
        offered = []
        try:
            actions = g.available_unit_actions(u["id"], seat) or {}
            offered = [p.get("promotion") for p in actions.get("promotions") or [] if p.get("promotion")]
        except Exception:                                       # noqa: BLE001 -- fall back to guessing
            offered = []
        for promo in offered or PROMOTION_CANDIDATES:
            r = g.choose_promotion(u["id"], promo, seat)
            if r.get("ok"):
                log(f"  promoted unit {u['id']} ({u['type']}) -> {promo}"
                    + ("" if offered else " (by guesswork: the unit offered no list)"))
                return True
    return False


def resolve_policy(g: Game, seat: int) -> bool:
    for pol in POLICY_CANDIDATES:
        if g.choose_policy(pol, seat).get("ok"):
            log(f"  adopted policy {pol}")
            return True
    for br in BRANCH_CANDIDATES:
        if g.unlock_policy_branch(br, seat).get("ok"):
            log(f"  unlocked policy branch {br}")
            return True
    return False


def resolve_pantheon(g: Game, seat: int) -> bool:
    for b in BELIEF_CANDIDATES:
        if g.found_pantheon(b, seat).get("ok"):
            log(f"  founded pantheon: {b}")
            return True
    return False


def resolve_research(g: Game, seat: int) -> bool:
    cur = g.summary(seat).get("research")
    for t in TECH_CANDIDATES:
        if t == cur:
            continue
        g.set_research(t, seat)
        time.sleep(0.3)
        new = g.summary(seat).get("research")
        if new and new != cur:
            log(f"  research set to {t}")
            return True
    return False


def resolve_stacked_units(g: Game, seat: int) -> bool:
    """Live-tested 2026-09-16: unlike plain ENDTURN_BLOCKING_UNITS, giving an idle unit
    MISSION_SKIP/MISSION_FORTIFY does NOT clear ENDTURN_BLOCKING_STACKED_UNITS, even
    though unit_mission() returns {ok:true} either way and the unit's mission/ready
    state is unchanged by either call -- confirmed with two idle Workers sharing the
    capital's city tile at turn 18. What DOES clear it: physically moving one of the
    units off the shared tile with move_unit() (verified live: blocking flipped from
    STACKED_UNITS to plain UNITS for the one remaining idle unit, which
    resolve_units_need_orders then handles normally). This holds even on a city tile,
    which disproves the assumption (baked into an earlier version of this function)
    that stacking is always legal there. See docs/NOTES.md."""
    by_tile: dict[tuple[int, int], list[dict]] = {}
    for u in g.units(seat):
        by_tile.setdefault((u["x"], u["y"]), []).append(u)
    moved = False
    for (x, y), us in by_tile.items():
        if len(us) < 2:
            continue
        for u in us[1:]:
            if u["moves"] <= 0:
                continue
            for dx, dy in MOVE_OFFSETS:
                r = g.move_unit(u["id"], x + dx, y + dy, seat)
                if r.get("ok") and (r.get("x"), r.get("y")) != (x, y):
                    moved = True
                    log(f"  moved unit {u['id']} off stack at ({x},{y}) -> ({r.get('x')},{r.get('y')})")
                    break
    # Fallback for units that couldn't move (0 moves left, or boxed in): give orders to
    # whatever is left idle. Won't clear STACKED_UNITS by itself but keeps other
    # blockers (plain UNITS) from piling up behind it.
    return resolve_units_need_orders(g, seat) or moved


def resolve_units_need_orders(g: Game, seat: int) -> bool:
    """ENDTURN_BLOCKING_UNITS/UNIT_NEEDS_ORDERS: any idle unit with moves left and no
    mission blocks end-turn. A settler that can found gets MISSION_FOUND; everything
    else just gets fortified (a heuristic bot has no plan for exploring/building)."""
    acted = False
    for u in g.units(seat):
        if u["fortified"] or u["automated"] or u["moves"] <= 0:
            continue
        if u["mission"] != -1:
            continue
        if u.get("can_found"):
            g.unit_mission(u["id"], "MISSION_FOUND", pid=seat)
            log(f"  unit {u['id']} ({u['type']}): founding city")
        else:
            # MISSION_FORTIFY silently no-ops on non-combat units (e.g. Worker) -- CanFortify
            # is false for them, so fortified/mission never change and this blocker never
            # clears. MISSION_SKIP is valid for every unit type; it just re-asks next turn
            # instead of sticking, which is fine for a heuristic bot.
            g.unit_mission(u["id"], "MISSION_SKIP", pid=seat)
        acted = True
    return acted


def ensure_production(g: Game, seat: int) -> None:
    for c in g.cities(seat):
        if c["queue_len"] > 0:
            continue
        for item, order in PRODUCTION_CANDIDATES:
            r = g.set_production(c["id"], order, item, seat)
            if r.get("ok"):
                log(f"  city {c['name']}: queued {item}")
                break


BLOCKER_HANDLERS = {
    "ENDTURN_BLOCKING_UNIT_PROMOTION": resolve_promotion,
    "ENDTURN_BLOCKING_POLICY": resolve_policy,
    "ENDTURN_BLOCKING_FOUND_PANTHEON": resolve_pantheon,
    "ENDTURN_BLOCKING_RESEARCH": resolve_research,
    "ENDTURN_BLOCKING_STACKED_UNITS": resolve_stacked_units,
    "ENDTURN_BLOCKING_UNITS": resolve_units_need_orders,
    "ENDTURN_BLOCKING_UNIT_NEEDS_ORDERS": resolve_units_need_orders,
    "ENDTURN_BLOCKING_PRODUCTION": lambda g, seat: (ensure_production(g, seat) or True),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seat", type=int, default=0)
    ap.add_argument("--max-turns", type=int, default=0, help="0 = unlimited")
    ap.add_argument("--stall-limit", type=int, default=15)
    ap.add_argument("--wait-timeout", type=float, default=3600)
    args = ap.parse_args()

    g = Game()
    seat = args.seat
    turns_played = 0
    last_blocking = None
    stalls = 0

    log(f"play_loop starting: seat={seat} max_turns={args.max_turns or 'unlimited'}")

    while True:
        try:
            ts = g.wait_for_my_turn(timeout=args.wait_timeout)
        except TunerConnectionLost as e:
            log(f"FATAL: tuner connection lost: {e}")
            return 1
        except TimeoutError:
            log("timed out waiting for our turn; retrying")
            continue

        if ts.get("game_over"):
            log(f"game over at turn {ts.get('turn')}")
            return 0

        blocking_name = ts.get("blocking_name")
        if blocking_name and blocking_name != "NO_ENDTURN_BLOCKING_TYPE":
            if blocking_name == last_blocking:
                stalls += 1
            else:
                last_blocking = blocking_name
                stalls = 1
            if stalls > args.stall_limit:
                log(f"FATAL: stuck on {blocking_name} for {stalls} consecutive attempts; giving up "
                    f"(turn_state={ts})")
                return 2
            log(f"turn {ts.get('turn')}: blocked on {blocking_name} (attempt {stalls})")
            handler = BLOCKER_HANDLERS.get(blocking_name)
            if handler is None:
                log(f"  no handler for {blocking_name}; needs a new harness tool (see NOTES.md pattern)")
            else:
                try:
                    resolved = handler(g, seat)
                    if not resolved:
                        log("  handler ran but could not resolve it this pass")
                except Exception as e:  # noqa: BLE001 - keep the loop alive, log and retry
                    log(f"  handler raised {e!r}")
            time.sleep(1.0)
            continue

        last_blocking = None
        stalls = 0
        ensure_production(g, seat)
        resolve_units_need_orders(g, seat)
        turn_before = ts.get("turn")
        r = g.end_turn()
        if not r.get("ok"):
            log(f"end_turn failed: {r.get('err')}; retrying")
            time.sleep(1.0)
            continue
        time.sleep(0.5)
        turn_after = g.turn_state().get("turn")
        if turn_after == turn_before:
            # end_turn() returned ok but the game turn counter didn't move -- usually AI
            # processing hasn't caught up yet; back off instead of busy-spinning the tuner.
            time.sleep(1.0)
            continue
        turns_played += 1
        log(f"ended turn {turn_before} (played {turns_played} this session)")
        if args.max_turns and turns_played >= args.max_turns:
            log("reached --max-turns; stopping")
            return 0


if __name__ == "__main__":
    sys.exit(main())
