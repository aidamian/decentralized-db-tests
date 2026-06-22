# ckroch-db-tunnels

Native CockroachDB tunnel experiment. This project is the last-resort design: CockroachDB still requires inter-node TCP, so every peer address is a local Cloudflare TCP proxy sidecar. No two CockroachDB containers share a Docker network.

Run static checks:

```bash
./scripts/verify.sh
docker compose config >/tmp/ckroch-db-tunnels.compose.yaml
```

Run the tunnel experiment:

```bash
set -a
. ../.env
set +a
docker compose --profile edge up --build -d
```

Cloudflare prerequisites:

- `CLOUDFLARE_TOKEN_EXTERNAL` routes to the gateway HTTP origin for client ingress.
- `CLOUDFLARE_TOKEN_1..3` route to each CockroachDB node's inter-node TCP origin on port `26357`.
- `CLOUDFLARE_URL_1..3` must be TCP-capable Cloudflare Access hostnames usable by `cloudflared access tcp`.
- Automated long-lived TCP Access needs service authentication or WARP/private routing. If those hostnames are ordinary HTTP tunnel routes, native Cockroach clustering will not form.

The gateway exposes a small HTTP key/value test API backed by the local Cockroach SQL endpoint on node 1. Native Cockroach quorum semantics require two of three nodes for writes.
