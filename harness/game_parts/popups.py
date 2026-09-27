"""Engine popups and screens: what is pending, what the harness closes itself, and the choosers (goody hut, city capture, archaeology, Maya, free Great Person)."""
from __future__ import annotations

import time

from ..client import TunerdError

from .support import POPUP_SHIM_LUA, lua_str, plain_text


class PopupsMixin:
    """Engine popups and screens: what is pending, what the harness closes itself, and the choosers (goody hut, city capture, archaeology, Maya, free Great Person).

    A part of harness.game.Game (see harness/game_parts/__init__.py); `self` is the whole Game."""

    # ------------------------------------------------------------ generic popups
    # GenericPopup is the Lua state behind every popupsgeneric/*Popup.lua yes/no confirmation
    # (return a captured civilian, annex/puppet a city, barbarian ransom, enter a city-state's land ...).
    # Its buttons are closures; harness/lua/generic_popup_shim.lua wraps AddButton so they can be
    # replayed. The shim must be in place *before* the popup is shown, hence it is installed with the
    # runtime and re-checked on every read.
    def ensure_popup_shim(self) -> bool:
        if getattr(self, "_popup_shim_ok", False):
            return True
        if not self.has_state("GenericPopup"):
            return False
        installed = self.c.query("GenericPopup", "return __H_BTN_SHIM == true and type(__H_answer_popup) == 'function'")
        if not installed:
            self.load_lua("GenericPopup", POPUP_SHIM_LUA.read_text(), "harness_popup_shim")
        self._popup_shim_ok = True
        return True

    def generic_popup(self, pid: int | None = None) -> dict:
        """What the open generic confirmation says and which buttons it offers."""
        if not self.ensure_popup_shim():
            return {"ok": True, "open": False, "note": "no GenericPopup state (not in a game)"}
        st = self.c.query("GenericPopup", "return __H_popup_state()")
        st["ok"] = True
        st["pending_popups"] = self.q(f"return H.pending_popups({self._pid(pid)})")
        if not st.get("open"):
            # A closed dialog still holds its XML placeholder text ("BLAH BLAH", live t374) -- not a question.
            st.pop("text", None)
            st.pop("buttons", None)
            st["note"] = ("no generic confirmation is open; pending_popups are announcement screens the harness "
                          "sweeps itself (end_turn / any action retries them)")
        if st.get("open") and st.get("buttons_shown", 0) > len(st.get("buttons") or []):
            st["note"] = ("this popup opened before the shim was installed, so its handlers are unknown: "
                          "answer it with `lua` in state GenericPopup (e.g. Network.SendReturnCivilian(...)) "
                          "and then HideWindow()")
        return st

    def answer_popup(self, button: int) -> dict:
        """Press button `button` (1-based, see generic_popup) of the open generic confirmation."""
        if not self.ensure_popup_shim():
            return {"ok": False, "err": "no GenericPopup state (not in a game)"}
        r = self.c.query("GenericPopup", f"return __H_answer_popup({int(button)})")
        if r.get("ok"):
            time.sleep(0.3)
            # e.g. returning a civilian makes its owner thank us on the leader screen
            r["discussion_pending"] = self.discussion_pending()
            r["pending_popups"] = self.turn_state().get("pending_popups", [])
        return r

    # ------------------------------------------------------------ hotseat seat handoff
    def player_change_pending(self, ts: dict | None = None) -> bool:
        """True when the hotseat 'pass the device' modal is up for our seat. A turn_state from runtime v215 on
        already carries the answer (`hand_off_pending`, read by H.hand_off_up in the same trip); without one
        this asks the PlayerChange state itself (two trips)."""
        if isinstance(ts, dict) and isinstance(ts.get("hand_off_pending"), bool):
            return ts["hand_off_pending"]
        try:
            pc = self.c.wait_state("PlayerChange", 1)
        except TunerdError:
            return False
        # ContextPtr:IsHidden() is unreliable for modals; the modal flag + visible container are.
        out = self.c.exec(pc, "print(tostring(UIManager:IsModal(ContextPtr) and not Controls.MainContainer:IsHidden()))", check=False)
        return bool(out) and out[0] == "true"

    def dismiss_player_change(self) -> None:
        pc = self.c.wait_state("PlayerChange", 5)
        self.c.exec(pc, "OnContinue()")

    def _visible_in_state(self, name: str, lua_return: str, known: dict[int, str] | None = None) -> bool:
        names = known.values() if known is not None else self.states().values()
        if name not in names:
            return False
        try:
            return bool(self.c.query(name, lua_return))
        except TunerdError:
            return False

    def _screens(self) -> dict:
        """Every popup / leader screen's up-or-down in one query (runtime v214 H.modal_flags): the five
        turn_state flags, `leader_head_root_up` (the engine's own flag), `trade_state` (which trade table is
        up, if one is) and `screens` {tuner state name: bool} for every context the runtime knows the path
        of (absent when not loaded). Before v214 each of these was a round-trip of its own through the
        tuner, ~0.37 s each: a turn_state cost eight, a popup sweep twenty-odd, and the profiled S1 t270
        turn spent 250 of its 278 trips (about 90 s) on them."""
        r = self.q("return H.modal_flags()")
        r = r if isinstance(r, dict) else {}
        if r.get("trade_state"):
            self._trade_state = r["trade_state"]
        return r

    def _modal_flags(self) -> dict[str, bool]:
        r = self._screens()
        return {k: bool(r.get(k)) for k in self.MODAL_FLAGS}

    def leader_greeting_pending(self) -> bool:
        """True when the LeaderHeadRoot popup is up. That popup only ever shows three informational
        states (see leaderheadroot.lua's `bMyMode` check): a first-contact/general greeting
        (DIPLO_UI_STATE_DEFAULT_ROOT), an echo of a war we just declared, or an echo of peace we just
        made -- none of them need a response, they're just acknowledged. An actual negotiation/demand
        goes through the separate DiscussionDialog/DiscussLeader states instead (not handled here;
        surfaced via turn_digest's `leader_message` events for `diplo_event`/`declare_war`/etc. to act
        on). This one blocks turn_state from ever reporting my_turn=true until dismissed -- confirmed
        live: wait_for_my_turn spun to its full timeout with my_turn stuck false while this was up,
        with no other signal that anything was wrong."""
        # After a proposal to a HUMAN seat the trade table closes back onto the leader scene ("Anything
        # else?", Back button showing) with the engine's flag already false -- and the engine's update
        # loop frozen behind it, so every notification stayed live and ENDTURN_BLOCKING_PRODUCTION named a
        # city whose queue was full (live 2026-09-24 t226, two-human hotseat). The scene itself is the
        # signal then; a real negotiation still counts as a discussion, not a greeting. Both rules live in
        # H.modal_flags now (one query for every screen).
        return self._modal_flags()["leader_greeting_pending"]

    def dismiss_leader_greeting(self) -> None:
        """Same call as leaderheadroot.lua's own Back button (OnReturn)."""
        lh = self.c.wait_state("LeaderHeadRoot", 5)
        self.c.exec(lh, "UIManager:DequeuePopup(ContextPtr); UI.SetLeaderHeadRootUp(false); UI.RequestLeaveLeader()")

    def city_state_greeting_pending(self) -> bool:
        """True when the "you have met the city-state of X" CityStateGreetingPopup is up. Purely
        informational (status/quest info + a Close/Find-on-map button, no decision to make) -- like
        LeaderHeadRoot, but for city-states rather than major civs, and NOT handled by
        leader_greeting_pending()/UI.GetLeaderHeadRootUp() at all (confirmed live: that check stayed
        false while this was visibly up). Also confirmed live: unlike LeaderHeadRoot, this does NOT
        block turn_state()'s my_turn -- end_turn() kept returning {ok:true} every call with
        blocking_before=-1 while this sat on screen, but the turn genuinely never advanced (score/culture
        static across ~19 repeated end_turn calls) -- DoControl(CONTROL_ENDTURN) silently no-ops while
        this popup's modal queue entry is active, with no engine-level signal distinguishing it from a
        real turn advance. Root-caused via a user screen report after `tech_popup_pending()` and every
        other known popup check came back false/hidden -- see docs/NOTES.md."""
        return self._modal_flags()["city_state_greeting_pending"]

    def dismiss_city_state_greeting(self) -> None:
        """Close the CityStateGreetingPopup. Its CloseButton:CallCallback() does nothing (confirmed
        live, with and without a Mouse.eLClick argument) -- unlike simple popups, this one's close
        handler isn't reachable that way, so this goes straight to ContextPtr:SetHide(true) instead,
        same as leader_greeting_pending's sibling. No SerialEventGameMessagePopupProcessed call needed
        (unlike dismiss_tech_popup) -- confirmed live this alone was enough to unstick end_turn."""
        cs = self.c.wait_state("CityStateGreetingPopup", 5)
        self.c.exec(cs, "ContextPtr:SetHide(true)", check=False)

    def great_person_reward_pending(self) -> bool:
        """True when GreatPersonRewardPopup (e.g. "you have earned a Great Scientist") is up. Same
        silent-block shape as city_state_greeting_pending(): purely informational, does not touch
        turn_state()'s my_turn, but end_turn() silently no-ops while it's on screen -- found the same
        way, scanning every known popup context's IsHidden() after a repeated-end_turn stall with no
        other popup pending. See city_state_greeting_pending() for the general pattern this follows."""
        return self._modal_flags()["great_person_reward_pending"]

    def dismiss_great_person_reward(self) -> None:
        """Close GreatPersonRewardPopup via ContextPtr:SetHide(true) -- confirmed live sufficient to
        unstick end_turn(), same as dismiss_city_state_greeting()."""
        gp = self.c.wait_state("GreatPersonRewardPopup", 5)
        self.c.exec(gp, "ContextPtr:SetHide(true)", check=False)

    # Purely-informational modal popups discovered live to share the exact same silent-block shape as
    # city_state_greeting_pending()/great_person_reward_pending(): end_turn()'s DoControl(CONTROL_ENDTURN)
    # no-ops while ANY of these sit on screen (repeated {ok:true} with no turn advance), and none of them
    # touch turn_state()'s my_turn the way LeaderHeadRoot/DiscussionDialog do, so there's no other signal.
    # Only two (CityStateGreetingPopup, GreatPersonRewardPopup) are live-confirmed as of this writing --
    # the rest are the same "announcement + OK/Close button, no real choice" shape by inspection of the
    # Lua state list and are swept defensively so the next one doesn't cost another multi-turn stall
    # before being found by hand. If one of these turns out to gate on something other than SetHide,
    # dismiss_pending_popups() will silently fail to unstick it -- same as any newly-discovered popup not
    # in this list yet, not a regression.
    _SWEEP_POPUP_STATES = (
        "GoldenAgePopup", "NaturalWonderPopup", "BarbarianCampPopup", "GoodyHutPopup",
        "WonderPopup", "NewEraPopup", "TechAwardPopup",
    )

    def dismiss_pending_popups(self, ts: dict | None = None) -> list[str]:
        """Close informational screens through their real callbacks, never child controls.

        `ts` is a turn_state the caller already holds (saves the read); any other value reads one.

        A child's IsHidden flag is local to that child, not effective visibility
        through its parents. Hiding those children corrupts future popup displays
        and skips DequeuePopup/turn-timer bookkeeping.
        """
        handlers = {
            "TechAwardPopup": "OnClose",
            "GreatWorkPopup": "OnClose", "WhosWinningPopup": "OnClose",
            "WonderPopup": "OnClose", "LeagueSplash": "OnClose",
            # BUTTONPOPUP_LEAGUE_PROJECT_COMPLETED (leagueprojectpopup.lua: OnClose -> DequeuePopup). Live t375:
            # the International Games result sat unswept and held the TECH_AWARD behind it; end_turn refused.
            "LeagueProjectPopup": "OnClose",
            # BUTTONPOPUP_NEW_ERA (newerapopup.lua: OnClose -> DequeuePopup). Was in _SWEEP_POPUP_STATES
            # but missing here, so it was never swept -- found live at the Classical era (China game, t63).
            "NewEraPopup": "OnClose",
            "GoldenAgePopup": "OnCloseButtonClicked",
            "NaturalWonderPopup": "OnCloseButtonClicked",
            "BarbarianCampPopup": "OnCloseButtonClicked",
            "GoodyHutPopup": "OnCloseButtonClicked",
            "GreatPersonRewardPopup": "OnCloseButtonClicked",
            "CityStateGreetingPopup": "OnCloseButtonClicked",
            # BUTTONPOPUP_TEXT: a plain message box with one Close button (textpopup.lua), e.g. "<player>
            # has disconnected" in LAN games. Found live 2026-09-17 blocking every action tool with
            # "popup needs a decision" after the other LLM's client crashed out of the game.
            "TextPopup": "OnCloseButtonClicked",
            # DeclareWarPopup hosts the generic yes/no confirmations from popupsgeneric/ (e.g.
            # BUTTONPOPUP_DECLAREWARMOVE "entering that territory would trigger war" after a move_unit into
            # a city-state's or rival's border). HideWindow() is its No/Escape path: the move is dropped,
            # no war is declared. The unit then still needs a real order. Found live 2026-09-17 (the other
            # LLM's warrior on the Deck seat sat behind it with ENDTURN_BLOCKING_UNITS unclearable).
            "DeclareWarPopup": "HideWindow",
        }
        if not (isinstance(ts, dict) and "active_player" in ts):
            ts = self.turn_state()
        if ts.get("active_player") != self.seat:
            return []
        dismissed = []
        for _ in range(5):
            count = len(dismissed)
            # v214: every screen's up/down in one query (was one tuner round-trip per popup context, ~14
            # of them, on every wait poll and every end_turn).
            sc = self._screens()
            up = sc.get("screens") or {}
            if sc.get("leader_greeting_pending") and not sc.get("discussion_pending"):
                self.dismiss_leader_greeting()
                dismissed.append("LeaderHeadRoot")
                time.sleep(0.15)
            for name, handler in handlers.items():
                if up.get(name):
                    self.c.exec(name, f"{handler}()")
                    time.sleep(0.15)
                    if not self.c.query(name, "return ContextPtr:IsHidden()"):
                        raise TunerdError(f"{name} did not close; needs attention")
                    if name == "DeclareWarPopup":
                        # HideWindow() (the No path) does not fire SerialEventGameMessagePopupProcessed, so
                        # the BUTTONPOPUP_DECLAREWAR* record in H.popups would otherwise stay forever and
                        # keep end_turn() refusing with "popup needs attention" (seen live 2026-09-17).
                        self.q('for k in pairs(H.popups) do local n = H.enum_name("popup", ButtonPopupTypes, k) or "" '
                               'if n:find("DECLAREWAR", 1, true) then H.popups[k] = nil end end return true')
                    dismissed.append(name)
            if sc.get("tech_popup_pending"):
                current = self.q(f"return Players[{self.seat}]:GetCurrentResearch()")
                if current != -1:
                    self.dismiss_tech_popup()
                    dismissed.append("TechPopup")
            if len(dismissed) != count:
                ts = self.turn_state()      # something closed: the popup records may have moved
            dismissed += self._drop_stale_popup_records(ts, up)
            if len(dismissed) == count:
                dismissed += self._process_orphaned_popups(handlers, ts, sc)
                break
        return dismissed

    def _process_orphaned_popups(self, handlers: dict[str, str], ts: dict | None = None,
                                 sc: dict | None = None) -> list[str]:
        """The engine is waiting on a popup (UI.IsPopupUp() true) that nothing draws: every popup context
        the harness knows is hidden, no leader screen is up, and H.popups still records an announcement
        type. The engine does not re-evaluate its end-turn blocker while it waits (GitLab #23: the
        CityStateGreeting record sat beside ENDTURN_BLOCKING_UNITS with an empty todo and the sweep, which
        only closes visible screens, had nothing to close). Tell the engine what the screen's own close
        button tells it -- SerialEventGameMessagePopupProcessed for that type -- and nothing else: no
        DequeuePopup on a context that is not queued, and never for a popup type with a decision in it
        (those are not in _POPUP_CONTEXTS)."""
        ts = ts if isinstance(ts, dict) else self.turn_state()
        pending = ts.get("pending_popups") or []
        pending = [p for p in pending if (p.get("name") or "") in self._POPUP_CONTEXTS]
        if not pending or not self.q("return UI.IsPopupUp()"):
            return []
        sc = sc if isinstance(sc, dict) else self._screens()
        if sc.get("leader_greeting_pending") or sc.get("discussion_pending"):
            return []
        up = sc.get("screens") or {}
        for ctx in set(self._POPUP_CONTEXTS.values()) | set(handlers):
            if up.get(ctx):
                return []
        states = set(self.states().values())
        processed = []
        for p in pending:
            # Exactly what the screen's close handler does (citystategreetingpopup.lua OnCloseButtonClicked
            # and its siblings): Processed for the type, then DequeuePopup on its own context -- a no-op
            # when the context was never queued, the right bookkeeping when it was queued and hidden.
            ctx = self._POPUP_CONTEXTS[p["name"]]
            lua = f"Events.SerialEventGameMessagePopupProcessed.CallImmediate({int(p['type'])}, 0)"
            if ctx in states:
                self.c.exec(ctx, lua + "; UIManager:DequeuePopup(ContextPtr)")
            else:
                self.q(lua + "; return true")
            self.q(f"H.popups[{int(p['type'])}] = nil; return true")
            processed.append(f"{p['name']} (orphaned: the engine waited on a popup nothing was drawing; processed)")
        return processed

    # Popup type -> the Lua context that draws it. H.popups records a type on SerialEventGameMessagePopupShown
    # and forgets it on ...PopupProcessed; a screen that goes away without firing Processed leaves a record
    # for a popup nobody can see, and every action then refuses with "popup needs a decision" for good.
    # Live 2026-09-24 t219 (two-human hotseat): the World Congress splash was queued during the hand-off,
    # its context was hidden with UI.IsPopupUp() false, and the record outlived it -- generic_popup itself
    # said "no generic confirmation is open" while set_production/unit_mission refused on the same record.
    _POPUP_CONTEXTS = {
        "BUTTONPOPUP_LEAGUE_SPLASH": "LeagueSplash",
        "BUTTONPOPUP_LEAGUE_PROJECT_COMPLETED": "LeagueProjectPopup",
        "BUTTONPOPUP_NEW_ERA": "NewEraPopup",
        "BUTTONPOPUP_TEXT": "TextPopup",
        "BUTTONPOPUP_CITY_STATE_GREETING": "CityStateGreetingPopup",
        "BUTTONPOPUP_NATURAL_WONDER_REWARD": "NaturalWonderPopup",
        "BUTTONPOPUP_GOLDEN_AGE_REWARD": "GoldenAgePopup",
        "BUTTONPOPUP_BARBARIAN_CAMP_REWARD": "BarbarianCampPopup",
        "BUTTONPOPUP_GOODY_HUT_REWARD": "GoodyHutPopup",
        "BUTTONPOPUP_WONDER_COMPLETED": "WonderPopup",
        "BUTTONPOPUP_TECH_AWARD": "TechAwardPopup",
        "BUTTONPOPUP_GREAT_PERSON_REWARD": "GreatPersonRewardPopup",
    }

    def _drop_stale_popup_records(self, ts: dict | None = None, up: dict | None = None) -> list[str]:
        """Forget H.popups records whose screen is not up: the context exists and is hidden, and the engine
        has no popup on screen at all. A record whose screen is merely queued behind a leader screen or
        another popup is left alone (UI.IsPopupUp() is true then, or the context is not hidden)."""
        ts = ts if isinstance(ts, dict) else self.turn_state()
        pending = ts.get("pending_popups") or []
        if not pending:
            return []
        if up is None:
            up = self._screens().get("screens") or {}
        dropped = []
        for p in pending:
            ctx = self._POPUP_CONTEXTS.get(p.get("name") or "")
            if not ctx or ctx not in up:        # not a loaded context: nothing to judge
                continue
            if up.get(ctx):                     # drawn: not stale
                continue
            if self.q("return UI.IsPopupUp()"):
                continue
            self.q(f"H.popups[{int(p['type'])}] = nil; return true")
            dropped.append(f"{p['name']} (stale record, screen already gone)")
        return dropped

    # TechPopup's real content, found live by enumerating pairs(Controls) on the running state --
    # techpopup.lua/xml gives none of them an all-encompassing container the way GreatWorkPopup's
    # GreatWorkSplashContainer does, so every one of them has to be hidden individually (same shape as
    # WonderPopup, whose splash/title/quote/icon/stats/close-button controls are its own similar list).
    _TECH_POPUP_CONTROLS = ("OpenTTButton", "ScrollPanel", "ButtonStack", "ScrollPanelBlackFrame", "ScrollPanelFrame", "TechBackground")

    def tech_popup_pending(self) -> bool:
        return self._modal_flags()["tech_popup_pending"]

    def dismiss_tech_popup(self) -> None:
        self.c.exec("TechPopup", "ClosePopup()")
        time.sleep(0.15)
        if self.tech_popup_pending():
            raise TunerdError("technology choice popup did not close; needs attention")

    def free_great_person_options(self, pid: int | None = None) -> dict:
        """How many free Great People are owed (ENDTURN_BLOCKING_FREE_ITEMS) and the unit types to pick from."""
        return self.q(f"return H.free_great_person_options({self._pid(pid)})")

    def maya_options(self, pid: int | None = None) -> dict:
        return self.q(f"return H.maya_options({self._pid(pid)})")

    def choose_maya_bonus(self, unit: str, pid: int | None = None) -> dict:
        r = self.q(f"return H.choose_maya_bonus({lua_str(unit)}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        for _ in range(12):
            time.sleep(0.25)
            r["remaining"] = self.maya_options(pid)["count"]
            if r["remaining"] < r["before"]:
                break
        r["ok"] = r["remaining"] < r["before"]
        if r["ok"]:
            if self._visible_in_state("ChooseMayaBonus", "return not ContextPtr:IsHidden()"):
                self.c.exec("ChooseMayaBonus", "ContextPtr:SetHide(true)")
            self.q("H.popups[ButtonPopupTypes.BUTTONPOPUP_CHOOSE_MAYA_BONUS] = nil; return true")
        else:
            r["err"] = "Maya reward was sent but the pending count did not decrease"
        return r

    def archaeology_options(self, pid: int | None = None) -> dict:
        seat = self._pid(pid)
        r = self.q(f"return H.archaeology_options({seat})")
        if r.get("pending") and r.get("unit_id") is None:
            # The engine does not publish the archaeologist ID until the completed-dig
            # notification is activated (the stock end-turn button follows this path).
            opened = self.q(f"""local p = Players[{seat}]
                if Game.GetActivePlayer() == {seat} and
                   p:GetEndTurnBlockingType() == EndTurnBlockingTypes.ENDTURN_BLOCKING_CHOOSE_ARCHAEOLOGY then
                  UI.ActivateNotification(p:GetEndTurnBlockingNotificationIndex()); return true
                end
                return false""")
            if opened:
                for _ in range(10):
                    time.sleep(0.2)
                    r = self.q(f"return H.archaeology_options({seat})")
                    if r.get("unit_id") is not None:
                        break
        return r

    def choose_archaeology(self, choice: int, x: int, y: int, pid: int | None = None) -> dict:
        self.archaeology_options(pid)
        r = self.q(f"return H.choose_archaeology({int(choice)}, {int(x)}, {int(y)}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        for _ in range(12):
            time.sleep(0.25)
            after = self.archaeology_options(pid)
            if after.get("ok") and (not after.get("pending") or (after.get("x"), after.get("y")) != (x, y)):
                break
        r["ok"] = bool(after.get("ok") and (not after.get("pending") or (after.get("x"), after.get("y")) != (x, y)))
        if r["ok"]:
            if self._visible_in_state("ChooseArchaeologyPopup", "return not ContextPtr:IsHidden()"):
                self.c.exec("ChooseArchaeologyPopup", "OnClose()")
            self.q("H.popups[ButtonPopupTypes.BUTTONPOPUP_CHOOSE_ARCHAEOLOGY] = nil; return true")
        else:
            r["err"] = "archaeology choice was sent but the completed dig is still pending"
        return r

    def choose_free_great_person(self, unit: str, pid: int | None = None) -> dict:
        """Claim a free Great Person (e.g. UNIT_SCIENTIST) via Network.SendGreatPersonChoice -- what the
        ChooseFreeItem popup's Confirm button sends (choosefreeitem.lua) -- then close that popup the same
        way its Close button does. Polls briefly for the unit count to rise so a silently-refused choice
        is reported instead of trusted."""
        r = self.q(f"return H.choose_free_great_person({lua_str(unit)}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        for _ in range(10):
            time.sleep(0.2)
            n = self.q(f"return Players[{self._pid(pid)}]:GetNumUnits()")
            if n > r["units_before"]:
                r["units_after"] = n
                break
        if self._visible_in_state("ChooseFreeItem", "return not ContextPtr:IsHidden()"):
            self.c.exec("ChooseFreeItem", "OnClose()")
            r["popup_closed"] = True
        r["free_after"] = self.q(f"return Players[{self._pid(pid)}]:GetNumFreeGreatPeople()")
        return r

    def _goody_popup_unit(self) -> int | None:
        for pop in self.turn_state().get("pending_popups", []):
            if pop.get("name") == "BUTTONPOPUP_CHOOSE_GOODY_HUT_REWARD":
                return pop.get("data2")
        return None

    def goody_hut_options(self, pid: int | None = None) -> dict:
        """The ancient-ruins rewards on offer while BUTTONPOPUP_CHOOSE_GOODY_HUT_REWARD is pending (Shoshone
        Pathfinder)."""
        unit_id = self._goody_popup_unit()
        if unit_id is None:
            return {"ok": False, "err": "no ruins reward choice is pending"}
        return self.q(f"return H.goody_hut_options({unit_id}, {self._pid(pid)})")

    def choose_goody_hut(self, goody: str, pid: int | None = None) -> dict:
        """Pick a ruins reward (Network.SendGoodyChoice, what the popup's Confirm sends), then hide the popup
        the way Confirm does."""
        unit_id = self._goody_popup_unit()
        if unit_id is None:
            return {"ok": False, "err": "no ruins reward choice is pending"}
        r = self.q(f"return H.choose_goody_hut({lua_str(goody)}, {unit_id}, {self._pid(pid)})")
        if r.get("ok"):
            self.c.exec("ChooseGoodyHutReward", "ContextPtr:SetHide(true)", check=False)
            time.sleep(0.5)
            r["popup_pending"] = self._goody_popup_unit() is not None
        elif "options" not in r:
            r["options"] = self.goody_hut_options(pid).get("options")
        return r

    def city_capture_options(self, pid: int | None = None) -> dict:
        r = self.q(f"return H.city_capture_options({self._pid(pid)})")
        for o in r.get("options", []):
            for k in ("warmonger", "effect"):
                if o.get(k):
                    o[k] = plain_text(o[k])
        return r

    def choose_city_capture(self, choice: str, pid: int | None = None) -> dict:
        """Answer BUTTONPOPUP_CITY_CAPTURED with the popup's own network call, then close the generic popup the
        way any of its buttons does (HideWindow) and report what the city became."""
        r = self.q(f"return H.choose_city_capture({lua_str(choice)}, {self._pid(pid)})")
        if r.get("ok"):
            self.c.exec("GenericPopup", "HideWindow()", check=False)
            time.sleep(0.7)
            cid = r["city"]["id"]
            r["after"] = self.q(f"""
                local c = Players[{self._pid(pid)}]:GetCityByID({cid})
                if not c then return {{ gone = true }} end
                return {{ puppet = c:IsPuppet(), occupied = c:IsOccupied(), razing = c:IsRazing(),
                         happiness = Players[{self._pid(pid)}]:GetExcessHappiness() }}""")
        return r
