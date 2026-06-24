# Architecture Decision

This repository contains six independent labs for decentralized database experiments where DB node containers must not have direct TCP access to other DB node containers.

## Core Rule

- No host port forwarding is used.
- A DB node container is attached only to its own node network.
- Base projects use NATS JetStream as the brokered operation log.
- Tunnel projects use Cloudflare Tunnel as the only permitted direct transport
  exception. In the custom tunnel lab that path is gateway-to-node HTTP; in the
  rqlite and CockroachDB tunnel labs it is native peer TCP through local
  Cloudflare proxy sidecars.
- Client ingress uses `CLOUDFLARE_TOKEN_EXTERNAL` and `CLOUDFLARE_URL_EXTERNAL`.

## Base Projects

The base projects are brokered logical replication labs:

- `custom-db-base`: custom event-store nodes receive deterministic events through local relay sidecars.
- `rqlite-db-base`: three isolated single-node rqlite instances receive the same logical write stream.
- `ckroch-db-base`: three isolated `cockroach start-single-node` stores receive the same logical write stream.

The rqlite and CockroachDB base projects are intentionally not native clusters. Native rqlite Raft and native CockroachDB require peer TCP reachability, which violates the base constraint.

## Tunnel Projects

The tunnel projects are last-resort tunnel experiments:

- `custom-db-tunnels`: a gateway reaches custom nodes through the node Cloudflare URLs.
- `rqlite-db-tunnels`: rqlite Raft peer names resolve to local `cloudflared access tcp` proxies.
- `ckroch-db-tunnels`: CockroachDB inter-node RPC peer names resolve to local `cloudflared access tcp` proxies.

Only one tunnel project should run at a time because the `.env` file supplies one external token and three node tokens shared by all tunnel labs.

## References

- Cloudflare Tunnel run parameters: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/
- Cloudflare arbitrary TCP with `cloudflared access tcp`: https://developers.cloudflare.com/cloudflare-one/access-controls/applications/non-http/cloudflared-authentication/arbitrary-tcp/
- rqlite clustering: https://rqlite.io/docs/clustering/automatic-clustering/
- rqlite configuration: https://rqlite.io/docs/guides/config/
- CockroachDB `cockroach start`: https://www.cockroachlabs.com/docs/stable/cockroach-start
- CockroachDB cluster setup troubleshooting: https://www.cockroachlabs.com/docs/stable/cluster-setup-troubleshooting
