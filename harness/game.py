"""High-level Python API over the game (through tunerd). The only module that speaks Lua.

    from harness.game import Game
    g = Game()                    # connects to tunerd (CIV5_TUNERD_SOCK selects the instance)
    g.host_hotseat(human_seats=[0, 1], nicknames={1: "Claude"})   # hotseat: one instance, seats alternate
    g.join_lan("192.168.1.10", nickname="Claude")                  # LAN: this instance is the LLM's own client
    g.wait_ingame(); g.detect_seat()
    g.summary(1); g.units(1); g.cities(1); g.plots_around(x, y, 3)
    g.move_unit(unit_id, x, y); g.end_turn()
"""
from __future__ import annotations

import json
import hashlib
import pathlib
import re
import time
from dataclasses import dataclass, field
from typing import Any

from .client import Civ5, TunerdError, TunerConnectionLost

RUNTIME_LUA = pathlib.Path(__file__).with_name("lua") / "runtime.lua"
RUNTIME_VERSION = int(re.search(r"RUNTIME_VERSION = (\d+)", RUNTIME_LUA.read_text()).group(1))
RUNTIME_DIGEST = hashlib.sha256(RUNTIME_LUA.read_bytes()).hexdigest()


@dataclass
class Game:
    sock_path: str | None = None
    c: Civ5 = field(init=False)
    seat: int = 0                       # player id the LLM controls (LAN: detect_seat() = the local player)
    _runtime_ok: bool = field(default=False, init=False)
    _last_event_seq: int = field(default=0, init=False)
    _mode: str | None = field(default=None, init=False)

    def __post_init__(self):
        self.c = Civ5(self.sock_path) if self.sock_path else Civ5()

    # ------------------------------------------------------------ plumbing
    def states(self) -> dict[int, str]:
        return self.c.states()

    def has_state(self, name: str) -> bool:
        return name in self.c.states().values()

    def lua(self, state: int | str, code: str, timeout: float | None = None) -> list[str]:
        return self.c.exec(state, code, timeout=timeout)

    def q(self, code: str, timeout: float | None = None):
        """Run `code` (must `return` a value) in InGame and get JSON back."""
        self.ensure_runtime()
        return self.c.query("InGame", code, timeout=timeout)

    # The tuner accepts commands of at most ~2.5 KB, so big sources are shipped in escaped
    # string chunks into a global and compiled with loadstring().
    CHUNK = 1500

    def load_lua(self, state: int | str, src: str, name: str = "chunk") -> None:
        self.c.exec(state, "__H_SRC = ''")
        for i in range(0, len(src), self.CHUNK):
            piece = src[i:i + self.CHUNK]
            self.c.exec(state, f"__H_SRC = __H_SRC .. {lua_str(piece)}")
        self.c.exec(state, f"local f, err = loadstring(__H_SRC, {lua_str(name)}); __H_SRC = nil; "
                           f"if not f then error(err, 0) end; f()", timeout=30)

    def ensure_runtime(self, force: bool = False) -> None:
        if self._runtime_ok and not force:
            return
        # a truncated/failed earlier injection leaves a partial H behind: check for the last symbol
        if not force:
            out = self.c.exec("InGame", f"print(type(H) == 'table' and H.source_hash == '{RUNTIME_DIGEST}' and type(H.turn_state) == 'function')")
            if out and out[0] == "true":
                self._runtime_ok = True
                return
        src = RUNTIME_LUA.read_text()
        # A changed source must reload even when a developer forgot to bump the
        # numeric version. Mark completion only after every chunk has executed.
        src = "if H then H.version = -1 end\n" + src
        src += f"\nH.source_hash = '{RUNTIME_DIGEST}'\n"
        self.load_lua("InGame", src, "harness_runtime")
        self._runtime_ok = True

    # ------------------------------------------------------------ front end
    # State (Lua context) names seen in the front end: MainMenu, MultiplayerSelect, LobbyScreen
    # (LAN/internet game list; context name "Lobby"), MPGameSetupScreen, JoiningRoom, StagingRoom.
    def _select_mp(self, kind: str) -> None:
        """From the main menu (Multiplayer already opened or not): pick Hotseat / LAN."""
        c = self.c
        try:
            mps = c.wait_state("MultiplayerSelect", 3)
        except TunerdError:
            mm = c.wait_state("MainMenu", 10)
            c.exec(mm, "MultiplayerClick()", check=False)
            mps = c.wait_state("MultiplayerSelect", 15)
        c.exec(mps, {"hotseat": "HotSeatButtonClick()", "lan": "LANButtonClick()", "internet": "InternetButtonClick()"}[kind])
        time.sleep(1.0)

    def host_hotseat(self, human_seats: list[int], game_name: str = "LLM Harness", nicknames: dict[int, str] | None = None,
                     launch: bool = True) -> None:
        """From the main menu: Multiplayer > Hotseat > Setup > Staging room > (launch)."""
        c = self.c
        self._select_mp("hotseat")
        setup = c.wait_state("MPGameSetupScreen", 10)
        c.exec(setup, f'Controls.NameBox:SetText({lua_str(game_name)})')
        c.exec(setup, "OnStart()")
        stg = c.wait_state("StagingRoom", 30)
        for seat in human_seats:
            if seat == 0:
                continue  # host slot is already human
            c.exec(stg, f"SetSlotToHuman({seat})")
        for seat, nick in (nicknames or {}).items():
            c.exec(stg, f"PreGame.SetNickName({seat}, {lua_str(nick)})")
        c.exec(stg, "Network.BroadcastPlayerInfo()")
        if launch:
            c.exec(stg, "LaunchGame()")
        self._save_rejoin("hotseat", human_seats=human_seats, game_name=game_name, nicknames=nicknames)

    def host_lan(self, game_name: str = "LLM Harness", open_seats: list[int] | None = None, nickname: str | None = None,
                 launch: bool = False, map_script: str | None = None, world_size: str | None = None,
                 closed_seats: list[int] | None = None, handicap: str | None = None) -> dict:
        """From the main menu: Multiplayer > LAN > Host > Setup > Staging room. Slots in `open_seats` are set
        SS_OPEN for joiners, `closed_seats` SS_CLOSED (the rest stay AI). Returns staging_status(). Launch
        later with launch_game() once everyone is connected (or pass launch=True to launch immediately).

        `map_script` is a case-insensitive substring of a MapScripts row's FileName (e.g. "continents.lua";
        "smallcontinents.lua" is excluded unless asked for), `world_size` a WORLDSIZE_* type. Both must be
        set before the setup screen's OnStart(): the slot count comes from the world size's DefaultPlayers
        (mpgamesetupscreen.lua). `handicap` (a HANDICAP_* type) is applied to every human-capable slot;
        in Civ V the AI's bonuses follow the humans' difficulty, so this is how "hard AI" is set."""
        c = self.c
        self._select_mp("lan")
        lobby = c.wait_state("Lobby", 15)
        c.exec(lobby, "HostButtonClick()")
        setup = c.wait_state("MPGameSetupScreen", 10)
        c.exec(setup, f'Controls.NameBox:SetText({lua_str(game_name)})')
        if world_size:
            c.exec(setup, f"PreGame.SetWorldSize(GameInfo.Worlds[{lua_str(world_size)}].ID)")
        if map_script:
            want = map_script.lower()
            c.exec(setup, f"""
                for row in GameInfo.MapScripts() do
                    local f = string.lower(row.FileName or "")
                    local base = f:match("[^/\\]+$") or f
                    if base == {lua_str(want)} or (base:find({lua_str(want)}, 1, true) and not base:find("small", 1, true)) then
                        PreGame.SetMapScript(row.FileName); PreGame.SetRandomMapScript(false)
                    end
                end""")
            got = c.query(setup, "return {script=PreGame.GetMapScript(), size=PreGame.GetWorldSize()}")
            if want not in (got.get("script") or "").lower():
                raise TunerdError(f"map script {map_script!r} not found; PreGame reports {got}")
        c.exec(setup, "OnStart()")
        stg = c.wait_state("StagingRoom", 30)
        for seat in open_seats or []:
            c.exec(stg, f"PreGame.SetSlotStatus({seat}, SlotStatus.SS_OPEN); PreGame.SetSlotClaim({seat}, SlotClaim.SLOTCLAIM_ASSIGNED)")
        for seat in closed_seats or []:
            c.exec(stg, f"PreGame.SetSlotStatus({seat}, SlotStatus.SS_CLOSED)")
        if handicap:
            c.exec(stg, f"""
                local h = GameInfo.HandicapInfos[{lua_str(handicap)}].ID
                for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
                    local st = PreGame.GetSlotStatus(i)
                    if st == SlotStatus.SS_TAKEN or st == SlotStatus.SS_OPEN then PreGame.SetHandicap(i, h) end
                end""")
        if nickname:
            c.exec(stg, f"PreGame.SetNickName(Matchmaking.GetLocalID(), {lua_str(nickname)})")
        c.exec(stg, "Network.BroadcastPlayerInfo()")
        if launch:
            self.launch_game()
        self._save_rejoin("lan_host", game_name=game_name, open_seats=open_seats, nickname=nickname)
        return self.staging_status()

    def lan_games(self, refresh_seconds: float = 3.0) -> list[dict]:
        """Games advertised on the LAN (from the LAN lobby screen; opens it if needed)."""
        c = self.c
        try:
            lobby = c.wait_state("Lobby", 2)
        except TunerdError:
            self._select_mp("lan")
            lobby = c.wait_state("Lobby", 15)
        c.exec(lobby, "if not Matchmaking.IsRefreshingGameList() then Matchmaking.RefreshLANGameList() end")
        time.sleep(refresh_seconds)
        return c.query(lobby, "local out = {} for _, e in ipairs(Matchmaking.GetMultiplayerGameList() or {}) do "
                              "out[#out+1] = {id=e.serverID, name=e.serverName, map=e.MapName, players=e.numPlayers, max=e.maxPlayers, "
                              "list=e.Players} end return out")

    def join_lan(self, host: str | int, nickname: str | None = None, ready: bool = True, timeout: float = 60) -> dict:
        """Join a LAN game as this instance's local player. `host` is an IPv4 address (Matchmaking.JoinIPAddress)
        or a serverID from lan_games() (Matchmaking.JoinMultiplayerGame). Ends in the staging room; the host
        launches. Returns staging_status()."""
        c = self.c
        try:
            lobby = c.wait_state("Lobby", 2)
        except TunerdError:
            self._select_mp("lan")
            lobby = c.wait_state("Lobby", 15)
        if isinstance(host, int):
            out = c.exec(lobby, f"local r, p = Matchmaking.JoinMultiplayerGame({host}); print(tostring(r), tostring(p))")
        else:
            out = c.exec(lobby, f"local r, p = Matchmaking.JoinIPAddress({lua_str(host)}); print(tostring(r), tostring(p))")
        deadline = time.monotonic() + timeout
        stg = None
        while time.monotonic() < deadline:
            states = c.states()
            if "StagingRoom" in states.values():
                stg = [k for k, v in states.items() if v == "StagingRoom"][0]
                # the context exists early; it is live once Matchmaking knows our id
                if c.query(stg, "return {ok = Matchmaking.GetLocalID() >= 0 and not Matchmaking.IsHost()}").get("ok"):
                    break
            time.sleep(1.0)
        else:
            raise TimeoutError(f"join did not reach the staging room (join call printed {out!r})")
        time.sleep(1.0)
        if nickname:
            c.exec(stg, f"PreGame.SetNickName(Matchmaking.GetLocalID(), {lua_str(nickname)})")
        if ready:
            c.exec(stg, "PreGame.SetReady(Matchmaking.GetLocalID(), true)")
        c.exec(stg, "Network.BroadcastPlayerInfo()")
        self._save_rejoin("lan_join", host=host, nickname=nickname)
        return self.staging_status()

    # ------------------------------------------------------------ crash recovery (harness/supervisor.py)
    def _rejoin_state_path(self) -> pathlib.Path | None:
        """Where to persist 'how to get back into this game' -- a sibling file of this instance's tunerd
        socket, so it works for any instance without extra config. None if the socket has no filesystem path
        (shouldn't happen for the unix-socket transport this harness uses)."""
        try:
            return pathlib.Path(str(self.c.path) + ".rejoin.json")
        except Exception:
            return None

    def _save_rejoin(self, kind: str, **info) -> None:
        """Best-effort; a failure here must never break the caller's actual game action."""
        path = self._rejoin_state_path()
        if path is None:
            return
        try:
            path.write_text(json.dumps({"kind": kind, **info}, default=str))
        except OSError:
            pass

    def load_rejoin_state(self) -> dict | None:
        """Read back what _save_rejoin last wrote (used by harness/supervisor.py after a relaunch)."""
        path = self._rejoin_state_path()
        if path is None or not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return None

    def note_reconnected(self) -> None:
        """Record a 'reconnected' event in the digest so the LLM knows some turns may have been missed."""
        self.lua("InGame", "H.record('reconnected', {turn = Game.GetGameTurn()})", timeout=10)

    def set_ready(self, ready: bool = True) -> None:
        stg = self.c.wait_state("StagingRoom", 5)
        self.c.exec(stg, f"PreGame.SetReady(Matchmaking.GetLocalID(), {'true' if ready else 'false'}); Network.BroadcastPlayerInfo()")

    def launch_game(self) -> None:
        """Host only: launch from the staging room (LaunchGame() = Matchmaking.LaunchMultiplayerGame())."""
        stg = self.c.wait_state("StagingRoom", 5)
        self.c.exec(stg, "LaunchGame()")

    def staging_slots(self, n: int = 8) -> list[dict]:
        stg = self.c.wait_state("StagingRoom", 5)
        return self.c.query(stg, f"local t={{}} for i=0,{n-1} do t[#t+1]={{id=i, status=PreGame.GetSlotStatus(i), claim=PreGame.GetSlotClaim(i), nick=PreGame.GetNickName(i), civ=PreGame.GetCivilization(i), handicap=PreGame.GetHandicap(i), connected=Network.IsPlayerConnected(i), ready=PreGame.IsReady(i)}} end return t")

    def staging_status(self) -> dict:
        stg = self.c.wait_state("StagingRoom", 5)
        st = self.c.query(stg, "return {local_id=Matchmaking.GetLocalID(), is_host=Matchmaking.IsHost(), everyone_connected=Network.IsEveryoneConnected(), "
                               "hotseat=PreGame.IsHotSeatGame(), internet=PreGame.IsInternetGame(), game_name=PreGame.GetGameName and PreGame.GetGameName() or nil}")
        st["slots"] = self.staging_slots()
        return st

    def leave_to_main_menu(self) -> None:
        """Back out of wherever we are (in-game, staging room, lobby) to the main menu."""
        c = self.c
        states = c.states().values()
        if "InGame" in states:
            c.exec("InGame", "Events.ExitToMainMenu()", check=False)
        elif "StagingRoom" in states:
            c.exec("StagingRoom", "HandleExitRequest()", check=False)
        if "Lobby" in states:
            c.exec("Lobby", "HandleExitRequest()", check=False)
        self._mode = None
        self._runtime_ok = False

    def wait_ingame(self, timeout: float = 300) -> None:
        self.c.wait_state("InGame", timeout)
        # the InGame context exists before the map is fully initialised; wait for a live turn counter
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                r = self.c.call(op="exec", state="InGame", lua="print(Game.GetGameTurn(), Game.GetActivePlayer())", timeout=5)
                if r.get("ok") and r["output"]:
                    self._runtime_ok = False
                    self._mode = None
                    self.ensure_runtime()
                    return
            except TunerdError:
                pass
            time.sleep(2)
        raise TimeoutError("InGame state never became responsive")

    def front_end_screen(self) -> str:
        """Which screen is actually visible: InGame, StagingRoom, JoiningRoom, MPGameSetupScreen, Lobby,
        MultiplayerSelect, MainMenu, or "?". Civ5 keeps several front-end Lua states loaded-but-hidden at
        once (a stale JoiningRoom from an abandoned rejoin survives past the point where MainMenu is what's
        on screen), so this checks ContextPtr:IsHidden() per candidate id instead of trusting a name match."""
        by_name: dict[str, list[int]] = {}
        for sid, name in self.states().items():
            by_name.setdefault(name, []).append(sid)
        for name in ("InGame", "StagingRoom", "JoiningRoom", "MPGameSetupScreen", "Lobby", "MultiplayerSelect", "MainMenu"):
            for sid in by_name.get(name, ()):
                out = self.c.exec(sid, "print(tostring(not ContextPtr:IsHidden()))", check=False)
                if out and out[0].strip() == "true":
                    return name
        return "?"

    # ------------------------------------------------------------ mode / seat
    def mode(self) -> str:
        """'hotseat' | 'lan' | 'internet' | 'single' (cached per game)."""
        if self._mode is None:
            self._mode = self.turn_state(0)["mode"]
        return self._mode

    def detect_seat(self) -> int:
        """In a network game this instance IS one player: the active player. In hotseat the seat must be given."""
        if self.mode() in ("lan", "internet", "single"):
            self.seat = int(self.c.exec("InGame", "print(Game.GetActivePlayer())")[0])
        return self.seat

    # ------------------------------------------------------------ state
    def turn_state(self, pid: int | None = None) -> dict:
        ts = self.q(f"return H.turn_state({self._pid(pid)})")
        # pending_popups only tracks SerialEventGameMessagePopup. Greeting /
        # discussion / tech / great-person screens live in other Lua contexts
        # and can make end_turn silently no-op while that list is empty.
        ts.update(self._modal_flags())
        return ts

    def summary(self, pid: int | None = None) -> dict:
        return self.q(f"return H.player_summary({self._pid(pid)})")

    def units(self, pid: int | None = None) -> list[dict]:
        return self.q(f"return H.units({self._pid(pid)})")

    def cities(self, pid: int | None = None) -> list[dict]:
        return self.q(f"return H.cities({self._pid(pid)})")

    def plots_around(self, x: int, y: int, r: int = 3) -> list[dict]:
        if not 0 <= r <= 12:
            raise ValueError("radius must be between 0 and 12")
        return self.q(f"return H.plots_around({x}, {y}, {r}, Players[{self.seat}]:GetTeam())")

    def known_world(self, pid: int | None = None) -> dict:
        """Everything this seat currently knows: own empire/units/cities, met civs
        (including city-states), notifications, and every revealed plot.

        Each plot has vis=true (in sight now) or vis=false (discovered, currently
        fogged). Fogged plots omit units, owners, improvements, cities, and features.
        Unrevealed tiles are omitted entirely.
        """
        return self.q(f"return H.known_world({self._pid(pid)})")

    def notifications(self, pid: int | None = None) -> list[dict]:
        return self.q(f"return H.notifications({self._pid(pid)})")

    def diplomacy(self, pid: int | None = None) -> list[dict]:
        return self.q(f"return H.diplomacy({self._pid(pid)})")

    def available_policies(self, pid: int | None = None) -> dict:
        """The social policy screen: adopted policies, adoptable ones (with help text), branches and
        whether a policy can be adopted this turn."""
        return self.q(f"return H.available_policies({self._pid(pid)})")

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
        (runtime.lua v13): the engine silently no-ops an invalid war/peace event rather than erroring, so
        H.diplo_event mirrors the real UI's own preconditions (met/at-war state, CanChangeWarPeace,
        CanDeclareWar, IsForcePeace, GetNumTurnsLockedIntoWar) and returns a clean {ok:false, err:...}
        instead of a blind {ok:true} when one of those isn't satisfied. Any other event name is passed
        through unguarded (no precondition was found for it in the game's own Lua)."""
        return self.q(f"return H.diplo_event({lua_str(event)}, {other_player}, {data1}, {data2})")

    def declare_war(self, other_player: int) -> dict:
        return self.diplo_event("HUMAN_DECLARES_WAR", other_player)

    def make_peace(self, other_player: int) -> dict:
        """Offer peace to a civ you are at war with. {ok:true} only means the offer was successfully sent
        to the engine (you were at war, not locked into it) -- the AI still has to accept, and live-tested
        behavior confirms the AI can and typically will reject a peace offer made right after a war
        declaration for a number of turns, even though GetNumTurnsLockedIntoWar reports 0 (that counter
        did not gate this in testing -- the rejection is the AI's own diplomatic-acceptance logic, not
        something this harness can or should bypass). Don't read an accepted-looking {ok:true} as peace
        having actually been made; check diplomacy()'s at_war field to confirm."""
        return self.diplo_event("HUMAN_NEGOTIATE_PEACE", other_player)

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

    def events_since_last(self) -> list[dict]:
        """Recorded game events since the previous call (cursor is kept inside the game's Lua state).

        `unit_destroyed` comes from SerialEventUnitDestroyed, which is a *graphics* event: it also fires
        when the engine merely rebuilds a unit's model -- every unit on an era change (live, t244: all four
        workers "destroyed" on reaching the Industrial era), a caravan starting a route, a unit being
        upgraded. So each of my own `unit_destroyed` events is checked against the live unit list here and
        relabelled `unit_graphics_reset` when the unit still exists, so a caller never mourns a live
        worker. Genuine losses keep `unit_destroyed`."""
        events = self.q(f"return H.take_events({self.seat})")
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
        return events

    def events_peek(self, last_n: int = 50) -> list[dict]:
        return self.q(f"local e = H.events; local out = {{}}; for i = math.max(1, #e - {last_n} + 1), #e do out[#out+1] = e[i] end; return out")

    # ------------------------------------------------------------ hotseat seat handoff
    def player_change_pending(self) -> bool:
        """True when the hotseat 'pass the device' modal is up for our seat."""
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

    def _modal_flags(self) -> dict[str, bool]:
        states = self.states()
        diplo = self._visible_in_state("DiploTrade", "return not ContextPtr:IsHidden()", states)
        discuss = self._visible_in_state("DiscussionDialog", "return not ContextPtr:IsHidden()", states)
        return {
            "leader_greeting_pending": self._visible_in_state(
                "LeaderHeadRoot", "return UI.GetLeaderHeadRootUp()", states),
            "city_state_greeting_pending": self._visible_in_state(
                "CityStateGreetingPopup", "return not ContextPtr:IsHidden()", states),
            "great_person_reward_pending": self._visible_in_state(
                "GreatPersonRewardPopup", "return not ContextPtr:IsHidden()", states),
            "tech_popup_pending": self._visible_in_state(
                "TechPopup", "return not ContextPtr:IsHidden()", states),
            "discussion_pending": diplo or discuss,
        }

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
        return self._visible_in_state("LeaderHeadRoot", "return UI.GetLeaderHeadRootUp()")

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
        return self._visible_in_state("CityStateGreetingPopup", "return not ContextPtr:IsHidden()")

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
        return self._visible_in_state("GreatPersonRewardPopup", "return not ContextPtr:IsHidden()")

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

    def dismiss_pending_popups(self) -> list[str]:
        """Close informational screens through their real callbacks, never child controls.

        A child's IsHidden flag is local to that child, not effective visibility
        through its parents. Hiding those children corrupts future popup displays
        and skips DequeuePopup/turn-timer bookkeeping.
        """
        handlers = {
            "TechAwardPopup": "OnClose",
            "GreatWorkPopup": "OnClose", "WhosWinningPopup": "OnClose",
            "WonderPopup": "OnClose", "LeagueSplash": "OnClose",
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
        if self.turn_state().get("active_player") != self.seat:
            return []
        dismissed = []
        for _ in range(5):
            count = len(dismissed)
            if self.leader_greeting_pending():
                self.dismiss_leader_greeting()
                dismissed.append("LeaderHeadRoot")
                time.sleep(0.15)
            states = set(self.states().values())
            for name, handler in handlers.items():
                if name not in states:
                    continue
                if self.c.query(name, "return not ContextPtr:IsHidden()"):
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
            if self.tech_popup_pending():
                current = self.q(f"return Players[{self.seat}]:GetCurrentResearch()")
                if current != -1:
                    self.dismiss_tech_popup()
                    dismissed.append("TechPopup")
            if len(dismissed) == count:
                break
        return dismissed

    # TechPopup's real content, found live by enumerating pairs(Controls) on the running state --
    # techpopup.lua/xml gives none of them an all-encompassing container the way GreatWorkPopup's
    # GreatWorkSplashContainer does, so every one of them has to be hidden individually (same shape as
    # WonderPopup, whose splash/title/quote/icon/stats/close-button controls are its own similar list).
    _TECH_POPUP_CONTROLS = ("OpenTTButton", "ScrollPanel", "ButtonStack", "ScrollPanelBlackFrame", "ScrollPanelFrame", "TechBackground")

    def tech_popup_pending(self) -> bool:
        return self._visible_in_state("TechPopup", "return not ContextPtr:IsHidden()")

    def dismiss_tech_popup(self) -> None:
        self.c.exec("TechPopup", "ClosePopup()")
        time.sleep(0.15)
        if self.tech_popup_pending():
            raise TunerdError("technology choice popup did not close; needs attention")

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
        states = self.states()
        return (
            self._visible_in_state("DiploTrade", "return not ContextPtr:IsHidden()", states)
            or self._visible_in_state("DiscussionDialog", "return not ContextPtr:IsHidden()", states)
        )

    _DISCUSSION_READ_LUA = """
        local out = {}
        out.speech = Controls.LeaderSpeech:GetText()
        out.title = Controls.TitleText:GetText()
        out.mood = Controls.MoodText:GetText()
        out.player = -1
        for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
            local p = Players[i]
            if p and p:IsAlive() and GameplayUtilities.GetLocalizedLeaderTitle(p) == out.title then out.player = i end
        end
        out.buttons = {}
        for i = 1, 4 do
            local b = Controls['Button' .. i]
            local l = Controls['Button' .. i .. 'Label']
            if b and l and not b:IsHidden() then
                out.buttons[#out.buttons + 1] = {id = i, text = l:GetText() or '', disabled = b:IsDisabled()}
            end
        end
        out.can_go_back = not Controls.BackButton:IsHidden()
        print(out.player, out.title, out.mood, out.can_go_back)
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
        states = self.states()
        out: dict = {"pending": False, "screen": None}
        trade_up = self._visible_in_state("DiploTrade", "return not ContextPtr:IsHidden()", states)
        disc_up = self._visible_in_state("DiscussionDialog", "return not ContextPtr:IsHidden()", states)
        if not (trade_up or disc_up):
            return out
        out["pending"] = True
        out["screen"] = "trade" if trade_up else "discussion"
        dd = [k for k, v in states.items() if v == "DiscussionDialog"]
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
        if out.get("player", -1) >= 0:
            try:
                out["relationship"] = self.relationship(out["player"], pid)
            except TunerdError as e:
                out["relationship"] = {"ok": False, "err": str(e)}
            rel = out["relationship"]
            if rel.get("ok"):
                out.setdefault("leader", rel.get("leader"))
                if trade_up and rel.get("history"):
                    out["speech"] = rel["history"][-1]["text"]
        return out

    def respond_discussion(self, button: int) -> dict:
        """Press response button 1-4 on the open DiscussionDialog (the same OnButton<N> callback the
        real button fires). Refuses when that button is not currently visible, so a stale id from an
        earlier screen cannot pick a different answer on a newer one."""
        d = self.discussion()
        if not d.get("pending") or d.get("screen") != "discussion":
            return {"ok": False, "err": "no discussion screen is open", "discussion": d}
        ids = {b["id"] for b in d.get("buttons", []) if not b["disabled"]}
        if button not in ids:
            return {"ok": False, "err": f"button {button} is not an available response", "buttons": d.get("buttons")}
        dd = self.c.wait_state("DiscussionDialog", 5)
        self.c.exec(dd, f"OnButton{button}()", check=False)
        return {"ok": True, "pressed": button, "text": next(b["text"] for b in d["buttons"] if b["id"] == button),
                **self._settle_leader_remark(), "still_pending": self.discussion_pending()}

    def dismiss_discussion(self) -> dict:
        """Leave the current negotiation/demand/trade-offer screen without agreeing to anything -- same
        call discussiondialog.lua's own Back button makes (OnBack(true), forcing past its g_bCanGoBack
        gate). For a trade table that is already open, prefer refuse_deal() (reads terms first).
        Do not use this to accept; see accept_deal()."""
        dd = self.c.wait_state("DiscussionDialog", 5)
        self.c.exec(dd, "OnBack(true)", check=False)
        return {"ok": True}

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
        deadline = time.monotonic() + 3.0
        after = before
        while time.monotonic() < deadline:
            time.sleep(0.25)
            after = self.city_state_gifts(minor_id, pid)
            if after.get("friendship") != before.get("friendship") or after.get("gold") != before.get("gold"):
                break
        r.update({"friendship_before": before.get("friendship"), "friendship": after.get("friendship"),
                  "friends": after.get("friends"), "allied": after.get("allied"), "gold": after.get("gold")})
        if after.get("friendship") == before.get("friendship") and after.get("gold") == before.get("gold"):
            r["note"] = "no change observed within 3s; re-read city_state_gifts to confirm"
        return r

    def incoming_deal(self, pid: int | None = None) -> dict:
        """Read the current scratch deal (empty, our draft, or an AI/human offer) without mutating it.
        Uses Deal:ResetIterator/GetNextItem, the same read tradelogic.lua's DisplayDeal uses.
        Never calls Add*/ClearItems/DoProposeDeal."""
        return self.q(f"return H.incoming_deal({self._pid(pid)})")

    def accept_deal(self, pid: int | None = None) -> dict:
        """Accept an existing incoming offer already on the trade table. Does not construct a deal.

        If DiploTrade is open, this clicks the stock Accept button (OnPropose / OnPropose(ACCEPT_TYPE)).
        Otherwise it finalizes the current scratch deal via UI.DoFinalizePlayerDeal(them, us, true),
        which tradelogic.lua uses for PvP accept. Refuses if the scratch deal is empty.
        Do not use propose_deal to build a new offer -- that Add* path has crashed the process."""
        states = self.states()
        if self._visible_in_state("DiploTrade", "return not ContextPtr:IsHidden()", states):
            self.c.exec(
                "DiploTrade",
                "if g_bPVPTrade then OnPropose(ACCEPT_TYPE) else OnPropose() end",
                check=False,
            )
            return {"ok": True, "via": "DiploTrade.OnPropose", **self._settle_leader_remark()}
        return self.q(f"return H.accept_deal({self._pid(pid)})")

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
        if self._visible_in_state("DiploTrade", "return not ContextPtr:IsHidden()", states):
            self.c.exec(
                "DiploTrade",
                "if g_bPVPTrade then OnBack(REFUSE_TYPE) else OnBack() end",
                check=False,
            )
            return {"ok": True, "via": "DiploTrade.OnBack", **self._settle_leader_remark()}
        return self.q(f"return H.refuse_deal({self._pid(pid)})")

    def wait_for_my_turn(self, timeout: float = 3600, poll: float = 1.0) -> dict:
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
        yet, see its docstring), then call wait_for_my_turn() again."""
        deadline = time.monotonic() + timeout
        was_connected = bool(self.c.ping().get("connected"))
        while time.monotonic() < deadline:
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
                time.sleep(poll)
                continue
            if self.dismiss_pending_popups():
                time.sleep(0.5)
            if self.discussion_pending():
                d = self.discussion()
                if d.get("screen") == "discussion" and not d.get("buttons") and d.get("can_go_back"):
                    # A leader remark with nothing to answer (e.g. "Very well." after a deal): the only
                    # control is Back. Real choices (buttons) or a trade table always stop here.
                    self.dismiss_discussion()
                    time.sleep(0.5)
                    continue
                return {**self.turn_state(), "discussion_pending": True, "discussion": d}
            if self.tech_popup_pending():
                # Only auto-dismiss once research is actually chosen (GetCurrentResearch() != -1) --
                # dismissing an unresolved choice would leave research silently unset with no reliable
                # blocking signal to catch it (see tech_popup_pending()'s docstring), trading one silent
                # hang for a worse one. If research is still unset, return immediately so the caller
                # can pick a tech instead of polling until timeout with my_turn stuck false.
                cur = self.q(f"return Players[{self._pid(None)}]:GetCurrentResearch()")
                if cur != -1:
                    self.dismiss_tech_popup()
                    time.sleep(0.5)
                else:
                    return {**self.turn_state(), "tech_popup_pending": True}
            ts = self.turn_state()
            if ts["my_turn"] and not ts["processing"]:
                if ts["hotseat"] and self.player_change_pending():
                    self.dismiss_player_change()
                    time.sleep(0.5)
                    ts = self.turn_state()
                return ts
            time.sleep(poll)
        raise TimeoutError("timed out waiting for our turn")

    def net_players(self) -> list[dict]:
        """Network games: human players with connected / turn-active / ended-turn flags."""
        return self.q("return H.net_players()")

    # ------------------------------------------------------------ actions
    def select_unit(self, unit_id: int, pid: int | None = None, look_at: bool = False) -> dict:
        """Select a unit. Camera pan is opt-in: UI.LookAt has flipped the live map into 2D."""
        look = "UI.LookAt(u:GetPlot(), 0)" if look_at else "-- camera pan skipped"
        return self.q(f"""
            if Game.GetActivePlayer() ~= {self._pid(pid)} then return {{ok=false, err="this seat is not active"}} end
            local u = Players[{self._pid(pid)}]:GetUnitByID({unit_id})
            if not u then return {{ok=false, err="no such unit"}} end
            UI.SelectUnit(u); {look}
            return {{ok=true}}""")

    def move_unit(self, unit_id: int, x: int, y: int, pid: int | None = None, settle_timeout: float = 1.0) -> dict:
        """Issue a move-to for a unit via Unit:PushMission (no UI.SelectUnit).

        PushMission queues pathing -- the unit's x/y read back in the same Lua call can still
        be the pre-move plot, so poll briefly for GetX/GetY or MovesLeft to change before
        returning. If the engine has not advanced within the timeout, report the pre-move
        reading honestly. Does not pan the camera or flip 2D/3D."""
        r = self.q(f"return H.move_unit({unit_id}, {x}, {y}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        deadline = time.monotonic() + settle_timeout
        cur = r
        while time.monotonic() < deadline:
            time.sleep(0.15)
            cur = self.q(f"return H.unit_pos({unit_id}, {self._pid(pid)})")
            if not cur.get("ok"):
                return cur
            if (cur["x"], cur["y"]) != (r["x"], r["y"]) or cur["moves"] != r["moves"]:
                return cur
        # Nothing changed within settle_timeout. A unit with no moves left keeps the order queued for
        # next turn (activity MISSION); otherwise the engine dropped it silently -- no path to that
        # plot (unexplored/impassable terrain in the way, another civ's closed borders, a unit in the
        # way) -- and reporting ok:true here sent callers on with a unit that never moved (live t252).
        if cur.get("ok") and (cur.get("activity") == 6 or (r.get("moves") or 0) <= 0):
            cur["queued"] = True
            return cur
        return {"ok": False, "err": "unit did not move: the engine found no path to that plot (unexplored or impassable "
                                    "terrain in the way, a closed border, or a unit blocking it); try a nearer plot",
                "x": r.get("x"), "y": r.get("y"), "moves": r.get("moves")}

    def unit_mission(self, unit_id: int, mission: str, x: int = -1, y: int = -1, data2: int = 0,
                      build: str | None = None, pid: int | None = None) -> dict:
        """Push a mission by name via Unit:PushMission (no UI.SelectUnit).

        e.g. MISSION_FOUND, MISSION_FORTIFY, MISSION_SLEEP, MISSION_SKIP, MISSION_MOVE_TO (x, y).
        `data2` is accepted for call-site compatibility and ignored: extra mission data is `build`
        for MISSION_BUILD, or x/y for movement-shaped missions.

        MISSION_BUILD: pass the improvement via `build=` (e.g. build="BUILD_FARM"), NOT x/y --
        PushMission puts the BuildTypes id in iData1. The build always applies to the unit's own tile.

        PushMission itself does not report whether the mission stuck (same class of silent no-op
        as the old SelectionListGameNetMessage path). For MISSION_BUILD this verifies GetBuildType()
        actually left -1 before reporting success."""
        _ = data2
        build_arg = lua_str(build) if build else "nil"
        push = lambda: self.q(
            f"return H.unit_mission({unit_id}, {lua_str(mission)}, {x}, {y}, {build_arg}, {self._pid(pid)})"
        )
        if mission in ("MISSION_RANGE_ATTACK", "MISSION_NUKE", "MISSION_PARADROP") and x >= 0 and y >= 0:
            r = self._with_target_result(x, y, push, pid)
        else:
            r = push()
        if not r.get("ok"):
            return r
        if build is not None:
            if r.get("buildtype", -1) != -1 or r.get("completed"):
                return r
            time.sleep(0.3)
            chk = self.q(f"return H.unit_pos({unit_id}, {self._pid(pid)})")
            if chk.get("ok") and chk.get("buildtype", -1) == -1:
                return {"ok": False, "err": "mission accepted but did not start a build (bad build type for this tile/unit?)"}
            return r
        # Report the unit's state after the mission so the caller need not re-read units(): a Great
        # Person mission (MISSION_GIVE_POLICIES / CREATE_GREAT_WORK / BUILD_ACADEMY...) consumes the
        # unit, and otherwise moves/position tell whether the order actually took.
        time.sleep(0.2)
        after = self.q(f"return H.unit_pos({unit_id}, {self._pid(pid)})")
        if after.get("ok"):
            r.update({k: after[k] for k in ("x", "y", "moves", "activity", "activity_name") if k in after})
        else:
            r["consumed"] = True
        return r

    def set_production(self, city_id: int, order: str, item: str, pid: int | None = None) -> dict:
        """order: ORDER_TRAIN|ORDER_CONSTRUCT|ORDER_CREATE|ORDER_MAINTAIN; item: UNIT_WARRIOR / BUILDING_MONUMENT / PROJECT_... / PROCESS_...

        `city:GetProductionNameKey()` read back in the same Lua call as `Game.CityPushOrder` still
        reports the *previous* head-of-queue item -- confirmed live (pushing a Settler over an
        in-progress Worker reported "Worker" back even though the queue had already been replaced).
        Re-read after a short settle delay so the returned name/turns match what was actually queued.

        Also checks the matching Can{{Construct,Train,Create,Maintain}}() guard up front: CityPushOrder
        itself accepts and silently drops an invalid order (e.g. a building the city already has) --
        confirmed live requesting BUILDING_MONUMENT a second time: {ok=true} came back but the queue
        never changed (production stayed empty, turns stuck at the 2147483647 "nothing queued"
        sentinel). This turns that into a real error up front instead.

        `order`/`item` must actually match (see `_check_order_item`) -- checked before this ever reaches
        the engine, for the same reason `purchase_cost`/`purchase_production` check it (see their
        docstrings for the live crash this class of bug caused there)."""
        mismatch = _check_order_item(order, item)
        if mismatch:
            return mismatch
        can_fn = {"ORDER_TRAIN": "CanTrain", "ORDER_CONSTRUCT": "CanConstruct",
                  "ORDER_CREATE": "CanCreate", "ORDER_MAINTAIN": "CanMaintain"}[order]
        pre = self.q(f"""
            local city = Players[{self._pid(pid)}]:GetCityByID({city_id})
            if not city then return {{ok=false, err="no such city"}} end
            local id = GameInfoTypes[{lua_str(item)}]
            if id == nil then return {{ok=false, err="unknown item"}} end
            if not city:{can_fn}(id, 0) then return {{ok=false, err="city cannot build this (missing prereq, already built, or one-per-city)"}} end
            return {{ok=true, id=id}}""")
        if not pre.get("ok"):
            return pre
        r = self.q(f"""
            local city = Players[{self._pid(pid)}]:GetCityByID({city_id})
            Game.CityPushOrder(city, OrderTypes.{order}, {pre['id']}, false, true, true)
            return {{ok=true}}""")
        if not r.get("ok"):
            return r
        time.sleep(0.3)
        return self.q(f"""
            local city = Players[{self._pid(pid)}]:GetCityByID({city_id})
            if not city then return {{ok=false, err="no such city"}} end
            return {{ok=true, production=H.L(city:GetProductionNameKey()), turns=city:GetProductionTurnsLeft()}}""")

    def purchase_cost(self, city_id: int, order: str, item: str, yield_type: str = "GOLD", pid: int | None = None) -> dict:
        """Read-only: cost to rush-buy `item` with gold or faith right now, and whether it's actually
        purchasable (`city:IsCanPurchase(true, true, ...)`, the same gate purchase_production checks before
        spending anything). order: ORDER_TRAIN (unit) | ORDER_CONSTRUCT (building) | ORDER_CREATE (project/
        wonder -- vanilla BNW's own UI hardcodes this as never purchasable regardless of cost, confirmed in
        `ui/ingame/popups/productionpopup.lua`'s wonder-listing code; `can_purchase` will read false).

        `order`/`item` must actually match -- see `_check_order_item`'s docstring for the live crash this
        exact function caused (ORDER_CREATE + a BUILDING_* item) before this check existed."""
        if order not in ("ORDER_TRAIN", "ORDER_CONSTRUCT", "ORDER_CREATE"):
            return {"ok": False, "err": "order must be ORDER_TRAIN, ORDER_CONSTRUCT, or ORDER_CREATE"}
        mismatch = _check_order_item(order, item)
        if mismatch:
            return mismatch
        unit_id, building_id, project_id = ("id", "-1", "-1") if order == "ORDER_TRAIN" else \
            (("-1", "id", "-1") if order == "ORDER_CONSTRUCT" else ("-1", "-1", "id"))
        cost_fn = {"ORDER_TRAIN": "GetUnitPurchaseCost", "ORDER_CONSTRUCT": "GetBuildingPurchaseCost",
                   "ORDER_CREATE": "GetProjectPurchaseCost"}[order]
        faith_cost_fn = {"ORDER_TRAIN": "GetUnitFaithPurchaseCost", "ORDER_CONSTRUCT": "GetBuildingFaithPurchaseCost",
                         "ORDER_CREATE": "GetProjectPurchaseCost"}[order]  # no project-faith-specific getter found; reuse gold one
        yield_const = {"GOLD": "YieldTypes.YIELD_GOLD", "FAITH": "YieldTypes.YIELD_FAITH"}[yield_type]
        cost_call = f"city:{cost_fn}(id)" if yield_type == "GOLD" else \
            (f"city:{faith_cost_fn}(id, true)" if order == "ORDER_TRAIN" else f"city:{faith_cost_fn}(id)")
        return self.q(f"""
            local city = Players[{self._pid(pid)}]:GetCityByID({city_id})
            if not city then return {{ok=false, err="no such city"}} end
            local id = GameInfoTypes[{lua_str(item)}]
            if id == nil then return {{ok=false, err="unknown item"}} end
            return {{ok=true, cost={cost_call}, can_purchase=city:IsCanPurchase(true, true, {unit_id}, {building_id}, {project_id}, {yield_const}),
                     balance=Players[{self._pid(pid)}]:{"GetGold" if yield_type == "GOLD" else "GetFaith"}()}}""")

    def purchase_production(self, city_id: int, order: str, item: str, yield_type: str = "GOLD", pid: int | None = None) -> dict:
        """Rush-buy a unit/building with gold or faith (yield_type: "GOLD" or "FAITH"). See purchase_cost
        for price/affordability first. order: ORDER_TRAIN (unit) | ORDER_CONSTRUCT (building) | ORDER_CREATE
        (project/wonder -- always refused, see purchase_cost's docstring). Checks
        `city:IsCanPurchase(true, true, ...)` up front -- the same real "can actually complete this" gate
        the UI reads to grey out the purchase button -- and returns a clean {ok:false} instead of a silent
        no-op or wasted currency. Confirmed against `ui/ingame/popups/productionpopup.lua`'s
        OnProductionButtonClick: `Game.CityPurchaseUnit/CityPurchaseBuilding/CityPurchaseProject(city, id,
        eYield)`.

        `order`/`item` must actually match -- see `_check_order_item`'s docstring for why this matters here
        specifically (a mismatched pair crashed the game via this function's sibling, `purchase_cost`)."""
        if order not in ("ORDER_TRAIN", "ORDER_CONSTRUCT", "ORDER_CREATE"):
            return {"ok": False, "err": "order must be ORDER_TRAIN, ORDER_CONSTRUCT, or ORDER_CREATE"}
        mismatch = _check_order_item(order, item)
        if mismatch:
            return mismatch
        unit_id, building_id, project_id = ("id", "-1", "-1") if order == "ORDER_TRAIN" else \
            (("-1", "id", "-1") if order == "ORDER_CONSTRUCT" else ("-1", "-1", "id"))
        purchase_fn = {"ORDER_TRAIN": "CityPurchaseUnit", "ORDER_CONSTRUCT": "CityPurchaseBuilding",
                       "ORDER_CREATE": "CityPurchaseProject"}[order]
        yield_const = {"GOLD": "YieldTypes.YIELD_GOLD", "FAITH": "YieldTypes.YIELD_FAITH"}[yield_type]
        pre = self.q(f"""
            local city = Players[{self._pid(pid)}]:GetCityByID({city_id})
            if not city then return {{ok=false, err="no such city"}} end
            local id = GameInfoTypes[{lua_str(item)}]
            if id == nil then return {{ok=false, err="unknown item"}} end
            if not city:IsCanPurchase(true, true, {unit_id}, {building_id}, {project_id}, {yield_const}) then
                return {{ok=false, err="cannot purchase this right now (not enough currency, already queued, or not purchasable this way)"}}
            end
            return {{ok=true, id=id}}""")
        if not pre.get("ok"):
            return pre
        item_id = pre["id"]
        r = self.q(f"""
            local city = Players[{self._pid(pid)}]:GetCityByID({city_id})
            Game.{purchase_fn}(city, {item_id}, {yield_const})
            return {{ok=true}}""")
        if not r.get("ok"):
            return r
        time.sleep(0.3)
        return self.q(f"""
            local city = Players[{self._pid(pid)}]:GetCityByID({city_id})
            if not city then return {{ok=false, err="no such city"}} end
            return {{ok=true, production=H.L(city:GetProductionNameKey()), turns=city:GetProductionTurnsLeft(),
                     balance=Players[{self._pid(pid)}]:{"GetGold" if yield_type == "GOLD" else "GetFaith"}()}}""")

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
            return pre
        if pre["has_tech"]:
            return {"ok": False, "err": "already researched"}
        if not pre.get("can"):
            return {"ok": False, "err": "cannot research this yet (missing prerequisites or disabled)"}
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
            return {{ok=true, current=cur, research=name, has_tech=Teams[p:GetTeam()]:IsHasTech({pre['id']}), free=p:GetNumFreeTechs()}}""")
        if pre.get("free", 0) > 0:
            # A free tech (Oxford University, Great Scientist-less ruins, ENDTURN_BLOCKING_FREE_TECH) is
            # granted outright and current research is left alone -- live: Oxford's free Industrialization
            # was granted while Chemistry stayed the active research, and the old "research did not
            # change" check reported a false failure. Success here is "the tech is now known".
            if chk.get("has_tech"):
                return {"ok": True, "granted": tech, "free_techs_left": chk.get("free"), "research": chk.get("research")}
            return {"ok": False, "err": "SendResearch accepted but the free tech was not granted", "free_techs_left": chk.get("free")}
        if chk.get("ok") and (chk.get("current") == -1 or chk.get("current") == pre["current"]):
            return {"ok": False, "err": "SendResearch accepted but current research did not change (free-tech count mismatch?)"}
        return {"ok": True, "research": chk.get("research")}

    def quick_save(self) -> dict:
        """Same path as the in-game Quick Save button / F5 (`UI.QuickSave()`, see gamemenu.lua's
        OnQuickSave). No filename/confirmation needed. Hotseat games can't be auto-rejoined by
        harness/supervisor.py after a crash, so treat this as cheap insurance against exactly that: call it
        after anything costly (founding a city, a policy/research choice, before combat) rather than only
        relying on the engine's own periodic autosave interval, since a crash before the next autosave loses
        everything back to the last one. See `load_save()` for the load counterpart."""
        return self.q("UI.QuickSave(); return {ok=true, turn=Game.GetGameTurn()}")

    def load_save(self, filename: str, timeout: float = 300) -> dict:
        """Load a save file from the main menu by its bare name -- no path, no `.Civ5Save` extension, e.g.
        "QuickSave" or "Sejong_0180 AD-1200" (auto-saves, quick-saves, and manual saves are all matched by
        basename regardless of which subfolder they live in). Fires the same event the Load Game screen's
        Start button does (`loadmenu.lua`'s `OnStartButton` -> native `InterfaceBuddy::OnPlayerChoseToLoadGame`,
        confirmed via `strings` on the `Civ5XP` binary -- so it's caught natively and can be fired from any
        Lua state, no popup UI needs to actually be open). The single required trick: that event wants the
        *exact* string `UI.SaveFileList()` produces -- a full OS path with `.Civ5Save`, backslash separators
        (this is a Windows port) -- not the bare display name `GetDisplayName()` derives from it for the
        list UI; an earlier reading of just the Lua source (not confirmed live) got this backwards. So this
        builds the real list via `UI.SaveFileList(t, GameTypes.GAME_SINGLE_PLAYER, showAutoSaves, true)` from
        the `LoadMenu` state and matches `filename` against each entry's basename minus extension before
        firing the event with the untouched raw path. `showAutoSaves` toggles which folder the list draws
        from rather than adding to it (manual+quick saves vs. auto-saves are mutually exclusive listings,
        confirmed live), so both are tried in turn.

        **"QuickSave" is ambiguous and used to silently pick the WRONG file** -- found live (2026-09-16,
        recovering from the crash right after a `propose_deal` OPEN_BORDERS test): the native F5 hotkey
        quicksave writes `Saves/single/QuickSave.Civ5Save`, while this harness's own `quick_save()`
        (`UI.QuickSave()`) writes a *different* file, `Saves/single/quick/QuickSave.Civ5Save` -- both display
        as bare name "QuickSave", both show up in the same `showAutoSaves=false` listing, and the old code
        just took the first list match. That happened to be the stale top-level one: `load_save("QuickSave")`
        came back `{ok:true, turn:215}` right after a `quick_save()` at turn 219 -- four turns silently lost,
        no error, exactly the "accepted but wrong" shape this harness keeps running into elsewhere. Now
        disambiguates every same-basename match by real filesystem mtime (`_newest_save`) instead of trusting
        list order -- the raw path IS a real Linux path (just backslash-separated, a Windows-port quirk, not
        an actual Windows path), so this stats it directly rather than guessing from engine-side ordering."""
        lm = self.c.wait_state("LoadMenu", 10)
        match = None
        available: list[str] = []
        for show_auto in ("false", "true"):
            listing = self.c.exec(lm, f"""
                local t = {{}}
                UI.SaveFileList(t, GameTypes.GAME_SINGLE_PLAYER, {show_auto}, true)
                for i, v in ipairs(t) do print(v) end
            """, check=True)
            available += [pathlib.PureWindowsPath(p).stem for p in listing]
            candidates = [p for p in listing if pathlib.PureWindowsPath(p).stem == filename]
            if candidates:
                match = _newest_save(candidates)
                break
        if match is None:
            return {"ok": False, "err": f"no save named {filename!r}; available: {available}"}
        return self._finish_load(lm, match, timeout)

    def _finish_load(self, lm: int | str, match: str, timeout: float) -> dict:
        self.c.exec(lm, f"Events.PlayerChoseToLoadGame({lua_str(match)})", check=True)
        self.wait_ingame(timeout)
        self._mode = None
        # A loaded (or freshly started) single-player game always lands on the "Dawn of Man"/continue
        # splash (loadscreen.lua's OnSequenceGameInitComplete) with Game.SetPausePlayer(activePlayer)
        # already in effect -- InGame is responsive and turn_state() looks normal except paused=true and
        # every action silently no-ops (end_turn, production, etc. all return {ok:true} but nothing moves)
        # until this is dismissed. Confirmed live: this is exactly what OnActivateButtonClicked (the
        # screen's own Continue button) does for a non-hotseat/non-MP game.
        try:
            ls = self.c.wait_state("LoadScreen", 5)
            self.c.exec(ls, "Events.LoadScreenClose(); Game.SetPausePlayer(-1)", check=False)
        except TunerdError:
            pass
        return {"ok": True, "turn": self.turn_state(0).get("turn")}

    def load_latest(self, timeout: float = 300) -> dict:
        """Crash-recovery convenience: load whichever single-player save (quick/manual OR auto-save) has
        the newest real filesystem mtime, full stop -- unlike `load_save(name)`, which only disambiguates
        *same-named* candidates and, by design, checks quick/manual saves before ever looking at auto-saves
        at all. That's the right default for "load the file named X", but wrong for "resume where I just
        was": found live (2026-09-16) recovering from an ambient rendering crash mid-turn-264 --
        `load_save("QuickSave")` came back `{ok:true, turn:257}`, silently 3-4 turns behind an actual
        `AutoSave_0260 AD-1750` autosave sitting on disk with a newer mtime, because the engine's periodic
        autosave had run during manual play after the last explicit quicksave and `load_save` never
        considered it. Costs an extra `UI.SaveFileList` call (auto=true) over `load_save`, otherwise
        identical mechanics (same `_finish_load` tail)."""
        lm = self.c.wait_state("LoadMenu", 10)
        all_paths: list[str] = []
        for show_auto in ("false", "true"):
            listing = self.c.exec(lm, f"""
                local t = {{}}
                UI.SaveFileList(t, GameTypes.GAME_SINGLE_PLAYER, {show_auto}, true)
                for i, v in ipairs(t) do print(v) end
            """, check=True)
            all_paths += listing
        if not all_paths:
            return {"ok": False, "err": "no save games found"}
        match = _newest_save(all_paths)
        return self._finish_load(lm, match, timeout)

    def end_turn(self, autosave: bool = True) -> dict:
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
        if self.discussion_pending():
            return {"ok": False, "err": "diplomatic decision pending"}
        if self.dismiss_pending_popups():
            time.sleep(0.5)
        autosave_lua = "if not Game.IsNetworkMultiPlayer() then UI.QuickSave() end" if autosave else ""
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
            if blocking ~= -1 then
                local name = H.blocking_name(blocking)
                return {{ok=false, err="turn has unresolved decisions: " .. H.blocking_hint(name), blocking=name, todo=H.todo({self.seat})}}
            end
            local popups = H.pending_popups({self.seat})
            if #popups > 0 then return {{ok=false, err="popup needs attention", pending_popups=popups}} end
            {autosave_lua}
            Game.DoControl(GameInfoTypes.CONTROL_ENDTURN)
            return {{ok=true, blocking_before=blocking, turn_complete_sent=Game.IsNetworkMultiPlayer() and Network.HasSentNetTurnComplete() or false}}""")

    def unready_turn(self) -> dict:
        """Network games: take back a sent turn-complete (only works until every player has ended)."""
        return self.q("if Network.HasSentNetTurnComplete() then return {ok=Network.SendTurnUnready()} end return {ok=false, err='turn-complete not sent'}")

    # ------------------------------------------------------------ more actions (added after a live crash
    # from an unguarded raw lua() probe for city_ranged_attack -- these follow the game's own validated
    # call paths, see docs/NOTES.md for the Lua source each one is derived from)
    def plot_units(self, x: int, y: int, pid: int | None = None) -> dict:
        """Units (and city) on one plot as my team sees it right now -- {visible, units:[{id,owner,type,hp}], city?}."""
        return self.q(f"return H.plot_units({x}, {y}, Players[{self._pid(pid)}]:GetTeam())")

    def _with_target_result(self, x: int, y: int, act, pid: int | None = None, settle: float = 2.0) -> dict:
        """Run an attack `act()` against plot (x, y) and attach what happened to the target: `target_before`,
        `target_after` (units/city on the plot with hp), `damage_dealt`, `killed`. The engine applies the
        attack asynchronously (a net message), so this polls until the plot's occupants change or `settle`
        seconds pass -- an unchanged reading is reported as-is, never guessed at."""
        before = self.plot_units(x, y, pid)
        r = act()
        if not r.get("ok"):
            return r
        r["target_before"] = before
        deadline = time.monotonic() + settle
        after = before
        while time.monotonic() < deadline:
            time.sleep(0.25)
            after = self.plot_units(x, y, pid)
            if after != before:
                break
        r["target_after"] = after
        bu = {u["id"]: u for u in before.get("units", [])}
        au = {u["id"]: u for u in after.get("units", [])}
        if bu:
            killed = [u["type"] for i, u in bu.items() if i not in au and u.get("owner") != self._pid(pid)]
            dmg = [bu[i]["hp"] - au[i]["hp"] for i in bu if i in au]
            if killed:
                r["killed"] = killed
            elif dmg:
                r["damage_dealt"] = max(dmg)
        if before.get("city") and after.get("city"):
            r["city_damage_dealt"] = before["city"]["hp"] - after["city"]["hp"]
        if after == before:
            r["note"] = "target unchanged after the attack settled; it may not have been visible, or the attack did not resolve"
        return r

    def city_ranged_attack(self, city_id: int, x: int, y: int, pid: int | None = None) -> dict:
        """Ranged attack from a city. Selection-free: Network.SendDoTask, not UI.SelectCity.
        Returns the target's hp before/after and damage_dealt / killed (see _with_target_result)."""
        return self._with_target_result(
            x, y, lambda: self.q(f"return H.city_ranged_attack({city_id}, {x}, {y}, {self._pid(pid)})"), pid)

    def available_city_strikes(self, city_id: int, pid: int | None = None) -> dict:
        """Plots this city can currently bombard (CanRangeStrikeAt). Empty if it cannot strike."""
        return self.q(f"return H.available_city_strikes({city_id}, {self._pid(pid)})")

    def choose_promotion(self, unit_id: int, promotion: str, pid: int | None = None) -> dict:
        """Pick a promotion for a unit with ENDTURN_BLOCKING_UNIT_PROMOTION, e.g. PROMOTION_SHOCK_1."""
        return self.q(f"return H.choose_promotion({unit_id}, {lua_str(promotion)}, {self._pid(pid)})")

    def upgrade_unit(self, unit_id: int, pid: int | None = None) -> dict:
        """Upgrade a unit for gold along its upgrade path (Warrior -> Swordsman ...). The engine
        replaces the unit: the result's `unit_id` is the NEW id, `old_unit_id` the one passed in."""
        return self.q(f"return H.upgrade_unit({unit_id}, {self._pid(pid)})")

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

    def _confirm_policy(self, r: dict, want: str, key: str, pid: int | None) -> dict:
        """Network.SendUpdatePolicies is asynchronous: poll available_policies until `want` shows up as
        adopted (policy) / unlocked (branch), then report culture, next cost and the blocker state, so the
        caller knows the choice took without a second read."""
        if not r.get("ok"):
            return r
        deadline = time.monotonic() + 3.0
        ap = {}
        done = False
        while time.monotonic() < deadline:
            time.sleep(0.25)
            ap = self.available_policies(pid) or {}
            if key == "policy":
                done = any(a.get("policy") == want for a in ap.get("adopted", []) if isinstance(a, dict))
            else:
                done = any(b.get("branch") == want and b.get("unlocked") for b in ap.get("branches", []) if isinstance(b, dict))
            if done:
                break
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

    def free_great_person_options(self, pid: int | None = None) -> dict:
        """How many free Great People are owed (ENDTURN_BLOCKING_FREE_ITEMS) and the unit types to pick from."""
        return self.q(f"return H.free_great_person_options({self._pid(pid)})")

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
        return self.q(f"return H.found_religion({lua_str(religion)}, {lua_beliefs}, {city_x}, {city_y}, {lua_str(custom_name)}, {self._pid(pid)})")

    def enhance_religion(self, religion: str, belief4: str, belief5: str, city_x: int, city_y: int,
                          custom_name: str = "", pid: int | None = None) -> dict:
        """Enhance my founded religion by picking two more beliefs. Check turn_state().blocking_name ==
        'ENDTURN_BLOCKING_ENHANCE_RELIGION' first (see found_pantheon)."""
        return self.q(f"return H.enhance_religion({lua_str(religion)}, {lua_str(belief4)}, {lua_str(belief5)}, {city_x}, {city_y}, {lua_str(custom_name)}, {self._pid(pid)})")

    def establish_trade_route(self, unit_id: int, dest_x: int, dest_y: int, trade_type: int, pid: int | None = None) -> dict:
        """Send a caravan/cargo ship to establish a trade route. See available_trade_routes for valid destinations/types.

        Uses Unit:PushMission (no UI.SelectUnit). The old SelectionListGameNetMessage path needed the
        unit selected first; selecting flips 2D/3D, and a same-call SelectUnit+push silently no-op'd."""
        # Confirm by the active-route list: the caravan is consumed and re-created under a NEW unit id
        # when the route starts, and GetNumInternationalTradeRoutesUsed counts trade units, not routes
        # (it read 5 before and after on the first live try), so neither the unit nor that count proves
        # anything. GetTradeRoutes() gains one entry.
        before = self.trade_routes(pid)
        r = self.q(f"return H.establish_trade_route({unit_id}, {dest_x}, {dest_y}, {trade_type}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        deadline = time.monotonic() + 3.0
        after = before
        while time.monotonic() < deadline:
            time.sleep(0.25)
            after = self.trade_routes(pid)
            if isinstance(after, list) and isinstance(before, list) and len(after) != len(before):
                break
        if isinstance(after, list) and isinstance(before, list) and len(after) > len(before):
            key = lambda x: (x.get("from_city"), x.get("to_city"), x.get("turns_left"))
            seen = {key(x) for x in before}
            new = [x for x in after if key(x) not in seen]
            r.update({"established": True, "route": new[0] if new else None, "routes_active": len(after)})
        else:
            r.update({"established": False, "note": "no new entry in trade_routes within 3s; check trade_routes / units"})
        return r

    def trade_routes(self, pid: int | None = None) -> list[dict]:
        """My active trade routes: from/to city, turns_left, per-turn yields for each end."""
        return self.q(f"return H.trade_routes({self._pid(pid)})")

    def plunder_trade_route(self, unit_id: int, pid: int | None = None) -> dict:
        """Order a military unit to plunder an enemy trade route it's standing on."""
        return self.unit_mission(unit_id, "MISSION_PLUNDER_TRADE_ROUTE", pid=pid)

    def available_research(self, pid: int | None = None) -> list[dict]:
        """Techs this seat can currently research (prereqs met, not already owned)."""
        return self.q(f"return H.available_research({self._pid(pid)})")

    def available_production(self, city_id: int, pid: int | None = None) -> dict:
        """Units/buildings/projects/processes this city can put at the head of its queue right now."""
        return self.q(f"return H.available_production({city_id}, {self._pid(pid)})")

    def available_unit_actions(self, unit_id: int, pid: int | None = None) -> dict:
        """Currently legal unit-panel actions for this unit (missions, builds, commands, promotions).

        Selection-free: uses CanStartMission/CanBuild/CanDoCommand so catalog reads do not
        UI.SelectUnit (that call flips the live 2D/3D map view).
        """
        return self.q(f"return H.available_unit_actions({unit_id}, {self._pid(pid)})")

    def available_trade_routes(self, unit_id: int, pid: int | None = None) -> list[dict]:
        """Valid trade-route destinations for a specific trade unit (caravan/cargo ship) right now, with
        the exact `trade_connection_type` to pass as `establish_trade_route`'s `trade_type`. Per-unit,
        not global -- see `establish_trade_route`'s docstring for why."""
        return self.q(f"return H.available_trade_routes({unit_id}, {self._pid(pid)})")

    def league_status(self, pid: int | None = None) -> dict:
        """Read-only: World Congress state. Between sessions (in_session=false): `proposable_enact`
        (resolution types I can propose to enact, with a `choices` list if the resolution needs one -- pass
        a choice id into league_propose_enact) and `proposable_repeal` (active resolutions I can propose to
        repeal). During a session (in_session=true): `votable`, the enact/repeal proposals on the table this
        session, for league_cast_votes. `has_league=false` if no league exists yet (too early in the game)."""
        return self.q(f"return H.league_status({self._pid(pid)})")

    def league_propose_enact(self, resolution_type: str, choice: int = -1, pid: int | None = None) -> dict:
        """Propose enacting a World Congress resolution (see league_status()'s proposable_enact), e.g.
        RESOLUTION_SCIENCES_FUNDING. Needed to clear ENDTURN_BLOCKING_LEAGUE_CALL_FOR_PROPOSALS -- this is a
        HARD block, confirmed live: closing the World Congress screen without actually proposing something
        does NOT clear it, unlike every other popup-shaped blocker in this harness. `choice` is required (an
        id from proposable_enact's `choices` list) for resolutions that need one, e.g. which civ to embargo
        or which resource to ban."""
        return self.q(f"return H.league_propose_enact({lua_str(resolution_type)}, {choice}, {self._pid(pid)})")

    def league_propose_repeal(self, resolution_id: int, pid: int | None = None) -> dict:
        """Propose repealing an active World Congress resolution (see league_status()'s proposable_repeal,
        `resolution_id`)."""
        return self.q(f"return H.league_propose_repeal({resolution_id}, {self._pid(pid)})")

    def league_cast_votes(self, votes: list[dict], pid: int | None = None) -> dict:
        """Vote on this session's World Congress proposals (see league_status()'s `votable` while
        in_session). Only valid when blocking_name is ENDTURN_BLOCKING_LEAGUE_CALL_FOR_VOTES -- a hard
        block like proposals, confirmed live (turn 243, First Rio de Janeiro Conference): casting the
        single available vote for the session's own "Sciences Funding" proposal cleared
        ENDTURN_BLOCKING_LEAGUE_CALL_FOR_VOTES immediately (blocking_name back to
        NO_ENDTURN_BLOCKING_TYPE in the same call). `votes`: a list of {"resolution_id": id,
        "direction": "enact"|"repeal", "num_votes": n, "choice": id (optional, for resolutions with
        voter choices)}. Any votes left over after these are automatically cast as abstain, matching
        the real UI's own always-abstain-the-remainder behaviour."""
        return self.q(f"return H.league_cast_votes({_lua_items(votes)}, {self._pid(pid)})")

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
        button uses; returns a clean {ok:false} if it's not actually available right now."""
        return self.q(f"return H.stage_coup({agent_id}, {self._pid(pid)})")

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
                        "RESEARCH_AGREEMENT", "TRADE_AGREEMENT", "ALLOW_EMBASSY", "CITIES")
    _TRADE_PROMPT = "What do you propose?"

    def _leader_up(self, states=None) -> bool:
        return self._visible_in_state("LeaderHeadRoot", "return UI.GetLeaderHeadRootUp()", states)

    def _trade_up(self, states=None) -> bool:
        return self._visible_in_state("DiploTrade", "return not ContextPtr:IsHidden()", states)

    def _discussion_up(self, states=None) -> bool:
        return self._visible_in_state("DiscussionDialog", "return not ContextPtr:IsHidden()", states)

    def _wait_until(self, pred, timeout: float, poll: float = 0.25) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if pred():
                return True
            time.sleep(poll)
        return bool(pred())

    def _trade_text(self) -> str:
        out = self.c.exec("DiploTrade", "print(Controls.DiscussionText:GetText())", check=False)
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
                self.c.exec("DiploTrade", "OnBack()", check=False)
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
        for r, b in before.get("resources", {}).items():
            a = after.get("resources", {}).get(r, {})
            if a != b:
                eff[r] = {"before": b, "after": a}
        return eff

    def _open_trade_screen(self, other: int, pid: int) -> dict:
        """Leader screen -> Trade button, verified: the leader on screen is `other` and the table's
        counterpart is `other`. Refuses (and closes up) on any mismatch."""
        states = self.states()
        if self._trade_up(states) or self._discussion_up(states) or self._leader_up(states):
            closed = self.close_trade_screens()
            if not closed.get("closed"):
                return {"ok": False, "err": "another leader/trade screen is open and could not be closed", **closed}
        chk = self.q(f"""
            local o = Players[{other}]
            if not o or not o:IsAlive() then return {{ok=false, err="no such player"}} end
            if o:IsMinorCiv() then return {{ok=false, err="city-states are not trade-table deals; use minor_gold_gift"}} end
            if o:IsHuman() then return {{ok=false, err="human recipients are not supported by propose_deal yet (PvP deal screen)"}} end
            if not Teams[Players[{pid}]:GetTeam()]:IsHasMet(o:GetTeam()) then return {{ok=false, err="have not met this player"}} end
            local pending = UI.HasMadeProposal({pid})
            if pending ~= -1 and pending ~= {other} then return {{ok=false, err="a proposal to another player is already outstanding", pending_to=pending}} end
            return {{ok=true}}""")
        if not chk.get("ok"):
            return chk
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
        if disabled == "true":
            self.close_trade_screens()
            return {"ok": False, "err": "this leader will not trade right now (Trade button disabled)", "leader_says": speech}
        self.c.exec("LeaderHeadRoot", "OnTrade()", check=False)
        if not self._wait_until(self._trade_up, 6.0):
            self.close_trade_screens()
            return {"ok": False, "err": "trade table did not open", "leader_says": speech}
        time.sleep(0.3)
        table = self.incoming_deal(pid)
        if table.get("to") != other and table.get("from") != other:
            self.close_trade_screens()
            return {"ok": False, "err": "trade table is with a different player", "table": table}
        if table.get("n"):
            # The AI already had a deal loaded (e.g. an offer it made to us earlier). Never build on it.
            self.close_trade_screens()
            return {"ok": False, "err": "the trade table already holds a deal with this player; answer it with accept_deal/refuse_deal first", "table": table}
        return {"ok": True, "leader_says": self._trade_text()}

    def _check_deal_items(self, other: int, items: list[dict], pid: int) -> dict:
        """Legality before any screen opens, with the same IsPossibleToTradeItem checks the UI uses to grey
        out pocket entries (trade_catalog), so the caller learns WHY instead of "it silently did not land"."""
        catalog = self.trade_catalog(other, pid)
        if not catalog.get("ok"):
            return catalog
        cat_res = {r["resource"]: r for r in catalog.get("resources", [])}
        for it in items:
            t = it.get("type")
            if t not in self._DEAL_ITEM_TYPES:
                return {"ok": False, "err": f"unsupported item type {t!r}; supported: {list(self._DEAL_ITEM_TYPES)}"}
            side = "us" if it.get("from_us", True) else "them"
            if t == "RESOURCES":
                r = it.get("resource", "")
                r = r if r.startswith("RESOURCE_") else "RESOURCE_" + r
                entry = cat_res.get(r)
                if not entry or not entry.get(side):
                    who = "I" if side == "us" else "they"
                    return {"ok": False, "err": f"{r} cannot be traded from {'me' if side == 'us' else 'them'} to this player right now "
                                                f"(the receiving side already has it, or {who} have no spare copy of it)",
                            "tradeable_resources": [{"resource": k, "from_me": v.get("us"), "from_them": v.get("them")} for k, v in cat_res.items()]}
            elif t != "CITIES":
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
        for it in items:
            t = it.get("type")
            from_us = bool(it.get("from_us", True))
            is_us = 1 if from_us else 0
            who = pid if from_us else other
            amount = it.get("amount")
            if t == "GOLD":
                code = f"PocketGoldHandler({is_us})"
                if amount is not None:
                    code += f"; UI.GetScratchDeal():ChangeGoldTrade({who}, {int(amount)}); DisplayDeal()"
            elif t == "GOLD_PER_TURN":
                code = f"PocketGoldPerTurnHandler({is_us})"
                if amount is not None:
                    code += f"; UI.GetScratchDeal():ChangeGoldPerTurnTrade({who}, {int(amount)}, {dur}); DisplayDeal()"
            elif t == "RESOURCES":
                r = it.get("resource", "")
                if not r.startswith("RESOURCE_"):
                    r = "RESOURCE_" + r
                code = f"local rid = GameInfoTypes[{lua_str(r)}]; if not rid then error('unknown resource {r}') end; PocketResourceHandler({is_us}, rid)"
                if amount is not None:
                    code += f"; UI.GetScratchDeal():ChangeResourceTrade({who}, rid, {int(amount)}, {dur}); DisplayDeal()"
            elif t == "CITIES":
                code = f"OnChooseCity({who}, {int(it.get('city_id', -1))})"
            else:
                handler = {"OPEN_BORDERS": "PocketOpenBordersHandler", "DEFENSIVE_PACT": "PocketDefensivePactHandler",
                           "RESEARCH_AGREEMENT": "PocketResearchAgreementHandler", "TRADE_AGREEMENT": "PocketTradeAgreementHandler",
                           "ALLOW_EMBASSY": "PocketAllowEmbassyHandler"}[t]
                code = f"{handler}({is_us})"
            try:
                self.c.exec("DiploTrade", code)
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

    def propose_deal(self, other_player: int, items: list[dict], ask_counter: bool = False, pid: int | None = None) -> dict:
        """Propose a trade to an AI through the game's real trade screen, wait for the answer, close the
        screens and report what actually changed. `items`: list of
          {"type": "RESOURCES", "resource": "RESOURCE_DYE", "from_us": true, "amount": 1}
          {"type": "GOLD", "from_us": false, "amount": 120}   {"type": "GOLD_PER_TURN", "from_us": true, "amount": 5}
          {"type": "OPEN_BORDERS"|"ALLOW_EMBASSY"|"DEFENSIVE_PACT"|"RESEARCH_AGREEMENT"|"TRADE_AGREEMENT", "from_us": bool}
          {"type": "CITIES", "from_us": true, "city_id": 123}
        Returns {ok, accepted, reply, table, effects}. `effects` is measured (gold, gold/turn, happiness,
        deal count, per-resource import/export before vs after), not inferred from the reply text. With
        `ask_counter=True` a rejection is followed by the AI's own "what would make this work" counter
        (`counter.items` / `counter.reply`) so the caller can re-propose without another round trip.
        Nothing is proposed if any item fails to land on the table at the requested amount."""
        pid = self._pid(pid)
        if len(items) == 0:
            return {"ok": False, "err": "no items in deal"}
        legal = self._check_deal_items(other_player, items, pid)
        if not legal.get("ok"):
            return legal
        before = self._deal_snapshot(items, pid)
        opened = self._open_trade_screen(other_player, pid)
        if not opened.get("ok"):
            return opened
        added = self._add_deal_items(other_player, items, pid)
        if not added.get("ok"):
            added["closed"] = self.close_trade_screens().get("closed")
            return added
        baseline = self._trade_text()
        self.c.exec("DiploTrade", "OnPropose()", check=False)
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
        self.c.exec("DiploTrade", call, check=False)
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

    # ------------------------------------------------------------ misc
    def _pid(self, pid: int | None) -> int:
        return self.seat if pid is None else pid


def _newest_save(candidates: list[str]) -> str:
    """Disambiguate save-file candidates that share a display basename (e.g. the native F5 hotkey's
    `Saves/single/QuickSave.Civ5Save` vs. `quick_save()`'s own `Saves/single/quick/QuickSave.Civ5Save` --
    two genuinely different files that both display as "QuickSave") by real filesystem mtime instead of
    trusting `UI.SaveFileList()`'s return order, which picked the stale one live (see `load_save`'s
    docstring). The raw path is a real Linux path with backslash separators (Windows-port quirk), so this
    swaps them and stats directly. Falls back to the first candidate if none can be stat'd (e.g. a
    permissions issue) rather than hard-failing -- matches the old behavior in that case."""
    if len(candidates) == 1:
        return candidates[0]

    def mtime(p: str) -> float:
        try:
            return pathlib.Path(p.replace("\\", "/")).stat().st_mtime
        except OSError:
            return -1.0

    best = max(candidates, key=mtime)
    return best if mtime(best) >= 0 else candidates[0]


_ORDER_ITEM_PREFIX = {
    "ORDER_TRAIN": "UNIT_", "ORDER_CONSTRUCT": "BUILDING_",
    "ORDER_CREATE": "PROJECT_", "ORDER_MAINTAIN": "PROCESS_",
}


def _check_order_item(order: str, item: str) -> dict | None:
    """`order` and `item` must belong to the same GameInfo table (Units/Buildings/Projects/Processes) --
    `GameInfoTypes` is a single flat id-space across EVERY table in the game database, so a mismatched pair
    (e.g. order=ORDER_CREATE with a BUILDING_* item) still resolves to a real, valid-looking id -- just in
    the WRONG table. Passing that id into a Projects-table call (GetProjectPurchaseCost, CanCreate, ...)
    when it's actually a Buildings-table id indexes out of bounds natively: confirmed live (2026-09-16),
    `purchase_cost(8192, "ORDER_CREATE", "BUILDING_SISTINE_CHAPEL")` (a real testing mistake -- wonders are
    BUILDING_* items built via ORDER_CONSTRUCT, not ORDER_CREATE) crashed the game process outright. Checked
    by plain string prefix (this game's own UNIT_/BUILDING_/PROJECT_/PROCESS_ naming convention -- the same
    one mcp_server.py's set_production wrapper already uses to *derive* order from item) rather than a live
    GameInfo lookup, so this is a zero-cost check before ever touching the engine. Returns None when the
    pair is consistent, or an {ok:false, err:...} dict ready to return directly otherwise."""
    expected = _ORDER_ITEM_PREFIX.get(order)
    if expected is None:
        return {"ok": False, "err": f"unknown order {order!r}"}
    if not item.startswith(expected):
        return {"ok": False, "err": f"item {item!r} does not match order {order!r} (expected a {expected}* item)"}
    return None


def lua_str(s: str) -> str:
    """Encode a Python str as a Lua double-quoted literal (safe for any bytes, incl. NUL and control chars)."""
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch == '"': out.append('\\"')
        elif ch == "\\": out.append("\\\\")
        elif ch == "\n": out.append("\\n")
        elif ch == "\r": out.append("\\r")
        elif ch == "\t": out.append("\\t")
        elif o < 32 or o == 127: out.append("\\%03d" % o)
        else: out.append(ch)
    out.append('"')
    return "".join(out)


def _lua_value(v: Any) -> str:
    if isinstance(v, bool): return "true" if v else "false"
    if isinstance(v, (int, float)): return repr(v)
    if isinstance(v, str): return lua_str(v)
    if isinstance(v, dict): return _lua_table(v)
    raise TypeError(f"cannot encode {v!r} as a Lua value")


def _lua_table(d: dict) -> str:
    return "{" + ", ".join(f"{k}={_lua_value(v)}" for k, v in d.items()) + "}"


def _lua_items(items: list[dict]) -> str:
    """Encode a list of flat dicts (string keys, str/int/float/bool values) as a Lua array-of-tables
    literal, for calls like H.propose_deal that take a structured item list rather than scalar args."""
    return "{" + ", ".join(_lua_table(item) for item in items) + "}"
