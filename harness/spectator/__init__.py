"""The read-only spectator behind the live visualization (docs/VISUALIZATION.md).

One more tunerd client that only ever runs queries: the static map once, a snapshot of players / cities / units /
borders when something changed, and the runtime's event ring unfiltered. It tails the call ledger and the notebook
files on disk for the seats' attention and their notes, merges everything into one sequenced stream (feed.py),
records it, replays it, and serves it over SSE with the page (server.py). Nothing here can act on the game and
nothing here is ever returned to a seat.

It deliberately uses the raw client (`harness.client.Civ5.query`) and not `Game.q`: `Game.q` calls ensure_runtime,
and a spectator built from a different runtime source than the seat servers would re-inject the runtime under
them (project_runtime_digest_pingpong). The event read needs `H.events`, which exists as soon as any seat server
has installed the runtime, and answers empty until then.
"""
