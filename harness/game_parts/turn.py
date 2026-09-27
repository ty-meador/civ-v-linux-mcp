"""The turn loop: turn_state, waiting for our turn, the hotseat hand-off, finish_turn and its wake reasons, end_turn."""
from __future__ import annotations

import time

from ..action_lock import LockBusy
from ..client import TunerdError, TunerConnectionLost

from .support import _game_busy_error, lua_table


class TurnMixin:
    """The turn loop: turn_state, waiting for our turn, the hotseat hand-off, finish_turn and its wake reasons, end_turn.

    A part of harness.game.Game (see harness/game_parts/__init__.py); `self` is the whole Game."""

    # ------------------------------------------------------------ state
    MODAL_FLAGS = ("leader_greeting_pending", "city_state_greeting_pending", "great_person_reward_pending",
                   "tech_popup_pending", "discussion_pending")

    def turn_state(self, pid: int | None = None) -> dict:
        ts = self.q(f"return H.turn_state({self._pid(pid)})")
        # pending_popups only tracks SerialEventGameMessagePopup. Greeting /
        # discussion / tech / great-person screens live in other Lua contexts
        # and can make end_turn silently no-op while that list is empty.
        # Runtime v214 reads them in the same query (H.modal_flags); an answer
        # without them gets one more query, not one per screen.
        if all(k in ts for k in self.MODAL_FLAGS):
            # trade_state stays on the status (the gate names accept_deal / refuse_deal by it; it used to be
            # popped here, so the runtime's answer never reached a caller: live t136, an AI offer at the hand-off)
            trade = ts.get("trade_state")
            if trade:
                self._trade_state = trade
            flags = ts
        else:
            flags = self._modal_flags()
            ts.update(flags)
        if pid is None or pid == self.seat:
            self._note_happiness(ts)
        if flags["leader_greeting_pending"] or flags["discussion_pending"]:
            # The engine does not re-evaluate the end-turn blocker while a leader screen is up: live t12,
            # ENDTURN_BLOCKING_POLICY stayed reported after the policy was adopted, until the greeting closed.
            ts["leader_screen_note"] = (
                "a leader screen is up: discussion() reads it, dismiss_discussion() closes a plain greeting. "
                "blocking_name/todo are frozen until it closes and may already be resolved")
        return ts

    def wait_for_my_turn(self, timeout: float = 3600, poll: float = 1.0, on_wait=None) -> dict:
        """Block until this seat may act. Hotseat: our seat is active and the hand-off modal is dismissed.
        LAN: our (local) player's turn is active and we have not yet sent turn-complete.

        Polls tunerd's `ping` alongside `turn_state` so a dropped connection surfaces immediately as
        TunerConnectionLost instead of silently spinning on stale-looking turn_state responses until
        `timeout` (the tuner-drop bug documented in docs/NOTES.md: the game's listener only re-arms on
        ExitToMainMenu/leaving the MP staging room, so a drop here will not self-heal).

        Also dismisses an informational LeaderHeadRoot popup (first-contact greeting, or an echo of a
        war/peace we just made -- see leader_greeting_pending()'s docstring for why those three are safe
        to auto-dismiss and nothing else is). Confirmed live: without this, turn_state's `my_turn` stays
        false the entire time that popup is up, so this loop just spun silently to the full `timeout`
        with no indication anything needed attention -- the fix a user had to point out live.

        A real negotiation/demand/trade-offer (discussion_pending()) is NOT auto-dismissed the same way --
        it's a genuine decision, not an echo -- but it has the identical silent-hang shape (my_turn stuck
        false, no other signal), confirmed live the same session: this loop spun for minutes with the game
        sitting on a leader's trade screen before the user spotted it on-screen and said so. So this
        returns early with `{..., "discussion_pending": true}` merged into the normal turn_state instead of
        continuing to poll to `timeout` -- call dismiss_discussion() to leave it (no accept path exists
        yet, see its docstring), then call wait_for_my_turn() again.

        `on_wait(elapsed_seconds, turn_state)` is called once per poll while still waiting; the MCP layer
        turns it into progress notifications so a client's idle timeout does not kill a long wait."""
        deadline = time.monotonic() + timeout
        started = time.monotonic()
        was_connected = None
        last_ts: dict = {}
        busy = None
        while time.monotonic() < deadline:
            if on_wait is not None:
                on_wait(time.monotonic() - started, last_ts)
            # One poll is one operation: the lock (mcp_server's per-socket action_lock; nothing elsewhere)
            # covers the reads and any dismissal, and is released before the sleep, so another seat's
            # server gets in between polls. Held across the whole wait, an inactive seat's 300 s
            # finish_turn starved the active seat's every call (Codex/Grok hotseat 2026-09-26, NOTES.md).
            # A lock still busy after its 10 s is the other seat's long operation (its end_turn): that poll
            # is skipped, not the wait. Raised, it ended a 600 s finish_turn as timed_out after 24 s
            # (Venice/Mongolia t50, 2026-09-27).
            try:
                with self.lock():
                    if was_connected is None:
                        was_connected = bool(self.c.ping().get("connected"))
                    was_connected, ts, done, again = self._poll_my_turn(was_connected)
            except LockBusy as e:
                busy = str(e)
                continue
            except TunerConnectionLost:
                raise
            except TunerdError as e:
                # The game answers the tuner late while it works through the AI turns (a seat that follows
                # them waits across all of it): a state list that came back empty or a command that hit
                # its 10 s is that poll's answer, not the wait's. Live 2026-09-27: "no Lua state named
                # 'InGame'; have []" ended three Codex cycles in a row, each in a finish_turn after the
                # other seat's turn, and the next call found the game fine.
                if not _game_busy_error(e):
                    raise
                busy = str(e)
                time.sleep(poll)
                continue
            last_ts = ts
            if done is not None:
                return done
            if not again:
                time.sleep(poll)
        raise TimeoutError("timed out waiting for our turn" + (f"; the last poll found: {busy}" if busy else ""))

    def _poll_my_turn(self, was_connected: bool) -> tuple[bool, dict, dict | None, bool]:
        """One poll of wait_for_my_turn, under the operation lock: (connected, turn_state, result or None,
        poll again at once). `again` is set when a leader remark was just dismissed and the state is worth
        re-reading without the usual sleep."""
        connected = bool(self.c.ping().get("connected"))
        if was_connected and not connected:
            raise TunerConnectionLost(
                "tunerd lost its connection to the game while waiting for our turn -- the game's "
                "listener only re-arms on ExitToMainMenu/leaving the MP staging room, so this instance "
                "likely needs to be torn down and relaunched rather than retried"
            )
        was_connected = connected
        ts = self.turn_state()
        if was_connected and not self.c.ping().get("connected"):
            raise TunerConnectionLost("game connection lost while reading turn state")
        if ts.get("active_player", self.seat) != self.seat:
            return was_connected, ts, None, False
        # v214: one turn_state carries every screen flag, and the sweep reuses it; a poll with nothing
        # up is two round-trips (was ~25: the profiled S1 t270 wait spent 157 trips on 50 s of AI round).
        if self.dismiss_pending_popups(ts):
            time.sleep(0.5)
            ts = self.turn_state()
        if ts.get("hotseat") and self.player_change_pending(ts):
            # Our own Continue screen is pressed before anything else is read: it is what the seat's human
            # does first, and nothing about the game changes between the hand-off and the press. Live
            # 2026-09-27 (Codex, t55): China's trade offer came up with the hand-off screen, the discussion
            # check below returned before the press further down ever ran, and the `hand_off_screen` gate
            # then blamed a press nobody had attempted -- the tool it named, this one, looped on itself.
            self.dismiss_player_change()
            time.sleep(0.5)
            ts = self.turn_state()
        if ts.get("discussion_pending"):
            d = self.discussion()
            if d.get("screen") == "discussion" and not d.get("buttons") and d.get("can_go_back"):
                # A leader remark with nothing to answer (e.g. "Very well." after a deal): the only
                # control is Back. Real choices (buttons) or a trade table always stop here.
                self.dismiss_discussion()
                time.sleep(0.5)
                return was_connected, ts, None, True
            return was_connected, ts, {**self.turn_state(), "discussion_pending": True, "discussion": d}, False
        if ts.get("tech_popup_pending"):
            # Only auto-dismiss once research is actually chosen (GetCurrentResearch() != -1) --
            # dismissing an unresolved choice would leave research silently unset with no reliable
            # blocking signal to catch it (see tech_popup_pending()'s docstring), trading one silent
            # hang for a worse one. If research is still unset, return immediately so the caller
            # can pick a tech instead of polling until timeout with my_turn stuck false.
            cur = self.q(f"return Players[{self._pid(None)}]:GetCurrentResearch()")
            if cur != -1:
                self.dismiss_tech_popup()
                time.sleep(0.5)
                ts = self.turn_state()
            else:
                return was_connected, ts, {**ts, "tech_popup_pending": True}, False
        if ts["my_turn"] and not ts["processing"]:
            if ts["hotseat"] and self.player_change_pending(ts):
                self.dismiss_player_change()
                time.sleep(0.5)
                ts = self.turn_state()
            ts = self._arrive(ts)
            late = self._late_discussion(ts)
            if late is not None:
                return was_connected, late, late, False
            return was_connected, ts, ts, False
        return was_connected, ts, None, False

    def _late_discussion(self, ts: dict) -> dict | None:
        """An AI's approach can land a moment after the turn became ours: the wait answered
        discussion_pending=false and the caller's very next order was refused "diplomatic decision pending"
        (Mongolia t126 and t127, 2026-09-27: a friendship offer, then a leader remark). One more look before the
        turn is handed back. A remark with nothing to answer is dismissed as the poll does; a real screen comes
        back as the wait's answer, with what the arrival already read (orders, resumed moves, expiring allies)."""
        time.sleep(self._LATE_DISCUSSION_SETTLE)
        try:
            ts2 = self.turn_state()
        except TunerdError:
            return None
        if not ts2.get("discussion_pending"):
            return None
        d = self.discussion()
        if d.get("screen") == "discussion" and not d.get("buttons") and d.get("can_go_back"):
            self.dismiss_discussion()
            return None
        keep = {k: v for k, v in ts.items() if k in ("orders", "resumed_moves", "expiring_city_states")}
        return {**ts2, **keep, "discussion_pending": True, "discussion": d}

    _LATE_DISCUSSION_SETTLE = 0.4   # seconds; tests shorten it

    def clear_hand_off(self, ts: dict) -> dict:
        """Our own hotseat hand-off screen ("<leader>'s turn -- Continue") is up: press it and hand back the
        turn exactly as wait_for_my_turn would (standing orders resumed, expiring city-states listed), marked
        `hand_off_cleared`. Any other state comes back untouched: another seat's screen is never pressed
        (active_player must be our seat), and a screen that stays up after two presses is left to the
        `hand_off_screen` gate, which is then an honest report of a press that did not take.

        Every guarded tool and turn_status call this, so an agent that (re)starts on its own Continue screen
        gets a game state, not a UI gate to clear first. Live 2026-09-26 (Codex, t22 and t24): the status
        said paused/popup_up under that screen, orders were refused, and the one tool that would have pressed
        it -- wait_for_my_turn -- was the last one tried. The press is what the seat's human would do before
        anything else; nothing about the game changes between the hand-off and Continue."""
        if not (isinstance(ts, dict) and ts.get("hotseat") and ts.get("active_player") == self.seat
                and self.player_change_pending(ts)):
            return ts
        for _ in range(2):
            try:
                self.dismiss_player_change()
            except TunerdError:
                break
            time.sleep(0.5)
            ts = self.turn_state()
            if not ts.get("hand_off_pending"):
                if ts.get("my_turn") and not ts.get("processing"):
                    ts = self._arrive(ts)
                ts["hand_off_cleared"] = True
                return ts
        return ts

    def _arrive(self, ts: dict) -> dict:
        """Our turn has just become playable: what happens once at its start, whichever call got there first.
        Standing move orders (move_unit destinations not yet reached) do not resume on their own at turn
        start; re-issue them now so the caller's "go to X" completes like a human's. A unit an open conditional
        order owns (#32) is left to the order, which runs afterwards: its checks come before its next step."""
        try:
            owned = [o["unit"]["id"] for o in self.notebook().orders("open")]
        except Exception:  # noqa: BLE001 -- an unreadable notebook must not block the hand-off either
            owned = []
        try:
            skip = f", {lua_table(owned)}" if owned else ""
            resumed = self.q(f"return H.resume_moves({self.seat}{skip})") or []
        except Exception:  # noqa: BLE001 -- never let this block the turn hand-off
            resumed = []
        expiring = self.expiring_city_states()
        if resumed:
            time.sleep(0.5)
            ts = self.turn_state()
            ts["resumed_moves"] = resumed
            # A dropped order's own err is the real advice (live t326: todo said "re-issue
            # move_unit" while resumed_moves said an enemy now stands on the destination).
            # "resumed" only meant the order was re-issued (live t333: a Missionary reported resumed, still
            # at full moves in Beijing -- a Worker held the destination city plot). Check it moved.
            try:
                by_id = {u.get("id"): u for u in self._unit_rows()}
            except TunerdError:
                by_id = {}
            for r in resumed:
                u = by_id.get(r.get("unit_id")) if isinstance(r, dict) and r.get("resumed") else None
                if u and (u.get("x"), u.get("y")) != (r.get("x"), r.get("y")) and u.get("moves") == u.get("max_moves"):
                    r["resumed"], r["dropped"] = False, True
                    r["err"] = ("re-issued but the unit did not move: the engine found no path; "
                                + (self._blocker_hint(u, r.get("x"), r.get("y"), by_id.values())
                                   or self._foreign_occupant_hint(r.get("x"), r.get("y")) or "pick another plot"))
            dropped = {r.get("unit_id"): r.get("err") for r in resumed
                       if isinstance(r, dict) and r.get("dropped") and r.get("err")}
            todo = ts.get("todo") if isinstance(ts.get("todo"), dict) else {}
            for u in todo.get("units") or []:
                if isinstance(u, dict) and u.get("id") in dropped:
                    u["note"] = dropped[u["id"]]
        if owned:
            orders = self._turn_start_orders(ts)
            if orders:
                if any(r.get("did") for r in orders.get("rows") or []):
                    time.sleep(0.3)
                    ts = {**self.turn_state(), **{k: v for k, v in ts.items() if k == "resumed_moves"}}
                ts["orders"] = orders
                # A unit whose order paused is back in my hands: say why on its todo row.
                held = {r["unit"]["id"]: r for r in orders.get("rows") or [] if r.get("status") in ("paused", "failed")}
                todo = ts.get("todo") if isinstance(ts.get("todo"), dict) else {}
                for u in todo.get("units") or []:
                    r = held.get(u.get("id")) if isinstance(u, dict) else None
                    if r:
                        u["order"] = {"id": r["id"], "status": r["status"], **({"reason": r["pause"].get("reason")}
                                                                               if r.get("pause") else {})}
        if expiring:
            ts["expiring_city_states"] = expiring
        return ts

    # ------------------------------------------------------------ the turn boundary as one call
    # Event kinds and notification words that end a run of quiet turns (finish_turn's skip_quiet_turns).
    # A human alt-tabbing during a dull stretch is pulled back by exactly these: fighting, losses, cities
    # changing hands, wars, someone at the door. Bookkeeping kinds (turn_start/turn_end/active_player,
    # a unit model rebuilt) never wake anyone.
    WAKE_KINDS = frozenset({"combat", "damage", "unit_lost", "unit_hurt", "unit_destroyed", "unit_captured",
                            "city_captured", "city_destroyed", "city_created", "civ_eliminated", "war_state",
                            "leader_message", "chat", "popup_shown"})

    WAKE_WORDS = ("war", "attack", "captured", "destroyed", "denounc", "wonder", "expired", "declar", "pillag",
                  "razed", "revolt", "unhappi", "starv", "spy", "coup", "intrigue", "religion", "converted",
                  "barbarian", "great ", "golden age", "ideolog", "world congress", "resolution", "election",
                  "ally", "friend", "insult", "demand", "trade route", "caravan", "cargo ship",
                  # the top-of-screen banners (event kind "alert") that pull a human back
                  "enemy", "spotted", "killed", "defeated", "withdraw", "intercept", "shot down", "plunder")

    # turn_status.alerts (#39). The runtime puts the facts on every status (happiness total, unhappy tier,
    # strategic deficits, for this seat only); this process remembers the total it last saw at the previous
    # turn so a quiet-turn run wakes on a DROP or a tier beginning, never on a steady low number -- a
    # Circus takes several turns at happiness 1, and waking on each would make skip_quiet_turns useless.
    UNHAPPY_RANK = {None: 0, "unhappy": 1, "very_unhappy": 2, "super_unhappy": 3}

    @staticmethod
    def _happiness_record(ts: dict) -> tuple | None:
        """(turn, happiness, tier, {resource: available}) from a status, or None when it carries no total
        (an older runtime, a status from the main menu)."""
        if not isinstance(ts.get("turn"), int) or not isinstance(ts.get("happiness"), int):
            return None
        deficits = {a["resource"]: a["available"] for a in ts.get("alerts") or []
                    if isinstance(a, dict) and a.get("kind") == "strategic_deficit"
                    and isinstance(a.get("available"), int) and isinstance(a.get("resource"), str)}
        return ts["turn"], ts["happiness"], ts.get("unhappy"), deficits

    def _note_happiness(self, ts: dict) -> None:
        """Remember this seat's happiness as of the status just read. The record for the turn being read
        is overwritten on every read (the last value seen); the record it replaced when the turn number
        changed becomes the baseline. A turn number going backwards is a reloaded save: no baseline."""
        rec = self._happiness_record(ts)
        if rec is None:
            return
        seen = self.__dict__.setdefault("_happiness_seen", {})
        prev = self.__dict__.setdefault("_happiness_prev", {})
        cur = seen.get(self.seat)
        if cur is None or cur[0] != rec[0]:
            prev[self.seat] = cur if (cur is not None and rec[0] > cur[0]) else None
        seen[self.seat] = rec

    def _alert_wake_reasons(self, ts: dict) -> list[str]:
        """Why the alerts on `ts` end a quiet-turn run: happiness below the previous turn's last value, an
        unhappy tier beginning or deepening, a strategic deficit appearing or deepening. Nothing without
        a baseline (the first turn this process saw) and nothing while the same figures hold."""
        rec = self._happiness_record(ts)
        prev = (getattr(self, "_happiness_prev", None) or {}).get(self.seat)
        if rec is None or prev is None or prev[0] >= rec[0]:
            return []
        out: list[str] = []
        _, h, tier, deficits = rec
        _, p_h, p_tier, p_deficits = prev
        if h < p_h:
            out.append(f"happiness_drop:{p_h}->{h}")
        if self.UNHAPPY_RANK.get(tier, 0) > self.UNHAPPY_RANK.get(p_tier, 0):
            out.append(f"unhappy:{tier}")
        for name in sorted(deficits):
            if deficits[name] < p_deficits.get(name, 0):
                out.append(f"strategic_deficit:{name}:{deficits[name]}")
        return out

    def _claim_turn(self, ts: dict, tool: str, force: bool = False) -> dict | None:
        """Own this seat's current turn for `tool` (turn_claim.py). None when the turn is ours or nobody's;
        the refusal dict (ok False, err, turn_claim) when another live client of the seat holds it."""
        if self.claim is None:
            return None
        from ..turn_claim import ClaimRefused
        try:
            self.claim(ts.get("turn"), tool, force)
        except ClaimRefused as e:
            return {"ok": False, "err": str(e), "turn_claim": e.info, "turn": ts.get("turn")}
        return None

    def finish_turn(self, autosave: bool = True, timeout: float = 600, on_wait=None,
                    skip_quiet_turns: int = 0, wake_on: list[str] | None = None, force: bool = False) -> dict:
        """End the turn, wait for the next one, and hand it back with everything that happened: one call is one
        turn boundary. Safe to call again after a client timeout -- when it is no longer our turn it does not
        end anything, it only waits (so a retried call never ends two turns).

        `skip_quiet_turns=N` keeps ending turns, up to N more, as long as each new turn is quiet: nothing in
        todo, no blocker, no popup, no expiring city-state, and nothing in the digest matching WAKE_KINDS /
        WAKE_WORDS or the caller's own `wake_on` words (matched case-insensitively against event kinds and
        notification text). `status.alerts` (#39: low happiness, an unhappy tier, strategic deficits) wakes
        the run only when it worsens against the previous turn this process saw (_alert_wake_reasons); the
        same low total across a multi-turn build does not. Cities keep building and research keeps ticking; the harness never issues an
        order on the caller's behalf. The digests of skipped turns are merged into the result.

        Result: ok, turn, status (turn_state), digest, turns_skipped, woke_because (why the run stopped),
        and any of discussion_pending / tech_popup_pending / timed_out that need the caller's attention.

        Another client of this seat that issued the turn's first order owns the turn (turn_claim.py): the
        end is then refused with `turn_claim` naming it, unless `force`. The ends of a quiet-turn run claim
        each new turn for this process; if a second client acts on one of them first, the run stops and
        hands that turn back (woke_because other_client_holds_turn) instead of ending it under them."""
        wake_words = tuple(w.lower() for w in (wake_on or []) if isinstance(w, str) and w.strip())
        merged: dict = {"events": [], "notifications": []}
        skipped = 0
        ended_any = False
        while True:
            # Each step is its own operation under the lock (see wait_for_my_turn): the end-turn, then
            # the wait's polls one by one, then the digest. The other seat's server acts in between.
            with self.lock():
                ts = self.turn_state()
                self._note_happiness(ts)
                # Under our own hand-off screen my_turn already reads true; that turn has not been seen yet,
                # so it is not ours to end (a finish_turn retried after a client timeout would otherwise end
                # the new turn blind): the wait below presses Continue and hands it back instead.
                mine = (ts.get("active_player") == self.seat and ts.get("my_turn") and not ts.get("processing")
                        and not (ts.get("hotseat") and ts.get("hand_off_pending")))
                if mine:
                    refused = self._claim_turn(ts, "finish_turn", force)
                    if refused is not None:
                        if ended_any:
                            # `skipped` was counted up for this turn before its end was tried: it is handed
                            # back, not skipped.
                            return {"ok": True, "ended": True, "turn": ts.get("turn"), "status": ts, "digest": merged,
                                    "turns_skipped": max(0, skipped - 1), "woke_because": ["other_client_holds_turn"],
                                    "turn_claim": refused["turn_claim"]}
                        refused.update({"ended": False, "turns_skipped": skipped})
                        return refused
                    if on_wait is not None:
                        on_wait(0.0, {"ending_turn": ts.get("turn")})
                    r = self.end_turn(autosave)
                    if not r.get("ok"):
                        out = {"ok": False, "ended": False, "turn": ts.get("turn"), "end_turn": r,
                               "status": self.turn_state(), "turns_skipped": skipped}
                        if merged["events"] or merged["notifications"]:
                            out["digest"] = merged
                        return out
                    ended_any = True
            try:
                ts = self.wait_for_my_turn(timeout=timeout, on_wait=on_wait)
            except TimeoutError:
                with self.lock():
                    ts = self.turn_state()
                ts.update({"ok": True, "ended": ended_any, "timed_out": True, "turns_skipped": skipped,
                           "hint": "still not my turn; call finish_turn again (it will only wait, not end another turn)"})
                if merged["events"] or merged["notifications"]:
                    ts["digest"] = merged
                return ts
            self._note_happiness(ts)
            with self.lock():
                digest = self.turn_digest()
            merged["events"].extend(digest.get("events") or [])
            merged["notifications"].extend(digest.get("notifications") or [])
            out = {"ok": True, "ended": ended_any, "turn": ts.get("turn"), "status": ts, "digest": merged,
                   "turns_skipped": skipped}
            for flag in ("discussion_pending", "tech_popup_pending"):
                if ts.get(flag):
                    out[flag] = True
                    out["woke_because"] = [flag]
                    return out
            reasons = self._wake_reasons(ts, digest, wake_words)
            if skipped >= skip_quiet_turns or reasons:
                out["woke_because"] = reasons or (["quiet_turn_budget_used"] if skip_quiet_turns else ["turn_started"])
                return out
            skipped += 1
            out_turn = ts.get("turn")
            if on_wait is not None:
                on_wait(0.0, {**ts, "skipping_quiet_turn": out_turn})

    def _wake_reasons(self, ts: dict, digest: dict, wake_words: tuple[str, ...] = ()) -> list[str]:
        """Why this turn is not quiet: empty means nothing needs the caller."""
        reasons: list[str] = []
        todo = ts.get("todo") if isinstance(ts.get("todo"), dict) else {}
        for k, v in todo.items():
            # `stacked` is a warning (two of my combat units share a plot; the engine lets the turn end), not a
            # decision: the unit that needs orders is in todo.units already (Codex c41, 2026-09-27: a quiet run
            # woke on "todo.stacked" alone, for a stack its own note called non-blocking).
            if v and k not in ("steal_tech_hint", "ongoing", "stacked"):
                reasons.append(f"todo.{k}")
        # #37: an ongoing unit (automated, or on a standing move) is not a decision; it wakes the run only
        # when the runtime attached `attention` -- a visible camp or hostile beside it, or a destination it
        # can no longer reach. An explorer simply walking lets the run continue.
        for u in todo.get("ongoing") or []:
            if isinstance(u, dict):
                for a in u.get("attention") or []:
                    if isinstance(a, dict) and a.get("kind"):
                        reasons.append(f"ongoing:{u.get('id')}:{a['kind']}")
        # #32: an order that paused, failed or finished at this turn start hands its unit back.
        orders = ts.get("orders") if isinstance(ts.get("orders"), dict) else {}
        for r in orders.get("rows") or []:
            if isinstance(r, dict) and r.get("status") in ("paused", "failed", "completed") and r.get("did"):
                reasons.append(f"order:{r.get('id')}:{r['status']}")
        if orders.get("not_run"):
            reasons.append("orders_not_run")
        name = ts.get("blocking_name")
        if name and name != "NO_ENDTURN_BLOCKING_TYPE":
            reasons.append(f"blocking:{name}")
        # #38: expiring_deals / expiring_friendships are the majors' version of the city-state warning.
        for k in ("pending_popups", "expiring_city_states", "expiring_deals", "expiring_friendships",
                  "leader_greeting_pending", "great_person_reward_pending", "city_state_greeting_pending", "game_over"):
            if ts.get(k):
                reasons.append(k)
        if ts.get("alive") is False:
            reasons.append("dead")
        reasons.extend(self._alert_wake_reasons(ts))   # #39: a drop or a new tier/deficit, not a steady low total
        words = tuple(w.lower() for w in self.WAKE_WORDS) + wake_words
        for e in digest.get("events") or []:
            kind = str(e.get("kind", ""))
            if kind in self.WAKE_KINDS or any(w in kind.lower() for w in wake_words):
                reasons.append(f"event:{kind}")
            elif kind == "alert" and isinstance(e.get("data"), dict):
                # A GameplayAlertMessage banner: "Work has now begun on a Colosseum." / "You have discovered
                # Trapping!" woke every quiet run (15 of 50 wakes, live 2026-09-27, Grok). Only a banner that
                # names hostiles or reads like one of the words above ends the run.
                text = str(e["data"].get("text", "")).lower()
                if e["data"].get("hostiles") or any(w in text for w in words):
                    reasons.append(f"alert:{str(e['data'].get('text'))[:60]}")
            elif kind == "notification" and isinstance(e.get("data"), dict):
                text = " ".join(str(e["data"].get(k, "")) for k in ("summary", "text")).lower()
                if any(w in text for w in words):
                    reasons.append(f"notification:{str(e['data'].get('summary') or e['data'].get('text'))[:60]}")
        for n in digest.get("notifications") or []:
            if isinstance(n, dict):
                text = " ".join(str(n.get(k, "")) for k in ("summary", "text")).lower()
                if any(w in text for w in words):
                    reasons.append(f"notification:{str(n.get('summary') or n.get('text'))[:60]}")
        return reasons

    # end_turn confirms the sent CONTROL_ENDTURN took: up to this many polls, this far apart (tests shorten them).
    _END_TURN_CONFIRM_POLLS = 12
    _END_TURN_STALE_SETTLE = 0.75   # seconds before the one re-send against a blocker the engine had not re-read

    _END_TURN_CONFIRM_SLEEP = 0.25

    def end_turn(self, autosave: bool = True, force: bool = False) -> dict:
        """Same path as the End Turn button. In network games a second call after turn-complete was sent
        would UN-ready us (Network.SendTurnUnready), so that case is refused here.

        Dismisses any pending informational popup first (see dismiss_pending_popups()) -- confirmed live
        that DoControl(CONTROL_ENDTURN) silently no-ops while one is up, with zero signal in the return
        value (ok:true, blocking_before=-1 every time): a caller not also polling wait_for_my_turn (which
        handles this too) would see this call "succeed" ~19 times in a row on the same turn number.

        `autosave=True` (default) calls `UI.QuickSave()` right before `CONTROL_ENDTURN`, single-player only
        (`not IsNetworkMultiPlayer()` -- untested in hotseat/LAN, where a mid-turn quicksave's semantics
        aren't confirmed, so left opt-in there via the standalone `quick_save()`). Cheap insurance against
        this game's frequent ambient crashes (see docs/NOTES.md's CPU-affinity/`taskset` entry) -- losing
        the current turn's actions is now the worst case on a crash, not several turns back to the last
        autosave. Only fires once every other precondition below has already passed, so a failed/refused
        end_turn never saves. Pass `autosave=False` to skip (e.g. calling this in a tight retry loop)."""
        ts = self.turn_state()
        if ts.get("active_player") != self.seat:
            return {"ok": False, "err": "this seat is not active"}
        refused = self._claim_turn(ts, "end_turn", force)   # another client of this seat owns the turn (#41)
        if refused is not None:
            return refused
        if ts.get("discussion_pending"):
            return {"ok": False, "err": "diplomatic decision pending"}
        if self.dismiss_pending_popups(ts):
            time.sleep(0.5)
        autosave_lua = "if not Game.IsNetworkMultiPlayer() then UI.QuickSave() end" if autosave else ""
        turn_before = ts.get("turn")
        r = self._end_turn_send(autosave_lua)
        if not r.get("ok") or r.get("turn_complete_sent"):
            return r
        # Single player and hotseat: ok only meant CONTROL_ENDTURN was sent. A unit with part of its moves left (e.g.
        # a worker that finished its route) makes the engine refuse it with no signal, and the caller waited on a
        # turn that never ended (live t112, t115). Confirm the turn actually left us. Hotseat used to return here
        # at once, and finish_turn's first poll then read the not-yet-processed end as the same turn still ours:
        # it came back with turn 93 / my_turn true while the game was already on seat 0's turn 94 (Mongolia,
        # 2026-09-27), so the caller acted on a turn that was over.
        for attempt in range(2):
            for _ in range(self._END_TURN_CONFIRM_POLLS):
                time.sleep(self._END_TURN_CONFIRM_SLEEP)
                ts = self.turn_state()
                if (not ts.get("my_turn") or ts.get("turn") != turn_before or ts.get("processing")
                        or ts.get("active_player") != self.seat):
                    r["confirmed"] = True
                    if attempt:
                        r["resent"] = "the first CONTROL_ENDTURN met a blocker the engine had not re-evaluated yet"
                    return r
            ts = self.turn_state()
            popups = bool(ts.get("pending_popups"))
            if attempt or not (popups or self._blocker_is_stale(ts)):
                break
            # The engine re-evaluates the end-turn blocker on its next update, so CONTROL_ENDTURN sent right
            # after the order that cleared it is discarded against the old one (live t139, Mongolia: set_production
            # then end_turn in one batch, "the turn did not end" with PRODUCTION named and no empty city). An
            # announcement that arrived after the sweep above (live t153: the Great Work splash a moment after
            # the artist's order) discards it too; sweep again. One settle and one more send, no second quick-save.
            if popups:
                self.dismiss_pending_popups(ts)
            time.sleep(self._END_TURN_STALE_SETTLE)
            r = self._end_turn_send("")
            if not r.get("ok") or r.get("turn_complete_sent"):
                return r
        diag = self.q(f"return H.end_turn_diagnosis({self.seat})")
        diag = diag if isinstance(diag, dict) else {}
        # Prefer the engine's own answer over a guess: when UI.CanEndTurn() is false the stock End Turn
        # button is greyed out and CONTROL_ENDTURN is discarded, which is a different situation from a
        # unit that still needs orders -- and the old message claimed the latter either way.
        why = diag.get("note") or ts.get("blocking_hint") or "a unit or decision still blocks it"
        return {"ok": False, "err": "CONTROL_ENDTURN was sent but the turn did not end: " + why,
                "blocking": ts.get("blocking_name"), "todo": ts.get("todo"), "engine": diag}

    @staticmethod
    def _blocker_is_stale(ts: dict) -> bool:
        """The engine names a blocker the todo no longer shows: PRODUCTION with no empty city, RESEARCH with
        research set, or the UNITS case turn_state already marks (`blocking_stale`)."""
        if not isinstance(ts, dict):
            return False
        if ts.get("blocking_stale"):
            return True
        todo = ts.get("todo") if isinstance(ts.get("todo"), dict) else {}
        name = ts.get("blocking_name")
        if name == "ENDTURN_BLOCKING_PRODUCTION":
            return not todo.get("cities")
        if name == "ENDTURN_BLOCKING_RESEARCH":
            return not todo.get("research_unset")
        return False

    def _end_turn_send(self, autosave_lua: str) -> dict:
        return self.q(f"""
            if Game.GetActivePlayer() ~= {self.seat} then return {{ok=false, err="this seat is not active"}} end
            local p = Players[{self.seat}]
            if Game.IsPaused() then return {{ok=false, err="game is paused"}} end
            if not p:IsTurnActive() then return {{ok=false, err="turn not active"}} end
            if Game.IsProcessingMessages() then return {{ok=false, err="game is processing messages; retry"}} end
            if Game.IsNetworkMultiPlayer() and Network.HasSentNetTurnComplete() then
                return {{ok=false, err="turn-complete already sent; waiting for the other players"}}
            end
            local blocking = p:GetEndTurnBlockingType()
            local todo = H.todo({self.seat})
            -- GitLab #23: ENDTURN_BLOCKING_UNITS with no ready unit is a reading the engine froze while a
            -- popup was up, not a unit that needs orders. Refusing on it named an empty todo; the popup
            -- (swept by end_turn() before this call, or waiting for an answer) is the real blocker.
            local stale = H.stale_units_blocker(p, blocking, todo)
            if blocking ~= -1 and not stale then
                local name = H.blocking_name(blocking)
                return {{ok=false, err="turn has unresolved decisions: " .. H.blocking_hint(name), blocking=name, todo=todo}}
            end
            local popups = H.pending_popups({self.seat})
            if #popups > 0 then
                return {{ok=false, err="popup needs attention" .. (stale and " (ENDTURN_BLOCKING_UNITS is stale: no unit needs orders; the engine re-evaluates its blocker once the popup is processed)" or ""),
                         pending_popups=popups, blocking=stale and H.blocking_name(blocking) or nil, blocking_stale=stale and true or nil}}
            end
            {autosave_lua}
            Game.DoControl(GameInfoTypes.CONTROL_ENDTURN)
            return {{ok=true, blocking_before=blocking, blocking_stale=stale and true or nil, turn_complete_sent=Game.IsNetworkMultiPlayer() and Network.HasSentNetTurnComplete() or false}}""")

    def unready_turn(self) -> dict:
        """Network games: take back a sent turn-complete (only works until every player has ended)."""
        return self.q("if Network.HasSentNetTurnComplete() then return {ok=Network.SendTurnUnready()} end return {ok=false, err='turn-complete not sent'}")
