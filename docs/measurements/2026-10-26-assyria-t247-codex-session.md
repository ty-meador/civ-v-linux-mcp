# Assyria t247 through the nine tools from a fresh Codex session (2026-10-26)

Stage 4 of "The tool surface" (GitLab #56), the Codex half: a fresh Codex CLI session (`codex-cli 0.160.0`,
model `gpt-6.1-sol`, clientInfo `codex-mcp-client`) played t247 of the solo Assyria game (seat 0, Prince,
Pangaea, Tiny, Quick) with the nine tools alone: its server was registered in `~/.codex/config.toml` as
`harness.mcp_server --seat 0` with `CIV5_RETIRED_NAMES=off`, so the listing carried the nine and nothing
else (the retirement map not needed, as the issue says). The prompt asked for exactly one turn: the briefing,
the todo from rows, one city-state gold gift from its full view's row, a read of the league without voting, a
note, `turn(action="finish")`, any gate through `question()` / `answer()`, one `turn(action="wait")`. The
ledger rows are beside this file (`2026-10-26-assyria-t247-codex-session-ledger.jsonl`); the Codex transcript
is the rollout under `~/.codex/sessions/2026/10/26/` (Codex calls MCP tools from inside `exec` scripts, so
the calls read `tools.mcp__civ5__turn({...})` there).

## The turn

| # | Call | Trips | What came back |
|---|---|---|---|
| 1 | `turn(action="briefing", since="turn")` | 10 | t247, no decisions, the expiring deals as warnings (Portugal's Salt for Truffles ends this turn) |
| 2 | `turn(action="status")` | 4 | the todo, empty -- Codex went looking for `status.todo`, which the briefing calls `decisions` (see below) |
| 3 | `inspect(what="civs")` | 2 | the known civs |
| 4 | `inspect(what="units", view="actions", id=[nine ongoing units])` | 2 | every one on its automation or route; nothing to order |
| 5 | `inspect(what="city_state", id=31, view="full")` | 11 | Ur: influence 49, the gift tiers with their rows |
| 6 | `inspect(what="league")` | 2 | between sessions: no votable row (the next session is t251) |
| 7 | `order(to="city_state", id=31, action="gift_gold", args={amount: 500})` | 6 | copied from Ur's row: influence 49 -> 89, `allied: true`, gold 2566 |
| 8 | `notebook(action="remember", args={text})` | 1 | note 7 (the gift, the Portugal deal to re-offer at t248) |
| 9 | `turn(action="finish", actions=[])` | 31 | the turn ended; t248 came back with nothing blocking |
| 10 | `turn(action="wait")` | 8 | t248, my turn, `gate: null` |

Ten calls, 77 trips, 1 min 25 s of Codex time. Every order was a row copied from a read; no refusal; no call
named a tool the listing did not carry. The city-state gift (#56's "both reach a city-state gift") ran from
the full view's row; the league vote through the nine is the t244 session
(`2026-10-26-assyria-t244-league-vote.md`), and at t247 the league read carried no votable row to copy.

## What the fresh session met

- **`order`'s schema, as Codex renders it, lost `id` and `args`** (Codex's own report: "order's schema omitted
  id and args, although the returned gift row required both and executed successfully"). This is #49's
  measurement for Codex: it renders a tool's input schema as a TypeScript declaration, and the `oneOf`
  variant became a union of the branches alone -- `{action?: "move" | ...; to?: "unit"} | {...} | ...` --
  with the top-level `id`, `args` and `action_id` gone and both words optional. The model copied the row
  with both and the server ran it, so the rows carried what the declaration did not. Fixed the same night:
  `codex` joins `FLAT_CLIENTS` in `harness/surface/listing.py`, so a `codex-mcp-client` handshake is shown the
  flat variant. Measured again through `codex exec` on the changed server: the declaration now reads
  `action: string` (its description the verbs by target), `action_id?`, `args?`, `id?`, `to: "unit" | "city" |
  ...`. Claude Code renders the `oneOf` (2026-10-25); the table is in `docs/ARCHITECTURE.md`.
- **The briefing's todo is `decisions`.** The instructions say "act on status.todo", the briefing reply names
  the same items `decisions`; Codex called `turn(action="status")` once more (4 trips) to be sure. The
  instructions now say `status.todo (the briefing's decisions)`.
- The Codex config carried per-tool `approval_mode` entries for ~50 retired names; replaced by the nine.
