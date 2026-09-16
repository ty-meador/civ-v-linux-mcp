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

import pathlib
import re
import time
from dataclasses import dataclass, field
from typing import Any

from .client import Civ5, TunerdError

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
        return self.staging_status()

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
        build's Lua (from static analysis); only declare_war/make_peace/denounce below were confirmed to
        resolve to real enum ids live -- actually firing one was not tested against a running game."""
        return self.q(f"return H.diplo_event({lua_str(event)}, {other_player}, {data1}, {data2})")

    def declare_war(self, other_player: int) -> dict:
        return self.diplo_event("HUMAN_DECLARES_WAR", other_player)

    def make_peace(self, other_player: int) -> dict:
        """Offer peace to a civ you are at war with (their AI/the other human still has to accept)."""
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
        LAN: our (local) player's turn is active and we have not yet sent turn-complete."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
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

    def move_unit(self, unit_id: int, x: int, y: int, pid: int | None = None) -> dict:
        """Issue a move-to for a unit (uses the same path as a right-click)."""
        self.select_unit(unit_id, pid)
        time.sleep(0.15)
        return self.q(f"""
            local u = Players[{self._pid(pid)}]:GetUnitByID({unit_id})
            if not u then return {{ok=false, err="no such unit"}} end
            local plot = Map.GetPlot({x}, {y})
            if not plot then return {{ok=false, err="no such plot"}} end
            Game.SelectionListMove(plot, false, false, false)
            return {{ok=true, x=u:GetX(), y=u:GetY(), moves=u:MovesLeft()/GameDefines.MOVE_DENOMINATOR}}""")

    def unit_mission(self, unit_id: int, mission: str, x: int = -1, y: int = -1, data2: int = 0, pid: int | None = None) -> dict:
        """Push a mission by name, e.g. MISSION_FOUND, MISSION_FORTIFY, MISSION_SLEEP, MISSION_SKIP, MISSION_BUILD..."""
        self.select_unit(unit_id, pid)
        time.sleep(0.15)
        return self.q(f"""
            local m = GameInfoTypes[{lua_str(mission)}]
            if m == nil then return {{ok=false, err="unknown mission"}} end
            Game.SelectionListGameNetMessage(GameMessageTypes.GAMEMESSAGE_PUSH_MISSION, m, {x}, {y}, {data2}, false, false)
            return {{ok=true}}""")

    def set_production(self, city_id: int, order: str, item: str, pid: int | None = None) -> dict:
        """order: ORDER_TRAIN|ORDER_CONSTRUCT|ORDER_CREATE|ORDER_MAINTAIN; item: UNIT_WARRIOR / BUILDING_MONUMENT / PROJECT_... / PROCESS_..."""
        return self.q(f"""
            local city = Players[{self._pid(pid)}]:GetCityByID({city_id})
            if not city then return {{ok=false, err="no such city"}} end
            local id = GameInfoTypes[{lua_str(item)}]
            if id == nil then return {{ok=false, err="unknown item"}} end
            Game.CityPushOrder(city, OrderTypes.{order}, id, false, true, true)
            return {{ok=true, production=H.L(city:GetProductionNameKey()), turns=city:GetProductionTurnsLeft()}}""")

    def set_research(self, tech: str, pid: int | None = None) -> dict:
        return self.q(f"""
            local id = GameInfoTypes[{lua_str(tech)}]
            if id == nil then return {{ok=false, err="unknown tech"}} end
            Network.SendResearch(id, 0, -1, false)
            return {{ok=true}}""")

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
