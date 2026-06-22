from __future__ import annotations

"""Tiny client used by the base-project e2e scenarios.

The client talks only to the gateway. It never receives node addresses and
therefore cannot accidentally create the direct node-to-node topology the lab is
designed to avoid.
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from typing import Any


API_URL = os.environ.get("API_URL", "http://gateway:8080").rstrip("/")
API_TIMEOUT_SECONDS = float(os.environ.get("API_TIMEOUT_SECONDS", "30"))


def request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Send one JSON request to the gateway."""

    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{API_URL}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=API_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Brokered DB client")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health")
    put = sub.add_parser("put")
    put.add_argument("key")
    put.add_argument("value")
    get = sub.add_parser("get")
    get.add_argument("key")
    sub.add_parser("e2e")
    args = parser.parse_args(argv)

    if args.command == "health":
        print(json.dumps(request("GET", "/health"), sort_keys=True))
        return 0
    if args.command == "put":
        path = f"/kv/{urllib.parse.quote(args.key, safe='')}"
        print(json.dumps(request("PUT", path, {"value": parse_value(args.value)}), sort_keys=True))
        return 0
    if args.command == "get":
        path = f"/kv/{urllib.parse.quote(args.key, safe='')}"
        print(json.dumps(request("GET", path), sort_keys=True))
        return 0
    if args.command == "e2e":
        # The scenario exercises the full brokered path: gateway -> NATS ->
        # relays -> isolated DB nodes -> query replies through NATS.
        key = "alpha"
        result = {
            "health": request("GET", "/health"),
            "put": request("PUT", f"/kv/{key}", {"value": {"count": 1}}),
            "get": request("GET", f"/kv/{key}"),
        }
        print(json.dumps(result, sort_keys=True))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
