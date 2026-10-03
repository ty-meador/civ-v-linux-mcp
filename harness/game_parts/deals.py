"""Deals: the trade table (AI and human), incoming offers, proposing, negotiating and demanding, city-state gold gifts."""
from __future__ import annotations

import time

from ..client import TunerdError

from .support import lua_str


def _seeded_peace_table(rows: list[dict]) -> bool:
    """True when the table holds only what the screens seed for a peace deal: the treaty on both sides and,
    from us, peace with the other side's allied city-states (the engine adds their war allies to the treaty:
    live t206, Russia's table carried THIRD_PARTY_PEACE Almaty beside the pair, Portugal's Zurich, Riga, Kiev and
    Jerusalem, and the old all-PEACE_TREATY test refused both tables as 'already holds a deal' the first turn
    the Negotiate Peace button was lit)."""
    return bool(rows) and all(
        r.get("type") == "PEACE_TREATY" or (r.get("type") == "THIRD_PARTY_PEACE" and r.get("minor"))
        for r in rows) and any(r.get("type") == "PEACE_TREATY" for r in rows)


def _allied_minors(rows: list[dict]) -> list[dict]:
    """The city-states a seeded peace table makes peace with alongside the treaty."""
    return [{"player_id": r.get("other"), "name": r.get("other_name")}
            for r in rows if r.get("type") == "THIRD_PARTY_PEACE" and r.get("minor")]


class DealsMixin:
    """Deals: the trade table (AI and human), incoming offers, proposing, negotiating and demanding, city-state gold gifts.

    A part of harness.game.Game (see harness/game_parts/__init__.py); `self` is the whole Game."""

    def trade_catalog(self, other_player: int, pid: int | None = None) -> dict:
        """Items currently legal to put on a deal with `other_player` (IsPossibleToTradeItem only).
        Never Add*s. City-states are not trade-table deals — see city_state_gifts."""
        return self.q(f"return H.trade_catalog({other_player}, {self._pid(pid)})")

    def city_state_gifts(self, minor_id: int, pid: int | None = None) -> dict:
        """Gold-gift tiers and current friendship for a met city-state."""
        return self.q(f"return H.city_state_gifts({minor_id}, {self._pid(pid)})")

    def minor_gold_gift(self, minor_id: int, amount: int, pid: int | None = None) -> dict:
        """Gift the small/medium/large gold tier to a city-state (Game.DoMinorGoldGift). The engine applies
        the gift asynchronously, so this polls city_state_gifts until friendship/gold move (or ~3s) and
        reports before/after -- the first live call returned the pre-gift numbers (t250, Antwerp)."""
        before = self.city_state_gifts(minor_id, pid)
        r = self.q(f"return H.minor_gold_gift({minor_id}, {amount}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        after, _ = self._settle(lambda: self.city_state_gifts(minor_id, pid),
                                lambda a: a.get("friendship") != before.get("friendship") or a.get("gold") != before.get("gold"),
                                initial=before)
        r.update({"friendship_before": before.get("friendship"), "friendship": after.get("friendship"),
                  "friends": after.get("friends"), "allied": after.get("allied"), "gold": after.get("gold")})
        # Influence bought is not the same as the alliance bought: another major can be sitting above us
        # (live t231, Sidon 5 -> 80 for 1000 gold, Ethiopia still ally at 83). Say so in the result.
        ally = after.get("ally") if isinstance(after.get("ally"), dict) else {}
        if not after.get("allied") and ally.get("to_become_ally"):
            r["ally"] = ally
            if ally.get("none"):
                # Nobody holds the alliance: nothing was missed, the threshold is simply not reached yet (Grok,
                # 2026-09-27: `still_short` under ally.none read as a race lost to a rival that did not exist).
                r["to_become_ally"] = ally["to_become_ally"]
                r["note"] = (f"influence is now {after.get('friendship')}; no civ holds the alliance yet: "
                             f"{ally['to_become_ally']} more Influence makes us ally")
            else:
                r["still_short"] = ally["to_become_ally"]
                holder = ally.get("civ") or ("another civ I have not met" if ally.get("met") is False else None)
                r["note"] = (f"influence is now {after.get('friendship')} but "
                             + (f"{holder} still holds the alliance" if holder else "the alliance is not ours")
                             + f": {ally['to_become_ally']} more Influence needed")
        if after.get("friendship") == before.get("friendship") and after.get("gold") == before.get("gold"):
            r["note"] = "no change observed within 3s; re-read city_state_gifts to confirm"
        return r

    def incoming_deal(self, pid: int | None = None) -> dict:
        """Read the current scratch deal (empty, our draft, or an AI/human offer) without mutating it.
        Uses Deal:ResetIterator/GetNextItem, the same read tradelogic.lua's DisplayDeal uses.
        Never calls Add*/ClearItems/DoProposeDeal."""
        r = self.q(f"return H.incoming_deal({self._pid(pid)})")
        # An empty scratch deal still carries the last counterpart (live t452: to=3 Sweden while Venice was
        # offering friendship, no deal at all): say plainly that nothing is on the table.
        if isinstance(r, dict) and r.get("ok") and not r.get("items"):
            return {"ok": True, "pending": False, "items": [], "note": "no deal is on the table"}
        # A research agreement's price is not a deal item: each side pays it in gold when the deal is signed
        # (tradelogic.lua shows it from Game.GetResearchAgreementCost). Live t327: America's offer, 350 gold.
        if isinstance(r, dict) and r.get("ok"):
            us = self._pid(pid)
            other = r.get("to") if r.get("from") == us else r.get("from")
            for it in r.get("items", []):
                if it.get("type") == "RESEARCH_AGREEMENT" and it.get("from_us") and isinstance(other, int) and other >= 0:
                    try:
                        it["gold_cost"] = self.q(f"return Game.GetResearchAgreementCost({us}, {other})")
                        # The trade screen's own number; live t327 exactly 350 was charged (775 + 66 income - 350 = 491).
                        it["note"] = "both sides pay gold_cost on signing; the tech boost lands when the agreement expires"
                    except TunerdError:
                        pass
            # A renewal is the expiring deal put back on the table: its exports are still counted in
            # us_exported, so accepting leaves our own supply as it is (live t322: Dye owned 2, exported 1 --
            # read as "our last copy" and a Copper renewal refused for nothing; t334 the same on Gems).
            # The offer is a renewal when the AI's latest line to us says so.
            hist = []
            if isinstance(other, int) and other >= 0:
                try:
                    rel = self.relationship(other, pid)
                    hist = (rel.get("history") if isinstance(rel, dict) else None) or []
                except TunerdError:
                    pass
            last = hist[-1] if hist else {}
            if last.get("state") == "DIPLO_UI_STATE_TRADE_AI_MAKES_OFFER" and "renew" in str(last.get("text", "")).lower():
                r["renewal"] = True
                for it in r.get("items", []):
                    if it.get("from_us") and it.get("type") == "RESOURCES" and (it.get("us_exported") or 0) >= (it.get("amount") or 1):
                        # us_exported may count a DIFFERENT partner's export (live t385: America's Copper renewal,
                        # the 1 export running was Venice's). Say only what holds either way.
                        left = (it.get("us_total") or 0) - (it.get("amount") or 1)
                        if left >= 1:
                            it["note"] = f"renewal: even if the old export already ended, {left} copy stays in use (no happiness lost)"
                            it.pop("last_copy", None)
                        else:
                            it["note"] = ("renewal: no change if this export is still running; if it already ended, "
                                          "this takes the copy we use and its happiness")
        return r

    def accept_deal(self, pid: int | None = None) -> dict:
        """Accept an existing incoming offer already on the trade table. Does not construct a deal.

        If DiploTrade is open, this clicks the stock Accept button (OnPropose / OnPropose(ACCEPT_TYPE)).
        Otherwise it finalizes the current scratch deal via UI.DoFinalizePlayerDeal(them, us, true),
        which tradelogic.lua uses for PvP accept. Refuses if the scratch deal is empty.
        Do not use propose_deal to build a new offer -- that Add* path has crashed the process."""
        states = self.states()
        if self._trade_up(states):
            # Measured effects, same as propose_deal: what was on the table, before/after.
            table = self.incoming_deal(pid)
            items = table.get("items", []) if isinstance(table, dict) else []
            before = self._deal_snapshot(items, self._pid(pid))
            self.c.exec(
                self._trade_state,
                "OnPropose(3)" if self._trade_state == "SimpleDiploTrade" else "OnPropose()",
                check=False,
            )
            out = {"ok": True, "via": "DiploTrade.OnPropose", **self._settle_leader_remark()}
            after, _ = self._settle(lambda: self._deal_snapshot(items, self._pid(pid)),
                                    lambda a: a.get("deals") != before.get("deals"), initial=before)
            out["accepted_items"] = items
            out["effects"] = self._diff_snapshot(before, after)
            if after.get("deals") == before.get("deals"):
                out["note"] = "deal count unchanged within 3s; the AI may have withdrawn the offer -- check diplomacy/relationship"
            else:
                us = self._pid(pid)
                other = table.get("to") if table.get("from") == us else table.get("from")
                self._stamp_new_deal(out, items, us, other)
            if self.leader_greeting_pending():
                # A proposal to a HUMAN seat: the table closes back onto the leader scene ("Anything else?")
                # and the engine stays frozen behind it until Back is pressed, which a human does next. The
                # other seat finds the offer on its own turn (incoming_deal) -- live 2026-09-24 t226.
                self.dismiss_leader_greeting()
                out["leader_screen_closed"] = True
                out["note"] = ("proposed to a human seat: they see it as incoming_deal on their turn "
                               "and accept_deal / refuse_deal there")
            return out
        return self.q(f"return H.accept_deal({self._pid(pid)})")

    def _stamp_new_deal(self, out: dict, items: list[dict], us: int, other) -> None:
        """A renewal offer's rows carry the OLD deal's final turn: the engine clones the expiring deal onto the
        scratch table with its end stamped on every timed item, so `accepted_items` said final_turn t161,
        turns_left 0 for a deal that had just been signed to run to t186 (live t161 Venice, China's open-borders
        renewal; `current_deals` had the right row). Once the deal count has risen, the new deal is read off
        current_deals -- the row with this counterpart that starts this turn -- and its end replaces the rows'
        stale one (the offered value stays as `final_turn_offered`); `new_deal` carries the row itself."""
        if not isinstance(other, int) or other < 0:
            return
        try:
            cur = self.current_deals(us)
        except TunerdError:
            return
        if not isinstance(cur, dict) or not cur.get("ok"):
            # current_deals loads each deal onto the scratch table, so it refuses while a table is occupied --
            # which it is whenever another leader's offer is queued behind this one (live t186 on both seats:
            # China's and Portugal's renewals, first of two at a turn start, came back with no `new_deal` while
            # the last of each queue had one). The engine's deal runs the items' duration from this turn: say so
            # from that, marked inferred.
            d = self._inferred_new_deal(items, other)
            if d is None:
                return
        else:
            rows = [d for d in (cur.get("deals") or []) if d.get("other") == other
                    and isinstance(d.get("ends_on"), int) and isinstance(d.get("turns_left"), int)]
            if not rows:
                return
            turn = rows[0]["ends_on"] - rows[0]["turns_left"]
            new = [d for d in rows if d.get("start_turn") == turn] or [max(rows, key=lambda d: d["ends_on"])]
            d = max(new, key=lambda d: d["ends_on"])
        out["new_deal"] = {k: d.get(k) for k in ("other", "civ", "start_turn", "duration", "ends_on", "turns_left", "inferred")
                           if d.get(k) is not None}
        stale = False
        for it in items:
            if isinstance(it.get("final_turn"), int) and it["final_turn"] != d["ends_on"]:
                it["final_turn_offered"] = it["final_turn"]
                it["final_turn"], it["turns_left"] = d["ends_on"], d["turns_left"]
                stale = True
        if stale:
            out["renewal"] = True
            out["note"] = (f"renewal: the offer's rows carried the old deal's end; the new deal runs to turn "
                           f"{d['ends_on']} ({d['turns_left']} turns)")

    def _inferred_new_deal(self, items: list[dict], other: int) -> dict | None:
        """The deal just signed, worked out from the table rows when current_deals cannot be read: a timed deal
        starts this turn and runs the rows' `duration` (the engine's deal length), so a renewal offered with the
        old end stamped on it (final_turn = this turn, turns_left 0) runs to turn + duration."""
        durations = [it["duration"] for it in items if isinstance(it.get("duration"), int) and it["duration"] > 0]
        if not durations:
            return None
        try:
            turn = self.q("return {turn = Game.GetGameTurn()}").get("turn")
        except TunerdError:
            return None
        if not isinstance(turn, int):
            return None
        dur = max(durations)
        return {"other": other, "start_turn": turn, "duration": dur, "ends_on": turn + dur, "turns_left": dur,
                "inferred": "current_deals could not be read (the next leader's offer holds the trade table); "
                            "the end is this turn plus the deal length"}

    def _settle_leader_remark(self, wait: float = 1.5) -> dict:
        """After answering a deal the AI leader usually replies with a one-line remark ("Very well.",
        "That is disappointing.") on the DiscussionDialog. When that remark offers no response buttons
        the only control is Back, so it is closed here; a remark WITH buttons (apologise / dismiss /
        threaten) is a real choice and is returned as `follow_up` for respond_discussion()."""
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            time.sleep(0.3)
            d = self.discussion()
            if d.get("screen") == "discussion":
                if not d.get("buttons") and d.get("can_go_back"):
                    self.dismiss_discussion()
                    time.sleep(0.3)
                    return {"remark": d.get("speech"), "remark_dismissed": True}
                return {"remark": d.get("speech"), "follow_up": d}
        return {}

    def refuse_deal(self, pid: int | None = None) -> dict:
        """Refuse an existing incoming offer already on the trade table. Does not construct a deal.

        If DiploTrade is open, this clicks the stock Refuse/Back button. Otherwise
        UI.DoFinalizePlayerDeal(them, us, false). Empty scratch deal is an error, not a no-op."""
        states = self.states()
        if self._trade_up(states):
            self.c.exec(
                self._trade_state,
                "OnBack(1)" if self._trade_state == "SimpleDiploTrade" else "OnBack()",
                check=False,
            )
            return {"ok": True, "via": "DiploTrade.OnBack", **self._settle_leader_remark()}
        return self.q(f"return H.refuse_deal({self._pid(pid)})")

    def current_deals(self, pid: int | None = None) -> dict:
        """Diplomacy Overview current deals with turns remaining. Refuses if the scratch table is occupied."""
        return self.q(f"return H.current_deals({self._pid(pid)})")

    # ------------------------------------------------------------ trade deals (driven through the real UI)
    # Every earlier attempt built the deal headlessly on UI.GetScratchDeal() and crashed the game (eight
    # crashes across 2026-09-16, see docs/NOTES.md "Phase 3a" and its follow-ups). Root cause, confirmed
    # live 2026-09-17: the native deal-mutation calls (Add*/DoProposeDeal) need an actual trade session open
    # in the engine -- the one the leader screen's Trade button starts via Players[ai]:DoTradeScreenOpened()
    # + UI.OnHumanOpenedTradeScreen(ai). With that session open, the very same Add* calls (made through
    # tradelogic.lua's own pocket handlers, exactly what a mouse click runs) and UI.DoProposeDeal() work,
    # and the AI answers through the normal AILeaderMessage path. So this drives the real screens:
    #   DoBeginDiploWithHuman(other) -> LeaderHeadRoot.OnTrade() -> DiploTrade pocket handlers ->
    #   DiploTrade.OnPropose() -> read the reply -> close everything back down.
    # Every step is verified (right leader on screen, right counterpart on the table, every requested item
    # actually on the table at the requested amount) because the engine clamps or drops silently: adding a
    # resource the other side does not own puts it on the table at amount 0, and opening a second trade
    # while the previous leader screen is still up talks to the OLD counterpart (a free Copper went to
    # Venice that way during development).
    _DEAL_ITEM_TYPES = ("GOLD", "GOLD_PER_TURN", "RESOURCES", "OPEN_BORDERS", "DEFENSIVE_PACT",
                        "RESEARCH_AGREEMENT", "TRADE_AGREEMENT", "ALLOW_EMBASSY", "CITIES", "VOTE_COMMITMENT",
                        "THIRD_PARTY_WAR", "THIRD_PARTY_PEACE", "PEACE_TREATY")

    _TRADE_PROMPT = "What do you propose?"

    def _leader_up(self, states=None) -> bool:
        return bool(self._screens().get("leader_head_root_up"))

    # The trade table lives in two contexts: DiploTrade (behind a leader scene, AI deals) and
    # SimpleDiploTrade (the plain PvP table; same tradelogic.lua included, plus the Modify button the
    # PvP button row needs -- DiploTrade's XML lacks it and its PvP branch throws). _trade_state is
    # whichever one is up, and every trade-flow exec goes there (GitLab #4).
    _trade_state = "DiploTrade"

    def _trade_up(self, states=None) -> bool:
        # _screens() records which table is up in _trade_state as a side effect.
        return bool(self._screens().get("trade_state"))

    def _discussion_up(self, states=None) -> bool:
        return bool((self._screens().get("screens") or {}).get("DiscussionDialog"))

    def _trade_text(self) -> str:
        out = self.c.exec(self._trade_state, "print(Controls.DiscussionText:GetText())", check=False)
        return out[0] if out else ""

    def close_trade_screens(self, timeout: float = 8.0) -> dict:
        """Back out of whatever the trade flow left open: the trade table (DiploTrade.OnBack, which also
        tells the AI the screen closed), a leader remark with no choices (DiscussionDialog Back) and the
        leader screen itself (LeaderHeadRoot.OnReturn). A remark WITH response buttons is a real decision
        and is returned as `follow_up` instead of being dismissed."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            states = self.states()
            if self._trade_up(states):
                # the PvP table wants CANCEL_TYPE (0) to clear its draft; the AI table takes no argument
                self.c.exec(self._trade_state, "OnBack(0)" if self._trade_state == "SimpleDiploTrade" else "OnBack()", check=False)
            elif self._discussion_up(states):
                d = self.discussion()
                if d.get("screen") == "discussion" and d.get("buttons"):
                    return {"closed": False, "follow_up": d}
                self.c.exec("DiscussionDialog", "OnBack(true)", check=False)
            elif self._leader_up(states):
                self.c.exec("LeaderHeadRoot", "OnReturn()", check=False)
            else:
                self.c.exec("InGame", "H.harness_diplo = nil", check=False)
                return {"closed": True}
            time.sleep(0.5)
        self.c.exec("InGame", "H.harness_diplo = nil", check=False)
        return {"closed": False, "err": "trade/leader screens did not close in time",
                "trade_up": self._trade_up(), "discussion_up": self._discussion_up(), "leader_up": self._leader_up()}

    def _deal_snapshot(self, items: list[dict], pid: int) -> dict:
        res = sorted({i["resource"] for i in items if i.get("type") == "RESOURCES" and i.get("resource")})
        res_lua = ", ".join(f"{lua_str(r)}" for r in res)
        return self.q(f"""
            local p = Players[{pid}]
            local out = {{gold = p:GetGold(), gold_per_turn = p:CalculateGoldRate(), happiness = p:GetExcessHappiness(),
                         deals = UI.GetNumCurrentDeals({pid}), resources = {{}}}}
            for _, r in ipairs({{{res_lua}}}) do
                local id = GameInfoTypes[r]
                if id then out.resources[r] = {{available = p:GetNumResourceAvailable(id, true),
                                               imported = p:GetResourceImport(id), exported = p:GetResourceExport(id)}} end
            end
            return out""")

    @staticmethod
    def _diff_snapshot(before: dict, after: dict) -> dict:
        eff = {k: {"before": before[k], "after": after[k]} for k in ("gold", "gold_per_turn", "happiness", "deals")
               if before.get(k) != after.get(k)}
        # an empty Lua table decodes as [] (live t286: accept_deal on a Research Agreement crashed here)
        for r, b in (before.get("resources") or {}).items():
            a = (after.get("resources") or {}).get(r, {})
            if a != b:
                eff[r] = {"before": b, "after": a}
        return eff

    def _open_pvp_trade_screen(self, other: int, pid: int) -> dict:
        """The deal screen between two humans (tradelogic.lua OnOpenPlayerDealScreen, what the diplo
        corner's "trade" button fires for a human): no leader scene, the DiploTrade context opens
        straight onto an empty table (or the proposal already pending between the two seats), with
        g_bPVPTrade set so Propose/Accept/Refuse take the PvP branch (GitLab #4)."""
        self._trade_state = "SimpleDiploTrade"
        self.c.exec("SimpleDiploTrade", f"OnOpenPlayerDealScreen({other})", check=False)
        if not self._wait_until(self._trade_up, 6.0):
            return {"ok": False, "err": "the PvP deal screen did not open (a proposal to another player may be outstanding)"}
        time.sleep(0.3)
        # tradelogic.lua keeps g_bPVPTrade / g_iThem as file locals, so the counterpart is read off the
        # scratch deal the screen just set up (SetFromPlayer(us) / SetToPlayer(them), or the pending
        # proposal it loaded).
        ends = self.q("local d = UI.GetScratchDeal(); return { from_p = d:GetFromPlayer(), to_p = d:GetToPlayer(), n = d:GetNumItems() }")
        pair = {ends.get("from_p"), ends.get("to_p")} if isinstance(ends, dict) else set()
        if pair != {pid, other}:
            self.close_trade_screens()
            return {"ok": False, "err": "the deal screen opened for a different counterpart", "got": ends}
        table = self.incoming_deal(pid)
        if table.get("pending"):
            self.close_trade_screens()
            return {"ok": False, "err": "that seat's own proposal is on the table; answer it with accept_deal/refuse_deal first", "table": table}
        rows = table.get("items", [])
        # At war the screen itself seeded TRADE_ITEM_PEACE_TREATY on both sides (tradelogic.lua
        # OnOpenPlayerDealScreen): the table is still new, and whatever goes on it now is a peace deal (GitLab #5).
        peace = bool(rows) and _seeded_peace_table(rows)
        return {"ok": True, "pvp": True, "new_deal": not ends.get("n") or peace, "peace": peace or None, "table": table}

    def _open_trade_screen(self, other: int, pid: int, demand: bool = False) -> dict:
        """Leader screen -> Trade button, verified: the leader on screen is `other` and the table's
        counterpart is `other`. Refuses (and closes up) on any mismatch. `demand` presses the Demand
        button instead (leaderheadroot.lua OnDemand -> UI.OnHumanDemand: the same DiploTrade table in
        DIPLO_UI_STATE_HUMAN_DEMAND with our pocket hidden; GitLab #6)."""
        states = self.states()
        if self._trade_up(states) or self._discussion_up(states) or self._leader_up(states):
            closed = self.close_trade_screens()
            if not closed.get("closed"):
                return {"ok": False, "err": "another leader/trade screen is open and could not be closed", **closed}
        chk = self.q(f"""
            local o = Players[{other}]
            if not o or not o:IsAlive() then return {{ok=false, err="no such player"}} end
            if o:IsMinorCiv() then return {{ok=false, err="city-states are not trade-table deals; use minor_gold_gift"}} end
            if not Teams[Players[{pid}]:GetTeam()]:IsHasMet(o:GetTeam()) then return {{ok=false, err="have not met this player"}} end
            local pending = UI.HasMadeProposal({pid})
            if pending ~= -1 and pending ~= {other} then return {{ok=false, err="a proposal to another player is already outstanding", pending_to=pending}} end
            return {{ok=true, human=o:IsHuman() and true or false}}""")
        if not chk.get("ok"):
            return chk
        if chk.get("human"):
            if demand:
                return {"ok": False, "err": "demands are made to AI leaders only: there is no leader screen for a human seat (propose_deal sends them a table instead)"}
            return self._open_pvp_trade_screen(other, pid)
        # Mark leader chatter from here until the screens close as provoked by us (turn_digest hides it).
        self.c.exec("InGame", f"H.harness_diplo = true; UI.SetRepeatActionPlayer({other}); UI.ChangeStartDiploRepeatCount(1); Players[{other}]:DoBeginDiploWithHuman()")
        if not self._wait_until(self._leader_up, 6.0):
            self.c.exec("InGame", "H.harness_diplo = nil", check=False)
            return {"ok": False, "err": "leader screen did not open"}
        time.sleep(0.3)
        # GameplayUtilities (localized leader title) only exists inside UI contexts, so compare in there.
        head = self.c.exec("LeaderHeadRoot", f"local want = GameplayUtilities.GetLocalizedLeaderTitle(Players[{other}]); "
                           "print(Controls.TitleText:GetText(), tostring(Controls.TradeButton:IsDisabled()), Controls.LeaderSpeech:GetText(), want)", check=False)
        title, disabled, speech, want = (head[0].split("\t") + ["", "", "", ""])[:4] if head else ("", "", "", "")
        if not title or title != want:
            self.close_trade_screens()
            return {"ok": False, "err": "leader screen shows a different leader", "expected": want, "got": title}
        at_war = self.q(f"return Teams[Players[{pid}]:GetTeam()]:IsAtWar(Players[{other}]:GetTeam()) and true or false") is True
        peace = False
        if demand:
            # leaderheadroot.lua OnShowHide: the Demand button is hidden only for our own team and greyed at war
            # (alongside Trade and Discuss). Read the real button rather than re-deriving its rule.
            btn = self.c.exec("LeaderHeadRoot", "print(tostring(Controls.DemandButton:IsHidden()), tostring(Controls.DemandButton:IsDisabled()))", check=False)
            hidden, d_disabled = (btn[0].split("\t") + ["", ""])[:2] if btn else ("", "")
            if hidden == "true" or d_disabled == "true" or at_war:
                self.close_trade_screens()
                return {"ok": False, "err": "the Demand button is unavailable on this leader screen" + (" (at war)" if at_war else ""),
                        "leader_says": speech}
            self.c.exec("LeaderHeadRoot", "OnDemand()", check=False)
            if not self._wait_until(self._trade_up, 6.0):
                self.close_trade_screens()
                return {"ok": False, "err": "the demand table did not open", "leader_says": speech}
            time.sleep(0.3)
            table = self.incoming_deal(pid)
            if table.get("n") or table.get("items"):
                self.close_trade_screens()
                return {"ok": False, "err": "the trade table already holds a deal with this player; answer it with accept_deal/refuse_deal first", "table": table}
            return {"ok": True, "demand": True, "leader_says": self._trade_text()}
        if at_war:
            # leaderheadroot.lua OnShowHide: at war the Trade button is disabled and the War button reads Negotiate
            # Peace -- hidden when CanChangeWarPeace is false, greyed with TXT_KEY_DIPLO_NEGOTIATE_PEACE_BLOCKED_TT
            # while locked into war. OnWarOrPeace fires HUMAN_NEGOTIATE_PEACE; the AI then opens the trade table with
            # a peace treaty already on both sides, or answers on the leader screen instead (GitLab #5).
            btn = self.c.exec("LeaderHeadRoot", "print(tostring(Controls.WarButton:IsHidden()), tostring(Controls.WarButton:IsDisabled()), "
                              "tostring(Controls.WarButton.GetToolTipString and Controls.WarButton:GetToolTipString() or ''))", check=False)
            hidden, war_disabled, tip = (btn[0].split("\t") + ["", "", ""])[:3] if btn else ("", "", "")
            if hidden == "true" or war_disabled == "true":
                self.close_trade_screens()
                return {"ok": False, "err": "peace cannot be negotiated with this leader right now (the Negotiate Peace button is unavailable)",
                        "reason": tip, "leader_says": speech}
            self.c.exec("LeaderHeadRoot", "OnWarOrPeace()", check=False)

            def peace_answered():
                s = self.states()
                return self._trade_up(s) or self._discussion_up(s)
            self._wait_until(peace_answered, 8.0)
            time.sleep(0.3)
            states = self.states()
            if not self._trade_up(states):
                says = speech
                if self._discussion_up(states):
                    says = self.discussion().get("speech") or says
                elif self._leader_up(states):
                    out = self.c.exec("LeaderHeadRoot", "print(Controls.LeaderSpeech:GetText())", check=False)
                    says = out[0] if out else says
                closed = self.close_trade_screens()
                res = {"ok": False, "err": "this leader will not negotiate peace right now", "leader_says": says, "closed": closed.get("closed")}
                if closed.get("follow_up"):
                    res["follow_up"] = closed["follow_up"]
                return res
            peace = True
        else:
            if disabled == "true":
                self.close_trade_screens()
                return {"ok": False, "err": "this leader will not trade right now (Trade button disabled)", "leader_says": speech}
            self.c.exec("LeaderHeadRoot", "OnTrade()", check=False)
            if not self._wait_until(self._trade_up, 6.0):
                self.close_trade_screens()
                return {"ok": False, "err": "trade table did not open", "leader_says": speech}
        time.sleep(0.3)
        table = self.incoming_deal(pid)
        # An empty table reads {"pending": false, "items": []} with no to/from (live t107: every propose_deal to
        # Ethiopia was refused as "a different player"); the leader-title check above already pinned who it is.
        empty = not table.get("n") and not table.get("items")
        if not empty and table.get("to") != other and table.get("from") != other:
            self.close_trade_screens()
            return {"ok": False, "err": "trade table is with a different player", "table": table}
        if table.get("n"):
            rows = table.get("items", [])
            if peace and _seeded_peace_table(rows):
                res = {"ok": True, "peace": True, "leader_says": self._trade_text(), "table": table}
                minors = _allied_minors(rows)
                if minors:
                    res["allied_minors"] = minors
                return res
            # The AI already had a deal loaded (e.g. an offer it made to us earlier). Never build on it.
            self.close_trade_screens()
            return {"ok": False, "err": "the trade table already holds a deal with this player; answer it with accept_deal/refuse_deal first", "table": table}
        if peace:
            self.close_trade_screens()
            return {"ok": False, "err": "the peace table opened without a treaty on it", "table": table}
        return {"ok": True, "leader_says": self._trade_text()}

    def _check_deal_items(self, other: int, items: list[dict], pid: int, demand: bool = False) -> dict:
        """Legality before any screen opens, with the same IsPossibleToTradeItem checks the UI uses to grey
        out pocket entries (trade_catalog), so the caller learns WHY instead of "it silently did not land".
        `demand`: the leader screen's Demand button (GitLab #6). tradelogic.lua hides OUR pocket in
        DIPLO_UI_STATE_HUMAN_DEMAND, so only their items may go on the table, and leaderheadroot.lua greys
        the button at war (the same OnShowHide that greys Trade), so a demand is never a peace deal."""
        catalog = self.trade_catalog(other, pid)
        if not catalog.get("ok"):
            return catalog
        cat_res = {r["resource"]: r for r in catalog.get("resources", [])}
        peace = catalog.get("peace") or {}
        if demand:
            if catalog.get("at_war") or peace.get("at_war"):
                return {"ok": False, "err": "at war with this player: the Demand button is disabled (Negotiate Peace is the only table; see make_peace)"}
            for it in items:
                if not isinstance(it, dict):
                    return {"ok": False, "err": f"each item must be an object like {{\"type\": ..., \"from_us\": false}}, got {it!r}"}
                if it.get("type") == "PEACE_TREATY":
                    return {"ok": False, "err": "a demand carries no peace treaty (not at war)"}
                if it.get("from_us", True):
                    return {"ok": False, "err": f"a demand lists only what THEY hand over (from_us: false); {it.get('type')} was marked as ours -- "
                                                "the screen hides our own pocket in demand mode"}
        if peace.get("at_war") and not peace.get("ok"):
            # At war the screens seed a peace treaty on both sides of any table (tradelogic.lua OnOpenPlayerDealScreen;
            # the engine after HUMAN_NEGOTIATE_PEACE), so every deal is a peace deal and the leader screen's Negotiate
            # Peace gate applies to all of it (GitLab #5).
            return {"ok": False, "err": "at war with this player and peace cannot be negotiated right now"
                                        + (f": {peace['note']}" if peace.get("note") else ""), "peace": peace}
        for it in items:
            if not isinstance(it, dict):
                return {"ok": False, "err": f"each item must be an object like {{\"type\": ..., \"from_us\": ...}}, got {it!r}"}
            t = it.get("type")
            if t not in self._DEAL_ITEM_TYPES:
                return {"ok": False, "err": f"unsupported item type {t!r}; supported: {list(self._DEAL_ITEM_TYPES)}"}
            side = "us" if it.get("from_us", True) else "them"
            me_them = "me" if side == "us" else "them"
            i_they = "I" if side == "us" else "they"
            amount = it.get("amount")
            if t in ("GOLD", "GOLD_PER_TURN", "RESOURCES") and amount is not None:
                # The trade screen clamps a typed amount to what the side has before the engine sees it
                # (tradelogic.lua ChangeGoldAmount / ChangeGoldPerTurnAmount / ChangeResourceAmount). Refuse
                # out-of-range amounts here instead of letting them reach ChangeGoldTrade & co.
                if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
                    return {"ok": False, "err": f"{t} amount must be a positive whole number, got {amount!r}"}
                if t in ("GOLD", "GOLD_PER_TURN"):
                    avail = (catalog.get({"GOLD": "gold", "GOLD_PER_TURN": "gold_per_turn"}[t]) or {}).get(f"{side}_available")
                    if isinstance(avail, (int, float)) and amount > avail:
                        return {"ok": False, "err": f"{t} amount {amount} exceeds what {i_they} can put on the table right now ({int(avail)})",
                                "available": int(avail)}
            if t == "RESOURCES":
                r = it.get("resource", "")
                r = r if r.startswith("RESOURCE_") else "RESOURCE_" + r
                entry = cat_res.get(r)
                if not entry or not entry.get(side):
                    who = "I" if side == "us" else "they"
                    return {"ok": False, "err": f"{r} cannot be traded from {me_them} to this player right now "
                                                f"(the receiving side already has it, or {who} have no spare copy of it)",
                            "tradeable_resources": [{"resource": k, "from_me": v.get("us"), "from_them": v.get("them")} for k, v in cat_res.items()]}
                avail = entry.get(f"{side}_available")
                if amount is not None and isinstance(avail, (int, float)) and amount > avail:
                    return {"ok": False, "err": f"{r} amount {amount} exceeds the {int(avail)} copies {i_they} can trade", "available": int(avail)}
            elif t == "CITIES":
                # OnChooseCity -> deal:AddCityTrade(player, id) is unconditional in tradelogic.lua; the real UI
                # only offers cities that pass IsPossibleToTradeItem(TRADE_ITEM_CITIES, x, y). Same gate here.
                cities = (catalog.get("cities") or {}).get(side) or []
                city_id = it.get("city_id")
                if isinstance(city_id, bool) or not isinstance(city_id, int):
                    return {"ok": False, "err": "CITIES needs an integer city_id (see cities() / trade_catalog().cities)",
                            "tradeable_cities": cities}
                if city_id not in {c.get("id") for c in cities}:
                    return {"ok": False, "err": f"city {city_id} is not tradeable from {me_them} to this player right now "
                                                "(not owned by that side, or the game does not allow trading it)",
                            "tradeable_cities": cities}
            elif t == "PEACE_TREATY":
                # No pocket button exists for this: the treaty is on the table the moment a screen opens while at
                # war, and cannot be put there at peace. Listing it only states the intent (make_peace does).
                if not peace.get("at_war"):
                    return {"ok": False, "err": "PEACE_TREATY: not at war with this player", "peace": peace}
            elif t in ("THIRD_PARTY_WAR", "THIRD_PARTY_PEACE"):
                # The Other Players pocket (tradelogic.lua ShowOtherPlayerChooser) greys out every leader that fails
                # IsPossibleToTradeItem(from, to, type, team); LeaderSelected -> AddThirdPartyWar/Peace is then
                # unconditional. trade_catalog().third_party is that list with the screen's reasons (GitLab #6).
                kind = "war" if t == "THIRD_PARTY_WAR" else "peace"
                rows = ((catalog.get("third_party") or {}).get(kind) or {}).get(side) or []
                who = it.get("other")
                if isinstance(who, bool) or not isinstance(who, int):
                    return {"ok": False, "err": f"{t} needs an integer `other` player id (see trade_catalog().third_party.{kind})",
                            "third_party": rows}
                row = next((r for r in rows if r.get("player") == who), None)
                if row is None:
                    return {"ok": False, "err": f"player {who} is not on the Other Players list for this deal (unmet by one side, or one of the two parties)",
                            "third_party": rows}
                if not row.get("ok"):
                    return {"ok": False, "err": f"{t} against {row.get('name') or who} from {me_them} is greyed out on the trade screen"
                                                + (f": {row['note']}" if row.get("note") else ""),
                            "third_party": rows}
            elif t == "VOTE_COMMITMENT":
                # The Pocket Votes list (tradelogic.lua RefreshPocketVotes) only offers (proposal, choice) pairs
                # that pass IsPossibleToTradeItem for that direction; trade_catalog().vote_commitments is that
                # list. OnChoosePocketVote -> AddVoteCommitment is unconditional, so the gate lives here (GitLab #7).
                votes = catalog.get("vote_commitments") or []
                rid, cid, repeal = it.get("resolution_id"), it.get("choice_id"), bool(it.get("repeal", False))
                if any(isinstance(v, bool) or not isinstance(v, int) for v in (rid, cid)):
                    return {"ok": False, "err": "VOTE_COMMITMENT needs integer resolution_id and choice_id "
                                                "(see trade_catalog().vote_commitments / league_status)",
                            "tradeable_votes": votes}
                match = next((v for v in votes if v.get("resolution_id") == rid and v.get("choice_id") == cid
                              and bool(v.get("repeal")) == repeal), None)
                if not match or not match.get(side):
                    return {"ok": False, "err": f"that vote commitment cannot be traded from {me_them} to this player right now "
                                                "(no such pending proposal/choice, or the World Congress does not allow it)",
                            "tradeable_votes": votes}
            else:
                key = {"GOLD": "gold", "GOLD_PER_TURN": "gold_per_turn", "OPEN_BORDERS": "open_borders", "DEFENSIVE_PACT": "defensive_pact",
                       "RESEARCH_AGREEMENT": "research_agreement", "TRADE_AGREEMENT": "trade_agreement", "ALLOW_EMBASSY": "embassy"}[t]
                flag = catalog.get(key)
                if isinstance(flag, dict) and not flag.get(side):
                    return {"ok": False, "err": f"{t} from {'me' if side == 'us' else 'them'} is not legal with this player right now (see trade_catalog)",
                            "catalog": {key: flag}}
        return {"ok": True}

    def _add_deal_items(self, other: int, items: list[dict], pid: int) -> dict:
        """Put each item on the open table through tradelogic.lua's own pocket handlers, then read the table
        back and check every item is there at the amount asked for."""
        dur = "Game.GetDealDuration()"
        placed_pairs: set[str] = set()
        for it in items:
            t = it.get("type")
            from_us = bool(it.get("from_us", True))
            is_us = 1 if from_us else 0
            who = pid if from_us else other
            amount = it.get("amount")
            if t in ("DEFENSIVE_PACT", "RESEARCH_AGREEMENT", "TRADE_AGREEMENT"):
                # tradelogic.lua's pocket handler for these puts the PAIR on the table in one press (a row from
                # each side); an item of the type from the other side pressed it again -- live t196 Venice's
                # research agreement with England held two pairs and cost 468 gold instead of 234.
                if t in placed_pairs:
                    continue
                placed_pairs.add(t)
            # Amounts go through the same clamp the trade screen applies to a typed number (tradelogic.lua
            # ChangeGoldAmount & co.), so the engine never sees more than the side has. _check_deal_items already
            # refused out-of-range requests; this is the second fence, and the read-back below still refuses
            # a clamped amount instead of proposing it.
            if t == "GOLD":
                code = f"PocketGoldHandler({is_us})"
                if amount is not None:
                    code += (f"; local d = UI.GetScratchDeal(); local a = math.min({int(amount)}, d:GetGoldAvailable({who}, TradeableItems.TRADE_ITEM_GOLD));"
                             f" d:ChangeGoldTrade({who}, a); DisplayDeal()")
            elif t == "GOLD_PER_TURN":
                code = f"PocketGoldPerTurnHandler({is_us})"
                if amount is not None:
                    code += (f"; local d = UI.GetScratchDeal(); local a = math.min({int(amount)}, Players[{who}]:CalculateGoldRate());"
                             f" d:ChangeGoldPerTurnTrade({who}, a, {dur}); DisplayDeal()")
            elif t == "RESOURCES":
                r = it.get("resource", "")
                if not r.startswith("RESOURCE_"):
                    r = "RESOURCE_" + r
                code = f"local rid = GameInfoTypes[{lua_str(r)}]; if not rid then error('unknown resource {r}') end; PocketResourceHandler({is_us}, rid)"
                if amount is not None:
                    code += (f"; local d = UI.GetScratchDeal(); local a = math.min({int(amount)}, d:GetNumResource({who}, rid));"
                             f" d:ChangeResourceTrade({who}, rid, a, {dur}); DisplayDeal()")
            elif t == "CITIES":
                # Re-check on the live table right before the unconditional AddCityTrade (the catalog check ran
                # before the screen opened); a Lua error here is a clean refusal, never an engine call.
                city_id = int(it.get("city_id", -1))
                to = other if from_us else pid
                code = (f"local c = Players[{who}]:GetCityByID({city_id}); if not c then error('no such city {city_id}') end;"
                        f" if not UI.GetScratchDeal():IsPossibleToTradeItem({who}, {to}, TradeableItems.TRADE_ITEM_CITIES, c:GetX(), c:GetY())"
                        f" then error('city {city_id} is not tradeable') end; OnChooseCity({who}, {city_id})")
            elif t in ("THIRD_PARTY_WAR", "THIRD_PARTY_PEACE"):
                # tradelogic.lua: the Declare War / Make Peace pocket button opens the leader chooser
                # (ShowOtherPlayerChooser(isUs, WAR=0|PEACE=1), file locals) and a leader click is LeaderSelected.
                mode = 0 if t == "THIRD_PARTY_WAR" else 1
                code = f"ShowOtherPlayerChooser({is_us}, {mode}); LeaderSelected({int(it['other'])}, {is_us})"
            elif t == "PEACE_TREATY":
                # Already on both sides of the table (seeded by the screen / the engine); nothing to press.
                code = None
            elif t == "VOTE_COMMITMENT":
                # tradelogic.lua's pocket entry: UpdateLeagueVotes fills g_LeagueVoteList (a global of the trade
                # state), GetLeagueVoteIndexFromData finds the (id, choice, repeal) row, OnChoosePocketVote adds it
                # with the committing side's GetCoreVotesForMember. A missing row is a Lua error, never an Add.
                rid, cid = int(it["resolution_id"]), int(it["choice_id"])
                rep = "true" if it.get("repeal") else "false"
                code = (f"UpdateLeagueVotes(); local idx = GetLeagueVoteIndexFromData({rid}, {cid}, {rep});"
                        f" if not idx then error('vote commitment {rid}/{cid} is not in the pocket') end; OnChoosePocketVote({who}, idx)")
            else:
                handler = {"OPEN_BORDERS": "PocketOpenBordersHandler", "DEFENSIVE_PACT": "PocketDefensivePactHandler",
                           "RESEARCH_AGREEMENT": "PocketResearchAgreementHandler", "TRADE_AGREEMENT": "PocketTradeAgreementHandler",
                           "ALLOW_EMBASSY": "PocketAllowEmbassyHandler"}[t]
                code = f"{handler}({is_us})"
            if code is None:
                continue
            try:
                self.c.exec(self._trade_state, code)
            except TunerdError as e:
                return {"ok": False, "err": f"could not add {t}: {e}"}
            time.sleep(0.2)
        table = self.incoming_deal(pid)
        got = list(table.get("items", []))
        missing = []
        for it in items:
            t = it["type"]
            from_us = bool(it.get("from_us", True))
            want_res = it.get("resource", "")
            if want_res.startswith("RESOURCE_"):
                want_res = want_res[len("RESOURCE_"):]
            match = None
            for g in got:
                if g.get("type") != t or bool(g.get("from_us")) != from_us:
                    continue
                if t == "RESOURCES" and g.get("resource") != want_res:
                    continue
                if t in ("THIRD_PARTY_WAR", "THIRD_PARTY_PEACE") and g.get("other") != it.get("other"):
                    continue
                if t == "VOTE_COMMITMENT" and (g.get("resolution_id") != it.get("resolution_id") or g.get("choice_id") != it.get("choice_id")
                                               or bool(g.get("repeal")) != bool(it.get("repeal", False))):
                    continue
                if t in ("DEFENSIVE_PACT", "RESEARCH_AGREEMENT", "TRADE_AGREEMENT") and match is not None:
                    continue
                match = g
                break
            if match is None:
                missing.append({"requested": it, "reason": "not on the table (engine refused it silently)"})
                continue
            if t in ("GOLD", "GOLD_PER_TURN", "RESOURCES"):
                want = it.get("amount", 1 if t == "RESOURCES" else None)
                if match.get("amount", 0) <= 0 or (want is not None and match.get("amount") != want):
                    missing.append({"requested": it, "on_table": match.get("amount"),
                                    "reason": "amount clamped by the engine (side does not have that much / any)"})
            got.remove(match)
        if missing:
            return {"ok": False, "err": "not every item made it onto the table as requested", "problems": missing, "table": table}
        return {"ok": True, "table": table}

    def demand(self, other_player: int, items: list[dict], pid: int | None = None) -> dict:
        """The leader screen's Demand button (GitLab #6): ask an AI to hand over `items` for nothing, through the
        real screens. leaderheadroot.lua OnDemand -> UI.OnHumanDemand opens the trade table in
        DIPLO_UI_STATE_HUMAN_DEMAND (our pocket hidden, the Propose button reads DEMAND), tradelogic.lua
        OnPropose then calls UI.DoDemand() and the leader answers on the spot. `items` take propose_deal's
        shapes with from_us false (gold, gold per turn, resources, cities, open borders...). AI-only: the
        button does not exist for a human seat, and it is greyed at war. A refused demand is remembered by
        that leader's AI (it worsens their opinion), exactly as in the stock game."""
        return self.propose_deal(other_player, [dict(i, from_us=False) if isinstance(i, dict) and "from_us" not in i else i for i in items],
                                 pid=pid, demand=True)

    def propose_deal(self, other_player: int, items: list[dict], ask_counter: bool = False, pid: int | None = None,
                     demand: bool = False) -> dict:
        """Propose a trade to an AI through the game's real trade screen, wait for the answer, close the
        screens and report what actually changed. `items`: list of
          {"type": "RESOURCES", "resource": "RESOURCE_DYE", "from_us": true, "amount": 1}
          {"type": "GOLD", "from_us": false, "amount": 120}   {"type": "GOLD_PER_TURN", "from_us": true, "amount": 5}
          {"type": "OPEN_BORDERS"|"ALLOW_EMBASSY"|"DEFENSIVE_PACT"|"RESEARCH_AGREEMENT"|"TRADE_AGREEMENT", "from_us": bool}
          {"type": "CITIES", "from_us": true, "city_id": 123}
          {"type": "VOTE_COMMITMENT", "from_us": true, "resolution_id": 5, "choice_id": 1, "repeal": false}
          {"type": "THIRD_PARTY_WAR"|"THIRD_PARTY_PEACE", "from_us": true, "other": 23}   (player id of the third party)
          {"type": "PEACE_TREATY"}   (at war only; the screens seed it on both sides themselves -- see make_peace)
        Returns {ok, accepted, reply, table, effects}. `effects` is measured (gold, gold/turn, happiness,
        deal count, per-resource import/export before vs after), not inferred from the reply text. With
        `ask_counter=True` a rejection is followed by the AI's own "what would make this work" counter
        (`counter.items` / `counter.reply`) so the caller can re-propose without another round trip.
        Nothing is proposed if any item fails to land on the table at the requested amount."""
        pid = self._pid(pid)
        if len(items) == 0:
            return {"ok": False, "err": "no items in deal"}
        legal = self._check_deal_items(other_player, items, pid, demand=demand)
        if not legal.get("ok"):
            return legal
        before = self._deal_snapshot(items, pid)
        opened = self._open_trade_screen(other_player, pid, demand=demand)
        if not opened.get("ok"):
            return opened
        added = self._add_deal_items(other_player, items, pid)
        if not added.get("ok"):
            added["closed"] = self.close_trade_screens().get("closed")
            return added
        if opened.get("pvp"):
            # Two humans: Propose sends the table to the other seat (UI.DoProposeDeal) and the screen
            # closes; nothing is answered until that seat's turn. Report the pending proposal, not a
            # verdict (GitLab #4).
            # tradelogic.lua keeps PROPOSE_TYPE & co. as file locals: pass the numbers (1 propose, 2 withdraw, 3 accept)
            self.c.exec(self._trade_state, "OnPropose(1)", check=False)
            self._wait_until(lambda: not self._trade_up(), 6.0)
            time.sleep(0.3)
            pending_to = self.q(f"return UI.HasMadeProposal({pid})")
            out = {"ok": True, "pvp": True, "accepted": None, "pending": pending_to == other_player,
                   "pending_to": pending_to, "table": added["table"],
                   "note": "sent to a human seat: they see it in incoming_deal / turn_status on their turn and answer with accept_deal or refuse_deal"}
            if opened.get("peace"):
                out["peace"] = True
                out["note"] = ("peace with terms sent to a human seat: the treaty is on both sides of the table; "
                               "they answer with accept_deal or refuse_deal on their turn")
            closed = self.close_trade_screens()
            out["closed"] = closed.get("closed")
            return out
        baseline = self._trade_text()
        self.c.exec(self._trade_state, "OnPropose()", check=False)
        reply = baseline
        def answered():
            nonlocal reply
            states = self.states()
            if not self._trade_up(states) or self._discussion_up(states):
                return True
            reply = self._trade_text()
            return reply != baseline
        self._wait_until(answered, 8.0)
        time.sleep(0.3)
        states = self.states()
        if self._discussion_up(states):
            d = self.discussion()
            reply = d.get("speech") or reply
        elif self._trade_up(states):
            reply = self._trade_text()
        after = self._deal_snapshot(items, pid)
        accepted = after.get("deals", 0) > before.get("deals", 0)
        out = {"ok": True, "accepted": accepted, "reply": reply, "table": added["table"]}
        if demand:
            out["demand"] = True
        if opened.get("peace"):
            # A peace deal is a deal too (the count above moves), and the war state is the fact that matters.
            out["peace"] = True
            out["at_war"] = self.q(f"return Teams[Players[{pid}]:GetTeam()]:IsAtWar(Players[{other_player}]:GetTeam()) and true or false") is True
            if not out["at_war"]:
                accepted = out["accepted"] = True
        if not accepted and ask_counter and self._trade_up():
            out["counter"] = self._ask_ai(pid, "OnEqualizeDeal()", added["table"])
        closed = self.close_trade_screens()
        out["closed"] = closed.get("closed")
        if closed.get("follow_up"):
            out["follow_up"] = closed["follow_up"]
        out["effects"] = self._diff_snapshot(before, self._deal_snapshot(items, pid))
        return out

    def _ask_ai(self, pid: int, call: str, table_before: dict) -> dict:
        """Run one of tradelogic.lua's AI-assist buttons on the open table and return what the AI put
        there: OnEqualizeDeal ("what would make this deal work?"), OnWhatWillAIGive, OnWhatDoesAIWant."""
        text_before = self._trade_text()
        self.c.exec(self._trade_state, call, check=False)
        changed = lambda: self.incoming_deal(pid) != table_before or self._trade_text() != text_before
        self._wait_until(changed, 6.0)
        time.sleep(0.3)
        table = self.incoming_deal(pid)
        return {"reply": self._trade_text(), "items": table.get("items", []), "changed": table != table_before}

    def negotiate_deal(self, other_player: int, items: list[dict], mode: str = "equalize", pid: int | None = None) -> dict:
        """Ask the AI about a deal WITHOUT proposing it, then close the screens. `items` as in propose_deal.
        mode: "equalize" (put a draft on the table, ask what would make it acceptable),
              "what_will_ai_give" (only my items on the table; the AI fills in its side),
              "what_does_ai_want" (only their items on the table; the AI fills in what it wants from me).
        Returns the AI's reply and the resulting table (`items`), ready to pass back to propose_deal."""
        pid = self._pid(pid)
        calls = {"equalize": "OnEqualizeDeal()", "what_will_ai_give": "OnWhatWillAIGive()", "what_does_ai_want": "OnWhatDoesAIWant()"}
        if mode not in calls:
            return {"ok": False, "err": f"mode must be one of {list(calls)}"}
        if mode == "what_will_ai_give" and any(not i.get("from_us", True) for i in items):
            return {"ok": False, "err": "what_will_ai_give takes only my items (from_us=true)"}
        if mode == "what_does_ai_want" and any(i.get("from_us", True) for i in items):
            return {"ok": False, "err": "what_does_ai_want takes only their items (from_us=false)"}
        legal = self._check_deal_items(other_player, items, pid)
        if not legal.get("ok"):
            return legal
        human = self.q(f"local o = Players[{int(other_player)}]; return o and o:IsHuman() and true or false")
        if human:
            return {"ok": False, "err": "no AI to ask: this counterpart is a human seat; propose_deal sends the table for them to accept or refuse"}
        opened = self._open_trade_screen(other_player, pid)
        if not opened.get("ok"):
            return opened
        table = {"items": []}
        if items:
            added = self._add_deal_items(other_player, items, pid)
            if not added.get("ok"):
                added["closed"] = self.close_trade_screens().get("closed")
                return added
            table = added["table"]
        asked = self._ask_ai(pid, calls[mode], table)
        closed = self.close_trade_screens()
        return {"ok": True, "mode": mode, **asked, "closed": closed.get("closed")}
