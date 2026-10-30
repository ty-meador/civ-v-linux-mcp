"""The turn loop: turn_state, waiting for our turn, the hotseat hand-off, finish_turn and its wake reasons, end_turn."""
from __future__ import annotations

import re
import time

from ..action_lock import LockBusy
from ..client import TunerdError, TunerConnectionLost

from .support import _game_busy_error


def note_held_units(units: list, order_rows: list) -> None:
    """A unit whose order paused or failed is back in my hands: say so on its todo row (`order`). The Lua row
    calls an idle standing move "queued move did not resume; re-issue move_unit"; when the order holding it
    paused, that is the reason, and the note says what to do with the order instead (live Assyria t13: the
    Warrior's garrison order paused on a Brute two plots away and the row said both)."""
    held = {r["unit"]["id"]: r for r in order_rows if isinstance(r, dict) and r.get("status") in ("paused", "failed")}
    for u in units:
        r = held.get(u.get("id")) if isinstance(u, dict) else None
        if not r:
            continue
        u["order"] = {"id": r["id"], "status": r["status"], **({"reason": r["pause"].get("reason")} if r.get("pause") else {})}
        if u.get("stalled_mission"):
            u["note"] = ("its order paused (order.reason): notebook(action='resume_order') carries on, notebook(action='cancel_order') drops it, or a new "
                         "order(to='unit', action='move') replaces it" if r["status"] == "paused"
                         else "its order failed (see notebook(action='orders')): a new order(to='unit', action='move') or notebook(action='give_order') replaces it")


class TurnMixin:
    """The turn loop: turn_state, waiting for our turn, the hotseat hand-off, finish_turn and its wake reasons, end_turn.

    A part of harness.game.Game (see harness/game_parts/__init__.py); `self` is the whole Game."""

    # ------------------------------------------------------------ state
    MODAL_FLAGS = ("leader_greeting_pending", "city_state_greeting_pending", "great_person_reward_pending",
                   "tech_popup_pending", "discussion_pending")

    def turn_state(self, pid: int | None = None) -> dict:
        ts = self.q(self.h('turn_state', pid=pid))
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
                "a leader screen is up: question() reads it, answer(choice='leave') closes a plain greeting. "
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
        if ts.get("game_over"):
            # Live 2026-10-04 t253 (Mongolia replay): Russia won in the AI round, GAMESTATE_OVER, my_turn never
            # came back -- the wait ran to its timeout and finish_turn said "call again". The over state is
            # the answer: nothing further happens in this game.
            return was_connected, ts, {**ts, "game_over": True}, False
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
        if ts.get("load_screen_pending"):
            # The Dawn of Man splash of a single-player game the human started by hand (or loaded from the
            # menu): the game is paused for this seat until its button is pressed, and only the harness's own
            # load used to press it. Live 2026-10-27 (Maya t0, GitLab #96): the `paused` gate sent the agent to
            # this wait, which returned at once with the same gate, forever. Press it as _finish_load does.
            self._dismiss_load_screen()
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
            cur = self.q(self.h("current_research"))
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
            # An announcement raised at the turn's start (a Great Person born, a city-state met, a wonder) lands
            # in the same moment as a late leader remark; the re-read above is the one that sees it. Close it
            # here, so the turn handed back is one to play, not a screen to clear (settle_announcements).
            fresh = self._arrival_state if isinstance(self._arrival_state, dict) else ts
            if self.announcement_pending(fresh):
                settled = self.settle_announcements(fresh)
                keep = {k: v for k, v in ts.items() if k in ("orders", "resumed_moves", "expiring_city_states")}
                ts = {**settled, **keep}
            return was_connected, ts, ts, False
        return was_connected, ts, None, False

    def _late_discussion(self, ts: dict) -> dict | None:
        """An AI's approach can land a moment after the turn became ours: the wait answered
        discussion_pending=false and the caller's very next order was refused "diplomatic decision pending"
        (Mongolia t126 and t127, 2026-09-27: a friendship offer, then a leader remark). One more look before the
        turn is handed back. A remark with nothing to answer is dismissed as the poll does; a real screen comes
        back as the wait's answer, with what the arrival already read (orders, resumed moves, expiring allies)."""
        time.sleep(self._LATE_DISCUSSION_SETTLE)
        self._arrival_state = None
        try:
            ts2 = self.turn_state()
        except TunerdError:
            return None
        self._arrival_state = ts2   # the freshest read of the arrived turn, for the announcement settle
        if not ts2.get("discussion_pending"):
            return None
        d = self.discussion()
        if d.get("screen") == "discussion" and not d.get("buttons") and d.get("can_go_back"):
            self.dismiss_discussion()
            return None
        keep = {k: v for k, v in ts.items() if k in ("orders", "resumed_moves", "expiring_city_states")}
        return {**ts2, **keep, "discussion_pending": True, "discussion": d}

    _LATE_DISCUSSION_SETTLE = 0.4   # seconds; tests shorten it
    _arrival_state: dict | None = None   # the turn_state _late_discussion read last, or None
    _arrived_at: tuple | None = None     # (turn, seat) _arrive last ran for

    ARRIVAL_KEYS = ("orders", "resumed_moves", "expiring_city_states")   # what the arrival reports, as the wait does

    def arrival_due(self, ts) -> bool:
        """Whether this turn's arrival work has yet to run: my turn, playable (no screen up, nothing processing)
        and _arrive not run for this (turn, seat)."""
        return bool(isinstance(ts, dict) and ts.get("my_turn") and not ts.get("processing")
                    and not ts.get("discussion_pending") and not ts.get("hand_off_pending")
                    and self._arrived_at != (ts.get("turn"), self.seat))

    def unseen_turn(self, ts) -> bool:
        """Whether the turn on screen is one nothing of ours has opened: my turn, its arrival still due, and its
        turn_start still undelivered to this seat's digest -- so no wait, finish_turn or order of ours met it.
        Live t147 (England, 2026-10-09): Spain's renewal came at the end of t146, accept_deal answered it, the AI
        round finished during the answer, and the "call again" the discussion reply asked for met t147 cold. A
        loaded game records no turn_start, a digest another client of this seat already took counts as seen, and
        a fake without a tuner reads False."""
        if not self.arrival_due(ts):
            return False
        try:
            return bool(self.q(self.h("turn_started_this_turn")))
        except (TunerdError, AttributeError, TypeError, OSError):
            return False

    def arrive_if_due(self, ts: dict | None = None) -> dict | None:
        """The turn's arrival work (standing moves resumed, open orders run) when it has not happened this turn.
        wait_for_my_turn runs it as the turn opens, but a turn can open without it: one that opens under a leader
        screen comes back from the wait before _arrive runs (live t221 and t225, Mongolia: a Great Merchant's
        build step and a Great Musician's walk both sat out the turn, each listed as `stalled_mission`), and one
        that no wait of ours opened at all (live t95, Portugal: accept_deal answered a leader at the end of t94
        while the AI round still ran, the round went on by itself, and the next call met t95 cold -- a worker's
        standing move stalled and a finished quarry's order stayed open). The tools that answer a leader call
        this once the table is free; every mutating tool and end_turn call it before their own work. `ts` is a
        turn state already read, saving the trip. None when nothing is due: not my turn, a screen still up, or
        already arrived this turn. The reply carries what the wait would have: `orders`, `resumed_moves`,
        `expiring_city_states` (None again when the arrival ran and had nothing to report)."""
        if ts is None:
            try:
                ts = self.turn_state()
            except TunerdError:
                return None
        if not self.arrival_due(ts):
            return None
        ts = self._arrive(ts)
        return {k: ts[k] for k in self.ARRIVAL_KEYS if k in ts} or None

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
        if isinstance(ts, dict) and ts.get("load_screen_pending") and ts.get("active_player") == self.seat:
            # The Dawn of Man splash of a single-player game started or loaded by hand (GitLab #96): the same
            # shape, pressed the same way, so the first call of a session meets the game and not a gate.
            for _ in range(2):
                try:
                    self._dismiss_load_screen()
                except TunerdError:
                    break
                time.sleep(0.5)
                ts = self.turn_state()
                if not ts.get("load_screen_pending"):
                    if ts.get("my_turn") and not ts.get("processing"):
                        ts = self._arrive(ts)
                    ts["load_screen_cleared"] = True
                    return ts
            return ts
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
        self._arrived_at = (ts.get("turn") if isinstance(ts, dict) else None, self.seat)
        try:
            # A paused or failed order has handed its unit back: a move_unit I gave it since is mine to resume
            # (live Assyria t20: the Scout's direct move sat as "queued move did not resume" under its paused order).
            owned = [o["unit"]["id"] for o in self.notebook().orders("open") if o.get("status") not in ("paused", "failed")]
        except Exception:  # an unreadable notebook must not block the hand-off either
            owned = []
        try:
            resumed = self.q(self.h("resume_moves", *([owned] if owned else []))) or []
        except Exception:  # never let this block the turn hand-off
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
            # A held move (#98: a hostile beside the unit, a civilian within reach) keeps its record and its
            # moves: the unit is a decision this turn, and the row says why.
            dropped = {r.get("unit_id"): r.get("err") for r in resumed
                       if isinstance(r, dict) and (r.get("dropped") or r.get("held")) and r.get("err")}
            todo = ts.get("todo") if isinstance(ts.get("todo"), dict) else {}
            # the ongoing rows too: a held move on a unit still automated (live Maya t5: the Warrior's move ordered at 0
            # moves beside a camp was held, and the unit sat in `ongoing` with no word of it)
            for u in list(todo.get("units") or []) + list(todo.get("ongoing") or []):
                if isinstance(u, dict) and u.get("id") in dropped:
                    u["note"] = dropped[u["id"]]
        if owned:
            orders = self._turn_start_orders(ts)
            if orders:
                if any(r.get("did") for r in orders.get("rows") or []):
                    time.sleep(0.3)
                    ts = {**self.turn_state(), **{k: v for k, v in ts.items() if k == "resumed_moves"}}
                ts["orders"] = orders
                todo = ts.get("todo") if isinstance(ts.get("todo"), dict) else {}
                note_held_units(todo.get("units") or [], orders.get("rows") or [])
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
                            "leader_message", "chat", "popup_shown", "city_state_allies", "automation_ended", "city_state_fell"})

    # popup_shown rows whose popup is one the harness closes itself with nothing to decide: the tech award
    # (research continues from the queue; research_unset wakes when it does not), the Who's Winning table
    # and the new-era splash. Live 2026-10-11 (Assyria t64): a skip_quiet_turns run woke at once on
    # TECH_AWARD + WHOS_WINNING with turns_skipped 0 and an empty todo. The great-work splash follows my own
    # MISSION_CREATE_GREAT_WORK (live t103: the reply already named the work and its slot). Any other popup
    # still wakes (a wonder completed is left waking: the queue moved on and the digest says to what). The
    # natural-wonder splash (t112, t113) and the golden-age splash (t123) decide nothing either; their
    # notifications wake on the words "wonder" / "golden age".
    QUIET_POPUPS = frozenset({"BUTTONPOPUP_TECH_AWARD", "BUTTONPOPUP_WHOS_WINNING", "BUTTONPOPUP_NEW_ERA",
                              "BUTTONPOPUP_GREAT_WORK_COMPLETED_ACTIVE_PLAYER", "BUTTONPOPUP_NATURAL_WONDER_REWARD",
                              "BUTTONPOPUP_GOLDEN_AGE_REWARD",
                              # the Great Person splash (live t164, t165): the harness closes it and the "Great Person
                              # born" notification and the new unit in todo.units wake the run by themselves
                              "BUTTONPOPUP_GREAT_PERSON_REWARD",
                              # GitLab #99 (Maya t5-t17): five ruins and five city-states met each woke the run at once;
                              # both screens are closed by the harness, the move's own reply carries the reward (#122)
                              "BUTTONPOPUP_GOODY_HUT_REWARD", "BUTTONPOPUP_CITY_STATE_GREETING"})

    #: Banner texts that report this seat's own order of the turn (GitLab #99): the batch reply already said it.
    OWN_RESULT_ALERTS = ("your ", " bombarded an enemy", "has been founded")

    WAKE_WORDS = ("war", "attack", "captured", "destroyed", "denounc", "wonder", "expired", "declar", "pillag",
                  "razed", "revolt", "unhappi", "starv", "spy", "coup", "intrigue", "religion", "converted",
                  "barbarian", "great ", "golden age", "ideolog", "world congress", "resolution", "election",
                  "ally", "allied", "alliance", "friend", "insult", "demand", "trade route", "caravan", "cargo ship",
                  # the top-of-screen banners (event kind "alert") that pull a human back
                  "enemy", "spotted", "killed", "defeated", "withdraw", "intercept", "shot down", "plunder")

    # Notifications that read like trouble to WAKE_WORDS but decide nothing for me. Live Assyria t130-t157
    # (2026-10-11): most wakes of a quiet run were these. QUIET_ABOUT_OTHERS: a city-state changing hands
    # between two OTHER players ("Yerevan has a new Ally!", "Zurich and Portugal now Allies!", "Kiev and Siam
    # no longer Allies!"), a denouncement between two other civs ("Siam has publicly Denounced The Zulus") and
    # a third party's public declaration (a Declaration of Friendship between others). In this build's text
    # the same events about ME use other words ("Influence over Yerevan has increased: they are now Allies!",
    # "Siam now has more Influence over Yerevan than you", "has publicly Denounced us!", "publicly denounced
    # YOU"), so one of these naming me (ABOUT_ME) still wakes. QUIET_NOTICES are quiet whoever they name: a
    # city-state quest ("Mombasa desires Ivory", "Kiev desires Oracle", "Sofia wants Ormus bullied", "Kiev
    # Seeks a Great General": city_state_actions lists the quests whenever I turn to a city-state), "May
    # Purchase With Faith" (a new Great Person buyable; set_faith_purchase is there any turn), "Your Golden
    # Age ends." (nothing to decide; its start is quiet too, QUIET_POPUPS), a quest completed by a Great Person
    # of mine ("Malacca Recognizes Your Great Scientist!", live t161: influence went up, nothing to do) and a
    # city-state asking for units ("Malacca requests Units", the gift-units quest). A caller's own wake_on words
    # always wake. Matched against summary + text, lower-cased.
    QUIET_ABOUT_OTHERS = (r" has a new ally!", r" now allies!", r" no longer allies!", r" has publicly denounced ",
                          r"^public declaration from ",
                          # "Portugal now Ally of Malacca!" / "Portugal is now the Ally of Malacca." (live t162, the
                          # form the list missed), "Siam has replaced Portugal as the Ally of Yerevan!", "Siam is no
                          # longer the Ally of Yerevan!" (TXT_KEY_NTFN_MINOR_*_ALL). My own form is the bare "Now Ally
                          # of Malacca!" / "No longer Ally of Malacca!" with no civ before it, so it still wakes.
                          r"^(\S+ ){1,3}now ally of ", r" is now the ally of ", r" has replaced .+ as the ally of ",
                          r" no longer the ally of ",
                          # "Portugal and Siam Now Friends!" / "... have made a public Declaration of Friendship"
                          # (live t164): the same third-party declaration under its own summary.
                          r"^(\S+ ){1,3}and (\S+ ){1,3}now friends!", r" have made a public declaration of friendship")
    ABOUT_ME = r"(?<![a-z])(you|your|us)(?![a-z])|influence over"
    QUIET_NOTICES = (r"^(\S+ ){1,3}desires ", r"^(\S+ ){1,3}wants .+ bullied", r"^(\S+ ){1,3}seeks a great ",
                     r"^(\S+ ){1,3}recognizes your ", r"^(\S+ ){1,3}requests units",
                     r"^may purchase with faith", r"^your golden age ends")

    def _notification_wakes(self, text: str, words, wake_words) -> bool:
        """`text` (summary + body, lower-cased) ends a quiet run when it reads like one of `words`, unless it is
        one of the quiet notifications above; the caller's own `wake_words` always count."""
        if not self._word_hit(text, words):
            return False
        if wake_words and self._word_hit(text, wake_words):
            return True
        if any(re.search(p, text) for p in self.QUIET_NOTICES):
            return False
        if any(re.search(p, text) for p in self.QUIET_ABOUT_OTHERS) and not re.search(self.ABOUT_ME, text):
            return False
        return True

    # The expiring warnings (#38) ride on every status for the whole window (a deal for 3 turns, a declaration
    # of friendship for 5) and woke a quiet run on each of those turns although nothing can be done before the
    # deal ends (live Assyria t65-t68: the Siam salt deal woke four runs in a row). A row wakes the run once,
    # the first time this process sees it; the status still lists it every turn. Keyed on what names the row,
    # never on turns_left, which changes every turn.
    EXPIRING_KEYS = ("expiring_city_states", "expiring_deals", "expiring_friendships")

    @staticmethod
    def _expiring_key(kind: str, row: dict, ts: dict) -> tuple:
        if kind == "expiring_deals":
            return (kind, row.get("player_id"), row.get("ends_on"), tuple(map(str, row.get("items") or ())))
        if kind == "expiring_friendships":
            left, turn = row.get("turns_left"), ts.get("turn")
            ends = turn + left if isinstance(left, int) and isinstance(turn, int) else left
            return (kind, row.get("player_id"), ends)
        return (kind, row.get("player_id"), row.get("status"))

    def _expiring_new(self, kind: str, rows: list, ts: dict) -> list:
        """The rows of `rows` this process has not reported for this seat yet; every row is remembered."""
        seen = self.__dict__.setdefault("_expiring_seen", {}).setdefault(self.seat, set())
        new = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = self._expiring_key(kind, row, ts)
            if key not in seen:
                new.append(row)
            seen.add(key)
        return new

    # The words that still wake on a leader's plain remark (DIPLO_UI_STATE_BLANK_DISCUSSION, nothing to answer):
    # trouble only. WAKE_WORDS is too wide there: "world congress" is in it, and the Congress thank-you is the
    # very remark that should stay quiet.
    REMARK_WAKE_WORDS = ("war", "attack", "denounc", "declar", "demand", "insult", "captured", "destroyed",
                         "pillag", "spy", "coup", "threat", "betray")

    @staticmethod
    def _word_hit(text: str, words) -> bool:
        """True when one of `words` starts a word of `text` (lower-cased). A stem ("denounc", "declar") still
        matches its forms; "ally" no longer matches "automatically" nor "war" "reward" / "toward" (live Assyria
        t66: "Nimrud has Grown! ... will automatically work the land" woke a quiet run as an ally notice)."""
        return any(re.search(r"(?<![a-z])" + re.escape(w), text) for w in words if w)

    # turn_status.alerts (#39). The runtime puts the facts on every status (happiness total, unhappy tier,
    # strategic deficits, for this seat only); this process remembers the total it last saw at the previous
    # turn so a quiet-turn run wakes on a DROP or a tier beginning, never on a steady low number -- a
    # Circus takes several turns at happiness 1, and waking on each would make skip_quiet_turns useless.
    UNHAPPY_RANK = {None: 0, "unhappy": 1, "very_unhappy": 2, "super_unhappy": 3}
    HAPPINESS_COMFORTABLE = 10   # a drop that still leaves this much is not a wake
    HAPPINESS_BIG_DROP = 5       # unless it is this large at once (a luxury lost is 4-5)

    @staticmethod
    def _happiness_record(ts: dict) -> tuple | None:
        """(turn, happiness, tier, {resource: available}) from a status, or None when it carries no total
        (an older runtime, a status from the main menu)."""
        if not isinstance(ts.get("turn"), int) or not isinstance(ts.get("happiness"), int):
            return None
        deficits = {a["resource"]: a["available"] for a in ts.get("alerts") or []
                    if isinstance(a, dict) and a.get("kind") == "strategic_deficit"
                    and isinstance(a.get("available"), int) and isinstance(a.get("resource"), str)}
        # v254: the unit-supply deficit (runtime alert kind "unit_supply") rides in the same dict as a
        # negative count under its own key, so a cap crossed or a deeper shortfall wakes like a resource.
        for a in ts.get("alerts") or []:
            if isinstance(a, dict) and a.get("kind") == "unit_supply" and isinstance(a.get("deficit"), int):
                deficits["unit_supply"] = -a["deficit"]
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
        # A drop is news when it lands below the comfortable band or takes a luxury's worth at once; live Assyria
        # t106 (2026-10-11) woke a quiet run on 22 -> 19 (a city grew) with nothing to do about it.
        if h < p_h and (h < self.HAPPINESS_COMFORTABLE or p_h - h >= self.HAPPINESS_BIG_DROP):
            out.append(f"happiness_drop:{p_h}->{h}")
        if self.UNHAPPY_RANK.get(tier, 0) > self.UNHAPPY_RANK.get(p_tier, 0):
            out.append(f"unhappy:{tier}")
        for name in sorted(deficits):
            if deficits[name] < p_deficits.get(name, 0):
                if name == "unit_supply":
                    out.append(f"unit_supply:{-deficits[name]}")
                else:
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

    @staticmethod
    def _merge_digest(merged: dict, digest: dict) -> None:
        """Fold one turn's digest into the merged one a finish_turn hands back (a quiet-turn run merges several);
        `omitted` (turn_digest's cap) adds up across them."""
        merged["events"].extend(digest.get("events") or [])
        merged["notifications"].extend(digest.get("notifications") or [])
        om = digest.get("omitted")
        if isinstance(om, dict):
            prev = merged.get("omitted")
            if isinstance(prev, dict):
                om = {**om, "count": (prev.get("count") or 0) + (om.get("count") or 0),
                      "turns": [min(prev["turns"][0], om["turns"][0]), max(prev["turns"][1], om["turns"][1])]
                      if prev.get("turns") and om.get("turns") else om.get("turns") or prev.get("turns")}
            merged["omitted"] = om

    @staticmethod
    def _trim_stale(merged: dict, ended_turn) -> None:
        """Drop from a finish_turn digest the events older than the turn before the one just ended: they happened
        before a turn this seat already played (that turn's briefing or an earlier digest had them), so they are
        not "what happened while I was away". Live 2026-10-03 (Venice t208, hotseat): the seat's event cursor
        had not moved since t198 and the hand-off timeout path handed back turn_digest's whole 120-event cap,
        ~10 KB, of which the last two turns mattered. `stale` says what was dropped (count, turns, by_kind);
        notification_log() still has every notice and briefing(since="turn") this turn's events."""
        if not isinstance(ended_turn, int):
            return
        keep_from = ended_turn - 1
        events = merged.get("events") or []

        def old(e) -> bool:
            return isinstance(e, dict) and isinstance(e.get("turn"), int) and e["turn"] < keep_from
        stale = [e for e in events if old(e)]
        if not stale:
            return
        merged["events"] = [e for e in events if not old(e)]
        turns = [e["turn"] for e in stale]
        by_kind: dict[str, int] = {}
        for e in stale:
            by_kind[str(e.get("kind"))] = by_kind.get(str(e.get("kind")), 0) + 1
        merged["stale"] = {"count": len(stale), "turns": [min(turns), max(turns)], "by_kind": by_kind,
                           "hint": f"{len(stale)} events from before turn {keep_from} were dropped: they predate the "
                                   f"turn before the one just ended (turn {ended_turn}), so this seat's briefings "
                                   "already covered them; state(what='notifications') has every notice"}

    def finish_turn(self, autosave: bool = True, timeout: float = 600, on_wait=None,
                    skip_quiet_turns: int = 0, wake_on: list[str] | None = None, force: bool = False) -> dict:
        """End the turn, wait for the next one, and hand it back with everything that happened: one call is one
        turn boundary. Safe to call again after a client timeout -- when it is no longer our turn it does not
        end anything, it only waits (so a retried call never ends two turns). A turn that began while nothing of
        ours was looking (unseen_turn: the AI round finished during a leader answer) is handed back unended
        (`unseen_turn`, woke_because turn_unseen) unless quiet turns may pass and it is one.

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
        ended_turn = None
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
                if mine and not ended_any and self.unseen_turn(ts):
                    # The turn began while nothing of ours was looking (unseen_turn): ending it here would end an
                    # unplayed turn blind -- live t147 only research-unset refused it. Open it instead (arrival,
                    # digest) and hand it back; when the caller lets quiet turns pass and nothing in it needs
                    # them, it counts as one of those and ends below.
                    arrival = self.arrive_if_due(ts)
                    ts = self.turn_state()
                    if arrival:
                        ts.update({k: v for k, v in arrival.items() if k in self.ARRIVAL_KEYS})
                        # The same todo notes the wait gives (live Assyria t52: the Settler under a paused order read
                        # "re-issue move_unit" here and "resume_order carries on" in the turn_status a moment later).
                        todo = ts.get("todo") if isinstance(ts.get("todo"), dict) else {}
                        note_held_units(todo.get("units") or [], (arrival.get("orders") or {}).get("rows") or [])
                    digest = self.turn_digest()
                    self._merge_digest(merged, digest)
                    reasons = self._wake_reasons(ts, digest, wake_words)
                    if reasons or skipped >= skip_quiet_turns:
                        return {"ok": True, "ended": False, "turn": ts.get("turn"), "status": ts, "digest": merged,
                                "turns_skipped": skipped, "unseen_turn": True, "woke_because": ["turn_unseen"] + reasons,
                                "hint": "this turn began while a leader screen was being answered and nothing of "
                                        "yours has seen it, so it was not ended: play it (status.todo, digest), "
                                        "then turn(action='finish')"}
                    skipped += 1
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
                    if ended_turn is None:
                        ended_turn = ts.get("turn")
            try:
                ts = self.wait_for_my_turn(timeout=timeout, on_wait=on_wait)
            except TunerdError as e:
                if not (ended_any and "did not close" in str(e)):
                    raise
                # GitLab #90 (live Assyria t269): the Great Person screen did not close inside the wait's sweep and
                # the whole reply was that one error -- no `ended`, no digest, while the orders had run and the turn
                # had ended. The turn boundary is the answer; the screen is a gate the next call clears.
                with self.lock():
                    ts = self.turn_state()
                    self._merge_digest(merged, self.turn_digest())
                self._trim_stale(merged, ended_turn)
                return {"ok": True, "ended": True, "turn": ts.get("turn"), "status": ts, "digest": merged,
                        "turns_skipped": skipped, "popup_stuck": str(e), "woke_because": ["popup_stuck"],
                        "hint": "the turn ended; an announcement screen did not close when swept: turn(action='wait') "
                                "sweeps it again (question() shows it), then play the turn"}
            except TimeoutError:
                with self.lock():
                    ts = self.turn_state()
                    if ended_any and ts.get("hotseat") and ts.get("active_player") != self.seat:
                        # Hotseat: my turn ended and the other human seat is on screen, so the boundary has
                        # passed even though the wait timed out -- take the digest now, or this seat's event
                        # cursor never moves (live t192: a two-seat session's finish_turn always timed out at
                        # the other seat's hand-off, so the first digest that did complete carried 350 events
                        # from 29 turns, 75 KB).
                        self._merge_digest(merged, self.turn_digest())
                ts.update({"ok": True, "ended": ended_any, "timed_out": True, "turns_skipped": skipped,
                           "hint": "still not my turn; call turn(action='finish') again (it will only wait, not end another turn)"})
                self._trim_stale(merged, ended_turn)
                if merged["events"] or merged["notifications"]:
                    ts["digest"] = merged
                return ts
            self._note_happiness(ts)
            with self.lock():
                digest = self.turn_digest()
            self._merge_digest(merged, digest)
            self._trim_stale(merged, ended_turn)
            out = {"ok": True, "ended": ended_any, "turn": ts.get("turn"), "status": ts, "digest": merged,
                   "turns_skipped": skipped}
            if ts.get("game_over"):
                # The wait answered with the over state (see _poll_my_turn): name the win and stop here, whatever
                # the quiet-turn budget says.
                out.update({"game_over": True, "woke_because": ["game_over"],
                            "hint": "the game is over: nothing more happens in it; session(action='main_menu') leaves it"})
                victory = self._victory_from_log()
                if victory:
                    out["victory"] = victory
                    out["hint"] = f"{victory['text']} The game is over; session(action='main_menu') leaves it"
                elif ts.get("alive") is False:
                    # No winner in the log and this seat is dead: the game ended for me (live England t226: London,
                    # the last city, captured by the Ottomans; the reply said only game_over).
                    taken = [e.get("data") for e in (merged.get("events") or [])
                             if e.get("kind") == "city_captured" and isinstance(e.get("data"), dict)]
                    defeat: dict = {"text": "you are out of the game: no city left"}
                    if taken:
                        last = taken[-1]
                        defeat["last_city"] = {k: last.get(k) for k in ("name", "x", "y", "by") if last.get(k) is not None}
                        defeat["text"] = f"you are out of the game: {last.get('name')}, your last city, was captured"
                    out["defeat"] = defeat
                    out["hint"] = f"{defeat['text']}. The game is over; session(action='main_menu') leaves it"
                return out
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

    def _victory_from_log(self) -> dict | None:
        """Who won and how, from the game's own notification ("Catherine has won the game through a Science
        Victory!"): {winner, type, text, turn}, or None when the log holds no such line (then only the state
        says the game is over)."""
        try:
            log = self.notification_log(limit=20)
        except (TunerdError, AttributeError, TypeError):
            return None
        for n in (log.get("notifications") or []) if isinstance(log, dict) else []:
            text = str(n.get("text") or "") if isinstance(n, dict) else ""
            m = re.search(r"(.+?) ha(?:s|ve) won the game through an? (\w+) Victory", text)
            if m:
                return {"winner": m.group(1), "type": m.group(2).lower(), "text": text, "turn": n.get("turn")}
        return None

    # Fights between other players ride in the digest whenever they happen in sight (the Portugal-Zulu war, live
    # Assyria t185-t187: four `damage` rows per turn, none mine, each ending a quiet run). A combat, damage or
    # unit_destroyed row that names its players and names none of mine decides nothing for me; a row that names
    # no player at all (an older runtime, a test) still wakes, as does a caller's wake_on word.
    THIRD_PARTY_KINDS = frozenset({"combat", "damage", "unit_destroyed", "unit_hurt"})

    def _fight_is_someone_elses(self, kind: str, data: dict) -> bool:
        if kind not in self.THIRD_PARTY_KINDS or not isinstance(data, dict):
            return False
        seat = getattr(self, "seat", None)
        players = [data.get(k) for k in ("player", "att_player", "def_player") if data.get(k) is not None]
        sides = [data.get(k) for k in ("side", "attacker", "defender") if isinstance(data.get(k), dict)]
        if not players and not sides:
            return False
        if any(p == seat for p in players):
            return False
        if any(sd.get("owner") == "you" for sd in sides):
            return False
        return True

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
            v = ts.get(k)
            if k == "expiring_deals" and isinstance(v, list):
                v = [d for d in v if not (isinstance(d, dict) and d.get("renewed"))]   # v258: already renewed
            if k in self.EXPIRING_KEYS and isinstance(v, list):
                v = self._expiring_new(k, v, ts)                                        # once per row, not per turn
            if k == "pending_popups" and isinstance(v, list):
                # The status is read before the sweep closes the informational screens (the next end_turn does
                # that), so a tech award or Who's Winning table listed here woke the run as `pending_popups` even
                # though its popup_shown row is quiet (live Assyria t112, t115, t116). The same QUIET_POPUPS rule
                # applies; a caller's wake_on word naming the popup still wakes.
                v = [x for x in v if not (isinstance(x, dict) and str(x.get("name", "")) in self.QUIET_POPUPS
                                          and not any(w in str(x.get("name", "")).lower() for w in wake_words))]
            if v:
                reasons.append(k)
        if ts.get("alive") is False:
            reasons.append("dead")
        reasons.extend(self._alert_wake_reasons(ts))   # #39: a drop or a new tier/deficit, not a steady low total
        words = tuple(w.lower() for w in self.WAKE_WORDS) + wake_words
        for e in digest.get("events") or []:
            kind = str(e.get("kind", ""))
            data = e.get("data") if isinstance(e.get("data"), dict) else {}
            if kind == "popup_shown" and str(data.get("name", "")) in self.QUIET_POPUPS \
                    and not any(w in str(data.get("name", "")).lower() for w in wake_words):
                continue        # an informational popup the harness sweeps itself (see QUIET_POPUPS)
            if kind in self.WAKE_KINDS and self._fight_is_someone_elses(kind, data) \
                    and not any(w in kind.lower() for w in wake_words):
                continue        # a fight between other players (live Assyria t185-t187: the Portugal-Zulu war)
            if kind == "city_created" and data.get("player") == self.seat and not any(w in kind.lower() for w in wake_words):
                continue        # my own founding, ordered by me (GitLab #99: it woke the next finish, a turn late)
            if kind == "alert" and isinstance(e.get("data"), dict) and data.get("hostiles_as_in") is not None:
                continue        # the second copy of an "enemy spotted" banner this turn points at the first row (#99)
            if kind == "alert" and isinstance(e.get("data"), dict) and not data.get("hostiles") \
                    and any(m in str(data.get("text", "")).lower() for m in self.OWN_RESULT_ALERTS) \
                    and not any(w in str(data.get("text", "")).lower() for w in wake_words):
                continue        # the result banner of my own strike or founding; the order's reply reported it (#99)
            if kind == "leader_message" and str(data.get("state", "")) == "DIPLO_UI_STATE_BLANK_DISCUSSION" \
                    and not self._word_hit(str(data.get("text", "")).lower(), self.REMARK_WAKE_WORDS + wake_words):
                # A plain remark with no buttons, closed by the harness itself: "Very well." after my accept,
                # "Our proposal to the World Congress succeeded, with the support of your delegation" (live
                # Assyria t204: it ended a quiet run with nothing to answer). A screen that asks something
                # comes back as discussion_pending and wakes through the status, not through this row.
                continue
            if kind in self.WAKE_KINDS or any(w in kind.lower() for w in wake_words):
                reasons.append(f"event:{kind}")
            elif kind == "alert" and isinstance(e.get("data"), dict):
                # A GameplayAlertMessage banner: "Work has now begun on a Colosseum." / "You have discovered
                # Trapping!" woke every quiet run (15 of 50 wakes, live 2026-09-27, Grok). Only a banner that
                # names hostiles or reads like one of the words above ends the run.
                text = str(e["data"].get("text", "")).lower()
                if e["data"].get("hostiles") or self._word_hit(text, words):
                    reasons.append(f"alert:{str(e['data'].get('text'))[:60]}")
            elif kind == "notification" and isinstance(e.get("data"), dict):
                text = " ".join(str(e["data"].get(k, "")) for k in ("summary", "text")).lower()
                if self._notification_wakes(text, words, wake_words):
                    reasons.append(f"notification:{str(e['data'].get('summary') or e['data'].get('text'))[:60]}")
        for n in digest.get("notifications") or []:
            if isinstance(n, dict):
                text = " ".join(str(n.get(k, "")) for k in ("summary", "text")).lower()
                if self._notification_wakes(text, words, wake_words):
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
        # A turn that no wait of ours opened (live t95, Portugal: the AI round ran on after accept_deal answered
        # a leader at the end of t94, and the next call was this one) never had its arrival: the standing moves
        # and open orders would sit out the turn. Give it now, before the turn ends; the reply carries it as
        # `arrival` (the wait's own `orders` / `resumed_moves`), since no wait will report it.
        arrival = self.arrive_if_due(ts)
        if arrival:
            ts = self.turn_state()

        def send(lua):
            r = self._end_turn_send(lua)
            if arrival and isinstance(r, dict):
                r["arrival"] = arrival
            return r

        if self.dismiss_pending_popups(ts):
            time.sleep(0.5)
        autosave_lua = "if not Game.IsNetworkMultiPlayer() then UI.QuickSave() end" if autosave else ""
        turn_before = ts.get("turn")
        r = send(autosave_lua)
        if not r.get("ok") and r.get("pending_popups"):
            # v254 (live t153, Mongolia): a popup the sweep above did not see yet (the Great Work splash still
            # queued when the status was read) is on the books by the time the send checks, and it is also what
            # froze the stale blocker. Sweep what is up now, let the engine re-read, and send once more.
            swept = self.dismiss_pending_popups()
            if swept:
                time.sleep(self._END_TURN_STALE_SETTLE)
                r = send(bool(autosave))
                if r.get("ok"):
                    r["swept_first"] = swept
        if not r.get("ok") or r.get("turn_complete_sent"):
            return r
        # Single player and hotseat: ok only meant CONTROL_ENDTURN was sent. A unit with part of its moves left (e.g.
        # a worker that finished its route) makes the engine refuse it with no signal, and the caller waited on a
        # turn that never ended (live t112, t115). Confirm the turn actually left us. Hotseat used to return here
        # at once, and finish_turn's first poll then read the not-yet-processed end as the same turn still ours:
        # it came back with turn 93 / my_turn true while the game was already on seat 0's turn 94 (Mongolia,
        # 2026-09-27), so the caller acted on a turn that was over.
        resent_why = "the first CONTROL_ENDTURN met a blocker the engine had not re-evaluated yet"
        for attempt in range(2):
            for _ in range(self._END_TURN_CONFIRM_POLLS):
                time.sleep(self._END_TURN_CONFIRM_SLEEP)
                ts = self.turn_state()
                if (not ts.get("my_turn") or ts.get("turn") != turn_before or ts.get("processing")
                        or ts.get("active_player") != self.seat):
                    r["confirmed"] = True
                    if attempt:
                        r["resent"] = resent_why
                    return r
            ts = self.turn_state()
            popups = bool(ts.get("pending_popups"))
            if attempt or not (popups or self._blocker_is_stale(ts)):
                break
            if not popups and self._nothing_blocks(ts):
                resent_why = ("the first CONTROL_ENDTURN was discarded with no blocker named and an empty todo "
                              "(something just ordered was still resolving)")
            # The engine re-evaluates the end-turn blocker on its next update, so CONTROL_ENDTURN sent right
            # after the order that cleared it is discarded against the old one (live t139, Mongolia: set_production
            # then end_turn in one batch, "the turn did not end" with PRODUCTION named and no empty city). An
            # announcement that arrived after the sweep above (live t153: the Great Work splash a moment after
            # the artist's order) discards it too; sweep again. One settle and one more send, no second quick-save.
            if popups:
                self.dismiss_pending_popups(ts)
            time.sleep(self._END_TURN_STALE_SETTLE)
            r = send("")
            if not r.get("ok") or r.get("turn_complete_sent"):
                return r
        rerun = self._rerun_orders_for_blocking(ts)
        if rerun:
            time.sleep(self._END_TURN_STALE_SETTLE)
            r = send("")
            if r.get("ok"):
                r["orders_rerun"] = rerun
                if r.get("turn_complete_sent"):
                    return r
                for _ in range(self._END_TURN_CONFIRM_POLLS):
                    time.sleep(self._END_TURN_CONFIRM_SLEEP)
                    ts = self.turn_state()
                    if (not ts.get("my_turn") or ts.get("turn") != turn_before or ts.get("processing")
                            or ts.get("active_player") != self.seat):
                        r["confirmed"] = True
                        return r
            ts = self.turn_state()
        diag = self.q(self.h('end_turn_diagnosis'))
        diag = diag if isinstance(diag, dict) else {}
        # Prefer the engine's own answer over a guess: when UI.CanEndTurn() is false the stock End Turn
        # button is greyed out and CONTROL_ENDTURN is discarded, which is a different situation from a
        # unit that still needs orders -- and the old message claimed the latter either way.
        why = diag.get("note") or ts.get("blocking_hint")
        todo_now = ts.get("todo") if isinstance(ts.get("todo"), dict) else {}
        if diag.get("note") and (todo_now.get("units") or ts.get("blocking_name") in self._TODO_BLOCKERS):
            # GitLab #104 (live Maya t87): UI.CanEndTurn() is false for a unit with moves too -- that IS the todo
            # blocker, not a screen the harness does not model. Say the todo, as the ordinary refusal does.
            why = "turn has unresolved decisions: " + (ts.get("blocking_hint")
                                                       or "a unit in todo.units still has moves (skip, fortify or move it)")
        if not why and self._nothing_blocks(ts) and not diag.get("has_ready_unit") and not diag.get("has_busy_unit"):
            why = ("the engine names no blocker and todo is empty, so the send was discarded against something "
                   "still resolving (a combat or an animation just ordered); call turn(action='finish') / turn(action='end') again")
        why = why or "a unit or decision still blocks it"
        out = {"ok": False, "err": "CONTROL_ENDTURN was sent but the turn did not end: " + why,
               "blocking": ts.get("blocking_name"), "todo": ts.get("todo"), "engine": diag}
        if rerun:
            out["orders_rerun"] = rerun
        return out

    #: End-turn blockers the todo itself explains (#104): a disabled End Turn button under one of these is no mystery.
    _TODO_BLOCKERS = frozenset({"ENDTURN_BLOCKING_UNITS", "ENDTURN_BLOCKING_UNIT_NEEDS_ORDERS", "ENDTURN_BLOCKING_STACKED_UNITS",
                                "ENDTURN_BLOCKING_UNIT_PROMOTION", "ENDTURN_BLOCKING_PRODUCTION", "ENDTURN_BLOCKING_RESEARCH",
                                "ENDTURN_BLOCKING_POLICY", "ENDTURN_BLOCKING_FREE_POLICY", "ENDTURN_BLOCKING_FREE_TECH"})

    def _rerun_orders_for_blocking(self, ts: dict) -> list | None:
        """A unit the engine lists as needing orders while an active order of mine holds it (building, walking): the
        engine dropped the mission under the order (live Assyria t41: the Worker's mine at (17,29) stopped the turn a
        Spearman came two plots from it; the order still read "building" and the end was refused for the idle
        Worker). Run the open orders again now, before the refusal: the rows that issued something come back, or
        None when no blocking unit is under an order (no read, no run)."""
        todo = ts.get("todo") if isinstance(ts.get("todo"), dict) else {}
        ids = {u.get("id") for u in todo.get("units") or [] if isinstance(u, dict)}
        if not ids:
            return None
        try:
            held = [o for o in self.notebook().orders("active") if (o.get("unit") or {}).get("id") in ids]
        except (TunerdError, OSError, ValueError, KeyError, TypeError):
            return None
        if not held:
            return None
        try:
            rows = self.run_orders("turn_end")
        except TunerdError:
            return None
        return [r for r in rows if (r.get("unit") or {}).get("id") in ids and r.get("did")] or None

    @staticmethod
    def _nothing_blocks(ts: dict) -> bool:
        """The engine names no blocker and the todo is empty: a CONTROL_ENDTURN that still did not take was
        discarded against something transient (live 2026-10-03, Codex t35: an Archer's attack move, then the
        end refused with NO_ENDTURN_BLOCKING_TYPE and nothing in todo; the very next finish_turn went through).
        Worth the one re-send `_blocker_is_stale` grants a frozen blocker."""
        if not isinstance(ts, dict) or ts.get("blocking_name") not in (None, "NO_ENDTURN_BLOCKING_TYPE"):
            return False
        if ts.get("pending_popups") or ts.get("discussion_pending"):
            return False
        todo = ts.get("todo") if isinstance(ts.get("todo"), dict) else {}
        return not (todo.get("units") or todo.get("cities") or todo.get("promotions") or todo.get("research_unset")
                    or todo.get("incoming_deal"))

    @classmethod
    def _blocker_is_stale(cls, ts: dict) -> bool:
        """The engine names a blocker the todo no longer shows: PRODUCTION with no empty city, RESEARCH with
        research set, or the UNITS case turn_state already marks (`blocking_stale`); or no blocker at all over
        an empty todo (`_nothing_blocks`)."""
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
        return cls._nothing_blocks(ts)

    def _end_turn_send(self, autosave: bool) -> dict:
        """The end-turn order itself (H.end_turn_send): the engine's own gates, the harness's blocker and popup
        checks, the quick save when asked, then CONTROL_ENDTURN."""
        return self.q(self.h("end_turn_send", bool(autosave)))
