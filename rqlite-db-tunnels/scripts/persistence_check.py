from __future__ import annotations

"""Persistence smoke test for the rqlite-db-tunnels lab.

The tunnel gateway proxies the rqlite HTTP API, so this script uses `/db/query`
and `/db/execute` through the gateway. It does not connect to a rqlite DB
container directly and does not use host port forwarding.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any


API_URL = os.environ.get("API_URL", "http://gateway:8080").rstrip("/")
LAB_NAME = os.environ.get("LAB_NAME", "rqlite-db-tunnels")
KEY = os.environ.get("PERSISTENCE_KEY", "persistence-check")
TIMEOUT_SECONDS = float(os.environ.get("API_TIMEOUT_SECONDS", "45"))
REQUEST_RETRIES = int(os.environ.get("REQUEST_RETRIES", "30"))
RETRY_DELAY_SECONDS = float(os.environ.get("RETRY_DELAY_SECONDS", "1"))
REQUIRE_PREVIOUS = os.environ.get("REQUIRE_PREVIOUS", "0") == "1"


def request_once(method: str, path: str, payload: Any | None = None) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{API_URL}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {exc.read().decode()}") from exc


def request_json(method: str, path: str, payload: Any | None = None) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            return request_once(method, path, payload)
        except Exception as exc:
            last_error = exc
            if attempt == REQUEST_RETRIES:
                break
            time.sleep(RETRY_DELAY_SECONDS)
    raise RuntimeError(f"{method} {path} failed after {REQUEST_RETRIES} attempts: {last_error}")


def sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def execute(statements: list[str]) -> dict[str, Any]:
    return request_json("POST", "/db/execute", statements)


def query(sql: str) -> dict[str, Any]:
    encoded = urllib.parse.urlencode({"level": "none", "q": sql})
    return request_json("GET", f"/db/query?{encoded}")


def read_count() -> tuple[int, dict[str, Any]]:
    payload = query(f"SELECT run_count FROM persistence_check WHERE key = {sql_quote(KEY)}")
    values = payload.get("results", [{}])[0].get("values") or []
    if not values:
        return 0, payload
    return int(values[0][0]), payload


def fail(payload: dict[str, Any]) -> int:
    print(json.dumps({"ok": False, "lab": LAB_NAME, **payload}, sort_keys=True))
    return 1


def main() -> int:
    execute(
        [
            "CREATE TABLE IF NOT EXISTS persistence_check (key TEXT PRIMARY KEY, run_count INTEGER NOT NULL, run_id TEXT NOT NULL, updated_at TEXT NOT NULL)"
        ]
    )
    previous_count, before_payload = read_count()
    if REQUIRE_PREVIOUS and previous_count < 1:
        return fail({"error": "previous data was required but not observed", "before": before_payload})

    next_count = previous_count + 1
    run_id = uuid.uuid4().hex
    execute(
        [
            "INSERT INTO persistence_check(key, run_count, run_id, updated_at) "
            f"VALUES({sql_quote(KEY)}, {next_count}, {sql_quote(run_id)}, {sql_quote(str(time.time()))}) "
            "ON CONFLICT(key) DO UPDATE SET "
            "run_count = excluded.run_count, run_id = excluded.run_id, updated_at = excluded.updated_at"
        ]
    )
    observed_count, after_payload = read_count()
    if observed_count != next_count:
        return fail(
            {
                "error": "new value was not observed",
                "expected_run_count": next_count,
                "observed_run_count": observed_count,
                "before": before_payload,
                "after": after_payload,
            }
        )

    print(
        json.dumps(
            {
                "ok": True,
                "lab": LAB_NAME,
                "key": KEY,
                "previous_run_count": previous_count,
                "current_run_count": observed_count,
                "observed_replicas": 1,
                "saw_previous_data": previous_count > 0,
                "before": before_payload,
                "after": after_payload,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
