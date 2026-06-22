from __future__ import annotations

import json
import os
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from custom.node.store import EventStore


class NodeHandler(BaseHTTPRequestHandler):
    store: EventStore

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(HTTPStatus.OK, self.store.health())
            return
        if self.path == "/events":
            self._json(HTTPStatus.OK, {"events": self.store.list_events()})
            return
        key = self._kv_key()
        if key is not None:
            state = self.store.get(key)
            if state is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            self._json(HTTPStatus.OK, state)
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
        event = self.store.local_put(key, payload["value"], actor=payload.get("actor", "client"))
        self._json(HTTPStatus.OK, event)

    def do_POST(self) -> None:
        if self.path != "/events":
            self._json(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})
            return
        payload = self._read_json()
        events = payload.get("events")
        if not isinstance(events, list):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "events must be a list"})
            return
        try:
            result = self.store.import_events(events)
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._json(HTTPStatus.OK, result)

    def log_message(self, format: str, *args: Any) -> None:
        if os.environ.get("ACCESS_LOG", "0") == "1":
            super().log_message(format, *args)

    def _kv_key(self) -> str | None:
        prefix = "/kv/"
        if not self.path.startswith(prefix):
            return None
        raw = self.path[len(prefix) :]
        if not raw:
            return None
        return urllib.parse.unquote(raw)

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


def build_server() -> ThreadingHTTPServer:
    node_id = os.environ.get("NODE_ID", "node")
    db_path = Path(os.environ.get("DB_PATH", "/data/node.db"))
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    NodeHandler.store = EventStore(node_id, db_path)
    return ThreadingHTTPServer((host, port), NodeHandler)


def main() -> None:
    server = build_server()
    host, port = server.server_address
    print(f"custom node listening on {host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
