# ckroch-db-base

This lab uses CockroachDB as a local SQL storage engine in three isolated
logical replicas. It is intentionally not a native CockroachDB cluster. Each
database container runs `start-single-node`, and the compose file forbids
Cockroach peer joins.

The replication layer in this base lab is outside CockroachDB. The gateway
publishes commands to NATS JetStream, and one relay beside each CockroachDB
container applies the same SQL locally. Native CockroachDB quorum and range
replication are tested only in `ckroch-db-tunnels`.

## What You Will Learn

- How CockroachDB can be used as an isolated local SQL engine under a brokered
  replication layer.
- Why `start-single-node` is used here instead of native CockroachDB clustering.
- How relays provide the only bridge from the NATS bus to private DB networks.
- How to inspect acknowledgement behavior when one logical replica is missing.
- What this lab cannot say about real CockroachDB distributed SQL.

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
 ckroch1 single-node SQL           ckroch2 single-node SQL           ckroch3 single-node SQL
```

The directory and service names use `ckroch`, but the database engine is
CockroachDB.

## Network Topology And Isolation

This lab enforces the ground rule as: no direct DB-node-to-DB-node Docker TCP.
Each CockroachDB container is an isolated single-node SQL store. CockroachDB
native peer RPC is intentionally absent from this base project.

| Service | Docker networks | Allowed communication |
| --- | --- | --- |
| `gateway` | `ingress_net`, `bus_net` | Receives client HTTP and coordinates NATS writes/reads. |
| `event-bus` | `bus_net` | Durable operation log; not attached to any Cockroach node network. |
| `relay1` | `bus_net`, `node1_net` | Applies SQL to `ckroch1` only. |
| `relay2` | `bus_net`, `node2_net` | Applies SQL to `ckroch2` only. |
| `relay3` | `bus_net`, `node3_net` | Applies SQL to `ckroch3` only. |
| `ckroch1..3` | One private `nodeN_net` each | Accept SQL only from the matching relay. |

Forbidden paths: no CockroachDB container can open TCP to another CockroachDB
container; the gateway never connects directly to SQL; the Docker host has no
published SQL or HTTP port; and the outside world reaches only the gateway via
Cloudflare when `edge` is enabled.

The rationale is to compare CockroachDB as a local SQL engine under brokered
logical replication against the native tunnel experiment in `ckroch-db-tunnels`.
It avoids claiming native CockroachDB distribution when peer RPC is forbidden.

## Persistent Volume Layout

Durable state is stored under ignored repository-local bind mounts:

| Path | Purpose |
| --- | --- |
| `../_volumes/ckroch-db-base/bus/nats` | NATS JetStream command log. |
| `../_volumes/ckroch-db-base/worker1/cockroach` | CockroachDB data for node 1. |
| `../_volumes/ckroch-db-base/worker2/cockroach` | CockroachDB data for node 2. |
| `../_volumes/ckroch-db-base/worker3/cockroach` | CockroachDB data for node 3. |

Use `docker compose down` for normal teardown. Remove
`../_volumes/ckroch-db-base` only when you intentionally want a clean lab.

## Technology Stack

| Component | Role | Important configuration |
| --- | --- | --- |
| `ckroch1..3` | Isolated single-node CockroachDB stores | `cockroachdb/cockroach:latest`, `start-single-node`, `--insecure` |
| `event-bus` | Durable command log | NATS JetStream |
| `relay1..3` | Apply SQL to one local CockroachDB node | `ENGINE=cockroach`, local `LOCAL_DB_DSN` |
| `gateway` | Client API and acknowledgement coordinator | `MIN_APPLY_ACKS=2`, `NATS_URL` |
| `cloudflared-external` | Optional client ingress | Profile `edge`, external tunnel token |

## Configuration

Before rendering compose, source the parent `.env`:

```bash
set -a
. ../.env
set +a
```

For the optional Cloudflare ingress, the remote route for
`CLOUDFLARE_TOKEN_EXTERNAL` should point to `http://localhost:8080`. The
container uses `network_mode: "service:gateway"`, so `localhost` from the
Cloudflare connector is the gateway network namespace.

CockroachDB is run in insecure mode because this is a lab. The image is
currently `cockroachdb/cockroach:latest`, which is convenient for experimentation
but less reproducible than a pinned version.

## Write Flow

1. The client sends `PUT /kv/<key>` to the brokered gateway.
2. The gateway publishes one command with a unique `command_id` to NATS
   JetStream.
3. Each relay consumes the command from the durable stream.
4. The relay connects to only its local CockroachDB SQL endpoint:
   `postgresql://root@ckrochN:26257/defaultdb?sslmode=disable`.
5. The relay creates `_applied_events` and `kv` tables if needed.
6. The relay records the command id and performs an `UPSERT` into `kv`.
7. The relay acknowledges to the gateway over NATS after local SQL apply.
8. The gateway returns `200 OK` when at least two relays acknowledge, otherwise
   `202 Accepted` with the lower `ack_count`.

The value write is replay-tolerant. The lab does not implement a complete
exactly-once SQL replication protocol.

## Read Flow

1. The client sends `GET /kv/<key>` to the gateway.
2. The gateway broadcasts a NATS query with a reply inbox.
3. Each live relay queries its local CockroachDB instance.
4. Relays publish their local results to the reply inbox.
5. The gateway returns the collected replica responses.

No CockroachDB node talks to another CockroachDB node in this base lab.

## Run The Lab Locally

```bash
cd ckroch-db-base
./scripts/verify.sh

set -a
. ../.env
set +a

docker compose config >/tmp/ckroch-db-base.compose.yaml
docker compose up --build -d event-bus ckroch1 ckroch2 ckroch3 relay1 relay2 relay3 gateway
docker compose run --rm client
docker compose down
```

CockroachDB startup can take longer than the Python services. If the first e2e
client run starts too early, inspect logs and rerun the client once the nodes
are ready.

## Persistence Check

The persistence client talks to the brokered gateway only. Run it twice without
deleting `_volumes`; the second run should show previous state:

```bash
cd ckroch-db-base
docker compose up --build -d event-bus ckroch1 ckroch2 ckroch3 relay1 relay2 relay3 gateway
docker compose --profile test run --rm persistence-client
docker compose down

docker compose up -d event-bus ckroch1 ckroch2 ckroch3 relay1 relay2 relay3 gateway
docker compose --profile test run --rm -e REQUIRE_PREVIOUS=1 persistence-client
docker compose down
```

## Run With Cloudflare Client Ingress

```bash
cd ckroch-db-base
set -a
. ../.env
set +a

docker compose --profile edge up --build -d

API="${CLOUDFLARE_URL_EXTERNAL%/}"
curl -sS "$API/health"
curl -sS -X PUT "$API/kv/tutorial" \
  -H 'content-type: application/json' \
  -d '{"value":{"engine":"cockroach-base"}}'
curl -sS "$API/kv/tutorial"

docker compose --profile edge down
```

The external tunnel publishes the gateway only. CockroachDB SQL and HTTP
interfaces are not exposed through host ports.

## Verifying The No-Direct-TCP Constraint

- `./scripts/verify.sh` rejects `--join`, `--listen-addr`, and host port
  forwarding in this base project.
- `docker compose config` should show each `ckrochN` service attached only to
  its own `nodeN_net`.
- Relays are the only services that attach to both `bus_net` and a node network.
- The Docker host should not have direct access to `26257` or CockroachDB HTTP
  on `8080`.

## Failure Drill

```bash
docker compose stop relay3
docker compose run --rm client python -m brokered.client put beta '{"count":2}'
docker compose run --rm client python -m brokered.client get beta
docker compose start relay3
```

With two healthy relays and nodes, writes can still reach the configured
acknowledgement requirement. If two nodes are down, this base gateway reports
the shortage rather than proving a native Cockroach quorum.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Relay logs show SQL connection failures | CockroachDB may still be starting; inspect `docker compose logs --tail=100 ckroch1 relay1`. |
| Static checks complain about join flags | Native CockroachDB clustering belongs in `ckroch-db-tunnels`, not this base lab. |
| Cloudflare route returns 502 or 503 | The external tunnel route should target `http://localhost:8080` inside the connector namespace. |
| Client output has fewer than two acknowledgements | Inspect `gateway`, `event-bus`, and all relay logs. |
| You expected Cockroach range replication | This lab does not create a CockroachDB cluster; each node is single-node. |

## Limitations

- This lab does not test CockroachDB distributed SQL, range replication, lease
  holders, or native quorum behavior.
- NATS is the central command log and is required for brokered writes and reads.
- CockroachDB runs with `--insecure`; this is not a security model.
- The schema is a toy key/value table plus a replay-tolerant command table.
- The use of `cockroachdb/cockroach:latest` makes exact version reproduction
  weaker than a pinned production lab.
