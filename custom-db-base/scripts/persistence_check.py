from __future__ import annotations

"""Persistence smoke test for the custom-db-base lab.

The script runs as the `persistence-client` compose service and uses only the
gateway on `ingress_net`. It never connects directly to a DB node. Repeated runs
write an incrementing counter to a stable key so persistent bind mounts under
`../_volumes/custom-db-base/workerN/...` are visible in the output.
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
LAB_NAME = os.environ.get("LAB_NAME", "custom-db-base")
KEY = os.environ.get("PERSISTENCE_KEY", "persistence-check")
TIMEOUT_SECONDS = float(os.environ.get("API_TIMEOUT_SECONDS", "30"))
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
        absent = exc.code == 404 or (exc.code == 503 and "required 1 responses" in error_body)
        if allow_absent and absent:
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


def values_from_payload(payload: dict[str, Any] | None) -> list[Any]:
    if not payload:
        return []
    values: list[Any] = []
    if "value" in payload:
        values.append(payload["value"])
    winner = payload.get("winner")
    if isinstance(winner, dict):
        state = winner.get("state")
        if isinstance(state, dict) and "value" in state:
            values.append(state["value"])
    for response in payload.get("responses", []):
        state = response.get("state")
        if isinstance(state, dict) and "value" in state:
            values.append(state["value"])
            continue
        value = response.get("value")
        if isinstance(value, dict) and "value" in value:
            values.append(value["value"])
        elif value is not None:
            values.append(value)
    return values


def run_count(value: Any) -> int:
    if isinstance(value, dict):
        try:
            return int(value.get("run_count", 0))
        except (TypeError, ValueError):
            return 0
    return 0


def max_run_count(payload: dict[str, Any] | None) -> int:
    return max([0, *[run_count(value) for value in values_from_payload(payload)]])


def matching_run_count(payload: dict[str, Any] | None, expected: int) -> int:
    return sum(1 for value in values_from_payload(payload) if run_count(value) == expected)


def fail(payload: dict[str, Any]) -> int:
    print(json.dumps({"ok": False, "lab": LAB_NAME, **payload}, sort_keys=True))
    return 1


def main() -> int:
    encoded_key = urllib.parse.quote(KEY, safe="")
    before_payload = request_json("GET", f"/kv/{encoded_key}", allow_absent=True)
    previous_count = max_run_count(before_payload)
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

    required_matches = int(os.environ.get("MIN_OBSERVED_REPLICAS", "2" if LAB_NAME.endswith("-base") else "1"))
    matches = matching_run_count(after_payload, next_count)
    ack_count = write_payload.get("ack_count") if isinstance(write_payload, dict) else None
    if isinstance(ack_count, int) and ack_count < 2:
        return fail({"error": "write did not reach two acknowledgements", "write": write_payload})
    if matches < required_matches:
        return fail(
            {
                "error": "new value was not observed on enough responses",
                "required_matches": required_matches,
                "matches": matches,
                "before": before_payload,
                "write": write_payload,
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
                "current_run_count": next_count,
                "observed_replicas": matches,
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
