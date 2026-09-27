"""Espionage: spies, intrigue, tech theft and coups."""
from __future__ import annotations

import time

from .support import lua_str, plain_text


class EspionageMixin:
    """Espionage: spies, intrigue, tech theft and coups.

    A part of harness.game.Game (see harness/game_parts/__init__.py); `self` is the whole Game."""

    def espionage_intrigue(self, pid: int | None = None) -> dict:
        return self.q(f"return H.espionage_intrigue({self._pid(pid)})")

    def spies(self, pid: int | None = None) -> dict:
        """My spies: agent_id, name, rank, state (TXT_KEY_SPY_STATE_...), city_name/city_owner (where
        stationed -- may be my own city for counter-intel), turns_left/percent_complete for the current
        activity, is_diplomat, established_surveillance, and can_stage_coup (see stage_coup). Spies do NOT
        use the unit-mission system -- see available_spy_cities/move_spy/stage_coup for actions."""
        return self.q(f"return H.spies({self._pid(pid)})")

    def available_spy_cities(self, agent_id: int, pid: int | None = None) -> list[dict]:
        """Cities a given spy (agent_id, from spies()) could be sent to right now -- my own cities (for
        counter-intelligence) and other civs'/city-states' cities (to steal tech or, for a city-state,
        eventually rig an election via stage_coup once surveillance is established). `potential` is the
        real UI's displayed success-chance percent. Pass `target_player_id` and `city_id` (as move_spy's `target_city_id`) into
        move_spy."""
        return self.q(f"return H.available_spy_cities({agent_id}, {self._pid(pid)})")

    def move_spy(self, agent_id: int, target_player_id: int, target_city_id: int,
                 as_diplomat: bool = False, pid: int | None = None) -> dict:
        """Assign or relocate a spy (see available_spy_cities for valid target_player_id/target_city_id).
        Recall a spy home instead: target_player_id=-1, target_city_id=-1. `as_diplomat` only matters when
        the target is another MAJOR civ's capital while not at war with them -- the real UI offers a
        spy-vs-diplomat choice there; leave it False for anywhere else (city-states, non-capital cities)."""
        r = self.q(f"return H.move_spy({agent_id}, {target_player_id}, {target_city_id}, "
                   f"{'true' if as_diplomat else 'false'}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        # After-state: the spy's entry from spies() (state is now "Travelling" / the new city), so the
        # caller need not re-read the whole list to confirm the order took.
        time.sleep(0.3)
        for s in self.spies(pid) or []:
            if isinstance(s, dict) and s.get("agent_id") == agent_id:
                r["spy"] = s
                break
        return r

    def stage_coup(self, agent_id: int, pid: int | None = None) -> dict:
        """Attempt a coup against a city-state's current ally with a spy that has established surveillance
        there (see spies()'s can_stage_coup). Gated by the same Player:CanSpyStageCoup check the real UI's
        button uses; a refusal carries `why_not` (spy_dead / surveillance_pending / no_ally / we_are_ally).
        On success `chance` is the percent the confirm printed and `outcome` the notification the coup
        produced (success or failure), read once the engine has handled the net message."""
        r = self.q(f"return H.stage_coup({agent_id}, {self._pid(pid)})")
        if not (isinstance(r, dict) and r.get("ok")):
            return r
        held_before = r.pop("held_before", None)
        if isinstance(held_before, int):
            log, seen = self._settle(lambda: self.q(f"return H.notification_log({self._pid(pid)}, 5, true)"),
                                     lambda lg: isinstance(lg, dict) and isinstance(lg.get("held"), int) and lg["held"] > held_before,
                                     timeout=6.0, poll=0.3)
            if seen:
                fresh = [e for e in log.get("notifications", []) if isinstance(e, dict) and e.get("i", -1) >= held_before]
                r["outcome"] = [plain_text(e.get("text") or e.get("summary") or "") for e in fresh]
            else:
                # live t270 Wittenberg: the coup resolved (ally flipped to us, spy row said we_are_ally)
                # without any notification inside 6s, so the ally is the result, not the log
                r["outcome"] = None
            # the result the screen shows: the city-state's ally afterwards (us on success; the old
            # ally, with our spy dead, on failure)
            owner = r.get("city_owner")
            if isinstance(owner, int):
                ally = self.q(f"local o = Players[{owner}]; return o and o:GetAlly() or -1")
                r["succeeded"] = (ally == self._pid(pid))
                r["ally_now"] = ally
        return r

    def steal_tech_options(self, pid: int | None = None) -> dict:
        """ENDTURN_BLOCKING_STEAL_TECH: which civs a spy has finished stealing from, and the techs
        (they have, I lack, prereqs met) I may take from each."""
        return self.q(f"return H.steal_tech_options({self._pid(pid)})")

    def steal_tech(self, tech: str, victim: int, pid: int | None = None) -> dict:
        """Take `tech` (TECH_...) from player `victim` to clear ENDTURN_BLOCKING_STEAL_TECH. Same net
        message as a free tech with the victim in SendResearch's 3rd slot; verified by re-reading
        IsHasTech / the blocking type since the engine never errors on a bad choice."""
        r = self.q(f"return H.steal_tech({lua_str(tech)}, {victim}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        for _ in range(10):
            time.sleep(0.3)
            chk = self.q(
                f"local p = Players[{self._pid(pid)}]; return {{has = Teams[p:GetTeam()]:IsHasTech(GameInfoTypes[{lua_str(tech)}]), "
                f"pending = p:GetNumTechsToSteal({victim}), blocking = H.blocking_name(p:GetEndTurnBlockingType())}}"
            )
            if chk.get("has"):
                # The grant raises BUTTONPOPUP_TECH_AWARD and ENDTURN_BLOCKING_STEAL_TECH stays set until
                # that popup is processed (live t219: blocker persisted with pending=0 until the sweep ran).
                swept = self.dismiss_pending_popups()
                after = self.q(f"return H.blocking_name(Players[{self._pid(pid)}]:GetEndTurnBlockingType())")
                return {"ok": True, "tech": tech, "victim": victim, "pending_after": chk.get("pending"),
                        "blocking": after, "popups_swept": swept}
        return {"ok": False, "err": "SendResearch accepted but the tech was not granted (wrong victim/tech?)", "check": chk}
