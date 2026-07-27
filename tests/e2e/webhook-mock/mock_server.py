"""Minimal webhook mock for the Markpost SDK e2e suite.

Re-implements the contract of the backend's own webhook mock
(`markpost/e2e/mock-services/webhook-mock`) in plain Python, so the SDK repo is
self-contained: `docker compose up` only needs the published app image plus
this in-tree mock, with no checkout of the sibling backend repo.

Endpoints (identical to the original):

- ``POST /webhook*``     — record the request, reply ``{code:0,msg:"success"}``.
- ``GET  /webhooks``      — return every recorded request (newest last).
- ``POST /webhooks/clear`` — drop every recorded request.
- ``GET  /health``        — liveness probe used by the compose healthcheck.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "3002"))

# Received requests are kept in process memory for the lifetime of the server.
# A single shared list is enough: tests are sequential and clear it explicitly.
_received: list[dict] = []


class _Handler(BaseHTTPRequestHandler):
    # The default BaseHTTPRequestHandler logs to stderr on every request, which
    # is noisy under load. Keep the access log quiet.
    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _send(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or "0")
        return self.rfile.read(length) if length else b""

    def do_OPTIONS(self) -> None:
        self._send(200, {})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        # /webhooks/clear must be checked BEFORE the /webhook* prefix branch:
        # /webhooks/... also starts with /webhook, so the prefix match would
        # swallow it and record it as a delivery instead of clearing the log.
        if path == "/webhooks/clear":
            _received.clear()
            self._send(200, {"success": True})
            return
        if path.startswith("/webhook"):
            raw = self._read_body()
            try:
                parsed: object = json.loads(raw)
            except (ValueError, json.JSONDecodeError):
                parsed = raw.decode(errors="replace")
            _received.append(
                {
                    "timestamp": _now_iso(),
                    "method": "POST",
                    "path": path,
                    "headers": dict(self.headers),
                    "body": parsed,
                }
            )
            self._send(200, {"code": 0, "msg": "success", "data": {}})
            return
        self._send(404, {"error": "Not found"})

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/webhooks":
            self._send(200, _received)
            return
        if path == "/health":
            self._send(200, {"status": "ok"})
            return
        self._send(404, {"error": "Not found"})


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), _Handler)
    print(f"Webhook mock server running on port {PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
