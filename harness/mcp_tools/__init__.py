"""The civ5 MCP server's tools, one module per domain (registered by harness/mcp_server.py in this order)."""
# reference first: how_to_play and the rule book are what a new seat should see at the top of the tool list;
# then the turn loop, and the domains in the order a turn visits them.
MODULE_NAMES = ("reference", "turn", "batch", "notebook", "units", "cities", "policies", "diplomacy", "trade", "front_end")
#: The nine tools of milestone 2.0.0 (GitLab #48), registered after the old catalog; `harness.surface.survey` counts
#: the old catalog without them until #52 retires the old names.
SURFACE_MODULE = "surface"
