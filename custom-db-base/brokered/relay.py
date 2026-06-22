from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import nats
import psycopg


ENGINE = os.environ["ENGINE"]
NODE_ID = os.environ["NODE_ID"]
NATS_URL = os.environ.get("NATS_URL", "nats://event-bus:4222")
LOCAL_HTTP_URL = os.environ.get("LOCAL_HTTP_URL", "").rstrip("/")
LOCAL_DB_DSN = os.environ.get("LOCAL_DB_DSN", "")
nc: nats.NATS | None = None


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def http_json(method: str, url: str, payload: Any | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def custom_event(command: dict[str, Any]) -> dict[str, Any]:
    event = {
        "schema": 1,
        "origin_node": "gateway",
        "origin_seq": int(command["sequence"]),
        "actor": command.get("actor", "client"),
        "key": command["key"],
        "value": command["value"],
        "vector": {"gateway": int(command["sequence"])},
        "timestamp": float(command["timestamp"]),
    }
    event["event_id"] = hashlib.sha256(canonical_json(event).encode("utf-8")).hexdigest()
    return event


def apply_custom(command: dict[str, Any]) -> None:
    http_json("POST", f"{LOCAL_HTTP_URL}/events", {"events": [custom_event(command)]})


def query_custom(key: str) -> Any:
    try:
        return http_json("GET", f"{LOCAL_HTTP_URL}/kv/{urllib.parse.quote(key, safe='')}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def rqlite_execute(statements: list[str]) -> dict[str, Any]:
    return http_json("POST", f"{LOCAL_HTTP_URL}/db/execute", statements)


def rqlite_query(sql: str) -> dict[str, Any]:
    encoded = urllib.parse.urlencode({"level": "none", "q": sql})
    return http_json("GET", f"{LOCAL_HTTP_URL}/db/query?{encoded}")


def apply_rqlite(command: dict[str, Any]) -> None:
    key = sql_quote(command["key"])
    value_json = sql_quote(canonical_json(command["value"]))
    command_id = sql_quote(command["command_id"])
    now = str(time.time())
    rqlite_execute(
        [
            "CREATE TABLE IF NOT EXISTS _applied_events (command_id TEXT PRIMARY KEY, applied_at REAL NOT NULL)",
            "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at REAL NOT NULL)",
            f"INSERT OR IGNORE INTO _applied_events(command_id, applied_at) VALUES({command_id}, {now})",
            f"INSERT INTO kv(key, value_json, updated_at) VALUES({key}, {value_json}, {now}) "
            f"ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
        ]
    )


def query_rqlite(key: str) -> Any:
    result = rqlite_query(f"SELECT value_json FROM kv WHERE key = {sql_quote(key)}")
    rows = result.get("results", [{}])[0].get("values", [])
    if not rows:
        return None
    return {"key": key, "value": json.loads(rows[0][0])}


def apply_cockroach(command: dict[str, Any]) -> None:
    with psycopg.connect(LOCAL_DB_DSN, autocommit=True) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS _applied_events (command_id STRING PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS kv (key STRING PRIMARY KEY, value_json STRING NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        conn.execute(
            "INSERT INTO _applied_events(command_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (command["command_id"],),
        )
        conn.execute(
            "UPSERT INTO kv(key, value_json, updated_at) VALUES (%s, %s, now())",
            (command["key"], canonical_json(command["value"])),
        )


def query_cockroach(key: str) -> Any:
    with psycopg.connect(LOCAL_DB_DSN, autocommit=True) as conn:
        row = conn.execute("SELECT value_json FROM kv WHERE key = %s", (key,)).fetchone()
    if row is None:
        return None
    return {"key": key, "value": json.loads(row[0])}


def apply_command(command: dict[str, Any]) -> None:
    if ENGINE == "custom":
        apply_custom(command)
    elif ENGINE == "rqlite":
        apply_rqlite(command)
    elif ENGINE == "cockroach":
        apply_cockroach(command)
    else:
        raise ValueError(f"unknown ENGINE {ENGINE}")


def query_key(key: str) -> Any:
    if ENGINE == "custom":
        return query_custom(key)
    if ENGINE == "rqlite":
        return query_rqlite(key)
    if ENGINE == "cockroach":
        return query_cockroach(key)
    raise ValueError(f"unknown ENGINE {ENGINE}")


async def wait_for_nats() -> nats.NATS:
    while True:
        try:
            return await nats.connect(NATS_URL, connect_timeout=2)
        except Exception as exc:
            print(f"waiting for NATS: {exc}", flush=True)
            await asyncio.sleep(1)


async def ensure_stream(js: Any) -> None:
    try:
        await js.add_stream(name="DB_COMMANDS", subjects=["db.cmd.>"])
    except Exception:
        pass


async def handle_query(msg: Any) -> None:
    if nc is None:
        raise RuntimeError("NATS connection is not initialized")
    payload = json.loads(msg.data.decode("utf-8"))
    result = {"node_id": NODE_ID, "value": query_key(payload["key"])}
    await nc.publish(payload["reply"], json.dumps(result).encode("utf-8"))


async def main() -> None:
    global nc
    nc = await wait_for_nats()
    js = nc.jetstream()
    await ensure_stream(js)
    await nc.subscribe("db.query", cb=handle_query)
    sub = await js.subscribe("db.cmd.>", durable=f"{NODE_ID}-commands", manual_ack=True)
    print(f"{NODE_ID} relay consuming {ENGINE} commands", flush=True)
    async for msg in sub.messages:
        command = json.loads(msg.data.decode("utf-8"))
        try:
            apply_command(command)
            await nc.publish(
                f"db.event.applied.{command['command_id']}.{NODE_ID}",
                json.dumps({"node_id": NODE_ID, "command_id": command["command_id"], "ok": True}).encode("utf-8"),
            )
            await msg.ack()
        except Exception as exc:
            print(f"failed to apply {command.get('command_id')}: {exc}", flush=True)
            await msg.nak()


if __name__ == "__main__":
    asyncio.run(main())
