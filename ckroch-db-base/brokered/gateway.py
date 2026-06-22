from __future__ import annotations

"""HTTP ingress for the brokered base labs.

The gateway is the only component that accepts client requests in the base
projects. It does not talk to DB nodes directly. Writes are converted into a
single command on the NATS JetStream log, and relays attached to each isolated
node network apply that command locally. The gateway returns after enough relay
acknowledgements arrive, which models a 2-of-3 quorum without giving DB nodes a
direct network path to each other.
"""

import argparse
import asyncio
import json
import os
import time
import urllib.parse
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import nats


NATS_URL = os.environ.get("NATS_URL", "nats://event-bus:4222")
MIN_APPLY_ACKS = int(os.environ.get("MIN_APPLY_ACKS", "2"))
ACK_TIMEOUT_SECONDS = float(os.environ.get("ACK_TIMEOUT_SECONDS", "10"))
QUERY_TIMEOUT_SECONDS = float(os.environ.get("QUERY_TIMEOUT_SECONDS", "3"))


class GatewayHandler(BaseHTTPRequestHandler):
    """Small HTTP API used by the local test client and Cloudflare origin."""

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(HTTPStatus.OK, {"ok": True, "role": "gateway"})
            return
        key = self._kv_key()
        if key is not None:
            result = asyncio.run(query_key(key))
            status = HTTPStatus.OK if result["responses"] else HTTPStatus.NOT_FOUND
            self._json(status, result)
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
        # The command ID is the idempotency key used by relays. A replayed
        # command can be seen more than once by a durable consumer, so relays
        # must be able to apply it safely.
        command = {
            "command_id": uuid.uuid4().hex,
            "operation": "put",
            "key": key,
            "value": payload["value"],
            "actor": payload.get("actor", "client"),
            "sequence": time.time_ns(),
            "timestamp": time.time(),
        }
        result = asyncio.run(publish_and_wait(command, MIN_APPLY_ACKS))
        status = HTTPStatus.OK if len(result["acks"]) >= MIN_APPLY_ACKS else HTTPStatus.ACCEPTED
        self._json(status, result)

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


async def publish_and_wait(command: dict[str, Any], min_acks: int) -> dict[str, Any]:
    """Publish one write command and wait for relay acknowledgements."""

    nc = await nats.connect(NATS_URL, connect_timeout=2)
    try:
        # Acks are ordinary NATS messages, not DB-to-DB communication. The
        # wildcard lets any node relay report that it applied the command.
        ack_subject = f"db.event.applied.{command['command_id']}.*"
        sub = await nc.subscribe(ack_subject)
        await nc.flush()
        js = nc.jetstream()
        await ensure_stream(js)
        await js.publish(f"db.cmd.{command['command_id']}", json.dumps(command).encode("utf-8"))
        acks: dict[str, dict[str, Any]] = {}
        deadline = asyncio.get_running_loop().time() + ACK_TIMEOUT_SECONDS
        while len(acks) < min_acks:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            try:
                msg = await sub.next_msg(timeout=remaining)
            except TimeoutError:
                break
            payload = json.loads(msg.data.decode("utf-8"))
            acks[payload["node_id"]] = payload
        return {"command": command, "acks": sorted(acks), "ack_count": len(acks), "required_acks": min_acks}
    finally:
        await nc.close()


async def ensure_stream(js: Any) -> None:
    """Create the command stream if this is the first component to start."""

    try:
        await js.add_stream(name="DB_COMMANDS", subjects=["db.cmd.>"])
    except Exception:
        pass


async def query_key(key: str) -> dict[str, Any]:
    """Ask all live relays for a key without connecting to any DB node."""

    nc = await nats.connect(NATS_URL, connect_timeout=2)
    try:
        # The reply inbox is sent inside the payload so every subscribed relay
        # can answer independently. This is a fan-out read through the bus.
        inbox = nc.new_inbox()
        sub = await nc.subscribe(inbox)
        await nc.publish("db.query", json.dumps({"key": key, "reply": inbox}).encode("utf-8"))
        await nc.flush()
        responses = []
        deadline = asyncio.get_running_loop().time() + QUERY_TIMEOUT_SECONDS
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            try:
                msg = await sub.next_msg(timeout=remaining)
            except TimeoutError:
                break
            responses.append(json.loads(msg.data.decode("utf-8")))
        return {"key": key, "responses": responses}
    finally:
        await nc.close()


def build_server() -> ThreadingHTTPServer:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    return ThreadingHTTPServer((host, port), GatewayHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Brokered DB gateway")
    parser.parse_args()
    server = build_server()
    host, port = server.server_address
    print(f"gateway listening on {host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
