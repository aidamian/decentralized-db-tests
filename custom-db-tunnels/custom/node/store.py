from __future__ import annotations

"""SQLite-backed custom event store.

The store is deliberately small so the lab can show the replication mechanics
without relying on a native database cluster. Every write becomes an immutable
event with a vector clock. When relays replay the same event into different
nodes, the state converges locally because inserts are idempotent and conflicts
are reduced deterministically.
"""

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _decode_json(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value)


def _dominates(left: dict[str, int], right: dict[str, int]) -> bool:
    keys = set(left) | set(right)
    return all(left.get(key, 0) >= right.get(key, 0) for key in keys)


def compare_vectors(left: dict[str, int], right: dict[str, int]) -> str:
    left_dominates = _dominates(left, right)
    right_dominates = _dominates(right, left)
    if left_dominates and right_dominates:
        return "equal"
    if left_dominates:
        return "after"
    if right_dominates:
        return "before"
    return "concurrent"


class EventStore:
    """Local event log and materialized key/value state for one node."""

    def __init__(self, node_id: str, db_path: str | Path):
        self.node_id = node_id
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def local_put(self, key: str, value: Any, actor: str) -> dict[str, Any]:
        """Create a local event and immediately apply it to local state."""

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            seq = self._next_local_seq(conn)
            current = self._get_state_row(conn, key)
            vector = self._merged_leaf_vector(current)
            vector[self.node_id] = seq
            event = {
                "schema": 1,
                "origin_node": self.node_id,
                "origin_seq": seq,
                "actor": actor,
                "key": key,
                "value": value,
                "vector": vector,
                "timestamp": time.time(),
            }
            event["event_id"] = self.event_id(event)
            self._insert_event(conn, event)
            self._apply_to_state(conn, event)
            return event

    def import_events(self, events: list[dict[str, Any]]) -> dict[str, int]:
        """Import replicated events; duplicates are counted but not re-applied."""

        inserted = 0
        ignored = 0
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for event in events:
                normalized = self.normalize_event(event)
                if self._insert_event(conn, normalized):
                    inserted += 1
                    self._apply_to_state(conn, normalized)
                else:
                    ignored += 1
        return {"inserted": inserted, "ignored": ignored}

    def get(self, key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = self._get_state_row(conn, key)
        if row is None:
            return None
        return row

    def list_events(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT event_json
                FROM events
                ORDER BY received_seq ASC
                """
            ).fetchall()
        return [json.loads(row["event_json"]) for row in rows]

    def health(self) -> dict[str, Any]:
        with self._connect() as conn:
            event_count = conn.execute("SELECT COUNT(*) AS count FROM events").fetchone()["count"]
            key_count = conn.execute("SELECT COUNT(*) AS count FROM state").fetchone()["count"]
        return {
            "node_id": self.node_id,
            "db_path": str(self.db_path),
            "event_count": event_count,
            "key_count": key_count,
            "ok": True,
        }

    @staticmethod
    def normalize_event(event: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(event)
        normalized["vector"] = {str(k): int(v) for k, v in normalized.get("vector", {}).items()}
        expected = EventStore.event_id(normalized)
        if normalized.get("event_id") != expected:
            raise ValueError("event_id does not match event content")
        return normalized

    @staticmethod
    def event_id(event: dict[str, Any]) -> str:
        payload = {key: value for key, value in event.items() if key != "event_id"}
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    received_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    origin_node TEXT NOT NULL,
                    origin_seq INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    received_at REAL NOT NULL,
                    UNIQUE(origin_node, origin_seq)
                );

                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    conflicts_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )

    def _next_local_seq(self, conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT value FROM meta WHERE key = 'local_seq'").fetchone()
        seq = int(row["value"]) + 1 if row else 1
        conn.execute(
            """
            INSERT INTO meta(key, value)
            VALUES('local_seq', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(seq),),
        )
        return seq

    def _insert_event(self, conn: sqlite3.Connection, event: dict[str, Any]) -> bool:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO events(
                event_id, origin_node, origin_seq, key, event_json, received_at
            )
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (
                event["event_id"],
                event["origin_node"],
                int(event["origin_seq"]),
                event["key"],
                _canonical_json(event),
                time.time(),
            ),
        )
        return cursor.rowcount == 1

    def _apply_to_state(self, conn: sqlite3.Connection, event: dict[str, Any]) -> None:
        """Merge one event into the materialized state using vector clocks."""

        current = self._get_state_row(conn, event["key"])
        incoming = self._leaf_from_event(event)
        leaves = self._state_leaves(current)

        if any(
            leaf["event_id"] != incoming["event_id"]
            and compare_vectors(leaf["vector"], incoming["vector"]) == "after"
            for leaf in leaves
        ):
            return

        by_id = {leaf["event_id"]: leaf for leaf in leaves}
        by_id[incoming["event_id"]] = incoming
        reduced = []
        for leaf in by_id.values():
            dominated = any(
                other["event_id"] != leaf["event_id"]
                and compare_vectors(other["vector"], leaf["vector"]) == "after"
                for other in by_id.values()
            )
            if not dominated:
                reduced.append(leaf)

        # Concurrent leaves are ordered by event ID so every node chooses the
        # same visible winner while still preserving the other leaves as
        # conflict metadata.
        reduced.sort(key=lambda item: item["event_id"])
        winner = reduced[-1]
        conflicts = [leaf for leaf in reduced if leaf["event_id"] != winner["event_id"]]
        self._upsert_state(conn, event["key"], winner, conflicts)

    def _upsert_state(
        self,
        conn: sqlite3.Connection,
        key: str,
        event: dict[str, Any],
        conflicts: list[dict[str, Any]],
    ) -> None:
        conn.execute(
            """
            INSERT INTO state(
                key, event_id, value_json, vector_json, conflicts_json, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                event_id = excluded.event_id,
                value_json = excluded.value_json,
                vector_json = excluded.vector_json,
                conflicts_json = excluded.conflicts_json,
                updated_at = excluded.updated_at
            """,
            (
                key,
                event["event_id"],
                _canonical_json(event["value"]),
                _canonical_json(event["vector"]),
                _canonical_json(conflicts),
                time.time(),
            ),
        )

    def _get_state_row(self, conn: sqlite3.Connection, key: str) -> dict[str, Any] | None:
        row = conn.execute(
            """
            SELECT key, event_id, value_json, vector_json, conflicts_json, updated_at
            FROM state
            WHERE key = ?
            """,
            (key,),
        ).fetchone()
        if row is None:
            return None
        return {
            "key": row["key"],
            "event_id": row["event_id"],
            "value": _decode_json(row["value_json"], None),
            "vector": _decode_json(row["vector_json"], {}),
            "conflicts": _decode_json(row["conflicts_json"], []),
            "updated_at": row["updated_at"],
        }

    def _merged_leaf_vector(self, current: dict[str, Any] | None) -> dict[str, int]:
        vector: dict[str, int] = {}
        for leaf in self._state_leaves(current):
            for node_id, seq in leaf["vector"].items():
                vector[node_id] = max(vector.get(node_id, 0), int(seq))
        return vector

    def _state_leaves(self, current: dict[str, Any] | None) -> list[dict[str, Any]]:
        if current is None:
            return []
        return [
            {
                "event_id": current["event_id"],
                "value": current["value"],
                "vector": current["vector"],
            },
            *[
                {
                    "event_id": conflict["event_id"],
                    "value": conflict["value"],
                    "vector": conflict["vector"],
                }
                for conflict in current["conflicts"]
            ],
        ]

    def _leaf_from_event(self, event: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_id": event["event_id"],
            "value": event["value"],
            "vector": event["vector"],
        }
