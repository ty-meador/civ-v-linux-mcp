# Assyria t238 through the nine tools from a fresh Grok session, and #49's Grok row (2026-10-27)

The Grok half of the client measurement on GitLab #49, taken the way the Codex half was
(`2026-10-26-assyria-t247-codex-session.md`): a fresh Grok CLI session (Grok Build 1.0.70, model `grok-4.7`,
clientInfo `grok-shell-civ5/1.0.70`, the server registered by the repo's `.mcp.json` as
`harness.mcp_server --seat auto`) played t238 of the solo Assyria game (seat 0, Prince, Pangaea, Tiny, Quick;
the save `single/Ashurbanipal_0238 international-games`, loaded for it after the t278 victory). The prompt
asked for exactly one turn: the briefing, the todo from rows, one city-state gold gift from its full view's
row, a read of the league without voting, one deliberately malformed order reported word for word, a note,
`turn(action="finish")`, any gate through `question()` / `answer()`, one `turn(action="wait")`, and a report
of what `order`'s input schema looked like to it. The ledger rows are beside this file
(`2026-10-27-assyria-t238-grok-session-ledger.jsonl`; the last row is Claude Code's own malformed order, see
below); the Grok transcript is `~/.grok/sessions/<encoded cwd>/01a17f7b-.../chat_history.jsonl`, and
`tool_definitions.json` there is what the model was shown.

## The turn

| # | Call | Trips | What came back |
|---|---|---|---|
| 1 | `search_tool("civ5 turn inspect order ...")` | -- | Grok's own step: it finds MCP tools by keyword and receives their `input_schema` verbatim; every MCP call then goes through `use_tool(tool_name, tool_input)` |
| 2 | `turn(action="briefing", since="turn")` | 12 | t238, `decisions: []`, the two expiring deals as warnings; the baseline said a save was loaded (last briefing t247); eight notebook notes rode along, seven of them from t239-t278 |
| 3 | `inspect(what="city_states")` | 0 | refused: no such object, the objects listed |
| 4 | `inspect(what="city_state")` | 0 | refused: no default view (`full`, `summary`) |
| 5 | `reference(book="playbook", section="city_states")` | 0 | unknown topic, the topics listed |
| 6 | `reference(book="playbook", section="diplomacy")` | 0 | the section that says a city-state is `inspect(what="city_state", id, view="full")` |
| 7 | `inspect(what="civs")` | 2 | the civs with the city-states as `minor: true` rows; Zurich is id 30 |
| 8 | `inspect(what="city_state", id=30, view="full")` | 11 | Zurich: influence 46, the gift tiers with their rows |
| 9 | `order(to="city_state", id=30, action="gift_gold", args={amount: 1000})` | 6 | copied from the large-gift row: influence 46 -> 131, `allied: true`, gold 2334 -> 1334 |
| 10 | `inspect(what="league")` | 2 | the UN between sessions, no votable row; ISS and Ban Furs pending |
| 11 | `order(to="unit", id=335873, action="produce")` | 1 | **the deliberate malformed order**: the client sent it; the server refused it, `order:unit has no 'produce'`, the unit's seven verbs under `choices` |
| 12 | `notebook(action="remember", args={text})` | 1 | note 12 |
| 13 | `turn(action="finish", actions=[])` | 31 | the turn ended; t239 came back, my turn, `gate: null` |
| 14 | `turn(action="wait")` | 8 | t239 at once |

Thirteen server calls, 74 trips, 9.4 s of game time inside 75 s of wall clock; the Grok session took 4 min 10 s
and 14 model calls (511k tokens, 419k of them cached reads). Three refusals, all reads by a wrong name; the
one order copied from a row ran; the deliberate malformed order reached the server. No call named a tool the
listing did not carry.

## #49: what the Grok client renders

- **It passes the schema through verbatim.** `search_tool`'s result carries `input_schema` exactly as the
  server lists it: `to` the enum, `action` a string "whose words depend on `to` (oneOf below)", `id`, `args`,
  `action_id`, `required: [to, action]`, and the `oneOf` with its seven branches (`to` by `const`, `action`
  its enum; the city-state branch a free string). Grok's own words: "Both shapes were visible at once."
- **It does not validate against it.** `use_tool` says the arguments "must match the input schema" but sends
  them unchanged: `order(to="unit", action="produce")` went to the server and came back as the server's
  refusal, in the server's shape (`ok`, `err`, `choices`). No client-side error exists to tell apart.
- So the Grok row is: shows the enums **yes** (raw `oneOf`), validates **no**, passes a malformed call through
  **yes**. The oneOf variant is the right one for Grok: nothing is lost in rendering and the per-target enums
  reach the model.

**Claude Code, measured again the same evening (2.1.311).** The row of 2026-10-25 said Claude Code shows the
`oneOf` with its branches. On 2.1.311 `ToolSearch` renders `order` with the plain properties and one added
line, *"Input constraint: Provide parameters for exactly one of: (to, action)"*: the `oneOf` has become a
sentence about mutually exclusive parameter groups, which is not what it says, and the branches' enums are
gone from view. The same malformed order sent from Claude Code reached the server unvalidated (the ledger's
last row, `claude-code/2.1.311`, `order:unit has no 'produce'`). Since the flat variant's description already
lists the verbs by target, Claude Code loses nothing by being shown flat and loses the misleading line:
`claude-code` joins `FLAT_CLIENTS` beside `codex`. Grok, the one client that renders the `oneOf` as it is,
keeps it. Both rows are in `docs/ARCHITECTURE.md`.

## What the fresh session met

- **Where city-state ids come from.** Grok tried `inspect(what="city_states")` (refused: no such object) and
  `inspect(what="city_state")` (refused: no default view), then the playbook topic `city_states` (unknown),
  and found the answer in the `diplomacy` section: city-states are the `minor: true` rows of
  `inspect(what="civs")`. Four calls for a fact the refusals could have carried. Now: an `inspect` refusal for
  an object that takes an id says where the ids come from (`hint`: "city-state ids are the `minor: true` rows
  of inspect(what='civs')", likewise unit, city and civ), a plural miss (`city_states`) names the object
  it meant, and the playbook answers `city_state`, `city_states`, `deals` and `trade` with the diplomacy
  section.
- **Notes from a later timeline read as the present.** The save is t238; the seat's notebook holds the notes
  of the game played on to t278. The briefing's baseline said a save was loaded and compared nothing, but the
  eight notes it carried (t98 and t239-t278) came with no such mark, and Grok's note for the next turn tells it
  to "order the new Great Scientist and Great Musician" -- units that exist in the t257 note, not on the
  t239 board (`inspect(what="units")` at t239: a Great General and a Great Engineer, no Scientist, no
  Musician). Now a note written on a turn later than the one on screen carries `later_timeline: true` and the
  notes section a `notes_later_timeline` sentence saying a save was loaded and the plan those notes describe
  is a timeline this game has not reached.
- **The briefing's `decisions` is the todo.** Like Codex, Grok looked for `status.todo` and noted the
  briefing calls it `decisions` ("status.todo showed up only on the finish and wait replies"). The
  instructions already say `status.todo (the briefing's decisions)`; left as is.
- **A closed league session has no vote rows**, and Grok was unsure whether one ever does. It does: the t244
  measurement (`2026-10-26-assyria-t244-league-vote.md`) has the `votable` rows with their yes / no calls;
  between sessions the proposal rows carry `call`s to propose instead. The playbook's diplomacy section
  gained one sentence saying so.

The game stands at t239, Grok's note 12 in the notebook (its next-turn plan is partly from the later
timeline: the Zulu and Siam deals to re-offer are real, the Great Scientist and Musician are not).

Seen live at t239 through a fresh server (`scripts/mcp_session.py`, reads only) on this code: the two
refusals carry their `hint`, `reference(section="city_states")` answers with the diplomacy section, and the
briefing with `notes="all"` marks six of eight notes `later_timeline: true` with the `notes_later_timeline`
sentence.
