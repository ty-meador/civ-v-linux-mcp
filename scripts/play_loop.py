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
import contextlib
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
    "ENDTURN_BLOCKING_LEAGUE_CALL_FOR_VOTES",
}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class Profile:
    """Where a turn's wall time goes: per loop phase, and per Game method by tuner round-trips.

    Every trip to the game passes through `Civ5.call`; wrapping it attributes each trip to the
    outermost `harness/game.py` frame on the stack (the public Game method, not `q`) and to the
    phase the loop is in. Written for the open ROADMAP row "where a late-game turn spends its
    ~15 min": the handoff blamed `available_unit_actions` per unit, which measured at 0.37 s a
    call, so the guess was wrong and the loop had to be timed rather than reasoned about.
    """

    def __init__(self, g: Game) -> None:
        self.phase = "-"
        self.calls: dict[tuple[str, str], list[float]] = {}     # (phase, method) -> [n, seconds]
        self.phases: dict[str, list[float]] = {}                # phase -> [n, seconds]
        self.turn_started = time.perf_counter()
        inner = g.c.call

        def call(**req):
            t0 = time.perf_counter()
            try:
                return inner(**req)
            finally:
                row = self.calls.setdefault((self.phase, self._method()), [0, 0.0])
                row[0] += 1
                row[1] += time.perf_counter() - t0
        g.c.call = call

    @staticmethod
    def _method() -> str:
        f, name = sys._getframe(2), "?"
        while f is not None:
            if f.f_code.co_filename.endswith("harness/game.py") and not f.f_code.co_name.startswith("_"):
                name = f.f_code.co_name
            f = f.f_back
        return name

    @contextlib.contextmanager
    def in_phase(self, name: str):
        prev, self.phase = self.phase, name
        t0 = time.perf_counter()
        try:
            yield
        finally:
            row = self.phases.setdefault(name, [0, 0.0])
            row[0] += 1
            row[1] += time.perf_counter() - t0
            self.phase = prev

    def report(self, label: str) -> None:
        total = time.perf_counter() - self.turn_started
        log(f"profile {label}: {total:.1f} s wall")
        for name, (n, secs) in sorted(self.phases.items(), key=lambda kv: -kv[1][1]):
            trips = sum(v[0] for (ph, _), v in self.calls.items() if ph == name)
            in_game = sum(v[1] for (ph, _), v in self.calls.items() if ph == name)
            log(f"  phase {name:<28} {secs:7.1f} s  x{n:<3} {trips:4d} trips, {in_game:6.1f} s in the game")
        by_method: dict[str, list[float]] = {}
        for (_, m), (n, secs) in self.calls.items():
            row = by_method.setdefault(m, [0, 0.0])
            row[0] += n
            row[1] += secs
        for m, (n, secs) in sorted(by_method.items(), key=lambda kv: -kv[1][1])[:12]:
            log(f"  {m:<34} {n:5d} trips {secs:7.1f} s  {secs / n:6.2f} s each")
        self.calls.clear()
        self.phases.clear()
        self.turn_started = time.perf_counter()


def resolve_promotion(g: Game, seat: int) -> bool:
    """Ask each unit what it can actually take, and only fall back to guessing.

    The candidate list predates `available_unit_actions(unit).promotions` (v153), which is the
    engine's own answer. Walking 26 candidates is one tuner round-trip each: live t195 a single
    promoting unit spent over a minute being told "no" 20-odd times before landing on one.
    """
    ready = (g.turn_state(seat).get("todo") or {}).get("promotions") or []
    units = {u["id"]: u for u in g.units(seat)}
    for unit_id in ready or list(units):
        offered = []
        try:
            actions = g.available_unit_actions(unit_id, seat) or {}
            offered = [p.get("promotion") for p in actions.get("promotions") or [] if p.get("promotion")]
        except Exception:                                       # noqa: BLE001 -- fall back to guessing
            offered = []
        what = units.get(unit_id, {}).get("type", "?")
        for promo in offered or PROMOTION_CANDIDATES:
            r = g.choose_promotion(unit_id, promo, seat)
            if r.get("ok"):
                log(f"  promoted unit {unit_id} ({what}) -> {promo}"
                    + ("" if offered else " (by guesswork: the unit offered no list)"))
                return True
    return False


def resolve_policy(g: Game, seat: int) -> bool:
    """Adopt what the policy screen offers; the static lists only order the preference.

    Live Doge t215: an Atomic start's free policies offered Oligarchy / Philanthropy / Consulates, none of
    them in POLICY_CANDIDATES, and re-"unlocking" the already-open Tradition counted as progress five
    times, so the sweeper gave up on a turn it could have ended.
    """
    try:
        screen = g.available_policies(seat) or {}
    except Exception as e:  # noqa: BLE001 -- fall back to the static lists
        log(f"  available_policies raised {e!r}")
        screen = {}
    adoptable = [r.get("policy") for r in screen.get("adoptable") or [] if r.get("policy")]
    ordered = [p for p in POLICY_CANDIDATES if p in adoptable] + [p for p in adoptable if p not in POLICY_CANDIDATES]
    for pol in ordered or POLICY_CANDIDATES:
        if g.choose_policy(pol, seat).get("ok"):
            log(f"  adopted policy {pol}")
            return True
    unlockable = [b.get("branch") for b in screen.get("branches") or []
                  if b.get("can_unlock") and not b.get("unlocked") and not b.get("blocked") and not b.get("ideology")]
    ordered_b = [b for b in BRANCH_CANDIDATES if b in unlockable] + [b for b in unlockable if b not in BRANCH_CANDIDATES]
    for br in ordered_b or BRANCH_CANDIDATES:
        if g.unlock_policy_branch(br, seat).get("ok"):
            log(f"  unlocked policy branch {br}")
            return True
    return False


IDEOLOGY_CANDIDATES = ["POLICY_BRANCH_FREEDOM", "POLICY_BRANCH_ORDER", "POLICY_BRANCH_AUTOCRACY"]


def resolve_ideology(g: Game, seat: int) -> bool:
    """ENDTURN_BLOCKING_CHOOSE_IDEOLOGY (live Doge t215: an Atomic start reaches it on the first
    policy turn). choose_ideology is chooseideologypopup.lua's Confirm; the first tree that takes wins."""
    for br in IDEOLOGY_CANDIDATES:
        r = g.choose_ideology(br, seat)
        if r.get("ok") and r.get("ideology"):
            log(f"  chose ideology {r.get('ideology')}")
            return True
    return False


def resolve_pantheon(g: Game, seat: int) -> bool:
    for b in BELIEF_CANDIDATES:
        if g.found_pantheon(b, seat).get("ok"):
            log(f"  founded pantheon: {b}")
            return True
    return False


def decline_diplomacy(g: Game, seat: int) -> str:
    """Leave a leader screen without agreeing to anything, and name what was on it.

    A trade table needs refuse_deal; a remark or a yes/no question only has dismiss_discussion,
    which is the Back button and commits to nothing.
    """
    try:
        d = g.discussion(seat) or {}
    except Exception as e:  # noqa: BLE001 -- never let a read stop the loop
        return f"unreadable: {e}"
    what = d.get("screen") or "discussion"
    leader = (d.get("relationship") or {}).get("leader") or d.get("player")
    try:
        if what == "trade":
            g.refuse_deal(seat)
        else:
            g.dismiss_discussion()
    except Exception as e:  # noqa: BLE001
        return f"{what} from {leader}: could not close it ({e})"
    return f"{what} from {leader}"


def abstain_league_votes(g: Game, seat: int) -> bool:
    """Clear a World Congress session without deciding world policy.

    ENDTURN_BLOCKING_LEAGUE_CALL_FOR_VOTES only clears on a real vote call (see NOTES.md: opening and
    closing the overview does nothing), so this loop used to stall out on it -- live t236, the First
    Congress of Palenque's Choose Host vote, 16 attempts and a FATAL. `league_cast_votes([])` casts
    every remaining vote as abstain, which clears the blocker and commits to nothing. Picking a side
    is a strategic decision and stays with whoever is driving.

    CALL_FOR_PROPOSALS has no equivalent: it needs an actual proposal, so it is still a stall.
    """
    try:
        r = g.league_cast_votes([])
    except Exception as e:  # noqa: BLE001 -- report as unresolved, let the stall counter decide
        log(f"  could not abstain: {e}")
        return False
    if not r.get("ok"):
        log(f"  abstain refused: {r.get('err')}")
        return False
    log(f"  abstained {r.get('abstained', '?')} vote(s) in the World Congress")
    return True


def resolve_research(g: Game, seat: int) -> bool:
    """Ask the engine what is researchable before falling back to the candidate list.

    TECH_CANDIDATES is an early-game ladder; by the Industrial era every name on it is already
    researched, so this walked all of them, set nothing, and reported a stall on a turn where the
    tech chooser was simply open (live t232). `available_research` is the chooser's own rows -- the
    same fix resolve_promotion got when it started asking the unit instead of guessing.
    """
    cur = g.summary(seat).get("research")
    offered = []
    try:
        offered = [r.get("tech") for r in (g.available_research(seat) or []) if isinstance(r, dict)]
    except Exception as e:  # noqa: BLE001 -- fall back to the static ladder below
        log(f"  available_research failed ({e}); falling back to the candidate list")
    for t in [t for t in offered if t] + TECH_CANDIDATES:
        if t == cur:
            continue
        g.set_research(t, seat)
        time.sleep(0.3)
        new = g.summary(seat).get("research")
        if new and new != cur:
            log(f"  research set to {t}")
            return True
    return False


def resolve_steal_tech(g: Game, seat: int) -> bool:
    """ENDTURN_BLOCKING_STEAL_TECH: a spy finished stealing and the Steal Technology chooser is
    up. Live t228 and t242 this stalled the loop (no handler, answered by hand both times). The
    chooser's rows are steal_tech_options; take the dearest tech from each victim -- a heuristic
    bot has no research plan, and beakers are beakers."""
    opts = g.steal_tech_options(seat)
    acted = False
    for v in opts.get("victims") or []:
        techs = [t for t in (v.get("techs") or []) if t.get("tech")]
        if not techs:
            continue
        pick = max(techs, key=lambda t: t.get("cost") or 0)
        r = g.steal_tech(pick["tech"], v["player_id"], seat)
        if r.get("ok"):
            log(f"  stole {pick['tech']} from player {v['player_id']} ({v.get('civ')})")
            acted = True
        else:
            log(f"  steal_tech {pick['tech']} from {v['player_id']} refused: {r.get('err')}")
    return acted


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
    routed = ensure_trade_routes(g, seat)
    # Runtime v183 lists the real stacks (todo.stacked: same-class land/sea units on one tile;
    # aircraft never count). Live t248 the plain per-tile grouping below walked a Worker out of
    # Te-Moak because a Fighter and a Bomber shared its city -- not a stack. Fall back to the
    # grouping only when the runtime has no such list.
    stacks: list[tuple[tuple[int, int], list[dict]]] = []
    todo = (g.turn_state(seat) or {}).get("todo") or {}
    if isinstance(todo.get("stacked"), list):
        stacks = [((s["x"], s["y"]), s.get("units") or []) for s in todo["stacked"]]
    else:
        by_tile: dict[tuple[int, int], list[dict]] = {}
        for u in g.units(seat):
            if u.get("domain") != "AIR":
                by_tile.setdefault((u["x"], u["y"]), []).append(u)
        stacks = [(k, v) for k, v in by_tile.items() if len(v) >= 2]
    moved = False
    for (x, y), us in stacks:
        # Live t245: a Caravan finished in Goshute on top of a Worker. The old loop only tried the
        # units after the first on the tile -- the Caravan, which cannot be walked anywhere -- and
        # stalled eleven attempts. Try every unit that can walk; a trade unit leaves by route.
        cleared = False
        for u in us:
            if cleared:
                break
            if u["moves"] <= 0 or u["type"] in TRADE_UNIT_TYPES or u.get("domain") == "AIR":
                continue
            for dx, dy in MOVE_OFFSETS:
                r = g.move_unit(u["id"], x + dx, y + dy, seat)
                if r.get("ok") and (r.get("x"), r.get("y")) != (x, y):
                    moved = cleared = True
                    log(f"  moved unit {u['id']} off stack at ({x},{y}) -> ({r.get('x')},{r.get('y')})")
                    break
    # Fallback for units that couldn't move (0 moves left, or boxed in): give orders to
    # whatever is left idle. Won't clear STACKED_UNITS by itself but keeps other
    # blockers (plain UNITS) from piling up behind it.
    return resolve_units_need_orders(g, seat) or moved or routed


TRADE_UNIT_TYPES = {"CARAVAN", "CARGO_SHIP"}
BUILDER_UNIT_TYPES = {"WORKER", "WORK_BOAT"}


def ensure_trade_routes(g: Game, seat: int) -> bool:
    """A finished Caravan / Cargo Ship sits idle in its city (not automated, moves left) until it is
    given a route; a heuristic bot takes the row with the most gold for us, else the most food or
    production delivered. The route is the unit for its duration, so this also clears any stack it
    was part of."""
    acted = False
    for u in g.units(seat):
        if u["type"] not in TRADE_UNIT_TYPES or u["automated"] or u["moves"] <= 0:
            continue
        rows = g.available_trade_routes(u["id"], seat)
        if not isinstance(rows, list) or not rows:
            continue
        best = max(rows, key=lambda r: (r.get("gold") or 0, (r.get("production_them") or 0) + (r.get("food_them") or 0)))
        r = g.establish_trade_route(u["id"], best["x"], best["y"], best["trade_connection_type"], seat)
        if r.get("ok"):
            log(f"  {u['type']} {u['id']}: route to {best.get('city_name')} ({best.get('kind')}, "
                f"gold {best.get('gold')}, food {best.get('food_them')}, production {best.get('production_them')})")
            acted = True
        else:
            log(f"  {u['type']} {u['id']}: route to {best.get('city_name')} refused: {r.get('err')}")
    return acted


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
        elif u["type"] in BUILDER_UNIT_TYPES and not u.get("build"):
            # An idle Worker / Work Boat skipped every turn never improves a tile; the human's
            # answer is the unit panel's Automate button (live t252: four Workers sat around
            # Goshute for ten turns of the loop). Once automated it never blocks again.
            r = g.unit_mission(u["id"], "AUTOMATE_BUILD", pid=seat)
            if r.get("automated"):
                log(f"  unit {u['id']} ({u['type']}): automated")
            else:
                log(f"  unit {u['id']} ({u['type']}): automate refused: {r.get('err')}")
                g.unit_mission(u["id"], "MISSION_SKIP", pid=seat)
        else:
            # MISSION_FORTIFY silently no-ops on non-combat units (e.g. Worker) -- CanFortify
            # is false for them, so fortified/mission never change and this blocker never
            # clears. MISSION_SKIP is valid for every unit type; it just re-asks next turn
            # instead of sticking, which is fine for a heuristic bot.
            g.unit_mission(u["id"], "MISSION_SKIP", pid=seat)
        acted = True
    return acted


def ensure_production(g: Game, seat: int) -> None:
    cities = g.cities(seat)
    # UNIT_WORKER heads the fallback list, so every idle city trained another Worker: live t254
    # Goshute's fourth spare Worker spawned on the one already standing in the city and the
    # unstacker had to walk it out every other turn. One Worker per city is plenty for a bot.
    workers = sum(1 for u in g.units(seat) if u["type"] in BUILDER_UNIT_TYPES)
    enough_workers = workers >= len(cities)
    for c in cities:
        if c["queue_len"] > 0:
            continue
        for item, order in PRODUCTION_CANDIDATES:
            if item == "UNIT_WORKER" and enough_workers:
                continue
            r = g.set_production(c["id"], order, item, seat)
            if r.get("ok"):
                log(f"  city {c['name']}: queued {item}")
                break


BLOCKER_HANDLERS = {
    "ENDTURN_BLOCKING_UNIT_PROMOTION": resolve_promotion,
    "ENDTURN_BLOCKING_POLICY": resolve_policy,
    "ENDTURN_BLOCKING_CHOOSE_IDEOLOGY": resolve_ideology,
    "ENDTURN_BLOCKING_FOUND_PANTHEON": resolve_pantheon,
    "ENDTURN_BLOCKING_RESEARCH": resolve_research,
    "ENDTURN_BLOCKING_STACKED_UNITS": resolve_stacked_units,
    "ENDTURN_BLOCKING_UNITS": resolve_units_need_orders,
    "ENDTURN_BLOCKING_UNIT_NEEDS_ORDERS": resolve_units_need_orders,
    "ENDTURN_BLOCKING_PRODUCTION": lambda g, seat: (ensure_production(g, seat) or True),
    "ENDTURN_BLOCKING_LEAGUE_CALL_FOR_VOTES": abstain_league_votes,
    "ENDTURN_BLOCKING_STEAL_TECH": resolve_steal_tech,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seat", type=int, default=0)
    ap.add_argument("--seats", type=int, nargs="+", default=None,
                    help="hotseat: play every one of these seats in turn (overrides --seat); a turn "
                         "counts once the whole rotation has ended it")
    ap.add_argument("--max-turns", type=int, default=0, help="0 = unlimited")
    ap.add_argument("--stall-limit", type=int, default=15)
    ap.add_argument("--wait-timeout", type=float, default=3600)
    ap.add_argument("--profile", action="store_true",
                    help="log, after every turn, the wall time per loop phase and per Game method")
    args = ap.parse_args()

    g = Game()
    prof = Profile(g) if args.profile else None
    phase = prof.in_phase if prof else (lambda name: contextlib.nullcontext())
    seats = args.seats or [args.seat]
    rotation = 0          # index into seats: the seat whose turn we are playing (or waiting for)
    seat = seats[0]
    turns_played = 0
    ended_turn = None  # the turn whose end_turn was accepted and whose successor we have not seen yet
    last_blocking = None
    stalls = 0

    log(f"play_loop starting: seats={seats} max_turns={args.max_turns or 'unlimited'}")

    while True:
        # Hotseat: every seat is ours, one after the other. The Game object reads and orders as
        # `g.seat`, so it is re-pointed at the seat whose turn comes next before the wait (the
        # wait dismisses that seat's hand-off screen). A blocker keeps the same seat; a turn that
        # ended moves on to the next one.
        seat = seats[rotation % len(seats)]
        g.seat = seat
        try:
            with phase("wait_for_my_turn"):
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

        # Count the turn once its successor is on the table. The old code checked the counter
        # half a second after end_turn and, when the AIs had not finished, backed off into the
        # next wait -- which returned on the new turn with no memory of the old one (live t253
        # went unlogged and uncounted, so --max-turns 8 played nine).
        if ended_turn is not None and ts.get("turn") not in (None, ended_turn):
            # With several seats the counter only moves once the last seat of the rotation has
            # ended the turn, so this still counts each turn exactly once.
            turns_played += 1
            log(f"ended turn {ended_turn} (played {turns_played} this session)")
            if prof:
                prof.report(f"turn {ended_turn}")
            ended_turn = None
            if args.max_turns and turns_played >= args.max_turns:
                log("reached --max-turns; stopping")
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
            log(f"turn {ts.get('turn')} seat {seat}: blocked on {blocking_name} (attempt {stalls})")
            handler = BLOCKER_HANDLERS.get(blocking_name)
            if handler is None:
                log(f"  no handler for {blocking_name}; needs a new harness tool (see NOTES.md pattern)")
            else:
                try:
                    with phase(f"blocker:{blocking_name.removeprefix('ENDTURN_BLOCKING_')}"):
                        resolved = handler(g, seat)
                    if not resolved:
                        log("  handler ran but could not resolve it this pass")
                except Exception as e:  # noqa: BLE001 - keep the loop alive, log and retry
                    log(f"  handler raised {e!r}")
            time.sleep(1.0)
            continue

        last_blocking = None
        stalls = 0
        with phase("ensure_production"):
            ensure_production(g, seat)
        with phase("ensure_trade_routes"):
            ensure_trade_routes(g, seat)
        with phase("resolve_units_need_orders"):
            resolve_units_need_orders(g, seat)
        turn_before = ts.get("turn")
        with phase("end_turn"):
            r = g.end_turn()
        if not r.get("ok"):
            if "diplomatic decision pending" in str(r.get("err", "")):
                # An AI at the table blocks end_turn and no blocking_name reports it, so the old
                # code retried the same failing call forever (live t232: Pacal offering Open
                # Borders, five minutes of "retrying"). This loop declines on principle -- it is a
                # plumbing stress test and must not sign treaties unattended -- and says what it
                # turned down so the transcript shows what the AI wanted.
                with phase("decline_diplomacy"):
                    walked_away = decline_diplomacy(g, seat)
                log(f"  declined a diplomatic approach ({walked_away})")
                time.sleep(0.5)
                continue
            log(f"end_turn failed: {r.get('err')}; retrying")
            time.sleep(1.0)
            continue
        if len(seats) > 1:
            log(f"  seat {seat} ended turn {turn_before}")
        ended_turn = turn_before
        rotation += 1
        time.sleep(0.5)


if __name__ == "__main__":
    sys.exit(main())
