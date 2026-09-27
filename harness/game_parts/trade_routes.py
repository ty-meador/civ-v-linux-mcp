"""Trade routes: establishing, reading and plundering them."""
from __future__ import annotations




class TradeRoutesMixin:
    """Trade routes: establishing, reading and plundering them.

    A part of harness.game.Game (see harness/game_parts/__init__.py); `self` is the whole Game."""

    def establish_trade_route(self, unit_id: int, dest_x: int = -1, dest_y: int = -1, trade_type: int = -1,
                              pid: int | None = None, city_name: str = "", kind: str = "") -> dict:
        """Send a caravan/cargo ship to establish a trade route. See available_trade_routes for valid destinations/types.
        `city_name` (+ optional `kind`: international/food/production) picks the row from
        available_trade_routes instead of dest_x/dest_y/trade_type (live t303: every caller first read the
        list, then copied three numbers back).

        Goes through the selection list + GAMEMESSAGE_PUSH_MISSION like every unit order (v86); the
        selection can land a frame late, which `_order` handles by re-issuing the call."""
        if city_name:
            rows = self.available_trade_routes(unit_id, pid)
            rows = rows if isinstance(rows, list) else []
            hits = [r for r in rows if str(r.get("city_name", "")).lower() == city_name.lower()
                    and (not kind or r.get("kind") == kind)]
            if not hits:
                return {"ok": False, "err": f"no available route to {city_name!r}" + (f" of kind {kind!r}" if kind else ""),
                        "available": [(r.get("city_name"), r.get("kind")) for r in rows]}
            if len(hits) > 1:
                return {"ok": False, "err": f"{len(hits)} routes to {city_name!r}; pass kind=international/food/production",
                        "available": [(r.get("city_name"), r.get("kind")) for r in hits]}
            dest_x, dest_y, trade_type = hits[0]["x"], hits[0]["y"], hits[0]["trade_connection_type"]
        elif dest_x >= 0 and dest_y >= 0 and trade_type < 0:
            # The destination alone names the route when only one kind goes there (live 2026-09-27, Codex
            # t64: dest_x/dest_y with kind="international" and no trade_type was refused, then retried).
            rows = self.available_trade_routes(unit_id, pid)
            rows = rows if isinstance(rows, list) else []
            hits = [r for r in rows if r.get("x") == dest_x and r.get("y") == dest_y
                    and (not kind or r.get("kind") == kind)]
            if not hits:
                return {"ok": False, "err": f"no available route to ({dest_x},{dest_y})" + (f" of kind {kind!r}" if kind else ""),
                        "available": [(r.get("city_name"), r.get("kind")) for r in rows]}
            if len(hits) > 1:
                return {"ok": False, "err": f"{len(hits)} routes to ({dest_x},{dest_y}); pass kind=international/food/production",
                        "available": [(r.get("city_name"), r.get("kind")) for r in hits]}
            trade_type = hits[0]["trade_connection_type"]
        if dest_x < 0 or dest_y < 0 or trade_type < 0:
            return {"ok": False, "err": "pass city_name, or dest_x/dest_y (with kind when several route kinds go there), "
                                        "or dest_x/dest_y/trade_type from available_trade_routes"}
        # Confirm by the active-route list: the caravan is consumed and re-created under a NEW unit id
        # when the route starts, and GetNumInternationalTradeRoutesUsed counts trade units, not routes
        # (it read 5 before and after on the first live try), so neither the unit nor that count proves
        # anything. GetTradeRoutes() gains one entry.
        before = self.trade_routes(pid)
        before_out = (before or {}).get("outgoing") if isinstance(before, dict) else (before or [])
        r = self._order(f"return H.establish_trade_route({unit_id}, {dest_x}, {dest_y}, {trade_type}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        def outgoing():
            after = self.trade_routes(pid)
            return (after or {}).get("outgoing") if isinstance(after, dict) else (after or [])
        after_out, _ = self._settle(outgoing, lambda a: isinstance(a, list) and isinstance(before_out, list)
                                    and len(a) != len(before_out), initial=before_out)
        if isinstance(after_out, list) and isinstance(before_out, list) and len(after_out) > len(before_out):
            key = lambda x: (x.get("from_city"), x.get("to_city"), x.get("turns_left"))
            seen = {key(x) for x in before_out}
            new = [x for x in after_out if key(x) not in seen]
            route = new[0] if new else None
            r.update({"established": True, "route": route, "routes_active": len(after_out)})
            ru = route.get("unit") if isinstance(route, dict) else None
            if isinstance(ru, dict) and ru.get("id") not in (None, unit_id):
                # The engine re-creates the trade unit for its route: same caravan, new id (Codex c41,
                # 2026-09-27, read the reply as "a different unit was substituted and mine consumed").
                r["unit_id_now"] = ru["id"]
                r["note"] = (f"unit {unit_id} is the caravan on this route, re-created by the engine under id "
                             f"{ru['id']} when the route started; the old id is gone and nothing was substituted "
                             "(the digest shows it as unit_destroyed, then trade_route_started)")
        else:
            r.update({"established": False, "note": "no new entry in trade_routes within 3s; check trade_routes / units"})
        return r

    def trade_routes(self, pid: int | None = None) -> dict:
        """Trade Route Overview: `outgoing` (Your TR) and `incoming` (With You).

        Religion columns (`from_religion` / `from_pressure`, `to_religion` / `to_pressure`) are present
        only when the screen would print them. `details` is the gold and science hover."""
        return self.q(f"return H.trade_routes({self._pid(pid)})")

    def plunder_trade_route(self, unit_id: int, pid: int | None = None) -> dict:
        """Order a military unit to plunder an enemy trade route it's standing on."""
        return self.unit_mission(unit_id, "MISSION_PLUNDER_TRADE_ROUTE", pid=pid)

    def available_trade_routes(self, unit_id: int, pid: int | None = None, detail: str = "summary") -> list[dict]:
        """Valid trade-route destinations for a specific trade unit (caravan/cargo ship) right now, with
        the exact `trade_connection_type` to pass as `establish_trade_route`'s `trade_type`. Per-unit,
        not global -- see `establish_trade_route`'s docstring for why. Religious pressure matches the
        chooser row; the gold/science hover (`details`, ~600 characters per destination, the same
        numbers the row already carries) only with detail="full": a capital with ten reachable cities
        answered 6 KB of hover text for one caravan (Mongolia t102, 2026-09-27)."""
        rows = self.q(f"return H.available_trade_routes({unit_id}, {self._pid(pid)})")
        if detail != "full" and isinstance(rows, list):
            for r in rows:
                if isinstance(r, dict):
                    r.pop("details", None)
        return rows
