#!/usr/bin/env python3
"""Compact picture of the new turn from logs/et_last.log (wait_for_my_turn + turn_digest + overview)."""
import json, re, sys
txt = open(sys.argv[1] if len(sys.argv) > 1 else "logs/et_last.log").read()
def section(name):
    m = re.search(r"== " + name + r"\n(.*?)\n(?:== |\Z)", txt, re.S)
    if not m: return None
    try: return json.loads(m.group(1).strip())
    except Exception as e: return {"_unparsed": m.group(1)[:300]}
w = section("wait_for_my_turn") or {}
print("STATUS", {k: w.get(k) for k in ("turn", "my_turn", "blocking_name", "blocking_hint", "discussion_pending", "pending_popups")})
print("TODO", w.get("todo"))
d = section("turn_digest") or {}
for e in d.get("events", []):
    dd = e.get("data", {}) or {}
    if e.get("kind") in ("alert",) and "Quicksaving" in str(dd.get("text")): continue
    print(" ", e.get("turn"), e.get("kind"), (dd.get("summary") or dd.get("text") or json.dumps(dd))[:200])
print("NOTIFS", [n.get("summary") for n in d.get("notifications", [])])
o = section("overview") or {}
print("OVERVIEW", {k: o.get(k) for k in ("turn", "gold", "gold_per_turn", "happiness", "science", "research", "research_turns_left", "culture", "next_policy_cost", "faith")})
