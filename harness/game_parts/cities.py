"""City management: citizens, focus, plots, tasks, production and purchases, city strikes."""
from __future__ import annotations

from .. import affordances as A

import time
from typing import Any

from ..client import TunerdError

from .support import _check_order_item


def _yield_type(yield_type) -> str:
    """"GOLD" or "FAITH" as the tools document it, in any case and with or without the YIELD_ prefix; anything
    else is refused here, before a query, instead of surfacing as a KeyError."""
    yt = str(yield_type or "GOLD").upper().removeprefix("YIELD_")
    if yt not in ("GOLD", "FAITH"):
        raise ValueError(f'yield_type must be "GOLD" or "FAITH", not {yield_type!r}')
    return yt


# A city's production queue as item enums, head first (`queue`), for set_production's reply and remove_from_queue's
# before/after check. Inserted into f-string Lua, so single braces here.


class CitiesMixin:
    """City management: citizens, focus, plots, tasks, production and purchases, city strikes.

    A part of harness.game.Game (see harness/game_parts/__init__.py); `self` is the whole Game."""

    def set_auto_specialists(self, city_id: int, automatic: bool, pid: int | None = None) -> dict:
        r = self.q(self.h('set_auto_specialists', int(city_id), str(bool(automatic)).lower(), pid=pid))
        if r.get("ok"):
            for _ in range(10):
                time.sleep(0.2)
                r["auto_specialists"] = self.city_screen(city_id, pid).get("auto_specialists")
                if r["auto_specialists"] == automatic:
                    break
            r["ok"] = r["auto_specialists"] == automatic
            if not r["ok"]:
                r["err"] = "specialist automation did not change after the city task"
        return r

    def change_specialist(self, city_id: int, building: str, add: bool, pid: int | None = None) -> dict:
        r = self.q(self.h('change_specialist', int(city_id), building, str(bool(add)).lower(), pid=pid))
        if r.get("ok"):
            for _ in range(10):
                time.sleep(0.2)
                sc = self.city_screen(city_id, pid)
                b = next((b for b in sc.get("buildings", []) if b["building"] == r["building"]), {})
                r["assigned"] = b.get("specialist_assigned")
                r["auto_specialists"] = sc.get("auto_specialists")
                if r["assigned"] == r["expected"]:
                    break
            r["ok"] = r["assigned"] == r["expected"] and r["auto_specialists"] is False
            if not r["ok"]:
                r["err"] = "specialist assignment did not match the requested city task"
        return r

    def set_city_focus(self, city_id: int, focus: str, pid: int | None = None) -> dict:
        """Citizen focus: balanced / food / production / gold / science / culture / great_people / faith.
        Same as the city-screen focus buttons (Network.SendSetCityAIFocus)."""
        r = self.q(self.h('set_city_focus', int(city_id), focus, pid=pid))
        if not r.get("ok"):
            return r
        time.sleep(0.2)
        sc = self.city_screen(city_id, pid)
        return {**r, "focus": sc.get("focus"), "food_surplus": sc.get("food_surplus"), "growth": sc.get("growth")}

    def set_avoid_growth(self, city_id: int, avoid: bool, pid: int | None = None) -> dict:
        r = self.q(self.h('set_avoid_growth', int(city_id), str(bool(avoid)).lower(), pid=pid))
        if not r.get("ok"):
            return r
        time.sleep(0.2)
        sc = self.city_screen(city_id, pid)
        return {**r, "avoid_growth": sc.get("avoid_growth")}

    def change_working_plot(self, city_id: int, x: int, y: int, pid: int | None = None) -> dict:
        """Toggle whether this city works plot (x, y). Same as clicking the tile in the city screen."""
        r = self.q(self.h('change_working_plot', int(city_id), int(x), int(y), pid=pid))
        if not r.get("ok"):
            return r
        time.sleep(0.2)
        sc = self.city_screen(city_id, pid)
        tile = next((p for p in (sc.get("plots") or []) if p.get("x") == x and p.get("y") == y), None)
        return {**r, "worked": bool(tile and tile.get("worked")), "food_surplus": sc.get("food_surplus"),
                "growth": sc.get("growth")}

    def buy_city_plot(self, city_id: int, x: int, y: int, pid: int | None = None) -> dict:
        r = self.q(self.h('buy_city_plot', int(city_id), int(x), int(y), pid=pid))
        if not r.get("ok"):
            return r
        time.sleep(0.2)
        sc = self.city_screen(city_id, pid)
        tile = next((p for p in (sc.get("plots") or []) if p.get("x") == x and p.get("y") == y), None)
        return {**r, "owned": tile is not None and not tile.get("buyable"), "gold": self.summary(pid).get("gold")}

    def city_task(self, city_id: int, action: str, pid: int | None = None) -> dict:
        """annex / raze / unraze. Puppets can be annexed later; raze burns pop per turn."""
        r = self.q(self.h('city_task', int(city_id), action, pid=pid))
        if not r.get("ok"):
            return r
        time.sleep(0.3)
        sc = self.city_screen(city_id, pid)
        return {**r, "puppet": sc.get("puppet"), "razing": sc.get("razing"), "occupied": sc.get("occupied"),
                "resistance_turns": sc.get("resistance_turns")}

    def sell_building(self, city_id: int, building: str, pid: int | None = None) -> dict:
        """City-screen sell: Network.SendSellBuilding. city_screen marks can_sell + sell_gold."""
        r = self.q(self.h('sell_building', int(city_id), building, pid=pid))
        if not r.get("ok"):
            return r
        for _ in range(12):
            time.sleep(0.2)
            gold = (self.summary(pid) or {}).get("gold")
            sc = self.city_screen(city_id, pid) or {}
            still = any(isinstance(b, dict) and b.get("building") == building for b in sc.get("buildings") or [])
            r["gold"] = gold
            r["still_present"] = still
            if not still:
                r["ok"] = True
                return r
        r["ok"] = False
        r["err"] = "sell was sent but the building is still listed"
        return r

    def set_production(self, city_id: int, order: str, item: str, pid: int | None = None, append: bool = False) -> dict:
        """order: ORDER_TRAIN|ORDER_CONSTRUCT|ORDER_CREATE|ORDER_MAINTAIN; item: UNIT_WARRIOR / BUILDING_MONUMENT / PROJECT_... / PROCESS_...

        `city:GetProductionNameKey()` read back in the same Lua call as `Game.CityPushOrder` still
        reports the *previous* head-of-queue item -- confirmed live (pushing a Settler over an
        in-progress Worker reported "Worker" back even though the queue had already been replaced).
        Re-read after a short settle delay so the returned name/turns match what was actually queued.

        Also checks the matching Can{{Construct,Train,Create,Maintain}}() guard up front: CityPushOrder
        itself accepts and silently drops an invalid order (e.g. a building the city already has) --
        confirmed live requesting BUILDING_MONUMENT a second time: {ok=true} came back but the queue
        never changed (production stayed empty, turns stuck at the 2147483647 "nothing queued"
        sentinel). This turns that into a real error up front instead.

        `order`/`item` must actually match (see `_check_order_item`) -- checked before this ever reaches
        the engine, for the same reason `purchase_cost`/`purchase_production` check it (see their
        docstrings for the live crash this class of bug caused there)."""
        mismatch = _check_order_item(order, item)
        if mismatch:
            return mismatch
        pre = self.q(self.h("production_check", city_id, order, item, pid=pid))
        if not pre.get("ok"):
            return self._name_hint(pre, item)
        r = self.q(self.h("city_push_order", city_id, order, pre["id"], bool(append), pid=pid))
        if not r.get("ok"):
            return r
        before = r.get("before") if isinstance(r.get("before"), list) else []
        time.sleep(0.3)
        # append=True is the production screen's shift-click (productionpopup.lua passes `not g_append` as the
        # 5th argument): the item goes behind what the city is building instead of replacing it. The reply
        # carries the whole queue so the caller sees where it landed.
        r = self._read_queue(city_id, pid)
        # a process never completes: the engine answers 2^31-1 turns (live t405 International Space Station)
        if isinstance(r, dict) and isinstance(r.get("turns"), int) and r["turns"] >= 2**31 - 1:
            r["turns"] = None
            r["note"] = "ongoing process: converts production every turn, never completes"
        # CityPushOrder drops an order the engine rejects without saying so; confirm it is really queued
        if isinstance(r, dict) and r.get("ok") and isinstance(r.get("queue"), list) and item not in r["queue"]:
            r["ok"] = False
            r["err"] = "order was not queued (the engine rejected it)"
        if isinstance(r, dict) and r.get("ok") and not append and before:
            # GitLab #114 (live Maya t153, t182): a replacing produce dropped three queued items and the reply did
            # not say so; the agent re-added them by hand once it noticed. Name them, and the way to keep them.
            r["replaced"] = before
            r["note"] = ((r.get("note") + "; ") if r.get("note") else "") + \
                "produce replaces the whole queue: the items listed under replaced are gone (the production put " \
                "into the old head is kept by the engine for that item); append: true adds behind the current build instead"
        return r

    def _read_queue(self, city_id: int, pid: int | None = None) -> dict:
        """The city's production queue as item enums, head first, with the head's name and turns."""
        return self.q(self.h("city_queue", city_id, pid=pid))

    def remove_from_queue(self, city_id: int, position: int, pid: int | None = None) -> dict:
        """Drop one item from a city's production queue (the city screen's click on a queued item). `position`
        is 1-based, as set_production's `queue` and the "already in this city's production queue (position N)"
        refusal count it: 1 is the item being built now, 2 the one behind it.

        The engine call is `city:PopOrder(index, 0, 0)` -- CvCity::popOrder(iNum, bFinish, bChoose) with a 0-based
        index. The Lua binding wants numbers for the two flags: booleans answer "bad argument #2 to 'PopOrder'
        (number expected, got boolean)" (live 2026-09-27, Babylon t24). `Network.SendPopOrder` and
        `Game.CityPopOrder` do not exist in this build. Like CityPushOrder, the pop is verified by re-reading the
        queue after a settle delay: the reply carries `removed` and the `queue` left."""
        if not isinstance(position, int) or isinstance(position, bool) or position < 1:
            return {"ok": False, "err": f"position is 1-based: 1 is what the city is building now, 2 the item behind "
                                        f"it, not {position!r}", "hint": "inspect(what='city', view='screen', id=city_id) lists the queue in order"}
        pre = self.q(self.h("city_pop_order", city_id, position, pid=pid))
        if not isinstance(pre, dict) or not pre.get("ok"):
            return pre if isinstance(pre, dict) else {"ok": False, "err": str(pre)}
        before = pre.get("queue") if isinstance(pre.get("queue"), list) else []
        time.sleep(0.3)
        r = self._read_queue(city_id, pid)
        if not isinstance(r, dict) or not r.get("ok"):
            return r if isinstance(r, dict) else {"ok": False, "err": str(r)}
        after = r.get("queue") if isinstance(r.get("queue"), list) else []
        expected = before[:position - 1] + before[position:]
        if len(before) > 0 and after != expected:
            r["ok"] = False
            r["err"] = "the item is still queued (the engine refused the pop)"
            return r
        if position - 1 < len(before):
            r["removed"] = before[position - 1]
        if isinstance(r.get("turns"), int) and r["turns"] >= 2**31 - 1:
            r["turns"] = None
        if not after:
            r["production"] = None
            r["note"] = "the city's production queue is now empty: order(to='city', action='produce') before ending the turn"
        return r

    _NAME_TABLES = {"UNIT_": "Units", "BUILDING_": "Buildings", "PROJECT_": "Projects", "PROCESS_": "Processes",
                    "TECH_": "Technologies"}

    def _name_hint(self, r: Any, name: str) -> Any:
        """On an "unknown item/tech" refusal, add the closest real names (live t321: UNIT_GREAT_PROPHET is
        UNIT_PROPHET). The table's Type list is read once per session."""
        if not (isinstance(r, dict) and str(r.get("err", "")).startswith("unknown")):
            return r
        import difflib
        table = next((t for pre, t in self._NAME_TABLES.items() if name.upper().startswith(pre)), None)
        tables = [table] if table else list(self._NAME_TABLES.values())
        cache = self.__dict__.setdefault("_type_names", {})
        names = []
        for t in tables:
            if t not in cache:
                cache[t] = self.q(self.h("info_types", t)) or []
            names += cache[t]
        close = difflib.get_close_matches(name.upper(), names, n=4, cutoff=0.6)
        close += [n for n in names if name.upper().split("_", 1)[-1] in n and n not in close][:4]
        return dict(r, err=f"{r['err']} {name!r}", did_you_mean=close[:5]) if close else dict(r, err=f"{r['err']} {name!r}")

    def purchase_cost(self, city_id: int, order: str, item: str, yield_type: str = "GOLD", pid: int | None = None) -> dict:
        """Read-only: cost to rush-buy `item` with gold or faith right now, and whether it's actually
        purchasable (`city:IsCanPurchase(true, true, ...)`, the same gate purchase_production checks before
        spending anything). order: ORDER_TRAIN (unit) | ORDER_CONSTRUCT (building) | ORDER_CREATE (project/
        wonder -- vanilla BNW's own UI hardcodes this as never purchasable regardless of cost, confirmed in
        `ui/ingame/popups/productionpopup.lua`'s wonder-listing code; `can_purchase` will read false).

        `order`/`item` must actually match -- see `_check_order_item`'s docstring for the live crash this
        exact function caused (ORDER_CREATE + a BUILDING_* item) before this check existed."""
        if order not in ("ORDER_TRAIN", "ORDER_CONSTRUCT", "ORDER_CREATE"):
            return {"ok": False, "err": "order must be ORDER_TRAIN, ORDER_CONSTRUCT, or ORDER_CREATE"}
        mismatch = _check_order_item(order, item)
        if mismatch:
            return mismatch
        yield_type = _yield_type(yield_type)
        return self._name_hint(self.q(self.h("purchase_cost", city_id, order, item, yield_type, pid=pid)), item)

    def purchase_production(self, city_id: int, order: str, item: str, yield_type: str = "GOLD", pid: int | None = None) -> dict:
        """Rush-buy a unit/building with gold or faith (yield_type: "GOLD" or "FAITH"). See purchase_cost
        for price/affordability first. order: ORDER_TRAIN (unit) | ORDER_CONSTRUCT (building) | ORDER_CREATE
        (project/wonder -- always refused, see purchase_cost's docstring). Checks
        `city:IsCanPurchase(true, true, ...)` up front -- the same real "can actually complete this" gate
        the UI reads to grey out the purchase button -- and returns a clean {ok:false} instead of a silent
        no-op or wasted currency. Confirmed against `ui/ingame/popups/productionpopup.lua`'s
        OnProductionButtonClick: `Game.CityPurchaseUnit/CityPurchaseBuilding/CityPurchaseProject(city, id,
        eYield)`.

        `order`/`item` must actually match -- see `_check_order_item`'s docstring for why this matters here
        specifically (a mismatched pair crashed the game via this function's sibling, `purchase_cost`)."""
        if order not in ("ORDER_TRAIN", "ORDER_CONSTRUCT", "ORDER_CREATE"):
            return {"ok": False, "err": "order must be ORDER_TRAIN, ORDER_CONSTRUCT, or ORDER_CREATE"}
        mismatch = _check_order_item(order, item)
        if mismatch:
            return mismatch
        yield_type = _yield_type(yield_type)
        pre = self.q(self.h("purchase_check", city_id, order, item, yield_type, pid=pid))
        if not pre.get("ok"):
            if str(pre.get("err", "")).startswith("cannot purchase"):
                # purchase_cost knows why (live t409: a faith Missionary refused in Guangzhou, a city with no
                # majority religion -- the generic error listed three wrong guesses).
                try:
                    why = self.purchase_cost(city_id, order, item, yield_type, pid)
                    if isinstance(why, dict):
                        for k in ("reason", "engine_reason", "cost", "balance", "blocking_units"):
                            if why.get(k) is not None:
                                pre[k] = why[k]
                except TunerdError:
                    pass
            return self._name_hint(pre, item)
        item_id = pre["id"]
        # For a unit purchase, remember the unit ids so the NEW unit can be named in the result (a bought
        # unit has 0 moves this turn; the caller still wants its id to give it orders next turn).
        before_ids = set()
        if order == "ORDER_TRAIN":
            before_ids = set(self.q(self.h("unit_ids", pid=pid)) or [])
        r = self.q(self.h("city_purchase", city_id, order, item_id, yield_type, pid=pid))
        if not r.get("ok"):
            return r
        time.sleep(0.3)
        out = self.q(self.h("city_after_purchase", city_id, yield_type, pid=pid))
        # The keys describe the city AFTER the purchase, not the purchase (live t335: a bought Laboratory that
        # was the city's current build left production "" and turns 2147483647 -- an idle city).
        if isinstance(out, dict) and out.get("ok"):
            out["bought"] = item
            out["city_now_building"] = out.pop("production", None) or None
            turns = out.pop("turns", None)
            if out["city_now_building"]:
                # a process answers 2^31-1 turns (live t179 Venice: a Bank bought under the Research process
                # read city_now_building_turns 2147483647); null it and say why, as set_production does
                if isinstance(turns, int) and turns >= 2**31 - 1:
                    turns = None
                    out["note"] = "ongoing process: converts production every turn, never completes"
                out["city_now_building_turns"] = turns
            else:
                out["note"] = "the city's production queue is now empty: order(to='city', action='produce') before ending the turn"
        if order == "ORDER_TRAIN" and out.get("ok"):
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                new = [u for u in (self.q(self.h("unit_brief_list", pid=pid)) or [])
                       if isinstance(u, dict) and u.get("id") not in before_ids]
                if new:
                    out["unit"] = new[0]
                    out["note"] = "a purchased unit has no moves this turn; order(to='unit', action='move') now queues a standing order it will follow next turn"
                    break
                time.sleep(0.25)
            if "unit" not in out:
                out["note"] = "purchase went through (balance changed) but the new unit was not found within 2s; see inspect(what='units')"
        return out

    def city_ranged_attack(self, city_id: int, x: int, y: int, pid: int | None = None) -> dict:
        """Ranged attack from a city. Selection-free: Network.SendDoTask, not UI.SelectCity.
        Returns the target's hp before/after and damage_dealt / killed (see _with_target_result)."""
        return self._with_target_result(
            x, y, lambda: self.q(self.h('city_ranged_attack', city_id, x, y, pid=pid)), pid)

    def available_city_strikes(self, city_id: int, pid: int | None = None) -> dict:
        """Plots this city can currently bombard (CanRangeStrikeAt). Empty if it cannot strike."""
        return A.strike_rows(self.q(self.h('available_city_strikes', city_id, pid=pid)), city_id)
