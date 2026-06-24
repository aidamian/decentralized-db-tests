# rqlite-db-base

This lab uses rqlite as the local storage engine inside three isolated logical
replicas. It is intentionally not a native rqlite cluster. There is no rqlite
Raft peer join, no `-bootstrap-expect`, and no direct TCP path between rqlite
containers.

Instead, the gateway publishes logical write commands to NATS JetStream. One
relay per node consumes those commands and applies SQL through the local rqlite
HTTP API. This makes the network constraint easy to inspect: the rqlite
containers never share a Docker network with each other or with the NATS bus.

## What You Will Learn

- How to use an existing open source database engine as a local replica while
  moving the replication layer outside the engine.
- Why this base lab is logical replication, not rqlite Raft clustering.
- How NATS JetStream and relays preserve the no-direct-node-TCP rule.
- How the local e2e client verifies the brokered write and read path.
- Where the consistency and availability limits are when native consensus is
  not being used.

## Architecture At A Glance

```text
client container
      |
      v
gateway  -- command stream and query fan-out -->  NATS JetStream
                                                  |
              +-----------------------------------+-----------------------------------+
              |                                   |                                   |
              v                                   v                                   v
 relay1 on bus_net+node1_net       relay2 on bus_net+node2_net       relay3 on bus_net+node3_net
              |                                   |                                   |
              v                                   v                                   v
 rqlite1 single-node store         rqlite2 single-node store         rqlite3 single-node store
```

Each rqlite service exposes its HTTP API and Raft port only to its private Docker
network. In this base lab, the Raft port is not used for clustering.

## Network Topology And Isolation

This lab enforces the ground rule as: no direct DB-node-to-DB-node Docker TCP.
The rqlite containers are isolated single-node stores; they do not use native
Raft clustering in this base project.

| Service | Docker networks | Allowed communication |
| --- | --- | --- |
| `gateway` | `ingress_net`, `bus_net` | Receives client HTTP and publishes logical write/query messages to NATS. |
| `event-bus` | `bus_net` | Durable operation log; never attached to node networks. |
| `relay1` | `bus_net`, `node1_net` | Applies SQL to `rqlite1` only. |
| `relay2` | `bus_net`, `node2_net` | Applies SQL to `rqlite2` only. |
| `relay3` | `bus_net`, `node3_net` | Applies SQL to `rqlite3` only. |
| `rqlite1..3` | One private `nodeN_net` each | Accept local HTTP from the matching relay. |

Forbidden paths: no rqlite container can resolve or open TCP to another rqlite
container; the gateway does not join any node network; the Docker host has no
published rqlite port; and the outside world reaches the lab only through the
external Cloudflare tunnel to the gateway.

The rationale is to demonstrate rqlite as an embedded local database engine
while the replication mechanism is the brokered command stream. This avoids
pretending that native Raft can work without a permitted peer transport.

## Persistent Volume Layout

Durable state is stored under ignored repository-local bind mounts:

| Path | Purpose |
| --- | --- |
| `../_volumes/rqlite-db-base/bus/nats` | NATS JetStream command log. |
| `../_volumes/rqlite-db-base/worker1/rqlite` | rqlite data for node 1. |
| `../_volumes/rqlite-db-base/worker2/rqlite` | rqlite data for node 2. |
| `../_volumes/rqlite-db-base/worker3/rqlite` | rqlite data for node 3. |

Use `docker compose down` for normal teardown. Remove
`../_volumes/rqlite-db-base` only when you intentionally want a clean lab.

## Technology Stack

| Component | Role | Important configuration |
| --- | --- | --- |
| `rqlite1..3` | Isolated single-node rqlite stores | `rqlite/rqlite:10.2.1`, HTTP `4001`, Raft `4002` |
| `event-bus` | Durable command log | NATS JetStream bind mount under `_volumes/rqlite-db-base/bus` |
| `relay1..3` | Apply gateway commands to local rqlite | `ENGINE=rqlite`, `LOCAL_HTTP_URL=http://rqliteN:4001` |
| `gateway` | Only client-facing brokered API | `MIN_APPLY_ACKS=2`, `NATS_URL=nats://event-bus:4222` |
| `cloudflared-external` | Optional public client ingress | Profile `edge`, external tunnel token |

## Configuration

Source the parent `.env` before compose rendering:

```bash
set -a
. ../.env
set +a
```

The base rqlite lab only uses `CLOUDFLARE_TOKEN_EXTERNAL` and
`CLOUDFLARE_URL_EXTERNAL` when the `edge` profile is enabled. The remote
Cloudflare tunnel route must already exist. Because the tunnel connector shares
the gateway network namespace, the external Cloudflare route should target
`http://localhost:8080`.

The rqlite services intentionally omit `-join` and `-bootstrap-expect`. Those
flags belong to `rqlite-db-tunnels`, where the lab attempts native Raft over
Cloudflare TCP sidecars.

## Write Flow

1. The client sends `PUT /kv/<key>` to the gateway.
2. The gateway publishes one command to the NATS JetStream command stream.
3. Each relay receives the command through a durable JetStream subscription.
4. The relay executes SQL against its local rqlite HTTP API:
   - create `_applied_events` if needed;
   - create `kv` if needed;
   - record the command id;
   - upsert the key/value JSON payload.
5. The relay acknowledges to the gateway over NATS after local SQL apply.
6. The gateway returns `200 OK` when at least two relays acknowledge. If fewer
   than two relays acknowledge before timeout, it returns `202 Accepted` with
   the lower `ack_count`.

The SQL is replay-tolerant for the key/value result. It is not a full
exactly-once replication protocol; replayed commands may update metadata such as
timestamps.

## Read Flow

1. The client sends `GET /kv/<key>` to the gateway.
2. The gateway sends a NATS `db.query` request containing a reply inbox.
3. Each live relay queries its local rqlite store with `SELECT value_json`.
4. Relays publish their local answers to the reply inbox.
5. The gateway returns all collected responses.

No rqlite node is contacted directly by the gateway or by another rqlite node.

## Run The Lab Locally

```bash
cd rqlite-db-base
./scripts/verify.sh

set -a
. ../.env
set +a

docker compose config >/tmp/rqlite-db-base.compose.yaml
docker compose up --build -d event-bus rqlite1 rqlite2 rqlite3 relay1 relay2 relay3 gateway
docker compose run --rm client
docker compose down
```

The expected client output is JSON containing `health`, `put`, and `get`
sections. In the `put` section, `ack_count` should normally be `3`; with one
relay or node down, `2` is still enough for the configured quorum.

## Persistence Check

The persistence client uses the brokered gateway path, not direct rqlite access.
Run it twice without deleting `_volumes`; the second run should report previous
data:

```bash
cd rqlite-db-base
docker compose up --build -d event-bus rqlite1 rqlite2 rqlite3 relay1 relay2 relay3 gateway
docker compose --profile test run --rm persistence-client
docker compose down

docker compose up -d event-bus rqlite1 rqlite2 rqlite3 relay1 relay2 relay3 gateway
docker compose --profile test run --rm -e REQUIRE_PREVIOUS=1 persistence-client
docker compose down
```

## Run With Cloudflare Client Ingress

```bash
cd rqlite-db-base
set -a
. ../.env
set +a

docker compose --profile edge up --build -d

API="${CLOUDFLARE_URL_EXTERNAL%/}"
curl -sS "$API/health"
curl -sS -X PUT "$API/kv/tutorial" \
  -H 'content-type: application/json' \
  -d '{"value":{"engine":"rqlite-base"}}'
curl -sS "$API/kv/tutorial"

docker compose --profile edge down
```

Only the gateway is published through Cloudflare. The rqlite nodes are not
public and still do not share Docker networks.

## Verifying The No-Direct-TCP Constraint

- `./scripts/verify.sh` rejects host port forwarding and native rqlite join
  flags in this base project.
- `docker compose config` should show each rqlite service on only its own
  `nodeN_net`.
- The gateway service is attached to `bus_net` and `ingress_net`, not to any
  rqlite node network.
- `localhost:4001` and `localhost:4002` on the Docker host should not expose
  rqlite.

## Failure Drill

```bash
docker compose stop relay3
docker compose run --rm client python -m brokered.client put beta '{"count":2}'
docker compose run --rm client python -m brokered.client get beta
docker compose start relay3
```

With two healthy relays, the write should still meet `MIN_APPLY_ACKS=2`. If the
event bus is down, the gateway cannot publish commands. If the gateway is down,
clients have no ingress path even if the three stores still exist.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Static checks fail on native join flags | This base project must not use `-join` or `-bootstrap-expect`; use `rqlite-db-tunnels` for native Raft. |
| Client times out on write | Check `gateway`, `event-bus`, and relay logs. rqlite startup can lag behind relay startup. |
| Cloudflare route fails | Confirm the external tunnel route targets `http://localhost:8080` inside the connector namespace. |
| Query responses disagree | Inspect relay logs and run another write/read cycle; this lab has logical replicas, not a native consensus read. |
| Host-local curl fails | Expected. There are no host ports. Use `docker compose run --rm client` or Cloudflare. |

## Limitations

- This is not rqlite clustering and does not test rqlite Raft semantics.
- NATS is the central command log and is required for writes and brokered reads.
- Reads return collected replica responses; they are not native rqlite
  linearizable cluster reads.
- SQL apply is replay-tolerant for the stored value, but this is not a complete
  exactly-once replication system.
- The lab has no production security hardening, no backup workflow, and no
  automatic membership management.
