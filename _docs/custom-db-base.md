# custom-db-base

This lab teaches the custom AP/event-store design in its brokered form. The
important rule is that the three database containers never connect directly to
each other and never join a shared Docker network. A NATS JetStream bus carries
commands, and one relay beside each node applies those commands to its local
custom node.

This is a good first lab because it shows the custom architecture without the
extra Cloudflare node tunnels. The tradeoff is also visible: NATS becomes shared
infrastructure for the experiment, so this is brokered logical replication, not
a fully peer-to-peer database cluster.

## What You Will Learn

- How the custom database stores immutable events in SQLite and materializes
  key/value state from those events.
- How NATS JetStream acts as the operation log when direct node TCP is
  forbidden.
- How relays enforce the network boundary between the shared bus and each
  private DB node network.
- How `MIN_APPLY_ACKS=2` models a 2-of-3 write acknowledgement rule.
- What the static checks prove, and what the runtime client scenario proves.

## Architecture At A Glance

```text
client container
      |
      | HTTP /health and /kv/<key>
      v
gateway  -- publishes commands and receives query replies -->  NATS JetStream
                                                                |
                         +--------------------------------------+--------------------------------------+
                         |                                      |                                      |
                         v                                      v                                      v
              relay1 on bus_net+node1_net          relay2 on bus_net+node2_net          relay3 on bus_net+node3_net
                         |                                      |                                      |
                         v                                      v                                      v
              custom-node1 on node1_net            custom-node2 on node2_net            custom-node3 on node3_net
```

The gateway can reach NATS. Each relay can reach NATS and exactly one local DB
node. The DB nodes themselves are only on `node1_net`, `node2_net`, or
`node3_net`. There are no `ports:` mappings, so the Docker host cannot connect
to the services through localhost.

## Network Topology And Isolation

This lab enforces the ground rule as: no direct DB-node-to-DB-node Docker TCP.
The custom DB containers are isolated behind separate Docker bridge networks,
and each one can only be reached by its matching relay.

| Service | Docker networks | Allowed communication |
| --- | --- | --- |
| `gateway` | `ingress_net`, `bus_net` | Receives client HTTP from `client` or Cloudflare and publishes NATS commands. |
| `event-bus` | `bus_net` | Stores the command stream; it never joins any node network. |
| `relay1` | `bus_net`, `node1_net` | Bridges NATS to `custom-node1` only. |
| `relay2` | `bus_net`, `node2_net` | Bridges NATS to `custom-node2` only. |
| `relay3` | `bus_net`, `node3_net` | Bridges NATS to `custom-node3` only. |
| `custom-node1..3` | One private `nodeN_net` each | Accept local HTTP only from the matching relay. |

Forbidden paths are just as important: `custom-node1` cannot resolve or open TCP
to `custom-node2` or `custom-node3`; DB nodes cannot reach `event-bus`; the
Docker host has no `ports:` mapping to any service; and the outside world can
only enter through `CLOUDFLARE_URL_EXTERNAL` when the `edge` profile is running.

The rationale is to simulate nodes hidden behind independent NAT boundaries:
database state is replicated by shipping commands through a brokered channel,
not by letting database processes dial each other directly.

## Persistent Volume Layout

The lab stores durable data in bind mounts under the repository-level
`_volumes/` directory, which is intentionally ignored by git:

| Path | Purpose |
| --- | --- |
| `../_volumes/custom-db-base/bus/nats` | NATS JetStream command log. |
| `../_volumes/custom-db-base/worker1/data` | SQLite data for `custom-node1`. |
| `../_volumes/custom-db-base/worker2/data` | SQLite data for `custom-node2`. |
| `../_volumes/custom-db-base/worker3/data` | SQLite data for `custom-node3`. |

Normal teardown should use `docker compose down`, not `down -v`. To reset this
lab intentionally, stop it and remove `../_volumes/custom-db-base`.

## Technology Stack

| Component | Role | Important configuration |
| --- | --- | --- |
| `custom-node1..3` | SQLite-backed custom event stores | `NODE_ID`, `DB_PATH=/data/node.db`, `PORT=8080` |
| `event-bus` | NATS JetStream operation log | `nats:2-alpine`, `-js`, bind mount under `_volumes/custom-db-base/bus` |
| `relay1..3` | Consume commands and apply them to one local node | `ENGINE=custom`, `LOCAL_HTTP_URL=http://custom-nodeN:8080` |
| `gateway` | Only client-facing API in the base lab | `NATS_URL`, `MIN_APPLY_ACKS=2`, `PORT=8080` |
| `cloudflared-external` | Optional public client ingress | `CLOUDFLARE_TOKEN_EXTERNAL`, profile `edge` |

## Configuration

The local brokered test can run without public Cloudflare traffic, but the
compose file still references Cloudflare variables. Source the parent `.env`
before rendering compose so the configuration is explicit and warnings are
avoided:

```bash
set -a
. ../.env
set +a
```

For Cloudflare ingress, the remotely managed tunnel represented by
`CLOUDFLARE_TOKEN_EXTERNAL` must already publish a hostname matching
`CLOUDFLARE_URL_EXTERNAL`. Because `cloudflared-external` uses
`network_mode: "service:gateway"`, the Cloudflare origin service should be
`http://localhost:8080` from inside the tunnel connector namespace. The
`PUBLIC_URL` environment value is documentation for the container; it does not
create a Cloudflare route by itself.

## Write Flow

1. The client sends `PUT /kv/<key>` to the gateway.
2. The gateway creates one command with a unique `command_id`.
3. The gateway publishes the command to the `DB_COMMANDS` JetStream stream.
4. Each relay consumes the command through its durable subscription.
5. A relay converts the command into one deterministic custom event.
6. The relay posts that event to `/events` on its local custom node only.
7. The local custom node inserts the event idempotently and updates local state.
8. The relay publishes an acknowledgement on NATS.
9. The gateway returns `200 OK` when at least two different relays acknowledge.
   If fewer than two relays acknowledge before the timeout, the response is
   `202 Accepted` with the lower `ack_count` visible in the JSON body.

## Read Flow

1. The client sends `GET /kv/<key>` to the gateway.
2. The gateway publishes a `db.query` message with a private reply inbox.
3. Every live relay queries its local custom node.
4. Relays publish their responses to the reply inbox.
5. The gateway returns the collected responses. This is a fan-out read through
   NATS, not a direct DB-node read.

## Run The Lab Locally

Run the commands from the repository root unless otherwise noted:

```bash
cd custom-db-base
./scripts/verify.sh

set -a
. ../.env
set +a

docker compose config >/tmp/custom-db-base.compose.yaml
docker compose up --build -d event-bus custom-node1 custom-node2 custom-node3 relay1 relay2 relay3 gateway
docker compose run --rm client
docker compose down
```

What each step proves:

- `./scripts/verify.sh` is a static guardrail. It checks for NATS, Cloudflare
  external ingress, isolated node networks, and the absence of host port
  forwarding.
- `docker compose config` proves the compose file renders with the environment
  variables available.
- `docker compose up` starts the local topology without any host ports.
- `docker compose run --rm client` executes a full write and read through the
  gateway, NATS, relays, and isolated custom nodes.

## Persistence Check

The persistence client first queries a stable key, writes an incremented
`run_count`, then queries the key again. Run it twice with a stop/start in
between; the second output should show `"saw_previous_data": true`.

```bash
cd custom-db-base
docker compose up --build -d event-bus custom-node1 custom-node2 custom-node3 relay1 relay2 relay3 gateway
docker compose --profile test run --rm persistence-client
docker compose down

docker compose up -d event-bus custom-node1 custom-node2 custom-node3 relay1 relay2 relay3 gateway
docker compose --profile test run --rm -e REQUIRE_PREVIOUS=1 persistence-client
docker compose down
```

## Run With Cloudflare Client Ingress

This starts the same brokered lab plus the external Cloudflare tunnel. It does
not add direct node communication.

```bash
cd custom-db-base
set -a
. ../.env
set +a

docker compose --profile edge up --build -d

API="${CLOUDFLARE_URL_EXTERNAL%/}"
curl -sS "$API/health"
curl -sS -X PUT "$API/kv/tutorial" \
  -H 'content-type: application/json' \
  -d '{"value":{"count":1}}'
curl -sS "$API/kv/tutorial"

docker compose --profile edge down
```

The only approved external client path is through
`CLOUDFLARE_URL_EXTERNAL`. `localhost:8080` on the Docker host should not work.

## Failure Drill

With the lab running, stop one relay and run the client again:

```bash
docker compose stop relay3
docker compose run --rm client python -m brokered.client put beta '{"count":2}'
docker compose run --rm client python -m brokered.client get beta
docker compose start relay3
```

The write should still be able to reach two acknowledgements if the other two
relays and nodes are healthy. If two relays or nodes are unavailable, the base
gateway reports the shortfall with `ack_count < required_acks` and an HTTP
`202 Accepted` response.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Compose warns that Cloudflare variables are blank | Source `../.env` before `docker compose config` or `up`. |
| `curl http://localhost:8080/health` fails on the host | Expected. This lab forbids host port forwarding. Use the test client container or Cloudflare. |
| Client write returns fewer than two acknowledgements | Inspect `docker compose logs --tail=100 gateway relay1 relay2 relay3 event-bus`. |
| Cloudflare returns 502 or 503 | Confirm the remote tunnel route points to `http://localhost:8080` for the external connector. |
| A relay repeatedly replays a command | Check the local custom-node logs; JetStream redelivers until the relay acknowledges after local apply. |

## Limitations

- This is not a production database. It is a lab for the network and replication
  shape.
- NATS is a central availability dependency in the base architecture.
- The custom conflict model is deliberately small: vector-clock conflicts are
  reduced deterministically, but there is no application-level merge policy.
- There is no authentication, TLS between internal containers, backup policy,
  admission control, or operational hardening.
- The external Cloudflare tunnel only solves client ingress. It does not remove
  the gateway and NATS availability dependencies in this base lab.
