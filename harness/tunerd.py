"""tunerd: owns the single FireTuner connection to Civ V and multiplexes it.

Civ V accepts exactly ONE tuner client per arming of the listener (it is re-armed only
on ExitToMainMenu / leaving the MP staging room).  Any client that drops the TCP
connection wedges the port until then.  So one long-lived process holds the
connection and everyone else talks to this daemon over a local Unix socket with
newline-delimited JSON:

    -> {"op": "states"}
    -> {"op": "exec",  "state": "InGame" | 12, "lua": "print(1)", "timeout": 10}
    -> {"op": "query", "state": "InGame", "lua": "return {a=1}", "timeout": 10}
    -> {"op": "wait_state", "name": "InGame", "timeout": 120}
    -> {"op": "events", "since": 0}      # unsolicited output the game printed on its own
    -> {"op": "ping"}
    <- {"ok": true, ...} | {"ok": false, "error": "..."}

Run:  python -m harness.tunerd [--sock PATH] [--host 127.0.0.1] [--port 4318]
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import socketserver
import sys
import threading
import time
import traceback

from .tuner import TunerClient, TunerError, LuaError, TAG_OUTPUT

DEFAULT_SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "civ5-tuner.sock")


class Bridge:
    def __init__(self, host: str, port: int):
        self.host, self.port = host, port
        self.lock = threading.RLock()
        self.client: TunerClient | None = None
        self.events: list[dict] = []      # unsolicited game output
        self.connected_at = 0.0

    # -- game side --------------------------------------------------------
    def ensure(self) -> TunerClient:
        with self.lock:
            if self.client is None:
                c = TunerClient(self.host, self.port, timeout=15).connect(retries=2, delay=0.5)
                states = c.handshake()
                self.client, self.connected_at = c, time.time()
                log(f"connected to game tuner; {len(states)} lua states; app={c.app[:60]!r}")
            return self.client

    def drop(self):
        with self.lock:
            if self.client:
                try:
                    self.client.close()
                finally:
                    self.client = None
            log("game connection dropped; will reconnect (game must re-arm its listener)")

    def pump_unsolicited(self):
        """Background: while idle, collect anything the game prints on its own."""
        while True:
            time.sleep(0.25)
            with self.lock:
                c = self.client
                if c is None:
                    try:
                        self.ensure()
                    except (OSError, ConnectionError):
                        pass
                    continue
                try:
                    for m in c.drain(0.05):
                        if m.tag == TAG_OUTPUT:
                            text = m.payload[2:] if m.payload.startswith("O\x00") else m.payload
                            self.events.append({"t": time.time(), "text": text})
                            if len(self.events) > 5000:
                                del self.events[:1000]
                except ConnectionError:
                    self.drop()

    # -- request handling -------------------------------------------------
    def handle(self, req: dict) -> dict:
        op = req.get("op")
        if op == "ping":
            return {"ok": True, "connected": self.client is not None, "since": self.connected_at}
        if op == "events":
            since = int(req.get("since", 0))
            return {"ok": True, "events": self.events[since:], "next": len(self.events)}
        with self.lock:
            c = self.ensure()
            try:
                if op == "states":
                    st = c.refresh_states()
                    return {"ok": True, "states": {str(k): v for k, v in st.items()}}
                if op == "wait_state":
                    sid = c.wait_for_state(req["name"], timeout=float(req.get("timeout", 120)))
                    return {"ok": True, "id": sid}
                if op == "exec":
                    r = c.execute(req["state"], req["lua"], timeout=req.get("timeout"), raise_on_error=False)
                    return {"ok": r.error is None, "output": r.output, "error": r.error}
                if op == "query":
                    v = c.query(req["state"], req["lua"], timeout=req.get("timeout"))
                    return {"ok": True, "value": v}
                return {"ok": False, "error": f"unknown op {op!r}"}
            except LuaError as e:
                return {"ok": False, "error": str(e)}
            except (ConnectionError, BrokenPipeError) as e:
                self.drop()
                return {"ok": False, "error": f"game connection lost: {e}"}
            except (TunerError, KeyError, TimeoutError) as e:
                return {"ok": False, "error": str(e)}
            except (OSError, ConnectionError) as e:
                return {"ok": False, "error": f"game tuner not reachable: {e}"}


def log(msg: str):
    print(f"[tunerd {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        for line in self.rfile:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                resp = self.server.bridge.handle(req)
            except Exception as e:  # noqa: BLE001
                resp = {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]}
            self.wfile.write((json.dumps(resp) + "\n").encode())
            self.wfile.flush()


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sock", default=DEFAULT_SOCK)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4318)
    a = ap.parse_args(argv)
    if os.path.exists(a.sock):
        os.unlink(a.sock)
    bridge = Bridge(a.host, a.port)
    srv = Server(a.sock, Handler)
    srv.bridge = bridge
    threading.Thread(target=bridge.pump_unsolicited, daemon=True).start()
    threading.Thread(target=bridge.ensure, daemon=True).start()
    log(f"listening on {a.sock}; game tuner at {a.host}:{a.port}")
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
        if os.path.exists(a.sock):
            os.unlink(a.sock)


if __name__ == "__main__":
    main()
