from __future__ import annotations

"""HTTP gateway for the native rqlite tunnel experiment.

The gateway gives the external Cloudflare tunnel one stable HTTP origin. It
proxies client requests to the local rqlite HTTP API on node 1. Raft peer
traffic is not handled here; that traffic is configured in compose through
`cloudflared access tcp` sidecars attached to each node network.
"""

import json
import os
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


RQLITE_HTTP_URL = os.environ.get("RQLITE_HTTP_URL", "http://rqlite1:4001").rstrip("/")


class GatewayHandler(BaseHTTPRequestHandler):
    """Forward rqlite HTTP API calls from the client ingress to node 1."""

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(HTTPStatus.OK, {"ok": True, "role": "rqlite-tunnel-gateway"})
            return
        self._proxy()

    def do_POST(self) -> None:
        self._proxy()

    def log_message(self, format: str, *args: Any) -> None:
        if os.environ.get("ACCESS_LOG", "0") == "1":
            super().log_message(format, *args)

    def _proxy(self) -> None:
        """Proxy the current HTTP request to the configured local rqlite API."""

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else None
        headers = {"Accept": self.headers.get("Accept", "application/json")}
        if self.headers.get("Content-Type"):
            headers["Content-Type"] = self.headers["Content-Type"]
        request = urllib.request.Request(f"{RQLITE_HTTP_URL}{self.path}", data=body, headers=headers, method=self.command)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                data = response.read()
                self.send_response(response.status)
                self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as exc:
            data = exc.read()
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer((host, port), GatewayHandler)
    print(f"rqlite tunnel gateway listening on {host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
