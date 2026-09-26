# civ-v-llm-harness

**Give an LLM a civilization. See what survives.**

![Civilization V armies gathering across a river and contested border, official game screenshot](https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/8930/ss_84ee7ab3b0148a260359f8d5a78a2ab9033aa695.1920x1080.jpg)

*Game image from [Civilization V on Steam](https://store.steampowered.com/app/8930/Sid_Meiers_Civilization_V/).*

A rival settles the river first. Your peaceful science plan now has a border problem. The model in that seat
sees the same fogged map you would, knows only the civilizations it has met, and has to decide anyway.

This harness puts a language model in a real seat in **Sid Meier's Civilization V**. Challenge it in hotseat
or over LAN, hand it your seat against the game's AI, or put several models in the same match.

It sees the world the way you do, in text. Every revealed tile comes back as terrain, yields, resources, what
a worker could build there and who is standing on it. Unexplored land is a frontier it can go and look at, not
a list of coordinates to memorize. It has to scout, settle, negotiate, fight and adapt, and it never gets more
than a human in that seat would. Fogged tiles stay fogged. Unmet civilizations stay unknown. The AI's private
plans stay private.

Most games bolt an LLM on as a chat layer. This one goes inside the game so a model plays by the same rules as
everyone else at the table.

**Want to play?** Give an LLM of your choice the [agent install guide](docs/AGENT_INSTALL.md) and ask it to
set up the harness and start a game. The guide has the commands and checks; this page is for you.
[Raw guide for your agent](https://gitlab.com/Tyler-Meador/civ-v-linux-mcp/-/raw/main/docs/AGENT_INSTALL.md).

*Requires the native Linux Steam build of Civilization V with Brave New World. Version 1.0.0, Lua runtime
v212.*

Quick links: [What you get](#what-you-get) · [What it looks like](#what-it-looks-like) ·
[What to expect](#what-to-expect) · [Ways to play](#ways-to-play) · [How it works](#how-it-works) ·
[Honest limits](#honest-limits) · [Documentation](#documentation) · [Development](#development) · [Authorship](#authorship)

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
- **Recovery.** `end_turn` quick-saves by default, `load_latest` resumes after a crash, and a supervisor can
  relaunch the game and rejoin a LAN game on its own.
- **Tested without the game.** 528 regression tests run the shipped Lua under lupa and the Python layer
  against fake bridges. Live claims are logged per turn against saved states in `saves/`.

## What it looks like

The model plays through tool calls; you watch the game window. On its turn it checks what changed, inspects
its cities and units, chooses actions the game permits, then ends the turn. In hotseat, the window passes
back to you. The working loop looks like this:

```
wait_for_my_turn -> turn_digest -> turn_status -> overview / units / cities / known_world
-> act (check available_* first) -> turn_status until nothing blocks -> quick_save -> end_turn
```

A real `turn_status` reply from a live solo game, turn 269, trimmed for width:

```json
{"turn": 269, "my_turn": true, "mode": "single", "blocking_name": "NO_ENDTURN_BLOCKING_TYPE",
 "todo": {"promotions": [], "research_unset": false, "cities": [], "units": []},
 "pending_popups": [], "game_over": false, "notifications": {"live": 2, "held": 99}}
```

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
  and `load_latest` make it a pause, not a loss.

## Ways to play

| Mode | Who is where | Start it with |
|---|---|---|
| Solo | LLM in seat 0 versus the game's AI | `harness.cli start-single --civ CIVILIZATION_ROME` |
| Hotseat | You and the LLM at one machine, turn by turn | `harness.cli host-hotseat --humans 0 1 --nick 1=Claude` |
| LAN | The LLM runs its own game instance and joins like any player | `scripts/launch_llm_client.sh`, then `harness.cli join-lan <host>` |
| Multi-LLM | One instance and one bridge per LLM seat, served over HTTP | `scripts/launch_seat.sh <name>`, `python -m harness.http_server` |

The install guide walks through each. Saved states in `saves/` reproduce late-game diplomacy, peace terms,
Venice puppets and a combat lab if you want to drop an LLM into something interesting on turn one.

## How it works

```
LLM client  --stdio-->  harness.mcp_server  --unix socket-->  harness.tunerd  --TCP 4318-->  Civ5XP
                        (122 tools, game.py)                   (owns the one     (+ LD_PRELOAD shim,
                                                                tuner connection)  EnableTuner = 1)
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
scripts/check.sh            # 528 tests, no game needed; run before every push
```

The Lua runtime (`harness/lua/runtime.lua`) carries its own version counter, bumped on every change, because
a running game keeps the old runtime until a newer number arrives. Commit subjects carry it as `runtime vNNN`.

Issues and milestones live on GitLab: <https://gitlab.com/Tyler-Meador/civ-v-linux-mcp>.

## Authorship

This project was written by Claude, Anthropic's AI model, working in Claude Code under the direction of
Ty Meador, who owns the game, ran every live session and decided what the harness should and should not do.
Across 401 commits between 2026-09-15 and 2026-09-25, Claude Fable 5.1 co-authored 215, Claude Opus 5 133
and Claude Sonnet 5 10: the reverse engineering of the FireTuner protocol and the game binary, the shim, the
Lua runtime, the MCP server, the tests, the documentation and this README. Ty's contribution is the design
brief, the live verification against the running game, the judgement calls recorded in `docs/GAPS.md`, and
the standard that the seat may see only what a human sees.

## License

[MIT](LICENSE). Sid Meier's Civilization V, its assets and the stock UI Lua quoted in `docs/` belong to
Firaxis Games and Take-Two Interactive and are not covered by this licence; you need your own copy of the
game.
