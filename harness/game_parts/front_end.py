"""The front end: hosting and joining games, the staging room, seat detection, saving and loading."""
from __future__ import annotations

import json
import pathlib
import time

from ..client import TunerdError

from .support import _newest_save, lua_str


class FrontEndMixin:
    """The front end: hosting and joining games, the staging room, seat detection, saving and loading.

    A part of harness.game.Game (see harness/game_parts/__init__.py); `self` is the whole Game."""

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
        self._game_keys = {}

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
                    self._game_keys = {}   # another save may be another game: the notebook key is rebuilt
                    self.ensure_runtime()
                    return
            except TunerdError:
                pass
            time.sleep(2)
        raise TimeoutError("InGame state never became responsive")

    def front_end_screen(self) -> str:
        """Which screen is actually visible: InGame, StagingRoom, JoiningRoom, MPGameSetupScreen, Lobby,
        MultiplayerSelect, LegalScreen (the start-up splash), MainMenu, or "?". Civ5 keeps several front-end Lua states loaded-but-hidden at
        once (a stale JoiningRoom from an abandoned rejoin survives past the point where MainMenu is what's
        on screen), so this checks ContextPtr:IsHidden() per candidate id instead of trusting a name match."""
        by_name: dict[str, list[int]] = {}
        for sid, name in self.states().items():
            by_name.setdefault(name, []).append(sid)
        # LegalScreen is the splash a cold start sits on before MainMenu shows (live 2026-09-27: turn_status said
        # the game was "on its ? screen"); load_save / load_latest work through it.
        for name in ("InGame", "StagingRoom", "JoiningRoom", "MPGameSetupScreen", "Lobby", "MultiplayerSelect",
                     "LegalScreen", "MainMenu"):
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

    def net_players(self) -> list[dict]:
        """Network games: human players with connected / turn-active / ended-turn flags."""
        return self.q(f"return H.net_players({self.seat})")

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
