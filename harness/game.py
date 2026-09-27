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

import contextlib
import json
import hashlib
import pathlib
import re
import time
from dataclasses import dataclass, field
from typing import Any

from . import runtime_source
from .action_lock import LockBusy
from .client import Civ5, TunerdError, TunerConnectionLost


def _game_busy_error(e: BaseException) -> bool:
    """A tuner failure that means the game is busy, not gone: the state list read empty (the LSQ answer did
    not come in time) or a command ran past its timeout. Read by the wait loop, which polls on."""
    s = str(e)
    return "have []" in s or "timeout waiting for completion" in s or "no Lua state named" in s
from .tuner import TunerClient

LUA_DIR = pathlib.Path(__file__).with_name("lua")
POPUP_SHIM_LUA = LUA_DIR / "generic_popup_shim.lua"
# The runtime's source is harness/lua/runtime/*.lua, assembled by harness/runtime_source.py (GitLab #42). These
# two are the values at import; ensure_runtime takes its own snapshot so the digest it checks and the text it
# injects always come from the same read.
_SOURCE = runtime_source.snapshot()
RUNTIME_VERSION = _SOURCE.version
RUNTIME_DIGEST = _SOURCE.digest


@dataclass
class Game:
    sock_path: str | None = None
    c: Civ5 = field(init=False)
    seat: int = 0                       # player id the LLM controls (LAN: detect_seat() = the local player)
    _runtime_ok: bool = field(default=False, init=False)
    _last_event_seq: int = field(default=0, init=False)
    _mode: str | None = field(default=None, init=False)
    # A context-manager factory taken around each operation of the wait loops (one poll, the end-turn,
    # the digest), released while they sleep. The MCP server sets its per-socket action_lock here;
    # the CLI, the HTTP server and tests run unlocked.
    lock = contextlib.nullcontext
    # `claim(turn, tool, force) -> dict`, raising turn_claim.ClaimRefused when another client of this seat
    # owns the turn (GitLab #41). The MCP server sets the per-socket, per-seat file claim here; the CLI,
    # the HTTP server and tests leave it None, and the turn is nobody's to contest.
    claim = None

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
        """Run `code` (must `return` a value) in InGame and get JSON back.

        A body that would not fit inline is shipped in string chunks first: the tuner truncates a
        command at TunerClient.COMMAND_MAX and the game then reports a bare "Syntax Error" quoting
        the cut-off source (live t319, purchase_cost's body plus the query wrapper; again at t193,
        where two lines added to set_production's puppet guard took the wrapped command from 2003
        bytes to 2093). The budget counts the wrapper query() puts around the body, because that is
        what the tuner measures -- a flat body limit is only ever right by luck. The per-call global
        name keeps two clients from interleaving."""
        self.ensure_runtime()
        if self.q_fits_inline(code):
            return self.c.query("InGame", code, timeout=timeout)
        self._q_seq += 1
        var = f"__H_Q{self._q_seq}_{id(self) % 100000}"
        self.c.exec("InGame", f"{var} = ''")
        for cmd in self.append_commands(var, code):
            self.c.exec("InGame", cmd)
        return self.c.query("InGame", f"local src = {var}; {var} = nil; "
                                      f"local f, err = loadstring(src, 'q'); if not f then error(err, 0) end; return f()",
                            timeout=timeout)

    # Headroom under the tuner's command limit for the `CMD:<state>:` framing execute() adds and the
    # trailing NUL, and for a body whose formatted length we measure after substitution.
    Q_MARGIN = 64
    _q_seq = 0

    @classmethod
    def q_inline_max(cls) -> int:
        """Largest *ASCII* body that still fits inline: a character estimate for source-level checks.
        The live decision is `q_fits_inline`, which measures encoded bytes."""
        return TunerClient.COMMAND_MAX - TunerClient.query_overhead() - cls.Q_MARGIN

    @classmethod
    def command_budget(cls) -> int:
        """Bytes one tuner command may carry after framing, under COMMAND_MAX with Q_MARGIN to spare."""
        return TunerClient.COMMAND_MAX - cls.Q_MARGIN

    @classmethod
    def q_fits_inline(cls, code: str) -> bool:
        """Whether the *encoded* wrapped query stays under the tuner's limit.

        `len(code)` counts characters; the tuner counts bytes after UTF-8 encoding. A body of 1000
        CJK characters is 3000 bytes and used to go inline on the strength of its character count,
        so the tuner cut it and the game answered a bare "Syntax Error" (GAPS §0 / GitLab #3)."""
        wrapped = TunerClient._wrap_query(TunerClient, code)
        return len(wrapped.encode("utf-8")) <= cls.command_budget()

    @classmethod
    def string_chunks(cls, src: str, prefix: str) -> list[str]:
        """Cut `src` so that `prefix .. lua_str(piece)` fits one tuner command *after* escaping.

        Escaping is what used to break the fixed 1500-character cut: 1500 backslashes escape to
        3000 bytes, and 1500 CJK characters encode to 4500. The cut is made on the escaped byte
        count of each character (`lua_str_len`), never on characters."""
        room = cls.command_budget() - len(prefix.encode("utf-8")) - 2   # the two quotes
        if room < 4:
            raise ValueError(f"no room for a string chunk under prefix {prefix!r}")
        pieces, start, used = [], 0, 0
        for i, ch in enumerate(src):
            n = lua_str_len(ch)
            if used + n > room:
                pieces.append(src[start:i])
                start, used = i, 0
            used += n
        if start < len(src) or not pieces:
            pieces.append(src[start:])
        return pieces

    @classmethod
    def append_commands(cls, var: str, src: str) -> list[str]:
        """The `{var} = {var} .. "..."` commands that ship `src` into the Lua global `var`, each one
        under `command_budget()` bytes once encoded."""
        prefix = f"{var} = {var} .. "
        return [prefix + lua_str(piece) for piece in cls.string_chunks(src, prefix)]

    def _order(self, code: str, tries: int = 6, delay: float = 0.2):
        """Run a unit order that goes through the selection list (harness/lua/runtime/helpers.lua net_unit_message).

        The Lua side selects the unit and, when the selection has not landed yet in the same call,
        answers `select_pending`; re-issue the identical call once the engine has had a frame."""
        r = self.q(code)
        n = 0
        while isinstance(r, dict) and r.get("select_pending") and n < tries:
            n += 1
            time.sleep(delay)
            r = self.q(code)
        if isinstance(r, dict) and r.get("select_pending"):
            r = dict(r, err="could not select the unit for the order (UI.GetHeadSelectedUnit never became it)")
        return r

    # The tuner truncates a command at COMMAND_MAX bytes, so big sources are shipped in escaped
    # string chunks into a global and compiled with loadstring(). See `string_chunks`.

    def ship_string(self, state: int | str, src: str) -> str:
        """Put `src` into a fresh global of `state`, in escaped byte-budgeted pieces; returns the global's name.
        The caller consumes and clears it (load_lua, the runtime installer)."""
        # A per-load global: two processes reloading a bumped runtime at once (live t394, et.sh's wait loop and
        # a direct call) shared __H_SRC -- one reset it mid-way and the other's append failed on a nil global.
        # The counter keeps two strings of one load apart (the runtime text and its installer).
        import os
        self._ship_seq = getattr(self, "_ship_seq", 0) + 1
        var = f"__H_SRC_{os.getpid()}_{id(self) % 100000}_{self._ship_seq}"
        self.c.exec(state, f"{var} = ''")
        for cmd in self.append_commands(var, src):
            self.c.exec(state, cmd)
        return var

    def load_lua(self, state: int | str, src: str, name: str = "chunk") -> None:
        var = self.ship_string(state, src)
        self.c.exec(state, f"local f, err = loadstring({var}, {lua_str(name)}); {var} = nil; "
                           f"if not f then error(err, 0) end; f()", timeout=30)

    def ensure_runtime(self, force: bool = False) -> None:
        if self._runtime_ok and not force:
            return
        src = runtime_source.snapshot()
        # A truncated/failed earlier injection leaves a partial H behind with no source_hash: the hash is set
        # by the last line of the chunk, so it is only there when every definition ran. A changed source
        # (any fragment) has another digest and reloads even when RUNTIME_VERSION was not bumped.
        if not force:
            out = self.c.exec("InGame", f"print(type(H) == 'table' and H.source_hash == '{src.digest}' and type(H.turn_state) == 'function')")
            if out and out[0] == "true":
                self._runtime_ok = True
                return
        self._runtime_ok = False   # not current until every chunk has run: a failed force-reload retries
        var = self.ship_string("InGame", src.text)
        self.load_lua("InGame", src.install_lua(var), "harness_runtime_install")   # errors read `events.lua:57:`
        self._runtime_ok = True
        self._popup_shim_ok = False
        self.ensure_popup_shim()

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
                     launch: bool = True, world_size: str | None = None, handicap: str | None = None) -> None:
        """From the main menu: Multiplayer > Hotseat > Setup > Staging room > (launch).
        `world_size` (WORLDSIZE_*) and `handicap` (HANDICAP_*, every human slot) work as in host_lan."""
        c = self.c
        self._select_mp("hotseat")
        setup = c.wait_state("MPGameSetupScreen", 10)
        c.exec(setup, f'Controls.NameBox:SetText({lua_str(game_name)})')
        if world_size:
            c.exec(setup, f"PreGame.SetWorldSize(GameInfo.Worlds[{lua_str(world_size)}].ID)")
        c.exec(setup, "OnStart()")
        stg = c.wait_state("StagingRoom", 30)
        for seat in human_seats:
            if seat == 0:
                continue  # host slot is already human
            c.exec(stg, f"SetSlotToHuman({seat})")
        if handicap:
            c.exec(stg, f"""
                local h = GameInfo.HandicapInfos[{lua_str(handicap)}].ID
                for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
                    if PreGame.GetSlotStatus(i) == SlotStatus.SS_TAKEN then PreGame.SetHandicap(i, h) end
                end""")
        for seat, nick in (nicknames or {}).items():
            c.exec(stg, f"PreGame.SetNickName({seat}, {lua_str(nick)})")
        c.exec(stg, "Network.BroadcastPlayerInfo()")
        if launch:
            c.exec(stg, "LaunchGame()")
        self._save_rejoin("hotseat", human_seats=human_seats, game_name=game_name, nicknames=nicknames)

    def start_single_player(self, civilization: str | None = None, handicap: str | None = None,
                            start: bool = True) -> dict:
        """From the main menu: Single Player > Set Up Game > (start). `civilization` is a CIVILIZATION_* type,
        None = random leader (the setup screen's own -1). `handicap` is a HANDICAP_* type. Map, size, pace and
        victory types stay at the persisted "Play Now" settings; the reply lists them."""
        c = self.c
        c.exec(c.wait_state("MainMenu", 10), "SinglePlayerClick()", check=False)
        c.exec(c.wait_state("SinglePlayer", 15), "SetupGameClicked()", check=False)
        time.sleep(1.0)
        # Front-end contexts all exist from boot, and GameSetupScreen exists three times (single player, mods,
        # scenarios): the one just opened is the one that is not hidden.
        shown = [sid for sid, name in c.states().items() if name == "GameSetupScreen"
                 and c.exec(sid, "print(ContextPtr:IsHidden())", check=False) == ["false"]]
        if len(shown) != 1:
            raise TunerdError(f"expected one visible GameSetupScreen, found {len(shown)}")
        setup = shown[0]
        civ = f"GameInfo.Civilizations[{lua_str(civilization)}].ID" if civilization else "-1"
        c.exec(setup, f"PreGame.SetCivilization(0, {civ})")
        if handicap:
            c.exec(setup, f"PreGame.SetHandicap(0, GameInfo.HandicapInfos[{lua_str(handicap)}].ID)")
        out = c.exec(setup, """
            local v = {}
            for row in GameInfo.Victories() do if PreGame.IsVictory(row.ID) then v[#v + 1] = row.Type end end
            local ms = PreGame.IsRandomMapScript() and "random" or PreGame.GetMapScript()
            local ws = PreGame.IsRandomWorldSize() and "random" or GameInfo.Worlds[PreGame.GetWorldSize()].Type
            print(PreGame.GetCivilization(0), GameInfo.HandicapInfos[PreGame.GetHandicap(0)].Type, ms, ws,
                  GameInfo.GameSpeeds[PreGame.GetGameSpeed()].Type, table.concat(v, ","))""")
        keys = ("civilization_id", "handicap", "map_script", "world_size", "game_speed", "victories")
        settings = dict(zip(keys, out[0].split("\t"))) if out else {}
        if start:
            c.exec(setup, "OnStart()", check=False)
            self.wait_ingame(600)
            self._dismiss_load_screen()
            self.detect_seat()
        return settings

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

    def human_seats(self) -> list[int]:
        """Major civs the engine considers human-controlled, lowest id first."""
        code = ("local n = (GameDefines and GameDefines.MAX_MAJOR_CIVS) or 22 local ids = {} "
                "for i = 0, n - 1 do local p = Players[i] "
                "if p and p:IsAlive() and p:IsHuman() then ids[#ids+1] = i end end "
                "print(table.concat(ids, ','))")
        out = [ln.strip() for ln in self.c.exec("InGame", code) if ln.strip()]
        return [int(t) for t in out[-1].split(",")] if out else []

    def detect_seat(self) -> int:
        """In a network game this instance IS one player: the active player. In hotseat the seat must be given.

        Solo games are the exception: the engine runs the AIs through the same active-player slot, so
        `Game.GetActivePlayer()` mid-turn is whichever AI is thinking (live 2026-09-21: a server that
        resolved while Pacal was moving pinned seat 1 in a game where we are Pocatello at 0, and every
        tool answered "this seat is not active" from then on). A solo game has exactly one human, so
        ask who that is and only fall back to the active player if the scan cannot tell.
        """
        mode = self.mode()
        if mode == "single":
            try:
                humans = self.human_seats()
            except (TunerdError, TimeoutError, OSError, ValueError, IndexError):
                humans = []
            if len(humans) == 1:
                self.seat = humans[0]
                return self.seat
        if mode in ("lan", "internet", "single"):
            self.seat = int(self.c.exec("InGame", "print(Game.GetActivePlayer())")[0])
        return self.seat

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
            trade = ts.pop("trade_state", None)
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

    def summary(self, pid: int | None = None) -> dict:
        r = self.q(f"return H.player_summary({self._pid(pid)})")
        # A slot with no trade unit in it earns nothing and nothing else says so (live t354: Railroad raised
        # the cap 6 -> 7). used counts caravans/cargo ships, idle or not, so free = cap - used.
        if isinstance(r, dict) and isinstance(r.get("trade_routes_available"), int) and isinstance(r.get("trade_routes_used"), int):
            free = r["trade_routes_available"] - r["trade_routes_used"]
            if free > 0:
                r["free_trade_route_slots"] = free
                r["trade_note"] = "build or buy a Caravan / Cargo Ship to fill the free slot(s)"
        # An unassigned spy is the espionage version of the idle caravan above: it costs nothing and
        # earns nothing, and after the notification that announced it the game never mentions it again.
        if isinstance(r, dict) and r.get("idle_spies"):
            r["spy_note"] = ("unassigned spies do nothing: available_spy_cities(agent_id) then "
                             "move_spy to steal tech / rig a city-state election / defend a city")
        return r

    def units(self, pid: int | None = None) -> list[dict]:
        return self.q(f"return H.units({self._pid(pid)})")

    def cities(self, pid: int | None = None) -> list[dict]:
        rows = self.q(f"return H.cities({self._pid(pid)})")
        for c in rows if isinstance(rows, list) else []:
            if isinstance(c, dict):
                self._normalize_production_turns(c)
        return rows

    def city_screen(self, city_id: int, pid: int | None = None) -> dict:
        """City-view contents for one of my cities: buildings, specialists + GP meters, worked tiles,
        production queue, citizen focus, avoid-growth, buyable plots (and the red price of a tile
        this city cannot afford), and the corner meters (food, production, culture-to-border,
        gold/science/faith/tourism). cities() is the banner list."""
        r = self.q(f"return H.city_screen({int(city_id)}, {self._pid(pid)})")
        if isinstance(r, dict):
            self._normalize_production_turns(r)
        return r

    @staticmethod
    def _normalize_production_turns(row: dict) -> dict:
        """INT_MAX turns means empty queue or a process. Only a process is 'never completes'
        (live t179: Goshute's empty queue was labelled as Wealth/Research)."""
        turns = row.get("production_turns")
        if isinstance(turns, int) and turns >= 2**31 - 1:
            row["production_turns"] = None
            prod = (row.get("production") or "").strip()
            if not row.get("production_note") and prod and not row.get("needs_production"):
                row["production_note"] = "ongoing process: converts production every turn, never completes"
        return row

    def great_person_progress(self, pid: int | None = None) -> dict:
        return self.q(f"return H.great_person_progress({self._pid(pid)})")

    def demographics(self, pid: int | None = None) -> dict:
        return self.q(f"return H.demographics({self._pid(pid)})")

    def culture_works(self, pid: int | None = None) -> dict:
        return self.q(f"return H.culture_works({self._pid(pid)})")

    def set_swappable_great_work(self, work_class: str, work_id: int = -1, pid: int | None = None) -> dict:
        """The swap tab's pull-down for one class (writing / art / artifact): put one of our works up for
        swapping, or -1 to clear the spot (Network.SendSetSwappableGreatWork)."""
        return self.q(f"return H.set_swappable_great_work({lua_str(work_class)}, {int(work_id)}, {self._pid(pid)})")

    def swap_great_works(self, their_work_id: int, pid: int | None = None) -> dict:
        """The Swap button: exchange our put-up work of the same class for `their_work_id`, an offer
        listed in culture_works().swap.theirs (Network.SendSwapGreatWorks)."""
        return self.q(f"return H.swap_great_works({int(their_work_id)}, {self._pid(pid)})")

    def domination_progress(self, pid: int | None = None) -> dict:
        return self.q(f"return H.domination_progress({self._pid(pid)})")

    def wonder_overview(self, pid: int | None = None) -> dict:
        return self.q(f"return H.wonder_overview({self._pid(pid)})")

    def espionage_intrigue(self, pid: int | None = None) -> dict:
        return self.q(f"return H.espionage_intrigue({self._pid(pid)})")

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

    def set_auto_specialists(self, city_id: int, automatic: bool, pid: int | None = None) -> dict:
        r = self.q(f"return H.set_auto_specialists({int(city_id)}, {str(bool(automatic)).lower()}, {self._pid(pid)})")
        if r.get("ok"):
            for _ in range(10):
                time.sleep(0.2)
                r["auto_specialists"] = self.city_screen(city_id, pid).get("auto_specialists")
                if r["auto_specialists"] == automatic:
                    break
            r["ok"] = r["auto_specialists"] == automatic
            if not r["ok"]:
                r["err"] = "specialist automation did not change after the city task"
        return r

    def change_specialist(self, city_id: int, building: str, add: bool, pid: int | None = None) -> dict:
        r = self.q(f"return H.change_specialist({int(city_id)}, {lua_str(building)}, {str(bool(add)).lower()}, {self._pid(pid)})")
        if r.get("ok"):
            for _ in range(10):
                time.sleep(0.2)
                sc = self.city_screen(city_id, pid)
                b = next((b for b in sc.get("buildings", []) if b["building"] == r["building"]), {})
                r["assigned"] = b.get("specialist_assigned")
                r["auto_specialists"] = sc.get("auto_specialists")
                if r["assigned"] == r["expected"]:
                    break
            r["ok"] = r["assigned"] == r["expected"] and r["auto_specialists"] is False
            if not r["ok"]:
                r["err"] = "specialist assignment did not match the requested city task"
        return r

    def set_city_focus(self, city_id: int, focus: str, pid: int | None = None) -> dict:
        """Citizen focus: balanced / food / production / gold / science / culture / great_people / faith.
        Same as the city-screen focus buttons (Network.SendSetCityAIFocus)."""
        r = self.q(f"return H.set_city_focus({int(city_id)}, {lua_str(focus)}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        time.sleep(0.2)
        sc = self.city_screen(city_id, pid)
        return {**r, "focus": sc.get("focus"), "food_surplus": sc.get("food_surplus"), "growth": sc.get("growth")}

    def set_avoid_growth(self, city_id: int, avoid: bool, pid: int | None = None) -> dict:
        r = self.q(f"return H.set_avoid_growth({int(city_id)}, {str(bool(avoid)).lower()}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        time.sleep(0.2)
        sc = self.city_screen(city_id, pid)
        return {**r, "avoid_growth": sc.get("avoid_growth")}

    def change_working_plot(self, city_id: int, x: int, y: int, pid: int | None = None) -> dict:
        """Toggle whether this city works plot (x, y). Same as clicking the tile in the city screen."""
        r = self.q(f"return H.change_working_plot({int(city_id)}, {int(x)}, {int(y)}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        time.sleep(0.2)
        sc = self.city_screen(city_id, pid)
        tile = next((p for p in (sc.get("plots") or []) if p.get("x") == x and p.get("y") == y), None)
        return {**r, "worked": bool(tile and tile.get("worked")), "food_surplus": sc.get("food_surplus"),
                "growth": sc.get("growth")}

    def buy_city_plot(self, city_id: int, x: int, y: int, pid: int | None = None) -> dict:
        r = self.q(f"return H.buy_city_plot({int(city_id)}, {int(x)}, {int(y)}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        time.sleep(0.2)
        sc = self.city_screen(city_id, pid)
        tile = next((p for p in (sc.get("plots") or []) if p.get("x") == x and p.get("y") == y), None)
        return {**r, "owned": tile is not None and not tile.get("buyable"), "gold": self.summary(pid).get("gold")}

    def city_task(self, city_id: int, action: str, pid: int | None = None) -> dict:
        """annex / raze / unraze. Puppets can be annexed later; raze burns pop per turn."""
        r = self.q(f"return H.city_task({int(city_id)}, {lua_str(action)}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        time.sleep(0.3)
        sc = self.city_screen(city_id, pid)
        return {**r, "puppet": sc.get("puppet"), "razing": sc.get("razing"), "occupied": sc.get("occupied"),
                "resistance_turns": sc.get("resistance_turns")}

    def sell_building(self, city_id: int, building: str, pid: int | None = None) -> dict:
        """City-screen sell: Network.SendSellBuilding. city_screen marks can_sell + sell_gold."""
        r = self.q(f"return H.sell_building({int(city_id)}, {lua_str(building)}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        for _ in range(12):
            time.sleep(0.2)
            gold = (self.summary(pid) or {}).get("gold")
            sc = self.city_screen(city_id, pid) or {}
            still = any(isinstance(b, dict) and b.get("building") == building for b in sc.get("buildings") or [])
            r["gold"] = gold
            r["still_present"] = still
            if not still:
                r["ok"] = True
                return r
        r["ok"] = False
        r["err"] = "sell was sent but the building is still listed"
        return r

    def plots_around(self, x: int, y: int, r: int = 3) -> list[dict]:
        if not 0 <= r <= 12:
            raise ValueError("radius must be between 0 and 12")
        return self.q(f"return H.plots_around({x}, {y}, {r}, Players[{self.seat}]:GetTeam())")

    def explore_frontier(self, unit_id: int, pid: int | None = None, limit: int = 12) -> dict:
        """Where the known map ends for one unit: revealed, passable plots of its domain (water for a
        ship, land otherwise, both when embarked) that touch unrevealed plots, nearest first. The fog
        edge a human sees on the minimap; nothing beyond it is read."""
        if not 1 <= int(limit) <= 100:
            raise ValueError("limit must be between 1 and 100")
        return self.q(f"return H.explore_frontier({int(unit_id)}, {self._pid(pid)}, {int(limit)})")

    TACTICAL_DETAILS = ("summary", "full")

    def tactical_view(self, unit_id: int, radius: int = 2, detail: str = "summary", pid: int | None = None) -> dict:
        """One bounded read around one unit (#31): its six neighbours by coordinate with what move_unit would do
        there (the same checks move_unit makes; no path cost or turns, which the engine cannot give safely), river
        crossings, visible occupants and known cities within `radius`, fog counts, the unit's attack targets with
        the existing combat previews, and a lettered grid with its legend. detail="full" adds every revealed plot
        in radius as map_window reads it and keeps the previews' modifier rows."""
        if not 1 <= int(radius) <= 5:
            raise ValueError("radius must be between 1 and 5")
        if detail not in self.TACTICAL_DETAILS:
            raise ValueError(f"detail must be one of {self.TACTICAL_DETAILS}")
        return self.q(f"return H.tactical_view({int(unit_id)}, {self._pid(pid)}, {int(radius)}, {lua_str(detail)})")

    def compare(self, kind: str, city_id: int | None = None, unit_id: int | None = None,
                candidates: list[str] | None = None, plots: list[list[int]] | None = None, sort: str | None = None,
                limit: int | None = None, detail: str = "summary", pid: int | None = None) -> dict:
        """A few caller-chosen candidates side by side from one read (#34; harness/compare.py): production items in
        one city, techs, worker builds on plots, or a caravan's trade destinations. Engine answers, table effects,
        estimates and their assumptions are separate fields; every field names its source."""
        from . import compare as C
        err = C.validate(kind, city_id=city_id, unit_id=unit_id, candidates=candidates, plots=plots, sort=sort,
                         limit=limit, detail=detail)
        if err:
            return {"ok": False, "err": err}
        seat = self._pid(pid)
        raw = self.q(C.lua_call(kind, seat, city_id=city_id, unit_id=unit_id, candidates=candidates, plots=plots,
                                detail=detail), timeout=120)
        args = {"pid": seat, "city_id": city_id, "unit_id": unit_id, "candidates": list(candidates or [])}
        return C.shape(kind, raw, args, detail=detail, limit=limit, sort=sort)

    def known_world(self, pid: int | None = None) -> dict:
        """Everything this seat currently knows: own empire/units/cities, met civs
        (including city-states), notifications, and every revealed plot.

        Each plot has vis=true (in sight now) or vis=false (discovered, currently
        fogged). Fogged plots omit units, owners, improvements, cities, and features.
        Unrevealed tiles are omitted entirely.
        """
        return self.q(f"return H.known_world({self._pid(pid)})")

    def map_index(self, pid: int | None = None) -> dict:
        """Compact map scan: revealed luxuries/strategics, camps, ruins, met foreign
        cities, visible natural wonders, and in-sight world wonders. Prefer this over
        known_world when you do not need every plot."""
        return self.q(f"return H.map_index({self._pid(pid)})")

    REVEALED_MAP_LAYERS = ("vis", "terrain", "elevation", "river", "owner", "feature", "improvement", "resource", "route")

    def revealed_map(self, layers: list[str] | None = None, x0: int | None = None, y0: int | None = None,
                     x1: int | None = None, y1: int | None = None, pid: int | None = None) -> dict:
        """The revealed map as character grids, one byte per plot per layer (a Huge map after Satellites
        is ~10 KB a layer). `vis` separates plots in sight ('#') from revealed-but-fogged ('~'), whose
        contents are what was last seen and may be stale. Fog rules match describe_plot: a fogged
        feature is the remembered one or '?', improvement/route/owner are the engine's Revealed* values,
        live occupants and pillage marks appear on visible plots only. Legends are built per reply."""
        if layers is not None:
            bad = [l for l in layers if l not in self.REVEALED_MAP_LAYERS]
            if bad:
                return {"ok": False, "err": f"unknown layer(s) {bad}", "layers": list(self.REVEALED_MAP_LAYERS)}
        lua_layers = "nil" if not layers else "{" + ", ".join(lua_str(l) for l in layers) + "}"
        args = ", ".join("nil" if v is None else str(int(v)) for v in (x0, y0, x1, y1))
        return self.q(f"return H.revealed_map({self._pid(pid)}, {lua_layers}, {args})", timeout=120)

    # ------------------------------------------------------------ reference (the rule book)
    def reference(self) -> dict:
        """The static rule book: every help sentence the stock UI shows for units, buildings, techs,
        policies, promotions, beliefs, resources, terrain, improvements, specialists and unit actions,
        read from this game's database (H.reference) once per process and cached -- the words never
        change mid-game. Since v216 no other read repeats them (harness/reference.py)."""
        cached = getattr(self, "_reference", None)
        if cached is None:
            cached = self.q("return H.reference()", timeout=240)
            if not isinstance(cached, dict):
                return {"ok": False, "err": f"unexpected reference reply {cached!r}"}
            if not cached.get("ok"):
                return cached
            self._reference = cached
        return cached

    def reference_markdown(self, section: str | None = None) -> str | dict:
        """The rule book as Markdown, whole or one section; a dict is a refusal (unknown section, or the
        game could not be read). The whole book is also written beside the notebooks for the human."""
        from .reference import SECTIONS, render_markdown
        if section is not None and section not in SECTIONS:
            return {"ok": False, "err": f"unknown reference section {section!r}", "sections": list(SECTIONS)}
        data = self.reference()
        if not data.get("ok"):
            return data
        text = render_markdown(plain_text(data), section)
        if section is None:
            self._save_reference(text)
        return text

    def _save_reference(self, text: str) -> None:
        """A copy for humans at $XDG_DATA_HOME/civ5-harness/reference/<game>.md (same root as the
        notebooks). Best effort: a failed copy never fails the read."""
        if getattr(self, "_reference_saved", False):
            return
        try:
            from .notes import notes_dir, safe_key
            path = notes_dir().parent / "reference" / (safe_key(self.game_key()) + ".md")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            self._reference_saved = True
            self.reference_path = str(path)
        except Exception:  # noqa: BLE001 -- the disk copy is a convenience
            pass

    def notifications(self, pid: int | None = None) -> list[dict]:
        return self.q(f"return H.notifications({self._pid(pid)})")

    def notification_log(self, limit: int = 40, include_dismissed: bool = True,
                         pid: int | None = None) -> dict:
        """The Notification Log popup: everything the gamecore still holds, newest first, dismissed
        entries included. `notifications()` is only the ones the panel is still showing, so anything
        read once and dismissed had nowhere to be read again."""
        r = self.q(f"return H.notification_log({self._pid(pid)}, {int(limit)}, "
                   f"{'true' if include_dismissed else 'false'})")
        return plain_text(r)

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

    def spaceship_status(self, pid: int | None = None) -> dict:
        """Space race: Apollo done, each part's needed / in-ship / built-not-delivered count and prerequisite tech,
        and met rivals that finished Apollo with their part count (the Victory Progress screen)."""
        return self.q(f"return H.spaceship_status({self._pid(pid)})")

    def culture_overview(self, pid: int | None = None) -> dict:
        """Culture Overview screen: per met major civ, influential_on/needed for a culture victory, tourism, and
        its influence level/percent/tourism-per-turn/trend on each other major (unmet ones as "unknown")."""
        return self.q(f"return H.culture_overview({self._pid(pid)})")

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
        try:
            hist = self.relationship(other_player, pid).get("history") or []
            if hist:
                out["reply"] = hist[-1].get("text")
        except TunerdError:
            pass
        # The answer is spoken on a leader screen that then drops back to the Discuss menu (our own asks, not
        # a question for us -- live t345 America); close it or every later action reads "decision pending".
        if self.discussion_pending():
            out["screen_closed"] = bool(self.dismiss_discussion().get("ok"))
        return out

    def turn_digest(self) -> dict:
        """events_since_last plus the notifications panel, without the panel entries the events already
        carry (live t320: all ten notifications came twice, ~5 KB) and with the game's text markup removed."""
        events = self.events_since_last()
        seen = {e["data"].get("text") for e in events if e.get("kind") == "notification" and isinstance(e.get("data"), dict)}
        notes = [n for n in self.notifications() if n.get("text") not in seen]
        if notes:
            # The panel keeps a notification live for about a turn, so one delivered as an event by the previous
            # digest came back here (live t343: "Washington has made peace with Gandhi!" twice across two
            # digests). Drop any the event log already delivered; keep the ones it never saw (pre-reload).
            try:
                delivered = set(self.q(f"""local t = {{}}
                    for _, e in ipairs(H.events) do
                      if e.kind == "notification" and e.audience == {self.seat} and e.data and e.data.text then t[#t + 1] = e.data.text end
                    end
                    return t""") or [])
                notes = [n for n in notes if n.get("text") not in delivered]
            except (TunerdError, TypeError):
                pass
        # "Shanghai has been converted to another religion!" never says which (live t332: Catholicism;
        # t179 Machu was a follower tie so cities().religion was nil). Lua attach_conversion_banner
        # fills the city-banner tooltip at record time; this is the fallback for events recorded
        # before that hook.
        conv = [e["data"] for e in events if e.get("kind") == "notification" and isinstance(e.get("data"), dict)
                and any(k in str(e["data"].get("text", "")) for k in ("converted to another religion", "has adopted a religion"))]
        if conv:
            try:
                for d in conv:
                    if d.get("religions") is not None:
                        continue
                    banner = self.q(
                        f"local d = {{text = {lua_str(d.get('text') or '')}, player = {self.seat}}}; "
                        f"H.attach_conversion_banner(d, Players[{self.seat}]); return d")
                    if isinstance(banner, dict):
                        for k in ("city_id", "x", "y", "religion", "majority", "religions", "note"):
                            if k in banner:
                                d[k] = banner[k]
            except TunerdError:
                pass
        # "Steal Technology" names the victim civ but not which tech (live t181: Inca / Sailing).
        steal_notes = [e["data"] for e in events if e.get("kind") == "notification" and isinstance(e.get("data"), dict)
                       and ("steal a technology" in str(e["data"].get("text", "")).lower()
                            or "Steal Technology" in str(e["data"].get("summary", "")))]
        if steal_notes:
            try:
                for d in steal_notes:
                    if d.get("steal_tech") is not None:
                        continue
                    attached = self.q(
                        f"local d = {{text = {lua_str(d.get('text') or '')}, summary = {lua_str(d.get('summary') or '')}, "
                        f"player = {self.seat}}}; H.attach_steal_tech(d, Players[{self.seat}]); return d")
                    if isinstance(attached, dict):
                        for k in ("steal_tech", "hint"):
                            if k in attached:
                                d[k] = attached[k]
            except TunerdError:
                pass
        return plain_text({"events": events, "notifications": notes})

    def events_since_last(self) -> list[dict]:
        """Recorded game events since the previous call (cursor is kept inside the game's Lua state).

        `unit_destroyed` comes from SerialEventUnitDestroyed, which is a *graphics* event: it also fires
        when the engine merely rebuilds a unit's model -- every unit on an era change (live, t244: all four
        workers "destroyed" on reaching the Industrial era), a caravan starting a route, a unit being
        upgraded. So each of my own `unit_destroyed` events is checked against the live unit list here and
        relabelled `unit_graphics_reset` when the unit still exists, so a caller never mourns a live
        worker. Genuine losses keep `unit_destroyed`."""
        return self._refine_events(self.q(f"return H.take_events({self.seat})"))

    def _refine_events(self, events: list[dict]) -> list[dict]:
        """The digest's corrections to raw runtime events, shared by turn_digest and the briefing."""
        events = list(events or [])
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
        return self._narrate_combat(events)

    def _narrate_combat(self, events: list[dict]) -> list[dict]:
        """Give every `combat` event a one-line `summary` ("your SCOUT (12,8) was hit by Barbarians WARRIOR
        from (13,8): -38 hp, 62 left") built from the attacker/defender rows the Lua hook captured, and
        drop the `unit_hurt` / `unit_lost` fallback rows (hp compared across the AI phase) for units a
        `combat` event already explains, so only *unexplained* losses remain."""
        def side(s: dict | None, raw_player) -> str:
            s = s or {}
            owner = s.get("owner") or f"player {raw_player}"
            name = f"{'your' if owner == 'you' else owner} {s.get('unit', 'unit (not visible)')}"
            return f"{name} ({s['x']},{s['y']})" if "x" in s else name

        def outcome(s: dict | None, dmg) -> str:
            s = s or {}
            if s.get("killed"):
                return f"-{dmg} hp, killed"
            return f"-{dmg} hp, {s['hp']} left" if "hp" in s else f"-{dmg} hp"

        # A unit of mine that disappears during MY OWN turn without a combat event was spent by my own
        # order (great person used, unit upgraded into a new id, settler founded, disband) -- live t314 the
        # digest read like four losses after one DISCOVER and three upgrades. Only a disappearance during
        # the other players' turns, or one a combat explains, stays `unit_destroyed`.
        markers = [e.get("kind") for e in events if e.get("kind") in ("turn_start", "turn_end")]
        in_my_turn = not markers or markers[0] == "turn_end"
        fought = {d.get(k) for e in events if e.get("kind") == "combat" and isinstance(d := e.get("data"), dict)
                  for k in ("att_unit", "def_unit")}
        # A civilian taken is not a unit killed. The capture notice (Lua attach_capture) names the unit id
        # and tile; the bare `unit_destroyed` row for that id becomes `unit_captured` with the notice's
        # words, and the hp-compare fallback for it is dropped (live 2026-09-24 t217: Bravo's Settler came
        # as three unrelated rows).
        captured = {d.get("unit_id"): d for e in events if e.get("kind") == "notification"
                    and isinstance(d := e.get("data"), dict) and isinstance(d.get("unit_id"), int)
                    and " was captured by " in str(d.get("text", ""))}
        for e in events:
            d = e.get("data")
            if e.get("kind") == "unit_destroyed" and isinstance(d, dict) and d.get("unit") in captured:
                n = captured[d["unit"]]
                e["kind"] = "unit_captured"
                where = f" at ({n['x']},{n['y']})" if "x" in n and "y" in n else ""
                by = str(n.get("text", "")).split(" was captured by ", 1)[1].split("!", 1)[0]
                d["summary"] = f"your {n.get('unit') or d.get('unit_type') or 'unit'}{where} was captured by {by}"
                for k in ("captor", "nearest_revealed_camp", "hint"):
                    if k in n:
                        d[k] = n[k]
                fought.add(d["unit"])
        starts = None
        for e in events:
            if e.get("kind") == "turn_start":
                in_my_turn = True
            elif e.get("kind") == "turn_end":
                in_my_turn = False
            elif (e.get("kind") == "unit_destroyed" and in_my_turn and isinstance(e.get("data"), dict)
                  and e["data"].get("player") == self.seat and e["data"].get("unit") not in fought):
                if starts is None:
                    try:
                        starts = {r.get("unit_id"): r for r in (self.q("return H.route_starts or {}") or [])}
                    except TunerdError:
                        starts = {}
                if e["data"].get("unit") in starts:
                    r = starts[e["data"]["unit"]]
                    e["kind"] = "trade_route_started"
                    e["data"]["summary"] = f"your {r.get('unit')} left on its trade route to {r.get('to')}"
                    continue
                e["kind"] = "unit_spent"
                e["data"]["note"] = "gone during your own turn with no combat: used up, upgraded (new unit id) or disbanded by your order"

        explained: set[int] = set(captured)
        for e in events:
            d = e.get("data")
            if e.get("kind") != "combat" or not isinstance(d, dict):
                continue
            att, dfn = d.get("attacker"), d.get("defender")
            for who, key in ((att, "att_unit"), (dfn, "def_unit")):
                if isinstance(who, dict) and who.get("owner") == "you":
                    explained.add(d.get(key))
            verb = "shot" if isinstance(att, dict) and att.get("ranged") else "attacked"
            d["summary"] = (f"{side(att, d.get('att_player'))} {verb} {side(dfn, d.get('def_player'))}: "
                            f"defender {outcome(dfn, d.get('def_dmg'))}; attacker {outcome(att, d.get('att_dmg'))}")
        # Quick combat (always on in multiplayer) fires no combat sim: the fight arrives as one `damage` row
        # per visible unit, followed by the game's own banner as an `alert` row that says who attacked whom.
        for e in events:
            d = e.get("data")
            if e.get("kind") != "damage" or not isinstance(d, dict):
                continue
            s = d.get("side") or {}
            if s.get("owner") == "you":
                explained.add(d.get("unit_id"))
            d["summary"] = f"{side(s, d.get('player'))} took {d.get('dmg')} damage: {outcome(s, d.get('dmg'))}"
        for e in events:
            d = e.get("data")
            if e.get("kind") == "civ_eliminated" and isinstance(d, dict):
                d["summary"] = (f"{d.get('civ')} ({d.get('leader')}) has been eliminated: its deals, friendships and "
                                f"votes are gone")
        # One disappearance, two rows (live t335: a caravan home from its route came as unit_lost, which explains
        # it, and unit_spent): keep the explained one.
        lost_ids = {e["data"].get("unit_id") for e in events if e.get("kind") == "unit_lost" and isinstance(e.get("data"), dict)}
        out = []
        for e in events:
            d = e.get("data")
            if e.get("kind") == "unit_spent" and isinstance(d, dict) and d.get("unit") in lost_ids:
                continue
            if e.get("kind") == "damage" and isinstance(d, dict) and d.get("unit_id") in fought:
                continue  # animations on: the combat row above already tells it
            if e.get("kind") in ("unit_hurt", "unit_lost") and isinstance(d, dict):
                if d.get("unit_id") in explained:
                    continue
                if e["kind"] == "unit_hurt":
                    d["summary"] = (f"your {d.get('unit')} ({d.get('x')},{d.get('y')}) lost {d.get('hp_before', 0) - d.get('hp', 0)} hp "
                                    f"between turns ({d.get('hp')} left) with no combat seen -- look around it with map_window")
                elif d.get("unit") in ("CARAVAN", "CARGO_SHIP"):
                    # live t324: a route ran out and the caravan came home to its city under a new unit id
                    d["summary"] = (f"your {d.get('unit')} last at ({d.get('x')},{d.get('y')}) is gone with no combat seen: "
                                    f"most likely its trade route ended and it is back home under a new id "
                                    f"(overview.idle_trade_units); a plundered route shows up as a notification")
                else:
                    d["summary"] = (f"your {d.get('unit')} last at ({d.get('x')},{d.get('y')}) is gone "
                                    f"(had {d.get('hp_before')} hp) with no combat seen")
            out.append(e)
        return out

    def events_peek(self, last_n: int = 50) -> list[dict]:
        return self.q(f"local e = H.events; local out = {{}}; for i = math.max(1, #e - {last_n} + 1), #e do out[#out+1] = e[i] end; return out")

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

    def dismiss_discussion(self) -> dict:
        """Leave the current negotiation/demand/trade-offer screen without agreeing to anything -- same
        call discussiondialog.lua's own Back button makes (OnBack(true), forcing past its g_bCanGoBack
        gate). For a trade table that is already open, prefer refuse_deal() (reads terms first).
        Do not use this to accept; see accept_deal(). Also closes the plain LeaderHeadRoot greeting
        (turn_status leader_greeting_pending): live t12, this returned ok while Temujin's greeting stayed
        on screen and kept the end-turn blocker frozen."""
        if not self.discussion_pending() and self.leader_greeting_pending():
            self.dismiss_leader_greeting()
            time.sleep(0.15)
            return {"ok": not self.leader_greeting_pending(), "closed": "greeting"}
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
            deadline = time.monotonic() + 3.0
            after = before
            while time.monotonic() < deadline:
                time.sleep(0.25)
                after = self._deal_snapshot(items, self._pid(pid))
                if after.get("deals") != before.get("deals"):
                    break
            out["accepted_items"] = items
            out["effects"] = self._diff_snapshot(before, after)
            if after.get("deals") == before.get("deals"):
                out["note"] = "deal count unchanged within 3s; the AI may have withdrawn the offer -- check diplomacy/relationship"
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
            return was_connected, ts, ts, False
        return was_connected, ts, None, False

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
        from .turn_claim import ClaimRefused
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
            if v and k not in ("steal_tech_hint", "ongoing"):
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

    # ------------------------------------------------------------ notebook
    def game_key(self) -> str:
        """A name for this game that every save of it shares and no other game does (well enough): leader,
        civ, map script, the capital and the turn it was founded. Cached: it never changes mid-game."""
        if getattr(self, "_game_key", None):
            return self._game_key
        info = self.q(f"""local p = Players[{self.seat}]; local cap = p:GetCapitalCity()
            local ms = PreGame.GetMapScript and PreGame.GetMapScript() or ""
            return {{leader = tostring(p:GetLeaderType()), civ = tostring(p:GetCivilizationType()),
                     map = tostring(ms):match("([^/\\]+)%.lua$") or tostring(ms),
                     cap = cap and cap:GetName() or "", founded = cap and cap:GetGameTurnFounded() or -1,
                     name = PreGame.GetGameName and PreGame.GetGameName() or "", start = Game.GetStartTurn()}}""")
        info = info if isinstance(info, dict) else {}
        parts = [str(info.get("name") or ""), f"L{info.get('leader')}", f"C{info.get('civ')}", str(info.get("map") or ""),
                 str(info.get("cap") or ""), f"t{info.get('founded')}", f"s{info.get('start')}"]
        self._game_key = "-".join(x for x in parts if x)
        return self._game_key

    def notebook(self):
        from .notes import Notebook
        return Notebook(self.game_key(), self.seat)

    # ------------------------------------------------------------ briefing (#30)
    BRIEFING_SINCE = ("previous", "turn")

    def briefing(self, since: str = "previous", limit: int = 8, ts: dict | None = None) -> dict:
        """This seat's turn in one compact read: mandatory decisions (never cut), warnings, opportunities,
        changes since the seat's previous briefing (empire totals, cities, units, events), the board
        (empire, notable cities, units needing a look, visible threats) and, without a comparable baseline,
        the civilization's own rules. Built from turn_state, summary, cities, units and one runtime read
        (H.briefing_board); five tuner trips.

        Events come from the game's event log after the previous briefing's cursor, not from the digest's
        cursor: turn_digest / finish_turn and the briefing each see every event once. since="turn" (or no
        comparable baseline) shows everything after this seat's last turn_end instead -- the recovery read
        after a context reset. The baseline lives beside the notebook, per game and seat, and is replaced by
        every briefing. The caller checks the gate first: this reads the board."""
        from . import briefing as B
        if since not in self.BRIEFING_SINCE:
            return {"ok": False, "err": f"since must be one of {list(self.BRIEFING_SINCE)}, not {since!r}"}
        limit = max(0, min(int(limit), 50))
        ts = ts if isinstance(ts, dict) else self.turn_state()
        nb = self.notebook()
        prev = nb.briefing_baseline()
        turn = ts.get("turn")
        # The comparability of `prev` needs the log head; the cursor it chooses needs the comparability.
        # Decide the cursor from the turn check alone, then confirm the log did not restart underneath it.
        base = B.baseline_state(prev, turn, None)
        since_seq = prev.get("event_seq") if since == "previous" and base.get("comparable") else -1
        if not isinstance(since_seq, int):
            since_seq = -1
        board = self.q(f"return H.briefing_board({self.seat}, {since_seq})") or {}
        base = B.baseline_state(prev, turn, board.get("event_seq"))
        if since_seq != -1 and base.get("events_restarted"):
            board = self.q(f"return H.briefing_board({self.seat}, -1)") or {}
        # Markup off before the composer shortens a line (a cut "[ICON_..." is no longer a tag to strip).
        events = plain_text(self._refine_events(board.get("events") or []))
        base["events_since"] = ("previous briefing" if since_seq != -1 and not base.get("events_restarted")
                                else "this seat's last turn end")
        summary = self.summary()
        cities = self.cities()
        units = self.units()
        out, snap = B.build(ts, summary if isinstance(summary, dict) else {}, cities if isinstance(cities, list) else [],
                            units if isinstance(units, list) else [], board, base, prev, events, limit,
                            include_rules=not base.get("comparable") or since == "turn")
        nb.set_briefing_baseline(snap)
        try:
            section, by_unit = self._assignment_section(nb, limit)
        except Exception as e:  # noqa: BLE001 -- the plan read must never cost the turn's briefing
            section, by_unit = {"error": f"{type(e).__name__}: {e}"}, {}
        if section:
            out["assignments"] = section
            for row in out.get("decisions") or []:
                if row.get("kind") == "unit_orders" and row.get("id") in by_unit:
                    row["assignment"] = by_unit[row["id"]]
        from . import orders as O
        open_orders = nb.orders("open")   # the stored state: no game read
        if open_orders:
            out["orders"] = O.briefing_section(open_orders, limit)
            by_unit_order = {o["unit"]["id"]: o for o in open_orders}
            for row in out.get("decisions") or []:
                o = by_unit_order.get(row.get("id")) if row.get("kind") == "unit_orders" else None
                if o:
                    row["order"] = {"id": o["id"], "status": o["status"],
                                    **({"reason": o["pause"]["reason"]} if o.get("pause") else {})}
        out["ok"] = True
        return plain_text(out)

    # ------------------------------------------------------------ assignments (#33)
    def assignment_facts(self, records: list[dict]) -> dict:
        """One runtime read of everything `records` reference (harness/assignments.py `spec`)."""
        from . import assignments as A
        facts = self.q(f"return H.assignment_facts({self.seat}, {lua_table(A.spec(records))})")
        return facts if isinstance(facts, dict) else {}

    def _reconciled(self, nb, records: list[dict]) -> tuple[list[dict], int | None]:
        """Every record reconciled against one read; what it saw is stored back on the notebook."""
        from . import assignments as A
        if not records:
            return [], None
        facts = self.assignment_facts(records)
        turn = facts.get("turn")
        rows, updates = [], {}
        for a in records:
            row, upd = A.reconcile(a, facts, turn, self.seat)
            rows.append(row)
            if upd:
                updates[a["id"]] = upd
        nb.store_observations(updates)
        return rows, turn

    def _assignment_section(self, nb, limit: int) -> tuple[dict | None, dict]:
        """(the briefing's `assignments`, {unit id: {id, role}} for the decision rows); None without any."""
        from . import assignments as A
        rows, _ = self._reconciled(nb, nb.assignments("active"))
        if not rows:
            return None, {}
        by_unit = {}
        for r in rows:
            for u in r.get("units") or []:
                if not u.get("gone"):
                    by_unit.setdefault(u["id"], {"id": r["id"], "role": r.get("role")})
        return A.briefing_section(rows, limit), by_unit

    def assign(self, role: str, purpose: str, unit_ids=None, city_ids=None, target=None, done_when=None,
               review=None, replace_id: int | None = None) -> dict:
        """Store a structured assignment (harness/assignments.py): who, what for, where, when it is done and
        when to look again. Every unit and city must be mine now; each is fingerprinted (type and creation
        turn, name and founding turn) so a reused id later reads as the assigned one gone. replace_id closes
        that assignment as replaced by this one. Returns the stored record and how it reconciles right now."""
        from . import assignments as A
        try:
            rec = {"role": A.clean_text(role, A.ROLE_MAX, "role", required=True),
                   "purpose": A.clean_text(purpose, A.PURPOSE_MAX, "purpose", required=True)}
            uids, cids = A.normalize_ids(unit_ids, "unit_ids"), A.normalize_ids(city_ids, "city_ids")
            rec["target"] = A.normalize_target(target)
            rec["done_when"] = A.normalize_done(done_when, rec["target"])
            rec["review"] = A.normalize_review(review)
            probe = {**rec, "units": [{"id": i} for i in uids], "cities": [{"id": i} for i in cids]}
            facts = self.assignment_facts([probe])
            rec["units"], rec["cities"] = A.check_new_refs(uids, cids, facts)
        except A.AssignmentError as e:
            return {"ok": False, "err": str(e)}
        if not rec["units"] and not rec["cities"] and not rec["target"]:
            return {"ok": False, "err": "an assignment needs at least one of unit_ids, city_ids or target "
                                        "(a plan with none of them is a note: remember())"}
        turn = facts.get("turn")
        row, upd = A.reconcile({**rec, "id": 0}, facts, turn, self.seat)
        if upd.get("seen"):
            rec["seen"] = upd["seen"]
        nb = self.notebook()
        res = nb.add_assignment(rec, turn if isinstance(turn, int) else -1, replace_id=replace_id)
        if not res.get("ok"):
            return res
        row["id"] = res["assignment"]["id"]
        row["since_turn"] = res["assignment"]["created_turn"]
        out = {"ok": True, "assignment": row}
        if res.get("replaced") is not None:
            out["replaced"] = res["replaced"]
        return out

    AMENDABLE = ("role", "purpose", "unit_ids", "city_ids", "target", "done_when", "review")

    def amend_assignment(self, assignment_id: int, changes: dict, note: str = "") -> dict:
        """Change fields of an active assignment in place (only the keys in `changes`; target={} clears the
        target). New unit / city ids are fingerprinted as in assign. The result carries `previous`."""
        from . import assignments as A
        nb = self.notebook()
        cur = next((a for a in nb.assignments("all") if a.get("id") == assignment_id), None)
        if cur is None or cur.get("status") != "active":
            return nb.update_assignment(assignment_id, {}, -1, "amend")   # the same refusal, with ids / replaced_by
        bad = [k for k in changes if k not in self.AMENDABLE]
        if bad or not changes:
            return {"ok": False, "err": f"amend one or more of {list(self.AMENDABLE)}" + (f"; not {bad}" if bad else "")}
        try:
            new: dict = {}
            if "role" in changes:
                new["role"] = A.clean_text(changes["role"], A.ROLE_MAX, "role", required=True)
            if "purpose" in changes:
                new["purpose"] = A.clean_text(changes["purpose"], A.PURPOSE_MAX, "purpose", required=True)
            if "target" in changes:
                new["target"] = A.normalize_target(changes["target"])
                new["seen"] = None
            target = new.get("target", cur.get("target")) if "target" in changes else cur.get("target")
            if "done_when" in changes:
                new["done_when"] = A.normalize_done(changes["done_when"], target)
            if "review" in changes:
                new["review"] = A.normalize_review(changes["review"])
            uids = A.normalize_ids(changes["unit_ids"], "unit_ids") if "unit_ids" in changes else None
            cids = A.normalize_ids(changes["city_ids"], "city_ids") if "city_ids" in changes else None
            probe = {**cur, **new}
            if uids is not None:
                probe["units"] = [{"id": i} for i in uids]
            if cids is not None:
                probe["cities"] = [{"id": i} for i in cids]
            facts = self.assignment_facts([probe])
            nu, nc = A.check_new_refs(uids or [], cids or [], facts)
            if uids is not None:
                new["units"] = nu
            if cids is not None:
                new["cities"] = nc
        except A.AssignmentError as e:
            return {"ok": False, "err": str(e)}
        merged = {**cur, **new}
        if not merged.get("units") and not merged.get("cities") and not merged.get("target"):
            return {"ok": False, "err": "that would leave no unit, city or target: close_assignment it instead"}
        turn = facts.get("turn")
        row, upd = A.reconcile(merged, facts, turn, self.seat)
        if upd.get("seen") and "target" in changes:
            new["seen"] = upd["seen"]
        what = "amended " + ", ".join(sorted(changes)) + (f": {A.clean_text(note, A.NOTE_MAX, 'note')}" if note else "")
        res = nb.update_assignment(assignment_id, new, turn if isinstance(turn, int) else -1, what)
        if not res.get("ok"):
            return res
        prev = res.get("previous") or {}
        return {"ok": True, "assignment": row, "previous": {k: v for k, v in prev.items() if k != "seen"}}

    def close_assignment(self, assignment_id: int, outcome: str = "completed", note: str = "") -> dict:
        """Close an active assignment as completed or cancelled. No game read beyond the turn number."""
        from . import assignments as A
        if outcome not in A.OUTCOMES:
            return {"ok": False, "err": f"outcome must be one of {list(A.OUTCOMES)}"}
        try:
            note = A.clean_text(note, A.NOTE_MAX, "note")
        except A.AssignmentError as e:
            return {"ok": False, "err": str(e)}
        turn = self.turn_state().get("turn", -1)
        res = self.notebook().update_assignment(assignment_id, {"outcome_note": note} if note else {}, turn,
                                                outcome + (f": {note}" if note else ""), close=outcome)
        if res.get("ok"):
            a = res["assignment"]
            return {"ok": True, "closed": assignment_id, "status": a["status"], "turn": turn,
                    "active": len(self.notebook().assignments("active"))}
        return res

    def assignments(self, status: str = "active") -> dict:
        """Active assignments reconciled against the board now (one read), or the stored closed ones."""
        nb = self.notebook()
        if status not in ("active", "closed", "all"):
            return {"ok": False, "err": "status must be active, closed or all"}
        out: dict = {"ok": True, "game": nb.key}
        if status in ("active", "all"):
            rows, turn = self._reconciled(nb, nb.assignments("active"))
            out["turn"] = turn
            out["active"] = rows
        if status in ("closed", "all"):
            out["closed"] = [{k: a.get(k) for k in ("id", "role", "purpose", "status", "created_turn", "closed_turn",
                                                    "replaced_by", "replaces", "outcome_note") if a.get(k) is not None}
                             for a in nb.assignments("closed")]
        return plain_text(out)

    # ------------------------------------------------------------ conditional orders (#32)
    def order_facts(self, orders: list[dict], extra_builds: list[dict] | None = None) -> dict:
        """One runtime read of what `orders` need (harness/orders.py `spec`)."""
        from . import orders as O
        sp = O.spec(orders)
        if extra_builds:
            sp["builds"] = sp.get("builds", []) + extra_builds
        facts = self.q(f"return H.order_facts({self.seat}, {lua_table(sp)})")
        return facts if isinstance(facts, dict) else {}

    def give_order(self, unit_id: int, steps, interrupt=None, purpose: str = "", replace_id: int | None = None,
                   start: bool = True) -> dict:
        """Store a conditional order for one of my units (harness/orders.py) and, with `start`, run it at once:
        steps are issued one after another through move_unit / unit_mission until one has to wait (walking,
        building, healing, out of moves) or something pauses the order. A first step that could not be issued
        now (an illegal destination, an unknown build, a unit that cannot build there) refuses the order and
        stores nothing. Hostiles already in sight within the interrupt radius are acknowledged: only new ones
        pause it."""
        from . import assignments as A
        from . import orders as O
        try:
            steps = O.normalize_steps(steps)
            intr = O.normalize_interrupt(interrupt)
            purpose = O.clean_purpose(purpose)
            uid = O._int(unit_id, "unit_id")
        except O.OrderError as e:
            return {"ok": False, "err": str(e)}
        probe = {"id": 0, "unit": {"id": uid}, "steps": steps, "step": 0, "interrupt": intr}
        checks = [{"unit_id": uid, "build": s["build"], "x": s.get("x", -1), "y": s.get("y", -1)}
                  for s in steps if s["kind"] == "build"]
        facts = self.order_facts([probe], extra_builds=checks)
        r = (facts.get("units") or {}).get(str(uid)) or {}
        if r.get("missing") or not r.get("type"):
            return {"ok": False, "err": f"unit {uid} is not mine now (units() lists my ids)"}
        unknown = [s["build"] for s in steps if s["kind"] == "build"
                   and ((facts.get("builds") or {}).get(f"{uid}:{s['build']}") or {}).get("known") is False]
        if unknown:
            return {"ok": False, "err": f"not a build in this game: {', '.join(unknown)} (available_unit_actions names "
                                        "the BUILD_* a unit can start)"}
        for s in steps:
            if s["kind"] == "build" and s.get("x") is None:
                s["x"], s["y"] = r["x"], r["y"]   # no move before it: the build is where the unit stands
        probe["unit"] = A.fingerprint_unit(r)
        acked = [O.hostile_key(h) for h in r.get("hostiles") or [] if (h.get("distance") or 99) <= intr["hostile_within"]]
        probe["acked"] = acked
        turn = facts.get("turn")
        if start:
            d = O.decide(probe, facts, turn)
            if d["do"] in ("pause", "fail") and d.get("kind") in ("destination", "enemy_on_destination", "prerequisite",
                                                                   "unknown_build"):
                return {"ok": False, "err": f"step 1 ({O.step_label(steps[0])}) cannot run now: {d['reason']}",
                        **({"hint": d["hint"]} if d.get("hint") else {})}
        rec = {"unit": probe["unit"], "steps": steps, "interrupt": intr, "acked": acked,
               "seen": {"hp": r.get("hp"), "x": r.get("x"), "y": r.get("y")}}
        if purpose:
            rec["purpose"] = purpose
        nb = self.notebook()
        res = nb.add_order(rec, turn if isinstance(turn, int) else -1, replace_id=replace_id)
        if not res.get("ok"):
            return res
        old = res.get("replaced_order")
        if old and old["unit"]["id"] != uid:
            self._release_standing_move(old)
        o = res["order"]
        out: dict = {"ok": True}
        if res.get("replaced") is not None:
            out["replaced"] = res["replaced"]
        if acked:
            out["acknowledged_hostiles"] = [h for h in r.get("hostiles") or [] if O.hostile_key(h) in acked]
        if start:
            o, did = self._run_order(nb, o, "given", facts)
            if did:
                out["did"] = did
        # A unit on automation (a Worker on AUTOMATE_BUILD) keeps it until a move_unit / unit_mission replaces it.
        # An order whose first step could only wait (no moves left this turn, or start=False) issued nothing, and
        # the game's automation then walked the unit away at the next turn start, before the harness ran the
        # order (Grok, Venice/Mongolia 2026-09-27). The order is a claim on the unit: it leaves automation now.
        if not o.get("issued_count") and o.get("status") in O.OPEN and self._stop_automation(uid):
            out["automation_stopped"] = True
        out["order"] = O.row(o)
        return plain_text(out)

    def _stop_automation(self, unit_id: int) -> bool:
        """COMMAND_STOP_AUTOMATION for one of my units the game is automating: True when it was automated and
        the command took, False when it was not automated (nothing sent)."""
        auto = self.q(f"local u = Players[{self._pid(None)}]:GetUnitByID({int(unit_id)}); "
                      "return u ~= nil and u:IsAutomated() or false")
        if auto is not True:
            return False
        r = self.unit_mission(int(unit_id), "COMMAND_STOP_AUTOMATION")
        return bool(isinstance(r, dict) and r.get("ok"))

    def orders(self, status: str = "open") -> dict:
        """My orders as stored (no game read): open (active and paused), closed, or all."""
        from . import orders as O
        if status not in ("open", "closed", "all"):
            return {"ok": False, "err": "status must be open, closed or all"}
        nb = self.notebook()
        rows = [O.row(o) for o in nb.orders(status)]
        return plain_text({"ok": True, "game": nb.key, "orders": rows, "count": len(rows)})

    def resume_order(self, order_id: int) -> dict:
        """Hand a paused order back its unit and run it now (an active one just runs now). The hostiles in sight
        and the unit's hp are taken as seen, so only something new pauses it again; every step is re-checked
        against the board first, so a step completed meanwhile is not issued twice."""
        from . import orders as O
        nb = self.notebook()
        o = next((x for x in nb.orders("all") if x.get("id") == order_id), None)
        if o is None or o.get("status") not in O.OPEN:
            return {"ok": False, "err": f"no open order {order_id}" + (f" (it is {o.get('status')})" if o else ""),
                    "open_ids": [x.get("id") for x in nb.orders("open")]}
        facts = self.order_facts([o])
        u = (facts.get("units") or {}).get(str(o["unit"]["id"])) or {}
        was = o.get("pause")
        turn = facts.get("turn")
        o["status"] = "active"
        o.pop("pause", None)
        o.pop("inflight", None)
        if (was or {}).get("kind") in ("no_progress", "not_started", "turn_went_back", "uncertain", "manual"):
            o.pop("issued", None)
        if isinstance(turn, int) and isinstance(o.get("updated_turn"), int) and turn < o["updated_turn"]:
            o["updated_turn"] = turn
        if not u.get("missing"):
            o["acked"] = sorted(set(o.get("acked") or []) | {O.hostile_key(h) for h in u.get("hostiles") or []})
            o["seen"] = {"hp": u.get("hp"), "x": u.get("x"), "y": u.get("y")}
        o.setdefault("history", []).append({"turn": turn, "what": "resumed" + (f" after {was['kind']}" if was else "")})
        o, did = self._run_order(nb, o, "resumed", facts)
        out = {"ok": True, "order": O.row(o)}
        if did:
            out["did"] = did
        return plain_text(out)

    def cancel_order(self, order_id: int, note: str = "") -> dict:
        """Close an open order as cancelled. The standing move it had issued is dropped too (the unit stops where
        it is next turn); anything else the unit is doing (a build, fortified) is left as it is."""
        from . import orders as O
        try:
            note = O.clean_text(note, O.PURPOSE_MAX, "note")
        except O.OrderError as e:
            return {"ok": False, "err": str(e)}
        nb = self.notebook()
        o = next((x for x in nb.orders("all") if x.get("id") == order_id), None)
        if o is None or o.get("status") not in O.OPEN:
            return {"ok": False, "err": f"no open order {order_id}" + (f" (it is {o.get('status')})" if o else ""),
                    "open_ids": [x.get("id") for x in nb.orders("open")]}
        released = self._release_standing_move(o)
        turn = o.get("updated_turn")
        o.update({"status": "cancelled", "closed_turn": turn})
        o.pop("state", None)
        o.setdefault("history", []).append({"turn": turn, "what": "cancelled" + (f": {note}" if note else "")})
        nb.put_order(o)
        out = {"ok": True, "cancelled": order_id, "open": len(nb.orders("open"))}
        if released:
            out["standing_move_dropped"] = released
        return out

    def note_manual_order(self, unit_id: int, tool: str) -> dict | None:
        """A direct order to a unit an active order owns takes the unit: the order pauses (never fights the
        command), and the answer names it. None when no open order holds the unit."""
        from . import orders as O
        try:
            nb = self.notebook()
            o = next((x for x in nb.orders("active") if x["unit"]["id"] == int(unit_id)), None)
        except (TunerdError, OSError, ValueError, KeyError, TypeError):
            return None
        if o is None:
            return None
        o["status"] = "paused"
        o.pop("state", None)
        o["pause"] = {"kind": "manual", "turn": o.get("updated_turn"),
                      "reason": f"unit {unit_id} was given a direct order ({tool}); that command owns it now",
                      "hint": "resume_order hands the unit back to this order; cancel_order drops the order"}
        o.setdefault("history", []).append({"turn": o.get("updated_turn"), "what": f"paused: direct {tool}"})
        nb.put_order(o)
        return {"id": o["id"], "status": "paused", "reason": o["pause"]["reason"], "hint": o["pause"]["hint"]}

    def run_orders(self, trigger: str = "turn_start") -> list[dict]:
        """Run every active order once (one read for all of them first). The rows say what each did."""
        from . import orders as O
        nb = self.notebook()
        active = nb.orders("active")
        if not active:
            return []
        facts = self.order_facts(active)
        out = []
        for o in active:
            o, did = self._run_order(nb, o, trigger, facts)
            r = O.row(o)
            if did:
                r["did"] = did
            out.append(r)
        return out

    def _release_standing_move(self, o: dict) -> dict | None:
        """Drop the standing move the order's current move step issued (only that one: a destination the unit
        was given some other way is not the order's to clear)."""
        from . import orders as O
        st = O.current(o)
        if not st or st["kind"] != "move":
            return None
        uid = int(o["unit"]["id"])
        try:
            gone = self.q(f"local k = H.pm_key({uid}, {self.seat}) local pm = H.pending_moves[k] "
                          f"if pm and pm.x == {int(st['x'])} and pm.y == {int(st['y'])} then H.pending_moves[k] = nil "
                          f"return true end return false")
        except TunerdError:
            return None
        return {"x": st["x"], "y": st["y"]} if gone is True else None

    def _order_action(self, tool: str, args: dict) -> dict:
        """One step through the ordinary game-command path: the same Game calls the move_unit / unit_mission
        tools make, with their checks and verification."""
        if tool == "move_unit":
            return self.move_unit(int(args["unit_id"]), int(args["x"]), int(args["y"]))
        if tool == "unit_mission":
            r = self.unit_mission(int(args["unit_id"]), args["mission"], build=args.get("build"))
            # A hold means "stay here": the unit panel offers Fortify or Sleep, never both (Sleep is for units that
            # cannot fortify; live t44 a Scout's MISSION_SLEEP was illegal while MISSION_FORTIFY was listed).
            alt = {"MISSION_FORTIFY": "MISSION_SLEEP", "MISSION_SLEEP": "MISSION_FORTIFY"}.get(args["mission"])
            if alt and not r.get("ok") and alt in (r.get("legal_missions") or []):
                r = self.unit_mission(int(args["unit_id"]), alt)
                if r.get("ok"):
                    r["note"] = f"{args['mission']} is not offered to this unit; {alt} holds it instead"
            return r
        return {"ok": False, "err": f"not an order step: {tool}"}

    def _run_order(self, nb, o: dict, trigger: str, facts: dict | None = None) -> tuple[dict, list[str]]:
        """Carry `o` forward as far as it goes now. Every step is decided on a fresh read (the first may be
        handed in), written ahead as `inflight` before it is issued, and its answer recorded as `last`. Stops
        at the first wait, pause, failure or completion; each step is issued at most once per turn."""
        from . import orders as O
        did: list[str] = []
        steps = o.get("steps") or []
        for _ in range(2 * len(steps) + 2):
            if facts is None:
                facts = self.order_facts([o])
            turn = facts.get("turn")
            d = O.decide(o, facts, turn)
            facts = None
            if d.get("seen"):
                o["seen"] = d["seen"]
            if isinstance(turn, int):
                o["updated_turn"] = turn
            kind = d["do"]
            hist = o.setdefault("history", [])
            if kind == "next":
                label = O.step_label(O.current(o))
                o.pop("inflight", None)
                did.append(f"{label}: done")
                hist.append({"turn": turn, "what": f"step {o.get('step', 0) + 1} done: {label}"})
                o["step"] = o.get("step", 0) + 1
                if O.current(o) is None:
                    kind = "complete"
                else:
                    o.pop("state", None)
                    nb.put_order(o)
                    continue
            if kind == "complete":
                o.update({"status": "completed", "closed_turn": turn, "state": "completed"})
                if d.get("note"):
                    o["note"] = d["note"]
                hist.append({"turn": turn, "what": "completed" + (f": {d['note']}" if d.get("note") else "")})
                did.append("order complete" + (f" ({d['note']})" if d.get("note") else ""))
            elif kind == "fail":
                o.update({"status": "failed", "closed_turn": turn, "state": "failed",
                          "pause": {"kind": d.get("kind"), "reason": d["reason"], "turn": turn}})
                hist.append({"turn": turn, "what": f"failed: {d['reason']}"})
                did.append(f"failed: {d['reason']}")
            elif kind == "pause":
                self._release_standing_move(o)
                o.update({"status": "paused", "state": "paused"})
                o["pause"] = {k: d[k] for k in ("kind", "reason", "hint", "hostiles") if d.get(k)}
                o["pause"]["turn"] = turn
                o.pop("inflight", None)
                hist.append({"turn": turn, "what": f"paused ({d.get('kind')}): {d['reason']}"})
                did.append(f"paused: {d['reason']}")
            elif kind == "wait":
                o["state"] = d.get("state")
                o["note"] = d.get("note")
            elif kind == "issue":
                me = (d.get("seen") or {})
                o["inflight"] = {"turn": turn, "step": o.get("step", 0), "what": d["what"], "trigger": trigger}
                nb.put_order(o)   # written ahead: a harness that dies mid-call leaves this for the next run to see
                o["issued"] = {"turn": turn, "step": o.get("step", 0), "x": me.get("x"), "y": me.get("y")}
                try:
                    r = self._order_action(d["tool"], d["args"])
                except TunerdError as e:
                    r = {"ok": False, "err": f"the game connection failed while issuing it: {e}", "uncertain": True}
                o.pop("inflight", None)
                o["issued_count"] = o.get("issued_count", 0) + 1
                last = {"turn": turn, "what": d["what"], "ok": bool(r.get("ok"))}
                for k in ("err", "note", "arrived", "queued", "turns_left", "x", "y"):
                    if r.get(k) is not None:
                        last[k] = r[k]
                o["last"] = last
                if not r.get("ok"):
                    kind = "pause"
                    self._release_standing_move(o)
                    o.update({"status": "paused", "state": "paused"})
                    o["pause"] = {"kind": "uncertain" if r.get("uncertain") else "refused", "turn": turn,
                                  "reason": f"{d['what']} was refused: {r.get('err')}",
                                  "hint": "fix what the refusal names and resume_order, or replace / cancel the order"}
                    hist.append({"turn": turn, "what": f"paused (refused): {r.get('err')}"})
                    did.append(f"{d['what']}: refused ({r.get('err')})")
                else:
                    did.append(f"{d['what']}: issued")
                    hist.append({"turn": turn, "what": f"issued {d['what']}"})
                    if O.current(o)["kind"] == "hold":
                        o["step"] = o.get("step", 0) + 1   # a hold is done once the mission is accepted
                        o.update({"status": "completed", "closed_turn": turn, "state": "completed"})
                        hist.append({"turn": turn, "what": "completed"})
                        did.append("order complete")
                        kind = "complete"
                    else:
                        nb.put_order(o)
                        continue
            if kind in ("pause", "complete", "fail") and not (kind == "complete" and d.get("note")):
                o.pop("note", None)   # the transient wait note goes; a completion's own note stays on the row
            nb.put_order(o)
            return o, did
        o.update({"state": "waiting", "note": "stopped after too many steps in one run; carries on next run"})
        nb.put_order(o)
        return o, did

    def _turn_start_orders(self, ts: dict) -> dict | None:
        """The start of this seat's turn is an order's execution window: claim the turn for this process (another
        client of the seat that holds it keeps its turn, and the orders wait), then run every active order.
        None when there is no open order (no read at all)."""
        from . import orders as O
        try:
            nb = self.notebook()
            open_ = nb.orders("open")
        except (TunerdError, OSError, ValueError):
            return None
        if not open_:
            return None
        active = [o for o in open_ if o.get("status") == "active"]
        out: dict = {"open": len(open_)}
        if active:
            refused = self._claim_turn(ts, "orders")
            if refused is not None:
                out["not_run"] = "another client of this seat holds the turn; the orders run when it is mine to act"
                out["turn_claim"] = refused.get("turn_claim")
            else:
                try:
                    out["rows"] = self.run_orders("turn_start")
                except TunerdError as e:
                    out["error"] = f"orders not run: {e}"
        ran = {r["id"] for r in out.get("rows") or []}
        out.setdefault("rows", [])
        out["rows"] += [O.row(o) for o in open_ if o.get("id") not in ran]
        out["paused"] = sum(1 for r in out["rows"] if r.get("status") == "paused")
        return out

    def net_players(self) -> list[dict]:
        """Network games: human players with connected / turn-active / ended-turn flags."""
        return self.q(f"return H.net_players({self.seat})")

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
        """move-to; when a visible enemy stands on the destination the move is a melee attack, and the
        result carries `attack`: both sides' hp before/after and who died (the unit's x/y do not change
        on an attack unless it kills and advances, so a bare move result read like nothing happened --
        live 2026-09-18)."""
        return self._with_attack_result(
            unit_id, x, y, lambda: self._move_unit(unit_id, x, y, pid, settle_timeout), pid)

    def _with_attack_result(self, unit_id: int, x: int, y: int, act, pid: int | None = None) -> dict:
        """Run `act()` and, when a visible enemy stands on (x, y), attach `attack`: both sides' hp
        before/after and who died.

        Shared by move_unit (a melee attack is a right-click onto the enemy) and unit_mission's
        move-shaped missions -- an **air strike is MISSION_MOVE_TO onto the target plot**, and until
        this was shared it returned only the bomber's own x/y/moves. Live t182: a Bomber killed an
        Inca Composite Bowman outright and took 11 damage, and the tool said
        `{"ok":true,"x":50,"y":24,"moves":0}` -- the pilot at the screen watches the damage numbers,
        the LLM had to wait for the next turn_digest to learn it had hit anything."""
        pre = self.q(f"return H.attack_before({unit_id}, {x}, {y}, {self._pid(pid)})")
        air = (pre or {}).get("air") if isinstance(pre, dict) else None
        if isinstance(pre, dict) and pre.get("attack") and air and not air.get("can_strike"):
            # An air unit does not walk toward a target: the engine answers an illegal strike by doing
            # nothing at all, so issuing it returned ok with both sides' hp unchanged. Live t184: a
            # Fighter at (49,19) sent at Cusco (42,23), nine plots away against a range of eight.
            rng = air.get("range")
            return {"ok": False, "err": "this air unit cannot strike that plot right now"
                                        + (f" (its range is {rng})" if rng else "")
                                        + "; available_unit_actions(unit_id).ranged_targets and "
                                          "unit_mission_targets list the plots it can actually reach",
                    "x": x, "y": y, "range": rng}
        seq0 = None
        if isinstance(pre, dict) and pre.get("attack") and air:
            try:
                seq0 = self.q("return H.event_seq")
            except TunerdError:
                seq0 = None
        r = act()
        if isinstance(pre, dict) and pre.get("attack") and r.get("ok"):
            time.sleep(0.3)
            if pre.get("city"):
                post = self.q(f"return H.city_attack_after({unit_id}, {x}, {y}, {self._pid(pid)})")
            else:
                post = self.q(f"return H.attack_after({unit_id}, {pre['def_player']}, {pre['def_unit']}, {self._pid(pid)})")
            r["attack"] = {"defender": pre.get("defender"), "defender_hp_before": pre.get("def_hp"),
                           "my_hp_before": pre.get("my_hp"), **(post if isinstance(post, dict) else {})}
            if air:
                self._attach_interception(r["attack"], seq0, pre, unit_id, x, y, pid)
            dtype = (pre.get("defender") or {}).get("unit")
            if r["attack"].get("defender_killed") and dtype:
                new_id = self.q(f"return H.captured_at({x}, {y}, {lua_str(str(dtype))}, {self._pid(pid)})")
                if isinstance(new_id, int):
                    r["attack"].pop("defender_killed", None)
                    r["attack"]["captured"] = True
                    r["attack"]["captured_unit_id"] = new_id
            # A target two plots away is walked toward first; when the moves run out on the way nobody
            # fought, and unchanged hp on both sides read like a fight both survived (live t327).
            a = r["attack"]
            if r.get("arrived") is False and a.get("def_hp") == a.get("defender_hp_before") and a.get("my_hp") == a.get("my_hp_before"):
                r["attack"] = {"happened": False, "defender": a.get("defender"),
                               "note": "moves ran out before reaching the target: no combat this turn. The standing "
                                       "order is dropped at turn start (an enemy is on the destination); move_unit "
                                       "onto it again next turn to attack"}
        return r

    def _attach_interception(self, a: dict, seq0, pre: dict, unit_id: int, x: int, y: int, pid: int | None = None) -> None:
        """An air strike can be intercepted on the way in. The pilot sees the interceptor fire and the damage
        it did; the result only said my_hp / my_unit_killed, which read as if the strike itself had gone wrong
        (live 2026-09-24: a Bomber lost to an AA gun). The engine's banner for a strike is just "Your Bomber
        bombarded an enemy Infantry! (87 damage)" -- no interception line -- so the interception is read the
        way the stock panel counts it: a visible interceptor that fired is out of interceptions for the turn
        and drops out of GetInterceptorCount (1 before, 0 after, live). The unit the engine would send up is
        named when it was in sight before the strike. When the aircraft died another of ours asks; failing
        that, a dead aircraft beside an untouched target still means it never got to strike. Banner texts
        that do name an interception ("was intercepted by" / "was shot down by") are honoured too."""
        before = pre.get("interception") if isinstance(pre.get("interception"), dict) else {}
        after: dict = {}
        try:
            after = self.q(f"return H.interception_after({unit_id}, {x}, {y}, {pre.get('def_player', -1)}, "
                           f"{pre.get('def_unit', -1)}, {self._pid(pid)})") or {}
        except TunerdError:
            after = {}
        if isinstance(before.get("count"), int):
            a["visible_interceptors_before"] = before["count"]
        fired = (isinstance(before.get("count"), int) and isinstance(after.get("count"), int)
                 and after["count"] < before["count"])
        texts: list = []
        if isinstance(seq0, int):
            try:
                texts = self.q(f"return H.alerts_since({seq0}, {self._pid(pid)})") or []
            except TunerdError:
                texts = []
        hits = [t for t in texts if isinstance(t, str) and ("was intercepted by" in t or "was shot down by" in t)]
        unhurt = (a.get("def_hp") is not None and a.get("def_hp") == a.get("defender_hp_before")
                  and not a.get("defender_killed"))
        killed_on_the_way = bool(a.get("my_unit_killed") and unhurt)
        if not (fired or hits or killed_on_the_way):
            return
        a["intercepted"] = True
        if isinstance(before.get("best"), dict):
            a["interceptor"] = {k: v for k, v in before["best"].items() if k != "player"}
        elif hits:
            m = re.search(r"by an enemy (.+?)!", hits[0])
            if m:
                a["interceptor"] = {"unit": m.group(1)}
        if hits:
            a["interception"] = hits[0] if len(hits) == 1 else hits
        if a.get("my_unit_killed"):
            a["shot_down"] = True
            if unhurt:
                a["note"] = "shot down by an interceptor before it could strike: the target is unhurt"
            else:
                a["note"] = ("intercepted on the way in and destroyed: the interception and the target's air defence "
                             "together used up its hp; the strike still landed (see def_hp)")
        else:
            a["note"] = ("intercepted on the way in and still struck; my_hp includes the interception damage, "
                         "which the preview's expected_damage_taken excluded")

    def _move_unit(self, unit_id: int, x: int, y: int, pid: int | None = None, settle_timeout: float = 1.0) -> dict:
        """Issue a move-to for a unit through the game's network path (selection list +
        GAMEMESSAGE_PUSH_MISSION, see harness/lua/runtime/helpers.lua net_unit_message).

        The order is applied on a later game update -- the unit's x/y read back in the same Lua
        call is still the pre-move plot -- so poll briefly for GetX/GetY or MovesLeft to change
        before returning. If the engine has not advanced within the timeout, report the pre-move
        reading honestly."""
        r = self._order(f"return H.move_unit({unit_id}, {x}, {y}, {self._pid(pid)})")
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
                # Say whether it got there: activity MISSION alone left "moved (24,23)->(24,29), asked for
                # (25,30)" to be worked out by the caller (live t325).
                cur["arrived"] = (cur["x"], cur["y"]) == (x, y)
                if not cur["arrived"]:
                    cur["destination"] = {"x": x, "y": y}
                    if cur.get("activity") == 6:
                        cur["note"] = "still on its way: the order carries on next turn (move_unit again to change it)"
                elif r.get("swap_candidates"):
                    # One of ours stood on the destination: if it is now on the plot we left, the
                    # engine swapped the two (live t252, Workers at Goshute). Say so -- the other
                    # unit moved too, and spent its moves doing it.
                    ids = ", ".join(str(c["id"]) for c in r["swap_candidates"] if isinstance(c, dict) and "id" in c)
                    sw = self.q(f"return H.swapped_unit({{{ids}}}, {r['x']}, {r['y']}, {self._pid(pid)})")
                    if isinstance(sw, dict) and sw.get("unit"):
                        cur["swapped_with"] = sw["unit"]
                        cur["note"] = (f"swapped places with {sw['unit'].get('type')} {sw['unit'].get('id')}, "
                                       f"which is now at ({r['x']},{r['y']}) with {sw['unit'].get('moves')} moves")
                # The loss roster is snapshotted at turn start/end; a unit we moved and then lost during our own
                # turn would otherwise be placed where the turn began (live S1 t267). Refresh it here, cheaply.
                try:
                    self.q(f"local u = Players[{self._pid(pid)}]:GetUnitByID({unit_id}); if u then H.note_unit(u, {self._pid(pid)}) end; return true")
                except TunerdError:
                    pass
                return cur
        # Nothing changed within settle_timeout. A unit with no moves left keeps the order queued for
        # next turn (activity MISSION); otherwise the engine dropped it silently -- no path to that
        # plot (unexplored/impassable terrain in the way, another civ's closed borders, a unit in the
        # way) -- and reporting ok:true here sent callers on with a unit that never moved (live t252).
        if cur.get("ok") and (cur.get("activity") == 6 or (r.get("moves") or 0) <= 0):
            cur["queued"] = True
            # #37: say where it is going; the next turn_status repeats it under todo.ongoing.
            cur["going_to"] = {"x": int(x), "y": int(y)}
            cur["note"] = (cur.get("note") + "; " if cur.get("note") else "") + \
                "standing move: resumes at the start of each of my turns until the unit arrives (todo.ongoing)"
            return cur
        out = {"ok": False, "err": "unit did not move: the engine found no path to that plot (unexplored or impassable "
                                   "terrain in the way, a closed border, or a unit blocking it); try a nearer plot",
               "x": r.get("x"), "y": r.get("y"), "moves": r.get("moves")}
        # H.move_unit already stored this destination as a standing order; a refused move must not leave it for
        # resume_moves to re-push next turn (live t76: a Worker refused onto another Worker's plot kept (48,15)).
        try:
            # Keyed per seat since the hotseat fix (H.pm_key), not by the bare id: the old form cleared nothing
            # and the refused destination came back as going_to / a resumed order the next turn.
            self.q(f"H.pending_moves[H.pm_key({int(unit_id)}, {self._pid(pid)})] = nil return true")
        except TunerdError:
            pass
        try:
            mine = self._unit_rows(pid)
            me = next((u for u in mine if u.get("id") == unit_id), None)
            hint = (me and self._blocker_hint(me, x, y, mine)) or self._foreign_occupant_hint(x, y)
            if hint:
                out["err"] = "unit did not move: " + hint
        except TunerdError:
            pass
        return out

    def _unit_rows(self, pid: int | None = None) -> list[dict]:
        """units() filtered to well-formed rows (hint helpers must never break the call they decorate)."""
        rows = self.units(pid)
        return [u for u in rows if isinstance(u, dict)] if isinstance(rows, list) else []

    def _foreign_occupant_hint(self, x: int, y: int) -> str | None:
        """Another civ's unit visible on the destination (map_window's own visibility rules). Live t414: a
        Missionary's path to a plot next to Quebec City failed turn after turn -- the city-state's Infantry and
        Anti-Aircraft Gun stood on both target plots, and the error said only 'no path'."""
        try:
            w = self.plots_around(x, y, 0)
        except TunerdError:
            return None
        plots = w.get("plots", w) if isinstance(w, dict) else w
        for p in plots if isinstance(plots, list) else []:
            if isinstance(p, dict) and (p.get("x"), p.get("y")) == (x, y):
                others = [u for u in p.get("units") or [] if isinstance(u, dict) and u.get("owner") != self.seat]
                if others:
                    names = ", ".join(str(u.get("type")) for u in others)
                    return f"({x},{y}) is occupied by another civ's unit ({names}); pick an adjacent free plot"
        return None

    @staticmethod
    def _blocker_hint(me: dict, x: int, y: int, mine) -> str | None:
        """One unit per plot per class (combat / civilian) and domain, cities included (live t333: a Worker on
        Shanghai's plot kept a Missionary out). Name my own blocker when there is one."""
        cls = lambda u: (u.get("strength") or 0) > 0
        for u in mine:
            # caravans/cargo ships on a route are automated and pass through; an idle one home in a city does
            # block (live t449: a returned Caravan on Beijing's plot kept an SS Booster out of the capital)
            if (u.get("id") != me.get("id") and (u.get("x"), u.get("y")) == (x, y) and not u.get("automated")
                    and cls(u) == cls(me) and u.get("domain") == me.get("domain")):
                trade = u.get("type") in ("CARAVAN", "CARGO_SHIP")
                return (f"your {u.get('type')} (unit {u.get('id')}) already holds ({x},{y}) and only one "
                        f"{'combat' if cls(me) else 'civilian'} unit fits per plot: "
                        + ("send it on a trade route (establish_trade_route) or move it" if trade else
                           "move it, or pick an adjacent plot")
                        + (" (a missionary/prophet can spread from next to the city)" if me.get("type") in
                           ("MISSIONARY", "PROPHET", "INQUISITOR") else ""))
        return None

    def unit_mission(self, unit_id: int, mission: str, x: int = -1, y: int = -1, data2: int = 0,
                     build: str | None = None, pid: int | None = None) -> dict:
        """See _unit_mission. A mission the engine calls illegal comes back with the unit's legal ones
        (live t328: MISSION_FORTIFY on a Cannon -- siege units cannot fortify, MISSION_SLEEP is the answer)."""
        # Great-person missions whose payoff is an empire number: measure it (live t333: a political treatise
        # answered only consumed:true; culture had gone 1218 -> 1874).
        gp_stat = {"MISSION_GIVE_POLICIES": "culture", "MISSION_TRADE": "gold",
                   "MISSION_GOLDEN_AGE": "golden_age_turns",
                   # live t379: a 5106-science bulb took Computers from 9 turns to 2 -- say so
                   "MISSION_DISCOVER": "research_turns_left"}.get(mission)
        before = research_before = None
        if gp_stat:
            try:
                summ0 = self.summary(pid)
                before, research_before = summ0.get(gp_stat), summ0.get("research")
            except (TunerdError, AttributeError):
                before = None
        hurry0 = self._hurry_city_production(unit_id, None, pid) if mission == "MISSION_HURRY" else None
        pillage_gold0 = None
        pillage_plot0 = None
        if mission in ("MISSION_PILLAGE", "MISSION_PILLAGE_ROUTE"):
            # The engine accepts a pillage order from a unit with no moves left and then does nothing:
            # the plot stays improved, the unit goes to HOLD, and the old reply said ok with
            # gold_gained 0 (live 2026-09-24 t219: Infantry walked two tiles onto a quarry and "pillaged"
            # it). The stock button is greyed at 0 moves; refuse the same way and say when to retry.
            try:
                pillage_plot0 = self.q(f"local u = Players[{self._pid(pid)}]:GetUnitByID({int(unit_id)}) "
                                       f"if not u then return nil end local p = u:GetPlot() "
                                       f"return {{moves = u:MovesLeft(), improvement = p:IsImprovementPillaged(), "
                                       f"route = p:IsRoutePillaged(), x = p:GetX(), y = p:GetY()}}")
            except (TunerdError, AttributeError):
                pillage_plot0 = None
            if isinstance(pillage_plot0, dict) and (pillage_plot0.get("moves") or 0) <= 0:
                return {"ok": False, "err": "the unit has no moves left this turn, so the engine would drop the pillage "
                                            "order; pillage next turn (or before moving)",
                        "x": pillage_plot0.get("x"), "y": pillage_plot0.get("y"), "moves": 0}
            try:
                pillage_gold0 = self.summary(pid).get("gold")
            except (TunerdError, AttributeError):
                pillage_gold0 = None
        r = self._unit_mission(unit_id, mission, x, y, data2, build, pid)
        if hurry0 and isinstance(r, dict) and r.get("ok"):
            # live t437: an Engineer hurrying Hubble answered only consumed:true
            after = self._hurry_city_production(None, hurry0.get("city_id"), pid)
            if after:
                r["effect"] = {"city": hurry0.get("city"), "production": hurry0.get("production"),
                               "turns_before": hurry0.get("turns"), "turns_after": after.get("turns"),
                               "progress_before": hurry0.get("progress"), "progress_after": after.get("progress"),
                               "cost": after.get("cost")}
                if after.get("production") != hurry0.get("production"):
                    r["effect"]["completed"] = hurry0.get("production")
                    r["effect"]["now_building"] = after.get("production")
        if gp_stat and before is not None and isinstance(r, dict) and r.get("ok"):
            try:
                summ = self.summary(pid)
                r["effect"] = {gp_stat + "_before": before, gp_stat + "_after": summ.get(gp_stat)}
                # A bulb that finishes the current tech moves research on: turns_left 6 -> 8 read like a loss
                # (live t419, Penicillin done, Ecology next). Name the research on both sides.
                if gp_stat == "research_turns_left":
                    r["effect"]["research_before"] = research_before
                    r["effect"]["research_after"] = summ.get("research")
            except (TunerdError, AttributeError):
                pass
        if mission in ("MISSION_PILLAGE", "MISSION_PILLAGE_ROUTE") and isinstance(r, dict) and r.get("ok") \
                and pillage_gold0 is not None:
            # Stock combat banner shows the gold; digest used to be the only place it landed.
            try:
                gold1 = pillage_gold0
                for _ in range(8):
                    time.sleep(0.25)
                    gold1 = self.summary(pid).get("gold")
                    if gold1 != pillage_gold0:
                        break
                r["effect"] = {"gold_before": pillage_gold0, "gold_after": gold1,
                               "gold_gained": (gold1 or 0) - (pillage_gold0 or 0)}
                # Say whether the plot actually changed, not just the treasury: a pillaged route, farm or
                # camp yields no gold at all, and the gold line alone read like "nothing happened".
                if isinstance(pillage_plot0, dict):
                    after = self.q(f"local p = Map.GetPlot({int(pillage_plot0['x'])}, {int(pillage_plot0['y'])}) "
                                   f"return {{improvement = p:IsImprovementPillaged(), route = p:IsRoutePillaged()}}") or {}
                    r["effect"]["improvement_pillaged"] = bool(after.get("improvement")) and not pillage_plot0.get("improvement")
                    r["effect"]["route_pillaged"] = bool(after.get("route")) and not pillage_plot0.get("route")
                    if not (r["effect"]["improvement_pillaged"] or r["effect"]["route_pillaged"]):
                        r["effect"]["note"] = "nothing on the plot was pillaged"
            except (TunerdError, AttributeError):
                pass
        if mission == "MISSION_SPACESHIP" and isinstance(r, dict) and r.get("ok"):
            # Live t424: adding the Cockpit answered only consumed:true -- show the ship after.
            try:
                r["spaceship"] = {p["part"]: f"{p['in_ship']}/{p['needed']}" for p in self.spaceship_status(pid).get("parts", [])}
            except (TunerdError, AttributeError, KeyError):
                pass
        if isinstance(r, dict) and r.get("err") == "action is not currently legal":
            try:
                acts = self.available_unit_actions(unit_id, pid)
                r["legal_missions"] = [a.get("mission") or a.get("type") for a in acts.get("actions", [])]
                # Live t330: a freshly built Infantry in a garrisoned city could only move/swap -- two combat
                # units on one plot until one leaves. Say so instead of leaving the caller to guess.
                mine = self._unit_rows(pid)
                me = next((u for u in mine if u.get("id") == unit_id), None)
                if me and (me.get("strength") or 0) > 0:
                    mates = [u["id"] for u in mine if u.get("id") != unit_id and (u.get("strength") or 0) > 0
                             and (u.get("x"), u.get("y")) == (me.get("x"), me.get("y")) and u.get("domain") == me.get("domain")]
                    if mates:
                        r["reason"] = (f"stacked with your combat unit(s) {mates} on ({me['x']},{me['y']}): only one may stay; "
                                       f"move this one (or that one) to another plot first")
            except TunerdError:
                pass
        return r

    def _hurry_city_production(self, unit_id: int | None, city_id: int | None, pid: int | None = None) -> dict | None:
        """Production of the city on `unit_id`'s plot (or city `city_id`): what it builds, turns, stored hammers."""
        sel = (f"local u = p:GetUnitByID({int(unit_id)}); if not u then return {{}} end; "
               f"local c = u:GetPlot() and u:GetPlot():GetPlotCity()") if unit_id is not None else \
              f"local c = p:GetCityByID({int(city_id)})"
        try:
            r = self.q(f"""
                local p = Players[{self._pid(pid)}]
                {sel}
                if not c or c:GetOwner() ~= p:GetID() then return {{}} end
                return {{city_id=c:GetID(), city=c:GetName(), production=H.L(c:GetProductionNameKey()),
                         turns=c:GetProductionTurnsLeft(), progress=c:GetProduction(), cost=c:GetProductionNeeded()}}""")
        except TunerdError:
            return None
        return r if isinstance(r, dict) and r.get("city_id") is not None else None

    def _unit_mission(self, unit_id: int, mission: str, x: int = -1, y: int = -1, data2: int = 0,
                      build: str | None = None, pid: int | None = None) -> dict:
        """Push a mission by name through the game's network path (selection list +
        GAMEMESSAGE_PUSH_MISSION, see harness/lua/runtime/helpers.lua net_unit_message).

        e.g. MISSION_FOUND, MISSION_FORTIFY, MISSION_SLEEP, MISSION_SKIP, MISSION_MOVE_TO (x, y).
        `data2` is accepted for call-site compatibility and ignored: extra mission data is `build`
        for MISSION_BUILD, or x/y for movement-shaped missions.

        MISSION_BUILD: pass the improvement via `build=` (e.g. build="BUILD_FARM"), NOT x/y --
        the BuildTypes id travels as the mission's first data word. The build always applies to the
        unit's own tile.

        The message does not report whether the mission stuck, and it is applied on a later game
        update. For MISSION_BUILD this polls until GetBuildType() shows the build (or the plot has
        already changed for an instant build) before reporting success."""
        _ = data2
        build_arg = lua_str(build) if build else "nil"
        push = lambda: self._order(
            f"return H.unit_mission({unit_id}, {lua_str(mission)}, {x}, {y}, {build_arg}, {self._pid(pid)})"
        )
        religious = mission in ("MISSION_SPREAD_RELIGION", "MISSION_REMOVE_HERESY")
        before = self.q(f"return H.religion_target({unit_id}, {self._pid(pid)})") if religious else None
        if religious and before.get("ok") and not before.get("city"):
            return {"ok": False, "err": "no city on or adjacent to the unit's plot; move next to (or into) the target city first"}
        # A Great Person is a once-in-many-turns resource and MISSION_CREATE_GREAT_WORK answered with a
        # bare {ok, consumed}: which work, in which city's which building, was left for the caller to
        # find by diffing culture_works (live t215: "Martin Fierro" went into Te-Moak's Amphitheater).
        # The game shows a popup naming it. Snapshot the slots and report the one that filled.
        works_before = (self.q(f"return H.great_work_index({self._pid(pid)})") or {}
                        ) if mission == "MISSION_CREATE_GREAT_WORK" else None
        found_pre = None
        if mission == "MISSION_FOUND":
            # PushMission(MISSION_FOUND) "succeeds" with no moves left and no city (live t283), so check
            # first and confirm the city afterwards instead of trusting the accept.
            found_pre = self.q(f"return H.found_check({unit_id}, -1, -1, {self._pid(pid)})")
            if found_pre.get("ok") and found_pre.get("unit_exists"):
                if found_pre.get("city"):
                    return {"ok": False, "err": "there is already a city on this plot"}
                if (found_pre.get("moves") or 0) <= 0:
                    return {"ok": False, "err": "the settler has no moves left this turn (a standing move just spent "
                                                "them); MISSION_FOUND needs at least one move -- found next turn",
                            "x": found_pre.get("x"), "y": found_pre.get("y"), "moves": 0}
                if not found_pre.get("can_found"):
                    return {"ok": False, "err": "cannot found a city on this plot (too close to another city, "
                                                "water, or foreign territory); move first",
                            "x": found_pre.get("x"), "y": found_pre.get("y")}
        if mission in ("MISSION_RANGE_ATTACK", "MISSION_NUKE", "MISSION_PARADROP") and x >= 0 and y >= 0:
            r = self._with_target_result(x, y, push, pid)
        elif mission in ("MISSION_MOVE_TO", "MISSION_MOVE_UNIT_TO") and x >= 0 and y >= 0:
            # An air strike is issued exactly like a move onto the target plot, so this is the
            # attack path for every air unit. attack_before answers "no enemy there" for an
            # ordinary move, and then this costs nothing extra.
            r = self._with_attack_result(unit_id, x, y, push, pid)
        else:
            r = push()
        if not r.get("ok"):
            return r
        if r.get("automate_pending") is not None:
            chk = {}
            for _ in range(12):
                time.sleep(0.25)
                chk = self.q(f"return H.automate_check({unit_id}, {self._pid(pid)})")
                if chk.get("automated") or chk.get("gone"):
                    break
            if chk.get("automated") or chk.get("gone"):
                chk.pop("ok", None)
                return {"ok": True, **chk}
            return {"ok": False, "err": f"{mission} was sent but the unit is not automated after 3 s"}
        if r.get("command_pending"):
            # Verify: a delete must make the unit disappear; other commands report the unit's state after.
            for _ in range(12):
                time.sleep(0.25)
                pos = self.q(f"return H.unit_pos({unit_id}, {self._pid(pid)})")
                gone = not (isinstance(pos, dict) and pos.get("ok"))
                if mission == "COMMAND_DELETE":
                    if gone:
                        return {"ok": True, "command": mission, "unit_gone": True}
                elif not gone:
                    return {"ok": True, "command": mission, **{k: v for k, v in pos.items() if k != "ok"}}
            return {"ok": False, "err": f"{mission} was sent but no effect was seen within 3 s"}
        if build and r.get("pending"):
            before = r.pop("before", None)
            r.pop("pending", None)
            chk = None
            for _ in range(12):
                time.sleep(0.25)
                chk = self.q(f"return H.build_check({unit_id}, {r.get('x', -1)}, {r.get('y', -1)}, "
                             f"{lua_table(before) if before else 'nil'}, {self._pid(pid)})")
                if chk.get("started") or chk.get("completed"):
                    break
            if chk and chk.get("completed"):
                done = {"ok": True, "buildtype": -1, "completed": True, "moves": chk.get("moves")}
                for k in ("improvement", "claimed_plots", "unit_consumed"):
                    if chk.get(k) is not None:
                        done[k] = chk[k]
                if chk.get("claimed_plots"):
                    # Naming the civ we took tiles from is the part a human sees as a diplomatic
                    # incident, not just a border move.
                    taken = sorted({r.get("taken_from_name") or str(r.get("taken_from"))
                                    for r in chk["claimed_plots"]
                                    if isinstance(r, dict) and r.get("taken_from") is not None})
                    done["note"] = (f"claimed {len(chk['claimed_plots'])} tile(s)"
                                    + (", taken from " + ", ".join(taken) if taken else ""))
                return done
            if chk and chk.get("started"):
                out = {"ok": True, "buildtype": chk.get("buildtype"), "build": chk.get("build"),
                       "turns_left": chk.get("turns_left"), "moves": chk.get("moves")}
                if r.get("build_id") is not None and chk.get("buildtype") != r.get("build_id"):
                    # The engine clears a feature the ordered improvement removes as its own build first, then
                    # carries on with the order (live: Spices plantation on marsh t71 -> REMOVE_MARSH, finished
                    # as a plantation t79 without a new order; Silk/forest-hill mine t79 -> REMOVE_FOREST).
                    if str(chk.get("build") or "").startswith("BUILD_REMOVE_"):
                        out["note"] = (f"{chk.get('build')} runs first ({chk.get('turns_left')} turns); the ordered "
                                       "build follows on its own, no new order needed")
                    else:
                        out["note"] = (f"the unit is working on {chk.get('build')}, not the ordered build "
                                       f"(id {r.get('build_id')})")
                return out
            return {"ok": False, "err": "MISSION_BUILD was sent but the unit did not start the build within 3 s "
                                        "(GetBuildType still -1 and the plot unchanged)"}
        if works_before is not None:
            for _ in range(8):
                time.sleep(0.25)
                after = self.q(f"return H.great_work_index({self._pid(pid)})") or {}
                new = [w for k, w in after.items() if k not in works_before]
                if new:
                    r["great_work"] = new[0]
                    return r
            r["note"] = ("no new great work appeared; the slot may have been taken this turn -- "
                         "culture_works shows every slot and which are empty")
            return r
        if found_pre is not None and found_pre.get("unit_exists"):
            fx, fy = found_pre.get("x", -1), found_pre.get("y", -1)
            post = None
            for _ in range(8):
                time.sleep(0.25)
                post = self.q(f"return H.found_check({unit_id}, {fx}, {fy}, {self._pid(pid)})")
                if post.get("city"):
                    break
            if post and post.get("city"):
                r["city"] = post["city"]
                r["consumed"] = not post.get("unit_exists")
            else:
                r["ok"] = False
                r["err"] = "MISSION_FOUND was accepted but no city appeared on the settler's plot"
            return r
        if religious and before.get("ok"):
            # Measure the conversion instead of trusting the accept: followers/majority in the target
            # city before vs after, and how many spreads the unit has left (0 = it is consumed).
            time.sleep(0.3)
            after = self.q(f"return H.religion_target({unit_id}, {self._pid(pid)})")
            if not after.get("ok"):
                # Last charge consumed the unit: re-read the same city by plot instead.
                after = self.q(f"return H.city_religion_at({before.get('x', -1)}, {before.get('y', -1)}, "
                               f"{before.get('unit_religion', -1)}, {self._pid(pid)})")
                if after.get("ok"):
                    after["spreads_left"] = 0
                r["consumed"] = True
            eff = spread_effects(before, after)
            if eff.get("gained_followers") is False and (after.get("spreads_left") == before.get("spreads_left")):
                r["ok"] = False
                r["err"] = "mission accepted but nothing changed (no charge used, no new followers) -- is the unit adjacent to or inside the city, with moves left?"
            r["effects"] = eff
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
            # A route the engine drops ("Route to cancelled!": no path, or nothing left to build on it) leaves the
            # worker AWAKE; the bare ok:true read like it was on its way (live t96, Agaidika -> capital).
            if mission == "MISSION_ROUTE_TO" and after.get("activity_name") == "AWAKE" and after.get("buildtype", -1) == -1:
                r["ok"] = False
                r["err"] = ("the engine dropped the route (no path to that plot, or no road left to build on the way); "
                            "move the worker onto each missing plot and use BUILD_ROAD")
        else:
            r["consumed"] = True
        return r

    def set_production(self, city_id: int, order: str, item: str, pid: int | None = None, append: bool = False) -> dict:
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
            local puppet = H.city_production_guard(city)
            if puppet then return puppet end
            local id = GameInfoTypes[{lua_str(item)}]
            if id == nil then return {{ok=false, err="unknown item"}} end
            if not city:{can_fn}(id, 0) then
              local r = {{ok=false, err="city cannot build this (missing prereq, already built, or one-per-city)"}}
              -- a wonder/building already sitting in this city's queue is refused too (live t437 Hubble)
              pcall(function()
                for i = 0, city:GetOrderQueueLength() - 1 do
                  local _, data = city:GetOrderFromQueue(i)
                  if data == id then r.err = "already in this city's production queue (position " .. (i + 1) .. ")" end
                end
              end)
              -- per-player unit caps (spaceship parts: 3 boosters) count units already built plus ones in any
              -- city's queue (live t437: a 4th booster refused while three cities were building one)
              local u = {lua_str(order)} == "ORDER_TRAIN" and GameInfo.Units[id]
              local uc = u and GameInfo.UnitClasses[u.Class]
              if uc and (uc.MaxPlayerInstances or -1) > 0 then
                local p = Players[{self._pid(pid)}]
                local have, making = p:GetUnitClassCount(uc.ID), p:GetUnitClassMaking(uc.ID)
                if have + making >= uc.MaxPlayerInstances then
                  r.err = "player limit reached: " .. have .. " built + " .. making .. " in production of max " .. uc.MaxPlayerInstances
                end
              end
              return r
            end
            return {{ok=true, id=id}}""")
        if not pre.get("ok"):
            return self._name_hint(pre, item)
        r = self.q(f"""
            local city = Players[{self._pid(pid)}]:GetCityByID({city_id})
            Game.CityPushOrder(city, OrderTypes.{order}, {pre['id']}, false, {"false" if append else "true"}, true)
            return {{ok=true}}""")
        if not r.get("ok"):
            return r
        time.sleep(0.3)
        # append=True is the production screen's shift-click (productionpopup.lua passes `not g_append` as the
        # 5th argument): the item goes behind what the city is building instead of replacing it. The reply
        # carries the whole queue so the caller sees where it landed.
        r = self.q(f"""
            local city = Players[{self._pid(pid)}]:GetCityByID({city_id})
            if not city then return {{ok=false, err="no such city"}} end
            local queue = {{}}
            pcall(function()
              for i = 0, city:GetOrderQueueLength() - 1 do
                local orderType, data = city:GetOrderFromQueue(i)
                local row = (orderType == OrderTypes.ORDER_TRAIN and GameInfo.Units[data])
                         or (orderType == OrderTypes.ORDER_CONSTRUCT and GameInfo.Buildings[data])
                         or (orderType == OrderTypes.ORDER_CREATE and GameInfo.Projects[data])
                         or (orderType == OrderTypes.ORDER_MAINTAIN and GameInfo.Processes[data]) or nil
                queue[#queue + 1] = row and row.Type or tostring(data)
              end
            end)
            return {{ok=true, production=H.L(city:GetProductionNameKey()), turns=city:GetProductionTurnsLeft(), queue=queue}}""")
        # a process never completes: the engine answers 2^31-1 turns (live t405 International Space Station)
        if isinstance(r, dict) and isinstance(r.get("turns"), int) and r["turns"] >= 2**31 - 1:
            r["turns"] = None
            r["note"] = "ongoing process: converts production every turn, never completes"
        # CityPushOrder drops an order the engine rejects without saying so; confirm it is really queued
        if isinstance(r, dict) and r.get("ok") and isinstance(r.get("queue"), list) and item not in r["queue"]:
            r["ok"] = False
            r["err"] = "order was not queued (the engine rejected it)"
        return r

    _NAME_TABLES = {"UNIT_": "Units", "BUILDING_": "Buildings", "PROJECT_": "Projects", "PROCESS_": "Processes",
                    "TECH_": "Technologies"}

    def _name_hint(self, r: Any, name: str) -> Any:
        """On an "unknown item/tech" refusal, add the closest real names (live t321: UNIT_GREAT_PROPHET is
        UNIT_PROPHET). The table's Type list is read once per session."""
        if not (isinstance(r, dict) and str(r.get("err", "")).startswith("unknown")):
            return r
        import difflib
        table = next((t for pre, t in self._NAME_TABLES.items() if name.upper().startswith(pre)), None)
        tables = [table] if table else list(self._NAME_TABLES.values())
        cache = self.__dict__.setdefault("_type_names", {})
        names = []
        for t in tables:
            if t not in cache:
                cache[t] = self.q(f"local t = {{}} for row in GameInfo.{t}() do t[#t + 1] = row.Type end return t") or []
            names += cache[t]
        close = difflib.get_close_matches(name.upper(), names, n=4, cutoff=0.6)
        close += [n for n in names if name.upper().split("_", 1)[-1] in n and n not in close][:4]
        return dict(r, err=f"{r['err']} {name!r}", did_you_mean=close[:5]) if close else dict(r, err=f"{r['err']} {name!r}")

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
        # What a human actually reads when the button is greyed out: the stock production popup appends
        # the engine's own tooltip to a disabled row (productionpopup.lua, "Disabled help text" -- one
        # getter per order x yield). The reason ladder above is our guesswork; this is the game's answer,
        # and it is the only thing that explains e.g. a Pagoda refused in a puppet that follows another
        # religion (live t205: all three puppets read "cannot be bought here at all").
        tip_fn = {("ORDER_TRAIN", "GOLD"): "GetPurchaseUnitTooltip",
                  ("ORDER_TRAIN", "FAITH"): "GetFaithPurchaseUnitTooltip",
                  ("ORDER_CONSTRUCT", "GOLD"): "GetPurchaseBuildingTooltip",
                  ("ORDER_CONSTRUCT", "FAITH"): "GetFaithPurchaseBuildingTooltip"}.get((order, yield_type))
        tip_probe = "" if not tip_fn else f"""
              if city.{tip_fn} then
                local okt, tip = pcall(function() return city:{tip_fn}(id) end)
                if okt and type(tip) == "string" and tip ~= "" then out.engine_reason = tip end
              end"""
        return self._name_hint(self.q(f"""
            local buyer = Players[{self._pid(pid)}]
            local city = buyer:GetCityByID({city_id})
            if not city then return {{ok=false, err="no such city"}} end
            local id = GameInfoTypes[{lua_str(item)}]
            if id == nil then return {{ok=false, err="unknown item"}} end
            local cost = {cost_call}
            local balance = buyer:{"GetGold" if yield_type == "GOLD" else "GetFaith"}()
            local can = city:IsCanPurchase(true, true, {unit_id}, {building_id}, {project_id}, {yield_const})
            local out = {{ok=true, cost=cost, can_purchase=can, balance=balance}}
            if not can then
              -- The purchase screen only greys the button out. Say why when it is knowable (live t319: 975
              -- gold vs a 960 Great War Infantry, refused because a Swordsman stood on the city tile).
              if {"true" if yield_type == "FAITH" else "false"} and (cost or 0) <= 0 then
                out.reason = "not sold for faith (faith buys religious units, and Great People or other units only with the belief/policy/era that unlocks them)"
              elseif {"true" if yield_type == "FAITH" and order == "ORDER_TRAIN" else "false"}
                     and ((GameInfo.Units[id] or {{}}).ReligionSpreads or 0) > 0 and city:GetReligiousMajority() < 0 then
                -- live t409: a Missionary spreads the religion of the city it is bought in; Guangzhou had none
                out.reason = "religious units spread the city's majority religion: this city has none -- buy it in a city that follows your religion"
              elseif type(cost) == "number" and cost < 0 then
                -- live t403: SS_COCKPIT priced -1 -- no gold price exists for it at all
                out.reason = "this item has no gold price (spaceship parts, wonders, projects): it can only be built"
                out.cost = nil
              elseif {"true" if order == "ORDER_CONSTRUCT" else "false"} and city:IsHasBuilding(id) then
                out.reason = "already built in this city"  -- live t431: Nanjing's Spaceship Factory, read as 'cannot be bought here at all'
              elseif city.IsPuppet and city:IsPuppet()
                     and not (buyer.MayNotAnnex and buyer:MayNotAnnex()) then
                -- The purchase screen does not open for a puppet at all: productionpopup.lua returns
                -- early on IsPuppet() unless the player MayNotAnnex() (Venice). So the engine has no
                -- tooltip to offer either -- live t205, a faith Pagoda in Tiwanaku, a puppet that does
                -- follow our religion and does not have one yet, refused with nothing said.
                out.reason = "this city is a puppet: the purchase screen does not open for puppets (annex it to buy here)"
              elseif type(cost) == "number" and cost > balance
                     and city:IsCanPurchase(false, true, {unit_id}, {building_id}, {project_id}, {yield_const}) then
                -- Before the "cannot be bought here at all" catch-all: live t205, a 1050-gold Factory
                -- against 385 gold was called unbuildable while the engine's own tooltip said
                -- "You do not have enough Gold to buy this." Only where the buy button exists: Venice's
                -- Settler (live t42, v225) was "not enough gold (189 of 370)" though Venice can never have one.
                out.reason = "not enough " .. {lua_str(yield_type.lower())} .. " (" .. balance .. " of " .. cost .. ")"
              elseif not city:IsCanPurchase(false, false, {unit_id}, {building_id}, {project_id}, {yield_const}) then
                out.reason = "this item cannot be bought here at all (wonders/projects, or not buildable in this city)"
              elseif not city:IsCanPurchase(false, true, {unit_id}, {building_id}, {project_id}, {yield_const}) then
                out.reason = "this city cannot train or build it, so there is no buy button (compare(kind='production') names the rule)"
              elseif {"true" if order == "ORDER_TRAIN" else "false"} then
                local plot, blockers = city:Plot(), {{}}
                local row = GameInfo.Units[id]
                local combat = row and (row.Combat or 0) > 0
                for i = 0, plot:GetNumUnits() - 1 do
                  local u = plot:GetUnit(i)
                  if u and u:GetOwner() == city:GetOwner() and (u:IsCombatUnit() == combat)
                     and GameInfo.Units[u:GetUnitType()].Domain == row.Domain then
                    blockers[#blockers + 1] = {{unit_id = u:GetID(), type = GameInfo.Units[u:GetUnitType()].Type}}
                  end
                end
                if #blockers > 0 then
                  out.reason = "a unit of the same kind already stands in the city (one per tile); move it out first"
                  out.blocking_units = blockers
                else
                  out.reason = "the game refuses the purchase this turn (already bought something here this turn?)"
                end
              else
                out.reason = "the game refuses the purchase this turn"
              end
              {tip_probe}
            end
            return out"""), item)

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
            if str(pre.get("err", "")).startswith("cannot purchase"):
                # purchase_cost knows why (live t409: a faith Missionary refused in Guangzhou, a city with no
                # majority religion -- the generic error listed three wrong guesses).
                try:
                    why = self.purchase_cost(city_id, order, item, yield_type, pid)
                    if isinstance(why, dict):
                        for k in ("reason", "cost", "balance", "blocking_units"):
                            if why.get(k) is not None:
                                pre[k] = why[k]
                except TunerdError:
                    pass
            return self._name_hint(pre, item)
        item_id = pre["id"]
        # For a unit purchase, remember the unit ids so the NEW unit can be named in the result (a bought
        # unit has 0 moves this turn; the caller still wants its id to give it orders next turn).
        before_ids = set()
        if order == "ORDER_TRAIN":
            before_ids = set(self.q(f"local out = {{}}; for u in Players[{self._pid(pid)}]:Units() do out[#out+1] = u:GetID() end; return out") or [])
        r = self.q(f"""
            local city = Players[{self._pid(pid)}]:GetCityByID({city_id})
            Game.{purchase_fn}(city, {item_id}, {yield_const})
            return {{ok=true}}""")
        if not r.get("ok"):
            return r
        time.sleep(0.3)
        out = self.q(f"""
            local city = Players[{self._pid(pid)}]:GetCityByID({city_id})
            if not city then return {{ok=false, err="no such city"}} end
            return {{ok=true, production=H.L(city:GetProductionNameKey()), turns=city:GetProductionTurnsLeft(),
                     balance=Players[{self._pid(pid)}]:{"GetGold" if yield_type == "GOLD" else "GetFaith"}()}}""")
        # The keys describe the city AFTER the purchase, not the purchase (live t335: a bought Laboratory that
        # was the city's current build left production "" and turns 2147483647 -- an idle city).
        if isinstance(out, dict) and out.get("ok"):
            out["bought"] = item
            out["city_now_building"] = out.pop("production", None) or None
            turns = out.pop("turns", None)
            if out["city_now_building"]:
                out["city_now_building_turns"] = turns
            else:
                out["note"] = "the city's production queue is now empty: set_production before ending the turn"
        if order == "ORDER_TRAIN" and out.get("ok"):
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                new = [u for u in (self.q(f"local out = {{}}; for u in Players[{self._pid(pid)}]:Units() do "
                                          f"out[#out+1] = {{id = u:GetID(), x = u:GetX(), y = u:GetY(), "
                                          f"type = (GameInfo.Units[u:GetUnitType()] or {{}}).Type or u:GetUnitType()}} end; return out") or [])
                       if isinstance(u, dict) and u.get("id") not in before_ids]
                if new:
                    out["unit"] = new[0]
                    out["note"] = "a purchased unit has no moves this turn; move_unit now queues a standing order it will follow next turn"
                    break
                time.sleep(0.25)
            if "unit" not in out:
                out["note"] = "purchase went through (balance changed) but the new unit was not found within 2s; see units()"
        return out

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

    def quick_save(self) -> dict:
        """Same path as the in-game Quick Save button / F5 (`UI.QuickSave()`, see gamemenu.lua's
        OnQuickSave). No filename/confirmation needed. Hotseat games can't be auto-rejoined by
        harness/supervisor.py after a crash, so treat this as cheap insurance against exactly that: call it
        after anything costly (founding a city, a policy/research choice, before combat) rather than only
        relying on the engine's own periodic autosave interval, since a crash before the next autosave loses
        everything back to the last one. See `load_save()` for the load counterpart."""
        return self.q("UI.QuickSave(); return {ok=true, turn=Game.GetGameTurn()}")

    def load_save(self, filename: str, timeout: float = 600) -> dict:
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
        # Each listing is one folder: single-player saves, then hotseat, then network (2026-09-24: the
        # Alpha-Bravo hotseat save was invisible to a single-player-only listing).
        for game_type in ("GAME_SINGLE_PLAYER", "GAME_HOTSEAT_MULTIPLAYER", "GAME_NETWORK_MULTIPLAYER"):
            for show_auto in ("false", "true"):
                listing = self.c.exec(lm, f"""
                    local t = {{}}
                    local gt = GameTypes and GameTypes.{game_type}
                    if gt ~= nil then UI.SaveFileList(t, gt, {show_auto}, true) end
                    for i, v in ipairs(t) do print(v) end
                """, check=True)
                available += [pathlib.PureWindowsPath(p).stem for p in listing]
                candidates = [p for p in listing if pathlib.PureWindowsPath(p).stem == filename]
                if candidates:
                    match = _newest_save(candidates)
                    break
            if match is not None:
                break
        if match is None:
            return {"ok": False, "err": f"no save named {filename!r}; available: {available}"}
        return self._finish_load(lm, match, timeout)

    def _finish_load(self, lm: int | str, match: str, timeout: float) -> dict:
        self.c.exec(lm, f"Events.PlayerChoseToLoadGame({lua_str(match)})", check=True)
        try:
            self.wait_ingame(timeout)
        except (TimeoutError, TunerdError):
            # Live 2026-09-18: a t314 save loaded from a cold boot took over 5 minutes; the load itself
            # was fine. Say so instead of surfacing a bare TimeoutError the caller cannot act on.
            return {"ok": False, "loading": True, "save": pathlib.PureWindowsPath(match).stem,
                    "err": f"load started but the map was not live after {timeout:.0f}s; late-game saves "
                           "can take several minutes -- call turn_status again in a minute"}
        self._mode = None
        # A loaded (or freshly started) single-player game always lands on the "Dawn of Man"/continue
        # splash (loadscreen.lua's OnSequenceGameInitComplete) with Game.SetPausePlayer(activePlayer)
        # already in effect -- InGame is responsive and turn_state() looks normal except paused=true and
        # every action silently no-ops (end_turn, production, etc. all return {ok:true} but nothing moves)
        # until this is dismissed. Confirmed live: this is exactly what OnActivateButtonClicked (the
        # screen's own Continue button) does for a non-hotseat/non-MP game.
        self._dismiss_load_screen()
        return {"ok": True, "turn": self.turn_state(0).get("turn")}

    def _dismiss_load_screen(self) -> None:
        """Press the Dawn of Man screen's Continue button (loadscreen.lua OnActivateButtonClicked: closes the
        screen, unpauses a single-player game, re-enables popups)."""
        try:
            ls = self.c.wait_state("LoadScreen", 5)
            self.c.exec(ls, "OnActivateButtonClicked()", check=False)
        except TunerdError:
            pass

    def load_latest(self, timeout: float = 600) -> dict:
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

    # end_turn confirms the sent CONTROL_ENDTURN took: up to this many polls, this far apart (tests shorten them).
    _END_TURN_CONFIRM_POLLS = 12
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
        for _ in range(self._END_TURN_CONFIRM_POLLS):
            time.sleep(self._END_TURN_CONFIRM_SLEEP)
            ts = self.turn_state()
            if (not ts.get("my_turn") or ts.get("turn") != turn_before or ts.get("processing")
                    or ts.get("active_player") != self.seat):
                r["confirmed"] = True
                return r
        ts = self.turn_state()
        diag = self.q(f"return H.end_turn_diagnosis({self.seat})")
        diag = diag if isinstance(diag, dict) else {}
        # Prefer the engine's own answer over a guess: when UI.CanEndTurn() is false the stock End Turn
        # button is greyed out and CONTROL_ENDTURN is discarded, which is a different situation from a
        # unit that still needs orders -- and the old message claimed the latter either way.
        why = diag.get("note") or ts.get("blocking_hint") or "a unit or decision still blocks it"
        return {"ok": False, "err": "CONTROL_ENDTURN was sent but the turn did not end: " + why,
                "blocking": ts.get("blocking_name"), "todo": ts.get("todo"), "engine": diag}

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
            killed_rows = [u for i, u in bu.items() if i not in au and u.get("owner") != self._pid(pid)]
            killed = [u.get("type") for u in killed_rows]
            dmg = [bu[i]["hp"] - au[i]["hp"] for i in bu if i in au]
            if killed:
                r["killed"] = killed
                # A kill used to omit damage_dealt (city strike that finishes a unit). The
                # remaining hp on the vanished defender is what the combat banner shows.
                dmg.extend(u.get("hp") or 0 for u in killed_rows)
            if dmg:
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
        """Pick a promotion for a unit with ENDTURN_BLOCKING_UNIT_PROMOTION, e.g. PROMOTION_SHOCK_1.
        Sent as the unit panel's DO_COMMAND; confirmed by polling the unit's level/promotion (<= 3 s)."""
        r = self._order(f"return H.choose_promotion({unit_id}, {lua_str(promotion)}, {self._pid(pid)})")
        if not r.get("ok") or not r.get("pending"):
            return r
        r.pop("pending", None)
        pr_id = r.pop("promotion_id", -1)
        chk = None
        for _ in range(12):
            time.sleep(0.25)
            chk = self.q(f"return H.promotion_check({unit_id}, {pr_id}, {self._pid(pid)})")
            if not chk.get("ok") or chk.get("has") or (chk.get("level") or 0) > (r.get("level_before") or 0):
                break
        if chk and chk.get("ok"):
            r.update({k: chk.get(k) for k in ("level", "has", "hp", "promotion_ready")})
        # PROMOTION_INSTA_HEAL is spent on the spot, never held: the level-up is the proof it applied
        # (live 2026-09-18: 42 -> 92 hp, level 2, reported as a failure).
        applied = bool(chk and (chk.get("has") or (chk.get("level") or 0) > (r.get("level_before") or 0)))
        if not applied:
            r["ok"] = False
            r["err"] = "COMMAND_PROMOTION was sent but the unit does not have the promotion after 3 s"
        return r

    def upgrade_unit(self, unit_id: int, pid: int | None = None) -> dict:
        """Upgrade a unit for gold along its upgrade path (Warrior -> Swordsman ...). The engine
        replaces the unit: the result's `unit_id` is the NEW id, `old_unit_id` the one passed in.
        Sent as the unit panel's DO_COMMAND; confirmed by polling the plot for the new unit (<= 3 s)."""
        r = self._order(f"return H.upgrade_unit({unit_id}, {self._pid(pid)})")
        if not r.get("ok") or not r.get("pending"):
            return r
        r.pop("pending", None)
        ut, old_type = r.pop("target_type_id", -1), r.pop("old_type_id", -1)
        chk = None
        for _ in range(12):
            time.sleep(0.25)
            chk = self.q(f"return H.upgrade_unit_check({unit_id}, {r.get('x', -1)}, {r.get('y', -1)}, {ut}, {old_type}, {self._pid(pid)})")
            if chk.get("unit_id") is not None:
                break
        if chk:
            r.update({"unit_id": chk.get("unit_id"), "type": chk.get("type"), "gold": chk.get("gold"),
                      "old_still_exists": chk.get("old_still_exists")})
        if not (chk and chk.get("unit_id") is not None):
            r["ok"] = False
            r["err"] = "COMMAND_UPGRADE was sent but no upgraded unit appeared on the plot within 3 s"
        return r

    def disband_unit(self, unit_id: int, pid: int | None = None) -> dict:
        """Disband a unit (COMMAND_DELETE). Irreversible; frees maintenance and strategic resources.
        The engine deletes the unit on its next tick, so the result is confirmed by polling (<= 3 s)."""
        r = self._order(f"return H.disband_unit({int(unit_id)}, {self._pid(pid)})")
        if not r.get("ok") or not r.get("pending"):
            return r
        before = r.pop("before", None)
        r.pop("pending", None)
        chk = None
        for _ in range(12):
            time.sleep(0.25)
            chk = self.q(f"return H.disband_unit_check({int(unit_id)}, {self._pid(pid)})")
            if chk.get("gone"):
                break
        after = {"units": chk.get("units"), "strategic": chk.get("strategic")} if chk else None
        r["ok"] = bool(chk and chk.get("gone"))
        if not r["ok"]:
            r["err"] = "COMMAND_DELETE was sent but the unit still exists after 3 s"
        r["effects"] = {"before": before, "after": after}
        return r

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

    def choose_ideology(self, branch: str, pid: int | None = None) -> dict:
        """Pick an ideology (POLICY_BRANCH_FREEDOM / ORDER / AUTOCRACY) -- what chooseideologypopup.lua's
        Confirm sends (Network.SendIdeologyChoice), then close that popup like its Close button. Polls
        (<= 3 s) for Player:GetLateGamePolicyTree to change so a refused choice is reported, not trusted."""
        r = self.q(f"return H.choose_ideology({lua_str(branch)}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        state = None
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            time.sleep(0.25)
            state = self.q(f"return H.ideology_state({self._pid(pid)})")
            if state.get("ideology"):
                break
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

    def unit_mission_targets(self, unit_id: int, mission: str, offset: int = 0, limit: int = 100,
                             pid: int | None = None) -> dict:
        return self.q(f"return H.unit_mission_targets({int(unit_id)}, {lua_str(mission)}, {self._pid(pid)}, {int(offset)}, {int(limit)})")

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

    def establish_trade_route(self, unit_id: int, dest_x: int = -1, dest_y: int = -1, trade_type: int = -1,
                              pid: int | None = None, city_name: str = "", kind: str = "") -> dict:
        """Send a caravan/cargo ship to establish a trade route. See available_trade_routes for valid destinations/types.
        `city_name` (+ optional `kind`: international/food/production) picks the row from
        available_trade_routes instead of dest_x/dest_y/trade_type (live t303: every caller first read the
        list, then copied three numbers back).

        Goes through the selection list + GAMEMESSAGE_PUSH_MISSION like every unit order (v86); the
        selection can land a frame late, which `_order` handles by re-issuing the call."""
        if city_name:
            rows = self.available_trade_routes(unit_id, pid)
            rows = rows if isinstance(rows, list) else []
            hits = [r for r in rows if str(r.get("city_name", "")).lower() == city_name.lower()
                    and (not kind or r.get("kind") == kind)]
            if not hits:
                return {"ok": False, "err": f"no available route to {city_name!r}" + (f" of kind {kind!r}" if kind else ""),
                        "available": [(r.get("city_name"), r.get("kind")) for r in rows]}
            if len(hits) > 1:
                return {"ok": False, "err": f"{len(hits)} routes to {city_name!r}; pass kind=international/food/production",
                        "available": [(r.get("city_name"), r.get("kind")) for r in hits]}
            dest_x, dest_y, trade_type = hits[0]["x"], hits[0]["y"], hits[0]["trade_connection_type"]
        elif dest_x >= 0 and dest_y >= 0 and trade_type < 0:
            # The destination alone names the route when only one kind goes there (live 2026-09-27, Codex
            # t64: dest_x/dest_y with kind="international" and no trade_type was refused, then retried).
            rows = self.available_trade_routes(unit_id, pid)
            rows = rows if isinstance(rows, list) else []
            hits = [r for r in rows if r.get("x") == dest_x and r.get("y") == dest_y
                    and (not kind or r.get("kind") == kind)]
            if not hits:
                return {"ok": False, "err": f"no available route to ({dest_x},{dest_y})" + (f" of kind {kind!r}" if kind else ""),
                        "available": [(r.get("city_name"), r.get("kind")) for r in rows]}
            if len(hits) > 1:
                return {"ok": False, "err": f"{len(hits)} routes to ({dest_x},{dest_y}); pass kind=international/food/production",
                        "available": [(r.get("city_name"), r.get("kind")) for r in hits]}
            trade_type = hits[0]["trade_connection_type"]
        if dest_x < 0 or dest_y < 0 or trade_type < 0:
            return {"ok": False, "err": "pass city_name, or dest_x/dest_y (with kind when several route kinds go there), "
                                        "or dest_x/dest_y/trade_type from available_trade_routes"}
        # Confirm by the active-route list: the caravan is consumed and re-created under a NEW unit id
        # when the route starts, and GetNumInternationalTradeRoutesUsed counts trade units, not routes
        # (it read 5 before and after on the first live try), so neither the unit nor that count proves
        # anything. GetTradeRoutes() gains one entry.
        before = self.trade_routes(pid)
        before_out = (before or {}).get("outgoing") if isinstance(before, dict) else (before or [])
        r = self._order(f"return H.establish_trade_route({unit_id}, {dest_x}, {dest_y}, {trade_type}, {self._pid(pid)})")
        if not r.get("ok"):
            return r
        deadline = time.monotonic() + 3.0
        after_out = before_out
        while time.monotonic() < deadline:
            time.sleep(0.25)
            after = self.trade_routes(pid)
            after_out = (after or {}).get("outgoing") if isinstance(after, dict) else (after or [])
            if isinstance(after_out, list) and isinstance(before_out, list) and len(after_out) != len(before_out):
                break
        if isinstance(after_out, list) and isinstance(before_out, list) and len(after_out) > len(before_out):
            key = lambda x: (x.get("from_city"), x.get("to_city"), x.get("turns_left"))
            seen = {key(x) for x in before_out}
            new = [x for x in after_out if key(x) not in seen]
            r.update({"established": True, "route": new[0] if new else None, "routes_active": len(after_out)})
        else:
            r.update({"established": False, "note": "no new entry in trade_routes within 3s; check trade_routes / units"})
        return r

    def trade_routes(self, pid: int | None = None) -> dict:
        """Trade Route Overview: `outgoing` (Your TR) and `incoming` (With You).

        Religion columns (`from_religion` / `from_pressure`, `to_religion` / `to_pressure`) are present
        only when the screen would print them. `details` is the gold and science hover."""
        return self.q(f"return H.trade_routes({self._pid(pid)})")

    def plunder_trade_route(self, unit_id: int, pid: int | None = None) -> dict:
        """Order a military unit to plunder an enemy trade route it's standing on."""
        return self.unit_mission(unit_id, "MISSION_PLUNDER_TRADE_ROUTE", pid=pid)

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

    def current_deals(self, pid: int | None = None) -> dict:
        """Diplomacy Overview current deals with turns remaining. Refuses if the scratch table is occupied."""
        return self.q(f"return H.current_deals({self._pid(pid)})")

    def available_production(self, city_id: int, pid: int | None = None) -> dict:
        """Units/buildings/projects/processes this city can put at the head of its queue right now."""
        return self.q(f"return H.available_production({city_id}, {self._pid(pid)})")

    def available_unit_actions(self, unit_id: int, pid: int | None = None) -> dict:
        """Currently legal unit-panel actions for this unit (missions, builds, commands, promotions).

        Selection-free: uses CanStartMission/CanBuild/CanDoCommand so catalog reads do not
        UI.SelectUnit (that call flips the live 2D/3D map view).
        """
        return self.q(f"return H.available_unit_actions({unit_id}, {self._pid(pid)})")

    def todo_actions(self, unit_ids: list[int] | None = None, full: bool = False, pid: int | None = None,
                     detail: str | None = None, limit: int | None = None) -> dict:
        """Legal actions for many units in one read: every unit still needing orders plus every unit with a
        promotion waiting when `unit_ids` is empty, else exactly those. One tuner query instead of one per
        unit (live S1 t270: 38 units, one available_unit_actions round-trip each).

        `detail` (#35): "normal" (the default, the rows as before), "full" (= `full=True`: the computed help
        line on every action row) or "summary" (see `_summary_unit_row`: one short row per unit plus the exact
        arguments that fetch the rest). Every level is cut from the same one Lua read, so the facts and the
        tuner cost are identical; only the reply's size differs. `limit` returns the first N units (todo order)
        and lists the rest under `omitted` with the arguments that fetch them -- a unit is never dropped
        silently. Every reply carries `detail`, `n` (total) and `returned`."""
        level = detail or ("full" if full else "normal")
        if level not in TODO_DETAIL_LEVELS:
            return {"ok": False, "err": f"detail must be one of {', '.join(TODO_DETAIL_LEVELS)}, not {detail!r}"}
        if full and level != "full":
            return {"ok": False, "err": f"full=true asks for detail='full' but detail={detail!r} was passed; pass one"}
        if limit is not None and int(limit) < 1:
            return {"ok": False, "err": "limit must be 1 or more (leave it out for every unit)"}
        ids = "nil" if not unit_ids else "{" + ",".join(str(int(i)) for i in unit_ids) + "}"
        r = self.q(f"return H.todo_actions({self._pid(pid)}, {ids}, {'true' if level == 'full' else 'false'})",
                   timeout=180)
        if not isinstance(r, dict) or not r.get("ok"):
            return r
        rows = r.get("units") or []
        r["detail"] = level
        if limit is not None and len(rows) > int(limit):
            rest = rows[int(limit):]
            rows = rows[:int(limit)]
            rest_ids = [u.get("id") for u in rest]
            r["omitted"] = {"count": len(rest_ids), "ids": rest_ids,
                            "args": {"unit_ids": rest_ids, "detail": level}}
        if level == "summary":
            rows = [_summary_unit_row(u) for u in rows]
            r["routine_actions"] = list(ROUTINE_ACTIONS)
            r["drill_down"] = {"tool": "todo_actions",
                               "args": {"unit_ids": [u.get("id") for u in rows], "detail": "normal"},
                               "note": "any subset of these ids; detail='full' adds the computed help lines"}
        r["units"] = rows
        r["returned"] = len(rows)
        return r

    def available_trade_routes(self, unit_id: int, pid: int | None = None, detail: str = "summary") -> list[dict]:
        """Valid trade-route destinations for a specific trade unit (caravan/cargo ship) right now, with
        the exact `trade_connection_type` to pass as `establish_trade_route`'s `trade_type`. Per-unit,
        not global -- see `establish_trade_route`'s docstring for why. Religious pressure matches the
        chooser row; the gold/science hover (`details`, ~600 characters per destination, the same
        numbers the row already carries) only with detail="full": a capital with ten reachable cities
        answered 6 KB of hover text for one caravan (Mongolia t102, 2026-09-27)."""
        rows = self.q(f"return H.available_trade_routes({unit_id}, {self._pid(pid)})")
        if detail != "full" and isinstance(rows, list):
            for r in rows:
                if isinstance(r, dict):
                    r.pop("details", None)
        return rows

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
        button uses; a refusal carries `why_not` (spy_dead / surveillance_pending / no_ally / we_are_ally).
        On success `chance` is the percent the confirm printed and `outcome` the notification the coup
        produced (success or failure), read once the engine has handled the net message."""
        r = self.q(f"return H.stage_coup({agent_id}, {self._pid(pid)})")
        if not (isinstance(r, dict) and r.get("ok")):
            return r
        held_before = r.pop("held_before", None)
        if isinstance(held_before, int):
            deadline = time.monotonic() + 6.0
            while time.monotonic() < deadline:
                time.sleep(0.3)
                log = self.q(f"return H.notification_log({self._pid(pid)}, 5, true)")
                if isinstance(log, dict) and isinstance(log.get("held"), int) and log["held"] > held_before:
                    fresh = [e for e in log.get("notifications", []) if isinstance(e, dict) and e.get("i", -1) >= held_before]
                    r["outcome"] = [plain_text(e.get("text") or e.get("summary") or "") for e in fresh]
                    break
            else:
                # live t270 Wittenberg: the coup resolved (ally flipped to us, spy row said we_are_ally)
                # without any notification inside 6s, so the ally is the result, not the log
                r["outcome"] = None
            # the result the screen shows: the city-state's ally afterwards (us on success; the old
            # ally, with our spy dead, on failure)
            owner = r.get("city_owner")
            if isinstance(owner, int):
                ally = self.q(f"local o = Players[{owner}]; return o and o:GetAlly() or -1")
                r["succeeded"] = (ally == self._pid(pid))
                r["ally_now"] = ally
        return r

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

    def _wait_until(self, pred, timeout: float, poll: float = 0.25) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if pred():
                return True
            time.sleep(poll)
        return bool(pred())

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
        peace = bool(rows) and all(r.get("type") == "PEACE_TREATY" for r in rows)
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
            if peace and rows and all(r.get("type") == "PEACE_TREATY" for r in rows):
                return {"ok": True, "peace": True, "leader_says": self._trade_text(), "table": table}
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
        for it in items:
            t = it.get("type")
            from_us = bool(it.get("from_us", True))
            is_us = 1 if from_us else 0
            who = pid if from_us else other
            amount = it.get("amount")
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

    # ------------------------------------------------------------ misc
    def _pid(self, pid: int | None) -> int:
        return self.seat if pid is None else pid


def spread_effects(before: dict, after: dict) -> dict:
    """What a religious spread actually did, from the target city read either side of the mission.

    Both flags have been wrong in a live game before, in opposite directions:
    * t333, Shanghai went 2 -> 3 of 10 Taoists with no majority at all and read `converted: true`,
      so `converted` stopped meaning "gained followers" and started meaning "the majority is ours";
    * t205, a Catholic Missionary spent its last charge on Cusco -- already Catholic, 4 of 5
      followers -- and read `converted: true` with followers 4 -> 4. The majority *was* ours, and
      had been before the unit moved. So it must now be a change: already-ours is its own flag.
    """
    rel = before.get("unit_religion_name") or before.get("unit_religion")
    eff = {"city": before.get("city"), "city_owner": before.get("city_owner"), "religion": rel,
           "population": before.get("population"),
           "followers_before": before.get("followers"),
           "majority_before": before.get("majority_name", before.get("majority")),
           "spreads_before": before.get("spreads_left")}
    if not after.get("ok"):
        eff["converted"] = eff["gained_followers"] = None  # city could not be re-read after the unit was consumed
        return eff
    eff.update({"followers_after": after.get("followers"),
                "majority_after": after.get("majority_name", after.get("majority")),
                "spreads_left": after.get("spreads_left")})
    if "influence" in before or "influence" in after:
        eff["influence_before"] = before.get("influence"); eff["influence_after"] = after.get("influence")
    eff["gained_followers"] = (after.get("followers") or 0) > (before.get("followers") or 0)
    for k in ("majority_before", "majority_after"):
        if eff.get(k) in (-1, None):
            eff[k] = None
    eff["already_majority"] = eff["majority_before"] is not None and eff["majority_before"] == rel
    eff["converted"] = (eff["majority_after"] is not None and eff["majority_after"] == rel
                        and not eff["already_majority"])
    if eff["already_majority"] and not eff["gained_followers"]:
        eff["note"] = "this city already followed that religion and gained no followers: the charge bought nothing"
    if eff["majority_after"] is None:
        eff["note"] = "no religion holds a majority in this city now; another spread can tip it"
    return eff


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



# todo_actions detail levels (#35). "normal" is the default and the pre-#35 shape.
TODO_DETAIL_LEVELS = ("summary", "normal", "full")
# Orders nearly every unit has on nearly every turn. A summary row counts them (`routine`) instead of
# naming them; which ones a given unit has is in its normal row. Anything not listed here -- builds,
# upgrades, great-person missions, paradrop, air strikes, embark, automation -- is named on the row.
ROUTINE_ACTIONS = ("MISSION_MOVE_TO", "MISSION_ROUTE_TO", "MISSION_SWAP_UNITS", "MISSION_SKIP", "MISSION_SLEEP",
                   "MISSION_FORTIFY", "MISSION_ALERT", "COMMAND_WAKE", "COMMAND_CANCEL", "COMMAND_DELETE",
                   "COMMAND_AUTOMATE", "COMMAND_STOP_AUTOMATION", "BUILD_REMOVE_ROUTE")


def _summary_unit_row(u: dict) -> dict:
    """One todo_actions row cut to what a decision starts from: id, type, position, moves, hp when damaged, the non-routine
    action types (bare strings; `kind`/`mission` follow from the prefix, `target_tool` from the normal row),
    how many routine ones, promotion enums, targets in reach (where and what, no preview), and the plots a
    worker could improve (where and which builds, no turns or yield deltas). Keys in a fixed order."""
    if u.get("ok") is False:
        return {"id": u.get("id"), "ok": False, "err": u.get("err")}
    row: dict[str, Any] = {"id": u.get("id"), "type": u.get("type"), "x": u.get("x"), "y": u.get("y"),
                           "moves": u.get("moves")}
    if u.get("hp") is not None:
        row["hp"], row["max_hp"] = u["hp"], u.get("max_hp")
    if u.get("promotion_ready"):
        row["promotion_ready"] = True
    acts = [a.get("type") for a in u.get("actions") or []]
    row["actions"] = [a for a in acts if a not in ROUTINE_ACTIONS]
    row["routine"] = len(acts) - len(row["actions"])
    if u.get("promotions"):
        row["promotions"] = [p.get("promotion") for p in u["promotions"]]
    for key, name in (("attack_targets", "attack"), ("ranged_targets", "ranged")):
        if u.get(key):
            row[name] = [{k: t[k] for k in ("x", "y", "unit", "city", "owner", "hp") if t.get(k) is not None}
                         for t in u[key]]
    if u.get("nearby_builds"):
        row["build_plots"] = [{k: e[k] for k in ("x", "y", "builds", "resource") if e.get(k) is not None}
                              for e in u["nearby_builds"]]
    return row

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


def lua_table(v) -> str:
    """Encode a JSON-shaped Python value (dict/list/str/number/bool/None) as a Lua table literal."""
    if v is None:
        return "nil"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return lua_str(v)
    if isinstance(v, dict):
        return "{" + ", ".join(f"[{lua_str(str(k))}]={lua_table(x)}" for k, x in v.items()) + "}"
    if isinstance(v, (list, tuple)):
        return "{" + ", ".join(lua_table(x) for x in v) + "}"
    raise TypeError(f"cannot encode {type(v).__name__} as Lua")


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


def lua_str_len(ch: str) -> int:
    """UTF-8 bytes `lua_str` emits for one character -- the unit the tuner's command limit counts in.

    Kept next to `lua_str` so the two cannot drift: `tests/test_query_chunking.py` checks that summing
    this over a string plus the two quotes equals the encoded length of `lua_str`."""
    o = ord(ch)
    if ch in '"\\\n\r\t':
        return 2
    if o < 32 or o == 127:
        return 4
    return len(ch.encode("utf-8"))


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


_MARKUP = re.compile(r"\[(?:ICON|COLOR)_[A-Z0-9_]*\]|\[ENDCOLOR\]")
# An icon standing alone for its word ("+1 to these yields: [ICON_GOLD], [ICON_FOOD]", live t22 God King):
# followed by punctuation, another icon or the end rather than by text. Keep its name.
_BARE_ICON = re.compile(r"\[ICON_([A-Z0-9_]+)\](?=\s*(?:[,.;:)]|\[ICON_|$))")
_DISMISS = re.compile(r"\s*\[COLOR_POSITIVE_TEXT\]RIGHT-CLICK\[ENDCOLOR\] to dismiss\.?|\s*RIGHT-CLICK to dismiss\.?")


def plain_text(v: Any) -> Any:
    """Strip the game's display markup from every string in `v`: [COLOR_*]/[ENDCOLOR]/[ICON_*] go (the icon
    is normally followed by its word -- "[ICON_GOLD] Gold"; a bare one keeps its name), [NEWLINE] becomes a newline, and the panel's
    "RIGHT-CLICK to dismiss" line is dropped. Brackets that are not markup are left alone."""
    if isinstance(v, str):
        s = _DISMISS.sub("", v).replace("[NEWLINE]", "\n").replace("[TAB]", " ").replace("[SPACE]", " ")
        s = _BARE_ICON.sub(lambda m: m.group(1).replace("_", " ").title(), s)
        s = _MARKUP.sub("", s)
        return re.sub(r"[ \t]{2,}", " ", s).strip() if s is not v else v
    if isinstance(v, dict):
        return {k: plain_text(x) for k, x in v.items()}
    if isinstance(v, list):
        return [plain_text(x) for x in v]
    return v
