# rqlite-db-tunnels

This lab is the last-resort native rqlite clustering experiment. Unlike
`rqlite-db-base`, this project does use rqlite Raft flags: every node has
`-bootstrap-expect 3` and a `-join` list. The difference is that peer names do
not resolve to remote DB containers on a shared Docker network. They resolve to
local `cloudflared access tcp` proxy sidecars.

Use this lab to test whether native rqlite Raft can form over Cloudflare TCP
Access while preserving the rule that DB containers do not have direct Docker
TCP access to each other.

## What You Will Learn

- How the tunnel variant differs from the brokered rqlite base project.
- How peer aliases such as `rqlite2-peer` are implemented with local TCP proxy
  sidecars.
- Why ordinary HTTP Cloudflare routes are not enough for Raft peer traffic.
- How client ingress through the gateway is separate from Raft inter-node
  traffic.
- Why a native 3-node quorum can tolerate one failed node, but not two.

## Architecture At A Glance

```text
external client
      |
      | HTTPS to CLOUDFLARE_URL_EXTERNAL
      v
Cloudflare external tunnel -> gateway -> rqlite1 HTTP API on node1_net

Raft peer traffic:

rqlite1 on node1_net
  rqlite1-peer -> local alias for itself
  rqlite2-peer -> node1-to-node2 cloudflared access tcp -> CLOUDFLARE_URL_2
  rqlite3-peer -> node1-to-node3 cloudflared access tcp -> CLOUDFLARE_URL_3

rqlite2 and rqlite3 have the same pattern for their remote peers.
```

The DB containers remain isolated: `rqlite1` is only on `node1_net`, `rqlite2`
only on `node2_net`, and `rqlite3` only on `node3_net`. The sidecars provide the
last-resort TCP overlay.

## Network Topology And Isolation

This lab enforces the ground rule as: no direct DB-node-to-DB-node Docker TCP.
Native rqlite Raft still uses TCP, but every remote peer name resolves to a
local `cloudflared access tcp` sidecar instead of a remote DB container.

| Service | Docker networks | Allowed communication |
| --- | --- | --- |
| `gateway` | `ingress_net`, `node1_net` | Proxies client HTTP to `rqlite1` only. |
| `rqlite1..3` | One private `nodeN_net` each | Runs native rqlite; sees peer names on its local network. |
| `cloudflared-node1..3` | Shares one `rqliteN` namespace | Publishes the local node's Raft TCP origin. |
| `nodeX-to-nodeY` | One private `nodeX_net` | Exposes a local peer alias and dials remote Cloudflare TCP. |
| `cloudflared-external` | Shares `gateway` namespace | Publishes the gateway to the outside world. |

Forbidden paths: no rqlite DB container is attached to another rqlite DB
container's Docker network; the Docker host has no published rqlite ports; and
the outside world reaches the lab only through the external gateway URL or the
Cloudflare Access TCP endpoints configured for peer traffic.

The rationale is to preserve native rqlite Raft semantics while replacing the
normally direct peer network with an explicit tunnel/proxy boundary. This tests
feasibility of the last-resort tunnel approach without weakening Docker network
isolation.

## Persistent Volume Layout

Durable state is stored under ignored repository-local bind mounts:

| Path | Purpose |
| --- | --- |
| `../_volumes/rqlite-db-tunnels/worker1/rqlite` | rqlite data for node 1. |
| `../_volumes/rqlite-db-tunnels/worker2/rqlite` | rqlite data for node 2. |
| `../_volumes/rqlite-db-tunnels/worker3/rqlite` | rqlite data for node 3. |

Use `docker compose down` for normal teardown. Remove
`../_volumes/rqlite-db-tunnels` only when you intentionally want a clean lab.

## Technology Stack

| Component | Role | Important configuration |
| --- | --- | --- |
| `rqlite1..3` | Native rqlite nodes | `rqlite/rqlite:10.2.1`, HTTP `4001`, Raft `4002` |
| `nodeX-to-nodeY` | Local TCP proxy to a remote peer | Wrapper normalizes `CLOUDFLARE_URL_N`, then runs `cloudflared access tcp --hostname ... --url 0.0.0.0:4002` |
| `cloudflared-node1..3` | Publish each node's Raft TCP origin | `--url tcp://127.0.0.1:4002`, node tunnel tokens, profile `edge` or `node-direct` |
| `gateway` | HTTP client ingress proxy to node 1 | `RQLITE_HTTP_URL=http://rqlite1:4001` |
| `rqlite-leader-init` | Requests leadership transfer to node 1 | Profile `edge`, local HTTP to `rqlite1` |
| `cloudflared-external` | Publishes the gateway | `--url http://127.0.0.1:8080`, `CLOUDFLARE_TOKEN_EXTERNAL`, profile `edge` |

## Cloudflare Configuration

This lab needs one HTTP route and three TCP-capable node routes:

| Variable | Purpose | Compose origin passed to `cloudflared tunnel run --url` |
| --- | --- | --- |
| `CLOUDFLARE_TOKEN_EXTERNAL` / `CLOUDFLARE_URL_EXTERNAL` | Client ingress to the gateway | `http://127.0.0.1:8080` inside the gateway namespace |
| `CLOUDFLARE_TOKEN_1` / `CLOUDFLARE_URL_1` | rqlite node 1 Raft TCP | `tcp://127.0.0.1:4002` inside node 1's namespace |
| `CLOUDFLARE_TOKEN_2` / `CLOUDFLARE_URL_2` | rqlite node 2 Raft TCP | `tcp://127.0.0.1:4002` inside node 2's namespace |
| `CLOUDFLARE_TOKEN_3` / `CLOUDFLARE_URL_3` | rqlite node 3 Raft TCP | `tcp://127.0.0.1:4002` inside node 3's namespace |

The node values used by `CLOUDFLARE_URL_1..3` must be hostnames accepted by
`cloudflared access tcp`, such as `node1.example.com`, not full `https://...`
URLs. If they are ordinary HTTP tunnel routes, native rqlite clustering will not
form. Automated containers also need non-interactive Access handling, such as
service authentication or a private routing setup; a browser login prompt inside
a container will block the cluster. The hostname route must already point at the
matching Cloudflare tunnel token; compose supplies the local TCP origin, not the
Cloudflare DNS route. The sidecar wrapper accepts either a bare hostname or a
full URL-shaped `.env` value and strips scheme/path before calling
`cloudflared access tcp`; it cannot convert an HTTP-only Cloudflare route into a
TCP-capable Access route.

Run only one tunnel lab with the shared Cloudflare tokens at a time.

## Profiles

- `edge`: starts the gateway tunnel, the node tunnel connectors, the rqlite
  nodes, the TCP peer proxy sidecars, and `rqlite-leader-init`.
- `node-direct`: starts node-side tunnel pieces without the external gateway
  tunnel. This is diagnostic only; it is not the full client-ingress lab.

## Native rqlite Peer Flow

1. Each rqlite node starts with `-bootstrap-expect 3`.
2. Each rqlite node advertises its Raft address as `rqliteN-peer:4002`.
3. For the local node, that peer name is a local alias on the same node network.
4. For remote nodes, that peer name is an alias on a local `cloudflared access
   tcp` sidecar.
5. The sidecar dials the remote `CLOUDFLARE_URL_N` and exposes a local TCP
   listener on port `4002`.
6. rqlite performs normal Raft communication against those peer addresses.

From rqlite's perspective it has TCP peers. From Docker's perspective no rqlite
container is connected to another rqlite container's network.

## Client Data Flow

1. The external client calls `CLOUDFLARE_URL_EXTERNAL`.
2. Cloudflare forwards to `cloudflared-external`.
3. The gateway proxies the HTTP request to `http://rqlite1:4001`.
4. rqlite node 1 handles the HTTP API request.
5. Native rqlite Raft replication, if the cluster formed, happens through the
   Cloudflare TCP peer overlay.

The gateway depends on node 1 for the test ingress path. If node 1 or the
gateway is down, client ingress can fail even if nodes 2 and 3 still have a
Raft majority.

Because the gateway has an allowed HTTP path only to node 1, the `edge` profile
also starts `rqlite-leader-init`. That helper asks the formed cluster to make
`rqlite1` leader. Without that step, a write sent to node 1 while another node is
leader may require an HTTP redirect to a node the gateway is not allowed to
reach over Docker networking.

## Run Static Checks

```bash
cd rqlite-db-tunnels
./scripts/verify.sh

set -a
. ../.env
set +a

docker compose config >/tmp/rqlite-db-tunnels.compose.yaml
```

The static check proves that the compose file includes native rqlite join flags,
Cloudflare node variables, `cloudflared access tcp`, and no host ports. It does
not prove that Cloudflare TCP Access is configured correctly.

## Persistence Check

The persistence client uses rqlite HTTP through the gateway, not direct DB-node
addresses. It requires a formed native rqlite cluster over the Cloudflare TCP
peer overlay. Run it twice without deleting `_volumes`; the second run should
show previous state:

```bash
cd rqlite-db-tunnels
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
cd rqlite-db-tunnels
set -a
. ../.env
set +a

docker compose --profile edge up --build -d

API="${CLOUDFLARE_URL_EXTERNAL%/}"
curl -sS "$API/health"
curl -sS "$API/status?pretty" | head
curl -sS -X POST "$API/db/execute" \
  -H 'content-type: application/json' \
  -d '["CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)","INSERT OR REPLACE INTO kv(key,value) VALUES(\"tutorial\",\"rqlite-tunnels\")"]'
curl -sS "$API/db/query?level=none&q=SELECT%20value%20FROM%20kv%20WHERE%20key%3D%27tutorial%27"

docker compose --profile edge down
```

If the cluster does not form, the rqlite status endpoint and container logs are
the first places to inspect.

## Verifying The No-Direct-TCP Constraint

- `docker compose config` should show each rqlite DB service on only its own
  node network.
- Remote peer aliases should belong to `nodeX-to-nodeY` proxy sidecars, not to
  remote rqlite containers.
- There should be no `ports:` mappings.
- The only client path from outside Docker should be the external Cloudflare
  tunnel.

## Failure Drill

After the cluster has formed, stop one rqlite node:

```bash
docker compose --profile edge stop rqlite3 cloudflared-node3 node1-to-node3 node2-to-node3
API="${CLOUDFLARE_URL_EXTERNAL%/}"
curl -sS "$API/status?pretty" | head
docker compose --profile edge start rqlite3 cloudflared-node3 node1-to-node3 node2-to-node3
```

A real 3-node rqlite cluster should tolerate one failed node. It cannot tolerate
two failed nodes for writes because Raft requires a majority.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Cloudflare returns WAF error `1010` / Access denied | The request was blocked by Cloudflare policy before it reached the container. For HTTP checks, allow the lab service client or adjust WAF, Browser Integrity, bot, or Access rules on the hostname. |
| rqlite never elects a leader | Confirm all three node URLs are TCP-capable Access routes, not HTTP routes. |
| `cloudflared access tcp` waits for login | Configure non-interactive service auth or private routing; browser auth inside containers is not suitable. |
| `cloudflared access tcp` logs `websocket: bad handshake` | The hostname is behaving like an ordinary HTTP tunnel route. Reconfigure the Cloudflare route as a TCP-capable Access/private-network route for this hostname. |
| External `/health` works but rqlite writes fail | The gateway is up, but Raft may not have formed. Check `docker compose --profile edge logs --tail=100 rqlite1 rqlite2 rqlite3`. |
| Cloudflare route returns 502 or 503 | Check that each tunnel token is used by only this lab, that the hostname is routed to that token, and that compose includes the `--url tcp://127.0.0.1:4002` origin. |
| Node 1 is down but nodes 2 and 3 are healthy | The cluster may still have majority, but this lab's gateway ingress depends on node 1. |

## Limitations

- This is a fragile last-resort topology for native Raft over Cloudflare TCP.
- It requires Cloudflare TCP Access or private routing, not ordinary HTTP
  tunnels.
- Long-lived database peer traffic can be sensitive to latency, reconnects, and
  Access policy changes.
- The gateway-to-node1 test ingress is a single ingress dependency.
- This lab is useful for proving feasibility and failure modes, not for claiming
  production readiness.
