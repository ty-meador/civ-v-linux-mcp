"""Diplomacy: relationships, friendship, war and peace, leader discussions, city-state actions and gifts, the World Congress."""
from __future__ import annotations

import time
from typing import Any

from ..client import TunerdError

from .support import _lua_items, lua_str, plain_text


class DiplomacyMixin:
    """Diplomacy: relationships, friendship, war and peace, leader discussions, city-state actions and gifts, the World Congress.

    A part of harness.game.Game (see harness/game_parts/__init__.py); `self` is the whole Game."""

    def diplomacy(self, pid: int | None = None) -> list[dict]:
        return self.q(f"return H.diplomacy({self._pid(pid)})")

    def relationship(self, other_player: int, pid: int | None = None) -> dict:
        """Our standing with one civ (approach guess, DoF, denouncements, embassies, open borders,
        agreements, opinion lines) plus their public relations with every civ we have met and the
        recent leader messages they sent us. Human-visible information only."""
        return self.q(f"return H.relationship({self._pid(pid)}, {int(other_player)})")

    def diplo_event(self, event: str, other_player: int, data1: int = 0, data2: int = 0) -> dict:
        """Escape hatch: fire a FromUIDiploEventTypes event straight on the engine (Game.DoFromUIDiploEvent),
        the same call the game's own leader-head/discussion-dialog buttons use -- no UI screen needs to be
        open. `event` is the enum name with or without its FROM_UI_DIPLO_EVENT_ prefix, e.g.
        "HUMAN_DECLARES_WAR" or "AI_REQUEST_DENOUNCE_RESPONSE". See docs/NOTES.md for the list found in this
        build's Lua (from static analysis). declare_war/make_peace/denounce below are live-verified
        (runtime v13): the engine silently no-ops an invalid war/peace event rather than erroring, so
        H.diplo_event mirrors the real UI's own preconditions (met/at-war state, CanChangeWarPeace,
        CanDeclareWar, IsForcePeace, GetNumTurnsLockedIntoWar) and returns a clean {ok:false, err:...}
        instead of a blind {ok:true} when one of those isn't satisfied. Any other event name is passed
        through unguarded (no precondition was found for it in the game's own Lua)."""
        return self.q(f"return H.diplo_event({lua_str(event)}, {other_player}, {data1}, {data2})")

    def declare_war(self, other_player: int) -> dict:
        return self.diplo_event("HUMAN_DECLARES_WAR", other_player)

    def make_peace(self, other_player: int, items: list[dict] | None = None, pid: int | None = None) -> dict:
        """Offer peace to a civ you are at war with, with optional terms, through the real screens (GitLab #5):
        the same propose_deal flow with the treaty on both sides of the table. `items` are the terms in
        propose_deal's shapes (gold, gold per turn, resources, cities, third-party war/peace...). Against an AI
        the leader screen's Negotiate Peace button (leaderheadroot.lua OnWarOrPeace -> HUMAN_NEGOTIATE_PEACE) opens
        the table with the treaty already on it and the reply is read on the spot: `accepted`, `reply`, `at_war`
        afterwards. An AI can and typically will refuse right after a declaration even once
        GetNumTurnsLockedIntoWar reports 0; that is its own acceptance logic, not something to bypass. Against a
        human seat the proposal is pending (`pending: true`) until that seat answers with accept_deal /
        refuse_deal on its turn. Refused with the screen's reason while locked into war (trade_catalog().peace).
        The old bare HUMAN_NEGOTIATE_PEACE event is still reachable through diplo_event."""
        return self.propose_deal(other_player, [{"type": "PEACE_TREATY"}] + list(items or []), pid=pid)

    def denounce(self, other_player: int) -> dict:
        return self.diplo_event("DENOUNCE", other_player)

    def accept_friendship(self, other_player: int) -> dict:
        """Accept a pending `DISCUSS_WORK_WITH_US` Declaration of Friendship proposal (the discussion
        state used for every AI "let's be friends" offer seen live so far). Works whether or not the
        DiscussionDialog is still open -- `discussiondialog.lua`'s own OnButton1 for this state does
        nothing but this same call (`Game.DoFromUIDiploEvent(FROM_UI_DIPLO_EVENT_WORK_WITH_US_RESPONSE,
        player, 1, 0)`; button 2 is decline, same event), so it works standalone too, and live-tested
        working even *after* the dialog had already been declined/closed (2026-09-16, turns 258 and 263 --
        the second time on a dialog that was still fresh, not previously declined, closing out the
        one-off caveat from the first test). Confirm real effect with `Players[pid]:IsDoF(other_player)`
        via `q()` if in doubt -- like every other unguarded `diplo_event`, {ok:true} only means the engine
        call didn't error, not that the AI's own preconditions were met."""
        return self.diplo_event("WORK_WITH_US_RESPONSE", other_player, 1, 0)

    def expiring_city_states(self, within: int = 3, pid: int | None = None) -> list[dict]:
        """City-states whose ally/friend status lapses within `within` turns at the current influence decay
        (diplomacy()'s turns_until_status_lost). Live t352: the Monaco alliance (7 Oil, +13 culture) lapsed
        at 59/60 with no warning; a 250-gold gift restored it."""
        try:
            rows = self.diplomacy(pid)
        except TunerdError:
            return []
        return [{"player_id": r.get("id"), "civ": r.get("civ"), "status": "ally" if r.get("allied") else "friend",
                 "influence": r.get("influence"), "turns_left": r.get("turns_until_status_lost"),
                 "hint": "city_state_gifts / minor_gold_gift to keep it"}
                for r in (rows if isinstance(rows, list) else [])
                if isinstance(r, dict) and r.get("minor") and isinstance(r.get("turns_until_status_lost"), int)
                and r["turns_until_status_lost"] <= within]

    def propose_friendship(self, other_player: int, pid: int | None = None) -> dict:
        """Ask an AI civ for a Declaration of Friendship: the leader screen's Discuss -> "work together" button
        (discussiondialog.lua OnButton6 in DISCUSS_HUMAN_INVOKED root mode), with its own guards -- not already
        friends, not IsDoFMessageTooSoon -- plus met / not at war / major civ. The AI answers through its
        leader message; the reply reports IsDoF after a short settle (live t345: DoFs with America and Sweden
        expired after their term and there was no way to renew them)."""
        me = self._pid(pid)
        pre = self.q(f"""
            local p, o = Players[{me}], Players[{int(other_player)}]
            if not o or not o:IsAlive() or o:IsMinorCiv() or {int(other_player)} == {me} then return {{ok=false, err="not a living major civ"}} end
            local myTeam = Teams[p:GetTeam()]
            if not myTeam:IsHasMet(o:GetTeam()) then return {{ok=false, err="not met"}} end
            if myTeam:IsAtWar(o:GetTeam()) then return {{ok=false, err="at war with them"}} end
            if o:IsDoF({me}) then return {{ok=false, err="already friends (declaration still running)"}} end
            if o:IsDoFMessageTooSoon({me}) then return {{ok=false, err="asked too recently; the leader screen greys this out -- try again in a few turns"}} end
            return {{ok=true}}""")
        if not pre.get("ok"):
            return pre
        # The AI's answer is a reply to OUR ask: flag it harness_initiated so turn_digest does not present it as
        # the AI approaching us (live t346 digest showed "I am happy to accept" / "Sorry, but no" as approaches).
        self.c.exec("InGame", "H.harness_diplo = true", check=False)
        try:
            r = self.diplo_event("HUMAN_DISCUSSION_WORK_WITH_US", other_player, 0, 0)
            if not r.get("ok"):
                return r
            time.sleep(0.5)
            return self._friendship_result(other_player, me, pid)
        finally:
            self.c.exec("InGame", "H.harness_diplo = nil", check=False)

    def _friendship_result(self, other_player: int, me: int, pid: int | None) -> dict:
        post = self.q(f"return {{dof = Players[{int(other_player)}]:IsDoF({me})}}")
        out = {"ok": True, "accepted": bool(post.get("dof"))}
        # The answer is spoken on a leader screen that then drops back to the Discuss menu (our own asks, not
        # a question for us -- live t345 America); close it or every later action reads "decision pending".
        # It takes a beat to come up (live t182, Mongolia: Babylon's "That will work" screen was not there
        # 0.5 s after the ask, so nothing was closed, `reply` was the t171 line and the next finish_turn was
        # refused with a discussion gate): wait for it the way dismiss_discussion waits for a queued leader.
        screen = False
        for _ in range(self._NEXT_LEADER_POLLS):
            if self.discussion_pending():
                screen = True
                break
            time.sleep(0.2)
        try:
            hist = self.relationship(other_player, pid).get("history") or []
            if hist:
                out["reply"] = hist[-1].get("text")
        except TunerdError:
            pass
        if screen:
            out["screen_closed"] = bool(self.dismiss_discussion().get("ok"))
        return out

    def discussion_pending(self) -> bool:
        """True when an AI leader has opened a real negotiation/demand/trade-offer screen (the
        DiscussionDialog/DiploTrade pair) -- as opposed to the purely-informational LeaderHeadRoot greeting
        (see leader_greeting_pending()). Confirmed live: this leaves turn_state()'s my_turn stuck false
        (p:IsTurnActive() is false while it's up) exactly like the greeting popup, but unlike that one this
        represents a REAL decision -- accept/reject a deal, respond to a demand -- so wait_for_my_turn()
        surfaces it immediately instead of auto-resolving it; blindly auto-declining every AI proposal
        would be its own silent bug.

        `Controls.LeaderPanel:IsHidden()` inside DiscussionDialog is NOT reliable -- stayed `true` live
        for a real, on-screen Spain trade offer (a first Sweden trade offer had briefly made LeaderPanel
        look like the right signal; a second, different offer from Spain disproved it). `DiploTrade`'s own
        `ContextPtr:IsHidden()` tracked correctly for both of those. But `DiscussionDialog`'s own
        `ContextPtr:IsHidden()` -- dismissed as unreliable in an earlier pass alongside LeaderPanel -- was
        later caught live actually being the more reliable of the two: a `wait_for_my_turn` stall (my_turn
        stuck false, `dismiss_pending_popups()` empty, no other check catching it) turned out to be a pure
        AI demand/ultimatum with DiploTrade staying hidden the whole time while DiscussionDialog itself
        plainly was not -- exactly the gap this docstring used to flag as unconfirmed. Net effect: neither
        single check is reliable alone, so this now checks both and treats either as pending."""
        return self._modal_flags()["discussion_pending"]

    _DISCUSSION_READ_LUA = """
        local out = {}
        out.speech = Controls.LeaderSpeech:GetText()
        out.title = Controls.TitleText:GetText()
        out.mood = Controls.MoodText:GetText()
        -- The screen names a leader; we match that title back to a player id. Restricting the match to
        -- living players left the DEFEAT screen -- the one that opens when we destroy a civ -- reporting
        -- player -1 with the leader plainly written on it (live t190, "Pachacuti the Pious of The Inca",
        -- his last city just taken). A dead leader is still a leader we can name, so the sweep falls back
        -- to the eliminated ones, and says which pass matched.
        out.player, out.player_alive = -1, false
        local function match(alive_only)
            for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
                local p = Players[i]
                if p and not (alive_only and not p:IsAlive()) then
                    local ok, title = pcall(GameplayUtilities.GetLocalizedLeaderTitle, p)
                    if ok and title == out.title then return i end
                end
            end
            return -1
        end
        out.player = match(true)
        if out.player >= 0 then out.player_alive = true else out.player = match(false) end
        out.buttons = {}
        for i = 1, 4 do
            local b = Controls['Button' .. i]
            local l = Controls['Button' .. i .. 'Label']
            if b and l and not b:IsHidden() then
                out.buttons[#out.buttons + 1] = {id = i, text = l:GetText() or '', disabled = b:IsDisabled()}
            end
        end
        out.can_go_back = Controls.BackButton ~= nil and not Controls.BackButton:IsHidden()
        print(out.player, out.title, out.mood, out.can_go_back, out.player_alive)
        print(out.speech)
        for _, b in ipairs(out.buttons) do print(b.id, tostring(b.disabled), b.text) end
    """

    def discussion(self, pid: int | None = None) -> dict:
        """What the open leader screen says, so a caller can decide instead of guessing.

        Returns {pending, screen: 'discussion'|'trade'|None, player, leader, mood, speech,
        buttons: [{id, text, disabled}], can_go_back, deal}. `buttons` are the DiscussionDialog's
        visible response buttons (Button1..4; their text lives in the Button<N>Label child, the
        GridButton itself has no text) -- respond with respond_discussion(id). `deal` is the trade
        table (incoming_deal) when DiploTrade is up: accept_deal / refuse_deal answer that one.
        A screen with no buttons and can_go_back (e.g. "Very well." after a deal) is a plain
        acknowledgement: dismiss_discussion() closes it. The leader's player id is recovered by
        matching the title text against every major civ's localized leader title (the dialog keeps
        its own g_iAIPlayer as a file-local, unreadable from outside)."""
        out: dict = {"pending": False, "screen": None}
        sc = self._screens()
        trade_up = bool(sc.get("trade_state"))
        disc_up = bool((sc.get("screens") or {}).get("DiscussionDialog"))
        greeting_up = not (trade_up or disc_up) and bool(sc.get("leader_head_root_up"))
        if not (trade_up or disc_up or greeting_up):
            return out
        states = self.states()
        out["pending"] = True
        out["screen"] = "trade" if trade_up else "discussion" if disc_up else "greeting"
        out["how_to_answer"] = ("a deal is on the table: incoming_deal() shows the items, then accept_deal() or refuse_deal()"
                                if trade_up else "respond_discussion(button_id) with one of `buttons`, or dismiss_discussion() if there are none"
                                if disc_up else "nothing to decide (first meeting, or the echo of a war/peace just made): dismiss_discussion() closes it")
        # LeaderHeadRoot carries the same TitleText/MoodText/LeaderSpeech controls (no response buttons).
        dd = [k for k, v in states.items() if v == ("LeaderHeadRoot" if greeting_up else "DiscussionDialog")]
        if trade_up:
            # DiscussionDialog's controls keep the PREVIOUS conversation's text while it is hidden
            # behind a trade screen; the trade offer's own words arrive via the AILeaderMessage hook.
            dd = []
        if dd:
            lines = self.c.exec(dd[0], self._DISCUSSION_READ_LUA, check=False)
            if lines:
                head = lines[0].split("\t")
                out["player"] = int(head[0])
                out["leader"] = head[1]
                out["mood"] = head[2]
                out["can_go_back"] = head[3] == "true"
                if len(head) > 4 and head[4] == "false" and out["player"] >= 0:
                    # Matched only on the second pass: this is the defeat screen of a civ we just ended.
                    out["player_eliminated"] = True
                out["speech"] = lines[1] if len(lines) > 1 else ""
                out["buttons"] = []
                for line in lines[2:]:
                    parts = line.split("\t", 2)
                    if len(parts) == 3:
                        out["buttons"].append({"id": int(parts[0]), "disabled": parts[1] == "true", "text": parts[2]})
        if trade_up:
            try:
                out["deal"] = self.incoming_deal(pid)
            except TunerdError as e:
                out["deal"] = {"ok": False, "err": str(e)}
            other = out["deal"].get("to") if out["deal"].get("ok") else None
            if other is not None and other != self._pid(pid):
                out["player"] = other
            out["buttons"] = []
        if out.get("player", -1) >= 0 and not out.get("player_eliminated"):
            try:
                out["relationship"] = self.relationship(out["player"], pid)
            except TunerdError as e:
                out["relationship"] = {"ok": False, "err": str(e)}
            rel = out["relationship"]
            if rel.get("ok"):
                out.setdefault("leader", rel.get("leader"))
                if trade_up and rel.get("history"):
                    out["speech"] = rel["history"][-1]["text"]
                # The civ's public relations with everyone else and its full message log are relationship()
                # reads; inline they tripled every AI question (~3 KB, live t322).
                rel.pop("relations", None)
                if rel.get("history"):
                    rel["history"] = rel["history"][-2:]
        if trade_up and out.get("deal", {}).get("renewal"):
            out["renewal"] = True
        return out

    def respond_discussion(self, button: int, expect: str = "") -> dict:
        """Press response button 1-4 on the open DiscussionDialog (the same OnButton<N> callback the
        real button fires). Refuses when that button is not currently visible, so a stale id from an
        earlier screen cannot pick a different answer on a newer one."""
        d = self.discussion()
        if not d.get("pending") or d.get("screen") != "discussion":
            return {"ok": False, "err": "no discussion screen is open", "discussion": d}
        ids = {b["id"] for b in d.get("buttons", []) if not b["disabled"]}
        if button not in ids:
            return {"ok": False, "err": f"button {button} is not an available response", "buttons": d.get("buttons")}
        # `expect`: a word or phrase the chosen button's text must contain, so a remembered id cannot press a
        # different answer on a screen laid out differently (war requests put "(Declares War)" on button 4).
        text = next(b["text"] for b in d["buttons"] if b["id"] == button)
        if expect and expect.lower() not in text.lower():
            return {"ok": False, "err": f"button {button} reads {text!r}, which does not contain {expect!r}; nothing pressed",
                    "buttons": d.get("buttons")}
        dd = self.c.wait_state("DiscussionDialog", 5)
        self.c.exec(dd, f"OnButton{button}()", check=False)
        out = {"ok": True, "pressed": button, "text": next(b["text"] for b in d["buttons"] if b["id"] == button),
               **self._settle_leader_remark(), "still_pending": self.discussion_pending()}
        if out["still_pending"]:
            # Another leader was queued behind this one (live t295: America, Sweden and India in a row);
            # hand over the next question so the caller needs no extra discussion() read.
            nxt = self.discussion()
            out["next"] = {k: nxt.get(k) for k in ("screen", "leader", "speech", "buttons", "how_to_answer")}
            if nxt.get("screen") == "trade":
                out["next"]["deal"] = self.incoming_deal().get("items")
        return out

    _GREETING_CLICKS = 8   # first-meeting greetings closed in one dismiss_discussion call, at most

    def dismiss_discussion(self) -> dict:
        """Leave the current negotiation/demand/trade-offer screen without agreeing to anything -- same
        call discussiondialog.lua's own Back button makes (OnBack(true), forcing past its g_bCanGoBack
        gate). For a trade table that is already open, prefer refuse_deal() (reads terms first).
        Do not use this to accept; see accept_deal(). Also closes the plain LeaderHeadRoot greeting
        (turn_status leader_greeting_pending): live t12, this returned ok while Temujin's greeting stayed
        on screen and kept the end-turn blocker frozen."""
        if not self.discussion_pending() and self.leader_greeting_pending():
            # Greetings queue up: a cargo ship reaching a new shore met England, Babylon and Portugal at one
            # turn start (live t145, Venice), and one Back per call answered ok=false with the next greeting
            # up. Click through them as a human would, up to a bound, stopping at anything that needs an
            # answer (a trade table or buttons: discussion_pending), which the caller then gets as `next`.
            closed = 0
            for _ in range(self._GREETING_CLICKS):
                self.dismiss_leader_greeting()
                closed += 1
                time.sleep(0.15)
                if self.discussion_pending() or not self.leader_greeting_pending():
                    break
            still = self.leader_greeting_pending() and not self.discussion_pending()
            return {"ok": not still, "closed": "greeting", "closed_count": closed}
        dd = self.c.wait_state("DiscussionDialog", 5)
        self.c.exec(dd, "OnBack(true)", check=False)
        # The leader queued behind this one takes a beat to appear (live t174, Mongolia: England's remark closed,
        # Portugal's behind it showed only to the next discussion() read, so the hand-over `next` was empty and
        # the following briefing was refused with a gate). Wait for the screen to close and, if another comes
        # straight back up, for that one: the MCP wrapper (_with_next) then reports it.
        closed_seen = False
        for _ in range(self._NEXT_LEADER_POLLS):
            time.sleep(0.2)
            if not self.discussion_pending():
                closed_seen = True
            elif closed_seen:
                break
        return {"ok": True}

    _NEXT_LEADER_POLLS = 6   # ~1.2 s for the next queued leader after Back

    def war_consequences(self, other: int, pid: int | None = None) -> dict:
        """The declare-war confirmation's list for `other`: friendship / denouncements, its allied city-states,
        a city-state's protectors, trade routes that would be cancelled."""
        return self.q(f"return H.war_consequences({int(other)}, {self._pid(pid)})")

    def city_state_actions(self, minor_id: int, pid: int | None = None) -> dict:
        """What the city-state screen offers besides gifts, plus its quest text (citystatestatushelper.lua's
        GetActiveQuestToolTip, run in the popup's own context where that include lives)."""
        r = self.q(f"return H.city_state_actions({int(minor_id)}, {self._pid(pid)})")
        if r.get("ok"):
            out = self.c.exec("CityStateDiploPopup", f"print(GetActiveQuestToolTip({self._pid(pid)}, {int(minor_id)}))", check=False)
            r["quests"] = plain_text("\n".join(out)) if out else ""
        return r

    def city_state_action(self, minor_id: int, action: str, pid: int | None = None) -> dict:
        r = self.q(f"return H.city_state_action({int(minor_id)}, {lua_str(action)}, {self._pid(pid)})")
        if r.get("ok"):
            time.sleep(0.5)
            r["after"] = self.q(f"return H.city_state_actions({int(minor_id)}, {self._pid(pid)})")
            r["gold_after"] = self.q(f"return Players[{self._pid(pid)}]:GetGold()")
        return r

    def city_state_bonuses(self, minor_id: int, pid: int | None = None) -> dict:
        return self.q(f"return H.city_state_bonuses({int(minor_id)}, {self._pid(pid)})")

    def gift_unit_options(self, minor_id: int, pid: int | None = None) -> dict:
        return self.q(f"return H.gift_unit_options({int(minor_id)}, {self._pid(pid)})")

    def unit_home_options(self, unit_id: int, pid: int | None = None) -> dict:
        return self.q(f"return H.unit_home_options({int(unit_id)}, {self._pid(pid)})")

    def gift_tile_improvement_options(self, minor_id: int, pid: int | None = None) -> dict:
        return self.q(f"return H.gift_tile_improvement_options({int(minor_id)}, {self._pid(pid)})")

    def gift_tile_improvement(self, minor_id: int, x: int, y: int, pid: int | None = None) -> dict:
        r = self.q(
            f"return H.gift_tile_improvement({int(minor_id)}, {int(x)}, {int(y)}, {self._pid(pid)})"
        )
        if not (isinstance(r, dict) and r.get("ok")):
            return r
        # The purchase lands on a later game update: read straight after the order, the reply said
        # gold_spent 0 with the treasury untouched while the mine was already on the map a moment later
        # (live 2026-09-24, Budapest's Gems). Poll like gift_unit does, until the gold or the plot moves.
        before = r.get("before") or {}
        for _ in range(10):
            time.sleep(0.2)
            after = self.q(f"local p = Map.GetPlot({int(x)}, {int(y)}) local imp = p:GetImprovementType() "
                           f"return {{gold = Players[{self._pid(pid)}]:GetGold(), "
                           f"influence = Players[{int(minor_id)}]:GetMinorCivFriendshipWithMajor({self._pid(pid)}), "
                           f"improvement = imp >= 0 and GameInfo.Improvements[imp].Type or nil}}") or {}
            r["after"] = {"gold": after.get("gold"), "influence": after.get("influence")}
            if after.get("improvement"):
                r["after"]["improvement"] = after["improvement"].replace("IMPROVEMENT_", "", 1)
            r["gold_spent"] = (before.get("gold") or 0) - (after.get("gold") or 0)
            if r["gold_spent"] > 0 or after.get("improvement"):
                break
        if not (r["gold_spent"] > 0 or r["after"].get("improvement")):
            r["note"] = "the order went out but neither the treasury nor the plot has changed yet"
        return r

    def gift_unit(self, minor_id: int, unit_id: int, pid: int | None = None) -> dict:
        r = self.q(f"return H.gift_unit({int(minor_id)}, {int(unit_id)}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        for _ in range(10):
            time.sleep(0.2)
            still = any(isinstance(u, dict) and u.get("id") == unit_id for u in (self.units(pid) or []))
            inf = self.q(
                f"return Players[{int(minor_id)}]:GetMinorCivFriendshipWithMajor({self._pid(pid)})"
            )
            r["influence"] = inf
            if not still:
                r["unit_gone"] = True
                break
        r["ok"] = r.get("unit_gone") is True
        if not r["ok"]:
            r["err"] = "gift was sent but the unit is still ours"
        return r

    def league_status(self, pid: int | None = None) -> dict:
        """Read-only: World Congress state. Between sessions (in_session=false): `proposable_enact`
        (resolution types I can propose to enact, with a `choices` list if the resolution needs one -- pass
        a choice id into league_propose_enact) and `proposable_repeal` (active resolutions I can propose to
        repeal). `name` drops the choice icon tag GetResolutionName embeds (the screen draws the icon).
        Each row's `details` is the League Overview tooltip (what the resolution does). Greyed
        resolutions are `unavailable_enact`. `active_resolutions` is everything already passed, including
        ones this seat cannot repeal. `active_effects` is the summary printed on the league screen.
        `pending_proposals` includes on-hold rows; an unmet proposer is `proposer_civ: "unknown"`.
        During a session (in_session=true): `votable`, the enact/repeal proposals on the table this
        session, for league_cast_votes, with the same tooltip. `projects` is the World's Fair / Games / ISS
        the production tooltip describes (percent, our hammers, reward thresholds). Other civs'
        contributions are listed only once the project is complete -- that popup is the first screen that
        shows the split. Unmet contributors are `civ: "unknown"` with no player id. A met member's
        `details` is the delegate tooltip. `has_league=false` if no league exists yet."""
        return self.q(f"return H.league_status({self._pid(pid)})")

    def _league_readback(self, r: Any, pid: int | None) -> Any:
        """A proposal answered a bare ok:true; read back what now stands for the next session."""
        if isinstance(r, dict) and r.get("ok"):
            try:
                st = self.league_status(pid)
                r["pending_proposals"] = st.get("pending_proposals")
                r["remaining_proposals"] = st.get("remaining_proposals")
            except TunerdError:
                pass
        return r

    def league_propose_enact(self, resolution_type: str, choice: int = -1, pid: int | None = None) -> dict:
        """Propose enacting a World Congress resolution (see league_status()'s proposable_enact), e.g.
        RESOLUTION_SCIENCES_FUNDING. Needed to clear ENDTURN_BLOCKING_LEAGUE_CALL_FOR_PROPOSALS -- this is a
        HARD block, confirmed live: closing the World Congress screen without actually proposing something
        does NOT clear it, unlike every other popup-shaped blocker in this harness. `choice` is required (an
        id from proposable_enact's `choices` list) for resolutions that need one, e.g. which civ to embargo
        or which resource to ban."""
        return self._league_readback(self.q(f"return H.league_propose_enact({lua_str(resolution_type)}, {choice}, {self._pid(pid)})"), pid)

    def league_propose_repeal(self, resolution_id: int, pid: int | None = None) -> dict:
        """Propose repealing an active World Congress resolution (see league_status()'s proposable_repeal,
        `resolution_id`)."""
        return self._league_readback(self.q(f"return H.league_propose_repeal({resolution_id}, {self._pid(pid)})"), pid)

    def league_cast_votes(self, votes: list[dict], pid: int | None = None) -> dict:
        """Vote on this session's World Congress proposals (see league_status()'s `votable` while
        in_session). Only valid when blocking_name is ENDTURN_BLOCKING_LEAGUE_CALL_FOR_VOTES -- a hard
        block like proposals, confirmed live (turn 243, First Rio de Janeiro Conference): casting the
        single available vote for the session's own "Sciences Funding" proposal cleared
        ENDTURN_BLOCKING_LEAGUE_CALL_FOR_VOTES immediately (blocking_name back to
        NO_ENDTURN_BLOCKING_TYPE in the same call). `votes`: a list of {"resolution_id": id,
        "direction": "enact"|"repeal", "num_votes": n, "choice": id (optional, for resolutions with
        voter choices)}. Any votes left over after these are automatically cast as abstain, matching
        the real UI's own always-abstain-the-remainder behaviour.

        Votes are irreversible, so rows are checked strictly first: live t315 a row spelled `votes` instead
        of `num_votes` was read as zero votes and all four delegates were silently cast as abstain."""
        allowed = {"resolution_id", "direction", "num_votes", "choice"}
        for i, row in enumerate(votes):
            if not isinstance(row, dict):
                return {"ok": False, "err": f"votes[{i}] must be an object", "expected_keys": sorted(allowed)}
            unknown = sorted(set(row) - allowed)
            n = row.get("num_votes")
            if unknown or "resolution_id" not in row or not isinstance(n, int) or isinstance(n, bool) or n < 1:
                return {"ok": False, "nothing_cast": True, "unknown_keys": unknown, "expected_keys": sorted(allowed),
                        "err": f"votes[{i}] needs resolution_id and a positive whole num_votes; "
                               "to abstain on purpose pass an empty votes list"}
        # Yes/no questions (every repeal, and enacts whose VoterDecision is RESOLUTION_DECISION_YES_OR_NO) take
        # choice 1 = yes / 0 = no -- leagueoverview.lua kChoiceYes/kChoiceNo. The old default -1 is kChoiceNone,
        # which the stock UI never sends for these (live t437: "yea" crashed SendLeagueVoteRepeal, and the
        # earlier choice-less World Religion repeal votes may not have counted either way).
        words = {"yes": 1, "yea": 1, "aye": 1, "for": 1, "no": 0, "nay": 0, "against": 0}
        votes = [dict(v) for v in votes]
        for i, row in enumerate(votes):
            c = row.get("choice")
            if isinstance(c, str):
                if c.strip().lower() not in words:
                    return {"ok": False, "nothing_cast": True,
                            "err": f"votes[{i}].choice {c!r}: use yes/no for yes-or-no proposals, or a choice id"}
                row["choice"] = words[c.strip().lower()]
            if row.get("choice") is None and self._league_vote_is_yes_no(row, pid):
                return {"ok": False, "nothing_cast": True,
                        "err": f"votes[{i}] is a yes-or-no proposal: pass choice \"yes\" or \"no\""}
        return self.q(f"return H.league_cast_votes({_lua_items(votes)}, {self._pid(pid)})")

    def _league_vote_is_yes_no(self, row: dict, pid: int | None = None) -> bool:
        if row.get("direction") == "repeal":
            return True
        try:
            st = self.league_status(pid)
        except TunerdError:
            return False
        rtype = next((v.get("resolution_type") for v in (st.get("votable") or []) if isinstance(v, dict)
                      and v.get("resolution_id") == row.get("resolution_id") and v.get("direction") == row.get("direction")), None)
        if not rtype:
            return False
        d = self.q(f"local r = GameInfo.Resolutions[{lua_str(rtype)}]; return {{d = r and r.VoterDecision}}")
        return isinstance(d, dict) and d.get("d") == "RESOLUTION_DECISION_YES_OR_NO"
