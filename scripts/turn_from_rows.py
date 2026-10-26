"""Play one turn through the nine tools from the rows alone (milestone 2.0.0, stage 4; GitLab #47, #56).

One real stdio MCP server, started with the retired names off (`CIV5_RETIRED_NAMES=off`), so nothing but the
nine is callable; every order is a row copied out of a read. The loop: `turn(action="briefing", since="turn")`
-> for each decision run its read rows as they are, take the first complete `call` the read hands back (or
fill the decision's `choose` row from the read), then every unit's own orders -> a city-state gift from the
`full` view's rows when `--gift` names a city-state -> `turn(action="finish", actions=[...])`. One JSON line per
call on stdout (the call, then the reply cut short); the ledger (`CIV5_CALL_LOG`) has the rest.

Usage:
    CIV5_CALL_LOG=docs/measurements/<file>.jsonl .venv/bin/python scripts/turn_from_rows.py --seat 0 --gift 22
    ... --dry-run     # reads only: every order is listed, nothing is ordered, the turn is not ended
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.rows import rows_in  # noqa: E402
from harness.surface import dispatch as D  # noqa: E402
from harness.surface import vocabulary as V  # noqa: E402

NINE = set(V.TOOLS)


def fill(row: dict, read_reply) -> dict:
    """A `choose` argument takes the first value under the same key anywhere in the read's reply, at the top of
    the row when the tool takes it there, under `args` otherwise."""
    args = json.loads(json.dumps(row["args"]))
    for key in row.get("choose") or []:
        stack = [read_reply]
        while stack:
            v = stack.pop()
            if isinstance(v, dict):
                if key in v:
                    top = key in V.TOP_LEVEL[row["tool"]] or key in D.FIXED_FIELDS.get(row["tool"], ())
                    (args if top else args.setdefault("args", {}))[key] = v[key]
                    break
                stack.extend(v.values())
            elif isinstance(v, list):
                stack.extend(v)
    return {"tool": row["tool"], "args": args}


def is_write(row: dict) -> bool:
    return row["tool"] in ("order", "answer", "notebook", "batch")


class Seat:
    def __init__(self, session: ClientSession):
        self.session = session

    async def call(self, tool: str, args: dict):
        assert tool in NINE, f"{tool} is not one of the nine"
        res = await self.session.call_tool(tool, args)
        text = "".join(c.text for c in res.content if c.type == "text")
        try:
            reply = json.loads(text)
        except ValueError:
            reply = {"text": text}
        print(json.dumps({"call": {"tool": tool, "args": args}, "reply": text[:600]}))
        return reply


async def play(a) -> int:
    params = StdioServerParameters(command=sys.executable, args=["-m", "harness.mcp_server"], cwd=str(ROOT),
                                   env={**os.environ, "CIV5_SEAT": str(a.seat), "CIV5_RETIRED_NAMES": "off"})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = sorted(t.name for t in (await session.list_tools()).tools)
            print(json.dumps({"listed": listed}))
            assert set(listed) <= NINE | {"lua"}, listed
            seat = Seat(session)
            briefing = await seat.call("turn", {"action": "briefing", "since": "turn"})
            if briefing.get("gate"):
                print(json.dumps({"stop": "a gate is up", "gate": briefing["gate"]}))
                return 1
            orders: list[dict] = []
            for d in briefing.get("decisions") or []:
                rows = d.get("actions") or []
                reads = [r for r in rows if not is_write(r) and "choose" not in r]
                reply = await seat.call(reads[0]["tool"], reads[0]["args"]) if reads else {}
                complete = [r for r in rows_in(reply) if is_write(r) and "choose" not in r]
                if d.get("kind") in ("unit_orders", "promotion"):
                    orders.extend(complete)
                elif complete:
                    orders.append(complete[0])
                else:
                    orders.extend(fill(r, reply) for r in rows if is_write(r) and "choose" in r)
            if a.gift is not None:
                full = await seat.call("inspect", {"what": "city_state", "view": "full", "id": a.gift})
                gifts = full.get("gifts") or {}
                tier = next((gifts[k] for k in ("small", "medium", "large") if isinstance(gifts.get(k), dict) and gifts[k].get("call")), None)
                if tier and tier.get("affordable", True):
                    orders.append(tier["call"])
            league = await seat.call("inspect", {"what": "league"})
            print(json.dumps({"league_rows": rows_in(league), "session_in": league.get("next_session_turns", league.get("turns_until_session"))}))
            print(json.dumps({"orders": orders}))
            if a.dry_run:
                return 0
            done = await seat.call("turn", {"action": "finish", "actions": orders, "timeout_seconds": 900, "args": {"briefing": True}})
            print(json.dumps({"ended": done.get("ended"), "turn": done.get("turn"), "ok": done.get("ok")}))
            return 0 if done.get("ok") else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seat", type=int, default=0)
    ap.add_argument("--gift", type=int, default=None, help="a city-state's player id: gift its first affordable gold tier")
    ap.add_argument("--dry-run", action="store_true")
    return asyncio.run(play(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
