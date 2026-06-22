from __future__ import annotations

"""Gateway for the custom Cloudflare-tunnel lab.

This gateway is the only client-facing origin. It does not share a Docker
network with any DB node. Instead, it receives the public node URLs from `.env`
and talks to those URLs through Cloudflare, matching the last-resort tunnel
architecture requested for direct node access.
"""

import json
import os
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from custom.client.ddb_client import QuorumUnavailable, SyncClient


class TunnelGatewayHandler(BaseHTTPRequestHandler):
    """Expose a small key/value API backed by Cloudflare-published nodes."""

    client: SyncClient

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(HTTPStatus.OK, self.client.health())
            return
        key = self._kv_key()
        if key is not None:
            try:
                self._json(HTTPStatus.OK, self.client.get(key, min_responses=1, repair=True))
            except QuorumUnavailable as exc:
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})

    def do_PUT(self) -> None:
        key = self._kv_key()
        if key is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})
            return
        payload = self._read_json()
        if "value" not in payload:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "value is required"})
            return
        try:
            # The gateway asks for two successful node writes, which matches the
            # corrected 3-node quorum requirement while still tolerating one
            # unavailable node.
            result = self.client.put(key, payload["value"], min_acks=int(os.environ.get("MIN_APPLY_ACKS", "2")))
        except QuorumUnavailable as exc:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
            return
        self._json(HTTPStatus.OK, result)

    def log_message(self, format: str, *args: Any) -> None:
        if os.environ.get("ACCESS_LOG", "0") == "1":
            super().log_message(format, *args)

    def _kv_key(self) -> str | None:
        parsed = urllib.parse.urlparse(self.path)
        prefix = "/kv/"
        if not parsed.path.startswith(prefix):
            return None
        raw = parsed.path[len(prefix) :]
        return urllib.parse.unquote(raw) if raw else None

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    TunnelGatewayHandler.client = SyncClient.from_env()
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer((host, port), TunnelGatewayHandler)
    print(f"custom tunnel gateway listening on {host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
