"""The turn loop: status, briefing, waiting, ending, the digest and the empire overview.

One of the civ5 MCP server's tool modules: every tool here registers on the server in
harness/mcp_server.py, which keeps the game handle, the guard and the tool sets (see its docstring).
"""
from __future__ import annotations

import os

from harness import call_ledger
from harness.client import TunerdError
from harness.game import Game
from harness.turn_claim import claim_status

from harness import mcp_server as core
from harness.mcp_server import mcp, Context, J, _gate, _may_change_seat, _op, _sock, guarded, progress_reporter


@mcp.tool()
@guarded
def turn_status() -> str:
    """Whose turn it is, current turn number, whether it is my turn, what blocks ending it, and whether a
    greeting / discussion / tech / great-person screen is up (those are not in pending_popups).
    `gate` is the one thing to read first: null means act freely; otherwise it names what must happen before
    any action works and `clear_with` the tool that does it (every refusal carries the same object). `seat` is
    the player this server plays. `todo` lists the decisions the turn still needs: units (need orders), cities
    (empty production), promotions, steal_tech (a pending spy chooser, even when blocking_name says something
    else: the engine reports one blocker at a time), and `todo.ongoing` -- units the game is already moving
    (automated or on a multi-turn move; `attention` names a camp, hostile or lost destination beside one),
    which never block the turn. `blocking_name` / `blocking_hint` say what stops end_turn and which tool clears
    it. `alerts` are facts about my own empire that block nothing: low happiness or an unhappy tier, a strategic
    resource in deficit; `happiness` rides on every status. `expiring_deals` (within 3 turns) and
    `expiring_friendships` (within 5) list what is about to lapse; `wars` lists every war I am in with the
    Negotiate Peace gate (`peace.ok`: make_peace can be asked now). While a leader screen is up
    (leader_greeting_pending / discussion_pending) the engine freezes blocking_name and todo: discussion()
    reads it, dismiss_discussion() closes a plain greeting. From the main menu it reports {"ingame": false,
    "screen": ...}: load_latest / load_save get back into a game. Every key in detail: how_to_play("turn_status")."""
    g = core.game()
    if not g.has_state("InGame"):
        out = {"ok": True, "ingame": False, "screen": g.front_end_screen(), "seat": g.seat}
        out["gate"] = _gate(out, g.seat)
        return J(out)
    ts = g.turn_state()
    if ts.get("hotseat") and ts.get("hand_off_pending"):
        ts = g.clear_hand_off(ts)   # our own Continue screen is pressed, never reported as a chore
    settle = getattr(g, "settle_announcements", None)
    if settle:
        ts = settle(ts)   # announcement screens are closed, never reported as a chore either
    ts["seat"] = g.seat
    if "expiring_city_states" not in ts:
        expiring = g.expiring_city_states()
        if expiring:
            ts["expiring_city_states"] = expiring  # ally/friend status lapsing within 3 turns
    ts["gate"] = _gate(ts, g.seat)
    if getattr(g, "claim", None) is not None and ts.get("active_player") == g.seat:
        c = claim_status(_sock(), g.seat, ts.get("turn"), client=call_ledger.client(core._client_info()))
        if c:   # another client of this seat (or this process) has already acted this turn (#41)
            ts["turn_claim"] = c
    if ts.get("hotseat") and ts.get("active_player") != g.seat:
        ts["seat_note"] = (f"this server plays seat {g.seat}; seat {ts.get('active_player')} is on screen, so it is "
                           "not your turn: wait_for_my_turn blocks until it is")
        if _may_change_seat():
            ts["seat_note"] += (f". Only if nobody else plays seat {ts.get('active_player')} (this server's seat "
                                f"was guessed), set_seat({ts.get('active_player')}) moves it there")
    return J(ts)


def _briefing_for(g, ts: dict, since: str = "previous", limit: int = 8, notes: str = "auto",
                  detail: str = "compact") -> dict:
    """The briefing of the turn `ts` describes, or only its gate when one is up: the board is not read while
    something else must happen first (and never while another seat is on screen)."""
    gate = _gate(ts, g.seat)
    if gate is not None:
        return {"ok": True, "seat": g.seat, "turn": ts.get("turn"), "gate": gate,
                "withheld": "the board is not read while a gate is up: clear it with gate.clear_with, then briefing()"}
    if "expiring_city_states" not in ts:
        expiring = g.expiring_city_states()
        if expiring:
            ts = {**ts, "expiring_city_states": expiring}
    out = g.briefing(since=since, limit=limit, ts=ts, notes=notes, detail=detail)
    out["seat"] = g.seat
    out["gate"] = None
    return out


@mcp.tool()
@guarded
def briefing(since: str = "previous", limit: int = 8, notes: str = "auto", detail: str = "compact") -> str:
    """My turn in one compact read, for deciding and for recovering after a context reset: what I must do, what
    changed, and what the board looks like. `decisions` is every mandatory item, never cut -- units needing
    orders, promotions, cities with nothing to build, research unset, an incoming deal, a stolen tech, decision
    popups, or the blocker -- each with the tool that clears it. `warnings` are facts that do not block (alerts,
    expiring deals / friendships / allies); `opportunities` idle caravans and spies, free route slots.
    `changes` since the `baseline` (my previous briefing of this game and seat, kept beside my notebook):
    empire totals {was, now}, cities and units new / gone, `events` from the game's log (its own cursor:
    turn_digest keeps its own). `empire`; `cities` (only those worth a look, with `why`); `units` (totals,
    ongoing, attention, damaged); `threats` (visible hostiles within 4 plots of a city or 2 of a unit, nearest
    first; distance only, no odds; ones already briefed are marked `seen`); `camps`; `civ_rules` (my leader's
    trait text, on a first briefing or since="turn"); `notes` (new since my last briefing or finish_turn;
    notes="all" the latest `limit`); `assignments` and `orders` when I have any. While a gate is up only `gate`
    comes back (`withheld`).
    Every list but `decisions` stops at `limit` (default 8, max 50) with `omitted` and `more` naming the tool
    that shows the rest. since="turn" lists every event after my previous turn ended: use it after a context
    reset. detail="full" gives every field of every row. Five game reads; nothing another seat can see is
    read. Every key in detail: how_to_play("briefing")."""
    g = core.game()
    ts = g.turn_state()
    ts["seat"] = g.seat
    return J(_briefing_for(g, ts, since=since, limit=limit, notes=notes, detail=detail))


@mcp.tool()
@guarded
def set_seat(player_id: int | None = None) -> str:
    """Change which player this server plays, or re-detect it (player_id omitted). Needed when every tool
    answers "this seat is not active" although the game is waiting for a human: the server was started
    with --seat auto before the game was up, or a hotseat save was loaded and auto's default (seat 1) is not
    the seat on screen. Only a seat the engine considers human can be chosen; the answer lists `human_seats`.
    With no player_id: solo and network games re-run detection; hotseat takes the seat on screen when it is
    human. The notebook follows the seat (one notebook per game and seat). Usable while it is not my turn."""
    g = core.game()
    if not g.has_state("InGame"):
        return J({"ok": False, "err": "no game is loaded; load_latest / load_save first", "seat": g.seat})
    g._mode = None  # a save may have been loaded since the mode was cached
    mode = g.mode()
    humans = g.human_seats()
    ts = g.turn_state(0)
    before = g.seat
    if player_id is None:
        if mode == "hotseat":
            if ts.get("active_player") not in humans:
                return J({"ok": False, "err": "the seat on screen is not human; give player_id", "seat": g.seat,
                          "active_player": ts.get("active_player"), "human_seats": humans})
            g.seat = int(ts["active_player"])
        else:
            g.detect_seat()
    else:
        player_id = int(player_id)
        if player_id not in humans:
            return J({"ok": False, "err": f"player {player_id} is not a human seat in this game", "seat": g.seat,
                      "human_seats": humans, "mode": mode})
        pinned = os.environ.get("CIV5_SEAT", "auto")
        if pinned != "auto" and player_id != int(pinned):
            # Two agents in one hotseat game each get a server started with their own --seat. The other
            # human seat is the other player's: taking it on its turn would read their map and units.
            return J({"ok": False, "err": f"this server was started with --seat {pinned} and plays only that seat; "
                                          f"seat {player_id} is another player's", "seat": g.seat,
                      "human_seats": humans, "mode": mode})
        g.seat = player_id
    core._seat_rechecked, core._seat_unresolved = False, False
    ts = g.turn_state()
    return J({"ok": True, "seat": g.seat, "seat_before": before, "mode": mode, "human_seats": humans,
              "active_player": ts.get("active_player"), "my_turn": ts.get("my_turn"), "turn": ts.get("turn"),
              "hint": None if ts.get("active_player") == g.seat else
              "not this seat's turn yet: wait_for_my_turn / finish_turn wait for it"})


@mcp.tool()
@guarded
def wait_for_my_turn(timeout_seconds: int = 90, ctx: Context = None) -> str:
    """Block until it is my turn (hotseat: dismisses the hand-off screen; LAN/solo: waits for the AIs to finish),
    then return turn_status. On timeout it returns the current status with my_turn=false -- call it again.
    A progress notification goes out every few seconds while waiting, so with a client that honours progress
    timeout_seconds can be as long as an AI round needs (600-1800); otherwise keep it under the client's
    tool-call limit. Also sweeps informational popups. finish_turn does end_turn + this + turn_digest in one call.

    Returns early with discussion_pending=true when an AI leader wants an answer mid-turn: discussion()
    shows what they said and the buttons, respond_discussion(button_id) answers; for a trade offer on the
    table incoming_deal() reads the terms and accept_deal()/refuse_deal() resolve it; dismiss_discussion()
    leaves without agreeing. Then call this again.
    Returns early with tech_popup_pending=true when a technology must be chosen (research still unset).
    Every answer carries `gate` (as turn_status): null when you may act, else what still stands in the way
    and the tool that clears it. A timeout answer carries `seat` (the player this server waits for) and
    `active_player`; in hotseat a different active_player is the other player's turn -- call again."""
    g = core.game()
    try:
        r = g.wait_for_my_turn(timeout=timeout_seconds, on_wait=progress_reporter(ctx, g.seat))
    except TimeoutError as e:
        return J(_wait_timeout(g, str(e)))
    r["seat"] = g.seat
    r["gate"] = _gate(r, g.seat)
    return J(r)


def _wait_timeout(g: Game, err: str) -> dict:
    """A wait that ran out: say which seat was waited for and who holds the turn, so a wrong seat is visible
    (live 2026-09-25: 420 s of waiting for seat 1 in a hotseat game where seat 0 sat on the hand-off screen)."""
    out = {"ok": False, "err": err, "seat": g.seat, "timed_out": True}
    try:
        with _op(g):
            ts = g.turn_state(g.seat)
        out["active_player"], out["turn"] = ts.get("active_player"), ts.get("turn")
        out["gate"] = _gate(ts, g.seat)
        if ts.get("hotseat") and ts.get("active_player") != g.seat:
            out["hint"] = (f"hotseat: seat {ts.get('active_player')} is on screen and this server plays seat "
                           f"{g.seat}: still the other player's turn; call again")
            if _may_change_seat():
                out["hint"] += f". Only if nobody else plays seat {ts.get('active_player')}, set_seat({ts.get('active_player')})"
        else:
            out["hint"] = "still not my turn; call again"
    except (TunerdError, TimeoutError, OSError, ValueError, KeyError):
        pass
    return out


@mcp.tool()
@guarded
def players() -> str:
    """HUMAN seats only (network/hotseat games): whether each is connected, has an active turn, and has ended
    their turn. Like the in-game player list, a seat I have not met shows its name but not its civ. In a solo game this is just me. For the AI civs and city-states I have met -- their ids,
    scores, war state -- use `diplomacy`; that is where `player_id`s for trade/diplomacy tools come from."""
    return J(core.game().net_players())


@mcp.tool()
@guarded
def overview() -> str:
    """My empire at a glance: gold, science, culture, happiness, research, era, counts, turn/year.
    `strategic_resources` (revealed only) with `available` spare copies -- negative is a deficit: units and
    buildings fight and produce at a penalty. `luxuries` with owned / imported / exported copies (`last_copy`
    when selling one would drop the happiness bonus); `bonus_resources` the resource list's bonus stack.
    The top-bar tooltips ride along: `happiness_breakdown` (with the Happiness screen's rows: by_luxury,
    cities, unhappiness tooltips, the `unhappy` tier, `penalties`), `gold_breakdown` (income vs expenses, unit
    maintenance), `science_breakdown`, `culture_breakdown`, `tourism_breakdown`, `faith_breakdown`;
    `unit_supply` (Military Overview cap and deficit), `score_breakdown`, `golden_age_progress` /
    `golden_age_threshold`. `idle_trade_units` lists caravans and cargo ships without a route (with `in_city`
    and the nearest city to walk to: only one standing in my city can be given a route) and `idle_spies`
    unassigned spies. Every key in detail: how_to_play("overview")."""
    return J(core.game().summary())


@mcp.tool()
@guarded
def notification_log(limit: int = 40, include_dismissed: bool = True) -> str:
    """The Notification Log: every notification the game still holds for me, newest first, including
    ones already dismissed -- which is what the screen is for. `turn_digest` carries only what the
    panel is currently showing, so something read once and dismissed is otherwise gone. Each row has
    the `turn` it arrived on. `limit` is the newest N (default 40); include_dismissed=false keeps only the
    ones still showing."""
    return J(core.game().notification_log(limit, include_dismissed))


@mcp.tool()
@guarded
def turn_digest() -> str:
    """Everything recorded since my last call: combats, cities founded/lost, wars, chat, notifications, alerts.
    Notes: a caravan / cargo ship shows up as `unit_destroyed` the turn its trade route starts -- the route
    IS the unit now (it comes back as a new unit when the route ends); `unit_graphics_reset` means the engine
    only rebuilt a model (era change, upgrade), the unit is fine; `unit_displaced` is a unit of mine the engine
    moved while the others played, with no order of mine (`shared_with`: a trade unit on the tile it left). `unit_captured` is a civilian taken, not killed:
    the row carries the unit, its tile, the captor when in sight and (barbarians) the nearest revealed camp. Leader lines you provoked yourself via
    negotiate_deal/propose_deal are not included; unsolicited AI approaches are."""
    return J(core.game().turn_digest())


@mcp.tool()
@guarded
def quick_save() -> str:
    """Save the game right now (same as the in-game Quick Save / F5). Cheap -- call it after anything
    costly (founding a city, a policy/research choice, before combat), not just periodically, since a
    crash loses everything back to the engine's last autosave otherwise."""
    return J(core.game().quick_save())


@mcp.tool()
@guarded
def end_turn(autosave: bool = True, force: bool = False) -> str:
    """End my turn. If something blocks it (unit needs orders, research/production choice), turn_status shows it.
    Auto-quicksaves first by default (single-player only) -- cheap insurance against this game's frequent
    ambient crashes; pass autosave=False to skip. Refused with `turn_claim` when another client of this seat
    gave this turn's first order and is still at it (its pid and timings are in the answer): that client owns
    the turn until 180 s pass without an order from it or its process exits; force=true takes it over."""
    return J(_with_skip_actions(core.game().end_turn(autosave, force=force)))


def _with_skip_actions(refusal: dict) -> dict:
    """An end-turn refusal that names units with movement left gets `skip_actions`: the unit_mission MISSION_SKIP
    orders that end the turn with them, ready for finish_turn(actions=...). A unit keeps the turn open while
    it has moves after its order (a one-plot move, an attack): Codex hit this five times in 48 turns on
    2026-10-03, one extra round trip each, because the rule was only in the refusal text."""
    if not isinstance(refusal, dict) or refusal.get("ok") is not False:
        return refusal
    todo = refusal.get("todo")
    units = todo.get("units") if isinstance(todo, dict) else None
    ids = [u["id"] for u in units or [] if isinstance(u, dict) and isinstance(u.get("id"), int)]
    if ids:
        refusal["skip_actions"] = [{"tool": "unit_mission", "args": {"unit_id": i, "mission": "MISSION_SKIP"}}
                                   for i in ids]
        refusal["hint"] = ("these units can still act this turn (movement left after a one-plot move, an attack): "
                           "give each a real order (a second move, an attack, fortify, sleep), or "
                           "finish_turn(actions=skip_actions) ends the turn with them skipped")
    return refusal


@mcp.tool()
@guarded
def finish_turn(actions: list[dict] | None = None, autosave: bool = True, timeout_seconds: int = 600,
                skip_quiet_turns: int = 0, wake_on: list[str] | None = None, force: bool = False,
                briefing: bool = False, notes: str = "new", ctx: Context = None) -> str:
    """The turn boundary as one call: end my turn, wait until it is my turn again, and return the new turn --
    `status` (as turn_status), `digest` (as turn_digest: what happened while I was away), `turn` and `notes`
    (notebook entries since my last boundary; notes="all": the latest eight). briefing=true returns
    `briefing` (see the briefing tool) in place of status and digest.
    actions=[{tool, args}, ...] runs those orders first, exactly as do() would (stops at the first refusal,
    action_id replay), and ends the turn only when every one was ok: the reply carries `batch` (results,
    skipped) either way, with the new turn on success and with the current `status` and ended=false on a
    refusal.
    If the turn will not end, ok=false and `end_turn` carries the refusal with the todo that blocks it: nothing
    is waited on. A unit with movement left after its order (a one-plot move, an attack) still blocks the end:
    skip, fortify or sleep it in the same actions, or pass the refusal's `end_turn.skip_actions`.
    Safe to repeat: when it is already not my turn it only waits, never ends a second turn. Returns early with
    discussion_pending=true (an AI wants an answer: discussion(), answer it, call again) or
    tech_popup_pending=true (set_research).
    timed_out=true: the AIs are still moving; call again (600 is safe in Claude Code).
    skip_quiet_turns=N keeps ending turns, up to N more, while nothing needs me (no unit awaiting orders, empty
    city, promotion, popup, blocker, expiring ally, worsening alert, paused order or eventful digest); wake_on
    adds my own words (event kinds or notification text). `turns_skipped` / `woke_because` say what happened;
    the harness never issues an order for me. One client owns the turn: another client of this seat gets
    ok=false with `turn_claim`; force=true takes it over. autosave=false skips the quick-save.
    game_over=true: the game ended while I waited; `victory` names the winner and how.
    Every reply key, what wakes a quiet run, the claim rules: how_to_play("finish_turn")."""
    g = core.game()
    if notes not in ("new", "all"):
        return J({"ok": False, "err": f"notes must be 'new' or 'all', not {notes!r}"})
    batch = None
    if actions:
        from harness.mcp_tools.batch import run_batch
        batch = run_batch(actions, stop_on_refusal=True, force=force)
        if not batch.get("ok"):
            with _op(g):
                st = g.turn_state()
            return J({"ok": False, "ended": False, "seat": g.seat, "turn": st.get("turn"), "batch": batch,
                      "status": st, "gate": _gate(st, g.seat),
                      "hint": "an order was refused, so the turn was not ended: read batch.results, re-check the "
                              "state, then finish_turn again with the orders still wanted (or none)"})
    r = g.finish_turn(autosave=autosave, timeout=timeout_seconds, on_wait=progress_reporter(ctx, g.seat),
                      skip_quiet_turns=max(0, int(skip_quiet_turns)), wake_on=wake_on, force=force)
    r["seat"] = g.seat
    if isinstance(r.get("end_turn"), dict):
        _with_skip_actions(r["end_turn"])
    if batch is not None:
        r["batch"] = batch
    # The gate of the turn handed back: from `status` on a normal boundary, from the answer itself when it
    # returned early (a discussion, a tech choice, a timeout carry the turn_state at top level).
    st = r.get("status") if isinstance(r.get("status"), dict) else r
    r["gate"] = _gate(st, g.seat)
    if r.get("timed_out") and r.get("hotseat") and r.get("active_player") != g.seat:
        r["hint"] = (f"hotseat: seat {r.get('active_player')} is on screen and this server plays seat {g.seat}: "
                     "still the other player's turn; call again")
        if _may_change_seat():
            r["hint"] += f". Only if nobody else plays seat {r.get('active_player')}, set_seat({r.get('active_player')})"
    if briefing and r.get("ok") and isinstance(r.get("status"), dict) and r["gate"] is None:
        try:
            with _op(g):
                b = _briefing_for(g, {**r["status"], "seat": g.seat}, notes=notes)
        except Exception as e:  # noqa: BLE001 -- the turn has already ended: status and digest must still arrive
            b = {"ok": False}
            r["briefing_error"] = f"{type(e).__name__}: {e}"
        if b.get("ok") and b.get("gate") is None:
            r["briefing"] = b
            if r["status"].get("orders"):
                # What the orders did at this turn start; their state (now, pause, steps) is in the briefing's own
                # `orders`, so the full rows are not repeated here (#43: ~1.1 KB a turn with two open orders).
                so = r["status"]["orders"]
                r["orders"] = {k: v for k, v in so.items() if k != "rows"}
                r["orders"]["rows"] = [{k: v for k, v in row.items() if k in ("id", "unit", "status", "did")}
                                       for row in so.get("rows") or [] if isinstance(row, dict)]
                r["orders"]["state"] = "briefing.orders"
            r.pop("status", None)
            r.pop("digest", None)
    if "briefing" not in r:   # the briefing carries the notes itself (and moved the hand-off cursor once)
        try:
            with _op(g):   # game_key() reads the game once per process
                r.update(g.notebook().hand_off_section(notes))
        except Exception:  # noqa: BLE001 -- the notebook is a convenience; the turn result must still arrive
            pass
    return J(r)
