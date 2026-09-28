"""City management: citizens, focus, plots, tasks, production and purchases, city strikes."""
from __future__ import annotations

import time
from typing import Any

from ..client import TunerdError

from .support import _check_order_item, lua_str


def _yield_type(yield_type) -> str:
    """"GOLD" or "FAITH" as the tools document it, in any case and with or without the YIELD_ prefix; anything
    else is refused here, before a query, instead of surfacing as a KeyError."""
    yt = str(yield_type or "GOLD").upper().removeprefix("YIELD_")
    if yt not in ("GOLD", "FAITH"):
        raise ValueError(f'yield_type must be "GOLD" or "FAITH", not {yield_type!r}')
    return yt


class CitiesMixin:
    """City management: citizens, focus, plots, tasks, production and purchases, city strikes.

    A part of harness.game.Game (see harness/game_parts/__init__.py); `self` is the whole Game."""

    def set_auto_specialists(self, city_id: int, automatic: bool, pid: int | None = None) -> dict:
        r = self.q(f"return H.set_auto_specialists({int(city_id)}, {str(bool(automatic)).lower()}, {self._pid(pid)})")
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
        r = self.q(f"return H.change_specialist({int(city_id)}, {lua_str(building)}, {str(bool(add)).lower()}, {self._pid(pid)})")
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
        r = self.q(f"return H.set_city_focus({int(city_id)}, {lua_str(focus)}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        time.sleep(0.2)
        sc = self.city_screen(city_id, pid)
        return {**r, "focus": sc.get("focus"), "food_surplus": sc.get("food_surplus"), "growth": sc.get("growth")}

    def set_avoid_growth(self, city_id: int, avoid: bool, pid: int | None = None) -> dict:
        r = self.q(f"return H.set_avoid_growth({int(city_id)}, {str(bool(avoid)).lower()}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        time.sleep(0.2)
        sc = self.city_screen(city_id, pid)
        return {**r, "avoid_growth": sc.get("avoid_growth")}

    def change_working_plot(self, city_id: int, x: int, y: int, pid: int | None = None) -> dict:
        """Toggle whether this city works plot (x, y). Same as clicking the tile in the city screen."""
        r = self.q(f"return H.change_working_plot({int(city_id)}, {int(x)}, {int(y)}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        time.sleep(0.2)
        sc = self.city_screen(city_id, pid)
        tile = next((p for p in (sc.get("plots") or []) if p.get("x") == x and p.get("y") == y), None)
        return {**r, "worked": bool(tile and tile.get("worked")), "food_surplus": sc.get("food_surplus"),
                "growth": sc.get("growth")}

    def buy_city_plot(self, city_id: int, x: int, y: int, pid: int | None = None) -> dict:
        r = self.q(f"return H.buy_city_plot({int(city_id)}, {int(x)}, {int(y)}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        time.sleep(0.2)
        sc = self.city_screen(city_id, pid)
        tile = next((p for p in (sc.get("plots") or []) if p.get("x") == x and p.get("y") == y), None)
        return {**r, "owned": tile is not None and not tile.get("buyable"), "gold": self.summary(pid).get("gold")}

    def city_task(self, city_id: int, action: str, pid: int | None = None) -> dict:
        """annex / raze / unraze. Puppets can be annexed later; raze burns pop per turn."""
        r = self.q(f"return H.city_task({int(city_id)}, {lua_str(action)}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        time.sleep(0.3)
        sc = self.city_screen(city_id, pid)
        return {**r, "puppet": sc.get("puppet"), "razing": sc.get("razing"), "occupied": sc.get("occupied"),
                "resistance_turns": sc.get("resistance_turns")}

    def sell_building(self, city_id: int, building: str, pid: int | None = None) -> dict:
        """City-screen sell: Network.SendSellBuilding. city_screen marks can_sell + sell_gold."""
        r = self.q(f"return H.sell_building({int(city_id)}, {lua_str(building)}, {self._pid(pid)})")
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
        can_fn = {"ORDER_TRAIN": "CanTrain", "ORDER_CONSTRUCT": "CanConstruct",
                  "ORDER_CREATE": "CanCreate", "ORDER_MAINTAIN": "CanMaintain"}[order]
        pre = self.q(f"""
            local city = Players[{self._pid(pid)}]:GetCityByID({city_id})
            if not city then return {{ok=false, err="no such city"}} end
            local puppet = H.city_production_guard(city)
            if puppet then return puppet end
            local id = GameInfoTypes[{lua_str(item)}]
            if id == nil then return {{ok=false, err="unknown item"}} end
            if not city:{can_fn}(id, 0) then
              local r = {{ok=false, err="city cannot build this (missing prereq, already built, or one-per-city)"}}
              -- a wonder/building already sitting in this city's queue is refused too (live t437 Hubble)
              pcall(function()
                for i = 0, city:GetOrderQueueLength() - 1 do
                  local _, data = city:GetOrderFromQueue(i)
                  if data == id then r.err = "already in this city's production queue (position " .. (i + 1) .. ")" end
                end
              end)
              -- per-player unit caps (spaceship parts: 3 boosters) count units already built plus ones in any
              -- city's queue (live t437: a 4th booster refused while three cities were building one)
              local u = {lua_str(order)} == "ORDER_TRAIN" and GameInfo.Units[id]
              local uc = u and GameInfo.UnitClasses[u.Class]
              if uc and (uc.MaxPlayerInstances or -1) > 0 then
                local p = Players[{self._pid(pid)}]
                local have, making = p:GetUnitClassCount(uc.ID), p:GetUnitClassMaking(uc.ID)
                if have + making >= uc.MaxPlayerInstances then
                  r.err = "player limit reached: " .. have .. " built + " .. making .. " in production of max " .. uc.MaxPlayerInstances
                end
              end
              -- caravans / cargo ships: the engine trains none beyond the routes possible, counting the ones
              -- alive and the ones queued in any city (H.trade_unit_count; live t139 Venice "4 of 8" refused)
              if u and (u.Trade == true or u.Trade == 1) then
                local tu = H.trade_unit_count(Players[{self._pid(pid)}])
                if tu.remaining and tu.remaining <= 0 then
                  r.err = "every trade-route slot already has a caravan or cargo ship (" .. tu.alive .. " alive"
                          .. (tu.queued > 0 and (" + " .. tu.queued .. " queued") or "") .. " of " .. tostring(tu.possible)
                          .. "): the engine trains no more; route the idle ones (overview.idle_trade_units) or wait for a slot"
                end
              end
              return r
            end
            return {{ok=true, id=id}}""")
        if not pre.get("ok"):
            return self._name_hint(pre, item)
        r = self.q(f"""
            local city = Players[{self._pid(pid)}]:GetCityByID({city_id})
            Game.CityPushOrder(city, OrderTypes.{order}, {pre['id']}, false, {"false" if append else "true"}, true)
            return {{ok=true}}""")
        if not r.get("ok"):
            return r
        time.sleep(0.3)
        # append=True is the production screen's shift-click (productionpopup.lua passes `not g_append` as the
        # 5th argument): the item goes behind what the city is building instead of replacing it. The reply
        # carries the whole queue so the caller sees where it landed.
        r = self.q(f"""
            local city = Players[{self._pid(pid)}]:GetCityByID({city_id})
            if not city then return {{ok=false, err="no such city"}} end
            local queue = {{}}
            pcall(function()
              for i = 0, city:GetOrderQueueLength() - 1 do
                local orderType, data = city:GetOrderFromQueue(i)
                local row = (orderType == OrderTypes.ORDER_TRAIN and GameInfo.Units[data])
                         or (orderType == OrderTypes.ORDER_CONSTRUCT and GameInfo.Buildings[data])
                         or (orderType == OrderTypes.ORDER_CREATE and GameInfo.Projects[data])
                         or (orderType == OrderTypes.ORDER_MAINTAIN and GameInfo.Processes[data]) or nil
                queue[#queue + 1] = row and row.Type or tostring(data)
              end
            end)
            return {{ok=true, production=H.L(city:GetProductionNameKey()), turns=city:GetProductionTurnsLeft(), queue=queue}}""")
        # a process never completes: the engine answers 2^31-1 turns (live t405 International Space Station)
        if isinstance(r, dict) and isinstance(r.get("turns"), int) and r["turns"] >= 2**31 - 1:
            r["turns"] = None
            r["note"] = "ongoing process: converts production every turn, never completes"
        # CityPushOrder drops an order the engine rejects without saying so; confirm it is really queued
        if isinstance(r, dict) and r.get("ok") and isinstance(r.get("queue"), list) and item not in r["queue"]:
            r["ok"] = False
            r["err"] = "order was not queued (the engine rejected it)"
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
                cache[t] = self.q(f"local t = {{}} for row in GameInfo.{t}() do t[#t + 1] = row.Type end return t") or []
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
        unit_id, building_id, project_id = ("id", "-1", "-1") if order == "ORDER_TRAIN" else \
            (("-1", "id", "-1") if order == "ORDER_CONSTRUCT" else ("-1", "-1", "id"))
        cost_fn = {"ORDER_TRAIN": "GetUnitPurchaseCost", "ORDER_CONSTRUCT": "GetBuildingPurchaseCost",
                   "ORDER_CREATE": "GetProjectPurchaseCost"}[order]
        faith_cost_fn = {"ORDER_TRAIN": "GetUnitFaithPurchaseCost", "ORDER_CONSTRUCT": "GetBuildingFaithPurchaseCost",
                         "ORDER_CREATE": "GetProjectPurchaseCost"}[order]  # no project-faith-specific getter found; reuse gold one
        yield_type = _yield_type(yield_type)
        yield_const = {"GOLD": "YieldTypes.YIELD_GOLD", "FAITH": "YieldTypes.YIELD_FAITH"}[yield_type]
        cost_call = f"city:{cost_fn}(id)" if yield_type == "GOLD" else \
            (f"city:{faith_cost_fn}(id, true)" if order == "ORDER_TRAIN" else f"city:{faith_cost_fn}(id)")
        # What a human actually reads when the button is greyed out: the stock production popup appends
        # the engine's own tooltip to a disabled row (productionpopup.lua, "Disabled help text" -- one
        # getter per order x yield). The reason ladder above is our guesswork; this is the game's answer,
        # and it is the only thing that explains e.g. a Pagoda refused in a puppet that follows another
        # religion (live t205: all three puppets read "cannot be bought here at all").
        tip_fn = {("ORDER_TRAIN", "GOLD"): "GetPurchaseUnitTooltip",
                  ("ORDER_TRAIN", "FAITH"): "GetFaithPurchaseUnitTooltip",
                  ("ORDER_CONSTRUCT", "GOLD"): "GetPurchaseBuildingTooltip",
                  ("ORDER_CONSTRUCT", "FAITH"): "GetFaithPurchaseBuildingTooltip"}.get((order, yield_type))
        tip_probe = "" if not tip_fn else f"""
              if city.{tip_fn} then
                local okt, tip = pcall(function() return city:{tip_fn}(id) end)
                if okt and type(tip) == "string" and tip ~= "" then out.engine_reason = tip end
              end"""
        return self._name_hint(self.q(f"""
            local buyer = Players[{self._pid(pid)}]
            local city = buyer:GetCityByID({city_id})
            if not city then return {{ok=false, err="no such city"}} end
            local id = GameInfoTypes[{lua_str(item)}]
            if id == nil then return {{ok=false, err="unknown item"}} end
            local cost = {cost_call}
            local balance = buyer:{"GetGold" if yield_type == "GOLD" else "GetFaith"}()
            local can = city:IsCanPurchase(true, true, {unit_id}, {building_id}, {project_id}, {yield_const})
            local out = {{ok=true, cost=cost, can_purchase=can, balance=balance}}
            if not can then
              -- The purchase screen only greys the button out. Say why when it is knowable (live t319: 975
              -- gold vs a 960 Great War Infantry, refused because a Swordsman stood on the city tile).
              if {"true" if yield_type == "FAITH" else "false"} and (cost or 0) <= 0 then
                out.reason = "not sold for faith (faith buys religious units, and Great People or other units only with the belief/policy/era that unlocks them)"
              elseif {"true" if yield_type == "FAITH" and order == "ORDER_TRAIN" else "false"}
                     and ((GameInfo.Units[id] or {{}}).ReligionSpreads or 0) > 0 and city:GetReligiousMajority() < 0 then
                -- live t409: a Missionary spreads the religion of the city it is bought in; Guangzhou had none
                out.reason = "religious units spread the city's majority religion: this city has none -- buy it in a city that follows your religion"
              elseif type(cost) == "number" and cost < 0 then
                -- live t403: SS_COCKPIT priced -1 -- no gold price exists for it at all
                out.reason = "this item has no gold price (spaceship parts, wonders, projects): it can only be built"
                out.cost = nil
              elseif {"true" if order == "ORDER_CONSTRUCT" else "false"} and city:IsHasBuilding(id) then
                out.reason = "already built in this city"  -- live t431: Nanjing's Spaceship Factory, read as 'cannot be bought here at all'
              elseif city.IsPuppet and city:IsPuppet()
                     and not (buyer.MayNotAnnex and buyer:MayNotAnnex()) then
                -- The purchase screen does not open for a puppet at all: productionpopup.lua returns
                -- early on IsPuppet() unless the player MayNotAnnex() (Venice). So the engine has no
                -- tooltip to offer either -- live t205, a faith Pagoda in Tiwanaku, a puppet that does
                -- follow our religion and does not have one yet, refused with nothing said.
                out.reason = "this city is a puppet: the purchase screen does not open for puppets (annex it to buy here)"
              elseif type(cost) == "number" and cost > balance
                     and city:IsCanPurchase(false, true, {unit_id}, {building_id}, {project_id}, {yield_const}) then
                -- Before the "cannot be bought here at all" catch-all: live t205, a 1050-gold Factory
                -- against 385 gold was called unbuildable while the engine's own tooltip said
                -- "You do not have enough Gold to buy this." Only where the buy button exists: Venice's
                -- Settler (live t42, v225) was "not enough gold (189 of 370)" though Venice can never have one.
                out.reason = "not enough " .. {lua_str(yield_type.lower())} .. " (" .. balance .. " of " .. cost .. ")"
              elseif not city:IsCanPurchase(false, false, {unit_id}, {building_id}, {project_id}, {yield_const}) then
                out.reason = "this item cannot be bought here at all (wonders/projects, or not buildable in this city)"
              elseif not city:IsCanPurchase(false, true, {unit_id}, {building_id}, {project_id}, {yield_const}) then
                out.reason = "this city cannot train or build it, so there is no buy button (compare(kind='production') names the rule)"
              elseif {"true" if order == "ORDER_TRAIN" else "false"} then
                local plot, blockers = city:Plot(), {{}}
                local row = GameInfo.Units[id]
                local combat = row and (row.Combat or 0) > 0
                for i = 0, plot:GetNumUnits() - 1 do
                  local u = plot:GetUnit(i)
                  if u and u:GetOwner() == city:GetOwner() and (u:IsCombatUnit() == combat)
                     and GameInfo.Units[u:GetUnitType()].Domain == row.Domain then
                    blockers[#blockers + 1] = {{unit_id = u:GetID(), type = GameInfo.Units[u:GetUnitType()].Type}}
                  end
                end
                if #blockers > 0 then
                  out.reason = "a unit of the same kind already stands in the city (one per tile); move it out first"
                  out.blocking_units = blockers
                else
                  out.reason = "the game refuses the purchase this turn (already bought something here this turn?)"
                end
              else
                out.reason = "the game refuses the purchase this turn"
              end
              {tip_probe}
            end
            return out"""), item)

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
        unit_id, building_id, project_id = ("id", "-1", "-1") if order == "ORDER_TRAIN" else \
            (("-1", "id", "-1") if order == "ORDER_CONSTRUCT" else ("-1", "-1", "id"))
        purchase_fn = {"ORDER_TRAIN": "CityPurchaseUnit", "ORDER_CONSTRUCT": "CityPurchaseBuilding",
                       "ORDER_CREATE": "CityPurchaseProject"}[order]
        yield_type = _yield_type(yield_type)
        yield_const = {"GOLD": "YieldTypes.YIELD_GOLD", "FAITH": "YieldTypes.YIELD_FAITH"}[yield_type]
        pre = self.q(f"""
            local city = Players[{self._pid(pid)}]:GetCityByID({city_id})
            if not city then return {{ok=false, err="no such city"}} end
            local id = GameInfoTypes[{lua_str(item)}]
            if id == nil then return {{ok=false, err="unknown item"}} end
            if not city:IsCanPurchase(true, true, {unit_id}, {building_id}, {project_id}, {yield_const}) then
                return {{ok=false, err="cannot purchase this right now (not enough currency, already queued, or not purchasable this way)"}}
            end
            return {{ok=true, id=id}}""")
        if not pre.get("ok"):
            if str(pre.get("err", "")).startswith("cannot purchase"):
                # purchase_cost knows why (live t409: a faith Missionary refused in Guangzhou, a city with no
                # majority religion -- the generic error listed three wrong guesses).
                try:
                    why = self.purchase_cost(city_id, order, item, yield_type, pid)
                    if isinstance(why, dict):
                        for k in ("reason", "cost", "balance", "blocking_units"):
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
            before_ids = set(self.q(f"local out = {{}}; for u in Players[{self._pid(pid)}]:Units() do out[#out+1] = u:GetID() end; return out") or [])
        r = self.q(f"""
            local city = Players[{self._pid(pid)}]:GetCityByID({city_id})
            Game.{purchase_fn}(city, {item_id}, {yield_const})
            return {{ok=true}}""")
        if not r.get("ok"):
            return r
        time.sleep(0.3)
        out = self.q(f"""
            local city = Players[{self._pid(pid)}]:GetCityByID({city_id})
            if not city then return {{ok=false, err="no such city"}} end
            return {{ok=true, production=H.L(city:GetProductionNameKey()), turns=city:GetProductionTurnsLeft(),
                     balance=Players[{self._pid(pid)}]:{"GetGold" if yield_type == "GOLD" else "GetFaith"}()}}""")
        # The keys describe the city AFTER the purchase, not the purchase (live t335: a bought Laboratory that
        # was the city's current build left production "" and turns 2147483647 -- an idle city).
        if isinstance(out, dict) and out.get("ok"):
            out["bought"] = item
            out["city_now_building"] = out.pop("production", None) or None
            turns = out.pop("turns", None)
            if out["city_now_building"]:
                out["city_now_building_turns"] = turns
            else:
                out["note"] = "the city's production queue is now empty: set_production before ending the turn"
        if order == "ORDER_TRAIN" and out.get("ok"):
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                new = [u for u in (self.q(f"local out = {{}}; for u in Players[{self._pid(pid)}]:Units() do "
                                          f"out[#out+1] = {{id = u:GetID(), x = u:GetX(), y = u:GetY(), "
                                          f"type = (GameInfo.Units[u:GetUnitType()] or {{}}).Type or u:GetUnitType()}} end; return out") or [])
                       if isinstance(u, dict) and u.get("id") not in before_ids]
                if new:
                    out["unit"] = new[0]
                    out["note"] = "a purchased unit has no moves this turn; move_unit now queues a standing order it will follow next turn"
                    break
                time.sleep(0.25)
            if "unit" not in out:
                out["note"] = "purchase went through (balance changed) but the new unit was not found within 2s; see units()"
        return out

    def city_ranged_attack(self, city_id: int, x: int, y: int, pid: int | None = None) -> dict:
        """Ranged attack from a city. Selection-free: Network.SendDoTask, not UI.SelectCity.
        Returns the target's hp before/after and damage_dealt / killed (see _with_target_result)."""
        return self._with_target_result(
            x, y, lambda: self.q(f"return H.city_ranged_attack({city_id}, {x}, {y}, {self._pid(pid)})"), pid)

    def available_city_strikes(self, city_id: int, pid: int | None = None) -> dict:
        """Plots this city can currently bombard (CanRangeStrikeAt). Empty if it cannot strike."""
        return self.q(f"return H.available_city_strikes({city_id}, {self._pid(pid)})")
