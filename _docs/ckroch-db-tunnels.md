# ckroch-db-tunnels

This lab is the last-resort native CockroachDB clustering experiment. Unlike
`ckroch-db-base`, this project does run CockroachDB with `start`, `--join`, and
advertised peer addresses. The peer addresses resolve to local Cloudflare TCP
proxy sidecars, not to remote CockroachDB containers on shared Docker networks.

Use this lab to test whether CockroachDB inter-node RPC can be carried through
Cloudflare TCP Access while preserving the no-direct-DB-node-TCP rule.

## What You Will Learn

- How the native CockroachDB tunnel variant differs from the brokered base lab.
- How `ckrochN-peer:26357` names are implemented through local proxy sidecars.
- Why CockroachDB inter-node RPC is separate from SQL client ingress.
- How `cockroach-init` fits into first cluster startup.
- Why a 3-node CockroachDB cluster needs two of three nodes for quorum.

## Architecture At A Glance

```text
external client
      |
      | HTTPS to CLOUDFLARE_URL_EXTERNAL
      v
Cloudflare external tunnel -> gateway -> ckroch1 SQL on node1_net

Cockroach inter-node RPC:

ckroch1 on node1_net
  ckroch1-peer -> local alias for itself
  ckroch2-peer -> node1-to-node2 cloudflared access tcp -> CLOUDFLARE_URL_2
  ckroch3-peer -> node1-to-node3 cloudflared access tcp -> CLOUDFLARE_URL_3

ckroch2 and ckroch3 use the same pattern for their remote peers.
```

The gateway exposes a small HTTP key/value API for testing. Native CockroachDB
replication, if the cluster forms, happens underneath through CockroachDB RPC on
port `26357`.

## Network Topology And Isolation

This lab enforces the ground rule as: no direct DB-node-to-DB-node Docker TCP.
Native CockroachDB still uses inter-node TCP, but remote peer names resolve to
local `cloudflared access tcp` sidecars rather than remote DB containers on a
shared Docker network.

| Service | Docker networks | Allowed communication |
| --- | --- | --- |
| `gateway` | `ingress_net`, `node1_net` | Exposes the HTTP test API and uses SQL on `ckroch1` only. |
| `ckroch1..3` | One private `nodeN_net` each | Runs CockroachDB and sees peer names on its local network. |
| `cloudflared-node1..3` | Shares one `ckrochN` namespace | Publishes the local node's RPC origin on port `26357`. |
| `nodeX-to-nodeY` | One private `nodeX_net` | Exposes a local peer alias and dials remote Cloudflare TCP. |
| `cockroach-init` | `node1_net` | Initializes the cluster through node 1 SQL after startup. |
| `cloudflared-external` | Shares `gateway` namespace | Publishes the gateway to the outside world. |

Forbidden paths: no CockroachDB container joins another CockroachDB container's
Docker network; the Docker host has no published SQL, RPC, or HTTP ports; and
the outside world enters only through Cloudflare routes. Native peer traffic is
allowed only through the tunnel sidecar exception.

The rationale is to test native CockroachDB quorum behavior while replacing
direct peer reachability with explicit Cloudflare TCP proxy boundaries. This is
a feasibility lab, not a recommendation to run production CockroachDB this way.

## Persistent Volume Layout

Durable state is stored under ignored repository-local bind mounts:

| Path | Purpose |
| --- | --- |
| `../_volumes/ckroch-db-tunnels/worker1/cockroach` | CockroachDB data for node 1. |
| `../_volumes/ckroch-db-tunnels/worker2/cockroach` | CockroachDB data for node 2. |
| `../_volumes/ckroch-db-tunnels/worker3/cockroach` | CockroachDB data for node 3. |

Use `docker compose down` for normal teardown. Remove
`../_volumes/ckroch-db-tunnels` only when you intentionally want a clean lab.

## Technology Stack

| Component | Role | Important configuration |
| --- | --- | --- |
| `ckroch1..3` | Native CockroachDB nodes | SQL `26257`, RPC `26357`, HTTP `8080`, `--insecure` |
| `nodeX-to-nodeY` | Local TCP proxy to remote peer RPC | Wrapper normalizes `CLOUDFLARE_URL_N`, then runs `cloudflared access tcp --hostname ... --url 0.0.0.0:26357` |
| `cloudflared-node1..3` | Publish each node's RPC origin | `--url tcp://127.0.0.1:26357`, node tunnel tokens, profile `edge` or `node-direct` |
| `cockroach-init` | First cluster initialization | Retries `COCKROACH_INIT_ATTEMPTS` bounded `timeout 10s cockroach init --insecure --host=ckroch1:26257` attempts and fails if init cannot complete |
| `gateway` | Test HTTP key/value API | Uses SQL endpoint `postgresql://root@ckroch1:26257/defaultdb?sslmode=disable` |
| `cloudflared-external` | Publishes the gateway | `--url http://127.0.0.1:8080`, external tunnel token, profile `edge` |

## Cloudflare Configuration

This lab needs one HTTP route and three TCP-capable node routes:

| Variable | Purpose | Compose origin passed to `cloudflared tunnel run --url` |
| --- | --- | --- |
| `CLOUDFLARE_TOKEN_EXTERNAL` / `CLOUDFLARE_URL_EXTERNAL` | Client ingress to the gateway | `http://127.0.0.1:8080` inside the gateway namespace |
| `CLOUDFLARE_TOKEN_1` / `CLOUDFLARE_URL_1` | CockroachDB node 1 inter-node RPC | `tcp://127.0.0.1:26357` inside node 1's namespace |
| `CLOUDFLARE_TOKEN_2` / `CLOUDFLARE_URL_2` | CockroachDB node 2 inter-node RPC | `tcp://127.0.0.1:26357` inside node 2's namespace |
| `CLOUDFLARE_TOKEN_3` / `CLOUDFLARE_URL_3` | CockroachDB node 3 inter-node RPC | `tcp://127.0.0.1:26357` inside node 3's namespace |

The node values used by `CLOUDFLARE_URL_1..3` must be hostnames accepted by
`cloudflared access tcp`, such as `node1.example.com`, not full `https://...`
URLs. Ordinary HTTP tunnel routes are not sufficient for CockroachDB inter-node
RPC. Automated TCP flows also need non-interactive authentication or private
routing; a browser login prompt inside a container will prevent the cluster from
forming. The Cloudflare hostname route must already point at the matching tunnel
token; compose supplies the local TCP origin, not the DNS route. The sidecar
wrapper accepts either a bare hostname or a full URL-shaped `.env` value and
strips scheme/path before calling `cloudflared access tcp`; it cannot convert an
HTTP-only Cloudflare route into a TCP-capable Access route.

Run only one tunnel lab with the shared Cloudflare tokens at a time.

## Profiles

- `edge`: starts the gateway tunnel, node tunnel connectors, CockroachDB nodes,
  TCP peer proxy sidecars, and `cockroach-init`.
- `node-direct`: starts node-side tunnel pieces without the external gateway
  tunnel and without `cockroach-init`. Use this only for diagnostics.

## Native CockroachDB Peer Flow

1. Each CockroachDB node starts with `--join=ckroch1-peer:26357,ckroch2-peer:26357,ckroch3-peer:26357`.
2. Each node listens for inter-node RPC on its local service name and advertises
   `ckrochN-peer:26357`.
3. The local peer alias points to the local node on its own network.
4. Remote peer aliases point to local `cloudflared access tcp` sidecars.
5. Those sidecars dial the remote node Cloudflare URL and expose local TCP
   listeners on port `26357`.
6. CockroachDB performs native cluster communication over those peer addresses.
7. `cockroach-init` retries cluster initialization after startup. Each attempt
   is bounded with `timeout 10s` by default, the default attempt count is `12`,
   and the helper exits non-zero if initialization cannot complete.

Successful `cockroach-init` completion is useful evidence, but still inspect
runtime status and logs when diagnosing a tunnel cluster. Cloudflare TCP,
authentication, or peer alias failures can still keep the native cluster from
becoming useful.

## Client Data Flow

1. The external client calls `CLOUDFLARE_URL_EXTERNAL`.
2. Cloudflare forwards to `cloudflared-external`.
3. The gateway receives `/health` or `/kv/<key>` over HTTP.
4. The gateway talks to the local SQL endpoint on `ckroch1`.
5. CockroachDB replicates through native inter-node RPC if the cluster is
   healthy.

The gateway depends on node 1 for this test API. A CockroachDB majority on other
nodes does not automatically provide a second client ingress path.

## Run Static Checks

```bash
cd ckroch-db-tunnels
./scripts/verify.sh

set -a
. ../.env
set +a

docker compose config >/tmp/ckroch-db-tunnels.compose.yaml
```

The static check proves that the compose file includes CockroachDB join flags,
Cloudflare node variables, TCP proxy sidecars, `cockroach-init`, and no host
ports. It does not prove that Cloudflare TCP Access is correctly configured.

## Persistence Check

The persistence client uses the HTTP gateway on `ingress_net`; the gateway uses
node 1 SQL, and CockroachDB handles native replication underneath if the cluster
formed. Run it twice without deleting `_volumes`; the second run should show
previous state:

```bash
cd ckroch-db-tunnels
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

## Run The Tunnel Experiment

```bash
cd ckroch-db-tunnels
set -a
. ../.env
set +a

docker compose --profile edge up --build -d

docker compose --profile edge logs --tail=100 cockroach-init ckroch1 ckroch2 ckroch3

API="${CLOUDFLARE_URL_EXTERNAL%/}"
curl -sS "$API/health"
curl -sS -X PUT "$API/kv/tutorial" \
  -H 'content-type: application/json' \
  -d '{"value":{"engine":"cockroach-tunnels"}}'
curl -sS "$API/kv/tutorial"

docker compose --profile edge down
```

If the SQL API fails at first, wait for cluster initialization and inspect the
CockroachDB logs. Native cluster startup is more timing-sensitive than the base
logical-replica labs.

## Verifying The No-Direct-TCP Constraint

- `docker compose config` should show each `ckrochN` DB service on only its own
  node network.
- Remote `ckrochN-peer` names should belong to proxy sidecars, not remote DB
  containers.
- There should be no host `ports:` mappings.
- The only external client path should be `CLOUDFLARE_URL_EXTERNAL`.

## Failure Drill

After the cluster has formed, stop one CockroachDB node and its related tunnel
pieces:

```bash
docker compose --profile edge stop ckroch3 cloudflared-node3 node1-to-node3 node2-to-node3
API="${CLOUDFLARE_URL_EXTERNAL%/}"
curl -sS -X PUT "$API/kv/failure-drill" \
  -H 'content-type: application/json' \
  -d '{"value":{"node3":"down"}}'
curl -sS "$API/kv/failure-drill"
docker compose --profile edge start ckroch3 cloudflared-node3 node1-to-node3 node2-to-node3
```

A native 3-node CockroachDB cluster should tolerate one failed node for quorum.
It cannot tolerate two failed nodes for writes.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Cloudflare returns WAF error `1010` / Access denied | The request was blocked by Cloudflare policy before it reached the container. For HTTP checks, allow the lab service client or adjust WAF, Browser Integrity, bot, or Access rules on the hostname. |
| Cluster never initializes | Confirm all three node routes are TCP-capable, point at the right tunnel tokens, and that compose includes `--url tcp://127.0.0.1:26357`. |
| `cloudflared access tcp` waits for login | Configure non-interactive service auth or private routing before running the lab. |
| `cloudflared access tcp` logs `websocket: bad handshake` | The hostname is behaving like an ordinary HTTP tunnel route. Reconfigure the Cloudflare route as a TCP-capable Access/private-network route for this hostname. |
| `cockroach-init` exits non-zero | Inspect `ckroch1..3` logs; the init helper retries bounded attempts and fails loudly if the cluster cannot form. |
| Need a shorter failure during diagnostics | Run with `COCKROACH_INIT_ATTEMPTS=3` in the shell before `docker compose --profile edge up`. |
| External `/health` works but `/kv` fails | The gateway is up, but node 1 SQL or cluster init may not be ready. |
| Two nodes are stopped | Native CockroachDB quorum is lost; writes are expected to fail. |

## Limitations

- This is an experimental last-resort topology for native CockroachDB RPC over
  Cloudflare TCP.
- CockroachDB runs in insecure mode and uses `cockroachdb/cockroach:latest`.
- Cloudflare latency, reconnect behavior, and Access policy can affect native
  database peer traffic.
- The gateway is a single client-ingress dependency in this lab.
- `cockroach-init` is intentionally simple and timing-sensitive.
- Passing this lab is not a production recommendation; it is an end-to-end
  feasibility and failure-mode test.
