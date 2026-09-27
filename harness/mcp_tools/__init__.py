"""The civ5 MCP server's tools, one module per domain (registered by harness/mcp_server.py in this order)."""
# reference first: how_to_play and the rule book are what a new seat should see at the top of the tool list;
# then the turn loop, and the domains in the order a turn visits them.
MODULE_NAMES = ("reference", "turn", "batch", "notebook", "units", "cities", "policies", "diplomacy", "trade", "front_end")
