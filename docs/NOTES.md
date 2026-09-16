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

## Diplomacy / leader interactions (added 2026-09-15, mostly static analysis + safe live checks)
- Bug found and fixed in the existing harness: the `AILeaderMessage` event hook had its arguments in the
  wrong order. The real signature (matches leaderheadroot.lua's own handler on the same event) is
  `(iPlayer, iDiploUIState, szLeaderMessage, iAnimationAction, iData1)`; the hook had `msg`/`animation` in
  the position of `iDiploUIState`/`szLeaderMessage`, so every `leader_message` event in the digest recorded
  the numeric diplo-state as the "text" and the real message as "anim". Fixed in runtime.lua v4.
- Second bug found and fixed: `H.install_hooks()` was guarded by a boolean `H.installed_hooks` that
  **carries over** from the previous `H` table on every version bump (see the `H = {...}` constructor at
  the top of the file). That meant any code change *inside* a hook's callback (like the fix above) never
  actually took effect on an already-running game instance -- only a fresh InGame context (leave to menu,
  or relaunch) would pick it up, silently. Fixed by tracking each hook's closure in `H.hook_fns` and having
  `install_hooks()` `Events[name].Remove(prev)` + re-`Add` on every (re)injection, so a version bump always
  takes effect immediately and never double-registers. Verified live: after bumping to v4 on the running
  LAN instance, `H.hook_fns.AILeaderMessage` was non-nil and `H.version` read back as 4 without restarting
  the game or affecting turn state.
- **Diplomatic actions bypass the UI entirely**, same pattern as `move_unit`/`set_production`:
  `Game.DoFromUIDiploEvent(FromUIDiploEventTypes.<NAME>, otherPlayerID, data1, data2)` is the exact call
  the game's own leader-head and discussion-dialog buttons make (`ui/ingame/leaderhead/leaderheadroot.lua`,
  `.../discussiondialog.lua`). It needs no popup open, so the harness never has to detect or click through
  the leader-head screen -- it can act straight from the `leader_message` event text.
  - `FromUIDiploEventTypes` (37 keys) and `DiploUIStateTypes` (42 keys) are live, non-empty globals in the
    InGame Lua context -- confirmed by reading them read-only from the running game (no state changed).
  - Enum values confirmed live (read-only lookup, no event fired): `FROM_UI_DIPLO_EVENT_HUMAN_DECLARES_WAR`
    = 0, `FROM_UI_DIPLO_EVENT_HUMAN_NEGOTIATE_PEACE` = 1, `FROM_UI_DIPLO_EVENT_DENOUNCE` = 20.
  - Full enum list (from grepping this build's Lua for every `FromUIDiploEventTypes.*` and
    `Game.DoFromUIDiploEvent(...)` call site, prefix `FROM_UI_DIPLO_EVENT_` omitted below):
    `HUMAN_DECLARES_WAR`, `HUMAN_NEGOTIATE_PEACE`, `DENOUNCE`, `HUMAN_WANTS_DISCUSSION`,
    `HUMAN_DISCUSSION_WORK_WITH_US` / `_END_WORK_WITH_US` / `_DONT_SETTLE` / `_STOP_DIGGING` /
    `_STOP_SPYING` / `_STOP_SPREADING_RELIGION` / `_SHARE_INTRIGUE`, `COOP_WAR_OFFER` / `_RESPONSE` /
    `_NOW_RESPONSE`, `WORK_WITH_US_RESPONSE`, `WORK_AGAINST_SOMEONE_RESPONSE`,
    `AI_REQUEST_DENOUNCE_RESPONSE`, `PLAN_RA_RESPONSE` (research agreement), `DEMAND_HUMAN_REFUSAL`,
    `REQUEST_HUMAN_REFUSAL`, `AGGRESSIVE_MILITARY_WARNING_RESPONSE`, `EXPANSION_WARNING_RESPONSE` /
    `_SERIOUS_WARNING_RESPONSE`, `PLOT_BUYING_WARNING_RESPONSE` / `_SERIOUS_WARNING_RESPONSE`,
    `ATTACKED_MINOR_RESPONSE`, `I_ATTACKED_YOUR_MINOR_CIV_RESPONSE`, `BULLIED_MINOR_RESPONSE`,
    `I_BULLIED_YOUR_MINOR_CIV_RESPONSE`, `KILLED_MINOR_RESPONSE`, `KILLED_MY_SPY_RESPONSE`,
    `CAUGHT_YOUR_SPY_RESPONSE`, `STOP_CONVERSIONS`, `STOP_DIGGING`. `data1`/`data2` vary per event (mostly
    a button-choice id and/or a third-party player id) -- read the call sites in discussiondialog.lua for
    the exact meaning of a given event before firing it with non-zero data.
  - **NOT live-tested**: no diplomatic event was actually fired against the friend's shared LAN game (that
    would have altered a real shared game state -- declaring war, denouncing, etc. -- without asking them).
    Only the read-only pieces (enum presence, id values, plumbing with a bogus event name) were verified.
  - **Open question, not yet checked**: whether a lingering leader-head/discussion popup (if one is ever
    shown, e.g. after a genuine `HUMAN_WANTS_DISCUSSION`) blocks `Game.DoControl(CONTROL_ENDTURN)` or
    `Game.IsProcessingMessages()`. Since diplomatic actions are fired directly on the engine rather than by
    clicking through that screen, this shouldn't matter in practice, but it hasn't been provoked and
    observed live.
  - Item-based trade deals (gold/tech/resource exchanges, not just discrete yes/no diplomatic events) use a
    separate `CvDeal`-style object API (`ui/ingame/worldview/tradelogic.lua`, `.../diplotrade.lua`) that
    was not reverse-engineered in this pass -- out of scope for this round.

## Phase 1 action tools (added after a live crash, verified only via static analysis + a Lua syntax check)
- **The crash**: a raw `lua()` call probing for a city-ranged-attack API crashed Civ5XP outright mid-session.
  Root cause found: the real path is `Game.SelectedCitiesGameNetMessage(GameMessageTypes.GAMEMESSAGE_DO_TASK,
  TaskTypes.TASK_RANGED_ATTACK, x, y)` (see `dlc/expansion2/ui/ingame/worldview/worldview.lua`'s
  `CityBombard()`), and it must be preceded by `UI.SelectCity(city)` and guarded by
  `city:CanRangeStrike()` / `city:CanRangeStrikeAt(x, y, true, true)` -- the probe almost certainly skipped
  one of those guards. `H.city_ranged_attack` now does both checks before calling `GAMEMESSAGE_DO_TASK`.
- **Policy adoption**: `Network.SendUpdatePolicies(id, isPolicy, true)` -- `isPolicy=true` adopts an
  individual policy (`id` = `GameInfo.Policies` index, gated by `Player:CanAdoptPolicy(id)`); `isPolicy=false`
  unlocks a branch (`id` = branch index, gated by `Player:CanUnlockPolicyBranch(id)`). Confirmed in
  `dlc/expansion2/ui/ingame/popups/socialpolicypopup.lua` (`OnYes`/`PolicySelected`/`PolicyBranchSelected`).
- **Unit promotion**: NOT resolved this pass. `unitpanel.lua`'s `OnPromotionButton` only toggles UI
  visibility; no `Network.Send*`/`GAMEMESSAGE_*` call for actually picking a promotion was found in a grep
  across the whole `ui/ingame` tree. Needs a dedicated look at whatever registers each individual promotion
  button's callback (likely built dynamically per-instance, not a single named function) before adding a
  `unit_promotion` tool -- do not guess here given the city-ranged-attack lesson above.
- **New Lua-syntax safety net**: no `lua`/`luac` binary is installed (only the shared libs), but `pip install
  lupa` in a scratch venv gives a working embedded Lua 5.x via `lua.compile(source)` (parses without
  executing, so it works even though the file references Civ5-only globals like `Players`/`GameInfoTypes`
  that don't exist outside the game). Used to syntax-check `runtime.lua` before every push to a live game
  from now on -- catches typos/syntax errors, NOT bad API calls (those can only be caught by reading the
  game's own Lua first, as above, or by testing against a throwaway game).
- Trade routes / spies / religion: see ARCHITECTURE.md and the function docstrings in `runtime.lua`
  (`H.establish_trade_route`, `H.plunder_trade_route`, `H.available_trade_routes`, `H.spies`,
  `H.found_pantheon`, `H.found_religion`) -- all added this pass, none live-tested yet (no game was running
  after the crash). Verify all of them against a throwaway game before relying on them live.

## Two more live-only bugs found verifying Phase 1b/1c (runtime.lua v5 -> v8)
- **`_G` does not exist** in Civ5's UI Lua contexts (confirmed: `type(_G) == "nil"` in InGame) -- a
  generalised `H.enum_name(table_name_as_string, v)` that tried `_G[table_name]` silently failed every
  lookup (pcall caught the "index a nil value" error and cached an empty table). Fixed by passing the enum
  TABLE itself at each call site (`H.enum_name("EndTurnBlockingTypes", EndTurnBlockingTypes, v)`) instead of
  looking it up by name -- direct global references work fine, only `_G`-style dynamic-by-name indexing
  doesn't. The original hand-written `H.diplo_state_name` (before this generalisation) never had the bug
  for exactly this reason.
- That fix alone did not take effect: `H._enum_names` (the per-enum reverse-lookup cache) was carried over
  from the OLD `H` table across the version bump the same way `H.events`/`H.hook_fns` are -- so the stale,
  empty cache built by the buggy code survived the reinject and kept masking the fix. `_enum_names` is a
  pure cache with no unique state worth preserving (unlike events/hook closures), so it's now always reset
  to `{}` on every (re)injection instead of inherited. **General rule for this codebase going forward: only
  carry state across a RUNTIME_VERSION bump that is genuinely irreplaceable (accumulated event log, hook
  closures needed for `Events.X.Remove()`); anything re-derivable from live game state should start fresh
  every time, or a fix to how it's derived can silently never take effect.**
- **Wrong enum table entirely for game state**: `Game.GetGameState()` pairs with the global
  `GameplayGameStateTypes` (`GAMESTATE_ON`/`_EXTENDED`/`_OVER`), not `GameStateTypes` -- a different, real
  global that turned out to be the UI's screen/view state machine (`CIV5_GS_EXIT`/`MAIN_MENU`/
  `MAINGAMEVIEW`/`LANLOBBY`/...). The original research grep (`GameStateTypes\.[A-Z_]+`, no left boundary)
  silently matched the *tail* of the longer identifier `GameplayGameStateTypes.GAMESTATE_ON` and reported it
  as `GameStateTypes.GAMESTATE_ON`. Both tables happen to define a value `0`, so the bug was invisible until
  live-checked: `game_state_name` resolved to the confusingly-wrong-but-real name `CIV5_GS_EXIT` while
  mid-game, and `game_over` (`gs == GameStateTypes.GAMESTATE_OVER`, which is `gs == nil`) was **silently
  always false** -- the entire point of Phase 1c. Fixed by pointing both at `GameplayGameStateTypes`;
  confirmed live (`game_state_name` now reads `GAMESTATE_ON` while genuinely mid-game).
- Lesson reinforced: an unanchored grep across DLC Lua for an enum's usage can match a substring of a
  *different, longer* identifier and look completely plausible (real values, real-sounding names) while
  being entirely wrong -- static analysis here still needs a live check on the actual returned value/name
  before being trusted, not just "did the grep find something."

## Verification coverage this pass (what was and wasn't exercised live)
Exercised live against a fresh throwaway hotseat instance (not any shared game): turn_state's new
blocking_name/game_state_name/game_over fields (including catching and fixing the two bugs above),
choose_policy/unlock_policy_branch/city_ranged_attack/found_pantheon's precondition-guard and
unknown-name error paths (all return clean {ok:false, err:...} rather than crashing), spies(),
available_trade_routes(), and a full crash-detect-relaunch-rejoin cycle (harness/supervisor.py) including a
real bug fix (wait_for_main_menu needed its own retry loop; wait_state fails fast rather than blocking).
**NOT exercised**: the actual success path of city_ranged_attack / establish_trade_route / plunder_trade_route
/ found_religion / enhance_religion (all need real in-game preconditions -- a valid ranged-attack target, a
caravan and a discovered destination, accumulated faith, a founded religion -- that a few-minute throwaway
game doesn't have time to reach). Their failure/validation paths are confirmed safe; their success paths are
not yet confirmed to use the right constant names end-to-end. Verify each once before relying on it in a
real game, the same discipline that would have caught tonight's crash in the first place.

## Phase 3a trade deals: CRASHED on first live test -- disabled, not root-caused
`H.propose_deal`/`Game.propose_deal` (item-based trade deals via `UI.GetScratchDeal()`) is implemented in
runtime.lua/game.py but **deliberately NOT exposed** as an MCP tool or HTTP route: the very first live test
-- proposing a single `ALLOW_EMBASSY` item to the AI player, nothing exotic, no gold/resource amounts that
could hit an unvalidated-quantity edge case -- crashed the game process outright (`tuner socket closed by
game`; Civ5XP gone from the process list; no Lua-level error, meaning pcall never even got a chance -- a
native crash, the same signature as the city_ranged_attack incident that started this whole round of work).

Every individual piece of the sequence is confirmed-real API, read directly from
`ui/ingame/worldview/tradelogic.lua`: `UI.GetScratchDeal()`, `:ClearItems()`, `:AddAllowEmbassy(playerID)`,
`:SetFromPlayer()`/`:SetToPlayer()`, `UI.DoProposeDeal()` -- the same file's own `OnPropose()` calls this
exact sequence for both PVP and human-vs-AI trades. The leading hypothesis (not confirmed) is that
`UI.DoProposeDeal()` -- a `UI.*`-namespaced call, unlike the `Game.*`/`Network.*` calls that work fine
headlessly elsewhere in this harness (`Game.DoFromUIDiploEvent`, `Network.SendFoundPantheon`, etc.) --
assumes some UI/popup state exists (e.g. the trade-deal screen actually being open, a real `ContextPtr`)
that isn't true when invoked from a bare tuner `exec` outside any popup. Not yet bisected to confirm which
single call in the sequence is the fatal one, or whether it's `DoProposeDeal()` specifically vs. one of the
`Add*`/`Set*Player` calls before it.

**Do not re-expose `propose_deal` as a tool until this is root-caused** (bisect each call in isolation
against a throwaway game, the same discipline this whole file has been reinforcing all night) and confirmed
safe, or an alternative lower-level call (a `Network.Send*` equivalent, if one exists, the same pattern that
worked for `SendFoundPantheon`/`SendFoundReligion`/`SendUpdatePolicies`) is found instead.
