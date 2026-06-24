from __future__ import annotations

"""Persistence smoke test for the ckroch-db-tunnels lab.

The script connects to the HTTP gateway on `ingress_net`. The gateway talks to
node 1 SQL; CockroachDB peer traffic, if formed, uses the Cloudflare TCP sidecar
overlay.
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
LAB_NAME = os.environ.get("LAB_NAME", "ckroch-db-tunnels")
KEY = os.environ.get("PERSISTENCE_KEY", "persistence-check")
TIMEOUT_SECONDS = float(os.environ.get("API_TIMEOUT_SECONDS", "45"))
REQUEST_RETRIES = int(os.environ.get("REQUEST_RETRIES", "30"))
RETRY_DELAY_SECONDS = float(os.environ.get("RETRY_DELAY_SECONDS", "1"))
REQUIRE_PREVIOUS = os.environ.get("REQUIRE_PREVIOUS", "0") == "1"


def request_once(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    allow_absent: bool = False,
) -> dict[str, Any] | None:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{API_URL}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        if allow_absent and exc.code == 404:
            return None
        raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {error_body}") from exc


def request_json(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    allow_absent: bool = False,
) -> dict[str, Any] | None:
    last_error: Exception | None = None
    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            return request_once(method, path, payload, allow_absent=allow_absent)
        except Exception as exc:
            last_error = exc
            if attempt == REQUEST_RETRIES:
                break
            time.sleep(RETRY_DELAY_SECONDS)
    raise RuntimeError(f"{method} {path} failed after {REQUEST_RETRIES} attempts: {last_error}")


def run_count(value: Any) -> int:
    if isinstance(value, dict):
        try:
            return int(value.get("run_count", 0))
        except (TypeError, ValueError):
            return 0
    return 0


def fail(payload: dict[str, Any]) -> int:
    print(json.dumps({"ok": False, "lab": LAB_NAME, **payload}, sort_keys=True))
    return 1


def main() -> int:
    encoded_key = urllib.parse.quote(KEY, safe="")
    before_payload = request_json("GET", f"/kv/{encoded_key}", allow_absent=True)
    previous_count = run_count(before_payload.get("value") if before_payload else None)
    if REQUIRE_PREVIOUS and previous_count < 1:
        return fail({"error": "previous data was required but not observed", "before": before_payload})

    next_count = previous_count + 1
    value = {
        "lab": LAB_NAME,
        "key": KEY,
        "run_count": next_count,
        "run_id": uuid.uuid4().hex,
        "previous_run_count": previous_count,
        "written_at": time.time(),
    }
    write_payload = request_json("PUT", f"/kv/{encoded_key}", {"value": value})
    after_payload = request_json("GET", f"/kv/{encoded_key}")
    after_value = after_payload.get("value") if after_payload else None
    if run_count(after_value) != next_count:
        return fail({"error": "new value was not observed", "write": write_payload, "after": after_payload})

    print(
        json.dumps(
            {
                "ok": True,
                "lab": LAB_NAME,
                "key": KEY,
                "previous_run_count": previous_count,
                "current_run_count": next_count,
                "observed_replicas": 1,
                "saw_previous_data": previous_count > 0,
                "write": write_payload,
                "after": after_payload,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
