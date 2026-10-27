# Assyria t239 through the nine tools from a fresh Claude Code session (2026-10-26)

Stage 4 of "The tool surface" (GitLab #56), the Claude Code half: a session that had just been cleared
(`/clear`, then `/mcp` reconnect) played t239 of the solo Assyria game (seat 0, Prince, Pangaea, Tiny, Quick)
with the nine tools as its client listed them. The server was the Claude Code session server (`--seat auto`,
started from main at 1d0bc7a, the stage 4 commit) on the plain daemon; the Lua runtime moved to v286 (#57) on
this session's first call. The ledger rows are beside this file
(`2026-10-26-assyria-t239-claude-code-session-ledger.jsonl`).

## The turn

| # | Call | Trips | What came back |
|---|---|---|---|
| 1 | `turn(action="status")` | 392 | the install of runtime v286 (the client ships the source on a plain daemon), then t239's status in the new words |
| 2 | `turn(action="status")` | 4 | the usual count again |
| 3 | `turn(action="briefing", since="turn")` | 8 | four decisions with their rows: Worker 106504, Great Merchant 1343522, Nineveh and Nimrud with empty queues |
| 4 | `inspect(what="units", view="actions", id=[106504, 1343522], detail="summary")` | 2 | the Worker's `AUTOMATE_BUILD` row; the Merchant's `BUILD_CUSTOMS_HOUSE` row (no trade mission from (18,22), outside any city-state's land) |
| 5 | `notebook(action="recall")` | 0 | no notes under this game key (see below) |
| 6-7 | `inspect(what="city", view="production", id=...)` twice | 2 + 2 | nothing left for the science race but the processes: `PROCESS_RESEARCH` chosen for both |
| 8 | `inspect(what="map", view="index")` | 2 | the city-states: Belgrade (17,19) and Malacca (21,21) nearest the Merchant |
| 9 | `inspect(what="city_state", id=34, view="summary")` | 3 | Belgrade: influence 52, allied to someone else (Siam, it turned out) |
| 10 | `inspect(what="unit", id=1343522, view="tactical", radius=3)` | 2 | (17,21) is Belgrade's tile, one step SW, `move: open` |
| 11 | `order(to="unit", id=1343522, action="move", args={x: 17, y: 21})` | 8 | arrived, 1 move left |
| 12 | `inspect(what="units", view="actions", id=[1343522], detail="summary")` | 2 | the `MISSION_TRADE` row now offered |
| 13 | `order(to="unit", id=1343522, action="mission", args={mission: "MISSION_TRADE"})` | 5 | consumed; gold 2120 -> 2890 |
| 14 | `inspect(what="city_state", id=34, view="summary")` | 3 | influence 82, `allied: true` (the tenth ally, +2 UN delegates) |
| 15 | `notebook(action="remember", args={text})` | 1 | note 1 |
| 16 | `turn(action="finish", actions=[3 rows], notes="<free text>")` | 0 | **refused**: `notes` is `new` / `all`, not free text (the description now says so) |
| 17 | `turn(action="finish", actions=[the Worker's automate row, both cities' produce rows])` | 30 | all three ran; the turn ended; woke on Portugal's denouncement screen (`gate: discussion`) |
| 18 | `answer(choice=1)` | 24 | "Very well."; the next screen: Shaka's offer, 1 Fur for 5 Iron over 25 turns |
| 19 | `answer(choice="refuse")` | 11 | the table closed |
| 20 | `turn(action="wait")` | 13 | t240, my turn, nothing blocking |

Twenty calls, 122 trips after the install (514 with it). Every order was a row copied from a read; no call
named a tool the listing did not carry. The city-state gift path (#56's "both reach a city-state gift") was
exercised by the trade mission row rather than a gold gift; the league vote is the t244 session, still open.

## What the fresh session met that it should not have

- Four reply strings still named retired tools, all on the Python side and outside the audit's keys:
  `drill_down` (`{tool: "todo_actions"}`) on every `units` actions read, `how_to_answer` on the leader and
  trade screens (`incoming_deal() ... accept_deal() or refuse_deal()`, `respond_discussion(button_id) ...
  dismiss_discussion()`), `leader_screen_note` on the status, and the frozen-game refusal. Fixed in this commit:
  the row goes through `rows.act`, the three strings say `question()` / `answer(choice=...)`, and the three
  keys are in `audit.KEYS`.
- `turn`'s description said "`notes`, `timeout_seconds`" and the session passed a sentence; the refusal was
  clear and nothing ran. The description now says `notes='new' / 'all'`.
- The notebook answered no notes under game key `L36-C36-pangaea-Assur-t0-s0-seat0` although the handoff cites
  note 2 of t236. The remember landed as note 1. Where the earlier notes live (another `CIV5_NOTES_DIR`, another
  key) is not yet known.
- Widening the audit to `err` / `note` keys finds 27 more refusal sentences naming old tools
  (`accept_deal/refuse_deal`, `trade_catalog()`, `available_research`, `move_unit`, ...): the next words item.
