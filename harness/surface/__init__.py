"""The tool surface of milestone 2.0.0 (GitLab #59): nine tools that model the game, not its buttons.

One module per concern, none of them dispatching yet:

- `vocabulary`: the enums -- every `view` of every object `inspect` reads, every `action` on every `to` that
  `order` gives, the actions of `turn` / `notebook` / `session`, the books of `reference` (#48);
- `retirement`: the map from each of the 145 old tool names onto its row in the new surface, with the
  argument renames, and the check that every name maps to exactly one row (#50; stage 2c wires it into the
  call wrapper so an old name stays callable with `renamed` in the reply);
- `survey`: the stage 0 measurements (#44) -- the catalog by module, the zero-argument reads, the eight
  shapes the count comes from, the listing's byte and token size;
- `audit`: the affordance audit (#44) -- which replies hand back `{tool, args}` rows and which hand back a
  tool name in prose, by file and key; the seam stage 1 closes.

- `dispatch` (stage 2a, #48): the retirement map read the other way -- which old handler a new call runs, the
  arguments renamed back, the old names that share a row told apart, a refusal that names the shape with an
  example; `harness/mcp_tools/surface.py` registers the nine tools on it;
- `forward` (stage 2c, #50): the map read forward -- which old handler an unlisted name or alias means and the
  new call for its arguments, rendered as the `renamed` string the server's call wrapper puts on the reply;
  `new_call()` is the one place the shape of a new call (top-level selectors vs `args`) is written, from the new
  tool's own schema, and `example()` is what the refusals print;
- `schemas`: the registered tools' schemas read lazily, the leaf both directions stand on.

`scripts/tool_survey.py` prints the measurements for `docs/measurements/`.
"""
