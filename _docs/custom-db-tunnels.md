# custom-db-tunnels

This lab runs the custom event-store database with Cloudflare-published node
URLs. It is the tunnel variant of the custom architecture: the gateway does not
share a Docker network with any DB node, and there is no NATS bus. Instead, the
gateway receives `CLOUDFLARE_URL_1..3` from `.env` and calls those node URLs
through Cloudflare.

This is still not DB-node peer networking. The gateway coordinates requests.
Each custom node is published by its own adjacent `cloudflared-nodeN` connector,
and each connector shares only that node's network namespace.

## What You Will Learn

- How the custom AP/event-store behaves when all node access goes through HTTP
  Cloudflare tunnels.
- Why `network_mode: "service:custom-nodeN"` makes the tunnel origin local to
  one node without joining DB nodes together.
- How a 2-of-3 write acknowledgement rule works when one node URL is down.
- How read repair and event sync are modeled by the custom `SyncClient`.
- Why this is a last-resort direct-node-access lab, not the preferred base
  brokered architecture.

## Architecture At A Glance

```text
external client
      |
      | HTTPS to CLOUDFLARE_URL_EXTERNAL
      v
Cloudflare tunnel external -> gateway
                              |
                              | HTTPS to CLOUDFLARE_URL_1..3
        +---------------------+---------------------+
        |                     |                     |
        v                     v                     v
Cloudflare node1       Cloudflare node2       Cloudflare node3
connector              connector              connector
        |                     |                     |
        v                     v                     v
custom-node1           custom-node2           custom-node3
node1_net only         node2_net only         node3_net only
```

There are no host ports and no shared Docker network between the custom node
containers. The Cloudflare node URLs are the only direct node access path in
this lab.

## Network Topology And Isolation

This lab enforces the ground rule as: no direct DB-node-to-DB-node Docker TCP.
Unlike the base lab, there is no NATS bus. The gateway reaches nodes by their
Cloudflare-published HTTP URLs, which is the allowed last-resort direct path for
this tunnel variant.

| Service | Docker networks | Allowed communication |
| --- | --- | --- |
| `gateway` | `ingress_net` | Receives client HTTP and calls `CLOUDFLARE_URL_1..3`. |
| `cloudflared-external` | Shares `gateway` namespace | Publishes the gateway to the outside world. |
| `custom-node1..3` | One private `nodeN_net` each | Accept local HTTP only from its own tunnel connector namespace. |
| `cloudflared-node1..3` | Shares one `custom-nodeN` namespace | Publishes exactly one node URL through Cloudflare. |

Forbidden paths: no custom DB node is attached to another node's Docker network;
the gateway has no Docker network route to any node; the Docker host has no
published ports; and the outside world enters through Cloudflare URLs only. The
node URLs are direct diagnostic/test surfaces and should be treated as
privileged.

The rationale is to model DB nodes hidden behind independent NAT boundaries
where the only available direct route is a remotely managed tunnel endpoint.
This is less preferred than brokered pub/sub, but it keeps direct Docker
reachability out of the design.

## Persistent Volume Layout

Durable state is stored under ignored repository-local bind mounts:

| Path | Purpose |
| --- | --- |
| `../_volumes/custom-db-tunnels/worker1/data` | SQLite data for custom node 1. |
| `../_volumes/custom-db-tunnels/worker2/data` | SQLite data for custom node 2. |
| `../_volumes/custom-db-tunnels/worker3/data` | SQLite data for custom node 3. |

Use `docker compose down` for normal teardown. Remove
`../_volumes/custom-db-tunnels` only when you intentionally want a clean lab.

## Technology Stack

| Component | Role | Important configuration |
| --- | --- | --- |
| `gateway` | Client-facing coordinator | `NODE_URLS=${CLOUDFLARE_URL_1},...`, `MIN_APPLY_ACKS=2` |
| `custom-node1..3` | SQLite-backed event stores | Private `nodeN_net`, bind mounts under `_volumes/custom-db-tunnels` |
| `cloudflared-external` | Publishes the gateway | `--url http://127.0.0.1:8080`, `CLOUDFLARE_TOKEN_EXTERNAL`, profile `edge` |
| `cloudflared-node1..3` | Publish one custom node each | `--url http://127.0.0.1:8080`, `CLOUDFLARE_TOKEN_1..3`, profiles `edge` and `node-direct` |
| `SyncClient` | Gateway-side quorum/sync helper | HTTP calls to node URLs, read repair, event import |

## Cloudflare Configuration

This lab needs four HTTP Cloudflare routes:

| Variable | Purpose | Compose origin passed to `cloudflared tunnel run --url` |
| --- | --- | --- |
| `CLOUDFLARE_TOKEN_EXTERNAL` / `CLOUDFLARE_URL_EXTERNAL` | Client ingress to the gateway | `http://127.0.0.1:8080` inside the gateway namespace |
| `CLOUDFLARE_TOKEN_1` / `CLOUDFLARE_URL_1` | Direct test URL for custom node 1 | `http://127.0.0.1:8080` inside node 1's namespace |
| `CLOUDFLARE_TOKEN_2` / `CLOUDFLARE_URL_2` | Direct test URL for custom node 2 | `http://127.0.0.1:8080` inside node 2's namespace |
| `CLOUDFLARE_TOKEN_3` / `CLOUDFLARE_URL_3` | Direct test URL for custom node 3 | `http://127.0.0.1:8080` inside node 3's namespace |

The origin is loopback in all four rows because every cloudflared container uses
`network_mode: "service:..."` and therefore shares the target service's network
namespace. The compose file now passes the origin explicitly with `--url`;
`PUBLIC_URL` in compose remains documentation only and does not create DNS or
hostname routes. The Cloudflare hostname route must already exist for the token.

Run only one tunnel lab with these shared tokens at a time. Starting another
project with the same tunnel tokens can disconnect or confuse the active test.

## Profiles

- No profile: starts the gateway and custom nodes, but without node Cloudflare
  connectors the gateway cannot complete real node calls.
- `edge`: starts the external gateway tunnel and all three node tunnels.
- `node-direct`: starts the three node tunnels without the external gateway
  tunnel. This is useful for diagnostics, but it is not the full client-ingress
  lab.

## Write Flow

1. The client sends `PUT /kv/<key>` to `CLOUDFLARE_URL_EXTERNAL`.
2. Cloudflare forwards the request to `cloudflared-external`, which reaches the
   gateway on local port `8080`.
3. The gateway asks `SyncClient` to write the value with `MIN_APPLY_ACKS=2`.
4. `SyncClient` calls the first reachable node URL and creates one custom event.
5. `SyncClient` imports the same event into the remaining reachable nodes.
6. If at least two nodes acknowledge, the gateway returns `200 OK`.
7. If fewer than two nodes acknowledge, the gateway returns `503 Service
   Unavailable`.

## Read Flow

1. The client sends `GET /kv/<key>` to the external gateway URL.
2. The gateway calls `SyncClient.get(..., repair=True)`.
3. `SyncClient` first exchanges known events among reachable nodes with
   `sync_all()`.
4. `SyncClient` reads the key from all reachable nodes.
5. The winner is selected by vector-clock dominance where possible, then by
   deterministic event id ordering for concurrent values.
6. The gateway returns the winner, all reachable responses, and any node errors.

## Run Static Checks

```bash
cd custom-db-tunnels
./scripts/verify.sh

set -a
. ../.env
set +a

docker compose config >/tmp/custom-db-tunnels.compose.yaml
```

The static check proves that Cloudflare node variables exist, no host ports are
declared, and each node tunnel shares only its matching node namespace. It does
not prove that the remote Cloudflare routes are correctly configured.

## Persistence Check

The persistence client connects to the gateway, and the gateway then reaches the
nodes through `CLOUDFLARE_URL_1..3`. This requires valid node Cloudflare routes.
Run it twice without deleting `_volumes`; the second run should show previous
state:

```bash
cd custom-db-tunnels
set -a
. ../.env
set +a

docker compose --profile edge up --build -d
docker compose --profile edge --profile test run --rm persistence-client
docker compose --profile edge down

docker compose --profile edge up -d
docker compose --profile edge --profile test run --rm -e REQUIRE_PREVIOUS=1 persistence-client
docker compose --profile edge down
```

## Run The Tunnel Lab

```bash
cd custom-db-tunnels
set -a
. ../.env
set +a

docker compose --profile edge up --build -d

API="${CLOUDFLARE_URL_EXTERNAL%/}"
curl -sS "$API/health"
curl -sS -X PUT "$API/kv/tutorial" \
  -H 'content-type: application/json' \
  -d '{"value":{"engine":"custom-tunnels"}}'
curl -sS "$API/kv/tutorial"

docker compose --profile edge down
```

The health response should report reachable and unreachable nodes. If the node
routes are correctly configured, `reachable_nodes` should normally be `3`.

## Verifying The No-Direct-TCP Constraint

- `custom-node1..3` are each attached only to their own `nodeN_net`.
- The gateway is attached only to `ingress_net`, not to node networks.
- `cloudflared-nodeN` uses `network_mode: "service:custom-nodeN"` and therefore
  exposes only its own node origin.
- There are no `ports:` mappings. Host-local curl should not reach the gateway
  or nodes.

## Failure Drill

Stop one custom node while the tunnel lab is running:

```bash
docker compose stop custom-node3
API="${CLOUDFLARE_URL_EXTERNAL%/}"
curl -sS "$API/health"
curl -sS -X PUT "$API/kv/failure-drill" \
  -H 'content-type: application/json' \
  -d '{"value":{"node3":"down"}}'
docker compose start custom-node3
```

With two reachable node URLs, the write should still satisfy
`MIN_APPLY_ACKS=2`. With only one reachable node, the gateway should return
`503 Service Unavailable`.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Health shows zero reachable nodes | Confirm the three node Cloudflare hostnames are attached to the correct tunnel tokens and that the compose command includes `--url http://127.0.0.1:8080`. |
| External route works but writes fail quorum | At least two of `CLOUDFLARE_URL_1..3` must be reachable from the gateway container. |
| Cloudflare returns WAF error `1010` / Access denied | Cloudflare blocked the gateway's service-style HTTP client before traffic reached the node container. The gateway sends `User-Agent: DecentralizedDbLab/1.0`; allow that service identity or adjust the hostname's WAF, Browser Integrity, bot, or Access policy. |
| Cloudflare returns 503 | The connector may be down, the hostname may not be routed to this tunnel token, or the same token may be running in another lab. |
| Direct node URL is reachable from the public internet | Expected for this lab, but treat node URLs as privileged diagnostics and do not expose them in production. |
| `docker compose config` shows blank URLs | Source `../.env` before rendering compose. |

## Limitations

- The gateway is a client-ingress dependency. If it is down, clients cannot use
  the system even if two custom nodes are healthy.
- The node Cloudflare URLs are direct diagnostic surfaces and should be
  protected in any real deployment.
- Cloudflare availability, route configuration, and authentication policy are
  part of the experiment's availability story.
- This lab does not use the preferred brokered NATS communication path.
- The custom database is a prototype: no production auth, no encryption policy,
  no schema evolution workflow, and only a small deterministic conflict model.
