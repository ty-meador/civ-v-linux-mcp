"""`python -m harness.spectator`: serve the live visualization, record the stream, or replay a recording.

  python -m harness.spectator --ledger logs/calls.jsonl --record logs/spectate.jsonl
  python -m harness.spectator --replay logs/spectate.jsonl --speed 8

Live mode needs tunerd (CIV5_TUNERD_SOCK or the default socket) and reads the ledger the seat servers write
(their CIV5_CALL_LOG). Replay needs no game at all. Either way the page is at http://HOST:PORT/.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import threading

from .feed import Feed, Live, replay
from .server import WEB_DIR, serve


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m harness.spectator", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", help="the seat servers' CIV5_CALL_LOG file to tail")
    ap.add_argument("--notes-dir", help="notebook dir (default: harness.notes.notes_dir())")
    ap.add_argument("--record", help="append the merged stream to this JSONL file")
    ap.add_argument("--replay", help="replay this recording instead of watching a game")
    ap.add_argument("--speed", type=float, default=1.0, help="replay speed factor (0 = instant)")
    ap.add_argument("--sock", help="tunerd socket (default: CIV5_TUNERD_SOCK / XDG_RUNTIME_DIR)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--web", type=pathlib.Path, default=WEB_DIR, help="the page's directory")
    a = ap.parse_args(argv)

    feed = Feed(record_path=a.record)
    if a.replay:
        threading.Thread(target=replay, args=(a.replay, feed, a.speed), daemon=True).start()
    else:
        if not a.ledger:
            print("spectator: --ledger is needed in live mode (the seat servers' CIV5_CALL_LOG)", file=sys.stderr)
        from ..client import Civ5
        live = Live(feed, Civ5(a.sock), a.ledger, a.notes_dir)
        threading.Thread(target=live.run, daemon=True).start()
    print(f"spectator: http://{a.host}:{a.port}/  ({'replay ' + a.replay if a.replay else 'live'})", file=sys.stderr)
    try:
        serve(feed, a.host, a.port, a.web)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
