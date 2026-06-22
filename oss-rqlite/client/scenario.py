from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class RqliteUnavailable(RuntimeError):
    pass


def node_urls() -> list[str]:
    urls = [url.strip().rstrip("/") for url in os.environ.get("NODE_URLS", "").split(",")]
    urls = [url for url in urls if url]
    if not urls:
        raise ValueError("NODE_URLS must contain at least one rqlite HTTP URL")
    return urls


def request_json(
    base_url: str, method: str, path: str, payload: Any | None = None, timeout: float = 3.0
) -> Any:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            if not body:
                return {"status": response.status}
            return json.loads(body)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise RqliteUnavailable(f"{base_url}{path}: {exc}") from exc


def request_status(base_url: str, path: str, timeout: float = 3.0) -> int:
    request = urllib.request.Request(base_url + path, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
            return response.status
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        raise RqliteUnavailable(f"{base_url}{path}: {exc}") from exc


def execute(sql: list[str]) -> dict[str, Any]:
    errors = []
    for url in node_urls():
        try:
            return {"node": url, "response": request_json(url, "POST", "/db/execute", sql)}
        except RqliteUnavailable as exc:
            errors.append(str(exc))
    raise RqliteUnavailable("; ".join(errors))


def query(sql: str, level: str = "strong") -> dict[str, Any]:
    encoded = urllib.parse.urlencode({"q": sql, "level": level})
    errors = []
    for url in node_urls():
        try:
            return {"node": url, "response": request_json(url, "GET", f"/db/query?{encoded}")}
        except RqliteUnavailable as exc:
            errors.append(str(exc))
    raise RqliteUnavailable("; ".join(errors))


def health() -> dict[str, Any]:
    nodes = []
    errors = []
    for url in node_urls():
        try:
            request_status(url, "/readyz")
            nodes.append({"url": url, "ready": True})
        except RqliteUnavailable as exc:
            errors.append(str(exc))
            nodes.append({"url": url, "ready": False})
    return {"nodes": nodes, "ready_count": sum(1 for node in nodes if node["ready"]), "errors": errors}


def nodes() -> dict[str, Any]:
    errors = []
    for url in node_urls():
        try:
            return {"node": url, "response": request_json(url, "GET", "/nodes?ver=2")}
        except RqliteUnavailable as exc:
            errors.append(str(exc))
    raise RqliteUnavailable("; ".join(errors))


def wait_ready(min_ready: int, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last = {}
    while time.monotonic() < deadline:
        last = health()
        if last["ready_count"] >= min_ready:
            return last
        time.sleep(1)
    raise RqliteUnavailable(f"timed out waiting for {min_ready} ready nodes: {last}")


def e2e() -> dict[str, Any]:
    wait = wait_ready(3, 60)
    create = execute(["CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL)"])
    write = execute(["INSERT OR REPLACE INTO kv(k, v) VALUES('alpha', 'one')"])
    read = query("SELECT v FROM kv WHERE k = 'alpha'")
    return {"wait": wait, "create": create, "write": write, "read": read, "nodes": nodes()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="rqlite quorum lab scenario runner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    wait_parser = subparsers.add_parser("wait")
    wait_parser.add_argument("--min-ready", type=int, default=3)
    wait_parser.add_argument("--timeout", type=float, default=60)
    subparsers.add_parser("health")
    subparsers.add_parser("nodes")
    subparsers.add_parser("e2e")
    exec_parser = subparsers.add_parser("execute")
    exec_parser.add_argument("sql", nargs="+")
    query_parser = subparsers.add_parser("query")
    query_parser.add_argument("sql")

    args = parser.parse_args(argv)
    try:
        if args.command == "wait":
            result = wait_ready(args.min_ready, args.timeout)
        elif args.command == "health":
            result = health()
        elif args.command == "nodes":
            result = nodes()
        elif args.command == "e2e":
            result = e2e()
        elif args.command == "execute":
            result = execute(args.sql)
        elif args.command == "query":
            result = query(args.sql)
        else:
            return 1
        print(json.dumps(result, sort_keys=True))
        return 0
    except RqliteUnavailable as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
