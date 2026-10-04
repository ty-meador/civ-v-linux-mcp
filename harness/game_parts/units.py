"""Units: movement with its attack and interception previews, missions, promotions, upgrades, the per-unit action reads."""
from __future__ import annotations

import re
import threading
import time

from ..client import TunerdError

from .support import ROUTINE_ACTIONS, TODO_DETAIL_LEVELS, _summary_unit_row, lua_str, lua_table, spread_effects

# An order goes out as a net message and is applied on the next game frame: a read that follows the push by one
# tuner trip already shows it (live t151: MISSION_SKIP and AUTOMATE_BUILD, six pushes, 43-60 ms each). One short
# wait covers a frame that runs long; the 0.2-0.25 s it used to be was most of a plain order's time.
AFTER_READ_DELAY = 0.05
# Great Person missions that spend the unit in one go: afterwards the unit is gone, or nothing happened.
ONE_SHOT_GP_MISSIONS = frozenset({"MISSION_ONE_SHOT_TOURISM", "MISSION_GIVE_POLICIES", "MISSION_GOLDEN_AGE",
                                  "MISSION_TRADE", "MISSION_DISCOVER", "MISSION_HURRY", "MISSION_BUY_CITY_STATE",
                                  "MISSION_REPAIR_FLEET"})


def _automate_landed(chk) -> bool:
    return isinstance(chk, dict) and bool(chk.get("automated") or chk.get("gone"))


# `do` turns this on for the length of a batch, in the thread that runs its orders: a unit order then answers an
# `after_pending` marker (unit_id, mission, kind) instead of spending its own tuner trip on the read-back that
# follows every mission, and the batch reads every such unit in one query at its end (read_after_batch).
# Thread-local so a lone order served on another thread meanwhile still reads its unit back itself.
_DEFER = threading.local()


def defer_after_reads(on: bool) -> None:
    _DEFER.on = bool(on)


def deferring_after_reads() -> bool:
    return bool(getattr(_DEFER, "on", False))



class UnitsMixin:
    """Units: movement with its attack and interception previews, missions, promotions, upgrades, the per-unit action reads.

    A part of harness.game.Game (see harness/game_parts/__init__.py); `self` is the whole Game."""

    # ------------------------------------------------------------ actions
    def select_unit(self, unit_id: int, pid: int | None = None, look_at: bool = False) -> dict:
        """Select a unit. Camera pan is opt-in: UI.LookAt has flipped the live map into 2D."""
        look = "UI.LookAt(u:GetPlot(), 0)" if look_at else "-- camera pan skipped"
        return self.q(f"""
            if Game.GetActivePlayer() ~= {self._pid(pid)} then return {{ok=false, err="this seat is not active"}} end
            local u = Players[{self._pid(pid)}]:GetUnitByID({unit_id})
            if not u then return {{ok=false, err="no such unit"}} end
            UI.SelectUnit(u); {look}
            return {{ok=true}}""")

    def move_unit(self, unit_id: int, x: int, y: int, pid: int | None = None, settle_timeout: float = 1.0) -> dict:
        """move-to; when a visible enemy stands on the destination the move is a melee attack, and the
        result carries `attack`: both sides' hp before/after and who died (the unit's x/y do not change
        on an attack unless it kills and advances, so a bare move result read like nothing happened --
        live 2026-09-18)."""
        return self._with_attack_result(
            unit_id, x, y, lambda: self._move_unit(unit_id, x, y, pid, settle_timeout), pid)

    def _with_attack_result(self, unit_id: int, x: int, y: int, act, pid: int | None = None) -> dict:
        """Run `act()` and, when a visible enemy stands on (x, y), attach `attack`: both sides' hp
        before/after and who died.

        Shared by move_unit (a melee attack is a right-click onto the enemy) and unit_mission's
        move-shaped missions -- an **air strike is MISSION_MOVE_TO onto the target plot**, and until
        this was shared it returned only the bomber's own x/y/moves. Live t182: a Bomber killed an
        Inca Composite Bowman outright and took 11 damage, and the tool said
        `{"ok":true,"x":50,"y":24,"moves":0}` -- the pilot at the screen watches the damage numbers,
        the LLM had to wait for the next turn_digest to learn it had hit anything."""
        pre = self.q(f"return H.attack_before({unit_id}, {x}, {y}, {self._pid(pid)})")
        air = (pre or {}).get("air") if isinstance(pre, dict) else None
        if isinstance(pre, dict) and pre.get("attack") and air and not air.get("can_strike"):
            # An air unit does not walk toward a target: the engine answers an illegal strike by doing
            # nothing at all, so issuing it returned ok with both sides' hp unchanged. Live t184: a
            # Fighter at (49,19) sent at Cusco (42,23), nine plots away against a range of eight.
            rng = air.get("range")
            return {"ok": False, "err": "this air unit cannot strike that plot right now"
                                        + (f" (its range is {rng})" if rng else "")
                                        + "; available_unit_actions(unit_id).ranged_targets and "
                                          "unit_mission_targets list the plots it can actually reach",
                    "x": x, "y": y, "range": rng}
        seq0 = None
        if isinstance(pre, dict) and pre.get("attack") and air:
            try:
                seq0 = self.q("return H.event_seq")
            except TunerdError:
                seq0 = None
        r = act()
        if isinstance(pre, dict) and pre.get("attack") and r.get("ok"):
            time.sleep(0.3)
            if pre.get("city"):
                post = self.q(f"return H.city_attack_after({unit_id}, {x}, {y}, {self._pid(pid)})")
            else:
                post = self.q(f"return H.attack_after({unit_id}, {pre['def_player']}, {pre['def_unit']}, {self._pid(pid)})")
            r["attack"] = {"defender": pre.get("defender"), "defender_hp_before": pre.get("def_hp"),
                           "my_hp_before": pre.get("my_hp"), **(post if isinstance(post, dict) else {})}
            if air:
                self._attach_interception(r["attack"], seq0, pre, unit_id, x, y, pid)
            dtype = (pre.get("defender") or {}).get("unit")
            if r["attack"].get("defender_killed") and dtype:
                new_id = self.q(f"return H.captured_at({x}, {y}, {lua_str(str(dtype))}, {self._pid(pid)})")
                if isinstance(new_id, int):
                    r["attack"].pop("defender_killed", None)
                    r["attack"]["captured"] = True
                    r["attack"]["captured_unit_id"] = new_id
            # A target two plots away is walked toward first; when the moves run out on the way nobody
            # fought, and unchanged hp on both sides read like a fight both survived (live t327).
            a = r["attack"]
            if r.get("arrived") is False and a.get("def_hp") == a.get("defender_hp_before") and a.get("my_hp") == a.get("my_hp_before"):
                r["attack"] = {"happened": False, "defender": a.get("defender"),
                               "note": "moves ran out before reaching the target: no combat this turn. The standing "
                                       "order is dropped at turn start (an enemy is on the destination); move_unit "
                                       "onto it again next turn to attack"}
        return r

    def _attach_interception(self, a: dict, seq0, pre: dict, unit_id: int, x: int, y: int, pid: int | None = None) -> None:
        """An air strike can be intercepted on the way in. The pilot sees the interceptor fire and the damage
        it did; the result only said my_hp / my_unit_killed, which read as if the strike itself had gone wrong
        (live 2026-09-24: a Bomber lost to an AA gun). The engine's banner for a strike is just "Your Bomber
        bombarded an enemy Infantry! (87 damage)" -- no interception line -- so the interception is read the
        way the stock panel counts it: a visible interceptor that fired is out of interceptions for the turn
        and drops out of GetInterceptorCount (1 before, 0 after, live). The unit the engine would send up is
        named when it was in sight before the strike. When the aircraft died another of ours asks; failing
        that, a dead aircraft beside an untouched target still means it never got to strike. Banner texts
        that do name an interception ("was intercepted by" / "was shot down by") are honoured too."""
        before = pre.get("interception") if isinstance(pre.get("interception"), dict) else {}
        after: dict = {}
        try:
            after = self.q(f"return H.interception_after({unit_id}, {x}, {y}, {pre.get('def_player', -1)}, "
                           f"{pre.get('def_unit', -1)}, {self._pid(pid)})") or {}
        except TunerdError:
            after = {}
        if isinstance(before.get("count"), int):
            a["visible_interceptors_before"] = before["count"]
        fired = (isinstance(before.get("count"), int) and isinstance(after.get("count"), int)
                 and after["count"] < before["count"])
        texts: list = []
        if isinstance(seq0, int):
            try:
                texts = self.q(f"return H.alerts_since({seq0}, {self._pid(pid)})") or []
            except TunerdError:
                texts = []
        hits = [t for t in texts if isinstance(t, str) and ("was intercepted by" in t or "was shot down by" in t)]
        unhurt = (a.get("def_hp") is not None and a.get("def_hp") == a.get("defender_hp_before")
                  and not a.get("defender_killed"))
        killed_on_the_way = bool(a.get("my_unit_killed") and unhurt)
        if not (fired or hits or killed_on_the_way):
            return
        a["intercepted"] = True
        if isinstance(before.get("best"), dict):
            a["interceptor"] = {k: v for k, v in before["best"].items() if k != "player"}
        elif hits:
            m = re.search(r"by an enemy (.+?)!", hits[0])
            if m:
                a["interceptor"] = {"unit": m.group(1)}
        if hits:
            a["interception"] = hits[0] if len(hits) == 1 else hits
        if a.get("my_unit_killed"):
            a["shot_down"] = True
            if unhurt:
                a["note"] = "shot down by an interceptor before it could strike: the target is unhurt"
            else:
                a["note"] = ("intercepted on the way in and destroyed: the interception and the target's air defence "
                             "together used up its hp; the strike still landed (see def_hp)")
        else:
            a["note"] = ("intercepted on the way in and still struck; my_hp includes the interception damage, "
                         "which the preview's expected_damage_taken excluded")

    def _move_unit(self, unit_id: int, x: int, y: int, pid: int | None = None, settle_timeout: float = 1.0) -> dict:
        """Issue a move-to for a unit through the game's network path (selection list +
        GAMEMESSAGE_PUSH_MISSION, see harness/lua/runtime/helpers.lua net_unit_message).

        The order is applied on a later game update -- the unit's x/y read back in the same Lua
        call is still the pre-move plot -- so poll briefly for GetX/GetY or MovesLeft to change
        before returning. If the engine has not advanced within the timeout, report the pre-move
        reading honestly."""
        r = self._order(f"return H.move_unit({unit_id}, {x}, {y}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        deadline = time.monotonic() + settle_timeout
        cur = r
        while time.monotonic() < deadline:
            time.sleep(0.15)
            # reveal=true: `revealed` is what the move showed (new plots, units/cities that came into sight;
            # count 0 means nothing new), so "move and see what is there" needs no second read.
            cur = self.q(f"return H.unit_pos({unit_id}, {self._pid(pid)}, true)")
            if not cur.get("ok"):
                return cur
            if (cur["x"], cur["y"]) != (r["x"], r["y"]) or cur["moves"] != r["moves"]:
                # Say whether it got there: activity MISSION alone left "moved (24,23)->(24,29), asked for
                # (25,30)" to be worked out by the caller (live t325).
                cur["arrived"] = (cur["x"], cur["y"]) == (x, y)
                if not cur["arrived"]:
                    cur["destination"] = {"x": x, "y": y}
                    if cur.get("activity") == 6:
                        cur["note"] = "still on its way: the order carries on next turn (move_unit again to change it)"
                elif r.get("swap_candidates"):
                    # One of ours stood on the destination: if it is now on the plot we left, the
                    # engine swapped the two (live t252, Workers at Goshute). Say so -- the other
                    # unit moved too, and spent its moves doing it.
                    ids = ", ".join(str(c["id"]) for c in r["swap_candidates"] if isinstance(c, dict) and "id" in c)
                    sw = self.q(f"return H.swapped_unit({{{ids}}}, {r['x']}, {r['y']}, {self._pid(pid)})")
                    if isinstance(sw, dict) and sw.get("unit"):
                        cur["swapped_with"] = sw["unit"]
                        cur["note"] = (f"swapped places with {sw['unit'].get('type')} {sw['unit'].get('id')}, "
                                       f"which is now at ({r['x']},{r['y']}) with {sw['unit'].get('moves')} moves")
                # The loss roster is snapshotted at turn start/end; a unit we moved and then lost during our own
                # turn would otherwise be placed where the turn began (live S1 t267). Refresh it here, cheaply.
                try:
                    self.q(f"local u = Players[{self._pid(pid)}]:GetUnitByID({unit_id}); if u then H.note_unit(u, {self._pid(pid)}) end; return true")
                except TunerdError:
                    pass
                return cur
        # Nothing changed within settle_timeout. A unit with no moves left keeps the order queued for
        # next turn (activity MISSION); otherwise the engine dropped it silently -- no path to that
        # plot (unexplored/impassable terrain in the way, another civ's closed borders, a unit in the
        # way) -- and reporting ok:true here sent callers on with a unit that never moved (live t252).
        if cur.get("ok") and (cur.get("activity") == 6 or (r.get("moves") or 0) <= 0):
            cur.pop("revealed", None)   # it has not moved yet: nothing was shown
            cur["queued"] = True
            # #37: say where it is going; the next turn_status repeats it under todo.ongoing.
            cur["going_to"] = {"x": int(x), "y": int(y)}
            cur["note"] = (cur.get("note") + "; " if cur.get("note") else "") + \
                "standing move: resumes at the start of each of my turns until the unit arrives (todo.ongoing)"
            return cur
        out = {"ok": False, "err": "unit did not move: the engine found no path to that plot (unexplored or impassable "
                                   "terrain in the way, a closed border, or a unit blocking it); try a nearer plot",
               "x": r.get("x"), "y": r.get("y"), "moves": r.get("moves")}
        # H.move_unit already stored this destination as a standing order; a refused move must not leave it for
        # resume_moves to re-push next turn (live t76: a Worker refused onto another Worker's plot kept (48,15)).
        try:
            # Keyed per seat since the hotseat fix (H.pm_key), not by the bare id: the old form cleared nothing
            # and the refused destination came back as going_to / a resumed order the next turn.
            self.q(f"H.pending_moves[H.pm_key({int(unit_id)}, {self._pid(pid)})] = nil return true")
        except TunerdError:
            pass
        try:
            mine = self._unit_rows(pid)
            me = next((u for u in mine if u.get("id") == unit_id), None)
            hint = (me and self._blocker_hint(me, x, y, mine)) or self._foreign_occupant_hint(x, y)
            if hint:
                out["err"] = "unit did not move: " + hint
        except TunerdError:
            pass
        return out

    def _unit_rows(self, pid: int | None = None) -> list[dict]:
        """units() filtered to well-formed rows (hint helpers must never break the call they decorate)."""
        rows = self.units(pid)
        return [u for u in rows if isinstance(u, dict)] if isinstance(rows, list) else []

    def _foreign_occupant_hint(self, x: int, y: int) -> str | None:
        """Another civ's unit visible on the destination (map_window's own visibility rules). Live t414: a
        Missionary's path to a plot next to Quebec City failed turn after turn -- the city-state's Infantry and
        Anti-Aircraft Gun stood on both target plots, and the error said only 'no path'."""
        try:
            w = self.plots_around(x, y, 0)
        except TunerdError:
            return None
        plots = w.get("plots", w) if isinstance(w, dict) else w
        for p in plots if isinstance(plots, list) else []:
            if isinstance(p, dict) and (p.get("x"), p.get("y")) == (x, y):
                others = [u for u in p.get("units") or [] if isinstance(u, dict) and u.get("owner") != self.seat]
                if others:
                    names = ", ".join(str(u.get("type")) for u in others)
                    return f"({x},{y}) is occupied by another civ's unit ({names}); pick an adjacent free plot"
        return None

    @staticmethod
    def _blocker_hint(me: dict, x: int, y: int, mine) -> str | None:
        """One unit per plot per class (combat / civilian) and domain, cities included (live t333: a Worker on
        Shanghai's plot kept a Missionary out). Name my own blocker when there is one."""
        cls = lambda u: (u.get("strength") or 0) > 0
        for u in mine:
            # caravans/cargo ships on a route are automated and pass through; an idle one home in a city does
            # block (live t449: a returned Caravan on Beijing's plot kept an SS Booster out of the capital)
            if (u.get("id") != me.get("id") and (u.get("x"), u.get("y")) == (x, y) and not u.get("automated")
                    and cls(u) == cls(me) and u.get("domain") == me.get("domain")):
                trade = u.get("type") in ("CARAVAN", "CARGO_SHIP")
                return (f"your {u.get('type')} (unit {u.get('id')}) already holds ({x},{y}) and only one "
                        f"{'combat' if cls(me) else 'civilian'} unit fits per plot: "
                        + ("send it on a trade route (establish_trade_route) or move it" if trade else
                           "move it, or pick an adjacent plot")
                        + (" (a missionary/prophet can spread from next to the city)" if me.get("type") in
                           ("MISSIONARY", "PROPHET", "INQUISITOR") else ""))
        return None

    def unit_mission(self, unit_id: int, mission: str, x: int = -1, y: int = -1, data2: int = 0,
                     build: str | None = None, pid: int | None = None) -> dict:
        """See _unit_mission. A mission the engine calls illegal comes back with the unit's legal ones
        (live t328: MISSION_FORTIFY on a Cannon -- siege units cannot fortify, MISSION_SLEEP is the answer)."""
        # Great-person missions whose payoff is an empire number: measure it (live t333: a political treatise
        # answered only consumed:true; culture had gone 1218 -> 1874).
        gp_stat = {"MISSION_GIVE_POLICIES": "culture", "MISSION_TRADE": "gold",
                   "MISSION_GOLDEN_AGE": "golden_age_turns",
                   # live t379: a 5106-science bulb took Computers from 9 turns to 2 -- say so
                   "MISSION_DISCOVER": "research_turns_left"}.get(mission)
        before = research_before = None
        if gp_stat:
            try:
                summ0 = self.summary(pid)
                before, research_before = summ0.get(gp_stat), summ0.get("research")
            except (TunerdError, AttributeError):
                before = None
        hurry0 = self._hurry_city_production(unit_id, None, pid) if mission == "MISSION_HURRY" else None
        pillage_gold0 = None
        pillage_plot0 = None
        if mission in ("MISSION_PILLAGE", "MISSION_PILLAGE_ROUTE"):
            # The engine accepts a pillage order from a unit with no moves left and then does nothing:
            # the plot stays improved, the unit goes to HOLD, and the old reply said ok with
            # gold_gained 0 (live 2026-09-24 t219: Infantry walked two tiles onto a quarry and "pillaged"
            # it). The stock button is greyed at 0 moves; refuse the same way and say when to retry.
            try:
                pillage_plot0 = self.q(f"local u = Players[{self._pid(pid)}]:GetUnitByID({int(unit_id)}) "
                                       f"if not u then return nil end local p = u:GetPlot() "
                                       f"return {{moves = u:MovesLeft(), improvement = p:IsImprovementPillaged(), "
                                       f"route = p:IsRoutePillaged(), x = p:GetX(), y = p:GetY()}}")
            except (TunerdError, AttributeError):
                pillage_plot0 = None
            if isinstance(pillage_plot0, dict) and (pillage_plot0.get("moves") or 0) <= 0:
                return {"ok": False, "err": "the unit has no moves left this turn, so the engine would drop the pillage "
                                            "order; pillage next turn (or before moving)",
                        "x": pillage_plot0.get("x"), "y": pillage_plot0.get("y"), "moves": 0}
            try:
                pillage_gold0 = self.summary(pid).get("gold")
            except (TunerdError, AttributeError):
                pillage_gold0 = None
        r = self._unit_mission(unit_id, mission, x, y, data2, build, pid)
        if hurry0 and isinstance(r, dict) and r.get("ok"):
            # live t437: an Engineer hurrying Hubble answered only consumed:true
            after = self._hurry_city_production(None, hurry0.get("city_id"), pid)
            if after:
                r["effect"] = {"city": hurry0.get("city"), "production": hurry0.get("production"),
                               "turns_before": hurry0.get("turns"), "turns_after": after.get("turns"),
                               "progress_before": hurry0.get("progress"), "progress_after": after.get("progress"),
                               "cost": after.get("cost")}
                if after.get("production") != hurry0.get("production"):
                    r["effect"]["completed"] = hurry0.get("production")
                    r["effect"]["now_building"] = after.get("production")
        if gp_stat and before is not None and isinstance(r, dict) and r.get("ok"):
            try:
                summ = self.summary(pid)
                r["effect"] = {gp_stat + "_before": before, gp_stat + "_after": summ.get(gp_stat)}
                # A bulb that finishes the current tech moves research on: turns_left 6 -> 8 read like a loss
                # (live t419, Penicillin done, Ecology next). Name the research on both sides.
                if gp_stat == "research_turns_left":
                    r["effect"]["research_before"] = research_before
                    r["effect"]["research_after"] = summ.get("research")
            except (TunerdError, AttributeError):
                pass
        if mission in ("MISSION_PILLAGE", "MISSION_PILLAGE_ROUTE") and isinstance(r, dict) and r.get("ok") \
                and pillage_gold0 is not None:
            # Stock combat banner shows the gold; digest used to be the only place it landed.
            try:
                gold1 = pillage_gold0
                for _ in range(8):
                    time.sleep(0.25)
                    gold1 = self.summary(pid).get("gold")
                    if gold1 != pillage_gold0:
                        break
                r["effect"] = {"gold_before": pillage_gold0, "gold_after": gold1,
                               "gold_gained": (gold1 or 0) - (pillage_gold0 or 0)}
                # Say whether the plot actually changed, not just the treasury: a pillaged route, farm or
                # camp yields no gold at all, and the gold line alone read like "nothing happened".
                if isinstance(pillage_plot0, dict):
                    after = self.q(f"local p = Map.GetPlot({int(pillage_plot0['x'])}, {int(pillage_plot0['y'])}) "
                                   f"return {{improvement = p:IsImprovementPillaged(), route = p:IsRoutePillaged()}}") or {}
                    r["effect"]["improvement_pillaged"] = bool(after.get("improvement")) and not pillage_plot0.get("improvement")
                    r["effect"]["route_pillaged"] = bool(after.get("route")) and not pillage_plot0.get("route")
                    if not (r["effect"]["improvement_pillaged"] or r["effect"]["route_pillaged"]):
                        r["effect"]["note"] = "nothing on the plot was pillaged"
            except (TunerdError, AttributeError):
                pass
        if mission == "MISSION_SPACESHIP" and isinstance(r, dict) and r.get("ok"):
            # Live t424: adding the Cockpit answered only consumed:true -- show the ship after.
            try:
                ship = self.spaceship_status(pid)
                r["spaceship"] = {p["part"]: f"{p['in_ship']}/{p['needed']}" for p in ship.get("parts", [])}
                if ship.get("complete"):
                    # Live t502: the last Booster completed the ship and the engine went straight to
                    # GAMESTATE_OVER, where its delayed removal of the part unit never runs: the read-back found
                    # the unit standing in the capital with its 2 moves and the reply carried no `consumed`.
                    # The part is spent all the same; say what the order did instead of where the unit stands.
                    for k in ("x", "y", "moves", "activity", "activity_name", "buildtype"):
                        r.pop(k, None)
                    r["consumed"] = True
                    r["ship_complete"] = True
                    if ship.get("game_over"):
                        r["game_over"] = True
                        r["victory"] = "science"
                        r["note"] = ("the ship is complete: Science Victory, the game is over (turn_status carries the "
                                     "game_over gate; exit_to_main_menu leaves it)")
            except (TunerdError, AttributeError, KeyError):
                pass
        if isinstance(r, dict) and r.get("err") == "action is not currently legal":
            if mission == "MISSION_RANGE_ATTACK":
                # Live t193: a Keshik rode three plots to shoot and got the bare refusal -- the plot was in range
                # by count but not in its line of fire. Say which test failed, so the next order is the right one.
                why = self._range_attack_reason(unit_id, x, y, pid)
                if why:
                    r["reason"] = why
            try:
                acts = self.available_unit_actions(unit_id, pid)
                r["legal_missions"] = [a.get("mission") or a.get("type") for a in acts.get("actions", [])]
                # Live t330: a freshly built Infantry in a garrisoned city could only move/swap -- two combat
                # units on one plot until one leaves. Say so instead of leaving the caller to guess.
                mine = self._unit_rows(pid)
                me = next((u for u in mine if u.get("id") == unit_id), None)
                if me and (me.get("strength") or 0) > 0:
                    mates = [u["id"] for u in mine if u.get("id") != unit_id and (u.get("strength") or 0) > 0
                             and (u.get("x"), u.get("y")) == (me.get("x"), me.get("y")) and u.get("domain") == me.get("domain")]
                    if mates:
                        r["reason"] = (f"stacked with your combat unit(s) {mates} on ({me['x']},{me['y']}): only one may stay; "
                                       f"move this one (or that one) to another plot first")
            except TunerdError:
                pass
        return r

    def _range_attack_reason(self, unit_id: int, x: int, y: int, pid: int | None = None) -> str | None:
        """Why MISSION_RANGE_ATTACK on (x, y) is not legal for this unit: the engine's own tests in order --
        no ranged attack, no moves, already attacked, a siege unit not set up, the plot out of range, out of the
        unit's line of fire (CvPlot::canSeePlot with the attack range, the test tactical_view's fire_los shows),
        or no visible enemy there. None when the probe cannot run (the refusal then stays bare)."""
        try:
            f = self.q(f"""
                local p = Players[{self._pid(pid)}]; local u = p:GetUnitByID({int(unit_id)})
                if not u then return nil end
                local here = u:GetPlot(); local q = Map.GetPlot({int(x)}, {int(y)})
                local out = {{x = here:GetX(), y = here:GetY(), moves = u:MovesLeft(), range = 0, plot = q ~= nil}}
                pcall(function() out.range = u:Range() or 0 end)
                if not q then return out end
                out.distance = math.floor(Map.PlotDistance(here:GetX(), here:GetY(), {int(x)}, {int(y)}))
                pcall(function() out.out_of_attacks = u:IsOutOfAttacks() and true or false end)
                pcall(function() out.needs_setup = u:IsMustSetUpToRangedAttack() and not u:IsSetUpForRangedAttack() end)
                pcall(function() out.ignores_los = u:IsRangeAttackIgnoreLOS() and true or false end)
                if out.range > 0 and here.CanSeePlot then
                  pcall(function() out.los = here:CanSeePlot(q, u:GetTeam(), out.range, -1) and true or false end)
                end
                pcall(function() out.visible = q:IsVisible(u:GetTeam(), false) and true or false end)
                local enemy = false
                local team = Teams[u:GetTeam()]
                for i = 0, q:GetNumUnits() - 1 do
                  local v = q:GetUnit(i)
                  if v and team:IsAtWar(v:GetTeam()) then enemy = true end
                end
                pcall(function() local c = q:GetPlotCity(); if c and team:IsAtWar(c:GetTeam()) then enemy = true end end)
                out.enemy = enemy
                return out""")
        except (TunerdError, AttributeError):
            return None
        if not isinstance(f, dict):
            return None
        rng = f.get("range") or 0
        if rng <= 0:
            return "this unit has no ranged attack (a melee attack is move_unit onto the enemy's plot)"
        if not f.get("plot"):
            return f"({x},{y}) is not a plot on this map"
        if (f.get("moves") or 0) <= 0:
            return "the unit has no moves left this turn"
        if f.get("out_of_attacks"):
            return "the unit has already attacked this turn"
        if f.get("needs_setup"):
            return "a siege unit must set up before it fires (MISSION_SETUP_FOR_RANGED_ATTACK), which takes a turn"
        d = f.get("distance")
        if isinstance(d, int) and d > rng:
            return (f"({x},{y}) is {d} plots from the unit at ({f.get('x')},{f.get('y')}) and its range is {rng}: "
                    "move within range first (tactical_view lists the plots in its fire_los)")
        if f.get("los") is False and not f.get("ignores_los"):
            return (f"({x},{y}) is within range {rng} but not in the unit's line of fire from ({f.get('x')},{f.get('y')}): "
                    "hills or forest in between block the shot (tactical_view's in_fire_los); fire from another plot")
        if not f.get("visible"):
            return f"({x},{y}) is not visible to the unit"
        if not f.get("enemy"):
            return f"no enemy unit or city on ({x},{y}) (a target must be at war with you and visible)"
        return None

    def _hurry_city_production(self, unit_id: int | None, city_id: int | None, pid: int | None = None) -> dict | None:
        """Production of the city on `unit_id`'s plot (or city `city_id`): what it builds, turns, stored hammers."""
        sel = (f"local u = p:GetUnitByID({int(unit_id)}); if not u then return {{}} end; "
               f"local c = u:GetPlot() and u:GetPlot():GetPlotCity()") if unit_id is not None else \
              f"local c = p:GetCityByID({int(city_id)})"
        try:
            r = self.q(f"""
                local p = Players[{self._pid(pid)}]
                {sel}
                if not c or c:GetOwner() ~= p:GetID() then return {{}} end
                return {{city_id=c:GetID(), city=c:GetName(), production=H.L(c:GetProductionNameKey()),
                         turns=c:GetProductionTurnsLeft(), progress=c:GetProduction(), cost=c:GetProductionNeeded()}}""")
        except TunerdError:
            return None
        return r if isinstance(r, dict) and r.get("city_id") is not None else None

    def _unit_mission(self, unit_id: int, mission: str, x: int = -1, y: int = -1, data2: int = 0,
                      build: str | None = None, pid: int | None = None) -> dict:
        """Push a mission by name through the game's network path (selection list +
        GAMEMESSAGE_PUSH_MISSION, see harness/lua/runtime/helpers.lua net_unit_message).

        e.g. MISSION_FOUND, MISSION_FORTIFY, MISSION_SLEEP, MISSION_SKIP, MISSION_MOVE_TO (x, y).
        `data2` is accepted for call-site compatibility and ignored: extra mission data is `build`
        for MISSION_BUILD, or x/y for movement-shaped missions.

        MISSION_BUILD: pass the improvement via `build=` (e.g. build="BUILD_FARM"), NOT x/y --
        the BuildTypes id travels as the mission's first data word. The build always applies to the
        unit's own tile.

        The message does not report whether the mission stuck, and it is applied on a later game
        update. For MISSION_BUILD this polls until GetBuildType() shows the build (or the plot has
        already changed for an instant build) before reporting success."""
        _ = data2
        build_arg = lua_str(build) if build else "nil"
        push = lambda: self._order(
            f"return H.unit_mission({unit_id}, {lua_str(mission)}, {x}, {y}, {build_arg}, {self._pid(pid)})"
        )
        religious = mission in ("MISSION_SPREAD_RELIGION", "MISSION_REMOVE_HERESY")
        before = self.q(f"return H.religion_target({unit_id}, {self._pid(pid)})") if religious else None
        if religious and before.get("ok") and not before.get("city"):
            return {"ok": False, "err": "no city on or adjacent to the unit's plot; move next to (or into) the target city first"}
        # A Great Person is a once-in-many-turns resource and MISSION_CREATE_GREAT_WORK answered with a
        # bare {ok, consumed}: which work, in which city's which building, was left for the caller to
        # find by diffing culture_works (live t215: "Martin Fierro" went into Te-Moak's Amphitheater).
        # The game shows a popup naming it. Snapshot the slots and report the one that filled.
        works_before = (self.q(f"return H.great_work_index({self._pid(pid)})") or {}
                        ) if mission == "MISSION_CREATE_GREAT_WORK" else None
        found_pre = None
        if mission == "MISSION_FOUND":
            # PushMission(MISSION_FOUND) "succeeds" with no moves left and no city (live t283), so check
            # first and confirm the city afterwards instead of trusting the accept.
            found_pre = self.q(f"return H.found_check({unit_id}, -1, -1, {self._pid(pid)})")
            if found_pre.get("ok") and found_pre.get("unit_exists"):
                if found_pre.get("city"):
                    return {"ok": False, "err": "there is already a city on this plot"}
                if (found_pre.get("moves") or 0) <= 0:
                    return {"ok": False, "err": "the settler has no moves left this turn (a standing move just spent "
                                                "them); MISSION_FOUND needs at least one move -- found next turn",
                            "x": found_pre.get("x"), "y": found_pre.get("y"), "moves": 0}
                if not found_pre.get("can_found"):
                    return {"ok": False, "err": "cannot found a city on this plot (too close to another city, "
                                                "water, or foreign territory); move first",
                            "x": found_pre.get("x"), "y": found_pre.get("y")}
        if mission in ("MISSION_RANGE_ATTACK", "MISSION_NUKE", "MISSION_PARADROP") and x >= 0 and y >= 0:
            r = self._with_target_result(x, y, push, pid)
        elif mission in ("MISSION_MOVE_TO", "MISSION_MOVE_UNIT_TO") and x >= 0 and y >= 0:
            # An air strike is issued exactly like a move onto the target plot, so this is the
            # attack path for every air unit. attack_before answers "no enemy there" for an
            # ordinary move, and then this costs nothing extra.
            r = self._with_attack_result(unit_id, x, y, push, pid)
        else:
            r = push()
        if not r.get("ok"):
            return r
        if r.get("automate_pending") is not None:
            if deferring_after_reads():
                return {"ok": True, "after_pending": {"unit_id": unit_id, "mission": mission, "kind": "automate"}}
            # The command lands on the next game frame (live t151, six pushes: automated on the first read every
            # time, 43-60 ms after the push), so the first read follows at once and polling is the fallback.
            check = lambda: self.q(f"return H.automate_check({unit_id}, {self._pid(pid)})")
            chk = check()
            if not _automate_landed(chk):
                chk, _ = self._settle(check, _automate_landed, timeout=3.0, poll=0.1, initial=chk)
            return self._apply_automate_after(mission, chk)
        if r.get("command_pending"):
            # Verify: a delete must make the unit disappear; other commands report the unit's state after.
            for _ in range(12):
                time.sleep(0.25)
                pos = self.q(f"return H.unit_pos({unit_id}, {self._pid(pid)})")
                gone = not (isinstance(pos, dict) and pos.get("ok"))
                if mission == "COMMAND_DELETE":
                    if gone:
                        return {"ok": True, "command": mission, "unit_gone": True}
                elif not gone:
                    return {"ok": True, "command": mission, **{k: v for k, v in pos.items() if k != "ok"}}
            return {"ok": False, "err": f"{mission} was sent but no effect was seen within 3 s"}
        if build and r.get("pending"):
            before = r.pop("before", None)
            r.pop("pending", None)
            chk = None
            for _ in range(12):
                time.sleep(0.25)
                chk = self.q(f"return H.build_check({unit_id}, {r.get('x', -1)}, {r.get('y', -1)}, "
                             f"{lua_table(before) if before else 'nil'}, {self._pid(pid)})")
                if chk.get("started") or chk.get("completed"):
                    break
            if chk and chk.get("completed"):
                done = {"ok": True, "buildtype": -1, "completed": True, "moves": chk.get("moves")}
                for k in ("improvement", "claimed_plots", "unit_consumed"):
                    if chk.get(k) is not None:
                        done[k] = chk[k]
                if chk.get("claimed_plots"):
                    # Naming the civ we took tiles from is the part a human sees as a diplomatic
                    # incident, not just a border move.
                    taken = sorted({r.get("taken_from_name") or str(r.get("taken_from"))
                                    for r in chk["claimed_plots"]
                                    if isinstance(r, dict) and r.get("taken_from") is not None})
                    done["note"] = (f"claimed {len(chk['claimed_plots'])} tile(s)"
                                    + (", taken from " + ", ".join(taken) if taken else ""))
                return done
            if chk and chk.get("started"):
                out = {"ok": True, "buildtype": chk.get("buildtype"), "build": chk.get("build"),
                       "turns_left": chk.get("turns_left"), "moves": chk.get("moves")}
                if r.get("build_id") is not None and chk.get("buildtype") != r.get("build_id"):
                    # The engine clears a feature the ordered improvement removes as its own build first, then
                    # carries on with the order (live: Spices plantation on marsh t71 -> REMOVE_MARSH, finished
                    # as a plantation t79 without a new order; Silk/forest-hill mine t79 -> REMOVE_FOREST).
                    if str(chk.get("build") or "").startswith("BUILD_REMOVE_"):
                        out["note"] = (f"{chk.get('build')} runs first ({chk.get('turns_left')} turns); the ordered "
                                       "build follows on its own, no new order needed")
                    else:
                        out["note"] = (f"the unit is working on {chk.get('build')}, not the ordered build "
                                       f"(id {r.get('build_id')})")
                return out
            return {"ok": False, "err": "MISSION_BUILD was sent but the unit did not start the build within 3 s "
                                        "(GetBuildType still -1 and the plot unchanged)"}
        if works_before is not None:
            for _ in range(8):
                time.sleep(0.25)
                after = self.q(f"return H.great_work_index({self._pid(pid)})") or {}
                new = [w for k, w in after.items() if k not in works_before]
                if new:
                    r["great_work"] = new[0]
                    return r
            r["note"] = ("no new great work appeared; the slot may have been taken this turn -- "
                         "culture_works shows every slot and which are empty")
            return r
        if found_pre is not None and found_pre.get("unit_exists"):
            fx, fy = found_pre.get("x", -1), found_pre.get("y", -1)
            post = None
            for _ in range(8):
                time.sleep(0.25)
                post = self.q(f"return H.found_check({unit_id}, {fx}, {fy}, {self._pid(pid)})")
                if post.get("city"):
                    break
            if post and post.get("city"):
                r["city"] = post["city"]
                r["consumed"] = not post.get("unit_exists")
            else:
                r["ok"] = False
                r["err"] = "MISSION_FOUND was accepted but no city appeared on the settler's plot"
            return r
        if religious and before.get("ok"):
            # Measure the conversion instead of trusting the accept: followers/majority in the target
            # city before vs after, and how many spreads the unit has left (0 = it is consumed).
            time.sleep(0.3)
            after = self.q(f"return H.religion_target({unit_id}, {self._pid(pid)})")
            if not after.get("ok"):
                # Last charge consumed the unit: re-read the same city by plot instead.
                after = self.q(f"return H.city_religion_at({before.get('x', -1)}, {before.get('y', -1)}, "
                               f"{before.get('unit_religion', -1)}, {self._pid(pid)})")
                if after.get("ok"):
                    after["spreads_left"] = 0
                r["consumed"] = True
            eff = spread_effects(before, after)
            if eff.get("gained_followers") is False and (after.get("spreads_left") == before.get("spreads_left")):
                r["ok"] = False
                r["err"] = "mission accepted but nothing changed (no charge used, no new followers) -- is the unit adjacent to or inside the city, with moves left?"
            r["effects"] = eff
        if build is not None:
            if r.get("buildtype", -1) != -1 or r.get("completed"):
                return r
            time.sleep(0.3)
            chk = self.q(f"return H.unit_pos({unit_id}, {self._pid(pid)})")
            if chk.get("ok") and chk.get("buildtype", -1) == -1:
                return {"ok": False, "err": "mission accepted but did not start a build (bad build type for this tile/unit?)"}
            return r
        # Report the unit's state after the mission so the caller need not re-read units(): a Great
        # Person mission (MISSION_GIVE_POLICIES / CREATE_GREAT_WORK / BUILD_ACADEMY...) consumes the
        # unit, and otherwise moves/position tell whether the order actually took. Inside a batch the read
        # is deferred to one query for every order of the batch (read_after_batch).
        if deferring_after_reads():
            r["after_pending"] = {"unit_id": unit_id, "mission": mission, "kind": "pos"}
            return r
        time.sleep(AFTER_READ_DELAY)
        after = self.q(f"return H.unit_pos({unit_id}, {self._pid(pid)})")
        return self._apply_unit_after(r, mission, after)

    def _apply_unit_after(self, r: dict, mission: str, after: dict) -> dict:
        """Fold a unit_pos reading taken after `mission` into its result `r`."""
        if isinstance(after, dict) and after.get("ok"):
            r.update({k: after[k] for k in ("x", "y", "moves", "activity", "activity_name") if k in after})
            # A route the engine drops ("Route to cancelled!": no path, or nothing left to build on it) leaves the
            # worker AWAKE; the bare ok:true read like it was on its way (live t96, Agaidika -> capital).
            if mission == "MISSION_ROUTE_TO" and after.get("activity_name") == "AWAKE" and after.get("buildtype", -1) == -1:
                r["ok"] = False
                r["err"] = ("the engine dropped the route (no path to that plot, or no road left to build on the way); "
                            "move the worker onto each missing plot and use BUILD_ROAD")
            # A sleep or fortify given to a unit with no moves left is recorded as HOLD (this turn's skip), not as
            # SLEEP_OR_FORTIFY: the unit is back in todo next turn (live t182-t190, Venice's idle workers slept at
            # 0 moves woke every turn; slept with moves left they stayed asleep).
            if mission in ("MISSION_SLEEP", "MISSION_FORTIFY", "MISSION_ALERT") and after.get("activity_name") == "HOLD":
                r["note"] = ("recorded as HOLD, a skip for this turn only (the unit had no moves left): it wakes next "
                             "turn; give the order again then, with moves left, for a lasting sleep")
            # A one-shot Great Person mission spends the unit; one that leaves it standing did nothing. The
            # engine accepts the push and records HOLD, like a pillage at 0 moves (live t205: a Great Musician
            # moved onto Shoshone land with its last move, MISSION_ONE_SHOT_TOURISM answered ok, and the unit
            # was still there with the mission on offer -- no tourism happened).
            if mission in ONE_SHOT_GP_MISSIONS and r.get("ok", True):
                r["ok"] = False
                r["consumed"] = False
                moves = after.get("moves")
                why = ("it had no moves left this turn" if moves == 0 else
                       "the engine did not carry it out (not in a plot where it is legal, or the unit is busy)")
                r["err"] = (f"{mission} was sent but the unit still stands at ({after.get('x')}, {after.get('y')}) "
                            f"with {moves} moves: {why}; "
                            + ("give the mission again next turn before moving" if moves == 0 else
                               "check available_unit_actions(unit_id) and the unit's plot, then try again"))
        else:
            r["consumed"] = True
        return r

    @staticmethod
    def _apply_automate_after(mission: str, chk: dict) -> dict:
        """The result of an AUTOMATE_* order from the automate_check reading that followed it."""
        if _automate_landed(chk):
            return {"ok": True, **{k: v for k, v in chk.items() if k != "ok"}}
        return {"ok": False, "err": f"{mission} was sent but the unit is not automated after 3 s"}

    def read_after_batch(self, pending: list[dict], pid: int | None = None) -> list[dict]:
        """The read-backs a batch deferred (`after_pending` markers: unit_id, mission, kind), in one tuner trip:
        one unit_pos / automate_check per marker, in order. An automate that has not landed by then (the last
        order of the batch, pushed a moment ago) is re-read on its own until it has, up to 3 s."""
        if not pending:
            return []
        p = self._pid(pid)
        fn = {"automate": "H.automate_check", "pos": "H.unit_pos"}
        parts = [f"{fn.get(m.get('kind'), 'H.unit_pos')}({int(m['unit_id'])}, {p})" for m in pending]
        time.sleep(AFTER_READ_DELAY)
        rows = self.q("return {" + ", ".join(parts) + "}")
        rows = list(rows) if isinstance(rows, list) else []
        rows += [{}] * (len(pending) - len(rows))
        for i, m in enumerate(pending):
            if m.get("kind") == "automate" and not _automate_landed(rows[i]):
                rows[i], _ = self._settle(lambda uid=m["unit_id"]: self.q(f"return H.automate_check({int(uid)}, {p})"),
                                          _automate_landed, timeout=3.0, poll=0.1, initial=rows[i])
        return rows

    def apply_after(self, r: dict, marker: dict, after: dict) -> dict:
        """Finish a batch order's result `r` from the reading its marker asked for."""
        if marker.get("kind") == "automate":
            out = self._apply_automate_after(marker.get("mission", "AUTOMATE"), after if isinstance(after, dict) else {})
            r.pop("after_pending", None)
            r.update(out)
            return r
        r.pop("after_pending", None)
        return self._apply_unit_after(r, marker.get("mission", ""), after)

    def _with_target_result(self, x: int, y: int, act, pid: int | None = None, settle: float = 2.0) -> dict:
        """Run an attack `act()` against plot (x, y) and attach what happened to the target: `target_before`,
        `target_after` (units/city on the plot with hp), `damage_dealt`, `killed`. The engine applies the
        attack asynchronously (a net message), so this polls until the plot's occupants change or `settle`
        seconds pass -- an unchanged reading is reported as-is, never guessed at."""
        before = self.plot_units(x, y, pid)
        r = act()
        if not r.get("ok"):
            return r
        r["target_before"] = before
        after, _ = self._settle(lambda: self.plot_units(x, y, pid), lambda a: a != before, timeout=settle, initial=before)
        r["target_after"] = after
        bu = {u["id"]: u for u in before.get("units", [])}
        au = {u["id"]: u for u in after.get("units", [])}
        if bu:
            killed_rows = [u for i, u in bu.items() if i not in au and u.get("owner") != self._pid(pid)]
            killed = [u.get("type") for u in killed_rows]
            dmg = [bu[i]["hp"] - au[i]["hp"] for i in bu if i in au]
            if killed:
                r["killed"] = killed
                # A kill used to omit damage_dealt (city strike that finishes a unit). The
                # remaining hp on the vanished defender is what the combat banner shows.
                dmg.extend(u.get("hp") or 0 for u in killed_rows)
            if dmg:
                r["damage_dealt"] = max(dmg)
        if before.get("city") and after.get("city"):
            r["city_damage_dealt"] = before["city"]["hp"] - after["city"]["hp"]
        if after == before:
            r["note"] = "target unchanged after the attack settled; it may not have been visible, or the attack did not resolve"
        return r

    def choose_promotion(self, unit_id: int, promotion: str, pid: int | None = None) -> dict:
        """Pick a promotion for a unit with ENDTURN_BLOCKING_UNIT_PROMOTION, e.g. PROMOTION_SHOCK_1.
        Sent as the unit panel's DO_COMMAND; confirmed by polling the unit's level/promotion (<= 3 s)."""
        r = self._order(f"return H.choose_promotion({unit_id}, {lua_str(promotion)}, {self._pid(pid)})")
        if not r.get("ok") or not r.get("pending"):
            return r
        r.pop("pending", None)
        pr_id = r.pop("promotion_id", -1)
        chk = None
        for _ in range(12):
            time.sleep(0.25)
            chk = self.q(f"return H.promotion_check({unit_id}, {pr_id}, {self._pid(pid)})")
            if not chk.get("ok") or chk.get("has") or (chk.get("level") or 0) > (r.get("level_before") or 0):
                break
        if chk and chk.get("ok"):
            r.update({k: chk.get(k) for k in ("level", "has", "hp", "promotion_ready")})
        # PROMOTION_INSTA_HEAL is spent on the spot, never held: the level-up is the proof it applied
        # (live 2026-09-18: 42 -> 92 hp, level 2, reported as a failure).
        applied = bool(chk and (chk.get("has") or (chk.get("level") or 0) > (r.get("level_before") or 0)))
        if not applied:
            r["ok"] = False
            r["err"] = "COMMAND_PROMOTION was sent but the unit does not have the promotion after 3 s"
        return r

    def upgrade_unit(self, unit_id: int, pid: int | None = None) -> dict:
        """Upgrade a unit for gold along its upgrade path (Warrior -> Swordsman ...). The engine
        replaces the unit: the result's `unit_id` is the NEW id, `old_unit_id` the one passed in.
        Sent as the unit panel's DO_COMMAND; confirmed by polling the plot for the new unit (<= 3 s)."""
        r = self._order(f"return H.upgrade_unit({unit_id}, {self._pid(pid)})")
        if not r.get("ok") or not r.get("pending"):
            return r
        r.pop("pending", None)
        ut, old_type = r.pop("target_type_id", -1), r.pop("old_type_id", -1)
        chk = None
        for _ in range(12):
            time.sleep(0.25)
            chk = self.q(f"return H.upgrade_unit_check({unit_id}, {r.get('x', -1)}, {r.get('y', -1)}, {ut}, {old_type}, {self._pid(pid)})")
            if chk.get("unit_id") is not None:
                break
        if chk:
            r.update({"unit_id": chk.get("unit_id"), "type": chk.get("type"), "gold": chk.get("gold"),
                      "old_still_exists": chk.get("old_still_exists")})
        if not (chk and chk.get("unit_id") is not None):
            r["ok"] = False
            r["err"] = "COMMAND_UPGRADE was sent but no upgraded unit appeared on the plot within 3 s"
        return r

    def disband_unit(self, unit_id: int, pid: int | None = None) -> dict:
        """Disband a unit (COMMAND_DELETE). Irreversible; frees maintenance and strategic resources.
        The engine deletes the unit on its next tick, so the result is confirmed by polling (<= 3 s)."""
        r = self._order(f"return H.disband_unit({int(unit_id)}, {self._pid(pid)})")
        if not r.get("ok") or not r.get("pending"):
            return r
        before = r.pop("before", None)
        r.pop("pending", None)
        chk = None
        for _ in range(12):
            time.sleep(0.25)
            chk = self.q(f"return H.disband_unit_check({int(unit_id)}, {self._pid(pid)})")
            if chk.get("gone"):
                break
        after = {"units": chk.get("units"), "strategic": chk.get("strategic")} if chk else None
        r["ok"] = bool(chk and chk.get("gone"))
        if not r["ok"]:
            r["err"] = "COMMAND_DELETE was sent but the unit still exists after 3 s"
        r["effects"] = {"before": before, "after": after}
        return r

    def unit_mission_targets(self, unit_id: int, mission: str, offset: int = 0, limit: int = 100,
                             pid: int | None = None) -> dict:
        return self.q(f"return H.unit_mission_targets({int(unit_id)}, {lua_str(mission)}, {self._pid(pid)}, {int(offset)}, {int(limit)})")

    def available_unit_actions(self, unit_id: int, pid: int | None = None) -> dict:
        """Currently legal unit-panel actions for this unit (missions, builds, commands, promotions).

        Selection-free: uses CanStartMission/CanBuild/CanDoCommand so catalog reads do not
        UI.SelectUnit (that call flips the live 2D/3D map view).
        """
        return self.q(f"return H.available_unit_actions({unit_id}, {self._pid(pid)})")

    def todo_actions(self, unit_ids: list[int] | None = None, full: bool = False, pid: int | None = None,
                     detail: str | None = None, limit: int | None = None) -> dict:
        """Legal actions for many units in one read: every unit still needing orders plus every unit with a
        promotion waiting when `unit_ids` is empty, else exactly those. One tuner query instead of one per
        unit (live S1 t270: 38 units, one available_unit_actions round-trip each).

        `detail` (#35): "normal" (the default, the rows as before), "full" (= `full=True`: the computed help
        line on every action row) or "summary" (see `_summary_unit_row`: one short row per unit plus the exact
        arguments that fetch the rest). Every level is cut from the same one Lua read, so the facts and the
        tuner cost are identical; only the reply's size differs. `limit` returns the first N units (todo order)
        and lists the rest under `omitted` with the arguments that fetch them -- a unit is never dropped
        silently. Every reply carries `detail`, `n` (total) and `returned`."""
        level = detail or ("full" if full else "normal")
        if level not in TODO_DETAIL_LEVELS:
            return {"ok": False, "err": f"detail must be one of {', '.join(TODO_DETAIL_LEVELS)}, not {detail!r}"}
        if full and level != "full":
            return {"ok": False, "err": f"full=true asks for detail='full' but detail={detail!r} was passed; pass one"}
        if limit is not None and int(limit) < 1:
            return {"ok": False, "err": "limit must be 1 or more (leave it out for every unit)"}
        ids = "nil" if not unit_ids else "{" + ",".join(str(int(i)) for i in unit_ids) + "}"
        r = self.q(f"return H.todo_actions({self._pid(pid)}, {ids}, {'true' if level == 'full' else 'false'})",
                   timeout=180)
        if not isinstance(r, dict) or not r.get("ok"):
            return r
        rows = r.get("units") or []
        r["detail"] = level
        if limit is not None and len(rows) > int(limit):
            rest = rows[int(limit):]
            rows = rows[:int(limit)]
            rest_ids = [u.get("id") for u in rest]
            r["omitted"] = {"count": len(rest_ids), "ids": rest_ids,
                            "args": {"unit_ids": rest_ids, "detail": level}}
        if level == "summary":
            rows = [_summary_unit_row(u) for u in rows]
            r["routine_actions"] = list(ROUTINE_ACTIONS)
            r["drill_down"] = {"tool": "todo_actions",
                               "args": {"unit_ids": [u.get("id") for u in rows], "detail": "normal"},
                               "note": "any subset of these ids; detail='full' adds the computed help lines"}
        r["units"] = rows
        r["returned"] = len(rows)
        return r
