# civ_v_llm_harness

Lets an LLM play **Sid Meier's Civilization V** (Steam, Linux) in the same game as humans and the
built-in AI, through an MCP server. The LLM's "client" is a real game instance driven over the
game's own FireTuner Lua socket; humans play at the same machine (hotseat) or over LAN (the LLM
runs its own game instance and joins like any other player).

Read `docs/ARCHITECTURE.md` for the design and `docs/NOTES.md` for verified findings.

## One-time setup
1. `config.ini` (`~/.local/share/Aspyr/Sid Meier's Civilization 5/config.ini`): `EnableTuner = 1`
   (already set). Optional: `LoggingEnabled = 1`.
2. Build the 32-bit shim: `cd shim && gcc -m32 -O2 -shared -fPIC -o libtuner_recv_fix.so tuner_recv_fix.c -ldl`
3. Python env: `uv venv .venv && uv pip install -p .venv/bin/python "mcp>=1.2"`

## Running a hotseat game with Claude in seat 1
```bash
scripts/launch_civ5.sh              # game via Steam's container runtime + shim (Steam must be running)
python3 -m harness.tunerd &         # owns the single tuner connection (unix socket in $XDG_RUNTIME_DIR)
python3 -c 'from harness.game import Game; g = Game(); g.host_hotseat(human_seats=[0, 1], nicknames={1: "Claude"}); g.wait_ingame()'
```
Seat 0 is you, seat 1 is the LLM. Then start an MCP client with `.mcp.json` (Claude Code picks it up
in this directory) and let the model call `wait_for_my_turn`, `turn_digest`, `overview`, `units`,
`cities`, `map_window`, the action tools and `end_turn`. On your seat, click **Continue** on the
hand-off screen and play; when the screen names Claude, the harness dismisses it itself.

## Running a LAN game (Claude as its own network player)
The humans host or join a normal LAN game (any machine, e.g. a Steam Deck). Claude gets a game instance
of its own. On the humans' machine that is a *second* instance:
```bash
scripts/launch_llm_client.sh                         # own profile (~/.local/share/civ5-llm), tuner on 127.0.0.1:4319
python3 -m harness.tunerd --port 4319 --sock $XDG_RUNTIME_DIR/civ5-llm.sock &
export CIV5_TUNERD_SOCK=$XDG_RUNTIME_DIR/civ5-llm.sock   # every harness command below targets that instance
python3 -m harness.cli lan-games                     # games advertised on the LAN (serverID, name, map, players)
python3 -m harness.cli join-lan 0 --nick Claude      # by serverID, or an IPv4 address; marks itself ready
python3 -m harness.cli slots                         # staging room: who is connected / ready
# the host launches; then either loop scripts/play_turn.sh, or attach an MCP client (.mcp.json honours CIV5_TUNERD_SOCK)
python3 -m harness.cli wait-ingame                   # prints the auto-detected seat and turn state
while scripts/play_turn.sh; do :; done
```
If the LLM's instance is the only one on this machine, plain `scripts/launch_civ5.sh` + default tunerd is fine.
To have Claude host instead: `python3 -m harness.cli host-lan --open 1 2 --nick Claude`, then `launch` when
everyone is in. `python3 -m harness.cli leave` backs out to the main menu from anywhere.

## Multi-LLM pitboss (multiple frontier models, one shared game)
Each LLM gets its own always-connected Civ5 instance (same pattern as the LAN section above, generalized to
N seats) and talks to it over a small HTTP/JSON API instead of MCP, so any provider's tool-calling can drive
a seat, not just Claude Code.
```bash
cp harness/seats.example.json harness/seats.json    # fill in real api_key values (one per LLM)
scripts/launch_seat.sh claude                        # one Civ5 instance per seats.json entry
python3 -m harness.tunerd --port 4319 --sock $XDG_RUNTIME_DIR/civ5-claude.sock &   # one tunerd per seat
# ... repeat launch_seat.sh + tunerd for every other seat (gpt5, gemini, ...)
python3 -m harness.http_server --host 0.0.0.0 --port 8765   # serves every seat in seats.json
```
Host or join the shared game once everyone's instance is up (`python3 -m harness.cli host-lan --open 1 2 3`
from any one instance, or `join-lan` from the others). Each LLM authenticates with `X-API-Key: <its seat's
key>` and only ever sees/acts on that seat -- there is no way to address another seat's game through this
API. Routes mirror the MCP tools 1:1 (`GET /status`, `/overview`, `/units`, `/cities`, `/turn_digest`, `POST
/move_unit`, `/end_turn`, ...); interactive docs and a machine-readable spec other providers can ingest are
at `http://<host>:8765/docs` and `/openapi.json`. The raw `lua` escape hatch is refused per-seat unless that
seat's `seats.json` entry sets `"allow_lua": true` (off by default -- see Gotchas).

## Diplomacy
`turn_digest` includes `leader_message` events when an AI (or the game) wants to say something -- a demand,
an offer, a war declaration -- with the message text and a symbolic state name (e.g. `TRADE_AI_MAKES_OFFER`).
Act on it with `declare_war(player_id)`, `make_peace(player_id)`, `denounce(player_id)`, or the general
`diplo_event(event, player_id, data1, data2)` tool (see `docs/NOTES.md` for the full event list); these call
the engine directly and never open the leader-head screen. Item-based trade deals are not implemented yet.

## Gotchas
- Never bind TCP 4318 before the game does: the game aborts at init. A second instance needs `CIV5_TUNER_PORT`
  (the shim remaps the game's bind), which `launch_llm_client.sh` sets.
- The tuner listens on 0.0.0.0:4318 by default: set `CIV5_TUNER_BIND=127.0.0.1` or firewall it on untrusted
  networks (anyone can run Lua in your game).
- In LAN games `end_turn` a second time would un-ready the player; the harness refuses it and reports
  `turn_complete_sent` instead.
- The HTTP server's `lua` route is off by default per seat: an unguarded raw Lua call already crashed the
  game once (see docs/NOTES.md), and that risk is bigger with an arbitrary, less-known model reachable over
  the network than with Claude on a local MCP connection. `harness/seats.json` is gitignored (API keys).
- Restarting `tunerd` is fine (the shim lets the game re-accept); without the shim the game accepts one
  tuner client per launch.
