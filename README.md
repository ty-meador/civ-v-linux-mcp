# civ_v_llm_harness

Lets an LLM play **Sid Meier's Civilization V** (Steam, Linux) in the same game as humans and the
built-in AI, through an MCP server. The LLM's "client" is a real game instance driven over the
game's own FireTuner Lua socket; humans play at the same machine (hotseat) or, later, over LAN.

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

## Gotchas
- Never bind TCP 4318 before the game does: the game aborts at init.
- The tuner listens on 0.0.0.0:4318: firewall it on untrusted networks (anyone can run Lua in your game).
- Restarting `tunerd` is fine (the shim lets the game re-accept); without the shim the game accepts one
  tuner client per launch.
