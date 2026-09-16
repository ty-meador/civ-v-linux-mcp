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

## Phase 3a follow-up (2026-09-16): root cause found and fixed, not yet re-verified live
Re-reading `tradelogic.lua` end to end (both the pocket-population code and `OnPropose`) found the actual
gate the crash was missing: **every single `Add*` call in the real UI is only reachable through a pocket
button that gets populated by first calling `deal:IsPossibleToTradeItem(from, to, TradeableItems.TRADE_ITEM_*,
...)`** -- e.g. `IsPossibleToTradeItem(g_iUs, g_iThem, TradeableItems.TRADE_ITEM_ALLOW_EMBASSY, g_iDealDuration)`
at line ~1124, similarly for gold (~1057), GPT (~1095), open borders (~1180), defensive pact (~1234),
research/trade agreement (~1283/~1351), declaration of friendship (~1403), cities (~1440), resources
(~1529). An item that fails that check is never even offered to a human player to add. `H.propose_deal`
skipped this gate entirely and called `Add*` unconditionally, so the crashing test (a single `ALLOW_EMBASSY`
item) almost certainly built a deal containing an item that was **not actually valid** between those two
players (the AI already had an embassy, or embassy trading was disallowed for some other precondition) --
and `UI.DoProposeDeal()` then crashed natively on the invalid deal rather than the earlier hypothesis of
`UI.DoProposeDeal()` needing an open popup/ContextPtr (nothing in `OnPropose`'s human-vs-AI branch does
anything beyond `SetFromPlayer`/`SetToPlayer`/`DoProposeDeal()`, the same three calls this harness was
already making -- so that hypothesis doesn't hold up under closer reading).

**Fix (runtime.lua v10)**: `H.propose_deal` now calls `deal:IsPossibleToTradeItem(...)` with the correct
per-item-type argument shape (matched 1:1 against each pocket-population call site above) before every
`Add*`, and aborts the whole deal with a clean `{ok:false, err:...}` if any item fails. Also mirrors two
smaller guards from the real UI: `OnPropose` returns early on an empty deal (`GetNumItems() == 0`), and
`OnOpenPlayerDealScreen` refuses to open a second negotiation while `UI.HasMadeProposal(pid)` shows one
already outstanding to a different player. `PEACE_TREATY` has no `IsPossibleToTradeItem` gate in the real
UI either (it's added unconditionally when `IsAtWar` is true in `OnOpenPlayerDealScreen`), so that one guard
is `Teams[fromTeam]:IsAtWar(toTeam)` instead, matching the same precondition.

Syntax-checked with lupa (see Phase 1 entry above for the technique) -- passes. **NOT YET LIVE-TESTED**: no
game was running in this pass. Before re-exposing `propose_deal` as an MCP tool or HTTP route, verify live
against a throwaway game: (1) a deal with a genuinely valid `ALLOW_EMBASSY` item does not crash and the AI
responds, (2) a deliberately invalid item (e.g. embassy already established) is rejected with a clean
`{ok:false, err:"item not tradeable: ..."}` instead of crashing, (3) an empty `items` list and a duplicate
in-flight proposal both return clean errors instead of touching the engine.

## Phase 3a live verification (2026-09-16, same day): the IsPossibleToTradeItem fix works, but it was not
## the whole story -- crashed the game twice more, root cause is deeper than a missing validation gate
Ran the verification the previous entry called for, against three successive throwaway hotseat instances
(never touched the friend's shared LAN game -- an AI opponent is all `propose_deal` needs). Findings, in the
order they happened:

1. **The `IsPossibleToTradeItem` gate works as designed.** A deliberately-invalid `ALLOW_EMBASSY` (to an
   unmet player) came back a clean `{ok:false, err:"item not tradeable: ..."}`, no crash. Every other item
   type (`GOLD`, `GOLD_PER_TURN`, `RESOURCES`, `OPEN_BORDERS`, `DEFENSIVE_PACT`, `RESEARCH_AGREEMENT`,
   `TRADE_AGREEMENT`) also came back a clean rejection against a fresh turn-0 AI (none of their preconditions
   are met that early) without crashing anything -- confirms the read-only `IsPossibleToTradeItem` query
   itself is safe to call headlessly for every item type tried.

2. **Second bug found and fixed live**: proposing `DECLARATION_OF_FRIENDSHIP` to an AI crashed the game
   outright (`tuner socket closed by game`, process gone) -- this time the crash was *inside* (or immediately
   around) the `IsPossibleToTradeItem` call itself for that one item type. Re-reading tradelogic.lua's pocket
   population code found the reason directly: the DoF pocket block is the **only** item wrapped in
   `if (g_bPVPTrade) then ... end` (line ~1399, comment: "Only PvP trade, with the AI there is a dedicated
   interface for this trade") -- the real UI never even calls `IsPossibleToTradeItem` for this item type
   against an AI, let alone `Add*`. Fixed in runtime.lua v11: `H.propose_deal` now checks
   `Players[other_player]:IsHuman()` and refuses `DECLARATION_OF_FRIENDSHIP` for an AI recipient *before*
   touching the engine at all (use `H.diplo_event`/`Game.diplo_event` with a DoF-flavoured
   `FromUIDiploEventTypes` event against an AI instead -- that's the "dedicated interface" the comment means).

3. **Third crash, and the important one**: relaunched again, declared war on the AI (so `PEACE_TREATY`
   passes its precondition -- `IsAtWar`, the same guard the real UI uses since peace treaties have no
   `IsPossibleToTradeItem` gate), and called the real `Game.propose_deal(1, [{"type":"PEACE_TREATY", ...}])`
   end to end. **Crashed again**, same signature. Bisected by hand this time, one raw Lua call per step
   against a fourth fresh instance, checking the process was still alive after each: `deal:ClearItems()` --
   fine (proven safe many times over by this point); `deal:AddPeaceTreaty(0, ...); deal:AddPeaceTreaty(1,
   ...)` (both sides, exactly matching `OnOpenPlayerDealScreen`'s own sequence at lines 300-303, unlike
   `H.propose_deal`'s current one-sided `AddPeaceTreaty(from, ...)`) -- **this line itself crashed the game**
   (`tuner socket closed by game`, confirmed via `ps aux` after the log line). Never got to
   `SetFromPlayer`/`SetToPlayer`/`DoProposeDeal()` at all.

**This means the "missing IsPossibleToTradeItem gate" fix from earlier today, while real and worth keeping
(the *query* call is genuinely safe and rejects invalid items cleanly, verified above), does NOT make
`propose_deal` safe to use.** The actual mutating `deal:Add*()` call can crash the game outright even when
the item is legitimately valid (we were actually at war; both required sides were added, matching the real
UI's own call sequence exactly) and even though the read-only validity check for the exact same item/players
just returned true moments earlier. This resurrects -- and for `AddPeaceTreaty` specifically, *confirms* --
the original hypothesis this file dismissed in the "Phase 3a follow-up" entry above: that dismissal was
premature. The deal-mutation methods (`Add*`, and very possibly `UI.DoProposeDeal()` itself, not yet reached
in this bisection) most likely depend on native `CvDeal`/negotiation state that only gets initialized when
the real trade-deal screen (`ui/ingame/worldview/tradelogic.lua`'s own `ContextPtr`) is actually open --
`UI.GetScratchDeal()` returns a real object headlessly (confirmed: `:ClearItems()`, `:IsPossibleToTradeItem()`
never crashed), but mutating it outside that live UI context appears to corrupt or dereference something
that isn't there.

**Do not re-expose `propose_deal`, in its current `UI.GetScratchDeal()`/`Add*`/`UI.DoProposeDeal()` form, as
a tool or route.** The `IsPossibleToTradeItem` validation and the PvP-only DoF guard stay in runtime.lua
(genuinely correct, tested behavior for the read-only path, and cheap safety nets if this is ever revisited),
but three live crashes in one day against this call pattern -- one avoidable by better validation, two not --
is enough signal that this whole approach needs a different foundation, not another patch. Next step, if
this is picked up again: look for a `Network.Send*` equivalent the way `SendFoundPantheon`/`SendFoundReligion`
/`SendUpdatePolicies` worked around the same class of problem for other systems, rather than trying to make
`UI.*`-namespaced deal calls work from a bare tuner `exec`. Three fresh throwaway instances were
launched/crashed/relaunched for this pass (`propose_deal_test`, `propose_deal_test2`, `propose_deal_test3` in
`logs/`); all cleaned up, no shared/LAN game was ever touched.

## Diplomacy escape hatch (`H.diplo_event`/`declare_war`/`make_peace`/`denounce`) fixed and live-verified (2026-09-16)
`H.diplo_event` previously fired `Game.DoFromUIDiploEvent(...)` unconditionally and returned a blind
`{ok=true}` no matter what -- never live-tested (see previous docstring caveat). Live-testing against a
throwaway hotseat instance (`diplo_test` in `logs/`) found the same false-success shape this file has been
hunting all day for `propose_deal`: `Game.DoFromUIDiploEvent` does not error or reject an invalid war/peace
event, it just silently no-ops, so the old code reported success for actions that did nothing.

**Fix, in two passes** (runtime.lua v12 then v13, re-reading `leaderheadroot.lua`'s `OnShowHide`/`OnWarOrPeace`
each time): v12 added `CanChangeWarPeace` (button-visibility gate) plus each direction's own precondition --
`GetNumTurnsLockedIntoWar(otherTeam) > 0` for peace, `IsForcePeace`/`CanDeclareWar` for war. Live-testing v12
immediately found the gap: `make_peace` against a player never met and never at war still returned
`{ok=true}` because `CanChangeWarPeace` and a 0 locked-war-turn count are both trivially true when no war
has ever happened. v13 added the missing `IsHasMet` precondition (the leaderhead screen this logic lives on
can't even open without it) and made the `IsAtWar` branch explicit, matching `OnWarOrPeace` exactly: peace
requires `IsAtWar == true`, war requires `IsAtWar == false`.

**Live-verified sequence** (fresh hotseat vs. 5 AI, seat 0/Korea targeting player 1/Babylon, no crashes at
any step): `make_peace` before meeting -> clean reject ("not at war with this player" -- caught before even
checking met-ness, since not-at-war is true either way; a not-yet-met target hits this same branch).
`Teams[0]:Meet(1, false)` (test-only bootstrap -- `MakeHasMet` isn't exposed to InGame Lua in this build;
`Meet` is, confirmed via metatable introspection: `getmetatable(Teams[0]).__index` listed
`GetHasMetCivCount`/`Meet`/`IsHasMet`/`HasMetHuman`) -> `diplomacy()` correctly flips `met: true`.
`make_peace` while met-but-at-peace -> clean reject ("not at war with this player"). `declare_war` while
met-and-at-peace -> `{ok:true}`, and `diplomacy()` confirms `at_war: true` immediately after. `declare_war`
again while already at war -> clean reject ("already at war with this player"), no double-declare sent.

**Important nuance for future sessions (and the reason this entry exists)**: `make_peace` called
*immediately* after the war declaration above still returned `{ok:true}` -- `GetNumTurnsLockedIntoWar`
read `0` right after declaring, so the v13 lock gate did not block it. The proposal reached the AI and was
(correctly, per `diplomacy()` still showing `at_war: true` afterward) not accepted. This matches what the
user flagged from prior play experience: after declaring war on a player, peace proposals toward that same
player get rejected by the game for roughly the next 10 turns. **That rejection is the AI's own
diplomatic-acceptance logic, not a `GetNumTurnsLockedIntoWar` button-lock** -- our gate mirrors the real
UI's button-enable state correctly (and that button really is enabled with 0 locked turns in this build/
ruleset right after a human-initiated declaration), but the UI enabling the button only means you're
*allowed to ask*, not that the AI will say yes. Don't misread a live `make_peace` test that "does nothing"
as a harness bug: check `diplomacy()`'s `at_war` field to see whether peace actually landed, and expect AI
refusals for a number of turns after any war declaration as normal, unfixable-on-our-end behavior.

`denounce` has no equivalent precondition in `discussiondialog.lua` (`OnDenonceConfirmYes` goes straight
from a confirm click to `DoFromUIDiploEvent`) and was left unguarded; fired cleanly against a met AI with no
crash. Runtime bumped to v13. Test instance (`diplo_test` in `logs/`) launched, driven via ad-hoc scripts
(not checked in), and fully torn down afterward -- no shared/LAN game touched. `declare_war`/`make_peace`/
`denounce` can now be considered safe to keep exposed as MCP tools/HTTP routes; `propose_deal` is still
disabled per the entry above.

## `propose_deal`: external research confirms the dead end, closing this out for now (2026-09-16)
Before spending more live-crash budget on `propose_deal`, checked for prior art instead of re-bisecting:

- **CivFanatics ["How to Force a Deal?"](https://forums.civfanatics.com/threads/how-to-force-a-deal.640218/)**
  (a modder hitting the exact same wall in 2018): no one in the thread found a Lua-only way to finalize an
  arbitrary `Deal` (gold/resources/embassy/etc). The one working pattern that emerged is unrelated to
  `Deal`/`UI.GetScratchDeal()` entirely -- `Teams[x]:MakePeace(y)` + `Teams[x]:SetPermanentWarPeace(true)`,
  a DLL-level *forced* peace with no AI consent involved, used for scripted scenario events. That's a
  different primitive than what `H.propose_deal`'s `PEACE_TREATY` item wants (a negotiated peace the AI can
  still evaluate) and doesn't help with economic items at all, but is worth remembering if a "hard reset to
  peace" tool is ever wanted (e.g. an admin/debug override, not a diplomacy action an LLM seat would call
  normally).
- **[Category:Civ5 Trade API](http://modiki.civfanatics.com/index.php?title=Category:Civ5_Trade_API)** (the
  full indexed list of `Deal.*`/`Team.*`/`Player.*`/`UI.*` trade functions): confirms there is no
  `Game.`/`Network.`-namespaced entry point into the deal system at all -- `UI.GetScratchDeal()` is the only
  documented way to obtain a `Deal` object, and finalizing one goes through `UI.DoProposeDeal()` /
  `UI.DoFinalizePlayerDeal()`, both `UI.*`-namespaced. There is no `SendFoundPantheon`-style `Network.Send*`
  sibling for deals to fall back to, unlike religion/policies.
- **[civ6-mcp](https://github.com/lmwilki/civ6-mcp)** (an existing, much larger MCP project doing the same
  FireTuner-based approach for Civ **VI**, found while looking for prior art on this project generally):
  Civ6 exposes a proper `DiplomacyManager`/`DiplomacySession` API built for exactly this kind of headless
  proposal-and-response flow, and civ6-mcp's `build_propose_trade`/`build_propose_peace` use it directly with
  no reported crash class like ours. That's a real engine-level difference between the two games, not a
  technique this harness was missing -- Civ5's Lua API for trade genuinely never got an equivalent, headless
  entry point. (Also worth a look for other design ideas -- it has a much larger surface, including a
  turn-blocker-resolution loop and a full eval framework, of a similar shape to `harness/supervisor.py` and
  the "blocking_name" fields here.)

**Conclusion: closing this out as a Civ5 engine limitation, not a solvable harness bug.** `propose_deal`
stays disabled/unexposed. If revisited, the only two remotely promising directions are (1) a DLL mod (out of
scope for this project, which is Lua/tuner-only by design) or (2) actually driving the real trade-screen
popup open (`LeaderHeadRoot`/`DiscussionDialog`'s `ContextPtr`) via tuner exec before touching `Deal`, so the
native code sees the UI state it expects -- unverified, likely to cost another crash or two to test, and not
attempted this pass.

## Live-play session (2026-09-16): found a real tuner-drop bug in multi-human hotseat, root-caused

Launched a throwaway instance (`playtest_session` in `logs/`) and drove it end-to-end through `harness.game.Game`
(no MCP client attached -- scripted directly, same calls the tools wrap) to exercise turns for real rather than
via a single short live-test. Intent was to reach the still-unverified success paths (`establish_trade_route`,
`plunder_trade_route`, `found_religion`/`enhance_religion`, `city_ranged_attack`); didn't get there this pass,
but surfaced a more fundamental issue first.

**What happened**: `host_hotseat(human_seats=[0, 1], ...)` (both seats human, rest AI -- 6 players total:
Sweden/us, Korea/us, Arabia, The Celts, Austria, The Aztecs) launched fine. Scripted through turn 0's blockers
in sequence (`ENDTURN_BLOCKING_UNITS` -> found city / fortify, `ENDTURN_BLOCKING_PRODUCTION` -> train a
warrior, `ENDTURN_BLOCKING_RESEARCH` -> pick a tech) for player 0, ended their turn cleanly, then did the same
for player 1. After player 1's `end_turn()` returned `{ok:true}`, the game never advanced: ~380 further polls
over several minutes all showed `active_player=1`, `turn=0`, `blocking_name=NO_ENDTURN_BLOCKING_TYPE`,
`processing=false` -- i.e. nothing indicated a problem, `end_turn()` kept returning `ok:true`, but the actual
game state was frozen. The loop exited normally (hit its iteration cap) rather than erroring, so this would
look like a silent hang to anything polling the same way (including `wait_for_my_turn`, which uses the same
`turn_state()` fields and would spin forever here without a `TimeoutError`, since every read reports `my_turn`
truthy-looking and no blocker).

**Root cause, found in `tunerd.err` and the shim's own log**: the tuner connection to the game genuinely dropped
partway through this (`[tunerd] game connection dropped; will reconnect (game must re-arm its listener)`,
timestamped well after the scripted turns had been running). `logs/playtest_session.err` explains why: this
launch's `[tuner_fix]` patch pass logged
```
EnteringMultiplayerStagingRoom at 0x897c378 -> ret
ExitingMultiplayerStagingRoom: unexpected prologue; NOT patched
patched call Disable() at 0x897bdb4 (OnMultiplayerGameLaunched+0xa4)
```
`shim/tuner_recv_fix.c`'s own comment on `ExitingMultiplayerStagingRoom` (line ~140): "tail-jumps to Disable();
... re-arms the listener (dropping the current client)". The shim tries to neutralize all three known
Disable()-triggering paths (`EnteringMultiplayerStagingRoom`, `ExitingMultiplayerStagingRoom`,
`OnMultiplayerGameLaunched`'s internal call), but `ExitingMultiplayerStagingRoom`'s prologue didn't match the
expected byte pattern in this build/run and the safety check refused to touch it -- so that one path stayed
live and, whenever the game happened to call it, dropped the tuner client exactly as observed. The gap between
"turn genuinely froze" (stale-looking success responses, no error) and "tunerd logs an actual drop" a few
minutes later is consistent with the OS-level TCP connection lingering half-open for a while after the game
side already stopped servicing it.

**Not yet confirmed**: the exact in-game trigger for the call (its name suggests staging-room exit, which
should only fire once at game launch, not mid-game at a hotseat `PlayerChange` hand-off -- but the timing here
points at player 1's turn-end/hand-off specifically). Worth confirming with a fresh instance: launch, immediately
check `playtest.err` for the same "unexpected prologue" line, then watch whether the tuner drops at the very
first hotseat hand-off rather than later.

**Impact / next steps**: this is a real gap in `harness/supervisor.py`'s crash-recovery coverage -- it watches
for the reaper process dying, not for "process alive, tuner silently wedged/dropped mid-poll returning stale
success". `wait_for_my_turn`/any polling loop needs either a liveness check (e.g. a monotonically-increasing
counter or a `ping` roundtrip with a tight timeout) distinct from "the last query happened to return ok", or
`tunerd`'s `ping` op (already exists: `{"ok":true,"connected":...}`) should be polled alongside `turn_state()`
so a dropped `connected:false` state surfaces immediately instead of silently. Fixing the shim's byte-pattern
match for `ExitingMultiplayerStagingRoom` in this Aspyr build revision (dump the actual prologue bytes at that
symbol and compare against the assumed `e8 00 00 00 00 58`) would remove the root cause entirely; not attempted
this pass -- requires disassembling the live binary to find the real prologue, out of scope for a live-play
session. Instance torn down after diagnosis (tuner unreachable, nothing more to learn from it); the
trade-route/religion/ranged-attack verification gaps from the "Verification coverage" section above are still
open for a future session, ideally against a build where this patch succeeds.
