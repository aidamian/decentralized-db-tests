from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from custom.client.ddb_client import QuorumUnavailable, SyncClient


def _parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Custom AP database client scenarios")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("health")

    put_parser = subparsers.add_parser("put")
    put_parser.add_argument("key")
    put_parser.add_argument("value")
    put_parser.add_argument("--min-acks", type=int, default=1)
    put_parser.add_argument("--actor", default="scenario")

    get_parser = subparsers.add_parser("get")
    get_parser.add_argument("key")
    get_parser.add_argument("--min-responses", type=int, default=1)
    get_parser.add_argument("--repair", action="store_true")

    subparsers.add_parser("sync")
    subparsers.add_parser("e2e")

    args = parser.parse_args(argv)
    client = SyncClient.from_env()
    try:
        if args.command == "health":
            _print(client.health())
            return 0
        if args.command == "put":
            _print(client.put(args.key, _parse_value(args.value), args.min_acks, actor=args.actor))
            return 0
        if args.command == "get":
            _print(client.get(args.key, min_responses=args.min_responses, repair=args.repair))
            return 0
        if args.command == "sync":
            _print(client.sync_all())
            return 0
        if args.command == "e2e":
            result = {
                "health": client.health(),
                "put": client.put("alpha", {"count": 1}, min_acks=1, actor="e2e"),
                "sync": client.sync_all(),
                "get": client.get("alpha", min_responses=1, repair=True),
            }
            _print(result)
            return 0
    except QuorumUnavailable as exc:
        _print({"error": str(exc)})
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
