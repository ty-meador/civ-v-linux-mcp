"""The page's server: static files, a bootstrap state, the recording, and the feed over Server-Sent Events.
Read-only, stdlib only.

GET /            -> web/viz/index.html
GET /<path>      -> a file under the web dir (no `..`)
GET /state       -> feed.state(): mode, whether there is a recording, the map, the last snapshot, the notebooks,
                    recent calls and events
GET /recording   -> the recording so far as JSON lines (one event per line, the stream's seq numbers);
                    `?since=N` from seq N on; 404 when the spectator has none (live without --record)
GET /events      -> text/event-stream; `?since=N` or `Last-Event-ID: N` resumes; a comment line every KEEPALIVE
                    seconds keeps proxies and the browser happy
"""
from __future__ import annotations

import json
import mimetypes
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .feed import Feed

KEEPALIVE = 15.0
WEB_DIR = pathlib.Path(__file__).resolve().parents[2] / "web" / "viz"


def make_handler(feed: Feed, web_dir: pathlib.Path):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # quiet
            pass

        def handle(self):
            # A keep-alive client that resets between two requests (a tab closed, a test's response object collected)
            # makes handle_one_request's readline raise, and http.server only expects a timeout there: the socketserver
            # thread would print a forty-dash banner and a traceback on stderr for what is just a client gone.
            try:
                super().handle()
            except (ConnectionResetError, BrokenPipeError):
                pass

        def _json(self, obj, status: int = 200) -> None:
            body = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            self._body(body, "application/json; charset=utf-8", status)

        def _body(self, body: bytes, ctype: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/state":
                return self._json(feed.state())
            if url.path == "/recording":
                return self._recording(url)
            if url.path == "/events":
                return self._stream(url)
            return self._static(url.path)

        def _recording(self, url) -> None:
            if not feed.recording_path:
                self._json({"ok": False, "err": "no recording (start the spectator with --record or --replay)"}, 404)
                return
            try:
                since = int((parse_qs(url.query).get("since") or ["0"])[0])
            except ValueError:
                since = 0
            lines = [json.dumps(ev, separators=(",", ":"), ensure_ascii=False) for ev in feed.recording(since)]
            body = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
            self._body(body, "application/x-ndjson; charset=utf-8")

        def _stream(self, url) -> None:
            qs = parse_qs(url.query)
            since = self.headers.get("Last-Event-ID") or (qs.get("since") or ["0"])[0]
            try:
                seq = int(since)
            except ValueError:
                seq = 0
            if seq > feed.seq:      # a cursor from an earlier spectator process (live 2026-09-29): start over
                seq = 0
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                while True:
                    batch = feed.wait(seq, KEEPALIVE)
                    if not batch:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        continue
                    for ev in batch:
                        self.wfile.write(sse(ev))
                        seq = ev["seq"]
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

        def _static(self, path: str) -> None:
            rel = path.lstrip("/") or "index.html"
            target = (web_dir / rel).resolve()
            if web_dir.resolve() not in target.parents or not target.is_file():
                self._json({"ok": False, "err": "not found"}, 404)
                return
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                ctype += "; charset=utf-8"
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def sse(ev: dict) -> bytes:
    data = json.dumps(ev, separators=(",", ":"), ensure_ascii=False)
    return f"id: {ev['seq']}\nevent: {ev['type']}\ndata: {data}\n\n".encode()


def serve(feed: Feed, host: str = "127.0.0.1", port: int = 8765, web_dir: pathlib.Path | None = None,
          background: bool = False) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), make_handler(feed, web_dir or WEB_DIR))
    httpd.daemon_threads = True
    if background:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
    else:
        httpd.serve_forever()
    return httpd
