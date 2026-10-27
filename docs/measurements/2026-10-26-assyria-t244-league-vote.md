# Assyria t244: the UN session through the nine tools (GitLab #56, stage 4's league vote)

Live, 2026-10-26 night, the solo Assyria game (seat 0, Prince, Quick), runtime v287 installed by the first call of a
fresh `scripts/mcp_session.py` server on this code (the Claude Code session server ran the code of 4d84483).

## What happened

| Step | Call | Result |
|---|---|---|
| t240 | `inspect(what="civ", id=3, view="trade_catalog")` -> `order(to="civ", action="negotiate", ...)` from the Fur and Dye rows -> `order(to="civ", action="propose_deal", ...)` | "Very well.": Fur for Dye to t265, happiness 63 -> 67 |
| t241 | `inspect(what="options", view="trade_routes", id=1351706)` -> its Belgrade row | route established (27 turns) |
| t242 | `turn(action="finish", actions=[policy row, AUTOMATE_BUILD row])` | Universal Healthcare adopted, the Worker automated, t243 came back |
| t243 | `batch` of two `MISSION_FORTIFY` rows; a caravan's Zurich row | both fortified; route established (70 turns) |
| t244 | `inspect(what="league")` | `in_session: true`, two `votable` rows, **no `actions` / `call` on either** |
| t244 | `order(to="league", action="vote", args={votes: [{resolution_id: 14, direction: "enact", num_votes: 28, choice: "no"}]})` | **refused: `league.lua:493: bad argument #1 to 'ipairs' (table expected, got string)`** |
| t244 (fixed code) | `inspect(what="league")` | each votable row carries two `actions` rows (yes / no, 28 delegates), the reply `actions` the vote call |
| t244 (fixed code) | the Furs row's no vote, as it was | `{"ok": true, "votes_cast": 28, "abstained": 0}`; blocker -> ENDTURN_BLOCKING_UNITS |
| t245 | `turn(action="finish", actions=[the caravan's Yerevan row, AUTOMATE_BUILD])` | ISS passed (6 Yea Siam, 1 Zulu, 1 Nay Portugal); Ban Furs failed (28 Nay Assyria, 5 Portugal, 3 Zulu; 10 Yea Siam) |
| t245 | `inspect(what="league")` on the fixed code | `proposable_enact` rows carry `call` (a `choose: ["choice"]` where the resolution takes one), `proposable_repeal` rows too |

## What it found

1. **The vote's list reached Lua as a string.** `league_cast_votes` was the last caller of `_lua_items`, which
   rendered a Python list as Lua source for the old text path; since runtime v285 every entry goes through
   `{"op": "call"}` and `lua_wire.lua_table` encodes a list itself, so the pre-rendered string was quoted once
   more. Fixed by passing the list; the encoders are deleted; `tests/test_league_vote_choice.py` asserts the
   wire form (`({{["resolution_id"]=17, ...}})`, no quoted table).
2. **The league read handed back no rows.** `harness/affordances/objects.py` `league_rows` (applied in
   `league_status`) is the missing maker; the audit's choice reads include `("inspect:league", "default")`.

Ledger rows: `logs/calls.jsonl` turn 244, clients `claude-code/2.1.310` (the failed vote, 2 trips) and
`mcp/0.1.0` (the fresh server: `inspect league` 3 trips, `order league/vote` 5 trips, `turn status` 4 trips).
