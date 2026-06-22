# ckroch-db-tunnels

Use this lab for the last-resort native CockroachDB inter-node-RPC-over-Cloudflare experiment.

```bash
cd ckroch-db-tunnels
./scripts/verify.sh
set -a
. ../.env
set +a
docker compose config >/tmp/ckroch-db-tunnels.compose.yaml
docker compose --profile edge up --build -d
```

Design details:

- Each CockroachDB node is isolated on its own node network.
- Peer names such as `ckroch2-peer` resolve to local `cloudflared access tcp` proxy sidecars.
- CockroachDB inter-node RPC uses port `26357` in this lab.
- `cockroach-init` initializes the cluster after nodes start.
- The node Cloudflare URLs must be TCP-capable and suitable for non-interactive long-lived access.
