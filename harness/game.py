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
import pathlib
import re
import time
from dataclasses import dataclass, field
from typing import Any

from .client import Civ5, TunerdError, TunerConnectionLost

RUNTIME_LUA = pathlib.Path(__file__).with_name("lua") / "runtime.lua"
RUNTIME_VERSION = int(re.search(r"RUNTIME_VERSION = (\d+)", RUNTIME_LUA.read_text()).group(1))


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
            out = self.c.exec("InGame", f"print(type(H) == 'table' and H.version == {RUNTIME_VERSION} and type(H.turn_state) == 'function')")
            if out and out[0] == "true":
                self._runtime_ok = True
                return
        src = RUNTIME_LUA.read_text()
        if force:
            src = "if H then H.version = -1 end\n" + src   # force re-definition but keep recorded events
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
                 launch: bool = False) -> dict:
        """From the main menu: Multiplayer > LAN > Host > Setup > Staging room. Slots in `open_seats` are set
        SS_OPEN for joiners (the rest stay AI). Returns staging_status(). Launch later with launch_game()
        once everyone is connected (or pass launch=True to launch immediately)."""
        c = self.c
        self._select_mp("lan")
        lobby = c.wait_state("Lobby", 15)
        c.exec(lobby, "HostButtonClick()")
        setup = c.wait_state("MPGameSetupScreen", 10)
        c.exec(setup, f'Controls.NameBox:SetText({lua_str(game_name)})')
        c.exec(setup, "OnStart()")
        stg = c.wait_state("StagingRoom", 30)
        for seat in open_seats or []:
            c.exec(stg, f"PreGame.SetSlotStatus({seat}, SlotStatus.SS_OPEN); PreGame.SetSlotClaim({seat}, SlotClaim.SLOTCLAIM_ASSIGNED)")
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
        return self.q(f"return H.turn_state({self._pid(pid)})")

    def summary(self, pid: int | None = None) -> dict:
        return self.q(f"return H.player_summary({self._pid(pid)})")

    def units(self, pid: int | None = None) -> list[dict]:
        return self.q(f"return H.units({self._pid(pid)})")

    def cities(self, pid: int | None = None) -> list[dict]:
        return self.q(f"return H.cities({self._pid(pid)})")

    def plots_around(self, x: int, y: int, r: int = 3) -> list[dict]:
        return self.q(f"return H.plots_around({x}, {y}, {r})")

    def notifications(self, pid: int | None = None) -> list[dict]:
        return self.q(f"return H.notifications({self._pid(pid)})")

    def diplomacy(self, pid: int | None = None) -> list[dict]:
        return self.q(f"return H.diplomacy({self._pid(pid)})")

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

    def events_since_last(self) -> list[dict]:
        """Recorded game events since the previous call (cursor is kept inside the game's Lua state)."""
        return self.q("return H.take_events()")

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

    def wait_for_my_turn(self, timeout: float = 3600, poll: float = 1.0) -> dict:
        """Block until this seat may act. Hotseat: our seat is active and the hand-off modal is dismissed.
        LAN: our (local) player's turn is active and we have not yet sent turn-complete.

        Polls tunerd's `ping` alongside `turn_state` so a dropped connection surfaces immediately as
        TunerConnectionLost instead of silently spinning on stale-looking turn_state responses until
        `timeout` (the tuner-drop bug documented in docs/NOTES.md: the game's listener only re-arms on
        ExitToMainMenu/leaving the MP staging room, so a drop here will not self-heal)."""
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
    def select_unit(self, unit_id: int, pid: int | None = None) -> None:
        self.lua("InGame", f"local u = Players[{self._pid(pid)}]:GetUnitByID({unit_id}); if u then UI.SelectUnit(u); UI.LookAt(u:GetPlot(), 0) end")

    def move_unit(self, unit_id: int, x: int, y: int, pid: int | None = None, settle_timeout: float = 1.0) -> dict:
        """Issue a move-to for a unit (uses the same path as a right-click).

        `Game.SelectionListMove` only queues pathing -- the unit's x/y read back in the same Lua call
        is whatever it was *before* the engine advances a frame, so an immediate read misreports the
        unit as not having moved even when the move fully succeeds. Poll briefly for GetX/GetY or
        MovesLeft to change before returning, so the reported position/moves are the post-move truth
        (or an honest "hasn't started yet" if the engine really hasn't processed it within the timeout)."""
        self.select_unit(unit_id, pid)
        time.sleep(0.15)
        r = self.q(f"""
            local u = Players[{self._pid(pid)}]:GetUnitByID({unit_id})
            if not u then return {{ok=false, err="no such unit"}} end
            local plot = Map.GetPlot({x}, {y})
            if not plot then return {{ok=false, err="no such plot"}} end
            local x0, y0, m0 = u:GetX(), u:GetY(), u:MovesLeft()
            Game.SelectionListMove(plot, false, false, false)
            return {{ok=true, x=x0, y=y0, moves=m0/GameDefines.MOVE_DENOMINATOR}}""")
        if not r.get("ok"):
            return r
        deadline = time.monotonic() + settle_timeout
        while time.monotonic() < deadline:
            time.sleep(0.15)
            cur = self.q(f"""
                local u = Players[{self._pid(pid)}]:GetUnitByID({unit_id})
                if not u then return {{ok=false, err="no such unit"}} end
                return {{ok=true, x=u:GetX(), y=u:GetY(), moves=u:MovesLeft()/GameDefines.MOVE_DENOMINATOR}}""")
            if not cur.get("ok"):
                return cur
            if (cur["x"], cur["y"]) != (r["x"], r["y"]) or cur["moves"] != r["moves"]:
                return cur
        return r  # engine never advanced within settle_timeout -- report the pre-move reading honestly

    def unit_mission(self, unit_id: int, mission: str, x: int = -1, y: int = -1, data2: int = 0,
                      build: str | None = None, pid: int | None = None) -> dict:
        """Push a mission by name, e.g. MISSION_FOUND, MISSION_FORTIFY, MISSION_SLEEP, MISSION_SKIP,
        MISSION_MOVE_TO (x, y = target tile).

        MISSION_BUILD: pass the improvement via `build=` (e.g. build="BUILD_FARM"), NOT x/y -- the
        underlying Game.SelectionListGameNetMessage(msg, mission, iData1, iData2, iFlags, ...) call
        puts a build mission's BuildTypes id in the iData1 slot, i.e. this wrapper's `x` parameter,
        not `data2`. `x`/`y` are movement-mission-shaped names that don't generalize; `build=` exists
        so a build-type id never has to be smuggled into the wrong slot again (see docs/NOTES.md).
        The build always applies to the unit's own tile.

        Every PUSH_MISSION call returns {ok=true} from the engine regardless of whether the mission
        actually stuck (confirmed live: a wrong-slot build id silently no-ops instead of erroring) --
        for MISSION_BUILD specifically this verifies GetBuildType() actually left -1 before reporting
        success, so a caller doesn't mistake an accepted-but-ignored order for a working one."""
        self.select_unit(unit_id, pid)
        time.sleep(0.15)
        if build is not None:
            r = self.q(f"""
                local m = GameInfoTypes[{lua_str(mission)}]
                if m == nil then return {{ok=false, err="unknown mission"}} end
                local b = GameInfoTypes[{lua_str(build)}]
                if b == nil then return {{ok=false, err="unknown build"}} end
                Game.SelectionListGameNetMessage(GameMessageTypes.GAMEMESSAGE_PUSH_MISSION, m, b, -1, 0, false, false)
                return {{ok=true}}""")
            if not r.get("ok"):
                return r
            time.sleep(0.3)
            chk = self.q(f"""
                local u = Players[{self._pid(pid)}]:GetUnitByID({unit_id})
                if not u then return {{ok=false, err="no such unit"}} end
                return {{ok=true, buildtype=u:GetBuildType()}}""")
            if chk.get("ok") and chk.get("buildtype", -1) == -1:
                return {"ok": False, "err": "mission accepted but did not start a build (bad build type for this tile/unit?)"}
            return r
        return self.q(f"""
            local m = GameInfoTypes[{lua_str(mission)}]
            if m == nil then return {{ok=false, err="unknown mission"}} end
            Game.SelectionListGameNetMessage(GameMessageTypes.GAMEMESSAGE_PUSH_MISSION, m, {x}, {y}, {data2}, false, false)
            return {{ok=true}}""")

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
        sentinel). This turns that into a real error up front instead."""
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
            return {{ok=true, id=id, has_tech=team:IsHasTech(id), current=p:GetCurrentResearch()}}""")
        if not pre.get("ok"):
            return pre
        if pre["has_tech"]:
            return {"ok": False, "err": "already researched"}
        r = self.q(f"""
            local p = Players[{self._pid(pid)}]
            Network.SendResearch({pre['id']}, p:GetNumFreeTechs(), -1, false)
            return {{ok=true}}""")
        if not r.get("ok"):
            return r
        time.sleep(0.3)
        chk = self.q(f"""
            return {{ok=true, current=Players[{self._pid(pid)}]:GetCurrentResearch()}}""")
        if chk.get("ok") and (chk.get("current") == -1 or chk.get("current") == pre["current"]):
            return {"ok": False, "err": "SendResearch accepted but current research did not change (free-tech count mismatch?)"}
        return {"ok": True}

    def end_turn(self) -> dict:
        """Same path as the End Turn button. In network games a second call after turn-complete was sent
        would UN-ready us (Network.SendTurnUnready), so that case is refused here."""
        return self.q("""
            local p = Players[Game.GetActivePlayer()]
            if not p:IsTurnActive() then return {ok=false, err="turn not active"} end
            if Game.IsProcessingMessages() then return {ok=false, err="game is processing messages; retry"} end
            if Game.IsNetworkMultiPlayer() and Network.HasSentNetTurnComplete() then
                return {ok=false, err="turn-complete already sent; waiting for the other players"}
            end
            local blocking = p:GetEndTurnBlockingType()
            Game.DoControl(GameInfoTypes.CONTROL_ENDTURN)
            return {ok=true, blocking_before=blocking, turn_complete_sent=Game.IsNetworkMultiPlayer() and Network.HasSentNetTurnComplete() or false}""")

    def unready_turn(self) -> dict:
        """Network games: take back a sent turn-complete (only works until every player has ended)."""
        return self.q("if Network.HasSentNetTurnComplete() then return {ok=Network.SendTurnUnready()} end return {ok=false, err='turn-complete not sent'}")

    # ------------------------------------------------------------ more actions (added after a live crash
    # from an unguarded raw lua() probe for city_ranged_attack -- these follow the game's own validated
    # call paths, see docs/NOTES.md for the Lua source each one is derived from)
    def city_ranged_attack(self, city_id: int, x: int, y: int, pid: int | None = None) -> dict:
        """Ranged attack from a city with a garrison/defensive building that supports it."""
        return self.q(f"return H.city_ranged_attack({city_id}, {x}, {y}, {self._pid(pid)})")

    def choose_promotion(self, unit_id: int, promotion: str, pid: int | None = None) -> dict:
        """Pick a promotion for a unit with ENDTURN_BLOCKING_UNIT_PROMOTION, e.g. PROMOTION_SHOCK_1."""
        return self.q(f"return H.choose_promotion({unit_id}, {lua_str(promotion)}, {self._pid(pid)})")

    def choose_policy(self, policy: str, pid: int | None = None) -> dict:
        """Adopt a social policy within an already-unlocked branch, e.g. POLICY_TRADITION."""
        return self.q(f"return H.choose_policy({lua_str(policy)}, {self._pid(pid)})")

    def unlock_policy_branch(self, branch: str, pid: int | None = None) -> dict:
        """Unlock a policy branch/tree, e.g. POLICY_BRANCH_TRADITION."""
        return self.q(f"return H.unlock_policy_branch({lua_str(branch)}, {self._pid(pid)})")

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
        """Send a caravan/cargo ship to establish a trade route. See available_trade_routes for valid destinations/types."""
        return self.q(f"return H.establish_trade_route({unit_id}, {dest_x}, {dest_y}, {trade_type}, {self._pid(pid)})")

    def plunder_trade_route(self, unit_id: int, pid: int | None = None) -> dict:
        """Order a military unit to plunder an enemy trade route it's standing on."""
        return self.q(f"return H.plunder_trade_route({unit_id}, {self._pid(pid)})")

    def available_trade_routes(self, pid: int | None = None) -> list[dict]:
        """Valid trade-route destinations and types for my trade units right now."""
        return self.q(f"return H.available_trade_routes({self._pid(pid)})")

    def spies(self, pid: int | None = None) -> dict:
        """Read-only: how many spies I have. Spy missions (move/steal/rig election) are not yet implemented
        -- no MissionTypes.MISSION_*SPY* constant was found in this build's Lua, so writing that action
        needs its own research pass rather than a guess (see docs/NOTES.md)."""
        return self.q(f"return H.spies({self._pid(pid)})")

    def propose_deal(self, other_player: int, items: list[dict], pid: int | None = None) -> dict:
        """** CRASHED THE GAME THREE SEPARATE TIMES ACROSS A DAY OF LIVE TESTING ** -- not exposed as an
        MCP tool or HTTP route for exactly this reason; see docs/NOTES.md "Phase 3a" and its two follow-up
        entries before calling this directly or re-exposing it. Two real bugs were found and fixed along
        the way (runtime.lua v11): a missing `deal:IsPossibleToTradeItem(...)` validation gate (the real UI
        never lets an invalid item reach Add*/DoProposeDeal; this now mirrors that), and
        DECLARATION_OF_FRIENDSHIP being PvP-only in the real UI (now refused outright against an AI, before
        touching the engine). Both fixes are confirmed correct and crash-free live. **But a third live
        crash showed the problem goes deeper**: `deal:AddPeaceTreaty()` crashed the game outright even when
        called with a fully valid, correctly-built deal (both required sides added, exactly matching the
        real UI's own sequence, genuinely at war so the precondition held) -- the crash happened in the
        Add* mutation itself, before SetFromPlayer/SetToPlayer/DoProposeDeal were ever reached. The leading
        theory (not yet disproven) is that these deal-mutation methods need real trade-screen UI state
        (`ContextPtr`) that doesn't exist from a bare tuner exec, the same class of problem as
        `UI.DoProposeDeal()` was originally suspected of. **DO NOT re-expose this as a tool/route** without
        finding a different underlying API (e.g. a lower-level `Network.Send*` equivalent, the pattern that
        worked for `SendFoundPantheon`/`SendFoundReligion`/`SendUpdatePolicies`) -- this call pattern itself
        appears fundamentally unsafe from a bare tuner context, not just under-validated.

        Propose a trade deal (gold/GPT/resources/embassy/open borders/pacts/agreements/friendship/peace/
        cities) to `other_player` -- a human or an AI. Same result either way: an AI accepts or doesn't; a
        human sees it as an incoming offer. Each item in `items` is a dict:
          {"type": "GOLD", "from_us": true, "amount": 100}
          {"type": "GOLD_PER_TURN", "from_us": false, "amount": 5}
          {"type": "RESOURCES", "from_us": true, "resource": "RESOURCE_IRON", "amount": 2}
          {"type": "OPEN_BORDERS" | "DEFENSIVE_PACT" | "RESEARCH_AGREEMENT" | "TRADE_AGREEMENT", "from_us": bool}
          {"type": "ALLOW_EMBASSY" | "DECLARATION_OF_FRIENDSHIP" | "PEACE_TREATY", "from_us": bool}
          {"type": "CITIES", "from_us": bool, "city_id": 123}
        `from_us` picks whether this item flows from me or from them. Not yet supported: vote commitments,
        third-party peace/war (see H.propose_deal in runtime.lua if you need to extend this)."""
        return self.q(f"return H.propose_deal({other_player}, {_lua_items(items)}, {self._pid(pid)})")

    # ------------------------------------------------------------ misc
    def _pid(self, pid: int | None) -> int:
        return self.seat if pid is None else pid


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
