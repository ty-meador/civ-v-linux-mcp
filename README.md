# civ-v-llm-harness

> **Give an LLM a civilization. See what survives.**

![Civilization V armies gathering across a river and contested border, official game screenshot](https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/8930/ss_84ee7ab3b0148a260359f8d5a78a2ab9033aa695.1920x1080.jpg)

*Game image from [Civilization V on Steam](https://store.steampowered.com/app/8930/Sid_Meiers_Civilization_V/).*

A rival settles the river first. Your peaceful science plan now has a border problem. The model in that seat
sees the same fogged map you would, knows only the civilizations it has met, and has to decide anyway.

This harness puts a language model in a real seat in **Sid Meier's Civilization V**. Challenge it in hotseat
or over LAN, hand it your seat against the game's AI, or put several models in the same match.

It sees the world the way you do, in text. Every revealed tile comes back as terrain, yields, resources, what
a worker could build there and who is standing on it, at hex coordinates the move tools take. Unexplored land
is a frontier it can go and look at, not a list of unknown tiles to plan over. What things *do* (a Library, a
Pikeman, Tradition, Drill I) is a rule book it reads once, not a tooltip repeated on every row. It has to
scout, settle, negotiate, fight and adapt, and it never gets more than a human in that seat would. Fogged
tiles stay fogged. Unmet civilizations stay unknown. The AI's private plans stay private.

Most games bolt an LLM on as a chat layer. This one goes inside the game so a model plays by the same rules as
everyone else at the table.

> **Ready to play?** Give an LLM of your choice the [agent install guide](docs/AGENT_INSTALL.md) and ask it
> to set up the harness and start a game. The guide has the commands and checks; this page is for you.
> [Give your agent the raw guide](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/raw/main/docs/AGENT_INSTALL.md).

> **NOTE** **The model occupies a *human* seat at the table** - The game does not expose the necessary mechanisms that would allow the model to control the non-player AI seats.

| Requirements | Current release | Ways to play |
| --- | --- | --- |
| Native Linux Steam build, Brave New World | **1.4.0** · Lua runtime **v225** | Solo · hotseat · LAN · multi-LLM |

## On this page

- **Explore**
  - [What you get](#what-you-get)
  - [What it looks like](#what-it-looks-like)
  - [What to expect](#what-to-expect)
- **Play**
  - [Ways to play](#ways-to-play)
  - [How it works](#how-it-works)
  - [Honest limits](#honest-limits)
- **Project**
  - [Documentation](#documentation)
  - [Development](#development)
  - [Authorship](#authorship)
  - [License](#license)

## What you get

- **Information parity.** Fogged tiles carry no live units, unmet civs do not exist, private AI state is
  unreadable. Every screen, hover and refusal reason a human reads is a tool result. `docs/LIMITATIONS.md`
  lists what is withheld and why.
- **The whole game, not a demo.** Units, cities, research, policies, religion, espionage, World Congress,
  trade routes, archaeology, ideology, great works, city-states, and the spaceship.
- **Real diplomacy.** Deals, demands, peace with terms, friendship, denouncement and leader conversations go
  through the game's own screens, with the AI's actual replies. Human-to-LLM trades work in hotseat and LAN.
- **A digest, not a firehose.** `turn_digest` says what happened since the model last looked: combats,
  captures, growth, leader messages, each linked to its notification.
- **Three seats, one server.** Solo, hotseat and LAN share the same tools; a multi-LLM HTTP mode runs one
  seat per API key.
- **Recovery.** In a solo game `end_turn` quick-saves by default (elsewhere `quick_save` is one call),
  `load_latest` resumes after a crash, and a supervisor can relaunch the game and rejoin a LAN game on its own.
- **One call per turn.** `finish_turn` ends the turn, waits (sending progress so the wait is not cut
  short), and returns the new turn's status, digest and the model's own notes. `skip_quiet_turns` lets
  uneventful turns pass; anything a human would look up for (combat, a leader at the door, an empty city,
  happiness falling or a new strategic-resource shortfall, a barbarian camp or hostile unit beside a unit
  on its way somewhere) wakes the model. With `briefing=true` (or the `briefing` tool on its own) the turn
  comes back as one compact read: every decision with its tool, changes since the last briefing, notable
  cities, visible threats and the notes -- 2.5 KB for a 38-unit empire where the separate reads are 30 KB.
- **A unit's surroundings in one read.** `tactical_view(unit_id)` names the six neighbouring plots by
  coordinate (the engine's own adjacency, map wrap included) with what `move_unit` would do with each --
  attack, open, refused with the reason, or a visible enemy -- plus river crossings, the unit's attack
  previews, visible occupants, known cities, fog counts and a lettered grid with its legend. No path cost or
  turns-to-reach: the engine cannot give them safely, so the view does not guess.
- **Batches and retries.** `do` runs a list of orders in one call and stops at the first refusal; an
  `action_id` on any action makes a retried call a replay, never a second move.
- **Knows its seat.** Every status names the player the server is playing; if that is the wrong one
  (a hotseat save loaded under an auto seat), `set_seat` moves it to another human seat without a restart.
- **A notebook.** `remember` / `recall` keep the model's plan, threats and promises beside the game, per
  seat, across sessions and context loss, and the latest notes ride along with every new turn.
- **Assignments that survive a context reset.** `assign` gives units or cities a role, a purpose, a target
  (a plot, a foreign unit, a civ), a completion condition and review triggers. Every `assignments()` and
  `briefing()` read checks each one against what the seat can see now: `condition_met`, `needs_review` with
  the observation behind it (a unit gone -- an upgrade on its last plot named --, a reused id never
  followed, a city lost, a site now too close to a city, a target out of sight kept as last seen, never
  assumed gone), or `on_track`. It reports and never orders; `amend_assignment` and `close_assignment` do
  the rest.
- **Conditional unit orders.** `give_order` hands one unit a short plan -- walk there, build a farm; heal to 80%,
  go back, fortify -- that the harness runs step by step at the start of each turn through the ordinary move and
  mission tools. It checks the unit before every step and pauses with a reason (a hostile in sight, damage, an
  enemy on the destination, a refused step, no progress, a direct command to that unit) instead of taking
  another one; it never attacks, declares war or ends the turn.
- **Side-by-side comparisons.** `compare` lays out a few candidates the model picked -- production items in a
  city, techs, worker builds on plots, a caravan's destinations -- with costs, turns, buy prices, effects, why
  one is refused, and estimates that state their formula. A tile's own gain is kept apart from the empire's
  (nothing until a city works it), and a trade destination is never called safe under fog. It never picks.
- **A rule book.** `reference(section)` is every unit, building, tech, policy, promotion, belief, resource,
  terrain, improvement and unit action with its effect text, read once from the game's own database (mods
  included). Chooser rows carry enums, names and live numbers only, so the same hover is never paid for twice.
- **Tested without the game.** 931 regression tests run the shipped Lua under lupa and the Python layer
  against fake bridges. Live claims are logged per turn against saved states in `saves/`.

## What it looks like

The model plays through tool calls; you watch the game window. On its turn it checks what changed, inspects
its cities and units, chooses actions the game permits, then ends the turn. In hotseat, the window passes
back to you. The working loop looks like this:

```
finish_turn -> (status, digest, notes; or briefing=true) -> briefing / overview / units / cities / known_world
-> act (check available_* first) -> turn_status until nothing blocks -> remember(plan) -> finish_turn
```

A real `turn_status` reply from a live solo game, turn 269, trimmed for width. It predates runtime v217;
a status now also names the `seat`, carries the `gate` to clear first, `happiness` and any
`alerts`, and lists automated or already-moving units under `todo.ongoing`:

<details>
<summary>Expand the turn status</summary>

```json
{"turn": 269, "my_turn": true, "mode": "single", "blocking_name": "NO_ENDTURN_BLOCKING_TYPE",
 "todo": {"promotions": [], "research_unset": false, "cities": [], "units": []},
 "pending_popups": [], "game_over": false, "notifications": {"live": 2, "held": 99}}
```

</details>

When something blocks the turn, `blocking_name` names it and `blocking_hint` points to the tool that clears
it. Refused actions explain why and what to try instead.

## What to expect

- **Setup is one sitting.** Your agent does the install; you handle two things in Steam if they are not
  already true: the game must be the native Linux build (not Proton), and the tuner must be enabled in the
  game's config. Cold start of the game is about two minutes.
- **The game runs in a normal window on your desktop.** Leave it alone during the LLM's turn. In hotseat you
  take your own turn in that window as usual.
- **It is slow and it costs tokens.** A developed empire means dozens of tool calls per turn. A game to
  victory is a long project; an evening is a few dozen turns.
- **The LLM has no hidden game state.** The raw Lua escape hatch is disabled unless you turn it on.
- **The game crashes sometimes.** The Linux port does, with or without the harness. Quick saves every turn
  (solo), the game's own autosaves and `load_latest` make it a pause, not a loss.

## Ways to play

| Mode | Who is where | Start it with |
|---|---|---|
| Solo | LLM in seat 0 versus the game's AI | `harness.cli start-single --civ CIVILIZATION_ROME` |
| Hotseat | You and the LLM(s) at one machine, turn by turn | `harness.cli host-hotseat --humans 0 1 --nick 1=Claude` |
| LAN | Each LLM runs its own game instance and joins like any player | `scripts/launch_llm_client.sh`, then `harness.cli join-lan <host>` |
> Notice that the model occupies a **human** seat at the table - it cannot take the place of the built-in AI due to limitations in the game itself

The install guide walks through each. Saved states in `saves/` reproduce late-game diplomacy, peace terms,
Venice puppets and a combat lab if you want to drop an LLM into something interesting on turn one.

## How it works

```mermaid
flowchart LR
    A["LLM client"] -->|stdio| B["MCP server<br/>142 tools"]
    B -->|Unix socket| C["tunerd<br/>one tuner connection"]
    C -->|TCP 4318| D["Civilization V<br/>preload shim + FireTuner"]
```

Civilization V ships a debugging channel, FireTuner, that is a remote Lua console into the game's own UI
contexts. The harness keeps that channel open in multiplayer with a small preload shim, injects a Lua
runtime that ports the stock UI's own logic (combat previews, trade legality, hovers), and drives every
screen the way a mouse would. Because the network only carries player commands in a lockstep simulation, a
real game instance is the only faithful client; that is why the LLM gets one. `docs/ARCHITECTURE.md` has
the long version.

## Honest limits

- Linux only, native Steam build only, Brave New World only. No Windows, no macOS, no Proton.
- With the tuner enabled the game listens on every interface by default. The install guide binds it to
  loopback; do not skip that on a shared network.
- A few end-turn blockers (some World Congress votes, some free-choice popups) have no tool yet; the model
  is told to stop and ask you. `docs/GAPS.md` is the running audit.
- Movement-cost previews and path overlays are not readable: the engine calls that back them crash the game.
- No hosted CI by choice; the suite runs locally before every push.

## Documentation

- [`docs/AGENT_INSTALL.md`](docs/AGENT_INSTALL.md): the complete install brief for an agent.
- [`docs/PLAYBOOK.md`](docs/PLAYBOOK.md): how a seat should play, turn by turn, with the blocker table.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): layers, information boundary, game modes, repo layout.
- [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md): what the harness will not do, each item checked against the engine.
- [`docs/GAPS.md`](docs/GAPS.md), [`docs/ROADMAP.md`](docs/ROADMAP.md), [`CHANGELOG.md`](CHANGELOG.md): live audit, plan, and the map from package versions to runtime versions.
- [`docs/DECK_HOWTO.md`](docs/DECK_HOWTO.md): running a seat on a Steam Deck.
- [`saves/README.md`](saves/README.md): the reproduction states and what each one shows.

## Development

```bash
uv sync --group dev
scripts/check.sh            # 931 tests, no game needed; run before every push
```

The Lua runtime (`harness/lua/runtime.lua`) carries its own version counter, bumped on every change, because
a running game keeps the old runtime until a newer number arrives. Commit subjects carry it as `runtime vNNN`.

Issues and milestones live on GitLab: <https://gitlab.com/Tyler-Meador/civ-v-linux-mcp>.

## Authorship

This project was written by Claude, Anthropic's AI model, working in Claude Code under the direction of
Ty Meador, who owns the game, ran every live session and decided what the harness should and should not do.
Across 430 commits between 2026-09-15 and 2026-09-26, Claude Fable 5.1 co-authored 239, Claude Opus 5 133,
Claude Sonnet 5 10 and Claude Opus 5.5 3: the reverse engineering of the FireTuner protocol and the game
binary, the shim, the Lua runtime, the MCP server, the tests, the documentation and this README. Ty's
contribution is the design brief, the live verification against the running game, the judgement calls
recorded in `docs/GAPS.md`, and the standard that the seat may see only what a human sees.

## License

[MIT](LICENSE). Sid Meier's Civilization V, its assets and the stock UI Lua quoted in `docs/` belong to
Firaxis Games and Take-Two Interactive and are not covered by this licence; you need your own copy of the
game.
