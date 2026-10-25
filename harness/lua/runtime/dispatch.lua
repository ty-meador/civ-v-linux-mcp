---------------------------------------------------------------- dispatch: the daemon's entry
-- tunerd writes `return H._call(name, seat, args, n)` for a client's {"op": "call", "fn": name, "args": [...]}
-- (docs/ROADMAP.md "A seat bound to its channel", stage 3). The seat is the connection's binding, never an
-- argument of the caller's: it is inserted here at the entry's own seat slot. H._seat_slot (name -> 1-based
-- index of the `pid` parameter) and H._seat_free (the entries with no seat that may be called from outside)
-- are generated at build from the parameter lists (harness/runtime_source.py) and set by the installer just
-- before H.source_hash. `n` travels with the arguments because a nil leaves a hole `#args` cannot count.
local unpack = unpack or table.unpack

function H._call(name, seat, args, n)
  local fn = H[name]
  if type(fn) ~= "function" then
    return { ok = false, err = "no runtime entry H." .. tostring(name) }
  end
  n = n or #args
  local slot = H._seat_slot and H._seat_slot[name]
  if slot == nil then
    if not (H._seat_free and H._seat_free[name]) then
      return { ok = false, err = "H." .. name .. " takes no seat and is not callable from outside the runtime" }
    end
    return fn(unpack(args, 1, n))
  end
  if n < slot - 1 then
    return { ok = false, err = "H." .. name .. " takes " .. (slot - 1) .. " argument(s) before the seat, got " .. n }
  end
  local out = {}
  for i = 1, slot - 1 do out[i] = args[i] end
  out[slot] = seat
  for i = slot, n do out[i + 1] = args[i] end
  return fn(unpack(out, 1, n + 1))
end
