"""Empire-wide reads: overview, units, cities, map windows, tactical view, comparisons, the reference and notifications."""
from __future__ import annotations



from .support import lua_str, plain_text


class ReadsMixin:
    """Empire-wide reads: overview, units, cities, map windows, tactical view, comparisons, the reference and notifications.

    A part of harness.game.Game (see harness/game_parts/__init__.py); `self` is the whole Game."""

    def summary(self, pid: int | None = None) -> dict:
        r = self.q(f"return H.player_summary({self._pid(pid)})")
        # A slot with no trade unit in it earns nothing and nothing else says so (live t354: Railroad raised
        # the cap 6 -> 7). used counts caravans/cargo ships, idle or not, so free = cap - used.
        if isinstance(r, dict) and isinstance(r.get("trade_routes_available"), int) and isinstance(r.get("trade_routes_used"), int):
            free = r["trade_routes_available"] - r["trade_routes_used"]
            idle = len(r.get("idle_trade_units") or [])
            if free > 0:
                r["free_trade_route_slots"] = free
                # used counts running routes, not trade units: a free slot may already have an idle caravan
                # waiting for a route, and the engine trains no trade unit beyond the slots (live t139)
                if idle >= free:
                    r["trade_note"] = (f"{idle} idle caravan(s) / cargo ship(s) already cover the free slot(s): give them "
                                       "routes (available_trade_routes then establish_trade_route); do not build another")
                elif idle:
                    r["trade_note"] = (f"{idle} idle trade unit(s) cover {idle} of the {free} free slot(s): route them "
                                       f"first, then build or buy a Caravan / Cargo Ship for the other {free - idle}")
                else:
                    r["trade_note"] = "build or buy a Caravan / Cargo Ship to fill the free slot(s)"
        # An unassigned spy is the espionage version of the idle caravan above: it costs nothing and
        # earns nothing, and after the notification that announced it the game never mentions it again.
        if isinstance(r, dict) and r.get("idle_spies"):
            r["spy_note"] = ("unassigned spies do nothing: available_spy_cities(agent_id) then "
                             "move_spy to steal tech / rig a city-state election / defend a city")
        return r

    def units(self, pid: int | None = None) -> list[dict]:
        return self.q(f"return H.units({self._pid(pid)})")

    def cities(self, pid: int | None = None) -> list[dict]:
        rows = self.q(f"return H.cities({self._pid(pid)})")
        for c in rows if isinstance(rows, list) else []:
            if isinstance(c, dict):
                self._normalize_production_turns(c)
        return rows

    def city_screen(self, city_id: int, pid: int | None = None) -> dict:
        """City-view contents for one of my cities: buildings, specialists + GP meters, worked tiles,
        production queue, citizen focus, avoid-growth, buyable plots (and the red price of a tile
        this city cannot afford), and the corner meters (food, production, culture-to-border,
        gold/science/faith/tourism). cities() is the banner list."""
        r = self.q(f"return H.city_screen({int(city_id)}, {self._pid(pid)})")
        if isinstance(r, dict):
            self._normalize_production_turns(r)
        return r

    @staticmethod
    def _normalize_production_turns(row: dict) -> dict:
        """INT_MAX turns means empty queue or a process. Only a process is 'never completes'
        (live t179: Goshute's empty queue was labelled as Wealth/Research)."""
        turns = row.get("production_turns")
        if isinstance(turns, int) and turns >= 2**31 - 1:
            row["production_turns"] = None
            prod = (row.get("production") or "").strip()
            if not row.get("production_note") and prod and not row.get("needs_production"):
                row["production_note"] = "ongoing process: converts production every turn, never completes"
        return row

    def great_person_progress(self, pid: int | None = None) -> dict:
        return self.q(f"return H.great_person_progress({self._pid(pid)})")

    def demographics(self, pid: int | None = None) -> dict:
        return self.q(f"return H.demographics({self._pid(pid)})")

    def culture_works(self, pid: int | None = None) -> dict:
        return self.q(f"return H.culture_works({self._pid(pid)})")

    def set_swappable_great_work(self, work_class: str, work_id: int = -1, pid: int | None = None) -> dict:
        """The swap tab's pull-down for one class (writing / art / artifact): put one of our works up for
        swapping, or -1 to clear the spot (Network.SendSetSwappableGreatWork)."""
        return self.q(f"return H.set_swappable_great_work({lua_str(work_class)}, {int(work_id)}, {self._pid(pid)})")

    def swap_great_works(self, their_work_id: int, pid: int | None = None) -> dict:
        """The Swap button: exchange our put-up work of the same class for `their_work_id`, an offer
        listed in culture_works().swap.theirs (Network.SendSwapGreatWorks)."""
        return self.q(f"return H.swap_great_works({int(their_work_id)}, {self._pid(pid)})")

    def domination_progress(self, pid: int | None = None) -> dict:
        return self.q(f"return H.domination_progress({self._pid(pid)})")

    def wonder_overview(self, pid: int | None = None) -> dict:
        return self.q(f"return H.wonder_overview({self._pid(pid)})")

    def plots_around(self, x: int, y: int, r: int = 3) -> list[dict]:
        if not 0 <= r <= 12:
            raise ValueError("radius must be between 0 and 12")
        return self.q(f"return H.plots_around({x}, {y}, {r}, Players[{self.seat}]:GetTeam())")

    def explore_frontier(self, unit_id: int, pid: int | None = None, limit: int = 12) -> dict:
        """Where the known map ends for one unit: revealed, passable plots of its domain (water for a
        ship, land otherwise, both when embarked) that touch unrevealed plots, nearest first. The fog
        edge a human sees on the minimap; nothing beyond it is read."""
        if not 1 <= int(limit) <= 100:
            raise ValueError("limit must be between 1 and 100")
        return self.q(f"return H.explore_frontier({int(unit_id)}, {self._pid(pid)}, {int(limit)})")

    TACTICAL_DETAILS = ("summary", "full")

    def tactical_view(self, unit_id: int, radius: int = 2, detail: str = "summary", pid: int | None = None) -> dict:
        """One bounded read around one unit (#31): its six neighbours by coordinate with what move_unit would do
        there (the same checks move_unit makes; no path cost or turns, which the engine cannot give safely), river
        crossings, visible occupants and known cities within `radius`, fog counts, the unit's attack targets with
        the existing combat previews, and a lettered grid with its legend. detail="full" adds every revealed plot
        in radius as map_window reads it and keeps the previews' modifier rows."""
        if not 1 <= int(radius) <= 5:
            raise ValueError("radius must be between 1 and 5")
        if detail not in self.TACTICAL_DETAILS:
            raise ValueError(f"detail must be one of {self.TACTICAL_DETAILS}")
        return self.q(f"return H.tactical_view({int(unit_id)}, {self._pid(pid)}, {int(radius)}, {lua_str(detail)})")

    def compare(self, kind: str, city_id: int | None = None, unit_id: int | None = None,
                candidates: list[str] | None = None, plots: list[list[int]] | None = None, sort: str | None = None,
                limit: int | None = None, detail: str = "summary", pid: int | None = None) -> dict:
        """A few caller-chosen candidates side by side from one read (#34; harness/compare.py): production items in
        one city, techs, worker builds on plots, or a caravan's trade destinations. Engine answers, table effects,
        estimates and their assumptions are separate fields; every field names its source."""
        from .. import compare as C
        err = C.validate(kind, city_id=city_id, unit_id=unit_id, candidates=candidates, plots=plots, sort=sort,
                         limit=limit, detail=detail)
        if err:
            return {"ok": False, "err": err}
        seat = self._pid(pid)
        raw = self.q(C.lua_call(kind, seat, city_id=city_id, unit_id=unit_id, candidates=candidates, plots=plots,
                                detail=detail), timeout=120)
        args = {"pid": seat, "city_id": city_id, "unit_id": unit_id, "candidates": list(candidates or [])}
        return C.shape(kind, raw, args, detail=detail, limit=limit, sort=sort)

    def known_world(self, pid: int | None = None) -> dict:
        """Everything this seat currently knows: own empire/units/cities, met civs
        (including city-states), notifications, and every revealed plot.

        Each plot has vis=true (in sight now) or vis=false (discovered, currently
        fogged). Fogged plots omit units, owners, improvements, cities, and features.
        Unrevealed tiles are omitted entirely.
        """
        return self.q(f"return H.known_world({self._pid(pid)})")

    def map_index(self, pid: int | None = None) -> dict:
        """Compact map scan: revealed luxuries/strategics, camps, ruins, met foreign
        cities, visible natural wonders, and in-sight world wonders. Prefer this over
        known_world when you do not need every plot."""
        return self.q(f"return H.map_index({self._pid(pid)})")

    REVEALED_MAP_LAYERS = ("vis", "terrain", "elevation", "river", "owner", "feature", "improvement", "resource", "route")

    def revealed_map(self, layers: list[str] | None = None, x0: int | None = None, y0: int | None = None,
                     x1: int | None = None, y1: int | None = None, pid: int | None = None) -> dict:
        """The revealed map as character grids, one byte per plot per layer (a Huge map after Satellites
        is ~10 KB a layer). `vis` separates plots in sight ('#') from revealed-but-fogged ('~'), whose
        contents are what was last seen and may be stale. Fog rules match describe_plot: a fogged
        feature is the remembered one or '?', improvement/route/owner are the engine's Revealed* values,
        live occupants and pillage marks appear on visible plots only. Legends are built per reply."""
        if layers is not None:
            bad = [l for l in layers if l not in self.REVEALED_MAP_LAYERS]
            if bad:
                return {"ok": False, "err": f"unknown layer(s) {bad}", "layers": list(self.REVEALED_MAP_LAYERS)}
        lua_layers = "nil" if not layers else "{" + ", ".join(lua_str(l) for l in layers) + "}"
        args = ", ".join("nil" if v is None else str(int(v)) for v in (x0, y0, x1, y1))
        return self.q(f"return H.revealed_map({self._pid(pid)}, {lua_layers}, {args})", timeout=120)

    # ------------------------------------------------------------ reference (the rule book)
    def reference(self) -> dict:
        """The static rule book: every help sentence the stock UI shows for units, buildings, techs,
        policies, promotions, beliefs, resources, terrain, improvements, specialists and unit actions,
        read from this game's database (H.reference) once per process and cached -- the words never
        change mid-game. Since v216 no other read repeats them (harness/reference.py)."""
        cached = getattr(self, "_reference", None)
        if cached is None:
            cached = self.q("return H.reference()", timeout=240)
            if not isinstance(cached, dict):
                return {"ok": False, "err": f"unexpected reference reply {cached!r}"}
            if not cached.get("ok"):
                return cached
            self._reference = cached
        return cached

    def reference_markdown(self, section: str | None = None) -> str | dict:
        """The rule book as Markdown, whole or one section; a dict is a refusal (unknown section, or the
        game could not be read). The whole book is also written beside the notebooks for the human."""
        from ..reference import SECTIONS, render_markdown
        if section is not None and section not in SECTIONS:
            return {"ok": False, "err": f"unknown reference section {section!r}", "sections": list(SECTIONS)}
        data = self.reference()
        if not data.get("ok"):
            return data
        text = render_markdown(plain_text(data), section)
        if section is None:
            self._save_reference(text)
        return text

    def _save_reference(self, text: str) -> None:
        """A copy for humans at $XDG_DATA_HOME/civ5-harness/reference/<game>.md (same root as the
        notebooks). Best effort: a failed copy never fails the read."""
        if getattr(self, "_reference_saved", False):
            return
        try:
            from ..notes import notes_dir, safe_key
            path = notes_dir().parent / "reference" / (safe_key(self.game_key()) + ".md")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            self._reference_saved = True
            self.reference_path = str(path)
        except Exception:  # noqa: BLE001 -- the disk copy is a convenience
            pass

    def notifications(self, pid: int | None = None) -> list[dict]:
        return self.q(f"return H.notifications({self._pid(pid)})")

    def notification_log(self, limit: int = 40, include_dismissed: bool = True,
                         pid: int | None = None) -> dict:
        """The Notification Log popup: everything the gamecore still holds, newest first, dismissed
        entries included. `notifications()` is only the ones the panel is still showing, so anything
        read once and dismissed had nowhere to be read again."""
        r = self.q(f"return H.notification_log({self._pid(pid)}, {int(limit)}, "
                   f"{'true' if include_dismissed else 'false'})")
        return plain_text(r)

    def spaceship_status(self, pid: int | None = None) -> dict:
        """Space race: Apollo done, each part's needed / in-ship / built-not-delivered count and prerequisite tech,
        and met rivals that finished Apollo with their part count (the Victory Progress screen)."""
        return self.q(f"return H.spaceship_status({self._pid(pid)})")

    def culture_overview(self, pid: int | None = None) -> dict:
        """Culture Overview screen: per met major civ, influential_on/needed for a culture victory, tourism, and
        its influence level/percent/tourism-per-turn/trend on each other major (unmet ones as "unknown")."""
        return self.q(f"return H.culture_overview({self._pid(pid)})")

    def available_production(self, city_id: int, pid: int | None = None) -> dict:
        """Units/buildings/projects/processes this city can put at the head of its queue right now."""
        return self.q(f"return H.available_production({city_id}, {self._pid(pid)})")

    # ------------------------------------------------------------ more actions (added after a live crash
    # from an unguarded raw lua() probe for city_ranged_attack -- these follow the game's own validated
    # call paths, see docs/NOTES.md for the Lua source each one is derived from)
    def plot_units(self, x: int, y: int, pid: int | None = None) -> dict:
        """Units (and city) on one plot as my team sees it right now -- {visible, units:[{id,owner,type,hp}], city?}."""
        return self.q(f"return H.plot_units({x}, {y}, Players[{self._pid(pid)}]:GetTeam())")
