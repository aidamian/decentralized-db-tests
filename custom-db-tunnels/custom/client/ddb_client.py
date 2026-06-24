from __future__ import annotations

"""Client helpers for the custom DB node HTTP API.

The base projects now prefer the brokered gateway, but this client remains
useful for the tunnel variant. It treats Cloudflare node URLs as ordinary HTTP
node endpoints and performs quorum-style writes by reusing one event across the
reachable nodes.
"""

import json
import hashlib
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Protocol

from custom.node.store import EventStore, compare_vectors


class NodeUnavailable(RuntimeError):
    pass


class QuorumUnavailable(RuntimeError):
    pass


class Node(Protocol):
    node_id: str

    def health(self) -> dict[str, Any]:
        ...

    def put(self, key: str, value: Any, actor: str = "client") -> dict[str, Any]:
        ...

    def get(self, key: str) -> dict[str, Any] | None:
        ...

    def list_events(self) -> list[dict[str, Any]]:
        ...

    def import_events(self, events: list[dict[str, Any]]) -> dict[str, int]:
        ...


class InMemoryNode:
    def __init__(self, node_id: str, reachable: bool = True):
        self.node_id = node_id
        self.reachable = reachable
        self._tmpdir = tempfile.TemporaryDirectory()
        self._store = EventStore(node_id, Path(self._tmpdir.name) / "node.db")

    def health(self) -> dict[str, Any]:
        self._ensure_reachable()
        return self._store.health()

    def put(self, key: str, value: Any, actor: str = "client") -> dict[str, Any]:
        self._ensure_reachable()
        return self._store.local_put(key, value, actor)

    def get(self, key: str) -> dict[str, Any] | None:
        self._ensure_reachable()
        return self._store.get(key)

    def list_events(self) -> list[dict[str, Any]]:
        self._ensure_reachable()
        return self._store.list_events()

    def import_events(self, events: list[dict[str, Any]]) -> dict[str, int]:
        self._ensure_reachable()
        return self._store.import_events(events)

    def close(self) -> None:
        self._tmpdir.cleanup()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _ensure_reachable(self) -> None:
        if not self.reachable:
            raise NodeUnavailable(self.node_id)


class HttpNode:
    """HTTP adapter for one Cloudflare-published custom node.

    The adapter keeps the full URL private in operational output. Errors include
    only the host and status/body preview so failed labs can identify whether
    Cloudflare returned an Access page, a 502/503 route error, or a node API
    response without dumping complete tunnel URLs into logs.
    """

    def __init__(self, base_url: str, timeout: float = 2.0, label: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.node_id = label or _redacted_endpoint(base_url)
        self.user_agent = os.environ.get(
            "NODE_HTTP_USER_AGENT",
            "DecentralizedDbLab/1.0 (+https://developers.cloudflare.com/cloudflare-one/)",
        )

    def health(self) -> dict[str, Any]:
        payload = self._request("GET", "/health")
        self.node_id = payload.get("node_id", self.node_id)
        return payload

    def put(self, key: str, value: Any, actor: str = "client") -> dict[str, Any]:
        path = f"/kv/{urllib.parse.quote(key, safe='')}"
        return self._request("PUT", path, {"value": value, "actor": actor})

    def get(self, key: str) -> dict[str, Any] | None:
        path = f"/kv/{urllib.parse.quote(key, safe='')}"
        try:
            return self._request("GET", path)
        except NodeUnavailable as exc:
            if "HTTP 404" in str(exc):
                return None
            raise

    def list_events(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/events")
        return payload["events"]

    def import_events(self, events: list[dict[str, Any]]) -> dict[str, int]:
        return self._request("POST", "/events", {"events": events})

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None
        # Cloudflare WAF/Bot rules often reject the default Python urllib user
        # agent before traffic reaches the tunnel origin. Use an explicit lab
        # service identity so policy owners can allowlist it if needed.
        headers = {"Accept": "application/json", "User-Agent": self.user_agent}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            preview = exc.read(300).decode("utf-8", errors="replace").replace("\n", " ")
            raise NodeUnavailable(
                f"{_redacted_endpoint(self.base_url)} HTTP {exc.code}: {preview}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise NodeUnavailable(f"{_redacted_endpoint(self.base_url)}: {exc}") from exc


class SyncClient:
    """Coordinate custom-node reads/writes over a list of HTTP endpoints."""

    def __init__(self, nodes: list[Node]):
        self.nodes = nodes

    @classmethod
    def from_env(cls) -> "SyncClient":
        urls = [_normalize_url(url.strip()) for url in os.environ.get("NODE_URLS", "").split(",") if url.strip()]
        if not urls:
            raise ValueError("NODE_URLS must contain at least one node URL")
        timeout = float(os.environ.get("NODE_TIMEOUT_SECONDS", "2"))
        return cls([HttpNode(url, timeout=timeout, label=f"node-url-{index}") for index, url in enumerate(urls, 1)])

    def health(self) -> dict[str, Any]:
        reachable = []
        unreachable = []
        for node in self.nodes:
            try:
                reachable.append(node.health())
            except NodeUnavailable as exc:
                unreachable.append(str(exc))
        return {
            "reachable_nodes": len(reachable),
            "unreachable_nodes": unreachable,
            "nodes": reachable,
        }

    def put(self, key: str, value: Any, min_acks: int = 1, actor: str = "client") -> dict[str, Any]:
        """Write once, then import the same event into the remaining nodes."""

        acks = []
        errors = []
        event = None
        for node in self.nodes:
            try:
                if event is None:
                    event = node.put(key, value, actor=actor)
                else:
                    node.import_events([event])
                acks.append(node.node_id)
            except NodeUnavailable as exc:
                errors.append(str(exc))
        if len(acks) < min_acks:
            detail = "; ".join(errors) if errors else "no node errors were reported"
            raise QuorumUnavailable(
                f"required {min_acks} acknowledgements, got {len(acks)}; node errors: {detail}"
            )
        return {"acks": acks, "errors": errors, "events": [event] if event else []}

    def get(self, key: str, min_responses: int = 1, repair: bool = False) -> dict[str, Any]:
        if repair:
            self.sync_all()
        responses = []
        errors = []
        for node in self.nodes:
            try:
                state = node.get(key)
                if state is not None:
                    responses.append({"node_id": node.node_id, "state": state})
            except NodeUnavailable as exc:
                errors.append(str(exc))
        if len(responses) < min_responses:
            raise QuorumUnavailable(f"required {min_responses} responses, got {len(responses)}")
        winner = self._choose_winner(responses)
        return {"winner": winner, "responses": responses, "errors": errors}

    def _choose_winner(self, responses: list[dict[str, Any]]) -> dict[str, Any]:
        dominant = [
            candidate
            for candidate in responses
            if all(
                compare_vectors(candidate["state"]["vector"], other["state"]["vector"])
                in {"after", "equal"}
                for other in responses
            )
        ]
        if dominant:
            return max(dominant, key=lambda item: item["state"]["event_id"])
        return max(responses, key=lambda item: item["state"]["event_id"])

    def sync_all(self) -> dict[str, Any]:
        """Exchange all known events among reachable nodes."""

        reachable: list[Node] = []
        events_by_id: dict[str, dict[str, Any]] = {}
        errors = []
        for node in self.nodes:
            try:
                for event in node.list_events():
                    events_by_id[event["event_id"]] = event
                reachable.append(node)
            except NodeUnavailable as exc:
                errors.append(str(exc))

        imported = {}
        events = list(events_by_id.values())
        for node in reachable:
            result = node.import_events(events)
            imported[node.node_id] = result
        return {
            "reachable_nodes": len(reachable),
            "event_count": len(events),
            "imported": imported,
            "errors": errors,
        }


def _normalize_url(url: str) -> str:
    if url.startswith(("http://", "https://")):
        return url
    return f"https://{url}"


def _redacted_endpoint(url: str) -> str:
    """Return a stable non-secret endpoint label for operational diagnostics."""

    parsed = urllib.parse.urlparse(url)
    if not parsed.netloc:
        return "<invalid-url>"
    digest = hashlib.sha256(parsed.netloc.encode("utf-8")).hexdigest()[:10]
    return f"{parsed.scheme}://host-{digest}"
