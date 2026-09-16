# Working notes (chronological findings)

## Environment
- Game: Aspyr Linux port, `Civ5XP` 32-bit ELF, build 1.0.3.279 (Firaxis 403694). Stripped, but ~44k dynamic symbols
  incl. full Lua 5.1 C API and C++ class names (cvTunerListener, FSocket, Net*, ...).
- Game core is a real shared object (`libCvGameCoreDLL_Expansion2.so`), loaded dynamically.
- Assets live in `steamassets/assets/` (lowercase). DLC packages under `steamassets/assets/dlc/*` with `.civ5pkg`.
- User data: `~/.local/share/Aspyr/Sid Meier's Civilization 5/` (config.ini, Logs/, Saves/, MODS/, ModUserData/).
- Desktop: COSMIC on Wayland, `DISPLAY=:1`, `WAYLAND_DISPLAY=wayland-1`. Steam client running.
- Toolchain: python3.12, gcc/clang with -m32, gdb, strace. No xdotool/Xvfb/sqlite3 CLI.

## Multiplayer model (why a from-scratch network client is infeasible)
- Strings: "City/Unit/Plot out of sync", NetMapScriptCheck checksum, "EnableOutOfSyncDebugging" =>
  lockstep deterministic simulation; the network carries player commands only.
  A custom client would have to reimplement the whole rules engine to know the game state.
- Chosen approach: a *real game instance* is the LLM's client; we drive it via the FireTuner socket.

## FireTuner (the control channel) — VERIFIED
- `EnableTuner = 1` in config.ini `[Debugging]`. Game then LISTENS on TCP **0.0.0.0:4318** (all interfaces!).
  `Civ5App::Init` -> `cvTunerListener::Enable(FInetHostAddress, 4318)`. Re-armed on ExitToMainMenu /
  ExitingMultiplayerStagingRoom.
- If something else already holds 4318 at init the game ABORTS ("Terminating due to uncaught exception ... of type int").
  (Three early crashes were exactly this: my probe listener held the port.)
- Wire format: `uint32 LE len | int32 LE tag | payload\0`.
  - tag 4 `APP:`  -> "Civ5\0Sid Meier's Civilization V\0<path>\0Eric Jordan\0Jon Shafer\0Brian Wade"
  - tag 4 `LSQ:`  -> NUL-separated (id, name) pairs. ids are sparse (no id 1). One state per UI context.
  - tag 3 `CMD:<id>:<lua>` -> zero or more tag -1 `O\0<text>` (one per print line, prefixed "<Context>: "),
    then tag 3 `""` (done) or tag 3 `ERR:Syntax Error: ...` / `ERR:Runtime Error: ...` (with traceback).
  - `return` values are not echoed: use print(). JSON helper injected by harness/tuner.py (`query()`).
- Other tuner verbs seen in strings: KILLQRY, LISTSEL, STRACKERS, START_TRACKER, STOP_TRACKER, SET:, help/tree requests.
- State 0 = "Main State" (bare Lua, no Game/PreGame). UI contexts (FrontEnd, MainMenu, MultiplayerSelect,
  StagingRoom, InGame, ...) have the full UI Lua API (Game, Players, PreGame, Network, Matchmaking, UI, Controls...).
- Client disconnect handling: see "Connection lifecycle" below.

## Launching
- `steam.sh -applaunch 8930` works from a shell with the desktop env vars; Steam even registers a directly
  launched `./Civ5XP` as the game process. Direct launch (scripts/launch_civ5.sh) also starts fine.
- A second instance can be started while the first is running (Steam did not refuse).
- Time to main menu ≈ 45-60 s. Tuner port opens ~40 s after launch.

## Front-end automation (Lua globals in the respective contexts)
- MultiplayerSelect: `HotSeatButtonClick()` / `LANButtonClick()` / `InternetButtonClick()`.
- MPGameSetupScreen: `Controls.NameBox:SetText(..)`, `OnStart()` -> Matchmaking.HostHotSeatGame / HostLANGame.
- StagingRoom: `SetSlotToHuman(id)`, `PreGame.SetSlotStatus(id, SlotStatus.SS_COMPUTER|SS_TAKEN|SS_OPEN|SS_CLOSED|SS_OBSERVER)`,
  `PreGame.SetNickName`, `PreGame.SetCivilization`, `PreGame.SetHandicap`, `Network.BroadcastPlayerInfo()`,
  `PreGame.SetReady(localID, true)`, `LaunchGame()` -> Matchmaking.LaunchMultiplayerGame().
- Lobby (LAN): `Matchmaking.InitLanLobby()`, `Matchmaking.RefreshLANGameList()`, `Matchmaking.JoinIPAddress(ip)`,
  `Matchmaking.JoinMultiplayerGame(idx)`.
- Hotseat in-game: context `PlayerChange` (ingame/playerchange.lua) is a modal shown on GameplaySetActivePlayer;
  it pauses the game (Game.SetPausePlayer). `OnContinue()` dismisses it (password check via PreGame.TestPassword).
- End turn: actioninfopanel.lua `OnEndTurnClicked()`; MP uses Network.SendTurnComplete/HasSentNetTurnComplete.

## Verified in-game (2026-09-15, hotseat, seat 1 = "Claude")
- Launch MUST go through Steam's container runtime (scripts/launch_civ5.sh reproduces reaper + SLR soldier
  entry points + STEAM_COMPAT_* env). A bare ./Civ5XP reaches the menu but dies silently when hosting MP.
- Tuner toggles found and neutralised by the shim: OnMultiplayerGameLaunched -> Disable (NOP the call);
  EnteringMultiplayerStagingRoom is a tail-jump to Disable (patched to `ret`); ExitingMultiplayerStagingRoom
  re-arms (Disable+Enable => drops the client once; tunerd reconnects). OnExitToMainMenu also re-arms.
- Tuner command payload limit is between 2000 and 3000 bytes -> harness ships big Lua in 1500-byte string
  chunks and loadstring()s them (Game.load_lua). Query bodies must stay small.
- The hotseat hand-off modal is context "PlayerChange". `ContextPtr:IsHidden()` lies for modals; use
  `UIManager:IsModal(ContextPtr) and not Controls.MainContainer:IsHidden()`. While it is up the game is paused
  (Game.IsPaused()==true) and queued orders (CityPushOrder etc.) are NOT processed until `OnContinue()`.
- Working actions: MISSION_FOUND via SelectionListGameNetMessage; Game.SelectionListMove for moves;
  Game.CityPushOrder(city, ORDER_TRAIN, id, false, true, true); Network.SendResearch(id, 0, -1, false);
  Game.DoControl(GameInfoTypes.CONTROL_ENDTURN) ends the turn (AI turns run, next human seat gets PlayerChange).
- Events hooks that fired: SerialEventCityCreated (hex arg is {x,y} in a different coordinate space than plot x),
  NotificationAdded, GameplayAlertMessage, SerialEventUnitDestroyed (settler consumed).

## LAN mode (verified 2026-09-15, joined a friend's LAN game hosted on a Steam Deck)
- Second instance on one machine: `XDG_DATA_HOME` is honoured -> profile under `$XDG_DATA_HOME/Aspyr/Sid Meier's
  Civilization 5/` (seed config.ini with EnableTuner=1; the rest is regenerated). Steam does not refuse a second
  Civ5XP under the same account. scripts/launch_llm_client.sh = launch_civ5.sh + CIV5_DATA_HOME + CIV5_TUNER_PORT.
- Tuner port 4318 is an immediate in the binary; the shim now hooks `bind()` and remaps it (CIV5_TUNER_PORT) and
  can pin the bind address (CIV5_TUNER_BIND=127.0.0.1). Generic remap for other ports: CIV5_PORT_MAP=a=b,...
  Log line: `[tuner_fix] bind: port 4318 -> 127.0.0.1:4319`. One tunerd per instance (--port/--sock or env
  CIV5_TUNER_PORT / CIV5_TUNERD_SOCK; clients pick the instance with CIV5_TUNERD_SOCK).
- Front-end flow (context names as the tuner lists them): MainMenu `MultiplayerClick()` -> MultiplayerSelect
  `LANButtonClick()` -> creates contexts **Lobby** and MPGameSetupScreen. Lobby: `Matchmaking.RefreshLANGameList()`
  (async, ~2-4 s), `Matchmaking.GetMultiplayerGameList()` entries {serverID, serverName, MapName, numPlayers,
  maxPlayers, Players="nick@HOST, ..."}; `Matchmaking.JoinMultiplayerGame(serverID)` or `JoinIPAddress(ip)`.
  Join goes JoiningRoom -> StagingRoom; the StagingRoom context is live once `Matchmaking.GetLocalID() >= 0`.
  `PreGame.SetNickName(localID, ..)`, `PreGame.SetReady(localID, true)`, `Network.BroadcastPlayerInfo()`;
  ready flag is read with `PreGame.IsReady(i)` (there is no GetReady). SlotStatus: SS_OPEN=0 SS_COMPUTER=1
  SS_CLOSED=2 SS_TAKEN=3 SS_OBSERVER=4. The host launches; the tuner survives the launch thanks to the shim.
- LAN discovery from the second instance found the Deck's game on the first refresh (UDP broadcast); joining by
  serverID worked without any port remap for game traffic (only the tuner port collides on a shared machine).
- In a network game the local player IS the active player: `Game.GetActivePlayer()` = our seat (Game.detect_seat()).
  No PlayerChange modal. End turn = same `Game.DoControl(CONTROL_ENDTURN)`; afterwards `Network.HasSentNetTurnComplete()`
  is true and a second CONTROL_ENDTURN would *un-ready* us (actioninfopanel.lua), so Game.end_turn() refuses it.
  Turn options: GAMEOPTION_SIMULTANEOUS_TURNS, GAMEOPTION_DYNAMIC_TURNS, GAMEOPTION_END_TURN_TIMER_ENABLED.
- A host sitting in an observer slot is not `IsHuman()` -> not listed by H.net_players().
- Shim log on this build shows `ExitingMultiplayerStagingRoom: unexpected prologue; NOT patched` (harmless: that
  path only re-arms the listener; tunerd reconnects).
