"""Research, social policies, ideology and religion."""
from __future__ import annotations

import time

from .support import lua_str


class PoliciesMixin:
    """Research, social policies, ideology and religion.

    A part of harness.game.Game (see harness/game_parts/__init__.py); `self` is the whole Game."""

    def available_policies(self, pid: int | None = None) -> dict:
        """The social policy screen: adopted policies, adoptable ones (with help text), branches and
        whether a policy can be adopted this turn."""
        return self.q(f"return H.available_policies({self._pid(pid)})")

    def set_research(self, tech: str, pid: int | None = None) -> dict:
        """Choose the current research.

        The hardcoded `0` this used to pass as SendResearch's 2nd arg is wrong whenever the player has
        a free tech pending (e.g. just popped from a hut/ruin): the real UI (techtree.lua) always sends
        `player:GetNumFreeTechs()` there, and passing 0 instead makes the call silently no-op --
        GetCurrentResearch() stays -1, no error, ok:true is still returned (see docs/NOTES.md). Also
        verifies research actually started instead of trusting the unconditional {ok=true} from the
        network call, since an already-researched tech silently no-ops the same way -- checked up
        front here so that case gets a real error instead of a false success. Note: the engine may
        set current research to a *prerequisite* of `tech` rather than `tech` itself when the full
        path isn't unlocked yet (observed live requesting Currency -> Mathematics got set instead,
        still a legitimate step toward it) -- so success is "research changed to something new", not
        an exact id match; check `summary()['research']` afterward to see what it actually picked."""
        pre = self.q(f"""
            local id = GameInfoTypes[{lua_str(tech)}]
            if id == nil then return {{ok=false, err="unknown tech"}} end
            local p = Players[{self._pid(pid)}]
            local team = Teams[p:GetTeam()]
            return {{ok=true, id=id, has_tech=team:IsHasTech(id), can=p:CanResearch(id), current=p:GetCurrentResearch(),
                     free=p:GetNumFreeTechs()}}""")
        if not pre.get("ok"):
            return self._name_hint(pre, tech)
        if pre["has_tech"]:
            return {"ok": False, "err": "already researched"}
        goal = not pre.get("can")
        if goal and pre.get("free", 0) > 0:
            return {"ok": False, "err": "a free tech must be one you can research right now (see available_research)"}
        r = self.q(f"""
            local p = Players[{self._pid(pid)}]
            Network.SendResearch({pre['id']}, p:GetNumFreeTechs(), -1, false)
            return {{ok=true}}""")
        if not r.get("ok"):
            return r
        time.sleep(0.3)
        chk = self.q(f"""
            local p = Players[{self._pid(pid)}]
            local cur = p:GetCurrentResearch()
            local name = cur >= 0 and GameInfo.Technologies[cur] and GameInfo.Technologies[cur].Type or nil
            local queue = {{}}
            for t in GameInfo.Technologies() do
              local pos = p:GetQueuePosition(t.ID)
              if pos and pos > 0 then queue[#queue + 1] = {{pos = pos, tech = t.Type}} end
            end
            table.sort(queue, function(a, b) return a.pos < b.pos end)
            local path = {{}}
            for i, e in ipairs(queue) do path[i] = e.tech end
            return {{ok=true, current=cur, research=name, has_tech=Teams[p:GetTeam()]:IsHasTech({pre['id']}), free=p:GetNumFreeTechs(),
                     queue=path}}""")
        if pre.get("free", 0) > 0:
            # A free tech (Oxford University, Great Scientist-less ruins, ENDTURN_BLOCKING_FREE_TECH) is
            # granted outright and current research is left alone -- live: Oxford's free Industrialization
            # was granted while Chemistry stayed the active research, and the old "research did not
            # change" check reported a false failure. Success here is "the tech is now known".
            if chk.get("has_tech"):
                return {"ok": True, "granted": tech, "free_techs_left": chk.get("free"), "research": chk.get("research")}
            return {"ok": False, "err": "SendResearch accepted but the free tech was not granted", "free_techs_left": chk.get("free")}
        if goal:
            # Same as clicking a far tech in the tech tree: the engine researches the cheapest missing
            # prerequisite now and queues the rest (live t316: TECH_PLASTIC -> queue [RADIO, PLASTIC]; the
            # current research may legitimately stay the same when it is already the first step).
            queue = chk.get("queue") or []
            if tech not in queue:
                return {"ok": False, "err": "cannot research this yet and the game queued no path to it (disabled?)",
                        "research": chk.get("research")}
            return {"ok": True, "research": chk.get("research"), "goal": tech, "queue": queue}
        if chk.get("ok") and (chk.get("current") == -1 or chk.get("current") == pre["current"]):
            return {"ok": False, "err": "SendResearch accepted but current research did not change (free-tech count mismatch?)"}
        return {"ok": True, "research": chk.get("research")}

    def available_research(self, pid: int | None = None) -> list[dict]:
        """Techs this seat can currently research (prereqs met, not already owned).

        Each row's `unlocks` is the tech-tree button row for this civilization.
        """
        return self.q(f"return H.available_research({self._pid(pid)})")

    def tech_tree(self, pid: int | None = None) -> dict:
        """Full tech tree: researched, current, available, locked-with-prereqs. No rival techs (GitLab #1).

        Unresearched rows carry `unlocks`, the buttons on that tech for this seat.
        """
        return self.q(f"return H.tech_tree({self._pid(pid)})")

    def _confirm_policy(self, r: dict, want: str, key: str, pid: int | None) -> dict:
        """Network.SendUpdatePolicies is asynchronous: poll available_policies until `want` shows up as
        adopted (policy) / unlocked (branch), then report culture, next cost and the blocker state, so the
        caller knows the choice took without a second read."""
        if not r.get("ok"):
            return r
        def took(ap: dict) -> bool:
            if key == "policy":
                return any(a.get("policy") == want for a in ap.get("adopted", []) if isinstance(a, dict))
            return any(b.get("branch") == want and b.get("unlocked") for b in ap.get("branches", []) if isinstance(b, dict))
        ap, done = self._settle(lambda: self.available_policies(pid) or {}, took, initial={})
        r.update({key: want, "confirmed": done, "culture": ap.get("culture"), "next_policy_cost": ap.get("next_policy_cost"),
                  "can_adopt_another": ap.get("can_adopt_now")})
        try:
            r["blocking_name"] = self.turn_state().get("blocking_name")
        except Exception:  # noqa: BLE001 -- purely informational
            pass
        if not done:
            r["note"] = "not visible as adopted/unlocked within 3s; re-read available_policies"
        return r

    def choose_policy(self, policy: str, pid: int | None = None) -> dict:
        """Adopt a social policy within an already-unlocked branch, e.g. POLICY_TRADITION."""
        r = self.q(f"return H.choose_policy({lua_str(policy)}, {self._pid(pid)})")
        return self._confirm_policy(r, policy, "policy", pid)

    def unlock_policy_branch(self, branch: str, pid: int | None = None) -> dict:
        """Unlock a policy branch/tree, e.g. POLICY_BRANCH_TRADITION."""
        r = self.q(f"return H.unlock_policy_branch({lua_str(branch)}, {self._pid(pid)})")
        return self._confirm_policy(r, branch, "branch", pid)

    def choose_ideology(self, branch: str, pid: int | None = None) -> dict:
        """Pick an ideology (POLICY_BRANCH_FREEDOM / ORDER / AUTOCRACY) -- what chooseideologypopup.lua's
        Confirm sends (Network.SendIdeologyChoice), then close that popup like its Close button. Polls
        (<= 3 s) for Player:GetLateGamePolicyTree to change so a refused choice is reported, not trusted."""
        r = self.q(f"return H.choose_ideology({lua_str(branch)}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        state, _ = self._settle(lambda: self.q(f"return H.ideology_state({self._pid(pid)})"),
                                lambda st: bool(st.get("ideology")))
        r.pop("pending", None)
        r.update(state or {})
        if not r.get("ideology"):
            r["ok"] = False
            r["err"] = "SendIdeologyChoice was sent but no ideology appeared within 3s"
            return r
        if self.has_state("ChooseIdeologyPopup") and self.c.query("ChooseIdeologyPopup", "return not ContextPtr:IsHidden()"):
            self.c.exec("ChooseIdeologyPopup", "OnClose()")
        # OnClose only dequeues the popup: drop the BUTTONPOPUP_CHOOSE_IDEOLOGY record ourselves
        self.q('for k in pairs(H.popups) do local n = H.enum_name("popup", ButtonPopupTypes, k) or "" '
               'if n:find("CHOOSE_IDEOLOGY", 1, true) then H.popups[k] = nil end end return true')
        r["blocking_name"] = self.turn_state().get("blocking_name")
        return r

    def change_ideology(self, pid: int | None = None) -> dict:
        """The policy screen's Switch Ideology confirm (Network.SendChangeIdeology): only while
        public-opinion unhappiness is positive; overview().public_opinion shows the cost first."""
        return self.q(f"return H.change_ideology({self._pid(pid)})")

    def set_faith_purchase(self, kind: str, index: int = 0, pid: int | None = None) -> dict:
        """The Religion Overview's automatic faith purchase pull-down (Network.SendFaithPurchase):
        `kind` nothing / save_prophet / unit / building, `index` the unit or building id from
        religion_overview().auto_purchase.options. Refused for anything the pull-down does not list."""
        return self.q(f"return H.set_faith_purchase({lua_str(kind)}, {int(index)}, {self._pid(pid)})")

    def religion_overview(self, pid: int | None = None) -> dict:
        """The Religion Overview screen: my faith / pantheon / religion + beliefs, every founded religion (founder
        and holy city "unknown" until met), and followers + pressure per religion in each of my cities."""
        return self.q(f"return H.religion_overview({self._pid(pid)})")

    def faith_great_person_options(self, pid: int | None = None) -> dict:
        return self.q(f"return H.faith_great_person_options({self._pid(pid)})")

    def choose_faith_great_person(self, unit: str, pid: int | None = None) -> dict:
        """Network.SendFaithGreatPersonChoice, then close the ChooseFaithGreatPerson popup if it is up."""
        r = self.q(f"return H.choose_faith_great_person({lua_str(unit)}, {self._pid(pid)})")
        if r.get("ok"):
            time.sleep(0.5)
            r["units_after"] = self.q(f"return Players[{self._pid(pid)}]:GetNumUnits()")
            if self._visible_in_state("ChooseFaithGreatPerson", "return not ContextPtr:IsHidden()"):
                self.c.exec("ChooseFaithGreatPerson", "ContextPtr:SetHide(true)", check=False)
        return r

    def available_beliefs(self, kind: str, pid: int | None = None) -> dict:
        """Beliefs still on offer for one slot kind (pantheon / founder / follower / enhancer / bonus /
        reformation), with the popup's name + description; kind=founder also lists the unfounded religions."""
        return self.q(f"return H.available_beliefs({lua_str(kind)}, {self._pid(pid)})")

    def add_reformation_belief(self, belief: str, pid: int | None = None) -> dict:
        return self.q(f"return H.add_reformation_belief({lua_str(belief)}, {self._pid(pid)})")

    def found_pantheon(self, belief: str, pid: int | None = None) -> dict:
        """Found a pantheon with the given belief, e.g. BELIEF_GOD_OF_THE_SEA. No Can*() precondition check
        was found for this call (unlike city_ranged_attack/choose_policy); check turn_state().blocking_name
        == 'ENDTURN_BLOCKING_FOUND_PANTHEON' first rather than calling this speculatively."""
        return self.q(f"return H.found_pantheon({lua_str(belief)}, {self._pid(pid)})")

    def found_religion(self, religion: str, beliefs: list[str], city_x: int, city_y: int,
                        custom_name: str = "", pid: int | None = None) -> dict:
        """Found a religion (RELIGION_...) with 1-4 beliefs, in the city at (city_x, city_y). Check
        turn_state().blocking_name == 'ENDTURN_BLOCKING_FOUND_RELIGION' first (see found_pantheon)."""
        lua_beliefs = "{" + ", ".join(lua_str(b) for b in beliefs) + "}"
        r = self.q(f"return H.found_religion({lua_str(religion)}, {lua_beliefs}, {city_x}, {city_y}, {lua_str(custom_name)}, {self._pid(pid)})")
        if not (isinstance(r, dict) and r.get("ok")):
            return r
        # The net message lands on a later tick and the bare {"ok":true} said nothing about what was founded
        # (live t64, Tengriism). Report the religion as the overview screen shows it once it exists.
        me = self._pid(pid)
        for _ in range(12):
            time.sleep(0.25)
            ov = self.religion_overview(pid)
            world = ov.get("world") if isinstance(ov, dict) else None
            hit = next((w for w in world or [] if isinstance(w, dict) and w.get("founder") == me), None)
            if hit:
                return {**r, "founded": hit}
        return {**r, "ok": False, "err": "the found-religion message was sent but no religion of mine exists after 3 s"}

    def enhance_religion(self, religion: str, belief4: str, belief5: str, city_x: int, city_y: int,
                          custom_name: str = "", pid: int | None = None) -> dict:
        """Enhance my founded religion by picking two more beliefs. Check turn_state().blocking_name ==
        'ENDTURN_BLOCKING_ENHANCE_RELIGION' first (see found_pantheon)."""
        return self.q(f"return H.enhance_religion({lua_str(religion)}, {lua_str(belief4)}, {lua_str(belief5)}, {city_x}, {city_y}, {lua_str(custom_name)}, {self._pid(pid)})")
