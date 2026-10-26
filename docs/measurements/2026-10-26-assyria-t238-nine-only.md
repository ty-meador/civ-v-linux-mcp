# A turn through the nine tools alone: Assyria t238 -> t239 (stage 4, GitLab #56), 2026-10-26

`scripts/turn_from_rows.py --seat 0 --gift 22` against a fresh stdio server started with `CIV5_RETIRED_NAMES=off`:
the listing is the nine (`answer, batch, inspect, notebook, order, question, reference, session, turn`), an old
name is unknown, and every order is a row copied out of a read. The transcript is
`2026-10-26-assyria-t238-nine-only-transcript.jsonl` (one line per call, the reply cut short), the ledger
`2026-10-26-assyria-t238-nine-only-ledger.jsonl`.

| Call | Trips | Seconds | What it did |
|---|---|---|---|
| `turn(action="briefing", since="turn")` | 9 | 0.6 | t238: no decisions (the save's turn had been played before the quick save); the expiring Zulu deal in `warnings` |
| `inspect(what="city_state", view="full", id=22)` | 11 | 0.6 | Yerevan: the screen's buttons as rows (pledge, declare_war), the gift tiers each with `call` |
| `inspect(what="league")` | 2 | 0.1 | the UN: no vote rows, the session is in 6 turns (t244) |
| `turn(action="finish", actions=[<the small tier's call>], timeout_seconds=900, args={"briefing": true})` | 40 | 6.5 | the 250-gold gift to Yerevan ran (`batch.done: 1`), the turn ended, t239 came back with its briefing |

Four calls, 62 trips, 7.9 s. The gift was the row `{"tool": "order", "args": {"to": "city_state", "action": "gift_gold",
"id": 22, "args": {"amount": 250}}}` as the read handed it back; no name the listing does not carry was used.

A first run failed before any order: the driver put `briefing` at the top of the `turn` call, where the tool keeps
it under `args` (the vocabulary's `TOP_LEVEL`); the validation error named the field and nothing ran.

## t239, reads only (`--dry-run`)

The turn that followed has real decisions. `turn(action="briefing", since="turn")` listed a Worker and a Great
Merchant needing orders and two cities with an empty queue (Nineveh and Nimrud, their Spaceship Factories done),
each with its rows; the driver ran the reads and took the first `call` of each
(`2026-10-26-assyria-t239-nine-only-dry-run-transcript.jsonl`, 6 calls, 19 trips):

- `order(to="unit", id=106504, action="mission", args={"mission": "AUTOMATE_BUILD"})` -- the Worker's row
- `order(to="unit", id=1343522, action="mission", args={"mission": "MISSION_BUILD", "build": "BUILD_CUSTOMS_HOUSE"})` -- the Merchant's
- `order(to="city", id=16385, action="produce", args={"item": "UNIT_SETTLER"})` and the same for 24578 -- the first item of each production read

Nothing was ordered: the first item of a production list is not a choice for the science race, and the campaign is
the user's. The t239 turn, the renewals due this turn and the league vote at t244 are left to the user's own
session (a fresh Claude Code session and a fresh Codex session are the two checks still open on #56).

## The trip count

`2026-10-26-assyria-t238-profile-before-after.md`: `scripts/play_loop.py --profile` on the same save before the
surface (the commit before stage 0) and after -- 72 trips both times, 9.1 s against 8.9 s wall.

## The listing

9 tools, 11,229 bytes, ~2.8k tokens (`tool_survey.md`), against 145 tools, 112,417 bytes, ~28k tokens before.
