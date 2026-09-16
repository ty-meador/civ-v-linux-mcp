#!/usr/bin/env bash
# Launch one named seat from harness/seats.json (copy harness/seats.example.json and fill it in first).
# Each seat gets its own Civ5 instance: separate profile (data_home), separate tuner port, bound to
# 127.0.0.1 only. Pair with a tunerd for that seat:
#   python3 -m harness.tunerd --port <seat's port> --sock $XDG_RUNTIME_DIR/civ5-<name>.sock
#
# Usage: scripts/launch_seat.sh <name> [seats.json path, default harness/seats.json]
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="${1:?usage: launch_seat.sh <name> [seats.json]}"
SEATS_FILE="${2:-$HERE/harness/seats.json}"

if [ ! -f "$SEATS_FILE" ]; then
  echo "no seats file at $SEATS_FILE -- copy harness/seats.example.json to harness/seats.json and fill it in" >&2
  exit 1
fi

# python3 (not jq) to keep this in step with the project's one real dependency assumption.
SEAT_ENV="$(python3 - "$SEATS_FILE" "$NAME" <<'PY'
import json, os, sys
path, name = sys.argv[1], sys.argv[2]
seats = json.load(open(path))
seat = seats.get(name)
if seat is None:
    print(f"no seat {name!r} in {path}", file=sys.stderr)
    sys.exit(1)
port = seat["port"]
data_home = os.path.expanduser(seat.get("data_home", f"~/.local/share/civ5-{name}"))
print(f"export CIV5_TUNER_PORT={port}")
print(f"export CIV5_DATA_HOME={data_home!r}")
print("export CIV5_TUNER_BIND=127.0.0.1")
PY
)" || exit 1
eval "$SEAT_ENV"

exec "$HERE/scripts/launch_civ5.sh" "civ5-$NAME"
