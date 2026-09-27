"""The event stream: turn_digest and the combat narration built from the runtime's event records."""
from __future__ import annotations

from ..client import TunerdError

from .support import lua_str, plain_text


class EventsMixin:
    """The event stream: turn_digest and the combat narration built from the runtime's event records.

    A part of harness.game.Game (see harness/game_parts/__init__.py); `self` is the whole Game."""

    def turn_digest(self) -> dict:
        """events_since_last plus the notifications panel, without the panel entries the events already
        carry (live t320: all ten notifications came twice, ~5 KB) and with the game's text markup removed."""
        events = self.events_since_last()
        seen = {e["data"].get("text") for e in events if e.get("kind") == "notification" and isinstance(e.get("data"), dict)}
        notes = [n for n in self.notifications() if n.get("text") not in seen]
        if notes:
            # The panel keeps a notification live for about a turn, so one delivered as an event by the previous
            # digest came back here (live t343: "Washington has made peace with Gandhi!" twice across two
            # digests). Drop any the event log already delivered; keep the ones it never saw (pre-reload).
            try:
                delivered = set(self.q(f"""local t = {{}}
                    for _, e in ipairs(H.events) do
                      if e.kind == "notification" and e.audience == {self.seat} and e.data and e.data.text then t[#t + 1] = e.data.text end
                    end
                    return t""") or [])
                notes = [n for n in notes if n.get("text") not in delivered]
            except (TunerdError, TypeError):
                pass
        # "Shanghai has been converted to another religion!" never says which (live t332: Catholicism;
        # t179 Machu was a follower tie so cities().religion was nil). Lua attach_conversion_banner
        # fills the city-banner tooltip at record time; this is the fallback for events recorded
        # before that hook.
        conv = [e["data"] for e in events if e.get("kind") == "notification" and isinstance(e.get("data"), dict)
                and any(k in str(e["data"].get("text", "")) for k in ("converted to another religion", "has adopted a religion"))]
        if conv:
            try:
                for d in conv:
                    if d.get("religions") is not None:
                        continue
                    banner = self.q(
                        f"local d = {{text = {lua_str(d.get('text') or '')}, player = {self.seat}}}; "
                        f"H.attach_conversion_banner(d, Players[{self.seat}]); return d")
                    if isinstance(banner, dict):
                        for k in ("city_id", "x", "y", "religion", "majority", "religions", "note"):
                            if k in banner:
                                d[k] = banner[k]
            except TunerdError:
                pass
        # "Steal Technology" names the victim civ but not which tech (live t181: Inca / Sailing).
        steal_notes = [e["data"] for e in events if e.get("kind") == "notification" and isinstance(e.get("data"), dict)
                       and ("steal a technology" in str(e["data"].get("text", "")).lower()
                            or "Steal Technology" in str(e["data"].get("summary", "")))]
        if steal_notes:
            try:
                for d in steal_notes:
                    if d.get("steal_tech") is not None:
                        continue
                    attached = self.q(
                        f"local d = {{text = {lua_str(d.get('text') or '')}, summary = {lua_str(d.get('summary') or '')}, "
                        f"player = {self.seat}}}; H.attach_steal_tech(d, Players[{self.seat}]); return d")
                    if isinstance(attached, dict):
                        for k in ("steal_tech", "hint"):
                            if k in attached:
                                d[k] = attached[k]
            except TunerdError:
                pass
        return plain_text({"events": events, "notifications": notes})

    def events_since_last(self) -> list[dict]:
        """Recorded game events since the previous call (cursor is kept inside the game's Lua state).

        `unit_destroyed` comes from SerialEventUnitDestroyed, which is a *graphics* event: it also fires
        when the engine merely rebuilds a unit's model -- every unit on an era change (live, t244: all four
        workers "destroyed" on reaching the Industrial era), a caravan starting a route, a unit being
        upgraded. So each of my own `unit_destroyed` events is checked against the live unit list here and
        relabelled `unit_graphics_reset` when the unit still exists, so a caller never mourns a live
        worker. Genuine losses keep `unit_destroyed`."""
        return self._refine_events(self.q(f"return H.take_events({self.seat})"))

    def _refine_events(self, events: list[dict]) -> list[dict]:
        """The digest's corrections to raw runtime events, shared by turn_digest and the briefing."""
        events = list(events or [])
        # Leader lines said while the harness itself had the trade screen open (propose_deal /
        # negotiate_deal) are replies to our visit, not the AI approaching us: drop them here so the
        # digest only carries unsolicited diplomacy. relationship()'s history still keeps them.
        events = [e for e in events if not (e.get("kind") == "leader_message" and isinstance(e.get("data"), dict)
                                            and e["data"].get("harness_initiated"))]
        ids = sorted({e["data"]["unit"] for e in events
                      if e.get("kind") == "unit_destroyed" and isinstance(e.get("data"), dict)
                      and e["data"].get("player") == self.seat and isinstance(e["data"].get("unit"), int)})
        if ids:
            alive = self.q(f"""
                local p = Players[{self.seat}]; local out = {{}}
                for _, id in ipairs({{{", ".join(str(i) for i in ids)}}}) do
                    local u = p:GetUnitByID(id)
                    if u and not u:IsDelayedDeath() then out[#out + 1] = id end
                end
                return out""") or []
            alive = set(alive)
            for e in events:
                if e.get("kind") == "unit_destroyed" and isinstance(e.get("data"), dict) and e["data"].get("unit") in alive:
                    e["kind"] = "unit_graphics_reset"
                    e["data"]["note"] = "unit still exists; the engine only rebuilt its model (era change, route start, upgrade)"
        return self._narrate_combat(events)

    def _narrate_combat(self, events: list[dict]) -> list[dict]:
        """Give every `combat` event a one-line `summary` ("your SCOUT (12,8) was hit by Barbarians WARRIOR
        from (13,8): -38 hp, 62 left") built from the attacker/defender rows the Lua hook captured, and
        drop the `unit_hurt` / `unit_lost` fallback rows (hp compared across the AI phase) for units a
        `combat` event already explains, so only *unexplained* losses remain."""
        def side(s: dict | None, raw_player) -> str:
            s = s or {}
            owner = s.get("owner") or f"player {raw_player}"
            name = f"{'your' if owner == 'you' else owner} {s.get('unit', 'unit (not visible)')}"
            return f"{name} ({s['x']},{s['y']})" if "x" in s else name

        def outcome(s: dict | None, dmg) -> str:
            s = s or {}
            if s.get("killed"):
                return f"-{dmg} hp, killed"
            return f"-{dmg} hp, {s['hp']} left" if "hp" in s else f"-{dmg} hp"

        # A unit of mine that disappears during MY OWN turn without a combat event was spent by my own
        # order (great person used, unit upgraded into a new id, settler founded, disband) -- live t314 the
        # digest read like four losses after one DISCOVER and three upgrades. Only a disappearance during
        # the other players' turns, or one a combat explains, stays `unit_destroyed`.
        markers = [e.get("kind") for e in events if e.get("kind") in ("turn_start", "turn_end")]
        in_my_turn = not markers or markers[0] == "turn_end"
        fought = {d.get(k) for e in events if e.get("kind") == "combat" and isinstance(d := e.get("data"), dict)
                  for k in ("att_unit", "def_unit")}
        # A civilian taken is not a unit killed. The capture notice (Lua attach_capture) names the unit id
        # and tile; the bare `unit_destroyed` row for that id becomes `unit_captured` with the notice's
        # words, and the hp-compare fallback for it is dropped (live 2026-09-24 t217: Bravo's Settler came
        # as three unrelated rows).
        captured = {d.get("unit_id"): d for e in events if e.get("kind") == "notification"
                    and isinstance(d := e.get("data"), dict) and isinstance(d.get("unit_id"), int)
                    and " was captured by " in str(d.get("text", ""))}
        for e in events:
            d = e.get("data")
            if e.get("kind") == "unit_destroyed" and isinstance(d, dict) and d.get("unit") in captured:
                n = captured[d["unit"]]
                e["kind"] = "unit_captured"
                where = f" at ({n['x']},{n['y']})" if "x" in n and "y" in n else ""
                by = str(n.get("text", "")).split(" was captured by ", 1)[1].split("!", 1)[0]
                d["summary"] = f"your {n.get('unit') or d.get('unit_type') or 'unit'}{where} was captured by {by}"
                for k in ("captor", "nearest_revealed_camp", "hint"):
                    if k in n:
                        d[k] = n[k]
                fought.add(d["unit"])
        starts = None
        for e in events:
            if e.get("kind") == "turn_start":
                in_my_turn = True
            elif e.get("kind") == "turn_end":
                in_my_turn = False
            elif (e.get("kind") == "unit_destroyed" and in_my_turn and isinstance(e.get("data"), dict)
                  and e["data"].get("player") == self.seat and e["data"].get("unit") not in fought):
                if starts is None:
                    try:
                        starts = {r.get("unit_id"): r for r in (self.q("return H.route_starts or {}") or [])}
                    except TunerdError:
                        starts = {}
                if e["data"].get("unit") in starts:
                    r = starts[e["data"]["unit"]]
                    e["kind"] = "trade_route_started"
                    e["data"]["summary"] = f"your {r.get('unit')} left on its trade route to {r.get('to')}"
                    continue
                e["kind"] = "unit_spent"
                e["data"]["note"] = "gone during your own turn with no combat: used up, upgraded (new unit id) or disbanded by your order"

        explained: set[int] = set(captured)
        for e in events:
            d = e.get("data")
            if e.get("kind") != "combat" or not isinstance(d, dict):
                continue
            att, dfn = d.get("attacker"), d.get("defender")
            for who, key in ((att, "att_unit"), (dfn, "def_unit")):
                if isinstance(who, dict) and who.get("owner") == "you":
                    explained.add(d.get(key))
            verb = "shot" if isinstance(att, dict) and att.get("ranged") else "attacked"
            d["summary"] = (f"{side(att, d.get('att_player'))} {verb} {side(dfn, d.get('def_player'))}: "
                            f"defender {outcome(dfn, d.get('def_dmg'))}; attacker {outcome(att, d.get('att_dmg'))}")
        # Quick combat (always on in multiplayer) fires no combat sim: the fight arrives as one `damage` row
        # per visible unit, followed by the game's own banner as an `alert` row that says who attacked whom.
        for e in events:
            d = e.get("data")
            if e.get("kind") != "damage" or not isinstance(d, dict):
                continue
            s = d.get("side") or {}
            if s.get("owner") == "you":
                explained.add(d.get("unit_id"))
            d["summary"] = f"{side(s, d.get('player'))} took {d.get('dmg')} damage: {outcome(s, d.get('dmg'))}"
        for e in events:
            d = e.get("data")
            if e.get("kind") == "civ_eliminated" and isinstance(d, dict):
                d["summary"] = (f"{d.get('civ')} ({d.get('leader')}) has been eliminated: its deals, friendships and "
                                f"votes are gone")
        # One disappearance, two rows (live t335: a caravan home from its route came as unit_lost, which explains
        # it, and unit_spent): keep the explained one.
        lost_ids = {e["data"].get("unit_id") for e in events if e.get("kind") == "unit_lost" and isinstance(e.get("data"), dict)}
        out = []
        for e in events:
            d = e.get("data")
            if e.get("kind") == "unit_spent" and isinstance(d, dict) and d.get("unit") in lost_ids:
                continue
            if e.get("kind") == "damage" and isinstance(d, dict) and d.get("unit_id") in fought:
                continue  # animations on: the combat row above already tells it
            if e.get("kind") in ("unit_hurt", "unit_lost") and isinstance(d, dict):
                if d.get("unit_id") in explained:
                    continue
                if e["kind"] == "unit_hurt":
                    d["summary"] = (f"your {d.get('unit')} ({d.get('x')},{d.get('y')}) lost {d.get('hp_before', 0) - d.get('hp', 0)} hp "
                                    f"between turns ({d.get('hp')} left) with no combat seen -- look around it with map_window")
                elif d.get("unit") in ("CARAVAN", "CARGO_SHIP"):
                    # live t324: a route ran out and the caravan came home to its city under a new unit id
                    d["summary"] = (f"your {d.get('unit')} last at ({d.get('x')},{d.get('y')}) is gone with no combat seen: "
                                    f"most likely its trade route ended and it is back home under a new id "
                                    f"(overview.idle_trade_units); a plundered route shows up as a notification")
                else:
                    d["summary"] = (f"your {d.get('unit')} last at ({d.get('x')},{d.get('y')}) is gone "
                                    f"(had {d.get('hp_before')} hp) with no combat seen")
            out.append(e)
        return out

    def events_peek(self, last_n: int = 50) -> list[dict]:
        return self.q(f"local e = H.events; local out = {{}}; for i = math.max(1, #e - {last_n} + 1), #e do out[#out+1] = e[i] end; return out")
