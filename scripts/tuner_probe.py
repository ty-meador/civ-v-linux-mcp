#!/usr/bin/env python3
"""Probe: act as a FireTuner *server* on 127.0.0.1:4318, log every byte the game sends,
and reply to nothing except an optional handshake so we can learn the wire format."""
import socket, sys, time, struct, threading, os

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 4318
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs", "tuner_probe.log")

def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)
    print(line, end="", flush=True)

def frame(tag, payload: str) -> bytes:
    data = payload.encode() + b"\x00"
    return struct.pack("<II", len(data), tag) + data

def handle(conn, addr):
    log(f"CONNECT from {addr}")
    conn.settimeout(None)
    buf = b""
    try:
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                log("EOF"); break
            buf += chunk
            while len(buf) >= 8:
                ln, tag = struct.unpack("<II", buf[:8])
                if len(buf) < 8 + ln:
                    break
                payload = buf[8:8 + ln]
                buf = buf[8 + ln:]
                log(f"MSG tag={tag} len={ln} payload={payload[:600]!r}")
            if buf and len(buf) < 8:
                log(f"PARTIAL {buf!r}")
            # after first data, ask for the lua-state list, then run a probe command
            if os.environ.get("PROBE_SEND") and not getattr(handle, "sent", False):
                handle.sent = True
                for p in os.environ["PROBE_SEND"].split("|"):
                    tag, _, pl = p.partition("~")
                    conn.sendall(frame(int(tag), pl)); log(f"SENT tag={tag} {pl!r}")
    except Exception as e:
        log(f"ERR {e}")
    finally:
        conn.close(); log("CLOSED")

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", PORT)); srv.listen(4)
log(f"listening on 127.0.0.1:{PORT}")
while True:
    c, a = srv.accept()
    threading.Thread(target=handle, args=(c, a), daemon=True).start()
