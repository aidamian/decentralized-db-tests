from __future__ import annotations

"""HTTP key/value gateway for the CockroachDB tunnel experiment.

The external Cloudflare tunnel points at this small HTTP API. It talks only to
the local SQL endpoint on Cockroach node 1. Cockroach inter-node RPC is separate
and is modeled in compose with Cloudflare TCP sidecars.
"""

import json
import os
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import psycopg


LOCAL_DB_DSN = os.environ.get("LOCAL_DB_DSN", "postgresql://root@ckroch1:26257/defaultdb?sslmode=disable")


class GatewayHandler(BaseHTTPRequestHandler):
    """Expose a simple JSON key/value API over Cockroach SQL."""

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(HTTPStatus.OK, {"ok": True, "role": "ckroch-tunnel-gateway"})
            return
        key = self._kv_key()
        if key is not None:
            value = self._get_key(key)
            if value is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            else:
                self._json(HTTPStatus.OK, {"key": key, "value": value})
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
        self._put_key(key, payload["value"])
        self._json(HTTPStatus.OK, {"key": key, "stored": True})

    def log_message(self, format: str, *args: Any) -> None:
        if os.environ.get("ACCESS_LOG", "0") == "1":
            super().log_message(format, *args)

    def _ensure_schema(self, conn: psycopg.Connection[Any]) -> None:
        """Create the test table lazily so the gateway can start before SQL is ready."""

        conn.execute(
            "CREATE TABLE IF NOT EXISTS kv (key STRING PRIMARY KEY, value_json STRING NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )

    def _get_key(self, key: str) -> Any | None:
        with psycopg.connect(LOCAL_DB_DSN, autocommit=True) as conn:
            self._ensure_schema(conn)
            row = conn.execute("SELECT value_json FROM kv WHERE key = %s", (key,)).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def _put_key(self, key: str, value: Any) -> None:
        """UPSERT one JSON value through the local Cockroach SQL endpoint."""

        with psycopg.connect(LOCAL_DB_DSN, autocommit=True) as conn:
            self._ensure_schema(conn)
            conn.execute(
                "UPSERT INTO kv(key, value_json, updated_at) VALUES (%s, %s, now())",
                (key, json.dumps(value, sort_keys=True, separators=(",", ":"))),
            )

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
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer((host, port), GatewayHandler)
    print(f"ckroch tunnel gateway listening on {host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
