# rqlite-db-tunnels

Use this lab for the last-resort native rqlite Raft-over-Cloudflare experiment.

```bash
cd rqlite-db-tunnels
./scripts/verify.sh
set -a
. ../.env
set +a
docker compose config >/tmp/rqlite-db-tunnels.compose.yaml
docker compose --profile edge up --build -d
```

Design details:

- Each rqlite DB container is isolated on its own node network.
- Peer names such as `rqlite2-peer` resolve to local `cloudflared access tcp` proxy sidecars.
- The node Cloudflare URLs must be TCP-capable Access applications, not ordinary HTTP routes.
- The external tunnel publishes the gateway for client ingress.
